#!/usr/bin/env python3
"""Screen ONE location against the candidate's own geography config — a query, not a memory.

WHY THIS EXISTS (public #89, dev #355)
---------------------------------------
The daily run's digest-triage step dismissed a whole board digest on the stated reasoning that
its metro "was not a relocation destination" — while that exact metro had been added to
`config.json.geography.relocation.affirmative_destinations` days earlier. The triage step never
ran a query; it answered from memory, the same defect class `alert_sweep.py` already exists to
prevent for "did we see this digest" (CLAUDE.md: "a daily, predictable artifact is a query, not
a summary"), one level over — a geography VERDICT is exactly as deterministic as a digest scan,
and was being produced by a model guessing instead.

Investigating why turned up dev #355: `init_profile.py` scaffolds
`geography.relocation_open_to` / `geography.radius_minutes`, but every profile actually derived
from a resume carries `geography.relocation.{open, affirmative_destinations}` and
`geography.commute_anchors[].max_commute_minutes` instead — TWO SPELLINGS of one meaning, the
`_ats_keys.py` defect one config section over. No shipped script read the live names at all, so
there was nothing FOR the triage step to consult even if it had tried. `m_0_50_0_geography_keys`
(migrate.py) rewrites a profile still carrying the old names; `config_keys.py` now registers the
live ones ONCE, so `profile.py --options`, `--list` below, and this screen's own reads cannot
drift into three different spellings again.

## THE CONTRACT — seven verdicts, EACH CITING THE CONFIG KEY IT CAME FROM

    remote          the posting is remote (--type remote, or "remote" in the location text) —
                    cites `geography.remote_ok`
    commute         the location names one of `geography.commute_anchors[]` (matched the same
                    conservative, text-based way `profile.within_commute()` already does — a
                    posting whose location NAMES the anchor's place is treated as within it) —
                    cites that anchor's own `max_commute_minutes`
    affirmative     the location names one of `geography.relocation.affirmative_destinations` —
                    cites that key (public #89's own list)
    relocation-ok   not a commute anchor, not an affirmative destination, but
                    `geography.relocation.open` is true — cites that key. Also: an onsite role
                    PROVEN far (see `outside-radius`) that `geography.relocation.keep_outside_radius`
                    keeps — cites that key
    outside-radius  an ONSITE role whose place resolves, through the shipped place table, to a
                    distance no commute from ANY anchor can cover (`profile.commute_outcome`, state
                    `outside`), that names no affirmative destination, while
                    `geography.relocation.open` is true and
                    `geography.relocation.keep_outside_radius` is false. A DISMISSAL, like `out`
                    (jobsearch 0.70.0, dev #729 / public #157: until then a role in a city nobody
                    had named could never be called far, and a profile that screened 75 roles
                    removed none). Cites `geography.relocation.keep_outside_radius`.
    out             `geography.relocation.open` is false (whether set or the registered
                    default) and nothing above matched — cites that key. A far onsite role is `out`
                    too when relocation is closed (the closed key outranks the opt-in). NEVER printed from
                    silence: this is the one verdict that ends a role's consideration, so it is
                    reached only through an explicit or DEFAULT-BUT-REGISTERED key, never
                    because something could not be read.
    unknown         `config.json` has no `geography` section AT ALL (not merely an unset key —
                    a registered key always has a default; a MISSING SECTION does not). Exits
                    non-zero and is never silently read as "out" — `profile.py`'s own rule for
                    a key it cannot find ("never infer relocation from silence") applied here to
                    the whole section.

⭐ ONE RULE, TWO ENTRY POINTS (dev #729 / public #157, design R6). This CLI with no `--type` and
`profile.screen_rules` apply the SAME inference: a concrete place the place table can read (`City,
ST`), with no `remote` or `hybrid` token, is screened as ONSITE -- the way the daily run's digest
triage meets a bare location -- so it can print `outside-radius`; both entry points read
`profile.commute_outcome`, and `test_binding.TestGeoScreenVerdicts` runs both on the same places. A
role the profile types `relocation` or `unresolved` is never inferred onsite.

Usage:
    python3 scripts/geo_screen.py "Austin, TX"                    # screen one location
    python3 scripts/geo_screen.py "Remote - USA" --type remote    # explicit posting type
    python3 scripts/geo_screen.py "Denver, CO" --json             # machine-readable
    python3 scripts/geo_screen.py --list                          # the config keys this reads —
                                                                   # same set `profile.py
                                                                   # --options` prints

⭐ THE FIRST PRINTED LINE (human mode) / the `"line"` field (--json) IS THE CITABLE VERDICT — a
geography dismissal in a skill or agent file must quote it verbatim, never paraphrase the
reasoning from memory (the daily-run SKILL.md and board-sweeper.md rule this script exists to
let them keep).

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import config_keys as _ck
import places as _places
import profile as _profile

REMOTE = "remote"
COMMUTE = "commute"
AFFIRMATIVE = "affirmative"
RELOCATION_OK = "relocation-ok"
OUTSIDE_RADIUS = "outside-radius"
OUT = "out"
UNKNOWN = "unknown"


def _token(name):
    """The distinctive part of a place name — text before the first comma, lowercased. The
    exact matching convention `profile.within_commute()` already uses; kept identical rather
    than reinvented so a location that matches one matches the other."""
    return str(name or "").split(",")[0].strip().lower()


def _match_anchor(location_lower, anchors):
    """(index, anchor_dict, matched_name) for the first `geography.commute_anchors[]` entry
    whose `place` or any `includes[]` name appears in the location text, or (None, None, None).
    A non-dict entry is skipped, never crashed on — a malformed anchor is a data problem for
    `validate_data.py`/a migration, not a reason for this screen to raise."""
    for i, anchor in enumerate(anchors or ()):
        if not isinstance(anchor, dict):
            continue
        # jobsearch 0.67.0 (dev #714, design §3.8): an `includes[]` entry is a string (today) or a
        # `{place, minutes}` object whose `place` is the name -- matched exactly as a string is.
        names = [anchor.get("place")] + [e.get("place") if isinstance(e, dict) else e
                                         for e in (anchor.get("includes") or [])]
        for n in names:
            token = _token(n)
            if token and token in location_lower:
                return i, anchor, n
    return None, None, None


def _match_destination(location_lower, destinations):
    """(index, matched_name) for the first `geography.relocation.affirmative_destinations[]`
    entry the location text names, or (None, None). Same conservative text match as anchors —
    a destination list is exactly as free-form as a commute anchor's `place`/`includes`."""
    for i, dest in enumerate(destinations or ()):
        token = _token(dest)
        if token and token in location_lower:
            return i, dest
    return None, None


def screen(location, cfg, work_type=None, table=None, loc_obj=None):
    """(verdict, line, detail_dict) -- see `_screen`. A role LISTED AT SEVERAL PLACES (`loc_obj` carries
    `listed_at`, the places beyond `location.primary`; dev #728 / public #158, design §5.6) is judged
    at its MOST FAVOURABLE place: the text paths read every place (the location text becomes
    `"<primary> ; <other> ; ..."`), the distance path asks `profile.commute_outcome`, which takes the
    most favourable listing. The geo order is remote > commute > affirmative > relocation-ok >
    outside-radius > out. The line names the listing that decided it when the role has several."""
    extra = [t for t in ((loc_obj or {}).get("listed_at") or []) if isinstance(t, str) and t.strip()]
    joined = " ; ".join([str(location or "")] + extra) if extra else location
    verdict, line, detail = _screen(joined, cfg, work_type, table, loc_obj)
    if extra and verdict in (COMMUTE, OUTSIDE_RADIUS, RELOCATION_OK, OUT, AFFIRMATIVE):
        onsite = work_type == "onsite" or (work_type is None
                                           and _places.parse_place(joined) is not None)
        if onsite and isinstance(cfg.get("geography"), dict):
            place = _profile.commute_outcome(loc_obj, cfg, table)["place"]
            if place:
                line += " [decided by the listing at %s]" % place
                detail = dict(detail, listing=place)
    return verdict, line, detail


def _screen(location, cfg, work_type=None, table=None, loc_obj=None):
    """(verdict, line, detail_dict) for ONE location against a loaded config.json `cfg`.

    `line` is the single citable sentence — see the module docstring's ⭐ note. `detail_dict`
    carries the structured citation (`key`, `value`, `provenance`) plus whatever else is useful
    to a caller that wants more than the one line (the --json surface below).

    `work_type` is the posting's own stated arrangement. `onsite` screens the place through
    `profile.commute_outcome` (the one resolver, so this rule and the comp rule cannot disagree);
    `None` INFERS onsite from a concrete parseable place with no remote or hybrid token (R6);
    `hybrid`, `relocation` and `unresolved` keep the text-only logic below. `loc_obj` is the role's
    whole `location` object when the caller has it (its `note` and `commute_minutes` are read by
    the same resolver); `table` is a place table to use instead of the shipped one."""
    geo = cfg.get("geography")
    if not isinstance(geo, dict):
        return (UNKNOWN,
                "unknown: %r — config.json has no \"geography\" section at all (never read as "
                "out; this is a MISSING SECTION, not an unset key with a default)." % location,
                {"key": None, "value": None, "provenance": "geography section absent"})

    loc_lower = str(location or "").lower()
    is_remote = (work_type == "remote") or ("remote" in loc_lower)

    if is_remote:
        value, provenance = _ck.describe(cfg, _ck.GEOGRAPHY_REMOTE_OK)
        key = _ck.GEOGRAPHY_REMOTE_OK
        if value:
            return (REMOTE,
                    "remote: %r — %s=%r (%s)." % (location, key, value, provenance),
                    {"key": key, "value": value, "provenance": provenance})
        return (OUT,
                "out: %r — %s=%r (%s): remote work is not screened in." % (location, key, value, provenance),
                {"key": key, "value": value, "provenance": provenance})

    anchors, anchors_prov = _ck.describe(cfg, _ck.GEOGRAPHY_COMMUTE_ANCHORS)
    onsite = work_type == "onsite" or (work_type is None and _places.parse_place(location) is not None)
    outcome = None
    if onsite:
        # jobsearch 0.70.0 (dev #729 / public #157): the ONE resolver, not a second text matcher.
        outcome = _profile.commute_outcome(loc_obj if isinstance(loc_obj, dict) and loc_obj
                                           else {"primary": location}, cfg, table)
        anchor = outcome["anchor"] if outcome["state"] in ("inside", "inside-radius") else None
        idx = next((i for i, a in enumerate(anchors or ()) if a is anchor), None)
        matched_name = _profile._entry_name(outcome["entry"]) if anchor is not None else None
    else:
        idx, anchor, matched_name = _match_anchor(loc_lower, anchors)
    if anchor is not None and outcome is not None and outcome["state"] == "inside-radius":
        key = "%s[%d].radius_miles" % (_ck.GEOGRAPHY_COMMUTE_ANCHORS, idx)
        return (COMMUTE,
                "commute: %r — %s=%r (~%d mi from anchor %r, within its radius)."
                % (location, key, anchor.get("radius_miles"), round(outcome["miles"]),
                   anchor.get("place")),
                {"key": key, "value": anchor.get("radius_miles"), "provenance": anchors_prov,
                 "anchor": anchor.get("place"), "miles": outcome["miles"]})
    if anchor is not None:
        minutes = anchor.get("max_commute_minutes")
        key = "%s[%d].max_commute_minutes" % (_ck.GEOGRAPHY_COMMUTE_ANCHORS, idx)
        return (COMMUTE,
                "commute: %r — %s=%r (matched anchor %r via %r)."
                % (location, key, minutes, anchor.get("place"), matched_name),
                {"key": key, "value": minutes, "provenance": anchors_prov,
                 "anchor": anchor.get("place")})

    destinations, dest_prov = _ck.describe(cfg, _ck.GEOGRAPHY_AFFIRMATIVE_DESTINATIONS)
    didx, matched_dest = _match_destination(loc_lower, destinations)
    if matched_dest is not None:
        key = _ck.GEOGRAPHY_AFFIRMATIVE_DESTINATIONS
        return (AFFIRMATIVE,
                "affirmative: %r — %s includes %r (%s)."
                % (location, key, matched_dest, dest_prov),
                {"key": key, "value": matched_dest, "provenance": dest_prov})

    value, provenance = _ck.describe(cfg, _ck.GEOGRAPHY_RELOCATION_OPEN)
    key = _ck.GEOGRAPHY_RELOCATION_OPEN
    if value and outcome is not None and outcome["state"] == "outside":
        # A role PROVEN far (design §3.2). `relocation.open` is true, so the old answer was to keep
        # it; the owner's decision of 2026-10-19 is that open alone does not keep a role nobody
        # named, and the opt-in is its own key. Every line below names that key.
        keep_key = _ck.GEOGRAPHY_KEEP_OUTSIDE_RADIUS
        keep, keep_prov = _ck.describe(cfg, keep_key)
        cite = {"key": keep_key, "value": keep, "provenance": keep_prov,
                "anchor": outcome["anchor"].get("place"), "miles": outcome["miles"],
                "bound": outcome["bound"]}
        far = "~%d mi from %s (beyond %d mi)" % (round(outcome["miles"]),
                                                 outcome["anchor"].get("place"), round(outcome["bound"]))
        if keep is True:
            return (RELOCATION_OK,
                    "relocation-ok: %r — %s=%r (%s): %s, but outside-radius roles are kept."
                    % (location, keep_key, keep, keep_prov, far), cite)
        return (OUTSIDE_RADIUS,
                "outside-radius: %r — %s, farther than any commute from it can reach; not a "
                "commute anchor, not an affirmative destination. Keep it with %s=true (now %r, %s)."
                % (location, far, keep_key, keep, keep_prov), cite)
    if value:
        return (RELOCATION_OK,
                "relocation-ok: %r — %s=%r (%s): not a commute anchor, not an affirmative "
                "destination, but relocation is open." % (location, key, value, provenance),
                {"key": key, "value": value, "provenance": provenance})
    return (OUT,
            "out: %r — %s=%r (%s): not a commute anchor, not an affirmative destination, and "
            "relocation is not open." % (location, key, value, provenance),
            {"key": key, "value": value, "provenance": provenance})


def _geography_keys():
    """The `geography.*` slice of `config_keys.READER_KEYS` — deliberately the SAME registry
    `profile.py --options` iterates in full, never a second hand-typed list, so the two
    surfaces cannot name two different key sets (design-states-and-views.md §15.7's own gate,
    applied here)."""
    return sorted(k for k in _ck.READER_KEYS if k.startswith("geography."))


def cmd_list(cfg):
    print("GEOGRAPHY CONFIG KEYS — the same registry `profile.py --options` reads in full")
    print("=" * 78)
    for key in _geography_keys():
        value, provenance = _ck.describe(cfg, key)
        default, kind, bounds, why = _ck.metadata(key)
        print("  %-46s %r  (%s)" % (key, value, provenance))
        print("  %-46s default %r · kind %s" % ("", default, kind))
        print("  %-46s %s" % ("", why))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("location", nargs="?",
                    help="the posting's location text, verbatim (e.g. 'Austin, TX', 'Remote - USA')")
    ap.add_argument("--type", choices=["remote", "hybrid", "onsite"],
                    help="the posting's OWN stated work arrangement, when known — 'remote' short-"
                         "circuits location matching entirely; omit to infer remote only from "
                         "the location text itself")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--list", action="store_true",
                    help="print the geography.* config keys this screen reads, with current "
                         "value/provenance and default — never a location screen")
    args = ap.parse_args()

    cfg = _profile.config()

    if args.list:
        return cmd_list(cfg)

    if not args.location:
        ap.error("a location is required unless --list is given")

    verdict, line, detail = screen(args.location, cfg, work_type=args.type)

    if args.json:
        print(json.dumps({"location": args.location, "type": args.type, "verdict": verdict,
                          "line": line, "cites": detail}, indent=2))
    else:
        print(line)

    return 2 if verdict == UNKNOWN else 0


if __name__ == "__main__":
    sys.exit(main())
