#!/usr/bin/env python3
"""The sourcing queue: which channels are due for review, from data/channels.jsonl.

Turns sourcing from "remember to check Dice" into a data-driven loop. Run at the
start of every daily/weekly run: it lists the active-search channels that are due
(cadence + last_reviewed), the recruiter relationships that have gone quiet, and
after reviewing a channel you stamp its last_reviewed so it drops off the queue.

    python3 scripts/channels_due.py                 # what's due today
    python3 scripts/channels_due.py --stamp <id>    # mark <id> reviewed today (--date YYYY-MM-DD to override)
    python3 scripts/channels_due.py --board-decision --run <id> [--attended] [--kind company|board] [--today D]
                                                    # may a board sweep start? Decides PER KIND (company
                                                    # career pages on company_days, job boards on
                                                    # board_days; O4) AND writes one `pass board
                                                    # dispatched` row per dispatched kind (dev #770-4);
                                                    # --dry-run asks without writing. Exit 0 dispatch,
                                                    # 1 not today, 3 refused.

IMPORTANT — what "review a channel" means (the 2026-07-20 clarification):
  Active-search channels are reviewed by DIRECT SEARCH on the source's own job
  pages (LinkedIn Jobs, Dice, Indeed, BuiltIn) plus organizations' own career
  pages/ATS — NOT by reading the source's algorithmic ALERT EMAILS, which are
  noise. Recruiters are reviewed on-inbound (a human reached out) and by not
  letting an open thread go silent.

Date handling: pass --today YYYY-MM-DD (the runtime forbids Date.now-style calls
being assumed; scripts should be handed the date). Defaults to the system date.

Targets Python 3.9+, stdlib only.
"""

import argparse
import datetime
import json
import os

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
from _atomic import write_jsonl, write_json
import touches as _touches
# public #98 — your_move.py is the SINGLE OWNER of "which group does a channel plan belong
# in" (ADR-031 §14, your_move.py's own docstring: "generate_dashboard.py must never
# re-derive group membership"). This queue used to have zero awareness of `next_touch` at
# all, so a plan your_move.py put in its 'now' group (dashboard: overdue) rendered here as
# nothing due — the exact disagreement #98 reports. Never re-derive the fulfilment rule;
# only read its answer (now_channel_plans below).
import your_move as _ym

ROOT = _profile_root()
DATA = os.path.join(ROOT, "data")
CH = os.path.join(DATA, "channels.jsonl")

CADENCE_DAYS = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}
# "monthly" added 2026-08-02 with the anchor-employer cadence cut. Without it the
# lookup missed and `if not d: continue` dropped the channel from the queue SILENTLY —
# a cadence change would have read as full coverage while nothing was ever swept.
QUIET_RECRUITER_DAYS = 10  # a recruiter relationship untouched this long is worth a nudge


def load():
    return [json.loads(l) for l in open(CH, encoding="utf-8") if l.strip()]


def load_opps():
    """Live pipeline — the other place a real channel touch gets recorded."""
    path = os.path.join(DATA, "opportunities.jsonl")
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def save(chans):
    # Atomic: this runs unattended and rewrites the whole channel store.
    write_jsonl(CH, chans)


def as_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# THE ONE DEFINITION of sourcing-channel review state and channel yield — dev #148.
#
# This logic used to live inline in main(), which made this script the ONLY surface that
# could answer "which channels are due, and what has each one produced?" — the strategy
# review's central question, reachable by CLI alone while the dashboard rendered none of it.
# generate_dashboard.py now imports these two functions rather than re-deriving them (the
# same single-owner rule your_move.py establishes for Your Move membership: a consumer that
# re-derives a classification eventually disagrees with it).
# ─────────────────────────────────────────────────────────────────────────────

# Review states, in the order a strategy review reads them.
REVIEW_STATES = ("due", "current", "on-inbound", "unscheduled", "retired")


def review_rows(chans, today):
    """[(channel, state, detail)] for every SOURCING channel (recruiter/referral
    relationship channels are excluded — they are reviewed on-inbound and live on the
    Network surface, not the sourcing queue).

    state ∈ REVIEW_STATES; detail is a dict:
        next_due   ISO date the next review is due (None where no schedule applies)
        days_over  int, only when state == "due" and a due date exists
        why        one human-readable line ("never reviewed", "due 2026-08-10 (3 days over)",
                   the unrecognized-cadence warning, ...)

    ⚠️ An unrecognized cadence is state "unscheduled", never a silent skip — the 2026-08-02
    incident: "monthly" was set in data before CADENCE_DAYS knew it, and `if not d: continue`
    dropped the channel from the queue while everything read as full coverage.
    """
    rows = []
    for c in chans:
        if c.get("type") in ("recruiter", "referral"):
            continue
        if c.get("relationship_status") == "retired":
            rows.append((c, "retired", {"next_due": None, "why": "retired — deliberately "
                                        "no longer reviewed or swept"}))
            continue
        cad = c.get("review_cadence")
        d = CADENCE_DAYS.get(cad)
        if not d:
            if cad == "on-inbound":
                rows.append((c, "on-inbound",
                             {"next_due": None, "why": "reviewed on inbound — no schedule "
                              "by design"}))
            else:
                rows.append((c, "unscheduled",
                             {"next_due": None, "why": "unrecognized review_cadence %r — "
                              "NOT being scheduled. Add it to CADENCE_DAYS." % (cad,)}))
            continue
        lr = as_date(c.get("last_reviewed"))
        if lr is None:
            rows.append((c, "due", {"next_due": None, "why": "never reviewed"}))
            continue
        due_date = lr + datetime.timedelta(days=d)
        if due_date <= today:
            days_over = (today - due_date).days
            rows.append((c, "due", {"next_due": due_date.isoformat(),
                                    "days_over": days_over,
                                    "why": "due %s%s" % (due_date.isoformat(),
                                           " (%d days over)" % days_over
                                           if days_over else "")}))
        else:
            rows.append((c, "current", {"next_due": due_date.isoformat(),
                                        "why": "next %s" % due_date.isoformat()}))
    return rows


def now_channel_plans(chans, root, today_iso):
    """{channel_id: (channel, why)} for every channel `your_move.classify_channels` puts in
    its 'now' group — a `next_touch` plan that is due (§14). This is never a second
    computation of the fulfilment rule (public #98: the two used to disagree because this
    file had no `next_touch` awareness at all); it reads `your_move`'s own answer and
    renders it, exactly as `review_rows()` above is this file's single owner for cadence-
    scheduled review."""
    messages = _ym._load_jsonl(root, "messages.jsonl")
    involvements = _ym._load_jsonl(root, "involvements.jsonl")
    classified = _ym.classify_channels(chans, messages, today=today_iso,
                                       involvements=involvements)
    out = {}
    for c, state, touch, evidence in classified:
        if state != "now":
            continue
        nt = c.get("next_touch") or {}
        why = "next_touch plan due %s (%s)" % (nt.get("date"),
                                                evidence or "no derived touch yet")
        out[c.get("id")] = (c, why)
    return out


def load_companies():
    path = os.path.join(DATA, "companies.jsonl")
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def budget_failure_since(recs, company_id):
    """The ISO date a company's CURRENT run of consecutive `budget-exhausted` polls began, or None when its latest
    poll did not end that way. The twin of `journal.feed_board_failure_since` for the one host-class code that
    `feed_review` treats as a board matter once it repeats (dev #820 / public #175, B4.3): a switched-off event is
    not a poll, as in `journal.feed_repeat_failures`, so it neither counts nor breaks the streak."""
    import journal as _journal
    since = None
    for ev in reversed([e for e in _journal.feeds_events(recs) if not e.get("off")]):
        if (ev.get("companies_not_covered") or {}).get(company_id) == "budget-exhausted":
            since = str(ev.get("at") or "")[:10]
        else:
            break
    return since


def feed_review(chans, companies, recs, today, feeds_on=True):
    """dev #751 (design §3.7 as amended by review B1): `{channel_id: (state, text)}` for every
    company-site channel linked to a company that polls a feed. `state` is

      covered   TODAY's `feeds` event polled the company and did not list it as not covered: the feed
                IS this channel's review (`feed_poll.py` stamped `last_reviewed`), so it is not listed
                for the browser;
      due       the feed failed with a BOARD code (404, not the documented shape, redirect, odd
                status) and no browser review has stamped the channel since the streak began: listed
                DUE regardless of cadence -- this is the fallback #751's 'a failing feed is loud'
                requires;
                dev #820 / public #175 (B4.3, CV2): a company the poll's own deadline cut off
                (`budget-exhausted`) on its last TWO polls (`journal.feed_repeat_failures`) is DUE the same
                way, until one browser review is stamped after the streak began. `budget-exhausted` is not a
                host failure: the machine reached the vendor and the poll ran out of time, so the feed has
                not looked at this company for two runs and the browser is the only thing that will;
      cadence   everything else, and the reason is in `text`: no `feeds` event yet today, a HOST failure
                (the machine cannot reach the vendor: a monthly page must not become a daily browser
                visit), a SINGLE budget-exhausted, or a streak a browser review has already answered.

    Pure over what it is handed: today's events and the journal's streak helper come from `recs`."""
    import journal as _journal
    by_company = {c.get("id"): c for c in companies}
    linked = [ch for ch in chans if ch.get("type") == "company-site" and ch.get("company_id")
              and isinstance((by_company.get(ch.get("company_id")) or {}).get("ats"), dict)]
    if not feeds_on:                                   # dev #774: the switch is off, so no page is covered by a feed
        return {ch["id"]: ("cadence", "company feeds are turned off (sourcing.feeds.enabled)") for ch in linked}
    # a switched-off event (dev #774) lists nothing as failed and polled nothing: it is never a poll that covered a page
    events = [e for e in _journal.feeds_events(recs, on=today.isoformat()) if not e.get("off")]
    if not events:
        return {ch["id"]: ("cadence", "no feed poll yet today") for ch in linked}
    failed = events[-1].get("companies_not_covered") or {}
    repeated_budget = set(_journal.feed_repeat_failures(recs, "budget-exhausted", 2))   # dev #820 (B4.3)
    polled = {c.get("id") for c in companies
              if isinstance(c.get("ats"), dict) and c.get("status") != "passed"}
    out = {}
    for ch in linked:
        cid = ch["company_id"]
        if cid in failed:
            code = failed[cid]
            if code in _journal.FEED_BOARD_CODES:
                since = _journal.feed_board_failure_since(recs, cid)
                lr = as_date(ch.get("last_reviewed"))
                if since and lr is not None and lr >= datetime.date.fromisoformat(since):
                    out[ch["id"]] = ("cadence", "feed failed (%s) but the page was reviewed since "
                                     "%s" % (code, since))
                else:
                    out[ch["id"]] = ("due", "feed not covered: %s" % code)
            elif code == "budget-exhausted" and cid in repeated_budget:
                since = budget_failure_since(recs, cid)
                lr = as_date(ch.get("last_reviewed"))
                if since and lr is not None and lr >= datetime.date.fromisoformat(since):
                    out[ch["id"]] = ("cadence", "feed ran out of time (budget-exhausted) on consecutive polls "
                                     "but the page was reviewed since %s" % since)
                else:
                    out[ch["id"]] = ("due", "feed not covered: budget-exhausted, 2 polls running")
            else:
                out[ch["id"]] = ("cadence", "feed not covered (%s: the machine or the poll's own "
                                 "budget, not this board)" % code)
        elif cid in polled:
            out[ch["id"]] = ("covered", "covered by the %s feed" % by_company[cid]["ats"].get("vendor"))
        else:
            out[ch["id"]] = ("cadence", "not polled today")
    return out


def load_cfg():
    """`config.json` as a dict; `{}` when it cannot be read (the callers' feed switch then reads
    its registered default and the route preference its own)."""
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def due_state(chans, companies, recs, cfg, today):
    """The ONE definition of which channels are due for review today, after the feed's word
    (dev #751) is folded in -- extracted from `main()` (dev #770-4) so the board worklist below and
    the printed queue cannot disagree. Pure over what it is handed. Returns a dict:

      due, upcoming     [(channel, why)] / [(channel, date)], feed-adjusted: a channel the feed
                        covered today is in neither; a board-code feed failure is DUE whatever its
                        cadence. NOT yet split by `manual-candidate` (that is a presentation split
                        `main()` keeps, and `board_worklist` applies through `route`).
      retired           [channel]
      covered           [channel] covered by today's feed poll
      feed              `feed_review()`'s `{channel_id: (state, text)}`
      cadence_warnings  printable lines, one per unrecognised review_cadence (never a silent skip)
      feeds_problem     a printable line, or None, about the `sourcing.feeds` switch"""
    import config_keys as _config_keys
    due, upcoming, retired, cadence_warnings = [], [], [], []
    # Classification is review_rows()'s alone -- dev #148. A retired channel stays in the file (its
    # sighting history must keep resolving for validate_data.py and funnel_report.py) but must never
    # be queued for review again (2026-08-02, the Dice/CareerBuilder retirement); an unrecognized
    # cadence must WARN, not silently skip.
    for c, state, detail in review_rows(chans, today):
        if state == "retired":
            retired.append(c)
        elif state == "due":
            due.append((c, detail["why"]))
        elif state == "current":
            upcoming.append((c, datetime.date.fromisoformat(detail["next_due"])))
        elif state == "unscheduled":
            cadence_warnings.append("  !! WARNING: channel %r has unrecognized review_cadence %r — "
                                    "NOT being scheduled. Add it to CADENCE_DAYS."
                                    % (c["id"], c.get("review_cadence")))
    feeds_on, feeds_problem = _config_keys.feeds_enabled(cfg if isinstance(cfg, dict) else {})
    feed = feed_review(chans, companies, recs, today, feeds_on=feeds_on)
    covered = [c for c in chans if feed.get(c.get("id"), ("",))[0] == "covered"
               and c.get("relationship_status") != "retired"]
    cov_ids = {c["id"] for c in covered}
    due = [(c, why) for c, why in due if c["id"] not in cov_ids]
    upcoming = [(c, dd) for c, dd in upcoming if c["id"] not in cov_ids]
    for c in chans:
        st = feed.get(c.get("id"))
        if st and st[0] == "due" and c.get("relationship_status") != "retired":
            if any(cc["id"] == c["id"] for cc, _w in due):
                due = [(cc, ("DUE (%s); %s" % (st[1], w)) if cc["id"] == c["id"] else w)
                       for cc, w in due]
            else:
                due.append((c, "DUE (%s)" % st[1]))
            upcoming = [(cc, dd) for cc, dd in upcoming if cc["id"] != c["id"]]
    return {"due": due, "upcoming": upcoming, "retired": retired, "covered": covered,
            "feed": feed, "cadence_warnings": cadence_warnings,
            "feeds_problem": ("  !! WARNING: " + feeds_problem) if feeds_problem else None}


# dev #770-4 (design-employer-discovery.md §5.3) -- the channel types a board sweep can visit. A
# `recruiter`, `referral` or `alert-email` row, and every `next_touch` plan, is NOT board work.
BOARD_TYPES = ("job-board", "aggregator", "company-site")


# dev #811 / public #170 (design-sweep-partial-failure.md N2) -- the route mechanisms the board
# sweeper's own tool allowlist can drive: `plugin` (a site plugin's tools) and `browser` (the built-in
# browser pane's `mcp__Claude_Browser__*` tools). `agents/board-sweeper.md`'s `tools:` line lists NO
# `mcp__claude-in-chrome__*` tool, so `chrome` is NOT here: dispatching a sweeper to a route it holds no
# tool for spends the kind's slot on a pass that can only fail. Granting the extension to the sweeper is
# a capability change with its own review; when it lands this constant moves with it, and
# `TestSweeperCanUseRoute` (which reads the `tools:` line) fails until it does.
SWEEPER_MECHANISMS = ("plugin", "browser")


def _capable(mechanism, caps):
    """Can THIS machine run a `route.route()` mechanism with a tool the board sweeper's allowlist
    could hold? `plugin:<name>` is taken as runnable (whether the plugin is installed is not probed --
    UNDETERMINED, as today). `chrome` needs `caps["chrome"]`. `browser` needs `caps["pane"]`, the
    Browser PANE probe (`whoami.probe_with_pane()`), NOT `caps["browser"]`: `whoami._has_browser()`
    falls back to `_has_chrome()`, so a machine with only the Claude in Chrome extension reports
    `browser=True` and would dispatch a sweeper that has no pane tool (dev #811 / public #170, N2).
    A `caps` without `pane` reads as no pane, loudly (a refused dispatch), never as the fallback.
    `feed:<vendor>` is not a mechanism the sweeper acts on."""
    if mechanism.startswith("plugin:"):
        return True
    if mechanism == "browser":
        return bool(caps.get("pane"))
    return bool(caps.get("chrome")) if mechanism == "chrome" else False


def _runnable(mechanism, caps):
    """Can the BOARD SWEEPER use a `route.route()` mechanism on THIS machine: the machine can run it
    (`_capable`) AND `SWEEPER_MECHANISMS` names it (dev #811 / public #170, N2). A mechanism the
    machine has but the sweeper holds no tool for (`chrome`) is not runnable."""
    return mechanism.split(":", 1)[0] in SWEEPER_MECHANISMS and _capable(mechanism, caps)


def sweeper_filtered(channel, cfg, caps):
    """dev #811 / public #170 (N2) -- the mechanisms of this channel's route that the MACHINE can run
    but the board sweeper's allowlist cannot (`_capable` and not `_runnable`), in route order; `[]`
    when there are none. A channel with no runnable mechanism and a non-empty answer here is stuck
    because of `SWEEPER_MECHANISMS`; one with `[]` is stuck because the capability itself is absent.
    `route.RouteError` from an unreadable preference or access propagates, as in `board_worklist`."""
    import route as _route
    requirement, _legacy = _route.parse_access(channel.get("access"))
    mechs = _route.route(requirement, _route.preference(cfg), channel.get("id"), cfg)
    return [m for m in mechs if _capable(m, caps) and not _runnable(m, caps)]


def _board_admissible(c):
    """dev #785 (design-sourcing-schedule.md §5.2) -- the ONE predicate for "is this channel
    board-sweeper work", by FIELD: `(admitted, warning)`. A channel is admitted exactly when (1) its
    `type` is `job-board`, `aggregator` or `company-site`; (2) its `relationship_status` is not
    `retired`; and (3) `route.parse_access(access)` succeeds and is not in `route.NOT_BROWSABLE`
    (`human`, `n/a`, `manual-candidate`). An UNREADABLE `access` is not admitted and carries a printable
    `warning` (named, never silently dropped); every other refusal has `warning` None. `board_worklist`
    (rules 1-3) and `schedule_due` (which channels the sweep schedule gates) both call this, so "what the
    sweeper is offered" and "what the schedule gates" cannot drift apart; `posture._career_pages` (the
    share line's population) calls it too, by a lazy import."""
    import route as _route
    if c.get("type") not in BOARD_TYPES or c.get("relationship_status") == "retired":
        return False, None
    try:
        requirement, _legacy = _route.parse_access(c.get("access"))
    except _route.RouteError as e:
        return False, ("  !! WARNING: channel %r has an unreadable access (%s) — NOT in the "
                       "board worklist." % (c.get("id"), e))
    if requirement in _route.NOT_BROWSABLE:
        return False, None
    return True, None


def schedule_due(chans, companies, recs, cfg, today, sched, attended=False):
    """dev #785 / public #167 (design-sourcing-schedule.md §5.2, §5.3) -- THE one owner of "is this
    channel due TODAY, given its pass". The bare listing, `board_worklist` and `--board-decision` all
    call it; none decides a sweep day itself. `sched` is `posture.sweep_schedule(...)`'s `{kind: K}`
    (required: `None` is a `ValueError`, never read as "no schedule").

    Returns `due_state()`'s dict, with `due`/`upcoming`/`cadence_warnings` adjusted, plus

      due        [(channel, why)]  DUE NOW: due by cadence or feed AND (not gated, or its pass is open)
      waiting    [(channel, kind, day_or_None, opens_on, why)]  gated, due, its pass closed today;
                 `day` is its split day (None unsplit), `opens_on` that bucket's next slot
      no_pass    [(channel, kind, why)]  gated, due, its kind is `off` on this posture
      blocked    [(channel, kind, why)]  gated, due, its kind is `unreadable` / `journal`
      schedule_problem  a printable line, or None, when any kind is `unreadable` / `journal`

    GATED = `_board_admissible` admits it. Every other due channel (`manual-candidate`, `human`,
    `n/a`, an unreadable `access`, a recruiter) stays in `due` EXACTLY as today: a person's task is
    never moved behind a sweep day. A gated channel's pass is its kind's bucket
    (`posture.split_day(id, K.split)` when the career-page split is on, else `"*"`); it is open when that
    bucket is due, or -- split channels only -- when `posture.nearer_chance` says today is strictly
    nearer its due date than its next split day (a `current` channel is then moved from `upcoming` to
    `due`). `attended=True` lifts the whole schedule: every kind open, no split, nothing waiting."""
    if sched is None:
        raise ValueError("schedule_due needs the sweep schedule (posture.sweep_schedule); None is "
                         "never read as 'no schedule'")
    import posture as _posture
    state = due_state(chans, companies, recs, cfg, today)
    due, upcoming = [], []
    waiting, no_pass, blocked = [], [], []
    warnings = list(state["cadence_warnings"])

    def bucket(c, K):
        """(day, key) of a gated company/board channel in K, or None when a split channel has no
        usable id. Unsplit: `(None, "*")`."""
        if not K["split"]:
            return None, "*"
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            return False
        day = _posture.split_day(cid, K["split"])
        return day, day

    for c, why in state["due"]:
        if attended or not _board_admissible(c)[0]:
            due.append((c, why))
            continue
        kind = sweep_kind(c)
        K = sched[kind]
        if K["state"] == "off":
            no_pass.append((c, kind, why))
        elif K["state"] in ("unreadable", "journal"):
            blocked.append((c, kind, why))
        else:
            b = bucket(c, K)
            if b is False:
                warnings.append("  !! WARNING: career-page channel %r has no usable id — NOT in any "
                                "split day, so NOT offered to any sweep." % (c.get("label") or "?",))
                continue
            day, key = b
            B = K["buckets"][key]
            if B["due"]:
                due.append((c, why))
            else:
                waiting.append((c, kind, day, B["next_slot"],
                                "swept today" if B["last"] == today else why))
    for c, next_due in state["upcoming"]:
        if not attended and _board_admissible(c)[0]:
            K = sched[sweep_kind(c)]
            if K["state"] in ("open", "closed") and K["split"]:
                b = bucket(c, K)
                if b is not False:
                    B = K["buckets"][b[1]]
                    if B["due"] and _posture.nearer_chance(next_due, today, B["next_slot"]):
                        due.append((c, "due %s, nearer than its next split day %s %s"
                                    % (next_due.isoformat(), _posture.weekday_name(B["next_slot"]),
                                       B["next_slot"].isoformat())))
                        continue
        upcoming.append((c, next_due))
    problems = [] if attended else [sched[k]["line"] for k in sched
                                    if sched[k]["state"] in ("unreadable", "journal")]
    out = dict(state)
    out.update({"due": due, "upcoming": upcoming, "cadence_warnings": warnings,
                "waiting": waiting, "no_pass": no_pass, "blocked": blocked,
                "schedule_problem": ("  !! SCHEDULE UNREADABLE: " + "; ".join(problems))
                if problems else None})
    return out


def board_worklist(chans, companies, recs, cfg, today, caps, *, sched, attended=False):
    """dev #770-4 -- the ONE definition of board-sweeper work, by FIELD. A channel is in it exactly
    when (1) its `type` is `job-board`, `aggregator` or `company-site`; (2) its `relationship_status`
    is not `retired`; (3) `route.parse_access(access)` is not in `route.NOT_BROWSABLE` (`human`,
    `n/a`, `manual-candidate`) -- rules 1-3 are `_board_admissible`; (4) `review_rows()` says `due`,
    or `feed_review()` says `due` (a board-code feed failure); and (5) `feed_review()` does not say
    `covered` today. (4) and (5) are `due_state()`'s, shared with the printed queue.

    dev #785 (design-sourcing-schedule.md §5.2): and (6) its pass is OPEN today -- `schedule_due`
    decides that, from `sched` (`posture.sweep_schedule`'s `{kind: K}`), a REQUIRED keyword argument:
    omitting it is a `TypeError` and `None` a `ValueError`, so a caller cannot skip the schedule by
    accident. A channel of a closed, off or unreadable kind, or whose split day is closed, is absent.
    `attended=True` lifts the schedule (never the worklist).

    Returns `(rows, unroutable, warnings)`. With `caps` (a `whoami.probe_with_pane()` dict), `rows` are
    `(channel, runnable_mechanisms, why)` for channels with at least one mechanism from
    `route.route()` this machine can run, and `unroutable` are `(channel, why)` for the rest. With
    `caps=None` nothing is routed: `rows` carries every channel the definition admits (mechanisms
    `[]`) and `unroutable` is empty -- the form `main()` uses for its warnings. `warnings` are
    printable lines (an unreadable `access` is named, never silently dropped). A
    `route.RouteError` from an unreadable route preference propagates: the caller refuses."""
    import route as _route
    state = schedule_due(chans, companies, recs, cfg, today, sched, attended=attended)
    pref = _route.preference(cfg) if caps is not None else None
    rows, unroutable, warnings = [], [], []
    for c, why in sorted(state["due"], key=lambda x: (x[0].get("last_reviewed") or "",
                                                       x[0].get("id") or "")):
        admitted, warning = _board_admissible(c)
        if warning:
            warnings.append(warning)
        if not admitted:
            continue
        requirement, _legacy = _route.parse_access(c.get("access"))
        if caps is None:
            rows.append((c, [], why))
            continue
        mechs = _route.route(requirement, pref, c.get("id"), cfg)
        runnable = [m for m in mechs if _runnable(m, caps)]
        if runnable:
            rows.append((c, runnable, why))
        else:
            unroutable.append((c, why))
    return rows, unroutable, warnings


def sweep_kind(channel):
    """Owner ruling O4: which board-sweeper kind a worklist channel belongs to, by its `type` --
    `company` for an employer career page (`company-site`), `board` for a job board or aggregator.
    None for any other type (not board work)."""
    import config_keys as _ck
    for kind in _ck.SWEEP_KINDS:
        if channel.get("type") in _ck.SWEEP_CHANNEL_TYPES[kind]:
            return kind
    return None


def _agent_budget(p, name, attended=False):
    """`max_agents_per_run` of posture `p` as `(ok, line)`: the board sweep is one `board-sweeper`
    agent, so on the UNATTENDED path a value below 1 means no sweep (a budget the posture sets for
    runs nobody is watching). The explicit attended form (dev #770, owner intent: posture levels
    govern only how often UNATTENDED runs search; `minimal` is the level where the user searches by
    hand) needs at least one agent whatever the posture caps, so `minimal`'s 0 does not stop
    `/jobsearch:search attended`. A value that is not an integer is unreadable either way: `ok` is
    None and the caller refuses, never reads it as a budget."""
    mx = p.get("max_agents_per_run") if isinstance(p, dict) else None
    if not isinstance(mx, int) or isinstance(mx, bool):
        return None, "max_agents_per_run unreadable on posture %s (%r)" % (name, mx)
    if mx < 1 and not attended:
        return False, "no agent budget (max_agents_per_run %d on posture %s)" % (mx, name)
    return True, ""


def board_decision(chans, companies, recs, cfg, today, run_id, dry_run, attended, caps,
                   root=None, fresh=False, kinds=None):
    """dev #770-4 (design §5.3), split by owner ruling O4 -- `channels_due.py --board-decision`:
    decide, PER SWEEP KIND, whether a board sweep starts, and WRITE one `pass board dispatched` row
    per dispatched kind (its `sweep` field names the kind) in the same call. Returns
    `(exit_code, lines)`.

    The two kinds are `company` (employer career pages, `company-site`, on `company_days`) and
    `board` (job boards and aggregators, on `board_days`). Each is decided against its own days and
    its own last-spent slot (`posture.board_spent_on(recs, kind)`), so a Monday company sweep never
    spends Tuesday's board slot, or the reverse.

      0  dispatch: at least one kind's gate holds and its worklist has a channel this machine can
         run. Its row is appended BEFORE this returns; if a row cannot be written the answer is 3
         and NO dispatch line (a dispatch never happens without its row).
      1  not today: for every kind, the gate is closed or the worklist is empty. When a kind's only
         due channels need a mechanism this machine lacks, its reason says so and NO row is written,
         so its slot stays open for a run on a machine that has one.
      3  refused: an unreadable posture, `company_days`, `board_days`, journal or route preference,
         or neither `--run` nor `--dry-run` (a decision that could say yes must be able to write).

    Printed: line 0 `BOARD DISPATCH yes <kinds>` or `BOARD DISPATCH no`, then every kind's reason
    joined by `; `; on a dispatch, `  worklist: <ids>` (exactly the dispatched kinds' channels: what
    board-sweeper is given) and `  <kind> worklist: <ids>` per dispatched kind.

    `recs` is the journal's rows (read once by the caller; `fresh=True` when `runs.jsonl` did not
    exist). `attended` (the explicit attended form only) lifts the schedule gate and the posture's
    `max_agents_per_run` cap (an attended sweep needs one agent, so `minimal`'s 0 does not stop it;
    a non-integer is still exit 3), never the worklist, and every row it writes carries `attended: true`, which spends no scheduled slot
    (`posture.board_spent_on`), so the scheduled sweep still runs on its day. `kinds` (`--kind`,
    `/jobsearch:search companies|boards`) limits the decision to those sweep kinds; None is both.
    `--dry-run` writes nothing."""
    import journal as _journal
    import posture as _posture
    import config_keys as _ck
    if not run_id and not dry_run:
        return 3, ["BOARD DISPATCH refused: --run <id> is required (the decision writes its own "
                   "dispatch row); use --dry-run to ask without writing"]
    wanted = tuple(kinds) if kinds else tuple(_ck.SWEEP_KINDS)
    unknown = [k for k in wanted if k not in _ck.SWEEP_KINDS]
    if unknown:
        return 3, ["BOARD DISPATCH refused: unknown sweep kind %s (one of %s)"
                   % (", ".join(map(repr, unknown)), ", ".join(_ck.SWEEP_KINDS))]
    name, p, err = _posture.load(root)
    if (err or p is None) and not attended:
        return 3, ["BOARD DISPATCH refused: posture unreadable (%s)" % err]
    # dev #785: THE schedule, read once for every kind (`posture.sweep_schedule`), then handed to the
    # worklist, so the decision and the printed queue answer from ONE place. An unreadable posture is
    # every kind `unreadable` there, which an attended decision lifts as it always did.
    sched = _posture.sweep_schedule(p, name, today, recs=recs, fresh=fresh, err=err, root=root)
    checks = [dict(_posture._checked(sched[k]), split=sched[k]["split"]) for k in _ck.SWEEP_KINDS]
    checks = [c for c in checks if c["sweep"] in wanted]
    bad = [c for c in checks if c["state"] in ("unreadable", "journal")]
    if bad and not attended:
        return 3, ["BOARD DISPATCH refused: %s" % "; ".join(c["line"] for c in bad)]
    try:
        rows, unroutable, _warn = board_worklist(chans, companies, recs, cfg, today, caps,
                                                 sched=sched, attended=attended)
    except Exception as e:                                       # noqa: BLE001 -- route.RouteError
        return 3, ["BOARD DISPATCH refused: the route preference cannot be read (%s)" % e]
    due, reasons = [], []
    for c in checks:
        kind = c["sweep"]
        if c["state"] != "yes" and not attended:
            reasons.append(c["line"])
            continue
        gate = c["line"] if c["state"] == "yes" else (
            "%s: attended run; posture limits unattended work only (%s)" % (kind, c["line"]))
        mine = [r for r in rows if sweep_kind(r[0]) == kind]
        stuck = [u for u in unroutable if sweep_kind(u[0]) == kind]
        if mine:
            due.append((kind, c, gate, mine))
            reasons.append(gate)
        elif stuck:
            # dev #811 / public #170 (N2): when EVERY stuck channel has a route this machine can run
            # that the board sweeper holds no tool for, say so by name; when the capability itself is
            # absent (or only some channels are filtered), the old line stays true.
            filtered = [sweeper_filtered(u[0], cfg, caps) for u in stuck]
            if all(filtered):
                names = []
                for m in (m for f in filtered for m in f):
                    if m not in names:
                        names.append(m)
                reasons.append("%s: no route the board sweeper can use on this machine "
                               "(%d due channels: %s, which agents/board-sweeper.md holds no tool for)"
                               % (kind, len(stuck), ", ".join(names)))
            else:
                reasons.append("%s: no route on this machine (%d due channels need a browser)"
                               % (kind, len(stuck)))
        else:
            reasons.append("%s: nothing due in the worklist (%s)" % (kind, gate))
    if not due:
        return 1, ["BOARD DISPATCH no %s" % "; ".join(reasons)]
    # A dispatch would start one board-sweeper agent: unattended, `max_agents_per_run` must allow one;
    # the explicit attended form needs one agent whatever the cap (a non-integer is refused either
    # way). Asked only now, so a closed schedule keeps its own reason.
    budget, why = _agent_budget(p, name, attended) if (p is not None and not err) else (True, "")
    if budget is None:
        return 3, ["BOARD DISPATCH refused: %s" % why]
    if budget is False:
        return 1, ["BOARD DISPATCH no %s" % "; ".join("%s: %s" % (k, why) for k, _c, _g, _m in due)]
    # dev #811 / public #170 (design §5.3): every id of THIS call's combined worklist, in the order it
    # is printed. Every `dispatched` row the call writes carries the same list, so the sweeper's
    # hand-back is checked against what it was handed (`journal.board_worklist` reads the latest row's).
    channels = list(dict.fromkeys(r[0]["id"] for _k, _c, _g, m in due for r in m))
    if not dry_run:
        # The row carries the asked-about date, so --today answers coherently in a test; a real
        # call has no --today and the row carries the real clock (journal.now_iso()).
        at = None
        if today != datetime.date.today():
            at = "%sT%s" % (today.isoformat(), _journal.now_iso()[11:])
        for kind, _c, _gate, _mine in due:
            # dev #785 (design §6): under an active career-page split the company row names the split
            # days whose pages are IN THIS WORKLIST -- a fact this run knows -- so each day spends its
            # own slot (`posture.board_spent_on(day=)`). An open day with nothing due contributes no
            # page, is not named, and stays open. An attended row spends nothing, so it never carries one.
            split = _c["split"] if (kind == "company" and not attended) else None
            split_days = (sorted({_posture.split_day(r[0]["id"], split) for r in _mine},
                                 key=_ck.WEEKDAYS.index) or None) if split else None
            try:
                _journal.record_pass(root or ROOT, run_id=run_id, kind="board",
                                     phase="dispatched", at=at, sweep=kind,
                                     attended=True if attended else None, split_days=split_days,
                                     channels=channels)
            except _journal.JournalError as e:
                return 3, ["BOARD DISPATCH refused: the dispatch row could not be written (%s)"
                           % e]
        if attended and any(c["state"] != "yes" for _k, c, _g, _m in due):
            _posture._record_attended_note(run_id, "board", root=root)
    kinds = [k for k, _c, _g, _m in due]
    lines = ["BOARD DISPATCH yes %s %s" % (",".join(kinds), "; ".join(reasons)),
             "  worklist: %s" % ", ".join(channels)]
    lines += ["  %s worklist: %s" % (k, ", ".join(r[0]["id"] for r in m)) for k, _c, _g, m in due]
    return 0, lines


def channel_yield(opps, since=None):
    """{channel_id: {"sightings": n, "pursued": n}} from opportunities' sightings[] —
    a QUERY of the records, never a hand-derived summary. `since` (datetime.date) windows
    it; None counts all-time. Raw counts on purpose: funnel_report.py owns the refusal to
    print a rate below MIN_SAMPLE, and this returns numerators only."""
    out = {}
    for o in opps:
        pursued = (o.get("verdict") == "pursue"
                   or o.get("status") in ("active-pursuit", "needs-resolution"))
        for sg in o.get("sightings") or []:
            cid = sg.get("channel_id")
            if not cid:
                continue
            if since is not None:
                sd = as_date(sg.get("seen_on"))
                if sd is None or sd < since:
                    continue
            row = out.setdefault(cid, {"sightings": 0, "pursued": 0})
            row["sightings"] += 1
            if pursued:
                row["pursued"] += 1
    return out


def _board_decision_cli(args):
    """`--board-decision`: read the stores once, ask `board_decision`, print, return its exit code.
    An unreadable channel store, journal or date is exit 3 with the line printed, never a trace."""
    import journal as _journal
    try:
        today = as_date(args.today) if args.today else datetime.date.today()
        if today is None:
            raise ValueError("--today %r is not YYYY-MM-DD" % args.today)
        chans = load()
        companies = load_companies()
        fresh = not os.path.exists(_journal.path(ROOT))
        recs = _journal.read(ROOT)
    except (OSError, ValueError) as e:                      # JournalError is a ValueError
        print("BOARD DISPATCH refused: the stores cannot be read (%s)" % e)
        return 3
    import whoami as _whoami
    code, lines = board_decision(chans, companies, recs, load_cfg(), today, args.run,
                                 args.dry_run, args.attended, _whoami.probe_with_pane(), root=ROOT,
                                 fresh=fresh, kinds=[args.kind] if args.kind else None)
    for line in lines:
        print(line)
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", metavar="ID")
    ap.add_argument("--date", metavar="YYYY-MM-DD")
    ap.add_argument("--today", metavar="YYYY-MM-DD")
    ap.add_argument("--yield-since", metavar="YYYY-MM-DD",
                    help="report sightings per channel since this date (trial-yield decision)")
    ap.add_argument("--board-decision", action="store_true",
                    help="dev #770-4 / O4: decide, per sweep kind (company career pages on "
                         "company_days, job boards and aggregators on board_days), whether a board "
                         "sweep starts, and WRITE one `pass board dispatched` row per dispatched "
                         "kind in the same call. Prints BOARD DISPATCH yes <kinds>|no <reasons> and "
                         "the worklist ids. Exit 0 dispatch, 1 not today, 3 refused (unreadable "
                         "posture/company_days/board_days/journal, or no --run).")
    ap.add_argument("--run", metavar="ID",
                    help="with --board-decision: the run id the dispatch row is written under.")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --board-decision: print the answer, write nothing.")
    ap.add_argument("--attended", action="store_true",
                    help="with --board-decision: the run was started with the EXPLICIT attended "
                         "form (/jobsearch:daily-run attended); lifts the weekday schedule, never "
                         "the worklist. Never inferred. Its rows carry `attended: true` and spend "
                         "no scheduled slot.")
    ap.add_argument("--kind", choices=("company", "board"),
                    help="with --board-decision: decide only this sweep kind (company career pages, "
                         "or job boards and aggregators); /jobsearch:search companies|boards. "
                         "Omitted: both.")
    args = ap.parse_args()

    if args.board_decision:
        return _board_decision_cli(args)

    chans = load()

    if args.stamp:
        stamp = args.date or (args.today or datetime.date.today().isoformat())
        hit = False
        for c in chans:
            if c["id"] == args.stamp:
                c["last_reviewed"] = stamp
                hit = True
        if not hit:
            print("No channel with id %r" % args.stamp)
            return 1
        save(chans)
        print("Stamped %s reviewed on %s." % (args.stamp, stamp))
        return 0

    if args.yield_since:
        since = as_date(args.yield_since)
        labels = {c["id"]: c.get("label", c["id"]) for c in chans}
        counts = channel_yield(load_opps(), since=since)
        print("Channel yield since %s — new sightings / of-which-pursued" % args.yield_since)
        print("=" * 60)
        if not counts:
            print("  No new sightings recorded in the window yet.")
        for cid, row in sorted(counts.items(), key=lambda x: -x[1]["sightings"]):
            print("  %-28s %d new / %d pursued" % (labels.get(cid, cid)[:28],
                                                   row["sightings"], row["pursued"]))
        print("\n  Decision rule (Dice/Indeed/CareerBuilder trial, ~2026-08-03): a bot-limited")
        print("  source earning 0 pursued that direct LinkedIn/ATS + recruiters didn't already")
        print("  surface is not worth the friction — drop it.")
        return 0

    today = as_date(args.today) or datetime.date.today()
    print("Channel review queue — as of %s\n" % today.isoformat())

    # dev #751 -- company feeds. A channel the feed covered TODAY is not listed for the browser (the
    # feed is its review); one whose feed failed with a BOARD code is listed DUE whatever its
    # cadence; a host failure, or a single budget-exhausted, keeps the cadence (dev #820: a budget-exhausted
    # on two polls running is DUE like a board failure). A `manual-candidate` channel is never in the
    # board worklist: it is a task for the candidate, printed apart below. dev #770-4: the
    # classification itself is `due_state()`, the one definition `board_worklist()` shares.
    import journal as _journal
    _journal_warning = None
    try:
        _recs = _journal.read(ROOT)
    except _journal.JournalError as _e:
        _journal_warning = ("  !! WARNING: the journal cannot be read (%s) -- feed coverage is "
                            "UNKNOWN, so no channel is dropped from the queue on a feed's word." % _e)
        _recs = []
    _cfg = load_cfg()
    _companies = load_companies()
    # dev #785 / public #167 (design-sourcing-schedule.md §5.1, §7): the SWEEP SCHEDULE is read once, here,
    # and `schedule_due` is the one owner of "due TODAY, given its pass" -- the same answer
    # `--board-decision` and `board_worklist` take. An unreadable posture, days, `company_split`,
    # `split_days` or journal is a SCHEDULE UNREADABLE section below, never a non-zero exit: this listing
    # is advisory (RULEBOOK.md, the daily-run hygiene paragraph) and REPORTS; `--board-decision`
    # is the gate that refuses (exit 3).
    import posture as _posture
    _pname, _pdict, _perr = _posture.load(ROOT)
    if _journal_warning:
        _sched = _posture.sweep_schedule(_pdict, _pname, today, err=_perr, root=ROOT)
    else:
        _sched = _posture.sweep_schedule(_pdict, _pname, today, recs=_recs,
                                         fresh=not os.path.exists(_journal.path(ROOT)),
                                         err=_perr, root=ROOT)
    _state = schedule_due(chans, _companies, _recs, _cfg, today, _sched)
    for _w in _state["cadence_warnings"]:
        print(_w)
    if _journal_warning:
        print(_journal_warning)
    if _state["feeds_problem"]:
        print(_state["feeds_problem"])
    # dev #770-4 -- the board worklist's own warnings (an unreadable `access` is named, not skipped).
    for _w in board_worklist(chans, _companies, _recs, _cfg, today, None, sched=_sched)[2]:
        print(_w)
    _feed = _state["feed"]
    covered_by_feed = _state["covered"]
    due, upcoming, retired = _state["due"], _state["upcoming"], _state["retired"]
    waiting, no_pass, blocked = _state["waiting"], _state["no_pass"], _state["blocked"]
    candidate_tasks = [(c, w) for c, w in due if c.get("access") == "manual-candidate"]
    due = [(c, w) for c, w in due if c.get("access") != "manual-candidate"]
    upcoming_manual = [(c, dd) for c, dd in upcoming if c.get("access") == "manual-candidate"]
    upcoming = [(c, dd) for c, dd in upcoming if c.get("access") != "manual-candidate"]

    # public #98 — fold in your_move.py's own 'now' group for channel `next_touch` plans.
    # Never a second computation of the fulfilment rule: `now_channel_plans` only reads
    # `your_move.classify_channels`'s answer. A channel review_rows() already put in `due`
    # (cadence-scheduled) keeps that entry unchanged — this only ADDS ids review_rows()
    # never considers (recruiter/referral channels, and any sourcing channel that also
    # carries a next_touch plan).
    due_ids = {c.get("id") for c, _why in due}
    for cid, (c, why) in now_channel_plans(chans, ROOT, today.isoformat()).items():
        if cid in due_ids:
            continue
        due.append((c, why))
        due_ids.add(cid)

    print("=" * 68)
    print("DUE NOW — review by DIRECT SEARCH on the source, then --stamp it")
    print("=" * 68)
    if due:
        for c, why in sorted(due, key=lambda x: x[0].get("last_reviewed") or ""):
            acc = c.get("access", "?")
            # `review_cadence` is absent on a channel surfaced only via now_channel_plans
            # (recruiter/referral channels are excluded from review_rows() by design,
            # ADR-031 §14) — never assume it is set just because this channel is due.
            cad = c.get("review_cadence") or "next_touch"
            print("  ● %-24s %-9s [%s] %s" % (c["label"][:24], cad, acc, why))
            if c.get("scope_notes"):
                print("      %s" % c["scope_notes"][:80])
    elif waiting or no_pass or blocked or _state["schedule_problem"]:
        print("  Nothing is due for a sweep today; see below.")
    else:
        print("  Nothing due. All active-search channels are current.")

    # dev #785 (design §7) -- a channel whose pass is not open today is NAMED here, never dropped and
    # never listed as DUE NOW (public #167 P5).
    if waiting:
        print("\nWAITING FOR ITS SWEEP DAY — due by cadence, but its sweep is not scheduled today:")
        for c, kind, day, opens_on, why in sorted(
                waiting, key=lambda x: (x[3] or datetime.date.max, x[0].get("id") or "")):
            print("  ◔ %-24s %-9s %s  %s; opens %s %s" % (
                c["label"][:24], c.get("review_cadence") or "next_touch",
                "%s, split day %s" % (kind, day) if day else kind, why,
                _posture.weekday_name(opens_on) if opens_on else "?",
                opens_on.isoformat() if opens_on else "(no slot)"))
    if no_pass:
        _kinds = [k for k in ("company", "board") if any(kk == k for _c, kk, _w in no_pass)]
        _arg = {"company": "companies", "board": "boards"}
        print("\nDUE, NO UNATTENDED SWEEP — posture %s does not sweep %s on its own; "
              "/jobsearch:search %s attended sweeps %s now:"
              % (_pname, " or ".join(_kinds), "|".join(_arg[k] for k in _kinds),
                 "it" if len(no_pass) == 1 else "them"))
        for c, kind, why in no_pass:
            print("  ◇ %-24s %-9s %s  %s" % (c["label"][:24], c.get("review_cadence") or "next_touch",
                                              kind, why))
    if _state["schedule_problem"]:
        print("\nSCHEDULE UNREADABLE — these due channels are offered to no sweep until it is fixed; "
              "channels_due.py --board-decision refuses (exit 3):")
        print(_state["schedule_problem"])
        for c, kind, why in blocked:
            print("  ✖ %-24s %-9s %s  %s" % (c["label"][:24], c.get("review_cadence") or "next_touch",
                                              kind, why))

    if covered_by_feed:
        print("\nCOVERED BY FEED — the feed is this page's review today; no browser visit:")
        for c in covered_by_feed:
            print("  ✓ %-24s %s" % (c["label"][:24], _feed[c["id"]][1]))

    if candidate_tasks or upcoming_manual:
        print("\nFOR YOU TO OPEN — sites whose terms forbid automated access (never the board "
              "worklist):")
        for c, w in candidate_tasks:
            print("  ☞ %-24s %s" % (c["label"][:24], w))
        for c, dd in upcoming_manual:
            print("  ○ %-24s next %s" % (c["label"][:24], dd.isoformat()))

    if upcoming:
        print("\nUPCOMING:")
        for c, dd in sorted(upcoming, key=lambda x: x[1]):
            print("  ○ %-24s [%s] next %s" % (c["label"][:24], c.get("access","?"), dd.isoformat()))

    # Named explicitly rather than silently dropped — a source that vanishes without a trace
    # reads as "we still cover it" to the next run (CLAUDE.md's no-silent-caps principle).
    if retired:
        print("\nRETIRED — deliberately no longer swept:")
        for c in retired:
            print("  ⛔ %-24s %s" % (c["label"][:24], (c.get("scope_notes") or "")[:70]))

    # Recruiter relationships gone quiet (soft signal — these are on-inbound, but a
    # silent open thread is worth a nudge; complements check_followups on opportunities).
    #
    # ⭐ 2026-08-02: this used to read ONLY channels.jsonl (log[] + last_reviewed), so a
    # real touch recorded as an OUTREACH ROW on an opportunity was invisible and the firm
    # looked silent. That produced a partly-false "15 firms gone quiet" list at the weekly
    # review — Ashford Search showed 12 days while the <an employer> chase to Calloway had gone out 7/31.
    # A nudge decision made off that list would have been wrong, so the live pipeline is
    # now folded in as a touch source.
    # ADR-031 B3 — the top-level touches store, never a nested array on the opportunity.
    outreach_touch = {}   # channel_id -> most recent outreach date
    for r in _touches.load(ROOT)[0]:
        d = as_date(r.get("date"))
        cid = r.get("channel_id")
        if d and cid and (cid not in outreach_touch or d > outreach_touch[cid]):
            outreach_touch[cid] = d

    quiet = []
    for c in chans:
        if c.get("type") != "recruiter":
            continue
        touches = [as_date(e.get("date")) for e in c.get("log", [])]
        touches += [as_date(c.get("last_reviewed"))]
        if c["id"] in outreach_touch:
            touches.append(outreach_touch[c["id"]])
        touches = [t for t in touches if t]
        if touches and (today - max(touches)).days >= QUIET_RECRUITER_DAYS:
            quiet.append((c, (today - max(touches)).days))
    if quiet:
        print("\nRECRUITER RELATIONSHIPS GONE QUIET (%d+ days) — consider a nudge:" % QUIET_RECRUITER_DAYS)
        for c, n in sorted(quiet, key=lambda x: -x[1]):
            print("  ~ %-24s %d days since last touch" % (c["label"][:24], n))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
