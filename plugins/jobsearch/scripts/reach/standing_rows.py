"""standing_rows: who is at a company, by standing, for every "at the company" reader (jobsearch 0.91.0, design-build-reach.md 5.3).

ONE PLACE THE READERS ASK. `reach.standing.standing` answers for one person, one company, one date; this module applies it over a
list of people rows for the readers of 5.3's table (`access`, `warm_path`, `reachouts`, `strategy_view`, `your_move`,
`pipeline_index`), so each passes ITS OWN date and none re-implements the rule:

    current       counted at the company: a tier, alumni, a path, a candidate, "somebody known is there"
    former        never counted at the company. Listed as "formerly at <company>"; a tie is still a tie (`people.ties` says how
                  the candidate knows a person, never where the person works), so a former employee may appear as a contact,
                  never as a way in
    unconfirmed   (standing `unknown`) never counted either: listed, with the one verb that settles it (`CONFIRM_VERB`)

`reconfirm` (owner O12) is a SUBSET of `current`: still counted, listed once because the last statement is older than the caller's
`recheck_days`. Re-confirming moves `confirmed_on` only, so `moves` never reports it.

Every function takes people ROWS (merges already resolved by the caller, or skipped here when `status: merged`) and a date. It
reads no store and no config, and no clock except `employer_words` with no date. Capability module of `access.py`. Python 3.9+,
standard library only."""

import datetime

from reach.standing import RECHECK_DAYS, needs_reconfirm, standing

BUCKETS = ("current", "former", "unconfirmed")
CONFIRM_VERB = "record.py employment <person_id> current|former"
_BUCKET = {"current": "current", "former": "former", "unknown": "unconfirmed"}


def _living(people):
    return [p for p in people or () if isinstance(p, dict) and p.get("status") != "merged"]


def bucket_of(person, company_id, as_of):
    """`current` · `former` · `unconfirmed` for `person` at `company_id` on `as_of`, or None when the row links them nowhere."""
    if not isinstance(person, dict):
        return None
    return _BUCKET.get(standing(person, company_id, as_of))


def is_current(person, company_id, as_of):
    """True only when `person` (a row, or None) is a current employee of `company_id` on `as_of`."""
    return bucket_of(person, company_id, as_of) == "current"


def split(people, company_id, as_of, recheck_days=RECHECK_DAYS):
    """`{"current": [rows], "former": [rows], "unconfirmed": [rows], "reconfirm": [rows]}` over the living rows linked to
    `company_id` on `as_of`, each list in id order. `reconfirm` repeats the `current` rows that are due a re-confirmation."""
    out = {"current": [], "former": [], "unconfirmed": [], "reconfirm": []}
    for p in sorted(_living(people), key=lambda r: str(r.get("id"))):
        b = bucket_of(p, company_id, as_of)
        if b is None:
            continue
        out[b].append(p)
        if b == "current" and needs_reconfirm(p, as_of, recheck_days):
            out["reconfirm"].append(p)
    return out


def ids(by):
    """`split()`'s result with each row replaced by its id: the shape a derived row carries (`access.table`'s `standing`)."""
    return {k: [p.get("id") for p in v] for k, v in by.items()}


def moves(before, now):
    """`[{"what": "standing", "person_id", "from", "to"}]` for every person whose bucket differs between two `ids()` results (the
    replayed table at `since` and at `as_of`); a bucket is None when the person was linked nowhere. `reconfirm` is not a bucket:
    a re-confirmation is never a move."""
    def where(by):
        return {pid: b for b in BUCKETS for pid in (by or {}).get(b, ())}
    was, is_ = where(before), where(now)
    return [{"what": "standing", "person_id": pid, "from": was.get(pid), "to": is_.get(pid)}
            for pid in sorted(set(was) | set(is_), key=str) if was.get(pid) != is_.get(pid)]


def current_ids(people, as_of):
    """The ids of the living rows that are current at their own employer of record on `as_of`."""
    return {p.get("id") for p in _living(people) if is_current(p, p.get("company_id"), as_of)}


def unconfirmed_ids(people, company_id, as_of):
    """Sorted ids of the living rows whose standing at `company_id` on `as_of` is unknown."""
    return [p.get("id") for p in split(people, company_id, as_of)["unconfirmed"]]


def current_firm(person, firms, as_of):
    """The firm id when `person`'s employer of record is one of `firms` (the backers of a company) and they are current there on
    `as_of`, else None: the firm route, like the direct one, needs a current employee."""
    cid = (person or {}).get("company_id")
    return cid if cid in (firms or ()) and is_current(person, cid, as_of) else None


def confirm_hint(person_ids):
    """The words a card adds when people at the company are unconfirmed: "" for none."""
    if not person_ids:
        return ""
    return ("; %d known there %s unconfirmed (%s): confirm employment first with `%s`"
            % (len(person_ids), "is" if len(person_ids) == 1 else "are", ", ".join(person_ids), CONFIRM_VERB))


def confirm_lines(people, targets, as_of):
    """`[{"kind": "confirm-employment", "company_id", "company_name", "person_ids", "why"}]`, one per company in `targets` (a dict
    id -> companies row, sorted by id) with unconfirmed people on `as_of`: the plan's one confirm line per company (5.3)."""
    out = []
    for cid in sorted(targets or {}):
        pids = unconfirmed_ids(people, cid, as_of)
        if pids:
            name = (targets[cid] or {}).get("name") or cid
            out.append({"kind": "confirm-employment", "company_id": cid, "company_name": (targets[cid] or {}).get("name"),
                        "person_ids": pids, "why": "still at %s? %s; not counted as known there until you say "
                                                   "(`%s`)" % (name, ", ".join(pids), CONFIRM_VERB)})
    return out


def employer_words(person, names, as_of=None):
    """Where `person` works, in the words a lookup prints: `Globex`, `Globex (unconfirmed)`, `formerly at Globex` (every former
    employer, newest learned first, after the employer of record if there is one), or an em dash for no employer at all. `names`
    maps a company id to its name; an id it does not hold prints as the id. `as_of` None is today (this module's one clock read:
    a lookup answers for now, and has no date of its own to pass)."""
    as_of = as_of or datetime.date.today()

    def name(cid):
        return (names or {}).get(cid) or cid
    cid = (person or {}).get("company_id")
    parts = []
    if cid:
        parts.append(name(cid) if is_current(person, cid, as_of) else "%s (unconfirmed)" % name(cid))
    left = [f for f in (person or {}).get("formerly") or () if isinstance(f, dict) and f.get("company_id")
            and bucket_of(person, f["company_id"], as_of) == "former"]
    for f in sorted(left, key=lambda f: str(f.get("as_of")), reverse=True):
        parts.append("formerly at %s" % name(f["company_id"]))
    return "; ".join(parts) or "—"


def label(person, company_id, as_of, company_name):
    """The suffix a list of people at a company adds after a name: "" for current, " (unconfirmed)", " (formerly at <name>)"."""
    b = bucket_of(person, company_id, as_of)
    if b == "unconfirmed":
        return " (unconfirmed)"
    if b == "former":
        return " (formerly at %s)" % (company_name or company_id)
    return ""


def at_company(people, company_id, as_of, company_name=None, key=None):
    """`[(row, label)]` for every living row linked to `company_id` on `as_of`: current first, then unconfirmed, then former, each
    in `key` order (default: id). A list of PEOPLE, never a count: a caller that counts uses `split()["current"]`."""
    by = split(people, company_id, as_of)
    return [(p, label(p, company_id, as_of, company_name)) for b in ("current", "unconfirmed", "former")
            for p in (sorted(by[b], key=key) if key else by[b])]


NO_TIES = {"alumni": 0, "alumni_former": 0, "alumni_unconfirmed": 0}
_TIE_KEY = {"current": "alumni", "former": "alumni_former", "unconfirmed": "alumni_unconfirmed"}


def tie_counts(people, as_of):
    """`{company_id: {"alumni": n, "alumni_former": n, "alumni_unconfirmed": n}}` over the living rows with a stated tie: LAMP's
    Alumni by standing. Only a CURRENT employee is Alumni; the other two are the words beside it (`NO_TIES` for a company with
    none)."""
    out = {}
    for p in _living(people):
        if not p.get("ties"):
            continue
        cids = [p.get("company_id")] + [f.get("company_id") for f in p.get("formerly") or () if isinstance(f, dict)]
        for cid in dict.fromkeys(c for c in cids if c):
            b = bucket_of(p, cid, as_of)
            if b is not None:
                counts = out.setdefault(cid, dict(NO_TIES))
                counts[_TIE_KEY[b]] += 1
    return out
