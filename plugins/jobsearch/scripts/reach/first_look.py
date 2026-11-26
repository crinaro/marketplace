"""first_look: does a role's CARD meet the owner's own criteria, judged before the role is read (jobsearch 0.94.0, step P2; dev 1062;
docs/design-role-first.md 3.1, RF1 to RF3).

A role at a company the owner has not chosen is released from the company question when this look says `match`, and stays held, with the
clause that held it, when it says `off`. The look is COMPUTED at read time against today's profile and never stored, so a changed criterion
takes effect at once. It judges with the owner's own rules and no others: `look` takes the three RESULTS of `profile._title_rule`,
`profile.screen_comp` and `geo_screen.screen`, so selection and the screen that follows the read cannot disagree about what a criterion is.

  title  (`_title_rule`)  fails on `NO-MATCH`, `OFF-MANDATE`, or its SENIORITY `BELOW-FLOOR`
  pay    (`screen_comp`)  fails only on its PAY `BELOW-FLOOR` (a range whose top is under the floor that applies). Undisclosed pay, pay not
                          captured, pay that cannot be compared, a commute not yet known and a pay the owner accepted never fail
  place  (`geo_screen`)   fails on `out` or `outside-radius` AND a STATED setting: `location.type` is remote, hybrid, onsite or relocation (`unresolved` is a contested setting, not a stated one), it was not
                          inferred (`setting_source`), and the card's place is not an echo of the owner's own anchor (`anchor_echo`)

The two `BELOW-FLOOR` words are told apart by the argument they arrive in, never by the word. The first failing clause, in the order title,
pay, place, is the `clause`; `state` is `match` (no clause fails and the title matched), `off`, or `no-criteria`: no target titles are
configured, a title key cannot be read, or the look itself could not be computed. `no-criteria` HOLDS, loudly ("criteria not checked"):
a criterion the engine could not read must never read as a role that passes.

Pure: no I/O, no clock, and it imports no module of this plugin. `look_at` builds the three calls' arguments the way `profile.screen_rules` does and takes the
functions it calls from its caller (a package imports no entry point, G5). Python 3.9+, standard library only."""

from typing import NamedTuple, Optional

MATCH, OFF, NO_CRITERIA = "match", "off", "no-criteria"
TITLE, PAY, PLACE, CRITERIA = "title", "pay", "place", "criteria"
CLAUSES = (TITLE, PAY, PLACE)
CAUSES = CLAUSES + (CRITERIA,)                  # what a held role's `Stage.cause` can say about the look
SETTINGS = ("remote", "hybrid", "onsite", "relocation", "unresolved")      # the `location.type` words
STATED = SETTINGS[:-1]                          # the ones a posting STATES: `unresolved` says two settings were claimed (docs/schema.md)
_TITLE_FAILS = ("NO-MATCH", "OFF-MANDATE", "BELOW-FLOOR")
_TITLE_UNREADABLE = ("NO-CONFIGURED-TITLES", "UNREADABLE-TITLE-KEYS")
_PAY_FAIL = "BELOW-FLOOR"
_PLACE_FAILS = ("out", "outside-radius")
NOT_CHECKED = "criteria not checked"


class Look(NamedTuple):
    """`state` is MATCH, OFF or NO_CRITERIA; `clause` the first failing clause (CLAUSES), CRITERIA for NO_CRITERIA, None for a match;
    `texts` the three rules' own sentences, `{"title", "pay", "place"}` (what a surface prints beside the clause)."""
    state: str
    clause: Optional[str]
    texts: dict


def setting_stated(opp):
    """True when the card STATES the role's setting: a `location.type` in STATED, not inferred by the capture
    script (`setting_source: inferred`) and not the echo of the owner's own anchor (`anchor_echo`). A place with no stated setting
    never fails the look (the role is read and the screen judges it from the posting)."""
    loc = opp.get("location") if isinstance(opp, dict) else None
    return (isinstance(loc, dict) and loc.get("type") in STATED and loc.get("setting_source") != "inferred"
            and not loc.get("anchor_echo"))


def _text(result, n=1):
    return str(result[n]) if isinstance(result, (tuple, list)) and len(result) > n else ""


def _token(result):
    return result[0] if isinstance(result, (tuple, list)) and result else None


def look(opp, title, comp, geo):
    """The `Look` of one role. `title` is `profile._title_rule(opp, profile)` `(token, text, review)`, `comp` is `profile.screen_comp`
    `(verdict, text)`, `geo` is `geo_screen.screen` `(verdict, line, detail)`; only the first two items of each are read."""
    texts = {TITLE: _text(title), PAY: _text(comp), PLACE: _text(geo)}
    ttok = _token(title)
    if ttok in _TITLE_UNREADABLE or (ttok != "MATCHES" and ttok not in _TITLE_FAILS):
        return Look(NO_CRITERIA, CRITERIA, texts)
    if ttok in _TITLE_FAILS:
        return Look(OFF, TITLE, texts)
    if _token(comp) == _PAY_FAIL:
        return Look(OFF, PAY, texts)
    if _token(geo) in _PLACE_FAILS and setting_stated(opp):
        return Look(OFF, PLACE, texts)
    return Look(MATCH, None, texts)


def unreadable(why):
    """The look of a role whose criteria could not be computed (`why` is the reason, kept in `texts`)."""
    return Look(NO_CRITERIA, CRITERIA, {TITLE: str(why), PAY: "", PLACE: ""})


def look_at(opp, profile, title_rule, screen_comp, geo_screen, listing_places):
    """`look` for one opportunity row under `profile`, with the arguments built as `profile.screen_rules` builds them: a requisition listed
    at several places is judged at its most favourable (`location.listed_at`, a transient key), and the stated work type goes to the geography
    rule as given. `title_rule`, `screen_comp` and `geo_screen` are the three functions named above and `listing_places` is
    `pipeline_index.listing_places`. A profile that is not a mapping, or a rule that cannot be computed (a value of the wrong type), is
    `no-criteria`: never a role that passes and never a crash."""
    if not isinstance(profile, dict):
        return unreadable("no readable profile")
    loc = opp.get("location") if isinstance(opp.get("location"), dict) else None
    row = opp
    if loc is not None:
        primary = (loc.get("primary") or "") if isinstance(loc.get("primary"), str) else ""
        extra = [p for p in listing_places(opp) if p != primary.strip()]
        if extra:
            row = dict(opp, location=dict(loc, listed_at=extra))
            loc = row["location"]
    loc = loc or {}
    try:
        ltype = loc.get("type")
        return look(row, title_rule(row, profile), screen_comp(row, profile),
                    geo_screen(loc.get("primary") or "", profile, work_type=ltype if ltype in SETTINGS else None, loc_obj=loc))
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        return unreadable("%s: %s" % (type(e).__name__, e))
