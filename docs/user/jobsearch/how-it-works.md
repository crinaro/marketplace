# How it works

A tour of what this plugin is, what runs when, and what it will never do without you.
If you just want it installed, start with **INSTALL.md** and come back here.

---

## The two halves — and why they are never the same folder

| | the engine | your profile |
|---|---|---|
| what it is | this plugin: skills, agents, scripts | your search: resume, contacts, roles, history |
| where it lives | wherever Claude Code installs plugins | a private directory **you** create and own |
| who can see it | anyone — it is public | only you |
| changes when | you update the plugin | every day you run it |

Everything personal lives on the right. Nothing personal lives on the left, and an automated
check enforces that on every change we publish.

This split is the single most important thing to understand, because it explains almost every
other design choice: the engine can be public, updated, and shared precisely because it holds
none of your data. Your profile is yours — back it up, put it in a private git repository if you
like, move it between machines.

> **You point the engine at your profile once.** After that, every command resolves it at
> runtime. If the pointer is missing the engine says so loudly rather than reading an empty
> folder and reporting that you have no opportunities.

---

## What actually runs

Four kinds of thing, and the difference matters when something misbehaves.

**Scripts** do the deterministic work — sweeping a mailbox, checking a calendar, finding
silences, building the dashboard. They are plain Python with no packages to install, they give
the same answer every time, and they cost nothing beyond running them. Most of the daily value
is here.

**Commands** are what you type: `/jobsearch:coordinator`, `/jobsearch:checkup`, `/jobsearch:tier`. They are
entry points. [Commands](commands.md) lists every one in plain words.

**Agents** are the parts that need their own context window — bulk reading (sweeping a mailbox,
scanning boards) or judgement (reading a job description against your resume, drafting a message
in your voice, researching a company). Each runs in its own context and reports back. Reading a job
description is one of these: a script fetches the page first, and what it cannot read goes to a reader
agent that works in a browser tab of its own, or to you (see *One lifecycle per role*, below).

**Skills** are procedures the assistant follows, loaded when a session starts.

> ⚠️ **Skills, agents and hooks load once, when a session starts.** If you update the plugin
> mid-session, scripts pick up the new version immediately but the loaded instructions do not.
> Start a fresh session after an update.

> **Gmail is a second plugin.** The tools that read, search and draft mail — this plugin never
> sends — come from `gmail-multi`, a standalone connector. Right after you install this plugin,
> its first session start installs the connector for you, from the same marketplace you
> installed this plugin from; you do not configure it separately, and the first session after
> that also points it at your profile, so a mailbox you add here reaches it without any second
> setup step. It is not this plugin misbehaving if you see `gmail-multi` in your
> installed-plugins list; it is how mail coverage works. **The tools take one extra session to
> arrive** — start a fresh session after installing before you expect Gmail tools to show up.
> **If mail tools are still missing after that,** run `claude plugin list`: this plugin's own
> commands keep working either way, so the symptom of a missing connector is never this
> plugin's commands going unrecognized — it is specifically the absence of Gmail tools. If the
> connector did not install itself (it will say so plainly when that happens), installing
> `gmail-multi` yourself from the same marketplace fixes it.

---

## A day, in order

Nothing below sends anything or commits anything without you.

1. **Session start.** The plugin checks its own installation is intact, and brings your profile's
   data format up to date if the version moved — the first such update also points the Gmail
   connector plugin at this profile, a one-time step (see **What actually runs**, above). All of
   this is automatic; none of it asks you anything.
   If the data format is current but `validate_data.py` still reports problems, session start says
   so in one line with the count, instead of "Profile is current", and points you at that script.
   (The 0.76.1 upgrade can ask one question in your asks for a row it cannot repair; see
   *What the 0.76.1 upgrade writes* in [Your data](your-data.md).)

2. **Sweep.** Your mailbox and LinkedIn are read for things that changed: recruiter replies,
   interview invitations, application receipts, rejections. This is deterministic — it finds
   what is there, it does not interpret. Employer career pages and job boards are searched on the
   days your posture names (see *Cost*), never on every run. Status mail from employers is counted
   by kind each run (application status, a person writing, a digest, noise), and a status message the
   plugin could not match to a role is listed by sender and subject, not dropped.

3. **Reconcile.** New findings are matched against roles you already track. A role seen twice on
   two job boards is *one* opportunity with two sightings, not two opportunities. Ambiguous
   matches are surfaced for you to confirm rather than merged automatically, because one job
   title can genuinely be several different roles.

4. **Read and screen.** Each role the run takes on has its job description read, and only then is it
   screened (see *One lifecycle per role*, below). Roles are checked against the floors you set — compensation, geography, work
   setting. A role whose office is far beyond every place you said you would commute from, and is
   not somewhere you would move to, is removed as too far (see *Where a role is, and when it is
   too far* in [Your data](your-data.md#where-a-role-is-and-when-it-is-too-far--since-070)). Something below your floor does not silently vanish; it is marked, and you can see
   why. A role you accept at that pay (`decide <id> pursue --why-kind comp-acceptable`) shows as
   accepted and is never removed; reversing the decision brings the removal back. Fractional,
   interim, advisory and contract roles are measured against your separate non-employee pay floors
   when you have set them, never the annual ones; without them they are marked for your review,
   not removed. A pay quoted by the hour or day is never removed against an annual floor.

5. **Surface.** What needs a human decision is collected: replies waiting, applications with no
   acknowledgement, conversations that have gone quiet, questions the assistant needs answered
   to pitch you accurately.

6. **Draft — only if you asked.** Outreach and cover letters are written citing sentences from
   your own resume rather than paraphrasing them. A draft is *staged*. You read it, you edit it,
   you send it.

---

## One lifecycle per role (since 0.82.0)

Every role goes through one sequence, and a run does not stop halfway through it:

1. **Capture.** A role a sweep found is recorded, or matched to a role you already have. What a search
   result card showed (pay, work setting, location) is kept, but marked as *provisional*, because a card
   is often wrong or thin.
2. **Read.** The job description is read for **every** role that has not been removed. A script tries a
   plain fetch first for a remote posting that states its pay; anything else, or anything the fetch could
   not read, goes to a reader agent working in a browser tab of its own. A posting only you can open comes to you
   as **your read**, and a posting that is down ends there as *gone*. The description's own pay and work
   setting replace the card's.
3. **Screen.** Your floors and rules are applied to the facts from the description. A screen that rests
   only on card facts can never say *keep*.
4. **Research.** Only a role the screen **keeps** is researched. A role marked for your review, or one the
   screen removed, is not.

A role is ready for your decision when it has been through all four. If you change a pay floor, your
title floor, your target titles or a likely-pass phrase, roles screened under the old rules go back to
*waiting* and a later run re-screens them.

**A run takes on a limited number of roles and finishes every one.** The limit is `search.intake_per_run`
(40 unless you changed it; a number above what the run has time for is trimmed, and the run says so).
While older unread roles are still waiting, half of the places go to roles found since. Roles found but
not yet taken on are *waiting*, counted and aged. **Anything a run took on and did not finish is a
process failure**, shown with its cause and how long it has been there: on the dashboard, in Your Move,
in the coordinator's start line and in the run's headline. Nothing is hidden, and an old unread role stays
a failure until it is read. Reading the files that show this is in
[Reading what the search produces](reading-your-files.md#one-lifecycle-per-role-since-0820).

**What a run looked at and what it did not.** A run that could not look at everything says so in its
headline as `DID NOT LOOK`, with a count and an age: company feeds it ran out of time for, searches it
could not reach, mail it could not read.

---

## Finding roles beyond the boards (since 0.72.0)

Three additions widen where roles come from. None of them sends anything or applies to anything.

### Company feeds

Many companies publish their openings through Greenhouse, Lever, Ashby or Workday. The first three publish a plain
public list of a company's open roles for exactly this purpose. When a company you track uses one, the daily
run reads that list with a script (no browser, no tokens, no mail) before the board pass, every day, under
every posture.

**A slug** is the board's short name in its address: in `jobs.lever.co/acme-example` the slug is
`acme-example`. It is never guessed. It is read, as text only, off a link you or the research step already
attached to that company: its `career_url`, a role's `jd_url`, or a sighting's link. A sender domain in a
receipt email never identifies an employer, so mail is not used. A company with no such link
stays on the browser route. (Workday is read differently, from a company's address of the form
`<company>.wd5.myworkdayjobs.com/<site>`; see *Workday career sites* in *Your sources* below.) The result is `companies.ats` (see *Companies* in [Your data](your-data.md)).

For each company with a slug, the run makes one read-only `GET` of the vendor's public list. It never posts
anything and never submits an application. It keeps the postings whose title matches one of your
`targets.titles`, and hands each through the same code a board sweep uses: a role you already have writes
nothing, a new one is captured and screened exactly like a board role. A feed that does not return the
documented list is **never read as "no roles"**: the page is listed for your browser review instead, and a
failure of the machine to reach the vendor is reported once as a gap rather than turning every careers page
into a daily visit. The poll has its own deadline (`sourcing.feeds.deadline_s`, 240 seconds unless you
change it), so a stalled network ends in a written summary, not a hung run. When a poll runs out of time
before reaching every company, it records which ones it did reach, and the next poll starts with the
companies covered longest ago, so the same companies are not skipped every day. The companies it did not
reach are counted under `DID NOT LOOK: feeds` in the run's headline. A company whose feed is cut short by
the deadline on two polls in a row is listed as due for a browser review until one is done.

Check or correct what it knows:

```
feed_poll.py --status                      # slugs, each company's last outcome, ambiguities, unlinked pages
record.py ats <company_id> --url <URL>     # set the board from a careers or posting address you give
record.py ats <company_id> --none          # decline a feed for this company; nothing rewrites it
record.py ats <company_id> --clear         # remove the entry so discovery may run again
```

`--status` also prints `ATS AMBIGUOUS` when one company's links name two different boards. Settle it with
`record.py ats <company_id> --url <the right board>`.

**The four hosts.** Reading a feed means web requests to `boards-api.greenhouse.io`, `api.lever.co`,
`api.eu.lever.co` and `api.ashbyhq.com`, and to nothing else. They are a requirement, not a preference: if
Claude Code's command sandbox is on and a host is not allowed, a scheduled run would wait on a prompt that
nobody is there to answer. The upgrade to 0.72.0 adds the four to `sandbox.network.allowedDomains` in your
profile project's `.claude/settings.json` (what else it does is under *What the 0.72.0 upgrade writes* in
[Your data](your-data.md)). If the sandbox ignores that entry, which the vendor documents as the case when an
administrator requires the sandbox, the hosts must be allowed in that administrator's settings. Until then
the feed reports `egress-blocked` or `unreachable` with one gap per host, and the browser sweep keeps covering
those careers pages as before. Nothing is lost and nothing is hidden: the pages are covered by the browser
instead, which is slower and costs more, and a feed that could not be read is counted in the run's headline.

### Finding a company's job feed

A feed is only read for a company whose Greenhouse, Lever or Ashby board the plugin knows. It learns that
from addresses you or the research step already attached to the company. A company whose careers page sits
on its own website, with the board linked from that page, was never found that way. `/jobsearch:sourcing
employers attended` closes that gap, in a session you are present for. For each company you already track
that has no feed, it reads the company's own careers page, plus at most one link to another page on the same
site, politely (one request a second to a host, and a site's robots file honoured). It only **proposes** the
board it finds. You accept or decline each one, and nothing changes in your companies until you do. A
decline is remembered and the plugin does not ask again. It never guesses a board from a company's name, and
the form without `attended` only shows what is waiting, with no web request. Because it reads employers' own
websites, the command sandbox may need to allow those hosts; when it cannot reach one, the command says so
rather than reporting "no board".

### The warm path on each role card

Referrals are the evidenced lever: warm outreach to a person at the company produces far more conversations
than a cold application. So every role that passes screening and is not passed on shows one line,
`Warm path:`, naming the single next action toward an inside person. It is worked out from your own people,
touches, drafts and applications each time, never stored, so it cannot go stale. One person at one company is
asked once, not once per opening there.

| line says | meaning |
|---|---|
| referral ask to *person* (after you decide) | someone you know there is not the hiring manager; the draft waits until you decide to pursue the role |
| note to the hiring manager *person* (after you decide) | the person you know is the hiring manager |
| ... (draft owed) | you decided to pursue (or applied), so a draft is owed to that person |
| ... (draft ready for you to send) | a draft already exists in your drafts file |
| ... (asked *date*) | you already reached out to that person recently or about this role: no second ask |
| no one known: look up on LinkedIn, then record who you found | nobody known; the link appears only when a LinkedIn company address is already on record, and you open it yourself |
| looked *date*, none found | you recorded that you looked; quiet for `search.warm_lookup_days` (90 by default) |

Record who you found as a people entry and `record.py involve`, or `record.py warm-lookup <company_id>
--none-found`. **Nothing here is ever sent.** The engine does not open LinkedIn for this, read it, or contact
anyone; a draft is written for you to send, as every draft is.

### Your sources

Every job source the search uses is listed in one place, from your own files, and each one has an on/off
switch. Print the list any time (it changes nothing):

```
python3 scripts/record.py source list
```

(`/jobsearch:sourcing` shows the same view.) For each source it gives the kind, whether it is **on**, whether
it came from the plugin's shipped catalog or is yours, and whether it is covered. Anything it cannot know prints
`NOT CHECKED`, never `0`. The kinds are:

| kind | what it is | example |
|---|---|---|
| browser-read board | a board Claude reads in your signed-in browser | the Indeed sweep, the LinkedIn job search |
| alert-email sender | the job-alert emails a board sends you, swept from your mail | LinkedIn, Dice and Indeed alerts |
| company feeds | the one switch for every company's own job list (see *Company feeds* above) | all of them together |
| curated board | a board whose terms forbid automated access; **you** open it | see *Curated boards and newsletters* |
| portfolio board | an investment firm's job board; **you** open it | see *Portfolio boards* |

**Turn one on or off.** `python3 scripts/record.py source on <id>` and `source off <id>`, where `<id>` is the
name `source list` shows (for example `indeed`, `company-feeds`). Turning a source off keeps the row and what
it was, so turning it on again puts it back exactly. It never deletes anything, and it changes nothing about the
roles already found. A recruiter, a referral or one of your own company careers pages is not a source in this
sense and is refused with the right command to use.

**What is on for a new install.** When a profile is created: company feeds, the LinkedIn, Dice and Indeed alert
emails, and the Indeed browser sweep are on. The LinkedIn job search, the curated boards and the portfolio
boards are off until you turn them on. **An existing install is never changed**: the 0.76.0 upgrade turns
nothing on and nothing off. It only recognises hand-made board rows that match a shipped one (see *What the
0.76.0 upgrade writes* in [Your data](your-data.md)).

**The Indeed browser sweep runs in your browser.** Because it is on for a new install, the first session tells
you once, in plain words: Claude opens Indeed in your signed-in browser pane and reads the listings that match
the titles in your profile. It never applies, messages or posts. Turn it off at any time with
`python3 scripts/record.py source off indeed`; `source on indeed --dry-run` shows the search it would run.

**Catalog updates.** A catalog update arrives with a plugin update and applies at the next session start to
rows you have not edited. One you edited is left alone, and if you and the catalog both changed it you get a
question (`channel-catalog take <id>` or `keep <id>`). A hand-made row that is *nearly* a shipped one gets one
question too: answer with `channel-catalog add <entry> --attach <channel_id>` or `source keep-mine <channel_id>`.

#### Workday career sites

A company on Workday has no public job list. The plugin reads the site's own published list of job pages
(its sitemap) and the standard job data the employer embeds in each page, only where the site's `robots.txt`
allows it, and only pages it has not seen. It never calls Workday's internal data interface. To set one up,
give the company's careers address with `record.py ats <company_id> --url <address>`. Because this is read
from the shape Workday sites are observed to have, not from a documented interface, the coverage `--status`
reports is deliberately modest:

- `covered (sitemap window; completeness assumed)`: the site's list showed fewer than 100 jobs and was read. The
  list is **assumed** to contain every open job; that is not proven. A run does not claim more.
- `not covered: sitemap-capped`: the list is at its 100-job limit, so jobs may be missing. The browser review
  covers the company.
- `not covered: locale-mismatch`: the address you gave is in a different language from the site's job pages.
  Give the address in the pages' own language.

Other `not covered` codes (for example `robots-disallowed`, `blocked`) mean the same thing: this company is
listed for your browser review instead, never read as "no jobs". A Workday job page carries no pay field, so a
pay figure found in the description text is marked as read from the description. The one-time sandbox entry
`*.myworkdayjobs.com` is added by the 0.76.0 upgrade; whether the command sandbox honours it is not yet
confirmed, and until it does a sandboxed scheduled run may report these companies as not covered.

### Curated boards and newsletters

Some boards forbid automated access in their terms (Wellfound, Y Combinator's Work at a Startup, Welcome to
the Jungle). They are channels with `access: manual-candidate`: **you open it**. The engine never visits them.

**Turn on a catalog entry.** The plugin ships a short catalog of these boards, checked once centrally so you
do not have to research each one. **None of these boards is on until you say so.** Turn on one entry, or every
curated entry in one write:

```bash
python3 scripts/record.py channel-catalog add wellfound
python3 scripts/record.py channel-catalog add --kind curated
```

The curated entries are `wellfound`, `welcome-to-the-jungle` and `yc-work-at-a-startup`. Add `--dry-run` to
preview the rows first. `python3 scripts/record.py source list` shows every entry and whether it is on, and
`/jobsearch:sourcing` suggests the entries that match what your profile already says (it only suggests, and
writes nothing). A board you already hold by hand is never duplicated: the refusal prints the `--attach
<channel_id>` form, which ties your existing row to the catalog so catalog updates reach it.

**Turn one off.** `python3 scripts/record.py source off <channel_id>`. A turned-off channel is never touched by a
catalog update, and `source on <channel_id>` restores it.

**Updates.** A catalog update arrives with a plugin update and applies at the next session start. A board you
have not edited is updated, and the session start prints a "channel catalog - N boards updated" block naming
each change. A board you edited is left alone. If you and the catalog both changed it, you get an ask, and you
settle it with `python3 scripts/record.py channel-catalog take <channel_id>` (use the catalog's values) or
`keep <channel_id>` (keep yours). Rows you wrote by hand carry no catalog stamp and are never changed.

**The manual path.** You can still add any board yourself as a channel with `access: manual-candidate`. If the
board sends alert emails, put the sender in the channel's `alert_sender` and those emails are swept like any
other. A niche newsletter is an `alert-email` channel the same way, one channel per newsletter so you can see
which one produces roles. Add them only if you want them; the upgrade adds none. The two rows for a firm's
portfolio board are in *Portfolio boards* below.

### Portfolio boards

Some investment firms, such as Vista Equity Partners and Francisco Partners, publish one job board that lists
roles across every company they back. Both of those boards run on a platform whose terms of use forbid
crawling or scraping, by hand-built or automated means. So a portfolio board is a **manual-candidate**
channel: **you open it**, and the plugin never reads it, polls it or sends a browser to it.

**Turn on a catalog entry.** The catalog lists two firms' boards: `vista-equity-partners` (Vista Equity
Partners, `https://vistaequitypartners.getro.com/jobs`) and `francisco-partners` (Francisco Partners,
`https://careers.franciscopartners.com/jobs`). **Neither is on until you say so.** Turning one on writes the
firm's company row and the board's channel row, linked by `portfolio_of`, in one step:

```bash
python3 scripts/record.py channel-catalog add vista-equity-partners
python3 scripts/record.py channel-catalog add --kind portfolio
```

`--dry-run` previews the rows. If you already track the firm under a different company id, pass `--firm
<company_id>`; if you already hold the board by hand, use the `--attach <channel_id>` form the refusal prints.
You open the board yourself, and the plugin never reads it. Turning one off, how updates arrive, and how
`take` and `keep` settle a disagreement are described under *Curated boards and newsletters* above and work the
same way here. The catalog stamp on each row is explained in [Your data](your-data.md).

**Add one by hand.** For a firm that is not in the catalog, paste these two rows, one into `companies.jsonl`
(the firm is an ordinary company) and one into `channels.jsonl`, and fill the placeholders. `portfolio_of`
names the firm's company id and `board_hosts` lists the board's own host, which the plugin must never open. When the plugin tries to fetch or open such a board through its web or browser tools, it is stopped: the message names the board and asks you to open it yourself. A fetch made through a shell command is not covered by that block.
`alert_sender` is optional and only matters if the board sends alert emails.

```jsonl
{"id": "<firm-id>", "name": "<Firm Name>", "vertical": "other", "status": "watching", "size_ownership": "investment firm", "research_log": []}
{"id": "portfolio:<firm-id>", "label": "<Firm Name> portfolio jobs", "type": "job-board", "access": "manual-candidate", "review_cadence": "weekly", "last_reviewed": null, "portfolio_of": "<firm-id>", "board_hosts": ["<the board's host>"], "alert_sender": "from:<the From address of one alert email from this board>", "scope_notes": "you open it at <the board's URL>; the engine never visits (its terms forbid automated access)"}
```

**Record a role you saw there.** Use the company's own posting address, never the board's:

```bash
python3 scripts/record.py board-sighting portfolio:<firm-id> --company "<name as the board shows it>" --title "<title>" --url <the company's own posting URL>
```

The verb creates or matches the company and records the role so the daily run takes it on like any other. It
never fetches the address, and it refuses one on the board's host. If the board only links to a page on
itself, open that page and find where the employer posts the role. A role whose every address is on the board
is never read by a run: it comes to you as **your read** (`manual-board`).

**See what a board produced.** `python3 scripts/portfolio_boards.py` prints, per board, the companies and
roles it produced and whether the board is covered. A board is covered only while your last review is inside
its `review_cadence`. A board you have not reviewed is reported as not covered, never as zero roles. It
fetches nothing and writes nothing.

**People you know at the firm.** If you know someone at a firm that backs a company, and nobody usable is
known at the company itself, the role card's `Warm path:` line offers a `backer-intro`: an ask that person for
an introduction into the company. It ranks below any person you know at the company, and a draft is written
for you to send, never sent. A backing you know of but never saw on a board goes in the company's `backed_by`.

### What it will not do

No auto-apply, no automated LinkedIn action, no bought contact lists, no tricks aimed at a screening model, no
service that applies or reaches out in your name. Each of these breaks a site's terms, puts other people's
data in your profile, or sends something you have not seen, and the plugin never sends anything for you.

---

## Is the role still open? Confirmation on the employer's own posting (since 0.80.0)

A job alert can outlive the job. A role copied from one board to the next stays "open" on every copy
long after the employer took it down, so the search no longer treats a role as real because an
aggregator lists it. Each role carries a record, `employer_posting`, of whether it was **confirmed on the
employer's own posting** (their careers page or applicant-tracking site), with the address and the date.

- **Research confirms it.** When the researcher finds the employer's posting, it opens it in the browser
  pane and writes down the visible text it saw, such as the Apply button. A plain fetch can say a posting
  is live; it can never say one is gone, because a fetched page from a script-driven site is often an
  empty shell that reads like a closed notice.
- **A role seen only on boards stays unconfirmed.** Two job-board copies, or an aggregator and a
  syndication copy, are never enough. Roles you already tracked before this version simply read as not yet
  checked; nothing about your data is rewritten.
- **Your Move and the dashboard flag what is not confirmed.** They flag, they do not hide: a role you
  are working through a contact, with no application in view, stays where you can see it. The two surfaces
  show the same text for the same role. The flag is read from the record, never from a note that says
  "confirmed".
- **The roles you are deciding on or pursuing are re-checked on the daily run.** A script reads the
  company's job feed first, then makes at most one read-only request per role per day, honouring the
  site's robots.txt. What it cannot settle is checked in the browser pane. The pane step runs on every
  run that has the browser, attended or not.
- **One sign that a posting is gone is not enough.** A single failed fetch or one "unavailable" page
  records a pending signal and the role shows "could not confirm". Only a second, agreeing signal marks it
  closed, and you still decide what to do with the role: nothing is expired automatically.
- **A check that did not happen says so.** If the machine was off, the browser was unavailable or a site
  was refused, the role shows `NOT CHECKED since <date>`. It is never shown as live.

**What is not verified.** Every "live" or "unavailable" the browser step records is the assistant's
statement of what it saw; no script watches the pane, which is why the exact visible text is kept beside
it. A site the pane has never visited can ask for approval. The search does not wait for that: it records
the site as refused and moves on, and the role shows `NOT CHECKED`. Whether an approval you gave in a
session you were watching carries over to a later scheduled run **has not been verified**, so do not count
on it. Whether a pending approval can stall a scheduled run has not been verified on any machine either;
the researcher already carries the same exposure.

**Run the daily task from your profile folder.** The scheduled task should launch in the same folder you
open the coordinator in, your profile directory. A scheduled run sees exactly what its launch folder sees:
the same project settings, plugin enablement and allowed commands. The coordinator reports a daily
run that was launched from anywhere else, from the run check it already makes.

---

## The rules it holds itself to

**It never sends.** Not email, not LinkedIn messages, not applications. Drafts are staged for
you. This is structural, not a setting. With a claude.ai mail connector selected, a guard also
refuses that connector's send, reply and forward tools; the script is tested, and whether the app
routes every call through it is not yet verified. Reporting a problem by `report_issue.py --email`
prints an email for you to send yourself; the plugin sends nothing.

**It never handles a credential.** Your passwords and app passwords live in your operating
system's keychain, placed by you. The engine asks the keychain for what it needs.

**It never invents a fact about you.** If a job description asks for something your resume does
not evidence, the honest answer is recorded as a gap and you get asked a targeted question. An
alignment claim without a citation is treated as a gap wearing a disguise.

**It prefers a query to a summary.** Your dashboard and reports are computed from your data
every time they are shown. Nothing is a stored summary that was true when written and wrong
when read.

**It shows each thing once.** The dashboard is one page at one link, and every role, draft,
channel or person is shown in full in exactly one list. Anywhere else it matters, you get a
one-line reference that links back to that row, so two copies can never disagree. Because the
page is generated from your data, a correction to a draft is made in the data — in a session, with a
before-and-after and your yes — never by editing the page. Each draft's **Copy as prompt** button
copies a ready-made request naming that draft, so you only add what should change and paste it in
your session.

**When it does not know, it says `unknown`.** A deliberate `unknown` is countable — a report can
tell you "12 unclassified". A guess folded quietly into a bucket cannot.

---

## Cost

Roughly `runs per day × agents per run`. The deterministic half — sweeps, calendar checks,
silence detection, the dashboard — is free at every tier and carries most of the daily value.

| posture | runs/day | agents/run | LinkedIn passes/day | career pages searched | job boards searched | what you get |
|---|---|---|---|---|---|---|
| `minimal` | 1 | 0 | 0 | never | never | mail and free feeds; you search by hand |
| `economy` | 2 | 1 | 1 | Mon | Tue | + LinkedIn — **the default** |
| `standard` | 3 | 2 | 1 | Mon, Wed | Tue, Thu | + more sweep days |
| `full` | 5 | 5 | 2 | Mon, Wed, Fri | Tue, Thu, Sat | + drafting |

**Research is not in this table because no posture gates it.** Every posture, `minimal` included, researches
each role it finds that passes your screen, in the run that found it.

Set `search.posture` in your configuration, or define your own tier. A profile that existed before 0.78.0
moves to these days when it upgrades.

**Career pages can be shared out across their days.** On a tier with more than one career-page day, you can
turn on `company_split` (`/jobsearch:tier` shows how). Each career page is then checked on one of the days,
always the same one, instead of all of them on every day, so each run is shorter and each page is still checked
once a week. It is off unless you turn it on. When you look at what is due (`channels_due.py`), a page whose day
has not come is listed under **WAITING FOR ITS SWEEP DAY**, with the date it opens, and only what the next
sweep will really pick up is listed under *DUE NOW*. A job board you want checked every day needs its `board_days`
set to all seven days; no tier ships that way.

**What a posture limits, and what it does not.** A posture controls **how often** an unattended run searches
employer career pages and job boards (the two day columns), how many agents a run may start, and whether it
drafts. Mail, company job feeds and LinkedIn run as before. A posture never controls **what happens to a role
once the search has found it.** Under every posture, including `minimal` and `economy`:

- every role a run sees is accounted for, one by one. It is captured, already known, carried
  forward as its own queued item, or recorded as a named gap. A run never ends on "12 roles
  seen, top few captured";
- every role that is not removed gets its **job description read**, and every captured role gets a
  **minimal screen**, done by a script with no agent and no tokens:
  your comp floor (annual floors for employment, your non-employee floors for fractional, interim, advisory and contract roles; a role whose pay you accepted is kept), whether you already passed on or applied to it, geography, and whether the
  title matches one of yours. The title check only marks a role for your review; it never
  removes one. A mandate rule is not scripted, and the screen says so on each role instead of
  staying quiet;
- **every role that passes the screen (`VERDICT keep`) is researched in that same run**, and a run finishes
  every role it takes on (up to `search.intake_per_run`, 40 unless you changed it). Roles not yet taken on
  are counted as waiting, never dropped. A borderline role (`review`) is not researched until you have
  looked at it.

Only **drafting** is held by a posture. A draft your posture refuses is **queued, not dropped**: it shows as
a held item (*held by posture*) and the next run whose posture permits it picks it up, with nothing for you
to re-request.

**`minimal` is the hands-on level.** It searches nothing on its own, so you run the searches:
`/jobsearch:search attended` (career pages and boards), `/jobsearch:search companies attended` or
`/jobsearch:search boards attended`. The same command without `attended` only previews what is due. An
on-demand search works on every posture, ignores the sweep days (and the career-page split), researches the roles
it keeps in the same session, and does not use up the scheduled sweep: a Monday on-demand board search leaves
Tuesday's scheduled one due.

**A run counts as unattended unless you say otherwise.** A scheduled run, or a session where you
just type `/jobsearch:daily-run`, follows the posture. To draft by hand on a tier that
would hold it, or to sweep outside the posture's days, start the run in its attended form:
`/jobsearch:daily-run attended`. The engine never guesses that you are at the keyboard. Attended lifts the
drafting limit and the sweep days only. It never lets a run touch LinkedIn, which stays governed by the
posture's LinkedIn quota and by whether a signed-in browser is available.

**LinkedIn passes are capped independently of runs/day.** A run above its posture's LinkedIn
quota still does everything else its posture permits, and still accounts for and screens every
role it finds. It just skips the LinkedIn pass for the rest of that day. `economy` and
`standard` get one LinkedIn pass a day even though they run 2 or 3 times; `full` gets two even
though it runs 5 times. Set `search.postures.<tier>.linkedin_runs_per_day` to change it for
your own tier.

**When a sweep cannot read everything, it says so (since 0.82.0).** A board sweep that hits a bot check
(a "prove you are human" page) or a channel it cannot read records that channel as **unreachable**, with a
reason. It never tries to get past the check: it does not click it, solve it, wait it out or reload it. It
carries on with the rest. Every channel it was given is accounted for: each one is either read, recorded as
unreachable, or recorded as not attempted, and a channel the sweep never mentioned is reported as unaccounted.
The run summary then marks the sweep **PARTIAL** and names what it missed (for example "3 of 5 channels
reached", then which channels were unreachable and why), instead of reporting a quiet zero.

- **LinkedIn: one unreadable line costs only that line.** If the LinkedIn helper's record has a line the
  engine cannot read, every other line is kept and recorded, and the run names the line it dropped. A
  person the dropped line could have been about is never reported as "nothing changed" on its account.
- **LinkedIn: a refused record keeps the hand-back.** If the whole record is refused (a broken hand-back),
  the raw hand-back is kept on your machine (see *Your data*, under `handbacks/`). The first refusal each day
  does not use up that day's LinkedIn pass, so the pass can run again. A second refusal the same day counts.
- **When the only way to reach a board on this machine is one the board sweeper cannot use, the board slot
  is not spent.** The board sweeper holds the plugin's own tools and the built-in browser. It does not hold
  the Claude in Chrome extension. If a due board can be reached only through the extension, the daily run
  does not start a sweep it cannot finish: it says there is no route the board sweeper can use on this
  machine, and the board slot stays open for a later run.

**Once a week, that day's LinkedIn pass looks further back.** The daily pass uses LinkedIn's
own "Past 24 hours" filter. One pass a week uses "Past week" instead, so a role missed on its
first day is seen a second time. It is not an extra pass: it is that day's pass, inside the
same daily quota, so it adds no cost, and on a tier whose quota is `0` it does not run. The run
summary then says the wide look is due and was not run, and why. Roles it re-surfaces go through
the same accounting as any other, and roles you already know about are not created twice.

---

## What needs a desktop

The search runs **on your own machine**. Supported places to run it:

- the **Claude Code tab of the Desktop app**, in your profile directory;
- a **scheduled task in the Desktop app**, which is how the daily and weekly background runs happen;
- the **`claude` command-line interface in a terminal**, which includes Linux;
- a **phone or another browser driving one of those through Remote Control**, as a remote: the
  session still runs on your machine.

**Not supported:** `claude -p` (headless) and the Agent SDK, and Claude Code on the web or any cloud
session. This is a statement of what the plugin is built and tested for, not a block: nothing stops
you starting it there and nothing will warn you, but a cloud session also does not install the
plugins your repository declares. Whether the `/jobsearch:status` command works when typed from a
phone over Remote Control has **not been verified**, so do not rely on it.

LinkedIn is the part that needs more than a machine. It has no API, so reaching it needs a real,
signed-in browser on a desktop (macOS); it cannot run from a phone on its own or from the cloud, and
it is roughly half of the outreach funnel. The mailbox, screening, reports and drafting need only
one of the supported places above.

### LinkedIn needs the browser pane in view (since 0.83.0)

LinkedIn is read in the desktop app's built-in browser pane. A pane you are not looking at does not draw
anything on screen, so a click in it cannot be checked. Since 0.83.0 the search asks the app whether the pane
is shown, once at the start of each LinkedIn pass, and works accordingly:

- **Pane shown (you are watching, or the session is in view).** The full pass runs: it reads your lists and
  does the work that needs clicks. If the pane stops drawing while it is shown, the pass says so and stops
  clicking, as before.
- **Pane hidden, or a scheduled run.** Nobody is looking at a scheduled run's pane, so it counts as hidden.
  The pass reads LinkedIn by text only: it opens each list's address and reads the words on the page, and it
  clicks nothing and types nothing. Work that needs a click is not done, and the pass does not call a hidden
  pane a broken one. A list read this way is still read, and it still counts as that day's LinkedIn pass.
  The pass is not run again later on its own, because on a schedule nobody would be there to show the pane.
- **Pane state unreadable.** If the app's answer cannot be understood (for example after an app update changes
  its wording), the pass carries on as it did before 0.83.0 and says so loudly. In that case a hidden pane can
  still be mistaken for a broken one.

The hidden and unreadable cases each leave a **gap** open. A text-only list is reported as partial rather than
as a complete read. The gap tells you what to do:

- **Hidden pane:** click-dependent LinkedIn work runs only while the Browser pane is shown. Run
  `/jobsearch:linkedin` in the desktop app and keep it in view. The gap closes when a pass runs that way.
  If your LinkedIn pass runs in Chrome instead of the pane, the same rule applies to the Chrome window: have
  it open and in view.
- **Pane state unreadable:** nothing for you to fix on your own. The gap stays open until a pass can read the
  pane again. If it never closes, report it (see **[reporting-issues.md](../reporting-issues.md)**): the app's
  wording has probably changed.

One limit is not covered. The app says whether the session is in view, not whether the pane is actually
drawing. A pane that reads as shown while the window is covered, on another desktop, on a sleeping display or
behind a locked screen can still be mistaken for a broken one, as before 0.83.0.

---

## When something looks wrong

Ask for a checkup first — it verifies the installation, the profile pointer, and your data's
referential integrity, and it tells you which of the three is at fault.

The most common cause of "it says I have no opportunities" is a profile pointer aimed at the
wrong directory. The second is a session started before an update finished. Both are reported
explicitly rather than shown as an empty result.

You may also see an agent refuse outright with a message like *"NOT BOUND — REFUSED
(pointer-only)."* That is deliberate, not a bug. This plugin installs once for your whole
machine, so its agents are technically reachable from any Claude Code session, in any project —
and this refusal is what stops one from reading or writing your search by accident when it is
dispatched from somewhere that is not your job search. It means: this session shows no evidence
it belongs to your profile — you are not running from your profile directory, and you have not
told the session which profile to use. Run the command again from your profile directory, or
from a session that is already part of your job search, and it will proceed normally.

To report a genuine defect, see **[reporting-issues.md](../reporting-issues.md)**.
