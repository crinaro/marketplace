#!/usr/bin/env python3
"""
Load `profile.json` and make its screening rules EXECUTABLE.

WHY THIS EXISTS
---------------
Created 2026-08-02, when the candidate asked to segment the process from the user data.

The tiered comp floor lived only as ~400 words of prose in `CLAUDE.md`. Prose gets
re-interpreted by a fresh model every run, and this particular prose has already
produced a real, costly error: on **2026-07-22 a re-scoring pass failed <an employer> against
the relocation bar** — but <an employer> is **25 minutes from the candidate's house**.
The pass had read `location.type == "onsite"` as "must relocate."

`onsite` in the data does NOT mean "move." It means the seat is in an office. Whether
that costs the candidate anything depends entirely on WHERE the office is, and there is a whole
separate, LOWER local-onsite tier for offices inside their commute radius. Getting this backwards flips a passing role into a failing one.

    screen_comp() encodes that distinction so it cannot drift again.

Usage:
    python3 scripts/profile.py                      # print the loaded profile summary
    python3 scripts/profile.py --screen <opp_id>    # screen one opportunity
    python3 scripts/profile.py --screen-all         # screen the whole live pipeline
    ~/.claude/jobsearch/run profile.py --minimal-screen <opp_id>   # the rules every run applies

    from profile import load, screen_comp, effective_setting

⭐ THE MINIMAL SCREEN RUNS UNDER EVERY POSTURE (dev #692 / public #140, owner decision of
2026-10-08). `--minimal-screen` is the scripted, zero-token screening a captured role gets in-run
whatever the posture says: the comp floor (`screen_comp`, unchanged), the duplicate/passed check
(`pipeline_index.find_excluded_match`, unchanged), the geography verdict (`geo_screen.screen`,
unchanged) and an ADVISORY title rule. It never reads `posture`: a posture limits how often the
search runs, not how much of what a run found is processed, so a role captured under `economy`
or `minimal` still gets screened. Only the rules that already remove a role remove it
(`remove:comp`, `remove:geo`, `remove:passed`); the title rule is advisory and only ever says
`review:title`. jobsearch 0.67.0 (dev #713-#716 / public #142-#145) adds, all in this file and
all still without a removal beyond the three above: the age line and the retained-search flag
(`review:age`), the NOT-CAPTURED and PAY-UNCOMPARABLE comp verdicts (`review:comp`; a role whose
pay nobody recorded is no longer the same quiet KEEP as one whose listing showed none), commute
bands (`resolve_floor`; a profile with no bands is screened exactly as before) and the likely-pass
signal matcher (`match_signals`, a lean and never a removal). `screen_rules` computes the screen
as data and `minimal_screen` prints it. There is still no separate mandate RULE LINE (owner, 2026-10-09: a line about a rule
that does not exist is noise on every role for every installer). jobsearch 0.69.0 (dev #722 /
public #156) adds, inside the one title line and still without a removal: `screen.title_floor`
(`BELOW-FLOOR`, whose lean follows the comp verdict, owner decision R1) and the title-field
`screen.likely_pass_signals` (`OFF-MANDATE`, the mandate). With neither configured the screen
prints exactly what 0.68.0 printed. jobsearch 0.73.0 (dev #739 / public #161, dev #740 / public #160)
adds to the comp rule alone, still without a new removal: `BELOW-FLOOR-ACCEPTED` (a BELOW-FLOOR role
whose current decision is pursue + comp-acceptable is KEPT; `comp_accepted`), the engagement routing
(`engagement`: a fractional, interim, advisory or contract role is measured against
`compensation.non_employee`, never the annual tiers; `BELOW-ENGAGEMENT-FLOOR` is a review) and a
`PAY-UNCOMPARABLE` for a `comp` in a unit or basis the annual BASE floor cannot be set against.
`comp_keys` / `screen_is_comp_stale` report a stored comp verdict computed without those inputs.

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_or_fixture as _profile_or_fixture
# dev #729 / public #157 (jobsearch 0.70.0): `places.py` is the distance half of the commute answer
# (place text -> coordinates -> miles, from the shipped table); `commute_outcome` below decides.
import places as _places

# ⭐ FIXTURE FALLBACK, LIKE EVERY OTHER GATE — and NOT a try/except that returns 0.
#
# `validate_data.py` began importing this module when `owner_token()` replaced a hardcoded name
# (issue #35), so a resolver that only ever finds a REAL profile took the data gate down in CI:
# `FileNotFoundError: .../user.json`, on a runner that deliberately has no profile.
#
# ⚠️ The obvious repair — catch the error and exit 0 when there is no profile — is the exact
# defect three gates were fixed for in this same branch: a check that reports success having
# read nothing. `profile_or_fixture()` is the answer the rest of the engine already uses. It
# resolves the real profile where one exists and the SYNTHESIZED fixture otherwise, so CI runs
# the real code against real-shaped data instead of skipping it.
ROOT = _profile_or_fixture()
USER_PATH = os.path.join(ROOT, "user.json")      # LAYER 1 — who the person is
CONFIG_PATH = os.path.join(ROOT, "config.json")  # LAYER 2 — how the search behaves

# Verdicts
CLEARS = "CLEARS"
BELOW = "BELOW-FLOOR"
UNDISCLOSED = "UNDISCLOSED"
NEEDS_COMMUTE = "NEEDS-COMMUTE-CHECK"
# Added 2026-08-11 (issue #4). A posting that declares two settings at once (tagged both
# hybrid and remote) has `location.type: "unresolved"` — and the resolver DECLINES to pick,
# because the pick selects which comp floor applies. Same family as NEEDS-COMMUTE-CHECK:
# an answer exists, it just has to come from the employer instead of an inference.
UNRESOLVED = "UNRESOLVED-SETTING"
# jobsearch 0.67.0 (dev #715 / public #143; design-sourcing-screen.md §5.1) -- two more verdicts.
# NOT-CAPTURED: nothing was ever recorded about this role's pay (no `listed_pay`, no `comp.max`),
# so "the listing showed no pay" and "nobody looked" are no longer the same quiet KEEP. It is a
# `review:comp` -- re-read the listing before surfacing -- and never a removal. PAY-UNCOMPARABLE:
# pay WAS recorded but cannot honestly be set against a floor (a non-annual interval, a currency
# other than the profile's, no profile currency set, or a board's own estimate below the floor).
# Also `review:comp`; no conversion is ever attempted, because a guessed conversion that removes a
# role is the defect class this verdict exists to prevent.
NOT_CAPTURED = "NOT-CAPTURED"
PAY_UNCOMPARABLE = "PAY-UNCOMPARABLE"
# jobsearch 0.73.0 (design-comp-and-company-data.md) -- two more verdicts, both NEVER a removal.
# BELOW-FLOOR-ACCEPTED (dev #739 / public #161): the role WOULD be BELOW-FLOOR, and the candidate's
# CURRENT decision is `pursue` with `reason_kind: comp-acceptable` (`comp_accepted`). The detail keeps
# the posting's own figures and floor; the verdict KEEPS the role (title lean: pursue).
# BELOW-ENGAGEMENT-FLOOR (dev #740 / public #160): a non-employee engagement (fractional, interim,
# advisory, contract) whose pay, in its own unit and the profile's currency, is below the same-unit
# floor in `compensation.non_employee.floors`. A review: non-employee pay is priced per scope, so a
# rate under the floor is a negotiating position, not a disqualifier.
BELOW_ACCEPTED = "BELOW-FLOOR-ACCEPTED"
BELOW_ENGAGEMENT = "BELOW-ENGAGEMENT-FLOOR"
# The two sentences a BELOW-FLOOR / BELOW-FLOOR-ACCEPTED detail ends with (after the figures, which
# are byte-identical in both). REMOVE_SENTENCE names the one decision shape that counts (A4).
REMOVE_SENTENCE = (
    "Profile says REMOVE unless you accept this pay: record.py decide %s pursue --why-kind "
    "comp-acceptable --why \"<why>\". Only that shape counts; a later decide with another "
    "--why-kind, or a verdict other than pursue, withdraws it.")
ACCEPTED_SENTENCE = (
    "ACCEPTED below the floor by your decision of %s (pursue, comp-acceptable: %s) -- KEEP, not "
    "removed; the figures are the posting's, unchanged.")
# dev #740 (E1), the 0.70.0 INFERRED_NOTE's twin: every screen line computed on a title inference says so.
ENGAGEMENT_INFERRED_NOTE = (
    " (engagement inferred from the title: %s; no engagement_type is recorded -- set it with "
    "`record.py set %s engagement_type <value>` to state it)")

# R2 -- the pay-slot grammar's interval abbreviations (`<min>-<max>/<yr|mo|day|hr>/<CUR>`) and the
# stored `interval` each one means. Only `year` is ever compared with a floor.
PAY_INTERVAL_ABBR = {"yr": "year", "mo": "month", "day": "day", "hr": "hour"}

# public #84 — the statuses `--screen-all` actually screens. `backlog` was missing from this
# tuple: newly sourced roles accumulate there and the screen never looked at them at all, with
# no skipped-count or warning anywhere in the output — the same "coverage, not silence" trap
# `check_engine_purity.py` prints `scanned N of M` against. `backlog` is live, screenable data
# (validate_data.TERMINAL_OPP_STATUSES excludes it for exactly this reason — a role that has not
# yet been decided still needs its comp checked), so it belongs here now. `passed`/`expired`
# stay OUT on purpose: a terminal role has already left the funnel and screening it again would
# print a verdict for a decision that is not live any more — the coverage line below is what
# says so, by name and count, instead of by silence.
SCREEN_ALL_STATUSES = ("active-pursuit", "needs-resolution", "in-motion", "backlog")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def user():
    """LAYER 1 — user data: who this person is."""
    return _read(USER_PATH)


def config():
    """LAYER 2 — configuration: how the search should behave."""
    return _read(CONFIG_PATH)


def load(path=None):
    """Both layers merged, for callers that just want 'the profile'.

    Kept so the engine has ONE obvious entry point. The layers stay separate ON DISK
    (that is the whole point); this is a read-time convenience, not a third file.
    """
    if path:
        return _read(path)
    merged = dict(config())
    merged.update(user())
    return merged


def mailboxes():
    """Addresses to search. THE source — never hardcode a mailbox in a script."""
    return [m["address"] for m in user()["mailboxes"]]


def owner_token():
    """The literal value `next_action_owner` uses for 'the candidate must act'.

    This candidate's own `preferred_reference`, lowercased — never a hardcoded name.
    `next_action_owner` ∈ {owner_token(), "me"}: "me" means the engine/assistant acts next,
    the candidate's own token means the human does. A previous version of this schema spelled
    the first value out as a literal name, one specific candidate's, hardcoded across
    validate_data.py, coordinator.py and generate_dashboard.py — correct for exactly one
    installation and silently wrong for anyone else's profile. Read it from user.json instead,
    the same way every other per-candidate fact in this engine is read rather than typed twice.
    """
    ident = user()["identity"]
    ref = ident.get("preferred_reference") or ident.get("display_name") or ident["full_name"]
    return ref.strip().lower()


def currency_symbol():
    """The symbol comp figures render with. `config.json.compensation.currency_symbol`,
    default "$" when unset — additive, so no existing profile needs a migration.

    The engine never converts between currencies: every figure in a profile is taken to be in
    that profile's own currency. This fixes only the LABEL, which used to be a hardcoded "$"
    for every installation — a profile in another currency got the right number under a wrong
    unit, which is worse than an error because nothing looked broken."""
    try:
        return config().get("compensation", {}).get("currency_symbol") or "$"
    except (OSError, ValueError):
        return "$"


def _render(template_lines):
    """Render a config TEMPLATE against user data — the two layers meeting.

    This is the concrete demonstration that configuration and user data are separate:
    config.json holds the SHAPE of a signature, user.json holds the phone number, and
    neither file contains the other's content.
    """
    u = user()["identity"]
    fields = {
        "full_name": u["full_name"],
        "phone": u["phone"],
        "city": u["city"],
        "primary_email": u["primary_email"],
        "linkedin": u["linkedin"],
        "linkedin_display": u["linkedin"].replace("https://", "").rstrip("/"),
    }
    return [line.format(**fields) for line in template_lines]


def comms():
    """LAYER 2 — how outreach is sent. The single source of truth for every constraint."""
    return config()["communications"]


def medium_constraints(medium):
    """Constraints for one medium, e.g. {'max_chars': 300, 'target_chars': [200, 260]}.

    Read this instead of retyping a limit. The 300-character connection-note cap lived in
    prose in four separate places before 2026-08-02, and the <=120-word cap was hardcoded
    inside an agent definition where nothing could check it.
    """
    return comms()["constraints_by_medium"].get(medium, {})


def email_signature():
    return _render(config()["writing"]["email_signature_template"])


def cover_letter_header():
    return _render(config()["writing"]["cover_letter_header_template"])


def tiers(profile):
    return {t["setting"]: t for t in profile["compensation"]["tiers"]}


def effective_setting(location, profile, commute_ok=None, table=None):
    """Map an opportunity's `location` object to a COMP TIER name.

    This is the function that exists because of the <an employer> error. The mapping is NOT
    a straight passthrough of `location.type`:

      remote                      -> "remote"
      hybrid                      -> "hybrid"
      relocation                  -> "relocation"
      onsite + inside the radius  -> "local-onsite"   (NO move: The candidate's own discount)
      onsite + outside the radius -> "relocation"     (a real move)
      onsite + unknown location   -> None             (ASK; never assume relocation)
      unresolved                  -> None             (the POSTING is contested — ask the
                                                       employer which setting governs;
                                                       location.declared holds its verbatim
                                                       wording. Never pick a tier.)

    `commute_ok`: pass True/False if you already know. Otherwise it is read from
    `commute_outcome()` against the profile's geography anchors, and an unrecognized place returns
    None rather than guessing — the whole point is to stop silent guessing.

    jobsearch 0.70.0 (dev #729 / public #157): the "onsite + outside the radius" arm is REACHABLE.
    It was documented from 0.4 and unreachable until `within_commute` could answer False, which it
    does only when a place is PROVEN beyond every anchor (`commute_outcome`, state `outside`).
    `table` is a place table to use instead of the shipped one (tests inject a synthesized one).
    """
    if not isinstance(location, dict):
        return None
    ltype = location.get("type")
    if ltype in ("remote", "hybrid", "relocation"):
        return ltype
    if ltype == "unresolved":
        return None      # contested by the posting itself — screen_comp() surfaces the question
    if ltype != "onsite":
        return None

    if commute_ok is None:
        commute_ok = within_commute(location, profile, table)
    if commute_ok is None:
        return None
    return "local-onsite" if commute_ok else "relocation"


def _entry_name(entry):
    """The place name of one `commute_anchors[].includes[]` entry: a string (the shape every
    profile carries) or a `{place, minutes}` object (0.67.0, design §3.8). None for anything else
    -- skipped by the matcher, never crashed on."""
    if isinstance(entry, dict):
        entry = entry.get("place")
    return entry if isinstance(entry, str) else None


def _commute_anchors(profile):
    """The `geography.commute_anchors[]` OBJECTS of a loaded profile. A non-object entry is skipped,
    never crashed on: a malformed anchor is a data problem for `validate_data.py` or a migration."""
    geo = profile.get("geography") if isinstance(profile, dict) else None
    anchors = geo.get("commute_anchors") if isinstance(geo, dict) else None
    return [a for a in anchors if isinstance(a, dict)] if isinstance(anchors, list) else []


def _match_commute(location, profile):
    """`(anchor, matched_entry)` for the first commute anchor whose `place` or any `includes[]`
    name appears in the location text, else `(None, None)`. THE one TEXT match: `commute_outcome`
    runs it first (state `inside`), so the comp rule, the band resolver and the geography rule
    cannot disagree about which anchor a role is in."""
    hay = " ".join(str(location.get(k) or "") for k in ("primary", "note")).lower()
    if not hay.strip():
        return None, None
    for anchor in _commute_anchors(profile):
        inc = anchor.get("includes")
        entries = [anchor.get("place")] + (list(inc) if isinstance(inc, list) else [])
        for e in entries:
            n = _entry_name(e)
            if n is None:
                continue
            # match on the distinctive part ("<the commute anchor>", "<a nearby metro>", "<a nearby metro>")
            token = n.split(",")[0].strip().lower()
            if token and token in hay:
                return anchor, e
    return None, None


# dev #729 / public #157 -- the states `commute_outcome` answers, MOST favourable first. A role
# listed at several places takes the most favourable one (design §5.6); `outside` is last because a
# role is outside only when EVERY listing is.
COMMUTE_STATES = ("inside", "inside-radius", "near", "unresolvable", "outside")
_STATE_RANK = {s: i for i, s in enumerate(COMMUTE_STATES)}
_HOLD_RANK = 3.5        # a held answer sorts between `near` and `unresolvable`: it says "not checked"


def _place_text(city_norm, region):
    return "%s, %s" % (city_norm.title(), region)


def _outcome(state, **kw):
    out = {"state": state, "anchor": None, "entry": None, "miles": None, "place": None,
           "via": None, "hold": None, "detail": None, "bound": None}
    out.update(kw)
    return out


def _unlocated_note(unlocated):
    if not unlocated:
        return ""
    return ("; anchor %s could not be located (give it lat and lon, or a place in the table)"
            % ", ".join(repr(a.get("place")) for a in unlocated))


def _place_outcome(label, coord, anchors, tbl):
    """The outcome of ONE parsed place with known coordinates against the anchors (design §3.1,
    §3.3, R7). `outside` is a PROOF: every anchor located and bounded, and every distance beyond
    its bound. An anchor that is unlocated or unbounded can never be proved far from, so it makes
    the answer `near`, never `outside`."""
    import config_keys as _ck
    located, unlocated = [], []
    for a in anchors:
        ac = _places.anchor_coords(a, tbl)
        if ac is None:
            unlocated.append(a)
        else:
            located.append((a, _places.haversine_miles(coord, ac)))
    if not located:
        return _outcome("unresolvable", place=label, via="table",
                        detail="no commute anchor has coordinates, so the distance from %s "
                               "cannot be measured%s" % (label, _unlocated_note(unlocated)))
    located.sort(key=lambda t: t[1])
    nearest, miles = located[0]
    for a, d in located:
        r = a.get("radius_miles")
        if r is not None and d <= r:
            return _outcome("inside-radius", anchor=a, entry=a.get("place"), miles=d, place=label,
                            via="table", bound=float(r),
                            detail="%s is ~%d mi from %s, within its radius_miles %s"
                                   % (label, round(d), a.get("place"), r))
    bounds = [_ck.outer_bound_miles(a)[0] for a, _d in located]
    provable = not unlocated and all(b is not None for b in bounds)
    if provable and all(d > b for (a, d), b in zip(located, bounds)):
        nearest_bound = bounds[0]
        return _outcome("outside", anchor=nearest, miles=miles, place=label, via="table",
                        bound=nearest_bound,
                        detail="%s is ~%d mi from %s (beyond %d mi)"
                               % (label, round(miles), nearest.get("place"), round(nearest_bound)))
    why = _unlocated_note(unlocated)
    if not why and any(b is None for b in bounds):
        why = "; an anchor declares no radius_miles, max_commute_minutes or bands, so no distance is far"
    return _outcome("near", anchor=nearest, miles=miles, place=label, via="table",
                    detail="%s is ~%d mi from %s: record location.commute_minutes%s"
                           % (label, round(miles), nearest.get("place"), why))


def _listing_outcome(loc, profile, anchors, table):
    """`commute_outcome` for ONE listing (a `location` object, or just `{"primary": text}`)."""
    anchor, entry = _match_commute(loc, profile)
    text = loc.get("primary")
    if anchor is not None:
        return _outcome("inside", anchor=anchor, entry=entry, place=text, via="text")
    parsed = _places.parse_place(text)
    if parsed is None:
        detail = (("%r is not a place the table knows" % text)
                  if isinstance(text, str) and text.strip() else "no place is recorded for this role")
        return _outcome("unresolvable", place=text, detail=detail)
    import config_keys as _ck
    bad = ["anchor %r: %s" % (a.get("place"), "; ".join(p)) for a in anchors
           for p in [_ck.validate_anchor_geo(a)] if p]
    if bad:
        return _outcome("held", place=text, hold="config",
                        detail="a commute anchor's distance keys cannot be read -- %s" % " | ".join(bad))
    tbl, problem = _places.resolve_table(table)
    if tbl is None:
        return _outcome("held", place=text, hold="place-table",
                        detail="PLACE TABLE MISSING (%s): distance not checked (%s)"
                               % (_places.table_path(), problem))
    results = []
    for city, region in parsed:
        label = _place_text(city, region)
        coord = _places.coords(city, region, tbl)
        if coord is None:
            results.append(_outcome("unresolvable", place=label, via="table",
                                    detail="%s is not a place the table knows" % label))
        elif not anchors:
            results.append(_outcome("unresolvable", place=label, via="table",
                                    detail="the profile declares no commute anchor to measure "
                                           "%s against" % label))
        else:
            results.append(_place_outcome(label, coord, anchors, tbl))
    return _best(results)


def _best(results):
    """The MOST favourable of several outcomes (design §5.6): `inside` over `inside-radius` over
    `near` over a held answer over `unresolvable` over `outside`; among equals, the nearer place."""
    def key(o):
        rank = _HOLD_RANK if o["state"] == "held" else _STATE_RANK[o["state"]]
        return (rank, o["miles"] if o["miles"] is not None else 0.0)
    return min(results, key=key)


def commute_outcome(location, profile, table=None, also=()):
    """The ONE answer to "how does this role's place relate to the commute?" (dev #729 / public #157,
    design-location-screen.md §3.1, R1, R4, R7). Returns `{state, anchor, entry, miles, place, via,
    hold, detail, bound}`, where `state` is:

      inside         a commute anchor's `place` or `includes[]` name appears in the location text
                     (`via: "text"`, as `within_commute` always did). `anchor` and `entry` are set.
      inside-radius  the place parses, the table locates it, and it is within the `radius_miles` of
                     an anchor that CONFIGURES one. `anchor` is set.
      outside        the place parses and is located, and for EVERY anchor, the anchor is located
                     AND bounded (`config_keys.outer_bound_miles`) AND the distance exceeds the
                     bound. A PROOF, never a guess: no road beats the great circle and no commute
                     averages 75 mph. R7: one anchor that cannot be located or bounded makes the
                     answer `near`, never `outside`.
      near           parsed and located, but neither inside nor provably outside. `miles` is the
                     distance to the nearest located anchor; the role needs a commute estimate.
      unresolvable   the text is not a place the table knows, or no anchor has coordinates.
      held           the answer could not be computed: `hold` is `"place-table"` (the shipped table
                     is missing, unreadable or empty -- NEVER folded into `unresolvable`, which
                     would claim a role is somewhere unknown when nobody looked) or `"config"` (an
                     anchor's radius_miles / lat / lon is unreadable: loud, never read as absent).

    `also` is extra place texts the SAME role is listed at (a sibling listing of one requisition,
    dev #728), as is `location["listed_at"]`; the most favourable listing wins, so a role is
    `outside` only when every listing is. `place` names the listing that decided it.
    `table` is a place table to use instead of the shipped one (`places.make_table`).

    `within_commute`, `effective_setting`, `resolve_floor` and `geo_screen` all read this function,
    so the comp rule and the geography rule cannot disagree about a role."""
    anchors = _commute_anchors(profile)
    listings = [location if isinstance(location, dict) else {}]
    # `listed_at` is the transient key `screen_rules` adds for a role listed at several places
    # (dev #728 / public #158): the same list as `also`, carried inside the location it travels with.
    extra = list(also) + list(listings[0].get("listed_at") or [])
    listings += [{"primary": t} for t in extra if isinstance(t, str) and t.strip()]
    return _best([_listing_outcome(loc, profile, anchors, table) for loc in listings])


def nearer_listing(previous, new, profile, table=None):
    """`(nearer, place, state)` -- is a NEW listing of a role strictly more favourable than the places
    it was already listed at (dev #728 / public #158, R8)? `previous` and `new` are lists of place
    texts. `nearer` is True only when the new listings' best commute state is `inside`,
    `inside-radius` or `near` while the previous ones' best is `outside`, `unresolvable` or held: a
    listing the candidate could actually take, of a role they passed on because the only place they
    knew was too far. `place` and `state` name the deciding new listing. Anything else is False: the
    new listing is linked to the existing row as a plain sibling."""
    prev = [t for t in previous if isinstance(t, str) and t.strip()]
    cur = [t for t in new if isinstance(t, str) and t.strip()]
    if not cur:
        return False, None, None
    before = commute_outcome({"primary": prev[0] if prev else ""}, profile, table, also=prev[1:])
    after = commute_outcome({"primary": cur[0]}, profile, table, also=cur[1:])
    good = ("inside", "inside-radius", "near")
    was_far = before["state"] in ("outside", "unresolvable", "held")
    return (after["state"] in good and was_far), after["place"], after["state"]


def within_commute(location, profile, table=None):
    """True / False / None(unknown), read from `commute_outcome`.

    True when the role is `inside` an anchor by name or `inside-radius`. **False only when the
    role is PROVEN outside every anchor** (dev #729 / public #157: until 0.70.0 this never returned
    False, so "onsite + outside the radius" was documented and unreachable). None for everything
    else -- `near`, `unresolvable`, `held` -- because an unknown commute is a question, never
    "relocation by default"."""
    state = commute_outcome(location, profile, table)["state"]
    if state in ("inside", "inside-radius"):
        return True
    if state == "outside":
        return False
    return None


def _commute_minutes(location, entry):
    """The commute minutes a role carries, or None (unknown). In order (design §5.4 step 2):
    `location.commute_minutes.minutes`, else the `minutes` of the `includes` OBJECT entry whose
    place matched. Only a positive int counts; anything else (a string, 0, a bool) is unknown --
    never read as a number it is not."""
    cm = location.get("commute_minutes")
    if isinstance(cm, dict):
        m = cm.get("minutes")
        if isinstance(m, int) and not isinstance(m, bool) and m > 0:
            return m
    if isinstance(entry, dict):
        m = entry.get("minutes")
        if isinstance(m, int) and not isinstance(m, bool) and m > 0:
            return m
    return None


def resolve_floor(location, profile, commute_ok=None, table=None):
    """Which floor a location is screened against: `{setting, floor, band, hold, detail, commute,
    anchor}`.

    jobsearch 0.67.0 (dev #714 / public #144; design §5.4). `setting` is `effective_setting()`'s
    answer, UNCHANGED, and `floor` is None -- the caller reads the tier's own floor -- in every case
    but one: the matched commute anchor DECLARES `bands` (`[{max_minutes, floor}]`, ascending), the
    role is onsite or hybrid, and the commute minutes fall inside a band. Then `floor` is that
    band's floor and `band` names it.

      * No anchor declares bands, or `commute_ok` was passed explicitly -> today's answer, line for
        line (criterion B4; proved against goldens taken before this edit).
      * Bands declared, onsite or hybrid, minutes UNKNOWN -> `hold="minutes"`: the screen says
        NEEDS-COMMUTE-CHECK. NEVER a guessed band (B2).
      * Minutes beyond the last band -> onsite is `relocation`, hybrid is the `hybrid` tier.
      * `hybrid` and `compensation.hybrid_inside_radius` is `"hybrid-tier"` -> today's `hybrid`
        tier; `"band"` (the default) prices it by the commute like an onsite role (B3).
      * Bands (or the key) present but UNREADABLE -> `hold="config"` with the reasons: loud, never
        an empty table and never a removal.

    jobsearch 0.70.0 (dev #729 / public #157, design R4): the anchor and the matched `includes`
    entry come from `commute_outcome` -- the ONE function that decides a role's anchor -- so a role
    that is `inside-radius` (no anchor NAMED in its text, but within a configured `radius_miles`)
    gets the same band logic as one that names its anchor. It never gets a band without
    `location.commute_minutes`: with bands declared and no minutes it holds (`hold="minutes"`),
    because a distance is not a commute time. An onsite role whose distance could not be computed
    (`hold="place-table"`, `hold="config"`) holds with the reason. `commute` is the outcome (None
    when the type is not onsite or hybrid, or `commute_ok` was passed), `anchor` the anchor it
    resolved (None otherwise).
    """
    import config_keys as _ck
    out = {"setting": effective_setting(location, profile, commute_ok, table), "floor": None,
           "band": None, "hold": None, "detail": None, "commute": None, "anchor": None}
    ltype = location.get("type") if isinstance(location, dict) else None
    if commute_ok is not None or ltype not in ("onsite", "hybrid"):
        return out
    oc = commute_outcome(location, profile, table)
    out["commute"] = oc
    if ltype == "onsite" and oc["hold"]:
        out["hold"], out["detail"] = oc["hold"], oc["detail"]
        return out
    if oc["state"] not in ("inside", "inside-radius"):
        return out                      # hybrid: outside every anchor -> hybrid tier (today's)
    anchor, entry = oc["anchor"], oc["entry"]
    out["anchor"] = anchor
    if ltype == "hybrid":
        mode, _prov = _ck.describe(profile, _ck.COMPENSATION_HYBRID_INSIDE_RADIUS)
        if mode not in _ck.COMPENSATION_HYBRID_INSIDE_RADIUS_VALUES:
            out["hold"] = "config"
            out["detail"] = ("compensation.hybrid_inside_radius is %r -- not one of: %s"
                             % (mode, ", ".join(_ck.COMPENSATION_HYBRID_INSIDE_RADIUS_VALUES)))
            return out
        if mode == "hybrid-tier":
            return out
    bands, problems = _ck.commute_bands(anchor)
    if problems:
        out["hold"] = "config"
        out["detail"] = ("anchor %r declares bands that cannot be read: %s"
                         % (anchor.get("place"), "; ".join(problems)))
        return out
    if not bands:
        return out                      # this anchor declares none -> today's
    minutes = _commute_minutes(location, entry)
    if minutes is None:
        out["hold"] = "minutes"
        out["detail"] = ("bands are declared on anchor %r; record location.commute_minutes -- a "
                         "band is never guessed" % anchor.get("place"))
        return out
    for max_minutes, floor in bands:
        if minutes <= max_minutes:
            out["setting"] = "local-onsite" if ltype == "onsite" else "hybrid"
            out["floor"] = floor
            out["band"] = {"max_minutes": max_minutes, "floor": floor, "minutes": minutes}
            return out
    out["setting"] = "relocation" if ltype == "onsite" else "hybrid"
    return out


# dev #727 / public #159 (jobsearch 0.70.0): a role whose `location.setting_source` is `inferred` was
# recorded onsite by the capture script because the sweep read NO setting at a concrete place. Every
# screen line computed on that inference says so, so a removal on it is never mistaken for one made
# on a stated setting.
INFERRED_NOTE = " (onsite inferred: the posting stated no setting)"


def is_inferred(opp_or_location):
    """True when the `location` (or the opportunity carrying it) is `setting_source: inferred`."""
    loc = opp_or_location.get("location") if isinstance(opp_or_location, dict) \
        and "location" in opp_or_location else opp_or_location
    return isinstance(loc, dict) and loc.get("setting_source") == "inferred"


def comp_accepted(opp):
    """True when the role's CURRENT decision accepts its pay (dev #739 / public #161): the row's own
    `verdict` is `pursue` and its `decision.reason_kind` is `comp-acceptable`. Read-only, from the row
    the screen is already handed. `record.py decide` overwrites `verdict` and `decision` together, so
    "current" holds by construction: a later decide with another `--why-kind` (superseded), or with a
    verdict other than `pursue` (reversed), makes this False and the plain BELOW-FLOOR returns."""
    dec = opp.get("decision")
    return (opp.get("verdict") == "pursue" and isinstance(dec, dict)
            and dec.get("reason_kind") == "comp-acceptable")


def title_engagement(title):
    """The non-employee engagement type the closed title vocabulary reads in `title`, or None
    (dev #740 / public #160; `config_keys.ENGAGEMENT_TITLE_PHRASES`). Whole-phrase, case-insensitive;
    when several types match, the first in the vocabulary's order wins."""
    import config_keys as _ck
    for etype, phrases in _ck.ENGAGEMENT_TITLE_PHRASES:
        if any(_contains_phrase(title, ph) for ph in phrases):
            return etype
    return None


def engagement(opp):
    """`(type, source)` -- how the screen routes a role's pay (dev #740 / public #160, E1).

    PRECEDENCE (controller decision R1, 2026-10-22): an explicitly STATED `engagement_type` always
    wins, `full-time` included -- #740's own wording is "an explicit field when present, otherwise the
    title", and it gives the candidate an override (set `full-time` on a role whose title says
    "Fractional" and it screens as employment).

      stated, a readable value   -> (that value, "stated")
      stated, not a readable one -> (the value, "unreadable"): the screen says PAY-UNCOMPARABLE naming
                                    it, never the annual floor (strict, loud)
      not stated, title marker   -> (the inferred type, "inferred"): flagged on every screen line
      otherwise                  -> (None, None): the employee path, 0.72.0's behaviour exactly."""
    import config_keys as _ck
    stated = opp.get("engagement_type")
    if isinstance(stated, str) and stated in _ck.ENGAGEMENT_TYPES:
        return stated, "stated"
    if stated is not None:
        return stated, "unreadable"
    inferred = title_engagement(opp.get("title"))
    if inferred:
        return inferred, "inferred"
    return None, None


def screen_comp(opp, profile, commute_ok=None, table=None, honour_decision=True):
    """Screen one opportunity's comp against the applicable tier. Returns `(verdict, detail)`; a
    role screened as onsite on an INFERENCE (`location.setting_source`, dev #727 / public #159)
    carries `INFERRED_NOTE` at the end of its detail, whatever the verdict, and a role routed by an
    ENGAGEMENT inferred from its title (dev #740 / public #160) carries `ENGAGEMENT_INFERRED_NOTE`.

    `honour_decision` (dev #739 / public #161): True (the default; every screen) reads the row's own
    current decision, so a BELOW-FLOOR role the candidate accepted (`comp_accepted`) is
    BELOW-FLOOR-ACCEPTED. `your_move.triage_suggestion` passes False: the engine's own suggestion
    must not feed the candidate's acceptance back into itself, or a re-decide would freeze
    `decision.suggested` at something other than `pass`.

    See `_screen_comp` for the rules themselves."""
    verdict, detail = _screen_comp(opp, profile, commute_ok, table, honour_decision)
    loc = opp.get("location") if isinstance(opp.get("location"), dict) else {}
    if loc.get("listed_at") and loc.get("type") in ("onsite", "hybrid") and commute_ok is None:
        # dev #728 / public #158 (design §5.6): the role is listed at several places and the MOST
        # FAVOURABLE one decided; the detail says which.
        detail += " [decided by the listing at %s]" % commute_outcome(loc, profile, table)["place"]
    if is_inferred(opp) and verdict != UNRESOLVED:
        detail += INFERRED_NOTE
    etype, esource = engagement(opp)
    if esource == "inferred":
        detail += ENGAGEMENT_INFERRED_NOTE % (etype, opp.get("id") or "<id>")
    return verdict, detail


def _below(figures, opp, note, honour_decision):
    """The ONE place a BELOW result is built, so the two BELOW sites (`comp.max` and `listed_pay`)
    cannot drift (dev #739 / public #161). `figures` is the sentence that names the band, its
    source/basis, the gap and the floor; `note` the `comp.max` path's total-basis warning (or "").
    Not accepted (or `honour_decision` False) -> BELOW-FLOOR and the sentence that names the decision
    that would lift it. Accepted -> BELOW-FLOOR-ACCEPTED with the SAME figures."""
    if honour_decision and comp_accepted(opp):
        dec = opp["decision"]
        reason = " ".join(str(dec.get("reason") or "no reason recorded").split())
        return BELOW_ACCEPTED, "%s %s%s" % (
            figures, ACCEPTED_SENTENCE % (dec.get("on") or "an earlier date", reason), note)
    return BELOW, "%s %s%s" % (figures, REMOVE_SENTENCE % (opp.get("id") or "<id>"), note)


def _amount(n):
    return format(n, ",")


def _screen_non_employee(opp, profile, etype, source):
    """`(verdict, detail)` for a role routed to a non-employee engagement (dev #740 / public #160,
    E2/E3; design §4.4). The annual base tiers are never consulted: a day rate set against an annual
    salary floor is the mismatch that removed fractional roles in 0.69.1.

      1. the figure: `comp.max` in its own `comp.period` (an absent or unreadable period is NOT assumed
         annual), else `listed_pay` through the 0.67.0 rules for state, selection and open-ended
         ranges; nothing recorded is NOT-CAPTURED, `none-shown` UNDISCLOSED
      2. `compensation.non_employee` absent -> PAY-UNCOMPARABLE naming the key to set; unreadable ->
         PAY-UNCOMPARABLE naming the problems
      3. `listed_pay` in a currency other than the profile's (or the profile's unset) -> PAY-UNCOMPARABLE
      4. no floor in the figure's unit -> PAY-UNCOMPARABLE, never converted
      5. at or above the same-unit floor -> CLEARS; below -> BELOW-ENGAGEMENT-FLOOR

    NEVER a removal: non-employee pay is priced per scope, so a rate under the floor is a negotiating
    position, not a disqualifier (design D8)."""
    import config_keys as _ck
    who = "%s engagement (%s)" % (etype, source)
    comp = opp.get("comp") if isinstance(opp.get("comp"), dict) else None
    lp = opp.get("listed_pay") if isinstance(opp.get("listed_pay"), dict) else None
    entries = []                      # (reach, unit, shown, has_max)
    selected, estimate = [], False
    if comp and comp.get("max") is not None:
        top = _num(comp["max"])
        period = comp.get("period")
        unit = period.strip().lower() if isinstance(period, str) else None
        shown = "%s per %s" % (_amount(top), unit) if top is not None and unit else "%r" % comp.get("max")
        if top is None:
            return PAY_UNCOMPARABLE, ("%s: comp.max %r is not a number -- not compared."
                                      % (who, comp.get("max")))
        if unit not in _ck.NON_EMPLOYEE_UNITS:
            return PAY_UNCOMPARABLE, (
                "%s: comp %s has no readable unit (comp.period is %r; one of %s) -- a non-employee "
                "figure is never assumed annual, and never converted. Record comp.period."
                % (who, _amount(top), period, "/".join(_ck.NON_EMPLOYEE_UNITS)))
        entries.append((top, unit, shown, True))
    elif lp is not None:
        state = lp.get("state")
        if state == "none-shown":
            return UNDISCLOSED, ("%s: the listing showed NO pay (recorded none-shown, not merely "
                                 "uncaptured) -- KEEP; it cannot be screened on." % who)
        ranges = [r for r in (lp.get("ranges") or []) if isinstance(r, dict)]
        if state not in ("employer-stated", "board-estimate") or not ranges or any(
                _num(r.get("min")) is None and _num(r.get("max")) is None for r in ranges):
            return NOT_CAPTURED, (
                "%s: listed_pay is recorded but carries no readable range (state %r) -- treated as "
                "NOT captured, never as a figure. RE-READ THE LISTING before surfacing it."
                % (who, state))
        loc = opp.get("location") or {}
        selected = [r for r in ranges if _label_matches(r.get("label"), loc, None)] or ranges
        estimate = state == "board-estimate"
        for r in selected:
            reach = _num(r.get("max")) if _num(r.get("max")) is not None else _num(r.get("min"))
            entries.append((reach, r.get("interval"), _range_text(r), _num(r.get("max")) is not None))
    else:
        return NOT_CAPTURED, (
            "%s: no pay was ever recorded for this role (no listed_pay, no comp figure) -- that is NOT "
            "the same as the listing showing none. RE-READ THE LISTING before surfacing it." % who)

    shown_all = "; ".join(e[2] for e in entries)
    block = (profile.get("compensation") or {}).get("non_employee") if isinstance(
        profile.get("compensation"), dict) else None
    if block is None:
        return PAY_UNCOMPARABLE, (
            "%s: pay %s is not measured against the annual base tiers; set "
            "compensation.non_employee.floors to compare (shape: {\"floors\": {\"day\": <int>, ...}}). "
            "KEEP for review -- a non-employee engagement is never removed on an annual floor."
            % (who, shown_all))
    problems = _ck.validate_non_employee(block)
    if problems:
        return PAY_UNCOMPARABLE, ("%s: pay %s cannot be compared -- %s. KEEP for review."
                                  % (who, shown_all, "; ".join(problems)))
    floors = block["floors"]
    if lp is not None and not (comp and comp.get("max") is not None):
        try:
            currency = _ck.resolve_currency(profile)
        except ValueError as e:
            return PAY_UNCOMPARABLE, "%s: listed pay %s cannot be compared: %s" % (who, shown_all, e)
        if currency is None:
            return PAY_UNCOMPARABLE, (
                "%s: listed pay %s cannot be compared -- set compensation.currency to compare listed "
                "pay (the profile's currency is unset, so no figure is ever read as below a floor)."
                % (who, shown_all))
        for r in selected:
            if str(r.get("currency") or "").upper() != currency:
                return PAY_UNCOMPARABLE, (
                    "%s: listed pay %s is in %s, the profile's currency is %s -- not converted. KEEP "
                    "for review." % (who, shown_all, r.get("currency"), currency))
    for _reach, unit, shown, _has_max in entries:
        if unit not in floors:
            return PAY_UNCOMPARABLE, (
                "%s: stated per %s; your non-employee floors are per %s -- not converted (a guessed "
                "conversion that removes is the defect class). KEEP for review."
                % (who, unit or "an unstated unit", ", ".join(sorted(floors))))
    clearing = [e for e in entries if e[0] is not None and e[0] >= floors[e[1]]]
    if clearing:
        best = max(clearing, key=lambda e: e[0])
        return CLEARS, ("%s: top of pay %s%s >= your non-employee %s floor %s."
                        % (who, best[2], " (board estimate)" if estimate else "", best[1],
                           _amount(floors[best[1]])))
    if estimate:
        return PAY_UNCOMPARABLE, (
            "%s: board estimate %s is below your non-employee floor -- an estimate is not the "
            "employer's figure, so it is never read as below a floor. Ask the employer."
            % (who, shown_all))
    open_ended = [e for e in entries if not e[3]]
    if open_ended:
        return UNDISCLOSED, ("%s: open-ended range %s; the top is not stated -- KEEP." %
                             (who, open_ended[0][2]))
    best = max(entries, key=lambda e: e[0])
    return BELOW_ENGAGEMENT, (
        "%s: top of pay %s is %s BELOW your non-employee %s floor (%s). A review, never a removal: "
        "non-employee pay is priced per scope." % (
            who, best[2], _amount(floors[best[1]] - best[0]), best[1], _amount(floors[best[1]])))


def _screen_comp(opp, profile, commute_ok=None, table=None, honour_decision=True):
    """Screen one opportunity's comp against the applicable tier.

    Returns (verdict, detail). Verdicts: CLEARS / BELOW-FLOOR / BELOW-FLOOR-ACCEPTED /
    BELOW-ENGAGEMENT-FLOOR / UNDISCLOSED / NEEDS-COMMUTE-CHECK / UNRESOLVED-SETTING / NOT-CAPTURED /
    PAY-UNCOMPARABLE.

    Screening is applied to the TOP of the stated band (profile's below_floor rule),
    and an undisclosed band is explicitly KEPT — comp is the first question to ask,
    so it cannot be screened on.

    jobsearch 0.73.0 (dev #740 / public #160): a role whose engagement is not employment is routed
    BEFORE the location holds (`engagement`, `_screen_non_employee`) -- the non-employee floors are not
    keyed by setting, so a contested setting does not block them -- and the annual tiers below never
    see it. An unreadable stated `engagement_type` is PAY-UNCOMPARABLE naming it.
    """
    import config_keys as _ck
    etype, esource = engagement(opp)
    if esource == "unreadable":
        return PAY_UNCOMPARABLE, (
            "engagement_type %r is not a value this engine reads (%s) -- the pay is not measured "
            "against the annual base tiers. KEEP for review; correct it with `record.py set %s "
            "engagement_type <value>`." % (etype, ", ".join(_ck.ENGAGEMENT_TYPES),
                                           opp.get("id") or "<id>"))
    if etype in _ck.ENGAGEMENT_NON_EMPLOYEE:
        return _screen_non_employee(opp, profile, etype, esource)
    comp = opp.get("comp")
    loc = opp.get("location") or {}

    # ⭐ A CONTESTED SETTING IS DECLINED, NOT RESOLVED (issue #4). The posting itself declared
    # more than one setting; whichever one a resolver picked would silently select the comp
    # floor the role is screened against. This is the third instance of the standing rule that
    # a fact a run knows goes into the queryable store: the run KNOWS the setting is contested,
    # and this verdict is where that fact surfaces — loudly, as a question for the EMPLOYER,
    # never as a silent skip. The role stays in the pipeline until the answer arrives.
    if loc.get("type") == "unresolved":
        declared = loc.get("declared")
        return UNRESOLVED, (
            "the posting declares a contested work setting%s — the answer selects which comp "
            "floor applies, so NO tier is picked. ASK THE EMPLOYER which setting governs, then "
            "record the answer in location.type. This role needs an answer; it is NOT screened "
            "and must not quietly drop out."
            % (" (verbatim: %r)" % declared if declared else ""))

    # dev #727 / public #159 (LS-B3): the sweep read NO setting and no place could be read from the
    # card, so the capture script had nothing to infer and left `location.type` ABSENT. That is a
    # question for the candidate, not a floor: never an inference fired on nothing.
    if isinstance(loc, dict) and "type" not in loc and loc.get("declared") == "none stated":
        return NEEDS_COMMUTE, (
            "no setting stated and no place: the sweep read no work setting on this posting "
            "(declared 'none stated') and location.primary %r is not a place the place table "
            "reads, so location.type is absent. Read the posting, then record its setting with "
            "`record.py set %s location '<json>'`. Ask/check before applying any floor."
            % (loc.get("primary"), opp.get("id") or "<id>"))

    resolved = resolve_floor(loc, profile, commute_ok, table)
    setting = resolved["setting"]

    if resolved["hold"]:
        return NEEDS_COMMUTE, (
            "location.type=%r at %r — %s. Ask/check before applying any floor."
            % (loc.get("type"), loc.get("primary"), resolved["detail"]))

    if setting is None:
        # dev #729 / public #157: an onsite role the commute resolver could not place says WHY
        # after the unchanged sentence -- `near` carries its distance, `unresolvable` says the
        # text is not a place the table knows. The sentence itself is the 0.67.0 text, byte for byte.
        oc = resolved.get("commute")
        has_place = isinstance(loc.get("primary"), str) and bool(loc["primary"].strip())
        why = (" (%s)" % oc["detail"]) if oc and oc.get("detail") and has_place else ""
        return NEEDS_COMMUTE, (
            "location.type=%r at %r — cannot tell whether this is a commute or a MOVE. "
            "Ask/check before applying any floor. Never assume 'onsite' means relocation.%s"
            % (loc.get("type"), loc.get("primary"), why))

    tier = tiers(profile)[setting]
    floor = resolved["floor"] if resolved["floor"] is not None else tier["floor"]
    label = setting
    if resolved["band"]:
        label = "%s band (%d min, within %d)" % (setting, resolved["band"]["minutes"],
                                                 resolved["band"]["max_minutes"])

    if comp and comp.get("max") is not None:
        pass                              # §5.2 step 1: the candidate's own figure screens, as before
    elif isinstance(opp.get("listed_pay"), dict):
        return _screen_listed_pay(opp["listed_pay"], opp, profile, label, floor,
                                  resolved.get("anchor"), honour_decision)
    else:
        return NOT_CAPTURED, (
            "no pay was ever recorded for this role (no listed_pay, no comp figure) — that is NOT "
            "the same as the listing showing none. RE-READ THE LISTING before surfacing it. "
            "Applicable tier would be %s (floor $%sK base)." % (label, floor // 1000))

    top = comp["max"]
    # dev #740 / public #160 (E3): the floor is an ANNUAL BASE figure. A band stated per hour, day or
    # month, or on a basis other than base/total (the reporter's `contract`), is a different quantity,
    # and an annotation alone left it BELOW-FLOOR and REMOVE. It is PAY-UNCOMPARABLE now (a review),
    # never converted. A `total` basis keeps its note and verdict: a total-comp top below a base floor
    # puts the base top below it too, so a removal on it stays certain.
    period = comp.get("period")
    if period is not None and str(period).strip().lower() != "year":
        return PAY_UNCOMPARABLE, (
            "comp %s is per %s, not per year -- not converted (hours or days per year is a guess, and "
            "a guessed conversion that removes is the defect class). Applicable tier would be %s "
            "(floor $%sK base). KEEP for review; ask the employer for the annual figure."
            % (top, period, label, floor // 1000))
    basis = str(comp.get("basis") or "base").lower()
    if basis not in ("base", "total"):
        return PAY_UNCOMPARABLE, (
            "comp is stated as %r; the floor is annual BASE -- not comparable, not converted. "
            "Applicable tier would be %s (floor $%sK base). KEEP for review; ask what the base is."
            % (basis, label, floor // 1000))
    note = ""
    if basis != "base":
        note = (" ⚠️ band is stated as %r, but the floor is BASE — compare like with like "
                "before trusting this verdict." % basis)

    if top >= floor:
        return CLEARS, ("top of band $%sK >= %s floor $%sK.%s"
                        % (int(top) // 1000, label, floor // 1000, note))
    gap = floor - top
    return _below(
        "top of band $%sK is $%sK BELOW the %s floor ($%sK)."
        % (int(top) // 1000, int(gap) // 1000, label, floor // 1000), opp, note, honour_decision)


def parse_pay_ranges(text):
    """Parse the ROLES pay slot's range list: `<range>[;<range>...]` with
    `<range>` := `<min>-<max>/<yr|mo|day|hr>/<CUR>` | `<min>+/<yr|mo|day|hr>/<CUR>` (integers, no
    separators; design §4.1, R2). Returns a list of `{min, max, currency, interval, label}` dicts
    (`label` None: the grammar carries none). STRICT: anything it cannot read raises `ValueError`
    naming the piece -- a figure is never guessed and never silently dropped."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a pay range list is empty")
    out = []
    for piece in text.split(";"):
        parts = piece.strip().split("/")
        if len(parts) != 3:
            raise ValueError("pay range %r is not <min>-<max>/<yr|mo|day|hr>/<CUR>" % piece)
        amount, unit, cur = parts
        if unit not in PAY_INTERVAL_ABBR:
            raise ValueError("pay range %r: interval %r is not one of %s"
                             % (piece, unit, "/".join(PAY_INTERVAL_ABBR)))
        if len(cur) != 3 or not cur.isalpha() or not cur.isascii():
            raise ValueError("pay range %r: currency %r is not a three-letter code" % (piece, cur))
        if amount.endswith("+"):
            lo, hi = amount[:-1], None
        elif "-" in amount:
            lo, hi = amount.split("-", 1)
        else:
            raise ValueError("pay range %r: amount %r is neither <min>-<max> nor <min>+"
                             % (piece, amount))
        for n in (lo, hi):
            if n is not None and not (n.isdigit() and n.isascii()):
                raise ValueError("pay range %r: %r is not a plain integer" % (piece, n))
        lo_i, hi_i = int(lo), (int(hi) if hi is not None else None)
        if hi_i is not None and lo_i > hi_i:
            raise ValueError("pay range %r: min %d is above max %d" % (piece, lo_i, hi_i))
        out.append({"min": lo_i, "max": hi_i, "currency": cur.upper(),
                    "interval": PAY_INTERVAL_ABBR[unit], "label": None})
    return out


def _range_text(r):
    lo, hi = r.get("min"), r.get("max")
    amount = ("%s-%s" % (format(lo, ","), format(hi, ",")) if lo is not None and hi is not None
              else "%s+" % format(lo, ",") if hi is None else "up to %s" % format(hi, ","))
    return "%s %s/%s" % (amount, r.get("currency"), r.get("interval"))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _label_matches(label, loc, anchor):
    """True when a range's own `label` (the posting's verbatim name for a location-specific
    range) names the role's matched commute anchor (`anchor`, as `commute_outcome` resolved it, or
    None) or its `location.primary` (case-insensitive substring, design §5.3)."""
    if not isinstance(label, str) or not label.strip():
        return False
    lab = label.lower()
    names = []
    if anchor is not None:
        names.append(anchor.get("place"))
    names.append(loc.get("primary"))
    for n in names:
        if not isinstance(n, str):
            continue
        for tok in (n.strip().lower(), n.split(",")[0].strip().lower()):
            if tok and tok in lab:
                return True
    return False


def _screen_listed_pay(lp, opp, profile, label, floor, anchor=None, honour_decision=True):
    """`screen_comp`'s §5.3: one `listed_pay` object against `floor` (the tier or band already
    chosen). Returns `(verdict, detail)`.

    REMOVE must be certain. So: no profile currency -> PAY-UNCOMPARABLE (R1); a non-annual interval
    or another currency -> PAY-UNCOMPARABLE, never converted (R2); a board's estimate NEVER says
    BELOW-FLOOR; several employer-stated ranges remove only when EVERY selected range's top is below
    the floor, and a range whose label names this role's anchor or place is screened alone."""
    import config_keys as _ck
    state = lp.get("state")
    if state == "none-shown":
        return UNDISCLOSED, (
            "the listing showed NO pay (recorded none-shown, not merely uncaptured) — KEEP (comp is "
            "the first question; it cannot be screened on). Applicable tier would be %s (floor "
            "$%sK base)." % (label, floor // 1000))
    ranges = [r for r in (lp.get("ranges") or []) if isinstance(r, dict)]
    if state not in ("employer-stated", "board-estimate") or not ranges or any(
            _num(r.get("min")) is None and _num(r.get("max")) is None for r in ranges):
        return NOT_CAPTURED, (
            "listed_pay is recorded but carries no readable range (state %r) — treated as NOT "
            "captured, never as a figure. RE-READ THE LISTING before surfacing it." % state)
    loc = opp.get("location") or {}
    selected = [r for r in ranges if _label_matches(r.get("label"), loc, anchor)] or ranges
    shown = "; ".join(_range_text(r) for r in selected)
    try:
        currency = _ck.resolve_currency(profile)
    except ValueError as e:
        return PAY_UNCOMPARABLE, "listed pay %s cannot be compared: %s" % (shown, e)
    if currency is None:
        return PAY_UNCOMPARABLE, (
            "listed pay %s cannot be compared — set compensation.currency to compare listed pay "
            "(the profile's currency is unset, so no figure is ever read as below a floor)." % shown)
    for r in selected:
        if r.get("interval") != "year":
            return PAY_UNCOMPARABLE, (
                "listed pay %s is per %s, not per year — not converted (hours or days per year is "
                "a guess, and a guessed conversion that removes is the defect class). KEEP for "
                "review; ask the employer for the annual figure." % (shown, r.get("interval")))
        if str(r.get("currency") or "").upper() != currency:
            return PAY_UNCOMPARABLE, (
                "listed pay %s is in %s, the profile's currency is %s — not converted. KEEP for "
                "review." % (shown, r.get("currency"), currency))

    def reach(r):                       # the best this range can be known to pay
        return _num(r.get("max")) if _num(r.get("max")) is not None else _num(r.get("min"))

    clearing = [r for r in selected if reach(r) is not None and reach(r) >= floor
                and (_num(r.get("max")) is not None or _num(r.get("min")) >= floor)]
    estimate = state == "board-estimate"
    if clearing:
        best = max(clearing, key=reach)
        return CLEARS, ("top of listed pay %s%s >= %s floor $%sK."
                        % (_range_text(best), " (board estimate)" if estimate else "", label,
                           floor // 1000))
    if estimate:
        return PAY_UNCOMPARABLE, (
            "board estimate %s is below the %s floor ($%sK) — an estimate is not the employer's "
            "figure, so it never removes. Ask the employer." % (shown, label, floor // 1000))
    open_ended = [r for r in selected if _num(r.get("max")) is None]
    if open_ended:
        r = open_ended[0]
        return UNDISCLOSED, (
            "open-ended range from %s; the top is not stated — KEEP. Applicable tier would be %s "
            "(floor $%sK base)." % (format(_num(r.get("min")), ","), label, floor // 1000))
    best = max(selected, key=reach)
    return _below(
        "employer-stated top %s (source %s) is $%sK BELOW the %s floor ($%sK)."
        % (_range_text(best), lp.get("source") or "unrecorded", int(floor - reach(best)) // 1000,
           label, floor // 1000), opp, "", honour_decision)


def _load_opps():
    path = os.path.join(ROOT, "data", "opportunities.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _load_optional(name):
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


TITLE_FLOOR_LEAN_ID = "title-floor"      # the computed lean hit's id (dev #722 / public #156)


def title_level(title):
    """The seniority level the closed ladder reads in `title`, or None when no phrase matches
    (dev #722 / public #156; `config_keys.SENIORITY_LADDER`). Phrases are matched whole-phrase,
    case-insensitively, LONGEST FIRST on NON-OVERLAPPING spans, so "vice president" is consumed
    before "president" and "general manager" before "manager"; the level is the HIGHEST rank any
    phrase matched. No match is None, and None is never below a floor."""
    import config_keys as _ck
    h = _squash(title)
    if not h:
        return None
    phrases = sorted(((p, rank) for rank, (_lvl, ps) in enumerate(_ck.SENIORITY_LADDER)
                      for p in ps), key=lambda pr: (-len(pr[0]), pr[0]))
    taken, best = [], None
    for phrase, rank in phrases:
        p = _squash(phrase)
        start = h.find(p)
        while start != -1:
            end = start + len(p)
            before_ok = start == 0 or not (h[start - 1].isalnum() or h[start - 1] == "_")
            after_ok = end == len(h) or not (h[end].isalnum() or h[end] == "_")
            if before_ok and after_ok and not any(start < e and s < end for s, e in taken):
                taken.append((start, end))
                best = rank if best is None else max(best, rank)
            start = h.find(p, start + 1)
    return None if best is None else _ck.SENIORITY_LEVELS[best]


def _screen_cfg(profile):
    node = (profile or {}).get("screen")
    return node if isinstance(node, dict) else {}


def title_signals(profile):
    """The title-field `screen.likely_pass_signals` (the MANDATE, owner decision R1: out-of-scope
    function phrases are a pass LEAN, never a removal) as signals restricted to the title field.
    Raises ValueError when the list cannot be read -- an unreadable list is loud, never empty."""
    import config_keys as _ck
    signals = _screen_cfg(profile).get("likely_pass_signals")
    problems = _ck.validate_likely_pass_signals(signals)
    if problems:
        raise ValueError("screen.likely_pass_signals cannot be read: %s" % "; ".join(problems))
    return [dict(s, fields=["title"]) for s in (signals or []) if "title" in s["fields"]]


def title_keys(profile):
    """A short hash of everything the title rule reads (dev #722 / public #156, R2):
    `screen.title_floor`, `targets.titles` and the title-field `likely_pass_signals` (id and
    phrase). `record.py screened` stores it on the screen; `your_move.triage_missing` asks for a
    re-screen when the stored hash is not today's. An unreadable signal list hashes as itself, so
    fixing it also re-screens."""
    import hashlib
    try:
        sigs = [[s["id"], s["phrase"]] for s in title_signals(profile)]
    except ValueError as e:
        sigs = ["unreadable", str(e)]
    floor = _screen_cfg(profile).get("title_floor")
    titles = [t for t in ((profile or {}).get("targets") or {}).get("titles") or [] if t]
    raw = json.dumps({"floor": floor, "titles": titles, "signals": sigs}, sort_keys=True,
                     ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def screen_is_title_stale(screen, profile):
    """True when a STORED screen was computed under different title keys than today's (dev #722 /
    public #156, R2): its `title_keys` is not `title_keys(profile)`, or it has none and a
    `screen.title_floor` is now set (a screen stored by 0.68.0 or earlier). With no floor set, an
    absent hash is NOT stale: nothing the old screen could have missed has been asked of it. A
    screen that is not an object is not this function's question (`triage_missing` already asks
    for it). `your_move.triage_missing` reads this, so the pile screened before the keys existed
    drains through the normal triage path, at the per-run cap, with no bulk pass."""
    if not isinstance(screen, dict):
        return False
    stored = screen.get("title_keys")
    if stored is None:
        return _screen_cfg(profile).get("title_floor") is not None
    return stored != title_keys(profile)


def title_scope_count(opps, profile):
    """`{undecided, below_floor, off_mandate, rescreen_pending}` over the undecided backlog roles
    (dev #722 / public #156, R2's measure): `undecided` is `status: backlog` with verdict
    `undecided`; `below_floor` / `off_mandate` count the ones whose TITLE reads that way under
    today's keys (computed live from the title, never from a stored screen, so it is the size of
    the problem before any role is re-screened); `rescreen_pending` counts those with a stored
    screen whose title keys are stale. Read-only. Run before and after on the fixture; on a real
    profile only the owner's own session reads it, never a dispatch."""
    import config_keys as _ck
    floor = _screen_cfg(profile).get("title_floor")
    problems = _ck.validate_title_floor(floor)
    try:
        signals = title_signals(profile)
    except ValueError:
        signals = []
    configured = [t for t in ((profile or {}).get("targets") or {}).get("titles") or [] if t]
    out = {"undecided": 0, "below_floor": 0, "off_mandate": 0, "rescreen_pending": 0}
    for o in opps:
        if o.get("status") != "backlog" or o.get("verdict") != "undecided":
            continue
        out["undecided"] += 1
        if screen_is_title_stale(o.get("screen"), profile):
            out["rescreen_pending"] += 1
        if floor is not None and not problems:
            level = title_level(o.get("title"))
            if level is not None and (_ck.SENIORITY_LEVELS.index(level)
                                      < _ck.SENIORITY_LEVELS.index(floor)):
                out["below_floor"] += 1
                continue
        if signals and not _matches_target(o, configured) and match_signals(
                o, None, "", signals):
            out["off_mandate"] += 1
    return out


def comp_keys(opp, profile):
    """A short hash of everything the comp screen reads that a stored screen could not have known
    (dev #739 / public #161 and dev #740 / public #160; design R2, the SIBLING of `title_keys`):

      * the engagement vocabulary (`config_keys.engagement_vocab_hash`: the values and every phrase)
      * `compensation.non_employee` (the profile's non-employee floors, as written)
      * the role's own routing: `engagement(opp)` -- the stated type or the title's inference
      * the role's `comp.period` and `comp.basis` (the E3 downgrade reads both)
      * `comp_accepted(opp)` -- whether the CURRENT decision is pursue + comp-acceptable

    `record.py screened` stores it as `screen.comp_keys`; `screen_is_comp_stale` compares it. It is a
    sibling hash, not folded into `title_keys`, so storing it does not make every screen already
    on disk stale."""
    import hashlib
    import config_keys as _ck
    comp = opp.get("comp") if isinstance(opp.get("comp"), dict) else {}
    cfg_comp = (profile or {}).get("compensation")
    block = cfg_comp.get("non_employee") if isinstance(cfg_comp, dict) else None
    raw = json.dumps({"vocab": _ck.engagement_vocab_hash(), "block": block,
                      "engagement": list(engagement(opp)), "period": comp.get("period"),
                      "basis": comp.get("basis"), "accepted": comp_accepted(opp)},
                     sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def screen_is_comp_stale(screen, opp, profile):
    """True when a STORED screen was computed without the comp inputs 0.73.0 reads, or under other
    ones (dev #739 / #740; design R2). Its `comp_keys` is not today's hash for this role, OR it has
    none (stored by 0.72.0 or earlier) and THIS role has an input the old screen could not have read:
    a non-employee or unreadable engagement, a `comp.period` other than year or a `comp.basis` other
    than base/total on a stated figure, or a current comp-acceptable pursue on a stored BELOW-FLOOR.
    An absent hash on a role with none of those is NOT stale: nothing the old screen could have
    missed was asked of it, so the pile screened before the keys existed drains only where it must.
    A screen that is not an object is not this function's question (`triage_missing` asks for it).
    `your_move.triage_missing` reads this, so a wrong stored `remove:comp` drains through the normal
    triage path at its per-run cap, with no bulk pass."""
    import config_keys as _ck
    if not isinstance(screen, dict):
        return False
    stored = screen.get("comp_keys")
    if stored is not None:
        return stored != comp_keys(opp, profile)
    etype, esource = engagement(opp)
    if esource == "unreadable" or etype in _ck.ENGAGEMENT_NON_EMPLOYEE:
        return True
    comp = opp.get("comp") if isinstance(opp.get("comp"), dict) else {}
    if comp.get("max") is not None:
        period, basis = comp.get("period"), comp.get("basis")
        if period is not None and str(period).strip().lower() != "year":
            return True
        if basis is not None and str(basis).lower() not in ("base", "total"):
            return True
    rules = screen.get("rules") if isinstance(screen.get("rules"), dict) else {}
    return comp_accepted(opp) and rules.get("comp") == BELOW


def comp_scope_count(opps, profile):
    """`{screened, rescreen_pending}` over every role carrying a stored screen (dev #739 / #740,
    design R2's measure): `rescreen_pending` counts those `screen_is_comp_stale` reports. Read-only,
    computed live, and run over EVERY status: a role the old screen wrongly removed has left the
    live pipeline, and it is exactly the one this count must not skip."""
    out = {"screened": 0, "rescreen_pending": 0}
    for o in opps:
        sc = o.get("screen")
        if isinstance(sc, dict) and sc.get("verdict"):
            out["screened"] += 1
            if screen_is_comp_stale(sc, o, profile):
                out["rescreen_pending"] += 1
    return out


def _matches_target(opp, configured):
    import pipeline_index as _pidx
    want = _pidx.normalize_title(opp.get("title"))
    return bool(want) and any(
        (" %s " % _pidx.normalize_title(t)) in (" %s " % want)
        for t in configured if _pidx.normalize_title(t))


def title_floor_lean(screen, profile):
    """`(lean, line, hit)` or None: the lean a STORED screen's BELOW-FLOOR title implies (owner
    decision R1, 2026-10-16). A below-floor title NEVER removes -- a larger company gives a lower
    title for the same scope -- so pay decides, read from the comp rule's stored verdict:

      comp CLEARS         -> pursue, "title below your floor (<level>), but pay is within your range"
      comp BELOW-FLOOR    -> None: the comp rule already removes; the title adds nothing
      comp BELOW-FLOOR-ACCEPTED -> pursue, "title below your floor (<level>), and you accepted the
                             pay" (dev #739: the candidate's own decision has settled pay)
      any other comp      -> ask, "title below your floor (<level>); check pay before deciding"

    `hit` is the computed signal `record.py lean` stores beside the matched signals, in the shape
    they have (`id`, `reason`, `matched_in`). None when the screen did not flag the title."""
    rules = screen.get("rules") if isinstance(screen, dict) else None
    if not isinstance(rules, dict) or rules.get("title") != "BELOW-FLOOR":
        return None
    floor = _screen_cfg(profile).get("title_floor")
    if rules.get("comp") == BELOW or not isinstance(floor, str) or not floor:
        return None
    if rules.get("comp") == CLEARS:
        lean, line = "pursue", "title below your floor (%s), but pay is within your range" % floor
    elif rules.get("comp") == BELOW_ACCEPTED:
        # dev #739 / public #161: the candidate accepted the pay below the floor, so pay has been
        # decided; the lean is the same as for pay that clears, and the line says why.
        lean, line = "pursue", "title below your floor (%s), and you accepted the pay" % floor
    else:
        lean, line = "ask", "title below your floor (%s); check pay before deciding" % floor
    return lean, line, {"id": TITLE_FLOOR_LEAN_ID, "reason": line, "matched_in": "title"}


def _matching_target(title, configured):
    """The first configured `targets.titles` entry whose normalized words sit inside the normalized
    `title`, or None. THE ONE DEFINITION of "this title matches": `_title_rule` (the screen's
    MATCHES / NO-MATCH) and `title_matches` (the feed poller's selection) both call it, so selection
    and screen cannot disagree about what a match is (dev #751, design §3.5)."""
    import pipeline_index as _pidx
    want = _pidx.normalize_title(title)
    if not want:
        return None
    for t in configured:
        nt = _pidx.normalize_title(t)
        if nt and (" %s " % nt) in (" %s " % want):
            return t
    return None


def title_matches(title, profile):
    """`True` / `False` / `None`: does `title` match a configured `targets.titles` entry, by the
    SAME matcher the screen's title rule uses (`_matching_target`)?

    `None` -- not a False -- when the answer cannot be given: no `targets.titles` configured, or the
    title keys (`screen.title_floor`, the title-field `likely_pass_signals`) cannot be read, which is
    the state in which `_title_rule` itself reports UNREADABLE-TITLE-KEYS. The feed poller refuses its
    whole pass on `None`: capturing every opening at every company is not a safe default (dev #751,
    design §3.5). Floor and mandate are NOT applied here; they are the screen's, after capture."""
    import config_keys as _ck
    configured = [t for t in (((profile or {}).get("targets") or {}).get("titles") or []) if t]
    if not configured:
        return None
    if _ck.validate_title_floor(_screen_cfg(profile).get("title_floor")):
        return None
    try:
        title_signals(profile)
    except ValueError:
        return None
    return _matching_target(title, configured) is not None


def _title_rule(opp, profile):
    """`(token, text, review)` for the advisory title rule: BELOW-FLOOR / OFF-MANDATE / MATCHES /
    NO-MATCH / NO-CONFIGURED-TITLES (/ UNREADABLE-TITLE-KEYS). Only ever a `review`, never a
    removal.

    dev #722 / public #156 (jobsearch 0.69.0): `screen.title_floor` and the title-field
    `screen.likely_pass_signals` (the mandate) add two tokens. PRECEDENCE: BELOW-FLOOR >
    OFF-MANDATE > MATCHES / NO-MATCH / NO-CONFIGURED-TITLES. Neither removes: the verdict stays
    `review:title` and the LEAN each implies is computed from the stored screen at `record.py lean`
    time (`title_floor_lean`; a signal match through `match_signals`). A seniority level the
    ladder cannot read is never below the floor. The floor is not skipped when the title matches a
    configured target (seniority is orthogonal to function); the mandate IS skipped then, because
    a configured target is in mandate by definition. With neither key configured this is exactly
    the 0.68.0 rule. A key that cannot be read is a visible `UNREADABLE-TITLE-KEYS` review, never a
    silent skip."""
    import config_keys as _ck
    import pipeline_index as _pidx
    configured = [t for t in ((profile.get("targets") or {}).get("titles") or []) if t]
    matched = _matching_target(opp.get("title"), configured)
    floor = _screen_cfg(profile).get("title_floor")
    floor_problems = _ck.validate_title_floor(floor)
    try:
        signals = title_signals(profile)
        signal_problem = None
    except ValueError as e:
        signals, signal_problem = [], str(e)
    if floor_problems or signal_problem:
        return ("UNREADABLE-TITLE-KEYS", "UNREADABLE -- %s" % "; ".join(
            floor_problems + ([signal_problem] if signal_problem else [])), True)
    if floor is not None:
        level = title_level(opp.get("title"))
        if level is not None and (_ck.SENIORITY_LEVELS.index(level)
                                  < _ck.SENIORITY_LEVELS.index(floor)):
            return ("BELOW-FLOOR",
                    "BELOW-FLOOR (reads %s, below your floor %s) -- advisory: pay decides, "
                    "nothing is removed" % (level, floor), True)
    if signals and not matched:
        hits = match_signals(opp, None, "", signals)
        if hits:
            return ("OFF-MANDATE",
                    "OFF-MANDATE (%s) -- advisory: a lean to pass, nothing is removed"
                    % "; ".join("%s: %s" % (h["id"], h["reason"]) for h in hits), True)
    if matched:
        return "MATCHES", "MATCHES %r" % matched, False
    if not configured:
        return ("NO-CONFIGURED-TITLES",
                "NO CONFIGURED TITLES (targets.titles is empty) -- advisory", False)
    return "NO-MATCH", "NO CONFIGURED TITLE MATCHES -- advisory", True


def posting_age(opp, today=None):
    """`(days, source, date)` of a role's posting, or `(None, None, None)` when the age is unknown
    (design §3.3, §6.1). Unknown is: no `posted`, `source: unknown`, a date that does not parse, or
    one in the future -- a negative age is a data fault and is never shown as a number."""
    import datetime as _dt
    posted = opp.get("posted")
    if not isinstance(posted, dict) or posted.get("source") in (None, "unknown"):
        return None, None, None
    try:
        when = _dt.date.fromisoformat(str(posted.get("date")))
    except ValueError:
        return None, None, None
    days = ((today or _dt.date.today()) - when).days
    if days < 0:
        return None, None, None
    return days, posted.get("source"), when.isoformat()


def _from_recruiter(opp, channels):
    """True when the role's `channel_id` resolves to a channel of `type: recruiter` (design §6.2).
    Not a distinction between retained and contingent firms: the store does not carry one, and the
    first move is the same question either way."""
    cid = opp.get("channel_id")
    return bool(cid) and any(isinstance(c, dict) and c.get("id") == cid
                             and c.get("type") == "recruiter" for c in (channels or []))


# The two first moves the age rule asks of a recruiter role (design §6.2), one copy: `_age_rule`
# prints them in the age line and `age_flag_first_move` hands them to the triage lean, so the line
# the candidate reads on the screen and the line on the Decide card cannot drift apart.
AGE_FIRST_MOVE_OVER = ("ask the recruiter what stage the search is in, before research or "
                       "letters")
AGE_FIRST_MOVE_UNKNOWN = "ask the recruiter when the search opened"


def age_flag_first_move(screen):
    """The first-move text when a STORED `screen` carries the age flag, else None (dev #716 /
    public #142; design §6.2). The flag is the age rule's two `review:age` outcomes for a recruiter
    role: `OVER-THRESHOLD` (older than `search.retained_search_age_days`) and an `UNKNOWN` age (the
    verdict then names `age` among its review rules, which a non-recruiter role's UNKNOWN never
    does). An unreadable threshold (`UNREADABLE-THRESHOLD`) is a config fault, not an age flag.
    Read from the stored screen, so the triage lean needs no profile, channel or date of its own."""
    if not isinstance(screen, dict):
        return None
    rules = screen.get("rules") if isinstance(screen.get("rules"), dict) else {}
    token = rules.get("age")
    verdict = screen.get("verdict")
    reviewed = (isinstance(verdict, str) and verdict.startswith("review:")
                and "age" in verdict[len("review:"):].split(","))
    if token == "OVER-THRESHOLD" and reviewed:
        return AGE_FIRST_MOVE_OVER
    if token == "UNKNOWN" and reviewed:
        return AGE_FIRST_MOVE_UNKNOWN
    return None


def _age_rule(opp, profile, channels, today):
    """`(token, text, review)` for the posting-age rule (dev #716 / public #142; design §6).

    The line always reports the age. Age NEVER changes the verdict except for a role from a
    recruiter channel: older than `search.retained_search_age_days` (default 35) it reads
    `OVER <n>d -- FIRST MOVE: ask the recruiter what stage the search is in, before research or
    letters` and adds `review:age`; an UNKNOWN age on a recruiter role says to ask when the
    search opened, also `review:age`. Never a removal."""
    import config_keys as _ck
    days, source, date = posting_age(opp, today)
    shown = "UNKNOWN" if days is None else "%dd (%s %s)" % (days, source, date)
    token = "UNKNOWN" if days is None else "OK"
    if not _from_recruiter(opp, channels):
        return token, shown, False
    try:
        limit = _ck.resolve_int(profile, _ck.SEARCH_RETAINED_SEARCH_AGE_DAYS)
    except ValueError as e:
        return "UNREADABLE-THRESHOLD", "%s -- %s" % (shown, e), True
    if days is None:
        return token, "UNKNOWN -- %s" % AGE_FIRST_MOVE_UNKNOWN, True
    if days > limit:
        return ("OVER-THRESHOLD",
                "%s OVER %dd -- FIRST MOVE: %s" % (shown, limit, AGE_FIRST_MOVE_OVER), True)
    return token, shown, False


def screen_rules(opp, profile, all_opps, applications=None, channels=None, today=None,
                 table=None):
    """The minimal screen as STRUCTURED rules: `{"rules", "detail", "verdict", "commute"}`.

    jobsearch 0.67.0 (R5, dev #713 / public #145): `record.py screened` stores what this returns,
    so a stored verdict is computed here, never transcribed by a model; `minimal_screen` below is
    only a printer over it. `rules` maps rule name -> a short token (comp: the screen_comp verdict;
    passed: MATCHES / NOT-EXCLUDED; geo: the geo_screen verdict; title: MATCHES / NO-MATCH /
    NO-CONFIGURED-TITLES; age: UNKNOWN / OK / OVER-THRESHOLD), `detail` the text each prints after
    its label, `verdict` `keep`, `remove:<rule>[,<rule>]` or `review:<rule>[,<rule>]`.

    Pure over what it is handed, and it never reads `posture`. Only rules that already remove a
    role can say `remove`: comp BELOW-FLOOR, geo `out`, a passed/excluded duplicate. A question the
    data cannot answer (a contested setting, an unknown commute, NOT-CAPTURED or PAY-UNCOMPARABLE
    pay, no geography section, a recruiter role's age) and the advisory title rule say `review`,
    never `remove` and never a quiet `keep`. UNDISCLOSED comp (recorded none-shown) is KEPT.

    jobsearch 0.70.0 (dev #729 / public #157): the geo rule can now say `outside-radius`, a REMOVAL
    -- an onsite role proven beyond every commute anchor that names no affirmative destination and
    is not kept by `geography.relocation.keep_outside_radius`. `commute` is the role's commute
    state (`commute_outcome`: inside, inside-radius, near, unresolvable, outside, or the hold
    `place-table` / `config`) for an onsite role, else None; the summary line counts it. It is not
    stored (`record.py screened` stores `rules` and `verdict`). `table` is a place table to use
    instead of the shipped one (tests inject a synthesized one)."""
    import geo_screen as _geo
    import pipeline_index as _pidx
    oid = opp.get("id")
    removes, reviews = [], []
    rules, detail = {}, {}

    # dev #728 / public #158 (design §5.6): one requisition listed at several places is screened at
    # its MOST FAVOURABLE place. The other places ride in `location.listed_at` (a transient key, never
    # stored), where `commute_outcome` and the geography rule read them.
    primary_text = ((opp.get("location") or {}).get("primary") or "") if isinstance(
        opp.get("location"), dict) else ""
    extra_places = [p for p in _pidx.listing_places(opp) if p != primary_text.strip()]
    if extra_places and isinstance(opp.get("location"), dict):
        opp = dict(opp, location=dict(opp["location"], listed_at=extra_places))

    verdict, text = screen_comp(opp, profile, table=table)
    rules["comp"], detail["comp"] = verdict, text
    # BELOW-FLOOR-ACCEPTED (dev #739) is neither list: the candidate's own decision keeps the role.
    # BELOW-ENGAGEMENT-FLOOR (dev #740) is a review and never a removal.
    if verdict == BELOW:
        removes.append("comp")
    elif verdict in (NEEDS_COMMUTE, UNRESOLVED, NOT_CAPTURED, PAY_UNCOMPARABLE, BELOW_ENGAGEMENT):
        reviews.append("comp")

    others = [o for o in all_opps if o.get("id") != oid]
    hit = _pidx.find_excluded_match(
        others, company_id=opp.get("company_id"), title=opp.get("title"),
        jd_url=opp.get("jd_url"), applications=applications or [])
    if hit:
        row, basis = hit
        rules["passed"] = "MATCHES"
        detail["passed"] = "MATCHES %s (%s) on %s" % (row.get("id"), row.get("status"), basis)
        removes.append("passed")
    else:
        rules["passed"], detail["passed"] = "NOT-EXCLUDED", "NOT EXCLUDED"

    # dev #728 / public #158 (design §5.4, LS-C2): a row that is another listing of an EARLIER, live,
    # unfolded row (same company + title, not vetoed) is a DUPLICATE: the screen says so, names the
    # one-verb fold, and its VERDICT is the canonical row's own, inherited. The canonical row is the
    # earliest of its group, so it has no earlier sibling and asking for its verdict cannot recurse.
    inherited = None
    if not hit:
        canonical = _pidx.earlier_sibling(opp, all_opps)
        if canonical is not None:
            canon_screen = screen_rules(canonical, profile, all_opps, applications, channels, today,
                                        table)
            inherited = canon_screen["verdict"]
            rules["passed"] = "DUPLICATE"
            detail["passed"] = ("DUPLICATE of %s on company + title; its verdict: %s; fold with "
                                "record.py link-sibling %s --into %s"
                                % (canonical.get("id"), inherited, oid, canonical.get("id")))

    loc = opp.get("location") or {}
    ltype = loc.get("type")
    # The stated type goes to the geography rule as given, so a `relocation` or `unresolved` role is
    # never taken for an onsite one (the CLI infers onsite only from a bare place, R6); a role with
    # NO type is the CLI's own case, and gets the same inference.
    gverdict, gline, _d = _geo.screen(loc.get("primary") or "", profile,
                                      work_type=ltype if ltype in (
                                          "remote", "hybrid", "onsite", "relocation",
                                          "unresolved") else None,
                                      table=table, loc_obj=loc)
    inferred = is_inferred(loc)
    typeless = "type" not in loc and loc.get("declared") == "none stated"
    if inferred:
        gline += INFERRED_NOTE
    if typeless and gverdict == _geo.OUT:
        # LS-B3: no setting and no place -- the geography rule has nothing to judge, so a text it
        # cannot read must not become a removal. Kept for review, the way the comp rule keeps it.
        gline += " -- no setting and no place were stated: kept for review, not removed"
        reviews.append("geo")
    rules["geo"], detail["geo"] = gverdict, gline
    if gverdict in (_geo.OUT, _geo.OUTSIDE_RADIUS) and not typeless:
        removes.append("geo")
    elif gverdict == _geo.UNKNOWN:
        reviews.append("geo")

    token, text, review = _title_rule(opp, profile)
    rules["title"], detail["title"] = token, text
    if review:
        reviews.append("title")

    token, text, review = _age_rule(opp, profile, channels, today)
    rules["age"], detail["age"] = token, text
    if review:
        reviews.append("age")

    if inherited is not None:
        v = inherited
    elif removes:
        v = "remove:" + ",".join(removes)
    elif reviews:
        v = "review:" + ",".join(reviews)
    else:
        v = "keep"
    commute = None
    if ltype == "onsite":
        oc = commute_outcome(loc, profile, table)
        commute = oc["hold"] or oc["state"]
    return {"rules": rules, "detail": detail, "verdict": v, "commute": commute,
            "setting_source": "inferred" if inferred else None,
            "engagement_source": "inferred" if engagement(opp)[1] == "inferred" else None}


def _screen_block(opp, r):
    d = r["detail"]
    return ["MINIMAL SCREEN %s" % opp.get("id"),
            "  comp:      %s  %s" % (r["rules"]["comp"], d["comp"]),
            "  passed:    %s" % d["passed"],
            "  geo:       %s" % d["geo"],
            "  title:     %s" % d["title"],
            "  age:       %s" % d["age"],
            "VERDICT %s" % r["verdict"]]


def minimal_screen(opp, profile, all_opps, applications=None, channels=None, today=None,
                   table=None):
    """dev #692 / public #140 -- the scripted screen every captured role gets under EVERY posture.
    Returns `(lines, verdict)`: the printable block (the header, then SIX rule lines -- comp,
    passed, geo, title, age, VERDICT -- and nothing else) and the VERDICT string `keep`,
    `remove:<rule>[,<rule>]` or `review:<rule>[,<rule>]`.

    A thin printer over `screen_rules` (R5): the rules, the verdict and the text of each line are
    computed there. `age` joined the block in 0.67.0 (dev #716 / public #142); before that it was
    header, four rules and the VERDICT. Pure over what it is handed, and it never reads `posture`
    (the point of the criterion)."""
    r = screen_rules(opp, profile, all_opps, applications, channels, today, table)
    return _screen_block(opp, r), r["verdict"]


# dev #729 / public #157 -- the run-level lines. `--minimal-screen` over several ids and
# `--screen-all` end with the commute split, so "75 screened, 0 removed" can never again be a number
# nobody can read behind: a far role is `outside`, one that needs a commute estimate is `near`, a
# text the table does not know is `unresolvable`, and a table that could not be read at all is its
# OWN count and its own line (it is never folded into `unresolvable`).
COMMUTE_COUNT_KEYS = ("outside", "near", "unresolvable", "place-table", "config")


def commute_counts(states):
    """`{outside, near, unresolvable, place-table, config}` counts over commute states (None, and
    the inside states, are not counted: they raise no question)."""
    counts = {k: 0 for k in COMMUTE_COUNT_KEYS}
    for st in states:
        if st in counts:
            counts[st] += 1
    return counts


def commute_text(counts):
    parts = ["outside %d" % counts["outside"], "near %d" % counts["near"],
             "unresolvable %d" % counts["unresolvable"]]
    if counts["place-table"]:
        parts.append("place table missing %d" % counts["place-table"])
    if counts["config"]:
        parts.append("anchor config unreadable %d" % counts["config"])
    return "commute: " + ", ".join(parts)


def place_table_missing_line():
    return "PLACE TABLE MISSING (%s): distance not checked" % _places.table_path()


def screen_summary(results):
    """The ONE summary line over several `screen_rules` results, then the PLACE TABLE MISSING line
    once when any role could not be measured: `MINIMAL SCREEN SUMMARY n screened · keep k · remove r
    (geo g, comp c, passed p) · review v · commute: outside o, near m, unresolvable u`."""
    n = len(results)
    keep = sum(1 for r in results if r["verdict"] == "keep")
    removed = [r for r in results if r["verdict"].startswith("remove:")]
    review = sum(1 for r in results if r["verdict"].startswith("review:"))
    by = {rule: sum(1 for r in removed if rule in r["verdict"][len("remove:"):].split(","))
          for rule in ("geo", "comp", "passed")}
    counts = commute_counts(r.get("commute") for r in results)
    lines = ["MINIMAL SCREEN SUMMARY %d screened · keep %d · remove %d (geo %d, comp %d, passed %d)"
             " · review %d · %s" % (n, keep, len(removed), by["geo"], by["comp"], by["passed"],
                                    review, commute_text(counts))]
    if counts["place-table"]:
        lines.append(place_table_missing_line())
    return lines


def _squash(text):
    """Lower-cased, whitespace-collapsed -- the one normalisation a phrase match compares in."""
    return " ".join(str(text or "").lower().split())


def _contains_phrase(haystack, phrase):
    """Whole-phrase containment on `_squash`ed text: the phrase must start and end on a word
    boundary, so 'sales' matches 'head of sales' and not 'wholesales'. A PHRASE, never a
    pattern -- nothing here compiles user text."""
    h, p = _squash(haystack), _squash(phrase)
    if not p:
        return False
    start = h.find(p)
    while start != -1:
        before_ok = start == 0 or not (h[start - 1].isalnum() or h[start - 1] == "_")
        end = start + len(p)
        after_ok = end == len(h) or not (h[end].isalnum() or h[end] == "_")
        if before_ok and after_ok:
            return True
        start = h.find(p, start + 1)
    return False


def match_signals(opp, company, jd_text, signals):
    """The likely-pass signals a role matches, for the LEAN on its Decide card (dev #713 / public
    #145 T2; design §7.2). Returns `[{"id", "reason", "matched_in"}]` in the order the signals are
    declared; `matched_in` is the first of the signal's own `fields` that matched.

    A case-insensitive WHOLE-PHRASE match of each `phrase` against the fields it names: `title`
    (the opportunity's), `jd` (the text the run read, passed in), `company` (the companies row's
    `name`, `vertical`, `size`, `hq`, `note`). Phrases, not regular expressions (OURS: a
    user-authored pattern is a parse-refusal surface and a backtracking risk). A match NEVER
    removes a role and never touches the screen verdict -- it is a reason to look.

    `signals` that fail `config_keys.validate_likely_pass_signals` raise `ValueError` listing the
    problems: an unreadable list is loud, never an empty one."""
    import config_keys as _ck
    problems = _ck.validate_likely_pass_signals(signals)
    if problems:
        raise ValueError("screen.likely_pass_signals cannot be read: %s" % "; ".join(problems))
    fields = {
        "title": opp.get("title") or "",
        "jd": jd_text or "",
        "company": " ".join(str(company.get(k)) for k in ("name", "vertical", "size", "hq", "note")
                            if isinstance(company, dict) and company.get(k)) if company else "",
    }
    hits = []
    for s in signals or []:
        for f in s["fields"]:
            if _contains_phrase(fields.get(f, ""), s["phrase"]):
                hits.append({"id": s["id"], "reason": s["reason"], "matched_in": f})
                break
    return hits


def print_options(cfg):
    """States & Views V1 §15.7 — 'options should be visible in the configuration.' The whole
    adjustable surface, read from `config_keys.py` (the ONE registry `doctor.py`'s CONFIG
    CURRENCY also reads — see that module's own check — so the two can never enumerate two
    different key lists), then the FIXED-by-the-engine block for the rest of "what else could
    I adjust". Never a second, hand-typed list."""
    import config_keys as _ck
    print("CONFIGURABLE — in config.json, with a default the engine falls back to")
    for key in sorted(_ck.READER_KEYS):
        value, provenance = _ck.describe(cfg, key)
        default, kind, bounds, why = _ck.metadata(key)
        legal = ("%d–%d" % bounds) if kind == "int" else "{%s}" % ", ".join(bounds)
        print("  %-40s %-24r %s" % (key, value, provenance))
        print("  %-40s default %r · legal %s" % ("", default, legal))
        print("  %-40s %s" % ("", why))
    print("\nFIXED BY THE ENGINE — a change here is a report, not a setting")
    for name, value in sorted(_ck.FIXED.items()):
        print("  %-40s %r" % (name, value))
    # dev #729 / public #157: what "far" means for THIS profile, so the answer to "why was nothing
    # (or everything) removed as outside-radius" is printed, not inferred.
    print("\nCOMMUTE DISTANCE — a role is outside-radius only when it is beyond EVERY anchor's bound")
    anchors = _commute_anchors(cfg)
    bounded = 0
    for a in anchors:
        bound, how = _ck.outer_bound_miles(a)
        problems = _ck.validate_anchor_geo(a)
        bounded += bound is not None
        shown = ("%d mi (%s)" % (round(bound), how)) if bound is not None else "no bound (%s)" % how
        print("  %-40s %s%s" % (a.get("place"), shown,
                                "  UNREADABLE: " + "; ".join(problems) if problems else ""))
    if not anchors or not bounded:
        print("  no anchor contributes a bound: every parsed place is `near` and none is ever "
              "removed as outside-radius. Set geography.commute_anchors[].max_commute_minutes or "
              "radius_miles.")
    print("  place table: %s (%s)" % (_places.table_path(),
          "present" if os.path.isfile(_places.table_path()) else "MISSING -- distance is not checked"))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Profile loader + executable comp screen.")
    ap.add_argument("--screen", metavar="OPP_ID")
    ap.add_argument("--screen-all", action="store_true")
    ap.add_argument("--title-scope-count", dest="title_scope_count", action="store_true",
                    help="dev #722 / public #156 (R2): print `undecided: N, flagged below floor: "
                         "F, off-mandate: M, re-screen pending: P` over the undecided backlog "
                         "under today's screen.title_floor / title-field likely_pass_signals. "
                         "Read-only; the measure to take before and after the keys are set.")
    ap.add_argument("--comp-scope-count", dest="comp_scope_count", action="store_true",
                    help="dev #739 / #740 (jobsearch 0.73.0, R2): print `stored screens: N, comp "
                         "re-screen pending: P` over every role carrying a stored screen -- the "
                         "ones whose stored comp verdict was computed without the engagement and "
                         "decision inputs 0.73.0 reads. Read-only; the measure to take before and "
                         "after the re-screens drain.")
    ap.add_argument("--minimal-screen", dest="minimal_screen", metavar="OPP_ID", nargs="+",
                    help="dev #692 / public #140: the scripted screen every captured role gets "
                         "under EVERY posture (comp floor, passed/duplicate, geography, advisory "
                         "title). Read-only, zero tokens, never reads "
                         "posture. Exit 0 on any verdict, 2 if an opportunity does not exist. "
                         "Several ids (dev #729 / public #157) print each block and then ONE "
                         "summary line: screened, keep, remove (by rule), review, and the commute "
                         "split (outside, near, unresolvable).")
    ap.add_argument("--options", action="store_true",
                    help="print the whole adjustable config surface, with defaults and "
                         "provenance (design-states-and-views.md §15.7)")
    args = ap.parse_args()

    profile = load()

    if args.options:
        # `profile` (load()'s merge of config()+user()) still carries every config.json
        # top-level section unchanged — config_keys.describe()'s dotted lookups (ats.*,
        # communications.*) read exactly the same tree either way, without a third read.
        return print_options(profile)

    if args.title_scope_count:
        c = title_scope_count(_load_opps(), profile)
        print("undecided: %d, flagged below floor: %d, off-mandate: %d, re-screen pending: %d"
              % (c["undecided"], c["below_floor"], c["off_mandate"], c["rescreen_pending"]))
        return 0

    if args.comp_scope_count:
        c = comp_scope_count(_load_opps(), profile)
        print("stored screens: %d, comp re-screen pending: %d" % (c["screened"], c["rescreen_pending"]))
        return 0

    if args.minimal_screen:
        all_opps = _load_opps()
        apps, chans = _load_optional("applications.jsonl"), _load_optional("channels.jsonl")
        results, missing = [], False
        for oid in args.minimal_screen:
            opp = next((o for o in all_opps if o.get("id") == oid), None)
            if opp is None:
                print("No opportunity with id %r" % oid)
                missing = True
                continue
            r = screen_rules(opp, profile, all_opps, applications=apps, channels=chans)
            results.append(r)
            print("\n".join(_screen_block(opp, r)))
        if len(args.minimal_screen) > 1 and results:
            print("\n".join(screen_summary(results)))
        elif results and results[0].get("commute") == "place-table":
            print(place_table_missing_line())
        return 2 if missing else 0

    if args.screen or args.screen_all:
        all_opps = _load_opps()
        excluded_counts = {}
        if args.screen:
            opps = [o for o in all_opps if o["id"] == args.screen]
            if not opps:
                print("No opportunity with id %r" % args.screen)
                return 1
        elif args.screen_all:
            screened = set(SCREEN_ALL_STATUSES)
            import pipeline_index as _pidx_f
            # dev #728 / public #158: a row folded into another (duplicate_of) is another listing of
            # a requisition already screened as the canonical row; it is counted, not screened twice.
            opps = [o for o in all_opps if o.get("status") in screened
                    and not _pidx_f.is_folded(o)]
            # ⭐ public #84 — COVERAGE, NOT SILENCE. Every status this run did NOT screen, and
            # how many rows sat in it, computed from what is actually on disk (never a
            # hardcoded enum that could itself drift from the data) — so an exclusion is a
            # printed fact, not a fact nobody stated.
            for o in all_opps:
                st = o.get("status")
                if _pidx_f.is_folded(o) and st in screened:
                    excluded_counts["folded (duplicate_of)"] = (
                        excluded_counts.get("folded (duplicate_of)", 0) + 1)
                elif st not in screened:
                    excluded_counts[st] = excluded_counts.get(st, 0) + 1

        print("Comp screen — %d opportunit%s" % (len(opps), "y" if len(opps) == 1 else "ies"))
        print("=" * 78)
        counts = {}
        commute_states = []
        for o in sorted(opps, key=lambda x: x["id"]):
            verdict, detail = screen_comp(o, profile)
            counts[verdict] = counts.get(verdict, 0) + 1
            print("  %-20s %s" % (verdict, o["id"][:52]))
            print("  %-20s %s" % ("", detail))
            oloc = o.get("location") or {}
            if oloc.get("type") == "onsite":
                oc = commute_outcome(oloc, profile)
                commute_states.append(oc["hold"] or oc["state"])
        print("\n" + "=" * 78)
        print("  " + " · ".join("%s=%d" % (k, v) for k, v in sorted(counts.items())))
        ccounts = commute_counts(commute_states)
        print("  " + commute_text(ccounts))
        inferred_n = sum(1 for o in opps if is_inferred(o))
        print("  onsite inferred (the posting stated no setting): %d" % inferred_n)
        engagement_n = sum(1 for o in opps if engagement(o)[1] == "inferred")
        print("  engagement inferred from the title: %d" % engagement_n)
        if ccounts["place-table"]:
            print("  " + place_table_missing_line())
        if args.screen_all:
            if excluded_counts:
                print("  NOT screened (status excluded from --screen-all): " +
                     " · ".join("%s=%d" % (k, v) for k, v in sorted(excluded_counts.items())))
            else:
                print("  NOT screened: none — every status present in the pipeline was covered.")
        print("\n  Reminder: BELOW-FLOOR is a REMOVE unless you accept the pay (record.py decide <id>")
        print("  pursue --why-kind comp-acceptable --why ...); BELOW-FLOOR-ACCEPTED is that")
        print("  acceptance, kept. BELOW-ENGAGEMENT-FLOOR: a non-employee rate below your")
        print("  compensation.non_employee floor in the same unit -- a review, never a removal.")
        print("  NEEDS-COMMUTE-CHECK is never 'relocation by default' — that assumption")
        print("  is what mis-scored <an employer> on 2026-07-22.")
        print("  UNRESOLVED-SETTING is a question FOR THE EMPLOYER, never a silent pick —")
        print("  the posting declared two settings, and the pick would select the comp floor.")
        print("  NOT-CAPTURED means nobody recorded this role's pay -- NOT that the listing showed")
        print("  none. PAY-UNCOMPARABLE means pay was recorded but cannot honestly be set against")
        print("  a floor (not annual, another currency, no compensation.currency set). Both are")
        print("  reviews, never removals.")
        return 0

    print("THREE-LAYER MODEL")
    print("  1. user.json    USER DATA      — who the candidate is")
    print("  2. config.json  CONFIGURATION  — how the search behaves")
    print("  3. engine       scripts/ .claude/agents/ CLAUDE.md tasks/ docs/")
    print()
    ident = profile["identity"]
    print("Profile: %s — %s" % (ident["full_name"], ident["city"]))
    print("  available: %s" % ident["availability"])
    print("  mailboxes: %s" % ", ".join(m["address"] for m in profile["mailboxes"]))
    # The titles themselves, not a count: inbox-scan and board-sweeper build their search
    # queries from this line. A count made agents fall back to whatever titles they assumed.
    print("  titles:    %s" % "; ".join(profile["targets"]["titles"]))
    print("             org-structure-is-a-filter = %s"
          % (profile["targets"]["org_structure_is_not_a_filter"] is False))
    print("\n  comp tiers (base/yr):")
    for t in profile["compensation"]["tiers"]:
        flag = "" if t.get("basis_confirmed", True) else "   ⚠️ basis UNCONFIRMED — ask the candidate"
        print("    %-14s %s%sK%s" % (t["setting"], currency_symbol(), t["floor"] // 1000, flag))
    cm = comms()
    print("\n  communications (config.json is the single source):")
    print("    default sequence : %s  (sent TOGETHER)" % " + ".join(cm["default_sequence"]))
    print("    last resort      : %s" % ", ".join(cm["last_resort"]))
    print("    every message    : %s" % " + ".join(cm["message_requirements"]))
    for med, con in cm["constraints_by_medium"].items():
        lim = ("%d chars" % con["max_chars"]) if "max_chars" in con else ("%d words" % con["max_words"])
        print("    %-26s %s" % (med, lim))

    print("\n  rendered signature (config template x user data):")
    for line in email_signature():
        print("    %s" % line)
    print("\n  mailboxes (user.json is THE source):  %s" % ", ".join(mailboxes()))
    print("\n  Screen the live pipeline:  python3 scripts/profile.py --screen-all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
