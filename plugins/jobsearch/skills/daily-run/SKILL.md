---
name: daily-run
description: 'Run one job-search sweep: mailbox, LinkedIn, sourcing, state updates, dashboard, and a summary to the coordinator queue. Invoked by the scheduled routine, or on demand.'
---

# Daily run


## Binding — say which profile this session is acting on (dev #150)

```bash
~/.claude/jobsearch/run binding.py
```

One line, before the journal start: it names the profile and the evidence (`cwd`, `env`, or
`pointer`). Invoking this skill by name is itself evidence of intent, so `pointer` does not
refuse here — but it is announced, never silent. **`NO PROFILE` (exit 3) means stop and say
so.** When you later dispatch a jobsearch agent from a `pointer`-bound session, name the
profile root in the dispatch prompt — agents refuse pointer-only binding, and the prefix
`CLAUDESEARCH_ROOT=<root>` on their commands is how a legitimate dispatch binds them.

## ⭐⭐ THE VERY FIRST ACTION OF THE RUN — JOURNAL THE START

```bash
~/.claude/jobsearch/run journal.py --start daily
```

Keep the run id it prints. **This is the evidence that a session existed**, and it must be written
before any work, because its whole value is being there when nothing else is.

**Why (GitHub #7).** A scheduled run can advance `lastRunAt` while **never creating a session at
all** — no step executed, nothing written. From outside that is identical to a quiet run: the task
shows enabled, correctly scheduled, recently run, and every health check passes. It was caught only
because a human noticed the sweep's effects were absent and went looking for the session.

⚠️ **`lastRunAt` is not evidence that a run occurred.** The START record is. With it, four states
that were one become four — `fired` (public #65) is written by the `SessionStart` hook itself,
before any model turn, so it splits the old "no START" bucket into the two rows below it:

| | means |
|---|---|
| `lastRunAt` newer than any `fired` | **the run was never even invoked** — #65's hard case, now distinguishable from every row below |
| `fired` with no matching START | the hook ran; the model turn that should have called `--start` never completed (#65) |
| a START with no `end` | it began and died — `journal.py --unfinished` has what it recorded (#4) |
| START + `end`, footprint empty | it ran; a quiet day is normal |

**As the run learns things, journal them immediately** — `--note` for a finding, `--gap` with a
reason code for a sweep that could not finish. Batching them to the end is the bug those exist to
fix.

**And close it:** `~/.claude/jobsearch/run journal.py --run <id> --end` as the last action. An
unmatched start is read as a death, so forgetting the end reports a failure that did not happen.

## ⚠️ HOW SCRIPTS ARE RUN HERE

**Every engine script is called through the launcher, by bare name:**

    ~/.claude/jobsearch/run validate_data.py

`${CLAUDE_PLUGIN_ROOT}` is NOT set inside a Bash tool call, and each Bash call is a FRESH SHELL, so
a variable exported once does not carry. Resolving the engine per command worked but produced a
COMPOUND command with a QUOTED path — **which a permission allowlist cannot match, so every call
stopped for approval. An unattended run that stops for a prompt is a run that does not happen.**
The launcher makes each call a single unquoted command with a stable prefix; one allowlist entry
covers all of them, and the engine can move without editing any skill.

If the launcher is missing, reinstall it with
`python3 <plugin>/scripts/install_launcher.py`.



Model **Sonnet** · schedule from `~/.claude/jobsearch/run posture.py --cron` (never retyped here — this line said 07:00–16:00 while the generator emitted 07,09,11,13,15) · working folder = this repo.

Run the daily job-search check for the candidate. Read `CLAUDE.md` first — it governs everything.
All state lives in this repo. Be token-frugal.

## Three invariants

1. **STEP ORDER IS LOAD-BEARING.** Every mutation happens BEFORE the dashboard is generated, and
   the commit is genuinely LAST. The opposite arrangement once shipped: the dashboard and commit
   ran mid-run while later steps wrote `channels.jsonl` and `opportunities.jsonl`, so those writes
   were never committed and never published.
2. **REFERENCE STEPS BY NAME, NEVER BY NUMBER.** A numeric cross-reference goes stale the first
   time anything is renumbered, which already sent one "still do step N" pointing at the wrong step.
3. **USE A SINCE-LAST-RUN WINDOW** (check `log.md` for the last timestamp), never a flat 24h
   lookback — back-to-back runs (`posture.py --cron` sets how many a day) would each re-scan the
   same ground. **A quiet run is the NORMAL outcome at this cadence.** Say so in one line and
   stop. **Do NOT pad it with make-work** — no re-researching settled roles, no speculative
   outreach, no padding `data/asks.jsonl` because the summary felt thin. The value of frequency is
   catching a reply within one run interval, not multiplying the work. A late run (the app was
   closed) is a "catch-up run"; the window handles the gap.

---

## 0. CHECK THE LOCK — DO NOT TAKE IT

```bash
~/.claude/jobsearch/run runlock.py --status
```

**⭐ THE READ PHASE RUNS UNLOCKED, ALWAYS, even while the candidate has a session open.** Running
*alongside* them is the point. This step used to take the lock for the whole run, which serialised
every run against their session: an idle coordinator held it from 07:02 and nothing could write for
hours, costing that morning's run outright.

- **UNLOCKED or LOCKED — PROCEED either way.** Note who holds it.
- **Carry forward:** if it was held, expect state to have moved during your read phase. UPDATE
  STATE re-checks with `changed.py` before writing.
- **Degrade only if the mailbox is unreachable** (credentials `[MISSING]`): run
  `~/.claude/jobsearch/run watch.py --since 3` to queue what you can, and say so.

## 1. HYGIENE — before any new work

```bash
~/.claude/jobsearch/run push_init.sh                        # mint this session's push token (a no-op that says so under local-only — adr-012)
~/.claude/jobsearch/run migrate.py                  # finish any pending migration FIRST — the SessionStart hook does not fire on every surface, and a gate below run on unmigrated data reports findings the release already resolved (G11)
~/.claude/jobsearch/run check_stale_claims.py       # decayed claims
~/.claude/jobsearch/run check_followups.py          # silent threads
~/.claude/jobsearch/run check_sections.py           # ask/commitment invariants (dev #93)
~/.claude/jobsearch/run check_action_claims.py      # a hand-authored ask the data already answered (#43)
~/.claude/jobsearch/run check_sent_drafts.py        # a draft/letter already sent or submitted but still shown as pending on Your Move (advisory — retire the entry)
~/.claude/jobsearch/run validate_data.py            # schema · enums · referential integrity
~/.claude/jobsearch/run channels_due.py             # which sources are due
~/.claude/jobsearch/run check_rule_homes.py         # archived lessons still have a home
~/.claude/jobsearch/run check_dashboard_fresh.py    # dashboard behind its sources, or PUBLISHED view behind the repo (dev #133)
~/.claude/jobsearch/run check_engine_purity.py --advisory --budget-s 60   # engine files carry no profile data (advisory: a scan cut short at 60 s says so and exits 0, dev #526)
~/.claude/jobsearch/run check_pointers.py           # every pointer resolves to real data
~/.claude/jobsearch/run knowledge.py                # pipeline/kb/prep joins resolve; promotion debt; kb files due
~/.claude/jobsearch/run archive_preps.py            # preps for calls already held move to archive/call-preps/ (a script, never a step to remember; takes the write lock itself for the seconds of the move — a refusal moves nothing and the next run retries)
~/.claude/jobsearch/run check_dashboard_coverage.py # every record rendered, counted in a remainder, or terminal — and nothing outside its window
~/.claude/jobsearch/run presence_set.py --check     # the presence working set round-trips against its sources: every pane carries its file, no retired tab, no resolved item (ADR-028)
~/.claude/jobsearch/run resume_variants.py --check  # printed variant bullets trace to the presence/claims.md union (public #26)
~/.claude/jobsearch/run brief.py --check            # every open draft's brief verdict (Query or Citation C1) — counts by state; exits 1 on any NEEDS_HUMAN (a queued/WAITS_ON_SURFACE row is not a red close)
```

**Dispose of what they report BEFORE starting.** Verify every **system-state** claim against the
machine — read the plist, tail the log, run the script — and correct the tracker line in the same
pass. **`validate_data.py`, `resume_variants.py --check`, and `check_dashboard_coverage.py` gate**
— each exits non-zero on a real finding (`check_dashboard_coverage.py` on any gap: ARTIFACT
WITHOUT A LEDGER, LEDGER PREDATES FILTERS, ROUTER ROW UNRECOGNIZED, COUNT DISAGREES, and the rest
of its assertions). The block above still runs to completion either way — it is a list, not an
`&&` chain — so a non-zero exit is a report to act on, not a run that stops itself. The remaining
scripts are advisory and exit 0 so they cannot wedge an unattended run. `resume_variants.py
--check` is a no-op (exit 0) on a profile that has declared no variants — `presence/claims.md`
doubles as the single printed resume and owes this check nothing.

## 2. DRAIN THE QUEUE

```bash
~/.claude/jobsearch/run inbox.py
```

Findings a previous run queued rather than wrote, plus run-summaries. Work each one — the tool
prints what to do per kind — then `--ack` it. **A reply or a meeting artifact is the urgent kind;
those are what cost opportunities when they sit.**

## 2b. ⭐ DRAIN THE *REQUEST* QUEUE — work asked of this laptop (added 2026-08-05)

```bash
~/.claude/jobsearch/run deferred.py --claimable --run <this run's id>
```

(`--run` is this run's own id, so a `read-jd` item THIS run queues later in the triage step, because
it had no browser, is never offered back to it: dev #723.)

**`inbox.py` above carries findings TO the owner. THIS carries requests FROM the owner to this laptop, and it was WRITE-ONLY until today.** The run
prompt called `deferred.py --add` and nothing ever called `--claim`/`--done`, so every request
queued for the laptop sat forever — three were pending when this was found, including a LinkedIn
sweep queued when the browser died. **A request channel nobody drains is worse than none: the
asker believes the work is scheduled.**

For each item THIS worker can run (`--claimable` filters by capability, so only take what you can
finish): **`--claim <id>` → do the work → `--done <id>`.** If you claim and cannot finish,
`--release <id>` — *a claimed task that fails looks handled, which is the worst state.* Leases
expire in 45 minutes so a dead worker cannot strand work.

**Items needing a capability this worker lacks stay unclaimed and are REPORTED in the summary**
("2 items need chrome; this worker has none") rather than silently skipped — that visibility is
the whole point of `whoami.py` declaring capability instead of everyone attempting everything.

**⭐ A `chrome` item can also be WITHHELD even on a worker that HAS chrome** (design-linkedin-
runner-resilience.md §5.1, public #47/#96) — `--claimable` reads the pane lock, and while it
shows a recent render-stall or not-signed-in verdict, the item is printed under a `⏸ WITHHELD`
heading with the reason instead of being claimed. **Leave it; do not `--claim` a withheld item,
and do not re-run the pane probe yourself to "check" — a session whose own probe finds the pane
usable claims it normally, on a later pass.** This is the fix for the #96 loop: the old rule
keyed the skip to THIS session's run_id in skill prose, so the next scheduled session (a fresh
run_id) re-claimed the same still-stalled pane. The withholding is data, read fresh every run,
never a rule this file states.

**⭐ The owed LinkedIn pass is listed, never claimed (dev #481 / public #112).** A failed pass
queues ONE item (`deferred.py --add-linkedin-pass`, no row while one is pending), and `--claimable`
prints it as `⇢ LINKEDIN PASS OWED` rather than offering it: §4's pass satisfies it every run, and
`linkedin_sweep.py record` closes it once a pass reaches a list. Claiming it would run the pass a
second time. **A free-text `chrome` item whose work is a LinkedIn reply/inbox/search pass** (rows
queued before this release, by hand-written text) **is satisfied by §4's pass the same way: claim it
before §4, `--done` it after §4's `record` exits 0 or 3, `--release` it otherwise.**

**⭐ An item whose `what` starts with `brief.py --probe` (Query or Citation C1, §5.2) drains
differently: run the `what` VERBATIM, then apply the disposition it prints** — every account
`confirmed*` → exit 0 → `deferred.py --done <id>`; any account `unreachable`/`not-permitted`/
`not-configured` → exit 2 → `deferred.py --release <id>` (the item stays queued; a per-account
credential gap is common — this worker held a keychain entry for one account and not another).
Never call `brief.py --probe` a second time with different arguments to "help" — the printed
disposition is the authority, not a re-run.

## 2c. ⭐ PROBE HELD DRAFTS — Query or Citation C1 (new step)

```bash
~/.claude/jobsearch/run brief.py --probe --held --deadline-s 40
```

Every draft currently held `unverified-cold` (mailbox not yet checked on ANY surface) gets
probed directly here, on a surface that can reach a mailbox — this IS that surface for most
runs. On one that cannot (no keychain), it queues one deferred row per person instead
(`brief.py --probe contact:<id>`, deduplicated on `what` — §2b above is what drains those on a
worker that can). Report the split in the summary: "N probed directly, M queued for a
keychain-holding session, K not reached."

**⭐ The call is bounded, and a kill loses nothing already done (dev #712 / public #146).**
**Give this Bash call a timeout of 90 seconds (`timeout: 90000`).** `--deadline-s 40` is the
call's own deadline, deliberately below that timeout and below the shortest kill ever observed
on it (50 s): the call stops starting new probes at 40 s instead of being killed mid-batch. People
are probed in a stable (sorted) order; **each person's result is posted the moment that person is
probed**, so even a hard kill keeps everyone already done. If the deadline passes first, the
remaining people are not attempted and ONE journal gap (`email:held-probe`, reason `timeout`)
names how many were probed and how many remain; the next run's `--probe --held` reaches them and
closes the gap. **The call's last line states `Probed N … queued M … K not reached`: put exactly
those three numbers in the summary, and treat K above zero as an open gap, never as "all clear".**

## 3. GMAIL — two passes, and the order matters

**⭐ ONE MAIL CONNECTOR, the selected one — and the run says which it used.** `config.json`'s
`communications.mail_connector` is `gmail-multi` (the default) or `claude-gmail` (the claude.ai-managed Gmail
connector); `~/.claude/jobsearch/run mailboxes.py --status` prints it. Call **only** the selected
connector's tools, here and in every `inbox-scan` dispatch. A hook denies the other connector's
mail tools and names the selection: a denial is reported, never routed around. Under
`claude-gmail` the deterministic sweeps in this skill (`alert_sweep.py`, `meeting_check.py`,
`reconcile.py --ats`, `check_followups.py`) skip with one line saying why, and **a skipped sweep is a
gap in the run summary, never a clean zero**. The RUN SUMMARY (§13) names the connector the run
used.

**⭐ ATS status mail (rejections, receipts, interview invites) is NOT read here or by
`inbox-scan` — it is §7a′'s `reconcile.py --ats`, in the write phase**, because resolving it
to a specific application is a write (a status change), not a finding to report.

**a. ALERT SWEEP — run this DIRECTLY, do NOT delegate it.**
`~/.claude/jobsearch/run alert_sweep.py` (`--days 1`; widen if a run was skipped). It deterministically
finds board and aggregator digests across EVERY configured mailbox. Read them yourself and cross-check
against the pipeline — **the exclusion list is `verdict: pass` OR `status: passed`.** This is a
script because a model summary once reported these "silent" for three consecutive runs while the
digest sat in the mailbox: **a daily, predictable artifact is a query, not a summary.** A non-zero
exit means an account could not be searched — the result is PARTIAL, never a zero.

**3a. ⭐⭐ A GEOGRAPHY DISMISSAL IS A QUERY, NEVER A MEMORY (public #89, dev #355).** The daily run
once dismissed a WHOLE digest on the reasoning that its metro "was not a relocation destination" —
while that exact metro had been sitting in `config.json.geography.relocation.affirmative_destinations`
for days. The model answered from memory because nothing forced it to look. **For every digest row
you are about to screen out on geography, run the script and quote its verdict line — never write
your own geography reasoning from recall:**

```bash
~/.claude/jobsearch/run geo_screen.py "<the row's location, verbatim>"
~/.claude/jobsearch/run geo_screen.py "<the row's location, verbatim>" --type remote
```

Seven verdicts, each citing the config key it came from: `remote`, `commute`, `affirmative`,
`relocation-ok`, `outside-radius`, `out`, `unknown`. **`out` and `outside-radius` are the two
dismissals.** `outside-radius` (jobsearch 0.70.0, dev #729 / public #157) is a place the shipped
place table puts further from every commute anchor than any commute could reach, while relocation
is open and nothing named keeps it; a bare `City, ST` with no `--type` is screened as onsite, the
same way the minimal screen screens it. `unknown` (the profile's `geography` section is missing
entirely) is NEVER read as `out` — surface it in the run summary as a gap needing the owner's
config, and keep the row. Paste the script's own printed line (the `out: ...` or
`outside-radius: ...` sentence, citing `geography.relocation.open` or
`geography.relocation.keep_outside_radius`) into the digest-triage note as the reason — never a
paraphrase, never "not a relocation destination" typed from memory.

**b. ⭐ WRITE IT DOWN NOW — the JSON is the OPERATING STORE.** The daily run does not re-derive
state from the mailbox; it reads `data/*.jsonl` and writes changes **immediately**:

| finding | write |
|---|---|
| a **reply** | the touch's `outcome` + `responded_on` (`data/touches.jsonl`, ADR-031 B3), AND the message into `data/messages.jsonl` (`direction: inbound`, with `source`) |
| a **new person** | a `people.jsonl` entry with `id`, structured `email`/`linkedin`, and the touch's `person_id` pointing at it |
| a **meeting booked** | advance `stage`, add it to This Week |
| **the candidate reports sending** | the touch AND the draft body moved into `data/messages.jsonl` (`direction: outbound`) |

**Never leave a change for the weekly audit to find.** A reply once sat unrecorded for 11 days
while the knowledge was already in the repo, written in one place and not the other.

**⭐ READ THE WHOLE THREAD, BOTH DIRECTIONS — the candidate may have ALREADY REPLIED (added 2026-08-05, per
the candidate: "enhance the daily process to also look at additional items in an email thread,
responses I may have already made").** An inbound reply is not automatically an open loop. Before
you treat one as needing a response, **fetch the full thread and look for a message the candidate
sent AFTER the inbound** — search the candidate's sent mail in that thread (`from:<candidate's address>` on the same
subject, or `in:sent`/`in:anywhere`). Two outcomes:
- **They already replied** → record BOTH directions into `data/messages.jsonl` (the inbound AND their
  reply, each with its `source` uid), set the touch to reflect the latest state, and **do
  NOT queue a needs-response or spawn a drafter** — the loop is closed. Note "candidate already
  replied" in the run summary so the candidate knows it was seen, not missed.
- **The last word is theirs** → proceed to §7b (queue + draft).
This happened 2026-08-05: Ashford Search's <an employer> decline landed overnight and the candidate replied ~1 hour
later; the scan saw only the inbound and nearly drafted a response to a thread the candidate had already closed.

**c. HUMAN/MEETING PASS — delegate to `inbox-scan`.** New recruiter/human inbound, thread replies,
and — swept FIRST per the hard rule — meeting artifacts. **It is NOT trusted for the digests**
(pass a owns those); brief it so it neither re-reports nor skips them.

## 4. LINKEDIN — delegate to `linkedin-runner`

**⭐ CHECK THE BUDGET BEFORE DISPATCHING (dev #292 — this is its first skill caller; ADR-031
§17 named the gap: no skill consulted `posture.may()`):**

```bash
~/.claude/jobsearch/run posture.py --may linkedin --run <id>
```

A LinkedIn pass is unattended browser work like any other spend this posture gates — **exit
non-zero means this posture does not permit it unattended; skip the dispatch, say so in the
summary, and do not improvise a lighter-weight substitute.** `--run <id>` is not optional here:
it is what lets `posture.py` record a `REFUSED` verdict as a `pass … phase refused` row (#87) —
omit it and the refusal is only a line in this run's transcript, gone the moment the session
ends.

**⭐⭐ THE ROW IS WRITTEN TWICE, AND ONLY THE SECOND COUNTS (design-script-first.md §2 item 2,
dev #483 / public #110 part 2).** A permitted pass is not journaled by the gate check above —
only a refusal is. So, once `posture.py --may linkedin` exits 0:

1. **Write `dispatched` in the same breath as the dispatch itself** — the call immediately
   before invoking `linkedin-runner`, never batched with anything else:
   ```bash
   ~/.claude/jobsearch/run journal.py --run <id> --pass linkedin --phase dispatched
   ```
2. **After `linkedin-runner` hands back**, translate its own per-surface REACHED / UNREACHABLE /
   NOT-ATTEMPTED report (the `SURFACE` lines of its SWEEP block, `linkedin-runner.md` §"What you
   hand back"; `connections` is a token like the rest) directly into the `returned`
   row — the SAME tokens, not a summary of them:
   ```bash
   ~/.claude/jobsearch/run journal.py --run <id> --pass linkedin --phase returned \
       --reached <tokens reported REACHED> --unreachable <tokens reported UNREACHABLE> \
       --not-attempted <tokens reported NOT-ATTEMPTED> \
       --jobsearch reached
   ```
   **`--jobsearch` is the runner's own report on its JOB SEARCH capability, and it is always
   passed (dev #692 / public #140, R4): `reached`, `unreachable` or `not-attempted`, exactly as
   the runner reported it.** It is a separate token from the five reply surfaces, so
   a pass that only searched jobs never spends the day's quota. `reached` means the pass owes a
   `ROLES v1` block (below); `unreachable` and `not-attempted` owe none. `journal.py --end` gaps a
   `reached` pass that has no accepted block, and the run summary prints `ROLES NOT ACCOUNTED`.
   **The quota only counts a `returned` row with at least one REACHED token** — a hand-back
   where every one of its tokens came back UNREACHABLE or NOT-ATTEMPTED still gets a
   `returned` row (it read *something*, even if nothing landed), it simply carries an empty
   `--reached` and does not consume the day's budget. A pass that never returns at all (the
   agent crashed mid-run, or ended before its own §"What you hand back" step) is a *crashed
   pass*, never papered over with a hand-written `returned` row — `journal.py --may
   linkedin`/`--passes` names it on its own line.

**⭐⭐ EVERY ROLE A PASS SEES IS ACCOUNTED FOR, BY SCRIPT (dev #692 / public #140, dev #489 /
public #102).** The JOB SEARCH result is a `ROLES v1` block in the runner's hand-back file, never a
prose count. Right after `linkedin_sweep.py record` below, and once per returned pass:

**Check it first, then accept it (dev #707 / public #151).** `--check` parses the hand-back with the
same code, prints every faulty line with its line number and the rule it broke, then a `verdict:`
line, and writes nothing:

```bash
~/.claude/jobsearch/run deferred.py --add-roles <the hand-back file's path> --run <id> --surface linkedin-jobsearch --check
~/.claude/jobsearch/run deferred.py --add-roles <the hand-back file's path> --run <id> --surface linkedin-jobsearch
```

Every `ROLE` line ends as **captured** (the runner already wrote the record; its opp id is printed
with a `SCREEN` line), **known** (already in the pipeline, active or passed), **carried** (one
`capture-role` queue item per role, `ref` the canonical URL), or a **per-role gap**. The exit code
says which of three things happened, on `--check` and on the real call alike: **0** clean; **4**
accepted with line faults (every valid role was recorded, and each faulty line, or a `SEEN` count
that disagrees with the lines, is a `partial-results` gap of its own: a line fault never discards
a valid role); **3** refused whole, only for a structural fault (no block, two blocks, a bad
header, a `run=` or `surface=` that is not this call's, no `END` line): nothing was written but one
`partial-results` gap. On 3 or 4 the raw hand-back is kept at
`<profile root>/.jobsearch/handbacks/roles-<run>-<surface>.md` and the output names it; the defect
in the hand-back is reported, never patched by hand. In the write phase (§7) each carried role gets
`record.py create … --from-item <item id> --already-locked` and the minimal screen, then `deferred.py --settle` closes
the items that now have a record; whatever is not captured stays a pending row, listed by
`--claimable` on every posture, so the run cannot end on "N seen, top few captured".

**One requisition listed once per city is ONE decision (dev #728 / public #158, jobsearch 0.70.0).**
Several `ROLE` lines with the same company and title under different URLs are one role: the first is
the item (or the row it already has), and each other is a **sibling listing**, printed
`SIBLING <url> (<place>) -> <item id>` (joined to the queued item) or `KNOWN <id> (company + title,
active|passed) +listing <place>` (a sighting carrying that place, added to the row, passed rows
included). Count them from the `ROLES RECORDED` line (`N sibling listing(s) linked`); never create a
row per city. `POSSIBLE SIBLING <url> ~ <id>` is a near miss (the titles match once a trailing place
is dropped): it is NEVER merged, only worth a look. **`NEARER LISTING of passed <id>: <place>
(<state>)`** means this listing is closer than anywhere the PASSED role was listed, so it is NOT
linked and its item stays claimable: read it as a fresh decision (`record.py create … --force`
records the pair as different). A role is screened at its most favourable listed place. A
pre-0.70.0 duplicate row screens `DUPLICATE of <id> …; fold with record.py link-sibling <dup> --into
<id>`: fold it by hand, and undo a false merge with `record.py unlink-sibling <id> --url <the
listing's URL> --to <the row it belongs to>` (nothing is deleted either way).

**The weekly wide re-scan is the same pass, not a second one (dev #489 / public #102, R5).** The
worklist's `JOBSEARCH` line says which window this pass runs: `window=daily f_TPR=r86400`
("Past 24 hours") on an ordinary day, `window=wide f_TPR=r604800` ("Past week", the full title
set) while the weekly re-scan is due. Paste it with the rest of the worklist and the runner reads
its window from it. LinkedIn's two UI buckets are the only windows; nothing is computed. A wide
pass counts only when every requested geography had a reached, window-applied query. A day the
pass is refused (`minimal` posture, the quota, no browser) is not made up: wide stays due, and the
summary prints `wide re-scan due since <date>, not run (<reason>)`. The summary lines come from
`run_summary.py`, not from you: `sourcing (daily)`, `wide re-scan: N re-surfaced`, `ROLES NOT
ACCOUNTED`.

**⭐⭐ THE RESPONSE SWEEP IS DRIVEN BY THE OUTREACH STATE, NOT BY UI SURFACES (2026-08-04, per the
candidate: "if our process has me sending messages & connection requests, it should be checking
linkedin messages").** The old instruction said "reply check on open outreach + message inbox,"
and a hiring-line response from a 3rd-degree contact sat unseen because it did not live
in either place — a 3rd-degree recipient can REPLY TO AN INVITATION WITHOUT ACCEPTING IT, and
that response lands on the invitations/message-requests surfaces the sweep never opened.
**Mail is no backstop: the candidate's mailbox receives NO LinkedIn notification emails** (verified
2026-08-04 — zero in 2 days despite two known acceptances), so the browser pass is the ONLY
detector for LinkedIn events.

**⭐⭐ THE WORKLIST GOES IN AND THE VERDICT COMES OUT, BOTH BY SCRIPT (dev #484 / public #109, dev
#488 / public #105).** The check-list is built from the data by a script, not by the runner:

```bash
~/.claude/jobsearch/run linkedin_sweep.py worklist --run <id>
```

**Paste its block, verbatim, into the `linkedin-runner` dispatch prompt: the runner's reply sweep
works ONLY from that list and never explores.** It holds one `WATCH` line per open touch (every
`data/touches.jsonl` row with medium `linkedin-*` and `outcome` in `awaiting`/`accepted`), the four
list surfaces to read and how far back to read each, and a `THREAD` line only where a thread URL is
on record. **A routine pass never visits a profile:** the old profile → Message walk is retired,
because acceptance is read POSITIVELY from the recency-sorted Connections list, never inferred from
absence on a truncated list. The runner writes its result as a SWEEP block in its hand-back file
(`linkedin-runner.md` §"What you hand back"). **After it returns, the verdict is a script too:**

```bash
~/.claude/jobsearch/run linkedin_sweep.py record --run <id> --file <the hand-back file's path>
```

Its printed lines are the verdict, and they are the ONLY source for what you write below:
`ACCEPTED` / `REPLIED` (act on them), `NO CHANGE` (silence, concluded only for a person every list
covered; it also journals the look as a probe, so a later brief cites it instead of dispatching
again), and **`!! INCOMPLETE COVERAGE` (a list showed part of what it holds; the person is NOT
concluded, a `partial-results` gap is filed, and "still pending" is never written by you).** Exit
**0** every person concluded · **3** some not concluded (the pass still counts) · **2** the
hand-back was refused, nothing journaled, and the pass stays owed · **4** the pass failed (a
reserved first line, or no list surface reached) and the owed item is queued. **`record` closes the
owed LinkedIn pass row only when at least one list surface was REACHED.** Job search and
notifications are not measured by it and do not gate closure; report them as before. A line it
refuses is a defect in the hand-back to report, never to patch by hand.

**The one-off degree check** (owner decision 2026-10-03): before drafting a message that is NOT a
first connection note to a person with no LinkedIn contact on record, dispatch the runner with
`linkedin_sweep.py worklist --run <id> --one-off contact:<id>` (it holds that person's profile URL
and nothing else), then `linkedin_sweep.py record --run <id> --one-off contact:<id> --file <path>`.
Its visit is journaled; a failed or garbled hand-back is reported to the owner and **never queues
the daily pass**. A first connection note needs no one-off.

**The sweep covers, in order:**
1. **INBOX FIRST**: the **Focused AND Other inbox tabs**, then **message requests**, then
   **Connections** (newest first), and **Sent invitations LAST — it truncates.** Measured at
   10 of 20 (08/02) and 10 of 25 (08/04): it caps near ten while the pending list grows, so the
   share it hides widens with every send. **Absence from Sent Invitations proves nothing.** A
   hiring-line reply was invisible there on 08/04 while sitting plainly in the inbox. An invitation REPLY without an accept is a first-class response — it is how a senior
   3rd-degree contact answers without connecting.
2. The notification bell (reported, not measured by `record`).
3. Anything `record` reports goes into the run's incremental write (`outcome`, `responded_on`,
   `messages.jsonl` with the verbatim text) — not just the summary.

**⭐ The sourcing step is conditional on the active search plan's `outcomes` (ADR-031 B4, design
§13).** Read `plans.jsonl` once at the top of the run: job search runs when the active `search`
plan's `outcomes` includes `role` or `contract`, and is **skipped — say so in the summary** —
when it names only `access` (a run working the network toward introductions, with no role search
live). Mailbox and LinkedIn reply sweeps above run regardless: a reply from a person is the
network working, whichever outcome the plan serves.

Job search since the last successful run (remote AND on-site/hybrid within the commute anchor —
the JOB SEARCH capability covers both), contact-path lookup for any new appealing role.
**Screen every candidate role's location with `~/.claude/jobsearch/run geo_screen.py
"<location>"` before deciding it is out of scope — §3a's rule applies here too: only its own
`out:` line dismisses a role, never a from-memory read of the metro.**

**If it reports BROWSER UNAVAILABLE or NOT SIGNED IN**, flag it at the top of the summary, tell the candidate to run **`/jobsearch:linkedin`** (a lapsed session is the commonest cause and they must sign in directly), **and QUEUE the work:**

<!-- pass-branch:begin -->
```bash
~/.claude/jobsearch/run deferred.py --add-linkedin-pass
```
<!-- pass-branch:end -->

The text is built by the script and a pass already owed adds **no second row** (dev #481 / public
#112): never write the queue text yourself, and expect the runner's own failure step to have queued
the same item already — adding it again is harmless by construction. `record` queues it too when it
reads a failed hand-back, and closes it once a pass reaches a list.

**Do not skip the queue step.** That flag used to be prose in a run summary and nothing else — no
later run recovered the work, and a skipped pass looked identical to one that found nothing.
Degrading gracefully was never the problem; forgetting was. **Expect this to fire rarely** — if it
fires repeatedly, run `~/.claude/jobsearch/run wake_chrome.sh` and check macOS Automation access for the app
before assuming a new fault (`docs/architecture.md` §3d).

**Weekly (first run on/after Monday, per `log.md`):** dispatch `board-sweeper` for the non-LinkedIn sourcing pass — boards, aggregators and employer career pages, each reached by its configured route.
**Write the dispatch as a script row, in the same breath (dev #692 / public #140, R3):**
`~/.claude/jobsearch/run journal.py --run <id> --pass board --phase dispatched`. The missing-ROLES
check keys on that row, never on a folded `dispatch` row. When the sweeper hands back, run
`~/.claude/jobsearch/run deferred.py --add-roles <hand-back file> --run <id> --surface board --check`
and then the same call without `--check`, the same gate, the same outcomes and the same exit codes
as the LinkedIn pass above; the sweeper no longer cross-checks the pipeline itself.
**Check `~/.claude/jobsearch/run channels_due.py` rather than assuming anything is due** — anchor-employer
career pages moved to MONTHLY, and two job boards were RETIRED after a zero-yield trial. Do not
re-add a retired channel.

## 5. RESEARCH — delegate to `opportunity-researcher`

**⭐ A POSTURE LIMITS HOW OFTEN, NEVER HOW MUCH (dev #692 / public #140).** Only the RESEARCH
agent is gated by posture. Capturing every role the run found, and screening it (§7's minimal
screen), happens under every posture, `minimal` and `economy` included. Check the gate before
dispatching:

```bash
~/.claude/jobsearch/run posture.py --may research
```

- **Exit 0** → dispatch `opportunity-researcher` as below, up to `max_agents_per_run`. Every new role
  over that cap gets `~/.claude/jobsearch/run deferred.py --add-research <opp_id>`.
- **Exit 1** → dispatch nothing, and queue each new role that needs research with
  `~/.claude/jobsearch/run deferred.py --add-research <opp_id>`. It is a script form: fixed text,
  `requires: research`, idempotent while one is pending. It is not a failure — §2b's `--claimable`
  lists it under `HELD BY POSTURE` and it drains on the first run whose posture permits research.
  Say "N research items held by posture" in the summary.
- **A free-text research row queued before this release** (no `requires`) is `--done` once its
  `--add-research` replacement exists; the old row cannot drain, and rewriting it is a migration.

**⭐ A RUN IS UNATTENDED BY DEFAULT (owner decision R2).** The rules above apply to every run
unless it was started with the explicit attended form, `/jobsearch:daily-run attended`. Only that
form passes `--attended` (`posture.py --may research --attended --run <id>`, `deferred.py
--claimable --attended`), which lifts the research and drafting gate and journals a note saying
so. **Never infer attended** from a missing scheduler line, an `ENGINE=` marker or the time of
day: Claude Code documents no in-session marker that tells a scheduled session from a typed one,
and the safe reading of an unmarked run is that nobody is watching. `--attended` never lifts
`linkedin` (§4's gate is the browser and the quota, not a posture word).

For every genuinely new role, in one batch. It finds the posting on the company's own site/ATS
(not the alert snippet), reads the full JD, and researches the company. Fold its findings into the
role's record — comp, scope, reporting line, company snapshot, and any discrepancy versus the
alert. **Skip roles already excluded or already researched.** An alert's title/company/comp snippet
alone cannot support a fit judgement or a draft.

**⭐ ANY ROLE THAT BECOMES A PURSUIT GETS A `fit` ANALYSIS** (`fit.requirements[]` — run
`~/.claude/jobsearch/run record.py fields --file opportunities` for the exact shape):
requirement → aligned/partial/not-aligned/unknown, each with cited evidence and a `pitch_line`.
**Every `unknown` carries a targeted question, and a dated one carries `act_by`.** Run
`~/.claude/jobsearch/run fit_report.py --gaps` and put the open questions on Your Move — the answers file
into `presence/projects.md`, `presence/claims.md`'s addenda, or `kb_<company>.md`, so the NEXT role's analysis starts
fuller. **The resume is deliberately incomplete; this is the loop that closes that gap while a live
role makes it concrete.**

## 6. NETWORK CADENCE

From `outreach/network.md`: check warm-intro deadlines. If fewer than 2 network actions in the last 7 days
(per `log.md`), propose the next 1–2 with drafts.

**Any draft must be saved IN FULL to `outreach/drafts.md`** (its header carries the entry layout — **the
body MUST be `> `-blockquoted or it publishes EMPTY**; the meta lines the engine parses — `**Status:**`,
`**Medium:**`, `**Blocked until:**` — are specified in `outreach-drafter`, and **a medium change rewrites
the `**Medium:**` line, never `**Status:**` prose**). A one-line summary elsewhere is not enough;
**the candidate reads the full text off the published dashboard, not the transcript.** Cover letters go to
`applying/cover_letters.md` via **`cover-letter-writer`** — a different artifact with different length,
constraints and failure mode.

**⭐ WARM-PATH ON EVERY APPLICATION.** An ATS application is NOT done until an inside-human touch
is attempted OR explicitly ruled out. The evidence: 11 ATS applications produced 9 auto-acks, 1
rejection and ZERO human contact, while warm outreach replied at 50% and produced every advancing
conversation. So for each role applied to, have `linkedin-runner` run a contact-path lookup and,
if a real path exists, draft the touch; if none exists, say so in the row. **Never fabricate a
connection.** This is per-application, not weekly.

---

## 7. UPDATE STATE — ⭐ THE WRITE PHASE BEGINS HERE

```bash
~/.claude/jobsearch/run changed.py --as daily
~/.claude/jobsearch/run runlock.py --take "daily $(date +%H:%M) write" --wait 120
```

- **STATE CHANGED** → **re-read the files you are about to edit.** Your reads are as old as this
  run is long. Acting on a stale read is how a run re-drafts outreach for a reply that already landed.
- **`--wait 120`** blocks rather than discarding the run. Holders release in seconds now.
  **Do NOT downgrade here** — the research is already done, and throwing it away is the failure
  this design removed.
- **Still refused, or reported STALE** → a session died holding it. `--steal`, and say so.

**7a′. ⭐ ATS STATUS SWEEP (design-inbound-resolution.md, ADR-029/030) — run it DIRECTLY, never
delegate:**

```bash
~/.claude/jobsearch/run reconcile.py --ats --already-locked
```

Deterministic — sender-domain identification, three-tier resolution (req-id/URL/company),
first hit wins, a tie asks rather than guesses. A tier-1/tier-2 hit (the ATS's own key
appeared in the mail) is applied; a tier-3 name match is proposed as an ask instead
(`ats.parsed_status`, default `receipt-grade`). **Read its plan lines into the run summary** —
what applied, what was proposed, what was withheld under the per-run ask cap. Every write is
under THIS run's own lock hold (`--already-locked`); invoked with the lock unheld it degrades
to plan-only and exits 2 — never a hard failure, never a half-written store.

**⭐ USE THE WRITE API — do not hand-edit the JSONL. A brand-new row is `create`, not an edit.**

**⭐ `--already-locked` on every call in this phase.** This run took the run lock two commands
ago, and record.py normally takes it again — waiting on your own hold never ends (public #17).
The flag says "write under the run's hold"; record.py verifies a hold actually exists and
neither takes nor releases anything.

**`plan_id` is required on every live opportunity (ADR-031 B4, design §17).** `create` derives it
for you when exactly one `search` plan is active (`plans.subject_kind: search`, sourcing
`role`/`contract`) — leave it off the payload. **With more than one active search plan, name
which one sourced this role:** `--plan <plan_id>` on the `create` call, or the write is refused
naming the ambiguity.

**⭐ public #83 rule 1 — a sighting from a URL-bearing channel (`job-board`/`aggregator`, board-
sweeper's and linkedin-runner's own channels) must carry `source_url`, captured NOW.** Put it
directly in the `sightings[]` entry on `create` (`{"channel_id":"...","seen_on":"...",
"source_url":"<the posting's own URL>"}`), or pass `--source-url <url>` on an `append ...
sightings` call so it never has to be hand-embedded in the JSON. `record.py` refuses a new
URL-bearing sighting that omits it, naming the channel and the rule — the link is free to grab
this moment and effectively unrecoverable once the posting comes down. (A recruiter-sourced
sighting, or one on a role an application already backs, is unaffected.)

```bash
~/.claude/jobsearch/run record.py create <opp_id> '{"company_id":"...","title":"...","status":"backlog","stage":"sourced","verdict":"undecided","jd_url":null,"location":{...},"sightings":[{"channel_id":"...","seen_on":"...","source_url":"..."}],"next_action_owner":"..."}' --already-locked [--plan <plan_id>]
~/.claude/jobsearch/run record.py set <opp_id> stage screening --already-locked
~/.claude/jobsearch/run record.py set-in <opp_id> outreach contact_id=<cid> outcome replied --already-locked
~/.claude/jobsearch/run record.py append <opp_id> sightings '{"channel_id":"...","seen_on":"..."}' --source-url "..." --already-locked
~/.claude/jobsearch/run record.py append <opp_id> research_log '{"date":"...","note":"..."}' --already-locked
```

It re-reads inside the lock, writes **atomically** (`os.replace` — a partial write would
destroy every record in the file), and validates. **A full cycle is ~0.2s.** Ad-hoc
`read-all / write-all` is what forced the lock to be coarse in the first place. **`--dry-run`
describes the change without touching anything.** (Outside a lock-holding run — an interactive
one-off — drop the flag and record.py takes and releases the lock itself, in milliseconds.)

**⭐ SCREEN EVERY ROLE CAPTURED THIS RUN, UNDER EVERY POSTURE (dev #692 / public #140).** After
each `create` above, and for any role that came in already created, run the scripted minimal
screen. It is zero-token, never reads posture, and covers the comp floor, the duplicate/passed
check, geography and an advisory title rule:

```bash
~/.claude/jobsearch/run profile.py --minimal-screen <opp_id> [<opp_id> ...]
```

Name every role captured this run in ONE call: each role prints its block, and with several ids
the last line is a summary (`MINIMAL SCREEN SUMMARY n screened · keep · remove (geo, comp, passed)
· review · commute: outside, near, unresolvable`) — quote that line in the run summary instead of
tallying by hand (dev #729 / public #157: a tally kept by hand said "75 screened, 0 removed"). A
`PLACE TABLE MISSING (...)` line means the distance was NOT checked for those roles: report it as
a gap, never as a clean screen.

Read each block's `VERDICT` line. **`VERDICT remove:<rule>`** → record the decision, which puts the role on the
exclusion list: `~/.claude/jobsearch/run record.py decide <opp_id> pass --why-kind other --why
"minimal screen: <rule>" --already-locked` (the `--why` pair is required when the engine's own
suggestion would have been `pursue`, so pass it every time), and name the rule in the run summary.
**`VERDICT review:<rule>`**
→ keep the role and say which rule asked for a look (an advisory title rule never removes a role).
**`VERDICT keep`** → nothing to do.

**⭐ CAPTURE WHAT THE PASSES CARRIED, THEN SETTLE (dev #692 / public #140).** `deferred.py
--add-roles` (§4) left one `capture-role` item per role the pass saw and did not capture. Each is
`--claimable` on every posture (no `requires`). Claim it, `record.py create … --from-item <the
item's id> --already-locked` from the item's URL, screen the new role as above, then `--done` the
item. **`--from-item` is what carries the sweep's pay, posting date and work setting onto the new
role** (it copies the item's parsed `listed_pay`, `posted`, `location.declared` and the card's
`location.primary`; a slot the sweep marked `?` stays absent). **Omit `location.primary` from the
JSON** (the script copies the card's text; a different one is refused, one value stated once), and
**when the item's setting is `none stated`, omit `location.type` too**: at a concrete place the
script records `onsite` with `location.setting_source: inferred` (jobsearch 0.70.0, dev #727 /
public #159), and with no readable place it leaves the type absent and the screen asks. A type you
give beside `none stated` is refused: it would be a guess nobody could tell from a stated setting.
Once you read the JD and it states a setting, replace the whole location with it: `record.py set
<opp_id> location '<json>'` (no `setting_source`); the write records the overturn. A create
without it copies nothing. Run
`~/.claude/jobsearch/run deferred.py --settle` before the dashboard: it closes every `capture-role`
item whose URL now has a record (a tracking-parameter variant of the URL still matches), every
`research-role` item whose opportunity has a `research_log` and every `read-jd` item whose role has
been read (a still-unread one past `search.triage_stuck_days` records `surface-cannot-read` first,
through `record.py`; pass `--already-locked` to `--settle` inside this write phase). Anything not
captured stays a pending row and is counted in the summary.

**A role held from a degraded sweep is not claimable** (dev #722 / public #156). `--add-roles`
holds a role every query of which dropped or added a filter, was `unapplied` or was truncated as a
`capture-role` item with a `quarantine` field. `--claimable` lists it under `QUARANTINED` and
`--claim` refuses it; do not capture it. A clean sighting in a later pass releases it, or the
owner does (`deferred.py --unquarantine <id>`). Say the held count and its codes in the summary
(`run_summary.py` prints them).

**⭐ TRIAGE BEFORE THE CANDIDATE IS ASKED (dev #713 / public #145).** A captured role becomes the
candidate's pursue/pass decision only once the system has READ it. Until it carries a recorded JD
read, pay and work setting as written, a stored screen and a lean, the dashboard labels it
`triaging` and it is in no needs-you count. This step reads the next batch; it is a bounded step,
never a sweep of the whole backlog:

```bash
~/.claude/jobsearch/run your_move.py --triage-queue
```

It prints JSON: `cap` (`search.triage_per_run`, default 10), `waiting` (roles still `triaging`),
`over_stuck_bound` and `batch` — **at most `cap` roles, oldest first sighting first**, each with
the fields it still `missing`. **Take that batch and no more**: the cap is what bounds the cost of
the step (one JD read per role), and a backlog larger than the cap drains over the next runs.
For each role in the batch, in order:

1. **Read the JD** (`jd_url`, else a sighting's `source_url`). Record it on the role's `fit`:
   `record.py show <opp_id>` first, then `record.py set <opp_id> fit '<that object, existing
   requirements[] kept, with analyzed_on = today and jd_source = what you actually read>'
   --already-locked`.
   - **A read that fails is still a read, and says why**: `jd_source` = `unavailable: <reason>`,
     the reason exactly one of `login-wall` · `dead-link` · `no-url` · `surface-cannot-read`. The
     role then goes to Decide with the lean defaulted to `ask` and the line `not read: <reason>`.
     A null `jd_source` means NOT TRIED, never "failed".
   - **A JD that needs an authenticated browser, on a surface that has none** (a headless run
     without `--chrome`, a cloud run) (dev #723): queue it, never type a free-text
     `deferred.py --add` for it (free text is for the send filter's denylist, never for an
     engine step):
     `~/.claude/jobsearch/run deferred.py --add-jd-read <opp_id> --run <run id>`. Leave the role
     `triaging`. A browser-holding worker claims the item (the claimable step above:
     `--claimable --run <this run's id>` never serves it back to the run that queued it), and
     `deferred.py --settle` records `surface-cannot-read` once the item has waited past
     `search.triage_stuck_days`. **Never record that reason by hand before then; `record.py`
     refuses it.** A worker that CLAIMS a `read-jd` item first checks it really has a browser
     (`list_connected_browsers`; `whoami.py`'s `chrome` only says the extension is configured, not
     that this session was launched with it). No browser: `deferred.py --release <id>` and record
     nothing. A browser: read the JD, `record.py set <opp_id> fit '<…jd_source = what you read, or
     unavailable: login-wall…>' --already-locked` as in the read step above, then `deferred.py --done <id>`.
2. **Pay and work setting as written.** The sweep's `pay=` and `setting=` slots reach the role only
   through `create … --from-item` (above); a role the runner captured in-pass, or created without
   `--from-item`, has neither. If either is still absent, record what the JD says. A listing that shows
   no pay is `record.py listed-pay <opp_id> --none-shown --already-locked`, never a way of saying
   "not read". The setting goes in `location.declared`, verbatim, or the literal `none stated`.
3. **Screen it**: `record.py screened <opp_id> --already-locked` re-runs the scripted minimal
   screen (above) and stores its result. A `remove:` verdict follows the removal path above; that
   role never reaches Decide.
4. **Lean**: `record.py lean <opp_id> --lean pursue|pass|ask --line "<one line>" --jd-file <the JD
   text you read> --already-locked`. The script matches the profile's likely-pass signals against
   the title, the JD and the company, and stores the matches beside your lean. **A signal is a
   LEAN, never a removal**: only a hard rule removes a role.
   **An age-flagged recruiter role defaults to `ask`** (dev #716 / public #142). When the
   stored screen (the screen step above) carries `review:age` (a retained-search role older than
   `search.retained_search_age_days`, or a recruiter role whose age is unknown), its screen line
   reads `FIRST MOVE: ask the recruiter …`; leave `--lean` and `--line` off and the script records
   `ask` with that first move as the line. Pass `--lean` only when the JD gives you a reason to
   lean the other way, and say it in `--line`.
   **A title below `screen.title_floor` leans by pay and never removes** (dev #722 / public #156,
   jobsearch 0.69.0). When the stored screen's title rule reads `BELOW-FLOOR`, leave `--lean` and
   `--line` off and the script records the lean the pay implies: `pursue` ("title below your
   floor (<level>), but pay is within your range") when the comp rule clears, `ask` ("... check pay
   before deciding") for any other comp verdict, beside a `title-floor` hit on the Decide card.
   Pass `--lean` only when the JD gives you a reason to lean the other way. A role the floor
   or the title keys newly cover is offered back by `--triage-queue` as missing `screen` (its
   stored screen was computed under other title keys): run `record.py screened` again, and it keeps
   the lean you recorded and adds the hit.

Then measure the drain. Put this one line in the run summary, verbatim:

```bash
~/.claude/jobsearch/run your_move.py --triage-report --batch <id>,<id>,...
# triaging: N waiting, M triaged this run, K over the stuck bound
```

`N` is what is still being read, `M` how many of this run's batch the step finished, `K` how many
roles have waited past `search.triage_stuck_days` (default 3) from their first sighting and so
reached the candidate in Decide labelled `not yet read (waited K days)`, lean `ask`. **A nonzero
`K` is the step failing, not finishing: say in the summary which reads failed and why** (the
first runs after the 0.67.0 upgrade also count the roles captured before it, which are already
older than the bound and drain oldest first). The gate
always exits; this line is how a run proves it is not exiting by timeout.

**⭐ `plays.py --all` (ADR-031 B4, design §26.8) — the due play step across every confirmed plan,
in this same write phase.** It is a **pure selector, not a writer** — it prints which pursuits
are due a research or a draft step (capped by `posture.py --may` and the plan's own
`max_drafts_per_run`, 0 unattended below `full` posture, and skipping `apply` steps, the owner's
own act, always); the actual write is the ordinary `research`-step delegation (§5) or
`outreach-drafter` dispatch (§7b) recording via `record.py touched`/`answered` — so one step
stays one transaction by construction, never a batch this run holds the lock across:

```bash
~/.claude/jobsearch/run plays.py --all
```

Run it once, after the incremental per-role writes above, to catch any due play step this run's
own event-driven passes (reply arrived, meeting confirmed, …) did not already surface.

Then: remaining edits to `outreach/network.md`; record any new cross-cutting ask in `data/asks.jsonl`
(kind: role|system — an ask leaves by setting `resolved_on`+`resolution`, never by rewriting
its text). **⭐ A decision ask requesting a specific action on a linked role — "approve
applying?", "approve this outreach?" — carries `resolves_when` (`application`|`outreach`) plus
`opp_id`: then `record.py`'s write that records the action resolves the ask in the same locked
transaction, and no drift window exists (dev #133).** Then any newly confirmed meeting in
`data/commitments.jsonl` (date verified from the
.ics, never recall); rewrite `handoff.md` — the letter to the next session — with its state taken
from `~/.claude/jobsearch/run handoff_state.py`, embedded verbatim, and prose only for reasoning
and next steps, pointing at record ids (coordinator skill § 6, dev #492); append a `log.md`
entry. **All mutation belongs in this step and the four below — nothing after
DASHBOARD may change tracked state.** Keep the window to COMMIT tight; it should be minutes.

## 7b. ⭐ WHEN A REPLY ARRIVES — RECORD IT, THEN DRAFT THE RESPONSE (added 2026-08-04, per the candidate)

**The candidate: "that process or the coordinator should suggest a response." It lives HERE, because a
reply can land at 9am while no coordinator session is open — a suggestion that waits hours for a
session is a post-mortem, not a suggestion.**

For every INBOUND reply this run discovers (Gmail or LinkedIn), after the incremental state write:
0. **⭐ FIRST confirm the candidate hasn't already answered it** (the thread-completeness check in §3b):
   pull the full thread and look for a message the candidate sent AFTER the inbound. If so, record both
   directions, note "already replied" in the summary, and **STOP — do not queue or draft.** Only if
   the last word is theirs do steps 1–3 apply.
1. **Queue an URGENT `reply` finding** with the sender, the role, and a ONE-LINE proposed response
   angle — this reaches the candidate's device via the completion notification.
2. **If the reply plainly calls for an answer** (a question, an objection, proposed times, a
   referral pointer), **spawn `outreach-drafter` to draft the response into `outreach/drafts.md`**, marked
   `**AUTO-DRAFT from a background run — review extra carefully before sending.**` A draft is
   inert by design; the send is always the candidate's. Skip drafting only when the reply closes the
   thread (a rejection, a "not my search" with no pointer) — then the queue line says so instead.
3. **Regenerate + verify the dashboard** (the DASHBOARD step covers it) so the draft is readable there.

⚠️ The drafter's first read is `brief.py --for contact:<people-id> [--opp <id> | --channel <id>]`
(Query or Citation C1) — a computed, stamped brief of what was actually said, never re-derived
from memory or a fresh introduction (the Part-B lesson, 2026-08-04). Cite the printed id on the
new entry's `**Brief:**` line, `**To:** contact:<people-id>` on the recipient.

## 8. MEETING CROSS-CHECK

`~/.claude/jobsearch/run meeting_check.py` — sweeps every configured mailbox for calendar artifacts and diffs them
against This Week on **date AND counterparty**. **Every meeting miss in this repo's history would
have been caught by this.** It reports artifacts TO GO READ; the authoritative time comes from
`gmail_get_attachment` + `parse_ics.py`, because a subject line can be weeks stale while the newest
message schedules something tomorrow. **An artifact carrying an `.ics` with no readable date is an
UNKNOWN, never a pass**, and two artifacts sharing an iCalendar UID are ONE meeting revised —
highest `SEQUENCE` wins. Anything it surfaces goes into `data/commitments.jsonl` (the store
behind the This Week tab) before the dashboard.

**⭐ THEN ASK WHAT EACH UPCOMING CALL STILL NEEDS — AND DRAIN EVERY `PREP OWED` ROW THIS
RUN.** After anything new is recorded into `data/commitments.jsonl`:

```bash
~/.claude/jobsearch/run conversations.py
```

It regenerates `views/conversations.md` and prints one row per commitment in the horizon
(default 7 days), each resolved against the three durable prep stores through
`knowledge.prep_hits` — the single existence predicate (dev #153: checking `conversations/`
alone once missed prep already promoted to `pipeline/kb/<company_id>.md` and re-promised it
as owed across multiple runs; this script asks the same resolver `knowledge.py` uses, never
a narrower re-implementation). The old rule — *ask whether one already exists before
promising* — is now a property of the script, not something a run must remember.

**For every row it prints as `⛔ PREP OWED` (`owed` or `owed-partial`): invoke the
`call-prep` skill NOW, in this run's write phase** — the same way `trigger.py`'s
sendable-now rows are worked when they surface, the fact makes the firing inevitable. On a
`prepped` row, **link to the file(s) it names, never re-promise a note that exists.** A
`unlinked`/`unreadable`/unplaceable-date row is a data fix this run makes before anything
else. If the note cannot be finished here (research unavailable), `call-prep` writes the
records-only note marked `**Prep status:** incomplete — <reason>` and the row stays
`owed-partial` — **report it as still owed in the summary; never report a drained row that
was not drained.** A promise from a stateless background run to do future work is the
failure mode this whole design avoids — the artifact on disk is the source of truth, and a
row that keeps standing is the self-healing form of loudness.

**⭐ A PREP NOTE JOINS THE PIPELINE; ITS ARCHIVE RECORDS THE PROMOTION** (issue #12 — both
stores looked populated and answered nothing). Every prep note carries a `**Companies:**`
line of `company:<id>` token(s) (`channel:<id>` for a call with a recruiting firm; the literal
`none` if genuinely untracked) — the note is date-keyed on purpose, so this line is the ONLY
path from a pursuit to its conversation history. **The archive itself is a script, not a
step:** `archive_preps.py` (HYGIENE, §1) moves every prep dated before today to
`archive/call-preps/`, appending `**Promoted:** unresolved` to any note that carries no
promotion record — so a skipped promotion is a visible debt, never a held call still
rendering in full on the dashboard. Promote durable content to `pipeline/kb/<company_id>.md`
and record `**Promoted:** kb:<id> on <date>` (or `nothing-durable`) on the archived note.
`knowledge.py` in HYGIENE reports every unjoined file, unrecorded promotion, and
conversation-stage pursuit with no kb file — **dispose of those in this run: structuring a
join or creating a named kb file is run work, never a note for the candidate.**

## 9. STAMP THE CHANNELS YOU SWEPT

`~/.claude/jobsearch/run channels_due.py --stamp <channel_id>`. **Nothing else writes `last_reviewed`**, so
skipping it makes the sourcing queue report false overdues — and a queue that is wrong in a known
direction stops being an instrument and becomes something a run talks itself out of.

## 10. ADVANCE `stage`, AND RECORD HOW IT WAS SENT

Set `stage` (`sourced`→`contacted`→`screening`→`interviewing`→`offer`→`closed`) in the same edit
that changes it. **It is the only field that can answer "what actually converts," and nothing
infers it.** A move into `screening` creates `pipeline/kb/<company_id>.md` in the same pass if it is
missing — accumulation is the run's job, and `knowledge.py` names every gap.

**When the candidate reports sending something, WRITE THE TOUCH** (a `data/touches.jsonl` row,
ADR-031 B3) with its `date` — a log entry once claimed a row had been added and it never was, and
`validate_data.py` cannot catch that because a MISSING row is schema-valid.

**Every new touch carries** `medium` · `touch_type` · `recipient_role` · `delivery` (plus
`address_status` for email, `campaign_id` for a multi-touch push). **`outreach-drafter` emits these
with the draft — copy them verbatim**, because the drafter is the only actor that knows which
medium applies. Then **MOVE the `outreach/drafts.md` entry into `data/messages.jsonl`** and set
`message_ref`. The old rule deleted the text, which is why the historical rows can be analyzed for
channel but never for content.

## 11. PROCESS DEBT (advisory here)

`~/.claude/jobsearch/run check_process_debt.py`. Daily runs may append freely; **the WEEKLY run drains it
to zero.**

## 12. DASHBOARD — after the LAST mutation

```bash
~/.claude/jobsearch/run check_dashboard_fresh.py --fix
~/.claude/jobsearch/run check_dashboard_coverage.py   # the page accounts for every record; a gap here is a renderer defect, never a hand-edit
~/.claude/jobsearch/run presence_set.py --check       # the presence working set (regenerated by the same --fix) round-trips against its sources (ADR-028)
```

Then **grep the OUTPUT** (`views/dashboard_artifact.html` — sendable message and letter bodies
render on the ONE page since the 2026-08-29 collapse) for a distinctive phrase from what you added.

**Two pages CAN publish each round since 0.39.0 (ADR-028):** the dashboard, and
`views/presence_set.html` — the presence working set (claim union, one tab per active variant,
open items, standing rules), to the URL in `views/presence_set_url.txt`. Same create-if-absent
rule on first publish (write that url file in the same step; `check_dashboard_fresh.py
--publish-state` names it as *first publish pending*), same recover-never-mint rule on
`url-missing`. It publishes on a zero-variant profile exactly as on five — its existence never
depends on the data.

**⭐ Check `check_dashboard_fresh.py --publish-state` before publishing either page (public
#107 §4.1): publish each page whose verdict is not `unchanged — skip`; never read a page you
are not publishing.** The presence page changes only when a presence file does, so on most
rounds it is byte-identical to its own stamp — the check names it `unchanged — skip`, and that
round it is neither opened nor republished, saving the read and the publish for nothing. One
`--stamp-published` still covers every published page in one call — it stays unconditional, so
a page you skipped has its existing stamp simply re-affirmed, not left stale.
**Verifying the source file is not verifying the deliverable** — a body that fails to render is
indistinguishable from one never written. Publish with the Artifact tool: **ONE artifact, every
round** — `views/dashboard_artifact.html`, to the URL in `views/dashboard_artifact_url.txt` (the
router and phase pages are retired). Create the artifact and write that url file in the same step
if it is absent — a fresh install has neither, and that is the defined `never-published` state, not
an error. Skip gracefully (and note it) if the tool is unavailable. If
`~/.claude/jobsearch/run pending_stubs.py --check` reports retired-URL rows, drain them while you
hold the tool: **read the live page at the row's URL first** (the publishing tool refuses a
publish over an unread URL, and the stub's content is never identical to what it replaces, so
neither refusal fires once you have), then stub-publish, then `--published` only after it is
confirmed — that order is what keeps a retired URL stubbable at all. See coordinator/SKILL.md's
own "Drain pending stubs" section for the full sequence.

**⭐ If the publish reports a VERSION CONFLICT, another session published since you generated
(dev #133 / public #22). Never pass `force`, and never drop the publish silently:** re-run
`check_dashboard_fresh.py --fix` (the store is the merge — both racers generate from it) and
publish again. **After every successful publish, stamp it:**

```bash
~/.claude/jobsearch/run check_dashboard_fresh.py --stamp-published
```

The stamp is what lets the next run detect a dropped publish mechanically; a publish that could
not succeed is a finding the summary states loudly, and the next run's hygiene check will flag
it regardless — that convergence is the design, so never silence it.

## 13. SUMMARY

Top 3 focus areas · new items with comp/fit assessment · status changes · proposed drafts ·
**the mail connector this run used** (`gmail-multi` or `claude-gmail`), with any sweep that skipped
because of it.
**NEVER send messages, emails or applications — drafts are for approval only.** If nothing is new,
one line, but still do UPDATE STATE and DASHBOARD.

**⭐ MONDAY DECISION BATCH.** On the first run on/after Monday, present a consolidated batch
pairing the standing ATS-portal stage check with EVERY open Your Move role ask, each carrying an
explicit lean (pursue/pass/apply) AND an act-by date. **The binding constraint is the candidate's
decision throughput, not sourcing** — make the queue clearable in one 15-minute pass. **Role-ask lapse
rule:** a *role-only* pursue/pass ask unanswered past its act-by date is closed as "lapsed" and
removed from Your Move — reversible, and logged. **NEVER applies to letters, sends, or anything
with an external deadline.**

## 14. POST A RUN-SUMMARY, THEN COMMIT + PUSH, THEN CLOSE THE JOURNAL

**public #85** — a scheduled run once posted "no change across mail, the professional network,
and sourcing" while that SAME run had recorded a genuine inbound reply and left real writes
uncommitted. The summary is no longer typed prose; it is a QUERY over this run's own journal and
its own git diff, computed at the moment it is posted — the model cannot assert a claim the
machine disagrees with, because the machine is what generates the claim:

```bash
~/.claude/jobsearch/run run_summary.py --run <id> --post \
    [--annotate "<what the candidate must decide, act-by date first>"]
```

This prints the run's own footprint — files changed, mailboxes swept, probes, gaps opened — as a
GENERATED headline (`CHANGED: …` or `NO CHANGE: …`) and posts it to the coordinator queue.
**`--annotate` adds context UNDER the headline; it can never change what the headline says.**
Both the annotation and this run's own journal notes (`journal.py --note`) are checked against the
footprint at post time (dev #703 / public #155), and they are treated differently on purpose. An
`--annotate` that contradicts the machine-measured footprint (e.g. "nothing new" over a real diff)
is REFUSED outright (exit 2, nothing posted, the phrase named), exactly the shape #85's bad summary
would have hit: reword it and post again. A journal note that contradicts the footprint (a note
reading "Quiet run." over a run that changed files) cannot be un-written, so it is WITHHELD instead:
the summary still posts, the note is replaced in the detail by `note withheld: it claimed '<phrase>'
but the footprint shows <N> changed file(s)`, and the script says so on stderr, so an unattended run
never loses its summary. **Do this even on a quiet run** — "nothing new" is information, and its absence is
indistinguishable from a run that never fired. **Writing state is not the same as telling the
candidate:** one run booked a call and sourced three roles while `notifyOnCompletion` was
unclaimed and the run queued nothing, so none of it reached their view.

Then commit, genuinely last for the DATA, and let the sync resolver decide the push half:

```bash
# ⚠️ EXPLICIT PATHS, never `git add -A`. Subagents have written into this same tree during the
# run, and `-A` bundles whatever they left mid-edit into this commit -- the exact failure the
# rulebook records for 2026-07-25. Name what this run changed.
git add data/ handoff.md log.md outreach/drafts.md applying/cover_letters.md dashboard.html 2>/dev/null
git commit -m "Daily run $(date +%F): <one-line summary> [run:<id>]"
~/.claude/jobsearch/run sync.py --end-of-run
```

**`~/.claude/jobsearch/run sync.py --end-of-run` replaces the old unconditional push (ADR-012).**
It resolves the profile's DECLARED `config.sync.mode` and acts: under `remote` it delegates to
`push.sh` (which reads this session's `.git/push_token`, minted at run start — a bare `git push`
still fails by design); under `local-only` it prints the one line the run summary must carry
verbatim: *committed locally; not pushed — this profile declares `sync.mode: local-only`*. Two
exits are LOUD, not optional reading: **NOT PERSISTED** means the push FAILED and the commit
exists only on this machine; **COMMIT-ONLY** means the mode is `undeclared`, `mismatch`, or
unreadable — never push by hand on a guess; say so and let `migrate.py` or `sync.py --set`
resolve it. **Either way, journal it immediately** rather than editing the already-posted
summary by hand — a fact the run knows goes into the store, never into prose someone has to
remember to update:

```bash
~/.claude/jobsearch/run journal.py --run <id> --note "<sync.py --end-of-run's own output line>"
```

**Close the journal now that the tree has settled — this is the run's own check that its writes
actually PERSISTED, not merely that it posted about them:**

```bash
~/.claude/jobsearch/run journal.py --run <id> --end
```

`--end` records this same footprint shape a SECOND time, measured NOW — after the commit/push
attempt, as the run's genuinely last action. A clean tree here is the proof the writes actually
landed; a dirty one means either the commit above never happened or something after it mutated
state, and `check_runs.py` reports exactly that run as one that wrote and never persisted. This
number is expected to differ from the one `--post` showed earlier (that one is the run's real
diff, taken BEFORE the commit) — the two are independent measurements of two different moments,
not one value copied twice.

**THEN, and only then:** `~/.claude/jobsearch/run runlock.py --release`. **Release even if the run failed
partway** — a held lock blocks every subsequent run until it goes stale, which is far worse than
the collision it was preventing.
