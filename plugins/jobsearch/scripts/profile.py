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
as data and `minimal_screen` prints it. There is no mandate rule (no script implements one and no config key names one),
so the screen prints no mandate line (owner, 2026-10-09: a line about a rule that does not exist
is noise on every role for every installer).

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_or_fixture as _profile_or_fixture

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


def effective_setting(location, profile, commute_ok=None):
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

    `commute_ok`: pass True/False if you already know. Otherwise it is inferred from
    the location string against profile geography anchors, and an unrecognized place
    returns None rather than guessing — the whole point is to stop silent guessing.
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
        commute_ok = within_commute(location, profile)
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


def _match_commute(location, profile):
    """`(anchor, matched_entry)` for the first commute anchor whose `place` or any `includes[]`
    name appears in the location text, else `(None, None)`. THE one text match: `within_commute`
    and the band resolver both read it, so they cannot disagree about which anchor a role is in."""
    hay = " ".join(str(location.get(k) or "") for k in ("primary", "note")).lower()
    if not hay.strip():
        return None, None
    for anchor in profile["geography"]["commute_anchors"]:
        entries = [anchor["place"]] + list(anchor.get("includes", []))
        for e in entries:
            n = _entry_name(e)
            if n is None:
                continue
            # match on the distinctive part ("<the commute anchor>", "<a nearby metro>", "<a nearby metro>")
            token = n.split(",")[0].strip().lower()
            if token and token in hay:
                return anchor, e
    return None, None


def within_commute(location, profile):
    """True / False / None(unknown). Text matching, deliberately conservative."""
    anchor, _entry = _match_commute(location, profile)
    if anchor is not None:
        return True
    return None  # unknown, NOT False — never infer "relocation" from silence


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


def resolve_floor(location, profile, commute_ok=None):
    """Which floor a location is screened against: `{setting, floor, band, hold, detail}`.

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
    """
    import config_keys as _ck
    out = {"setting": effective_setting(location, profile, commute_ok), "floor": None,
           "band": None, "hold": None, "detail": None}
    ltype = location.get("type") if isinstance(location, dict) else None
    if commute_ok is not None or ltype not in ("onsite", "hybrid"):
        return out
    anchor, entry = _match_commute(location, profile)
    if anchor is None:
        return out                      # hybrid: outside every anchor -> hybrid tier (today's)
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


def screen_comp(opp, profile, commute_ok=None):
    """Screen one opportunity's comp against the applicable tier.

    Returns (verdict, detail). Verdicts: CLEARS / BELOW-FLOOR / UNDISCLOSED /
    NEEDS-COMMUTE-CHECK / UNRESOLVED-SETTING.

    Screening is applied to the TOP of the stated band (profile's below_floor rule),
    and an undisclosed band is explicitly KEPT — comp is the first question to ask,
    so it cannot be screened on.
    """
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

    resolved = resolve_floor(loc, profile, commute_ok)
    setting = resolved["setting"]

    if resolved["hold"]:
        return NEEDS_COMMUTE, (
            "location.type=%r at %r — %s. Ask/check before applying any floor."
            % (loc.get("type"), loc.get("primary"), resolved["detail"]))

    if setting is None:
        return NEEDS_COMMUTE, (
            "location.type=%r at %r — cannot tell whether this is a commute or a MOVE. "
            "Ask/check before applying any floor. Never assume 'onsite' means relocation."
            % (loc.get("type"), loc.get("primary")))

    tier = tiers(profile)[setting]
    floor = resolved["floor"] if resolved["floor"] is not None else tier["floor"]
    label = setting
    if resolved["band"]:
        label = "%s band (%d min, within %d)" % (setting, resolved["band"]["minutes"],
                                                 resolved["band"]["max_minutes"])

    if comp and comp.get("max") is not None:
        pass                              # §5.2 step 1: the candidate's own figure screens, as before
    elif isinstance(opp.get("listed_pay"), dict):
        return _screen_listed_pay(opp["listed_pay"], opp, profile, label, floor)
    else:
        return NOT_CAPTURED, (
            "no pay was ever recorded for this role (no listed_pay, no comp figure) — that is NOT "
            "the same as the listing showing none. RE-READ THE LISTING before surfacing it. "
            "Applicable tier would be %s (floor $%sK base)." % (label, floor // 1000))

    top = comp["max"]
    basis = (comp.get("basis") or "base").lower()
    note = ""
    if basis != "base":
        note = (" ⚠️ band is stated as %r, but the floor is BASE — compare like with like "
                "before trusting this verdict." % basis)

    if top >= floor:
        return CLEARS, ("top of band $%sK >= %s floor $%sK.%s"
                        % (int(top) // 1000, label, floor // 1000, note))
    gap = floor - top
    return BELOW, (
        "top of band $%sK is $%sK BELOW the %s floor ($%sK). Profile says REMOVE unless "
        "the candidate explicitly opts in (standout-quality exception).%s"
        % (int(top) // 1000, int(gap) // 1000, label, floor // 1000, note))


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


def _label_matches(label, loc, profile):
    """True when a range's own `label` (the posting's verbatim name for a location-specific
    range) names the role's matched commute anchor or its `location.primary` (case-insensitive
    substring, design §5.3)."""
    if not isinstance(label, str) or not label.strip():
        return False
    lab = label.lower()
    names = []
    anchor, _e = _match_commute(loc, profile)
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


def _screen_listed_pay(lp, opp, profile, label, floor):
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
    selected = [r for r in ranges if _label_matches(r.get("label"), loc, profile)] or ranges
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
    return BELOW, (
        "employer-stated top %s (source %s) is $%sK BELOW the %s floor ($%sK). Profile says REMOVE "
        "unless the candidate explicitly opts in (record.py decide)."
        % (_range_text(best), lp.get("source") or "unrecorded", int(floor - reach(best)) // 1000,
           label, floor // 1000))


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


def _title_rule(opp, profile):
    """`(token, text, review)` for the advisory title rule: MATCHES / NO-MATCH /
    NO-CONFIGURED-TITLES. Only ever a `review`, never a removal."""
    import pipeline_index as _pidx
    configured = [t for t in ((profile.get("targets") or {}).get("titles") or []) if t]
    want = _pidx.normalize_title(opp.get("title"))
    matched = None
    if want:
        for t in configured:
            nt = _pidx.normalize_title(t)
            if nt and (" %s " % nt) in (" %s " % want):
                matched = t
                break
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


def screen_rules(opp, profile, all_opps, applications=None, channels=None, today=None):
    """The minimal screen as STRUCTURED rules: `{"rules", "detail", "verdict"}`.

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
    never `remove` and never a quiet `keep`. UNDISCLOSED comp (recorded none-shown) is KEPT."""
    import geo_screen as _geo
    import pipeline_index as _pidx
    oid = opp.get("id")
    removes, reviews = [], []
    rules, detail = {}, {}

    verdict, text = screen_comp(opp, profile)
    rules["comp"], detail["comp"] = verdict, text
    if verdict == BELOW:
        removes.append("comp")
    elif verdict in (NEEDS_COMMUTE, UNRESOLVED, NOT_CAPTURED, PAY_UNCOMPARABLE):
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

    loc = opp.get("location") or {}
    gverdict, gline, _d = _geo.screen(loc.get("primary") or "", profile,
                                      work_type=loc.get("type")
                                      if loc.get("type") in ("remote", "hybrid", "onsite") else None)
    rules["geo"], detail["geo"] = gverdict, gline
    if gverdict == _geo.OUT:
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

    if removes:
        v = "remove:" + ",".join(removes)
    elif reviews:
        v = "review:" + ",".join(reviews)
    else:
        v = "keep"
    return {"rules": rules, "detail": detail, "verdict": v}


def minimal_screen(opp, profile, all_opps, applications=None, channels=None, today=None):
    """dev #692 / public #140 -- the scripted screen every captured role gets under EVERY posture.
    Returns `(lines, verdict)`: the printable block (the header, then SIX rule lines -- comp,
    passed, geo, title, age, VERDICT -- and nothing else) and the VERDICT string `keep`,
    `remove:<rule>[,<rule>]` or `review:<rule>[,<rule>]`.

    A thin printer over `screen_rules` (R5): the rules, the verdict and the text of each line are
    computed there. `age` joined the block in 0.67.0 (dev #716 / public #142); before that it was
    header, four rules and the VERDICT. Pure over what it is handed, and it never reads `posture`
    (the point of the criterion)."""
    r = screen_rules(opp, profile, all_opps, applications, channels, today)
    d = r["detail"]
    lines = ["MINIMAL SCREEN %s" % opp.get("id"),
             "  comp:      %s  %s" % (r["rules"]["comp"], d["comp"]),
             "  passed:    %s" % d["passed"],
             "  geo:       %s" % d["geo"],
             "  title:     %s" % d["title"],
             "  age:       %s" % d["age"],
             "VERDICT %s" % r["verdict"]]
    return lines, r["verdict"]


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
    return 0


def main():
    ap = argparse.ArgumentParser(description="Profile loader + executable comp screen.")
    ap.add_argument("--screen", metavar="OPP_ID")
    ap.add_argument("--screen-all", action="store_true")
    ap.add_argument("--minimal-screen", dest="minimal_screen", metavar="OPP_ID",
                    help="dev #692 / public #140: the scripted screen every captured role gets "
                         "under EVERY posture (comp floor, passed/duplicate, geography, advisory "
                         "title). Read-only, zero tokens, never reads "
                         "posture. Exit 0 on any verdict, 2 if the opportunity does not exist.")
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

    if args.minimal_screen:
        all_opps = _load_opps()
        opp = next((o for o in all_opps if o.get("id") == args.minimal_screen), None)
        if opp is None:
            print("No opportunity with id %r" % args.minimal_screen)
            return 2
        out, _verdict = minimal_screen(opp, profile, all_opps,
                                       applications=_load_optional("applications.jsonl"),
                                       channels=_load_optional("channels.jsonl"))
        print("\n".join(out))
        return 0

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
            opps = [o for o in all_opps if o.get("status") in screened]
            # ⭐ public #84 — COVERAGE, NOT SILENCE. Every status this run did NOT screen, and
            # how many rows sat in it, computed from what is actually on disk (never a
            # hardcoded enum that could itself drift from the data) — so an exclusion is a
            # printed fact, not a fact nobody stated.
            for o in all_opps:
                st = o.get("status")
                if st not in screened:
                    excluded_counts[st] = excluded_counts.get(st, 0) + 1

        print("Comp screen — %d opportunit%s" % (len(opps), "y" if len(opps) == 1 else "ies"))
        print("=" * 78)
        counts = {}
        for o in sorted(opps, key=lambda x: x["id"]):
            verdict, detail = screen_comp(o, profile)
            counts[verdict] = counts.get(verdict, 0) + 1
            print("  %-20s %s" % (verdict, o["id"][:52]))
            print("  %-20s %s" % ("", detail))
        print("\n" + "=" * 78)
        print("  " + " · ".join("%s=%d" % (k, v) for k, v in sorted(counts.items())))
        if args.screen_all:
            if excluded_counts:
                print("  NOT screened (status excluded from --screen-all): " +
                     " · ".join("%s=%d" % (k, v) for k, v in sorted(excluded_counts.items())))
            else:
                print("  NOT screened: none — every status present in the pipeline was covered.")
        print("\n  Reminder: BELOW-FLOOR is a REMOVE unless the candidate explicitly opts in.")
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
