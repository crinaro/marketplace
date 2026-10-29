# gmail-multi — a multi-account Gmail connector

The managed Gmail connector OAuth-binds to **one** Google account. This plugin covers
**all of yours in a single query** over IMAP: every search runs across every configured
account, every result is tagged with the mailbox it came from, attachments actually
download, drafts land in `[Gmail]/Drafts`, and it can **send, reply, and forward** from
whichever account you name, over SMTP with the same app password IMAP already uses. **Every
send, reply and forward asks you first, and is refused when nobody is there to answer** (see
"Sending always needs you present" below); drafting never asks.

Standalone by design — it needs no other plugin and no profile directory. Other plugins
in this marketplace (jobsearch) consume its mechanisms, but nothing about it assumes a
job search, and there is no platform dependency between them: jobsearch names it as
metadata and installs it for you the first time it is missing.

**A consumer that must not send enforces that itself.** jobsearch, for example, is
draft-only by an explicit review policy: it denies this connector's send/reply/forward
tools with its own `PreToolUse` guard for the whole session it is loaded in, and fails
closed if it cannot even read the request. That guard is jobsearch's, not this
connector's. When both plugins are installed the two compose: jobsearch's refusal beats
this connector's ask, so inside a job-search session a send is simply denied.

**Every send outcome states what is known to have been delivered** — sent, not sent, or
unknown — so nothing downstream is tempted into a blind retry after an ambiguous
failure. A connection lost right after the message is handed to the server leaves delivery
genuinely unknown; the tool says so, tells you to check `[Gmail]/Sent Mail`, and says not to
retry blindly.

## What it runs, sends and fetches

Everything below is the complete list. Nothing in the plugin downloads code and runs it, and nothing
is installed at install time: the plugin is Python standard library and its own files.

**Programs it runs.**

- `python3`, on the plugin's own scripts: the mail server (`gmail_mcp_server.py`) and two
  session-start hooks.
  - `heal_install.py` repairs this plugin's own install record after a version move. It reads the
    marketplace clone with `git show`.
  - `migrate.py` upgrades the account list in place.
- To read the app password, your OS credential store's own tool: `security` on macOS,
  `secret-tool` on Linux, or PowerShell's PasswordVault on Windows.

**What it sends, and where.** It connects only to Google's mail servers:

- `imap.gmail.com`, to search, read and draft;
- `smtp.gmail.com`, to send, reply and forward, each only after you approve that call.

The one credential it reads is the Gmail app password **you** store in your OS credential store,
and it goes only to those two servers, over TLS. `myaccount.google.com` appears only as the link
where you create an app password. Nothing is sent to the plugin's authors.

## Setup

1. Install the plugin:
   ```
   /plugin marketplace add crinaro/marketplace
   /plugin install gmail-multi@crinaro-marketplace
   ```
   Then, in a session: `/gmail-multi:accounts`, or directly:

   ```bash
   python3 scripts/accounts.py --add you@example.com
   python3 scripts/accounts.py --status
   ```

2. `--status` prints the exact command to store each account's **app password** in your
   OS credential store (Keychain / PasswordVault / secret-service). **You** run that
   command; the plugin never accepts, stores, prints, or logs a secret, and Claude never
   sees one. Use an app password, never the account password — 2-Step Verification must
   be on.

`accounts.json` is **one file per machine**, and it is this plugin's registry: a plain list of
the addresses you have added (`{"schema": 2, "accounts": [...]}`). `accounts.py` is its only
writer. `accounts.py --status --json` prints the same state for a script to read.

**You must say which account, every time.** A call that leaves `account` unset is refused,
and the refusal lists your registered addresses. This is deliberate: an unset account
used to mean "every address on the machine", which is the wrong default for a tool that can
also send. To search everything on purpose, pass `account="all"` to `gmail_search`. Reads and
drafts of a single message (`gmail_get_message`, `gmail_get_attachment`,
`gmail_create_draft`) and every send take exactly one address; `all` is refused there.

## A consumer references your registry; it does not own it

The registry is a **published, read-only interface** for other plugins. A consumer
(jobsearch is the one in this marketplace) keeps only the addresses it uses, and checks each
one against this list. An address it names that is not registered here is reported loudly,
with the fix: add it with `/gmail-multi:accounts`. Nothing outside this plugin writes the
registry, and this plugin no longer reads anything from a consumer's files.

- jobsearch narrows further for itself: inside a job-search session it allows only the
  addresses listed in that profile, and it hides `gmail_accounts` (the machine-wide list)
  from the session. That is jobsearch's guard, and it applies only where jobsearch is
  installed.
- On its own, this plugin applies the two rules above (an account must be named, and it must
  be registered). It does not know which program is calling, so any narrower scope is the
  caller's.

**Upgrading from 0.4.x.** Earlier versions let a consumer's profile file be listed under
`include`, so a profile's mailboxes joined this list by delegation. 0.5.0 folds every
included address into `accounts` itself the first time a session starts, keeps your old file
as `accounts.json.v1` beside it, and removes `include`. If an included file cannot be read, <!-- retired-terms: ok -->
the registry is left exactly as it was, the step is reported as pending, and it is retried at
the next session start. The old flags for delegating a profile file no longer exist.

## Sending always needs you present

`gmail_send_message`, `gmail_reply` and `gmail_forward` are marked so that Claude Code asks you
to approve **each call**, even when permissions are otherwise pre-approved. Where no person
can answer (`dontAsk` mode, a headless run), the send is **refused, not sent**. A Claude Desktop
scheduled task is not confirmed either way yet, so do not rely on a scheduled task being able to
send. Drafts are unaffected, so unattended work can still leave a draft in `[Gmail]/Drafts` for
you to send yourself. The approval prompt needs Claude Code v2.1.214 or later; an older client
is expected to ignore the marker and apply its ordinary permission handling.

## Agents

One agent and one skill ship with the connector, for work that spans several accounts:

- `mail-reader` searches and reads across your accounts and hands back a short digest, so the
  raw mail stays out of your conversation. It has read-only tools and cannot draft or send.
- the `coordinator` skill checks which accounts are registered and reachable, then routes:
  reading to `mail-reader`; drafting and sending stay in your own session, where you approve
  them.

## The rule the design serves

**A missing thing must never read as an empty thing.** An unconfigured server refuses
loudly and names the fix; an account that cannot be searched makes the result say
`INCOMPLETE COVERAGE` and name the account — a result set is never silently partial,
because "no matches in half your mail" is indistinguishable from "no matches".

## Tools

Read/draft: `gmail_accounts` · `gmail_search` · `gmail_get_message` ·
`gmail_get_attachment` · `gmail_create_draft`. Send: `gmail_send_message` ·
`gmail_reply` · `gmail_forward` — see the schemas in `scripts/gmail_mcp_server.py`.

Python 3.9+, standard library only. Deployment surface support: `docs/deployment.md` in the
source repository (a maintenance artifact — an installed copy does not carry it).
