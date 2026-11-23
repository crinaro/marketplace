# Privacy and your data — jobsearch

jobsearch works with personal information: your resume, your mail and the people you talk to about
work. This page says what it reads, where that goes, and how long it stays.

## What it reads

- Your resume and the profile you fill in during onboarding.
- Mail in the accounts you declare, through **one** mail connector that you choose with
  `communications.mail_connector` (see "Mail connectors" below), to find replies, interview
  invitations and messages from applicant-tracking systems.
- LinkedIn and the job boards you list, through your own signed-in browser.
- Public job postings: Greenhouse, Lever, Ashby and Workday job lists, and a tracked employer's own
  careers page (see the README's "What it runs, sends and fetches").

## Mail connectors

| `mail_connector` value | what it is | what it reads | where it runs |
|---|---|---|---|
| `gmail-multi` (the default) | the `gmail-multi` plugin, over IMAP to `imap.gmail.com` (TLS), with an app password you store in your OS credential store | the messages that match each check's search, in every address you declared | Desktop app (S1), scheduled task (S2), terminal `claude` (S3a) |
| `claude-gmail` | the Gmail connector managed in claude.ai | the headers of every message in the window, plus up to 25 message bodies per account per run | S1, S2 and S3a under a claude.ai subscription login |
| `claude-m365` | the Microsoft 365 connector managed in claude.ai | as `claude-gmail` | as `claude-gmail` |
| `claude-fastmail` | the Fastmail connector managed in claude.ai | as `claude-gmail` | as `claude-gmail` |
| `claude-superhuman` | the Superhuman connector managed in claude.ai | as `claude-gmail`, from the mailbox your Superhuman account is connected to | as `claude-gmail` |

For the four `claude-*` values:

- **The window is at most 3 days.** A longer gap is reported as not covered, never filled in silently.
- **Claude does the fetching, and a script does the saving.** The connector's tools run inside your
  Claude session. The plugin's own scripts never contact Google, Microsoft, Fastmail or Superhuman.
  Claude writes what it fetched to one local file per account, and a script checks that file before
  anything uses it.
- **Not under an API key, and not on WSL.** A claude.ai connector reaches a session only under a
  claude.ai subscription login. Where it is missing, the run says so and skips the fetch.
- **Written to each connector's published contract.** The four `claude-*` connectors are built
  against the tools each vendor publishes. **Live behaviour against any of them is UNVERIFIED until
  users report it.** If a connector does not behave as published, the run prints
  `CONTRACT MISMATCH` or `MAIL BUNDLE REFUSED`, and `report_issue.py` sends the report.
- **"covered" is a narrow claim.** A run prints `covered` when no permission gap was found in the
  tool names the session reported and in the settings files the plugin can read. It does not mean
  "will not prompt": a rule your organisation sets outside those files can still stop a run.
- **Microsoft 365 is for work or school accounts only.** It works only where your organisation's
  Microsoft Entra administrator has consented to the Claude connector; an employee or student
  usually cannot grant this. Personal outlook.com, hotmail.com and live.com accounts are not
  covered. If your tenant is an employer's, tracking a job search there puts it in your employer's
  mailbox, and you should know that before you choose it.
- **`gmail-multi` is still installed** under a `claude-*` selection. It is installed on the machine,
  and the selection is per profile. Its tools are refused for that profile.

## Where it keeps it

Only in your own profile folder on your machine, as plain JSON and markdown files you can read, edit
and delete. That includes the full text of messages it records (`data/messages.jsonl`), your resume
variants and your drafts. Under a `claude-*` selection it also includes the fetched messages:
`.jobsearch/mail_bundle/` in your profile folder, pruned to the last 3 days, and never written
anywhere under your home folder. Under `sync.mode: remote` the whole profile is also pushed to your
profile repository's own remote. There is no server of ours, no telemetry and no analytics. The
plugin's authors never receive your data.

**Your LinkedIn text and the changes proposed to it** (since 0.93.0) are kept in
`data/presence_changes.jsonl`, beside your claim union: the headline, skills and profile status you
state, what was read from your own LinkedIn profile in a session you attended and confirmed, each
change the plugin drafted with the resume lines it rests on, and whether you applied or declined it.
The plugin never edits your LinkedIn profile: you paste every change yourself. **Under
`sync.mode: remote` this file leaves your machine** with every other file in your profile, pushed to
your profile repository's own remote. It never goes to the plugin's authors or to the marketplace.

**Your resume's Word file** (since 0.93.0, local `.docx` output only) is kept in your profile's resume folder,
`presence/resumes/` unless you set another folder inside the profile; a folder outside the profile is refused. Before
the plugin changes that file it saves your bytes beside it as `<name>.before-update-<date>.docx` (the ten newest are
kept), `<name>.before-keep-<date>.docx` or `<name>.before-fresh-<date>.docx` (kept until you delete them). Fingerprints
of the file (hashes, never its text) and of each paragraph it changed are kept in `data/presence_changes.jsonl`. To tell
your machines apart, the plugin writes a random id to `jobsearch-machine` inside your profile's `.git` folder, which
git never pushes; the id is recorded on those rows, and no computer name is ever read. **Whether the Word file leaves
your machine follows your profile's git remote:** with no remote it stays on this machine and the review's commit
leaves every `.docx` out; with a remote the Word file is committed and pushed with your profile, its dated backups are
not, and a copy from your other machine that differs is saved beside it as `<name>.remote-<short commit id>.docx`. When an email
attaches the resume, gmail-multi reads the file from your disk and puts it in the draft in your own mailbox; a
claude.ai connector is never given the file, and you add it to that draft yourself.

## What Claude sees

What the plugin reads in a session (mail, your resume, postings) is part of your conversation with
Claude, and is handled under your Claude account's terms and privacy settings. Mail fetched through
a claude.ai connector is also handled under that connector's own terms, with the vendor that runs it.

## What leaves your machine

Only the fetches and the mail connection listed above, and, under `sync.mode: remote`, your profile
pushed to your own profile repository's remote. The plugin never posts, connects or applies on
your behalf, and its guards refuse those calls. **It never sends mail either: you always press Send.**
If you set `actions.modes.email-send` to `me` (since 0.93.0), a message you were shown in full and
approved, in a session you are attending, is put into your own mailbox's drafts for you; you open your
drafts and send it yourself. The draft is written to your own mailbox through the mail connector you
selected (gmail-multi, or a claude.ai connector that offers a draft tool); nothing passes through a
server of ours. Until you send it, the message text is kept in your profile's `data/outbox.jsonl`, and
after it, in your own `messages` record, as for any mail you send. (From 0.91.0 to 0.92.0 this setting
let the plugin send an approved email after Claude Code's prompt; 0.93.0 removed that.)

**What that claim covers, exactly.** jobsearch's own code has no mail-sending code. Two guards refuse
mail sends. One covers `gmail-multi`'s send, reply and forward tools, in every session, whatever your
settings. Both guards are set to block the call if they fail to run (`onFailure: block`, Claude Code v2.1.295 or
later). The other guard covers the claude.ai connectors' send
tools (send, reply, forward, unsubscribe, mail rules, and the event writes of Superhuman and
Fastmail, which send invitations from your identity). The
second guard stays on while jobsearch is loaded, whatever your selection. Its script and its
matcher are TESTED; **platform routing is UNVERIFIED**. Nobody has yet measured that Claude Code
sends a claude.ai connector's call to the guard on every surface, or that a refusal stops it there.
Also not covered:

- a mail write tool with no mail word in its name that a vendor has not published, and calendar
  event writes through Microsoft 365, whose tool names are unpublished;
- a guard that fails to start (a syntax error, a missing `python3`, a hook timeout) on a Claude Code
  older than v2.1.295, which ignores `onFailure: block` and lets the call through. The session-start
  self-test warns about the first of these;
- mail changes that are not sends, such as moving, labelling or deleting a message.

**The cost of the guard.** On a user-scope install it applies to every session on your machine: no
claude.ai mail connector can send, reply or forward there, and any connector tool named exactly
`send_message`, `reply` or `forward` is refused whatever its product. To avoid that, disable
jobsearch for the project, or install it at project scope. **S6** (claude.ai with plugins):
whether plugin hooks run there is UNVERIFIED; if they do, the deny applies to every S6 session on
the account.

The one exception to "nothing leaves" is a step you start yourself. `report_issue.py` reports a
problem in two ways, and neither runs unless you ask for it. Both show you the report first, and
refuse one that carries an email address, a phone number, a pay figure or a person's name.

- `--file` files it as a **public** GitHub issue on `crinaro/marketplace`.
- `--email` prints a To line, a Subject and a body for you to paste into your own mail client. The
  plugin sends nothing. **An emailed report reaches the maintainers together with your own address**
  (your mail client adds it as the sender), and the maintainers may re-file it publicly with personal
  data removed.

## How long it keeps it

Until you delete it. Deleting your profile folder removes everything the plugin kept. Uninstalling
the plugin leaves that folder untouched. The Gmail app password stays in your OS credential store
until you remove it.

## Who it is for

jobsearch is not intended for anyone under 18.

## Contact

marketplace@crinaro.ai
