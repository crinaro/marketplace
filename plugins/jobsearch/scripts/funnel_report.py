#!/usr/bin/env python3
"""What's actually working: channel yield, application outcomes, outreach reply rates.

WHY THIS EXISTS (2026-07-21)
----------------------------
The candidate: "We should be tracking who we connected with & when i applied to analyze
what works and what doesnt."

Two things were in the way, both fixed the same day:

  1. Applications were stuffed into `outreach[]` with a person-shaped `to` field
     reading "<a recognizable employer> careers (direct ATS application)". Counting applications meant
     string-matching a free-text name, and an ATS submission looked identical to a
     networking note. They are different funnels -- an application's measure is
     "did anyone respond", outreach's is "did they reply" -- so they now live in
     separate arrays.
  2. `contacts[]` had been backfilled from markdown prose, so ~33 of its entries
     were placeholders ("N/A -- not pursued", "None found", "Not yet checked")
     sitting in the `name` field, every one typed `path_type: recruiter`. Averages
     over that are worse than no number at all.

This reads data/opportunities.jsonl and reports only what the data can actually
support. Where the sample is too small to mean anything, it says so rather than
printing a confident percentage over n=3.

    python3 scripts/funnel_report.py [--recommend]
    python3 scripts/funnel_report.py --by step [--as-of YYYY-MM-DD] [--window-from YYYY-MM-DD]

Advisory only; always exits 0 (2 on a malformed --as-of/--window-from). Targets Python 3.9+,
stdlib only.
"""

import argparse
import collections
import datetime
import json
import os
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

ROOT = _profile_root()
# ⭐ TEST-ISOLATABLE (2026-08-05). test_says_insufficient_data_today froze a date-dependent
# snapshot of the live data into an assertion ("everything is still awaiting") — and went red in
# CI the moment replies arrived and old awaiting rows aged past the 14-day resolution line. The
# suite failed BECAUSE the search succeeded. A guard test must run against a FIXTURE, not against
# whatever the pipeline looks like today; same pattern as runlock.py's CLAUDESEARCH_LOCK_PATH.
DATA = os.environ.get("CLAUDESEARCH_DATA_DIR") or os.path.join(ROOT, "data")

# Below this, a percentage is noise dressed up as a finding.
MIN_SAMPLE = 5
# The smallest gap, in percentage points, between two RATABLE arms before recommend() will call
# the configured one CONTRADICTED. ADR-031 B5: hoisted from a local inside recommend() to module
# level so `plays.py --assess` imports the same number this report prints — one home for both
# thresholds (design-connected-entities.md §27.2, design-b5-assessment.md §0). Value unchanged.
MIN_GAP_PP = 20

# A touch outcome that ENDS the wait — the resolution every reply/resolution rate reads. One
# tuple, read by `resolution()` in main() and by `step_funnel()` below, so the two funnels can
# never disagree about what "resolved" means.
TERMINAL_TOUCH_OUTCOMES = ("replied", "meeting-booked", "accepted", "no-response", "declined")

# ADR-031 B5 — the CLOSED construct-signal catalogue (design-connected-entities.md §27.3: four
# kinds; a fifth is an engine change, never a profile's). A proposal keyed `<signal>:<step|token>`
# is a CONSTRUCT — the shape did not play out, and the shape is the engine's. validate_data.py
# refuses any other signal name in a `plans.assessments[].proposals[].key`.
CONSTRUCT_SIGNALS = ("stalled", "no-exit", "goal-off-path", "branch-idle")

# ADR-031 B5 — the evidence keys a proposal of each kind carries: EXACTLY these, no more and no
# fewer (design-b5-assessment.md §2: "typed, fixed per kind"). A parameter proposal's evidence is
# how the resolutions split against the declared window (§27.2's parameter-evidence row); a
# construct proposal's is counts and medians over the shape plus the shipped pattern id and stamp
# it was observed on (§27.3's whitelist — nothing owner-typed is a key here). An undeclared key is
# a validator PROBLEM, never a dropped field (§28.2's type refusal, moved from the composer to the
# row so it holds on every write path).
PROPOSAL_EVIDENCE_KEYS = {
    "parameter": frozenset({"n_resolved", "answered_in_window", "silent", "answered_after",
                            "answer_days"}),
    "construct": frozenset({"pursuits", "attempts_median", "days_median", "pattern",
                            "pattern_sha"}),
}

# Owner decision 27 (design-b5-assessment.md §8, PENDING): an assessment window with no prior
# entry reaches back six weeks — a bound on how far the first replay goes, nothing else.
DEFAULT_WINDOW_DAYS = 42


# ⭐ dev #834 (M2) — the resolution rule, hoisted out of main() so the network section shares it.
# A WIN is a reply, a booking or an accepted connection request.
WIN_OUTCOMES = ("replied", "meeting-booked", "accepted")
NO_RESPONSE_AFTER = 14   # an `awaiting` row older than this is COUNTED as resolved, but the row
                         # is NEVER mutated — the inference stays in the report


def _age_days(d, today=None):
    """Days from ISO date `d` to `today` (a date), or to the wall clock when `today` is None."""
    if today is None:
        return days_since(d)
    try:
        return (today - _iso_to_date(d)).days
    except (ValueError, AttributeError, TypeError):
        return None


def touch_resolution(x, today=None):
    """resolved / resolved-aged / awaiting / bounced / undeliverable-unknown, for one SENT touch."""
    if x.get("delivery") == "bounced":
        return "bounced"
    oc = x.get("outcome")
    if oc in TERMINAL_TOUCH_OUTCOMES:
        return "resolved"
    age = _age_days(x.get("date"), today)
    if oc == "awaiting" and age is not None and age >= NO_RESPONSE_AFTER:
        return "resolved-aged"
    # A pattern-inferred address with unknown delivery cannot distinguish silence from a bounce.
    # It is evidence of NOTHING either way and must not sit in a denominator.
    if (x.get("medium") or "").startswith("email") and \
       x.get("address_status") == "pattern-inferred" and x.get("delivery") == "unknown":
        return "undeliverable-unknown"
    return "awaiting"


def touch_is_win(x):
    return x.get("outcome") in WIN_OUTCOMES


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in (raw.strip() for raw in fh) if line]


def pct(n, d):
    """A rate, or an explicit refusal to compute one."""
    if d == 0:
        return "n/a"
    if d < MIN_SAMPLE:
        return "%d/%d (too few to rate)" % (n, d)
    return "%d/%d = %d%%" % (n, d, round(100.0 * n / d))


def _iso_to_date(s):
    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


def is_iso(v):
    try:
        _iso_to_date(v)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def days_since(d):
    if not d:
        return None
    try:
        y, m, dd = (int(x) for x in d.split("-"))
        return (datetime.date.today() - datetime.date(y, m, dd)).days
    except ValueError:
        return None


def rule(title):
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


def recommend(cut_stats, comms_cfg):
    """Compare the CONFIGURED channel default against what the data actually shows.

    ⚠️ `cut_stats` MUST be a medium cut over FIRST-TOUCH sends only (public #71).
    `communications.default_sequence` configures the media sent together on the first touch —
    it says nothing about which medium a chase or a reply-thread uses — so a cut pooled across
    every touch_type compares default_sequence against a mixed bag it was never a proposal
    about, and a medium used mostly for chases (already-engaged recipients) can outscore one
    used mostly for cold first touches on data that supports no such comparison.

    Two guards, both required before this will say a configured option is CONTRADICTED:
      * n >= MIN_SAMPLE **resolved** in each arm — sends are not evidence, and with 5-10
        samples a "winner" is usually noise;
      * a gap of at least MIN_GAP_PP percentage points.
    Both thresholds are PRINTED alongside the verdict so the recommendation is auditable
    rather than oracular.

    It NEVER edits config.json. It emits a proposal that the weekly review takes to the candidate —
    same rule search-strategist already follows.
    """
    rule("RECOMMENDATION — is the configured default supported by the data?")
    default = comms_cfg.get("default_sequence", [])
    print("  configured default_sequence: %s" % " + ".join(default))
    print("  thresholds: n>=%d RESOLVED per arm AND a >=%d point gap. This script NEVER"
          % (MIN_SAMPLE, MIN_GAP_PP))
    print("  edits config.json — it proposes; the candidate decides at the weekly review.\n")

    ratable = {k: v for k, v in cut_stats.items() if v["resolved"] >= MIN_SAMPLE}
    if not ratable:
        for k in default:
            st = cut_stats.get(k, {"resolved": 0, "sent": 0})
            print("    INSUFFICIENT DATA  %-26s n=%d resolved (need %d) — no recommendation"
                  % (k, st["resolved"], MIN_SAMPLE))
        print("\n  Nothing is ratable yet. With the current pipeline the earliest meaningful")
        print("  read is once a first-touch arm reaches %d RESOLVED sends." % MIN_SAMPLE)
        return

    rates = {k: 100.0 * v["win"] / v["resolved"] for k, v in ratable.items()}
    best = max(rates, key=rates.get)
    for k in default:
        if k not in ratable:
            st = cut_stats.get(k, {"resolved": 0})
            print("    INSUFFICIENT DATA  %-26s n=%d resolved (need %d)"
                  % (k, st["resolved"], MIN_SAMPLE))
            continue
        gap = rates[best] - rates[k]
        if best != k and gap >= MIN_GAP_PP:
            print("    CONTRADICTED       %-26s %d%% vs %s at %d%% (gap %d pts >= %d)"
                  % (k, round(rates[k]), best, round(rates[best]), round(gap), MIN_GAP_PP))
            print("                       -> propose changing communications.default_sequence")
        else:
            print("    CONSISTENT         %-26s %d%% over n=%d resolved"
                  % (k, round(rates[k]), ratable[k]["resolved"]))


# ---- ADR-031 B5 — the step funnel (`--by step`) ---------------------------------------------
#
# Per governing plan, per step of its play: how many pursuits the step became RUNNABLE for
# (replaying `plays.next_step` DAILY over the window — never a stored stage), how many were
# ACTED on (a touch naming the step by `play_step`, a submitted application, or a person of the
# step's class on the record), SENT, REPLIED (`responded_on`), RESOLVED (a terminal touch
# outcome), and the median days the step stayed the answer. Every rate goes through `pct()`, so
# `n < MIN_SAMPLE` prints "too few to rate" with the n and no percentage — the same refusal the
# rest of this report makes. `as_of` is ALWAYS an argument: nothing on this path reads the wall
# clock, so the same window over the same stores renders the same bytes on any day.

def _median(values):
    xs = sorted(values)
    if not xs:
        return None
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0


def step_funnel(ctx_or_root, as_of, window_from=None):
    """{plan_id: {"play_id", "pattern", "pursuits", "window_from", "as_of", "skipped",
    "steps": [{"id", "kind", "runnable", "acted", "sent", "replied", "resolved",
    "days_median"}]}} — counts of PURSUITS (a pursuit counts once per column), replayed daily
    from `max(plan_assigned_on, window_from)` to `as_of` inclusive with `plays.next_step` pinned
    to each day (next_step is a pure function of the stores and a date, so starting the replay
    at the window edge loses nothing). `ctx_or_root` is a `plays.Context` or a profile root to
    build one from. `window_from` defaults to `as_of - DEFAULT_WINDOW_DAYS`.

    What each column means, stated rather than left to the reader:
      runnable    — the step was next_step()'s answer on at least one replayed day in the
                    window (a pursuit that entered the step before the window and is still
                    there counts — it IS in the step during the window)
      acted       — touch step: any touch (any status) naming the step by `play_step` and dated
                    in the window, or a SENT touch that resolves to the step through
                    plays._matching_touches (§26.1(a)); apply step: a submitted application
                    dated in the window; research step: a person of the step's `find` class on
                    the record (plays.class_known — involvements carry no date, so this one is
                    as-of the record, not the window)
      sent / replied / resolved — touch steps only (a sent matching touch · one with
                    `responded_on` · one whose outcome is in TERMINAL_TOUCH_OUTCOMES); an apply
                    step's `sent` equals its `acted`; a research step has none of the three
                    (rendered as —)
      days_median — median over pursuits of the replayed days the step was the answer,
                    truncated at the window edges
    """
    import plays as _plays
    ctx = ctx_or_root if hasattr(ctx_or_root, "plans_by_id") else _plays.Context(ctx_or_root)
    if window_from is None:
        window_from = (_iso_to_date(as_of)
                       - datetime.timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    out = {}
    opps_by_plan = collections.defaultdict(list)
    for o in ctx.opps:
        if o.get("plan_id"):
            opps_by_plan[o["plan_id"]].append(o)
    for plan in sorted(ctx.plans, key=lambda p: str(p.get("id"))):
        pid = plan.get("id")
        play_id = plan.get("play_id")
        play = ctx.plays_by_id.get(play_id) if play_id else None
        entry = {"play_id": play_id, "pattern": (play or {}).get("pattern"),
                 "pursuits": len(opps_by_plan.get(pid, ())), "window_from": window_from,
                 "as_of": as_of, "skipped": None, "steps": []}
        out[pid] = entry
        if play_id == _plays._plans.MANUAL_PLAY:
            entry["skipped"] = "manual play — the owner decides each step; nothing to replay"
            continue
        if play is None:
            entry["skipped"] = "no play to replay (play_id=%r)" % play_id
            continue
        steps = [s for s in play.get("steps") or [] if isinstance(s, dict) and s.get("id")]
        per_step = {s["id"]: {"runnable": set(), "acted": set(), "sent": set(),
                              "replied": set(), "resolved": set(), "days": []} for s in steps}
        for opp in opps_by_plan.get(pid, ()):
            oid = opp.get("id")
            start = max(opp.get("plan_assigned_on") or window_from, window_from)
            day, end = _iso_to_date(start), _iso_to_date(as_of)
            days_in = collections.Counter()
            while day <= end:
                ns = _plays.next_step(plan, play, opp, ctx, day.isoformat())
                if ns.kind == "step" and ns.step in per_step:
                    days_in[ns.step] += 1
                day += datetime.timedelta(days=1)
            for sid, n in days_in.items():
                per_step[sid]["runnable"].add(oid)
                per_step[sid]["days"].append(n)
            for s in steps:
                sid, do = s["id"], s.get("do") or {}
                kind, cell = do.get("kind"), per_step[sid]
                if kind == "touch":
                    named = [t for t in ctx.touches_by_opp.get(oid, ())
                             if t.get("play_step") == sid
                             and window_from <= str(t.get("date") or "")[:10] <= as_of]
                    sent = [t for t in _plays._matching_touches(oid, sid, play, ctx, as_of)
                            if str(t.get("date") or "")[:10] >= window_from]
                    if named or sent:
                        cell["acted"].add(oid)
                    if sent:
                        cell["sent"].add(oid)
                    if any(t.get("responded_on") and str(t["responded_on"])[:10] <= as_of
                           for t in sent):
                        cell["replied"].add(oid)
                    if any(t.get("outcome") in TERMINAL_TOUCH_OUTCOMES for t in sent):
                        cell["resolved"].add(oid)
                elif kind == "apply":
                    ad = _plays.application_date(oid, ctx, as_of)
                    if ad and ad >= window_from:
                        cell["acted"].add(oid)
                        cell["sent"].add(oid)
                elif kind == "research":
                    if do.get("find") and _plays.class_known(oid, do["find"], ctx):
                        cell["acted"].add(oid)
        for s in steps:
            sid, do = s["id"], s.get("do") or {}
            kind, cell = do.get("kind"), per_step[sid]
            entry["steps"].append({
                "id": sid, "kind": kind,
                "runnable": len(cell["runnable"]), "acted": len(cell["acted"]),
                "sent": len(cell["sent"]) if kind in ("touch", "apply") else None,
                "replied": len(cell["replied"]) if kind == "touch" else None,
                "resolved": len(cell["resolved"]) if kind == "touch" else None,
                "days_median": _median(cell["days"]),
            })
    return out


def render_step_funnel(ctx_or_root, as_of, window_from=None):
    """Print `step_funnel()` — one block per plan, one line per step plus its rates, every rate
    through pct(). Returns the computed table so a caller can assert on numbers, not on text."""
    table = step_funnel(ctx_or_root, as_of, window_from)
    some = next(iter(table.values()), None)
    wf = some["window_from"] if some else (window_from or "?")
    rule("STEP FUNNEL — per play step, replayed daily (ADR-031 B5)")
    print("  as of %s · window from %s · a pursuit counts once per column · no rate below n=%d"
          % (as_of, wf, MIN_SAMPLE))
    if not table:
        print("  No plans recorded.")
    for pid, entry in table.items():
        print("")
        print("  plan %s · play %s%s · %d pursuit(s) governed"
              % (pid, entry["play_id"],
                 (" (pattern %s)" % entry["pattern"]) if entry["pattern"] else "",
                 entry["pursuits"]))
        if entry["skipped"]:
            print("    skipped — %s" % entry["skipped"])
            continue
        print("    %-20s %-9s %8s %6s %5s %8s %9s %9s"
              % ("step", "kind", "runnable", "acted", "sent", "replied", "resolved",
                 "median d"))
        for s in entry["steps"]:
            med = s["days_median"]
            print("    %-20s %-9s %8d %6d %5s %8s %9s %9s"
                  % (s["id"], s["kind"] or "?", s["runnable"], s["acted"],
                     "—" if s["sent"] is None else s["sent"],
                     "—" if s["replied"] is None else s["replied"],
                     "—" if s["resolved"] is None else s["resolved"],
                     "—" if med is None else ("%g" % med)))
            rates = ["acted/runnable %s" % pct(s["acted"], s["runnable"])]
            if s["replied"] is not None:
                rates.append("replied/sent %s" % pct(s["replied"], s["sent"]))
                rates.append("resolved/sent %s" % pct(s["resolved"], s["sent"]))
            print("    %-20s   %s" % ("", " · ".join(rates)))
    return table


# ---- Age at capture, by channel (dev #716 / public #142, design §6.5; dev #713 triage surface) ----
#
# How old a posting already was when we first saw it, per channel: `posted.date` (the posting date
# the capture recorded, with its source) against the role's FIRST sighting. A channel that
# surfaces postings a month old is a different instrument from one that surfaces them in days,
# and a retained-search listing page is the clearest case - so the report says which.
#
# ⭐ AN UNKNOWN AGE IS NOT A ZERO. A role with no `posted`, or `posted.source: unknown`, or a
# date that cannot be read, is EXCLUDED from the median and COUNTED beside it ("no posting date"):
# averaging an invented 0 into a channel would make the worst-recorded channel look the freshest.
# And the same refusal as every other rate in this report: below MIN_SAMPLE a channel prints its
# n and "too few to rate", never a median over three roles.

POSTED_SOURCES = ("ats-posted", "board-relative", "profile-document-date")


def _first_sighting(opp):
    """(seen_on ISO date, channel_id) of the role's earliest readable sighting, or (None, None).
    Ties go to the sighting listed first."""
    best = None
    for s in opp.get("sightings") or []:
        if not isinstance(s, dict) or not is_iso(str(s.get("seen_on") or "")[:10]):
            continue
        d = str(s["seen_on"])[:10]
        if best is None or d < best[0]:
            best = (d, s.get("channel_id") or "(none)")
    return best if best else (None, None)


def age_at_capture_by_channel(opps):
    """{channel_id: {"n", "median", "sources": {source: n}, "ages": [days...]}} plus a
    "_excluded" entry {"no_posting_date", "posted_after_seen", "no_sighting"} - the roles that
    could not be measured, by reason. `n` is the number of roles measured; `median` is None
    below MIN_SAMPLE (the refusal lives here, not in the printer, so no caller can bypass it)."""
    by = collections.defaultdict(lambda: {"ages": [], "sources": collections.Counter()})
    excluded = {"no_posting_date": 0, "posted_after_seen": 0, "no_sighting": 0}
    for o in opps:
        seen, cid = _first_sighting(o)
        if seen is None:
            excluded["no_sighting"] += 1
            continue
        p = o.get("posted")
        if (not isinstance(p, dict) or p.get("source") not in POSTED_SOURCES
                or not is_iso(str(p.get("date") or ""))):
            excluded["no_posting_date"] += 1
            continue
        age = (_iso_to_date(seen) - _iso_to_date(str(p["date"]))).days
        if age < 0:
            excluded["posted_after_seen"] += 1
            continue
        by[cid]["ages"].append(age)
        by[cid]["sources"][p["source"]] += 1
    out = {}
    for cid, d in by.items():
        n = len(d["ages"])
        out[cid] = {"n": n, "median": _median(d["ages"]) if n >= MIN_SAMPLE else None,
                    "sources": dict(d["sources"]), "ages": sorted(d["ages"])}
    out["_excluded"] = excluded
    return out


def render_age_at_capture(opps, channels):
    """Print `age_at_capture_by_channel` - one line per channel, then what could not be measured.
    Returns the computed table so a test asserts on numbers, not text."""
    table = age_at_capture_by_channel(opps)
    excluded = table.pop("_excluded")
    rule("AGE AT CAPTURE - how old a posting already was when it was first seen")
    print("  first sighting minus posting date, per channel - no median below n=%d" % MIN_SAMPLE)
    if not table:
        print("  No role carries a posting date yet.")
    for cid, d in sorted(table.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        label = (channels.get(cid) or {}).get("label", cid)
        mix = ", ".join("%s %d" % (s, n) for s, n in sorted(d["sources"].items()))
        if d["median"] is None:
            figure = "n=%d - too few to rate" % d["n"]
        else:
            figure = "median %g days over n=%d" % (d["median"], d["n"])
        print("  %-34s %s (%s)" % (str(label)[:34], figure, mix))
    gaps = []
    if excluded["no_posting_date"]:
        gaps.append("%d with no posting date (age unknown, not zero)" % excluded["no_posting_date"])
    if excluded["posted_after_seen"]:
        gaps.append("%d posted after they were first seen (a date to correct)"
                    % excluded["posted_after_seen"])
    if excluded["no_sighting"]:
        gaps.append("%d with no readable sighting" % excluded["no_sighting"])
    if gaps:
        print("  Not measured: " + "; ".join(gaps) + ".")
    return dict(table, _excluded=excluded)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# ⭐ NETWORK (dev #834, M2 + M4) — design-network-first.md §10.3. The section printed FIRST: the
# relationship is the headline, the application is one source of an opportunity among several.
#
# THE RULES THIS SECTION KEEPS, each one a test in test_funnel_report.py:
#   * EVERY RATE GOES THROUGH MIN_SAMPLE. `_rate()` is the one place a percentage is made; below
#     MIN_SAMPLE it prints "too few to rate (n<5)" and NO percentage (plant: n=4 prints one).
#   * THE DENOMINATOR IS RESOLVED SENDS, by `touch_resolution` / `touch_is_win` — the SAME two
#     functions the application and channel sections below use. Not redefined here.
#   * AN UNRECORDED CHAT IS NEVER ZERO (M4). A past, non-cancelled `kind: chat` commitment with no
#     `attendance` is its own count, listed by id with the verb that records it, excluded from every
#     denominator, and the held count reads "at least N" while any exists (plant: count it as not held).
#   * EVERY BOOKING AND EVERY CHAT LANDS IN EXACTLY ONE PLACE, and the identity is asserted in the
#     output (`NOT CHECKED: ... identity broken` when it is not), so a bucket cannot silently drop one.
#   * A MISSING THING IS NOT AN EMPTY THING. Reply coverage is READ from the journal (`swept` for mail,
#     `pass` for LinkedIn); a medium with sends and no covered day prints `NOT CHECKED`, never a lower
#     number as if complete. An unreadable journal says so; it does not read as "no events".
#
# READ (reading this dispatch, 2026-11-14): `journal.coverage_intervals` / `_merge_intervals` do the
# interval, DST and legacy-row logic (dev #807, #711); this section CALLS them and never re-implements
# them. The journal is read RAW by event name, tolerant of events this script does not use, so a
# journal that carries a newer engine's event kinds cannot blank the section.
# INFERRED (design §10.3 flags it): a LinkedIn pass that read the messages list is a `pass` row of
# kind `linkedin`, phase `recorded`, whose `reached` carries `inbox` and whose `partial` does not.
# ═══════════════════════════════════════════════════════════════════════════════════════════

BOOKED_BUCKETS = ("held", "no-show", "unrecorded", "upcoming", "cancelled", "no chat recorded")
UNBOOKED_BUCKETS = ("held", "no-show", "unrecorded", "upcoming")
_INBOX_SURFACE = "inbox"
_ZERO_STATE_ROWS = ("new reach-outs sent", "role-specific first touches", "replied (a win)", "bookings (touches)",
                    "chats with no booking", "chats held (all chats)", "intros", "chat → opportunity")


def _rate(n, d, unit="resolved"):
    """The ONE place a network percentage is made. Below MIN_SAMPLE it prints no percentage; at 0 it says none yet."""
    if d == 0:
        return "none %s yet" % unit
    if d < MIN_SAMPLE:
        return "%d of %d %s   too few to rate (n<%d)" % (n, d, unit, MIN_SAMPLE)
    return "%d of %d %s   rate %d%%" % (n, d, unit, round(100.0 * n / d))


def _net_root(ctx_or_root):
    return str(getattr(ctx_or_root, "root", ctx_or_root))


def _net_rows(root, name):
    """Every row of `<root>/data/<name>`; a missing file is an empty store, a malformed line raises."""
    out = []
    try:
        fh = open(os.path.join(root, "data", name), encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _net_journal(root):
    """(rows, problem). Every parseable journal row; `problem` is a sentence when the journal could not
    be read in full, so a caller says NOT CHECKED rather than reading a hole as "no events"."""
    import journal as _j
    rows, bad = [], 0
    try:
        fh = open(_j.path(root), encoding="utf-8")
    except FileNotFoundError:
        return [], None
    except OSError as e:
        return [], "journal unreadable (%s)" % e
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(rec, dict):
                rows.append(rec)
            else:
                bad += 1
    return rows, ("%d journal line(s) unreadable" % bad) if bad else None


def _resolve_person(people, pid):
    """`people` merge chain followed to its end (a cycle or a dangling link stops where it is)."""
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        row = people.get(pid)
        if not row or row.get("status") != "merged" or not row.get("merged_into"):
            break
        pid = row["merged_into"]
    return pid


def _date_or_none(v):
    try:
        return _iso_to_date(v)
    except (ValueError, AttributeError, TypeError):
        return None


def _iso_week(d):
    y, w, _wd = d.isocalendar()
    return "%04d-W%02d" % (y, w)


def _chat_state(c, today):
    """cancelled / held / no-show / unrecorded / upcoming for one `kind: chat` commitment. A past chat
    with no `attendance` is UNRECORDED — a fact nobody has told the engine, never "not held"."""
    if c.get("status") == "cancelled":
        return "cancelled"
    if c.get("attendance") in ("held", "no-show"):
        return c["attendance"]
    d = _date_or_none(c.get("date"))
    return "unrecorded" if d is not None and d < today else "upcoming"


def _chat_model(root, as_of, window_from=None):
    """Everything `chat_buckets` and `network_section` share, computed once (design §10.3 'the join').
    `as_of` is a `datetime.date` (strategy_view) or an ISO string (the CLI): one ISO string from here on."""
    as_of = as_of.isoformat() if isinstance(as_of, datetime.date) else as_of
    today = _iso_to_date(as_of)
    wf = window_from or (today - datetime.timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    people = {p["id"]: p for p in _net_rows(root, "people.jsonl") if p.get("id")}
    touches = _net_rows(root, "touches.jsonl")
    commits = _net_rows(root, "commitments.jsonl")
    chats = [c for c in commits if c.get("kind") == "chat" and c.get("id")]
    in_scope = lambda c: str(c.get("date") or "") >= wf          # window start; no upper bound (upcoming)
    bookings = sorted((t for t in touches if t.get("outcome") == "meeting-booked"
                       and t.get("status") == "sent" and t.get("id")
                       and wf <= str(t.get("date") or "") <= as_of),
                      key=lambda t: (str(t.get("date") or ""), t["id"]))
    match, used = {}, set()                                       # touch id -> chat (or None); chat ids used
    for t in bookings:                                            # 1. the explicit link
        c = next((c for c in chats if c.get("touch_id") == t["id"] and c["id"] not in used), None)
        if c is not None:
            match[t["id"]] = c
            used.add(c["id"])
    for t in bookings:                                            # 2. earliest LIVE, 3. earliest CANCELLED
        if t["id"] in match:
            continue
        who = _resolve_person(people, t.get("person_id"))
        cands = [c for c in chats if c["id"] not in used and who
                 and _resolve_person(people, c.get("person_id")) == who
                 and str(c.get("date") or "") >= str(t.get("date") or "")]
        live = [c for c in cands if c.get("status") != "cancelled"]
        pool = live or cands
        pick = min(pool, key=lambda c: (str(c.get("date") or ""), c["id"])) if pool else None
        match[t["id"]] = pick
        if pick is not None:
            used.add(pick["id"])
    booked = {b: [] for b in BOOKED_BUCKETS}
    for t in bookings:
        c = match.get(t["id"])
        booked["no chat recorded" if c is None else _chat_state(c, today)].append(t["id"])
    scoped_live = [c for c in chats if in_scope(c) and c.get("status") != "cancelled"]
    matched_live = [c for c in scoped_live if c["id"] in used]
    unbooked = {b: [] for b in UNBOOKED_BUCKETS}
    for c in scoped_live:
        if c["id"] not in used:
            unbooked[_chat_state(c, today)].append(c["id"])
    unrecorded = sorted((c["id"] for c in scoped_live if _chat_state(c, today) == "unrecorded"))
    return {"today": today, "as_of": as_of, "window_from": wf, "bookings": bookings, "match": match, "booked": booked,
            "unbooked": unbooked, "unrecorded": unrecorded, "scoped_live": scoped_live,
            "matched_live": matched_live, "no_chat_recorded": list(booked["no chat recorded"]),
            "people": people, "touches": touches, "commits": commits, "chats": chats}


def chat_buckets(ctx_or_root, as_of, window_from=None):
    """{"bookings": {bucket: [touch ids]}, "unbooked": {bucket: [commitment ids]}, "unrecorded":
    [commitment ids], "no_chat_recorded": [touch ids]} — design §16.1; NF6's 'Chats to record' reads the
    last two. The join of a `meeting-booked` touch to its chat is DERIVED here, never stored."""
    m = _chat_model(_net_root(ctx_or_root), as_of, window_from)
    return {"bookings": m["booked"], "unbooked": m["unbooked"], "unrecorded": m["unrecorded"],
            "no_chat_recorded": m["no_chat_recorded"]}


def chat_identities_hold(m):
    """The two asserted identities: every booking is in exactly one of six buckets, and every
    non-cancelled chat is a matched chat or in `chats with no booking`."""
    n_booked = sum(len(v) for v in m["booked"].values())
    n_unbooked = sum(len(v) for v in m["unbooked"].values())
    return (n_booked == len(m["bookings"])
            and len(m["scoped_live"]) == len(m["matched_live"]) + n_unbooked)


def _day_bounds_utc(day):
    """[00:00, next 00:00) of `day` in the profile's zone, as aware UTC instants."""
    import journal as _j
    tz = _j._declared_zone()
    nxt = day + datetime.timedelta(days=1)

    def at(d):
        n = datetime.datetime(d.year, d.month, d.day)
        return n.replace(tzinfo=tz) if tz is not None else n.astimezone()
    return at(day).astimezone(datetime.timezone.utc), at(nxt).astimezone(datetime.timezone.utc)


def _mail_coverage(recs, days):
    """(mailboxes, {mailbox: [uncovered days]}). A mailbox is covered on day D when the union of its ok
    `swept` intervals covers the whole day in the profile's zone — `journal.coverage_intervals` and
    `journal._merge_intervals`, never a second implementation of the interval logic (dev #807)."""
    import journal as _j
    boxes = sorted({r.get("mailbox") for r in recs if r.get("event") == "swept" and r.get("mailbox")})
    gaps = {}
    for mb in boxes:
        merged = _j._merge_intervals(_j.coverage_intervals(recs, mb))
        miss = []
        for d in days:
            s, e = _day_bounds_utc(d)
            if not any(f <= s and t >= e for f, t in merged):
                miss.append(d)
        gaps[mb] = miss
    return boxes, gaps


def _linkedin_covered_days(recs):
    """The ISO days on which a recorded LinkedIn pass read the messages list (`inbox` in `reached`, not
    in `partial`). `inbox` is taken from `journal.LINKEDIN_REPLY_SURFACES` by name."""
    import journal as _j
    if _INBOX_SURFACE not in _j.LINKEDIN_REPLY_SURFACES:
        return None
    out = set()
    for r in recs:
        if r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "recorded":
            if _INBOX_SURFACE in (r.get("reached") or []) and _INBOX_SURFACE not in (r.get("partial") or []):
                out.add(str(r.get("at") or "")[:10])
    return out


def _opp_created(o, commits_by_id):
    """The date an opportunity entered the record: its earliest sighting, else the chat it came from,
    else its plan assignment; None when nothing says (never guessed). INFERRED: the schema has no
    created-on field."""
    seen = sorted(str(s.get("seen_on")) for s in (o.get("sightings") or []) if s.get("seen_on"))
    if seen:
        return seen[0]
    c = commits_by_id.get(o.get("via_commitment_id"))
    if c and c.get("date"):
        return str(c["date"])
    return str(o["plan_assigned_on"]) if o.get("plan_assigned_on") else None


def _reachouts_plan(root, as_of):
    """`reachouts.plan(...)` as of `as_of` (NF3, design §9.1); None when the engine has no `reachouts` module (an ImportError is
    the ONLY thing treated as "not built"). Anything else it raises is loud, never an empty answer. The contract (dev #834
    verify): `reachouts.plan` takes a `datetime.date`; this module carries ISO strings, so it converts once, here."""
    try:
        import reachouts as _r
    except ImportError:
        return None
    return _r.plan(root, _iso_to_date(as_of) if isinstance(as_of, str) else as_of) or {}


def _unobserved_items(root, as_of):
    """[(ref, label)] for `reachouts.plan(...)["unobserved"]`; [] when the engine has no `reachouts` module."""
    out = []
    for item in (_reachouts_plan(root, as_of) or {}).get("unobserved") or []:
        if isinstance(item, dict):
            ref = str(item.get("ref") or item.get("id") or "?")
            out.append((ref, "%s (%s%s)" % (ref, item.get("person") or item.get("person_id") or "?",
                                            (", %s days" % item["days"]) if item.get("days") is not None else "")))
        else:
            out.append((str(item).split(" ", 1)[0], str(item)))
    return out


def _unobserved_sends(root, as_of):
    return [label for _ref, label in _unobserved_items(root, as_of)]


def _age_unknown_drafts(root, as_of):
    """`["<ref> (<person>): <reason>"]` for `reachouts.plan(...)["age_unknown"]` (design 9.1): open first-touch drafts whose age
    cannot be read from their `**Brief:**` id. They are neither a send unobserved nor silently absent: the report names them."""
    return ["%s (%s): %s" % (u.get("ref"), u.get("person"), u.get("reason"))
            for u in (_reachouts_plan(root, as_of) or {}).get("age_unknown") or [] if isinstance(u, dict)]


def network_section(ctx_or_root, as_of, window_from=None):
    """The NETWORK section as text (design §10.3), over `[window_from, as_of]` (default the last
    `DEFAULT_WINDOW_DAYS`) and per ISO week. Pure over the stores and the journal: no wall clock, no
    write. Every figure is a count of rows or a rate through `_rate` (MIN_SAMPLE); a figure it cannot
    stand behind prints NOT CHECKED or PARTIAL, never a quiet number."""
    root = _net_root(ctx_or_root)
    m = _chat_model(root, as_of, window_from)
    today, wf, as_of = m["today"], m["window_from"], m["as_of"]
    in_win = lambda d: wf <= str(d or "") <= as_of
    people, touches, commits = m["people"], m["touches"], m["commits"]
    commits_by_id = {c["id"]: c for c in commits if c.get("id")}
    opps = _net_rows(root, "opportunities.jsonl")
    apps = _net_rows(root, "applications.jsonl")
    companies = {c["id"]: c for c in _net_rows(root, "companies.jsonl") if c.get("id")}
    proposals = _net_rows(root, "proposals.jsonl")
    recs, jproblem = _net_journal(root)
    L = []

    def line(label, text):
        L.append("  %-27s %s" % (label, text))

    # ---- the window's sends -----------------------------------------------------------------
    sent = [t for t in touches if t.get("status") == "sent" and in_win(t.get("date"))]

    def earlier_touch(t):
        who = _resolve_person(people, t.get("person_id"))
        return bool(who) and any(
            u is not t and u.get("status") == "sent" and _resolve_person(people, u.get("person_id")) == who
            and str(u.get("date") or "") < str(t.get("date") or "") for u in touches)
    firsts = [t for t in sent if t.get("touch_type") == "first-touch"]
    new_out = [t for t in firsts if not t.get("opp_id") and not earlier_touch(t)]
    role_specific = [t for t in firsts if t.get("opp_id")]
    resolved = [t for t in new_out if touch_resolution(t, today) in ("resolved", "resolved-aged")]
    awaiting = [t for t in new_out if touch_resolution(t, today) == "awaiting"]
    wins = [t for t in resolved if touch_is_win(t)]
    unobs = _unobserved_sends(root, as_of)

    # ---- coverage, READ from the journal ----------------------------------------------------
    days = [wf_d + datetime.timedelta(days=i)
            for wf_d in [_iso_to_date(wf)] for i in range((today - wf_d).days + 1)]
    media = {"mail": [t for t in sent if (t.get("medium") or "").startswith("email")],
             "LinkedIn": [t for t in sent if (t.get("medium") or "").startswith("linkedin")]}
    cov = {}                                   # medium -> ("full" | "partial" | "none", first uncovered day)
    cov_text = []
    if jproblem and not recs:
        cov_text.append("NOT CHECKED: %s" % jproblem)
        for k in media:
            cov[k] = ("none", None)
    else:
        boxes, gaps = _mail_coverage(recs, days)
        full_boxes = [b for b in boxes if not gaps[b]]
        any_cov = any(len(gaps[b]) < len(days) for b in boxes)
        first_gap = min((g[0] for g in gaps.values() if g), default=None)
        cov["mail"] = (("none" if not any_cov else "full" if not first_gap else "partial"), first_gap)
        if boxes:
            cov_text.append("mail %d of %d mailbox%s every day" % (len(full_boxes), len(boxes),
                                                                   "" if len(boxes) == 1 else "es"))
        else:
            cov_text.append("mail NOT CHECKED (no sweep recorded)")
        li = _linkedin_covered_days(recs)
        if li is None:
            cov["LinkedIn"] = ("none", None)
            cov_text.append("LinkedIn NOT CHECKED (journal has no `inbox` surface)")
        else:
            li_days = [d for d in days if d.isoformat() in li]
            li_gap = next((d for d in days if d.isoformat() not in li), None)
            cov["LinkedIn"] = (("none" if not li_days else "full" if li_gap is None else "partial"), li_gap)
            cov_text.append("LinkedIn messages read on %d of %d days" % (len(li_days), len(days)))
        if jproblem:
            cov_text.append("NOT CHECKED in part: %s" % jproblem)
    partial_tags = []
    not_checked = []
    for k, rows_k in media.items():
        if not rows_k:
            continue
        state, gap = cov.get(k, ("none", None))
        if state == "none":
            since = wf
            not_checked.append("NOT CHECKED: %s replies (no %s since %s)"
                               % (k, "sweep covered a day" if k == "mail" else "pass read messages", since))
        elif state == "partial":
            partial_tags.append("PARTIAL: %s %s" % (k, gap.isoformat()))
    any_gap = bool(partial_tags or not_checked or jproblem)

    # ---- weeks at budget, from the `network` events ----------------------------------------
    net_ev = sorted((r for r in recs if r.get("event") == "network" and r.get("week")),
                    key=lambda r: str(r.get("at") or ""))
    first_ev = net_ev[0] if net_ev else None
    since = str(first_ev.get("at") or "")[:10] if first_ev else None
    by_week = {}
    for r in net_ev:
        by_week.setdefault(r["week"], r)                      # the week's FIRST event: its recorded budget
    win_weeks = []
    for d in days:
        w = _iso_week(d)
        if w not in win_weeks:
            win_weeks.append(w)
    run_weeks = [w for w in win_weeks if w in by_week]
    sent_per_week = collections.Counter(_iso_week(_iso_to_date(t["date"])) for t in new_out if _date_or_none(t.get("date")))
    at_budget = [w for w in run_weeks if sent_per_week[w] >= int(by_week[w].get("budget") or 0)]

    # ---- print ---------------------------------------------------------------------------
    L.insert(0, "NETWORK  (window %s .. %s · %s)" % (
        wf, as_of, ("network-first since %s" % since) if since else "network-first: no `network` event recorded"))
    line("coverage", (" · ".join(cov_text) or "no journal events") + ("   PARTIAL" if any_gap else ""))
    tag = ("   " + "; ".join(partial_tags)) if partial_tags else ""
    line("new reach-outs sent", ("at least %d (+%d send unobserved)" % (len(new_out), len(unobs)) if unobs
                                 else "%d" % len(new_out)) + tag)
    line("role-specific first touches", "%d   (carry an opp_id; not budgeted)" % len(role_specific))
    if run_weeks:
        line("weeks at budget", "%d of %d run   (each week against the budget recorded that week; %d other "
             "week%s in the window not run)" % (len(at_budget), len(run_weeks), len(win_weeks) - len(run_weeks),
                                                "" if len(win_weeks) - len(run_weeks) == 1 else "s"))
    else:                                     # 0.90.3: what this week holds, not "none run"
        wk = _reachouts_plan(root, as_of)
        line("this week", "budget %s, spent %s" % (wk.get("budget"), wk.get("spent")) if wk else "no `network` event yet")
    if not_checked:
        line("replied (a win)", "; ".join(not_checked))
    else:
        line("replied (a win)", _rate(len(wins), len(resolved)) + "   (%d awaiting; win = replied · "
             "meeting-booked · accepted)" % len(awaiting) + tag)

    nb = len(m["bookings"])
    line("bookings (touches)", "%d   (a subset of replied)" % nb)
    bk = m["booked"]
    line("", "= " + " · ".join("%s %d" % (b, len(bk[b])) for b in BOOKED_BUCKETS))
    ub = m["unbooked"]
    n_ub = sum(len(v) for v in ub.values())
    line("chats with no booking", "%d   = %s" % (n_ub, " · ".join("%s %d" % (b, len(ub[b])) for b in UNBOOKED_BUCKETS)))
    for cid in m["unrecorded"]:
        line("", "unrecorded: %s — record it: record.py attended %s held|no-show" % (cid, cid))
    for tid in m["no_chat_recorded"]:
        t = next((x for x in touches if x.get("id") == tid), {})
        line("", "no chat recorded: touch %s (%s) — record it: record.py chat %s --on <date> --touch %s"
             % (tid, t.get("person_id") or "?", t.get("person_id") or "<person>", tid))
    held = [c for c in m["scoped_live"] if _chat_state(c, today) == "held"]
    n_unrec = len(m["unrecorded"])
    line("chats held (all chats)", ("at least %d   (while any is unrecorded)" % len(held)) if n_unrec else "%d" % len(held))
    if not chat_identities_hold(m):
        line("", "NOT CHECKED: a chat or booking bucket identity is broken; the counts above do not add up")

    offered = sum(len(c.get("intros_given") or []) for c in m["scoped_live"])
    landed_refs = {t.get("trigger_ref") for t in touches if t.get("trigger_kind") == "introduction"}
    landed = sum(len(c.get("intros_given") or []) for c in m["scoped_live"] if "commitment:%s" % c["id"] in landed_refs)
    line("intros", "offered %d · landed %d   %s" % (offered, landed, _rate(landed, offered, "offered")))
    win_opps = [o for o in opps if (lambda d: d is not None and in_win(d))(_opp_created(o, commits_by_id))]
    held_ids = {c["id"] for c in held}
    from_chat = [o for o in win_opps if o.get("via_commitment_id")]
    from_person = [o for o in win_opps if not o.get("via_commitment_id") and o.get("via_person_id")]
    unsourced = [o for o in win_opps if not o.get("via_commitment_id") and not o.get("via_person_id")]
    chat_opps = [o for o in from_chat if o["via_commitment_id"] in held_ids]
    line("chat → opportunity", _rate(len(chat_opps), len(held), "held"))
    if not (sent or nb or m["scoped_live"] or unobs):    # 0.90.3 zero state: one line of what happened, not rows of 0
        L[:] = [l for l in L if l[2:29].strip() not in _ZERO_STATE_ROWS + ("",)]      # "" = the bucket rows
        L.insert(3, "  %-27s %s" % ("reach-outs and chats", "none yet: no reach-out sent, chat held or meeting booked"))
    line("opportunities in window", "%d" % len(win_opps) + (": from a chat %d · from a person, no chat %d · source not recorded %d"
         % (len(from_chat), len(from_person), len(unsourced)) if win_opps else ""))
    app_opps = {a.get("opp_id") for a in apps}
    line("opportunity → application", "%d" % sum(1 for o in win_opps if o.get("id") in app_opps))

    raised_ev = [r for r in recs if r.get("event") == "companies-raised" and in_win(str(r.get("at") or "")[:10])]
    if raised_ev:
        raised_ids = [c for r in raised_ev for c in (r.get("raised") or [])]
        answered = sum(1 for c in raised_ids if (companies.get(c) or {}).get("status_on"))
        last = sorted(raised_ev, key=lambda r: str(r.get("at") or ""))[-1]
        line("look into", "raised %d in %d run%s · answered %d · waiting %s"
             % (len(raised_ids), len(raised_ev), "" if len(raised_ev) == 1 else "s", answered, last.get("waiting", "?")))
    else:
        line("look into", "no raise recorded in the window")
    p_sent = [p for p in proposals if p.get("sent_on") and in_win(p.get("sent_on"))]
    p_acc = [p for p in p_sent if p.get("status") == "accepted"]
    line("proposals sent %d · accepted %d" % (len(p_sent), len(p_acc)), _rate(len(p_acc), len(p_sent), "sent"))
    n_classify = sum(1 for c in commits if not c.get("kind") and c.get("status") != "cancelled"
                     and wf <= str(c.get("date") or "") < today.isoformat())
    if n_classify:
        line("meetings to classify", "%d   (commitments with no kind; record.py set <id> kind chat|interview "
             "--file commitments)" % n_classify)
    if unobs:
        line("send unobserved", " · ".join(unobs))
    unknown_age = _age_unknown_drafts(root, as_of)
    if unknown_age:
        line("draft age unknown", " · ".join(unknown_age) + "   (not counted as a send unobserved; record the send or delete the draft)")
    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# ⭐ THE NETWORK LIST'S ROWS (dev #834, M4 + M5; design §10.4). ONE derivation, two readers:
# `generate_dashboard.py` renders exactly these rows and `check_dashboard_coverage.py` expects exactly
# these keys, so the page and its gate cannot disagree about what the Network list owes the reader.
#
# Only rows the owner ACTS ON — status (reach-outs against budget, chats held, intros, targets, the LAMP
# table) is NOT here: it lives in the weekly review and `views/network_strategy.md`. Each row is
# `net:<kind>:<id>`, in these sub-groups (each omitted when empty):
#   look-into   a company raised for "look into this company?" (`your_move.classify_companies`, NF2)
#   chat        a past `kind: chat` commitment with no `attendance` (the M4 "unrecorded chat")
#   booking     a `meeting-booked` touch no chat was ever recorded for
#   suggestion  an open `kind: suggestion` ask (the strategist's proposal, awaiting confirm or decline)
#   send        a first-touch draft whose send was never observed (`reachouts.plan`, NF3)
#   proposal    a proposal still `drafting`
# A module the engine does not have yet (`your_move.classify_companies`, `reachouts`) contributes no rows;
# any OTHER failure inside one propagates, so a broken derivation is a loud page, never an empty list.
# ═══════════════════════════════════════════════════════════════════════════════════════════

NETWORK_GROUPS = ("look-into", "chat", "booking", "suggestion", "send", "proposal")
SUGGESTION_STALE_DAYS = 28


def _company_item_id(item):
    if isinstance(item, dict):
        return item.get("company_id") or item.get("id") or (item.get("company") or {}).get("id")
    return str(item) if item else None


def _look_into(root, today):
    """([items], new_count, waiting) from `your_move.classify_companies`; ([], 0, 0) when this engine has
    no such function (NF2 not built)."""
    try:
        import your_move as _ym
        fn = _ym.classify_companies
    except (ImportError, AttributeError):
        return [], 0, 0
    d = fn(root, today) or {}
    return (list(d.get("look-into") or []), len(d.get("look-into-new") or []),
            int(d.get("look-into-waiting") or 0))


def network_rows(ctx_or_root, today):
    """{"rows": [{"key", "group", "title", "detail", "verbs": [str], "subject", "actions": [{"action", "rec_id",
    "label"}]}], "look_into_new": n, "look_into_waiting": n, "sent_proposals": n} — the Network list's contents as of
    `today` (an ISO date). Pure over the stores; no write.

    `verbs` is the ENGINE's own record of the write each row asks for (a `record.py` string); it is never rendered on
    the candidate-facing page (jobsearch 0.88.0, dev #915). The page renders `actions`: `dashboard_actions.block`
    inputs, plain words and a copy-as-prompt block, never a command. `subject` is the row's one subject
    (`person:<id>` when an unrecorded chat or a booking names a person, else the row's own key)."""
    root = _net_root(ctx_or_root)
    companies = {c["id"]: c for c in _net_rows(root, "companies.jsonl") if c.get("id")}
    people = {p["id"]: p for p in _net_rows(root, "people.jsonl") if p.get("id")}
    rows = []

    items, n_new, n_wait = _look_into(root, today)
    li = []
    for it in items:
        cid = _company_item_id(it)
        if not cid:
            continue
        co = companies.get(cid) or {}
        raised = (it.get("raised_on") if isinstance(it, dict) else None) or co.get("raised_on") or ""
        li.append((str(raised), str(cid), co.get("name") or (it.get("name") if isinstance(it, dict) else None) or cid))
    for raised, cid, name in sorted(li):
        rows.append({"key": "net:look-into:%s" % cid, "group": "look-into", "title": name,
                     "detail": ("raised %s" % raised) if raised else "raised",
                     "verbs": ["record.py company-status %s %s" % (cid, st)
                               for st in ("active-target", "watching", "passed")],
                     "subject": "net:look-into:%s" % cid, "next_step": "decide: yes, no or later",
                     "actions": [{"action": "target-yes", "rec_id": "company:%s" % cid, "label": "Yes"},
                                 {"action": "target-no", "rec_id": "company:%s" % cid, "label": "No"},
                                 {"action": "target-later", "rec_id": "company:%s" % cid, "label": "Later"},
                                 {"action": "company-kind-staffing", "rec_id": "company:%s" % cid,
                                  "label": "This is a staffing firm or aggregator"}]})

    # a chat is "to record" whatever its age: the window here is the whole record, so an old unrecorded
    # chat is never aged off the page by a 42-day window.
    b = chat_buckets(root, today, "0001-01-01")
    commits = {c["id"]: c for c in _net_rows(root, "commitments.jsonl") if c.get("id")}
    touches = {t["id"]: t for t in _net_rows(root, "touches.jsonl") if t.get("id")}
    for cid in b["unrecorded"]:
        c = commits.get(cid) or {}
        who = (people.get(c.get("person_id")) or {}).get("name") or c.get("person_id") or "?"
        rows.append({"key": "net:chat:%s" % cid, "group": "chat", "title": "%s with %s" % (c.get("title") or "Chat", who),
                     "detail": "on %s, held or not recorded" % (c.get("date") or "?"),
                     "verbs": ["record.py attended %s held" % cid, "record.py attended %s no-show" % cid],
                     "subject": ("person:%s" % c["person_id"]) if c.get("person_id") else "net:chat:%s" % cid,
                     "next_step": "record whether it happened",
                     "actions": [{"action": "chat-held", "rec_id": "commit:%s" % cid, "label": "It happened"},
                                 {"action": "chat-no-show", "rec_id": "commit:%s" % cid, "label": "No-show"}]})
    for tid in b["no_chat_recorded"]:
        t = touches.get(tid) or {}
        who = (people.get(t.get("person_id")) or {}).get("name") or t.get("person_id") or "?"
        rows.append({"key": "net:booking:%s" % tid, "group": "booking", "title": "Booked with %s" % who,
                     "detail": "booked on %s, no chat recorded" % (t.get("date") or "?"),
                     "verbs": ["record.py chat %s --on <date> --touch %s" % (t.get("person_id") or "<person>", tid)],
                     "subject": ("person:%s" % t["person_id"]) if t.get("person_id") else "net:booking:%s" % tid,
                     "next_step": "record the chat you had",
                     "actions": [{"action": "booking-chat", "rec_id": "touch:%s" % tid, "label": "Record the chat"}]})

    for a in _net_rows(root, "asks.jsonl"):
        if a.get("kind") == "suggestion" and a.get("id") and not a.get("resolved_on"):
            age = _age_days(a.get("created"), _iso_to_date(today))
            stale = age is not None and age > SUGGESTION_STALE_DAYS
            rows.append({"key": "net:suggestion:%s" % a["id"], "group": "suggestion",
                         "title": a.get("title") or a["id"],
                         "detail": (a.get("ask") or "") + ("  (stale: open %d days)" % age if stale else ""),
                         "verbs": ["record.py confirm %s" % a["id"], "record.py decline %s" % a["id"]],
                         "subject": "net:suggestion:%s" % a["id"], "next_step": "confirm or decline",
                         "actions": [{"action": "suggestion-yes", "rec_id": "ask:%s" % a["id"], "label": "Yes"},
                                     {"action": "suggestion-no", "rec_id": "ask:%s" % a["id"], "label": "No"}]})

    for ref, label in _unobserved_items(root, today):
        rows.append({"key": "net:send:%s" % ref, "group": "send", "title": "Send unobserved: %s" % label,
                     "detail": "record the send, or delete the draft",
                     "verbs": ["record.py touch …", "delete the draft from outreach/drafts.md"],
                     "subject": "net:send:%s" % ref, "next_step": "record the send, or delete the draft",
                     "actions": [{"action": "send-observed", "rec_id": "send:%s" % ref, "label": "I sent it"}]})

    props = _net_rows(root, "proposals.jsonl")
    for p in props:
        if p.get("status") == "drafting" and p.get("id"):
            rows.append({"key": "net:proposal:%s" % p["id"], "group": "proposal", "title": "Proposal %s" % p["id"],
                         "detail": "still drafting", "verbs": ["record.py proposal-status %s sent" % p["id"]],
                         "subject": "net:proposal:%s" % p["id"], "next_step": "mark it sent when it goes out",
                         "actions": [{"action": "proposal-sent", "rec_id": "proposal:%s" % p["id"],
                                      "label": "I sent it"}]})
    order = {g: i for i, g in enumerate(NETWORK_GROUPS)}
    rows.sort(key=lambda r: order[r["group"]])               # stable: each group keeps its own order
    return {"rows": rows, "look_into_new": n_new, "look_into_waiting": n_wait,
            "sent_proposals": sum(1 for p in props if p.get("status") == "sent")}


def _today():
    """The ONE wall-clock read on the `--by step` path, and only as the CLI default for
    `--as-of` — `step_funnel()`/`render_step_funnel()` never call it (a test freezes this
    module's clock on two different days and asserts identical bytes)."""
    return datetime.date.today().isoformat()


def main():
    ap = argparse.ArgumentParser(description="What's actually working.")
    ap.add_argument("--recommend", action="store_true",
                    help="Also compare the configured channel default against the data.")
    ap.add_argument("--by", choices=("step",), default=None,
                    help="ADR-031 B5: `--by step` prints the per-play-step funnel INSTEAD of "
                         "the standard report (the assessment's arithmetic; weekly-review "
                         "runs the two as separate commands).")
    ap.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                    help="the last day of the replay (--by step) or of the NETWORK section's "
                         "window (the standard report). Default: today.")
    ap.add_argument("--window-from", default=None, metavar="YYYY-MM-DD",
                    help="the first day of the replay or of the NETWORK window (default: as-of "
                         "minus %d days)." % DEFAULT_WINDOW_DAYS)
    args = ap.parse_args()

    if args.by == "step":
        as_of = args.as_of or _today()
        for label, v in (("--as-of", as_of), ("--window-from", args.window_from)):
            if v is not None and not is_iso(v):
                print("%s must be YYYY-MM-DD, got %r" % (label, v))
                return 2
        print("Funnel report — by step, as of %s" % as_of)
        # plays.Context reads <root>/data; DATA is that directory (CLAUDESEARCH_DATA_DIR-
        # overridable), so the root the replay reads is DATA's parent — never a second
        # resolution of the profile that could disagree with the one this report reads.
        render_step_funnel(os.path.dirname(os.path.abspath(DATA)), as_of, args.window_from)
        return 0

    opps = load("opportunities.jsonl")
    companies = {c["id"]: c for c in load("companies.jsonl")}
    channels = {c["id"]: c for c in load("channels.jsonl")}
    involvements = load("involvements.jsonl")

    print("Funnel report - %s" % datetime.date.today().isoformat())
    print("%d opportunities tracked" % len(opps))

    # ---- 0. NETWORK FIRST (dev #834, M2): the relationship is the headline; the application
    # sections below stay, unchanged, but are no longer the first thing a reader meets. ------------
    _net_as_of = args.as_of or _today()
    for label, v in (("--as-of", _net_as_of), ("--window-from", args.window_from)):
        if v is not None and not is_iso(v):
            print("%s must be YYYY-MM-DD, got %r" % (label, v))
            return 2
    print("")
    print(network_section(os.path.dirname(os.path.abspath(DATA)), _net_as_of, args.window_from))

    # ---- 1. Channel yield: which sources produce roles worth pursuing? ------
    rule("CHANNEL YIELD - which sources produce roles worth pursuing")
    seen = collections.defaultdict(lambda: {"total": 0, "pursued": 0})
    for o in opps:
        pursued = o.get("verdict") == "pursue"
        for s in o.get("sightings") or []:
            cid = s.get("channel_id") or "(none)"
            seen[cid]["total"] += 1
            if pursued:
                seen[cid]["pursued"] += 1
    if not seen:
        print("  No sightings recorded.")
    for cid, d in sorted(seen.items(), key=lambda kv: -kv[1]["total"]):
        label = channels.get(cid, {}).get("label", cid)
        print("  %-34s %3d sourced -> %s pursued" % (label[:34], d["total"], pct(d["pursued"], d["total"])))
    print("")
    print("  NOTE: most sightings carry channel_id 'legacy-import' - the 2026-07-20")
    print("  markdown backfill could not recover where those roles originally came")
    print("  from. Channel yield only becomes meaningful for roles sourced after")
    print("  that date. Reported as-is rather than quietly excluded.")

    # ---- 1b. Age at capture, by channel (dev #716 / public #142) ------------
    render_age_at_capture(opps, channels)

    # ---- 2. Applications (ADR-031 B2 — the top-level applications/cover_letters stores,
    # joined by opp_id; never a nested array on the opportunity record) --------
    rule("APPLICATIONS - when the candidate applied, how, and what came back")
    opps_by_id = {o.get("id"): o for o in opps}
    cover_letters_by_id = {c["id"]: c for c in load("cover_letters.jsonl") if c.get("id")}
    apps = [(opps_by_id.get(a.get("opp_id"), {}), a) for a in load("applications.jsonl")]
    if not apps:
        print("  None recorded.")
    else:
        by_status = collections.Counter(a.get("status") for _, a in apps)
        by_method = collections.Counter(a.get("method") for _, a in apps)
        print("  %d application record(s)" % len(apps))
        print("  by status: " + ", ".join("%s=%d" % (k, v) for k, v in sorted(by_status.items())))
        print("  by method: " + ", ".join("%s=%d" % (k, v) for k, v in sorted(by_method.items())))
        print("")
        # ⭐ States & Views V1 §3c — the buckets are the ENDING vocabulary, not the raw status:
        # heard (rejected/advanced) · closed on silence (closed, plus resolved-aged — an
        # application past the ATS window that nobody confirmed a close on: COUNTED as no
        # answer, the row itself never mutated, exactly NO_RESPONSE_AFTER's own existing rule
        # for outreach) · live (still within the window) · withdrawn · expired · unrecorded —
        # the last three EXCLUDED from every rate and each printed with its own count.
        # Response rate = heard / (heard + closed on silence). Reuses your_move.ended_because()
        # — one derivation, never a second reading of the same fields.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import your_move as _ym
        import config_keys as _ck
        import profile as _profile_mod
        try:
            _silence_days, _ = _ck.describe(_profile_mod.config(), _ck.ATS_SILENCE_DAYS)
        except Exception:                                   # noqa: BLE001 — report, never crash
            _silence_days = _ck.ATS_SILENCE_DAYS_DEFAULT
        by_opp_apps = collections.defaultdict(list)
        for _o, _a in apps:
            if _a.get("opp_id"):
                by_opp_apps[_a["opp_id"]].append(_a)
        heard, closed_silence = [], []
        live_bucket, withdrawn_b, expired_b, unrecorded_b = [], [], [], []
        for oid, opp_apps in by_opp_apps.items():
            o = opps_by_id.get(oid, {})
            newest = sorted(opp_apps, key=lambda a: str(a.get("date") or ""))[-1]
            reason = _ym.ended_because(o, opp_apps)
            status = newest.get("status")
            if reason == "rejected" or status == "advanced":
                heard.append((o, newest))
            elif reason == "closed-silence":
                closed_silence.append((o, newest))
            elif reason == "withdrawn":
                withdrawn_b.append((o, newest))
            elif reason == "expired":
                expired_b.append((o, newest))
            elif reason == "unrecorded":
                unrecorded_b.append((o, newest))
            elif status in ("submitted", "acknowledged"):
                anchor = newest.get("status_on") or newest.get("date")
                age = days_since(anchor) if anchor else None
                if age is not None and age >= _silence_days:
                    closed_silence.append((o, newest))   # resolved-aged — counted, not mutated
                else:
                    live_bucket.append((o, newest))
        print("  Response rate (heard / (heard + closed on silence)): %s"
              % pct(len(heard), len(heard) + len(closed_silence)))
        print("  heard=%d · closed-on-silence=%d (incl. resolved-aged) · live=%d"
              % (len(heard), len(closed_silence), len(live_bucket)))
        print("  excluded from every rate — withdrawn=%d · expired=%d · unrecorded=%d"
              % (len(withdrawn_b), len(expired_b), len(unrecorded_b)))
        if unrecorded_b:
            print("    unrecorded: %s" % ", ".join(sorted(o.get("id", "?")
                                                          for o, _a in unrecorded_b)))
        # Does sending a cover letter correlate with hearing back? `cover_letter_attached`
        # retired with the nested array; "attached" is now "cover_letter_id is non-null"
        # (design §1's own rule) — the three-way yes/no/unrecorded split narrows to two,
        # since nothing distinguishes a recorded "no cover letter" from an unrecorded one
        # any more.
        withcl = [a for _, a in apps if a.get("cover_letter_id")]
        nocl = [a for _, a in apps if not a.get("cover_letter_id")]
        print("  Cover letter linked: %d yes / %d unrecorded" % (len(withcl), len(nocl)))
        if len(withcl) < MIN_SAMPLE or len(nocl) < MIN_SAMPLE:
            print("    (too few recorded either way to compare against response rate yet)")
        print("")
        for o, a in sorted(apps, key=lambda t: (t[1].get("date") or "9999")):
            name = companies.get(o.get("company_id"), {}).get("name", o.get("company_id"))
            age = days_since(a.get("date"))
            age_s = "%3d days ago" % age if age is not None else "  no date  "
            print("  %-11s %-13s %-34s %s" % (a.get("date") or "(none)", a.get("status"), name[:34], age_s))
            cl = cover_letters_by_id.get(a.get("cover_letter_id"))
            if cl and cl.get("cover_letter"):
                print("              cover letter: %s" % cl["cover_letter"])
            if a.get("note"):
                print("              %s" % a["note"][:150])

    # ---- 3. Outreach: who we connected with, and did they reply? -----------
    rule("OUTREACH - who the candidate connected with, and whether they replied")
    # ADR-031 B3 — the top-level touches store, joined by opp_id; never a nested array.
    rows = [(opps_by_id.get(t.get("opp_id"), {}), t) for t in load("touches.jsonl")]
    if not rows:
        print("  None recorded.")
    else:
        sent = [(o, x) for o, x in rows if x.get("status") == "sent"]
        replied = [(o, x) for o, x in sent if x.get("outcome") in ("replied", "meeting-booked")]
        print("  %d outreach record(s); %d sent" % (len(rows), len(sent)))
        print("  Reply rate: %s" % pct(len(replied), len(sent)))
        print("")
        for o, x in sorted(sent, key=lambda t: t[1].get("date") or ""):
            # dev #477 / public #116 — a channel-scoped touch (opp_id null, channel_id set)
            # is a shape validate_data's exactly-one-of rule explicitly ACCEPTS (public #53):
            # a touch anchored to a relationship rather than any one role. `o` is then `{}`
            # (opps_by_id.get(None) misses) and company_id is None, so the company-name path
            # resolves to None. Falling back to the channel's own label keeps the row in the
            # report instead of crashing and silently dropping every section after it.
            name = companies.get(o.get("company_id"), {}).get("name", o.get("company_id"))
            if name is None:
                chan_id = x.get("channel_id")
                name = ("via " + channels.get(chan_id, {}).get("label", chan_id)) if chan_id \
                    else "(no opp/channel)"
            age = days_since(x.get("date"))
            print("  %-11s %-14s %-26s %s" % (
                x.get("date") or "(none)", x.get("outcome") or "?", (x.get("to") or "")[:26], name[:26]))
            if age is not None and age >= 7 and x.get("outcome") == "awaiting":
                print("              ^ %d days silent" % age)

    # ---- 3b. WHAT ACTUALLY WORKS: cuts by medium / touch type / recipient ---
    #
    # THE BINDING DENOMINATOR IS *RESOLVED* SENDS, NOT SENDS. The 12 touches from
    # 2026-07-31 are all still `awaiting` — that is n=0 for rating, not n=12. Printing
    # "12 connection notes sent" and letting a reader treat it as evidence is exactly the
    # dishonest failure this section has to avoid.
    sent_rows = [(o, x) for o, x in rows if x.get("status") == "sent"]

    # ⭐ dev #834 (M2): the resolution rule and the win test are MODULE-level (`touch_resolution`,
    # `touch_is_win`, `NO_RESPONSE_AFTER`), so the NETWORK section printed first and every cut below
    # can never disagree about what "resolved" or "a win" means. These are thin names for them.
    def resolution(x):
        """resolved / awaiting / bounced / undeliverable-unknown."""
        return touch_resolution(x)

    def is_win(x):
        return touch_is_win(x)

    def cut(field, title, rows=None, quiet=False):
        rows = sent_rows if rows is None else rows
        buckets = {}
        for o, x in rows:
            v = x.get(field) or "unknown"
            if v == "unknown":
                continue           # excluded from every rate; counted separately below
            b = buckets.setdefault(v, {"sent": 0, "resolved": 0, "win": 0,
                                       "awaiting": 0, "bounced": 0, "unverifiable": 0})
            b["sent"] += 1
            st = resolution(x)
            if st in ("resolved", "resolved-aged"):
                b["resolved"] += 1
                if is_win(x):
                    b["win"] += 1
            elif st == "bounced":
                b["bounced"] += 1
            elif st == "undeliverable-unknown":
                b["unverifiable"] += 1
            else:
                b["awaiting"] += 1
        if quiet:
            return buckets     # silent recompute for a caller (e.g. recommend()) — no printing
        skipped = sum(1 for _o, x in rows if (x.get(field) or "unknown") == "unknown")
        print("\n  %s" % title)
        if not buckets:
            print("    (nothing classified yet)")
        for k, b in sorted(buckets.items(), key=lambda t: -t[1]["sent"]):
            rate = pct(b["win"], b["resolved"])
            print("    %-26s %2d sent · %2d resolved · %s"
                  % (k, b["sent"], b["resolved"], rate))
            detail = []
            if b["awaiting"]:
                detail.append("%d awaiting" % b["awaiting"])
            if b["bounced"]:
                detail.append("%d BOUNCED (excluded)" % b["bounced"])
            if b["unverifiable"]:
                detail.append("%d deliverability unverified (excluded)" % b["unverifiable"])
            if b["resolved"] < MIN_SAMPLE:
                detail.append("need %d more resolved to rate" % (MIN_SAMPLE - b["resolved"]))
            if detail:
                print("    %-26s   %s" % ("", " · ".join(detail)))
        if skipped:
            print("    (%d row(s) with %s='unknown' excluded from this cut. `scripts/reconcile.py`"
                  % (skipped, field))
            print("     recovered every one the MAILBOX could prove; what remains is LinkedIn-only")
            print("     traffic with no email notification — that needs a browser session.)")
        return buckets

    rule("OUTREACH — WHAT ACTUALLY WORKS")
    print("  A 'win' is replied · meeting-booked · accepted. The DENOMINATOR is RESOLVED sends,")
    print("  not sends: an `awaiting` row is not yet evidence. `awaiting` older than %d days is" % NO_RESPONSE_AFTER)
    print("  counted as resolved (computed here — the row itself is never mutated).")
    print("  BOUNCED rows are excluded entirely; a bounce that reads as a non-reply would poison")
    print("  every rate below. So are pattern-inferred emails whose delivery is unknown.")
    print("  ⚠️ medium/touch_type/recipient_role are only reliable for rows after 2026-08-02;")
    print("     earlier rows were backfilled from contemporaneous record where one existed.")

    cut("medium", "BY MEDIUM — the question the candidate actually asked")
    cut("touch_type", "BY TOUCH TYPE — a chase and a first touch are not the same bet")
    cut("recipient_role", "BY RECIPIENT — who is worth writing to")

    first = [(o, x) for o, x in sent_rows if x.get("touch_type") == "first-touch"]
    fres = [(o, x) for o, x in first if resolution(x) in ("resolved", "resolved-aged")]
    fwin = [(o, x) for o, x in fres if is_win(x)]
    print("\n  HEADLINE — FIRST TOUCHES ONLY (chases and replies inflate a pooled rate)")
    print("    %d first touches · %d resolved · %s" % (len(first), len(fres), pct(len(fwin), len(fres))))

    camps = {}
    for o, x in sent_rows:
        if x.get("campaign_id"):
            camps.setdefault(x["campaign_id"], []).append((o, x))
    if camps:
        print("\n  BY CAMPAIGN — a multi-touch push is one bet, not N independent ones")
        for cid, items in sorted(camps.items()):
            media = sorted({x.get("medium") for _o, x in items})
            people = len({(x.get("to") or "").split("(")[0].strip() for _o, x in items})
            wins = sum(1 for _o, x in items if is_win(x))
            print("    %-26s %d touches · %d people · %s · %d win(s)"
                  % (cid, len(items), people, "+".join(m or "?" for m in media), wins))

    if args.recommend:
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts"))
            import profile as _prof
            # public #71 — this used to pass the POOLED medium cut (every touch_type mixed
            # together: first touches, chases, replies). `communications.default_sequence`
            # configures only the FIRST-touch media (see outreach-drafter.md's "CHANNEL
            # DEFAULT" section — "sent together" describes the first outreach touch, not
            # every later chase on the same thread). A chase's reply rate is not evidence
            # about a first-touch medium choice — chases go to people already engaged, so
            # pooling let a medium used mostly for chases outscore one used mostly for cold
            # first touches, and CONTRADICTED the configured default on a comparison that was
            # never apples-to-apples. Re-use the SAME `first` filter the headline above
            # already applies, via `cut(..., quiet=True)` rather than a second computation.
            first_touch_medium_stats = cut("medium", "", rows=first, quiet=True)
            recommend(first_touch_medium_stats, _prof.comms())
        except Exception as exc:
            print("\n  (could not load communications config: %s)" % exc)

    # ---- 4. Paths: which kind of contact actually converts? ----------------
    # ADR-031 B1 — `opportunities.contacts[]` is retired; a role's people now join through
    # `involvements.opp_id`, and `path_type` lives on the involvement, never on `people`.
    rule("CONTACT PATHS - which kind of connection converts")
    verdict_by_opp = {o.get("id"): o.get("verdict") for o in opps}
    paths = collections.defaultdict(lambda: {"total": 0, "pursued": 0})
    for inv in involvements:
        opp_id = inv.get("opp_id")
        if not opp_id:
            continue
        pt = inv.get("path_type") or "(unset)"
        paths[pt]["total"] += 1
        if verdict_by_opp.get(opp_id) == "pursue":
            paths[pt]["pursued"] += 1
    for pt, d in sorted(paths.items(), key=lambda kv: -kv[1]["total"]):
        print("  %-18s %3d contacts -> %s on roles we pursued" % (pt, d["total"], pct(d["pursued"], d["total"])))
    print("")
    print("  CAVEAT: path_type is unreliable on backfilled rows - the markdown")
    print("  import typed nearly everything 'recruiter' regardless of what it was.")
    print("  Trust this only for contacts added after 2026-07-21.")

    # ---- 5. What the data still can't answer -------------------------------
    rule("WHAT THIS STILL CANNOT TELL YOU")
    print("  - Time-to-first-response: needs a responded_on date on outreach and an")
    print("    outcome date on applications. The fields exist; almost nothing fills")
    print("    them yet, because replies get read in Gmail and never written back.")
    print("  - Whether a warm intro beats a cold application: only %d contacts survive"
          % sum(d["total"] for d in paths.values()))
    print("    the placeholder purge, and the pursued/not split is confounded by")
    print("    the candidate choosing which roles to pursue in the first place.")
    stage_counts = {}
    for o in opps:
        s = o.get("stage")
        stage_counts[s] = stage_counts.get(s, 0) + 1

    # ⚠️ 2026-08-02: this used to print, unconditionally, "`stage` never goes past
    # 'contacted' on any record" — a HARDCODED sentence that was true when written and
    # false by the time it was read. The 08/02 weekly review quoted it as a finding and
    # proposed a backfill for records that were already correct. A script asserting a
    # stale fact is worse than a tracker doing it, because the output reads as measured.
    # Now computed from the data every run.
    deep = {s: n for s, n in stage_counts.items()
            if s in ("screening", "interviewing", "offer") and n}
    if deep:
        detail = ", ".join("%s=%d" % (s, n) for s, n in sorted(deep.items()))
        print("  - Interview conversion: PARTIALLY measurable — %s." % detail)
        print("    Still thin, and `stage` is advanced by hand, so treat it as a floor")
        print("    on how far roles actually got, not a count.")
    else:
        print("  - Interview conversion: no record has advanced past 'contacted', so the")
        print("    funnel below that is unmeasured, not empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
