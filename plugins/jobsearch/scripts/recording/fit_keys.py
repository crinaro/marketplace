"""fit_keys: the two optional keys of a `fit.requirements[]` row, `topic` and `claim` (design-presence-report.md §8.1),
as `record.py fit` checks them, and the two verbs that change them on rows already stored.

    record.py retopic <old> <new> [--dry-run] [--already-locked]
        rename a topic across every requirement row of every role, in one locked write
    record.py fit-key <opp_id> <index> [--topic <slug>] [--claim-file <f>] [--dry-run] [--already-locked]
        set the keys on one existing row (`index` is its 0-based place in `fit.requirements`)

A `topic` must be its own `presence.skill_slugs.slug()`. A `claim` is legal only on `aligned` or `partial`, and its
`claim_key()` must equal that of a bullet of `presence/claims.md` AT THE MOMENT OF THE WRITE: an unreadable union refuses
the claim, never passes it. `validate_data.py` checks the grammar only (validation/requirement_rules.py). A topic no
stored row used before prints `topic new: <slug>`, so drift is seen when it is made. A replaced fit carries nothing
forward, and the count of what it dropped is printed.

Each write is one locked, validated, rollback-verified write of the opportunities store (the `fit` verb's own sequence).

Capability module of record.py (an entry point over `recording/`). Reached from the store-verb path's first step
(`mutation.preflight`), as the affiliations verb is."""

import json

from presence.skill_slugs import topic_refusal
from presence.union_text import bullets_with_sections, claim_key, read_union
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.store_files import (
    LockError,
    find,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)

FIT_KEY_OPS = ("retopic", "fit-key")
CLAIM_VERDICTS = ("aligned", "partial")
RETOPIC_USAGE = "retopic <old topic> <new topic> [--dry-run] [--already-locked]"
FIT_KEY_USAGE = ("fit-key <opp_id> <index> [--topic <slug>] [--claim-file <file holding the union bullet>] "
                 "[--dry-run] [--already-locked]")


def union_keys(root=None):
    """The set of `claim_key()`s of every bullet of the claim union, or None when it cannot be read."""
    text = read_union(root or _paths.ROOT)
    if text is None:
        return None
    return {claim_key(b) for b, _section in bullets_with_sections(text)}


def requirement_refusal(q, keys_fn):
    """None when the row's `topic` and `claim` may be written, else the reason. `keys_fn()` gives `union_keys()`; it is
    called only when the row carries a claim."""
    topic = q.get("topic")
    if topic is not None:
        why = topic_refusal(topic)
        if why:
            return why
    claim = q.get("claim")
    if claim is None:
        return None
    if not (isinstance(claim, str) and claim.strip()):
        return "claim must be a non-empty string: the union bullet, verbatim"
    if q.get("verdict") not in CLAIM_VERDICTS:
        return "claim is legal only with verdict aligned or partial (verdict %r)" % q.get("verdict")
    keys = keys_fn()
    if keys is None:
        return "claim given, but presence/claims.md cannot be read, so it cannot be checked"
    if claim_key(claim) not in keys:
        return "claim matches no bullet of presence/claims.md: %r" % claim
    return None


def lines_refusal(reqs, keys_fn):
    """The first requirement refusal of a fit line, prefixed `requirements[<i>]`, or None."""
    for i, q in enumerate(reqs):
        why = requirement_refusal(q, keys_fn) if isinstance(q, dict) else None
        if why:
            return "requirements[%d]: %s" % (i, why)
    return None


def cached_keys():
    """A `keys_fn` that reads the union once, on first use."""
    memo = []

    def keys():
        if not memo:
            memo.append(union_keys())
        return memo[0]
    return keys


def stored_topics(opps):
    """Every `topic` any stored requirement row carries."""
    out = set()
    for o in opps:
        for q in _reqs(o):
            if isinstance(q.get("topic"), str):
                out.add(q["topic"])
    return out


def new_topic_notes(reqs, known):
    """`topic new: <slug>` for each topic of `reqs` not in `known`, which it then joins."""
    notes = []
    for q in reqs:
        t = q.get("topic") if isinstance(q, dict) else None
        if isinstance(t, str) and t not in known:
            known.add(t)
            notes.append("topic new: %s" % t)
    return notes


def replaced_note(old_fit):
    """The line a replaced fit prints when its rows carried keys the new fit does not inherit, else None."""
    reqs = old_fit.get("requirements") if isinstance(old_fit, dict) else None
    reqs = [q for q in (reqs or []) if isinstance(q, dict)]
    n = sum(1 for q in reqs if q.get("topic") is not None)
    m = sum(1 for q in reqs if q.get("claim") is not None)
    if not (n or m):
        return None
    return "replaced: %d topic and %d claim keys of the old fit were not carried" % (n, m)


def _reqs(o):
    fit = o.get("fit")
    reqs = fit.get("requirements") if isinstance(fit, dict) else None
    return [q for q in (reqs or []) if isinstance(q, dict)]


def retopic(opps, old, new):
    """Rename `old` to `new` on every row of `opps` in memory: `(rows changed, roles changed)`."""
    rows, roles = 0, set()
    for o in opps:
        for q in _reqs(o):
            if q.get("topic") == old:
                q["topic"] = new
                rows += 1
                roles.add(o.get("id"))
    return rows, len(roles)


def cmd_retopic(args):
    """`record.py retopic <old> <new>`: exit 0 written (or nothing to do under --dry-run), 1 refused, 2 usage."""
    if not args.rid or len(args.rest) != 1:
        print("usage: " + RETOPIC_USAGE)
        return 2
    old, new = args.rid, args.rest[0]
    why = topic_refusal(new)
    if why:
        print("⛔ REFUSED — the new %s; nothing written." % why)
        return 1
    if old == new:
        print("⛔ REFUSED — the old and new topic are the same (%r); nothing written." % old)
        return 1

    def apply(opps):
        rows, roles = retopic(opps, old, new)
        if not rows:
            return "no requirement row carries topic %r; nothing written." % old
        return None, "retopic: %s -> %s on %d row(s) in %d role(s)" % (old, new, rows, roles)
    return _locked_write(args, "record.py retopic", apply)


def _read_claim_file(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if not text or "\n" in text:
        raise ValueError("it must hold exactly one union bullet on one line")
    return text


def cmd_fit_key(args):
    """`record.py fit-key <opp_id> <index> [--topic <slug>] [--claim-file <f>]`: exit 0 written, 1 refused, 2 usage."""
    topic, claim_file = getattr(args, "topic_arg", None), getattr(args, "claim_file", None)
    if not args.rid or len(args.rest) != 1 or not args.rest[0].isdigit() or (topic is None and claim_file is None):
        print("usage: " + FIT_KEY_USAGE)
        return 2
    oid, index = args.rid, int(args.rest[0])
    keys = {}
    if topic is not None:
        keys["topic"] = topic
    if claim_file is not None:
        try:
            keys["claim"] = _read_claim_file(claim_file)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            print("⛔ REFUSED — --claim-file %s cannot be used (%s); nothing written." % (claim_file, e))
            return 1
    union = cached_keys()

    def apply(opps):
        row = find(opps, oid)
        if row is None:
            return "no opportunity with id %r." % oid
        reqs = _reqs(row)
        if index >= len(reqs):
            return "%s has %d requirement row(s); there is no index %d." % (oid, len(reqs), index)
        q = reqs[index]
        why = requirement_refusal(dict(q, **keys), union)
        if why:
            return "%s fit.requirements[%d]: %s; nothing written." % (oid, index, why)
        notes = new_topic_notes([keys], stored_topics(opps))
        q.update(keys)
        return None, "\n".join(["fit-key: %s fit.requirements[%d] set %s" % (oid, index, ", ".join(sorted(keys)))]
                               + ["  " + n for n in notes])
    return _locked_write(args, "record.py fit-key", apply)


def _attempt(apply, opps):
    """`(None, line)` when `apply` changed `opps`, else `(refusal, None)`."""
    out = apply(opps)
    if isinstance(out, str):
        return out, None
    return None, out[1]


def _locked_write(args, why, apply):
    """The fit verb's sequence for one in-memory change of the opportunities store: plan on a copy, then (unless
    --dry-run) take the lock, re-read and re-apply inside it, write, validate, and put the bytes back on a new problem."""
    try:
        opps = load("opportunities")
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — the opportunities store cannot be read (%s); nothing written." % e)
        return 1
    refusal, line = _attempt(apply, json.loads(json.dumps(opps)))
    if refusal:
        print("⛔ REFUSED — " + refusal)
        return 1
    if args.dry_run:
        print(line)
        print("  --dry-run: nothing written.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock(why, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        opps = load("opportunities")
        refusal, line = _attempt(apply, opps)
        if refusal:
            print("⛔ REFUSED — " + refusal)
            return 1
        snap = snapshot("opportunities")
        pre_problems = validate()[3]
        save_atomic("opportunities", opps)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok = restore("opportunities", snap)
            print("⛔ the write left the store invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok else
                     "NOT VERIFIABLY ROLLED BACK — restore opportunities.jsonl from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print(line)
    return 0
