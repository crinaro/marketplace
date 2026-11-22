"""sidedoor: the side-door play's own facts, over rows (jobsearch 0.91.0, design-build-reach.md 6.3; owner O10, O17).

THE PLAY (`plays/side-door.json`). Nobody current is known inside a company with a live role being pursued: ask a recruiting, HR or
talent person who is NOT the role's lead (an involvement with `path_type: side-contact`) whether the role is open and who the right
person is (step `ask-side`, an `intro-request` carrying `build_kind: side-door`), then write to the person they named, naming them
(step `named-note`, a `first-touch` with `trigger_kind: introduction` and `object_person_id` = the side contact).

WHAT THIS MODULE ANSWERS, each from stored rows and a date, never from prose:

    side_contact_ids(involvements)      who on a role is a side contact (their involvement's `path_type`)
    asked_ids(touches, side, as_of)     the side contacts who were sent a touch on the role by the date (the class rule: a recipient
                                        holding a side-contact involvement, whatever the touch's `play_step`)
    named(people, company, asked, D)    the CURRENT people at the company the candidate recorded as introduced by an asked side
                                        contact: `ties: [{kind: introduced, via: "person:<side contact id>"}]`. The engine never
                                        asserts whom a contact knows (ADR-031 decision 5): only the candidate's own tie counts
    referrer_named(...)                 the play token `referrer-named` (arity 0): `named(...)` is not empty
    open_asks(touches, company, D)      the derived `side_asks_open`: sent `build_kind: side-door` asks toward the company still
                                        awaiting on the date. An ask to a stranger is an action, never a way in (O17), so
                                        `access` does not count it as an open introduction and the company stays `path none`
    state(opp, touches, invs, people, D)  the `side_door` field of the derived `reach` block: `{opp_id, step, waiting_on}` for an
                                        adopted side-door play that has not finished, else None

`state` walks the play's three steps in the order `plays.next_step` does and reads the same facts (`done:ask-side` is a sent touch
naming the step, or one with no step to a side contact; `replied:ask-side` is such a touch with `responded_on` by the date), so the
step it names is the step `plays.py` would run (`tests/reach/test_sidedoor.py` holds the two to each other on the play itself). Where
`plays.py` has nothing runnable, `state` says what it is waiting on (`replied:ask-side`, `referrer-named`), so a pending note is never
hidden by a path that opened another way.

Imports no entry point: rows come from the caller (`plays.Context`, `access.py`, `reachouts.py`, `brief.py`). Capability module of
`plays.py`. Python 3.9+, standard library only."""

from _dates import date_or_none, to_date
from reach.recipients import touch_class
from reach.standing import standing

PATTERN = "side-door"
SIDE_CONTACT = "side-contact"          # the involvement `path_type`, and the recipient class it maps to
FIND_STEP, ASK_STEP, NOTE_STEP = "find-side-contact", "ask-side", "named-note"
NOTE_TO = "decider"                    # the named note's `do.to` class (plays/side-door.json)
BUILD_KIND = "side-door"
VIA_PERSON = "person:"
INTRODUCED = "introduced"
NO_STEP = (None, "unresolved")
GOAL_STAGES = ("screening", "interviewing", "offer")      # the play's goal, `interview-scheduled` (plays._evaluate_body)


class _Invs:
    """The one attribute `recipients.touch_class` reads (`plays.Context.involvements_by_opp`), for one role's involvements."""

    def __init__(self, opp_id, involvements):
        self.involvements_by_opp = {opp_id: list(involvements or ())}


def via_person(tie):
    """The people id a tie's `via` names (`person:<id>`), or None for any other `via` (free text, absent)."""
    via = tie.get("via") if isinstance(tie, dict) else None
    if isinstance(via, str) and via.startswith(VIA_PERSON):
        return via[len(VIA_PERSON):].strip() or None
    return None


def side_contact_ids(involvements):
    """The person ids holding a `side-contact` involvement in `involvements` (one role's)."""
    return {i.get("person_id") for i in involvements or () if isinstance(i, dict) and i.get("path_type") == SIDE_CONTACT
            and i.get("person_id")}


def _sent_by(t, as_of):
    d = date_or_none(t.get("date"))
    return t.get("status") == "sent" and d is not None and d <= as_of


def asked_ids(touches, side_ids, as_of):
    """The side contacts in `side_ids` who were sent a touch in `touches` (one role's) on or before `as_of`."""
    day = to_date(as_of)
    return {t.get("person_id") for t in touches or () if _sent_by(t, day) and t.get("person_id") in side_ids}


def _ask_touches(touches, side_ids, day):
    """The sent touches that count for `done:ask-side`: the step named, or no step and a side contact as recipient."""
    return [t for t in touches or () if _sent_by(t, day)
            and (t.get("play_step") == ASK_STEP or (t.get("play_step") in NO_STEP and t.get("person_id") in side_ids))]


def named(people, company_id, asked, as_of):
    """`[(person_id, side_contact_id)]`: each living person CURRENT at `company_id` on `as_of` whose own `ties` say a side contact in
    `asked` introduced them (`kind: introduced`, `via: person:<id>`), in id order. A side contact never names themself."""
    out = []
    for p in sorted((p for p in people or () if isinstance(p, dict) and p.get("status") != "merged"), key=lambda r: str(r.get("id"))):
        if standing(p, company_id, as_of) != "current":
            continue
        for tie in p.get("ties") or ():
            x = via_person(tie)
            if isinstance(tie, dict) and tie.get("kind") == INTRODUCED and x in asked and x != p.get("id"):
                out.append((p.get("id"), x))
                break
    return out


def referrer_named(people, company_id, asked, as_of):
    """The play token `referrer-named`: a current person at the company carries an `introduced` tie via an asked side contact."""
    return bool(named(people, company_id, asked, as_of))


def open_asks(touches, company_id, as_of):
    """How many sent `build_kind: side-door` asks toward `company_id` are still awaiting on `as_of` (the rule `access._open_intros`
    applies to an introduction: `outcome: awaiting`, or a reply dated after the date). Every touch in `touches` is considered."""
    day, n = to_date(as_of), 0
    for t in touches or ():
        if t.get("build_kind") != BUILD_KIND or t.get("object_company_id") != company_id or not _sent_by(t, day):
            continue
        replied = date_or_none(t.get("responded_on"))
        if t.get("outcome") == "awaiting" or (replied is not None and replied > day):
            n += 1
    return n


def state(opp, touches, involvements, people, as_of):
    """`{opp_id, step, waiting_on}` for the side-door play governing `opp` (its own touches and involvements), or None once its last
    step is sent. `waiting_on` is None when `step` can run now, else the token it waits on. `named` (the people a side contact
    pointed to) and `referrer` ride along on the `named-note` step."""
    day = to_date(as_of)
    if opp.get("stage") in GOAL_STAGES:
        return None
    side = side_contact_ids(involvements)
    base = {"opp_id": opp.get("id"), "waiting_on": None}
    if not side:
        return dict(base, step=FIND_STEP)
    asks = _ask_touches(touches, side, day)
    if not asks:
        return dict(base, step=ASK_STEP)
    ctx = _Invs(opp.get("id"), involvements)
    if any(_sent_by(t, day) and (t.get("play_step") == NOTE_STEP or (t.get("play_step") in NO_STEP
                                                                      and touch_class(t, ctx) == NOTE_TO)) for t in touches or ()):
        return None
    replied = [t for t in asks if date_or_none(t.get("responded_on")) is not None and date_or_none(t["responded_on"]) <= day]
    if not replied:
        return dict(base, step=NOTE_STEP, waiting_on="replied:%s" % ASK_STEP)
    found = named(people, opp.get("company_id"), asked_ids(touches, side, day), day)
    if not found:
        return dict(base, step=NOTE_STEP, waiting_on="referrer-named", referrer=replied[0].get("person_id"),
                    replied_on=str(replied[0].get("responded_on"))[:10])
    return dict(base, step=NOTE_STEP, named=[y for y, _x in found], referrer=found[0][1])
