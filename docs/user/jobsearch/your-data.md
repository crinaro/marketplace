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
| `involvements.jsonl` | how each person connects to a role or a channel — since 0.44.0, alongside `people.jsonl`. **Not purely hand-set**: since 0.54.0 (dev #479), `record.py touched`/`answered` auto-upserts the recipient's involvements row (`status`, `path_type`) from the touch itself — see *Touches* below |
| `applications.jsonl` | every application you have submitted, once each — see *Applications* below (since 0.45.0; before that, applications lived nested on the role) |
| `cover_letters.jsonl` | the link between an application and its cover letter — since 0.45.0, alongside `applications.jsonl`, see *Cover letters* below |
| `touches.jsonl` | every outreach touch you have made, once each — see *Touches* below (since 0.48.0; before that, touches lived nested on the role as `outreach[]`) |
| `asks.jsonl` | things waiting on you — a role decision or a piece of system upkeep |
| `commitments.jsonl` | what is scheduled — calls, deadlines, follow-ups due on a date |
| `briefs.jsonl` | since 0.46.0 — the append-only ledger of what a draft's `**Brief:**` line cites; see *What a draft now carries* and *The brief ledger* below. Never edit this by hand and never read it as "the current state of a thread" — it is evidence of what a computation SAW at drafting time, not a source of state |
| `resume_variants.jsonl` | the declared printed-resume set — since 0.39.0 (public #26); see *Resume variants* below |
| `pending_actions.jsonl` | work a run found but did not do, queued for the next run that can — a role to capture, research to run, a draft to write, the owed LinkedIn pass. Script-written; see *Deferred items* below |

### The documents

**Starting with 0.32.0, these live inside six phase directories** — `presence/`, `configure/`,
`pipeline/`, `applying/`, `conversations/`, `outreach/` — rather than loose at the profile root.
This happens automatically, the first time you open a session after upgrading; you do nothing to
trigger it, and the paths below are what you will have once it has. `config.json`, `user.json`,
`data/` and `docs/` are not part of the move and stay exactly where they are. (One part of `config.json` gets its own section below: [ATS receipt
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
| `archive/retired-trackers/dashboard.html` | retired. The profile root used to carry a generated `dashboard.html` tombstone stub, rewritten every run; the generator no longer writes it and the upgrade **moves** any existing one here. See [Reading what the search produces](reading-your-files.md) for where the dashboard and its URL actually live |
| `presence/resumes/*.docx` | rendered printed resumes, one per variant you have asked to be rendered. Older profiles wrote these to a bare `resumes/` at the profile root; the upgrade moves them here, and a profile with its own `local_dir` set in `config.json` keeps that |
| `views/dashboard_artifact.html` | **the one generated, published page** — since 0.71.0 only what is waiting on a decision from you: *Drafts to review* (staged messages in full, touches due, people due), *Opportunities to pursue* (a pursue-or-pass decision is owed) and *Applications to finish* (roles you are pursuing, with their cover letters), plus a short summary linking to each. **Every record is shown in full in exactly one list, and appears anywhere else only as a one-line reference linking to it.** Roles in flight, the week, asks, channels and call preps are in the status pane (`/jobsearch:status`), not on the page; what each list holds is in [Reading what the search produces](reading-your-files.md). Generated from your files on every run, so an edit to the page itself never reaches them |
| `views/presence_set.html`, `views/presence_set_ledger.json` | **retired in 0.71.0.** The second published page (0.39.0 to 0.70.0) is gone; its review is `/jobsearch:review-resume` and `/jobsearch:review-linkedin`. The upgrade deletes these two generated files, which the engine rebuilds from `presence/` on demand, so nothing of yours is lost. `views/presence_set_url.txt`, if present, is kept only until the "this page is retired" note is confirmed published at that address, then removed |
| `views/applying.md` | generated, **read-only**, regenerated in session (not by the scheduled runs) — the working queue: roles to apply to and the follow-up work a submission created |
| `views/conversations.md` | generated, **read-only**, regenerated by the **scheduled runs** (daily/weekly) — what each upcoming call still needs: whether its prep is written, and a `PREP OWED` row when it isn't |
| `presence/rules.md` | **authored, not generated** — settled decisions about the claim union and the open-items categories shown on the *Rules* tab of the resume and LinkedIn reviews. Created once, seeded with three starting rules, by the 0.39.0 upgrade; yours to extend |

Every generated file above (everything under `views/`) is overwritten **every
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
| `name`, `aliases` | display name, plus other names it gets listed under. `aliases` is a list of non-empty strings; since 0.73.0 `record.py set` can write it, and the validator refuses a bare string |
| `vertical` | the sector, used for tiering and search targeting |
| `size` | how big the company is and who owns it — e.g. public, PE-backed, employee count. Context for whether the role is a fit; free text |
| `hq` | where it is headquartered, as you would say it (a city, or `Remote` for a remote-first company). Free text, and `null` when you do not know |
| `domain` | since 0.73.0 declared — the company's primary web domain, a non-empty string, or `null` when unknown |
| `size_ownership` | since 0.73.0 declared — free text on ownership and scale, e.g. "public, large" or "PE-backed". A non-empty string. No script reads it yet; it is context for you. `size` (above) is the separate field the mandate matcher reads |
| `career_url` | its own careers page; setting this makes the company reviewable as its own channel. Since 0.73.0 declared, so `record.py set` can write it: a non-empty string or `null` |
| `status` | `active-target` · `watching` · `passed` |
| `research_log` | append-only notes; company-level findings go here, not on each role |
| `note` | free text of your own about the company as a whole — a remark that is not a dated finding (those go in `research_log`) |
| `ats` | since 0.72.0 — the company's public job-board feed, so the daily run can read its openings with a script instead of a browser turn. Three states: **absent** (no feed found yet), **`null`** (you declined a feed for this company; nothing rewrites it) and **an object** `{vendor, slug, region, source, since}`. `vendor` is `greenhouse`, `lever` or `ashby`; `slug` is the board's short name; `region` (`global` or `eu`) is required for Lever only. **Since 0.76.0** a fourth vendor, `workday`, has the shape `{vendor, tenant, wd, site, source, since}` instead, with no `slug` and no `region`: `tenant` and `wd` are the two parts of the company's `<tenant>.wd<N>.myworkdayjobs.com` address and `site` is the career site's name.  `source` says how it was found (`career-url`, `posting-url` or `candidate`). Set it, decline it or clear it with `record.py ats` (see *Company feeds* in [How it works](how-it-works.md)) |
| `backed_by` | since 0.75.0, optional: a list of company ids of the firms that back this company (an investment firm is an ordinary company row). Use it to state a backing a board sighting cannot show. A non-empty list of non-empty strings, each naming a company you track, never the company's own id, no repeats. Where a role was seen on a firm's portfolio board, the firm link is worked out from that sighting and is not stored. People you know at a backing firm become a `backer-intro` route on the role card, see *Portfolio boards* in [How it works](how-it-works.md) |
| `warm_lookup` | since 0.72.0 — `{on, result}` where `result` is always `none-found`: you looked for a person at this company and found nobody. It is the one stored fact of the warm path; everything else a role card shows about it is worked out from your people, touches, drafts and applications. Absent means you have not looked. Written by `record.py warm-lookup <company_id> --none-found` |

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
| `label` | the display name you see everywhere the channel is listed (the engine keys on `id`; `label` is the name for you to read) |
| `scope_notes` | which titles, filters and locations this channel covers |
| `next_touch` | a relationship call or reconnect you have planned with this channel, as `{date, time, note}` — not tied to any role. Once its `date` arrives it joins the channels-due queue beside anything overdue on `review_cadence`, so a planned touch surfaces on the day without you setting a reminder elsewhere |
| `access` | how it is reached — see below |
| `relationship_status`, `log` | for firms and referrals: where you stand, and the thread history — each `log` entry is a dated line, `log[].date` and `log[].note`. Who you know there is a person, not a field on the channel — see *People* below |
| `portfolio_of` | since 0.75.0, on a portfolio job board only: the id of the company row for the investment firm that publishes it. The channel must be a `job-board` with `access: manual-candidate` and a calendar `review_cadence` (`daily`, `weekly`, `biweekly` or `monthly`), and it needs `board_hosts`. See *Portfolio boards* in [How it works](how-it-works.md) |
| `board_hosts` | since 0.75.0, on a `manual-candidate` channel only: a non-empty list of distinct bare host names (for example `jobs.example.org`) that the engine must never open. A role whose every address is on one of these hosts, or on a subdomain of one, is not read by a run: it is recorded `not read: manual-board`, and you read it |
| `board_url` | since 0.76.0, optional, on a `manual-candidate` channel: the address of the board's front page, which **you** open. The engine never visits it. A channel turned on from the shipped catalog carries it; one you write by hand may omit it. Must be an `https://` address with no port whose host is covered by the channel's `board_hosts` |
| `channel_catalog_entry` | since 0.76.0, a catalog stamp: the id of the shipped catalog entry this channel was turned on from (`record.py channel-catalog add`). A channel you wrote by hand has no stamp, and the plugin never changes it |
| `channel_catalog_sha` | since 0.76.0, part of the stamp: a short fingerprint (12 hex characters) of the catalog-managed fields of the channel as the catalog last set or you last accepted them. Which fields are managed depends on the source's kind (a manual board: `label`, `type`, `access`, `board_url`, `board_hosts`; an alert sender: `label`, `type`, `access`, `alert_sender`; a browser-read board: `label`, `type`, `access`, `query_template`), and whether the channel is retired always counts. Comparing it to the row is how the plugin tells whether you edited those fields. It is never edited by hand |
| `channel_catalog_on` | since 0.76.0, part of the stamp: the date the catalog values were last applied or acknowledged |
| `query_template` | since 0.76.0, on a channel turned on from a browser-read catalog entry only (the Indeed sweep): the search wording the run uses, stored **unfilled**, with placeholders where your profile's titles and locations go. It is filled from your profile at the moment it is shown, when `record.py source on` prints "this will search: ..." and when the routing step prints the query, so a change to your profile reaches the search without editing the channel. You can see the filled text any time with `record.py source on <id> --dry-run` |
| `prior_relationship_status` | since 0.76.0, written by `record.py source off`: what the channel's `relationship_status` was before it was turned off, as `{had: false}` (it had none) or `{had: true, value: ...}`. `record.py source on` puts exactly that back and removes this field, so off then on returns the row to how it was. It is never edited by hand |
| `channel_catalog_rev` | since 0.76.0, part of the stamp: the catalog revision that wrote the stamp. An update is applied only from a strictly newer revision, so two plugin versions sharing one profile never undo each other; a channel stamped by a newer revision than the installed catalog is left untouched |
| `alert_sender` | for a channel that sends alert-digest emails (a board or aggregator): the Gmail search fragment for its own From address, e.g. `from:indeed`. Absent on a channel with nothing to sweep — a recruiter, a channel you only check by hand — which is correct, not a gap |
| `company_id` | since 0.72.0 — on a `company-site` channel only: the company whose careers page this channel is. It must name a company you track, a company has at most one such channel, and a company with an `ats` feed must have exactly one (the feed's roles are recorded against it). A company-site channel without it is just an unlinked careers page; `feed_poll.py --status` lists those |

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
- `manual-candidate` — you review it yourself: a site whose terms forbid automated access. The engine never visits it; the review list shows it under **for you to open**, and only its alert email (if you set `alert_sender`) is read. Since 0.72.0 the sourcing routes know this value too
- `human` — a recruiter or a referral
- `n/a`

## Opportunities — the roles

The main record. Everything about one role hangs off it.

| field | what it is |
|---|---|
| `id` | a short stable slug — what a touch, an application or a message means by its `opp_id` |
| `company_id` | must resolve to a company |
| `title` | |
| `comp` | `{min, max, period, basis}` as **typed numbers**, so it sorts and screens. `null` if genuinely undisclosed — never a guess |
| `location` | `{type, primary, remote, declared}` — see *contested settings* below. Since 0.70.0 `type` may be left out when the posting stated no setting and no place could be read, and `setting_source: inferred` marks an `onsite` the system filled in from a concrete place — see *Where a role is, and when it is too far* below. Since 0.67.0 `declared` also holds the work setting *as the posting wrote it* on every role that reaches your decision, and a role may carry `commute_minutes` — see *Listed pay, posting age, the screen and the lean* below |
| `listed_pay` | since 0.67.0 — the pay the **listing** showed, with whether the employer stated it, a board estimated it, or none was shown. Absent means *not captured* — see *Listed pay, posting age, the screen and the lean* below |
| `posted` | since 0.67.0 — when the role was posted, and how we know. Absent means the age is unknown |
| `screen` | since 0.67.0 — the hard screens the engine applied to the role, and their verdict, written by the script that ran them. Since 0.69.0 it also carries `title_keys`, a short fingerprint of the title settings it was computed under (see *The title floor and the mandate* below). Since 0.73.0 it also carries `comp_keys`, a fingerprint of the pay inputs it ran under, and `engagement_source: inferred` when the pay was routed on an engagement read from the title (see *The pay re-screen* below) |
| `lean` | since 0.67.0 — the system's read of the role (`pursue` · `pass` · `ask`) with a one-line reason. A lean is advice; it never removes a role |
| `status` | what you are **doing** about it |
| `stage` | where it **is** in the funnel |
| `passed_from` | since 0.69.0, only on a role whose `status` is `passed` — `{status, stage}`, where the role stood when you passed on it, kept so that `pursue` or `park` can put it back. See *A pass on a backlog role is final* below. Absent on every other role |
| `verdict` | `pursue` · `pass` · `parked` · `undecided` |
| `duplicate_of` | since 0.70.0, only on a row you folded into another with `record.py link-sibling` — the id of the row that stands for the same requisition. A folded row carries no decision of its own and leaves the undecided list. Absent on every other role |
| `distinct_from` | since 0.70.0, optional — ids of rows you recorded as a *different* role (a merge you undid, or a role you created anyway with `--force`), so the matcher never joins that pair again |
| `engagement_type` | `full-time` · `contract` · `fractional` · `interim` · `advisory` — since 0.45.0 (the last three since 0.73.0); the 0.45.0 upgrade set this to `full-time` on every existing role, since that fact about a role isn't derivable from anything else on the record. Since 0.73.0 the pay screen reads it. **A value you recorded always wins**, `full-time` included: a role titled "Fractional CTO" with `full-time` stored is screened against your annual floors. With no value recorded, a closed list of title words infers one (fractional, vCIO/vCTO and similar, interim, advisor, contract) and the screen line says it was inferred. A value outside the list screens `PAY-UNCOMPARABLE`. Older roles may need it set: `record.py set <id> engagement_type <value>` |
| `jd_url` | the posting. Required as a URL **or an explicit `null`** — never simply missing |
| `channel_id` | the channel that *represents* the role as a whole — typically the recruiting firm running the search. `null` when no single channel does. Distinct from a sighting's own `channel_id` below, which records each place the role was merely seen |
| `sightings` | every time this role was seen, and where: one entry per sighting, `{channel_id, seen_on, snippet, source_url}` — `channel_id` is the source it turned up on, `seen_on` the date, `snippet` a short excerpt of how the listing read at the time, and `source_url` the link to that listing (see *Sourcing* below for when the link becomes mandatory). Since 0.70.0 a sighting may also carry `location` (the place that listing put the role at, as written) and `split_to` (the id of the row that listing was split away to, after an undone merge — a split sighting no longer counts as evidence for this row) |
| `plan_id`, `plan_assigned_on` | which plan (see *Plans and plays* below) is working this role, and since when — every role has one, since 0.49.0 |
| `next_action_date`, `next_action_owner` | when the next thing happens, and whose move it is — *which* thing is now the plan's job (see below). **Not purely hand-set**: since 0.54.0 (dev #479), recording an outbound touch as `touched`/`answered` (`record.py`) clears these off you automatically when that touch already answers what you were waiting on — see *Touches* below |
| `blocked_until` | a precondition that makes a role yours *in name only* until someone else moves — written as `contact:<person_id> outcome:<value>`, for example waiting on a referral's reply. Your Move does not treat the role as waiting on you until the condition is met; the literal `unresolved` (or a value that will not parse) is reported loudly rather than read as "no precondition". It resolves only against touches on **this** role, never another role's |
| `research_log` | append-only role history — each entry is a `research_log[].date` with its `research_log[].note`, plus optionally `find` (what a research step went looking for) and `result` (what it turned up). Recording the step even when it found nobody is what lets a later check tell *nobody found* apart from *nobody looked* |
| `fit` | your match against the posting's requirements — see *Fit* below. Absent until the job description has been analysed |
| `decision` | `{on, suggested, reason_kind, reason}`, since 0.47.0 — see *Recording why a decision diverged* below |
| `networking_closed_on` | the date you decided to stop working the network on this role, since 0.47.0 — see *Endings* below |
| `resume_variant` | the printed-resume variant *planned* to be sent for this role, by its `id` in `resume_variants.jsonl` (see *Resume variants* below) — distinct from the one an application actually sent, which is recorded on the application. It must name a declared, **active** variant: a retired one is refused here |
| `note` | free text of your own about the role. The 0.49.0 upgrade moved any old free-text `next_action` here, prefixed so you can find it |

### `status` and `stage` are different questions

This is the one thing people mix up, so it is worth stating plainly:

- **`status`** = what you are doing about it → `active-pursuit` · `needs-resolution` · `in-motion` · `backlog` · `passed` · `expired`
- **`stage`** = where it sits in the funnel → `sourced` · `contacted` · `screening` · `interviewing` · `offer` · `closed`

They are orthogonal and you want both. A live pursuit waiting on a recruiter is
`status: active-pursuit`, `stage: contacted`. A role you have shelved is `status: backlog`,
`verdict: parked`, `stage: sourced`.

### A pass on a backlog role is final — since 0.69.0

Passing on a role you had only sourced (`record.py decide <role> pass`) now ends it in the same
write: `status: passed`, `stage: closed`, and `passed_from` holds the status and stage it had, for
example `{"status": "backlog", "stage": "sourced"}`. Before 0.69.0 the pass was recorded as
`verdict: pass` but the role stayed `status: backlog`, so the rest of the system still saw a live
backlog role. A pass on a role you are already pursuing is unchanged.

**Changing your mind.** `record.py decide <role> pursue` or `park` on a `passed` role that has a
`passed_from` puts `status` and `stage` back as they were and removes `passed_from`. A `passed`
role with no `passed_from` (passed some other way) is not guessed at: it is left as it is.

**Roles you had already passed.** The 0.69.0 upgrade runs the migration
`m_0_69_0_passed_backlog_terminal` once. Every role with `verdict: pass` that was still at
`status: backlog` becomes `passed` at `closed`, with `passed_from` recording what it was. Before it
writes anything it copies `data/opportunities.jsonl` to `data/opportunities.jsonl.pre-0.69.0` (and
never over a copy that is already there). It reads the file strictly and, if one line cannot be
read, changes nothing and reports itself pending, to run again next session. Afterwards it re-reads
the file to confirm no passed role is left at `backlog`. Running it again changes nothing, and a
profile with no such role gets no output. To undo it, restore the `.pre-0.69.0` copy; that is only
safe for roles you have not touched since.

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

### Listed pay, posting age, the screen and the lean — since 0.67.0

Four fields on a role record exist so that "the listing showed no pay" and "nobody read the
listing" stop looking the same. **Every one is optional, and a role without it means the fact was
not recorded** — so no existing role was rewritten by the upgrade.

**`listed_pay` — the pay as the listing showed it.**

| part | what it is |
|---|---|
| `state` | `employer-stated` (the employer wrote a range) · `board-estimate` (the board computed one; not the employer's word) · `none-shown` (the listing was read and showed no pay) |
| `ranges` | one or more `{min, max, currency, interval, label}`. `currency` is an ISO code such as `USD`. `interval` is `year` · `month` · `day` · `hour`. `max` may be empty for an open-ended "$X and up" range. `label` is the posting's own wording when a range is for one location. A `none-shown` role has no ranges |
| `source` | where it was read: the listing text, an ATS or structured-data read, a board's own estimate panel, or `candidate` when you recorded it by hand |
| `captured_on` | the date it was read |

**A role with no `listed_pay` at all is *NOT CAPTURED*: nobody has recorded what the listing
showed. That is not the same as `none-shown`, and the screen treats them differently** (below).
Your own `comp` figure, if the role has one, still comes first: it may come from a conversation
rather than a listing, and it is what an older role carries.

**`posted` — the posting date.** `{date, source, recorded_on}`. `source` is `ats-posted` (the
employer's own publication date, the strongest) · `board-relative` (a board said "12 days ago", or
gave a date; the script works out the date, never the model — the weaker source) ·
`profile-document-date` (a recruiter's own spec document was dated; recorded by hand) · `unknown`.
Absent means the same as `unknown`: the age is not known. A board's "N days ago" is recorded as
exactly that kind of source, not as if it were the employer's date.

**What the screen now says.** The minimal screen every captured role gets (comp floor,
passed/duplicate, geography, title) reports these comp verdicts. `NOT-CAPTURED` and
`PAY-UNCOMPARABLE` are new in 0.67.0, `UNDISCLOSED` now means only *none shown*, and
`NEEDS-COMMUTE-CHECK` is an old verdict with a new cause:

| verdict | meaning | what the screen does |
|---|---|---|
| `CLEARS` | the top of the stated range is at or above the floor that applies | keeps the role |
| `BELOW-FLOOR` | an **employer-stated** range, or your own `comp` figure, whose top is below the applicable floor | **removes** the role, and says why. Where a role lists several ranges, the screen removes only when every range's top is below the floor, or screens the one range labelled for the role's location. A removal is lifted only by one decision: `record.py decide <id> pursue --why-kind comp-acceptable --why "..."`. That role then shows `BELOW-FLOOR-ACCEPTED` and is never removed. Reversing it, or deciding again with another `--why-kind`, brings the removal back |
| `BELOW-FLOOR-ACCEPTED` | since 0.73.0 — the role would be `BELOW-FLOOR`, and your current decision is `pursue` with `--why-kind comp-acceptable` | **keeps** the role, with the posting's own figures and your decision named. Never removes |
| `BELOW-ENGAGEMENT-FLOOR` | since 0.73.0 — a fractional, interim, advisory or contract role whose top, in its own unit (hour, day, month, year), is below your `compensation.non_employee` floor for that same unit | **review**; it never removes. Non-employee pay is priced per scope, so a low rate is a negotiating position |
| `UNDISCLOSED` | **none shown**: the listing was read and showed no pay, or the range is open-ended and its start is below the floor | keeps the role. Pay is the first question to ask, so it cannot be screened on |
| `NOT-CAPTURED` | nobody recorded what pay the listing showed, and the role has no `comp` figure either | **review**, not keep: "re-read the listing before surfacing it" |
| `PAY-UNCOMPARABLE` | a figure exists but cannot be fairly compared: it is not annual (hourly, daily or monthly pay is never converted), it is in a currency other than yours, you have not set `compensation.currency`, or it is a board's estimate that falls below the floor. Since 0.73.0 it also covers a `comp` figure stated per hour, day or month, or on a basis other than base or total (a different pay basis never removes); a fractional, interim, advisory or contract role when no `compensation.non_employee` block is configured, or none for its unit; and an `engagement_type` outside the list | **review**; it never removes |
| `NEEDS-COMMUTE-CHECK` | an existing verdict. It means the screen cannot tell a commute from a move. **New cause since 0.67.0:** you declared commute-time bands (below) and this role's commute minutes are not known — the screen never guesses a band | **review** |
| `UNRESOLVED-SETTING` | the posting declares two settings at once (see above) | **review**: the question goes to the employer |

**"None shown" is `UNDISCLOSED`, and only that.** The screen's wording for "the listing showed
nothing" is `UNDISCLOSED`; the screen reads it as *none shown*, and keeps the role. A role nobody
has checked is `NOT-CAPTURED`, which asks for a re-read. A board's estimate is never grounds to
remove a role, because it is not the employer's word.

**What changed on upgrade, without any file being rewritten.** A live role with no `comp` figure
and no `listed_pay` used to screen `UNDISCLOSED` and be kept without a second look. It now screens
`NOT-CAPTURED` and is flagged for review. The role records are the same; the screen reads them
differently, because those roles were never shown to have listed no pay. The data check
(`validate_data.py`, which a run starts with) lists every live role whose pay was never captured
under a `HYGIENE` heading, so the count is visible and shrinks as roles are read; it reports them
and never refuses a run. `record.py listed-pay <role> --none-shown` closes one that really showed
no pay.

**The age line.** The minimal screen now also prints an `age` line: for example
`age: 41d (ats-posted 2026-09-04)`, or `age: UNKNOWN` when no posting date is recorded. Age alone
never changes the verdict. The exception is a role that came through a **recruiter** channel (a
search firm is a recruiter channel): when its age is over `search.retained_search_age_days`, the
line reads, for example, `age: 41d (ats-posted 2026-09-04) OVER 35d -- FIRST MOVE: ask the
recruiter what stage the search is in, before research or letters`, and the verdict becomes
`review:age`. When its age is unknown, the line reads `age: UNKNOWN -- ask the recruiter when the
search opened` and the verdict is also `review:age`. If `search.retained_search_age_days` holds a
value outside 14 to 120 the line says so and the verdict is `review:age` too, never the default.
It never removes the role, and it fires for any recruiter, because the store does not tell a
retained search from a contingent one and the first move is the same question. `funnel_report.py` also prints an *age at
capture* table per channel: how old roles were when first seen, with the mix of date sources, and
"too few to rate" until a channel has enough roles.

**`screen` and `lean` — what the system did before the role became yours to decide.**
`screen` is `{on, verdict, rules, engine}`: the result of the hard screens, written by
`record.py screened`, which re-runs the screen itself and stores what the screen computed (the
printed block is made from the same result, so the two cannot differ). A model never
types a verdict in. `lean` is `{lean, line, on, signals}`: `pursue`, `pass` or `ask`, a one-line
reason, and any likely-pass signals that matched (below). **A lean is shown on the role's
card as advice and never removes or decides anything.** When the age line asks for a first move
(a recruiter role over the age limit, or of unknown age), the lean defaults to `ask` and its line
is that first move; the run states a different lean only when the job description gives a reason. A role in `triaging` is described in
[Reading what the search produces](reading-your-files.md#triaging-versus-decide-since-0670).

**The title floor and the mandate — since 0.69.0.** Two optional settings keep titles that are
plainly not yours from piling up undecided. **Neither one removes a role.** Only the hard rules
(a stated range below your floor, a place you ruled out, a role you already passed on) remove; a
title is weak evidence, because a larger company gives a lower title for the same scope, and pay is
the real test.

- **`screen.title_floor`** names the lowest seniority you will consider. Its value is exactly one
  of these levels, lowest first: `intern`, `entry`, `associate`, `senior`, `lead`, `manager`,
  `director`, `vp`, `executive`. The engine reads a title against a fixed list of everyday words
  (for example `junior`, `senior`, `principal`, `manager`, `director`, `vice president`, `chief`),
  takes the highest level any of them gives, and flags the role when that level is below your floor.
  It is a heuristic and reads loosely ("Associate Director" reads `director`). **A title the list
  cannot read has no level and is never flagged.** Absent means no floor, and the screen prints
  exactly what it printed before.
- **The mandate** is the same `screen.likely_pass_signals` list you already have, with `fields`
  set to `["title"]`: phrases for work you do not do. A title that matches one, and does not match
  one of your `targets.titles`, is flagged `OFF-MANDATE` and shown as a **lean to pass** carrying
  your reason. No separate key exists for it.

The screen's title line then reads `BELOW-FLOOR (reads <level>, below your floor <floor>) --
advisory: pay decides, nothing is removed` or `OFF-MANDATE (<id>: <reason>) -- advisory: a lean to
pass, nothing is removed`. `BELOW-FLOOR` wins if both apply.

**What a below-floor title leans, by pay.** The lean is worked out by the engine from the pay
verdict the same screen already stored, never chosen by a model:

| pay verdict | lean | line shown on the card |
|---|---|---|
| `CLEARS` | `pursue` | `title below your floor (<floor>), but pay is within your range` |
| `BELOW-FLOOR` | none from the title | the pay rule already removes the role; the title adds nothing |
| `BELOW-FLOOR-ACCEPTED` | `pursue` | `title below your floor (<floor>), and you accepted the pay` |
| anything else (`NOT-CAPTURED`, `UNDISCLOSED`, `PAY-UNCOMPARABLE`, `NEEDS-COMMUTE-CHECK`, `UNRESOLVED-SETTING`) | `ask` | `title below your floor (<floor>); check pay before deciding` |

It is stored as a signal with id `title-floor` beside any signals that matched. A lean you or the
run state explicitly with `record.py lean --lean` still wins; the computed signal is attached
either way.

**The one-time re-screen.** A stored screen records `title_keys`, a fingerprint of
`screen.title_floor`, your `targets.titles` and the title-field signals. When the fingerprint no
longer matches today's settings, or the screen has none and a floor is now set, the role counts as
missing its screen and goes through the ordinary triage step again, within the usual
`search.triage_per_run` cap. So setting a floor re-screens the existing pile over the next daily
runs, once, and changing the floor or those phrases later does it again. With no floor set, an old
screen with no fingerprint is left alone. To see the size of it before and after:

```
~/.claude/jobsearch/run profile.py --title-scope-count
undecided: 40, flagged below floor: 12, off-mandate: 3, re-screen pending: 40
```

**The pay re-screen — since 0.73.0.** A stored screen also records `comp_keys`, a fingerprint of the
pay inputs: the engagement vocabulary, `compensation.non_employee`, the role's engagement, its `comp`
period and basis, and whether your current decision accepts the pay. A screen computed without those
inputs is stale where it could matter. A stale screen on an **undecided** role re-screens
automatically through the ordinary triage step, within the `search.triage_per_run` cap. Roles you
already decided, or that an earlier screen already removed, do not drain on their own. Count them
with:

```
~/.claude/jobsearch/run profile.py --comp-scope-count
stored screens: 212, comp re-screen pending: 9, would screen differently (flagged): 2
  opp-0042: remove:comp -> keep (CLEARS); <the command to run, below>
```

(numbers illustrative). The count covers every status, since a wrongly removed role is exactly the
one it must not skip. The last number, and the lines under it, are the roles worth a second look:
a role whose stored screen **removed it on pay alone** (`remove:comp`) and that today's pay rule
would not remove. Setting `compensation.non_employee`, or a role's `engagement_type`, makes a screen
stale the same way.

**Nothing is reopened for you.** The engine never changes a role's status, stage or decision on its
own. A flagged role is shown to you, in the status pane under *Roles to reconsider* and on the
review-now page (see [Reading your files](reading-your-files.md)), with the old verdict, the new
one, why, and the command that reopens it. You end a flag in one of two ways:

- **Reopen it:** `record.py decide <id> pursue` (or `park`), and then `record.py screened <id>`. A
  role that was passed and has no recorded way back (`passed_from`) cannot be restored by `decide`;
  the flag then names the status and stage to set first.
- **Dismiss it:** `record.py screened <id>` alone. It stores the verdict today's rule gives, so the
  role stops being stale and the flag goes. There is no separate dismissal and nothing extra is
  stored.

Two limits to know. A role you decided on a **later day** than its screen is not flagged, because
you have already made a decision since; a decision and a screen on the **same day** cannot be told
apart by order, so that role stays flagged. And a role you passed for some other reason, but whose
stored removal reads `remove:comp`, stays flagged until you run `record.py screened <id>`. A role
whose re-screen could not be computed is listed as *not checked*, never dropped.

(numbers illustrative). It counts your undecided backlog roles, how many read below the floor or
off-mandate under today's settings, and how many have a stored screen waiting to be redone. It
reads only; it changes nothing.

**Roles that already existed.** Triage state is *derived*, never stored. After upgrading, a role
that was waiting on your pursue-or-pass but has no recorded job-description read, pay as written,
work setting as written, screen and lean shows as `triaging` until the daily run has triaged it.
Nothing was moved; the derivation does it.

**Commute time on a role.** A role may carry `location.commute_minutes`: `{minutes, anchor,
source}`, where `source` is `candidate`, `map-estimate` or `config-place`. Absent means the minutes
are unknown. It matters only if you declared bands (see *Geography* below).

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
  `opportunity`) and `subject_id` say what it's *about*; the plan's own `id` is what `plan_id` on a role names, to
  say which plan *governs* it. `outcomes` (`role`/`contract`/`access`) matters only on a `search` plan — several
  can be active at once, e.g. a themed search alongside your main one. `goal`/`approach` are your
  own words; nothing writes them for you. `targets` is an optional override of the targets in your
  `config.json`, meaningful only on a `search` plan — set it when a themed search should chase
  something different from your main one.
- **A plan names its play in `play_id`** — a play's id, the literal `manual` when you decide each
  step yourself, or `null` when none is chosen yet. **`play_confirmed` is the switch**: while it is
  `false` the play acts on nothing outward, and it is what `plays.py --confirm` / `--unconfirm`
  flip. A plan also carries `resolves_when`, `resolved_on` and `resolution`, which work exactly as
  they do on an ask (see *Asks and commitments* below): the recorded action that answers it, set
  together with the resolution.
- **A play** is the sequence a plan is worked by — steps, each gated on a condition the engine
  can already prove (an application submitted, an insider known, a referral in hand, silence past
  a window, …), never a rule language. The chase-after-applying sequence that used to be the
  `play_stage` field is now one of these: `plays.py`'s engine looks at what you've actually
  recorded and tells you the next step, instead of asking you to keep a position field current by
  hand.
  A play row has an `id` (what a plan's `play_id` names) and holds `steps` — the ordered list, each gated — and `params`, the adjustable knobs
  (see *Adjusting a play* below). It also records where it came from: `pattern` is the shipped
  pattern it was copied from (`null` for a play you built by hand), `pattern_sha` is the version
  of that pattern at the moment of the copy, and `pattern_reconciled_on` is the date you last
  reconciled the copy against the shipped one. **The play is a full copy on purpose**, so an
  improvement to the shipped pattern arrives as a difference you can review rather than a silent
  change to your play; if you edit `steps` or `params` yourself the play counts as forked from
  its pattern, and `plays.py --check` says so.

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

**Weekly assessments.** A plan can carry `assessments` — a list with one entry per weekly look at how it is
going. `date` is the day the entry was recorded, `as_of` is the date the assessment was computed to and `window_from` the start of the
period it covered (the previous entry's `as_of`, or six weeks back for the first); `engine_version`
records which plugin version computed it. `working`, `not_working` and `next_steps` are **your
words only** — the engine never writes them, and the next assessment prints them beside the
funnel that followed. `proposals` is the list of what the assessment suggests, each either a `parameter`
(a setting you own; accepting it means changing that value) or a `construct` (the plan's shape
did not play out, which is a report to the plugin's maintainers, never something the engine
changes for you), with its `evidence`, a `status` (`proposed` · `accepted` · `declined` ·
`reported` · `superseded`) and, once decided, `decided_on` and `decision` together. **As of this
writing nothing in the engine writes this array yet** — the shape is declared ahead of its
writer — so an absent or empty `assessments` is the normal state, not a fault.

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
| `id` | a stable slug, unique across everyone — what a touch's or a message's `person_id` points at |
| `name` | a name. URLs and email addresses go in their own fields, not in here |
| `email`, `linkedin` | structured and validated, never prose |
| `email_status` | how you know the address is right: `verified-published` (they publish it) · `verified-received` (you have received mail from it) · `pattern-inferred` (guessed from the company's address format) · `unknown`. It tells you how far to trust the address before you write to it |
| `title`, `cadence` | who they are professionally, and (once you set it) how often you want to stay in touch |
| `company_id` | the company they were reached through, set only for a person reached through a role; `null` for someone known only through a channel |
| `not_same_as` | ids of people you have reviewed and confirmed are **different** humans. Once a pair is listed, `people.py --duplicates` stops surfacing it, so a same-name pair you have already ruled on does not come back on every run |
| `created` | when the record was made — `null` until you fill it in by hand |
| `note` | free text of your own about them |

| field (on the link to one role or channel) | what it is |
|---|---|
| `person_id` | who the link is about — it must resolve to a person, and with `opp_id` or `channel_id` it is what identifies the link (a link has no `id` of its own) |
| `opp_id`, `channel_id` | which role or channel the link is to — **exactly one is set**, never both and never neither. A person known only through a firm or a referral has `channel_id` set and no role at all. A person you keep in touch with who is tied to neither has **no link row at all**: they exist as a person and in their touches and messages, and that is a complete record |
| `role`, `path_type`, `status`, `note` | how you reached them and where it stands, **for this role or channel specifically** |

**Linking someone to a role later — `record.py involve <person-id> --opp <opp-id>` (since
0.62.0).** When a person you have been in touch with turns out to matter for a role, you link them
with this one command. It writes the link row (with `--role` if you want to say what they are for
this role) the same way recording a touch on the role would, and nothing else: the touches you
already recorded with that person are **not** edited or re-attributed to the role, so your history
and the role's funnel counts do not shift under you. Running it twice is harmless — an existing
link is left alone. It refuses if the person or the role does not exist, and it never guesses: the
engine does not link a person to a role because the dates line up. Once linked, recording a touch
on that role to that person works as it does for anyone else. There is no channel form.

`path_type` is `warm-referral` · `recruiter` · `hiring-manager` · `hiring-context` ·
`internal` · `cold`.

> **If you messaged someone, they are a person on record by definition.** Every outreach record
> must point at a person that exists, and this is enforced — which is what makes "what is my
> whole history with this person?" answerable, now across every role and channel at once, not
> just one.

Query one person's full history with `python3 scripts/pipeline_index.py --person <name>`.

**A person with no role and no channel is a full relationship (since 0.62.0).** Someone you keep
in touch with — a former colleague, a mentor, an introduction you are cultivating — needs no
opportunity and no channel to be tracked: you can record a message to or from them, record a touch
with them, set their `cadence`, and have the search draft to them and prune the finished draft,
all without inventing a role to hang it on.

**Creating a person without duplicating one — `record.py create <id> --file people '<json>'
--reuse` (since 0.62.0).** With `--reuse`, the command first looks for an existing person using
exactly the matching rule described above: an identical LinkedIn profile URL, **or** an identical
email address *and* an identical name. A hit means "this person is already on record": it tells
you which person and which field matched, writes nothing, and succeeds. A match on **email alone**
is not treated as the same person (it may be a shared inbox): the command refuses, lists that
person as a candidate in the same form `people.py --duplicates` uses, and leaves the decision to
you. With no match, the person is created as usual. Without `--reuse` the command behaves exactly
as before, and a duplicate id is still refused. This is how a draft that reads `**To:**
unaddressed` gets its recipient by script — see *What a draft now carries*, below.

**The People due view on your dashboard (since 0.62.0).** Your dashboard's outreach section now
has a **People due** block, right after the pending-drafts list. It lists the people with a
`cadence` whose time has come (`due`, or `awaiting-intro`) **and who are not linked to any role** —
a person who is linked to a role shows up through that role instead, so nobody appears twice. Each
row shows their name, whether they are due or awaiting an introduction, and why (`cadence 30
day(s); last touch 2026-08-14`). Under the list, one line counts the people on cadence who are
still comfortably within it, so a relationship that is fine reads as fine rather than as missing.
It is the same due-list the coordinator's `your_move` already printed; the dashboard just shows
it. The old footer line saying the network was not on the page is gone.

**Since 0.64.0, People due is still where a person is listed in full — and the follow-ups list
above it points at it.** The pending-drafts list is now the one *Follow-ups — what to send* list:
a person who is due appears there as a one-line reference ("no draft yet — <why>") that links down
to their row in People due, so nobody is shown in full twice. A relationship touch that is due and
an application with no follow-up drafted are shown the same way, linking to their channel or role.
A relationship touch counts as *Now* when its date falls within a fixed 5-day horizon (not a
setting you can change in `config.json`) and as *Later* beyond it; a person who is due, and an
application with no follow-up drafted, are always *Now*.

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
| `channel_id` | the relationship the touch travelled through — a recruiting firm, a warm-network channel. `null` is correct and expected for a cold touch: it names the *relationship*, never the medium (that is `medium`) |
| `to` | the recipient's display name as it read when you sent — required and non-empty on a sent touch. It is a label for you to read; the resolving link to the person is `person_id` |
| `variant` | a short slug naming the style or approach you used (for example a shorter opener versus a longer one), so an approach can be scored against `outcome` later. `null` when you are not tracking one |
| `recipient_role` | a hiring manager, a recruiter and a peer are not the same audience |
| `campaign_id` | groups a multi-touch push so it can be evaluated as one thing |
| `address_status` | required for email — records whether the address was verified or pattern-guessed |
| `delivery` | `delivered` · `bounced` · `unknown`. **Bounces are excluded from every denominator** — a bounce that looks like a non-reply poisons the metric |
| `outcome` | `awaiting` · `replied` · `accepted` · `no-response` · `declined` · `meeting-booked` |
| `message_ref` | points at the full text in `messages.jsonl`, and must resolve |
| `trigger_kind`, `trigger_ref` | what CAUSED this touch — `application`, `reply`, `elapsed` or `manual`, plus the specific application/message/date it points at. See *Triggers and sequences* below |
| `sequence_id`, `sequence_step` | groups this touch into a multi-step play with other outreach and staged drafts under the same `sequence_id`, ordered by `sequence_step` |
| `plan_id`, `play_step` | since 0.49.0 — which plan this touch counts toward, and which play step it satisfies (`reach-insider`, …), or the marker `unresolved` when the touch predates 0.49.0 and can't be assigned a step automatically. Only set on a touch anchored to a role (`opp_id`); a networking touch has no plan to derive one from. See *Plans and plays* above |
| `note` | free text of your own about this touch |

#### Recording a touch with no role — the person form of `touched` (since 0.62.0)

`record.py touched` no longer needs a role. Without one it records a touch to a person alone:
`record.py touched --to contact:<person-id> --medium <medium> [--on <date>] [--role <recipient_role>] [--touch-type <touch_type>]`.

The row it writes has no `opp_id` and no `channel_id`, an `outcome` of `awaiting`, and `delivery`
and `address_status` of `unknown`; `--touch-type` sets the `touch_type` (otherwise `unknown`). It
checks everything before it writes anything and names the field it is unhappy with: the person
must exist (and not be one that was merged away), the medium must be one the engine knows, `--on`
must be a real date, and `--role` and `--touch-type` must each be a valid value. Because there is
no role, there is no involvement to update, and the command says so rather than staying silent.
`record.py fields --file touches` lists every field a touch needs, including the ones required
only in some cases (a sent touch needs `to`; a touch dated on or after the 2026-08-02 cutover needs
`touch_type`, `recipient_role` and `delivery`; an email touch needs `address_status`), so you can
answer "what does this row need?" from that one command. The same flags work with a role too:
`--touch-type` is valid on both forms.

The weekly review's draft pruning uses this path: a draft you marked `SENT` on a date, addressed to
someone you have on record but with no role and no channel, is moved out of `drafts.md` by
recording (or finding) exactly this kind of touch for that date. A `SENT` entry with no date, or
one whose recipient resolves to nobody, is left in place and reported — the engine does not invent
a date or a recipient.

#### Recording a touch changes more than the touch — since 0.54.0

Recording an outbound touch as `touched` or `answered` (`record.py`) no longer only writes the
touch row. It also **upserts the recipient's `involvements.jsonl` row** (`status`, `path_type`)
from what you just recorded, and, when that touch already answers what an opportunity's
`next_action_owner`/`next_action_date` were waiting on you for, it **clears those two fields**
off the role in the same write. Neither field is purely hand-set any more — treat a change you
did not make by hand to an involvement or to `next_action_owner`/`next_action_date` as this
propagation having run, not as data corruption.

**If you upgraded across this change,** the 0.54.0 migration backfilled this onto every touch you
had already recorded before the fix existed — so your existing `involvements.jsonl` rows and
`next_action_owner`/`next_action_date` fields may have changed retroactively the first session you
opened on 0.54.0, to what they would have read had this propagation always run.

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

### Messages — `messages.jsonl`

Every communication, both directions, one row each. **Append-only**: `record.py` adds rows
(`touched` for something you sent, `answered` for a reply, `received` for inbound mail
identified by its sender) and nothing edits one in place, so a stored message is a record and
never a draft that can drift.

- **`direction`** is `inbound`, `outbound`, or `third-party` — something written by someone else on
  your behalf (a referral's endorsement), which is not your own outreach and is never counted as
  it.
- **`body`** is the full text, and **`subject`** the subject line where the medium has one
  (otherwise `null`). **`sent_on`** is the date, or `YYYY-MM-DD HH:MM` where the time is known.
- **`from`** and **`to`** are the sender and recipient as the message states them — an address, or
  a `contact:<id>` token when you record it through `record.py`. `from` is usually `null` on a
  message you sent yourself.
- **`source`** is required, and says where the text came from — `gmail:<account>:<uid>` for mail
  (`ats:<account>:<uid>` is the same shape, written by the ATS sweep, which also leaves
  `mail:<account>:<uid>` markers in the notes it writes), or `outreach/drafts.md` for something you wrote and sent
  yourself. A stored body with no provenance is an assertion, not a record. **Since 0.66.0 the
  `<uid>` is digits and nothing else** (see *A mail tag is always the same shape* below).
- **`channel_id`** anchors a message to a relationship rather than a role — a warm intro or a
  referral. Every message needs an anchor: an `opp_id`, a `channel_id`, **or — since 0.62.0 — the
  `person_id` alone**, at least one. A message to a person about no role and no channel (a
  networking reply, a thank-you) is a complete record on its own, provided that `person_id`
  resolves to a person you have on record. A message with none of the three is still refused.
- **`id`** is the message's own stable handle — what another message's `answers` points at. An
  inbound message's handle is made per message (its date is part of it), so two replies from the
  same conversation are two records, not one overwriting the other.
- **`person_id`** is who the message was to or from; it resolves through `people.jsonl`, the same
  as a touch's `person_id`. When it is the message's only anchor, it must resolve **directly**: an
  id that has since been merged into another person is refused like any dangling link, so point it
  at the surviving person.
- **`medium`** is how it travelled — a LinkedIn message, an email, an InMail — the same field, for
  the same reason, as a touch's `medium`.
- **`variant`** names the style or approach used, the same slug a touch's `variant` carries, so
  an approach can be scored against outcomes.

How one message points at another — `answers`, and the ATS sweep's `resolves`/`resolved_by` —
is described under *Touches* and *ATS receipt matching*.

#### A mail tag is always the same shape (since 0.66.0)

Every record that points at a stored email does it with a tag of one shape,
`<gmail|mail|ats>:<account>:<uid>`, where `<uid>` is the mailbox's own message number: digits only,
for example `gmail:work:4217`. A tag is the engine's memory that it has already seen a message, so
the same message must always spell the same way.

Before 0.66.0 that was not so. A defect in how the mailbox's message numbers were read could write
`gmail:work:b'4217'` — the number wrapped in Python's byte-string notation — instead of
`gmail:work:4217`. Two things followed: the weekly harvest and the ATS sweep did not recognise a
stored `b'4217'` row as the message they had just found, so they stored it a second time; and the
duplicate rows each carried their own links (a touch's `message_ref`, an ask's `trigger_ref`, a
brief's `latest_in`). **From 0.66.0 on:**

- the number is read as text at the mailbox boundary, so a new wrapped tag cannot be written;
- the validator **refuses** a wrapped tag in any field that carries one (`messages.source` and
  `id`/`answers`, `commitments.source`, `asks.trigger_ref` and `note`, `touches.message_ref` and
  `trigger_ref`, `briefs.evidence`, `latest_in` and `latest_out`), naming the file, the row and the
  field. A `source` that is not a mail tag at all (`outreach/drafts.md`, a LinkedIn thread link)
  is untouched;
- "have I already stored this message?" compares the tags after stripping the wrapper, so a stored
  `b'4217'` row and a fresh `4217` for the same email count as the same message.

**Upgrading to 0.66.0 repairs your existing files once, automatically, the first session you open
on that version** (the `m_0_66_0_uid_text` migration). It first copies each file it will change to
`data/<file>.jsonl.pre-0.66.0` (a copy from an earlier partial run is never overwritten), then
rewrites every wrapped tag to the plain form. Where a wrapped row and a plain row turn out to be
the same email, they are **merged into one**: the row whose tag was already plain survives, a field
it lacks is filled from the other, and where both hold different values the survivor's is kept and
the migration's report names the disagreement. Every link that pointed at the dropped row —
a touch, an ask, a brief, an ATS completion mark in an application's or ask's note — is moved to the
survivor. The migration then re-reads your files and reports *done* only if no wrapped tag, no
duplicate and no dangling link remains; otherwise it reports *pending* and says which, and leaves
the copies in place. Running it again changes nothing. A message row whose own `id` merely contained
the old wrapped number keeps that `id` — an id is only a handle, and nothing re-derives it.
**To undo it,** restore *all* the `.pre-0.66.0` copies together; restoring one file alone leaves
links pointing at ids that no longer exist, and anything written after the upgrade is lost.
Downgrading the engine to 0.65.x without restoring brings the old defect back.

Two places are deliberately **not** rewritten. The run journal's record of which alert-digest emails
were already triaged is an append-only log; it is read with the wrapper stripped instead. And the
`key` that `watch.py` gives each alert in `data/inbox.jsonl` (`alert:<account>:<uid>`, the key that
stops one alert being queued twice) is likewise normalised **when read**, so an older queue entry
with a wrapped number still suppresses its fresh, plain twin; no inbox row is edited.

#### What the weekly audit calls a reply (since 0.66.0)

`reconcile.py --all`, the weekly audit, looks for mail from someone you contacted that arrived
after your touch and that you have not recorded. Two rules decide what it reports:

- **Automated mail is never a reply.** A message from one of your configured ATS receipt domains
  (`config.json.ats.receipt_sender_domains`, see *ATS receipt matching*), or from a `noreply` or
  other automated sender, is not eligible to resolve a touch. An application acknowledgement that
  happens to quote the recruiter's name used to produce an *UNRECORDED REPLY* line for a touch to
  that recruiter; it no longer does. It also no longer counts as evidence of which medium the
  conversation is on.
- **A reply on a different medium is reported, but as a lower-confidence finding.** If your touch
  was a LinkedIn note and the mail from that person came by email, it is listed under its own
  heading, *POSSIBLE CROSS-MEDIUM REPLY*, with a reminder to read it before recording anything: a
  person can answer a LinkedIn note by email, but it may equally be a separate thread. It is
  counted separately and never added into the *UNRECORDED REPLY* count. A reply on the same medium
  is reported exactly as before.

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

### `**Revised:**` — a correction applied to a draft (since 0.64.0)

A draft that has had a reviewer's correction applied carries one `**Revised:**` meta line per
correction, under its heading, in the same `**Label:** value` form as the lines above:

```
**Revised:** <date> · <source> · "<old text>" → "<new text>"
```

- `<source>` is `comment:<thread id>` when the correction came from a comment on the published
  dashboard, or `chat` when you gave it to the session directly.
- The message text itself (the `>` lines) has already been changed; this line is the record of
  what was changed, and from where. **It is metadata, never part of the message:** it is not sent,
  and the correction step checks that recording it leaves whether a draft is ready, held, sent or
  moot unchanged, refusing if it would (the line quotes the old text, and a hold phrase is found
  anywhere in an entry).
- The line is written only by the session's correction step, and only after it has shown you the
  before and after and you have said yes. The step refuses unless the old text occurs exactly
  once in that draft, and refuses to apply a correction whose `**Revised:**` line is already on the
  draft, so a repeated apply cannot double an insertion.
- No upgrade step is involved: nothing in an existing `drafts.md` needs rewriting, and a profile
  with no corrections has no such lines.

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

- A draft whose recipient could not be resolved reads `**To:** unaddressed` and needs a recipient
  before it can be briefed at all. Since 0.62.0 that is two commands rather than a hand edit:
  `record.py create <id> --file people '<json>' --reuse` to get or create the person (see
  *People*, above), then `brief.py --address "<the draft's title>" --to contact:<id>`, which sets
  the draft's `**To:**` and computes and stamps its `**Brief:**` in one write and tells you the
  draft's new state. It refuses a draft that is already sent or dropped, and one already addressed
  to a *different* person.
- A draft aimed at someone with no prior thread and no confirmed-empty mailbox check holds as
  `unverified-cold` — it is not sendable until either a mailbox probe confirms the mailbox is
  genuinely empty, or, for someone with no known email address at all, you attest to having
  checked yourself: `brief.py --for contact:<id> --i-checked <date>` (refused if an address on
  file means the engine could have checked itself instead).
- Everything else is briefed and ready to re-check the normal way.

The migration's own summary line names the one command that drains what it could not resolve
on its own: `~/.claude/jobsearch/run brief.py --probe --held` — it walks every held draft and
probes the mailbox for each, promoting whatever it can confirm.

**0.57.0 — the probe only counts a real human reply.** Earlier versions searched for your name or
address anywhere a message stored it — including inside an automated sender's own copy of it, or a
job board's own confirmation text — which could match on the order of your whole mailbox. That
produced false "store-behind-mailbox" findings, each one demanding a manual mailbox search and an
explicit `--i-checked` attestation to clear, and — because the finding used to be re-created fresh
every day — the same acknowledged finding for the same contact could come back and demand that all
over again on the very next run. As of 0.57.0 a probe only counts a message where you were
genuinely the sender or the recipient, and only when it came from what looks like a real person —
a job board's or ATS's automated receipt, a LinkedIn notification, or a generic `noreply`-style
address no longer counts as evidence of a human thread. And once you acknowledge that finding for a
contact, it stays acknowledged: it does not come back on a later run as if it were new. Upgrading
carries forward any acknowledgment you already gave under the old behavior, so nothing you already
cleared re-queues itself because of this change.

One limit worth knowing: a newsletter sent from an otherwise ordinary-looking address (not a
`noreply` variant) can still be counted as a hit — nothing in your profile records which senders
are newsletters, so this only catches automated senders it can recognize structurally.

### The brief ledger — `briefs.jsonl`

Each time `brief.py` computes a brief for a draft it appends one row here, and the draft's
`**Brief:**` line cites that row by `id` — `brief:<timestamp with UTC offset>-<random hex digits>` (16 on new briefs, 4 on older ones).
**The ledger is append-only, never edited by hand, and never a source of state**: a row is
evidence of what the drafter saw at that moment. The engine recomputes everything from your
other files every time a draft is checked, and looks up only the row a draft cites — never "the
newest row for this person" — so a stale citation is detectable and a row is never mistaken
for the current truth.

What a row records, in the order you would read it:

- **Who and where.** `person_id` is who the brief is about. `opp_id` and `channel_id` are the
  role or channel it was scoped to — either can be `null`, because a brief can be about a person
  alone, folded across every thread they are in. `thread` is the one role or channel the brief
  actually read (`null` when the person has none).
- **When.** `computed_at` is the timestamp the row was written, with its UTC offset; `today` is
  the date the brief counted elapsed days to.
- **What it concluded.** `axis` is the state of the conversation: `reply-owed` (their message is
  the newest), `accepted` (a connection you sent was accepted, and this never ages out),
  `waiting` (your last message is too recent to chase), `silence-unverified` (old enough to
  chase, but no mailbox check covers it), `silent` (verified silent for at least
  `chase_after_days`; see *Communications* below), or `nothing-sent`. `register` is what the
  drafter should do about it, derived from the axis: `reply-owed`, `accepted`, `premature`
  (waiting), `unverified-silent`, `chase` or `reconnect` (verified silence under or over
  `no_response_after_days`), `cold` (nothing sent, and a mailbox check confirmed there is no
  prior thread) or `unverified-cold` (nothing sent, but nothing confirms the mailbox is empty).
  `last_word` is `theirs` or `ours` — who spoke last.
- **The clock.** `days_since_in` is how many days of verified silence have passed since your
  last message, counted to the mailbox coverage that was actually verified, never to today —
  and `null` unless the axis is `silent`. `latest_in` and `latest_out` are `{id, date}` for the
  newest inbound and outbound message (`null` if there is none).
- **What the mailbox could confirm.** `evidence` holds, per medium (email and LinkedIn), what
  the mailbox check found and what it probed, so an empty thread can be told apart from one
  nobody looked at.
- **What the brief used.** `windows` carries the two `communications` thresholds it applied,
  each with where it came from (`in your config.json` or `default — not in your file`) so the
  card says which numbers decided the register. `open_asks` lists the ids of any open asks
  touching that person's role or channel. `engine` is the plugin version that computed the row.

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
  `data/opportunities.jsonl`) when the entry names one via `**Triggered by:** opp:<id>` (the field name in bold, then the
  value), or to
  `data/channels.jsonl`'s `log[]` when the entry addresses only a channel-anchored person with no
  role attached. Either way, the entry's own title and status line become the note on that new
  row, dated from the entry's own `SENT <date>` where it has one, otherwise today.
- **An entry naming neither an opportunity nor a channel-resolvable contact is left exactly where
  it is**, reported as `unresolved` — the one thing this will not do automatically is guess a
  home for it.

**Checking that a pending entry has not already gone out.** `check_sent_drafts.py` compares what
is still in `drafts.md` and `cover_letters.md` against what the record says was sent (a sent touch,
or an application that has been submitted or has moved on). Since 0.66.0 it matches **only inside the same piece of work**:
an entry that declares an opportunity (`**Triggered by:** opp:<id>`) is compared with sends on that
opportunity only; an entry that declares none is compared with sends to the one company its heading
names, if exactly one is named. The same person on a *different* role, or another role at the same
employer with a similar title, is never a match — that guess used to tell you to retire a draft
that was still live work. An entry that names neither an opportunity nor a company is listed as
*not checked*, with the line to add to anchor it. A match no longer says "retire": it names the
opportunity and says to **verify against it before changing the entry**. The half-sent case — a
connection request is out and the follow-up is waiting on acceptance — still reports as before, and
the right response is still to say so in the heading and leave it. The check only reads; it always
exits clean.

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
| `note` | free text of your own about this application |
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
| `created`, `note` | the date the variant was declared, and a free-text remark of your own |
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
| `note` | free text of your own about this letter |
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

This is the role's `fit` field. Optional. Absent means the job description has not been analysed yet.

Each material requirement from the posting becomes a row in `fit.requirements[]`: the
`requirement` in the posting's own words, a `verdict` of `aligned` · `partial` · `not-aligned` ·
`unknown`, and then:

- **`evidence`** — required when aligned or partial. A pointer to the resume sentence, project
  or note that backs the claim. An alignment claim with no citation is a gap in disguise.
- **`pitch_line`** — how to *present* that match, so your positioning is not reinvented for
  every draft.
- **`question_for_candidate`** — required when `unknown`. A targeted question, asked only when
  the answer would change the pitch.
- **`landed_in`** — where your answer was filed, so the same question is never asked twice.
- **`question_status`** — `n/a` · `open` · `answered`. Only an `open` question is put to you; once
  it is `answered` it stops appearing anywhere you are asked.
- **`act_by`** — the date an open question needs its answer by, when the fact that makes it
  urgent has one (an interview slot, a deadline). Open questions sort by it, earliest first and
  undated last, on the coordinator's list and on the dashboard's fit section — the date used to
  live as prose inside the question, where nothing could sort it.
- **`answered_on`** — the date you answered it.

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
| `id`, `created` | the ask's stable handle (a fixed slug on a system ask, such as `system-application-endings`), and the date it was raised |
| `kind` | `role` (about one opportunity) or `system` (tooling, a credential, a setting — for example `system-application-endings`, the one row naming every ended pursuit with no recorded ending, described under *Endings* above) — decides which group it shows in |
| `title`, `ask` | what it is, and what is actually being asked |
| `opp_id`, `channel_id` | the role or channel it concerns, if any |
| `act_by` | the date by which it needs an answer, if it has one. Open asks sort by it (undated last), so the one with a real deadline leads your queue instead of hiding in prose |
| `resolves_when` | `application` or `outreach` — the recorded action on this ask's `opp_id` that answers it. When you record that action through `record.py`, the ask is resolved in the **same write**, so it never sits open after you have already done the thing. Requires `opp_id` (a `resolves_when` that could never fire would look handled and not be). Without it the ask waits for you, or for a later check that notices the action was taken |
| `resolved_on`, `resolution` | set together, once, when it is answered |
| `trigger_kind`, `trigger_ref` | what CAUSED this ask, same as an outreach touch above — `trigger_kind: application` additionally requires `opp_id`, since resolving it means reading that role's own applications |

**An ask disappears from every view the moment it is resolved** — resolving it is what removes
it, not editing its text into a "done" line in place. The row itself stays as history.

**Since 0.50.0, `asks.jsonl` is writable through `record.py`**, the same tool you already use for
everything else — before this, an ask row could only ever be created by a migration.

**`commitments.jsonl`** — things scheduled on a date: a call, a deadline, a follow-up.

| field | what it is |
|---|---|
| `id` | the commitment's stable handle |
| `date` | ISO `YYYY-MM-DD`, or the literal `unresolved` if a date could not be read from its source and needs your eyes |
| `time` | the time of day, if it has one — free text as the invite states it, so a call at a fixed hour reads as one |
| `title`, `note` | what it is |
| `who` | the counterparty — names, companies — kept as words on purpose: the calendar cross-check matches on **date and who together**, because a date alone is not an identity and two meetings can share a day |
| `opp_id`, `channel_id` | the role or channel it concerns, if any |
| `source` | where the row came from — for example an invite you recorded, or `migrated 0.25.0 from focus.md ## This Week` on a row the upgrade moved for you. Provenance for you, not something the engine acts on |
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

`receipt_sender_domains` and `status_phrases` both start **empty** on a fresh profile, and **both
are read on every run, since 0.50.0** — the deterministic ATS sweep described just below uses
`receipt_sender_domains` to recognize which mail came from an ATS at all, and `status_phrases` to
decide which status that mail evidences. (An earlier version of this page said nothing read them
yet and that filling them in had no visible effect. That stopped being true in 0.50.0; it is
corrected here.) Match strings are your own words — whatever your ATSes' actual subject lines say —
not a fixed vocabulary the plugin ships with, and the plugin will never guess them for you.

⭐ **An empty class is not a neutral setting. Fill in all three, or none.** The sweep
says so out loud, because the in-between state is the one that quietly gets a status wrong:

- **All three classes empty** — the stock, freshly-seeded state. The feature is simply **off**:
  nothing is classified from subject lines at all. Nothing warns you about this, on purpose; a
  warning that fires on every install forever is a warning nobody reads.
- **Some filled, some empty** — the state to avoid. An empty class does not "match nothing"; it
  **cannot compete.** A rejection arrives, your `rejected` list is empty, your `acknowledged` list
  is not, and the mail hits exactly one populated class — which reads as an *unambiguous* match and
  is applied as if it were right. So an empty `status_phrases.rejected` beside a filled
  `acknowledged` does not mean "I have no way to recognize a rejection"; it means your rejections
  are being **actively misclassified as acknowledgments.** The sweep now detects exactly this
  asymmetry and writes you an ask (`ask-ats-empty-phrase-classes-…`, titled *"ATS status phrases: a
  class with no phrases"*) naming the empty class and the consequence. **It never proposes
  phrases** — the wording that decides whether your rejections are read as rejections is yours to
  write, not the engine's to guess. The ask is written once per configuration, not once per run, and
  changing your config is a different condition that gets its own row.

⭐ **And the sweep will no longer move an application backwards.** Every status write
is checked against the lifecycle order — `not-started → started → submitted → acknowledged →
advanced`, with `rejected`, `withdrawn` and `closed` as the three endings. Only a **strictly
forward** move is written automatically. A backwards move (a subject line reading as `acknowledged`
against an application you already have on record as `rejected`), or a sideways one (two of the
three endings disagreeing), is **refused and handed to you** as an ask
(`ask-ats-status-conflict-<application id>`) rather than overwriting what your record already says.
The engine cannot know which side is right, so it stops and asks. A first status onto an
application that has none is still an ordinary forward write — the check exists to stop
regressions, not to refuse a first write.

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
| `relocation.keep_outside_radius` | since 0.70.0 — whether an onsite role that is *provably* too far from every commute anchor (and names none of your affirmative destinations) is kept when `relocation.open` is true. Defaults to **false**: such a role is removed as `outside-radius`. Set it to **true** to get the earlier behaviour back. The 0.70.0 upgrade writes `false` into your `config.json` if the key is absent and never changes a value already there; the original is kept as `config.json.pre-0.70.0` |
| `commute_anchors` | places you can actually commute to, each with its own `max_commute_minutes` |
| `commute_anchors[].bands` | since 0.67.0, optional — pay floors that depend on how long the commute is, for an anchor: a list of `{max_minutes, floor}` in ascending order, the last `max_minutes` no larger than that anchor's `max_commute_minutes`. For example a role 20 minutes away can be held to a lower floor than one 50 minutes away. **An anchor with no `bands` behaves exactly as before.** See *Commute bands* below |
| `commute_anchors[].radius_miles` | since 0.70.0, optional — a straight-line radius, a number from 1 to 300. A place within it counts as inside the anchor; a place beyond it is provably outside. Without it the bound is derived from `max_commute_minutes` (or, when that is absent, the last band's minutes) |
| `commute_anchors[].lat`, `.lon` | since 0.70.0, optional, given together — the anchor's coordinates, used instead of looking its `place` up in the shipped place table |
| `commute_anchors[].includes` | the nearby places that count as inside the anchor. Each entry is a name, or since 0.67.0 `{place, minutes}` so the commute time to that place is known. A bare name leaves the minutes unknown |

Screening one location produces exactly one of seven verdicts, each citing the specific key that
decided it: `remote`, `commute` (names a commute anchor, or since 0.70.0 lies within an anchor's
`radius_miles`), `affirmative` (names an affirmative destination), `relocation-ok`
(`relocation.open` is true and nothing more specific matched, or `relocation.keep_outside_radius` is
true for a role that is far), `outside-radius` (since 0.70.0, see below), `out`
(`relocation.open` is false and nothing matched — the one verdict that ends a role's
consideration, reached only through an explicit or default-but-registered key, never through
silence), or `unknown` (your `config.json` has no `geography` section at all — different from an
unset key, which always has a registered default).

**Renamed by the 0.50.0 upgrade, the same defect one config section over as `ats`'s 0.41.0
rename.** `init_profile.py` used to scaffold this section as `geography.relocation_open_to` /
`geography.radius_minutes`, but every profile actually derived from a resume ended up with the
shape documented above instead — two spellings of one meaning, with nothing ever reading the
scaffolded names. `m_0_50_0_geography_keys` rewrites a profile still carrying the old names into
the shape above; nothing is dropped in the process.

### Where a role is, and when it is too far — since 0.70.0

Until 0.70.0 the screen could only tell that a role's place was *named* by one of your commute
anchors. A role in a city you never mentioned could not be called far, so a profile that screened
dozens of roles might remove none of them. Now the engine works out a distance.

- **The place table.** The plugin ships a table of US places with their coordinates, built from the
  US Census Bureau's public-domain Gazetteer (`places/us_places.csv.gz`, about 32,000 places). It is
  read from the plugin itself: no network, and nothing from your profile is sent anywhere. A place
  written like `Springfield, ST` or `Springfield, State name`, optionally with a ZIP, is looked up;
  a text it cannot read as a place (no comma, `remote`, `hybrid`, an unknown town) is reported as
  *unresolvable*, never guessed. If the table file is missing the screen says `PLACE TABLE MISSING:
  distance not checked`, counted on its own and never confused with an unknown place.
- **What counts as far.** A role is `outside-radius` only when it is beyond *every* anchor's reach:
  the anchor's `radius_miles` if you set one, otherwise a generous upper bound from its
  `max_commute_minutes` (minutes times 75 mph, plus 15 miles for the size of a city; a 45-minute
  anchor gives about 71 miles). An anchor the engine cannot locate or bound makes the role *near*,
  never *outside*. A *near* role stays on your list with its distance printed and a request for a
  commute estimate.
- **What is removed.** An onsite role proven far, that names none of your
  `affirmative_destinations`, is removed as `outside-radius` when `relocation.open` is true and
  `relocation.keep_outside_radius` is false. With `keep_outside_radius` set to true it is kept as
  `relocation-ok`. With `relocation.open` false it is `out`, as before. Every line says which key
  decided it.
- **A setting the posting never stated.** When a posting states no setting but gives a concrete
  place, the role is recorded as `onsite` with `location.setting_source: inferred`, and the screen
  line ends *(onsite inferred: the posting stated no setting)*. If you later correct the setting
  (`record.py set <role> location '<json>'`), the change is remembered in `location.inference_overturned`
  as `{was, to, on}`. A role with no setting and no readable place has no `type` and is kept for
  review rather than removed.
- **One role at several places.** A requisition listed in several cities is one row, not several:
  each listing is a sighting with its own `location`, and the role is screened at its most
  favourable place, so it is `outside-radius` only if every listing is. A listing of a role you
  already passed on that is *nearer* than anywhere it was listed before is shown as `NEARER LISTING`
  instead of being closed. The matcher joins rows on company plus title only, so two genuinely
  different openings with the same title at one company can be joined; `record.py unlink-sibling`
  undoes that. Rows from before 0.70.0 are never folded automatically: `record.py link-sibling
  <duplicate> --into <kept row>` folds one by hand (nothing is deleted; the row gets `duplicate_of`
  and leaves the undecided list).
- **Reading the result.** `profile.py --minimal-screen` with several role ids prints a block per role
  and then one summary line: how many were screened, kept, removed (and by which rule), left for
  review, and the commute split (`outside`, `near`, `unresolvable`). `profile.py --options` prints
  each anchor's bound and whether the place table is present.

### Commute bands — since 0.67.0

A pay floor that is the same for a 15-minute commute and a 50-minute one removes the near role
against a number meant for a move. Declaring `bands` on an anchor lets the floor depend on the
minutes. The screen picks the band as follows:

- **No anchor declares `bands`:** nothing changes. Every floor is the one it has always been.
- **The role is onsite or hybrid, an anchor with `bands` matches, and the commute minutes are
  known** (from the role's own `location.commute_minutes`, or from the `minutes` on a matching
  `includes` entry): the first band whose `max_minutes` is at or above the commute decides the
  floor. Beyond the last band, an onsite role is screened as a relocation and a hybrid role as the
  hybrid tier, as before.
- **The minutes are not known:** the verdict is `NEEDS-COMMUTE-CHECK`, with the reason that bands
  are declared and the minutes must be recorded. The screen never guesses a band, and never
  defaults to relocation.
- **A hybrid role inside the commute radius** is held to the band, not to the out-of-area hybrid
  floor, unless you set `compensation.hybrid_inside_radius` to `hybrid-tier` (below).

## Compensation — `config.json.compensation`

The pay floors a role is screened against. The floors themselves (`compensation.tiers`, one per
work setting) are yours to set; this section lists the keys added in 0.67.0.

| key | what it is |
|---|---|
| `compensation.currency` | since 0.67.0 — the currency your floors and your own `comp` figures are in, as a three-letter ISO code such as `USD`. **Not set by the upgrade, and asked once** (below). Until it is set, any pay the listing showed screens `PAY-UNCOMPARABLE` ("set compensation.currency to compare listed pay") and nothing is removed on it, because "$" does not say which currency. Once set, a listed range in the same currency is compared against the floor, and a range in any other currency screens `PAY-UNCOMPARABLE`. Your own `comp` figure is unaffected |
| `compensation.non_employee` | since 0.73.0, optional — the pay floors for fractional, interim, advisory and contract roles: `{"floors": {"day": 1500, "hour": 200}, "note": "..."}`. Units are `year`, `month`, `day` or `hour`; each value is a positive whole number in your `compensation.currency`. A figure is compared only with the floor in its own unit and is never converted. Not set by the upgrade (any value would be a guess). Without it, these roles get a `PAY-UNCOMPARABLE` review verdict that names this key, never a removal |
| `compensation.hybrid_inside_radius` | since 0.67.0 — `band` (the default) or `hybrid-tier`. Only consulted when an anchor declares `bands`. `band` screens a hybrid role inside your commute radius against the commute band, like an onsite role; `hybrid-tier` keeps screening it against the hybrid floor, for a profile that prices hybrid separately. The upgrade sets `band` where the key is absent and never overwrites a value you have |

**The one ask.** `compensation.currency` is the only thing the upgrade asks of you. If the key is
absent, the upgrade files **one** ask in `asks.jsonl` (`kind: system`, id
`set-compensation-currency`) asking you to set it. A second filing replaces that row by its id
rather than adding another. Set the key, then resolve the ask; if the upgrade step runs again and
finds the key present, it closes an ask that is still open. Nothing else about the upgrade needs
you. Before the upgrade seeds the other keys it keeps a copy of your file as
`config.json.pre-0.67.0` beside it, and it never overwrites a value you already have.

## Screening — `config.json.screen`

| key | what it is |
|---|---|
| `screen.likely_pass_signals` | since 0.67.0, optional — a list of `{id, phrase, fields, reason}`. `phrase` is plain words, matched case-insensitively as a whole phrase (not a pattern). `fields` is any of `title`, `jd` (the job-description text the run read) and `company` (the company record's name, vertical, size, headquarters and note). `reason` is what you would say in a word. A match is shown as a **LEAN** with its reason on the role's card, **and never removes the role or changes the screen's verdict**: only the hard rules remove. Absent means no signals. Since 0.69.0, a signal whose `fields` is `["title"]` is the *mandate*: a title match not covered by one of your `targets.titles` shows `OFF-MANDATE` and leans pass — see *The title floor and the mandate* above |
| `screen.title_floor` | since 0.69.0, optional — one of `intern` · `entry` · `associate` · `senior` · `lead` · `manager` · `director` · `vp` · `executive`, lowest first. A title that reads below it is flagged `BELOW-FLOOR` and leans by pay; **it never removes the role**. Anything else (a different spelling, a list, a number) is refused with the levels named. Absent or `null` means no floor. Not added for you by an upgrade |

## Sourcing — `config.json.sourcing`

Another small settings block at your profile root, alongside `ats` above — this one about **how**
a role was found, rather than the application's own clock.

| key | what it is |
|---|---|
| `feeds.enabled` | since 0.76.0, the full path is `sourcing.feeds.enabled`: a boolean, the on/off switch for **all** company feeds at once. **Absent means on**, exactly as in 0.72.0. `false` polls no company feed (every company is then read by the browser as before) and changes nothing else: no company's `ats` slug is touched, so turning it back on resumes where it was. A new profile gets an explicit `true`. Set it with `record.py source off company-feeds` / `source on company-feeds`, not by editing the file |
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

## Communications — `config.json.communications`

Two thresholds that decide when silence after your message becomes something to act on. Every
profile already carries both; a profile that has not set one gets the default below.

| key | what it is |
|---|---|
| `chase_after_days` | days after your last message before a thread with no reply stops reading as *waiting* (too soon to chase) and reads as *silent*. Defaults to **7**; accepted range 1–60. **Lower it** and a thread is chase-able sooner, so a follow-up is proposed earlier; **raise it** and you wait longer first. Silence still has to be *verified* against your mailbox before it counts — the number is the earliest a thread can qualify, not a promise a chase will be drafted that day |
| `no_response_after_days` | once a thread is verified silent, the days of silence at which the suggested move stops being a **chase** (a nudge on the same thread) and becomes a **reconnect** (a fresh, warmer approach). Defaults to **14**; accepted range 1–90. **Lower it** and you move to a reconnect sooner; **raise it** and the drafter keeps chasing for longer. Read by the brief (see *The brief ledger* above), so changing it changes the `register` on every brief computed afterwards — never a row already written |

Both are written in full as `communications.chase_after_days` and
`communications.no_response_after_days`. `profile.py --options` prints each with its current
value and whether it came from your file or the default.

## Mailboxes — `user.json.mailboxes`

Which Gmail addresses the job search may read. Each entry is a **reference** to an account
that `gmail-multi` already holds, not a copy of it.

| field | what it is |
|---|---|
| `address` | the Gmail address. It must also be registered with `gmail-multi` (`/gmail-multi:accounts`), which owns the list of accounts on your machine. An address it does not know is not searched, and you are told |
| `kind` | optional. A short label for what the account is, for example work or personal |
| `note` | optional. Free text for you |

- **Since 0.63.0 there is no `keychain_service`.** Earlier profiles carried one on every mailbox.
  Nothing read it, and the first session after upgrading removes it (after saving a copy of the
  file beside it). The app password itself is in your operating system's credential store,
  never in this file.
- **Edit the list with `/jobsearch:mailboxes`, not by hand**, so that the registry check runs.
  Adding an address gmail-multi does not know is refused, and nothing is written.
- **An address missing from `gmail-multi` is never skipped silently.** The upgrade adds one ask
  per such address, `mailbox-unregistered:<address>`, until you register or remove it; the sweeps
  print a line for it and count it as not covered.
- **Under `claude-gmail`** (below) this list is not consulted, because that connector reads the
  one account you signed in to in claude.ai.

[Mailboxes](mailboxes.md) explains the two lists, what the job search can and cannot reach, and
the upgrade step by step.

## Mail connector — `config.json.communications.mail_connector`

Which Gmail connector the job search reads mail through. The search uses **one**, the one you
pick, and nothing else.

| key | what it is |
|---|---|
| `mail_connector` | `gmail-multi` or `claude-gmail`. **`gmail-multi`** (the default) is the plugin that installs alongside this one and searches every address you listed with `/jobsearch:mailboxes`. **`claude-gmail`** is the Gmail connector managed in claude.ai, which searches the one account you signed in to there |

Written in full as `communications.mail_connector`. A profile that never set it reads `gmail-multi`, exactly what
it did before this key existed, so nothing needed changing when it arrived.

- **An unknown value is refused, not guessed at.** Set it to anything else (a typo, a connector the
  plugin does not support) and the run stops with a message naming the two valid values. It is
  never quietly read as the default, because that would send your search through a connector you
  did not choose.
- **The other connector is switched off for the search.** With one selected, the plugin blocks the
  other one's mail tools and tells you which is selected and how to change it. This is enforced, not
  a suggestion.
- **With `claude-gmail`, the scheduled mail sweeps skip.** The checks that read your mail directly
  (the alert sweep, the meeting check, the ATS and follow-up sweeps) work only through
  `gmail-multi`. Under `claude-gmail` each one says in one line that it skipped and why, and the
  run summary reports it as a gap, not as "nothing new".
- **Every run says which connector it used.**
- **One limit.** The claude.ai connector is recognised by its tool names. A different connector that
  happens to expose a tool with the same name is treated the same way.

`/jobsearch:mailboxes` shows the current selection.

## Search posture — `config.json.search`

How much the plugin is allowed to do on its own — your cost tier. See *Cost* in
[How it works](how-it-works.md) for the four shipped tiers side by side.

| key | what it is |
|---|---|
| `search.posture` | the **name** of the tier in force, one of the names defined under `search.postures`. Defaults to `economy` on a new install. **Changing it changes what every scheduled run may do**: how often it fires, how many agents it may start, whether it may research or draft unattended, whether it may touch LinkedIn. **It does not change how much of what a run finds is processed**: every role a run sees is accounted for and minimally screened under every tier, and work a tier refuses is queued, not dropped (see *Deferred items* below). `posture.py` shows the effect (`posture.py --may drafting`, `--cron`). A name that is unset, or that is not defined in `search.postures`, permits **nothing** — the run reads the cheapest interpretation rather than guessing you meant a larger one |
| `search.postures` | the table of tiers, keyed by name. Each tier holds `runs_per_day`, a `cron` line, `max_agents_per_run`, `max_drafts_per_run`, an `unattended` list of what it may do without you (`sweeps`, `linkedin`, `research`, `drafting`), and a `_for` note describing it. **Retune a tier** by editing its numbers, or **add your own** by adding a name with the same keys and pointing `search.posture` at it. The engine reads the numbers and the permission list, never the name. `doctor.py --fix` puts the shipped four back if the table is missing, and only ever adds |
| `linkedin_runs_per_day` | lives **inside a tier** — `search.postures.<tier>.linkedin_runs_per_day` — not at the top of `config.json`. How many LinkedIn passes per day may actually reach a page, **independent of `runs_per_day`**: a run over its tier's quota still does everything else and only skips the LinkedIn pass. A tier that does not set it gets **1**; accepted range 0–20. **`0` switches LinkedIn passes off for that tier** (the pass is refused as skipped-for-cost and the work is queued, not lost). **Raise it** for more LinkedIn coverage at more cost — a LinkedIn pass is the most expensive thing a scheduled run does |

### Settings added in 0.67.0 (all under `config.json.search`)

The upgrade seeds each of these where it is absent and never overwrites a value you already have.

| key | what it is |
|---|---|
| `search.retained_search_age_days` | how many days old a role from a recruiter channel may be before the screen flags it and recommends asking the recruiter what stage the search is in. A whole number from 14 to 120; defaults to **35**. The default is our choice inside the 4 to 6 week window a retained search usually takes to a first shortlist, picked at the early end because a wrong flag costs one question and a late one costs research and letters for a closed search |
| `search.triage_per_run` | how many waiting roles one daily run reads and triages, oldest first. A whole number from 1 to 50; defaults to **10**. The run prints `triaging: N waiting, M triaged this run, K over the stuck bound` |
| `search.triage_stuck_days` | how many days a role may sit in `triaging` before it is shown to you anyway, labelled "not yet read (waited K days)", with the lean `ask`. A whole number from 1 to 14; defaults to **3**. Counted from the role's first sighting |

### Setting added in 0.72.0

| key | what it is |
|---|---|
| `search.warm_lookup_days` | how many days a company reads "looked, none found" on a role card after you record that you looked for a person there and found nobody (`record.py warm-lookup`). After that the lookup is owed again, because people change jobs. A whole number from 7 to 365; defaults to **90**. Not seeded by the upgrade: absent means the default |

### What the 0.72.0 upgrade writes

The upgrade is automatic and keeps the originals first. It does two independent things; either one that cannot be sure of itself says so, writes nothing, and tries again next session:

- **Company feeds.** For each company you track (not one marked `passed`) that has no `ats` key, it reads the company's own `career_url`, and the `jd_url` and sighting links of its roles. When they name exactly one Greenhouse, Lever or Ashby board, it writes `companies.ats` and links the company's careers-page channel (`channels.company_id`), creating that channel if there is none. It only reads strings and fetches nothing. Two different boards for one company are written nowhere and reported as `ATS AMBIGUOUS` for you to settle. Before the first write, `data/companies.jsonl` and `data/channels.jsonl` are copied to `*.pre-0.72.0`; if the result does not re-read cleanly the copies are put back. A company with `ats: null` is never touched. The upgrade writes no `warm_lookup` and no `search.warm_lookup_days`: those exist only when you record or set them.
- **The four feed hosts.** The feed reader makes web requests to `boards-api.greenhouse.io`, `api.lever.co`, `api.eu.lever.co` and `api.ashbyhq.com` (and, from 0.76.0, to Workday career sites; see *What the 0.76.0 upgrade writes* below). The 0.72.0 upgrade adds exactly those four to `sandbox.network.allowedDomains` in your **profile project's** `.claude/settings.json`, after saving a timestamped copy of that file. It leaves every other entry and setting alone, does not repeat hosts already listed, and never touches your global `~/.claude/settings.json`. A settings file it cannot parse is left exactly as it was, and the step waits.

### What the 0.76.0 upgrade writes

Two steps, both automatic, both keeping your own fields exactly as you wrote them. Either one that cannot be sure of itself says so, writes nothing, and tries again next session.

- **Source adoption** (`m_0_76_0_source_adoption`). Before 0.76.0 a hand-made channel for a board the plugin now lists (a manual-candidate job board or an investment firm's portfolio board) was just a row of yours. The upgrade compares each such row, one that carries no catalog stamp, with the boards the plugin once shipped. A row that is **exactly** one of them is given the catalog stamp (`channel_catalog_entry`, `channel_catalog_sha`, `channel_catalog_on`, `channel_catalog_rev`) and nothing else: no field of yours is changed, and a row you had retired stays retired. A row that is **nearly** one of them (the same id or the same board host, but edited) is not written; it gets one question in your asks, `source-adopt:<channel_id>`. Answer it with `record.py channel-catalog add <entry> --attach <channel_id>` to tie the row to the catalog, or `record.py source keep-mine <channel_id>` to leave it exactly as it is. Every other row is untouched, and the upgrade never turns a source on or off, creates a row, or writes `sourcing.feeds.enabled`. Before the first write, `data/channels.jsonl` is copied to `channels.jsonl.pre-0.76.0`; if the result does not re-read cleanly, the stores are put back.
- **The Workday host** (`m_0_76_0_workday_hosts`). Workday career sites, read as company feeds since 0.76.0, are served from many hosts of the form `<company>.wd<N>.myworkdayjobs.com`. The upgrade adds the one entry `*.myworkdayjobs.com` to `sandbox.network.allowedDomains` in your **profile project's** `.claude/settings.json`, after saving a timestamped copy of that file. It leaves every other entry and setting alone, does not repeat an entry already listed, and never touches your global `~/.claude/settings.json`. A settings file it cannot parse is left exactly as it was, and the step waits. Whether the sandbox accepts that wildcard for these two-level host names is not yet confirmed; if it does not, Workday companies show as not covered and the browser reads them.

A catalog update after that (a plugin version that changes a source you turned on) is applied at session start only to rows you have not edited; see *Your sources* in [How it works](how-it-works.md).

### Attended and unattended

A tier's `unattended` list is for **unattended** runs. A run is treated as unattended **unless
you start it in an explicit attended form**, for example `/jobsearch:daily-run attended`. The
engine never works out that you are at the keyboard from a missing scheduler marker. An attended
run may research and draft even when its tier would hold that work. It **never** gains LinkedIn
access that way: `linkedin` stays governed by the tier's `linkedin_runs_per_day` and by whether a
signed-in browser is available.

## Deferred items — `data/pending_actions.jsonl`

When a run finds work it cannot or may not do right now, it writes one line here, so the work is
a row, not a sentence in a summary. The next run that is able to do it picks it up. Each item
is built by a script (`deferred.py`), which is why you rarely write one by hand. Nothing here is
ever a send: a queued item is research, a capture or a draft that is saved and never sent, and
the queue refuses free text that reads like a send.

| field | what it is |
|---|---|
| `id` | the item's id |
| `kind` | what procedure drains it: `action` (free text written with `deferred.py --add`, and the owed LinkedIn pass), `capture-role`, `research-role`, `draft-message` or, since 0.69.0, `read-jd`. The `capture-role`, `research-role` and `draft-message` kinds are new in 0.61.0, so that a role a run saw, or research a tier held, is a structured row rather than a free-text sentence |
| `ref` | since 0.61.0, optional: what the item is *about*. For `capture-role` it is the posting's canonical URL (tracking parameters removed, a LinkedIn posting reduced to its job id). For `research-role` and `draft-message` it is the role's id. Adding the same `(kind, ref)` while one is pending writes no second row. Older rows have no `ref` and behave as before |
| `what`, `why` | the instruction in plain words, and why it was deferred |
| `requires` | what a worker needs to take it: `research`, `drafting`, `sweeps`, or a machine capability such as a browser. Empty means any worker under any tier |
| `status` | `pending` until it is done |
| `quarantine` | since 0.69.0, only on a `capture-role` item queued from a degraded sweep: `{run_id, because, queries}` — the run that saw the role, why it is held (one or more of `filter-dropped`, `param-added`, `window-unapplied`, `truncated`, `query-unparsed`), and which of that sweep's queries showed it. While present, no worker is served the item. Absent on every other item and once released. A release is a separate appended row of kind `_unquarantine`, never a rewrite of the item |
| `queued_run` | since 0.69.0, only on a `read-jd` item: the run that queued it, so that run is never handed back the job it could not do |

**Held by posture.** A `research-role` item requires `research`, and a `draft-message` item
requires `drafting`. Under a tier that does not permit that work the item is **held**: it is
listed as *held by posture* in `deferred.py --claimable`, counted in the run summary, and
stays pending. It is not failed and not dropped. The first run whose tier (or whose attended
form) permits the work claims it, does it, and marks it done. Only the names `research`,
`drafting` and `sweeps` can be granted by a tier; an unknown name in a tier's `unattended`
list is ignored and reported, never granted. `linkedin` is never granted that way. A browserless
machine can never claim a LinkedIn item, under any tier.

**Carried roles.** When a LinkedIn or board pass sees a role that is not yet captured, known or
passed on, it becomes one `capture-role` item. The run captures it, screens it, and
`deferred.py --settle` closes the item once the role exists in your pipeline. Whatever is not
captured stays pending and is listed on the next run, under any tier.

**A degraded sweep is held, not captured (since 0.69.0).** A sweep can come back looking clean while
the page it read was not showing what was asked: a filter the run set was dropped, one it never set
was added (an injected pay band, say), the date window was not applied, or the result list was cut
short ("99+" results, fewer shown). Roles from such a page are not safe to capture as if the sweep
had been whole. So each query line in a sweep's hand-back now says `dropped=` (filters it asked for
that the page did not apply), `added=` (filters the page applied that it did not ask for) and
`total=` (a lower bound is written `<m>+`), and every role line says `q=`, which queries showed it.
A role is **held (quarantined)** when every query that showed it reported a degradation. One clean
query that also showed it is enough to vouch for it.

- **Only a positive report holds a role.** A named dropped or added filter, `unapplied`, or a
  truncated list. `dropped=?`, `added=?` (the sweep could not read the filter state) and a total it
  could not read are counted and filed as a gap for that query, and they never hold a role.
- **A held role** is still written as one `capture-role` item, with the `quarantine` field above.
  `deferred.py --claimable` shows it under *QUARANTINED* (with a count by reason) and no worker is
  served it. `--claim` on it refuses with the reason.
- **A held role is released** in one of two ways: a later sweep sees it through a clean query (the
  run says `RELEASED` and appends the release), or you run
  `~/.claude/jobsearch/run deferred.py --unquarantine <item id>`. A claim never releases it.
- **The run's accounting.** The pass's `roles` event now reads `distinct = captured + known +
  carried + quarantined + role_gaps`, and the end-of-pass lines say how many were held and why,
  for example `HELD 2 role(s) (quarantined) from degraded queries: filter-dropped x1 · truncated x1`.
  See *Reading what the search produces* for the summary line.
- **What this does not do.** Whether a page dropped a filter is the sweeping agent's own report of
  what it saw. No script can check that against the page, so this catches a sweep that reports
  honestly, not one that does not look. That is why the counts are kept and shown (see the
  all-clean flag in *Reading what the search produces*). A role the pass already captured while it
  was still sweeping, before its hand-back was checked, cannot be held after the fact; it is
  counted and the line says `DEGRADED QUERY`.

**A job description only a browser can read (since 0.69.0).** When the triage step meets a posting
it cannot read on a surface with no browser (a sign-in wall, a headless or cloud run), it queues one
`read-jd` item for that role with `deferred.py --add-jd-read <role id> --run <run id>`. It is
one per role (asking twice adds nothing), needs the machine capability `chrome`, and is served only
to a worker that has a browser and did not itself queue it. That worker reads the posting and
records it on the role's `fit`. The role stays in *Triaging* meanwhile. If no browser-holding
worker has done it once the item has waited more than `search.triage_stuck_days` days,
`deferred.py --settle` records `fit.jd_source` as `unavailable: surface-cannot-read` on the role
and it goes to Decide with the lean `ask`. That value cannot be written by hand earlier: the
record script refuses it unless such an item exists and has waited past the bound.

**What a sweep hands back about each role (since 0.67.0).** Besides title, company, location and
link, each role line now carries three slots a screen needs: `posted` (the posting date; an `ats:`
prefix marks the employer's own date, a bare date or a shown age such as `12d` is a board's, and `?`
means not read), `pay` (`none` when the listing showed none, `stated:` or `estimate:` followed by
the range such as `120000-150000/yr/USD`, or `?` when it was not read) and `setting` (the work setting in the posting's words, `none stated`, or
`?`). **`?` is stored as nothing at all, which reads as not captured, never as `none`.** `pay` and
`setting` must be present on every line: a sweep that leaves them out is a gap in that run, not a
quiet blank. A script, not a model, parses each slot and keeps the result on the queued
capture item (as `listed_pay`, `posted` and `location_declared`, in the shapes a role stores).
When the run opens the role from that item, `record.py create … --from-item <the item's id>` copies
those three onto the new role, so a pay the sweep read is on the role without anyone retyping it
(a slot the sweep marked `?` is left off, so it still reads as not captured). A role created
without `--from-item` carries none of them; the run's triage step then records whatever the role
still lacks (`record.py listed-pay`, `record.py posted`, the work setting in `location.declared`).

## Dashboard — `config.json.dashboard`

| key | what it is |
|---|---|
| `body_collapse_words` | the word count above which a long free-text body on your dashboard — an ask's text, a role decision's memo — is shown as its opening clause, its word count and where to find the full text in your data, instead of in full. Defaults to **120**; accepted range 20–2000. **Lower it** for a shorter, more scannable page; **raise it** to read more without opening the record. **A draft that is ready to send is never collapsed, however long.** Only the page changes — the record itself is never shortened |

## Dispatch packet — `config.json.dispatch_packet`

When the plugin hands one job to a drafting agent it first prints a single packet of what that
agent needs. Two sections of it come straight from your own prose and are unbounded as you wrote
them, so each has a length cap; a section over its cap is cut at the cap and followed by a
`PACKET TRUNCATED` line naming the section and how much was dropped — never cut silently.

| key | what it is |
|---|---|
| `section_cap.voice` | the cap on the packet's `voice` section — your *Message style* text from `configure/strategy.md`, verbatim. Defaults to **2000** characters; accepted range 200–20000. **Raise it** if a long style guide is being cut off mid-thought (the agent then sees more of how you write, at the cost of a bigger packet); **lower it** for a leaner one |
| `section_cap.claims` | the same cap for the `claims` section — the parts of `presence/claims.md` matched to this draft. Defaults to **3000**; accepted range 200–20000. Raising it lets more of your matched background reach the agent; lowering it risks a claim being cut before the agent sees it |
| `section_cap.other` | one cap shared by every other section of the packet, which are short by construction. Defaults to **1500**; accepted range 200–20000. You should rarely need it: a `PACKET TRUNCATED` marker on a section other than `voice` or `claims` is the sign to raise it |

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

**You do not need to open it, and there is nothing there worth reading — with one exception,
described next.** Every value the diagnostics log and the drift markers store is a timestamp, an
event name, a version number, or a count — never a company, a contact, a message, a comp figure, or
any other fact about your search. The code that writes to them only accepts values shaped like short
codes and discards anything that looks like free text, so this holds even if a bug elsewhere tried
to write something it shouldn't.

**The exception: `handbacks/`.** The folder also holds the long reports your search's helper agents
hand back, each in its own file, so that a long report is a file you can open rather than a wall of
text in the conversation. One of them is kept for a reason of its own: when a job-search pass or a
board sweep hands back its list of roles and the daily run finds a problem in it, the run keeps
a byte-for-byte copy at `.jobsearch/handbacks/roles-<run>-<surface>.md` (the run's id, and
`linkedin-jobsearch` or `board`). It is kept when the whole report is refused, and also when some
lines are accepted and others are not. A bad line costs only that line: every role on a good line is
still recorded, and each bad line is listed as a gap in the run's journal with its line number and
the rule it broke. The kept copy is the whole report as the helper wrote it, so you can fix the
lines and re-run it. **Unlike the rest of this folder, these files do name roles and companies**,
because that is what a list of roles is. They stay on your machine, in the same git-ignored folder.

Before a report is accepted, `deferred.py --add-roles <file> --run <id> --surface <s> --check` reads
it the same way and prints each faulty line and a one-line verdict without writing anything.

**One more small file: `coverage_check.json`.** A coverage gap can be marked as already explained
by a filed issue (`journal.py --gap … --covered-by "public #58" --covered-reason "…"`), and that
citation hides the gap from the routine check. `journal.py --check-coverage` asks GitHub whether each
cited issue is still open and writes the answers to `.jobsearch/coverage_check.json`, one entry per
citation: `OPEN`, `CLOSED` or `MISSING`, and the date it was checked. It stores no issue titles, only
the citation, the verdict and the date. The routine `journal.py --check` reads this file without
touching the network: a gap whose citation was last known closed or missing is counted as open
again, with the reason shown, and a citation that has never been checked is reported as
`unverified` in the count line. If the file is missing, nothing has been checked yet and every
citation reads as unverified; if it cannot be read, the check says so and treats them the same way.
You can delete it at any time; the next `--check-coverage` writes it again.

**Two more small files: `purity-check.json` and `purity-progress.json`.** At the start of a
session the plugin checks that its own files do not contain text from your profile (a name, an
employer, a contact), because those files are meant to work unchanged for anyone. `purity-check.json`
is the verdict of the last complete check. `purity-progress.json` is how a check that runs out of
its few seconds of session-start time carries on where it stopped on the next run instead of
starting over: for each of the plugin's own files it keeps a fingerprint of the file as it was
checked, and which lines matched. A file whose fingerprint has not changed is not read again, so a
check that cannot finish in one session still finishes within a few, and a later check only reads
what changed. The progress file is thrown away and the check starts from the beginning
whenever the plugin is updated or the names it looks for change, so an old "clean" answer is never
reused for a question it was not asked. Neither file contains a name, an employer or any text from
your profile or from the plugin's files: a match is recorded only as a file, a line number and a
position in the list. You can delete either at any time; the next check writes it again.

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
