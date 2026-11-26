# Commands

Everything you can type to the job search, grouped by what you want to do. Each entry says when to
use it and whether it **runs** something (it changes a setting, writes a file or starts work) or only
**shows** you something. Type the full name, for example `/jobsearch:status`.

Two ideas first:

- **`attended` is a word you type.** A few commands do real work only when you add it, because the
  plugin never guesses that you are at the keyboard. Without it they show what would happen and stop.
- **Your posture** (`minimal`, `economy`, `standard`, `full`) decides how often an *unattended* run
  searches employer career pages and job boards. It never decides whether a role the search found
  gets researched. See [How it works: Cost](how-it-works.md#cost).

---

## Get started and set up

**`/jobsearch:onboarding`** *(skill)*. Use it when you are installing for the first time and have a
resume to read. It asks the handful of things a resume never says (pay floors, where you would
move, what you will not do) and fills in your profile. **Runs** (it writes your profile files, and
nothing is sent anywhere).

**`/jobsearch:coordinator`** *(skill)*. Use it to start or resume a working session: what has changed,
what is waiting on you, whether the checks pass. It is the one session you talk to. **Runs** a startup
check and lists what needs you; from there, changes happen as you decide things.

**`/jobsearch:doctor`**. Use it when you want to know whether the install and your configuration are
healthy and current. Add `fix` to let it repair the safe gaps. **Shows** a report; with `fix` it
**runs** and only ever adds missing settings. Whether the search is *working well* is `checkup`.

**`/jobsearch:setup-routines`**. Use it after setup, after changing your posture, or when a scheduled
run has drifted: it creates or repairs the two scheduled runs (daily and weekly). **Runs** (it creates
or changes scheduled tasks, in the desktop app).

**`/jobsearch:mailboxes`** *(also `add <address>` and `check`)*. Use it to choose which mail accounts
the search reads and to check that each one can actually be searched. With no argument it **shows**
the list; `add` and `check` **run**. The account itself is registered with `/gmail-multi:accounts`.
See [Mailboxes](mailboxes.md).

**`/jobsearch:linkedin`**. Use it when LinkedIn is not signed in, or you want to check that it is. It
walks you through signing in, in the desktop app's browser. **Runs** (it opens LinkedIn and reads the
page; it never types your password).

---

## Run the search

**`/jobsearch:daily-run`** *(skill; add `attended` to run it yourself)*. Use it when you want a full
sweep now instead of waiting for the scheduled one: mail, LinkedIn, sources, state updates and the
dashboard. **Runs.** On its own it follows your posture exactly as a scheduled run does. With
`/jobsearch:daily-run attended` it also drafts what your posture would hold and ignores the sweep days.
It never overrides the LinkedIn limit.

**`/jobsearch:search attended`**. Use it when you want to look for roles now, on any day, in both
employer career pages and job boards. **Runs** a sweep, then screens what it found and researches
every role that passes your screen, in the same session. It works on every posture, `minimal`
included, ignores the sweep days (and the career-page split, if you turned it on: every due career
page is checked, whatever its day), and does not use up the scheduled sweep.

**`/jobsearch:search companies attended`**. Use it for employer career pages only. **Runs**, as above.

**`/jobsearch:search boards attended`**. Use it for job boards and aggregators only. **Runs**, as above.

**`/jobsearch:search`**, **`/jobsearch:search companies`** or **`/jobsearch:search boards`**, without
`attended`. Use it to see what is due without searching. **Shows** a preview and stops. A career page
whose day in a split has not come is not in the preview's worklist; `channels_due.py` lists it under
WAITING FOR ITS SWEEP DAY, with the date it opens.

**`/jobsearch:sourcing employers attended`**. Use it to find the job-board feed of a company you track
that has none yet. **Runs**: it reads each company's careers page (plus one link on the same site),
then proposes what it found, and you accept or decline each one. Without `attended`
(`/jobsearch:sourcing employers`) it only **shows** what is waiting.

**`/jobsearch:tier`** *(`minimal`, `economy`, `standard` or `full`)*. Use it to change how often the
search runs, which is the main lever on cost, and on which weekdays it sweeps career pages and job
boards. **Shows** where you are; naming a posture **runs** (it saves the choice and updates the
schedule). It also explains how to share a tier's career pages out across its days, so each is checked on
one of them (`company_split`, off unless you turn it on), and that a job board you want checked every day
needs its `board_days` set to all seven days.

On `minimal` nothing sweeps career pages or job boards by itself, so the three `search ... attended`
commands above are how you search. Mail, company job feeds and LinkedIn keep running as set.

### The LinkedIn job search (since 0.94.0)

**`/jobsearch:search linkedin attended`**. Use it when the start line says `LINKEDIN JOB SEARCH DUE`, or when you want the LinkedIn job search now. **Runs** the search by each of your target titles and
places, the first page of results of each (up to `search.linkedin_queries_per_pass`, 20), in the Claude desktop app's browser pane. It only reads: it never clicks, types or signs in. **The `linkedin` form needs the
desktop app**: without `attended`, or in a session with no browser pane, it says where the search runs and stops. A scheduled run does the same search by itself when it is due (48 hours after the last search was
started or reached, `search.linkedin_search_every_days` days counted in hours, 2 unless you changed it; never before the 0.94.0 update step has run); this command is for when it could not, or you want it now. It does not use up the daily LinkedIn limit.

- **`journal.py --linkedin-search-skip --until <date>`**. Use it to pause the LinkedIn job search for up to 30 days (the start line stops asking, and the summary says `skipped by you until <date>`).
- **`record.py source off linkedin-jobsearch`** turns it off altogether; `source on linkedin-jobsearch` turns it back on.
- **`journal.py --linkedin-search-on --attended --warning <date>`**. Use it after LinkedIn showed a warning and you have looked at LinkedIn yourself: any warning, sign-in or identity check, CAPTCHA, unusual-activity
  or usage-limit page, or a LinkedIn page the plugin is in doubt about, ends the search at once and turns the scheduled search **off**, and this command (with the warning's date, which the first line of every summary shows) is the only thing that turns it back on (a command stamped before the warning it names is refused).
  The attended command above still works while it is off, and prints the warning first.

How it works, and what has not been tested, is in *The LinkedIn job search* in [How it works](how-it-works.md#the-linkedin-job-search-since-0940).

---

## Sources and connections

**`/jobsearch:sourcing`**. Use it to see every place the search looks for roles (LinkedIn, boards such
as Indeed and Dice, alert emails, company feeds, curated and investment-firm boards), whether each is
on, and how it is reached. **Shows** the list. Naming something changes it, so these **run**:

- `/jobsearch:sourcing on <source>` and `/jobsearch:sourcing off <source>` turn a source on or off.
- `/jobsearch:sourcing browser,plugin,chrome` sets the order the search tries to reach a board: a site
  plugin, Claude's built-in browser, or the Chrome extension.
- `/jobsearch:sourcing <channel> <plugin-name>` points one board at one plugin.

**`/jobsearch:mailboxes`**. Listed above; it is also where you check mail access.

**`/jobsearch:linkedin`**. Listed above; LinkedIn is the one source that needs a signed-in browser.

---

## See where things stand

**`/jobsearch:status`**. Use it when you ask where things stand: what needs you and by when, the
inbox, the last and next background run, whether the runs did anything, and whether the checks are
healthy. **Shows** only; it changes nothing and is safe to run at any time.

**`/jobsearch:coordinator`**. Listed above; use it when you want to *work* the items, not just see them.

**`/jobsearch:weekly-review`** *(skill)*. Use it for the weekly strategy look: it opens with your network (who
you can reach and how, the week's reach-out budget, the network funnel and any open suggestions), then which channels
produced roles, whether you kept to your own cadence, and proposed setting changes. **Runs** and writes a
review; any change to your settings, and any suggestion it makes about a company, a plan or a person, is a proposal for you
to confirm. Since 0.93.0 it also runs the resume and LinkedIn coverage report (`resume_report.py --gaps`) and, when that report's
last line says `DISPATCH: yes`, has `profile-optimizer` draft changes for the open gaps; each draft is recorded as a proposal
for you to apply. **`/jobsearch:weekly-review attended`** is the form for when you are at the keyboard: only it asks you
questions (your LinkedIn headline, skills or whether you have a profile at all), redrafts a gap whose last draft recorded
nothing, or starts a live read of your own LinkedIn profile. A review is unattended unless you type `attended`; an unattended
one only lists those questions, and drafts only when your search posture allows drafting.

**`/jobsearch:checkup`**. Use it when something is not working, or you want to know whether the search
is working well. **Runs** an investigation and tells you whether the cause is a setting here, a decision
for you, or a defect in the plugin; a defect is turned into a report for the plugin's maintainers only
after you approve what is in it.

### Looking at a role and at the pipeline from the command line

These are scripts, run as `~/.claude/jobsearch/run <script> ...`. They **show** or record one thing, and
you can leave them alone unless something looks wrong.

- **`lifecycle.py --report`**. Shows the whole pipeline in one place: how many roles are ready, how many are
  yours to read, how many are process failures (with the oldest age and each cause), how many are waiting
  for intake, anything the run did not look at, and the line that adds every role to exactly one group. Add
  `--json` for a machine-readable version. **Shows** only.
- **`record.py show <role id>`**. Prints the whole stored record of one role, including its read attempts,
  its research notes and its fit. Nothing is cut short. **Shows** only.
- **`record.py fit --from-file <file>`** (since 0.87.0). The run uses it after research to store the researcher's fit
  analysis for each role; a line it cannot read is refused with its reason and nothing is written for that role. You
  do not normally run it. **Runs**: it writes `fit` onto the role.
- **`record.py read-jd <role id> --via candidate`**. Use it when a role is waiting as *your read*: you open
  the posting yourself, then record what it says, quoting a short line that names the role. **Runs**: it
  writes the read onto the role, and the next run screens the role on it.

**What the daily run drives for you.** You do not type these; they are listed so a line in a run's output
makes sense.

- `record.py capture-batch` records the roles a sweep found. It ends with a count line: how many roles were
  created, linked to a role you have, folded into a duplicate, refused, left waiting, flagged unverified,
  and how many it left because it ran out of time. It repeats until nothing is left over, and a refused item
  is reported rather than treated as a fault. Since 0.83.0 every queued role names the source it was seen
  on, and a role is refused, with the fix named, in one of three cases: its address is on no board the search
  knows; it is on a listed board your profile does not link (for example LinkedIn when you have no LinkedIn
  row) or has turned off; or it names a source your profile does not hold. The fix is the command to turn
  the source on (`record.py source on <source>`), or to close the item. A refused role stays waiting and is
  listed again on the next run.
- `record.py read-batch` fetches job descriptions for the roles that state a pay and re-screens each one.
  A page it cannot read is listed as `RESIDUE <role> (render)` with the reason, and goes on to a reader
  agent, or to you.
- `record.py read-failed <role id> --outcome <reason> --evidence "..."` records a read that failed, with its
  cause. It does not re-screen the role.
- `lifecycle.py --drain-plan` chooses which roles a run takes on (and prints a line when the count is
  trimmed to the time a run has); `lifecycle.py --drain-close` writes down at the end which roles the run
  left unfinished and why.
- `reconcile.py --ats --run <run id>` sweeps status mail and records the per-kind counts and any
  unmatched messages for that run. `brief.py --rebrief --already-locked` is accepted when the run already
  holds the lock. `precondition.py --prune` now refuses, and says so, when an entry it would delete is
  malformed, instead of deleting it.

---

## Make documents

**`/jobsearch:review-resume`**. Use it to look over your resume layer: the claims, each print version as
it will look, the open items, and (since 0.93.0) the coverage report for the print versions. With the
plugin's mod on it opens a pane, whose **Coverage** tab shows that report. **Shows** only.

**`/jobsearch:review-linkedin`**. Use it to check your public-profile text field by field, each with its
character count (no LinkedIn length limit is recorded, so nothing is called over one), and (since 0.93.0)
the LinkedIn coverage report, also on the pane's **Coverage** tab. **Shows** only. Signing in to LinkedIn
is `/jobsearch:linkedin`.

### Your resume and LinkedIn coverage (since 0.93.0)

Scripts, run as `~/.claude/jobsearch/run <script> ...`. The plugin never edits your LinkedIn profile:
every change it drafts is a proposal you paste in yourself, then record.

- **`resume_report.py`**. The coverage report: whether each resume version leads with one of your target
  titles, how the requirements of the roles you are pursuing are covered, how many bullets carry a number,
  how each version has done (no rate under five applications), readability, and your LinkedIn headline
  and skills against the topics that recur. **Shows** only: it stores nothing it prints. A
  `NOT CHECKED (reason)` line means a source could not be read, never that it is empty. Forms:
  `--surface print` or `--surface public-profile` (only those versions), `--json` (the same report as one
  object, which the pane uses), `--topics` (every requirement topic on record and how many roles carry
  it), `--gaps` (the open gaps, the questions, and a last `DISPATCH:` line saying whether a draft is
  due), `--packet` (the brief `profile-optimizer` drafts from; it names the file the drafts come back in).
  `--attended` marks you as present: questions are printed as `ASK:` rather than `LISTED:`.
- **`record.py presence`**. Shows what your LinkedIn profile says as recorded (status, headline, skills,
  with dates) and the open proposals. **Shows** only.
- **`record.py presence-state linkedin status none|skip|active`**. Tells the plugin you have no LinkedIn
  profile (`none`), have one but will not state it (`skip`), or have one (`active`). `none` and `skip`
  end the question. **Runs**.
- **`record.py presence-state linkedin headline --text-file <file>`** and **`presence-state linkedin
  skills --from-file <file>`** (one skill per line). Record your current headline or skills. **Runs**.
  `presence-state --observed --from-file <file> --attended` records what a read of your own profile saw,
  after you confirm it.
- **`record.py presence-propose --from-file <file> --dispatched <gap> ...`**. The weekly review runs it to
  record the optimizer's drafts. Each line prints `RECORDED pc-<n> <gap>` or `REFUSED <gap>: <reason>`; a
  gap that got no draft is recorded as refused, so an unattended review does not pay to draft it again.
  You do not normally run it. **Runs**.
- **`record.py presence-decide <id> applied`** (`--applied-on <date>`, or `--as-edited --text-file <file>`
  when you changed the text) or **`presence-decide <id> declined`** (`--why "..."`). Say what you did
  with a proposal. **Runs**.
- **`record.py presence-apply <id>`**. For a proposal to one of your resume version files only: the
  plugin makes that one edit, checks the versions, puts the file back exactly as it was if the check
  fails, and records the edit. Your resume files are yours, in your own project, so it needs no other
  approval (since 0.93.0). It never edits LinkedIn. **Runs**.
- **`record.py presence-import <version id> --from-file <file>`**. Brings a resume from anywhere on your
  computer into one of your declared resume versions: a `.md`, `.txt` or Word `.docx` file (a Google Doc
  first saved from Drive as one of those; a PDF first copied into a `.md` file). Word list items become
  bullet lines. It records the version's earlier text first, so you can put it back. **Runs**.
- **`record.py retopic <old> <new>`**. Renames a requirement topic on every role at once, when two topics
  mean the same thing. **Runs**.
- **`record.py fit-key <role id> <index> [--topic <topic>] [--claim-file <file>]`**. Sets the topic, or the
  resume line the evidence rests on, on one requirement of a role's fit. The line must be in your claim
  union word for word. **Runs**.

### Your resume's Word file, and the resume attached to an email (since 0.93.0)

- **`record.py presence-docx <version id>`**. Keeps the Word file of a resume version in the layout you
  gave it. The first run writes the default layout. After that, when the version's text changes, only the
  paragraphs whose words changed are rewritten, inside your own formatting: the spacing, text size and
  margins you set are kept. A dated backup (`<name>.before-update-<date>.docx`) is taken before each
  update, and the ten newest are kept. **If you changed the words in Word**, nothing is overwritten and you
  are asked: "You changed the Word file for <version>. Update the resume we keep on file from it? If not,
  your change will be overwritten at the next update." Answer with `--keep word` (yes: your Word text goes
  into the version, your layout is kept) or `--keep md` (no: your file is backed up as
  `<name>.before-keep-<date>.docx`, then updated); in a session you are attending, add `--attended`. A
  scheduled run never answers: it files the question as an ask, and you answer it with `--keep word|md
  --answer resume-word-edited:<version id>`. `--fresh --attended` goes back to the default layout after a
  `before-fresh` backup. `--here --attended` makes this machine the home of a file another machine last
  wrote (a profile with no git remote; the `ELSEWHERE` line says so). `--all` settles every active print
  version and every version an approved email attaches, and is what the weekly review runs. Under Drive
  output it prints `SKIPPED` and writes nothing. Other lines: `TRACKED` (a Word file committed to your
  profile, with the command that stops tracking it, which you run yourself), `UNMERGED` (your two machines
  both changed it; the other side is saved beside it as `<name>.remote-<id>.docx`), `REFUSED` (with the
  reason and nothing written). **Runs**.
- **`variant_out.py --render <version id>`** no longer writes that Word file under `local_docx`: it is
  refused, because it would overwrite your layout. Use `--out <path>` for a separate copy, which is yours
  and never updated, or `--dry-run` to preview. **Runs**.
- **An email that attaches your resume.** A draft whose text says the resume is attached names the version
  (`**Attach:** resume:<version id>`). With gmail-multi 0.6.0 or later the file goes into the draft. With a
  claude.ai mail connector, an older gmail-multi, Drive output, or a Word file waiting on your answer, the
  draft is made without it and an `ATTACH BY HAND o-<n>: ...` line names the file: add it yourself before
  you press Send.
- **`outbox.py attached o-<n> --result-file <file>`**. After a draft that carried a file, the run saves the
  mail tool's reply to a file and runs this, which records whether the file you were shown is the file
  that was attached (its size and fingerprint). `o-<n>: ... attached, size and hash match` confirms it; a
  `MISMATCH` line is followed by `ATTACH BY HAND`; `NO DRAFT` means gmail-multi refused the file and made no
  draft. Until it runs, `outbox.py list` and `draft` print `UNCONFIRMED o-<n>`. **Runs**.

**`/jobsearch:resume`** *(`drive`, `local_docx` or a resume version's id)*. Use it to choose where a
finished resume goes (a Google Doc in your Drive folder, or a local `.docx`) and to produce one. With no
argument it **shows** the current setting; naming a destination or a version **runs**. Reviewing the
content is `review-resume`.

**`/jobsearch:letters`** *(`drive`, `local_docx` or an employer's name)*. Use it to choose where finished
cover letters go and to produce one for an employer. With no argument it **shows** the current setting;
naming a destination or an employer **runs**. Nothing is sent to anyone.

- **`letter_out.py --check`**. Checks every letter waiting in `applying/cover_letters.md` and your letter guide, and
  says which fails and why. It also runs at the start of a run. **Runs**; it changes nothing.
- **`letter_out.py --preflight <opp_id> [--record]`**. Asks whether a letter can be written for one role: it needs a fit
  analysis with something that matched, and a letter guide that still works. It prints one line, `ok` or `stop` with the
  reason. With `--record` a stop is also saved as an item in your Open asks (the desktop panel and `/jobsearch:status`).
  **Runs**; the writer does it first, so you rarely type it.
- **`letter_out.py --set-guide <path|none>`**. Declares your own letter guide, a file in your profile, or stops using
  one with `none`. It records the guide's headings, and refuses a path outside your profile or a file that is missing or
  empty. The setting it writes is `writing.letter_guide`. **Runs**.
- **`profile.py --writing`**. Prints the writing rules a letter follows: your header, the length, the banned characters,
  US English, and your guide if you declared one. **Runs**; it only reads.

---

## Work on a role

**`/jobsearch:application-session`** *(skill)*. Use it when you are submitting one or more applications
this session: it walks the applying view, the resume version for each role and the follow-up work each
submission creates. **Runs**; you submit, it never does.

**`/jobsearch:call-prep`** *(skill)*. Use it before a scheduled call or interview, or when a prep note is
shown as owed. It writes the prep note from what the plugin already knows about the company and the
people. **Runs** (it writes one note; it researches the company only if it is new to the plugin).

**`/jobsearch:coordinator`**. Listed above; the place to review drafts, decide on a role and say yes or no
to what the search proposes.

### Pursuing, and correcting a read (since 0.94.0)

- **`record.py decide <role> pursue`**. Use it when you want to pursue a role (usually by telling the coordinator). **Writes** the decision and, in the same step, makes the role's company a target with no 1-to-5 rating, unless
  you passed on it, it is a staffing firm or a job board, or you stated a motivation for it earlier; the line it prints says which. `--no-target` pursues only the role. Its other roles are then read only when they meet your criteria.
- **`record.py read-withdraw <role> --at <the read's time> --why "..."`**. Use it when a role's description was read wrongly, for example a page that showed a title and no description. **Writes** a withdrawal: the read stays in
  the history, the pay and place it replaced come back, the screen runs again and the role is read again. A decision you already made stays. `--dry-run` shows what it would do.

### Stopping follow-up with a person (since 0.92.0)

- **`record.py stop-following <person id> [--note "<why>"] [--dry-run]`**. Use it, by asking the coordinator ("stop
  following up with them"), when someone should leave *They wrote back* and *Awaiting a reply*. **Writes** one row and changes
  nothing else; a later message from them, or one you send them, brings them back. `--undo` resumes. If it prints
  `invalid choice: 'stop-following'`, run `/reload-plugins` and try again. Details: *Stopping follow-up with a person* in
  [Your data](your-data.md).
