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


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    out = []
    fh = open(path, encoding="utf-8")
    try:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    finally:
        fh.close()
    return out


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
                    help="--by step only: the replay's last day (default: today).")
    ap.add_argument("--window-from", default=None, metavar="YYYY-MM-DD",
                    help="--by step only: the replay's first day (default: as-of minus %d days)."
                         % DEFAULT_WINDOW_DAYS)
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
    NO_RESPONSE_AFTER = 14   # an `awaiting` row older than this is COUNTED as resolved,
                             # but the row is NEVER mutated — the inference stays in the report

    sent_rows = [(o, x) for o, x in rows if x.get("status") == "sent"]

    def resolution(x):
        """resolved / awaiting / bounced / undeliverable-unknown."""
        if x.get("delivery") == "bounced":
            return "bounced"
        oc = x.get("outcome")
        if oc in TERMINAL_TOUCH_OUTCOMES:
            return "resolved"
        age = days_since(x.get("date"))
        if oc == "awaiting" and age is not None and age >= NO_RESPONSE_AFTER:
            return "resolved-aged"
        # A pattern-inferred address with unknown delivery cannot distinguish silence from
        # a bounce. It is evidence of NOTHING either way and must not sit in a denominator.
        if (x.get("medium") or "").startswith("email") and \
           x.get("address_status") == "pattern-inferred" and x.get("delivery") == "unknown":
            return "undeliverable-unknown"
        return "awaiting"

    def is_win(x):
        return x.get("outcome") in ("replied", "meeting-booked", "accepted")

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
