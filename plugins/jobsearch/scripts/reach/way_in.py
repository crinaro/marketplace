"""way_in: how a company is reached on a date, derived from the rows (jobsearch 0.91.0, design-build-reach.md 6.1, 6.3, 6.6).

    path   `direct` if a current employee there is warm; else `via-intro` if an introduction toward it is open; else `none`

OPEN INTRODUCTIONS (design-network-first.md 10.1, design-connected-entities.md 12): an `intro-request` touch, sent, still awaiting on
the date, whose object is the company or a CURRENT employee there; or an `intros_given` entry on a non-cancelled chat naming the
company or a current employee there; in both cases not yet LANDED (a touch with `trigger_kind: introduction` whose `trigger_ref` is
`touch:<the request>` or `commitment:<the chat>`, dated on or before the date). **A side-door ask is never one** (owner O17): an
`intro-request` carrying `build_kind: side-door` asks a stranger whether a role is open and whom to write to. That is the
candidate's own action, not an introduction in progress, so it leaves the company `path none` and is counted as
`side_asks_open` instead (`reach/sidedoor.open_asks`). A measure must rise on a result.

Moved here from `access.py` (`_chat_dates`, `_landings`, `_person_company`, `_open_intros`, jobsearch 0.91.0 B4) so `reachouts.py`
and `brief.py` ask the same question `access.table` does, with two edits: dates read through the core `_dates` (the same function
`graph` re-exports), and a merge cycle is caught as the `ValueError` `graph.MergeCycleError` subclasses (this module imports no
entry point; `g` is a `graph.Graph`, passed in). Capability module of `access.py`. Python 3.9+, standard library only."""

from _dates import date_or_none
from reach import sidedoor as _sd
from reach import standing_rows as _rows


def chat_dates(c):
    """`(date, recorded_on)` of a non-cancelled `kind: chat` commitment with a readable date, else None."""
    if c.get("kind") != "chat" or c.get("status") == "cancelled":
        return None
    d = date_or_none(c.get("date"))
    if d is None:
        return None
    return d, (date_or_none(c.get("attendance_on")) or d)


def landings(g, as_of):
    """Every introduction that LANDED on or before `as_of`: `[(trigger_ref, person_survivor_row)]`."""
    out = []
    for t in g.stores["touches"]:
        if t.get("trigger_kind") != "introduction":
            continue
        d = date_or_none(t.get("date"))
        if d is None or d > as_of:
            continue
        out.append((t.get("trigger_ref"), person_row(g, t.get("person_id"))))
    return out


def person_row(g, person_id):
    """The living survivor row for `person_id`, or None (no id, no row, or a merge cycle)."""
    try:
        return g.resolve_person(person_id) if person_id else None
    except ValueError:                                     # graph.MergeCycleError
        return None


def open_intros(g, cid, as_of, landed):
    """How many introductions toward company `cid` are open as of `as_of` (the module docstring). `landed` is `landings(g, as_of)`."""
    n = 0
    for t in g.stores["touches"]:
        if t.get("touch_type") != "intro-request" or t.get("status") != "sent" or t.get("build_kind") == _sd.BUILD_KIND:
            continue                                       # 0.91.0: a side-door ask is an action, never a way in (O17)
        d = date_or_none(t.get("date"))
        if d is None or d > as_of:
            continue
        replied = date_or_none(t.get("responded_on"))
        if not (t.get("outcome") == "awaiting" or (replied is not None and replied > as_of)):
            continue
        obj = person_row(g, t.get("object_person_id"))      # toward a CURRENT employee at its date
        if t.get("object_company_id") != cid and not _rows.is_current(obj, cid, as_of):
            continue
        if any(ref == "touch:%s" % t.get("id") for ref, _p in landed):
            continue
        n += 1
    for c in g.stores["commitments"]:
        if chat_dates(c) is None:
            continue
        for e in c.get("intros_given") or []:
            if not isinstance(e, dict):
                continue
            on = date_or_none(e.get("on")) or date_or_none(c.get("date"))
            if on is None or on > as_of:
                continue
            who = person_row(g, e.get("person_id"))       # the commitments branch: the same current-at-its-date rule
            if e.get("company_id") != cid and not _rows.is_current(who, cid, as_of):
                continue
            ref = "commitment:%s" % c.get("id")
            done = False
            for lref, lperson in landed:
                if lref != ref or lperson is None:
                    continue
                if who is not None:
                    done = lperson.get("id") == who.get("id")
                else:
                    done = _rows.is_current(lperson, e.get("company_id"), as_of)
                if done:
                    break
            if not done:
                n += 1
    return n


def path_word(warm, intros):
    """The path from the two counts: `direct` when anyone current there is warm, else `via-intro` when an introduction is open."""
    return "direct" if warm else ("via-intro" if intros else "none")


def company_path(g, cid, as_of, warm_days, landed=None):
    """The path into company `cid` on `as_of` (a date): the rule `access.table` prints, for a caller that needs only the path
    (`reach/build.py`'s BUILD lines, `brief.py`'s BUILD step). Counts only CURRENT employees, as every "at the company" reader does."""
    landed = landings(g, as_of) if landed is None else landed
    warm = sum(1 for p in g.people_for_company(cid, as_of=as_of) if g.warmth(p.get("id"), as_of, warm_days=warm_days) == "warm")
    return path_word(warm, open_intros(g, cid, as_of, landed))
