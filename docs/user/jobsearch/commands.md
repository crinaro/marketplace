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
included, ignores the sweep days, and does not use up the scheduled sweep.

**`/jobsearch:search companies attended`**. Use it for employer career pages only. **Runs**, as above.

**`/jobsearch:search boards attended`**. Use it for job boards and aggregators only. **Runs**, as above.

**`/jobsearch:search`**, **`/jobsearch:search companies`** or **`/jobsearch:search boards`**, without
`attended`. Use it to see what is due without searching. **Shows** a preview and stops.

**`/jobsearch:sourcing employers attended`**. Use it to find the job-board feed of a company you track
that has none yet. **Runs**: it reads each company's careers page (plus one link on the same site),
then proposes what it found, and you accept or decline each one. Without `attended`
(`/jobsearch:sourcing employers`) it only **shows** what is waiting.

**`/jobsearch:tier`** *(`minimal`, `economy`, `standard` or `full`)*. Use it to change how often the
search runs, which is the main lever on cost, and on which weekdays it sweeps career pages and job
boards. **Shows** where you are; naming a posture **runs** (it saves the choice and updates the
schedule).

On `minimal` nothing sweeps career pages or job boards by itself, so the three `search ... attended`
commands above are how you search. Mail, company job feeds and LinkedIn keep running as set.

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

**`/jobsearch:weekly-review`** *(skill)*. Use it for the weekly strategy look: which channels produced
roles, whether you kept to your own cadence, and proposed setting changes. **Runs** and writes a
review; any change to your settings is a proposal for you to approve.

**`/jobsearch:checkup`**. Use it when something is not working, or you want to know whether the search
is working well. **Runs** an investigation and tells you whether the cause is a setting here, a decision
for you, or a defect in the plugin; a defect is turned into a report for the plugin's maintainers only
after you approve what is in it.

---

## Make documents

**`/jobsearch:review-resume`**. Use it to look over your resume layer: the claims, each print version as
it will look, and the open items. **Shows** only.

**`/jobsearch:review-linkedin`**. Use it to check your public-profile text field by field against its
length limit. **Shows** only. Signing in to LinkedIn is `/jobsearch:linkedin`.

**`/jobsearch:resume`** *(`drive`, `local_docx` or a resume version's id)*. Use it to choose where a
finished resume goes (a Google Doc in your Drive folder, or a local `.docx`) and to produce one. With no
argument it **shows** the current setting; naming a destination or a version **runs**. Reviewing the
content is `review-resume`.

**`/jobsearch:letters`** *(`drive`, `local_docx` or an employer's name)*. Use it to choose where finished
cover letters go and to produce one for an employer. With no argument it **shows** the current setting;
naming a destination or an employer **runs**. Nothing is sent to anyone.

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
