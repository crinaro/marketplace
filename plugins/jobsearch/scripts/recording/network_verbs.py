"""network: the network-first verbs, each the candidate's own decision or fact: `raise-companies` (the one writer of
`raised_on`), `company-status`, `company-later`, `company-kind`, `chat`, `attended`, `intro-offered` and `via`,
each one locked, validated, rollback-verified write, refused on a profile not migrated to 0.86.0.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import os
import re
from recording import profile_paths as _paths
from recording.row_checks import (
    _RAISED_FIELD,
    _diagnostic_lines,
    dry_run_validate,
    new_problems,
    validate,
)
from recording.common import _Refused, _now, _profile_mod, _validator_module
from recording.store_files import (
    LockError,
    STORES,
    _load_or_empty,
    find,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


RAISE_COMPANIES_USAGE = "raise-companies --run <run id> [--on YYYY-MM-DD] [--check | --dry-run] [--already-locked]"


def cmd_raise_companies(args):
    """Exit 0 on a raise (or a no-op, or a dry run), 1 when a store cannot be read or the write was rolled back, 2 on usage or
    a bad setting, 3 when the profile is not ready for the network block (the pin's own text is printed)."""
    import journal as _journal
    import config_keys as _ck
    if args.rid or args.rest:
        print("usage: " + RAISE_COMPANIES_USAGE)
        return 2
    run = (args.run_id_arg or "").strip()
    if not run or re.search(r"\s", run):
        print("⛔ REFUSED — --run <run id> is required (no whitespace).\nusage: " + RAISE_COMPANIES_USAGE)
        return 2
    if args.on_date:
        try:
            on = datetime.date.fromisoformat(args.on_date)
        except ValueError:
            print("⛔ REFUSED — --on %r is not an ISO date (YYYY-MM-DD)." % args.on_date)
            return 2
    else:
        on = _now().date()
    import reachouts as _reachouts
    gate = _reachouts._gate(_paths.ROOT)
    if gate:
        print(gate)
        return 3
    try:
        setting = _ck.resolve_int(_profile_mod().load(), _ck.SEARCH_COMPANY_INTAKE_PER_RUN)
    except (ValueError, OSError) as e:
        print("⛔ REFUSED — %s; nothing written." % e)
        return 2
    check = bool(args.check or args.dry_run)
    if not check:
        if args.already_locked:
            if not lock_is_held():
                print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
                return 1
        else:
            try:
                take_lock("record.py raise-companies --run %s" % run, wait=args.wait)
            except LockError as e:
                print("  REFUSED — %s" % e)
                return 1
    try:
        import your_move as _ym
        try:
            recs = _journal.read(_paths.ROOT)
            if any(r.get("event") == "companies-raised" and r.get("run_id") == run for r in recs):
                print("raise-companies run=%s already raised (nothing written)" % run)
                return 0
            companies = load("companies")
            cands = _ym.company_candidates(_paths.ROOT, on.isoformat())
        except (OSError, ValueError, _journal.JournalError) as e:
            print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
            return 1
        unraised = [c for c in cands if not c["raised_on"]]
        raised = unraised[:setting]
        waiting = len(unraised) - len(raised)
        line = "raised %d companies to look into (%d waiting)" % (len(raised), waiting)
        if check:
            print("raise-companies --dry-run: would raise %s; nothing written\n%s"
                  % (", ".join(c["id"] for c in raised) or "nothing", line))
            return 0
        if raised:
            ids = {c["id"] for c in raised}
            for row in companies:
                if row.get("id") in ids:
                    row[_RAISED_FIELD] = on.isoformat()
            snap = snapshot("companies")
            pre_problems = validate()[3]
            save_atomic("companies", companies)
            rc, out, err, post_problems = validate()
            added = new_problems(pre_problems, post_problems)
            if rc != 0 and (added is None or added):
                ok = restore("companies", snap)
                print("⛔ the write left the store invalid and was %s."
                      % ("ROLLED BACK (byte-identical)" if ok else
                         "NOT VERIFIABLY ROLLED BACK -- restore companies.jsonl from git"))
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
                return 1
        try:
            _journal.record_companies_raised(_paths.ROOT, run, setting, [c["id"] for c in raised], waiting)
        except _journal.JournalError as e:
            print("⚠️ could not journal the `companies-raised` event (%s)" % e)
            print(line)
            return 1
        print(line)
        return 0
    finally:
        if not check and not args.already_locked:
            release_lock()


NETWORK_VERB_USAGE = {
    "company-status": "company-status <company_id> active-target|watching|passed [--motivation <1-5>] [--on YYYY-MM-DD] "
                      "[--dry-run] [--already-locked]",
    # jobsearch 0.88.0 (dev #915, design-jobsearch-0.88.0.md 6.3, 6.4, 7.3): the two writers of the Targets-to-review list's stored
    # fields, called by the dashboard's action blocks through `dashboard_actions.py` (never typed on the page).
    "company-later": "company-later <company_id> [--on YYYY-MM-DD] [--dry-run] [--already-locked]",
    "company-kind": "company-kind <company_id> employer|staffing|aggregator [--dry-run] [--already-locked]",
    "chat": "chat <person_id> --on YYYY-MM-DD [--time HH:MM] [--title \"<title>\"] [--opp <opp_id>] [--touch <touch_id>] "
            "[--dry-run] [--already-locked]",
    "attended": "attended <commitment_id> held|no-show [--notes <relative path>] [--on YYYY-MM-DD] [--dry-run] [--already-locked]",
    "intro-offered": "intro-offered <commitment_id> (--person <person_id> | --company <company_id>) [--on YYYY-MM-DD] "
                     "[--dry-run] [--already-locked]",
    "via": "via <opp_id|app_id> --person <person_id> [--chat <commitment_id>] [--dry-run] [--already-locked]",
}
NETWORK_PENDING_LINE = ("network-first upgrade pending: the jobsearch 0.86.0 migration has not run on this profile (run "
                        "`~/.claude/jobsearch/run migrate.py` and read what it says); nothing was written")
_CHAT_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


PLAN_PENDING_LINE = ("jobsearch 0.88.0 upgrade pending: the 0.88.0 migration has not run on this profile (run "
                     "`~/.claude/jobsearch/run migrate.py` and read what it says); nothing was written")


def _network_gate(minimum=(0, 86, 0)):
    """`None` when this profile may take a write of the release `minimum` (default 0.86.0), else the line to print: the pin's own
    refusal when a NEWER engine upgraded the profile, or the pending-migration line when no pin at or above `minimum` exists (an
    unmigrated profile has no pin, and a verb that wrote a newer field into it would be a field a pinned-ahead older engine
    could not have meant). The two 0.88.0 company verbs pass `(0, 88, 0)`: their fields (`later_on`, `kind`) are new in it."""
    import journal as _journal
    refusal = _journal.pin_refusal(_paths.ROOT)
    if refusal:
        return refusal
    pin = _journal.pin_scan(_paths.ROOT)
    if pin is None or tuple(int(x) for x in pin.split(".")) < minimum:
        return NETWORK_PENDING_LINE if minimum <= (0, 86, 0) else PLAN_PENDING_LINE
    return None


def _parse_on(text, flag="--on", default=None, not_after_today=True):
    """The ISO date `text` names (or `default` when it is None), as a `datetime.date`. Refuses a malformed date, and a future one
    unless `not_after_today` is False: every date these verbs write is a day that has happened."""
    if text is None:
        return default
    try:
        d = datetime.date.fromisoformat(text)
    except ValueError:
        raise _Refused("%s %r is not an ISO date (YYYY-MM-DD)." % (flag, text))
    if not_after_today and d > _now().date():
        raise _Refused("%s %s is after today: these verbs record what has already happened." % (flag, text))
    return d


def _live_person(people, pid, what="person"):
    """The people row `pid` names, refused when it resolves to nothing or was merged (the survivor is named: link THAT one)."""
    row = find(people, pid)
    if row is None:
        raise _Refused("%s %r resolves to no people record." % (what, pid))
    if row.get("status") == "merged":
        raise _Refused("%s %r was merged into %r; use the survivor: %r." % (what, pid, row.get("merged_into"), row.get("merged_into")))
    return row


def _merged_map(people):
    return {p.get("id"): p.get("merged_into") for p in people if p.get("merged_into")}


def _network_row_write(args, verb, store, edit, minimum=(0, 86, 0)):
    """The ONE write path of the five network-first verbs. `edit(rows)` mutates `rows` (the store's rows, a fresh read) in place and
    returns the lines to print; it raises `_Refused` BEFORE anything is written. Returns the exit code: 0 written (or nothing to
    change, or a dry run that predicts a clean write), 1 refused or rolled back, 2 usage, 3 the profile is not ready.

    The sequence is the one every row-writing verb here follows: gate, edit a shadow, `--dry-run` runs the real validator over the
    shadow and stops, then the lock, a re-read INSIDE it, the edit again on what is really there, a snapshot, the atomic write, the
    validator, and a byte-identical rollback when the write introduced a problem the store did not have before."""
    gate = _network_gate(minimum)
    if gate:
        print(gate)
        return 3
    try:
        rows = _load_or_empty(store)
        shadow =json.loads(json.dumps(rows))
        lines = edit(shadow)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 1
    if shadow == rows:
        for line in lines:
            print(line)
        print("%s: nothing to change." % verb)
        return 0
    if args.dry_run:
        pre_rc, _, _, pre_problems = validate()
        rc, out, err, problems = dry_run_validate(store, shadow)
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if added is None or added:
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back (nothing is written):")
                print("  " + "\n  ".join("- " + a for a in (added if added else _diagnostic_lines(rc, out, err))))
                return 1
        for line in lines:
            print(line)
        print("  --dry-run: nothing written.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py %s %s" % (verb, args.rid), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        try:
            rows = load(store) if os.path.exists(os.path.join(_paths.DATA, STORES[store])) else []
            lines = edit(rows)                     # re-read INSIDE the lock, and edit what is really there
        except _Refused as e:
            print("⛔ REFUSED — %s" % e)
            return 1
        snap = snapshot(store)
        pre_problems = validate()[3]
        save_atomic(store, rows)
        rc, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        if rc != 0 and (added is None or added):
            ok = restore(store, snap) if snap is not None else _remove_new_store(store)
            print("⛔ the write left the %s store invalid and was %s."
                  % (store, "ROLLED BACK (byte-identical)" if ok else
                     "NOT VERIFIABLY ROLLED BACK -- restore %s from git" % STORES[store]))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    for line in lines:
        print(line)
    return 0


def _remove_new_store(store):
    """Undo the creation of a store file that did not exist before the write (nothing to restore byte for byte). True when gone."""
    try:
        os.unlink(os.path.join(_paths.DATA, STORES[store]))
    except OSError:
        return False
    return True


def cmd_company_status(args):
    """`record.py company-status <company_id> active-target|watching|passed [--motivation <1-5>] [--on D]`: the candidate's answer to
    "look into this company?", and the ONE writer of a company's `status` and `status_on` (design-network-first.md 3.3, 4.1).

    `status`, `status_on` (`--on`, default today) and, for a target, `motivation` are written in ONE locked write. A target without
    `--motivation` is refused (its motivation is the candidate's own statement, LAMP's M, never a default), and `--motivation` beside
    `watching` or `passed` is refused (it describes a target). Answering removes the company from the look-into item and leaves its
    `raised_on` byte for byte. Exit 0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["company-status"]
    if not args.rid or len(args.rest) != 1:
        print(usage)
        return 2
    cid, status = args.rid, args.rest[0]
    _vd = _validator_module()
    try:
        if status not in _vd.COMPANY_STATUS:
            raise _Refused("%r is not a status: one of %s.\n%s" % (status, ", ".join(sorted(_vd.COMPANY_STATUS)), usage))
        mot = None
        if args.motivation_arg is not None:
            try:
                mot = int(args.motivation_arg)
            except ValueError:
                raise _Refused("--motivation %r is not a whole number %d-%d." % (args.motivation_arg, _vd.MOTIVATION_MIN,
                                                                                  _vd.MOTIVATION_MAX))
            if not _vd.MOTIVATION_MIN <= mot <= _vd.MOTIVATION_MAX:
                raise _Refused("--motivation %d is outside %d-%d (1 = would not mind, 5 = the company the candidate most wants to "
                               "work at)." % (mot, _vd.MOTIVATION_MIN, _vd.MOTIVATION_MAX))
        if status == "active-target" and mot is None:
            raise _Refused("targeting %s needs `--motivation <%d-%d>`: how much the candidate wants to work there is their own "
                           "statement, never a default." % (cid, _vd.MOTIVATION_MIN, _vd.MOTIVATION_MAX))
        if status != "active-target" and mot is not None:
            raise _Refused("--motivation describes a target; `%s` is not one. Run `company-status %s active-target --motivation "
                           "<%d-%d>` to target it." % (status, cid, _vd.MOTIVATION_MIN, _vd.MOTIVATION_MAX))
        on = _parse_on(args.on_date, default=_now().date())
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(rows):
        row = find(rows, cid)
        if row is None:
            raise _Refused("%r resolves to no companies record." % cid)
        was = row.get("status")
        row["status"] = status
        row["status_on"] = on.isoformat()
        if mot is not None:
            row["motivation"] = mot
        return ["company-status %s: %s -> %s (status_on %s%s)"
                % (cid, was, status, on.isoformat(), ", motivation %d" % mot if mot is not None else "")]
    return _network_row_write(args, "company-status", "companies", edit)


def cmd_company_later(args):
    """`record.py company-later <company_id> [--on D]` (dev #915; design-jobsearch-0.88.0.md 6.3, D4): the candidate's "ask me about
    this company next week" on the Targets-to-review list. It writes ONE field, `later_on` (the day, default today), and nothing
    else: "later" is a derived snooze (a `later_on` in the current ISO week hides the company from the list for the rest of the
    week), never a company status, so `status`, `status_on` and `motivation` are untouched and the company is still unanswered.
    Run again it moves the date. Refused on a company that does not exist and on a profile whose 0.88.0 migration has not run.
    Exit 0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["company-later"]
    if not args.rid or args.rest:
        print(usage)
        return 2
    cid = args.rid
    try:
        on = _parse_on(args.on_date, default=_now().date())
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(rows):
        row = find(rows, cid)
        if row is None:
            raise _Refused("%r resolves to no companies record." % cid)
        was = row.get("later_on")
        row["later_on"] = on.isoformat()
        return ["company-later %s: later_on %s -> %s" % (cid, was, on.isoformat())]
    return _network_row_write(args, "company-later", "companies", edit, minimum=(0, 88, 0))


def cmd_company_kind(args):
    """`record.py company-kind <company_id> employer|staffing|aggregator` (dev #915; design 6.4): the candidate's own word for what
    a company is, written as `kind` on the company. `your_move.company_kind()` reads it FIRST (`how: stated`), before a channel of
    that name or the staffing-name heuristic, so one click fixes a wrong exclusion in either direction ("this is a staffing firm
    or aggregator", "this is an employer") and nothing is lost or removed. It writes ONE field. Refused on an unknown kind, a company
    that does not exist and a profile whose 0.88.0 migration has not run. Exit 0 written; 1 refused; 2 usage; 3 not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["company-kind"]
    if not args.rid or len(args.rest) != 1:
        print(usage)
        return 2
    cid, kind = args.rid, args.rest[0]
    _vd = _validator_module()
    if kind not in _vd.COMPANY_KINDS:
        print("⛔ REFUSED — %r is not a company kind: one of %s.\n%s" % (kind, ", ".join(_vd.COMPANY_KINDS), usage))
        return 1

    def edit(rows):
        row = find(rows, cid)
        if row is None:
            raise _Refused("%r resolves to no companies record." % cid)
        was = row.get("kind")
        row["kind"] = kind
        return ["company-kind %s: kind %s -> %s" % (cid, was, kind)]
    return _network_row_write(args, "company-kind", "companies", edit, minimum=(0, 88, 0))


def cmd_chat(args):
    """`record.py chat <person_id> --on D [--time HH:MM] [--title T] [--opp <opp_id>] [--touch <touch_id>]`: record a chat with a
    person as a `kind: chat` commitment (design-network-first.md 5.2). It writes NO attendance: whether the chat happened is a later
    `record.py attended`, which only the candidate runs. `--touch` joins the chat to the `meeting-booked` touch it came from, and
    that touch must be to the same person. A second chat with the same person on the same date is refused (the same chat, said
    twice). Exit 0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["chat"]
    if not args.rid or args.rest:
        print(usage)
        return 2
    pid = args.rid
    try:
        on = _parse_on(args.on_date, not_after_today=False)
        if on is None:
            raise _Refused("--on <date> is required: the day of the chat.\n" + usage)
        if args.time_arg is not None and not _CHAT_TIME_RE.match(args.time_arg):
            raise _Refused("--time %r is not HH:MM (24 hours)." % args.time_arg)
        people = _load_or_empty("people")
        person = _live_person(people, pid)
        if args.opp_id and find(_load_or_empty("opportunities"), args.opp_id) is None:
            raise _Refused("--opp %r resolves to no opportunities record." % args.opp_id)
        if args.touch_arg:
            touch = find(_load_or_empty("touches"), args.touch_arg)
            if touch is None:
                raise _Refused("--touch %r resolves to no touches record." % args.touch_arg)
            if touch.get("outcome") != "meeting-booked":
                raise _Refused("--touch %r is not a `meeting-booked` touch (its outcome is %r): a chat is joined to the booking it "
                               "came from." % (args.touch_arg, touch.get("outcome")))
            vd, mm = _validator_module(), _merged_map(people)
            if vd.resolve_person(touch.get("person_id"), mm) != vd.resolve_person(pid, mm):
                raise _Refused("--touch %r is a touch to %r, not to %r." % (args.touch_arg, touch.get("person_id"), pid))
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(rows):
        for r in rows:
            if r.get("kind") == "chat" and r.get("person_id") == pid and r.get("date") == on.isoformat() \
                    and r.get("status") != "cancelled":
                raise _Refused("%s already records a chat with %s on %s; nothing to add." % (r.get("id"), pid, on.isoformat()))
        base = "chat-%s-%s" % (pid, on.isoformat())
        used = {r.get("id") for r in rows}
        cid, n = base, 2
        while cid in used:
            cid, n = "%s-%d" % (base, n), n + 1
        row = {"id": cid, "date": on.isoformat(), "title": args.title_text or ("Chat with %s" % person.get("name", pid)),
               "who": person.get("name", pid), "source": "record.py chat", "status": "scheduled",
               "person_id": pid, "kind": "chat"}
        if args.time_arg:
            row["time"] = args.time_arg
        if args.opp_id:
            row["opp_id"] = args.opp_id
        if args.touch_arg:
            row["touch_id"] = args.touch_arg
        rows.append(row)
        return ["chat: %s with %s on %s%s -- no attendance recorded (`record.py attended %s held|no-show` after it happens)"
                % (cid, pid, on.isoformat(), (" " + args.time_arg) if args.time_arg else "", cid)]
    return _network_row_write(args, "chat", "commitments", edit)


def cmd_attended(args):
    """`record.py attended <commitment_id> held|no-show [--notes <relative path>] [--on D]`: whether a meeting happened, as the
    candidate says it did (design-network-first.md 5.2). Writes `attendance` and `attendance_on` (`--on`, default today, never
    before the meeting's own date and never after today) and, when given, `notes_ref`; it changes no other field of the row. Refused
    on a cancelled meeting, on one whose date has not come (or is `unresolved`), and for a notes path that is absolute or climbs out
    of the profile. Exit 0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["attended"]
    if not args.rid or len(args.rest) != 1:
        print(usage)
        return 2
    cid, att = args.rid, args.rest[0]
    _vd = _validator_module()
    try:
        if att not in _vd.ATTENDANCE:
            raise _Refused("%r is not an attendance: one of %s.\n%s" % (att, ", ".join(sorted(_vd.ATTENDANCE)), usage))
        on = _parse_on(args.on_date, default=_now().date())
        if args.notes_arg is not None:
            why = _vd._relative_path_problem(args.notes_arg)
            if why:
                raise _Refused("--notes %s -- %r" % (why, args.notes_arg))
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(rows):
        row = find(rows, cid)
        if row is None:
            raise _Refused("%r resolves to no commitments record." % cid)
        if row.get("status") == "cancelled":
            raise _Refused("%s was cancelled: a cancelled meeting has no attendance." % cid)
        d = row.get("date")
        if not (_vd.is_date(d) and d <= _now().date().isoformat()):
            raise _Refused("%s is dated %r: a meeting that has not happened yet has no attendance." % (cid, d))
        if on.isoformat() < d:
            raise _Refused("--on %s is before the meeting's own date %s." % (on.isoformat(), d))
        if row.get("attendance") == att and row.get("attendance_on") == on.isoformat() \
                and (args.notes_arg is None or row.get("notes_ref") == args.notes_arg):
            return ["attended: %s is already recorded %s on %s" % (cid, att, on.isoformat())]
        was = row.get("attendance")
        row["attendance"], row["attendance_on"] = att, on.isoformat()
        if args.notes_arg is not None:
            row["notes_ref"] = args.notes_arg
        return ["attended: %s %s on %s%s%s" % (cid, att, on.isoformat(), (" (was %s)" % was) if was and was != att else "",
                                              (", notes %s" % args.notes_arg) if args.notes_arg else "")]
    return _network_row_write(args, "attended", "commitments", edit)


def cmd_intro_offered(args):
    """`record.py intro-offered <commitment_id> (--person <id> | --company <id>) [--on D]`: one introduction the other person offered
    in this chat (design-network-first.md 5.2, 5.4): an `intros_given` entry `{person_id | company_id, on}`. An introduction is
    ASKED for and landed in the ordinary touches, never assumed here (double opt-in). The same entry twice is not repeated. Exit 0
    written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["intro-offered"]
    if not args.rid or args.rest:
        print(usage)
        return 2
    cid = args.rid
    pid, coid = args.person_id_arg, args.company_name
    if bool(pid) == bool(coid):
        print("⛔ REFUSED — exactly one of --person <person_id> or --company <company_id> is required.\n" + usage)
        return 1
    try:
        on = _parse_on(args.on_date, default=_now().date())
        if pid:
            _live_person(_load_or_empty("people"), pid, "--person")
        elif find(_load_or_empty("companies"), coid) is None:
            raise _Refused("--company %r resolves to no companies record." % coid)
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    key, val = ("person_id", pid) if pid else ("company_id", coid)

    def edit(rows):
        row = find(rows, cid)
        if row is None:
            raise _Refused("%r resolves to no commitments record." % cid)
        given = row.get("intros_given")
        if given is not None and not isinstance(given, list):
            raise _Refused("%s carries an `intros_given` that is not a list; fix it with `set` first." % cid)
        given = list(given or [])
        if any(isinstance(e, dict) and e.get(key) == val for e in given):
            return ["intro-offered: %s already lists %s %s" % (cid, key, val)]
        given.append({key: val, "on": on.isoformat()})
        row["intros_given"] = given
        return ["intro-offered: %s -> %s %s (offered on %s); asking for the introduction is a touch, not this" % (cid, key, val,
                                                                                                                 on.isoformat())]
    return _network_row_write(args, "intro-offered", "commitments", edit)


def cmd_via(args):
    """`record.py via <opp_id|app_id> --person <id> [--chat <commitment_id>]`: where a role or an application CAME FROM
    (design-network-first.md 5.3), written as `via_person_id` and, with `--chat`, `via_commitment_id`. NEVER inferred from a recent
    chat: only this verb (or a hand `create`) sets it. The id names an opportunity or an application (both are tried; an id that is
    both is refused). The chat must be with that person after merge resolution; a chat naming a different person is refused. Exit
    0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + NETWORK_VERB_USAGE["via"]
    if not args.rid or args.rest or not args.person_id_arg:
        print(usage)
        return 2
    rid, pid, chat = args.rid, args.person_id_arg, args.chat_arg
    try:
        people = _load_or_empty("people")
        _live_person(people, pid, "--person")
        in_opp = find(_load_or_empty("opportunities"), rid) is not None
        in_app = find(_load_or_empty("applications"), rid) is not None
        if in_opp and in_app:
            raise _Refused("%r names both an opportunity and an application; give the application's own id or rename one." % rid)
        if not (in_opp or in_app):
            raise _Refused("%r resolves to no opportunities or applications record." % rid)
        if chat:
            cm = find(_load_or_empty("commitments"), chat)
            if cm is None:
                raise _Refused("--chat %r resolves to no commitments record." % chat)
            vd, mm = _validator_module(), _merged_map(people)
            if not cm.get("person_id"):
                raise _Refused("--chat %r names no person, so it cannot be the conversation with %r (record the person on the chat "
                               "first)." % (chat, pid))
            if vd.resolve_person(cm["person_id"], mm) != vd.resolve_person(pid, mm):
                raise _Refused("--chat %r is a conversation with %r, not with %r." % (chat, cm["person_id"], pid))
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    store = "opportunities" if in_opp else "applications"

    def edit(rows):
        row = find(rows, rid)
        if row is None:
            raise _Refused("%r resolves to no %s record." % (rid, store))
        row["via_person_id"] = pid
        if chat:
            row["via_commitment_id"] = chat
        return ["via: %s (%s) came from %s%s" % (rid, store, pid, (" via chat %s" % chat) if chat else "")]
    return _network_row_write(args, "via", store, edit)
