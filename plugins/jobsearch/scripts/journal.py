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

JOURNAL = os.path.join("data", "runs.jsonl")
EVENTS = ("fired", "start", "note", "gap", "gap-closed", "end", "dispose", "swept", "probe",
         "triaged", "dispatch", "pass", "roles", "feeds", "drain", "mail-status", "readmit")

# dev #751 (sourcing-feeds; design §3.6 as amended by review B1/B3/B6) -- the company feed poller's
# failure vocabulary, CLOSED and validated by `record_feeds`: a code, not a sentence, each mapped to
# the existing `REASONS` code a gap carries (`REASONS` itself is unchanged, so no reader of it
# changes). A feed that did not return the documented list is NOT COVERED, never zero roles.
#
# The codes split in two, and the split is load-bearing (B1):
#   BOARD codes   -- one board is wrong (404, a body that is not the documented shape, a redirect, an
#                    odd status). The company's career-page channel is listed DUE for the browser
#                    regardless of cadence, until one browser review stamps `last_reviewed`.
#   HOST codes    -- the machine or the host failed (egress refused by a sandbox or firewall, a TLS
#                    chain the host does not trust, DNS/connect failure, a CONNECT-PHASE timeout or a
#                    rate limit on the host's FIRST request, or the poller's own deadline). Not a fact
#                    about any one company, so the channel keeps its NORMAL cadence: a machine that
#                    cannot reach a vendor must not turn a monthly browser visit into a daily one for
#                    every slugged company.
# dev #831 (public #179, jobsearch 0.84.0): a failure AFTER the request was sent (the server never finished
# its answer) is the BOARD's own, so `read-timeout` and `read-dropped` are BOARD codes. A host goes down on a
# connect-phase failure before it has answered this run, or on the second consecutive transport failure on it
# (`feed_poll._HostBreaker`); a host-down carries a HOST code, never a read-* one.
FEED_FAILURES = {
    "not-found": "upstream-error",          # 404
    "auth-required": "upstream-error",      # 401 / 403 once the host has answered (design U1)
    "http-error": "upstream-error",         # any other non-2xx, non-304
    "redirected": "upstream-error",         # a cross-host redirect is not followed
    "unparseable": "upstream-error",        # a 200 that is not the documented shape
    "rate-limited": "rate-limited",         # 429/503 not resolved by one capped wait
    "timeout": "timeout",
    "unreachable": "surface-unreachable",   # DNS, connect or generic transport failure
    "egress-blocked": "surface-unreachable",  # a sandbox/proxy refused the host (B1)
    "tls-untrusted": "surface-unreachable",   # certificate verification failed (B1)
    "read-timeout": "timeout",              # dev #831: the request was SENT and the answer never finished (a BOARD code)
    "read-dropped": "upstream-error",       # dev #831: the connection was reset or dropped after the request (a BOARD code)
    "budget-exhausted": "timeout",          # the poller's own deadline expired before this board (B3)
    # dev #775 (jobsearch 0.76.0, design-workday-feed.md 5.2 + ruling R2): the Workday vendor's board codes. All map to the
    # existing `upstream-error` reason (REASONS is unchanged) and all are BOARD codes (FEED_HOST_CODES is unchanged), so a
    # company they name is listed DUE for the browser until one browser review stamps it.
    "robots-unavailable": "upstream-error",     # robots.txt is not a 200 text/plain that parses (422 = no such tenant)
    "robots-disallowed": "upstream-error",      # /<site>/, the sitemap path or a job path is disallowed by robots.txt
    "sitemap-not-advertised": "upstream-error",  # not exactly one `Sitemap:` line naming this site's sitemap
    "blocked": "upstream-error",                # a block page (cf-mitigated: challenge, HTML where XML/text was due) or a 403
    "sitemap-malformed": "upstream-error",      # a sitemap that is not the strict 0.9 shape, or carries DOCTYPE/ENTITY
    "sitemap-empty": "upstream-error",          # a well-formed sitemap with zero <loc>
    "sitemap-capped": "upstream-error",         # the window is at the cap: completeness is not claimed (R3)
    "sitemap-window-gap": "upstream-error",     # the window does not overlap the last run's: roles may have passed through
    "no-jsonld": "upstream-error",              # a new job page with no JobPosting JSON-LD (or one that redirected away)
    "locale-mismatch": "upstream-error",        # the candidate's URL locale differs from the pages' inLanguage (R2)
}
FEED_BOARD_CODES = ("not-found", "auth-required", "http-error", "redirected", "unparseable",
                    "read-timeout", "read-dropped",
                    "robots-unavailable", "robots-disallowed", "sitemap-not-advertised", "blocked",
                    "sitemap-malformed", "sitemap-empty", "sitemap-capped", "sitemap-window-gap",
                    "no-jsonld", "locale-mismatch")
FEED_HOST_CODES = tuple(c for c in FEED_FAILURES if c not in FEED_BOARD_CODES)
FEED_COMPANY_GAP_SCOPE = "jobsearch:feed:%s"
FEED_HOST_GAP_SCOPE = "jobsearch:feeds:host:%s"
FEEDS_COUNT_FIELDS = ("polled", "covered", "unchanged", "not_covered", "postings", "unlisted",
                      "selected", "captured", "known", "carried", "role_gaps", "quarantined",
                      "sightings_added", "discovered", "ambiguous")

# dev #692 / public #140 -- the two pass surfaces a `roles` event can account for, and the windows
# one can carry. R5 (owner, 2026-10-09): LinkedIn's OWN UI time buckets only -- `r86400` ("Past 24
# hours") for the daily pass, `r604800` ("Past week") for the weekly wide re-scan. There is no
# computed window and no `r2592000`.
ROLES_SURFACES = ("linkedin-jobsearch", "board")
ROLES_WINDOWS = ("daily", "wide", "none")
ROLES_COVERAGE = ("complete", "partial")      # dev #811/#812 (0.82.0): a `roles` event's `coverage`
F_TPR_DAILY, F_TPR_WIDE = "r86400", "r604800"
F_TPR_BUCKETS = (F_TPR_DAILY, F_TPR_WIDE)
WIDE_EVERY_DAYS = 7
JOBSEARCH_TOKENS = ("reached", "unreachable", "not-attempted")
ROLES_GAP_SCOPE = "jobsearch:roles:%s"

# design-script-first.md §2 (public #75/#87/#110) — the three phases ONE LinkedIn pass moves
# through, written by TWO separate calls per §2 item 2 ("the row is written twice, and only the
# second counts"): `dispatched` in the same tool call that launches the runner
# (write-then-dispatch — a crash between the write and the launch still leaves the row, #87),
# `returned` from the hand-back's own REACHED/UNREACHABLE/NOT-ATTEMPTED line once the runner
# actually finishes, `refused` when the gate (browser capability or quota) never let the pass
# start at all — never a printed line with no row behind it (#87). Any other value is refused at
# write, loud, the same discipline `REASONS`/`PROBE_RESULT_RE` already apply to their own fields.
#
# dev #812 / public #169 (design-sweep-partial-failure.md §4) -- a FOURTH phase, `recorded`: written by
# `linkedin_sweep.py record` after it has judged a SWEEP hand-back, carrying a `verdict`. It is how the
# quota (`linkedin_passes_reached`) and the run summary learn whether a `returned` pass was actually
# recorded. A row older than 0.82.0 never has one, and every reader treats "no `recorded` row" as the
# conservative case (the pass counts).
#
# dev #820 / public #175 (0.82.0) -- a FIFTH phase, `done`: written by the two bounded drain verbs
# (`capture-batch`, `read-batch --fetch`) when a call ends, with the ids it did NOT reach. Only the
# `capture` and `fetch` pass kinds use it (`record_pass` refuses it elsewhere).
#
# dev #830 / public #180 (0.84.0) -- two more phases, BOARD only, written by `channels_due.py --board-batch`: `batch` (one
# bounded slice of the run's worklist was handed out: `channels`, `batch`, `of`, `t0_utc`) and `batch-end` (the loop ended:
# `state`, optional `code`, `handed`, `worklist`). `journal --end` writes `batch-end` too, for a loop the run left open.
PASS_PHASES = ("dispatched", "returned", "refused", "recorded", "done", "batch", "batch-end")
BATCH_END_STATES = ("done", "budget-spent", "stopped", "abandoned")
OWNED_RULES = ("link", "channel-id", "host-label")

# dev #812 / public #169 -- the six verdicts a `recorded` row can carry, one per row of the design's
# §3.4 table. `handback.VERDICTS` restates the same tuple (a test pins the equality).
RECORD_VERDICTS = ("clean", "incomplete", "line-faults", "refused", "pass-failed", "pane-held")

# dev #812 / public #169 -- owner ruling (2026-11-05), verbatim: "One free refusal a day." A `returned`
# pass whose run's latest `recorded` row says `refused` is not counted against `linkedin_runs_per_day`,
# for at most this many such passes a day (oldest first); any later one counts. The worst case is
# `linkedin_runs_per_day + 1` passes per day per synced journal.
LINKEDIN_FREE_REFUSALS_PER_DAY = 1

# Where a `recorded` row's `kept` value points: the kept raw hand-back (`handback.HANDBACK_DIR`),
# profile-relative, with `/` separators.
RECORDED_KEPT_PREFIX = ".jobsearch/handbacks/"

# design-script-first.md §2 — V0's only LinkedIn pass kind. A tuple, not a bare string field, so
# a second kind (were one ever added) is a vocabulary addition here, never free-text drift —
# `REASONS`/`TRIAGE_VERDICTS`'s own "counted, not narrated" rule, applied to `kind`.
#
# dev #820 / public #175 (design-role-pipeline.md section 9, 17 N7) -- five more kinds, all rows the SCRIPT
# or the dispatching run writes about a drain step: `reader` and `research` (a `dispatched` row naming
# the ids handed to a `jd-reader` / `opportunity-researcher` agent, written BEFORE the dispatch),
# `feeds` (the feed poll was started), and `capture` / `fetch` (a bounded verb's call ended: the
# `unreached` ids). A 0.81.0 reader tolerates the new kinds (it validates the event name only).
PASS_KINDS = ("linkedin", "board", "reader", "research", "feeds", "capture", "fetch")
AGENT_PASS_KINDS = ("reader", "research")          # `ids` required on dispatched/returned
UNREACHED_PASS_KINDS = ("capture", "fetch")        # phase `done`, with `unreached`

# dev #770-4 / O4 -- the `sweep` field of a `board` pass: which kind of board-sweeper work it covered
# (`config_keys.SWEEP_KINDS`, restated here so this module imports nothing new). See `record_pass`.
BOARD_SWEEPS = ("company", "board")

# dev #785 / public #167 -- the weekday vocabulary of a `split_days` field (`config_keys.WEEKDAYS`,
# restated here for the same reason as `BOARD_SWEEPS`). See `record_pass`.
SPLIT_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# design-script-first.md §8.2 (public #90/#111) — the ONE required shape for a `dispatch` row.
# Strict parser discipline reused from `scripts/dispatch_ledger.py` (the MAINTENANCE ledger this
# is a sibling of, never a second copy of — see §8.2's own "what this is not" section): an
# unknown key is refused, an incomplete row is refused, both at read time (`read()` below) and
# at write time (`record_dispatch()`).
DISPATCH_FIELDS = ("event", "run_id", "agent", "agent_id", "model", "tokens", "tool_uses",
                   "duration_s", "outcome", "for", "at")

# §3.4's hand-back rule 6 vocabulary (DONE|PARTIAL|BLOCKED — build-list item 6, not landed on any
# plugin agent yet), lower-cased to the maintenance ledger's own outcome words where they
# coincide (dispatch_ledger.py's OUTCOMES: landed|partial|stopped|redone). A hand-back that does
# not (yet) start with one of these three still gets an outcome — its own first word, lower-cased
# — rather than an empty field: "unparseable" is LOUD, never a blank read as fine.
OUTCOME_MAP = {"done": "landed", "partial": "partial", "blocked": "stopped"}

# A reason is a CODE, not a sentence — codes can be counted, sentences cannot. An unrecognised
# one is refused rather than stored, because a taxonomy nobody enforces becomes free text within
# a month and then nothing can group by it. dev #321 (V0): `swept ok:false` rows use this same
# set — a failed sweep is the same shape of "why didn't this complete" as a gap.
REASONS = {"browser-unavailable", "credential-missing", "rate-limited", "timeout",
           "partial-results", "skipped-for-cost", "upstream-error", "interrupted", "other",
           # ⭐ dev #354 / public #91's own gate — `linkedin-runner.md:247` and this file's own
           # D14 refusal message (below) have instructed `--reason surface-unreachable` since
           # public #15, while this set never actually admitted it: every such call was
           # refused by argparse's own `choices=sorted(REASONS)`, the exact "a shipped file
           # instructs a flag/value its own target refuses" shape check_cli_flags.py now scans
           # for. A page that never opened at all — distinct from `browser-unavailable`
           # (nothing answers) and from public #96's `render-stalled` (the page answered, the
           # click landed, nothing painted — a separate, not-yet-built token).
           "surface-unreachable",
           # design-linkedin-runner-resilience.md §8 (public #47/#96) — closing the two tokens
           # the comment above named as not-yet-built. `pane-held`: a `--take` on
           # `runlock.py --resource pane` was refused because another run genuinely holds it
           # (§1) — distinct from `browser-unavailable` (nothing answers at all). `render-stalled`:
           # the pane's own paint-proof missed twice, 4s apart, while the document stayed visible
           # (§2) — the page answered, a click may have landed, nothing painted. Reusing
           # `browser-unavailable` for either would erase exactly the signal these two issues say
           # is missing; a code exists to be counted.
           "pane-held", "render-stalled",
           # design-role-pipeline.md 9.1 (jobsearch 0.82.0): the prose is newer than the scripts, and a
           # drain verb is refused as unknown. A gap for that is not `other`: a code exists to be counted,
           # and "how often is the install behind its instructions" is a question worth asking.
           "version-skew",
           # dev #826 / public #177 (jobsearch 0.83.0, design-sweep-misfires.md section 2.4). The Browser pane was
           # not painting and the pass ran in HIDDEN MODE: the harness reported the pane hidden, or the page reported
           # itself hidden; stall detection and clicks were withheld, and the list surfaces were read by text only.
           # It is NOT `render-stalled` (a displayed pane that stopped painting, public #96): reusing that code would
           # erase the signal #177 says is missing, and a code exists to be counted. HOW TO COUNT IT: the pass-level
           # gap is scoped `linkedin:pane-hidden` (the in-app pane) or `linkedin:chrome-tab-hidden` (the extension),
           # one scope per reason because a gap id is (run, scope) and `linkedin:pane` already carries
           # `render-stalled` and `pane-held`. A gap closed by an attended run and reopened by the next hidden pass
           # is a NEW `gap` row (the journal is append-only; the old one stays closed): the number of hidden passes
           # over a period is the number of `gap` events on those two scopes, and the number still owed is the open
           # ones. A surface a hidden pass could not read by text is a `linkedin:<token>` gap with this reason too
           # (`SURFACE <token> UNREACHABLE reason=pane-hidden`): count those for WHICH lists went unread.
           "pane-hidden",
           # dev #826 (R2-SURF-3): the `tabs_context` display line could not be read after the pane was open
           # (`PANE state=unknown`): a harness rewording, or a parse slip. The pass applies the pre-0.83 rule, which
           # is #826 itself, so the user must see it without reading a transcript: this gap is open until a later
           # pass reads one of the two pinned literals (`displayed`, `hidden`). Scope `linkedin:pane`.
           "pane-unreadable",
           # dev #830 / public #180 (jobsearch 0.84.0, design-coverage-regressions.md section 2.5). A channel not swept names
           # its REAL cause, never `other`. `run-budget`: `channels_due.py --board-batch` ended the board loop (its batch cap
           # or its time budget) before this channel was handed out; written by the script, never by the sweeper.
           # `route-refused`: `route.py` refused this id (`HAS AN UNREADABLE ROUTE`, `NO SUCH CHANNEL`); written by the
           # sweeper for one id. `run-ended`: `journal --end` found the batch loop open and closed it, so this channel was
           # never handed out; written by the script, never by the sweeper. A cost stop reuses `skipped-for-cost`.
           "run-budget", "route-refused", "run-ended"}

# ⭐ dev #321 — a `probe` result is either the literal "empty" or "thread:<ISO timestamp>" (the
# newest inbound's date/time) — Class C's own vocabulary, settled here since V0 is the first
# design to ship it. Anything else is refused, loud, at write time (the precondition.py rule).
PROBE_RESULT_RE = re.compile(r"^(empty|thread:\d{4}-\d{2}-\d{2}.*)$")

STALE_DAYS = 3

# ⭐ public #69 — the SAME citation vocabulary `check_regression_links.py` already established
# for regression-case docstrings, reused here so a gap's `covered_by` and a test's class
# docstring speak one language rather than inventing a second. Case-insensitive; canonicalized
# to lowercase-kind + a single space before storing, so two spellings of the same issue never
# look like two different suppressions.
CITATION_RE = re.compile(r"^\s*(dev|github|marketplace|public)\s*#\s*([1-9]\d*)\s*$",
                         re.IGNORECASE)

# ⭐ dev #711 / public #147 — bounds on the reason a `covered_by` must carry. Not a quality check
# (nothing here can judge one): the floor refuses "ok"/"n/a", the ceiling keeps it a reason and
# not a paragraph. Counted after whitespace is collapsed.
COVERED_REASON_MIN, COVERED_REASON_MAX = 12, 240

# ⭐ dev #711 / public #147 — where `--check-coverage` leaves its verdicts so the routine, offline
# `--check` can read them. Per-profile engine state, gitignored with the rest of `.jobsearch/`
# (declared in docs/user/jobsearch/your-data.md). Verdict + date only: no issue titles, so the
# folder's "nothing about your search" promise holds.
COVERAGE_CACHE = os.path.join(STATE_DIRNAME, "coverage_check.json")
COVERAGE_STATES = ("OPEN", "CLOSED", "MISSING")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ⭐ public #99 — the per-uid TRIAGE disposition an alert-digest sweep writes so a LATER run can
# skip a uid it already surfaced instead of re-fetching and re-screening it every day it still
# falls inside the search window. This copies the ATS sweep's own per-uid idempotency discipline
# (design-inbound-resolution.md §5, dev #376) rather than inventing a second mechanism: ONE
# ledger (this file's `data/runs.jsonl`), not two. Unlike the ATS sweep, whose idempotency mark
# is a permanent `messages.jsonl` row (a resolved receipt is never re-seen), a digest sweep never
# writes to any data store — it only surfaces mail for the run to read — so its own disposition
# lives here as a new event kind rather than riding on a store row that does not exist for it.
#
# A verdict is a CODE, matching REASONS' own "counted, not narrated" rule. `alert_sweep.py` does
# not classify a digest's content today — it only surfaces it — so exactly one verdict exists;
# the set stays a set (not a bare string field) so a future verdict (e.g. a script-side
# duplicate-role check) is a vocabulary addition here, not a free-text drift.
TRIAGE_VERDICTS = {"surfaced"}

# How far back a `triaged` row still counts as a live disposition — BOUNDED, never unbounded
# growth of what a sweep must scan to answer "have I seen this uid before". Unlike the ATS
# sweep's mark (permanent, because a resolved receipt is never re-fetched), a digest uid can
# only ever be RE-FOUND by a later run while it still falls inside that run's own
# `newer_than:Nd` search window — `alert_sweep.py`'s own `--days` (default 1, rarely widened).
# A disposition older than the widest window the sweep can reasonably run can never be re-checked
# against a live search hit, so keeping it forever would only grow the ledger scan for no
# caller that could ever ask about it. The natural ceiling is the sweep's own lookback, capped
# the same way `mail_client.COVERAGE_BACKFILL_MAX_DAYS` caps the coverage ledger's own backfill
# reach, for the identical reason — this module cannot import `mail_client` (`mail_client`
# imports THIS module, so the reverse would be circular), so the number is repeated, not shared;
# both name the ceiling they express, not each other. A uid outside this window is simply
# treated as never-triaged and re-triaged the next time it is found — see `triaged_uids()`.
TRIAGE_TTL_DAYS = 30


class JournalError(ValueError):
    """Unparseable or unrecognised. Loud on purpose."""


def normalize_citation(raw):
    """Validate and canonicalize a `--covered-by` citation. Loud on anything else — an
    unparseable value is worse than none, because it looks handled and is not (the same rule
    this marketplace states for `precondition.py`, applied here to #69)."""
    m = CITATION_RE.match(raw or "")
    if not m:
        raise JournalError(
            "--covered-by %r is not a recognised citation — use 'dev #N', 'public #N', "
            "'marketplace #N' or 'GitHub #N' (check_regression_links.py's own vocabulary)"
            % raw)
    return "%s #%s" % (m.group(1).lower(), m.group(2))


def head_sha(root):
    """dev #703 -- `git rev-parse HEAD` in the profile, or None when git cannot answer (not a
    repository, no commits yet, no git on PATH, a timeout). None is "could not ask", which the
    caller records as an ABSENT field rather than a guess."""
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "HEAD"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (r.stdout or "").strip()
    return sha if r.returncode == 0 and re.match(r"^[0-9a-f]{7,64}$", sha) else None


def path(root):
    return os.path.join(root, JOURNAL)


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


# ⭐⭐ dev #313 — THE ONE CHOKE POINT, GUARDED ONCE. Every write site in this file — `--fired`,
# `--start`, `--note`, `--gap`, `--gap-closed`, `--end` (including its `footprint`), `--dispose`,
# `record_swept`, `record_probe` — funnels through this single `append()`, so a guard here covers
# all of them without touching each call site individually.
#
# `journal.py --fired` is the FIRST SessionStart hook, ahead of `migrate.py` — so it is the first
# shipped write of any session, and `scripts/run_shipped.py`'s DEFAULT (safe-by-construction) pin
# points `CLAUDESEARCH_ROOT` straight at the tracked, checked-in fixture
# (`plugins/jobsearch/tests/fixtures/profile`) precisely so a maintainer verification has
# somewhere synthetic to run against. That is exactly the path that triggers this: running the
# hook chain against the fixture the safe way silently created an untracked
# `tests/fixtures/profile/data/runs.jsonl` (issue #313).
#
# `_root.is_tracked_fixture()` is the existing, already-shared predicate (`check_engine_purity.py`,
# `check_profile_leakage.py`, `install_rulebook.py` all use it) — this file adds no new predicate,
# only a caller. Per `_root.py`'s own docstring ("this module resolves; it does not decide
# whether the resolution is safe to act on... every WRITE-capable caller decides that for
# itself"), the refusal lives HERE, in the write-capable caller, not inside `_root.py` itself.
#
# The guard is the TRACKED PATH, not the fixture's *shape* — `is_tracked_fixture` matches on
# `.../tests/fixtures/...` or `.../fixtures/...` appearing in the resolved path, so a scratch
# COPY of the fixture (no `fixtures` segment in its path — e.g. `check_shipped_package.py`'s own
# `tmp/profile` materialization) is a different path and is correctly left writable.
#
# ⭐⭐ dev #618 — AND THE SAME CHOKE POINT REFUSES AN UNBOUND ROOT. `profile_root()`'s last-resort
# fallback is the session's cwd, wrapped in `_root.UnboundRoot`; `--fired` is the first hook of
# every session, so before this check a session opened in ANY directory (an engine checkout, a
# scratch repo) created `data/runs.jsonl` there — and `data/` is a profile marker, so every later
# hook then resolved that directory as a profile and wrote `.jobsearch/` beside it. Refusing here
# covers `--fired` and every other journal write at once; a plain-`str` root (a real profile, a
# scratch profile a test built) is untouched.
def _refuse_if_unwritable(root):
    """The two write refusals every journal write shares (dev #618, dev #313): no profile bound,
    or the tracked fixture. Factored out so the coverage cache (dev #711) obeys the same rule."""
    if is_unbound(root):
        raise JournalError(
            "no job-search profile is bound to %s (no CLAUDESEARCH_ROOT, no profile at or above "
            "it) — journal refuses to create files there. Run from inside a profile, or pin "
            "CLAUDESEARCH_ROOT (dev #618)" % root)
    if is_tracked_fixture(root):
        raise JournalError(
            "%s is the tracked fixture — journal refuses to write; pin CLAUDESEARCH_ROOT to a "
            "scratch copy" % root)


def append(root, rec):
    _refuse_if_unwritable(root)
    p = path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def read(root):
    out = []
    try:
        with open(path(root), encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    raise JournalError("%s line %d is not valid JSON — a journal that cannot be "
                                       "read is a journal that is not protecting anything"
                                       % (JOURNAL, n))
                if rec.get("event") not in EVENTS:
                    raise JournalError("%s line %d has unknown event %r"
                                       % (JOURNAL, n, rec.get("event")))
                if rec.get("event") in ("drain", "mail-status", "readmit"):
                    try:
                        _ROW_CHECKS[rec["event"]](rec)
                    except JournalError as e:
                        raise JournalError("%s line %d %s row: %s" % (JOURNAL, n, rec["event"], e))
                if rec.get("event") == "dispatch":
                    missing = [k for k in DISPATCH_FIELDS if k not in rec]
                    unknown = [k for k in rec if k not in DISPATCH_FIELDS]
                    if missing:
                        raise JournalError(
                            "%s line %d dispatch row missing field(s): %s"
                            % (JOURNAL, n, ", ".join(missing)))
                    if unknown:
                        raise JournalError(
                            "%s line %d dispatch row has unknown field(s): %s — this parser "
                            "refuses what it cannot read rather than ignoring it"
                            % (JOURNAL, n, ", ".join(unknown)))
                out.append(rec)
    except FileNotFoundError:
        pass
    return out


def new_run_id(kind, at):
    slug = re.sub(r"[^a-z0-9]+", "-", (kind or "run").lower()).strip("-") or "run"
    return "%s-%s" % (slug, re.sub(r"[^0-9]", "", at)[:14])


def unfinished(recs):
    """Runs with a start and no end. ⭐ Their notes are the recoverable work.

    ⭐ public #72 — a dead run also carries whether its stranded notes were REVIEWED
    (`dispose`), so `--check` can tell "nobody has looked at this yet" from "looked at, nothing
    to write" instead of flagging both as an unresolved failure forever."""
    started, ended, disposed = {}, set(), {}
    for r in recs:
        if r["event"] == "start":
            started[r["run_id"]] = r
        elif r["event"] == "end":
            ended.add(r["run_id"])
        elif r["event"] == "dispose":
            disposed[r["run_id"]] = r          # last dispose wins if it ever happens twice
    out = []
    for rid, s in started.items():
        if rid in ended:
            continue
        notes = [r for r in recs if r.get("run_id") == rid and r["event"] == "note"]
        gaps = [r for r in recs if r.get("run_id") == rid and r["event"] == "gap"]
        d = disposed.get(rid)
        out.append({"run_id": rid, "at": s.get("at"), "kind": s.get("kind"),
                    "notes": [n.get("text") for n in notes], "gaps": len(gaps),
                    "disposed": bool(d), "disposed_at": d.get("at") if d else None,
                    "disposed_because": d.get("because") if d else None})
    return sorted(out, key=lambda x: x.get("at") or "")


def open_gaps(recs, run_id=None):
    """Every open (not `gap-closed`) `gap` event, oldest first — journal-wide by default.

    `run_id`, added for design-linkedin-runner-resilience.md §4 (closes D-5's sibling): when
    given, restricts to gaps opened by THAT run. `--end` uses this to report `gaps_open` (this
    run's own count, so a pass that opened nothing ends clean) alongside the unfiltered
    `gaps_open_all` — an older gap standing elsewhere must stay visible, just not blamed on a
    run that never touched it."""
    closed = {r.get("gap_id") for r in recs if r["event"] == "gap-closed"}
    gaps = [r for r in recs if r["event"] == "gap" and r.get("gap_id") not in closed]
    if run_id is not None:
        gaps = [g for g in gaps if g.get("run_id") == run_id]
    return sorted(gaps, key=lambda g: g.get("at") or "")


def split_gaps(gaps):
    """⭐ public #69 — (uncovered, covered). An uncovered gap is unexplained and is what ages
    into `--check`'s stale list; a covered one names the issue that already explains it and is
    reported every run (queryable, never silent) but never chased as if it were new."""
    uncovered = [g for g in gaps if not g.get("covered_by")]
    covered = [g for g in gaps if g.get("covered_by")]
    return uncovered, covered


def fired_events(recs):
    """Every `fired` record — proof a SessionStart hook ran, independent of whether the run's
    own `--start` ever followed it. See the module docstring, public #65."""
    return sorted((r for r in recs if r.get("event") == "fired"), key=lambda r: r.get("at") or "")


def run_events(recs, run_id):
    """dev #820 / public #175 (N1) -- the records that are `run_id`'s OWN: those whose `run_id` field
    names it (`start`, `note`, `gap`, `pass`, `drain`, `roles`, `feeds`, `end`, ...). A `fired` record
    is never anyone's: it carries only a session id and a cwd, and every SessionStart on the machine
    writes one, a compaction or resume of the run's own session included. A close written ON BEHALF of
    a run (`on_behalf_of`) names that run in `run_id` but is the CLOSING run's act, not this run's, so
    it is not counted either: if it were, closing a dead run would make it look alive again.
    `lifecycle` decides a run is over from the latest of these."""
    return [r for r in recs if r.get("run_id") == run_id and r.get("event") != "fired"
            and not r.get("on_behalf_of")]


def record_swept(root, mailbox, frm, through, by, ok, reason=None, at=None, source=None):
    """⭐ dev #321 (V0) — the ONE writer for positive mailbox coverage. `ok=True` needs `frm`
    and `through` (the window this sweep actually searched, ISO timestamps) — a positive
    coverage row with no window is not verifiable, so that shape is refused rather than stored
    with nulls. `ok=False` needs a REASON CODE from `REASONS` (the same "a code can be counted,
    a sentence cannot" rule the rest of this journal already enforces) and stores no window: a
    failed sweep covers nothing, which is the whole point — this is the `!! INCOMPLETE COVERAGE`
    banner stored instead of merely printed, so `covered_through()` for that mailbox does not
    advance past whatever it already had.

    ⭐ dev #799 — `source`, optional and ADDITIVE: `"connector-bundle"` marks a row whose window is the
    span a fetched connector bundle covered. Absent means IMAP, so every old row keeps its meaning; no
    reader refuses an unknown key on a `swept` row (checked at the build: `read()` validates only the
    `dispatch` shape).

    ⭐ dev #807 — `frm` and `through` are INSTANTS: an aware datetime (written through `coverage_iso`) or
    an ISO string that carries a numeric offset. A naive value is REFUSED, because a naive local time in
    the fall-back hour names two instants and the reader cannot tell which one the writer meant. `at`
    keeps the journal-wide naive-local convention (`reconcile.first_swept_at` sorts it as a string), so
    an aware `at` is converted to naive host-local here."""
    at = _journal_at(at) if at else now_iso()
    if not mailbox:
        raise JournalError("record_swept requires a mailbox")
    if ok:
        if not (frm and through):
            raise JournalError(
                "record_swept(ok=True) requires frm and through — the window this sweep "
                "actually searched. A positive coverage row with no window is not verifiable.")
        frm, through = _coverage_field(frm, "frm"), _coverage_field(through, "through")
        rec = {"event": "swept", "mailbox": mailbox, "from": frm, "through": through,
               "at": at, "by": by or "", "ok": True}
        if source:
            rec["source"] = source
    else:
        if reason not in REASONS:
            raise JournalError(
                "record_swept(ok=False) requires reason in REASONS, got %r — a failure without "
                "a reason code cannot be counted or grouped" % reason)
        rec = {"event": "swept", "mailbox": mailbox, "from": None, "through": None,
               "at": at, "by": by or "", "ok": False, "reason": reason}
    return append(root, rec)


def record_triaged(root, mailbox, uid, verdict, by, at=None):
    """⭐ public #99 — the completion mark for one triaged uid. `mailbox` is REQUIRED and stored
    alongside `uid` (never a bare `"<mailbox>:<uid>"` string) so two mailboxes that happen to
    reuse the same IMAP uid number are never confused by a caller that filters on `mailbox`
    first, the same shape `record_swept`'s own `mailbox` field already has.

    ⭐ Call this ONLY after a uid's disposition is actually decided — for `alert_sweep.py`, after
    its header fetch and its own row is built, never before. A run killed between fetching a uid
    and calling this leaves NO row for it, so the next run finds it un-triaged and processes it
    again — the same crash-safety the ATS sweep's own uid mark has (design-inbound-resolution.md
    §5): an unwritten disposition is re-seen next run, never silently skipped, by construction
    rather than by a recovery pass."""
    at = at or now_iso()
    if not mailbox:
        raise JournalError("record_triaged requires a mailbox")
    if not uid:
        raise JournalError("record_triaged requires a uid")
    if verdict not in TRIAGE_VERDICTS:
        raise JournalError(
            "record_triaged verdict %r is not in TRIAGE_VERDICTS %r — a verdict is a code, not "
            "a sentence" % (verdict, sorted(TRIAGE_VERDICTS)))
    rec = {"event": "triaged", "mailbox": mailbox, "uid": str(uid), "verdict": verdict,
           "at": at, "by": by or ""}
    return append(root, rec)


def record_dispatch(root, run_id, agent, agent_id, model, tokens, tool_uses, duration_s,
                    outcome, for_="", at=None):
    """⭐ design-script-first.md §8.2 (public #90/#111) — the ONE writer for a `dispatch` row.
    Every numeric field is required and type-checked: a dispatch row nobody can trust the
    numbers of is worse than none (this file's own "unparseable value must be LOUD" rule,
    applied to the cost ledger the fold below builds). `agent_id` is the fold's idempotence
    key — refused empty, the same way `record_probe` refuses an empty `subject`/`thread`."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_dispatch requires run_id")
    if not agent:
        raise JournalError("record_dispatch requires agent")
    if not agent_id:
        raise JournalError("record_dispatch requires agent_id — it is the fold's idempotence key")
    for name, v in (("tokens", tokens), ("tool_uses", tool_uses), ("duration_s", duration_s)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise JournalError("record_dispatch: %s must be an int >= 0 (got %r)" % (name, v))
    rec = {"event": "dispatch", "run_id": run_id, "agent": agent, "agent_id": agent_id,
           "model": model or "", "tokens": tokens, "tool_uses": tool_uses,
           "duration_s": duration_s, "outcome": outcome or "unknown", "for": for_ or "", "at": at}
    return append(root, rec)


def dispatch_rows(recs, today_only=False):
    rows = [r for r in recs if r.get("event") == "dispatch"]
    if today_only:
        today = now_iso()[:10]
        rows = [r for r in rows if str(r.get("at", ""))[:10] == today]
    return rows


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def check_recorded_fields(verdict, faults, kept, concluded, not_concluded):
    """dev #812 / public #169 (design §4, §15 N13) -- the ONE validation of a `recorded` pass row's
    fields. PURE: it reads nothing and writes nothing, and raises `JournalError` on any combination
    it refuses. `record_pass` calls it, and so does the `judge` test, which feeds every verdict
    `linkedin_sweep.py` can reach through it: a combination refused here fails that test and is
    never an `apply` exception.

      * `verdict` is one of `RECORD_VERDICTS`;
      * `faults` is an int >= 0: **0** on `clean`, `incomplete` and `refused` (a structural refusal
        judges no lines), **> 0** on `line-faults`, **>= 0** on `pass-failed` and `pane-held` (a
        pass that reached nothing can still carry garbled lines);
      * `kept` is `""` (no copy was kept, or the write failed) or a profile-relative path under
        `.jobsearch/handbacks/` (no `..` segment);
      * `concluded` and `not_concluded` are ints >= 0."""
    if verdict not in RECORD_VERDICTS:
        raise JournalError("a recorded pass row's verdict %r is not one of RECORD_VERDICTS %r"
                           % (verdict, RECORD_VERDICTS))
    if not _is_count(faults):
        raise JournalError("a recorded pass row's faults=%r is not a non-negative integer" % (faults,))
    if verdict == "line-faults" and faults == 0:
        raise JournalError("a recorded pass row with verdict 'line-faults' must carry faults > 0")
    if verdict in ("clean", "incomplete", "refused") and faults != 0:
        raise JournalError("a recorded pass row with verdict %r must carry faults=0 (got %r): "
                           "only line-faults, pass-failed and pane-held carry line faults"
                           % (verdict, faults))
    if not isinstance(kept, str):
        raise JournalError("a recorded pass row's kept=%r is not a string (use '' for no copy)"
                           % (kept,))
    if kept:
        tail = kept[len(RECORDED_KEPT_PREFIX):]
        if (not kept.startswith(RECORDED_KEPT_PREFIX) or not tail or "\\" in kept
                or ".." in kept.split("/")):
            raise JournalError("a recorded pass row's kept=%r is not a path under %s"
                               % (kept, RECORDED_KEPT_PREFIX))
    for label, v in (("concluded", concluded), ("not_concluded", not_concluded)):
        if not _is_count(v):
            raise JournalError("a recorded pass row's %s=%r is not a non-negative integer"
                               % (label, v))


def _check_ids(label, ids, nonempty):
    """A list of distinct ids: strings, non-empty, without whitespace. Opportunity ids, capture item ids
    and company ids all satisfy it."""
    if (not isinstance(ids, (list, tuple)) or (nonempty and not ids)
            or any(not isinstance(i, str) or not i or re.search(r"\s", i) for i in ids)
            or len(set(ids)) != len(ids)):
        raise JournalError("record_pass %s=%r is not %sa list of distinct ids (non-empty strings "
                           "without whitespace)" % (label, ids, "non-empty " if nonempty else ""))


def _check_channels(channels):
    """dev #811 / public #170 (design §5.3) -- a `pass board dispatched` row's `channels`: the ids of
    the call's combined worklist. A non-empty list of DISTINCT non-empty strings without whitespace."""
    if (not isinstance(channels, (list, tuple)) or not channels
            or any(not isinstance(c, str) or not c or re.search(r"\s", c) for c in channels)
            or len(set(channels)) != len(channels)):
        raise JournalError("record_pass channels=%r is not a non-empty list of distinct channel ids "
                           "(non-empty strings without whitespace)" % (channels,))


# dev #826 / public #177 (jobsearch 0.83.0, design-sweep-misfires.md section 2.4) -- what a `recorded` LinkedIn
# pass row says about the Browser pane. `pane` is the state the runner read from the harness (`displayed`,
# `hidden`, `unknown`) or `not-pane` (the pass ran on the Chrome extension); `unreported` is the script's own word
# for a SWEEP block that carried no readable `PANE` line, never something the runner writes. `mode` is whether any
# part of the pass ran in hidden mode; `unreported` goes with `pane == "unreported"` only, because a pass whose
# pane line is missing proves neither mode.
PASS_PANE_STATES = ("displayed", "hidden", "unknown", "not-pane", "unreported")
PASS_PANE_MODES = ("normal", "hidden", "unreported")


def _check_owned_elsewhere(owned):
    """dev #830 / public #180 (C6, owner ruling O2) -- a `pass board dispatched` row's `owned_elsewhere`: a non-empty
    `{channel_id: {"agent": str, "rule": OWNED_RULES}}`, the agent never `board-sweeper` (a channel the sweeper owns is in
    its worklist, not excluded from it)."""
    if not isinstance(owned, dict) or not owned:
        raise JournalError("record_pass owned_elsewhere=%r is not a non-empty {channel_id: {agent, rule}} map" % (owned,))
    for cid, v in owned.items():
        if not isinstance(cid, str) or not cid or re.search(r"\s", cid):
            raise JournalError("record_pass owned_elsewhere has the channel id %r (a non-empty string without "
                               "whitespace)" % (cid,))
        if (not isinstance(v, dict) or set(v) != {"agent", "rule"} or not isinstance(v["agent"], str) or not v["agent"]
                or v["agent"] == "board-sweeper" or v["rule"] not in OWNED_RULES):
            raise JournalError("record_pass owned_elsewhere[%r]=%r is not {agent: <an agent other than board-sweeper>, "
                               "rule: one of %s}" % (cid, v, ", ".join(OWNED_RULES)))


def record_pass(root, run_id, kind, phase, reached=None, unreachable=None, not_attempted=None,
                reason=None, at=None, jobsearch=None, sweep=None, attended=None,
                split_days=None, *, verdict=None, faults=None, kept=None, concluded=None,
                not_concluded=None, channels=None, ids=None, unreached=None,
                pane=None, mode=None, partial=None, batch=None, of=None, t0_utc=None, state=None,
                code=None, handed=None, worklist=None, owned_elsewhere=None):
    """design-script-first.md §2 (public #75/#87/#110) — the ONE writer for a `pass` row.
    `phase` is validated against `PASS_PHASES`, `kind` against `PASS_KINDS`, `reason` against
    `REASONS` (required for `phase="refused"`, refused otherwise — a reason on a row that is not
    a refusal is not a reason for anything). `reached`/`unreachable`/`not_attempted` are each
    validated against `LINKEDIN_SURFACES` when `kind == "linkedin"` when given at all: an
    unrecognised surface token is refused at write, the same "unparseable value must be LOUD"
    rule this whole file applies everywhere else. Every field is stored even when empty ([] is
    written, not omitted) so a reader never has to tell 'absent' from 'empty list' apart.

    dev #812 / public #169 -- `phase="recorded"` (a LinkedIn row only) is what `linkedin_sweep.py
    record` writes after judging a SWEEP hand-back. It REQUIRES the keyword-only `verdict`, `faults`,
    `kept`, `concluded` and `not_concluded`, validated by `check_recorded_fields`; any of the five on
    another phase is refused. dev #811 / public #170 -- the keyword-only `channels` is for a `pass
    board dispatched` row only (the call's combined worklist, `board_worklist` reads it back).

    dev #820 / public #175 (0.82.0) -- the drain's pass kinds. `reader` and `research` rows name the
    ids handed to an agent: `ids` (a non-empty list of distinct ids) is REQUIRED on their `dispatched`
    and `returned` rows and refused anywhere else; a `feeds` row may carry the company ids it covered.
    `capture` and `fetch` take phase `done` ONLY, with the keyword-only `unreached` (the ids the bounded
    call did not reach, `[]` when it reached them all); `done` and `unreached` are refused on any
    other kind. `drain_close` reads the LAST `capture` row's `unreached` to give an admitted item the
    cause `deadline-reached`.

    dev #826 / public #177 (0.83.0) -- the keyword-only `pane`, `mode` and `partial` are a `recorded`
    LinkedIn row's account of the Browser pane: all three or none (a row written before 0.83.0, or a failed
    pass whose block was never read, carries none). `pane` is one of `PASS_PANE_STATES`, `mode` one of
    `PASS_PANE_MODES` (`unreported` exactly when `pane == "unreported"`), and `partial` the surfaces read from
    a pane that was not painting, a subset of `reached`.

    dev #830 / public #180 (0.84.0) -- the board loop's rows. `phase="batch"` (board only) REQUIRES `channels` (the ids
    handed out), `batch` (an int >= 1), `of` (the planned batch count, an int >= batch) and `t0_utc` (an ISO instant WITH a
    UTC offset: batch 1's, copied by later batches). `phase="batch-end"` (board only) REQUIRES `state` (one of
    `BATCH_END_STATES`), `handed` and `worklist` (counts), and may carry `code` (a `REASONS` code). Every one of these
    keywords is refused on any other phase. `owned_elsewhere` is for a `dispatched` board row only: a non-empty
    `{channel_id: {"agent": <owning agent, never board-sweeper>, "rule": one of OWNED_RULES}}`, the channels the worklist
    left out because another agent owns them (`channels_due.owner_elsewhere`)."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_pass requires run_id")
    if kind not in PASS_KINDS:
        raise JournalError("record_pass kind %r is not in PASS_KINDS %r" % (kind, PASS_KINDS))
    if phase not in PASS_PHASES:
        raise JournalError("record_pass phase %r is not in PASS_PHASES %r" % (phase, PASS_PHASES))
    if (phase == "done") != (kind in UNREACHED_PASS_KINDS):
        raise JournalError("record_pass: phase 'done' is for the %s pass kinds and only for them (got "
                           "kind=%r phase=%r)" % (" and ".join(UNREACHED_PASS_KINDS), kind, phase))
    loop_fields = dict(batch=batch, of=of, t0_utc=t0_utc, state=state, code=code, handed=handed, worklist=worklist)
    if phase in ("batch", "batch-end"):
        if kind != "board":
            raise JournalError("record_pass: phase %r is only for a board pass (got kind=%r)" % (phase, kind))
        if phase == "batch":
            need = ("channels", "batch", "of", "t0_utc")
            missing = [k for k in need if (channels if k == "channels" else loop_fields[k]) is None]
            if missing:
                raise JournalError("record_pass(phase='batch') requires %s (missing: %s)" % (", ".join(need),
                                                                                         ", ".join(missing)))
            if not _is_count(batch) or batch < 1 or not _is_count(of) or of < batch:
                raise JournalError("record_pass batch=%r of=%r: batch is an integer >= 1 and of an integer >= batch"
                                   % (batch, of))
            parsed = _parse_iso(t0_utc) if isinstance(t0_utc, str) else None
            if parsed is None or parsed.tzinfo is None:
                raise JournalError("record_pass t0_utc=%r is not an ISO instant with a UTC offset (a naive time "
                                   "cannot be subtracted across a DST change)" % (t0_utc,))
        else:
            missing = [k for k in ("state", "handed", "worklist") if loop_fields[k] is None]
            if missing:
                raise JournalError("record_pass(phase='batch-end') requires state, handed and worklist (missing: %s)"
                                   % ", ".join(missing))
            if state not in BATCH_END_STATES:
                raise JournalError("record_pass state=%r is not one of %r" % (state, BATCH_END_STATES))
            if not _is_count(handed) or not _is_count(worklist) or handed > worklist:
                raise JournalError("record_pass handed=%r worklist=%r: counts, handed <= worklist" % (handed, worklist))
            if code is not None and code not in REASONS:
                raise JournalError("record_pass code=%r is not a REASONS code" % (code,))
    else:
        given_loop = sorted(k for k, v in loop_fields.items() if v is not None)
        if given_loop:
            raise JournalError("record_pass: %s only for phase 'batch' or 'batch-end' (got phase=%r)"
                               % (", ".join(given_loop), phase))
    if owned_elsewhere is not None:
        if kind != "board" or phase != "dispatched":
            raise JournalError("record_pass: owned_elsewhere is only for a board pass with phase='dispatched' "
                               "(got kind=%r phase=%r)" % (kind, phase))
        _check_owned_elsewhere(owned_elsewhere)
    if kind in ("reader", "research", "feeds") and phase not in ("dispatched", "returned", "refused"):
        raise JournalError("record_pass: a %s pass has phases dispatched, returned and refused (got %r)"
                           % (kind, phase))
    if kind in AGENT_PASS_KINDS and phase in ("dispatched", "returned") and ids is None:
        raise JournalError("record_pass: a %s pass %s row names the ids it handed over (ids=[...]); a "
                           "row that names none cannot be checked against what was admitted"
                           % (kind, phase))
    if ids is not None:
        if kind not in AGENT_PASS_KINDS and kind != "feeds":
            raise JournalError("record_pass: ids are for the reader, research and feeds passes (got "
                               "kind=%r)" % kind)
        if kind in AGENT_PASS_KINDS and phase not in ("dispatched", "returned"):
            raise JournalError("record_pass: ids are for a %s pass dispatched or returned row (got "
                               "phase=%r)" % (kind, phase))
        _check_ids("ids", ids, nonempty=kind in AGENT_PASS_KINDS)
    if unreached is not None:
        if kind not in UNREACHED_PASS_KINDS:
            raise JournalError("record_pass: unreached is for the capture and fetch passes (got kind=%r)"
                               % kind)
        _check_ids("unreached", unreached, nonempty=False)
    if phase == "refused" and reason not in REASONS:
        raise JournalError(
            "record_pass(phase='refused') requires --reason from REASONS %r (got %r)"
            % (sorted(REASONS), reason))
    if phase != "refused" and reason is not None:
        raise JournalError("record_pass: --reason is only for phase='refused' (got phase=%r)"
                           % phase)
    # dev #692 / public #140 (R4) -- the explicit JOB SEARCH token. A SEPARATE field, never one of
    # the reached surface tokens: the per-day quota counts a pass that REACHED a list surface, and
    # a pass that only ran its searches must not spend it. Only a LinkedIn `returned` row carries
    # one; the missing-ROLES check keys on `reached`.
    if jobsearch is not None:
        if kind != "linkedin" or phase != "returned":
            raise JournalError("record_pass: --jobsearch is only for a LinkedIn pass with "
                               "phase='returned' (got kind=%r phase=%r)" % (kind, phase))
        if jobsearch not in JOBSEARCH_TOKENS:
            raise JournalError("record_pass jobsearch=%r is not one of %r"
                               % (jobsearch, JOBSEARCH_TOKENS))
    # dev #770-4, owner ruling O4 (jobsearch 0.78.0) -- WHICH board-sweeper work a `board` pass
    # covers: `company` (employer career pages) or `board` (job boards and aggregators), so each kind
    # spends its own weekday slot (`posture.board_spent_on`). An EXTRA FIELD on the existing `board`
    # kind, never a new `kind`: a 0.77.0 `read()` accepts any field on a `pass` row (it validates the
    # event name and `dispatch` rows only), and its missing-ROLES check keys on `kind == "board"`, so
    # a 0.77.0 machine sharing `runs.jsonl` (ADR-012) still expects the sweep's `roles` event. A row
    # without it (any row written before 0.78.0) covered both kinds.
    if sweep is not None:
        if kind != "board":
            raise JournalError("record_pass: sweep is only for a board pass (got kind=%r)" % kind)
        if sweep not in BOARD_SWEEPS:
            raise JournalError("record_pass sweep=%r is not one of %r" % (sweep, BOARD_SWEEPS))
    # dev #770 (/jobsearch:search, jobsearch 0.78.0) -- `attended: true` marks a board pass a person
    # started on demand. It is outside the posture's schedule, so it never spends a scheduled slot
    # (`posture.board_spent_on` skips it): a Monday `/jobsearch:search boards attended` leaves
    # Tuesday's scheduled sweep due. Another EXTRA FIELD, tolerated by a 0.77.0 `read()` for the
    # reason `sweep` is (it validates the event name and `dispatch` rows only).
    if attended is not None:
        if attended is not True or kind != "board" or phase != "dispatched":
            raise JournalError("record_pass: attended=True is only for a board pass with "
                               "phase='dispatched' (got attended=%r kind=%r phase=%r)"
                               % (attended, kind, phase))
    # dev #785 / public #167 (design-sourcing-schedule.md §6, §15 N1) -- `split_days`: the split days
    # whose career pages were in a `company` dispatch's worklist, so each day spends its own slot
    # (`posture.board_spent_on(day=)`). Another EXTRA FIELD on the existing `board` kind, tolerated by an
    # older `read()` for the reason `sweep` is. Refused at WRITE unless the row is an unattended
    # `pass board dispatched` row with sweep `company`, and its value a non-empty list of DISTINCT weekday
    # names in weekday order -- the shape `posture.check_split_days` demands when the journal is read.
    # `None` means "not given" (the field is omitted: every split day, as a pre-0.81.0 row); `[]` is
    # refused, never read as "not given".
    if split_days is not None:
        if kind != "board" or phase != "dispatched" or sweep != "company" or attended:
            raise JournalError(
                "record_pass: split_days is only for an unattended board pass with phase='dispatched' "
                "and sweep='company' (got kind=%r phase=%r sweep=%r attended=%r)"
                % (kind, phase, sweep, attended))
        if (not isinstance(split_days, (list, tuple)) or not split_days
                or any(not isinstance(d, str) or d not in SPLIT_WEEKDAYS for d in split_days)
                or len(set(split_days)) != len(split_days)
                or list(split_days) != sorted(split_days, key=SPLIT_WEEKDAYS.index)):
            raise JournalError(
                "record_pass split_days=%r is not a non-empty list of distinct weekday names (%s) in "
                "weekday order" % (split_days, ", ".join(SPLIT_WEEKDAYS)))
    # dev #812 / public #169 (design §4, §15 N13) -- a `recorded` row says how `linkedin_sweep.py
    # record` judged a SWEEP hand-back. LinkedIn only, and every one of its five fields is required;
    # on any other phase they are refused, never stored (a field on a row that is not a record is not
    # a record of anything).
    recorded_fields = dict(verdict=verdict, faults=faults, kept=kept, concluded=concluded,
                           not_concluded=not_concluded)
    if phase == "recorded":
        if kind != "linkedin":
            raise JournalError("record_pass: phase='recorded' is only for a LinkedIn pass "
                               "(got kind=%r)" % kind)
        missing = sorted(k for k, v in recorded_fields.items() if v is None)
        if missing:
            raise JournalError("record_pass(phase='recorded') requires %s (missing: %s)"
                               % (", ".join(sorted(recorded_fields)), ", ".join(missing)))
        check_recorded_fields(verdict, faults, kept, concluded, not_concluded)
    else:
        given = sorted(k for k, v in recorded_fields.items() if v is not None)
        if given:
            raise JournalError("record_pass: %s only for phase='recorded' (got phase=%r)"
                               % (", ".join(given), phase))
    # dev #826 / public #177 -- the pane account. All three or none; a `recorded` LinkedIn row only.
    pane_fields = dict(pane=pane, mode=mode, partial=partial)
    given_pane = sorted(k for k, v in pane_fields.items() if v is not None)
    if given_pane:
        if kind != "linkedin" or phase != "recorded":
            raise JournalError("record_pass: %s only for a LinkedIn pass with phase='recorded' (got kind=%r "
                               "phase=%r)" % (", ".join(given_pane), kind, phase))
        if len(given_pane) != 3:
            raise JournalError("record_pass: pane, mode and partial go together (missing: %s)"
                               % ", ".join(sorted(set(pane_fields) - set(given_pane))))
        if pane not in PASS_PANE_STATES:
            raise JournalError("record_pass pane=%r is not one of %r" % (pane, PASS_PANE_STATES))
        if mode not in PASS_PANE_MODES:
            raise JournalError("record_pass mode=%r is not one of %r" % (mode, PASS_PANE_MODES))
        if (pane == "unreported") != (mode == "unreported"):
            raise JournalError("record_pass: mode 'unreported' goes with pane 'unreported' and only with it "
                               "(got pane=%r mode=%r)" % (pane, mode))
        if pane == "hidden" and mode != "hidden":
            raise JournalError("record_pass: pane 'hidden' requires mode 'hidden' (a hidden pane is read "
                               "without clicks); got mode=%r" % (mode,))
        if (not isinstance(partial, (list, tuple))
                or any(not isinstance(t, str) for t in partial)
                or len(set(partial)) != len(partial)):
            raise JournalError("record_pass partial=%r is not a list of distinct surface tokens" % (partial,))
        bad = sorted(set(partial) - LINKEDIN_SWEEP_SURFACES)
        if bad:
            raise JournalError("record_pass partial=%r is not in LINKEDIN_SWEEP_SURFACES %r"
                               % (bad, sorted(LINKEDIN_SWEEP_SURFACES)))
        stray = sorted(set(partial) - set(reached or []))
        if stray:
            raise JournalError("record_pass partial=%r names a surface that was not reached (reached=%r)"
                               % (stray, list(reached or [])))
    # dev #811 / public #170 (design §5.3) -- `channels`: the ids of the combined worklist one
    # `channels_due.py --board-decision` call handed the board sweeper, on its `dispatched` row, so
    # `deferred.add_roles` can ask which of them the hand-back accounts for (`board_worklist`). An
    # EXTRA FIELD on the existing `board` kind, tolerated by an older `read()` for the reason `sweep` is.
    if channels is not None:
        if kind != "board" or phase not in ("dispatched", "batch"):
            raise JournalError("record_pass: channels is only for a board pass with "
                               "phase='dispatched' or 'batch' (got kind=%r phase=%r)" % (kind, phase))
        _check_channels(channels)
    reached = list(reached) if reached is not None else []
    unreachable = list(unreachable) if unreachable is not None else []
    not_attempted = list(not_attempted) if not_attempted is not None else []
    if kind == "linkedin":
        for label, tokens in (("reached", reached), ("unreachable", unreachable),
                              ("not_attempted", not_attempted)):
            bad = sorted(set(tokens) - LINKEDIN_SWEEP_SURFACES)
            if bad:
                raise JournalError(
                    "record_pass %s=%r is not in LINKEDIN_SWEEP_SURFACES %r"
                    % (label, bad, sorted(LINKEDIN_SWEEP_SURFACES)))
    rec = {"event": "pass", "run_id": run_id, "kind": kind, "phase": phase,
           "reached": reached, "unreachable": unreachable, "not_attempted": not_attempted,
           "reason": reason or "", "at": at}
    if jobsearch is not None:
        rec["jobsearch"] = jobsearch
    if sweep is not None:
        rec["sweep"] = sweep
    if attended:
        rec["attended"] = True
    if split_days is not None:
        rec["split_days"] = list(split_days)
    if phase == "recorded":
        rec.update(verdict=verdict, faults=faults, kept=kept, concluded=concluded,
                   not_concluded=not_concluded)
    if channels is not None:
        rec["channels"] = list(channels)
    if phase == "batch":
        rec.update(batch=batch, of=of, t0_utc=t0_utc)
    if phase == "batch-end":
        rec.update(state=state, handed=handed, worklist=worklist)
        if code is not None:
            rec["code"] = code
    if owned_elsewhere is not None:
        rec["owned_elsewhere"] = {c: dict(v) for c, v in sorted(owned_elsewhere.items())}
    if given_pane:
        rec.update(pane=pane, mode=mode, partial=list(partial))
    if ids is not None:
        rec["ids"] = list(ids)
    if kind in UNREACHED_PASS_KINDS:
        rec["unreached"] = list(unreached) if unreached is not None else []
    return append(root, rec)


def record_verdict(row):
    """dev #812 / public #169 -- the verdict of a `recorded` pass row. Raises `JournalError` on a row
    that is not one, or whose verdict is outside `RECORD_VERDICTS` (a hand-edited journal): the quota
    count then fails LOUDLY rather than guessing which way an unreadable verdict should lean."""
    if row.get("event") != "pass" or row.get("phase") != "recorded":
        raise JournalError("record_verdict: not a recorded pass row: %r" % (row,))
    verdict = row.get("verdict")
    if verdict not in RECORD_VERDICTS:
        raise JournalError("a recorded pass row (run %r) carries verdict %r, which is not one of "
                           "RECORD_VERDICTS %r" % (row.get("run_id"), verdict, RECORD_VERDICTS))
    return verdict


def _latest_dispatched(recs, run_id):
    """`(index, row)` of the run's LATEST board `dispatched` row (by `at`, ties by file order), or None."""
    rows = [(i, r) for i, r in enumerate(recs)
            if r.get("event") == "pass" and r.get("kind") == "board"
            and r.get("phase") == "dispatched" and r.get("run_id") == run_id]
    if not rows:
        return None
    return max(rows, key=lambda t: (str(t[1].get("at", "")), t[0]))


def board_worklist_dispatched(recs, run_id):
    """dev #811 / public #170 (design §5.3) -- the combined worklist of the run's LATEST board
    `dispatched` row (by `at`, ties by file order), as a list of channel ids. `None` when the run
    has no such row, or the latest one lacks the field (written before 0.82.0): "no worklist on
    record" is a state the caller prints as NOT CHECKED, never an empty worklist. A repeated
    `--board-decision` in one run therefore supersedes the earlier call. Raises `JournalError` on a
    `channels` value that is present and unreadable (a hand-edited journal). (Until 0.84.0 this was `board_worklist`;
    `channels_due.py --board-batch` reads the whole worklist through it.)"""
    got = _latest_dispatched(recs, run_id)
    if got is None:
        return None
    latest = got[1]
    if "channels" not in latest:
        return None
    channels = latest["channels"]
    try:
        _check_channels(channels)
    except JournalError as e:
        raise JournalError("the board dispatched row of run %r carries an unreadable worklist: %s"
                           % (run_id, e))
    return list(channels)


def _batch_rows(recs, run_id):
    """`(batch rows, batch-end rows)` of the run written AFTER its latest board `dispatched` row, in file order."""
    got = _latest_dispatched(recs, run_id)
    if got is None:
        return [], []
    after = [r for i, r in enumerate(recs) if i > got[0] and r.get("event") == "pass"
             and r.get("kind") == "board" and r.get("run_id") == run_id]
    return ([r for r in after if r.get("phase") == "batch"], [r for r in after if r.get("phase") == "batch-end"])


def board_batch_current(recs, run_id):
    """dev #830 / public #180 -- `(n, channels)` of the run's latest board `batch` row written after its latest
    `dispatched` row, or None when the run has none (the attended path, a 0.83.0-shaped run, or a run whose loop never
    started). `deferred.add_roles` reads it to know which batch a hand-back belongs to."""
    batches, _ends = _batch_rows(recs, run_id)
    if not batches:
        return None
    last = max(batches, key=lambda r: r.get("batch", 0))
    return last.get("batch"), list(last.get("channels") or [])


def board_worklist(recs, run_id):
    """The ids a board hand-back is checked against: the run's latest `batch` row's `channels` when the run has a batch
    row after its latest `dispatched` row (dev #830 / public #180, 0.84.0), otherwise the `dispatched` row's whole
    worklist exactly as before (`board_worklist_dispatched`). `None` = no worklist on record (NOT CHECKED)."""
    cur = board_batch_current(recs, run_id)
    if cur is not None:
        return cur[1]
    return board_worklist_dispatched(recs, run_id)


def board_batches(recs, run_id):
    """dev #830 / public #180 (design §2.4.4) -- the board loop of one run, as a dict, or None when the run has no
    board `dispatched` row:

      worklist       the `dispatched` row's channels (``[]`` when it carries none)
      batches        ``[(n, channels)]`` in batch order
      of             the planned batch count the last `batch` row stated (0 with no batch)
      handed         the ids of every batch, in hand-out order
      unhanded       worklist ids no batch handed out
      open_batches   batch numbers with no board `roles` event carrying that `batch` (a sweeper that crashed, or a
                     hand-back never added)
      terminal       the run's latest `batch-end` row, or None
    """
    got = _latest_dispatched(recs, run_id)
    if got is None:
        return None
    batches, ends = _batch_rows(recs, run_id)
    wl = got[1].get("channels") if isinstance(got[1].get("channels"), list) else []
    ordered = sorted(batches, key=lambda r: r.get("batch", 0))
    handed = []
    for r in ordered:
        for c in r.get("channels") or []:
            if c not in handed:
                handed.append(c)
    have = {e.get("batch") for e in recs if e.get("event") == "roles" and e.get("surface") == "board"
            and e.get("run_id") == run_id}
    return {"worklist": list(wl), "batches": [(r.get("batch"), list(r.get("channels") or [])) for r in ordered],
            "of": max([r.get("of", 0) for r in ordered] or [0]), "handed": handed,
            "unhanded": [c for c in wl if c not in set(handed)],
            "open_batches": [r.get("batch") for r in ordered if r.get("batch") not in have],
            "terminal": ends[-1] if ends else None}


_ROLES_SUM_FIELDS = ("queries", "query_gaps_window", "query_gaps_truncated", "distinct", "captured", "known", "carried",
                     "role_gaps", "quarantined", "query_gaps_filters", "captured_degraded", "q_reached", "q_clean",
                     "q_unread", "q_total_unknown", "q_degraded_queries", "line_faults", "channels_reached")


def board_roles_run(recs, run_id):
    """dev #830 / public #180 (design §2.4.3) -- THE ONE FOLD of a run's board `roles` events, or None when it has
    none. Every reader of the board's coverage (run_summary, coverage, check_runs, add_roles) reads the run through it.

    A board event written from a batch carries `batch: n` (>= 1); the script's closing event (budget spent, a pass-wide
    stop, a loop left open) carries `batch: 0`; an event with no `batch` key (written before 0.84.0, or on the attended
    path) belongs to key None. (1) The run's events are grouped by `(window, batch)` and the LATEST of each group kept
    (by `at`, ties by file order), so a corrected re-submission still supersedes within ONE batch. (2) The kept events are
    folded: counters are summed, per-code maps (`q_degraded`, `quarantine_reasons`) summed per code, channel maps
    unioned, lists concatenated, `geos_ok` unioned, `channels_worklist` is the dispatched worklist's own length.
    (3) `coverage` is `partial` when any kept event is, when `board_batches` has unhanded ids or an open batch, or when
    the terminal state is not `done`. A role listed on two channels in two batches is counted twice in `distinct`
    (named, accepted: `captured` and `known` are resolved per role). A run whose events all lack `batch` returns its
    latest event UNCHANGED, which is today's latest-wins."""
    evs = [(i, e) for i, e in enumerate(recs) if e.get("event") == "roles" and e.get("surface") == "board"
           and e.get("run_id") == run_id]
    if not evs:
        return None
    best = {}
    for i, e in evs:
        key = (e.get("window"), e.get("batch"))
        rank = (str(e.get("at", "")), i)
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, e)
    kept = [e for _rank, e in sorted(best.values(), key=lambda t: t[0])]
    if all(e.get("batch") is None for e in kept):
        return kept[-1]
    out = dict(kept[-1])
    for f in _ROLES_SUM_FIELDS:
        out[f] = sum(int(e.get(f) or 0) for e in kept)
    for f in ("q_degraded", "quarantine_reasons"):
        m = {}
        for e in kept:
            for code, n in (e.get(f) or {}).items():
                m[code] = m.get(code, 0) + n
        out[f] = m
    for f in ("channels_unreachable", "channels_not_attempted"):
        m = {}
        for e in kept:
            m.update(e.get(f) or {})
        out[f] = m
    for f in ("channels_unaccounted", "channels_reached_ids"):
        out[f] = [c for e in kept for c in (e.get(f) or [])]
    out["batch"] = max(int(e.get("batch") or 0) for e in kept)       # 0 only when NO batch returned (closing event alone)
    out["geos_ok"] = sorted({g for e in kept for g in (e.get("geos_ok") or [])})
    out["at"] = max(str(e.get("at", "")) for e in kept)
    b = board_batches(recs, run_id)
    partial = any(e.get("coverage") == "partial" for e in kept)
    if b is not None:
        out["channels_worklist"] = len(b["worklist"]) or out["channels_worklist"]
        term = b["terminal"]
        partial = partial or bool(b["unhanded"]) or bool(b["open_batches"]) or (
            term is not None and term.get("state") != "done")
    out["coverage"] = "partial" if partial else "complete"
    return out


def record_roles(root, run_id, surface, window, f_tpr, queries, geos_ok, query_gaps_window,
                 query_gaps_truncated, distinct, captured, known, carried, role_gaps, at=None,
                 quarantined=0, quarantine_reasons=None, query_gaps_filters=0,
                 captured_degraded=0, q_reached=0, q_clean=0, q_unread=0, q_total_unknown=0,
                 q_degraded=None, q_degraded_queries=0, *, coverage=None, line_faults=None,
                 channels_worklist=None, channels_reached=None, channels_unreachable=None,
                 channels_not_attempted=None, channels_unaccounted=None, batch=None,
                 channels_reached_ids=None):
    """dev #692 / public #140 -- the ONE writer of a `roles` event: one per ACCEPTED `ROLES v1`
    block (`deferred.add_roles`). Validated at write, loud: an unknown surface or window, a
    bucket outside `F_TPR_BUCKETS`, a negative count, or an identity that does not hold
    (`distinct = captured + known + carried + quarantined + role_gaps`, dev #722 / public #156) is
    refused, so a row that claims a number it cannot account for never reaches the store. `f_tpr`
    is None for the board.
    The two query-gap counts are SEPARATE fields on purpose: a per-query gap (a window not
    applied, a query unreachable, a result truncated) moves what a wide re-scan may claim, a
    per-role gap (a URL that could not be exposed) moves conservation, and one must never hide
    the other.

    ⭐ dev #722 / public #156 -- the QUARANTINE and READ counts. `quarantined` (roles held because
    every query that showed them reported a degradation) is a term of the identity;
    `quarantine_reasons` is `{code: roles}` over `deferred.DEGRADED_CODES` (a role with two codes
    counts once under each). The query-read counts (R4) say how each REACHED query read, and are a
    partition: `q_reached = q_clean + q_unread + q_degraded_queries`, refused when it does not hold;
    `q_total_unknown` is counted apart (it can sit under any of the three) and `q_degraded` is
    `{code: queries}`. They are the sweep's SELF-REPORT (SHAPE, not enforced): they make a sweep
    that never looks countable (`check_runs.py`), they cannot prove it looked. An event written
    before 0.69.0 lacks every one of these fields and readers use `.get(k, 0)`.

    ⭐ dev #811 / public #170 + dev #812 / public #169 (design §6, 0.82.0) -- PARTIAL versus COMPLETE.
    The keyword-only `coverage` (`complete` | `partial`) and its accounting are written together or
    not at all (an event from before 0.82.0 has none, and readers treat the absence as "not
    recorded"): `line_faults` (an int, REQUIRED with `coverage`); `channels_worklist` (the board
    worklist's size, or None when none is on record); `channels_reached` (an int, or None);
    `channels_unreachable` and `channels_not_attempted` (each `{channel_id: REASONS code}`);
    `channels_unaccounted` (a list of ids). The channel fields are null or empty off the board.
    THE IDENTITY, refused when it breaks (the `feeds` event's own discipline): `coverage` is
    `partial` EXACTLY when `line_faults > 0`, or any QUERY was unreachable (`queries - q_reached > 0`:
    every QUERY line is reached or unreachable, so the difference is the unreachable count), or any
    channel map or list is non-empty. A truncated or filter-degraded query DID produce a recorded
    subset, keeps its own fields, and does not by itself make a pass partial.

    dev #830 / public #180 (0.84.0) -- the keyword-only `batch` (an int >= 0; board only) says which batch of the board
    loop the event was written from (`0` is the script's closing event), and `channels_reached_ids` (a list of distinct
    channel ids; board only) names the channels whose QUERY lines were reached, so the next batch order can put the
    longest-unattempted first. Both are additive: an event without them is today's (`batch` key None)."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_roles requires run_id")
    if surface not in ROLES_SURFACES:
        raise JournalError("record_roles surface %r is not in %r" % (surface, ROLES_SURFACES))
    if window not in ROLES_WINDOWS:
        raise JournalError("record_roles window %r is not in %r" % (window, ROLES_WINDOWS))
    if f_tpr is not None and f_tpr not in F_TPR_BUCKETS:
        raise JournalError("record_roles f_tpr %r is not one of LinkedIn's UI buckets %r "
                           "(R5: no computed window)" % (f_tpr, F_TPR_BUCKETS))
    counts = {"queries": queries, "query_gaps_window": query_gaps_window,
              "query_gaps_truncated": query_gaps_truncated, "distinct": distinct,
              "captured": captured, "known": known, "carried": carried,
              "role_gaps": role_gaps, "quarantined": quarantined,
              "query_gaps_filters": query_gaps_filters, "captured_degraded": captured_degraded,
              "q_reached": q_reached, "q_clean": q_clean, "q_unread": q_unread,
              "q_total_unknown": q_total_unknown, "q_degraded_queries": q_degraded_queries}
    for k, v in counts.items():
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise JournalError("record_roles %s=%r is not a non-negative integer" % (k, v))
    accounted = captured + known + carried + quarantined + role_gaps
    if distinct != accounted:
        raise JournalError(
            "record_roles: distinct=%d but captured+known+carried+quarantined+role_gaps=%d -- a "
            "pass's roles are all accounted for or the event is not written"
            % (distinct, accounted))
    quarantine_reasons = dict(quarantine_reasons or {})
    q_degraded = dict(q_degraded or {})
    for name, table in (("quarantine_reasons", quarantine_reasons), ("q_degraded", q_degraded)):
        for code, n in table.items():
            if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                raise JournalError("record_roles %s[%r]=%r is not a non-negative integer"
                                   % (name, code, n))
    if q_reached != q_clean + q_unread + q_degraded_queries:
        raise JournalError(
            "record_roles: q_reached=%d but q_clean+q_unread+q_degraded_queries=%d -- every "
            "reached query reads as exactly one of clean, unread or degraded"
            % (q_reached, q_clean + q_unread + q_degraded_queries))
    rec = {"event": "roles", "run_id": run_id, "surface": surface, "window": window,
           "f_tpr": f_tpr, "queries": queries, "geos_ok": sorted(set(geos_ok or [])),
           "query_gaps_window": query_gaps_window, "query_gaps_truncated": query_gaps_truncated,
           "distinct": distinct, "captured": captured, "known": known, "carried": carried,
           "role_gaps": role_gaps, "quarantined": quarantined,
           "quarantine_reasons": quarantine_reasons, "query_gaps_filters": query_gaps_filters,
           "captured_degraded": captured_degraded, "q_reached": q_reached, "q_clean": q_clean,
           "q_unread": q_unread, "q_total_unknown": q_total_unknown, "q_degraded": q_degraded,
           "q_degraded_queries": q_degraded_queries, "at": at}
    rec.update(_roles_coverage(surface, queries, q_reached, coverage, line_faults, channels_worklist,
                               channels_reached, channels_unreachable, channels_not_attempted,
                               channels_unaccounted))
    if batch is not None:
        if surface != "board" or not _is_count(batch):
            raise JournalError("record_roles batch=%r is a non-negative integer for surface 'board' only (got "
                               "surface=%r)" % (batch, surface))
        rec["batch"] = batch
    if channels_reached_ids is not None:
        if surface != "board":
            raise JournalError("record_roles: channels_reached_ids is for surface 'board' only")
        _check_ids("channels_reached_ids", channels_reached_ids, nonempty=False)
        rec["channels_reached_ids"] = sorted(channels_reached_ids)
    return append(root, rec)


def _check_channel_map(label, table):
    if not isinstance(table, dict):
        raise JournalError("record_roles %s=%r is not a {channel_id: REASONS code} map"
                           % (label, table))
    for cid, code in table.items():
        if not isinstance(cid, str) or not cid or re.search(r"\s", cid):
            raise JournalError("record_roles %s has the channel id %r (a non-empty string without "
                               "whitespace)" % (label, cid))
        if code not in REASONS:
            raise JournalError("record_roles %s[%r]=%r is not a REASONS code" % (label, cid, code))


def _roles_coverage(surface, queries, q_reached, coverage, line_faults, worklist, reached,
                    unreachable, not_attempted, unaccounted):
    """The `coverage` half of `record_roles`: validate it, and return the fields to store ({} when
    `coverage` is not given -- and then none of the others may be). See `record_roles`."""
    given = dict(line_faults=line_faults, channels_worklist=worklist, channels_reached=reached,
                 channels_unreachable=unreachable, channels_not_attempted=not_attempted,
                 channels_unaccounted=unaccounted)
    if coverage is None:
        extra = sorted(k for k, v in given.items() if v is not None)
        if extra:
            raise JournalError("record_roles: %s need coverage= (they are written together)"
                               % ", ".join(extra))
        return {}
    if coverage not in ROLES_COVERAGE:
        raise JournalError("record_roles coverage=%r is not one of %r" % (coverage, ROLES_COVERAGE))
    if not _is_count(line_faults):
        raise JournalError("record_roles line_faults=%r is not a non-negative integer "
                           "(required with coverage)" % (line_faults,))
    for label, v in (("channels_worklist", worklist), ("channels_reached", reached)):
        if v is not None and not _is_count(v):
            raise JournalError("record_roles %s=%r is neither None nor a non-negative integer"
                               % (label, v))
    unreachable = {} if unreachable is None else unreachable
    not_attempted = {} if not_attempted is None else not_attempted
    unaccounted = [] if unaccounted is None else unaccounted
    _check_channel_map("channels_unreachable", unreachable)
    _check_channel_map("channels_not_attempted", not_attempted)
    if (not isinstance(unaccounted, (list, tuple)) or any(not isinstance(c, str) or not c or re.search(r"\s", c) for c in unaccounted)
            or len(set(unaccounted)) != len(unaccounted)):
        raise JournalError("record_roles channels_unaccounted=%r is not a list of distinct channel "
                           "ids" % (unaccounted,))
    if surface != "board" and (worklist is not None or reached or unreachable or not_attempted
                               or unaccounted):
        raise JournalError("record_roles: the channel fields are for surface 'board' only (got "
                           "surface=%r)" % surface)
    query_unreachable = queries - q_reached
    if query_unreachable < 0:
        raise JournalError("record_roles: q_reached=%d exceeds queries=%d" % (q_reached, queries))
    partial = bool(line_faults > 0 or query_unreachable > 0 or unreachable or not_attempted
                   or unaccounted)
    if (coverage == "partial") != partial:
        raise JournalError(
            "record_roles: coverage=%r but line_faults=%d, unreachable queries=%d (queries - "
            "q_reached), channels_unreachable=%d, channels_not_attempted=%d, "
            "channels_unaccounted=%d -- a pass is partial exactly when any of them is non-zero"
            % (coverage, line_faults, query_unreachable, len(unreachable), len(not_attempted),
               len(unaccounted)))
    return {"coverage": coverage, "line_faults": line_faults, "channels_worklist": worklist,
            "channels_reached": reached, "channels_unreachable": dict(unreachable),
            "channels_not_attempted": dict(not_attempted), "channels_unaccounted": list(unaccounted)}


def record_feeds(root, run_id, polled, covered, unchanged, not_covered, failures,
                 companies_not_covered, postings, unlisted, selected, captured, known, carried,
                 role_gaps, sightings_added=0, discovered=0, ambiguous=0, quarantined=0,
                 hosts_down=None, at=None, off=False, *, covered_ids=None, attempted_ids=None):
    """dev #751 -- the ONE writer of a `feeds` event: one per `feed_poll.py --run`. Validated at
    write, loud: a row that claims a number it cannot account for never reaches the store.

      polled     = covered + not_covered         (every company the poll was asked about; a company the
                                                  deadline did not reach, or on a host marked down, is
                                                  NOT COVERED, never silently absent)
      unchanged <= covered                       (a 304 counts as covered: nothing changed)
      not_covered = sum(failures.values()) = len(companies_not_covered)
      selected   = captured + known + carried + role_gaps (+ quarantined, asserted 0: a feed is a
                                                  complete listing, so no role is held degraded)

    `failures` is `{code: companies}` over `FEED_FAILURES`; `companies_not_covered` is
    `{company_id: code}` (a dict, not the bare list the design first sketched: `channels_due.py` has
    to tell a BOARD failure from a HOST failure per company, B1); `hosts_down` is `{host: code}`, the
    hosts the poller stopped sending requests to for this run. ⚠️ ROLLBACK RISK, as for `roles`: an
    engine older than 0.72.0 refuses a journal holding a `feeds` row.

    `off=True` (dev #774): the run was asked to poll and `sourcing.feeds.enabled` is false, so NOTHING was polled. The
    row carries `off: true` and every count is 0 -- a switched-off feed is a row that says so, never an absent one,
    so `channels_due.py` cannot read the silence as coverage.

    dev #820 / public #175 (0.82.0, B0.2) -- the keyword-only `covered_ids` is the list of company ids
    this poll COVERED (distinct; as many as `covered`; none of them also in `companies_not_covered`).
    The event stored a count of covered companies and a map of the not-covered ones, so "when was this
    company last covered" had no answer; `feed_last_covered` reads this list to order the next poll's
    rotation and to age a "did not look" row. Omitted from an older event and from `off`.

    dev #832 (public #178, 0.84.0) -- the keyword-only `attempted_ids` is the list of company ids this poll ATTEMPTED:
    at least one request for the company was sent (a covered company is always attempted; a company skipped because
    its host was already down, or reached by the budget before its first request, sent nothing). `feed_last_attempted`
    reads it to order the next poll, so a feed that is reached but can never cover stops heading the order every run.
    Refused when: it is not a list of distinct ids; a covered company is not in it; it names a company the event does
    not account for (neither covered nor not covered); or `off` is set (a switched-off poll attempted nothing)."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_feeds requires run_id")
    counts = dict(polled=polled, covered=covered, unchanged=unchanged, not_covered=not_covered,
                  postings=postings, unlisted=unlisted, selected=selected, captured=captured,
                  known=known, carried=carried, role_gaps=role_gaps, quarantined=quarantined,
                  sightings_added=sightings_added, discovered=discovered, ambiguous=ambiguous)
    for k, v in counts.items():
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise JournalError("record_feeds %s=%r is not a non-negative integer" % (k, v))
    if polled != covered + not_covered:
        raise JournalError("record_feeds: polled=%d but covered+not_covered=%d -- every company "
                           "polled is covered or not covered, never neither"
                           % (polled, covered + not_covered))
    if unchanged > covered:
        raise JournalError("record_feeds: unchanged=%d exceeds covered=%d -- a 304 is a covered "
                           "feed, so it cannot outnumber them" % (unchanged, covered))
    failures = dict(failures or {})
    companies_not_covered = dict(companies_not_covered or {})
    for code, n in failures.items():
        if code not in FEED_FAILURES:
            raise JournalError("record_feeds failure code %r is not in FEED_FAILURES %r"
                               % (code, sorted(FEED_FAILURES)))
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise JournalError("record_feeds failures[%r]=%r is not a non-negative integer"
                               % (code, n))
    for cid, code in companies_not_covered.items():
        if code not in FEED_FAILURES:
            raise JournalError("record_feeds: company %r has failure code %r, not in FEED_FAILURES"
                               % (cid, code))
    if sum(failures.values()) != not_covered or len(companies_not_covered) != not_covered:
        raise JournalError(
            "record_feeds: not_covered=%d but sum(failures)=%d and companies_not_covered=%d -- every "
            "not-covered feed has a code and a name" % (not_covered, sum(failures.values()),
                                                         len(companies_not_covered)))
    by_code = {}
    for code in companies_not_covered.values():
        by_code[code] = by_code.get(code, 0) + 1
    if by_code != {c: n for c, n in failures.items() if n}:
        raise JournalError("record_feeds: failures %r disagrees with the per-company codes %r"
                           % (failures, by_code))
    if quarantined != 0:
        raise JournalError("record_feeds: quarantined=%d but a feed is a complete listing and "
                           "holds no role as degraded (must be 0)" % quarantined)
    if selected != captured + known + carried + role_gaps + quarantined:
        raise JournalError(
            "record_feeds: selected=%d but captured+known+carried+role_gaps=%d -- every selected "
            "posting resolves to exactly one outcome"
            % (selected, captured + known + carried + role_gaps + quarantined))
    hosts_down = dict(hosts_down or {})
    for host, code in hosts_down.items():
        if code not in FEED_HOST_CODES:
            raise JournalError("record_feeds: host %r down with %r, which is not a HOST code %r"
                               % (host, code, FEED_HOST_CODES))
    if covered_ids is not None:
        _check_ids("covered_ids", covered_ids, nonempty=False)
        if len(covered_ids) != covered:
            raise JournalError("record_feeds: covered=%d but covered_ids names %d company(ies)"
                               % (covered, len(covered_ids)))
        both = sorted(set(covered_ids) & set(companies_not_covered))
        if both:
            raise JournalError("record_feeds: %s is both covered and not covered" % ", ".join(both))
    if attempted_ids is not None:
        _check_ids("attempted_ids", attempted_ids, nonempty=False)
        if covered_ids is not None:
            unattempted = sorted(set(covered_ids) - set(attempted_ids))
            if unattempted:
                raise JournalError("record_feeds: %s is covered but not in attempted_ids -- a feed cannot be covered "
                                   "without a request for it having been sent" % ", ".join(unattempted))
            stray = sorted(set(attempted_ids) - (set(covered_ids) | set(companies_not_covered)))
            if stray:
                raise JournalError("record_feeds: attempted_ids names %s, which the event neither covers nor lists "
                                   "as not covered" % ", ".join(stray))
    rec = {"event": "feeds", "run_id": run_id, "polled": polled, "covered": covered,
           "unchanged": unchanged, "not_covered": not_covered,
           "failures": {c: n for c, n in sorted(failures.items()) if n},
           "companies_not_covered": dict(sorted(companies_not_covered.items())),
           "hosts_down": dict(sorted(hosts_down.items())), "postings": postings,
           "unlisted": unlisted, "selected": selected, "captured": captured, "known": known,
           "carried": carried, "role_gaps": role_gaps, "quarantined": quarantined,
           "sightings_added": sightings_added, "discovered": discovered, "ambiguous": ambiguous,
           "at": at}
    if off:
        if any(counts.values()) or failures or companies_not_covered or hosts_down or attempted_ids:
            raise JournalError("record_feeds: off=True but the row claims work was done -- a switched-off feed polls nothing")
        rec["off"] = True
    if covered_ids is not None:
        rec["covered_ids"] = sorted(covered_ids)
    if attempted_ids is not None:
        rec["attempted_ids"] = sorted(attempted_ids)
    return append(root, rec)


def feeds_events(recs, run_id=None, on=None):
    """Every `feeds` event, oldest first; `run_id` narrows to one run, `on` (an ISO date) to the
    events written that day -- how `channels_due.py` reads "this run" without a run id."""
    rows = [r for r in recs if r.get("event") == "feeds"]
    if run_id is not None:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if on is not None:
        rows = [r for r in rows if str(r.get("at") or "")[:10] == str(on)[:10]]
    return sorted(rows, key=lambda r: r.get("at") or "")


def feed_last_covered(recs):
    """`{company_id: 'YYYY-MM-DD'}`: the date of the latest `feeds` event whose `covered_ids` names the
    company. A switched-off event (`off`) covered nothing, and an event written before `covered_ids`
    existed says nothing about who was covered, so neither contributes. `feed_poll.poll` orders its
    companies by this (never-covered first) and `coverage` ages a "did not look" feed row from it."""
    out = {}
    for ev in feeds_events(recs):
        if ev.get("off"):
            continue
        day = str(ev.get("at") or "")[:10]
        for cid in ev.get("covered_ids") or []:
            out[cid] = day
    return out


def feed_last_attempted(recs):
    """`{company_id: ordinal}` (dev #832 / public #178, jobsearch 0.84.0): the 0-BASED position, among the `feeds`
    events in FILE order, of the latest event that ATTEMPTED the company -- the key `feed_poll.rotation_order` sorts on,
    so a company never attempted comes first and then the one attempted longest ago. An ordinal, not a date: two polls
    on one day (a manual rerun) tie on a date and would repeat the same head, while the position in the append-only
    journal is a total order that needs no clock.

    An event that carries `attempted_ids` contributes them. An event written before 0.84.0 has none, so it contributes
    its `covered_ids` (a covered company was necessarily attempted). A switched-off event (`off`) contributes nothing.
    `feed_last_covered` is unchanged: `coverage` still ages a "did not look" row from it."""
    out = {}
    for i, ev in enumerate(r for r in recs if r.get("event") == "feeds"):
        if ev.get("off"):
            continue
        ids = ev["attempted_ids"] if isinstance(ev.get("attempted_ids"), list) else ev.get("covered_ids") or []
        for cid in ids:
            out[cid] = i
    return out


def feed_repeat_failures(recs, code, n):
    """The sorted company ids that were NOT covered with failure `code` in EACH of the latest `n`
    polls (a switched-off event is not a poll). Fewer than `n` polls give `[]`: two failures need
    two polls to have happened. `channels_due` lists these companies DUE for the browser after a
    repeated `budget-exhausted` (n=2), which the host-code rule would otherwise leave on a normal
    cadence forever."""
    if code not in FEED_FAILURES:
        raise JournalError("feed_repeat_failures code %r is not in FEED_FAILURES" % (code,))
    if not _is_int(n, 1):
        raise JournalError("feed_repeat_failures n=%r is not a positive integer" % (n,))
    polls = [e for e in feeds_events(recs) if not e.get("off")]
    if len(polls) < n:
        return []
    sets = [{cid for cid, c in (e.get("companies_not_covered") or {}).items() if c == code}
            for e in polls[-n:]]
    return sorted(set.intersection(*sets))


def feed_board_failure_since(recs, company_id, today=None):
    """The ISO date a company's CURRENT run of consecutive BOARD failures began, or None when its
    latest feed outcome is not a board failure (B1): the streak runs back through `feeds` events
    that name the company with a `FEED_BOARD_CODES` code and stops at the first event that covered
    it, held it to a host/budget code, or did not name it as failed. `channels_due.py` lists a
    channel DUE only while its `last_reviewed` is older than this date, so one browser review ends
    the daily pull instead of every day of a streak repeating it."""
    since = None
    for ev in reversed(feeds_events(recs)):
        code = (ev.get("companies_not_covered") or {}).get(company_id)
        if code in FEED_BOARD_CODES:
            since = str(ev.get("at") or "")[:10]
        else:
            break
    return since


def feed_company_state(recs, company):
    """dev #765 (design B5) -- what the LAST `feeds` event says about ONE company's own feed, as a dict
    `{state, vendor, code, kind, poll, reason}`. It is the one reader `portfolio_boards.py` uses, and it
    exists because the event does not store who was covered: it stores a COUNT of covered companies and a
    map of the NOT-covered ones (`record_feeds`). "Covered" is therefore never read off absence alone. A
    company is covered only when the event could have polled it AND did not list it as failed:

      state          meaning
      no-feed        the company has no `ats` key: browser-routed, no feed to cover
      declined       `ats: null`: the candidate declined a feed
      not-checked    an `ats` feed exists but the last poll proves nothing about it. `reason` says why:
                     no `feeds` event at all · the company is `passed` (never polled) · its `ats.since`
                     is not before the poll's date (attached the day of, or after, the poll: it may not
                     have been in it) · `ats.since` unreadable
      not-covered    the last poll listed it with `code`; `kind` is `board` (this board is wrong:
                     `FEED_BOARD_CODES`) or `host` (the machine or the poll's own budget, not this board)
      covered        polled, and not listed as failed

    The poll used is the LATEST `feeds` event overall, and `poll` is its ISO date, so a stale poll is
    shown with its age rather than hidden. Pure: reads only `recs` and `company`."""
    ats = company.get("ats") if isinstance(company, dict) else None
    out = {"state": None, "vendor": None, "code": None, "kind": None, "poll": None, "reason": None}
    if not isinstance(company, dict) or "ats" not in company:
        out["state"] = "no-feed"
        return out
    if ats is None:
        out["state"] = "declined"
        return out
    out["vendor"] = ats.get("vendor") if isinstance(ats, dict) else None
    events = feeds_events(recs or [])
    if not events:
        out.update(state="not-checked", reason="no feeds event recorded: the feed has not been polled")
        return out
    ev = events[-1]
    poll = str(ev.get("at") or "")[:10]
    out["poll"] = poll or None
    if ev.get("off"):
        # dev #774: a switched-off run lists no company as failed, and "not listed as failed" must NOT read as covered
        out.update(state="not-checked", reason="company feeds are turned off (sourcing.feeds.enabled): the last "
                                                "feeds event, %s, polled nothing" % (poll or "undated"))
        return out
    cid = company.get("id")
    failed = ev.get("companies_not_covered") or {}
    if cid in failed:
        code = failed[cid]
        out.update(state="not-covered", code=code,
                   kind="board" if code in FEED_BOARD_CODES else "host")
        return out
    if company.get("status") == "passed":
        out.update(state="not-checked", reason="the company is passed, so its feed is not polled")
        return out
    since = ats.get("since") if isinstance(ats, dict) else None
    try:
        attached, polled_on = datetime.date.fromisoformat(str(since)), datetime.date.fromisoformat(poll)
    except ValueError:
        out.update(state="not-checked", reason="ats.since %r or the poll date %r is unreadable"
                   % (since, poll))
        return out
    if attached >= polled_on:
        out.update(state="not-checked",
                   reason="the feed was attached %s, not before the last poll (%s), so that poll may "
                          "not have included it" % (attached.isoformat(), poll))
        return out
    out["state"] = "covered"
    return out


ENGINE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def engine_version():
    """The running engine's version, from its `.claude-plugin/plugin.json`. Raises `JournalError` when
    it cannot be read as `X.Y.Z`: a `start` written without one would read as an OLDER engine and print a
    bogus ENGINE SKEW, so `--start` refuses rather than write it (dev #820, G3)."""
    try:
        with open(os.path.join(engine_root(), ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            v = json.load(fh).get("version")
    except (OSError, ValueError):
        v = None
    if not isinstance(v, str) or not ENGINE_VERSION_RE.match(v):
        raise JournalError("cannot read this engine's version from .claude-plugin/plugin.json (got %r): a "
                           "run start without its engine cannot be told from a pre-0.82.0 run" % (v,))
    return v


def record_start(root, kind, at=None, engine=None, start_sha=None):
    """dev #820 / public #175 -- the ONE writer of a `start` event. It carries `engine`, the plugin
    version that began the run (read from `plugin.json` when not given), which `lifecycle` reads for the
    cutover (nothing is legacy before the first 0.82.0 start) and for ENGINE SKEW. A missing or
    malformed engine is refused. `start_sha` (dev #703) is omitted when None. Returns the run id."""
    at = at or now_iso()
    if not kind or not isinstance(kind, str):
        raise JournalError("record_start requires a kind")
    engine = engine_version() if engine is None else engine
    if not isinstance(engine, str) or not ENGINE_VERSION_RE.match(engine):
        raise JournalError("record_start engine=%r is not X.Y.Z" % (engine,))
    rid = new_run_id(kind, at)
    rec = {"event": "start", "run_id": rid, "kind": kind, "at": at, "engine": engine}
    if start_sha:
        rec["start_sha"] = start_sha
    append(root, rec)
    return rid


# dev #820 / public #175 (design-role-pipeline.md section 4.5, 17) -- the `drain` event: one `planned`
# when a run admits its intake, one `closed` when it checks every admitted role finished (and at most one
# MORE, written on its behalf by the next run when it died). CLOSED vocabularies, validated at write and
# again at read. `lifecycle.CAUSES` is these plus the three causes `stage()` derives and never stores.
DRAIN_PHASES = ("planned", "closed")
CAPACITY_REASONS = ("no-render-route", "time-bound")
DRAIN_RUN_CAUSES = ("run-died", "cause-not-recorded", "not-dispatched", "deadline-reached")
DRAIN_ROLE_CAUSES = ("agent-returned-nothing", "capture-refused", "challenge", "render-failed",
                     "surface-cannot-read", "site-not-allowed")
# 0.85.0 (dev #839 / public #182, dev #840 / public #181; design-hidden-pane-reads.md sections 7.1, 10): a third cause
# class. The page was never read (the Browser pane was hidden, or the reader's tab stayed in the background), so the
# cause is neither the run's fault nor the role's: it breaks both retry-stop chains and counts toward neither.
DRAIN_ENV_CAUSES = ("pane-hidden",)
DRAIN_CLOSE_CAUSES = DRAIN_RUN_CAUSES + DRAIN_ROLE_CAUSES + DRAIN_ENV_CAUSES
# The admission classes. `held` (0.85.0) is a role whose read could not happen for an ENVIRONMENT cause: it waits
# behind retry, returned and legacy, and new roles keep their reserved share ahead of it. The 0.84.0 reader's key set
# is the first four: a stored `admitted_by_class` carries EITHER those four OR those plus `held`, and 0.85.0 WRITES
# `held` ONLY WHEN IT IS NON-ZERO (a journal that never held a role stays readable by 0.84.0).
DRAIN_CLASSES = ("retry", "returned", "legacy", "held", "new")
DRAIN_CLASSES_084 = ("retry", "returned", "legacy", "new")
# ⚠️ ROLLBACK RISK, STATED (0.85.0): an engine older than 0.85.0 raises on any journal holding a `held` admission
# class, a `readmit` event or an environment-class close cause (`read()` refuses them), so after one run on this
# version an older version cannot read this profile's journal. It is the 0.82.0 cutover's accepted behaviour (the
# older machine "stops at the journal read"); `lifecycle.process_report`'s `ENGINE SKEW` line shows it on the newer
# machine. The break starts at the FIRST `held` admission, environment close or `readmit` event, not at upgrade.
# The 0.85.0 release note says: upgrade every machine that shares the profile.
RENDER_ROUTES = ("yes", "no")
DRAIN_PLANNED_FIELDS = ("intake", "capacity", "render_route", "attended", "admitted", "waiting",
                        "retry_stopped", "fanout", "solo", "fetch_calls", "reserved_new",
                        "admitted_by_class", "excluded_open")


def _is_int(v, lo=0, hi=None):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)


def _id_list(label, v, what="drain"):
    if (not isinstance(v, list) or any(not isinstance(i, str) or not i or re.search(r"\s", i) for i in v)
            or len(set(v)) != len(v)):
        raise JournalError("%s %s=%r is not a list of distinct ids (non-empty strings without "
                           "whitespace)" % (what, label, v))


def _check_drain_row(rec):
    """The shape of a `drain` event, for the writer and the reader alike. Raises `JournalError`."""
    phase = rec.get("phase")
    if phase not in DRAIN_PHASES:
        raise JournalError("drain phase %r is not one of %r" % (phase, DRAIN_PHASES))
    if not isinstance(rec.get("run_id"), str) or not rec["run_id"]:
        raise JournalError("drain requires run_id")
    if phase == "planned":
        if rec.get("on_behalf_of") is not None:
            raise JournalError("drain planned: a plan is the run's own act (on_behalf_of is for a close)")
        missing = [k for k in DRAIN_PLANNED_FIELDS if rec.get(k) is None]
        if missing:
            raise JournalError("drain planned is missing %s" % ", ".join(missing))
        if not _is_int(rec["intake"], 1, 300):
            raise JournalError("drain planned intake=%r is not 1..300" % (rec["intake"],))
        if not _is_int(rec["capacity"], 0) or rec["capacity"] > rec["intake"]:
            raise JournalError("drain planned capacity=%r is not 0..intake (%r)" % (rec["capacity"], rec["intake"]))
        reason = rec.get("capacity_reason")
        if rec["capacity"] < rec["intake"]:
            if reason not in CAPACITY_REASONS:
                raise JournalError("drain planned capacity %r is below intake %r, so capacity_reason must be "
                                   "one of %r (got %r): a cut is never silent"
                                   % (rec["capacity"], rec["intake"], CAPACITY_REASONS, reason))
        elif reason is not None:
            raise JournalError("drain planned capacity_reason %r with capacity == intake" % (reason,))
        if rec["render_route"] not in RENDER_ROUTES:
            raise JournalError("drain planned render_route %r is not one of %r" % (rec["render_route"], RENDER_ROUTES))
        if rec["render_route"] == "no" and rec["capacity"] != 0:
            raise JournalError("drain planned: no render route admits nothing (capacity must be 0)")
        if not isinstance(rec["attended"], bool):
            raise JournalError("drain planned attended=%r is not a boolean" % (rec["attended"],))
        adm = rec["admitted"]
        if not isinstance(adm, dict) or set(adm) != {"opps", "items"}:
            raise JournalError("drain planned admitted must be {opps: [...], items: [...]} -- got %r" % (adm,))
        _id_list("admitted.opps", adm["opps"])
        _id_list("admitted.items", adm["items"])
        w = rec["waiting"]
        if (not isinstance(w, dict) or set(w) != {"count", "oldest"} or not _is_int(w["count"])
                or not (w["oldest"] is None or re.match(r"^\d{4}-\d{2}-\d{2}$", str(w["oldest"])))):
            raise JournalError("drain planned waiting must be {count: n, oldest: date|null} -- got %r" % (w,))
        _id_list("retry_stopped", rec["retry_stopped"])
        _id_list("solo", rec["solo"])
        if not _is_int(rec["fanout"], 1) or not _is_int(rec["fetch_calls"]) or not _is_int(rec["reserved_new"]):
            raise JournalError("drain planned fanout/fetch_calls/reserved_new are not non-negative integers")
        byc = rec["admitted_by_class"]
        if (not isinstance(byc, dict) or set(byc) not in (set(DRAIN_CLASSES), set(DRAIN_CLASSES_084))
                or any(not _is_int(v) for v in byc.values())):
            raise JournalError("drain planned admitted_by_class must be {%s: n} (`held` is optional: a missing "
                               "one reads as 0) -- got %r" % (", ".join(DRAIN_CLASSES_084), byc))
        if sum(byc.values()) > rec["capacity"]:
            raise JournalError("drain planned admits %d roles with capacity %d" % (sum(byc.values()), rec["capacity"]))
        ex = rec["excluded_open"]
        if not isinstance(ex, dict) or any(not isinstance(k, str) or not k or not _is_int(v, 1) for k, v in ex.items()):
            raise JournalError("drain planned excluded_open must be {run id: count >= 1} -- got %r" % (ex,))
        for k in ("finished", "left", "elapsed_s", "per_role_s"):
            if rec.get(k) is not None:
                raise JournalError("drain planned carries %s, which belongs to a close" % k)
        return
    # --- closed ---
    for k in DRAIN_PLANNED_FIELDS + ("capacity_reason",):
        if k != "admitted" and rec.get(k) is not None:       # `admitted` is a count here, a map in a plan
            raise JournalError("drain closed carries %s, which belongs to a plan" % k)
    if not _is_int(rec.get("admitted")) or not _is_int(rec.get("finished")) or rec["finished"] > rec["admitted"]:
        raise JournalError("drain closed needs integers 0 <= finished <= admitted (got admitted=%r finished=%r)"
                           % (rec.get("admitted"), rec.get("finished")))
    left = rec.get("left")
    if not isinstance(left, dict):
        raise JournalError("drain closed left must be {id: cause} -- got %r" % (left,))
    for i, cause in left.items():
        if not isinstance(i, str) or not i or re.search(r"\s", i):
            raise JournalError("drain closed left has the id %r (a non-empty string without whitespace)" % (i,))
        if cause not in DRAIN_CLOSE_CAUSES:
            raise JournalError("drain closed left[%r]=%r is not a cause a close may record (%s); "
                               "retry-stopped, legacy-backlog and unclassified are derived, never stored"
                               % (i, cause, ", ".join(DRAIN_CLOSE_CAUSES)))
    if rec["finished"] + len(left) != rec["admitted"]:
        raise JournalError("drain closed: admitted=%d but finished=%d + left=%d -- every admitted role "
                           "finished or has a cause" % (rec["admitted"], rec["finished"], len(left)))
    obh = rec.get("on_behalf_of")
    if obh is not None:
        if not isinstance(obh, str) or not obh or obh == rec["run_id"]:
            raise JournalError("drain closed on_behalf_of=%r must name ANOTHER run" % (obh,))
        for k in ("elapsed_s", "per_role_s"):
            if rec.get(k) is not None:
                raise JournalError("drain closed on behalf of %s carries %s: a close written for a dead "
                                   "run measures nothing" % (obh, k))
    else:
        if rec.get("elapsed_s") is not None and not _is_int(rec["elapsed_s"]):
            raise JournalError("drain closed elapsed_s=%r is not a non-negative integer" % (rec["elapsed_s"],))
        prs = rec.get("per_role_s")
        if prs is not None and (isinstance(prs, bool) or not isinstance(prs, (int, float)) or prs < 0):
            raise JournalError("drain closed per_role_s=%r is not a non-negative number" % (prs,))


def record_drain(root, run_id, phase, *, intake=None, capacity=None, capacity_reason=None,
                 render_route=None, attended=None, admitted=None, waiting=None, retry_stopped=None,
                 fanout=None, solo=None, fetch_calls=None, reserved_new=None, admitted_by_class=None,
                 excluded_open=None, finished=None, left=None, elapsed_s=None, per_role_s=None,
                 on_behalf_of=None, at=None):
    """dev #820 / public #175 (design section 4.5, 17 N1, N7) -- the ONE writer of a `drain` event.

      planned   `lifecycle.Plan.event_fields()`: intake, capacity (+ capacity_reason whenever it is below
                intake), render_route, attended, admitted {opps, items}, waiting {count, oldest},
                retry_stopped, fanout, solo, fetch_calls, reserved_new, admitted_by_class,
                excluded_open. One per run: a second is refused.
      closed    `admitted` (an INTEGER here: how many were admitted), `finished`, `left` {id: cause}
                with `finished + len(left) == admitted`, and for the run's own close `elapsed_s` and
                `per_role_s` (the measured rate N7's time cap reads). `on_behalf_of=<closing run>`
                marks a close written for a run that went silent; it measures nothing.

    EXACTLY ONE EFFECTIVE CLOSE PER RUN: a second own close for the run is refused, and a second
    on-behalf close is refused. The run's own close is still accepted after an on-behalf one (the
    run went silent past the window and then came back); `lifecycle.closed_event` reads the own close
    first. A close needs the run to have a plan."""
    at = at or now_iso()
    if isinstance(admitted_by_class, dict) and admitted_by_class.get("held") == 0:
        admitted_by_class = {k: v for k, v in admitted_by_class.items() if k != "held"}     # 0.85.0: held only when > 0
    rec = {"event": "drain", "phase": phase, "run_id": run_id, "at": at}
    planned = dict(intake=intake, capacity=capacity, render_route=render_route, attended=attended,
                   admitted=admitted, waiting=waiting, retry_stopped=retry_stopped, fanout=fanout,
                   solo=solo, fetch_calls=fetch_calls, reserved_new=reserved_new,
                   admitted_by_class=admitted_by_class, excluded_open=excluded_open)
    closed = dict(finished=finished, left=left, elapsed_s=elapsed_s, per_role_s=per_role_s)
    if phase == "planned":
        rec.update({k: v for k, v in planned.items()})
        if capacity_reason is not None:
            rec["capacity_reason"] = capacity_reason
        rec.update({k: v for k, v in closed.items() if v is not None})
        if on_behalf_of is not None:
            rec["on_behalf_of"] = on_behalf_of
    else:
        rec["admitted"] = admitted
        rec.update({k: v for k, v in closed.items() if v is not None})
        rec.update({k: v for k, v in planned.items() if v is not None and k != "admitted"})
        if capacity_reason is not None:
            rec["capacity_reason"] = capacity_reason
        if on_behalf_of is not None:
            rec["on_behalf_of"] = on_behalf_of
    _check_drain_row(rec)
    existing = [r for r in read(root) if r.get("event") == "drain" and r.get("run_id") == run_id]
    if phase == "planned":
        if any(r.get("phase") == "planned" for r in existing):
            raise JournalError("run %r already has a drain plan: a run plans once" % run_id)
    else:
        if not any(r.get("phase") == "planned" for r in existing):
            raise JournalError("run %r has no drain plan, so there is nothing to close" % run_id)
        kind_of = lambda r: "behalf" if r.get("on_behalf_of") else "own"   # noqa: E731
        mine = "behalf" if on_behalf_of else "own"
        if any(r.get("phase") == "closed" and kind_of(r) == mine for r in existing):
            raise JournalError("run %r already has a %s close: exactly one close of each kind is "
                               "allowed, and the run's own close outranks one written on its behalf"
                               % (run_id, "on-behalf" if on_behalf_of else "own"))
    return append(root, rec)


# jobsearch 0.85.0 (dev #840 / public #181; design-hidden-pane-reads.md sections 9, 10) -- the `readmit` event: roles a
# migration put back into intake because their stop was counted under rules that did not know the cause. One
# event, appended once by `record_readmit` (the ONLY writer), naming the role ids. `lifecycle.Ctx.working()` drops
# every admission planned at or before it for those ids; it reads two events of the same `by` as ONE (the union of
# the ids, at the earliest `at`), so two machines that each ran the migration before syncing cannot re-admit twice.
READMIT_FIELDS = ("event", "at", "by", "cause", "ids")
_READMIT_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _check_readmit_row(rec):
    """The shape of a `readmit` event, for the writer and the reader alike. Raises `JournalError`."""
    unknown = sorted(set(rec) - set(READMIT_FIELDS))
    missing = [k for k in READMIT_FIELDS if k not in rec]
    if unknown:
        raise JournalError("readmit has unknown field(s) %s" % ", ".join(unknown))
    if missing:
        raise JournalError("readmit is missing field(s) %s" % ", ".join(missing))
    at = rec["at"]
    if not isinstance(at, str) or not _READMIT_AT_RE.match(at):
        raise JournalError("readmit at=%r is not an ISO date and time" % (at,))
    try:
        datetime.datetime.fromisoformat(at)
    except ValueError:
        raise JournalError("readmit at=%r is not a real date and time" % (at,))
    by = rec["by"]
    if not isinstance(by, str) or not by or re.search(r"\s", by):
        raise JournalError("readmit by=%r is not a non-empty name without whitespace" % (by,))
    if rec["cause"] not in DRAIN_ROLE_CAUSES:
        raise JournalError("readmit cause=%r is not a role-class cause (%s)"
                           % (rec["cause"], ", ".join(DRAIN_ROLE_CAUSES)))
    if not isinstance(rec["ids"], list) or not rec["ids"]:
        raise JournalError("readmit ids=%r must be a non-empty list: a re-admit of nothing is not an event"
                           % (rec["ids"],))
    _id_list("ids", rec["ids"], what="readmit")


def record_readmit(root, ids, by, cause, at=None):
    """dev #840 / public #181 -- the ONE writer of a `readmit` event: `{event, at, by, cause, ids}`. `cause` must
    be a role-class cause and `ids` non-empty and distinct; nothing is appended on a refusal. Returns the row."""
    rec = {"event": "readmit", "at": at or now_iso(), "by": by, "cause": cause,
           "ids": list(ids) if isinstance(ids, (list, tuple)) else ids}
    _check_readmit_row(rec)
    return append(root, rec)


MAIL_CLASSES = ("ats-status", "human", "digest", "noise")
MAIL_UNMATCHED_CAP = 200


def _check_mail_status_row(rec):
    if not isinstance(rec.get("run_id"), str) or not rec["run_id"]:
        raise JournalError("mail-status requires run_id")
    mb = rec.get("mailbox")
    if not isinstance(mb, str) or not mb.strip():
        raise JournalError("mail-status mailbox %r is not a non-empty string" % (mb,))
    counts = rec.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(MAIL_CLASSES) \
            or any(not _is_int(v) for v in counts.values()):
        raise JournalError("mail-status counts must be {%s: n >= 0} (every class, no other) -- got %r"
                           % (", ".join(MAIL_CLASSES), counts))
    un = rec.get("unmatched")
    if not isinstance(un, list):
        raise JournalError("mail-status unmatched must be a list -- got %r" % (un,))
    for u in un:
        if (not isinstance(u, dict) or set(u) != {"source", "subject"}
                or not isinstance(u["source"], str) or not u["source"].strip()
                or not isinstance(u["subject"], str)
                or len(u["source"]) > MAIL_UNMATCHED_CAP or len(u["subject"]) > MAIL_UNMATCHED_CAP):
            raise JournalError("mail-status unmatched entries are {source, subject}, each at most %d "
                               "characters, source non-empty -- got %r" % (MAIL_UNMATCHED_CAP, u))
    if len(un) > counts["ats-status"]:
        raise JournalError("mail-status: %d unmatched but only %d ats-status messages -- an unmatched "
                           "message is an ats-status one that matched no application"
                           % (len(un), counts["ats-status"]))


# the event -> its row check, read by `read()` (a row of one of these events is validated when it is read)
_ROW_CHECKS = {"drain": _check_drain_row, "mail-status": _check_mail_status_row, "readmit": _check_readmit_row}


def record_mail_status(root, run_id, mailbox, counts, unmatched, at=None):
    """dev #820 / public #175 (design section 8.2, M818) -- the ONE writer of a `mail-status` event: what
    one mailbox's status-mail search found in a run. `counts` is `{ats-status, human, digest, noise: n}`
    (`reconcile.classify_status_mail`'s four classes, every one given); `unmatched` is a list of
    `{source, subject}` for each `ats-status` message that matched no application. `coverage` reads the
    latest event per mailbox. Validated at write; an unknown class or an `unmatched` longer than the
    `ats-status` count is refused."""
    at = at or now_iso()
    rec = {"event": "mail-status", "run_id": run_id, "mailbox": mailbox, "counts": dict(counts or {}),
           "unmatched": [dict(u) if isinstance(u, dict) else u for u in (unmatched or [])], "at": at}
    _check_mail_status_row(rec)
    return append(root, rec)


def roles_events(recs, run_id=None, surface=None):
    rows = [r for r in recs if r.get("event") == "roles"]
    if run_id is not None:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if surface is not None:
        rows = [r for r in rows if r.get("surface") == surface]
    return rows


def roles_missing(recs, run_id):
    """dev #692 / public #140 (N5, R3, R4) -> the surfaces whose pass RETURNED in this run with
    no accepted `roles` event, in `ROLES_SURFACES` order.

    * `linkedin-jobsearch`: a LinkedIn `pass … returned` row whose explicit `jobsearch` token reads
      `reached` (R4). `unreachable` and `not-attempted` do not trip it: no search ran. A returned
      row that carries NO token is not guessed at (an old row, or a caller that did not report):
      it trips nothing, and daily-run is told to always pass one.
    * `board`: a `pass` row of kind `board`, phase `dispatched` or `returned`, written by the
      dispatching script (R3) -- never a folded `dispatch` row (`--fold-dispatches` reads a
      transcript, which is model-dependent; a fact a run knows goes into a script-written row).
      A `refused` board pass trips nothing."""
    have = {r.get("surface") for r in roles_events(recs, run_id=run_id)}
    passes = [r for r in recs if r.get("event") == "pass" and r.get("run_id") == run_id]
    missing = []
    if (any(r.get("kind") == "linkedin" and r.get("phase") == "returned"
            and r.get("jobsearch") == "reached" for r in passes)
            and "linkedin-jobsearch" not in have):
        missing.append("linkedin-jobsearch")
    if any(r.get("kind") == "board" and r.get("phase") in ("dispatched", "returned") for r in passes):
        # dev #830 / public #180: a run that handed its worklist out in batches owes ONE block per batch, so each
        # open batch is `board:b<n>` (its gap is `jobsearch:roles:board:b<n>`); a run with no batch row owes the one
        # `board` block, as before. The closing `batch: 0` event accounts for no batch, so it never hides an open one.
        b = board_batches(recs, run_id)
        if b is not None and b["batches"]:
            missing.extend("board:b%d" % n for n in b["open_batches"])
        elif "board" not in have:
            missing.append("board")
    return missing


def close_board_loop(root, run_id, at=None):
    """dev #830 / public #180 (design §2.4.4, round-2 M1) -- close a board batch loop the run left open. Returns the
    text it printed, or None when there was nothing to close. Written by `journal --end` (a script, once, at the end of
    the run); `run_summary` and `check_runs` read an open loop themselves, so nothing relies on this having run.

    A run with at least one `batch` row and no `batch-end` row is closed in one of two ways:
      * every id of the worklist WAS handed out (the model went from the last hand-back straight to the summary without
        the extra call that would have printed `done`): write `batch-end state=done` and NOTHING else. A closing `roles`
        event with no id to account for would be refused (`partial` with nothing partial), and no sweep was abandoned.
        A batch with no hand-back is still reported by `roles_missing` as `board:b<n>`.
      * ids were never handed out: write `batch-end state=abandoned code=run-ended` and ONE closing `roles` event
        (`batch=0`, `partial`, each unhanded id `not-attempted reason=run-ended`).
    Idempotent: a run that already has a `batch-end` row writes nothing."""
    recs = read(root)
    b = board_batches(recs, run_id)
    if b is None or not b["batches"] or b["terminal"] is not None:
        return None
    at = at or now_iso()
    if not b["unhanded"]:
        record_pass(root, run_id, "board", "batch-end", at=at, state="done", handed=len(b["handed"]),
                    worklist=len(b["worklist"]))
        return "BOARD BATCHES %d of %d (every channel handed out)" % (len(b["batches"]), b["of"])
    record_pass(root, run_id, "board", "batch-end", at=at, state="abandoned", code="run-ended",
                handed=len(b["handed"]), worklist=len(b["worklist"]))
    record_closing_roles(root, run_id, b["unhanded"], "run-ended", len(b["worklist"]), at=at)
    return ("BOARD BATCHES LEFT OPEN %d of %d: %d ids never handed"
            % (len(b["batches"]), b["of"], len(b["unhanded"])))


def record_closing_roles(root, run_id, remaining, code, worklist_size, at=None):
    """The script's closing board `roles` event (`batch=0`): every id in `remaining` recorded `not-attempted` under
    `code` (`run-budget`, `run-ended`, `browser-unavailable`, `route-refused`). `queries=0`, `coverage="partial"`,
    `channels_worklist` the whole worklist's size. Written through `record_roles`, the writer `deferred.add_roles`
    uses, so it holds every identity that one does. `remaining` must be non-empty (an empty one would be a `partial`
    event with nothing partial, and `record_roles` refuses it)."""
    return record_roles(root, run_id, "board", "none", None, 0, [], 0, 0, 0, 0, 0, 0, 0, at=at, coverage="partial",
                        line_faults=0, channels_worklist=worklist_size, channels_reached=0,
                        channels_unreachable={}, channels_not_attempted={c: code for c in remaining},
                        channels_unaccounted=[], batch=0)


def jobsearch_geos(cfg):
    """The geographies a wide re-scan must cover, computed from config -- never self-reported by
    the runner: `remote` always, plus `local` when `geography.commute_anchors` is non-empty."""
    anchors = ((cfg or {}).get("geography") or {}).get("commute_anchors") or []
    return ["remote", "local"] if anchors else ["remote"]


def wide_satisfied_at(recs, geos):
    """The `at` of the newest `roles` event that satisfies the weekly wide re-scan, or None.

    Only a `surface == "linkedin-jobsearch"`, `window == "wide"` event can (N3): a board event, a
    daily event, and a refused LinkedIn pass (which writes no `roles` event at all) never do. And
    only when EVERY requested geography has a reached, non-gapped QUERY (`set(geos) <= geos_ok`,
    N4 as narrowed by R5): a wide pass that covered `remote` and not `local` leaves wide due."""
    want = set(geos or [])
    sat = [r.get("at") for r in roles_events(recs, surface="linkedin-jobsearch")
           if r.get("window") == "wide" and want <= set(r.get("geos_ok") or [])
           and r.get("at")]
    return max(sat) if sat else None


def jobsearch_window(now, recs, geos):
    """dev #692 / public #140 (489-1, R5) -> `{"window", "f_tpr", "titles", "due_since"}` for the
    LinkedIn job search `now` (an ISO string).

    WIDE when no satisfied wide pass falls in the last `WIDE_EVERY_DAYS` days: LinkedIn's "Past
    week" bucket (`r604800`), the full title set. Otherwise DAILY: "Past 24 hours" (`r86400`), the
    configured titles. Only these two UI buckets exist (R5): no computed window, so a day the app
    was closed is covered by the next weekly pass, never by an invented lookback. `due_since` is
    the date wide became due (the day after the last satisfied pass's seventh day), or `never`;
    None while the daily window applies."""
    sat = wide_satisfied_at(recs, geos)
    now_dt = _parse_iso(now) or datetime.datetime.now()
    sat_dt = _parse_iso(sat) if sat else None
    if sat_dt is not None and (now_dt - sat_dt) < datetime.timedelta(days=WIDE_EVERY_DAYS):
        return {"window": "daily", "f_tpr": F_TPR_DAILY, "titles": "configured",
                "due_since": None}
    due_since = ((sat_dt + datetime.timedelta(days=WIDE_EVERY_DAYS)).date().isoformat()
                 if sat_dt is not None else "never")
    return {"window": "wide", "f_tpr": F_TPR_WIDE, "titles": "all", "due_since": due_since}


def pass_rows(recs, kind=None, today_only=False):
    rows = [r for r in recs if r.get("event") == "pass"]
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    if today_only:
        today = now_iso()[:10]
        rows = [r for r in rows if str(r.get("at", ""))[:10] == today]
    return rows


def linkedin_passes_reached(recs, today=None):
    """design-script-first.md §2 item 2 — how many of TODAY's LinkedIn passes count against the
    quota: a `returned` row dated today whose `reached` carries at least one surface (#75 — the
    count comes from surfaces the pass actually REACHED, never from a `dispatched` row, so a
    browserless launch that read nothing never consumes the quota). A `dispatched` row with no
    matching `returned` row is a crashed pass (see `crashed_passes` below) and is not counted
    here either.

    ⭐ dev #812 / public #169 (design §4) -- ONE FREE REFUSAL A DAY (owner ruling, 2026-11-05). A
    `returned` pass is not counted when its run's LATEST `recorded` row (by `at`, ties by file
    order) says `refused`, for at most `LINKEDIN_FREE_REFUSALS_PER_DAY` such passes a day, oldest
    `returned` first; any later one counts. The pairing is by run id and the latest row, never by
    position, so the order in which the dispatcher writes `returned` and `record` writes `recorded`
    does not matter. A `returned` row with NO `recorded` row counts (a record not yet run, or a
    journal from before 0.82.0: the conservative reading), and so does one whose latest verdict is
    anything but `refused` -- including `pass-failed` and `pane-held`: the account was driven. Raises
    `JournalError` on a `recorded` row whose verdict is unreadable (`record_verdict`)."""
    counted, _excused = _linkedin_quota_split(recs, today)
    return len(counted)


def linkedin_refusals_excused(recs, today=None):
    """dev #812 / public #169 -- how many of TODAY's `returned` passes the quota did NOT count
    because their record was refused (0 or `LINKEDIN_FREE_REFUSALS_PER_DAY`). `posture.py --may
    linkedin` prints it, so an admitted rerun is never silent about why."""
    _counted, excused = _linkedin_quota_split(recs, today)
    return len(excused)


def linkedin_excused_rows(recs, today=None):
    """The `returned` pass rows `linkedin_refusals_excused` counts: `run_summary` asks whether THIS
    run's refusal was the excused one, and must not re-derive the rule."""
    return _linkedin_quota_split(recs, today)[1]


def latest_recorded_row(recs, run_id):
    """The LinkedIn `recorded` pass row of `run_id` with the latest `at` (ties by file order), or
    None. The one definition of "the run's outcome" the quota and the run summary both read."""
    best = None
    for i, r in enumerate(recs):
        if (r.get("event") == "pass" and r.get("kind") == "linkedin"
                and r.get("phase") == "recorded" and r.get("run_id") == run_id):
            key = (str(r.get("at", "")), i)
            if best is None or key >= best[0]:
                best = (key, r)
    return best[1] if best else None


def _linkedin_quota_split(recs, today=None):
    today = today or now_iso()[:10]
    returned = sorted(
        ((str(r.get("at", "")), i, r) for i, r in enumerate(recs)
         if r.get("event") == "pass" and r.get("kind") == "linkedin"
         and r.get("phase") == "returned" and str(r.get("at", ""))[:10] == today
         and len(r.get("reached") or []) >= 1),
        key=lambda t: (t[0], t[1]))
    counted, excused = [], []
    for _at, _i, r in returned:
        row = latest_recorded_row(recs, r.get("run_id"))
        if (row is not None and record_verdict(row) == "refused"
                and len(excused) < LINKEDIN_FREE_REFUSALS_PER_DAY):
            excused.append(r)
        else:
            counted.append(r)
    return counted, excused


def crashed_passes(recs):
    """design-script-first.md §2 item 2 — every `dispatched` LinkedIn pass, in a run that has
    ENDED, with no matching `returned` row: dispatched, but nothing proves it ever read a page.
    Printed on its own line by `journal.py --passes` (never `--may`, which journal.py rejects) rather than
    silently folded into
    either "counted" or "not counted" — a crashed pass is neither."""
    ended = {r.get("run_id") for r in recs if r.get("event") == "end"}
    dispatched = {r.get("run_id") for r in recs
                 if r.get("event") == "pass" and r.get("kind") == "linkedin"
                 and r.get("phase") == "dispatched"}
    returned = {r.get("run_id") for r in recs
               if r.get("event") == "pass" and r.get("kind") == "linkedin"
               and r.get("phase") == "returned"}
    return sorted((dispatched & ended) - returned)


MEDIA = ("email", "linkedin")

# Query or Citation C1, D14 — a LinkedIn `empty` verifies "no reply" only when the look actually
# covered every surface a reply could sit on: the inbox (both tabs a client can show), pending
# message requests, sent invitations (whose acceptance carries no message but does carry a
# reply-shaped signal), and connection degree (a reply can arrive as an acceptance rather than a
# message). A look that skipped one of these is not evidence of silence — see main()'s --probe
# handling, which refuses --result empty unless --read names all four.
#
# design-linkedin-runner-resilience.md §6 (public #47/#96) — renamed from the bare
# `LINKEDIN_SURFACES` this was before: `notifications` (the bell) is real coverage vocabulary a
# gap scope or a run's report can name, but it is NOT one of the four a reply can sit on — the
# bell has never been the surface a reply was found on, and making it part of the silence proof
# would refuse `--result empty` on every pass where it was unreachable for no reason tied to
# replies at all. `LINKEDIN_SURFACES` below is now the five-token superset.
LINKEDIN_REPLY_SURFACES = frozenset({"inbox", "requests", "invitations", "degree"})

# The coverage vocabulary a gap scope (`linkedin:<token>`) or a runner report names — the four
# reply surfaces above, plus `notifications` (the bell; LinkedIn's algorithmic feed and
# saved-search alerts, a distinct surface neither the inbox nor a deliberate job search reads).
LINKEDIN_SURFACES = LINKEDIN_REPLY_SURFACES | frozenset({"notifications"})

# dev #488 / public #105 (design-linkedin-reach.md §3.2) -- acceptance is read POSITIVELY from the
# recency-sorted Connections list, never inferred from absence on Sent Invitations, so a sweep
# reports `connections` as a sixth coverage token, and a silence proof's acceptance slot is
# satisfied by `connections` OR the one-off `degree` visit.
#
# ⚠️ DEVIATION FROM DESIGN §3.2, and why: the design extends LINKEDIN_REPLY_SURFACES and
# LINKEDIN_SURFACES themselves, but `tests/test_record.py::TestLinkedinSurfaceVocabulary` pins both
# at four and five tokens, and that file is outside this change's declared file set. So the two
# constants above are left exactly as they were and the wider vocabulary is a THIRD constant beside
# them; folding it back is a one-line change plus that one test (named in the hand-back).
LINKEDIN_SWEEP_SURFACES = LINKEDIN_SURFACES | frozenset({"connections"})

# A silence proof's four SLOTS, each satisfied by any one of its tokens. The `--probe --result
# empty --read` check below iterates this, so the shipped `--read inbox,requests,invitations,degree`
# and the new `--read inbox,requests,invitations,connections` are both accepted.
LINKEDIN_REPLY_SLOTS = (("inbox",), ("requests",), ("invitations",), ("connections", "degree"))

# design-linkedin-runner-resilience.md §6 — the old spelling stays ACCEPTED (profiles already
# carry gap rows written this way) but is no longer the canon a shipped file instructs: every
# `--gap` naming it is normalized to `linkedin:requests` at write time, printed once so the
# normalization is never silent. Rows already on disk keep their stored scope — nothing keys on
# scope, `--close-gap` is by id.
LINKEDIN_MESSAGE_REQUESTS_ALIAS = "linkedin:message-requests"
LINKEDIN_MESSAGE_REQUESTS_CANON = "linkedin:requests"


def record_probe(root, subject, thread, result, medium="linkedin", mailbox=None, by=None,
                 at=None):
    """⭐ dev #321 item 2 (V0), extended by Query or Citation C1 (D1) — one thread look, on
    either medium. Pointwise: unlike a mailbox sweep, which searches a window, a probe OPENS the
    thread (or, for email, searches an address/name-term set — see brief.py §4.3) and sees
    everything relevant, so one probe at T verifies that thread through T with no interval to
    merge.

    `medium` defaults to `"linkedin"` so every V0 caller (none existed before C1, but the
    default keeps the shape backward-compatible on principle) is unaffected. `mailbox` names the
    email account this probe searched — required when `medium="email"`, refused otherwise (a
    LinkedIn probe has no per-account shape; carrying a stray value there would let a reader
    mistake it for an email probe of that account). `by="owner"` marks the owner's own
    `--i-checked` attestation (brief.py §4.4) rather than a script-run search.

    C1's writers: `brief.py`'s mailbox probe (medium="email", one row per configured account)
    and `journal.py --probe --medium linkedin` (`linkedin-runner`, via --read — see main())."""
    at = at or now_iso()
    if not (subject and thread):
        raise JournalError("record_probe requires subject and thread")
    if medium not in MEDIA:
        raise JournalError("medium %r is not recognised — use 'email' or 'linkedin'" % medium)
    if medium == "email" and not mailbox and by != "owner":
        raise JournalError("record_probe(medium='email') requires mailbox (unless by='owner' "
                           "— the owner's own attestation names no specific account)")
    if medium == "linkedin" and mailbox:
        raise JournalError("record_probe(medium='linkedin') takes no mailbox — a LinkedIn probe "
                           "is not per-account")
    if not PROBE_RESULT_RE.match(result or ""):
        raise JournalError(
            "--result %r is not recognised — use 'empty' or 'thread:<ISO timestamp>' "
            "(Class C's probe vocabulary)" % result)
    rec = {"event": "probe", "medium": medium, "mailbox": mailbox, "subject": subject,
           "thread": thread, "result": result, "at": at}
    if by:
        rec["by"] = by
    return append(root, rec)


def record_gap(root, run_id, scope, reason, closes_when="", covered_by="", at=None,
               covered_reason=""):
    """The ONE writer of a `gap` row (factored out of main()'s `--gap` branch, dev #488 /
    public #105, so `linkedin_sweep.py record` can file a `partial-results` gap without shelling
    out). Returns the gap id. The caller owns scope normalisation and `covered_by` citation
    normalisation; this validates only what a stored gap must carry to be countable.

    ⭐ dev #711 / public #147 — a `covered_by` SUPPRESSES the gap, so it must say why the cited
    issue covers THIS gap's scope: `covered_reason`, required with `covered_by`, stored beside it.
    A reason with no citation is refused too (it would be a claim about nothing). Rows written
    before this field existed carry no reason; they stay valid and read as unverified."""
    at = at or now_iso()
    covered_reason = " ".join((covered_reason or "").split())
    if covered_by:
        if not (COVERED_REASON_MIN <= len(covered_reason) <= COVERED_REASON_MAX):
            raise JournalError(
                "--covered-by needs --covered-reason: %d-%d characters saying why %s covers THIS "
                "gap's scope (got %d). A citation hides the gap from --check, so it has to say "
                "what it is vouching for (dev #711)."
                % (COVERED_REASON_MIN, COVERED_REASON_MAX, covered_by, len(covered_reason)))
    elif covered_reason:
        raise JournalError("--covered-reason without --covered-by: a reason for a citation "
                           "that does not exist")
    if not run_id:
        raise JournalError("record_gap requires run_id")
    if not scope:
        raise JournalError("record_gap requires a scope")
    if reason not in REASONS:
        raise JournalError("record_gap reason %r is not in REASONS %r" % (reason, sorted(REASONS)))
    gid = "%s:%s" % (run_id, re.sub(r"[^A-Za-z0-9:._-]+", "-", scope))
    append(root, {"event": "gap", "run_id": run_id, "gap_id": gid, "scope": scope,
                  "reason": reason, "covered_by": covered_by or "",
                  "covered_reason": covered_reason,
                  "closes_when": closes_when or "", "at": at})
    return gid


def _parse_iso(raw):
    try:
        return datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# ⭐ dev #807 — coverage windows are INSTANTS, read by ONE parser
# --------------------------------------------------------------------------
# A `swept` row's `from`/`through` used to be naive local wall time. In the fall-back hour that names
# two instants, and `01:10` (before the change) and `01:50` (after it) compared with the wrong order:
# a real 1h40m hole merged away and printed as covered. The writer now stores a numeric offset, and
# every reader goes through `parse_instant`. Rows written before 0.83.0 stay naive on disk (the journal
# is append-only, and a rewrite could only apply the same rule the reader does: design-sweep-misfires
# section 4.2), so `parse_instant` carries the stated legacy interpretation too.
_UTC = datetime.timezone.utc
INSTANT_ROLES = ("from", "through", "point")


def _declared_zone():
    """The tzinfo `_localzone` resolves (declared `geography.timezone`, then `TZ`), or None when only
    the host zone is known. Never raises: a zone we cannot load is the host zone, not a crash."""
    try:
        import _localzone
        return _localzone.local_zone()
    except Exception:
        return None


def _fromiso(raw):
    """`fromisoformat` that accepts a trailing `Z` (3.9 and 3.10 refuse it); None on anything else."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def is_offset_bearing(raw):
    """True when `raw` is an ISO string that names ONE instant (it carries a numeric offset or `Z`).
    The predicate `record_swept` uses: `parse_instant` cannot be, because it deliberately reads a naive
    legacy value as an instant by the legacy rule."""
    d = _fromiso(raw)
    return d is not None and d.tzinfo is not None and d.utcoffset() is not None


def coverage_iso(dt):
    """An AWARE datetime as the ISO string a `swept` row stores: its offset, in the zone `_localzone`
    resolves (declared `geography.timezone`, then `TZ`, then the host), e.g. `2026-11-01T01:05:00-06:00`.
    The instant is correct in any zone; the declared zone only decides which offset is printed, so the
    ledger reads in the owner's clock even when the host is elsewhere. Never emits `Z` (3.9 cannot parse
    it back). Raises on a naive datetime: that is the defect this exists to end."""
    if not isinstance(dt, datetime.datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise JournalError("coverage_iso needs an AWARE datetime, got %r — a naive local time in the "
                           "fall-back hour names two instants (dev #807)" % (dt,))
    tz = _declared_zone()
    local = dt.astimezone(tz) if tz is not None else dt.astimezone()
    return local.replace(microsecond=0).isoformat()


def _coverage_field(value, name):
    """The stored form of a `swept` window end: an aware datetime through `coverage_iso`, or a string
    that already carries an offset (kept verbatim). Anything naive is refused."""
    if isinstance(value, datetime.datetime):
        return coverage_iso(value)
    if not is_offset_bearing(value):
        raise JournalError(
            "record_swept(ok=True) %s=%r carries no UTC offset. A naive local time in the fall-back hour "
            "names two instants, so a coverage window must be an instant: pass an aware datetime or "
            "journal.coverage_iso(dt) (dev #807)." % (name, value))
    return value


def _journal_at(at):
    """`at` keeps the journal-wide naive-local convention: an aware datetime becomes naive host-local."""
    if isinstance(at, datetime.datetime):
        if at.tzinfo is not None:
            at = at.astimezone().replace(tzinfo=None)
        return at.replace(microsecond=0).isoformat()
    return at


def parse_instant(raw, role="point"):
    """⭐ dev #807 — THE ONE parser for a coverage timestamp: an aware UTC datetime, or None when `raw`
    cannot be read. `role` is one of `INSTANT_ROLES`.

    An offset-bearing value is exact. A NAIVE value is a legacy row (written before 0.83.0 as wall time
    on the writing machine's zone), read by the stated rule of design-sweep-misfires section 4.2:
      * the candidate zones are this host's zone and the declared zone (`_localzone`);
      * in each candidate, BOTH readings of the wall time are built (`fold=0` and `fold=1`);
      * `from` takes the LATEST reading and `through` the EARLIEST, so coverage can only shrink: a
        real hole is never merged away, and a false hole is closed by the next sweep reaching back;
      * `point` takes `fold=0` in the declared zone (the host zone when none is declared).
    Outside a fold, with one zone, every reading is equal and nothing changes. When the candidate zones
    differ, a legacy row shrinks by their difference, so a legacy row SHORTER than that difference reads
    inverted and contributes no coverage (`coverage_intervals` drops it)."""
    if role not in INSTANT_ROLES:
        raise JournalError("parse_instant role must be one of %r, got %r" % (INSTANT_ROLES, role))
    d = _fromiso(raw)
    if d is None:
        return None
    if d.tzinfo is not None:
        return d.astimezone(_UTC)
    declared = _declared_zone()
    readings = []
    point = None
    for fold in (0, 1):
        naive = d.replace(fold=fold)
        candidates = [("host", naive)]
        if declared is not None:
            candidates.append(("declared", naive.replace(tzinfo=declared)))
        for kind, cand in candidates:
            try:
                utc = cand.astimezone(_UTC)
            except (OverflowError, OSError, ValueError):
                continue
            readings.append(utc)
            if fold == 0 and kind == ("declared" if declared is not None else "host"):
                point = utc
    if not readings:
        return None
    if role == "from":
        return max(readings)
    if role == "through":
        return min(readings)
    return point if point is not None else readings[0]


def coverage_intervals(recs, mailbox, by=None):
    """⭐ dev #807 — `[(from_utc, through_utc), ...]` for every `ok: true` `swept` row of `mailbox` (and
    of sweep kind `by`, when given), read through `parse_instant`. A row that cannot be read, or whose
    `from` is at or after its `through` (a legacy row wholly inside the fold, or shorter than the zone
    difference), contributes NOTHING: its hour reads as not covered, never as a crash. The one place a
    `swept` window is turned into intervals; `covered_through` and `mail_client.uncovered_spans` share it."""
    out = []
    for r in recs:
        if r.get("event") != "swept" or r.get("mailbox") != mailbox or not r.get("ok"):
            continue
        if by is not None and r.get("by") != by:
            continue
        fd, td = parse_instant(r.get("from"), "from"), parse_instant(r.get("through"), "through")
        if fd is None or td is None or fd >= td:
            continue
        out.append((fd, td))
    return out


def _as_of_instant(as_of):
    """`covered_through`'s `as_of` (a datetime or a string) as an aware UTC instant, or None."""
    if isinstance(as_of, datetime.datetime):
        if as_of.tzinfo is not None:
            return as_of.astimezone(_UTC)
        return parse_instant(as_of.isoformat(), "point")
    return parse_instant(as_of, "point")


def _merge_intervals(intervals):
    """[(from_dt, through_dt), ...] (aware datetimes) -> the same list with every overlapping or
    touching pair merged into one. Adjacency is guaranteed across a healthy run history by the
    ledger-derived lookback in `mail_client.py` (each sweep reaches back to the end of the last covered
    interval), so a gap that survives this merge is a REAL hole, not a rounding artefact. An empty or
    inverted pair is dropped (dev #807), never raised."""
    merged = []
    for f, t in sorted((p for p in intervals if p[0] < p[1]), key=lambda p: p[0]):
        if merged and f <= merged[-1][1]:
            if t > merged[-1][1]:
                merged[-1] = (merged[-1][0], t)
        else:
            merged.append((f, t))
    return merged


def covered_through(recs, mailbox, as_of=None, by=None):
    """⭐⭐ dev #321 (V0) — THE READER every silence consumer imports. The end (ISO string) of
    the contiguous VERIFIED-coverage interval for `mailbox` that CONTAINS `as_of` — or, with no
    `as_of`, the newest merged interval's end. Returns `None` when nothing verifies coverage
    there: no `swept` rows at all, or `as_of` falls in a gap between them. `None` is the honest
    default on an empty ledger — the caller's job (check_followups.py) is to render "unverified"
    rather than fall back to the wall clock, which is dev #321 itself.

    Coverage is the union of `[from, through]` windows from `ok: true` swept rows for this
    mailbox; a `swept ok: false` row (a failed account) contributes nothing, which is what makes
    a partial failure mark that account uncovered rather than merely annotated.

    ⭐ design-inbound-resolution.md §5 amendment D3 (surface pass 2026-09-14) — `by`, optional,
    filters to rows written by that sweep kind ONLY. Before this fix `by` was ignored entirely,
    so `covered_through(recs, mailbox)` merged EVERY sweep's coverage regardless of which one
    wrote it — a mailbox the daily `alert_sweep` has been covering every day reads as covered
    through today even though `reconcile-ats` has never once run there, so the very first
    `--ats` run saw the daily's 3-day floor instead of the 30-day first-run backfill, and a
    25-day-old decline (public #55) was never even in the searched window. `by=None` keeps the
    old, cross-sweep-kind merge every EXISTING caller relies on (check_followups.verified_as_of,
    the plain `mail_client.lookback_days(..., by=None)` call `watch.py`/`alert_sweep.py`/
    `meeting_check.py` already make) — only a caller that asks for its OWN sweep kind's history
    gets the narrower answer.

    ⭐ dev #807 — the windows are INSTANTS, read by `parse_instant` (a legacy naive row by its stated
    rule), merged as instants, and the answer is an offset-bearing ISO string in the declared zone,
    not a naive one: `01:05-05:00` and `01:05-06:00` are two different answers. `as_of` is read as a
    `point`. A row whose `from` is at or after its `through` contributes nothing.
    """
    intervals = coverage_intervals(recs, mailbox, by=by)
    if not intervals:
        return None
    merged = _merge_intervals(intervals)
    if as_of is None:
        return coverage_iso(merged[-1][1])
    as_of_dt = _as_of_instant(as_of)
    if as_of_dt is None:
        return None
    for f, t in merged:
        if f <= as_of_dt <= t:
            return coverage_iso(t)
    return None


def triaged_uids(recs, mailbox, by=None, as_of=None, ttl_days=TRIAGE_TTL_DAYS):
    """⭐ public #99 — the set of uid strings already triaged for `mailbox`, within the last
    `ttl_days` of `as_of` (default: now) — what a sweep should SKIP rather than re-fetch and
    re-screen. Read BEFORE any mailbox fetch, exactly the way `covered_through()` is read before
    a sweep decides its own search window.

    `by`, optional, narrows to one sweep kind's own history — the same filter
    `covered_through(..., by=...)` already carries (design-inbound-resolution.md §5 amendment
    D3), so a second sweep that someday triages the same mailbox for a different purpose does
    not silently cover for this one. `mailbox` is matched exactly, never merged across accounts
    — two mailboxes sharing an IMAP uid number are two different rows here, filtered apart the
    same way `covered_through()` never merges two mailboxes' coverage.

    A row older than `ttl_days` is treated as though it were never written — see
    `TRIAGE_TTL_DAYS`'s own docstring for why an aged-out disposition is correct rather than a
    leak: the uid can only be re-found inside a sweep's own bounded search window, so a
    disposition that has outlived every window a sweep could plausibly run can never be checked
    against a live hit anyway."""
    if as_of is None:
        as_of_dt = datetime.datetime.now()
    elif isinstance(as_of, datetime.datetime):
        as_of_dt = as_of
    else:
        as_of_dt = _parse_iso(as_of) or datetime.datetime.now()
    floor = as_of_dt - datetime.timedelta(days=ttl_days)
    out = set()
    for r in recs:
        if r.get("event") != "triaged" or r.get("mailbox") != mailbox:
            continue
        if by is not None and r.get("by") != by:
            continue
        at_dt = _parse_iso(r.get("at"))
        if at_dt is None or at_dt < floor:
            continue
        uid = r.get("uid")
        if uid:
            # dev #704 / public #154 (D1) — a uid stored before 0.66.0 is the REPR of a bytes
            # object ("b'101'"); the fresh uid a sweep now holds is "101". Same message.
            import validate_data as _vd
            out.add(str(_vd.normalize_uid(str(uid))))
    return out


def probe_covered_through(recs, thread, medium):
    """⭐ dev #321 item 2 (V0), medium-filtered by Query or Citation C1 (D1) — the newest
    `probe` row's `at` for this `thread` ON THIS MEDIUM, or `None`. A probe is pointwise (see
    `record_probe`), so the newest one alone verifies coverage through its own timestamp; no
    interval merge applies.

    `medium` carries NO DEFAULT on purpose: V0 had exactly one caller and none existed yet, so a
    default was harmless; C1 adds the first real consumers (`your_move.conversation_axis()`),
    and a caller that does not say which medium it means would silently accept an email probe
    as LinkedIn coverage of the same `contact:<id>` thread (or vice versa) — the exact
    cross-medium confusion D1 exists to prevent."""
    ats = [r.get("at") for r in recs
          if r.get("event") == "probe" and r.get("thread") == thread
          and r.get("medium") == medium and r.get("at")]
    return max(ats) if ats else None


def pass_durations(recs):
    """design-linkedin-runner-resilience.md §1 (public #47/#96) — the MEASUREMENT tool behind
    `linkedin.pane_stale_minutes`'s UNVERIFIED default. For every run that both started and
    ended AND carries evidence of LinkedIn work, its wall-clock duration in minutes — longest
    first, so the owner reads the worst case off the top rather than guessing.

    "Carries LinkedIn work" is two different correlations, because a `gap` carries `run_id`
    directly but a `probe` never has (it is pointwise, not run-scoped — see `record_probe`):
    a `gap` whose scope starts with `linkedin:` counts its own `run_id` directly; a `probe` on
    medium `linkedin` counts every run whose [start, end] window contains the probe's `at` —
    the same interval-containment idea `covered_through()` uses, applied to run duration
    instead of mailbox coverage."""
    starts, ends = {}, {}
    for r in recs:
        if r.get("event") == "start":
            starts[r.get("run_id")] = r.get("at")
        elif r.get("event") == "end":
            ends[r.get("run_id")] = r.get("at")
    linkedin_run_ids = {r.get("run_id") for r in recs
                        if r.get("event") == "gap"
                        and str(r.get("scope") or "").startswith("linkedin:")}
    # design-script-first.md §2 — a `pass … phase returned` row carries its own `run_id`
    # directly (unlike a `probe`, which is pointwise): a second, free correlation once the
    # `pass` event exists, no new query needed.
    linkedin_run_ids |= {r.get("run_id") for r in recs
                        if r.get("event") == "pass" and r.get("kind") == "linkedin"
                        and r.get("phase") == "returned"}
    probe_ats = [d for d in (_parse_iso(r.get("at")) for r in recs
                            if r.get("event") == "probe" and r.get("medium") == "linkedin")
                if d is not None]
    out = []
    for rid, s in starts.items():
        e = ends.get(rid)
        if not e:
            continue
        sd, ed = _parse_iso(s), _parse_iso(e)
        if sd is None or ed is None:
            continue
        carries = rid in linkedin_run_ids or any(sd <= p <= ed for p in probe_ats)
        if not carries:
            continue
        out.append({"run_id": rid, "minutes": round((ed - sd).total_seconds() / 60.0, 1),
                    "start": s, "end": e})
    return sorted(out, key=lambda d: -d["minutes"])


def _parse_transcript_ts(raw):
    """A transcript record's own `timestamp`, which — unlike every `at` this journal writes
    itself (always `now_iso()`, naive local time) — may carry a trailing 'Z' (UTC) that
    `datetime.fromisoformat` only accepts from Python 3.11 (this file targets 3.9+). Stripped to
    a naive datetime for comparison against a run's `start.at`: an approximation when the two
    clocks disagree (local vs UTC), stated rather than silently assumed exact — the fold's own
    idempotence (keyed on `agent_id`, not on this filter) is what keeps a borderline miss from
    ever duplicating a row, so an imprecise boundary here costs at most one late fold, never a
    wrong one."""
    if not raw:
        return None
    s = str(raw)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = _parse_iso(s)
    if dt is not None and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _is_agent_result(rec):
    """Duck-typed on the §8.1 measurement (`deployment-auditor`, #82): a transcript record whose
    `toolUseResult` carries `agentId` is an `Agent`/`Task` dispatch's return — no other tool's
    `toolUseResult` shape carries that key. Never assumes a chain-walk to the originating
    `tool_use`'s `name`; the key itself is the signal that was actually measured."""
    tur = rec.get("toolUseResult")
    return isinstance(tur, dict) and bool(tur.get("agentId"))


def _hand_back_text(tur):
    """(text, source) — the hand-back to read `outcome`'s first word from. `content` first (§8.1:
    populated in 53 of 349 measured results); else the first line of `outputFile`, opened only
    when `canReadOutputFile` (#82: `content` is `None` in 296 of 349 — the common case). `(None,
    "none")` when neither is available — never a guess."""
    content = tur.get("content")
    if content:
        if isinstance(content, str):
            return content, "content"
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("text")]
            if texts:
                return " ".join(texts), "content"
        return str(content), "content"
    output_file = tur.get("outputFile")
    if output_file and tur.get("canReadOutputFile"):
        try:
            with open(output_file, encoding="utf-8") as fh:
                return fh.read(), "outputFile"
        except OSError:
            return None, "outputFile-unreadable"
    return None, "none"


def _outcome_from_text(text):
    word = (text or "").strip().split()[0] if text and text.strip() else ""
    key = re.sub(r"[^A-Za-z]", "", word).lower()
    if not key:
        return "unknown"
    return OUTCOME_MAP.get(key, key)


def _fields_from_agent_result(rec):
    """(fields, refusal_reason) — `fields` is the writer-ready dict (minus `event`/`run_id`/
    `at`) for ONE `Agent` toolUseResult, or `None` with a reason when a required §8.1 field is
    missing: 'refused loudly' rather than silently defaulted, so a malformed result never reads
    as a free, zero-cost dispatch."""
    tur = rec.get("toolUseResult") or {}
    agent_id = tur.get("agentId")
    agent = tur.get("agentType")
    tokens = tur.get("totalTokens")
    tool_uses = tur.get("totalToolUseCount")
    duration_ms = tur.get("totalDurationMs")
    missing = [k for k, v in (("agentId", agent_id), ("agentType", agent),
                              ("totalTokens", tokens), ("totalToolUseCount", tool_uses),
                              ("totalDurationMs", duration_ms)) if v is None]
    if missing:
        return None, "missing %s" % ", ".join(missing)
    text, _source = _hand_back_text(tur)
    prompt = tur.get("prompt") or ""
    for_ = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
    return {"agent": agent, "agent_id": agent_id, "model": tur.get("resolvedModel") or "",
           "tokens": int(tokens), "tool_uses": int(tool_uses),
           "duration_s": int(round(duration_ms / 1000.0)), "outcome": _outcome_from_text(text),
           "for": for_}, None


def fold_dispatches(root, run_id, transcript_path=None, at=None):
    """design-script-first.md §8.2 (public #82/#90/#91) — the PROVEN path (the `PostToolUse`
    hook is the unverified primary and is not built by this function). Resolves the transcript
    from `transcript_path` when given (tests), else this session's stash
    (`_root.transcript_stash_path()`); a surface with neither prints `no transcript on this
    surface` and writes nothing — never a false zero read as fact. Every `Agent` result strictly
    newer than the run's own `--start` is a candidate; idempotent on `agent_id`, so a second fold
    over the same transcript adds nothing. Returns (written, skipped, refused) — `refused`
    entries are printed loudly to stderr, one per malformed result, and never silently dropped."""
    recs = read(root)
    start_rec = next((r for r in recs if r.get("event") == "start" and r.get("run_id") == run_id),
                     None)
    if start_rec is None:
        raise JournalError("--fold-dispatches --run %r: no matching --start run — get one from "
                           "--start" % run_id)
    start_dt = _parse_iso(start_rec.get("at"))

    if transcript_path is None:
        try:
            with open(transcript_stash_path(), encoding="utf-8") as fh:
                transcript_path = fh.read().strip() or None
        except OSError:
            transcript_path = None
    if not transcript_path:
        print("no transcript on this surface")
        return 0, 0, []
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        print("no transcript on this surface (%s)" % e)
        return 0, 0, []

    already = {r.get("agent_id") for r in recs if r.get("event") == "dispatch"}
    written, skipped, refused = 0, 0, []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or not _is_agent_result(rec):
            continue
        ts = _parse_transcript_ts(rec.get("timestamp"))
        if ts is None or (start_dt is not None and ts < start_dt):
            continue
        fields, reason = _fields_from_agent_result(rec)
        if fields is None:
            hint = (rec.get("toolUseResult") or {}).get("agentId") or "?"
            print("⛔ dispatch fold: result %s refused — %s" % (hint, reason), file=sys.stderr)
            refused.append(hint)
            continue
        if fields["agent_id"] in already:
            skipped += 1
            continue
        record_dispatch(root, run_id=run_id, agent=fields["agent"],
                        agent_id=fields["agent_id"], model=fields["model"],
                        tokens=fields["tokens"], tool_uses=fields["tool_uses"],
                        duration_s=fields["duration_s"], outcome=fields["outcome"],
                        for_=fields["for"], at=at or now_iso())
        already.add(fields["agent_id"])
        written += 1
    print("folded %d dispatch row(s) for %s (%d already recorded, %d refused)"
         % (written, run_id, skipped, len(refused)))
    return written, skipped, refused


def _percentile(sorted_vals, p):
    """Linear-interpolation percentile over an already-sorted, non-empty list — copied from
    `scripts/dispatch_ledger.py` (the MAINTENANCE ledger, at the marketplace repo root): that
    module is never importable from a SHIPPED file, so the shape is duplicated, not shared, the
    same reasoning `TRIAGE_TTL_DAYS`'s own docstring already states for `mail_client.py`."""
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    k = (p / 100.0) * (n - 1)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return float(sorted_vals[f])
    d = k - f
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * d


def cmd_calibrate_dispatches(root):
    rows = dispatch_rows(read(root))
    print("DISPATCH --calibrate (per agent — token/tool_use quantiles, no recommendation)")
    if not rows:
        print("  no dispatch rows yet.")
        return 0
    by_agent = {}
    for r in rows:
        by_agent.setdefault(r.get("agent"), {"tokens": [], "tool_uses": []})
        by_agent[r.get("agent")]["tokens"].append(r.get("tokens", 0))
        by_agent[r.get("agent")]["tool_uses"].append(r.get("tool_uses", 0))
    for agent in sorted(by_agent):
        toks = sorted(by_agent[agent]["tokens"])
        tus = sorted(by_agent[agent]["tool_uses"])
        print("  %-24s n=%-4d tool_uses min=%-5d p50=%-7.1f p90=%-7.1f max=%-5d  "
             "tokens min=%-8d p50=%-9.1f p90=%-9.1f max=%-8d"
             % (agent, len(toks), tus[0], _percentile(tus, 50), _percentile(tus, 90), tus[-1],
                toks[0], _percentile(toks, 50), _percentile(toks, 90), toks[-1]))
    return 0


def cmd_dispatches(root, today_only=False, calibrate=False):
    rows = dispatch_rows(read(root), today_only=today_only)
    print("DISPATCHES%s" % (" (today)" if today_only else ""))
    if not rows:
        print("  none.")
    else:
        for r in sorted(rows, key=lambda r: r.get("at", "")):
            print("  %-19s %-22s run=%-26s tokens=%-7d tool_uses=%-4d %-8s for=%s"
                 % (str(r.get("at", ""))[:19], r.get("agent"), r.get("run_id"),
                    r.get("tokens", 0), r.get("tool_uses", 0), r.get("outcome"),
                    r.get("for") or "-"))
        by_agent, by_run = {}, {}
        for r in rows:
            a = by_agent.setdefault(r.get("agent"), [0, 0])
            a[0] += r.get("tokens", 0)
            a[1] += r.get("tool_uses", 0)
            rn = by_run.setdefault(r.get("run_id"), [0, 0])
            rn[0] += r.get("tokens", 0)
            rn[1] += r.get("tool_uses", 0)
        print("  by agent:")
        for a in sorted(by_agent):
            print("    %-24s tokens=%-8d tool_uses=%-5d" % (a, by_agent[a][0], by_agent[a][1]))
        print("  by run:")
        for rn in sorted(by_run):
            print("    %-24s tokens=%-8d tool_uses=%-5d" % (rn, by_run[rn][0], by_run[rn][1]))
    if calibrate:
        print()
        cmd_calibrate_dispatches(root)
    return 0


def cmd_passes(root, today_only=False):
    """design-script-first.md §2 — every `pass` row, oldest first, plus the crashed-pass line
    (a `dispatched` row in an ended run with no matching `returned`). `0 passes` on an empty
    journal, exit 0 either way — this is a report, never a gate."""
    recs = read(root)
    rows = pass_rows(recs, today_only=today_only)
    label = "%d passes%s" % (len(rows), " today" if today_only else "")
    print(label if rows else "0 passes")
    for r in sorted(rows, key=lambda r: r.get("at", "")):
        bits = "%-19s %-8s %-10s run=%s" % (str(r.get("at", ""))[:19], r.get("kind"),
                                            r.get("phase"), r.get("run_id"))
        if r.get("phase") == "returned":
            bits += (" reached=%s unreachable=%s not_attempted=%s"
                    % (",".join(r.get("reached") or []) or "-",
                       ",".join(r.get("unreachable") or []) or "-",
                       ",".join(r.get("not_attempted") or []) or "-"))
            if r.get("jobsearch"):
                bits += " jobsearch=%s" % r["jobsearch"]
        elif r.get("phase") == "refused":
            bits += " reason=%s" % (r.get("reason") or "-")
        elif r.get("phase") == "recorded":
            # dev #812 / public #169 -- how `linkedin_sweep.py record` judged the hand-back
            bits += (" verdict=%s faults=%s concluded=%s not_concluded=%s kept=%s"
                    % (r.get("verdict"), r.get("faults"), r.get("concluded"),
                       r.get("not_concluded"), r.get("kept") or "-"))
            # dev #826 / public #177 -- the pane account (0.83.0). A row written before it carries none of the three
            # fields and prints exactly as it did; one that carries them says the pane, the mode and any partial surfaces.
            if r.get("pane") is not None:
                part = r.get("partial") if isinstance(r.get("partial"), list) else []
                bits += " pane=%s mode=%s partial=%s" % (r.get("pane"), r.get("mode"),
                                                         ",".join(str(t) for t in part) or "-")
                if part:
                    bits += " PARTIAL"
        elif r.get("phase") == "dispatched" and r.get("channels"):
            bits += " channels=%s" % ",".join(r["channels"])
        elif r.get("phase") == "done":
            bits += " unreached=%s" % (",".join(r.get("unreached") or []) or "-")
        if r.get("ids"):
            bits += " ids=%s" % ",".join(r["ids"])
        print("  %s" % bits)
    crashed = crashed_passes(recs)
    if crashed:
        print("  pass dispatched, never returned (%s)" % ", ".join(crashed))
    return 0


def age_days(at):
    try:
        then = datetime.datetime.fromisoformat(at)
        return (datetime.datetime.now() - then).days
    except Exception:
        return 0


# ⭐⭐ public #69 — THE PURE/IMPURE SPLIT, copied deliberately from
# `check_regression_links.py`'s own split for the identical reason: "is issue #N still open"
# needs `gh` and the network, and CI has neither. So the DECISION logic below (`evaluate_coverage`)
# is pure and exercised in CI against a fake `issue_state`; the ANSWER (`issue_state` itself) is
# impure, lives only here, and is never called by any CI-run gate — `--check-coverage` is a tool
# gate-keeper/release-manager run locally, on demand, exactly like that script's own `main()`.

def evaluate_coverage(gaps, issue_state):
    """Which covered_by citations are still doing their job? De-duplicates by citation first —
    ten gaps covered by the same filed issue need exactly one live lookup, not ten.

    `issue_state(citation) -> "OPEN" | "CLOSED" | "MISSING" | None` is the one impure call this
    function makes; everything else here is deterministic. Returns three lists of
    `(citation, [gap_id, ...])`: verified-open, stale (CLOSED or MISSING — the citation has
    outlived its cause, or never named a real issue), and unverifiable (no `gh`, no network, or —
    for a `dev`/`github`/`marketplace` citation checked from an INSTALLED copy — no private-repo
    remote to even ask; that last case is normal and not itself a failure)."""
    by_citation = {}
    for g in gaps:
        c = g.get("covered_by")
        if c:
            by_citation.setdefault(c, []).append(g.get("gap_id"))
    verified_open, stale, unverifiable = [], [], []
    for citation in sorted(by_citation):
        gap_ids = by_citation[citation]
        state = issue_state(citation)
        if state == "OPEN":
            verified_open.append((citation, gap_ids))
        elif state in ("CLOSED", "MISSING"):
            stale.append((citation, gap_ids))
        else:
            unverifiable.append((citation, gap_ids))
    return verified_open, stale, unverifiable


def _split_citation(citation):
    kind, _, num = (citation or "").partition("#")
    return kind.strip().lower(), num.strip()


def _public_repo():
    """This plugin's OWN public tracker, read from its manifest — the same derivation
    `report_issue.py`'s `tracker()` uses, so this resolves from an INSTALLED copy with no
    knowledge of the private repo at all."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(os.path.dirname(here), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            repo = str(json.load(fh).get("repository") or "")
        m = re.search(r"github\.com[:/]([\w.\-]+/[\w.\-]+?)(?:\.git)?/?$", repo)
        return m.group(1) if m else None
    except Exception:                                     # noqa: BLE001
        return None


def _private_repo():
    """This CHECKOUT's own origin — resolvable only from a maintainer checkout. An installed
    copy is not a git repository at all, so `git remote` simply fails here, which is correct: an
    installed copy has no business knowing the private repo's name, let alone querying it."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(["git", "-C", here, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", (out.stdout or "").strip())
        return m.group(1) if m else None
    except Exception:                                     # noqa: BLE001
        return None


def issue_lookup(citation):
    """LIVE, IMPURE, NEVER CALLED IN CI. Returns `(state, title)`: state is 'OPEN', 'CLOSED',
    'MISSING' (the repo resolved but the issue did not), or None -- unverifiable from here, which
    covers "no `gh` on PATH", "no network", and "a dev/github/marketplace citation asked from an
    installed copy with no private remote" alike. `evaluate_coverage()` above is what gives that
    None a name. `title` is the issue's title when GitHub answered, else None (dev #711: the
    write-time echo prints it so a wrong citation is visible to the person typing it)."""
    kind, num = _split_citation(citation)
    if not num.isdigit():
        return None, None
    repo = _public_repo() if kind == "public" else _private_repo()
    if not repo:
        return None, None
    try:
        out = subprocess.run(["gh", "issue", "view", num, "--repo", repo, "--json",
                              "state,title"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None, None
    if out.returncode != 0:
        return ("MISSING" if "could not resolve" in (out.stderr or "").lower() else None), None
    try:
        data = json.loads(out.stdout or "{}")
    except ValueError:
        return None, None
    state = str(data.get("state") or "").upper() or None
    title = " ".join(str(data.get("title") or "").split())[:120] or None
    return state, title


def issue_state(citation):
    """The state half of `issue_lookup()`; the one impure call `evaluate_coverage()` makes."""
    return issue_lookup(citation)[0]


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

def coverage_cache_path(root):
    return os.path.join(root, COVERAGE_CACHE)


def read_coverage_cache(root):
    """(verdicts, problem). `verdicts` is {citation: {"state", "at"}}; `problem` is None, or a
    sentence saying why the file could not be used. An ABSENT file is not a problem (nothing has
    been checked yet: every citation reads as unverified). A present-but-unreadable one is: it is
    returned as `({}, reason)` so the caller can say so out loud instead of quietly treating a
    corrupt cache as an empty one."""
    p = coverage_cache_path(root)
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as e:
        return {}, "%s is not readable (%s)" % (COVERAGE_CACHE, e)
    verdicts = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(verdicts, dict):
        return {}, "%s has no 'verdicts' object" % COVERAGE_CACHE
    for citation, v in verdicts.items():
        if not (isinstance(v, dict) and v.get("state") in COVERAGE_STATES
                and isinstance(v.get("at"), str) and _DATE_RE.match(v["at"])):
            return {}, ("%s entry %r is not {state: OPEN|CLOSED|MISSING, at: YYYY-MM-DD}"
                        % (COVERAGE_CACHE, citation))
    return verdicts, None


def write_coverage_cache(root, verdicts, checked_at):
    """Atomically write the cache (temp file + rename). Same refusals as the journal itself:
    no unbound directory, never the tracked fixture. Returns the path written."""
    _refuse_if_unwritable(root)
    p = coverage_cache_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp-%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"checked_at": checked_at, "verdicts": verdicts}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, p)
    return p


def apply_coverage_cache(covered, verdicts):
    """PURE. Split the `covered` gaps (from `split_gaps`) by what is known about their citation:

        (still_covered, degraded, unverified)

    `degraded`: the citation was last known CLOSED or MISSING -- each is a COPY of the gap with
    `degraded_because` set, to be counted as open. `unverified` is a subset of `still_covered`:
    the citation has no verdict yet, or the gap has no stored `covered_reason` (a row from before
    dev #711). CLOSED/MISSING wins over a missing reason: a closed issue covers nothing."""
    still, degraded, unverified = [], [], []
    for g in covered:
        v = verdicts.get(g.get("covered_by"))
        if v and v["state"] in ("CLOSED", "MISSING"):
            degraded.append(dict(g, degraded_because=(
                "%s was %s as of %s" % (g.get("covered_by"), v["state"], v["at"]))))
            continue
        still.append(g)
        if not v or not g.get("covered_reason"):
            unverified.append(g)
    return still, degraded, unverified


def coverage_echo(citation, lookup=None):
    """Lines the write-time `--gap --covered-by` prints so the citation can be eyeballed: the
    cited issue's title and state, or NOT VERIFIED. `lookup` is injectable for tests."""
    state, title = (lookup or issue_lookup)(citation)
    if state is None:
        return ["  covered by %s: NOT VERIFIED (no gh, no network, or no reachable repo) -- the "
                "reason is stored, but nobody has seen that this issue exists" % citation]
    lines = ["  covered by %s: %s%s" % (citation, state, " -- %s" % title if title else "")]
    if state in ("CLOSED", "MISSING"):
        lines.append("  !! %s is %s: it covers nothing now. Check the number; "
                     "`--check-coverage` will list this gap as stale."
                     % (citation, "closed" if state == "CLOSED" else "not a real issue"))
    return lines


def _record_fired(root, at):
    """⭐⭐ public #65 — called ONLY from `hooks.json`'s SessionStart entry, before any model
    turn. This is the whole fix: a `fired` event written by the HOOK, deterministically, is
    evidence a session existed that does not depend on the run's own logic ever getting a turn
    to call `--start`. MUST NEVER block a session — every failure is swallowed and reported to
    stderr only, the same contract `ensure_connectors.py`'s SessionStart hook already keeps."""
    try:
        # ⭐ dev #618 — nothing is bound: write nothing, say so once, exit 0 (`main()` returns 0
        # on every `--fired` path). Checked BEFORE `append` so the message is this hook's own
        # sentence rather than a swallowed JournalError, and so the refusal does not depend on
        # the choke point's wording.
        if is_unbound(root):
            say_unbound_once("journal.py --fired", root)
            return
        session_id, cwd = "", ""
        try:
            if not sys.stdin.isatty():
                payload = json.loads(sys.stdin.read() or "{}") or {}
                session_id = str(payload.get("session_id") or "")
                cwd = str(payload.get("cwd") or "")
        except Exception:                                 # noqa: BLE001 — stdin is best-effort
            pass
        append(root, {"event": "fired", "session_id": session_id, "cwd": cwd, "at": at})
    except Exception as e:                                # noqa: BLE001 — never block a session
        print("journal.py --fired: could not record (%s) — session continues unaffected" % e,
              file=sys.stderr)


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
            # dev #703 / public #155: the HEAD this run began on, so run_summary.footprint()
            # can count what the run COMMITTED. Omitted (never null) when git cannot be asked:
            # a `start` without it is the "not measured" case, same as every older `start`.
            # dev #820 / public #175: and the ENGINE that began it, from plugin.json -- refused
            # when unreadable (record_start), never written without.
            rid = record_start(root, args.start, at=at, start_sha=head_sha(root))
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
            for d in dead:
                tag = "  [reviewed — no write needed]" if d.get("disposed") else ""
                print("  %s  (%s)  %d note(s), %d gap(s)%s"
                      % (d["run_id"], d.get("at"), len(d["notes"]), d["gaps"], tag))
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
