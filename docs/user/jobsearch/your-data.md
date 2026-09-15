# Your data

Everything the plugin knows about your search lives in **your** profile directory, in files you
can read, edit and diff. There is no database and no hidden state. This page explains what each
file holds, what the important fields mean, and how to change things by hand safely.

---

## Two kinds of file, and the rule that decides

**Datasets are JSON. Documents are markdown.**

If something gets counted, sorted, filtered or joined to something else, it is data and lives in
a `.jsonl` file. If something is prose you read and edit in full, it is a document and lives in
markdown. The dividing question is *"would I ever want to ask a question across all of these?"*

That is why a cover letter's **text** is markdown but the **link** between that letter and the
role is a field: you will never sort your letters, but you will absolutely want to ask whether
applications with a letter attached get more responses.

### The datasets — `data/*.jsonl`

One record per line. Hand-editable, and every line is a self-contained JSON object, so a change
shows up as a one-line diff rather than a reformatted file.

| file | holds |
|---|---|
| `companies.jsonl` | employers — one record each, however many roles they post |
| `channels.jsonl` | where roles come from: job boards, company career pages, recruiting firms, referrals |
| `opportunities.jsonl` | the roles themselves, with their fit analysis |
| `messages.jsonl` | every communication, both directions, with its full text. Since 0.36.0 an inbound message can carry `answers`, the id of the outbound message it replies to — see *Touches* below. Since 0.50.0 it can also carry `resolves`/`resolved_by`, the ATS sweep's own resolution — see *ATS receipt matching* below |
| `people.jsonl` | every person you deal with, once each — see *People* below (since 0.44.0; before that, contacts lived nested on the role or channel) |
| `involvements.jsonl` | how each person connects to a role or a channel — since 0.44.0, alongside `people.jsonl` |
| `applications.jsonl` | every application you have submitted, once each — see *Applications* below (since 0.45.0; before that, applications lived nested on the role) |
| `cover_letters.jsonl` | the link between an application and its cover letter — since 0.45.0, alongside `applications.jsonl`, see *Cover letters* below |
| `touches.jsonl` | every outreach touch you have made, once each — see *Touches* below (since 0.48.0; before that, touches lived nested on the role as `outreach[]`) |
| `asks.jsonl` | things waiting on you — a role decision or a piece of system upkeep |
| `commitments.jsonl` | what is scheduled — calls, deadlines, follow-ups due on a date |
| `briefs.jsonl` | since 0.46.0 — the append-only ledger of what a draft's `**Brief:**` line cites; see *What a draft now carries* below. Never edit this by hand and never read it as "the current state of a thread" — it is evidence of what a computation SAW at drafting time, not a source of state |
| `resume_variants.jsonl` | the declared printed-resume set — since 0.39.0 (public #26); see *Resume variants* below |

### The documents

**Starting with 0.32.0, these live inside six phase directories** — `presence/`, `configure/`,
`pipeline/`, `applying/`, `conversations/`, `outreach/` — rather than loose at the profile root.
This happens automatically, the first time you open a session after upgrading; you do nothing to
trigger it, and the paths below are what you will have once it has. `config.json`, `user.json`,
`data/`, `docs/` and the `dashboard.html` tombstone are not part of the move and stay exactly
where they are. (One part of `config.json` gets its own section below: [ATS receipt
matching](#ats-receipt-matching-configjsonats).)

| file | holds |
|---|---|
| `presence/claims.md` (was `resume.md`) | every background claim, printed or not — the printed resume pages are separate files it feeds — plus an *Additional Detail* section for things a resume never says |
| `presence/projects.md` | projects and their scale, each with a note about when it is worth surfacing |
| `archive/retired-trackers/focus.md` | retired — a frozen stub. See *"focus.md is retired"* below |
| `handoff.md` | a short letter one session leaves for the next, so nothing gets lost between runs |
| `outreach/drafts.md` | **since 0.47.0, the working set only** — entries still under review: sendable, blocked on someone else, or needing you to resolve a precondition. Every open entry carries `**To:**` and `**Brief:**` meta lines (since 0.46.0; see *What a draft now carries* below). A sent or moot entry no longer stays here — see *The working set — what leaves and where it goes* below |
| `applying/cover_letters.md` | letters, one anchor per role |
| `pipeline/kb/<company>.md` | what you have learned about a specific company (older profiles used flat `kb_<company>.md` files at the root; migrations moved them first into a `kb/` directory and then, at 0.32.0, into `pipeline/kb/`) |
| `conversations/call_prep_<date>.md` | prep notes for a scheduled call, dated rather than named by company; durable content gets promoted into `pipeline/kb/<company>.md`. A note written when full research wasn't available carries a `**Prep status:** incomplete — <reason>` line under its heading rather than being skipped — see [Reading what the search produces](reading-your-files.md) for what that marker means |
| `dashboard.html` | a generated **tombstone stub** — carries no state, just a pointer to where the dashboard actually lives now. Stays at the profile root, unlike the rest of this table |
| `views/dashboard_artifact.html` | **one of two generated, published pages** — router section (one row per phase, next action and a count) plus every phase's own section, reached by an in-page link; drafts, letters and knowledge files show as title + status + location, not in full, except a pending message's full text, which lives on this page's outreach section |
| `views/presence_set.html` | **the other generated, published page** (since 0.39.0, ADR-028) — a review copy of `presence/`: one tab per declared resume variant, a claim-union tab, an open-items tab, and a rules tab rendering `presence/rules.md`. Always published, including on a profile with no declared variants |
| `views/applying.md` | generated, **read-only**, regenerated in session (not by the scheduled runs) — the working queue: roles to apply to and the follow-up work a submission created |
| `views/conversations.md` | generated, **read-only**, regenerated by the **scheduled runs** (daily/weekly) — what each upcoming call still needs: whether its prep is written, and a `PREP OWED` row when it isn't |
| `presence/rules.md` | **authored, not generated** — settled decisions about the claim union and the open-items categories on the presence working set above. Created once, seeded with three starting rules, by the 0.39.0 upgrade; yours to extend |

Every generated file above (the tombstone and everything under `views/`) is overwritten **every
run** (or, for `views/applying.md`, every application session), so hand edits to those are lost at
the next regeneration. If something on a generated view is wrong, the fix is in the underlying
record, never the HTML or markdown itself. See [Reading what the search
produces](reading-your-files.md) for what each one looks like and how to open it.

---

## Companies

An employer, recorded once. Twelve roles at the same company is one company record and twelve
opportunities — so a fact you learn about the company attaches in one place instead of being
copied twelve times.

| field | what it is |
|---|---|
| `id` | a short stable slug you will see referenced elsewhere |
| `name`, `aliases` | display name, plus other names it gets listed under |
| `vertical` | the sector, used for tiering and search targeting |
| `size_ownership` | e.g. public, PE-backed, employee count — context for whether the role is a fit |
| `career_url` | its own careers page; setting this makes the company reviewable as its own channel |
| `status` | `active-target` · `watching` · `passed` |
| `research_log` | append-only notes; company-level findings go here, not on each role |

## Channels — where roles come from

A channel is any source: a job board, an aggregator, a company's own careers page, a recruiting
firm, a referral, an alert email.

**A recruiting firm is just a channel** whose `type` is `recruiter`. A role a recruiter brings
you is a sighting whose channel is that firm — which means "which recruiters actually produce
roles I pursue?" is a query, not a memory exercise.

| field | what it is |
|---|---|
| `review_cadence` | `daily` · `weekly` · `biweekly` · `monthly` · `on-inbound` — drives the "what is due?" queue |
| `last_reviewed` | the date it was last checked |
| `scope_notes` | which titles, filters and locations this channel covers |
| `access` | how it is reached — see below |
| `relationship_status`, `log` | for firms and referrals: where you stand, and the thread history. Who you know there is a person, not a field on the channel — see *People* below |
| `alert_sender` | for a channel that sends alert-digest emails (a board or aggregator): the Gmail search fragment for its own From address, e.g. `from:indeed`. Absent on a channel with nothing to sweep — a recruiter, a channel you only check by hand — which is correct, not a gap |

**⭐ Retiring a channel now does two things, not one.** Setting `relationship_status: retired` used
to only drop the channel from the review queue (`channels_due.py` — "what needs reviewing"). Since
0.27.0 it also stops the daily alert sweep (`scripts/alert_sweep.py`) from reading that channel's
`alert_sender` digests, even though `alert_sender` itself is untouched. If you retire a channel to
get it off your review list but still want its automated alert emails scanned, retiring is the
wrong lever today — the one field now controls both, so it stops the digests along with the queue
entry whether you meant it to or not.

`access` states what a source **requires**, not the mechanism used to reach it:

- `public` — no login, reliable
- `login-chrome` — needs your signed-in desktop browser (this is LinkedIn)
- `public-bot-limited` — searchable by hand, but automation gets blocked
- `manual-candidate` — you review it yourself
- `human` — a recruiter or a referral
- `n/a`

## Opportunities — the roles

The main record. Everything about one role hangs off it.

| field | what it is |
|---|---|
| `company_id` | must resolve to a company |
| `title` | |
| `comp` | `{min, max, period, basis}` as **typed numbers**, so it sorts and screens. `null` if genuinely undisclosed — never a guess |
| `location` | `{type, primary, remote, declared}` — see *contested settings* below |
| `status` | what you are **doing** about it |
| `stage` | where it **is** in the funnel |
| `verdict` | `pursue` · `pass` · `parked` · `undecided` |
| `engagement_type` | `full-time` · `contract` — since 0.45.0; the 0.45.0 upgrade set this to `full-time` on every existing role, since that fact about a role isn't derivable from anything else on the record |
| `jd_url` | the posting. Required as a URL **or an explicit `null`** — never simply missing |
| `sightings` | every time this role was seen, and where |
| `plan_id`, `plan_assigned_on` | which plan (see *Plans and plays* below) is working this role, and since when — every role has one, since 0.49.0 |
| `next_action_date`, `next_action_owner` | when the next thing happens, and whose move it is — *which* thing is now the plan's job (see below) |
| `research_log` | append-only role history |
| `decision` | `{on, suggested, reason_kind, reason}`, since 0.47.0 — see *Recording why a decision diverged* below |
| `networking_closed_on` | the date you decided to stop working the network on this role, since 0.47.0 — see *Endings* below |

### `status` and `stage` are different questions

This is the one thing people mix up, so it is worth stating plainly:

- **`status`** = what you are doing about it → `active-pursuit` · `needs-resolution` · `in-motion` · `backlog` · `passed` · `expired`
- **`stage`** = where it sits in the funnel → `sourced` · `contacted` · `screening` · `interviewing` · `offer` · `closed`

They are orthogonal and you want both. A live pursuit waiting on a recruiter is
`status: active-pursuit`, `stage: contacted`. A role you have shelved is `status: backlog`,
`verdict: parked`, `stage: sourced`.

### Three values that exist to stop a guess

**`location.type: unresolved`.** Some postings declare two work settings at once — tagged both
hybrid and remote. Picking one silently decides which compensation floor applies. So instead the
setting is recorded as `unresolved`, with the posting's **verbatim** wording kept in `declared`,
and screening **declines to pick a tier**. The role stays in your pipeline and the question goes
to the employer. It is never quietly dropped.

**`status: expired`.** A posting that vanished before you ruled on it is not a role you passed
on. Recording it as `passed` would overstate how selective you are being. `expired` records the
*absence* of a decision — and because you never declined it, a repost of that same role surfaces
as a fresh signal rather than being filtered out.

**Where a role sits in the chase after you apply** — verify the posting is still live, identify
the recruiter, reach them through someone who knows you, use that name with the recruiter, wait
for the reply — used to be a field you set by hand (`play_stage`). **Since 0.49.0 it is no longer
a field at all: it is derived, every time, from your plan and your play** — see *Plans and plays*
below. The same "don't ask what the record already proves" rule applies to `verdict`: a role
still reading `undecided` once an application is on record becomes `pursue` automatically — the
act of applying was the decision, and you are never asked pursue-or-pass on a role you already
applied to.

### Endings — since 0.47.0

A role or an application can end in more than one way, and the record now says which:

- **`applications[].status: closed`** — you gave up on this application after the employer's ATS
  went silent, rather than hearing back `rejected`, `advanced`, or withdrawing it yourself. It
  joins those three as one of the ways an application can be over. `status_on` records the date
  the status last changed, so "how long did this sit before I gave up on it" is answerable.
- **`networking_closed_on`** — separately from the application, your own decision to stop working
  your network on this role. Once set it is never cleared automatically by a later touch; it is
  compared against the newest outbound touch to tell whether networking is still in force.
- **The two new `config.json.ats` settings below** (`silence_days`, `close`) are what turn ATS
  silence into a proposal to close, rather than leaving a stalled application sitting there
  indefinitely with no signal.

You record either ending with `record.py application-status` / `record.py networking-closed
--i-checked <date the you looked personally>` — you never hand-edit either field.

**The remainder — pursuits that ended with nothing recorded saying why — is one queryable ask,
not a list of commands to run.** The 0.47.0 upgrade that introduced this section originally
printed its own remainder as N separate `record.py application-status <app_id> ...` lines for
you to run by hand; as of 0.48.0 that remainder is instead one `kind: system` row in
`asks.jsonl` (`id: system-application-endings` — see *Asks and commitments* below), which shows
in your dashboard's System & tooling group like any other system ask and disappears once you
resolve it, the same as every other ask. A second 0.48.0 fix corrected the count itself: the
original logic could count a role you had already passed on and closed as "unrecorded" even
though it had no application to record an ending against — that precedence bug is fixed, and the
one system ask now carries the corrected count.

### Recording why a decision diverged — since 0.47.0

Every role's `verdict` (`pursue`/`pass`/`parked`/`undecided`) can be compared against what the
engine's own triage would have suggested at the time you decided. When you agree, nothing extra
is asked. When your call **diverges** from that suggestion, `decision` records why:
`{on: <date>, suggested: pursue|pass, reason_kind: <one of a fixed set>, reason: <your own
words>}`. The fixed set of reasons is `comp-acceptable` · `setting-acceptable` ·
`fit-misjudged` · `company-priority` · `not-interested` · `timing` · `other`. An override with no
reason recorded is a decision nobody — including future you — can audit later, which is exactly
what this closes. Written by `record.py decide`.

### Plans and plays — your strategy, worked automatically (since 0.49.0)

Every role you're pursuing is worked by a **plan** — what it's for, and (through a **play**) how
you're working it. `data/plans.jsonl` and `data/plays.jsonl` are the two new files this ships:

- **A plan** says what you're doing — `subject_kind` (`search` / `company` / `person` /
  `opportunity`) and `subject_id` say what it's *about*; `plan_id` on the role says which plan
  *governs* it. `outcomes` (`role`/`contract`/`access`) matters only on a `search` plan — several
  can be active at once, e.g. a themed search alongside your main one. `goal`/`approach` are your
  own words; nothing writes them for you.
- **A play** is the sequence a plan is worked by — steps, each gated on a condition the engine
  can already prove (an application submitted, an insider known, a referral in hand, silence past
  a window, …), never a rule language. The chase-after-applying sequence that used to be the
  `play_stage` field is now one of these: `plays.py`'s engine looks at what you've actually
  recorded and tells you the next step, instead of asking you to keep a position field current by
  hand.

**On upgrade,** the 0.49.0 migration adopts the shipped `referral-first` pattern into a play,
seeds a `default-plan` (a `search` plan, `outcomes: [role]`) and assigns it to every role you
have — even closed ones, so history stays attributable. **That plan starts UNCONFIRMED: nothing
acts outward on it until you look and confirm it.** Any `play_stage` text you had set by hand is
compared against what the play would derive, and if your hand-set position was *ahead* of what
the record can prove, the migration prints a **demotion** — the gap, and the `record.py touch
...` command that would close it. Your old free-text `next_action` moves onto the role's own
`note`, prefixed so you can find it, never dropped.

**Reading your plan and play:**

- `plays.py --options` — every adjustable parameter (a wait window, a search window), its bound,
  its anchor (what date it's counted from), its current value, and the command to change it.
- `plays.py --show <plan_id>` — the resolved position and *why* each parameter is set where it is.
- `plays.py --check` — how many pursuits are runnable now, waiting, manual, or stalled.
- `plays.py --late` — which pursuits are overdue their next step, and by how many days.
- `plays.py --brief <opp_id>` — what the drafter should say next for one role, and to whom.
- `plays.py --all` — drafts the due next steps across every confirmed plan in one pass (this is
  what a scheduled run calls); how many it's allowed to draft unattended depends on your posture
  (`posture.py --may drafting`) and the play's own `max_drafts_per_run` setting — 0 below `full`
  posture, up to 5 at `full`.

**Adjusting a play:** `record.py --file plays set <play_id> params.<name> <value>` — it refuses a
value outside the parameter's bound, or a parameter name that doesn't exist, naming the legal set
either way, so you can never silently set something the engine will never read.
`plays.py --adopt <pattern_id> --plan <plan_id>` swaps in a different shipped pattern (or
`--manual <plan_id>` to drop the play and decide each step yourself); `--confirm <plan_id>` /
`--unconfirm <plan_id>` turn outward action on and off.

**People, too.** `people.jsonl` rows can carry their own `cadence` (how often you want to stay in
touch); the same due-list logic that surfaces overdue pursuit steps surfaces people whose cadence
has lapsed, right beside the channels-due list — a run can exist to work your network alone, with
no application in view.

### People — the humans you deal with

**As of the 0.44.0 upgrade, a person is one record, period** — not one record per role they
happen to touch. Before 0.44.0, a contact lived on the opportunity (or the channel) where you
first recorded them, so the same recruiter showing up on two roles was two disconnected records
with no way to ask "what is my whole history with this person?" across both. Now every person
is one row in `data/people.jsonl`, and a separate `data/involvements.jsonl` record links that
person to each role or channel they touch — with a note on *what they are in that specific
context* (a warm referral on one role can be a cold recruiter contact on another; that fact
lives on the link, never on the person).

| field (on the person) | what it is |
|---|---|
| `name` | a name. URLs and email addresses go in their own fields, not in here |
| `email`, `linkedin` | structured and validated, never prose |
| `title`, `cadence` | who they are professionally, and (once you set it) how often you want to stay in touch |

| field (on the link to one role or channel) | what it is |
|---|---|
| `role`, `path_type`, `status`, `notes` | how you reached them and where it stands, **for this role or channel specifically** |

`path_type` is `warm-referral` · `recruiter` · `hiring-manager` · `hiring-context` ·
`internal` · `cold`.

> **If you messaged someone, they are a person on record by definition.** Every outreach record
> must point at a person that exists, and this is enforced — which is what makes "what is my
> whole history with this person?" answerable, now across every role and channel at once, not
> just one.

Query one person's full history with `python3 scripts/pipeline_index.py --person <name>`.

**What happens to your existing contacts on upgrade.** The 0.44.0 upgrade runs this migration
automatically, the first time you open a session on that version — you don't run anything
yourself. It reads every contact you already had on every role and every channel and, for each
one, decides one of two things:

- **Combine two contacts into one person**, but only when it is confident they are the same
  human by a strict rule: an identical LinkedIn profile URL, **or** an identical email address
  *and* an identical name — both, together. Two contacts that share only a name, or only an
  email, are never combined automatically.
- **Otherwise, keep every contact as its own separate person** — including cases the migration
  flags as *probably* the same person but isn't sure enough to decide for you: the same email
  with a different name (a shared team inbox, or a typo somewhere), the same name at the same
  company (two different people, or one record with a wrong slug), or the same name at two
  different companies (a slug collision, or genuinely the same person across two jobs over
  time). Nothing in this second group is merged. It is printed in the upgrade's own report so you
  can see it, and it stays available afterward from `python3 scripts/people.py --duplicates`
  — a live query, not a one-time list, so it never goes stale even if you don't act on it right
  away.

**Nothing is ever silently merged wrong, and nothing is ever silently lost.** When two contacts
*are* combined, the combination is a pointer (one row is marked as absorbed into the survivor),
never a rewrite of anything that already pointed at the absorbed record — so every old link to
either contact keeps resolving correctly. If you later discover a combination is wrong, or that
two people the migration kept separate really are the same person, confirm it yourself with
`record.py merge-person <duplicate-id> --into <survivor-id>` — a dedicated verb (since 0.48.0)
that sets `status: merged` and `merged_into` on the duplicate in one write, and refuses outright
if that merge would close a cycle (A into B, B already into A). And the whole migration only ever
writes once it has checked its own work is valid — if anything about your data would make the
result invalid, nothing is written and you keep exactly what you had before, with a report of
what needs attention first.

**`python3 scripts/people.py --duplicates` now also catches a name with a role or title stuffed
into it** — "Jordan Casey, VP Engineering" and "Jordan Casey" surface as the same pair, flagged
with the mechanism named in the reason (`stuffed title`) rather than leaving you to notice it
from two raw strings, the same discipline every other weak-signal pair already gets: surfaced for
you to decide, never merged for you.

**On email matching, deliberately:** `jane.doe@company.com` and `janedoe@company.com` are treated
as **different** email addresses, not the same one, even though some mail providers would
deliver both to the same inbox. So are `jane@company.com` and `jane+jobsearch@company.com`. This
is on purpose — collapsing those would risk merging two different people who happen to share a
mail provider's quirk, which is a worse mistake than leaving two genuinely-identical contacts
unmerged for you to combine by hand.

*Known limit, resolved by this upgrade:* the old per-role contact records are gone; every person
is now one record spanning every role and channel they touch.

### Touches — outreach you made

**As of the 0.48.0 upgrade, touches are their own file, `data/touches.jsonl`** — not a list
nested inside the role you were reaching out about. Before 0.48.0, each opportunity's own record
carried its outreach as a small array on itself (`outreach[]`); now every touch is one row in its
own file, linked back to its role by the optional `opp_id` below. Nothing about what a touch means
or how you work with it changed — only where it lives, and one new thing it can now say: a touch
no longer has to be about a role at all. A periodic reconnect with someone in your network, or an
introduction ask, is a legal touch with no `opp_id` — see *the object of a touch*, below.

One record per touch. The fields exist to make "which approach actually works?" a real question.

| field | why it exists |
|---|---|
| `id` | the stable handle a trigger points at (`<person_id>-t1`, `-t2`, ...). **You never mint it yourself**: `record.py` assigns the next number the moment a touch is recorded |
| `person_id` | who you reached — every touch is to a person, always resolved through `people.jsonl` |
| `opp_id` | the role this touch was about, if any. **Optional** — a channel-anchored or fully unanchored networking touch is a legal row with no role attached |
| `medium` | a LinkedIn connection note, an InMail and a direct message get read at completely different rates. Pooling them makes any reply rate meaningless |
| `touch_type` | a first touch and a chase have different base rates |
| `recipient_role` | a hiring manager, a recruiter and a peer are not the same audience |
| `campaign_id` | groups a multi-touch push so it can be evaluated as one thing |
| `address_status` | required for email — records whether the address was verified or pattern-guessed |
| `delivery` | `delivered` · `bounced` · `unknown`. **Bounces are excluded from every denominator** — a bounce that looks like a non-reply poisons the metric |
| `outcome` | `awaiting` · `replied` · `accepted` · `no-response` · `declined` · `meeting-booked` |
| `message_ref` | points at the full text in `messages.jsonl`, and must resolve |
| `trigger_kind`, `trigger_ref` | what CAUSED this touch — `application`, `reply`, `elapsed` or `manual`, plus the specific application/message/date it points at. See *Triggers and sequences* below |
| `sequence_id`, `sequence_step` | groups this touch into a multi-step play with other outreach and staged drafts under the same `sequence_id`, ordered by `sequence_step` |
| `plan_id`, `play_step` | since 0.49.0 — which plan this touch counts toward, and which play step it satisfies (`reach-insider`, …), or the marker `unresolved` when the touch predates 0.49.0 and can't be assigned a step automatically. Only set on a touch anchored to a role (`opp_id`); a networking touch has no plan to derive one from. See *Plans and plays* above |

#### The object of a touch — who or what it's about, when that's not the recipient

Two more fields, both optional: `object_person_id` and `object_company_id`. Most touches don't
need either — the touch is to the recipient, about the recipient. An **introduction ask** is the
case where that isn't true: you ask person A to introduce you to person B, or into company C. The
touch's `person_id` is still A (who you actually messaged); `object_person_id`/`object_company_id`
name who or what the ask is actually about.

`accepted` — an accepted connection request that drew no reply — is reported on its own line and
never merged into `replied`, because it is a real positive signal that unlocks a better second
touch.

**The reply is a link, not a coincidence of dates.** Since 0.36.0, an inbound message can record
`messages[].answers`, the id of the outbound message it replies to — a key, not a guess from
"same recipient, close date." When a linked reply exists, its date becomes this row's
`responded_on` and, only where the row still read `awaiting` or carried nothing, `outcome`
becomes `replied` — the neutral fact the reply proves. A finer outcome (`accepted`,
`declined`, `meeting-booked`) is a reading of what the reply actually said and stays yours to
set; the link never overwrites one. `responded_on` may never predate this row's own `date`, and a
linked reply with no `responded_on` at all is a validation error, not a silent gap. Two messages
sent the same day can't be told apart by date alone, so a same-day pair is left **unlinked** —
reported, not guessed — for you to link by hand with `answers` once you know which is which.
`messages[].sent_on` and this row's `date`/`responded_on` may all carry a time
(`YYYY-MM-DD HH:MM`) as well as a bare date, for exactly that case.

### What a draft now carries — `**To:**` and `**Brief:**` (since 0.46.0)

Every **open** entry in `outreach/drafts.md` carries two meta lines under its heading:

- `**To:** contact:<id>` — who the draft is for, resolved through `people.jsonl` (following a
  merge if the person was later merged into another record). **Since the 0.48.0 upgrade**, this
  reads the entry's own `**Contact:**` meta line first — a direct statement of who the draft is
  for — and only falls back to the `**Blocked until:** contact:<id>` hold when there is no
  `**Contact:**` line, or it does not resolve. If neither resolves, the line reads the literal
  `**To:** unaddressed`.
- `**Brief:**` — either the literal `none` (nobody has computed a brief for this draft yet)
  or a `brief:<timestamp>-<id>` token citing one row in `data/briefs.jsonl`. That row is what
  `brief.py` computed about the thread — who last wrote, how long it has been, and what the
  mailbox has (and has not) confirmed — the moment it was written. **The ledger row is evidence
  of what the drafter saw, never a source of state**: the engine recomputes the register from
  `data/*.jsonl` and the journal every time a draft is checked, so a citation can go stale (the
  thread moved since) without anyone editing the draft.

Tombstoned entries (`**Status:** SENT …` or `MOOT / DO-NOT-SEND …`) are never stamped — only
open entries carry these lines.

**Upgrading to the release that carries this.** The first session you open after upgrading
stamps every open draft that does not already have both lines: `**To:**` from whatever contact
the entry's own `**Contact:**` line or `**Blocked until:**` hold names (never guessed from the
heading or body otherwise — a wrong recipient is worse than an honestly-counted absence), and
`**Brief:** none` underneath every open entry regardless of whether `**To:**` resolved. It then
computes a real brief for every draft it could address, in bulk, straight from your existing
stores — no mailbox is touched for this step. Running it twice changes nothing the second time.
It also refuses outright, stamping nothing, if it runs before the people/involvements upgrade
(0.44.0) has actually landed on your profile — attributing `**To:**` against a people store that
is not there yet is exactly the wrong-recipient risk this whole feature exists to avoid, so it
waits rather than guesses.

**0.48.0 — a one-time repair, if you upgraded before this fix.** Two bugs in the original
0.46.0 code could leave a draft mis-stamped: it never read a `**Contact:**` line at all (only the
`**Blocked until:**` fallback), and on at least one real profile it ran before 0.44.0 had
actually finished, stamping `**To:** unaddressed` against an empty people store. Both are fixed
at the source now, but an entry already stamped `unaddressed` by the old code would never be
revisited on its own — 0.46.0's own idempotency treats "already stamped" as done forever. The
0.48.0 upgrade runs a one-time, re-runnable pass (`brief.py --restamp`) that finds every entry
still reading `**To:** unaddressed` and re-checks it against the fixed logic; anything that now
resolves — because a `**Contact:**` line was there all along, or because 0.44.0 has since landed
— gets its real `**To:**` line. An entry that still does not resolve is left exactly as it was.

**What that release morning actually looks like**, once the bulk pass has run:

- A draft whose recipient could not be resolved reads `**To:** unaddressed` and needs you to
  fix the hold before it can be briefed at all.
- A draft aimed at someone with no prior thread and no confirmed-empty mailbox check holds as
  `unverified-cold` — it is not sendable until either a mailbox probe confirms the mailbox is
  genuinely empty, or, for someone with no known email address at all, you attest to having
  checked yourself: `brief.py --for contact:<id> --i-checked <date>` (refused if an address on
  file means the engine could have checked itself instead).
- Everything else is briefed and ready to re-check the normal way.

The migration's own summary line names the one command that drains what it could not resolve
on its own: `~/.claude/jobsearch/run brief.py --probe --held` — it walks every held draft and
probes the mailbox for each, promoting whatever it can confirm.

### The working set — what leaves `drafts.md` and where it goes (since 0.47.0)

`drafts.md` used to accumulate every draft you ever staged, sent or not — a sent or moot entry
just sat there with a `**Status:**` line under it, forever. As of 0.47.0 it holds **only what is
still under review**: nothing sent, nothing moot. `precondition.py --prune` (and, once, the
0.47.0 upgrade itself) walks the file and, for every entry whose `**Status:**` reads `SENT` or
`MOOT / DO-NOT-SEND`, does one of two things — nothing is ever simply deleted with no trace:

- **If a matching row already exists** in `data/touches.jsonl`/`messages.jsonl` recording the
  send, the draft's paragraph is just removed — the fact it recorded is already on the record
  elsewhere, so keeping the draft too would be the same fact twice.
- **Otherwise it is relocated**, never dropped: to the named role's `research_log[]` (in
  `data/opportunities.jsonl`) when the entry names one via `**Triggered by: opp:<id>**`, or to
  `data/channels.jsonl`'s `log[]` when the entry addresses only a channel-anchored person with no
  role attached. Either way, the entry's own title and status line become the note on that new
  row, dated from the entry's own `SENT <date>` where it has one, otherwise today.
- **An entry naming neither an opportunity nor a channel-resolvable contact is left exactly where
  it is**, reported as `unresolved` — the one thing this will not do automatically is guess a
  home for it.

**The header above your first entry is now generated, not something you (or an earlier session)
wrote by hand.** It carries an HTML comment marking it as generated and explains the meta-line
grammar; `precondition.py --format` reprints it, and if you ever hand-edit it, the next
`precondition.py --check` calls that out rather than silently accepting the drift. Regenerate it
with `--format` rather than editing it directly.

**Upgrading to 0.47.0** runs this relocation once, automatically, the same session you first open
on that version — every already-terminal entry in your existing `drafts.md` is either deleted (a
row already existed) or relocated, and the file's preamble is replaced with the generated one.
Nothing is lost: `--prune` and the upgrade share the exact same decision about where each entry
goes, so running `--prune` yourself afterward is a no-op unless you have staged and closed out
new drafts since.

### Triggers and sequences — what caused a touch, and multi-step plays

Submitting an application creates work: ask a retained recruiter whether they know the employer,
chase after a week of silence. `trigger_kind`/`trigger_ref` on a touch (or an ask) name
what caused it, so a draft never sits unlinked to the application or reply that generated it:

- `application` → resolves against **this same role's own** applications
- `reply` → resolves against a message you received
- `elapsed` → the date a waiting clock started
- `manual` → you decided this with no recorded cause — carries no ref

A multi-step play — send part A, hold part B until the connection is accepted — used to live only
as prose in a heading. `sequence_id`/`sequence_step` make "which sequences can move today" a real
question, answered by `python3 scripts/trigger.py --sequences`; the hold on a staged step still
lives in the draft's own `**Blocked until:**` line, unchanged — a sequence only groups the steps,
it never adds a second way to spell a hold.

### Applications — places you applied

Deliberately **separate** from outreach, because they are different funnels with different
success measures. An application asks *did anyone respond at all*; outreach asks *did this
person reply*. Collapsing them makes both unmeasurable.

**As of the 0.45.0 upgrade, applications are their own file, `data/applications.jsonl`** — not a
list nested inside the role that filed them. Before 0.45.0, each opportunity's own record carried
its applications as a small array on itself; now every application is one row in its own file,
linked back to its role by `opp_id`. Nothing about what an application means or how you work with
it changed — only where it lives, so "how do my applications with a warm touch compare to bare
ones?" is a query across every application at once, rather than a walk over every role.

| field | what it is |
|---|---|
| `id` | the stable handle a trigger points at (`<opp_id>-a1`, `-a2`, ...). This was called `app_id` before 0.45.0 — the value is unchanged, it is just this file's own id now. **You never mint it yourself**: `record.py` assigns the next number the moment an application is recorded |
| `opp_id` | the role this application is for |
| `date`, `method`, `status` | when and how you applied, and where it stands: `status` runs `not-started` → `started` → `submitted` → `acknowledged` / `rejected` / `advanced` / `withdrawn` / `closed`. `closed` (added 0.47.0) means you gave up on it after ATS silence — see *Endings* below |
| `status_on` | the date the *current* `status` was written (added 0.47.0). `null` on a row from before this field existed — an honest "we don't know when," never a guessed date |
| `url` | the application's own URL, if it has one separate from the posting |
| `req_id` | the employer's own requisition id, where the posting or portal shows one |
| `portal_status`, `portal_confirmed_on` | what the employer's applicant portal shows, and when you last checked it |
| `resume_variant` | the page actually **sent** with this application — distinct from the opportunity's own `resume_variant`, the page *planned* to be sent. A retired variant still resolves here, so outcomes stay attributable to what really went out even after a variant is retired |
| `cover_letter_id` | points at this application's row in `cover_letters.jsonl`, or `null` if there is no letter for it — see *Cover letters* below |
| `notes` | |
| `form_answers` | what you actually answered on the application's own form (salary expectations, reason for leaving, and the like), as `{question_key, question, answer, answered_on}`. `question_key` is a shared slug, so the next form asking the same question surfaces what you answered last time instead of you re-deriving it — and if a later answer to the same question disagrees with an earlier one, that is flagged rather than silently overwritten |

**The number is a handle, not a timeline** — a historical row backfilled after two newer ones
were minted can land on `a3`, so nothing should read it as chronological order. A trigger (an
outreach touch's or an ask's `trigger_ref`) written before the 0.41.0 upgrade used to name an
application by its date, the only handle that existed at the time; that upgrade re-pointed each
of those to the application's `id` wherever the date belonged to exactly one application on the
role, and left a trigger pointing at the date, rather than guessing, wherever two applications
shared it — it still resolves, but only by naming one of the two applications yourself
(`record.py`) does it stop being ambiguous.

**What happens to your existing applications on upgrade.** The 0.45.0 upgrade runs this migration
automatically, the first time you open a session on that version — you don't run anything
yourself. Every application already nested on a role is copied out into `data/applications.jsonl`
as its own row, one for one, keeping its existing handle as the new file's `id`; nothing about
the application itself changes.

Wherever any of the three old fields — `cover_letter`, `cover_letter_attached`, `cover_letter_doc`
— was set on an application, a new row is written to `data/cover_letters.jsonl` carrying those
three values exactly as they were, under their original names, and the application's new
`cover_letter_id` points at it. The migration never invents a status for that letter — see *Cover
letters* below for what "attached" means going forward. As with every migration in this plugin,
the whole thing only ever writes once it has checked its own result is valid; if anything about
your data would make it invalid, nothing is written and you keep exactly what you had before,
with a report of what needs attention first.

### Resume variants — `resume_variants.jsonl`

A declared printed resume. With none declared, `presence/claims.md` (the claim union) doubles as
your single printed resume — the degenerate case, not a different mechanism. Once you declare
one or more variants, each is its own authored markdown file, and each bullet line in it must
appear in the union, verbatim (whitespace normalized), or `resume_variants.py --check` flags it
as drifted.

| field | what it is |
|---|---|
| `id`, `archetype` | a stable slug, and the buyer/audience this page is written for |
| `file` | path to the variant's own markdown file |
| `status` | `active` or `retired` (`retired` requires `retired_on`) |
| `union_sha`, `union_reconciled_on` | a stamp of the claim union at the last reconcile, written by `resume_variants.py --stamp` |
| `surface` | **since 0.50.0 (public #59/#64)** — which destination this variant targets: `print` or `public-profile` (`scripts/surfaces.py` is the one lookup table). A variant declared before this upgrade, or one that never sets it, has no `surface` and reads as `unplaced` — never silently defaulted to `print` |

**Visibility is derived from `surface`, never stored.** A claim can be true, provenanced in the
union, and still not safe to publish — a `print` variant only proves the claim traces back to the
union; a `public-profile` variant additionally requires every printed claim to carry its own
`[public]` tag at the head of its union bullet line (a `[private]`-tagged claim, or one with no
tag at all, is unsafe by default). A union bullet can carry both: a `[private]` line nested
directly under the `[public]` version of the same claim is that claim's original wording paired
with its reviewed, public-safe rewrite.

`resume_variants.py --check` reports one of these states per variant: `ok` · `stale` · `drifted`
· `no-claims` · `unstamped` · `missing-file` · `unreadable` · `unplaced` (no recognized
`surface`) · `private-on-public` (a `public-profile` variant printing an untagged or
`[private]`-tagged claim) · `retired`. `unplaced` and `private-on-public` both fail the check —
neither is ever read as "print, probably" or "private, probably."

**What happened to every existing variant on the 0.50.0 upgrade.** `m_0_50_0_variant_surface_field`
seeds `surface: "print"` onto every row that predates this field — every printed variant that
existed before 0.50.0 was, in fact, a print page, so the migration records that rather than
leaving the field unset (which would read as `unplaced`, a state that did not describe those
rows' actual history).

### Cover letters — `cover_letters.jsonl`

`resume_variants.jsonl`'s twin, introduced by the 0.45.0 upgrade described above. Before it, the
only structured facts about a cover letter lived inline on the application itself
(`cover_letter`, `cover_letter_attached`, `cover_letter_doc`) — pointer, submitted-or-not, and
rendered file, with no row of its own to hang a status on.

| field | what it is |
|---|---|
| `id` | stable handle, `<application id>-cl` |
| `opp_id` | the role the letter was written for |
| `file` | where the authored text lives — an anchor into `applying/cover_letters.md` |
| `doc` | the rendered file actually sent, once one exists |
| `status` | the value stored on the row: `draft` · `sent` · `retired` — or `null` on a legacy or migration-minted row the store never assigned a status to. This is not the same as the state you see reported below |
| `created` | when the row was created |
| `note` | |
| `cover_letter`, `cover_letter_attached`, `cover_letter_doc` | the three original fields, carried over **verbatim** by the 0.45.0 upgrade for any letter that predates it — including a row where they disagree with each other (e.g. `cover_letter_attached: true` with no `cover_letter_doc`), preserved exactly as found rather than resolved or guessed at. A letter created after the upgrade uses `file`/`doc`/`status` instead and leaves these three `null` |

**"Attached" is now a structural fact, not a separate flag to remember.** A letter is attached to
an application exactly when that application's `cover_letter_id` is non-null — there is no second
boolean that can drift out of sync with whether the row actually exists.

**What you actually see reported is a derived state, not the stored `status` above** — the
terminal cascade (since 0.50.0, public #95). A pending letter whose role has since ended reads
`moot`, not `draft` or `pending` — nothing will ever attach it now. A letter that some application
actually submitted reads `used` — permanently, even if that application is later rejected: "we
sent this" never gets relabeled just because the pursuit ended. The stored literals `sent` and
`retired` still read as themselves when neither of the above applies, and a `null` stored
`status` reads as **unrecorded** rather than `draft` — a missing status never asserts that
drafting actually happened.

Nothing on disk changes shape for this — it is a pure derivation, no migration accompanies it.
The one place you actually see its effect is a checkup line counting how many letters now read
`moot` this way, alongside the equivalent count for a touch whose role has ended
(`data/touches.jsonl`, derived the same way by `your_move.touch_state()`).

### Fit — how you match the role

Optional. Absent means the job description has not been analysed yet.

Each material requirement from the posting becomes a row: the requirement in the posting's own
words, a verdict of `aligned` · `partial` · `not-aligned` · `unknown`, and then:

- **`evidence`** — required when aligned or partial. A pointer to the resume sentence, project
  or note that backs the claim. An alignment claim with no citation is a gap in disguise.
- **`pitch_line`** — how to *present* that match, so your positioning is not reinvented for
  every draft.
- **`question_for_candidate`** — required when `unknown`. A targeted question, asked only when
  the answer would change the pitch.
- **`landed_in`** — where your answer was filed, so the same question is never asked twice.

`not-aligned` rows are kept, not suppressed. They tell you where you are stretching, and a fit
analysis that lists only matches is marketing rather than analysis.

Counts are always **computed** from these rows, never stored.

## Asks and commitments — what is waiting on you, and what is scheduled

These two files back the "needs you" and "this week" views on your dashboard. Both are one
record per line, same as the other datasets, and both exist so those views are computed from
data rather than kept up to date by hand.

**`asks.jsonl`** — anything waiting on a decision or action from you.

| field | what it is |
|---|---|
| `kind` | `role` (about one opportunity) or `system` (tooling, a credential, a setting — for example `system-application-endings`, the one row naming every ended pursuit with no recorded ending, described under *Endings* above) — decides which group it shows in |
| `title`, `ask` | what it is, and what is actually being asked |
| `opp_id` | the role it concerns, if any |
| `resolved_on`, `resolution` | set together, once, when it is answered |
| `trigger_kind`, `trigger_ref` | what CAUSED this ask, same as an outreach touch above — `trigger_kind: application` additionally requires `opp_id`, since resolving it means reading that role's own applications |

**An ask disappears from every view the moment it is resolved** — resolving it is what removes
it, not editing its text into a "done" line in place. The row itself stays as history.

**Since 0.50.0, `asks.jsonl` is writable through `record.py`**, the same tool you already use for
everything else — before this, an ask row could only ever be created by a migration.

**`commitments.jsonl`** — things scheduled on a date: a call, a deadline, a follow-up.

| field | what it is |
|---|---|
| `date` | ISO `YYYY-MM-DD`, or the literal `unresolved` if a date could not be read from its source and needs your eyes |
| `title`, `note` | what it is |
| `opp_id` | the role it concerns, if any |
| `status` | `scheduled` or `cancelled` — every commitment starts `scheduled`; a called-off meeting is set to `cancelled` rather than deleted or edited into a "cancelled" title |

Only commitments on or after today show on your dashboard; past ones stay in the file as a
record rather than being deleted. **A `cancelled` commitment is excluded from the This Week
list and the prep-owed report regardless of its date** — cancelling is terminal, the same way
an expired opportunity leaves the active pipeline view.

---

## ATS receipt matching — `config.json.ats`

Not a dataset and not one of the documents above — a small settings block inside `config.json`,
at your profile root (`config.json` itself is not part of the six-phase move; see *the documents*
table above). It exists to let something read your inbox and recognize an applicant-tracking
system's automated emails: an acknowledgment, a rejection, an advance to the next round.

| key | what it is |
|---|---|
| `receipt_sender_domains` | the domains your ATSes actually send receipts from — for example `["greenhouse-mail.io", "myworkday.com"]` (both fictional; put your own ATSes' real sending domains here, not these) |
| `status_phrases` | subject-line phrases that evidence a status, grouped by which one: `{acknowledged: [...], rejected: [...], advanced: [...]}` |
| `silence_days` | since 0.47.0 — how many days of ATS silence, measured to your verified mailbox coverage (never to today), before `check_followups.py` proposes closing an application. Defaults to **30**; seeded onto every existing profile by the 0.47.0 upgrade if you had not already set it |
| `close` | since 0.47.0 — `propose` (the default: the run only proposes a close, you confirm it) or `auto` (the run writes the close itself). Also seeded to its default, `propose`, by the 0.47.0 upgrade |
| `parsed_status` | since 0.50.0 — `receipt-grade` (the default), `propose`, or `all`. Governs the deterministic ATS sweep (`reconcile.py --ats`, below): whether a resolution is written straight to the record or only proposed for you to confirm, by how confident the match is |
| `sweep_days` | since 0.50.0 — the floor, in days, the sweep uses when it asks your mailbox to look back. Defaults to **3**; the sweep widens this automatically when it finds a coverage gap, never narrows it |
| `max_asks_per_run` | since 0.50.0 — how many asks the sweep will write in one run before holding the rest back for the next run. Defaults to **5**. Applied resolutions (the ones confident enough to write straight to the record) are never capped — only the ones that need your decision are |

`receipt_sender_domains` and `status_phrases` both start **empty** on a fresh profile. **Nothing
in the plugin reads either of those two automatically yet — filling them in has no visible effect
today.** They exist so your profile already carries this information, in the right shape, for the
ATS-receipt reader this scaffolding is built for; once that reader ships, an empty
`status_phrases.rejected` will mean "I have no way to recognize a rejection from mail," not "no
rejections have arrived" — worth knowing now, since filling these in today is exactly what gets
your profile ready for that day. Match strings are your own words — whatever your ATSes' actual
subject lines say — not a fixed vocabulary the plugin ships with.

**`silence_days` and `close`, unlike those two, are read today** — `check_followups.py` uses them
to decide when a stalled application is worth proposing as `closed`, so a value you set here has
a visible effect the next run after you change it.

**The deterministic ATS sweep — since 0.50.0.** `reconcile.py --ats` identifies an ATS's
automated mail by sender domain, then resolves it to a specific application through three
checks, in order, stopping on the first hit or a tie: a requisition id, an application URL, or
(when only one open application at that company could match) the company name alone. The first
two are receipt-grade and, by default (`parsed_status: receipt-grade`), written straight to the
application's record; the third is always a lower-confidence match and only ever *proposed* as
an ask for you to confirm, unless you set `parsed_status` to `all`. `sweep_days` and
`max_asks_per_run` are the two knobs on how far back it looks and how many asks it will hand you
in one sitting — both above. `parsed_status`, `sweep_days` and `max_asks_per_run` were seeded
onto every existing profile, absent-only, by the 0.50.0 upgrade. Every resolution the sweep makes
is recorded on the inbound message itself — `messages.jsonl`'s `resolves` (the application it
resolves) and `resolved_by` (which of the three checks decided it) — not only on the
application, so you can always trace a status change back to the specific email that caused it.

**Renamed in 0.41.0.** Earlier versions of the scaffold seeded this block as `ats.sender_domains`
and `ats.receipt_phrases` (one flat list, which could only ever mean "acknowledged"); every
profile that had actually filled the setting in, though, used `receipt_sender_domains` and
`receipt_subject_phrases` — two spellings of the same thing, split between what got scaffolded
and what people actually typed. The 0.41.0 upgrade renamed the scaffold's names to the ones
profiles were already using. If your `config.json` happened to carry both spellings — you added
the new name by hand while the old scaffolded one still sat there — the two lists were merged in
order, nothing dropped. Your existing `receipt_subject_phrases` list moved into
`status_phrases.acknowledged`, since that is the only status it could have meant; `rejected` and
`advanced` were seeded empty for you to fill in if you want those recognized too.

---

## LinkedIn — `config.json.linkedin`

A small settings block governing how the LinkedIn runner recovers from a stalled Browser pane
(since 0.50.0, public #47/#96).

| key | what it is |
|---|---|
| `pane_stale_minutes` | how many minutes a taken-but-never-released pane lock is trusted to mean "a run is genuinely still using it" before the next run treats it as abandoned and takes over. Defaults to **90** |

**This default is stated honestly as unverified**, not as a measured figure: no real pass
duration exists anywhere in this plugin's own history to derive it from. `journal.py
--pass-durations` prints every run's actual wall-clock length, so you can set this key from your
own real numbers once you have a few runs to look at, rather than trusting the placeholder.
Staleness itself is checked two ways, in order — first whether the run that took the lock has
actually ended (visible in the journal), and only when that is silent does the age threshold
above apply — so a crashed run is recovered by the journal check well before this timer would
otherwise matter.

## Geography — `config.json.geography`

A settings section a screening reader consults to decide whether a role's location works for
you (since 0.50.0, public #89).

| key | what it is |
|---|---|
| `remote_ok` | whether a fully-remote posting screens as usable at all. Defaults to **true** |
| `relocation.open` | whether a metro that is neither a commute anchor nor an affirmative destination (below) still screens as workable. Defaults to **false** — silence is never read as "open to relocating anywhere" |
| `relocation.affirmative_destinations` | metros you have explicitly said yes to, regardless of `relocation.open` |
| `commute_anchors` | places you can actually commute to, each with its own `max_commute_minutes` |

Screening one location produces exactly one of six verdicts, each citing the specific key that
decided it: `remote`, `commute` (names a commute anchor), `affirmative` (names an affirmative
destination), `relocation-ok` (`relocation.open` is true and nothing more specific matched),
`out` (`relocation.open` is false and nothing matched — the one verdict that ends a role's
consideration, reached only through an explicit or default-but-registered key, never through
silence), or `unknown` (your `config.json` has no `geography` section at all — different from an
unset key, which always has a registered default).

**Renamed by the 0.50.0 upgrade, the same defect one config section over as `ats`'s 0.41.0
rename.** `init_profile.py` used to scaffold this section as `geography.relocation_open_to` /
`geography.radius_minutes`, but every profile actually derived from a resume ended up with the
shape documented above instead — two spellings of one meaning, with nothing ever reading the
scaffolded names. `m_0_50_0_geography_keys` rewrites a profile still carrying the old names into
the shape above; nothing is dropped in the process.

## Sourcing — `config.json.sourcing`

Another small settings block at your profile root, alongside `ats` above — this one about **how**
a role was found, rather than the application's own clock.

| key | what it is |
|---|---|
| `linkless_grace_days` | since 0.48.0 — how many days a board/aggregator sighting with no link gets before it is named in the SOURCING advisory below. Defaults to **3** |

**The SOURCING advisory (since 0.48.0).** `doctor.py` now warns, at the start of every run, about
an opportunity that was sighted on a job board or aggregator but never recorded a link to the
posting (`jd_url`, or a sighting's own `source_url`) — once that posting comes down, there is no
way to ever recover it. Three shapes are excluded **by rule**, never by a guess:

- **recruiter-sourced** — the role's channel (or any of its sightings' channels) is a recruiting
  firm. There was never a public posting to link.
- **receipt-backed** — you have a submitted application on record for this role. The application
  itself is durable evidence the role existed, with or without the link.
- **too fresh** — every board/aggregator sighting is younger than `linkless_grace_days` above, so
  a research or backfill pass simply hasn't had the chance to fill the link in yet.

A role with no board/aggregator sighting at all — recruiter-only, company-site-only — is out of
scope entirely; it was never going to carry a public link, so its absence is not this advisory's
business. The advisory is a warning, never a hard failure: it names the gap so you can fill it
before the posting disappears, and does nothing on its own.

**Since 0.50.0 (public #83 rule 1), a NEW sighting is no longer just advised — it can be
refused.** Recording a sighting from a URL-bearing channel (a job board or aggregator) with no
`source_url` at the moment you capture it is refused outright by `record.py`, unless the
sighting is recruiter-sourced or receipt-backed (the same two exclusions the advisory itself
uses). And `validate_data.py` now hard-fails, as a PROBLEM rather than an advisory line, any
linkless URL-bearing sighting dated on or after **2026-09-14**. The SOURCING advisory above has
narrowed to match: it now names only sightings dated *before* that line — a sighting recorded
since then that is missing its link is the validator's problem to report, not the advisory's,
because it should never have been possible to record one that way in the first place.

---

## focus.md is retired

Earlier versions kept a hand-maintained file, `focus.md`, listing what needed your attention and
what was scheduled that week. It caused a real problem: an item copied into it by hand could go
stale sitting next to the same information generated fresh from your data, and nothing caught
the two disagreeing.

If you are upgrading from an older version, this happened to your profile automatically, once,
the first time you used it after the update:

- Anything under **Your Move** or **Process — Needs the candidate** moved into `asks.jsonl`.
- Anything under **This Week** moved into `commitments.jsonl`. A date that could not be read
  mechanically was written as `unresolved` rather than guessed — look for that value and set the
  real date once you know it.
- The **Session Handoff** note moved into `handoff.md`, unchanged.
- Anything else with real content was appended to `process_archive.md`, so nothing you had
  written was discarded.
- `focus.md` itself became a short stub naming where its content went. Nothing reads or writes
  it anymore, and it is safe to delete once you have confirmed the above.

Nothing in this file was silently dropped — every line either has a new home or is sitting in
`process_archive.md`, and the migration will not touch `focus.md` at all if anything about the
move could not be verified, so you never end up with content missing from both places.

**Starting with 0.32.0**, the stub itself and `process_archive.md` move again, along with
everything else in [the documents table above](#the-documents): `focus.md` →
`archive/retired-trackers/focus.md`, `process_archive.md` → `archive/process_archive.md`. Same
automatic, no-action-needed move as the rest of the tree.

---

## Editing by hand

You can. The formats exist to be readable and diffable. Two habits make it safe:

**Validate after editing.** A validator checks the whole profile: that every company and channel
reference resolves, that enum values are in range, that `comp.min ≤ comp.max`, that dates are
ISO `YYYY-MM-DD`, that slugs are unique, and that required fields are present rather than
missing.

**Unknown keys are rejected.** If you misspell a field name the validator refuses it rather than
silently ignoring it. Aliases drifted into the data historically precisely because nothing
rejected them.

Two nuances worth knowing:

- Newly required fields apply only to records dated after they were introduced. Older rows are
  explicitly grandfathered rather than failing the validator on day one.
- `unknown` is a legitimate value, not a gap. It makes the hole countable.

---

## `.jobsearch/` — engine state, not your data

Since 0.26.0 your profile directory also contains a `.jobsearch/` folder, created the first time
you run the plugin after upgrading. It holds two things the plugin keeps for itself: a
diagnostics log (a record of what the last few runs actually did — used to tell "nothing
happened" apart from "something failed silently") and a small set of internal drift markers used
to detect when your profile has fallen behind the installed plugin version.

**You do not need to open it, and there is nothing there worth reading.** Every value it stores
is a timestamp, an event name, a version number, or a count — never a company, a contact, a
message, a comp figure, or any other fact about your search. The code that writes to it only
accepts values shaped like short codes and discards anything that looks like free text, so this
holds even if a bug elsewhere tried to write something it shouldn't.

**It is not committed to git.** The same upgrade that created the folder added `.jobsearch/` to
your profile's `.gitignore` automatically — this state is specific to the machine it runs on,
and committing it would just add churn to every commit for no benefit.

**Where it used to live:** earlier versions kept this same information in one shared location,
`~/.claude/jobsearch/`, outside any profile. That was fine with one profile on one machine, but
it meant two different profiles on the same machine wrote into the same file with no way to tell
their histories apart. If you are upgrading from an older version, the move happened
automatically the first time you ran the plugin after updating: your existing diagnostics
history and drift markers were copied into this profile's `.jobsearch/`, and removed from the
old shared location only after the copy was verified — nothing is discarded if that verification
fails, it simply retries on your next run. `~/.claude/jobsearch/` still exists after the move; it
now holds only the three things needed to find your profile and the installed plugin before
either has been located — the run launcher and two locator pointers — nothing about your search
itself.

---

## Backups

Your profile is yours and lives outside the plugin. Nothing the plugin updates will touch it
except the data-format migrations, which run automatically, preserve content before transforming
it, and are safe to run twice.

Putting your profile directory in a **private** git repository is the recommended backup — you
get history and a diff of every change your search makes.
