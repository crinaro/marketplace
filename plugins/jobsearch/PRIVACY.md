# Privacy and your data — jobsearch

jobsearch works with personal information: your resume, your mail and the people you talk to about
work. This page says what it reads, where that goes, and how long it stays.

## What it reads

- Your resume and the profile you fill in during onboarding.
- Mail in the accounts you declare, through the gmail-multi connector or over IMAP to `imap.gmail.com`
  (TLS), to find replies, interview invitations and messages from applicant-tracking systems.
- LinkedIn and the job boards you list, through your own signed-in browser.
- Public job postings: Greenhouse, Lever, Ashby and Workday job lists, and a tracked employer's own
  careers page (see the README's "What it runs, sends and fetches").

## Where it keeps it

Only in your own profile folder on your machine, as plain JSON and markdown files you can read, edit
and delete. That includes the full text of messages it records (`data/messages.jsonl`), your resume
variants and your drafts. There is no server of ours, no telemetry and no analytics. The plugin's
authors never receive your data.

## What Claude sees

What the plugin reads in a session (mail, your resume, postings) is part of your conversation with
Claude, and is handled under your Claude account's terms and privacy settings.

## What leaves your machine

Only the fetches and the mail connection listed above. The plugin never sends mail, and never posts,
connects or applies on your behalf; its guards refuse those calls.

The one exception is a step you start yourself: `report_issue.py --file` files a bug report as a
**public** GitHub issue on `crinaro/marketplace`. It shows you the report first, and refuses one that
carries an email address, a phone number, a pay figure or a person's name.

## How long it keeps it

Until you delete it. Deleting your profile folder removes everything the plugin kept. Uninstalling
the plugin leaves that folder untouched. The Gmail app password stays in your OS credential store
until you remove it.

## Who it is for

jobsearch is not intended for anyone under 18.

## Contact

marketplace@crinaro.ai
