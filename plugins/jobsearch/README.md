# jobsearch

A job-search assistant that runs as a set of Claude Code skills, agents, and scripts. It sources
roles, screens them against *your* stated criteria, tracks every application and conversation, and
drafts outreach in your voice — while never sending anything without you.

**This repository is the ENGINE only.** Your resume, your contacts, your compensation floors and
your search history live in a separate private repository that you own. Nothing personal is here,
and a CI gate enforces that.

## What it actually does for you

- **Sweeps your mailbox and LinkedIn** for recruiter replies, interview invitations and application
  receipts, and tells you what needs a decision.
- **Screens roles against your comp floors and geography** before they reach you, so the pipeline
  holds things you would actually take.
- **Drafts** outreach and cover letters that cite your own resume sentences rather than paraphrasing
  them, and refuses to invent facts to fill a gap.
- **Remembers** every touch, so you never send someone a cold introduction they already answered.

## Requirements, stated honestly up front

| | |
|---|---|
| **Claude Code** | any subscription tier — see *Budget* below |
| **A desktop (macOS)** | **required for LinkedIn.** LinkedIn has no API; it needs a real signed-in browser. This is the one thing that cannot run from a phone or the cloud, and it is roughly half the outreach funnel |
| **Your own machine** | see *Where this runs*, below |
| **An email account** | IMAP with an app password, stored in your own OS keychain |
| **Python 3.9+** | standard library only, no packages to install |

**The engine never handles a credential.** You place them; it uses what your OS already holds.

## Where this runs

jobsearch runs **on your own machine**, in the Claude Code Desktop app or in the `claude` command-line
interface in a terminal (Linux is fine through the command line). A background run is a scheduled task in
the Desktop app. A phone can drive a session on your machine through Remote Control, as a remote.

**Not supported:** `claude -p` and the Agent SDK, and Claude Code on the web or any cloud session. Nothing
stops you starting the plugin there, and nothing will warn you; it is simply not a place the engine is
built or tested for, and a cloud session does not install the plugins your repository declares in the
first place. The status pane, the review panes and the Run buttons need the Desktop app or the terminal;
the Run buttons are drawn only in the Desktop app. **Not yet verified:** whether the `/jobsearch:status`
command works when typed from a phone, and whether a scheduled run can message a live session (the engine
does not depend on either).

## Budget — pick a tier that matches your subscription

Cost is essentially `runs per day × agents per run`. Deterministic work (mailbox sweeps, calendar
checks, silence detection, the dashboard) is free at every tier and carries most of the daily value.

| posture | runs/day | agents/run | unattended | career pages (`company_days`) | job boards (`board_days`) |
|---|---|---|---|---|---|
| `minimal` | 1 | 0 | mail and free feeds only | never | never |
| `economy` | 2 | 1 | + LinkedIn, + career-page and board sweeps — **the default** | Mon | Tue |
| `standard` | 3 | 2 | same sweeps, more often | Mon, Wed | Tue, Thu |
| `full` | 5 | 5 | + drafting | Mon, Wed, Fri | Tue, Thu, Sat |

The two day columns are the only thing a posture changes about searching: an **unattended** run
searches employer career pages and job boards only on those days. Mail, company job feeds and
LinkedIn run as before. A profile upgraded to 0.78.0 moves to these days (a copy of its
`config.json` is kept as `config.json.pre-0.78.0`). Change the days with
`posture.py --set-company-days` and `posture.py --set-board-days` (see `/jobsearch:tier`).

Set `search.posture` in your `config.json`, or define your own. See
[How it works — Cost](../../docs/user/jobsearch/how-it-works.md#cost).

**Research is never limited by a posture.** Every role a run finds that passes your screen
(`VERDICT keep`) is researched in that same run, on every posture, in batches of up to 10, with any
overflow on the next run. A borderline role (`review`) waits for you. Drafting is the other model
work a posture holds: what it refuses is queued and drained by the next run whose posture permits
it. A run is unattended unless started in its explicit attended form
(`/jobsearch:daily-run attended`), which lifts the drafting limit and the sweep days but never the
LinkedIn one.

**`minimal` is the hands-on level.** You run the searches yourself:
`/jobsearch:search attended` (both kinds), `/jobsearch:search companies attended` or
`/jobsearch:search boards attended`. The form without `attended` only previews. An on-demand search
works on every posture, ignores the sweep days, researches the roles it keeps in the same session,
and does not use up the scheduled sweep. `/jobsearch:sourcing employers attended` finds a tracked
company's job feed. Every command is listed in
[Commands](../../docs/user/jobsearch/commands.md).

## What it runs, sends and fetches

Everything below is the complete list. Nothing in the plugin downloads code and runs it, and nothing
is installed at install time: the plugin is Python standard library and its own files.

**Programs it runs.** `python3`, on the plugin's own scripts under `scripts/`. One of them,
`ensure_connectors.py`, also runs `claude plugin install gmail-multi` from this same marketplace when
that companion plugin is missing; it is the only connector `plugin.json` declares.

- **Hooks** (`hooks/hooks.json`):
  - At session start:
    - record that the session started (`journal.py --fired`);
    - apply pending data migrations, then do two more things in your own folder (`migrate.py --hook`):
      - scan your profile for engine terms;
      - bring opted-in channels up to the shipped channel catalog;
    - self-test the guards;
    - install the companion connector if it is missing (`ensure_connectors.py`).
  - On each prompt: `drift_guard.py` notices when the plugin was updated mid-session.
  - Before tool calls, five guards that either **refuse** a call or let it through unchanged; none
    approves anything:
    - `guard_engine_writes.py` refuses a write into the plugin's own files;
    - `guard_outbound_click.py` refuses a browser click that would send, connect or apply;
    - `guard_mail_send.py` refuses the mail send tools outright;
    - `guard_mail_scope.py` refuses mail access to an account your profile does not declare;
    - `guard_board_hosts.py` refuses opening a job-board host the plugin does not support.
- **The mod** (`hooks/register.ts`, the status pane) does these things, and only inside a session
  whose folder is a job-search profile:
  - Runs three scripts, each named as a literal: `panel.py` (the numbers it shows), `presence_set.py`
    (the resume and LinkedIn review panes) and `record.py source on|off <id>` (the Sources buttons;
    the only way the mod changes a file).
  - Calls one tool itself: the Desktop app's `scheduled-tasks` → `run_scheduled_task`, when you press
    **Run daily now** or **Run weekly now**. It starts your own `search-daily` or
    `search-strategy-weekly` task and sends nothing else.
  - Runs one slash command itself: `/jobsearch:resume <variant>`, when you press **Render**.
  - Submits three prompts, all fixed text:
    - "Start the scheduled task … and report only whether it started", when a Run button cannot call
      the tool directly;
    - "Revise the … variant … with profile-optimizer", when you press **Revise**;
    - "A background run queued N new item(s). Drain the queue.", from the watcher.

    They carry a task name, a variant name or a count, never your data.
  - Registers `jobsearch_watch` and answers it itself: calling it arms the watcher, which checks
    `data/inbox.jsonl` once a minute.
  - Hooks `command.run` only to open its three panes (`/jobsearch:status`, `review-resume`,
    `review-linkedin`).

**What it fetches.**

- Public job-posting APIs, with no account: Greenhouse (`boards-api.greenhouse.io`), Lever
  (`api.lever.co`, `api.eu.lever.co`), Ashby (`api.ashbyhq.com`), and a Workday tenant's `robots.txt`
  and sitemap (`feed_poll.py`).
- A tracked employer's own careers page, one page plus one same-site link, only in an attended run
  (`ats_finder.py`).
- Through your own signed-in browser: LinkedIn and the job boards you list.

**What it sends, and where.**

- Your mail is read through the gmail-multi connector, or over IMAP to `imap.gmail.com` (TLS).
- The one credential it reads is the Gmail app password **you** store in your OS credential store,
  and it is sent only to `imap.gmail.com`.
- It never sends mail, and it never posts, connects or applies on your behalf; the guards above
  refuse those calls.
- Your profile data stays in your own folder; nothing is sent to the plugin's authors.

## Privacy

[Privacy and your data](https://github.com/crinaro/marketplace/blob/main/plugins/jobsearch/PRIVACY.md) ([PRIVACY.md](PRIVACY.md) in this folder) says what jobsearch reads, where it keeps it, what leaves your machine, and how long it stays. Questions: marketplace@crinaro.ai.

## Getting started

1. **Install the plugin.**
   ```
   /plugin marketplace add crinaro/marketplace
   /plugin install jobsearch@crinaro-marketplace
   ```
   See [INSTALL.md](INSTALL.md) for the details.
2. **Create YOUR own private search directory**, then from inside it:
   ```bash
   ~/.claude/jobsearch/run init_profile.py --scaffold
   ```
   (If `~/.claude/jobsearch/run` does not exist yet, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_launcher.py"` once first.)
3. **The conversational half** — invoke the `onboarding` skill in Claude Code. It reads your
   resume, fills your config, and asks the handful of things a resume never says: comp floors,
   geography, and what you will NOT do.
4. **Credentials** — yours to place. See the generated `CREDENTIALS.md`.

## Understanding it

- **[Commands](../../docs/user/jobsearch/commands.md)** — every `/jobsearch:` command and skill, in
  plain words, grouped by what you want to do.
- **[How it works](../../docs/user/jobsearch/how-it-works.md)** — the engine/profile split, what runs when,
  and the rules it holds itself to: it never sends, never handles a credential, and never invents
  a fact about you.
- **[Mailboxes](../../docs/user/jobsearch/mailboxes.md)** — which mail accounts the search reads and
  how to add or check one.
- **[Your data](../../docs/user/jobsearch/your-data.md)** — every file it keeps, what the fields mean, and
  how to edit them by hand safely.
- **[Reading what the search produces](../../docs/user/jobsearch/reading-your-files.md)** — which file
  opens in which tool. There is **one published page**, `views/dashboard_artifact.html`, and since
  0.71.0 it holds only what is waiting on a decision from you: drafts to review (a pending message in
  full), opportunities to pursue, and applications to finish with their cover letters. Each record is
  shown in full in exactly one list and is a linked one-line reference elsewhere. A reviewer's comment
  on that page is applied to the draft through the session (before-and-after, your yes), never by
  editing the page. Where the rest went: **`/jobsearch:status`** shows where things stand (what needs
  you, the inbox, the lock, the last and next background run, what is in flight, the week, channels and
  open asks), and **`/jobsearch:review-resume`** and **`/jobsearch:review-linkedin`** review your resume
  and public-profile text (the second published page was retired in 0.71.0). With the plugin's mod on,
  `/jobsearch:status` is a pane and a one-line band under the prompt; with mods off, or anywhere a pane
  cannot be drawn, the same content prints as text. Plus kb files, call preps, drafts and letters, on
  the desktop or in an editor.

The one idea worth carrying into everything else: **datasets are JSON, documents are markdown.**
If it gets counted, sorted or joined it is data; if you read and edit it in full it is a
document. That is why a cover letter's text is markdown but the link between that letter and the
role is a field.

## Status

Extracted from a working single-user system that has been running daily since July 2026. It is
honest, not polished: the engine is well-tested (200+ regression tests, six CI gates) and the
onboarding path has been tested against a fresh install but **not yet against a second human**.
Expect rough edges in setup and tell me about them.

## License

Apache License 2.0 — see [`LICENSE`](../../LICENSE) at the repository root.
