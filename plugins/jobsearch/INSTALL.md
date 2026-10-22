# Installing jobsearch as a plugin

The engine is laid out as a Claude Code plugin: `.claude-plugin/plugin.json`, `agents/`, `skills/`,
`scripts/`, `tasks/`, `docs/`. Skills invoke their own code as
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/…"`, so the engine works from wherever it is installed.

## The two roots, and why they are different

| | resolves to | used for |
|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | where the plugin is installed | the engine's own scripts, schemas, prompts |
| **profile root** | **your working directory** (walk up to `config.json`/`data/`), or `CLAUDESEARCH_ROOT` | your resume, config, pipeline, history |

**They are never the same directory under a plugin install.** `scripts/_root.py` enforces the
split. Conflating them does not raise — it silently reads an empty profile and reports it as fact.
That is what emptied a real dashboard on 2026-08-05.

**So: always run from your search directory.** The engine finds you; you do not point at it.

## Install

Add this repository as a marketplace in Claude Code, then install the plugin from it. Use the
`/plugin` command in an interactive session — plugin installation is an app-level action, not a
repo change, and nothing should edit `~/.claude/plugins/known_marketplaces.json` by hand.

⭐ **That gets you a `directory` source, which is valid on exactly one machine.** It is the right
thing for developing the plugin and the wrong thing for using it from another clone on another
*local* machine, where the symptom is `Unknown command` for a correctly-spelled skill, with no error.
For another local machine, declare the marketplace as a **`github` source in your own repo's
`.claude/settings.json`** — see [Install](../../README.md#install). A **private** repository
additionally needs authentication on that machine.

**Where this plugin runs.** On your own machine only: the Claude Code Desktop app (including its
scheduled tasks) or `claude` interactively in a terminal on any operating system, with a phone able to
drive such a session through Remote Control. **Not supported:** `claude -p` and the Agent SDK, and Claude
Code on the web or any cloud session. Nothing refuses to start there; it is unsupported by
documentation. A cloud session does not install the plugins a repository declares, so declaring the
marketplace for one does not make it work, and a "container" install is not a supported route. LinkedIn
additionally needs a signed-in desktop browser. See the README's *Where this runs* and
[How it works — What needs a desktop](../../docs/user/jobsearch/how-it-works.md#what-needs-a-desktop).

**Mods.** The status pane and the review panes come from the plugin's mod, which needs Claude Code 2.1.287 (CLI)
or 2.1.286 (Desktop) or later. Without it (an older version, `disableAllHooks`, or an organisation that allows
only managed mods) everything still works: `/jobsearch:status`, `/jobsearch:review-resume` and
`/jobsearch:review-linkedin` print as text.

## Install the rulebook into your profile

A plugin cannot ship project context: Claude Code loads `CLAUDE.md` from the working directory,
which is your profile, never the plugin. The rulebook therefore ships as a template —
[`RULEBOOK.md`](RULEBOOK.md) at the plugin root — and reaches your sessions only as an installed
copy. From your search directory:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_rulebook.py"           # installs it as CLAUDE.md
    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_rulebook.py" --check   # is my copy current?

The copy carries a provenance stamp naming the engine version it came from; `--check` reports
MISSING / UNMANAGED / STALE / OK. **Edit the plugin's `RULEBOOK.md`, never the installed copy** —
a re-run overwrites it. A missing rulebook fails silently (the session simply starts without
rules), which is why `--check` exists; a stale one is worse, because it is read as authoritative.

## Multi-profile (an agency running several searches)

`CLAUDESEARCH_ROOT` selects the profile explicitly, so one engine serves many:

    CLAUDESEARCH_ROOT=~/clients/alice python3 "$ENGINE/scripts/coordinator.py"
    CLAUDESEARCH_ROOT=~/clients/bob   python3 "$ENGINE/scripts/coordinator.py"

⚠️ **Cross-profile contamination is the safety-critical risk in that mode.** The drafting agents
read "the candidate's" resume; with several profiles a root bug puts one person's history into
another person's cover letter. That needs a gate before the agency case is supported for real.

## Mail comes from the `gmail-multi` connector, installed for you

`jobsearch` does not declare its own Gmail MCP server. `plugin.json` names `gmail-multi` under
`metadata.connectors`, and a `SessionStart` hook installs it from the same marketplace `jobsearch`
came from the first time it is missing — you do not add it and do not hand-write a `.mcp.json`.
That connector is what searches, reads, and drafts across your mailboxes, and it **can also send,
reply, and forward** — capability the connector deliberately carries so it works like any
general-purpose mail tool for anyone who installs it on its own.

**`jobsearch` itself still never sends.** It only ever creates drafts for you to review and send
yourself. Until 2026-08-22 that was guaranteed by the connector having no send tools at all; now
that the connector can send, `jobsearch` enforces draft-only as a **policy**: a `PreToolUse` hook
(`scripts/guard_mail_send.py`) denies the connector's send/reply/forward tools for the whole
session while `jobsearch` is loaded, and fails closed (denies) if it cannot even read the request.
That is a review control on the tools this plugin routes mail through, not a sandbox around every
way mail could leave your machine — it does not, for example, stop a shell command from sending
mail some other way. Full per-surface detail (where the deny is measured live, where it holds only
because the tools themselves are absent, and the one surface — a server-side `claude.ai` install —
where it should be assumed **not** in force) is recorded in the plugin's surface matrix, "The mail-send guard" section — a maintenance
document kept in the marketplace repository rather than shipped with the plugin, so it is not
in your installed copy.

**Credentials are yours.** Both plugins read them from your OS keychain (service
`claudesearch-imap`), keyed by mailbox address. There is no fallback account: if `user.json` is
missing or malformed, mail commands fail loudly rather than guessing, because silently reading
someone else's mailbox is never the wanted behaviour.

⚠️ **Claude Code will ask you to approve the connector's MCP server the first time.** Approve it
for the project, **not** "all future MCP servers" — it is externally sourced, and a blanket
approval would let a future update register a server without asking you.

**If you are upgrading from a version older than 0.31.0:** the plugin's own vendored copy of the
mail-reading code, `scripts/gmail_mcp_server.py`, was renamed to `scripts/mail_client.py` (it now
carries only the handful of read-only functions the plugin's automated sweeps use — no send path
in it, then or now). Migration `m_0_31_0_mail_client_rename` runs itself at session start and
repoints any reference to the old filename in your profile's own incident archive; nothing for you
to run by hand.
