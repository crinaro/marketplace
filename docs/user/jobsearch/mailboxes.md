# Mailboxes

The job search reads your mail through a connector. By default that is `gmail-multi`, a
separate plugin that installs alongside this one and holds the list of Gmail accounts on your
machine. This page says how the two lists relate, what the search will and will not touch, and
what to do when it tells you an address is missing.

You can instead pick a mail connector you added in claude.ai: Gmail, Microsoft 365 (work or school
accounts only; personal outlook.com, hotmail.com and live.com are not covered), Fastmail or
Superhuman. Then the two lists below do not apply: the connector reads the account you signed in
to there. See [Mail connector](your-data.md#mail-connector--configjsoncommunicationsmail_connector).

Starting with jobsearch 0.63.0 and gmail-multi 0.5.0 the two are linked **by reference**: the
accounts live in one place, and your profile names the ones the job search may use.

---

## Two lists, and which one owns what

| | lives in | holds | edited with |
|---|---|---|---|
| **gmail-multi's accounts** | `~/.claude/gmail-multi/accounts.json`, one file per machine | every Gmail address you have connected, for any use | `/gmail-multi:accounts` |
| **your profile's mailboxes** | `user.json` in your profile directory, under `mailboxes` | the addresses the job search may read: just the address, plus an optional `kind` and `note` | `/jobsearch:mailboxes` |

The profile list is a **subset** of the first. An address in your profile that gmail-multi does
not know is not searched, and you are told so. The job search never adds an account to
gmail-multi on your behalf, and gmail-multi never reads your profile.

Passwords are not in either file. Each account's app password is stored in your operating
system's credential store, under one shared name, and you place it there yourself with the
command `/gmail-multi:accounts` prints. A mailbox needs both a registered address and a stored
password before it is searched.

## What changes for the job search

- **Only your listed addresses are searched.** A job-search session can search or read mail
  for an address that is both in your profile and registered with gmail-multi, one account per
  call. It cannot see gmail-multi's other accounts, and it cannot list them: the account list
  tool is blocked in a job-search session, and `/jobsearch:mailboxes` shows your own list
  instead.
- **A session on your machine may be narrowed even when it is not about the job search.** If
  the plugin is enabled and a profile is remembered, gmail-multi's tools are limited to that
  profile's addresses in every session. To use another account, open a session where the
  job-search plugin is turned off.
- **The job search still only drafts.** It never sends mail. Under a claude.ai connector, a
  guard refuses that connector's send, reply and forward tools while jobsearch is loaded (the
  script and its matcher are tested; whether the app routes every call through it is not yet
  verified). Separately, gmail-multi now asks
  you to approve every send, reply or forward, and refuses one when nobody is there to answer
  (see the [gmail-multi README](../../../plugins/gmail-multi/README.md)). Inside a job-search
  session the draft-only rule applies first.

## Checking and changing the list

`/jobsearch:mailboxes` shows, for each address, two separate facts:

1. whether it is **in gmail-multi's registry**, or `NOT IN gmail-multi's registry — add it with
   /gmail-multi:accounts`;
2. whether its **app password** is stored, or `NO CREDENTIAL — not searchable`.

An account with only one of the two is not searched. The search says so in its run summary, as
a gap, and never as "nothing new".

- **Add an address:** register it first with `/gmail-multi:accounts`, then add it with
  `/jobsearch:mailboxes`. Adding an address gmail-multi does not know is refused, and nothing is
  written.
- **Remove an address:** `/jobsearch:mailboxes` removes it from your profile. It stays in
  gmail-multi, and its stored password is not deleted.
- **Sweeps and scheduled runs** read only your listed, registered addresses. Each address that is
  listed but unregistered gets one line in the run's output and counts as not covered.

## Upgrading to 0.63.0

You do nothing. The first session after upgrading changes your profile for you:

1. **A copy first.** Your `user.json` is copied beside itself before anything is changed.
2. **The old password-name field is dropped.** Each mailbox used to carry a `keychain_service`
   field that nothing read. It is removed. Your stored passwords are untouched.
3. **Every address is checked against gmail-multi.** If gmail-multi has not updated yet, or an
   address is missing from its list, the step is reported as **pending**, not done. Nothing is
   lost and the search keeps working on the old rule in the meantime, with a notice at the
   start of the session.
4. **A question for each missing address.** For every address gmail-multi does not know, the
   plugin adds one entry to your asks (`mailbox-unregistered:<address>`) with two choices:
   register the account with `/gmail-multi:accounts`, or remove the address with
   `/jobsearch:mailboxes`. The entry closes itself once the address is registered.

gmail-multi 0.5.0 does its own half the same way. Its old setting that pointed at your profile
file is folded into its own list of accounts, the old file is kept beside it as
`accounts.json.v1`, and if the profile file cannot be read at that moment it changes nothing and
tries again at the next session.

Related: [Mail connector](your-data.md#mail-connector--configjsoncommunicationsmail_connector)
(choosing between `gmail-multi` and the claude.ai connector) and
[Your data](your-data.md#mailboxes--userjsonmailboxes).
