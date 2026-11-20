#!/usr/bin/env python3
"""The run journal — what a run knows, written the moment it knows it.

⭐ TWO ISSUES, ONE DEFECT (GitHub #4 and #5)
--------------------------------------------
**#4 — a run that dies early loses everything it learned.** Findings are held in the session
buffer and written out in one terminal step, so any early termination discards all of them. One
observed run had, before terminating: resolved a genuine contradiction between a generated
artifact and its underlying data, and enumerated roughly three times more outstanding items in a
channel than the previous run carried forward. **None of it reached any file.** Worse, the next
run cannot tell *did not fire* from *fired and found nothing* from *fired, found things, and died*.

**#5 — a coverage gap is recorded as prose.** When a sweep cannot finish, the gap goes into a
run-log narrative asking a future run to re-check. Nothing sorts it, nothing escalates it, no
run-start check reads it. One gap survived three runs with nothing flagging it.

⭐⭐ THEY ARE THE SAME BUG: **a fact the run ALREADY KNOWS, stored in the one format no check can
read.** So they get one mechanism, not two — fixing the class rather than the instance.

## The shape, copied from `precondition.py` deliberately

A named record · a strict parser that refuses what it cannot read · a resolver over data that
already exists. Append-only, one JSON object per line, because **two runs may journal at once and
an append cannot lose a concurrent write the way a rewrite can.**

    start   a run began              → an unmatched start is a run that DIED
    note    something was learned    → survives termination, because it is written NOW
    gap     a sweep did not complete  → structured, sortable, and closeable
    end     the run finished cleanly

⚠️ **Writing at the end is the bug.** `--note` and `--gap` are worth nothing if a run batches them;
they must be called as the run learns each thing. The whole point is that a crash one line later
still leaves the finding on disk.

⭐⭐⭐ THREE MORE STATES, ONE MORE CLASS (public #65, #69, #72) — a class audit confirmed all
three are the same defect that #4/#5 already are: a real state this journal has no vocabulary
for, so the absence is read as something worse than the truth.

**#65 — a run the SCHEDULER marks fired can leave zero trace.** `start` above is written by the
RUN's own logic (a skill instruction, the model's second action), so a run that dies before that
instruction ever executes is indistinguishable from a scheduler that never created a session at
all — no `start`, same as no session. The fix is a `fired` event, written by the SessionStart
HOOK ITSELF (`--fired`, wired as `hooks.json`'s first SessionStart hook) — deterministically,
before any model turn, so a session's existence is provable independent of whether the run ever
got as far as calling `--start`. A run that dies in the gap between "hook ran" and "skill called
--start" now leaves `fired` with no matching `start`, which is a NEW, narrower state than #65's
old one ("no session at all") and #4's ("session existed, died mid-run") — it means the hook
fired and the model turn that should have called `--start` never completed.

**#69 — a coverage gap has no way to say "this is a KNOWN, ALREADY-FILED limitation."** The same
permanent cause (a surface this profile has deliberately never wired, say) manufactures a fresh,
unexplained-looking gap on every run, forever. `--gap` now takes `--covered-by CITATION` — the
same `dev #N` / `public #N` / `marketplace #N` / `GitHub #N` vocabulary
`check_regression_links.py` already established, so a gap and a regression case cite issues the
same way. A gap that names one is COVERED rather than open-and-unexplained — it still records
every occurrence, because this is a queryable store and not a place to go quiet, but it is no
longer counted as an actionable open gap. ⚠️ **A suppression must not outlive its cause**:
`evaluate_coverage()` is the pure, offline half (which gaps need a live look, and what each
possible answer means) and `--check-coverage` is the on-demand `gh`+network half that actually
asks GitHub whether the cited issue is still open — the exact split `check_regression_links.py`
uses for the identical reason (CI has neither `gh` nor network), and for the same reason NOT
wired into CI. A `covered_by` naming a CLOSED or nonexistent issue is reported, loud, as stale
coverage — the same "cannot quietly outlive its defect" property `KNOWN_EXCEPTIONS` already has.

⭐ dev #711 / public #147 — A CITATION IS CHECKED WHEN WRITTEN AND RE-CHECKED WHEN READ. `--gap
--covered-by` now requires `--covered-reason` (why the cited issue covers THIS gap's scope), stored
beside the citation, and echoes the cited issue's title and state, or says NOT VERIFIED when `gh`
cannot answer. `--check-coverage` keeps its verdicts (open / closed / missing, with the date) in
`.jobsearch/coverage_check.json`; the routine, offline `--check` reads that file, DEGRADES a gap
whose citation was last known closed or missing to open (with the reason), and counts a citation
never checked, or a gap written before the reason existed, as "unverified" in the count line.

**#72 — a run that dies mid-flight is reported as an unresolved failure by `--check` forever**,
even after a human reviews its stranded notes and finds nothing worth writing. `--dispose --run
<id> [--because TEXT]` records exactly that outcome. The run is still reported as having died —
that fact is never hidden, because it is true — but it stops counting as a LOST run once its
notes are disposed of. Disposing is not the same as `--end`: `--end` claims the run finished
cleanly, which would be a lie about a run that actually died; `--dispose` tells the truth about a
dead run AND records that someone looked at what it left behind.

⭐⭐⭐⭐ dev #321 (V0) — A FIFTH STATE, AND IT IS AN INTERVAL, NOT A TIMESTAMP: nothing anywhere
recorded WHEN a mailbox was covered, so every "nobody has replied" rested on a mirror
(`data/messages.jsonl`) whose absence could mean either "nothing arrived" or "nothing looked."
`check_followups.py` measured silence against `datetime.now()` regardless of whether a sweep had
run in days — the exact "missing thing read as an empty thing" trap this repo names everywhere
else, sitting under the one path that tells a candidate to chase someone.

Two more events, both **positive** coverage (everything above is either negative — `gap` — or
run-shaped; these are per-mailbox and per-thread):

    swept   a multi-account search covered [from, through] for one mailbox, or failed
    probe   a LinkedIn thread was looked at — pointwise, one look sees the whole thread

`swept` is written by `mail_client.py`'s multi-account search, one row per configured account
per sweep, `ok: true` with the window actually searched or `ok: false` with a reason code — a
failed account is the loud `!! INCOMPLETE COVERAGE` banner **stored**, not just printed, so a
partial failure marks that account uncovered rather than merely annotated. `probe` is written
per LinkedIn thread look (`linkedin-runner`, wired later; V0 defines the shape so the
vocabulary exists — Class C's `probe … result=empty|thread:<date>`).

⭐⭐ public #85 — THE `end` EVENT NOW CARRIES A `footprint` OBJECT: a scheduled run once posted a
queue summary claiming "no change" while it had, in the same run, recorded a genuine reply and
left real writes uncommitted. `--end` computes `run_summary.footprint()` (defined in that module,
imported lazily right here — see the code) at the moment it is called, and stores the result on
the event: files/insertions/deletions from `git diff --stat`, a `git status --porcelain` count,
and this run's own swept/probe/gap/note counts from the journal itself. `run_summary.py --post`
computes the SAME shape independently, earlier in the run (before the commit, so its numbers are
the run's real diff rather than a post-commit clean tree) — the two calls measure two different
moments on purpose and are not expected to agree in value; `check_runs.py` reads both.

⭐ dev #703 / public #155 — THE `start` EVENT NOW CARRIES `start_sha`: the profile's HEAD when the
run began (`head_sha()`), so `footprint()` can add the paths the run COMMITTED mid-way
(`git diff --name-only <start_sha> HEAD`) instead of reading a clean tree as a quiet run. The
field is optional and new-events-only; it is omitted (never null) when git cannot be asked, and a
`start` without it is the "not measured" case. No row is rewritten, so this is not a migration.

**Why an interval and not a timestamp:** sweeps are windowed (`watch --since <hours>`,
`alert_sweep --days 1`), so *"swept at T"* is not *"covered through T"* — a scheduler outage
leaves a hole a later sweep does not backfill unless something widens the window over it.
`covered_through(recs, mailbox, as_of=None)` merges every `ok: true` row's `[from, through]`
window for that mailbox and returns the end of the interval that contains `as_of` (or, with no
`as_of`, the newest merged interval's end) — `None` when nothing verifies coverage there. `None`
is the honest, load-bearing answer on an empty ledger: a caller that would otherwise fall back to
the wall clock (`check_followups.py`, fixed here) must render "unverified" instead of a
confidently wrong day count. `probe_covered_through(recs, thread)` is `probe`'s pointwise twin —
one look verifies through its own timestamp, no interval needed.

⭐ dev #807 — A `swept` WINDOW IS AN INSTANT. `from`/`through` used to be naive local wall time, and in
the fall-back hour one wall time names two instants, so a real hole between two sweeps could be merged
away. Since 0.83.0 `record_swept` stores a numeric offset (`coverage_iso`, in the zone `_localzone`
resolves) and refuses a naive window; every reader goes through `parse_instant`, which reads a LEGACY
naive row by a stated rule that can only shrink coverage (both readings of the repeated hour, in the
host zone and the declared one: `from` takes the latest, `through` the earliest, an empty or inverted
row contributes nothing). `at` keeps the journal-wide naive-local form. Old rows are READ, not migrated:
the journal is append-only and its SessionStart writer runs before `migrate.py`.

Usage:
    python3 journal.py --start daily                     # prints the run id
    python3 journal.py --run <id> --note "what was found"
    python3 journal.py --run <id> --gap linkedin:replies --reason browser-unavailable \
                       --closes-when "a run with chrome completes the sweep"
    python3 journal.py --run <id> --gap slack:digest --reason skipped-for-cost \
                       --covered-by "public #58" \
                       --covered-reason "the surface was never wired, which #58 tracks"
                       # a KNOWN, filed limitation (#69); the reason is required (dev #711)
    python3 journal.py --run <id> --end
    python3 journal.py --run <id> --dispose --because "reviewed, nothing actionable"  # (#72)
    python3 journal.py --unfinished     # runs that started and never ended, with their notes
    python3 journal.py --open-gaps      # oldest first, covered ones called out separately
    python3 journal.py --close-gap <gap_id>
    python3 journal.py --check          # exit 1 if an UNCOVERED gap is stale, or a run died
                                         # holding findings nobody disposed of
    python3 journal.py --check --run <id>  # mid-run (dev #474/public #119): <id> is the
                                         # CALLER's own run, excluded from the dead-run check
    python3 journal.py --check-coverage # on demand, needs gh+network: is every covered_by
                                         # citation still open? (#69, never run in CI). Keeps its
                                         # verdicts in .jobsearch/coverage_check.json for --check
    python3 journal.py --fired          # hook use only — see hooks.json's SessionStart entry
    python3 journal.py --probe opp:<id> --thread contact:<id> --result empty      # (dev #321)
    python3 journal.py --probe opp:<id> --thread contact:<id> \
                       --result thread:2026-09-10T09:00:00
    python3 journal.py --probe contact:<id> --thread contact:<id> --medium email \
                       --mailbox acct-a@example.com --result empty       # Query or Citation C1
    python3 journal.py --probe contact:<id> --thread contact:<id> --medium linkedin \
                       --result empty --read inbox,requests,invitations,degree   # D14
    python3 journal.py --run <id> --fold-dispatches       # design-script-first.md §8.2 (#90/#111)
    python3 journal.py --dispatches [--today] [--calibrate]
    python3 journal.py --calibrate                        # per-agent tool_use/token quantiles
    python3 journal.py --run <id> --pass linkedin --phase dispatched     # design-script-first.md
    python3 journal.py --run <id> --pass linkedin --phase returned \
                       --reached inbox --not-attempted requests,invitations,degree # §2 (#75/#87/#110)
    python3 journal.py --run <id> --pass linkedin --phase refused --reason skipped-for-cost
    python3 journal.py --passes [--today]                 # every pass row, '0 passes' if none
    python3 journal.py --check [--since YYYY-MM-DD]        # dispatch totals; never refuses on
                                                            # them until §8.3's ceiling lands
    python3 journal.py --run <id> --pass linkedin --phase returned --reached inbox \
                       --jobsearch reached                 # dev #692 / R4: the JOB SEARCH token
    python3 journal.py --run <id> --pass board --phase dispatched   # dev #692 / R3: board pass

## ⭐ A ROLES EVENT, AND A MISSING ONE IS LOUD (dev #692 / public #140, N5, R3, R4)

`deferred.py --add-roles` accepts a pass's `ROLES v1` block and writes ONE `roles` event per
accepted block: `surface` (`linkedin-jobsearch` | `board`), the window it searched, the count of
distinct roles and how each resolved (`captured` / `known` / `carried` / `role_gaps`), and the
per-query gaps in two separate fields (`query_gaps_window`, `query_gaps_truncated`). ⭐ dev #722 /
public #156 (jobsearch 0.69.0): a role every query of which reported a DEGRADATION is held, not
carried -- `quarantined` joins the identity (`distinct = captured + known + carried + quarantined +
role_gaps`, refused by `record_roles` when it does not hold) with `quarantine_reasons`
(`{code: roles}`), and the event counts how each REACHED query read: `q_reached = q_clean +
q_unread + q_degraded_queries`, `q_total_unknown` (counted apart), `q_degraded` (`{code: queries}`).
Those counts are the sweep's SELF-REPORT (SHAPE, not enforced). `--end` then
asks `roles_missing()` whether a pass RETURNED with nothing accounted, and gaps it
(`jobsearch:roles:<surface>`, `partial-results`) instead of letting the run end on "N seen, top few
captured": a LinkedIn `pass … returned` row whose explicit `jobsearch` token reads `reached` (R4),
or a board `pass` row the dispatching script wrote (R3, never a folded `dispatch` row, which is
model-dependent), with no `roles` event for the run. `unreachable` and `not-attempted` trip
nothing: no search ran, so there is nothing to account for. ⚠️ ROLLBACK RISK, STATED: an engine
older than the release that added `roles` raises on any journal holding one (`read()` refuses an
event outside `EVENTS`), so after one run on this version an older version cannot read this
profile's journal. The reader here does not raise on a new event field of a known event.

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import (profile_root, is_tracked_fixture, transcript_stash_path, is_unbound,
                   say_unbound_once, STATE_DIRNAME, engine_root)
# S4a: the scripts directory for code that moved into journaling/ (it cannot read this file's __file__).
from journaling import where as _where
# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from journaling.board_runs import (
    _latest_dispatched,
    board_worklist_dispatched,
    _batch_rows,
    board_batch_current,
    board_worklist,
    board_batches,
    _ROLES_SUM_FIELDS,
    board_roles_run,
)
from journaling.coverage_claims import (
    age_days,
    evaluate_coverage,
    _split_citation,
    _public_repo,
    _private_repo,
    issue_lookup,
    issue_state,
    coverage_cache_path,
    read_coverage_cache,
    write_coverage_cache,
    apply_coverage_cache,
    coverage_echo,
    _record_fired,
)
from journaling.dispatch_folds import (
    pass_durations,
    _parse_transcript_ts,
    _is_agent_result,
    _hand_back_text,
    _outcome_from_text,
    _fields_from_agent_result,
    fold_dispatches,
    _percentile,
    cmd_calibrate_dispatches,
    cmd_dispatches,
    cmd_passes,
)
from journaling.drain import record_drain, record_readmit
from journaling.feeds import (
    record_feeds,
    feeds_events,
    feed_last_covered,
    feed_last_attempted,
    feed_repeat_failures,
    feed_board_failure_since,
    feed_company_state,
)
from journaling.instants import (
    _parse_iso,
    _UTC,
    INSTANT_ROLES,
    _declared_zone,
    _fromiso,
    is_offset_bearing,
    coverage_iso,
    _coverage_field,
    _journal_at,
    parse_instant,
    coverage_intervals,
    _as_of_instant,
    _merge_intervals,
    covered_through,
    triaged_uids,
    probe_covered_through,
)
from journaling.journal_file import (
    normalize_citation,
    head_sha,
    MACHINE_FILE,
    _git_common_dir,
    machine_id,
    dirty_paths,
    utc_offset,
    path,
    now_iso,
    _refuse_if_unwritable,
    _PIN_CACHE,
    pin_scan,
    profile_pin,
    pin_refusal,
    append,
    read,
    new_run_id,
    ENGINE_VERSION_RE,
    engine_version,
)
from journaling.linkedin_passes import (
    pass_rows,
    linkedin_passes_reached,
    linkedin_refusals_excused,
    linkedin_excused_rows,
    latest_recorded_row,
    _linkedin_quota_split,
    crashed_passes,
    record_probe,
    record_gap,
)
from journaling.passes import (
    record_swept,
    record_triaged,
    record_dispatch,
    dispatch_rows,
    _is_count,
    check_recorded_fields,
    _check_ids,
    _check_channels,
    PASS_PANE_STATES,
    PASS_PANE_MODES,
    _check_owned_elsewhere,
    record_pass,
    record_verdict,
)
from journaling.role_runs import (
    record_roles,
    _check_channel_map,
    _roles_coverage,
    roles_events,
    roles_missing,
    close_board_loop,
    record_closing_roles,
    jobsearch_geos,
    wide_satisfied_at,
    jobsearch_window,
)
from journaling.row_kinds import (
    record_profile_schema,
    record_network,
    record_companies_raised,
    record_mail_status,
)
from journaling.row_shapes import (
    _MACHINE_RE,
    _OFFSET_RE,
    PIN_EVENT,
    PIN_FIELDS,
    _PIN_VER_RE,
    _pin_ver,
    DRAIN_PHASES,
    CAPACITY_REASONS,
    DRAIN_RUN_CAUSES,
    DRAIN_ROLE_CAUSES,
    DRAIN_ENV_CAUSES,
    DRAIN_CLOSE_CAUSES,
    DRAIN_CLASSES,
    DRAIN_CLASSES_084,
    RENDER_ROUTES,
    DRAIN_PLANNED_FIELDS,
    _is_int,
    _id_list,
    DRAIN_COMPANIES_FIELDS,
    _check_companies_block,
    _check_drain_row,
    READMIT_FIELDS,
    _READMIT_AT_RE,
    _check_readmit_row,
    MAIL_CLASSES,
    MAIL_UNMATCHED_CAP,
    _check_mail_status_row,
    _check_start_row,
    _ROW_CHECKS,
    _check_profile_schema_row,
    NETWORK_FIELDS,
    _ISO_WEEK_RE,
    _check_network_row,
    COMPANIES_RAISED_FIELDS,
    _check_companies_raised_row,
)
from journaling.runs import (
    unfinished,
    _parse_at,
    run_states,
    open_gaps,
    split_gaps,
    fired_events,
    run_events,
    record_start,
)
from journaling.tables import (
    JOURNAL,
    EVENTS,
    FEED_FAILURES,
    FEED_BOARD_CODES,
    FEED_HOST_CODES,
    FEED_COMPANY_GAP_SCOPE,
    FEED_HOST_GAP_SCOPE,
    FEEDS_COUNT_FIELDS,
    ROLES_SURFACES,
    ROLES_WINDOWS,
    ROLES_COVERAGE,
    F_TPR_DAILY,
    F_TPR_WIDE,
    F_TPR_BUCKETS,
    WIDE_EVERY_DAYS,
    JOBSEARCH_TOKENS,
    ROLES_GAP_SCOPE,
    PASS_PHASES,
    BATCH_END_STATES,
    OWNED_RULES,
    RECORD_VERDICTS,
    LINKEDIN_FREE_REFUSALS_PER_DAY,
    RECORDED_KEPT_PREFIX,
    PASS_KINDS,
    AGENT_PASS_KINDS,
    UNREACHED_PASS_KINDS,
    BOARD_SWEEPS,
    SPLIT_WEEKDAYS,
    DISPATCH_FIELDS,
    OUTCOME_MAP,
    REASONS,
    PROBE_RESULT_RE,
    STALE_DAYS,
    CITATION_RE,
    COVERED_REASON_MIN,
    COVERED_REASON_MAX,
    COVERAGE_CACHE,
    COVERAGE_STATES,
    _DATE_RE,
    TRIAGE_VERDICTS,
    TRIAGE_TTL_DAYS,
    JournalError,
    MEDIA,
    LINKEDIN_REPLY_SURFACES,
    LINKEDIN_SURFACES,
    LINKEDIN_SWEEP_SURFACES,
    LINKEDIN_REPLY_SLOTS,
    LINKEDIN_MESSAGE_REQUESTS_ALIAS,
    LINKEDIN_MESSAGE_REQUESTS_CANON,
)

# ⭐⭐ public #69 — THE PURE/IMPURE SPLIT, copied deliberately from
# `check_regression_links.py`'s own split for the identical reason: "is issue #N still open"
# needs `gh` and the network, and CI has neither. So the DECISION logic below (`evaluate_coverage`)
# is pure and exercised in CI against a fake `issue_state`; the ANSWER (`issue_state` itself) is
# impure, lives only here, and is never called by any CI-run gate — `--check-coverage` is a tool
# gate-keeper/release-manager run locally, on demand, exactly like that script's own `main()`.

# ⭐⭐ dev #711 / public #147 -- A COVERAGE CITATION IS CHECKED WHEN WRITTEN AND RE-CHECKED WHEN
# READ. `covered_by` hides a gap from `--check` whether or not the cited issue covers it, and
# `--check-coverage` (the only thing that asks GitHub) was never run by anything routine, so a
# citation could outlive its issue for as long as nobody remembered to ask. The split stays the
# one `evaluate_coverage` already has (the network half is on demand, never in CI); what is new
# is that its ANSWER is kept, so the routine, offline `--check` can use it:
#
#   write time   record_gap requires a reason; the CLI echoes the cited issue's title and state
#                (or says NOT VERIFIED) so a wrong number is visible to whoever typed it.
#   --check-coverage   leaves `<profile>/.jobsearch/coverage_check.json`: per citation, the last
#                      definite verdict (OPEN / CLOSED / MISSING) and its date.
#   --check, and every other report   reads that file with NO network. A gap whose citation was
#                      last known CLOSED or MISSING is DEGRADED -- counted as open, with the
#                      reason, never left suppressed. A citation with no verdict, or a gap with no
#                      stored reason (written before this field existed), is "unverified": still
#                      covered, but said so in the count line instead of passing as verified.
#
# Not modelled, stated rather than silent: an OPEN verdict is not aged. A verdict from months ago
# still reads "OPEN, as of <date>"; the date is printed so the reader can judge it.

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", metavar="KIND")
    ap.add_argument("--run", metavar="ID",
                    help="the run this call concerns — with --note/--gap/--end/--dispose/"
                         "--pass/--fold-dispatches, the run being written to; with --check "
                         "(or any other read-only report), the CALLER's own still-executing "
                         "run, excluded from the dead-run check (dev #474/public #119)")
    ap.add_argument("--note")
    ap.add_argument("--covered-reason", dest="covered_reason", metavar="TEXT",
                    help="with --covered-by (required there, dev #711): %d-%d characters saying "
                         "why the cited issue covers THIS gap's scope"
                         % (COVERED_REASON_MIN, COVERED_REASON_MAX))
    ap.add_argument("--gap", metavar="SCOPE")
    ap.add_argument("--reason", choices=sorted(REASONS))
    ap.add_argument("--closes-when", dest="closes_when")
    ap.add_argument("--covered-by", dest="covered_by", metavar="CITATION",
                    help="with --gap: a KNOWN, already-filed limitation explains this every "
                         "time — 'dev #N' / 'public #N' / 'marketplace #N' / 'GitHub #N' "
                         "(public #69)")
    ap.add_argument("--end", action="store_true")
    ap.add_argument("--dispose", action="store_true",
                    help="with --run: a dead run's stranded notes were reviewed and needed no "
                         "write (public #72)")
    ap.add_argument("--because", help="optional free text: why --dispose needed no write")
    ap.add_argument("--unfinished", action="store_true")
    ap.add_argument("--liveness-hours", type=int, default=None,
                    help="with --unfinished: the liveness window (config runs.liveness_hours) to classify each run against")
    ap.add_argument("--open-gaps", dest="open_gaps", action="store_true")
    ap.add_argument("--close-gap", dest="close_gap", metavar="GAP_ID")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--check-coverage", dest="check_coverage", action="store_true",
                    help="on demand, needs gh+network: is every covered_by still open? "
                         "(public #69, never run in CI)")
    ap.add_argument("--pass-durations", dest="pass_durations", action="store_true",
                    help="read: wall-clock duration of every run carrying LinkedIn work (a "
                         "linkedin:* gap, or a linkedin probe inside its [start,end] window), "
                         "longest first — measures linkedin.pane_stale_minutes instead of "
                         "guessing it (design-linkedin-runner-resilience.md §1)")
    ap.add_argument("--fired", action="store_true",
                    help="hook use only — SessionStart wrote this before any model turn "
                         "(public #65); see hooks.json")
    ap.add_argument("--probe", metavar="SUBJECT",
                    help="record a thread/mailbox look (dev #321; extended C1) — needs --thread "
                         "and --result")
    ap.add_argument("--thread", metavar="THREAD",
                    help="with --probe: the thread this probe looked at (e.g. contact:<id>)")
    ap.add_argument("--result", metavar="RESULT",
                    help="with --probe: 'empty' or 'thread:<ISO timestamp>'")
    ap.add_argument("--medium", choices=sorted(MEDIA), default="linkedin",
                    help="with --probe: which medium this look covered (default: linkedin, "
                         "V0's original and only medium)")
    ap.add_argument("--mailbox", metavar="ADDRESS",
                    help="with --probe --medium email: the account this probe searched — "
                         "required for medium=email, refused for medium=linkedin")
    ap.add_argument("--read", metavar="SURFACES",
                    help="with --probe --medium linkedin --result empty: comma-separated "
                         "surfaces this look actually covered. `empty` is refused unless this "
                         "names inbox, requests, invitations and one of degree/connections "
                         "(D14; dev #488 -- the acceptance slot) — a look "
                         "that skipped one is not evidence of silence, and is recorded as a "
                         "'gap' instead, with no probe row")
    ap.add_argument("--by", choices=("owner",),
                    help="with --probe: 'owner' marks this as the owner's own attestation "
                         "(brief.py --i-checked), not a script-run search")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--at", help="ISO timestamp; for tests and for replaying a known time")
    ap.add_argument("--fold-dispatches", dest="fold_dispatches", action="store_true",
                    help="with --run <id>: fold this run's Agent/Task dispatch results out of "
                         "the session transcript into `dispatch` rows (design-script-first.md "
                         "§8.2, public #90/#111) — idempotent on agent_id")
    ap.add_argument("--transcript", metavar="PATH",
                    help="with --fold-dispatches: read this transcript instead of the session's "
                         "own stash (tests; advanced use)")
    ap.add_argument("--dispatches", action="store_true",
                    help="print dispatch rows, summed per agent and per run")
    ap.add_argument("--today", action="store_true", help="with --dispatches: only today's rows")
    ap.add_argument("--calibrate", action="store_true",
                    help="with --dispatches (or standalone): per-agent tool_use/token quantiles "
                         "— numbers only, no recommendation")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="with --check: only sum dispatch rows dated on/after this date")
    ap.add_argument("--pass", dest="pass_kind", metavar="KIND", choices=PASS_KINDS,
                    help="with --run: record a pass event, e.g. 'linkedin' — needs --phase")
    ap.add_argument("--phase", choices=PASS_PHASES,
                    help="with --pass: dispatched | returned | refused (done: capture and fetch only). "
                         "(`recorded` is written by "
                         "linkedin_sweep.py record, never by hand: this CLI cannot supply its "
                         "verdict, so it refuses.)")
    ap.add_argument("--reached", metavar="SURFACES", default="",
                    help="with --pass --phase returned: comma-separated LINKEDIN_SURFACES")
    ap.add_argument("--unreachable", metavar="SURFACES", default="",
                    help="with --pass --phase returned: comma-separated LINKEDIN_SURFACES")
    ap.add_argument("--not-attempted", dest="not_attempted", metavar="SURFACES", default="",
                    help="with --pass --phase returned: comma-separated LINKEDIN_SURFACES")
    ap.add_argument("--jobsearch", choices=JOBSEARCH_TOKENS, default=None,
                    help="with --pass linkedin --phase returned (dev #692, R4): did the JOB SEARCH "
                         "capability reach LinkedIn's job search this pass? `reached` means the "
                         "pass owes a ROLES block; `unreachable` and `not-attempted` do not. "
                         "daily-run reports it from the runner's hand-back, always.")
    ap.add_argument("--ids", metavar="ID,ID", default=None,
                    help="with --pass reader|research (dispatched/returned) or feeds: the ids handed "
                         "to the agent, comma-separated (dev #820). Required for reader and research.")
    ap.add_argument("--unreached", metavar="ID,ID", default=None,
                    help="with --pass capture|fetch --phase done: the ids the bounded call did not "
                         "reach, comma-separated; omitted means none (dev #820)")
    ap.add_argument("--passes", action="store_true",
                    help="print every pass row by phase, oldest first (design-script-first.md "
                         "§2) — '0 passes' on an empty journal")
    args = ap.parse_args()

    root = profile_root()
    at = args.at or now_iso()

    # ⭐ public #65 — MUST NEVER BLOCK A SESSION, so this bypasses the JournalError contract
    # entirely: `_record_fired` swallows its own failures and this always returns 0.
    if args.fired:
        _record_fired(root, at)
        return 0

    try:
        if args.probe:
            if not args.thread:
                raise JournalError("--probe requires --thread")
            if not args.result:
                raise JournalError("--probe requires --result ('empty' or 'thread:<ISO ts>')")
            # ⭐ D14 — a LinkedIn `empty` verifies silence only when every surface a reply
            # could sit on was actually read. A look that skipped one is NOT evidence, and gets
            # NO probe row — linkedin-runner's own standing rules (agents/linkedin-runner.md)
            # already say what to do instead: file the existing gap vocabulary
            # (`--gap linkedin:requests --reason surface-unreachable`) under the run that
            # attempted the look. This refusal is what keeps a partial read from being written
            # as if it were a complete one; it does not invent a second gap mechanism.
            #
            # design-linkedin-runner-resilience.md §6 — checked against LINKEDIN_REPLY_SURFACES
            # (the four a reply can sit on), never the five-token LINKEDIN_SURFACES: `notifications`
            # joining the coverage vocabulary must not make it required for a silence proof.
            if args.medium == "linkedin" and args.result == "empty":
                read_surfaces = {s.strip() for s in (args.read or "").split(",") if s.strip()}
                # dev #488 / public #105 -- per SLOT, not per token: the acceptance slot is
                # satisfied by `degree` (the one-off visit) or `connections` (the list).
                missing = ["|".join(slot) for slot in LINKEDIN_REPLY_SLOTS
                           if not read_surfaces.intersection(slot)]
                if missing:
                    raise JournalError(
                        "--result empty refused (D14) — --read did not name %s. A LinkedIn "
                        "look that skips a surface a reply could sit on is not evidence of "
                        "silence. File the gap instead: journal.py --run <id> --gap "
                        "linkedin:requests --reason surface-unreachable ..."
                        % ", ".join(sorted(missing)))
            record_probe(root, args.probe, args.thread, args.result,
                        medium=args.medium, mailbox=args.mailbox, by=args.by, at=at)
            print("probed")
            return 0

        if args.start:
            # dev #834: a profile pinned ABOVE this engine is not started on. Nothing is appended, stdout stays empty
            # (a caller reads it as the run id), the refusal goes to stderr, and the exit is 3 -- the skill's step 0
            # prints that line as the run's whole summary and stops.
            refusal = pin_refusal(root)
            if refusal:
                print("⛔ %s" % refusal, file=sys.stderr)
                return 3
            # dev #703 / public #155: the HEAD this run began on, so run_summary.footprint()
            # can count what the run COMMITTED. Omitted (never null) when git cannot be asked:
            # a `start` without it is the "not measured" case, same as every older `start`.
            # dev #820 / public #175: and the ENGINE that began it, from plugin.json -- refused
            # when unreadable (record_start), never written without.
            rid = record_start(root, args.start, at=at, start_sha=head_sha(root),
                               machine=machine_id(root, create=True), dirty_at_start=dirty_paths(root),
                               offset=utc_offset())
            print(rid)
            return 0

        if args.check_coverage:
            gaps = open_gaps(read(root))
            seen = {}

            def _recording_state(citation):
                seen[citation] = issue_state(citation)
                return seen[citation]

            verified_open, stale, unverifiable = evaluate_coverage(gaps, _recording_state)
            print("COVERAGE CHECK — live lookup against each covered_by citation\n")
            for citation, gap_ids in verified_open:
                print("  OK      %-16s covers %d gap(s), still open" % (citation, len(gap_ids)))
            for citation, gap_ids in unverifiable:
                print("  ??      %-16s NOT VERIFIED (no gh, no network, or no reachable repo)"
                      % citation)
            if stale:
                print("\n  !! %d STALE COVERAGE — the citation is CLOSED or does not exist, so "
                      "it has outlived whatever it was covering:" % len(stale))
                for citation, gap_ids in stale:
                    print("      %-16s covers %d gap(s): %s"
                          % (citation, len(gap_ids), ", ".join(gap_ids)))
            if not (verified_open or stale or unverifiable):
                print("  No covered gaps open. Nothing to verify.")
            # dev #711 / public #147 -- keep the answers, so the routine offline `--check` can
            # use them. Only DEFINITE verdicts are stored; an unverifiable lookup leaves that
            # citation's previous verdict (and its date) as it was. A citation no open gap cites
            # any more is dropped.
            old, problem = read_coverage_cache(root)
            cited = {g.get("covered_by") for g in gaps if g.get("covered_by")}
            verdicts = {c: v for c, v in old.items() if c in cited}
            day = at[:10] if _DATE_RE.match(at[:10]) else now_iso()[:10]
            for citation, state in seen.items():
                if state in COVERAGE_STATES:
                    verdicts[citation] = {"state": state, "at": day}
            try:
                written = write_coverage_cache(root, verdicts, day)
                print("\n  verdicts kept for the offline --check: %s (%d citation(s))"
                      % (written, len(verdicts)))
            except (JournalError, OSError) as e:
                print("\n  coverage cache NOT written (%s) -- the routine --check will read "
                      "these citations as unverified" % e)
            return 1 if stale else 0

        if args.pass_durations:
            durs = pass_durations(read(root))
            if not durs:
                print("No completed run carries LinkedIn evidence (a linkedin:* gap or a "
                      "linkedin probe) yet — nothing to measure linkedin.pane_stale_minutes "
                      "against.")
                return 0
            print("LINKEDIN PASS DURATIONS — longest first "
                  "(measures linkedin.pane_stale_minutes)\n")
            for d in durs:
                print("  %7.1f min  %s  (%s -> %s)"
                      % (d["minutes"], d["run_id"], d["start"], d["end"]))
            return 0

        if args.fold_dispatches:
            if not args.run:
                raise JournalError("--fold-dispatches requires --run <id> (get one from --start)")
            _written, _skipped, refused = fold_dispatches(root, args.run,
                                                          transcript_path=args.transcript, at=at)
            return 2 if refused else 0

        if args.dispatches or args.calibrate:
            if args.dispatches:
                cmd_dispatches(root, today_only=args.today, calibrate=args.calibrate)
            else:
                cmd_calibrate_dispatches(root)
            return 0

        if args.passes:
            cmd_passes(root, today_only=args.today)
            return 0

        if args.note or args.gap or args.end or args.close_gap or args.dispose or args.pass_kind:
            if args.close_gap:
                append(root, {"event": "gap-closed", "gap_id": args.close_gap, "at": at})
                print("closed %s" % args.close_gap)
                return 0
            if not args.run:
                raise JournalError("--run <id> is required (get one from --start)")
            if args.note:
                append(root, {"event": "note", "run_id": args.run, "text": args.note, "at": at})
                print("noted")
            if args.gap:
                if not args.reason:
                    raise JournalError(
                        "--reason is required with --gap. A gap without a reason code cannot be "
                        "counted or grouped, which is the whole reason this is not prose.")
                scope = args.gap
                if scope == LINKEDIN_MESSAGE_REQUESTS_ALIAS:
                    # design-linkedin-runner-resilience.md §6 — the old spelling is still
                    # ACCEPTED (rows already on disk say it) but is normalized at write time so
                    # the tree never carries two spellings as canon going forward.
                    print("normalizing gap scope %r -> %r"
                          % (LINKEDIN_MESSAGE_REQUESTS_ALIAS, LINKEDIN_MESSAGE_REQUESTS_CANON))
                    scope = LINKEDIN_MESSAGE_REQUESTS_CANON
                covered_by = normalize_citation(args.covered_by) if args.covered_by else ""
                gid = record_gap(root, args.run, scope, args.reason,
                                 closes_when=args.closes_when, covered_by=covered_by, at=at,
                                 covered_reason=args.covered_reason or "")
                print(gid)
                if covered_by:
                    # dev #711 / public #147 -- the citation is eyeballed WHEN WRITTEN: the
                    # cited issue's title and state, or NOT VERIFIED when gh cannot answer.
                    for ln in coverage_echo(covered_by):
                        print(ln)
            if args.end:
                # design-linkedin-runner-resilience.md §4 (closes D-5) — derived at write time,
                # never a new --end argument: THIS run's own open gaps (a pass that opened
                # nothing ends clean) alongside the journal-wide count (an older gap standing
                # elsewhere stays visible in gaps_open_all and --check, never hidden by a clean
                # --end elsewhere).
                # dev #692 / public #140 (N5) -- a pass that RETURNED with nothing accounted is a
                # gap, written HERE so this run's own `gaps_open` and its footprint include it.
                # Skipped when the run already holds an open gap with that scope (the gate files
                # one itself when it REFUSES a block).
                # dev #830 / public #180 (M1): close a board batch loop the run left open, BEFORE the footprint is
                # computed, wrapped like the footprint call so a fault here never blocks the `end` event.
                try:
                    closed_loop = close_board_loop(root, args.run, at=at)
                    if closed_loop:
                        print(closed_loop)
                except Exception as e:                        # noqa: BLE001 -- never block --end
                    print("⚠️ journal.py --end: the board batch loop could not be closed (%s) -- the end event "
                          "is recorded anyway; run_summary reads an open loop itself" % e, file=sys.stderr)
                for surface in roles_missing(read(root), args.run):
                    scope = ROLES_GAP_SCOPE % surface
                    if any(g.get("scope") == scope
                           for g in open_gaps(read(root), run_id=args.run)):
                        continue
                    record_gap(root, args.run, scope, "partial-results",
                               closes_when="the pass's ROLES block is accepted by "
                                           "deferred.py --add-roles --surface %s%s"
                                           % (surface.split(":")[0],
                                              (" --batch %s" % surface.split(":b")[1]) if ":b" in surface else ""),
                               at=at)
                    print("ROLES NOT ACCOUNTED (%s): the pass returned, no ROLES block was "
                          "accepted — gap filed" % surface.replace(":b", " batch "))
                recs_before_end = read(root)
                gaps_open_run = len(open_gaps(recs_before_end, run_id=args.run))
                gaps_open_all = len(open_gaps(recs_before_end))
                rec = {"event": "end", "run_id": args.run, "at": at,
                       "gaps_open": gaps_open_run, "gaps_open_all": gaps_open_all}
                # ⭐⭐ public #85 — THE FOOTPRINT IS DEFINED ONCE, in `run_summary.py`, and
                # written HERE, on the `end` event, so `check_runs.py` can ask "did this run
                # leave a footprint nobody flagged?" without recomputing anything itself.
                # Imported LAZILY (never at module top) so this foundational ledger module
                # never depends on the higher-level reporting script at import time — only
                # this branch ever needs it, and by the time it runs, `journal` itself is
                # already fully loaded, so `run_summary`'s own `import journal` cannot see a
                # half-built module (see run_summary.py's own docstring for the full reasoning
                # on why the dependency runs this direction and not the other).
                try:
                    from run_summary import footprint as _footprint
                    rec["footprint"] = _footprint(root, args.run, at=at)
                except Exception as e:                        # noqa: BLE001 — never block --end
                    print("⚠️ journal.py --end: footprint could not be computed (%s) — the end "
                          "event was recorded WITHOUT one; check_runs.py will flag this run"
                          % e, file=sys.stderr)
                append(root, rec)
                print("ended (gaps_open: %d, gaps_open_all: %d)"
                      % (gaps_open_run, gaps_open_all))
            if args.dispose:
                append(root, {"event": "dispose", "run_id": args.run,
                              "because": args.because or "", "at": at})
                print("disposed %s" % args.run)
            if args.pass_kind:
                if not args.phase:
                    raise JournalError("--pass requires --phase (dispatched|returned|refused)")
                reached = [s.strip() for s in args.reached.split(",") if s.strip()]
                unreachable = [s.strip() for s in args.unreachable.split(",") if s.strip()]
                not_attempted = [s.strip() for s in args.not_attempted.split(",") if s.strip()]
                _csv = lambda raw: (None if raw is None  # noqa: E731
                                    else [x.strip() for x in raw.split(",") if x.strip()])
                record_pass(root, args.run, args.pass_kind, args.phase,
                           reached=reached, unreachable=unreachable,
                           not_attempted=not_attempted, reason=args.reason, at=at,
                           jobsearch=args.jobsearch, ids=_csv(args.ids), unreached=_csv(args.unreached))
                print("pass %s %s recorded" % (args.pass_kind, args.phase))
            return 0

        recs = read(root)
        dead = unfinished(recs)
        if args.run:
            # ⭐ dev #474 (public #119) — a run invoking `--check` (or any of the read-only
            # reports below) WHILE it is still executing is not dead; it is the very run
            # asking. An unmatched `start` with no `end` yet is exactly what an alive,
            # still-in-progress session looks like from the journal's own side — there is no
            # way to distinguish "alive, mid-run" from "actually died" without the run naming
            # itself. `--run <id>` here IS that self-identification: it carves the caller's
            # own id out of the dead-run set before the bare summary, `--json`,
            # `--unfinished`, or `--check`'s own exit code ever sees it. A genuinely dead
            # OTHER run (a different id) is unaffected.
            dead = [d for d in dead if d["run_id"] != args.run]
        gaps = open_gaps(recs)
        uncovered, covered = split_gaps(gaps)
        # ⭐ dev #711 / public #147 -- the OFFLINE half of re-checking a citation: the last
        # `--check-coverage` verdicts, read from disk, no network. A gap whose citation was last
        # known CLOSED/MISSING is DEGRADED to open (counted with the uncovered, with its reason);
        # a citation never checked, or a gap with no stored reason, is reported as unverified.
        verdicts, cache_problem = read_coverage_cache(root)
        covered, degraded, unverified = apply_coverage_cache(covered, verdicts)
        uncovered = sorted(uncovered + degraded, key=lambda g: g.get("at") or "")
        fired = fired_events(recs)

        if args.json:
            print(json.dumps({"unfinished": dead, "open_gaps": gaps,
                              "uncovered_gaps": uncovered, "covered_gaps": covered,
                              "degraded_gaps": degraded, "unverified_gaps": unverified,
                              "coverage_cache_problem": cache_problem,
                              "fired": fired[-20:]}, indent=1))
        elif args.open_gaps:
            print("OPEN COVERAGE GAPS — oldest first\n")
            for g in uncovered:
                print("  [%2dd] %s  (%s)" % (age_days(g.get("at", "")), g.get("scope"),
                                             g.get("reason")))
                print("        %s · closes when: %s" % (g.get("gap_id"),
                                                        g.get("closes_when") or "unstated"))
                if g.get("degraded_because"):
                    print("        DEGRADED to open: %s, so it no longer suppresses this gap"
                          % g["degraded_because"])
            if not uncovered:
                print("  None. Every sweep that started has been completed, closed, or is "
                      "covered below.")
            if covered:
                print("\nCOVERED — a filed issue already explains these; not counted as open "
                      "(public #69)\n")
                for g in covered:
                    print("  [%2dd] %s  (%s)  covered by %s%s"
                          % (age_days(g.get("at", "")), g.get("scope"), g.get("reason"),
                             g.get("covered_by"),
                             "  [unverified]" if g in unverified else ""))
                    if g.get("covered_reason"):
                        print("        why: %s" % g["covered_reason"])
            if cache_problem:
                print("\n  ⚠️ coverage cache unusable: %s -- every citation reads as unverified"
                      % cache_problem)
        elif args.unfinished:
            print("RUNS THAT STARTED AND NEVER ENDED\n")
            states = {}
            if args.liveness_hours:
                states = {x["run_id"]: x for x in run_states(read(root), datetime.datetime.now(), args.liveness_hours)}
            for d in dead:
                tag = "  [reviewed — no write needed]" if d.get("disposed") else ""
                st = states.get(d["run_id"])
                state = (" [%s%s]" % (st["state"], (": " + st["why"]) if st["why"] else "")) if st else \
                    " [state not measured: pass --liveness-hours, runs.liveness_hours]"
                print("  %s  (%s)  %d note(s), %d gap(s)%s%s"
                      % (d["run_id"], d.get("at"), len(d["notes"]), d["gaps"], state, tag))
                for n in d["notes"][:5]:
                    print("      · %s" % str(n)[:110])
            if not dead:
                print("  None. Every run that started also finished.")
        else:
            lost_now = [d for d in dead if d["notes"] and not d.get("disposed")]
            print("RUN JOURNAL\n")
            print("  %d run(s) died mid-flight (%d unresolved) · %d open coverage gap(s) "
                  "(%d covered, %d unverified, %d degraded to open) · %d session(s) fired"
                  % (len(dead), len(lost_now), len(uncovered), len(covered), len(unverified),
                     len(degraded), len(fired)))
            for g in degraded:
                print("     ⚠️ %s: %s -- counted open, not suppressed"
                      % (g.get("scope"), g["degraded_because"]))
            if cache_problem:
                print("     ⚠️ coverage cache unusable: %s -- every citation reads as unverified"
                      % cache_problem)
            if dead:
                print("\n  ⭐ A run that started and never ended did NOT necessarily do nothing —")
                print("     its notes below are work that would otherwise have been lost.")
                for d in dead[:3]:
                    tag = " [reviewed]" if d.get("disposed") else ""
                    print("     %s: %d note(s)%s" % (d["run_id"], len(d["notes"]), tag))
            if uncovered:
                print("\n  ⏳ oldest unresolved gap: %s (%dd, %s)"
                      % (uncovered[0].get("scope"), age_days(uncovered[0].get("at", "")),
                         uncovered[0].get("reason")))

        if args.check:
            stale = [g for g in uncovered if age_days(g.get("at", "")) >= STALE_DAYS]
            lost = [d for d in dead if d["notes"] and not d.get("disposed")]
            for g in stale:
                print("⛔ coverage gap %r open %d days (%s)%s"
                      % (g.get("scope"), age_days(g.get("at", "")), g.get("reason"),
                         " -- coverage degraded: %s" % g["degraded_because"]
                         if g.get("degraded_because") else ""),
                      file=sys.stderr)
            for d in lost:
                print("⛔ run %s died holding %d unwritten finding(s)"
                      % (d["run_id"], len(d["notes"])), file=sys.stderr)
            # design-script-first.md §8.2/§11 item 1 (public #90/#111) — reused shape, not the
            # maintenance ledger's own semantics: `token_ceiling_per_run`/`_per_day` (§8.3) do
            # not exist yet (build-list item 4), so there is no ladder to refuse against. This
            # reports and NEVER refuses until that ceiling lands — stated here rather than
            # silently returning green for a check that cannot yet fail.
            drows = dispatch_rows(recs)
            if args.since:
                drows = [r for r in drows if str(r.get("at", "")) >= args.since]
            print("\nDISPATCH --check%s" % (" (since %s)" % args.since if args.since else ""))
            print("  %d dispatch row(s) · tokens %d · tool_uses %d"
                  % (len(drows), sum(r.get("tokens", 0) for r in drows),
                     sum(r.get("tool_uses", 0) for r in drows)))
            print("  NOT ENFORCED: token_ceiling_per_run/token_ceiling_per_day do not exist yet "
                  "(design-script-first.md §8.3, build-list item 4) — reporting only, never "
                  "refusing.")
            return 1 if (stale or lost) else 0
        return 0

    except JournalError as e:
        print("⛔ %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
