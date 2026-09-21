# gmail-multi — a multi-account Gmail connector

The managed Gmail connector OAuth-binds to **one** Google account. This plugin covers
**all of yours in a single query** over IMAP: every search runs across every configured
account, every result is tagged with the mailbox it came from, attachments actually
download, drafts land in `[Gmail]/Drafts`, and it can **send, reply, and forward** from
whichever account you name, over SMTP with the same app password IMAP already uses.

Standalone by design — it needs no other plugin and no profile directory. Other plugins
in this marketplace (jobsearch) consume its mechanisms, but nothing about it assumes a
job search, and there is no platform dependency between them: jobsearch names it as
metadata and installs it for you the first time it is missing.

**A consumer that must not send enforces that itself.** jobsearch, for example, is
draft-only by an explicit review policy: it denies this connector's send/reply/forward
tools with its own `PreToolUse` guard for the whole session it is loaded in, and fails
closed if it cannot even read the request. That guard is jobsearch's, not this
connector's — this connector sends on request from whoever is driving it, the same as
any general-purpose mail tool.

**Every send outcome states what is known to have been delivered** — sent, not sent, or
unknown — so nothing downstream is tempted into a blind retry after an ambiguous
failure. One gap is open and tracked (issue #219): a connection lost right after the
message is handed to the server leaves delivery genuinely unknown, and the tool does not
yet say so explicitly.

## Setup

1. Install the plugin. Then, in a session: `/gmail-multi:accounts`, or directly:

   ```bash
   python3 scripts/accounts.py --add you@example.com
   python3 scripts/accounts.py --status
   ```

2. `--status` prints the exact command to store each account's **app password** in your
   OS credential store (Keychain / PasswordVault / secret-service). **You** run that
   command; the plugin never accepts, stores, prints, or logs a secret, and Claude never
   sees one. Use an app password, never the account password — 2-Step Verification must
   be on.

`accounts.json` is **one file per machine**. Every address in `accounts` and every file
in `include` is searched by every `gmail_search` that omits `account` — including a
second consumer's, or a second profile's, on the same machine. A consumer plugin
delegates its list through `include` instead of copying addresses; to scope a call to
one mailbox, pass `account=<address>`. `gmail_accounts` shows where each address came
from.

## Who reads which mailbox

There is no server-side scope: whatever is in `accounts.json` — every literal address
plus everything every `include` file adds — is what a call with `account` unset or
`account="all"` searches, machine-wide, regardless of which plugin or profile is asking.
Scoping is the **caller's** job, not the connector's:

- Two profiles on one machine (say `acct-a@example.com` and `acct-b@example.com`, each
  added by its own consumer's setup) each keep their own address in `include` — nobody's
  address is ever removed to scope someone else — and each profile's own calls pass
  `account=<its own address>`, one call per address.
- jobsearch enforces this for itself with a `PreToolUse` guard
  (`plugins/jobsearch/scripts/guard_mail_scope.py`) that denies any mailbox-reading call
  whose `account` is not exactly one of that profile's own addresses, and prints the list
  when it denies. A consumer without such a guard is trusting its own text to pass
  `account` correctly — `all` will otherwise return every profile's mail on that machine.
- `gmail_accounts` always shows the full resolved list with provenance, so a "why did I
  get someone else's mail" question is answerable by running it, not by reading source.

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
