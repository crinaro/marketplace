"""affiliations_verb: `record.py affiliations`, the ONLY writer of `user.json`'s `affiliations` (jobsearch 0.91.0,
design-build-reach.md 7.1; the field model and the strict parser are `reach/affiliations.py`).

    record.py affiliations '<json list>' [--dry-run] [--already-locked]   the candidate's list, in their order
    record.py affiliations --none [--dry-run] [--already-locked]          asked, none: stores []
    record.py affiliations                                                 the derived state: not-asked | none | listed

Absent means never asked and `[]` means asked, none, so `'[]'` is refused in favour of `--none`: "none" is said on purpose,
never by an empty paste. A payload is parsed (and each LinkedIn address normalized) BEFORE the lock, so a refusal writes
nothing. The write is one locked, validated, rollback-verified write of `user.json`: the run lock (or the caller's verified
hold under `--already-locked`), user.json re-read inside it, the whole-store validator before and after, and the file's own
bytes put back when the write added a problem or did not read back as written. Writing the same list again is a no-op.

Nothing here runs unattended and nothing infers an affiliation: the onboarding question and the attended run's once-asked
prompt (skills/onboarding, skills/daily-run 4a) carry the candidate's own answer to this verb. No migration writes the field
(owner O6).

Capability module of record.py (an entry point over `recording/`). Reached from the store-verb path's first step
(`mutation.preflight`), as the employment verbs are, because record.py's own dispatch may not grow (segmentation ratchet)."""

import json
import os
import _atomic
from reach import affiliations as _aff
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.store_files import LockError, lock_is_held, release_lock, take_lock

AFFILIATION_OPS = ("affiliations",)
USAGE = ("affiliations '<json list of {kind, name, linkedin_url?, career_services?}>' | affiliations --none | affiliations\n"
         "       [--dry-run] [--already-locked]   kind: school | bootcamp | employer | community")


def user_path():
    return os.path.join(_paths.ROOT, "user.json")


def read_user():
    """user.json as a dict, or raises OSError/ValueError. An unreadable user.json is never an empty one."""
    with open(user_path(), encoding="utf-8") as fh:
        user = json.load(fh)
    if not isinstance(user, dict):
        raise ValueError("user.json is not a JSON object")
    return user


def payload(args):
    """`(entries, None)` for the list this call writes, `(None, None)` for the read form, or `(None, refusal text)`."""
    text, none = args.rid, bool(getattr(args, "ats_none", False))
    if args.rest:
        return None, "affiliations takes one JSON argument; quote the whole list.\n  usage: " + USAGE
    if text is None and not none:
        return None, None
    if text is not None and none:
        return None, "give the list or --none, not both.\n  usage: " + USAGE
    if none:
        return [], None
    try:
        value = json.loads(text)
    except ValueError as e:
        return None, "the list is not readable JSON (%s).\n  usage: %s" % (e, USAGE)
    if value == []:
        return None, ("an empty list is `record.py affiliations --none` (asked, none), said on purpose; "
                      "nothing written.")
    try:
        return _aff.parse(value), None
    except _aff.AffiliationError as e:
        return None, str(e)


def show():
    """The read form: one `AFFILIATIONS <state>` line, then each entry. Exit 0, or 1 on an unreadable user.json or value."""
    try:
        kind, entries = _aff.state(read_user())
    except (OSError, ValueError) as e:
        print("⛔ AFFILIATIONS unreadable -- %s" % e)
        return 1
    print("AFFILIATIONS %s -- %s" % (kind, _aff.describe(kind, entries)))
    for i, e in enumerate(entries or ()):
        print("  %d. %s" % (i + 1, json.dumps(e, ensure_ascii=False)))
    return 0


def _said(new):
    return _aff.describe(_aff.NONE if not new else _aff.LISTED, new)


def _write(new, user, before):
    """Inside the lock, on `user` as re-read there (`before` its exact bytes): write, validate, verify; roll the bytes back on
    failure. Returns the exit code."""
    if "affiliations" in user and user["affiliations"] == new:
        print("affiliations: already %s; nothing to change." % _said(new))
        return 0
    pre = validate()[3]
    user["affiliations"] = new
    _atomic.write_json(user_path(), user)
    rc_v, out, err, post = validate()
    added = new_problems(pre, post)
    try:
        verified = _aff.state(read_user())[1] == new
    except (OSError, ValueError):
        verified = False
    if (rc_v != 0 and (added is None or added)) or not verified:
        try:
            with open(user_path(), "wb") as fh:
                fh.write(before)
            with open(user_path(), "rb") as fh:
                ok = fh.read() == before
        except OSError:
            ok = False
        print("⛔ the write left the profile invalid and was %s."
              % ("ROLLED BACK (byte-identical)" if ok else "NOT VERIFIABLY ROLLED BACK — restore user.json from git"))
        print("  " + "\n  ".join(added if added else (["user.json did not read back as written"] if not verified
                                                      else _diagnostic_lines(rc_v, out, err))))
        return 1
    print("affiliations: %s (user.json)." % _said(new))
    return 0


def cmd_affiliations(args):
    """`record.py affiliations ...`. Exit 0: done, a no-op or the read form. 2: refused, nothing written. 1: the write failed
    and was rolled back (or the read form could not read user.json)."""
    new, refusal = payload(args)
    if refusal:
        print("⛔ REFUSED — %s" % refusal)
        return 2
    if new is None:
        return show()
    if args.dry_run:
        try:
            read_user()
        except (OSError, ValueError) as e:
            print("⛔ REFUSED — user.json cannot be read (%s); a real write would write nothing." % e)
            return 2
        print("affiliations would be: %s" % _said(new))
        for i, e in enumerate(new):
            print("  %d. %s" % (i + 1, json.dumps(e, ensure_ascii=False)))
        print("  --dry-run: nothing written.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 2
    else:
        try:
            take_lock("record.py affiliations", wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 2
    try:
        try:                                              # re-read INSIDE the lock: never write over a copy read before it
            with open(user_path(), "rb") as fh:
                before = fh.read()
            with open(user_path(), encoding="utf-8") as fh:
                user = json.load(fh)
            if not isinstance(user, dict):
                raise ValueError("user.json is not a JSON object")
        except (OSError, ValueError) as e:
            print("⛔ REFUSED — user.json cannot be read (%s); nothing written." % e)
            return 2
        return _write(new, user, before)
    finally:
        if not args.already_locked:
            release_lock()
