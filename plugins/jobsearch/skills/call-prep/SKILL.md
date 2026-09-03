---
name: call-prep
description: 'Write the prep note for an upcoming call or interview: synthesize the company kb, archived preps, and pipeline records into conversations/call_prep_<date>.md, dispatching opportunity-researcher only when the counterparty is new. Use when conversations.py reports a PREP OWED row, or before any scheduled call. Not the meeting sweep (daily-run runs meeting_check.py to FIND meetings; this preps ones already in data/commitments.jsonl) and not role research in isolation (opportunity-researcher researches one role; this composes what THIS call needs from everything already known). Never prompts — on a degraded surface it writes a records-only note marked incomplete and the row stays owed.'
---

# Call prep

The working capability for phase 5 (conversations). The evidence this exists: the phase had
real data — a schedule store, three prep stores, a promotion path — and no capability at
all, so the only way a prep note got written was the owner remembering to ask by hand
before each call. The firing fact is a `PREP OWED` row from `conversations.py`; this skill
is what drains it. **A prep that silently does not get written is worse than a loud owed
row** — so nothing here ever claims a drain it did not finish, and a failed write leaves
the row standing for the next run to see.

## Binding — say which profile this session is acting on (dev #150)

```bash
~/.claude/jobsearch/run binding.py
```

**`NO PROFILE` (exit 3) means stop and say so.**

## 1. What is owed — the view, never memory

```bash
~/.claude/jobsearch/run conversations.py
```

Regenerates `views/conversations.md` and prints every row that needs you. Work ONLY from
its rows:

| row state | what this skill does |
|---|---|
| `owed` | write the note (steps 2–4) |
| `owed-partial` | **finish the named note in place** — never start a second file |
| `prepped` | nothing — link to the listed file(s); re-promising an existing prep is the dev #153 defect |
| `unlinked` / `unreadable` / `*-date` | a **data fix**, not a note: repair the record (link the commitment, fix the `**Prep status:**` or date field), then re-run the script |

The exists-already question is a property of the script (it resolves through
`knowledge.prep_hits` across `pipeline/kb/`, `conversations/`, and `archive/call-preps/`)
— do not re-answer it by listing directories.

## 2. Read before writing — the synthesis inputs

For the row's counterparty (`company:<id>` from the linked opportunity, or `channel:<id>`
for a call with a recruiting firm):

- `pipeline/kb/<company_id>.md` — promoted durable knowledge from every prior conversation
- the paths `conversations.py` listed for any partial note, and `archive/call-preps/`
- the opportunity record in `data/opportunities.jsonl`: `fit` (aligned/partial/unknown
  rows and their `pitch_line`s), `outreach[]`, `applications[]`, `research_log`, `note`
- `data/messages.jsonl` — what has actually been said in both directions
- open asks with `act_by` touching this company (`data/asks.jsonl`) — a call is the
  cheapest place to close an open fit question
- the commitment row itself: `who`, `time`, `note` — and the time is verified from the
  invite's `.ics` (`parse_ics.py`), never recall

## 3. When the counterparty is new — research, bounded

If the linked opportunity has an empty `research_log` (or a channel counterparty has no
history at all), dispatch **`opportunity-researcher`** — it reads only, reports findings,
and runs under the outbound click guard, so it is safe on the scheduled run too. Fold its
findings into the record first (the run's job), then into the note.

**If research cannot run here** — no browser on this worker, the agent fails, the
counterparty stays unresolvable — **do not stop and do not ask.** Degrade to step 4's
records-only note. Degradation is declared in the note itself, never discovered later.

## 4. Write the note — `conversations/call_prep_<date>.md`

`<date>` is the CALL's date. One file per date: a second call the same day gets its own
section in the same file, and its token joins the shared `**Companies:**` line. The note
carries, in this order:

```markdown
# Call prep <date>
**Companies:** company:<id>          (or channel:<id>; the literal `none` if untracked)
**Prep status:** complete            (or: incomplete — <reason>, see below)

## <time> — <title> (<who>)
- Why this call, and what a good outcome is
- Their context: what the kb and research actually establish
- Your pitch: the fit rows' `pitch_line`s, in your own established voice
- Questions to ask — every open fit `unknown` first (they carry `act_by` for a reason)
- Logistics: time verified from the .ics, link, who joins
```

- The `**Companies:**` line is the ONLY join from a pursuit to its conversation history
  (the note is date-keyed on purpose) — omitting it is how a populated store answers
  nothing (issue #12).
- `**Prep status:** complete` only when every section is genuinely finished. If research
  was unavailable, write everything the records support and set
  `**Prep status:** incomplete — <machine-readable reason>` (e.g. `incomplete —
  research-unavailable: no browser on this worker`). The resolver reports that note as
  `owed-partial` — still owed — **which is correct: a partial prep must never impersonate
  a full one.** The next capable run finishes it in place.
- Anything else on that line is `unreadable` — loud in every view — so write one of the
  two words first.

## 5. Verify the drain — the script's word, not yours

```bash
~/.claude/jobsearch/run conversations.py
```

The row must now read `prepped` (or, degraded, `owed-partial` with your note named).
**Report exactly what the script reports**: a drained row as drained, a partial as still
owed with the reason. Never report a drained row that was not drained — the summary of a
scheduled run states what was owed and not completed.

## 6. After the call — promotion is yours; the archive is a script's

The note is a dated working artifact; durable content is PROMOTED, not left to rot:
`pipeline/kb/<company_id>.md` grows and the note records `**Promoted:** kb:<id> on <date>`
(or `nothing-durable`). **The move to `archive/call-preps/` is NOT a step here** —
`archive_preps.py` (daily-run HYGIENE §1, and the 0.36.0 migration once) moves every prep
dated before today by itself, appending `**Promoted:** unresolved` to any note still
carrying no promotion record. That marker is what `knowledge.py` reports until the
promotion is written on the archived note. This skill only has to leave the
`**Companies:**` join in place for any of it to work. (The archive was a line in this
section for months and was skipped every time — a step a session is told to
remember is the step that is dropped; a script is not.)

## Unattended rules (deployment.md — these are requirements, not tone)

- **Never prompt.** A scheduled run has nobody to answer; complete or degrade.
- Writing the note is profile mutation: on the daily run it happens in the write phase
  (§7–§11), before DASHBOARD, like every other mutation.
- The dashboard's conversations row counts owed preps via `conversations.report` — no
  extra step; regenerating the dashboard (daily-run §12) republishes the truth.
