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

3. **Work the network (since 0.86.0).** Before it touches a job board, every run works your
   relationships, whatever your search plan says it is for: replies you owe, follow-ups that have come
   due, chats to prepare for, and up to a weekly budget of new reach-outs, each *drafted* for you to
   send. See *Your network comes first*, below. This step sends nothing.

4. **Reconcile.** New findings are matched against roles you already track. A role seen twice on
   two job boards is *one* opportunity with two sightings, not two opportunities. Ambiguous
   matches are surfaced for you to confirm rather than merged automatically, because one job
   title can genuinely be several different roles.

5. **Read and screen.** Each role the run takes on at a company you target has its job description read, and only then is it
   screened (see *One lifecycle per role*, below). Roles are checked against the floors you set — compensation, geography, work
   setting. A role whose office is far beyond every place you said you would commute from, and is
   not somewhere you would move to, is removed as too far (see *Where a role is, and when it is
   too far* in [Your data](your-data.md#where-a-role-is-and-when-it-is-too-far--since-070)). Something below your floor does not silently vanish; it is marked, and you can see
   why. A role you accept at that pay (`decide <id> pursue --why-kind comp-acceptable`) shows as
   accepted and is never removed; reversing the decision brings the removal back. Fractional,
   interim, advisory and contract roles are measured against your separate non-employee pay floors
   when you have set them, never the annual ones; without them they are marked for your review,
   not removed. A pay quoted by the hour or day is never removed against an annual floor.

6. **Surface.** What needs a human decision is collected: replies waiting, applications with no
   acknowledgement, conversations that have gone quiet, questions the assistant needs answered
   to pitch you accurately.

7. **Draft — only if you asked.** Outreach and cover letters are written citing sentences from
   your own resume rather than paraphrasing them. A draft is *staged*. You read it, you edit it,
   you send it.

---

## One lifecycle per role (since 0.82.0)

Every role at a company you target goes through one sequence, and a run does not stop halfway through it. (A role
at a company you have not chosen to target is worked when it meets your criteria, and **held** when it does not: see *A role that
meets your criteria is shown, whatever its company*, below.)

1. **Capture.** A role a sweep found is recorded, or matched to a role you already have. What a search
   result card showed (pay, work setting, location) is kept, but marked as *provisional*, because a card
   is often wrong or thin.
2. **Read.** The job description is read for **every** role that has not been removed. A script tries a
   plain fetch first for a remote posting that states its pay; anything else, or anything the fetch could
   not read, goes to a reader agent working in a browser tab of its own. A posting only you can open comes to you
   as **your read**, and a posting that is down ends there as *gone*. Since 0.87.0 that includes a page that renders but says the role is closed, filled or no longer accepting applications: the reader records it as closed with the status words quoted, not as a read. The description's own pay and work
   setting replace the card's.
3. **Screen.** Your floors and rules are applied to the facts from the description. A screen that rests
   only on card facts can never say *keep*.
4. **Research.** Only a role the screen **keeps** is researched. A role marked for your review, or one the
   screen removed, is not. Research includes the fit analysis against the posting's requirements; since 0.87.0 it is
   stored when the role is researched (not later, when you pursue it), and the role is not *ready* without it.

A role is ready for your decision when it has been through all four. If you change a pay floor, your
title floor, your target titles or a likely-pass phrase, roles screened under the old rules go back to
*waiting* and a later run re-screens them.

**A run takes on a limited number of target companies and finishes every role of each.** Since 0.86.0 the
limit counts **companies**, not roles: `search.company_intake_per_run` (10 unless you changed it; a number above
what the run has time for is trimmed, and the run says so). A run takes on every waiting role of each company it
admits, together. While older unread roles are still waiting, part of the places is kept for roles found since.
Roles found but not yet taken on are *waiting*, counted and aged. **Anything a run took on and did not finish is a
process failure**, shown with its cause and how long it has been there: on the dashboard, in Your Move,
in the coordinator's start line and in the run's headline. Nothing is hidden, and an old unread role at a company
you target stays a failure until it is read. (Before 0.86.0 the limit was `search.intake_per_run`, counted in roles.
The upgrade leaves that setting in your file untouched, because a machine still on an older version reads it, and
this version no longer does.) Reading the files that show this is in
[Reading what the search produces](reading-your-files.md#one-lifecycle-per-role-since-0820).

## A board find asks about the company first (since 0.86.0)

> **Since 0.94.0 this applies only to a role that does not meet your criteria, and to a company you passed on.** A role that meets your own criteria is
> read and put to you whatever its company: see the next section. What follows is how a held role and the company question work.

A role a job board shows you at a company you have not chosen to target is **kept, and not worked**. The run
records the role (so you can see it was found), and then stops: it does not read the posting, screen it or research
it. Such a role has its own state, **held for company**. It is not a failure and it is counted, so every role is
still accounted for, and the line that counts them says how many are held and why (company not decided yet, watched,
or passed).

What the run does instead is ask about the **company**: *look into this company?* At most
`search.companies_raised_per_run` companies a run are raised this way, newly (since 0.93.0; unset, the same number as `search.company_intake_per_run`, 10 unless you changed it), and the rest are
counted as *waiting*, never dropped. Your answer is one command, and it is your decision, never the run's:

- `record.py company-status <company> active-target --motivation <1-5>`: target it. From the next run its roles are read,
  screened and researched like any other target's. Your motivation, 1 to 5, is your own word for how much you want to
  work there. Since 0.94.0 it is optional: leave `--motivation` off and the company is a target with no rating, shown as `?`.
- `record.py company-status <company> watching`: keep watching, and stop asking.
- `record.py company-status <company> passed`: not for you.

A later sighting at a company you answered does not raise it again. Your older held roles are not lost by the upgrade:
the first runs after it raise the first companies, and the rest follow on later runs.

**What a run looked at and what it did not.** A run that could not look at everything says so in its
headline as `DID NOT LOOK`, with a count and an age: company feeds it ran out of time for, searches it
could not reach, mail it could not read.

## A role that meets your criteria is shown, whatever its company (since 0.94.0)

Before 0.94.0 a role at a company you had not chosen waited until you answered a question about the company, even when the role was exactly what you asked for. Now **your own
criteria decide what is read and put to you**. Your company answers still matter, but for other things: who is written to, and how often a company's own page is checked.

**The first look.** Before a role is read, the run looks at its card and asks three questions with your own rules:

- **Title.** Does it match one of your target titles, and clear your seniority floor?
- **Pay.** If the listing states a range, is the top of it under your pay floor? Pay that is not stated, not captured or not comparable never counts against a role.
- **Place.** If the listing states a work setting, does it fit where you will work (remote, or within your commute)? A place that is not stated, or is only an echo of your own home
  address, never counts against a role.

A role that passes is **read, screened and researched like any other**, and if it keeps it comes to you to pursue or pass. A role that fails stays held and says which question held it.
A role at a company you **passed on** stays held whatever its title, and is counted as that. If the run cannot read your criteria (for example no target titles are set), the role stays
held and the line says `criteria not checked`: a criterion it could not read never counts as a pass. The look is worked out each time against today's settings, so changing a floor or a title
takes effect at once.

**How many, and in what order.** A run reads matching roles **newest first**, because a posting loses value with age: up to `search.matching_roles_per_run` (20 unless you changed it), and
never more than half of what the run has time for while a company you chose is waiting. It also **stops reading new matching roles while `search.open_decisions_max` (25 unless you changed it)
are open for your decision or being read**, and the plan, the start line and the summary say so. If you leave the list alone, new matching roles wait, and the page says so. If your scheduled
runs cannot read a LinkedIn page, up to 25 such roles wait for one attended read; roles a script can read carry on. Roles first seen before the upgrade are never counted as failures
for it.

**Each role says why it is on your page.** One short line, from facts the role already holds: the title and what it matched, the pay and its basis (stated by the employer, a board's
estimate, or yours), the setting, how long ago it was posted, and whether the employer's own posting was checked. What was not read is said as not read: `pay not stated`, `setting not stated`,
`posted date not shown`, `employer posting: not checked`. Nothing is guessed to fill a gap.

**Pursuing a role targets its company.** `record.py decide <role> pursue` now also makes the role's company a target, in the same step, with no 1-to-5 rating asked first. It leaves the
company alone, and says why, when you passed on it, when it is a staffing firm or a job board (the employer is not known), or when you stated a motivation for it earlier. Add `--no-target`
to pursue only the role. A target made this way starts outreach suggestions (each still needs your approval) and regular checks, and reads its other roles **only when they meet your criteria**.
A later pass on that role does not untarget the company; the line printed says how (`record.py company-status <company> watching`).

**A read now has to quote the description.** A role read in the browser is recorded only with a short quote (60 to 200 characters) from the description itself, not from the title or the
header. A posting whose description never filled used to pass as read on its title alone. A read that is wrong can be **withdrawn** (`record.py read-withdraw`): the run puts back the pay and
place the read replaced, runs the screen again, sets aside a research made on the wrong read, and keeps the whole history. A read the same run's later failed attempt contradicts is
withdrawn automatically. A role you have already decided stays decided. "Not currently accepting applications" now counts as a closed posting, alongside "No longer accepting applications"
(English only: a posting in another language is never closed by the script).

**A sweep that came back cut short no longer holds roles it showed.** A card that states its own setting or place is trusted when a search dropped that filter, and a cut-short result or a pay
filter LinkedIn added is counted as missing coverage instead of holding the roles that were shown (see *A sweep that was held* in [Reading your files](reading-your-files.md)).

**What the upgrade does.** The 0.94.0 upgrade marks your profile (older versions then stop and tell you to update), keeps a copy of the two files it may change (`opportunities.jsonl.pre-0.94.0`
and `pending_actions.jsonl.pre-0.94.0`; a copy already there is used only if it holds every row about to change exactly, otherwise a new one is written as `.pre-0.94.0.1` and on, and the message
names the copy that holds the originals), withdraws up to 50 reads a session that the same run's later failed attempt contradicts, and releases captured roles that were held only for a reason
their own card answers. Roles held for their company need nothing done: held is worked out each time, so the mark is what releases the ones that meet your criteria, and the first run's plan
says how many wait. A profile the upgrade has not reached behaves as 0.93.0 did.

## The LinkedIn job search (since 0.94.0)

The LinkedIn job search is its own step, no longer part of the pass that reads your replies and messages. It searches by each of your target titles and each place you work (remote, and your
commute area if you set one), reads the first page of results of each search (about 25 roles), and records what it finds. **It only reads.** It never clicks, scrolls, types, signs in or answers
anything on LinkedIn.

- **Who runs it.** You, with `/jobsearch:search linkedin attended` in the desktop app; or a scheduled run, when it is due and the run's tier uses LinkedIn. **Due means 48 hours have passed** (the
  setting `search.linkedin_search_every_days`, 2 unless you changed it, counted in hours) since the later of the last time a search was started, whether or not it finished or crashed, and the last one
  that reached LinkedIn. The clock is the time elapsed, never the calendar day. At most `search.linkedin_queries_per_pass` (20) searches a time, and only the searches the plan lists. With 14 titles and
  2 places every search repeats within a week; with many more, some wait longer than LinkedIn's one-week window and can miss roles, and the summary counts them.
- **Limits, in the script.** One page for each search, never a second. At most 20 searches a pass. Each page is judged once; the plugin takes at most 25 job links from a search and 500 in a pass, and
  counts them before it prints them. No scheduled LinkedIn search runs while the 0.94.0 update step has not yet run on your profile (it runs at your next session start); the reply pass says so.
- **What the summary says.** A run that did not search says `linkedin job search: NOT RUN (...)`, with the reason (not due yet, no browser, skipped, off, stopped, a LinkedIn warning) and the last
  date. It is never reported as zero roles found. A run that searched says how many of its planned searches it read.
- **Asking you.** The start line asks for the attended step only when scheduled searching cannot do it: the newest search failed, scheduled searching is stopped or off, or nothing has searched for
  twice the interval. To skip it for a while (at most 30 days): `journal.py --linkedin-search-skip --until <date>`.
- **Any LinkedIn warning stops it, and you turn it back on.** Every LinkedIn page the plugin opens (a search page, a posting, a reply page) is judged by a script before anything is taken from it, and
  only a page it can positively recognise as an ordinary page is ordinary. A warning, a sign-in or identity check, a CAPTCHA, an unusual-activity notice or a usage-limit page, **or any page it is in
  doubt about, counts as a warning** (a browser tool that errors, times out or returns nothing counts too). A warning recorded by any run ends every run already in flight at its next LinkedIn
  step: it opens no further LinkedIn page and takes nothing more from LinkedIn that run, and the roles not reached are held for the next run. The scheduled search then stays **off** until you have
  looked at LinkedIn yourself and run the command the first line of every summary shows (`journal.py --linkedin-search-on --attended --warning <date>`). Nothing else turns it back on: not a later good
  search, not time, not an update. A command stamped before the warning it names is refused.
- **What may turn it off, though nothing is wrong.** Because doubt counts as a warning: a search with no results (no job to show), a LinkedIn layout change, an account or page in another language than
  English, a pop-up, toast or notice on an otherwise ordinary page, a banner of several words, and a job description that itself uses a warning's words (for example a posting about identity
  verification). **The reason is shown in words** with the warning, and where it may be a layout change or an empty search the line says so ("This may be a LinkedIn layout change or a search with no
  results rather than a warning; it is treated as a warning"), so you can look and turn it back on. How often this happens on a real page has not been measured.
- **What the plugin does not check.** It refuses what it is shown; it cannot make the runner show it every page it opens. Two calls at the very same instant are not locked against each other.
  A warning drawn over a page full of ordinary results, in the main area, a header or a side panel, with no wording the plugin knows and no pop-up or notice, would be missed; so would a page with no
  language attribute, an image-only message, and a warning on a reply page that rests on weak evidence. An attended reply pass on a profile the update has not reached loses its LinkedIn search for the
  same reason as a scheduled one.
- **What has not been tested.** Several searches in one run have not been run on LinkedIn, and it is not known whether any address keeps LinkedIn's remote and place filters: in every load measured
  LinkedIn dropped them, so the 25 results read may be the first 25 of a wider search (counted as cut short, never as zero found). **The first five scheduled searches show their counts at your
  next start**: planned, read, cards, job ids, recorded, held, cut short, filters dropped and what stopped it.
- **LinkedIn's rules.** LinkedIn's terms bar software that scrapes or automates activity on the site. This search reads pages you are already signed in to, and the two small scripts it runs
  to check a page and to read job links send nothing and open nothing, but they are not claimed to be permitted. See [What it will not do](#what-it-will-not-do).

## Your network comes first (since 0.86.0)

The plugin treats a search as mostly people and conversations, with job boards feeding the list of companies you
are interested in. So every run works your network **before** it drains a board, on every profile, whatever your
search plan is for. In order, the run:

1. **Drafts the replies you owe**, from the mail and LinkedIn it just read.
2. **Drafts the follow-ups that have come due.** The timing is the "3B7" method: after you write to someone and hear
   nothing, a second person at their company is due on the third **business** day and a short follow-up to the first
   person on the seventh. The marks are `network.followup_business_days` (3 and 7 unless you changed them) and the
   days that count are `network.workdays` (Monday to Friday unless you changed them; holidays are not modelled). A
   reply from the person cancels what was owed.
3. **Prepares you for chats** that are coming up (`call-prep`).
4. **Drafts new reach-outs, up to a weekly budget.** `network.new_reachouts_per_week` (5 unless you changed it,
   counted over the Monday-to-Sunday week) is how many new people the run may draft a first message to. A draft you
   have not yet sent or deleted counts against it, however old, so the budget cannot grow behind your back; set it to
   0 to turn new reach-outs off. A reach-out is a short email, at most `network.reachout_max_words` words (75 unless you
   changed it) that mentions how you found the person, asks for their view and never for a job, and ends in one question
   with a small next step, such as a short call.

**Everything that sends, connects or looks up a person stays with you.** A run drafts messages for you to read and
send. It never sends a connection request and never searches LinkedIn for a person; where it needs someone found, it
lists a link for you to open. It never sends a message: under `actions.modes.email-send: me` (since 0.93.0), an email you
approve is put into your drafts, and you press Send ([Your data](your-data.md), *Outbox*). It also never
writes down that a chat happened: that is your word.

**Only current employees count at a company (since 0.91.0).** Someone who has left is still in your network, but is no
longer a way into their old employer. Someone whose employment you have not confirmed still counts in a target's known
and contacted columns, flagged as unconfirmed, but is never treated as a way in until you confirm it (since 0.93.0).
At a target where you have no way in, the reach-out plan offers a **BUILD** step instead of a bare lookup: an advice
ask to someone who used to work there, a lookup angled by your school or past employer, a side-door ask to someone
already involved, and others, inside the same weekly budget. The weekly review counts what you did that week, and quotes
a reply rate only over the last 12 weeks once there are at least 5 answered asks.

### Chats, and what a held chat is worth

A request for a chat is a message like any other. When the person agrees, you record the booking on that message
(its outcome becomes `meeting-booked`). The chat itself is a calendar commitment with a person:

- `record.py chat <person> --on <date>` records a chat with someone (with `--touch` to say which booking it came from);
- `record.py attended <chat> held` (or `no-show`) is how you say it happened, and `--notes <file>` points at your notes;
- `record.py intro-offered <chat> --person <id>` records an introduction someone offered you in it.

A chat you have not recorded is reported as **unrecorded**, never as zero held, and a count that includes it says
"at least". A held chat makes the person *warm* in your reach table for a while (`access.warm_days`, 180 days unless
you changed it).

### Targets, and what the plugin works out about them

`active-target` is simply your list of companies. You can state how much you want each one (`motivation`, 1 to 5, optional since 0.94.0) and, for
each person, how you know them (`people.ties`: former colleague, alumni, community, friend, introduced, other). From
those and from what is recorded, the weekly review's reach table works out for each target how many people you know there, how many are
alumni, how many roles are live and when you last made contact. None of it is stored: change a tie and the table
changes. A target with no stated motivation is counted, not guessed.

### Suggestions, and the weekly review

The weekly review opens with a network section, and the strategist may suggest a company to target, a plan, or a
cadence for a person. A suggestion is a question waiting for you in Your Move, with the change it would make written
out. **Nothing changes until you confirm it** (`record.py confirm <id>`), and `record.py decline <id>` closes it. The
plugin also writes `views/network_strategy.md`, a generated page of your targets, the people at them, the budget and
the open suggestions, rebuilt from your records; edit the records, never that page. Your own notes in
`outreach/network.md` are never touched.

### Proposals for contract and fractional work

For a fractional, interim, advisory or contract engagement the path is a **proposal**, not an application. Each one
records the agreement reached in conversation first (what the work is for, how it will be measured, what it is
worth), then the scope and rate, and a status from drafting to accepted or declined. There can be several for one
engagement. See `record.py proposal` in [Your data](your-data.md).

### On the dashboard

Since 0.89.0 the dashboard opens with **Today**, at most five things that need you now, each linking to its row; a
reply someone is waiting for comes first. When nothing needs you, Today is one sentence. The network is a **Network**
list below Drafts, with its own entry in the jump bar, holding only what you act on, in groups: *They wrote back*, *To
record*, *Applied, no one contacted yet*, *Awaiting a reply* (split into they accepted, went quiet recently, quiet for
a long time, and not checked yet), *Introductions* and *Relationships due this week*. Every list shows its first few
rows, folds the next 20 into one line each, and counts the rest. Since 0.92.0 each Network row says what it is about and
why it is listed, a reply owed for more than `network.reply_owed_days` days (60 by default) or about an ended role is named
under *Not listed* instead, and a person you asked to stop following (`record.py stop-following`) stays off both groups until
they write again. Held roles have their own section, *Held roles* (called *Roles waiting on a company decision* before 0.94.0), with the
held count, why they are held and its change since last week. Every button copies text to paste into your jobsearch session; nothing is recorded
by the click. See *The page since 0.92.0* in [Reading your files](reading-your-files.md). The numbers (reach-outs
against the budget, chats booked and held, introductions) live in the weekly review and in
`views/network_strategy.md`. A run that found no roles but worked your network is not a quiet run, and a profile with
no applications is not a stalled one.

### If you use more than one machine

The upgrade marks your profile as belonging to 0.86.0 or later. A machine still running an older version stops at its
first read of the run history with a message naming the upgrade, and writes only a short, fixed set of housekeeping
lines (a session-start record, a run-start record, a status line and diagnostics). It does not rewrite your
`CLAUDE.md`: this version stamps that file with a new marker which an older version reads as "not installed by this
plugin" and leaves alone. Update the plugin on that machine and it carries on.

Since 0.88.0 the upgrade writes a second mark, and a machine on 0.87.0 or older refuses the profile: it says "Update the plugin on this
machine before running it here" and writes nothing. Update it and it carries on.

Since 0.92.0 the upgrade writes a third mark, and a machine on 0.91.x refuses every `record.py` command and every read of the
run history with the same message. It can still regenerate its own dashboard, missing what it cannot read and naming the same
remedy, and publish it over the newer one; it also still adds to the inbox. So update the plugin on every machine you use.

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
data in your profile, or sends something you have not seen. The plugin never sends anything you have not seen and
approved, one message at a time.

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
  closed. Since 0.87.0 a role marked closed this way is *gone* and leaves the list of roles awaiting your decision
  (a role you have already decided on keeps its place), and a later read that finds the posting open brings it back.
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

**It never sends on its own.** Not email, not LinkedIn messages, not applications. Drafts are
staged for you. LinkedIn messages and applications are never sent by the plugin, whatever you set.
With `actions.modes.email-send: me` (since 0.93.0), a message you were shown in full and approved,
in a session you are attending, goes straight into your drafts; you press Send. A scheduled run puts
an already-approved message into your drafts too, and never approves one for you ([Your
data](your-data.md), *Outbox* and *Action modes*). With a claude.ai mail connector selected, a guard also
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
before-and-after and your yes — never by editing the page. Since 0.89.0 each row you can act on has a
tick box and each list one button: it copies one request naming the rows you ticked, and you paste
it in your session, where the coordinator records each one and asks you what it needs.

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
- **every role at a company you target that passes the screen (`VERDICT keep`) is researched in that same run**,
  and a run finishes every role of the companies it takes on (up to `search.company_intake_per_run` companies, 10
  unless you changed it). A role at a company you have not targeted that meets your criteria is read whatever its company (since 0.94.0, up to
  `search.matching_roles_per_run` a run, 20 unless you changed it); one that does not, or at a company you passed on, is held.
  Roles not yet taken on are counted as waiting, never dropped. A borderline role (`review`) is not researched until you have
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

**The board sweep runs in batches (since 0.84.0).** A script, not the model, cuts the list of boards due into batches
sized to the number of job titles you search, and each batch goes to its own sweep agent, one after another. The run
stops handing out batches when its batch cap or its time budget is reached, and the channels never handed out are
recorded as not attempted with the reason `run-budget`; a channel the router refused is recorded `route-refused`;
channels still unfinished when the run ends are recorded `run-ended`. None of these is the catch-all `other` any more.
The run summary shows a `BOARD BATCHES` line (for example `BOARD BATCHES 2 of 14 (stopped: browser-unavailable, 41
remaining)`). A LinkedIn source belongs to the LinkedIn helper, not to the board sweep: the run summary prints an
`OWNED BY linkedin-runner` line naming the channels left out of the board list for that reason. A source you added by
hand is matched to the LinkedIn helper by its name when it has no catalog link, and the line says that is how it matched.
A company job-board feed that is read but slow now counts as that board's own result; it no longer takes the whole
vendor down, and feeds are tried in order of the last time they were *attempted*, so the same few do not head the list
every day.

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

**The LinkedIn job search looks back a week, not a day (since 0.94.0).** Before 0.94.0 one LinkedIn pass a week used "Past week" and the
others "Past 24 hours". That separate wide look is gone: the job search is its own step (see *The LinkedIn job search*, below) and uses "Past week"
unless every search it will run was already read in the last 24 hours. Roles it re-surfaces go through the same accounting as any other, and roles
you already know about are not created twice.

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

### LinkedIn and the browser pane (since 0.83.0, changed in 0.94.0)

**Since 0.94.0 the question "is the pane in view?" no longer decides what a pass does.** The app still says whether a window shows the session, and the pass writes that
down, but it measured wrong as a test of whether a page draws: a pane nobody was looking at still drew a fresh tab, and a signed-in LinkedIn page filled with no
drawing at all. So each page now opens in its own new tab, set to a large fixed size, read, and closed. A LinkedIn results page or posting is accepted when its content is
complete on two reads in a row, whatever the app says about drawing. Any other page keeps the drawing test, and the pass reads by text only (no clicks) when a page still
does not draw after a second look. The text below describes the rules up to 0.93.0, which a profile the 0.94.0 upgrade has not reached keeps. What the app does with a pane
nobody is looking at is not documented by the vendor, and a scheduled session has been measured twice, not more: a locked screen, a sleeping display or a minimised app window
were not tested.

**What this means for the "hidden pane" notice.** From 0.94.0 only a reply pass that left a list unread counts towards it, three times in a row; a pass that read every list
does not, even when run on a schedule. A LinkedIn search counts only when three in a row ran with the pane hidden. A pass you run with the pane shown clears the notice, and it
comes back after three more.

Up to 0.93.0, LinkedIn needed the browser pane in view:

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
