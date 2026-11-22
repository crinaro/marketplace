"""employment: where a person works NOW, stated with the day the engine learned it (jobsearch 0.91.0, design-build-reach.md 5.2).

The writers of `people.company_id`, `people.employment` and `people.formerly` (validate_data.check_employment holds the shape):

    record.py employment <person_id> current|unknown            as_of = today; on a row already current, confirmed_on only
    record.py employment <person_id> former [--left YYYY-MM-DD]  the employer of record moves to formerly, in one locked write
    record.py moved <person_id> --to <company_id> [--left D]     the same move, then the new employer, current, as_of today
    record.py create <id> '<json>' --file people                 `stamp_people_create`: the first standing, and `created`
    record.py merge-person <dup> --into <survivor> [--current <company_id|none>]   `merge_employment` (recording/persons.py)

NO VERB TAKES A DATE FOR `as_of`. Every date a derivation reads is the day the engine learned the fact, never one the candidate
picks: a back-dated `as_of` would hide a confirmation from the week it was made in, and `access.py` replays "the table as the
candidate knew it on D" from these dates (`reach.standing`). So `--on` is refused here, and `--left` is stored as `until`, which
is display only. Re-confirming a `current` moves `confirmed_on` and nothing else, so it is never replayed as a move.

Each verb is one locked, validated, rollback-verified write of the people store (`network_verbs._network_row_write`), refused on a
profile the 0.86.0 network-first migration has not reached. ⚠️ Not built here: the `employment` journal event the design names
(the journal's event vocabulary is outside this step); the dated fields are what a measure reads.

Capability module of record.py (an entry point over `recording/`). The two verbs are reached from the store-verb path's first step
(`mutation.preflight`), because record.py's own dispatch may not grow (segmentation ratchet)."""

from recording.common import _Refused, _now
from recording.network_verbs import _live_person, _network_row_write, _parse_on
from recording.store_files import _load_or_empty, find

EMPLOYMENT_OPS = ("employment", "moved")
EMPLOYMENT_USAGE = {
    "employment": "employment <person_id> current|unknown|former [--left YYYY-MM-DD] [--dry-run] [--already-locked]",
    "moved": "moved <person_id> --to <company_id> [--left YYYY-MM-DD] [--dry-run] [--already-locked]",
}
NO_DATE = ("%s takes no date for when it was learned: as_of is the day this runs. `--left YYYY-MM-DD` (when they left, display "
           "only) is the one date these verbs take.")


def _today():
    return _now().date().isoformat()


def stated(status, today):
    """A fresh standing the candidate stated today: `current` is dated today, `unknown` carries no date."""
    return {"status": status, "as_of": today if status == "current" else None, "confirmed_on": None, "source": "stated"}


def confirm_current(row, today):
    """`employment <id> current` on `row`: a row already `current` gets `confirmed_on` today and nothing else (as_of, source untouched);
    any other row gets a fresh stated `current`. Returns the line to print."""
    emp = row.get("employment")
    if isinstance(emp, dict) and emp.get("status") == "current":
        emp["confirmed_on"] = today
        return "re-confirmed current at %s (confirmed_on %s; as_of %s unchanged)" % (row["company_id"], today, emp.get("as_of"))
    row["employment"] = stated("current", today)
    return "current at %s (as_of %s)" % (row["company_id"], today)


def depart(row, today, left=None):
    """Move `row`'s employer of record into `formerly`: `as_of` today, `until` from `--left`, `counted_from` the `as_of` it carried while
    `current` there (None if it never was). An earlier entry for the same company is replaced (a returner who left again). Clears
    `company_id` and removes `employment`. Returns the company id that moved."""
    cid = row.get("company_id")
    emp = row.get("employment") if isinstance(row.get("employment"), dict) else {}
    entry = {"company_id": cid, "as_of": today, "until": left,
             "counted_from": emp.get("as_of") if emp.get("status") == "current" else None}
    row["formerly"] = [f for f in (row.get("formerly") or []) if f.get("company_id") != cid] + [entry]
    row["company_id"] = None
    row.pop("employment", None)
    return cid


def stamp_people_create(new_row, today):
    """`create <id> '<json>' --file people`: stamp `created` (today) and the first `employment`, in place. Returns the refusal text, or
    None. A payload may state `"employment": {"status": "current"|"unknown"}` and nothing more inside it (as_of, confirmed_on and
    source are the writer's); a row with a `company_id` MUST state it, `unknown` being a legal answer; `formerly` and a typed
    `created` are refused (a departure is `employment <id> former`, after the create)."""
    if new_row.get("created") is not None:
        return "`created` is stamped by record.py with the day the row is made; leave it out of the payload."
    if new_row.get("formerly") is not None:
        return ("`formerly` is written by `record.py employment <id> former` or `moved`, which date the departure; create the person "
                "with their employer of record, then run one of those.")
    emp = new_row.get("employment")
    if new_row.get("company_id") and emp is None:
        return ('a person with a company_id must say whether they work there now: add "employment": {"status": "current"} or '
                '{"status": "unknown"} (unknown is a legal answer; it is not counted until confirmed).')
    if emp is not None:
        if not new_row.get("company_id"):
            return "`employment` describes the employer of record: set company_id, or leave employment out."
        if not isinstance(emp, dict) or set(emp) != {"status"} or emp["status"] not in ("current", "unknown"):
            return ('employment in a create payload is {"status": "current"} or {"status": "unknown"}, nothing else: the date it '
                    'was learned is today, stamped here. A past employer is `employment <id> former` after the create.')
        new_row["employment"] = stated(emp["status"], today)
    new_row["created"] = today
    return None


def merge_employment(dup, survivor, current, today):
    """`merge-person <dup> --into <survivor> [--current <company_id|none>]`: what the SURVIVOR keeps. Returns `(apply, refusal)`: a
    function that edits the survivor row in place (None when nothing changes), or the refusal text.

    Two different employers of record need `--current` (one of the two ids, or `none`); the other goes to `formerly`, dated today, with
    its `counted_from`. One employer, or none, needs nothing and `--current` is refused (there is nothing to decide). The absorbed
    row's own `formerly` entries join the survivor's (the survivor's entry wins for a company both name), because a merged person
    replays with the survivor's fields alone."""
    a, b = survivor.get("company_id"), dup.get("company_id")
    if a and b and a != b:
        if current not in (a, b, "none"):
            return None, ("%s works at %r on file and %s at %r: say which is current with `--current %s|%s|none`; the other moves to "
                          "formerly." % (survivor.get("id"), a, dup.get("id"), b, a, b))
    elif current is not None:
        return None, "--current decides between two different employers of record; these two rows do not have two."
    extra = [f for f in (dup.get("formerly") or []) if isinstance(f, dict)]
    if not (a and b and a != b) and not extra:
        return None, None

    def apply(row):
        if a and b and a != b:
            if current == b:
                depart(row, today)
                row["formerly"] = [f for f in row["formerly"] if f.get("company_id") != b]
                row["company_id"] = b
                if isinstance(dup.get("employment"), dict):
                    row["employment"] = dict(dup["employment"])
            else:
                gone = dict(dup, formerly=None)
                depart(gone, today)
                row["formerly"] = [f for f in (row.get("formerly") or []) if f.get("company_id") != b] + gone["formerly"]
                if current == "none":
                    depart(row, today)
        have = {f.get("company_id") for f in (row.get("formerly") or [])} | {row.get("company_id")}
        joined = [dict(f) for f in extra if f.get("company_id") not in have]
        if joined:
            row["formerly"] = (row.get("formerly") or []) + joined
    return apply, None


def cmd_employment(args):
    """`record.py employment|moved ...` (see the module docstring). Exit 0 written (or nothing to change, or a dry run that predicts a
    clean write); 1 refused or rolled back; 2 usage; 3 the profile is not ready."""
    verb = args.op
    usage = "usage: " + EMPLOYMENT_USAGE[verb]
    if not args.rid or len(args.rest) != (1 if verb == "employment" else 0):
        print(usage)
        return 2
    pid = args.rid
    what = args.rest[0] if verb == "employment" else "moved"
    try:
        if args.on_date is not None:
            raise _Refused(NO_DATE % verb)
        if what not in ("current", "unknown", "former", "moved"):
            raise _Refused("%r is not a standing: current, unknown or former.\n%s" % (what, usage))
        if verb == "moved" and not args.to_token:
            raise _Refused("moved needs `--to <company_id>`: the employer they work at now.\n%s" % usage)
        if verb == "employment" and args.to_token:
            raise _Refused("--to belongs to `moved`.\n%s" % usage)
        if args.left_date is not None and what in ("current", "unknown"):
            raise _Refused("--left says when they left an employer: it goes with `former` or `moved`.")
        left = _parse_on(args.left_date, flag="--left")
        left = left.isoformat() if left else None
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    today = _today()

    def edit(rows):
        row = _live_person(rows, pid)
        if what in ("current", "unknown", "former") and not row.get("company_id"):
            raise _Refused("%s has no employer of record; `moved %s --to <company_id>` sets one." % (pid, pid))
        if what == "current":
            return ["employment %s: %s" % (pid, confirm_current(row, today))]
        if what == "unknown":
            was = (row.get("employment") or {}).get("status")
            row["employment"] = stated("unknown", today)
            return ["employment %s: unknown at %s (was %s); not counted until confirmed" % (pid, row["company_id"], was)]
        if what == "former":
            return ["employment %s: formerly at %s (learned %s%s)" % (pid, depart(row, today, left), today,
                                                                     ", left %s" % left if left else "")]
        to = args.to_token
        if find(_load_or_empty("companies"), to) is None:
            raise _Refused("--to %r resolves to no companies record." % to)
        if row.get("company_id") == to:
            raise _Refused("%s's employer of record is already %s; `employment %s current` re-confirms it." % (pid, to, pid))
        if left and not row.get("company_id"):
            raise _Refused("--left names when they left the employer of record, and %s has none." % pid)
        old = depart(row, today, left) if row.get("company_id") else None
        kept = [f for f in row.get("formerly") or [] if f.get("company_id") != to]     # a returner: the earlier spell goes
        if kept:
            row["formerly"] = kept
        else:
            row.pop("formerly", None)
        row["company_id"] = to
        row["employment"] = stated("current", today)
        return ["moved %s: %s -> %s, current (as_of %s)" % (pid, old or "no employer", to, today)]
    return _network_row_write(args, verb, "people", edit)
