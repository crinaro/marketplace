"""The run journal's tables: event kinds, reasons, pass kinds and phases, feed and role vocabularies, LinkedIn surfaces,
coverage states, and `JournalError`.

Capability module of `journal.py` (S4a, moved unedited). Its importers read these names through `journal` today (the
facade); new code imports them from here."""

import os
import re
from _root import STATE_DIRNAME


JOURNAL = os.path.join("data", "runs.jsonl")
# `outbox-lapse` is written by no engine since 0.93.0 (ADR-043 removed the 600 s send window); it stays a known event so a journal
# a 0.91.0/0.92.0 engine wrote still reads.
EVENTS = ("fired", "start", "note", "gap", "gap-closed", "end", "dispose", "swept", "probe",
         "triaged", "dispatch", "pass", "roles", "feeds", "drain", "mail-status", "readmit",
         "profile-schema", "network", "companies-raised", "outbox-lapse")

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
           "run-budget", "route-refused", "run-ended",
           # dev #834 (jobsearch 0.86.0, design-network-first.md 7): the network block (and the weekly review's network section) did not run
           # because the profile's 0.86.0 migration has not (the pin is absent): scope `jobsearch:network`, the line the script printed is in
           # the summary. Not `version-skew` (the scripts are NOT older than the prose; the profile is behind both) and not `other`: a
           # code exists to be counted, and "how many runs went without the network block, waiting on a migration" is the question.
           "migration-pending"}

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
# LINKEDIN_SURFACES themselves, but `tests/test_record_ledger_reads.py::TestLinkedinSurfaceVocabulary` pins both
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
