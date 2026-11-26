#!/usr/bin/env python3
"""
THE WRITE API for the mutable data files — one code path, a lock held in milliseconds.

WHY THIS EXISTS
---------------
The candidate, 2026-08-04: *"do we have the locks on the appropriate items? … if we had processes
that are reused (atomic) that will make sense but the challenge is a process putting something on
the queue for another."*

The candidate was right, and an audit made the reason precise. The repo already runs **two** concurrency
strategies and they were mixed up:

    APPEND + REPLAY   data/inbox.jsonl · data/pending_actions.jsonl · messages.jsonl
                      Lock-free BY DESIGN. Two workers append at once and replay resolves it.
                      **These have never conflicted.** The queue hand-off the candidate worried
                      about is the part that already works.

    WHOLE-FILE REWRITE  opportunities.jsonl (167 rows) · companies.jsonl · channels.jsonl
                      Every mutation was an AD-HOC `read all → mutate → write all`, invented
                      fresh by whatever session happened to be editing. **There was no write
                      API at all.**

**That is why the lock had to be coarse.** You cannot make a file safe when any session may
rewrite it however it likes; the only defence left is a global mutex held across the whole
edit. So the lock grew to cover a verify-and-write cycle lasting minutes, and the observed cost
was four false-RED gate sweeps in a single afternoon plus a duplicated LinkedIn record.

**This collapses the window.** One code path takes the lock, reads, mutates, writes atomically,
and releases — milliseconds, not minutes. The lock stops being a convention that every session
must remember and becomes correct by construction.

## ⭐ THE WRITE IS ATOMIC, AND THAT IS NOT DECORATION

Writes go to a temp file in the same directory and are `os.replace`d into place, which is atomic
on POSIX. A partial write to `opportunities.jsonl` would corrupt **167 records** — the entire
pipeline — and the old ad-hoc pattern (`open(p,'w')` then loop) had exactly that failure mode if
a session died mid-loop. Nothing recovers that but a git checkout.

## What it does NOT solve, stated plainly

Two workers editing the **same record** still serialise. This shrinks the contention window; it
does not make concurrent edits to one row commutative. If that turns out to happen in practice,
the answer is journaling the store the way the queues are journaled — but that is a data-model
migration and should wait for evidence, not a guess.

## ⭐ CALLING THIS MID-RUN: `--already-locked` (public #17 / dev #97)

The daily run takes the run lock itself at the top of its write phase and releases after the
commit. Called inside that window, this script used to try to take the same lock AGAIN — and
since the holder was the caller's own run, it waited out the full timeout for a release that
could never come. The observed result was the exact failure this API exists to prevent:
sessions gave up and hand-edited the JSONL.

So the contract is now explicit, and it does not touch the two-strategy design above:

    OUTSIDE a lock-holding run   plain call — takes the lock, writes, releases (milliseconds).
    INSIDE the run's write phase pass `--already-locked` — the write proceeds under the RUN's
                                 hold; nothing here takes or releases. Verified, not trusted:
                                 if nobody actually holds the lock the call is REFUSED, because
                                 a caller claiming a hold that does not exist is writing
                                 unprotected by accident.

A refused take now also diagnoses the self-deadlock instead of leaving a silent wait: the
default `--wait` is seconds (holders release in seconds by design), and the refusal says when
`--already-locked` is the answer.

## ⭐ COMPLETING AN ACTION RESOLVES ITS ASK, IN THE SAME WRITE (dev #133 / public #22)

An ask in data/asks.jsonl that carries `resolves_when` ("application" | "outreach") plus
`opp_id` has declared which recorded action answers it. When this API lands that action on that
opportunity, the ask is resolved under the same lock hold — one transaction, no drift window.
Asks without the declaration are never touched (guessing closes still-needed questions);
check_action_claims.py remains the detection backstop for them.

Usage:
    python3 scripts/record.py create <opp_id> '{"company_id":"...","title":"...", ...}'
    python3 scripts/record.py create <opp_id> '{...}' --from-item <capture-role item id>
                                              # + the sweep's parsed pay, posted, setting
    python3 scripts/record.py set <opp_id> stage screening
    python3 scripts/record.py set <opp_id> next_action_owner <candidate>   # e.g. your own name, lowercased
    python3 scripts/record.py set-in <opp_id> outreach contact_id=jane-doe outcome replied
    python3 scripts/record.py append <opp_id> research_log '{"date":"2026-08-04","note":"..."}'
    python3 scripts/record.py show <opp_id> [--json]       # the WHOLE record, untruncated (0.82.0, SH1)
    python3 scripts/record.py capture-batch --run <id> --link-only | --admitted [--deadline-s N] [--check]
                                              # card -> role, two phases, one write per store (0.82.0, dev #820)
    python3 scripts/record.py read-jd <opp_id> --run <id> --url <u|-> --via render|fetch|feed|ats-api|candidate
                                  --pay none|stated:<range> --setting "<text>" --location "<text|?>" --evidence "<quote>"
                                  [--body-sha1 <sha1>]   # --via fetch: the reader's read of a saved body (0.85.0, dev #838 / public #183)
    python3 scripts/record.py read-failed <opp_id> --run <id> --url <u|-> --via render --outcome <outcome> --evidence "<text>"
                                  --page-result chars=<N>|error=<text> [--pane "<tabs_context line>" --gate <word>
                                  --browser pane|extension --ready <word> --fallback-extension <code>]
                                              # 0.85.0: no page outcome without a page (dev #838). 0.90.0 (dev #858): `render-failed`
                                              # needs --pane and --gate (`pane_probe.py --gate`'s word; `--probe` is retired)
    python3 scripts/record.py read-batch --run <id> --fetch [--deadline-s N] [--check]
                                              # 0.85.0: never a GET to a LinkedIn address (RESIDUE ... (render): browser-first)
    python3 scripts/record.py read-batch --run <id> --fallback [--ids <opp id> ...] [--deadline-s N] [--check]
                                              # 0.85.0 (dev #840), automatic from 0.90.0 (dev #858): the logged-out posting read of a
                                              # LinkedIn role no browser could read (posting_fetch.py; not when the key is `off`)
    python3 scripts/record.py not-attempted <opp_id> [<opp_id> ...] --run <id> --via render --reason pane-hidden
                                  --pane "<the tabs_context line>" --tab-active yes|no --evidence "<the status line>"
                                  [--gate <word> --ready <word> --fallback-extension <code> --browser pane]   # 0.90.0 (dev #858)
                                              # 0.85.0 (dev #839 / public #182): the page was NEVER READ because the Browser
                                              # pane was hidden or the reader's tab stayed in the background. ALL ids or none.
                                              # read-jd / read-failed / not-attempted / read-batch are the ONLY writers of `jd_read`
    python3 scripts/record.py screened <opp_id>            # store the minimal screen it computes
    python3 scripts/record.py lean <opp_id> --lean pursue|pass|ask --line "<one line>" [--jd-file P]
    python3 scripts/record.py listed-pay <opp_id> --none-shown --pay-source candidate | --stated R[;R] | --estimate R[;R]
    python3 scripts/record.py posted <opp_id> --document-date D | --shown-age N | --ats-date D | --unknown
    python3 scripts/record.py board-sighting <channel_id> --company "<name>" --title "<title>" --url <posting URL>
                                              # one role seen on a job board (dev #765): the company is matched or
                                              # created, the role created or given a sighting, in ONE write
    python3 scripts/record.py channel-catalog add <entry> | --kind portfolio|curated|swept-board|alert-sender [--attach <channel_id>]
    python3 scripts/record.py channel-catalog take|keep <channel_id>
    python3 scripts/record.py source on|off <id> [--anyway]      # turn ANY job source on or off (dev #774): a board, an
    python3 scripts/record.py source list | keep-mine <id>       # alert sender, the LinkedIn job search, `company-feeds`
    python3 scripts/record.py fit --from-file <file>             # the researcher's `fit` (dev #861), one JSON line per role:
                                              # strict parser, `analyzed_on` stamped by the script, before the role is `ready`
    python3 scripts/record.py posting --from-file <file>         # EMPLOYER-POSTING lines (dev #776): the ONLY writer of an
                                              # opportunity's `employer_posting` (never argv, never a flag)
                                              # turn shipped catalog boards on (nothing is on by default), and settle
                                              # a board you edited that the catalog also changed (dev #769)
    python3 scripts/record.py raise-companies --run <id> [--on D]   # the look-into raise (0.86.0, dev #834): the ONE writer of `raised_on`
    python3 scripts/record.py company-status <company_id> active-target|watching|passed [--motivation 1-5] [--on D]
                                              # 0.86.0 (dev #834): the candidate's answer to "look into this company?"; the ONE writer
                                              # of a company's `status` + `status_on` (+ `motivation`, required for a target)
    python3 scripts/record.py company-later <company_id> [--on D]                        # 0.88.0 (dev #915): "ask me next week" -- writes
                                              # `later_on` only (a derived snooze on the Targets-to-review list, never a status)
    python3 scripts/record.py company-kind <company_id> employer|staffing|aggregator       # 0.88.0 (dev #915): the candidate's own word
                                              # for what the company is; written as `kind`, read before any name heuristic
    python3 scripts/record.py chat <person_id> --on D [--time HH:MM] [--title T] [--opp <opp_id>] [--touch <touch_id>]
    python3 scripts/record.py attended <commitment_id> held|no-show [--notes <path>] [--on D]   # attendance only (+ notes_ref)
    python3 scripts/record.py intro-offered <commitment_id> (--person <id> | --company <id>) [--on D]
    python3 scripts/record.py via <opp_id|app_id> --person <id> [--chat <commitment_id>]       # where a role came from; never inferred
    python3 scripts/record.py proposal <opp_id> [--scope "<text>"] [--rate 1500/day/USD] [--on D] [--note "<text>"]
    python3 scripts/record.py proposal-status <proposal_id> sent|accepted|declined|withdrawn|expired [--on D]
                                              # 0.86.0 (dev #834): a proposal to a prospective client of a fractional / interim / advisory /
                                              # contract engagement, in the `proposals` store beside `applications`. The candidate's own
                                              # record: nothing writes a proposal unattended. `status` and `date` have ONE writer
    python3 scripts/record.py suggest --store companies|plans|people --action set|create --target-id <id> --values '<json>' --ask "<q>"
    python3 scripts/record.py confirm <ask_id> [--set field=value ...]    # writes the suggested row and resolves its ask, ONE locked write
    python3 scripts/record.py decline <ask_id> [--why "<text>"]           # resolves the ask `declined`; the suggested row was never written
                                              # 0.86.0 (dev #834): the strategist SUGGESTS a target company, a plan or a person's cadence as an
                                              # ask; only the candidate's `confirm` writes the row. `suggest` writes the ask and nothing else
                                              # 0.86.0 (dev #834): a chat is a `kind: chat` commitment WITH a person; whether it
                                              # happened is a later `attended`, which only the candidate runs
    ... --file companies|channels to address the other stores. --dry-run to preview.
    ... --already-locked when the calling run already holds the run lock (see above).

Python 3.9+. Standard library only.
"""

import os
import sys

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root, looks_like_profile as _looks_like_profile
from recording import profile_paths as _paths
from recording.profile_paths import ENGINE_SCRIPTS
# The names other code reaches through `record` (the released, frozen migrations call `record.mint_app_id`,
# `supersede_listed_pay`, `validate`, `new_problems`; plays.py and reconcile.py the lock, the store I/O and
# `append_message`). Every other moved name is imported from its own recording/ module (S3).
from recording.row_checks import validate, new_problems
from recording.ids import mint_app_id
from recording.messages import append_message
from recording.reads import supersede_listed_pay
from recording.store_files import (
    LockError,
    take_lock,
    lock_is_held,
    lock_held_by_wrapper,
    release_lock,
    load,
    save_atomic,
    snapshot,
    restore,
    find,
)

# design-inbound-resolution.md §2 amendment D4 (surface pass 2026-09-14) — the same code
# `binding.py` uses (`EXIT_NO_PROFILE = 3`). Measured: on S6 (claude.ai/Home) or any surface
# with no resolvable profile, `ROOT` falls to the CWD (`_root.py`'s own fallthrough) and every
# store load then raised a bare FileNotFoundError — a traceback, not a refusal naming the
# actual problem. record.py now asserts a profile before ANY verb touches a store.
EXIT_NO_PROFILE = 3

_paths.bind(_profile_root())


# ---- dev #133 / public #22: completing an action resolves its ask, IN THE SAME WRITE --------
#
# The incident: an application was recorded on an opportunity while the ask requesting approval
# for exactly that application stayed open in data/asks.jsonl — two independent writes, one
# happened without the other, and a freshly regenerated dashboard rendered the answered question
# as still pending. check_action_claims.py DETECTS that drift after the fact; this PREVENTS it,
# but only where the linkage is declared: an ask carrying `resolves_when` ("application" or
# "outreach") plus `opp_id` states, machine-readably, which recorded action answers it. When
# record.py lands that action on that opportunity, it resolves the ask under the SAME lock hold,
# before release. An ask without `resolves_when` is deliberately untouched — guessing which ask
# an action answers is how a still-needed question gets silently closed, which is worse than the
# drift this exists to prevent.

# ── States & Views V1b (design §13/§15.3) — `touched` and `answered` ───────────────────────
#
# Both span TWO files (messages.jsonl + opportunities.jsonl) with no cross-file transaction —
# §3b's own correction, generalised: "the touch lands in messages.jsonl or outreach[], the
# flag on the opportunity row, two files and two writers." So each write here is TWO
# ORDERED, IDEMPOTENT appends under ONE lock hold (message first, §15.3 point 2) rather than
# one atomic multi-file commit: a crash between them leaves a message with no completing
# outreach[] row, which validate_data.py's own orphan check (MESSAGES_TOUCHED_SOURCE) names,
# and a RE-RUN with the SAME arguments finds the message already there (mint_message_id is
# deterministic over the call's own inputs) and writes only the missing half.

# ── dev #479 / public #114 — completing an outbound touch PROPAGATES ────────────────────────
#
# The defect: `touched`/`answered` wrote only the touch/message row and stopped — the
# recipient's `involvements` row was never created or upserted (a person just written to could
# still read as not-contacted, or have no row at all), and the opportunity's
# `next_action_owner`/`next_action_date` never moved off the candidate even though the action
# they were waiting on had just been recorded. `check_followups.py` tracked the touch
# correctly; the role-decision surface reads `opportunities`/`involvements`, not the touch
# store, so completed outbound work kept rendering as an open to-do. This is proposal #1 from
# the report — the smallest of the three, and the one that closes the write path itself rather
# than adding a second, independent detector for the gap it leaves.

# ── design-inbound-resolution.md §2 (ADR-029) — the shared inbound message writer ──────────
#
# THE ONE PUBLIC INBOUND WRITER. Before this, the only code that ever appended an inbound
# `messages` row was `reconcile.py --harvest`'s own private `existing.append(...)` +
# `write_jsonl` — no lock, no validator, no rollback. `append_message` is that write, promoted:
# `cmd_received` below is its CLI face (`record.py received ...`); `reconcile.py --harvest`
# calls this function IN-PROCESS instead of keeping a second copy of the append+validate+
# rollback dance (§2's own words: "one inbound writer path and one rollback").

# ====================================================================================================================
# jobsearch 0.82.0 (dev #820 / public #175; design-role-pipeline.md sections 3, 4, 8.1 and 17): THE ROLE PIPELINE'S VERBS
#
#   screen_inputs / _store_screen   the screen, with the inputs it was computed from (section 3.2)
#   read-jd / read-failed           the ONLY writers of `jd_read` besides `read-batch --fetch` and the migration
#   capture-batch                   the card -> role step, two phases, one write per store (section 4.1)
#   read-batch --fetch              the script-first JD read (section 4.3)
#   show                            the whole record, untruncated (section 7, SH1)
# ====================================================================================================================

# ---- no page outcome without a page (0.85.0, dev #838 / public #183; design-hidden-pane-reads.md section 6, 16 entry 23) ------
#
# #838's failure was INFERENCE: a reader that had read one page recorded `render-failed` for the rest of its chunk, so a role
# nobody opened was retry-stopped on another role's evidence. The rule (`jd-reader.md`): record a page outcome only for a page
# you opened and read in this dispatch, by itself. The script cannot prove a number is true; it can refuse to take a page
# outcome that names no page. PARTIAL, stated: after this, inference needs a FABRICATED figure, which turns a default into an
# explicit violation of the agent rule. A batch-level copy-paste refusal was considered and rejected (design 6.1: identical
# challenge pages have identical lengths on honest records).
#
#   read-failed --via render --outcome ...      --page-result    --pane      --gate   (0.90.0: `--gate` replaces `--probe`)
#   render-failed                               required         required    required (refused when the gate says not painting)
#   closed dead-link login-wall challenge
#     surface-cannot-read                       required         optional    optional (each stored when given)
#   no-url manual-board site-not-allowed        exempt           exempt      exempt (no page exists to measure: the pane refused
#                                                                              the site, the role has no address, or a board's
#                                                                              terms forbid opening it)
#
# `read-batch`'s own failure writes are exempt: they go through `_apply_failed`, not this verb, and carry the status line they
# measured. A `--via fetch|feed|ats-api` read-failed is not a page the reader rendered, so it asks for none of these.

# ---- capture-batch: the card -> role step (design section 4.1, 17 N6, N7, N17) ----------------------------------------
#
# `record.py capture-batch --run <id> --link-only | --admitted [--deadline-s N] [--check] [--already-locked]`
#
#   --link-only   before intake, over EVERY open `capture-role` item (quarantined included): an item that is a sighting
#                 of a known role is linked (its listings join the row; `linked` when the address was already known,
#                 `folded` when it is another listing of the same company + title) and closed `linked:<opp>`. Those items
#                 are sightings of known roles, not new roles, so they never consume intake. ALSO (jobsearch 0.86.0, dev #834,
#                 design-network-first.md 3.1): every open item whose company is NOT an `active-target` company is created as
#                 a role here, in the same locked write, before the plan: the sighting is RECORDED (the row is kept) and the
#                 role waits as `held-for-company`; it consumes no intake and is never read, screened or researched until the
#                 candidate targets the company. It needs no render route, because nothing is read.
#   --admitted    after `lifecycle.py --drain-plan`: for each role the run's `drain planned` event admitted, create it from
#                 its OLDEST item (company matched or made, `provenance: card`, `capture: {run, at, item, unverified?}`),
#                 close that item `created:<opp>` and every SIBLING item (same `lifecycle.role_key`) `linked:<opp>`, and
#                 store the provisional screen.
#
# Bounded time and ONE write: each store is loaded once per call and written once with the atomic replace (companies,
# then opportunities); the queue is append-only, so the closes follow. A kill BEFORE the first replace leaves every store
# as it was; a kill BETWEEN replaces leaves a state the rerun completes without a duplicate (an item whose role already
# carries `capture.item == <its id>` is closed `created:` and never made twice). `--deadline-s` stops BETWEEN roles, writes
# what is done, and releases the lock in a `finally`; an admitted item it did not reach is journaled in `pass capture done
# unreached=[...]`, which `lifecycle.drain_close` turns into the cause `deadline-reached`. A per-item fault refuses that
# role only: the item stays open, a `jobsearch:capture-item:<id>` gap is filed, and `drain_close` gives `capture-refused`.

# ---- read-batch --fetch: the script-first JD read (design section 4.3, 17 N7) -----------------------------------------
#
# `record.py read-batch --run <id> --fetch [--deadline-s N] [--check] [--already-locked]`
#
# For every role THIS run admitted (its own `drain planned` event: the opportunity ids, and the roles made from the
# admitted capture items) that is at progress stage `captured` or `reading`, oldest first, within `--deadline-s`:
#   1. the address `board_hosts.jd_read_plan` gives; none -> `read-failed --outcome manual-board` (every address is on a
#      manual-candidate board) or `no-url`, which settles the role to `your-read`;
#   2. one GET, with the feed poller's politeness (`feed_poll.MIN_INTERVAL_S` per host, `RETRY_AFTER_CAP_S` on a 429/503) --
#      NEVER to a LinkedIn address (0.85.0): such a role is `RESIDUE <id> (render): browser-first`, key on or off;
#   3. `feed_poll.parse_jobposting`: pay, setting and place all derivable -> a `read` attempt `via fetch` (evidence: the
#      sha1 and length of the body fetched HERE, never a model's word); `expired` -> `closed`; 404/410 -> `dead-link`;
#      401/403 -> `login-wall` (the status line as evidence); anything else -> NO attempt, and the role is in the render
#      RESIDUE, which `jd-reader` takes. A role the deadline did not reach is in the residue as `fetch-unreached`.
# It also re-screens every admitted role at progress stage `read` (read, but its screen is absent or stale), which needs no
# fetch. The network is touched BEFORE the lock is taken; the lock is held only for the one write of the opportunities
# store, which re-reads the rows and applies each result only to a role that is still unread.

# ---- read-batch --fallback: the posting fetch (0.85.0; automatic for everyone from 0.90.0, dev 858; design-browser-fallback.md 6) --
#
# `record.py read-batch --run <id> --fallback [--ids <opp id> ...] [--deadline-s N] [--check] [--already-locked]`
#
# `recording/fallback.py` does the work. The script is `posting_fetch.py` (imported lazily, there only): the request, the parse, the
# pacing, the cap, the key, the sandbox admission check and the notice row. THIS verb owns the decisions that read the stores.
#
#   1. the gate, once per call (`posting_fetch.auto_gate`): the key `off` or unreadable prints `FALLBACK: off (<why>)`; a host not
#      admitted, or a missing notice row, prints `FALLBACK: withheld (<code>): <remedy>`. NOTHING is sent; the code is stored;
#   2. eligible = admitted in this run, not read, a LinkedIn job-view address, not tried in this run, and the browser's LATEST attempt
#      (`_fallback_ineligible`) `pane-hidden` or `render-failed` for a key `on`, else not painting and carrying an extension code;
#   3. a saved body younger than 7 days is reused with no GET; otherwise one GET (`posting_fetch.Session`);
#   4. only `read` and `closed` are outcomes about the role; any other answer is stored as a `via fetch` `pane-hidden` attempt.

# ---- not-attempted: a browser read that could not HAPPEN (0.85.0; design-hidden-pane-reads.md section 5.4) ------------
#
# `record.py not-attempted <opp_id> [<opp_id> ...] --run <id> --via render --reason pane-hidden --pane "<tabs_context line>"
#                          --tab-active yes|no --evidence "<the status line>" [--dry-run] [--already-locked]`
#
# Appends ONE `pane-hidden` attempt (through `jd_read.make_attempt`) to EVERY id named, in one locked, validated,
# rollback-verified write: all the ids or none, so a refused id refuses the call. It records that the page was never read
# because the Browser pane was hidden or the reader's tab stayed in the background, which is NOT a failed read: it is an
# `environment`-class cause that never counts toward retry-stop (`lifecycle`). The evidence is `{text, pane, tab_active}`:
# `pane` is the PARSED state (`pane_probe.pane_state`, never the raw line), and `tab_active` is the reader's OWN WORD about
# its tab, which the name says (the engine cannot check it). The verb is refused unless the pane line said hidden or the
# reader says its tab is in the background: a displayed pane with the tab in front is a page that could have rendered.

# ---- raise-companies: the "look into this company?" raise (dev #834, jobsearch 0.86.0; design-network-first.md 3.3) --------
#
# `record.py raise-companies --run <run id> [--on YYYY-MM-DD] [--check|--dry-run] [--already-locked]`
#
# A job-board sighting at a company the candidate has not decided about yields one question, "look into this company?". The
# question is DERIVED (`your_move.classify_companies`); what is STORED is the act of raising it, `companies.raised_on`, because
# nothing else records which companies were already asked, and "at most `search.company_intake_per_run` companies are newly
# raised per run" (owner answers 6 and 7, 2026-11-12) needs that count. This verb is the ONE writer of the field:
#   1. the candidates are the qualifying companies (`your_move.company_candidates`) whose `raised_on` is absent, in its rank;
#   2. the first `search.company_intake_per_run` (default 10) get `raised_on = --on` (default: today), in ONE locked, validated,
#      rollback-verified write of data/companies.jsonl;
#   3. ONE `companies-raised` journal event is appended even when nothing was raised, so "ran and raised nothing" differs from
#      "never ran";
#   4. it prints `raised K companies to look into (N waiting)`.
# A run that already journaled the event raises nothing more (a retried step never raises a second batch). A profile whose
# 0.86.0 migration has not run, or that is pinned above this engine, is refused with that reason and nothing is written. The
# step decides nothing about a company: the candidate answers with `record.py company-status`.

# ---- the network-first verbs: company-status, chat, attended, intro-offered, via (dev #834, jobsearch 0.86.0) ----------------
#
#   record.py company-status <company_id> active-target|watching|passed [--motivation <1-5>] [--on YYYY-MM-DD]
#   record.py chat <person_id> --on YYYY-MM-DD [--time HH:MM] [--title "<t>"] [--opp <opp_id>] [--touch <touch_id>]
#   record.py attended <commitment_id> held|no-show [--notes <relative path>] [--on YYYY-MM-DD]
#   record.py intro-offered <commitment_id> (--person <person_id> | --company <company_id>) [--on YYYY-MM-DD]
#   record.py via <opp_id|app_id> --person <person_id> [--chat <commitment_id>]
#
# Each is a decision or a fact only the CANDIDATE knows (design-network-first.md 11: what stays manual), so none is ever called by an
# unattended run and none infers anything: the engine never decides that a company is a target, that a chat was held, whom an
# introduction was to, or where a role came from. Each writes ONE store (`companies`, `commitments`, `opportunities` or
# `applications`) in one locked, validated, rollback-verified write, `--dry-run` predicting it with the real validator, and each is
# refused on a profile whose 0.86.0 migration has not run (or that a newer engine upgraded), before anything is written:
#
#   company-status   writes `status`, `status_on` and, for a target, `motivation` TOGETHER (the one writer of `status`/`status_on`:
#                    `set <co> status ...` is refused naming this verb). An `active-target` without `--motivation` is refused.
#   chat             creates a `kind: chat` commitment WITH a person (a chat is with someone), optionally joined to the
#                    `meeting-booked` touch it came from. Writes no attendance: whether it happened is a later `attended`.
#   attended         writes `attendance` and `attendance_on` (and `notes_ref` when `--notes` is given) and NOTHING else.
#   intro-offered    appends one `{person_id | company_id, on}` entry to `intros_given`; an entry already there is not repeated.
#   via              writes `via_person_id` (and `via_commitment_id` with `--chat`) on a role or an application; refuses a chat that
#                    is with somebody else.

# ---- show: the whole record, untruncated (design section 7, SH1) -----------------------------------------------------

def main():
    # design-inbound-resolution.md §2 amendment D4 — asserted before ANY argument parsing or
    # store touch, for every verb (not just `received`): a surface with no resolvable profile
    # (S6; a maintainer checkout with no CLAUDESEARCH_ROOT pinned) must refuse loudly rather
    # than fall to the cwd and traceback on the first missing store file.
    if not _looks_like_profile(_paths.ROOT):
        print("⛔ REFUSED — %r does not look like a job-search profile (no config.json, no "
              "data/ directory). record.py writes a PROFILE's stores; pin CLAUDESEARCH_ROOT to "
              "one, or run this from inside one." % _paths.ROOT)
        return EXIT_NO_PROFILE

    from recording.parser import parse
    args = parse()

    # dev #834 (design-network-first.md 14.2, V1): a profile pinned ABOVE this engine is read-only to it, so EVERY verb checks the pin
    # before it dispatches, not only the 0.86.0 ones (`_network_gate`, which adds the "not migrated yet" half for those). Without
    # this, `set`, `append`, `decide`, `touched` and the rest wrote into a profile a newer engine had upgraded.
    import journal as _pin_journal
    pinned_ahead = _pin_journal.pin_refusal(_paths.ROOT)
    if pinned_ahead:
        print(pinned_ahead)
        return 3

    from recording.parser import bind_store, messages_refusal
    bind_store(args)
    refused = messages_refusal(args)
    if refused is not None:
        return refused
    from recording.role_first import flag_refusal      # 0.94.0: `read-jd --body` and `decide --no-target` are stubs until P3 and P5
    refused = flag_refusal(args)
    if refused is not None:
        return refused

    return _dispatch(args)


def _dispatch(args):
    """The verbs that make their own write (each `cmd_*` names its own stores, lock and validator): one
    explicit branch each, with the import it needs. Every other verb is a store verb on the shared write."""
    if args.op == "touched":
        from recording.touched import cmd_touched
        return cmd_touched(args)
    if args.op == "answered":
        from recording.answered import cmd_answered
        return cmd_answered(args)
    if args.op == "received":
        from recording.received import cmd_received
        return cmd_received(args)
    if args.op == "involve":
        from recording.persons import cmd_involve
        return cmd_involve(args)
    if args.op == "ats":
        from recording.boards import cmd_ats
        return cmd_ats(args)
    if args.op == "warm-lookup":
        from recording.boards import cmd_warm_lookup
        return cmd_warm_lookup(args)
    if args.op == "board-sighting":
        from recording.boards import cmd_board_sighting
        return cmd_board_sighting(args)
    if args.op == "channel-catalog":
        from recording.catalog import cmd_channel_catalog
        return cmd_channel_catalog(args)
    if args.op == "source":
        from recording.sourcing import cmd_source
        return cmd_source(args)
    if args.op == "posting":
        from recording.posting import cmd_posting
        return cmd_posting(args)
    if args.op == "fit":
        from recording.fit import cmd_fit
        return cmd_fit(args)
    if args.op == "capture-batch":
        from recording.capture import cmd_capture_batch
        return cmd_capture_batch(args)
    if args.op == "read-batch":
        from recording.fetching import cmd_read_batch
        return cmd_read_batch(args)
    if args.op == "not-attempted":
        from recording.fallback import cmd_not_attempted
        return cmd_not_attempted(args)
    if args.op == "raise-companies":
        from recording.network_verbs import cmd_raise_companies
        return cmd_raise_companies(args)
    if args.op == "company-status":
        from recording.network_verbs import cmd_company_status
        return cmd_company_status(args)
    if args.op == "company-later":
        from recording.network_verbs import cmd_company_later
        return cmd_company_later(args)
    if args.op == "company-kind":
        from recording.network_verbs import cmd_company_kind
        return cmd_company_kind(args)
    if args.op == "read-withdraw":
        from recording.role_first import cmd_read_withdraw
        return cmd_read_withdraw(args)
    if args.op == "chat":
        from recording.network_verbs import cmd_chat
        return cmd_chat(args)
    if args.op == "attended":
        from recording.network_verbs import cmd_attended
        return cmd_attended(args)
    if args.op == "intro-offered":
        from recording.network_verbs import cmd_intro_offered
        return cmd_intro_offered(args)
    if args.op == "via":
        from recording.network_verbs import cmd_via
        return cmd_via(args)
    if args.op == "proposal":
        from recording.proposals import cmd_proposal
        return cmd_proposal(args)
    if args.op == "proposal-status":
        from recording.proposals import cmd_proposal_status
        return cmd_proposal_status(args)
    if args.op == "suggest":
        from recording.suggestions import cmd_suggest
        return cmd_suggest(args)
    if args.op == "confirm":
        from recording.suggestions import cmd_confirm
        return cmd_confirm(args)
    if args.op == "decline":
        from recording.suggestions import cmd_decline
        return cmd_decline(args)
    return _store_verb(args)


def _store_verb(args):
    """The verbs that share ONE single-store write (recording/mutation.py): fields, show, create, set, set-in,
    append, decide, application-status, merge-person, link-sibling, unlink-sibling, read-jd, read-failed, the
    sourcing verbs and networking-closed."""
    from recording import mutation
    from recording.generic import cmd_show
    refused = mutation.preflight(args)
    if refused is not None:
        return refused
    target = mutation.target(args)
    if isinstance(target, int):
        return target
    rows, rec = target
    if args.op == "show":
        return cmd_show(rec, args.json_out)
    m = _mutation(args, rows, rec)
    if isinstance(m, int):
        return m
    return mutation.run(args, rows, rec, m)


def _mutation(args, rows, rec):
    """The one chain from a store verb to the function that describes its write (a `common.Mutation`, built before
    anything is touched). Returns the Mutation, or the exit code of a refusal already printed. The entry points a
    verb needs (`deferred`, `pipeline_index`, `your_move`, `profile`) are imported HERE, where the verb runs, and
    passed in: a package module never imports an entry point."""
    from recording import decisions, generic, mutation, persons
    from recording.parser import SOURCING_OPS
    from recording.reads import JD_READ_OPS
    if args.op == "create":
        _deferred_mod = _pidx = None
        if args.file == "opportunities":
            import deferred as _deferred_mod
            import pipeline_index as _pidx
        return generic.create_mutation(args, rows, _deferred_mod, _pidx)
    if args.op == "set" and args.file == "plays" and args.rest \
            and args.rest[0].startswith("params."):
        return generic.play_params_mutation(args, rec)
    if args.op == "set":
        return generic.set_mutation(args, rec)
    if args.op == "append":
        return generic.append_mutation(args, rec)
    if args.op == "set-in":
        return generic.set_in_mutation(args)
    if args.op == "decide":
        new_verdict = decisions.decide_verdict(args)
        if isinstance(new_verdict, int):
            return new_verdict
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import your_move as _ym
        import profile as _profile_mod
        return decisions.decide_mutation(args, rec, new_verdict, _ym, _profile_mod)
    if args.op == "application-status":
        return decisions.application_status_mutation(args, rec)
    if args.op == "merge-person":
        return persons.merge_person_mutation(args, rows)
    if args.op == "link-sibling":
        import pipeline_index as _pidx
        return generic.link_sibling_mutation(args, rows, rec, _pidx)
    if args.op == "unlink-sibling":
        import pipeline_index as _pidx
        return generic.unlink_sibling_mutation(args, rows, rec, _pidx)
    if args.op in JD_READ_OPS:
        return mutation.read_verb(args, rec)
    if args.op in SOURCING_OPS:
        return mutation.sourcing_verb(args, rec)
    # networking-closed
    refused = decisions.networking_closed_check(args)
    if refused is not None:
        return refused
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import your_move as _ym
    return decisions.networking_closed_mutation(args, _ym)


if __name__ == "__main__":
    sys.exit(main())
