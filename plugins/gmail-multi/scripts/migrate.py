#!/usr/bin/env python3
"""Migrate the gmail-multi account registry to schema 2. Idempotent; safe to run every session.

⭐ WHY THIS EXISTS
------------------
Until 0.5.0 `~/.claude/gmail-multi/accounts.json` could carry an `include` list: files whose  # retired-terms: ok
mailbox addresses merged into the connector's account list on every call (jobsearch pointed one
at its profile). Two lists joined at read time drift apart silently, and the join meant the
connector read another plugin's private file. Registry SCHEMA 2 drops it:

    { "schema": 2, "accounts": ["you@example.com", ...] }

A change to what a user's own file means ships as a migration that runs itself, never as an
instruction (CLAUDE.md). This is that migration. It follows PRESERVE, THEN TRANSFORM, and it
queries its own success condition rather than assuming it:

    1. PRESERVE  copy the file byte-for-byte to `accounts.json.v1`, unless that copy exists.
    2. TRANSFORM read every include once; write `accounts` = the literal addresses, then the
                 include-derived ones, de-duplicated in first-seen order; drop `include`; keep
                 every other key; set `schema: 2`. Written through accounts.write_registry(),
                 the registry's one atomic writer.
    3. QUERY     re-read the file and check the success condition. Only then report done.

SUCCESS CONDITION (queried, never assumed): the registry is absent (nothing to migrate;
"unconfigured" stays loud where it is searched), or it reads `schema == 2` with no `include`.

PENDING, NEVER A FALSE DONE: an include that cannot be read means NOTHING IS WRITTEN and the
result is pending, naming the path. A skipped include would silently shrink coverage, and
partial coverage reads as "no mail" (the 2026-08-05 zero-mailboxes incident). The registry
stays exactly as it was, so the server keeps refusing loudly until the user fixes the include
or removes it with /gmail-multi:accounts.

THREE RUNNERS, ONE FUNCTION: SessionStart (`--hook`, hooks/hooks.json), the server's own
registry load (a surface with no SessionStart hook still migrates), and accounts.py before an
edit. Concurrent runs write the same bytes atomically, so they are idempotent.

Usage:
    python3 migrate.py --check     what is pending; writes nothing; exit 1 when pending
    python3 migrate.py             migrate now
    python3 migrate.py --hook      same, but silent when there is nothing to say; ALWAYS exit 0
                                   and says anything to STDERR (SessionStart stdout is context)

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _registry_path():
    import accounts
    return accounts._config_path()


def _addresses_from_obj(data):
    """Addresses out of one parsed JSON object, tolerant of the two mailbox shapes that exist
    in the wild (a list of {"address": ...} objects, or a dict keyed by address) and of a plain
    `accounts` list. Only used here, to consume an include once."""
    out = []
    if isinstance(data.get("accounts"), list):
        out.extend(str(a).strip() for a in data["accounts"] if str(a).strip())
    boxes = data.get("mailboxes")
    if isinstance(boxes, list):
        out.extend(m.get("address", "").strip() for m in boxes
                   if isinstance(m, dict) and str(m.get("address", "")).strip())
    elif isinstance(boxes, dict):
        out.extend(str(k).strip() for k in boxes.keys() if str(k).strip())
    return out


def _read(path):
    """(state, data, detail). state: absent | ok | needs_fold | newer | unreadable."""
    if not os.path.exists(path):
        return "absent", None, ""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return "unreadable", None, str(exc)
    if not isinstance(data, dict):
        return "unreadable", None, "top level is %s, not an object" % type(data).__name__
    schema = data.get("schema")
    if isinstance(schema, int) and not isinstance(schema, bool) and schema > 2:
        return "newer", data, "schema %s" % schema
    if schema == 2 and "include" not in data:  # retired-terms: ok
        return "ok", data, ""
    return "needs_fold", data, ""


def success(path):
    """The success condition, queried now: (bool, detail)."""
    state, _data, detail = _read(path)
    if state in ("absent", "ok"):
        return True, ""
    return False, "%s %s" % (state, detail)


def _pending(path, why, extra=""):
    return False, ("  ⏳ 0.5.0 PENDING — %s; registry %s unchanged.%s" % (why, path, extra))


def m_0_5_0_registry_v2(path=None, apply_it=True):
    """0.5.0 — account registry schema 2: fold every `include` into `accounts`, drop `include`.  # retired-terms: ok

    ⭐ PRESERVE, THEN TRANSFORM. `accounts.json.v1` is a byte-for-byte copy made before the first
    write (and never overwritten, so a second run cannot replace the original with a half-folded
    file). An unreadable include writes NOTHING and returns pending. The success condition is
    re-queried after the write; a write that did not produce it is reported pending, not done.

    SAFE: idempotent (a schema-2 registry with no `include` is a no-op, an absent one is nothing  # retired-terms: ok
    to migrate), and reversible by hand from the preserved copy.

    Returns (ok, message): ok False means PENDING with the reason in the message.
    """
    path = path or _registry_path()
    state, data, detail = _read(path)
    if state == "absent":
        return True, ""
    if state == "ok":
        return True, ""
    if state == "unreadable":
        return _pending(path, "%s cannot be read (%s)" % (path, detail),
                        " Fix or remove it.")
    if state == "newer":
        return _pending(path, "%s is %s, newer than this connector understands" % (path, detail),
                        " Update gmail-multi.")

    # needs_fold: collect everything BEFORE writing anything.
    literal = _addresses_from_obj(data)
    incs = data.get("include") or []  # retired-terms: ok
    if not isinstance(incs, list):
        return _pending(path, "`include` in %s is not a list" % path)
    folded, unreadable = [], None
    for inc in incs:
        inc_path = os.path.expanduser(str(inc))
        try:
            with open(inc_path, encoding="utf-8") as fh:
                inc_data = json.load(fh)
            if not isinstance(inc_data, dict):
                raise ValueError("top level is %s, not an object" % type(inc_data).__name__)
            folded.extend(_addresses_from_obj(inc_data))
        except (OSError, ValueError) as exc:
            unreadable = (inc_path, exc)
            break

    preserved = path + ".v1"
    if unreadable:
        inc_path, exc = unreadable
        return _pending(path, "include %s cannot be read (%s)" % (inc_path, exc),
                        " Nothing was folded. Fix the file, or drop the line from the registry.")

    seen, accounts = set(), []
    for addr in literal + folded:
        if addr not in seen:
            seen.add(addr)
            accounts.append(addr)
    n_folded = len([a for a in dict.fromkeys(folded) if a not in set(literal)])

    if not apply_it:
        return True, ("  would migrate %s to registry schema 2: %d account(s) (%d folded from "
                      "%d include(s)); a preserved copy goes to %s"
                      % (path, len(accounts), n_folded, len(incs), preserved))

    try:
        if not os.path.exists(preserved):
            shutil.copyfile(path, preserved)
    except OSError as exc:
        return _pending(path, "could not keep a preserved copy at %s (%s)" % (preserved, exc))

    new = dict((k, v) for k, v in data.items() if k not in ("include", "mailboxes"))  # retired-terms: ok
    new["schema"] = 2
    new["accounts"] = accounts
    try:
        import accounts as _accounts_mod
        _accounts_mod.write_registry(new, path)
    except OSError as exc:
        return _pending(path, "could not write %s (%s)" % (path, exc))

    ok, why = success(path)
    if not ok:
        return _pending(path, "the write did not produce registry schema 2 (%s)" % why)
    return True, ("  registry v2: %d account(s) (%d folded from %d include(s)); preserved copy "
                  "at %s" % (len(accounts), n_folded, len(incs), preserved))


MIGRATIONS = (("0.5.0", m_0_5_0_registry_v2),)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    ap.add_argument("--hook", action="store_true",
                    help="SessionStart mode: silent when nothing to say, always exit 0")
    args = ap.parse_args(argv)

    try:
        path = _registry_path()
        results = []
        for key, fn in MIGRATIONS:
            results.append((key, fn(path, apply_it=not args.check)))
    except Exception as exc:  # FAILS OPEN in a hook: housekeeping must never block a session
        if args.hook:
            sys.stderr.write("gmail-multi migrate.py could not run (%s: %s); the server "
                             "will migrate on its first call.\n" % (type(exc).__name__, exc))
            return 0
        raise

    pending = False
    for _key, (ok, msg) in results:
        if not ok or (args.check and msg):
            pending = True
        if not msg:
            continue
        if args.hook:
            sys.stderr.write(msg.strip() + "\n")
        else:
            print(msg)
    if args.hook:
        return 0
    if not pending and not any(msg for _k, (_ok, msg) in results):
        print("gmail-multi registry: nothing to migrate.")
    return 1 if pending else 0


if __name__ == "__main__":
    sys.exit(main())
