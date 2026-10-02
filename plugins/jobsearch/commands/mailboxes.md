---
argument-hint: "[add <address> | check]"
description: Configure which mail accounts the job search reads, check that each one can actually be searched, and show or switch which Gmail connector the search uses (gmail-multi or the claude.ai Gmail connector).
---

# Mailboxes

Show what is configured and what works:

```bash
~/.claude/jobsearch/run mailboxes.py --status
```

Add or remove an address (`$ARGUMENTS` may name one):

```bash
~/.claude/jobsearch/run mailboxes.py --add you@work.com
~/.claude/jobsearch/run mailboxes.py --remove old@example.com
```

## Which connector the search uses — show it, and how to switch

The search reads mail through **one** Gmail connector, chosen by `config.json`'s `communications.mail_connector`:

| value | what it means |
|---|---|
| `gmail-multi` (the default) | the `gmail-multi` plugin's tools, over the addresses listed above |
| `claude-gmail` | the claude.ai-managed Gmail connector: one account, the one you signed in to claude.ai with |

`--status` prints the current selection first, before the accounts. **Relay it in plain words**:
"jobsearch is reading mail through <connector>". A profile that never set the key reads
`gmail-multi`, which is how every profile behaved before the key existed.

To switch, the user sets `communications.mail_connector` in `config.json` to the other value. **Do not edit
`config.json` for them unprompted**; say which value they are asking for and make the change only
when they say so. Any other value is refused loudly, never read as the default, and the message
names the two valid ones.

⚠️ **Choosing a connector turns the other one off for the search.** A guard denies the unselected
connector's mail tools and says which connector is selected and how to change it, so a call that
reaches for the wrong one fails with an explanation rather than quietly reading a mailbox the user
did not pick. The scheduled sweeps that read mail directly (`alert_sweep.py`, `meeting_check.py`,
`reconcile.py --ats`, `check_followups.py`) run only under `gmail-multi`; under `claude-gmail` each one
skips with one line saying so. The addresses and app passwords on this page matter for
`gmail-multi` only.

## What to tell the user

Run `--status` and relay what it prints. **Two separate things have to be true for an account to
be searchable**, and the report distinguishes them:

1. **The address is in `user.json`** — that is what makes it part of the search.
2. **An app password is in the OS credential store** — that is what makes it reachable.

⭐ **An account with only the first is worse than one with neither**, because the search runs,
finds nothing, and reports a quiet inbox. On 2026-08-05 the MCP server resolved zero mailboxes and
reported "no new mail" for an entire run. **Never let a missing credential read as "nothing
arrived."**

## ⛔ NEVER HANDLE THE PASSWORD YOURSELF

`--status` prints the exact command for the platform it is running on. **The user runs it; you do
not.** Do not ask them to paste a password into the chat, do not put one in a command you run, and
do not offer to store it for them. A password in a CLI argument is in shell history and the process
table; a password in a chat is in a transcript. Both are worse than the provider's own page.

There is deliberately no `--set` flag. If asked to add one, say why it does not exist.

## Platform notes

| Platform | Store | Needs installing? |
|---|---|---|
| macOS | Keychain (`security`) | No |
| Windows | Credential Manager / PasswordVault, via PowerShell | No — Windows 10+. Use PowerShell, not `cmd` |
| Linux | secret-service (`secret-tool`) | Yes — `libsecret-tools` |

⚠️ **Native Windows: the credential store works, but the rest of the plugin is not yet an
audited surface.** The launcher every skill calls is POSIX `sh`
(`install_launcher.py`), and `docs/deployment.md` has no Windows row —
so a credential stored on native Windows is parked where nothing can yet use it. **Say this
BEFORE the user stores anything, not after.** The supported path today is WSL (which presents
as Linux, secret-service store); opening a native Windows surface is an owner decision tracked
in deployment.md.

⚠️ **It must be an APP PASSWORD, not the account password.** With 2FA on — which it should be —
the account password will not work over IMAP at all. An app password is also revocable on its own
and cannot change account recovery settings. For Google, 2-Step Verification must be ON before the
app-password page will appear; for Workspace accounts an admin must also leave IMAP enabled.

`--status` prints the right provider link for each address it finds.
