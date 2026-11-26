"""withdraw_write: the write of `read-withdraw`, one role or many (jobsearch 0.94.0, dev 1063; docs/design-role-first.md 6.3, 11).

`write_withdrawals(specs, run=...)` is the ONE write path of a withdrawal and the form P7's migration imports: `specs` is a list of `(opp_id, at, why)`, and the call
makes ONE lock, ONE read of each store, ONE validation before and after, and ONE atomic save of the opportunities store over all of them, with the byte-identical
rollback every batch verb has. A spec that cannot be made (no such role, no such read, a stored `jd_read` the parser refuses) is REFUSED ON ITS OWN and changes nothing; the
others still land (the `fit` verb's shape). The transform of one role is `read_withdraw.withdraw_in_row`; this module adds only what a write needs.

`cmd_read_withdraw(args)` is `record.py read-withdraw <opp> --at <the read's at> --why "..." [--run <id>] [--dry-run] [--already-locked]`: the pin first (a profile
without the 0.94.0 pin refuses naming the migration and writes nothing: an older engine would refuse the stored shape), then one spec through `write_withdrawals`.

Capability module of `record.py` (through `recording/role_first.py`). Python 3.9+, standard library only."""

import json

import jd_read as _jd
from journaling.pins import pin_missing_line
from recording import profile_paths as _paths
from recording.common import _engine_version, _now, _profile_mod
from recording.read_withdraw import DEFAULT_RUN, Refused, WHAT, withdraw_in_row
from recording.reads import _stage_line, _store_screen
from recording.row_checks import _diagnostic_lines, _row_checks, dry_run_validate, new_problems, validate
from recording.store_files import (
    LockError, _load_or_empty, find, load, lock_is_held, release_lock, restore, save_atomic, snapshot, take_lock)

USAGE = "read-withdraw <opp_id> --at <the read's at: YYYY-MM-DDTHH:MM:SS> --why \"<what was wrong with the read>\" [--run <id>] [--dry-run] [--already-locked]"


def _apply(opps, specs, run, now):
    """Apply each spec to `opps` (rows, edited in place) and return one result per spec, `{id, at, ok, text, notes}`. A refused spec leaves its row as it was."""
    profile, engine, on = _profile_mod().load(), _engine_version(), now.date()
    applications, channels = _load_or_empty("applications"), _load_or_empty("channels")
    out = []
    for oid, at, why in specs:
        res = {"id": oid, "at": at, "ok": False, "text": "", "notes": []}
        out.append(res)
        row = find(opps, oid)
        if row is None:
            res["text"] = "⛔ REFUSED — no opportunity %r" % oid
            continue
        work = json.loads(json.dumps(row))
        try:
            res["notes"] = withdraw_in_row(
                work, at, why, run=run, now_iso=now.isoformat(), applications=applications,
                rescreen=lambda r: _store_screen(r, on, engine, profile=profile, all_opps=opps, applications=applications, channels=channels))
        except Refused as e:
            res["text"] = "⛔ REFUSED — %s: %s" % (oid, e)
            continue
        except (OSError, ValueError, KeyError) as e:               # the screen's own inputs (profile, stores) could not be read: NOT CHECKED, never a guess
            res["text"] = "⛔ REFUSED — %s: NOT CHECKED, the screen could not be re-run (%s); nothing was written for it" % (oid, e)
            continue
        row.clear()
        row.update(work)
        res["ok"] = True
        res["text"] = "%s: the read of %s is withdrawn" % (oid, at)
    return out


def _check_rows(before, opps, results):
    """The introduced-only rules for every changed row (with the `jd_read` writer token held: the withdrawal is one of its writers). A row that fails is refused
    and put back."""
    for res in results:
        if not res["ok"]:
            continue
        old, new = find(before, res["id"]), find(opps, res["id"])
        bad = _row_checks("read-withdraw", old, new, jd_read_ok=True)
        if bad:
            new.clear()
            new.update(json.loads(json.dumps(old)))
            res["ok"], res["text"] = False, "⛔ REFUSED — %s: %s" % (res["id"], "; ".join(bad))


def write_withdrawals(specs, run=DEFAULT_RUN, already_locked=False, wait=None, dry_run=False, now=None):
    """Withdraw every `(opp_id, at, why)` of `specs` in ONE locked, validated, rollback-verified write. Returns `(exit code, results)`: 0 when every spec landed, 1 when one
    was refused (the others landed) or the write was rolled back. `dry_run` applies in memory and validates on a shadow copy, writing nothing. The pin is NOT checked
    here: the verb checks it, and the migration is what writes it."""
    now = now or _now()
    if not already_locked and not dry_run:
        try:
            take_lock("record.py read-withdraw", **({} if wait is None else {"wait": wait}))
        except LockError as e:
            return 1, [{"id": None, "at": None, "ok": False, "text": "REFUSED — %s" % e, "notes": []}]
    elif already_locked and not dry_run and not lock_is_held():
        return 1, [{"id": None, "at": None, "ok": False, "text": "REFUSED — --already-locked, but NOBODY holds the run lock.", "notes": []}]
    try:
        opps = load("opportunities")
        before = json.loads(json.dumps(opps))
        results = _apply(opps, specs, run, now)
        _check_rows(before, opps, results)
        if any(r["ok"] for r in results):
            pre_problems = validate()[3]
            if dry_run:
                rc, out, err, post = dry_run_validate("opportunities", opps)
                added = new_problems(pre_problems, post) if rc != 0 else []
                if rc != 0 and (added is None or added):
                    return 1, results + [{"id": None, "at": None, "ok": False, "notes": [],
                                          "text": "⛔ REFUSED — the write would be refused by the validator: %s" % "; ".join(added or _diagnostic_lines(rc, out, err))}]
            else:
                snap = snapshot("opportunities")
                save_atomic("opportunities", opps)
                rc, out, err, post = validate()
                added = new_problems(pre_problems, post)
                if rc != 0 and (added is None or added):
                    ok = restore("opportunities", snap)
                    return 1, results + [{"id": None, "at": None, "ok": False, "notes": [],
                                          "text": "⛔ the write left the store invalid and was %s: %s" % (
                                              "ROLLED BACK (byte-identical)" if ok else "NOT VERIFIABLY ROLLED BACK -- restore opportunities.jsonl from git",
                                              "; ".join(added or _diagnostic_lines(rc, out, err)))}]
    finally:
        if not already_locked and not dry_run:
            release_lock()
    return (0 if all(r["ok"] for r in results) else 1), results


def cmd_read_withdraw(args):
    """`record.py read-withdraw <opp> --at <at> --why "..."`: see the module docstring. Exit 0 landed, 1 refused or rolled back, 2 on usage."""
    refusal = pin_missing_line(_paths.ROOT, WHAT)
    if refusal:
        print("⛔ REFUSED — %s" % refusal)
        return 1
    if not args.rid or args.rest or not args.read_at_arg or not (args.why or "").strip():
        print("⛔ REFUSED — usage: " + USAGE)
        return 2
    run = (args.run_id_arg or DEFAULT_RUN).strip()
    if not run or any(c.isspace() for c in run):
        print("⛔ REFUSED — --run is a run id without whitespace\nusage: " + USAGE)
        return 2
    code, results = write_withdrawals([(args.rid, args.read_at_arg.strip(), args.why)], run=run, already_locked=args.already_locked, wait=args.wait,
                                      dry_run=args.dry_run)
    for r in results:
        print(("  " if r["id"] is None else "") + r["text"])
        for n in r["notes"]:
            print("    · " + n)
    if args.dry_run:
        print("  --dry-run: nothing written.")
    elif code == 0:
        print("  " + _stage_line(args.rid))
    return code
