#!/usr/bin/env python3
"""PreToolUse guard: DENY the gmail-multi connector's send-family tools. jobsearch is
draft-only, and that is now a POLICY, so this file is where it is enforced.

⭐ WHY THIS EXISTS (marketplace #213, owner decision 2026-08-21)
----------------------------------------------------------------
Until 2026-08-22 "jobsearch never sends" was guaranteed by CAPABILITY ABSENCE: the
gmail-multi connector had zero send tools and no SMTP path, so there was nothing to
misuse. The owner then decided the connector should send/reply/forward like any
general-purpose mail connector — capability belongs to the connector — while jobsearch
must keep drafting and never sending, as an explicit review control the owner may relax
later. That inverts the safety story: absence became policy, and policy is strictly
weaker unless it is enforced mechanically and has failed on purpose. This guard is the
enforcement; `test_checks.py` holds the induced-failure evidence.

MEASURED, NOT ASSUMED (2026-08-22, CLI 2.1.231, disposable --plugin-dir session)
--------------------------------------------------------------------------------
A PreToolUse hook registered by THIS plugin's hooks.json fires on a tool served by a
DIFFERENT plugin's MCP server: the probe hook intercepted and blocked
`mcp__plugin_gmail-multi_gmail-multi__gmail_accounts`. That run also measured the
naming scheme for plugin-served MCP tools — `mcp__plugin_<plugin>_<server>__<tool>` —
which is what GUARDED_MAIL_SEND_TOOLS encodes. The bare `mcp__gmail-multi__<tool>`
spellings are included as well, for a user who wires the same server through a manual
`.mcp.json` instead of the plugin manifest.

## The test, stated once

    tool_name is one of GUARDED_MAIL_SEND_TOOLS  -> DENY (exit 2, reason on stderr)
    tool_name is anything else                   -> ALLOW (exit 0) — defensive; the
                                                    matcher should never route it here
    payload unreadable / tool_name absent        -> DENY (exit 2)

⚠️ The unreadable-payload branch FAILS CLOSED, deliberately — the opposite of
`guard_outbound_click.py`. That guard must CLASSIFY an ambiguous click, and a wrong
deny there blocks legitimate work, so it fails open and says so. This guard performs no
classification: `hooks.json`'s matcher (gated equal to GUARDED_MAIL_SEND_TOOLS by
`check_mail_guard_matcher.py`) is the classifier, so the only way this script runs at
all is that a send-family tool was called. A payload we cannot parse changes nothing
about that, and the least reversible act in the system does not get the benefit of a
parsing doubt.

## SCOPE — this deny binds EVERY session where jobsearch is loaded. Decided, not drifted.

A hook cannot tell whether a given send is "job-search work"; attribution is not
mechanically decidable, and for the least reversible act ambiguity must fail closed
(the same posture as guard_outbound_click's verb match). So the deny is unconditional
while jobsearch is loaded — including a session where the user wants gmail-multi's send
tools for unrelated mail. The named remedy for that user is real and per-project:
disable jobsearch where mail is not job-search work (`claude plugin disable jobsearch`,
or scope jobsearch's enablement to the profile project, which is how the owner runs
it). There is deliberately NO in-band override — no profile flag, no env var — because
any switch this process reads is a switch a confident mid-task session can flip; the
owner's future relaxation ships as an engine version change, reviewed, like every other
behaviour change (rulebook: a change ships as a version, never as an instruction).

## WHAT THIS DOES NOT COVER — state it, don't let a reader assume more than what's here

- **The claude.ai-managed Gmail connector.** Its server name is a per-user UUID
  (`mcp__<uuid>__send_message`), which a shipped matcher cannot enumerate. If that
  connector is attached, its send tools are NOT guarded here.
- **Any other mail-capable tool the user installs.** Same reason as the click guard:
  a shipped matcher covers the surfaces this plugin routes to, nothing more.
- **The sweeps' own IMAP library (`mail_client.py`).** It has no send code at all —
  capability absence still guards the deterministic path; this guard exists for the
  model-invoked path, which is where the capability now lives.
- **S6 (the server-side claude.ai install — docs/surfaces.md).** Whether hooks execute there is
  UNVERIFIED (same standing caveat as guard_outbound_click). The behavioural rule in
  the plugin description — "It never sends anything itself" — remains the first line.

⭐⭐ THE CONNECTOR ENTRY (`--connector`, dev #799, design-mail-any-connector.md §5.1, §14 R2-M1, M5)
----------------------------------------------------------------------------------------------
jobsearch can now read mail through the claude.ai Gmail, Microsoft 365, Fastmail and Superhuman
connectors, and each of them can send. A second PreToolUse entry runs this script with `--connector`
and denies their send-family tools. It is a DIFFERENT shape from the gmail-multi entry above, which
is untouched:
  * UNCONDITIONAL while jobsearch is loaded. It resolves no profile and imports nothing from
    jobsearch (the name tuples below are literals, pinned equal to `mail_connectors.py` by test), so
    no ImportError and no unresolved profile can open it. The remembered-profile pointer made a
    "profile-scoped" deny apply machine-wide anyway; resolving a profile also adds an
    exception-to-allow path to the least reversible act.
  * ANY EXCEPTION EXITS 2. `_main_connector` wraps everything in `except BaseException`.
  * Routing is `CONNECTOR_SEND_MATCHER`, a deliberately OVER-routing regex (it fires for any MCP tool
    whose name carries a send-family verb, in any case). The Python floor below is the ONLY
    classifier. `check_mail_guard_matcher.py` holds the invariant that matters, as a PROPERTY: for a
    generated population of names, `floor denies => matcher routes`, with the matcher evaluated
    through `node` because Claude Code evaluates it as JavaScript.
  * A tool is denied only on a CONNECTOR-SHAPED server (`mcp_server.source == "claudeai"`, a UUID,
    a `claude_ai_` prefix, or a hint token such as `outlook` / `fastmail` / `superhuman` / `gmail` /
    `microsoft` / `m365` in the name, case-insensitive; each test only ever ADDS a server) when it
    is (a) a published send name, or (b) the mail-send FLOOR: a mail token together with a send,
    forward, reply (with no draft), or filter/rule-write token, case-insensitive, split on `_`, `-`
    and camelCase.

The cost, for every installer: this fires wherever jobsearch is enabled — the profile project on a
project-scope install, EVERY session on the machine on a user-scope install. There, no claude.ai mail
connector can send, reply, forward, unsubscribe or set mail rules, Superhuman and Fastmail cannot
create events, and any connector tool named exactly `send_message`, `reply` or `forward` is denied
whatever its product. The remedy is the same as above: disable jobsearch for that project or install
it at project scope. S6 (server-side claude.ai install): whether plugin hooks run there is UNVERIFIED;
if they do, the deny applies to every S6 session on the account.

NOT CLAIMED, stated rather than left for a reader to assume (design §5.2, §14 M5):
  * PLATFORM ROUTING IS UNVERIFIED: the verdict function and the matcher strings are TESTED; nobody
    has measured whether Claude Code routes an `sdk` or `claude_ai_` connector call to the hook, or
    whether exit 2 blocks it there (probe P3). "Script and matcher TESTED, platform routing
    UNVERIFIED."
  * THREE FAIL-OPEN RESIDUALS. The platform documents that a hook which does not start or exits with
    a code other than 0 or 2 is a NON-blocking error, and that a timed-out PreToolUse hook does not
    block. So a SYNTAX ERROR in this file (exit 1), a missing `python3` (127) and a HOOK TIMEOUT all
    let the call through. `hooks.json` sets `"onFailure": "block"` on this entry, which the hooks page
    documents ("whether the action that triggered the hook goes ahead when the hook fails", v2.1.295
    or later); on an older Claude Code the field does nothing and the three residuals are open. The
    SessionStart selftest (also `guard_mail_scope.py --selftest`, which compiles this file) warns
    about a syntax error, and nothing can warn about a missing interpreter from inside one.
  * A mail write tool whose name carries no mail token and is not a published name, for example a
    Microsoft 365 write tool named only `send` on a server that is neither UUID- nor `claude_ai_`-
    shaped and has no hint token.
  * A name that runs THREE OR MORE words together with no separator and no case change
    (`OUTLOOKSENDMAIL` in any case): the matcher routes it, but the floor sees one token. Two
    words run together (`SENDMAIL`, `EMAILSEND`) are expanded and denied.
  * A server that is not connector-shaped (no UUID, no `claude_ai_`, no hint token, no
    `source: "claudeai"`) AND whose tool is not a published send name is left alone.

Protocol: PreToolUse stdin is the hook payload; exit 2 blocks and stderr is shown to
the model. `--selftest` (run from SessionStart) proves the deny and allow branches
against synthetic payloads, so a syntax error or interpreter problem in this file is
LOUD at session start instead of silently letting sends through.

Python 3.9+, standard library only.
"""

import json
import re
import sys

# ⭐ SINGLE SOURCE OF TRUTH for what is guarded. hooks.json's PreToolUse matcher for this
# script must equal "|".join(GUARDED_MAIL_SEND_TOOLS) exactly — check_mail_guard_matcher.py
# asserts that, in CI and inside the materialized shipped package. A send-family tool added
# to the connector without extending this tuple is caught by
# TestMailGuardCoversConnectorSendFamily in test_checks.py.
GUARDED_MAIL_SEND_TOOLS = (
    # measured plugin-served spelling: mcp__plugin_<plugin>_<server>__<tool>
    "mcp__plugin_gmail-multi_gmail-multi__gmail_send_message",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_reply",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_forward",
    # manual .mcp.json spelling of the same server
    "mcp__gmail-multi__gmail_send_message",
    "mcp__gmail-multi__gmail_reply",
    "mcp__gmail-multi__gmail_forward",
)

DENY_MESSAGE = """\
BLOCKED — jobsearch is draft-only, by the owner's explicit review policy (marketplace
#213). While the jobsearch plugin is loaded, the gmail-multi send/reply/forward tools
are denied so that nothing is ever sent under the candidate's identity without their
own hands on it.

What to do instead:
  * Draft it: gmail_create_draft (with reply_to_uid to thread a reply). The user
    reviews and sends it from Gmail themselves.
  * Not doing job-search work? Disable jobsearch for this project
    (`claude plugin disable jobsearch`) and the guard goes with it.

This is a policy of the jobsearch plugin, not of the gmail-multi connector. Relaxing it
is an engine change, not something to work around mid-session.
"""


def evaluate(payload):
    """Returns (deny, reason). Unreadable payloads deny — see the module docstring."""
    if not isinstance(payload, dict):
        return True, "hook payload unreadable — failing CLOSED for a send-family matcher hit"
    name = payload.get("tool_name")
    if not name:
        return True, "hook payload carries no tool_name — failing CLOSED"
    if name in GUARDED_MAIL_SEND_TOOLS:
        return True, "tool %s is send-family" % name
    return False, "tool %s is not in GUARDED_MAIL_SEND_TOOLS" % name


# ── the connector entry (dev #799) ───────────────────────────────────────────────────────────────
# Literals, never imported: this entry must not be able to fail to import. Pinned equal to the
# connector table (`mail_connectors.py`) by test.

# (a) the published send / outbound names (exact tool name, compared case-insensitively). Gmail:
# send_message, reply, forward, create_filter. Superhuman: send_draft, undo_send, unsubscribe,
# create_or_update_event. Fastmail: compose_event. The two event writes are here because an event
# with attendees sends invitations from the user's identity.
CONNECTOR_PUBLISHED_SEND_NAMES = (
    "send_message", "reply", "forward", "create_filter",
    "send_draft", "undo_send", "unsubscribe", "create_or_update_event",
    "compose_event",
)

# (b) the mail send FLOOR (OURS): the fail-closed answer for the write names no connector publishes.
# `gmail` is a mail token here although design §5.1 does not list it: `gmail_send_message` carries
# no other one, and adding a token only ever denies more.
FLOOR_MAIL_TOKENS = frozenset(("mail", "email", "emails", "outlook", "inbox", "gmail"))
FLOOR_SEND_TOKENS = frozenset(("send", "forward", "forwarding", "unsubscribe", "autoreply"))
FLOOR_REPLY_TOKENS = frozenset(("reply", "replies"))
FLOOR_DRAFT_TOKENS = frozenset(("draft", "drafts"))
FLOOR_RULE_TOKENS = frozenset(("filter", "filters", "rule", "rules"))
FLOOR_RULE_VERBS = frozenset(("create", "update", "set"))

# A server segment is CONNECTOR-SHAPED when any one of these holds (each only ever adds a server).
CONNECTOR_SERVER_HINTS = ("microsoft", "m365", "outlook", "fastmail", "superhuman", "gmail")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# The send-family verbs hooks.json's matcher routes on, and the matcher itself: ONE literal,
# JavaScript- and Python-compatible, no `(?` group, anchored `^mcp__`, then `.*`, then an
# alternation of the verbs with EVERY letter spelled as a case class, so any casing routes
# (`SENDMAIL`, `sEnd`, `send_Mail`). It over-routes on purpose: Python is spawned for an MCP tool
# whose name carries one of these verbs, never for every MCP call, and the floor above is the only
# classifier. `check_mail_guard_matcher.py` recomputes this string from CONNECTOR_SEND_VERBS and
# holds the PROPERTY (floor denies => matcher routes) through `node`.
# ⚠️ Design §14 R2-M1's example verb list lacked `unsubscribe`, `replies` and `event`, all of which
# the floor or the published names deny: the property gate would have been red on them, which is
# what it is for. They are here.
CONNECTOR_SEND_VERBS = ("send", "forward", "reply", "replies", "compose", "filter", "rule",
                        "draft", "unsubscribe", "event")
CONNECTOR_SEND_MATCHER = (
    "^mcp__.*([Ss][Ee][Nn][Dd]|[Ff][Oo][Rr][Ww][Aa][Rr][Dd]|[Rr][Ee][Pp][Ll][Yy]"
    "|[Rr][Ee][Pp][Ll][Ii][Ee][Ss]|[Cc][Oo][Mm][Pp][Oo][Ss][Ee]|[Ff][Ii][Ll][Tt][Ee][Rr]"
    "|[Rr][Uu][Ll][Ee]|[Dd][Rr][Aa][Ff][Tt]"
    "|[Uu][Nn][Ss][Uu][Bb][Ss][Cc][Rr][Ii][Bb][Ee]|[Ee][Vv][Ee][Nn][Tt])"
)

CONNECTOR_DENY_MESSAGE = """\
BLOCKED — jobsearch is draft-only, by the owner's explicit review policy. While the jobsearch
plugin is loaded, a mail connector's send / reply / forward / unsubscribe / mail-rule tools are
denied so that nothing is ever sent under the candidate's identity without their own hands on it.

What to do instead:
  * Draft it, if the connector offers a draft tool; the user reviews and sends it from their mail
    client themselves.
  * Not doing job-search work? Disable jobsearch for this project
    (`claude plugin disable jobsearch`) and the guard goes with it.

This is a policy of the jobsearch plugin, not of the connector. Relaxing it is an engine change,
not something to work around mid-session.
"""


def _splits(name):
    """Every (server, tool) reading of `mcp__<server>__<tool>`: one per `__` boundary, so a tool
    name that itself contains `__` cannot hide its server. [] when `name` is not an MCP tool name."""
    if not isinstance(name, str) or not name.startswith("mcp__"):
        return []
    rest = name[len("mcp__"):]
    out = []
    i = rest.find("__")
    while i != -1:
        out.append((rest[:i], rest[i + 2:]))
        i = rest.find("__", i + 1)
    return out


def connector_shaped(server, mcp_server=None):
    """True when `server` looks like a mail connector's. Tests only ever ADD a server."""
    if isinstance(mcp_server, dict) and mcp_server.get("source") == "claudeai":
        return True
    low = (server or "").lower()
    if _UUID_RE.match(server or ""):
        return True
    if low.startswith("claude_ai_"):
        return True
    return any(h in low for h in CONNECTOR_SERVER_HINTS)


def tool_tokens(tool):
    """Lower-case tokens of a tool name, split on any non-alphanumeric run (`_`, `-`, ...) and on
    camelCase boundaries. A token that is two vocabulary words run together (`SENDMAIL`,
    `EMAILSEND`) is ALSO expanded, because an all-caps or unseparated name has no boundary to split
    on. `get_senders` stays `get`, `senders`: a substring test would deny it."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", tool or "")
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if t]
    vocab = (FLOOR_SEND_TOKENS | FLOOR_REPLY_TOKENS | FLOOR_DRAFT_TOKENS | FLOOR_RULE_TOKENS)
    extra = []
    for t in tokens:
        for m in FLOOR_MAIL_TOKENS:
            if t.startswith(m) and t[len(m):] in vocab:
                extra += [m, t[len(m):]]
            if t.endswith(m) and t[:-len(m)] in vocab:
                extra += [m, t[:-len(m)]]
    return set(tokens) | set(extra)


def floor_reason(tool):
    """Why the mail send floor denies `tool`, or None. Pure and case-insensitive."""
    t = tool_tokens(tool)
    if not (t & FLOOR_MAIL_TOKENS):
        return None
    if t & FLOOR_SEND_TOKENS:
        return "mail token with a send-family token (%s)" % ", ".join(sorted(t & FLOOR_SEND_TOKENS))
    if (t & FLOOR_REPLY_TOKENS) and not (t & FLOOR_DRAFT_TOKENS):
        return "mail token with a reply token and no draft token"
    if (t & FLOOR_RULE_TOKENS) and (t & FLOOR_RULE_VERBS):
        return "mail token with a filter/rule write"
    return None


def evaluate_connector(payload):
    """(deny, reason) for the connector entry. No profile, no import, no file read."""
    if not isinstance(payload, dict):
        return True, "hook payload unreadable - failing CLOSED for a connector send matcher hit"
    name = payload.get("tool_name")
    if not name or not isinstance(name, str):
        return True, "hook payload carries no tool_name - failing CLOSED"
    mcp_server = payload.get("mcp_server")
    for server, tool in _splits(name):
        if not connector_shaped(server, mcp_server):
            continue
        if tool.lower() in CONNECTOR_PUBLISHED_SEND_NAMES:
            return True, "tool %s is a published connector send name (%s)" % (name, tool.lower())
        why = floor_reason(tool)
        if why:
            return True, "tool %s hits the mail send floor: %s" % (name, why)
    return False, "tool %s is not a connector send tool" % name


def floor_denies(name, mcp_server=None):
    """The property gate's handle on the verdict: does the connector entry deny `name`?"""
    return evaluate_connector({"tool_name": name, "mcp_server": mcp_server})[0]


def _connector_selftest():
    """Proves the connector entry's branches against synthetic payloads. Loud, never blocking
    startup, and never lets its own exception escape as a silent pass."""
    failures = []
    try:
        uuid = "0a1b2c3d-0000-4000-8000-000000000000"
        for name in ("mcp__%s__send_message" % uuid, "mcp__%s__outlook_send_mail" % uuid,
                     "mcp__claude_ai_Gmail__reply", "mcp__outlook-work__sendMail",
                     "mcp__%s__send-email" % uuid, "mcp__%s__Send_Mail" % uuid,
                     "mcp__%s__unsubscribe" % uuid, "mcp__%s__compose_event" % uuid):
            if not evaluate_connector({"tool_name": name})[0]:
                failures.append("did not deny %s" % name)
        for name in ("mcp__%s__create_reply_draft" % uuid, "mcp__%s__get_senders" % uuid,
                     "mcp__%s__slack_send_message" % uuid, "mcp__%s__search_threads" % uuid,
                     "mcp__ccd_session_mgmt__send_message"):
            if evaluate_connector({"tool_name": name})[0]:
                failures.append("denied %s" % name)
        if not evaluate_connector(None)[0]:
            failures.append("unreadable payload did not deny")
        if not (CONNECTOR_SEND_MATCHER.startswith("^mcp__") and "(?" not in CONNECTOR_SEND_MATCHER):
            failures.append("CONNECTOR_SEND_MATCHER is not a plain anchored regex")
        elif not re.search(CONNECTOR_SEND_MATCHER, "mcp__%s__send_message" % uuid):
            failures.append("CONNECTOR_SEND_MATCHER does not route send_message")
    except BaseException as exc:                          # noqa: BLE001 - a broken selftest is a loud one
        failures = ["selftest raised %s: %s" % (type(exc).__name__, exc)]
    if failures:
        print(json.dumps({"systemMessage":
                          "guard_mail_send --connector SELFTEST FAILED (%s) - the draft-only "
                          "guard for claude.ai mail connectors may be inert; treat connector "
                          "sends as unguarded this session." % "; ".join(failures)}))
    return 0


def _main_connector(args):
    """The connector entry. ANY exception exits 2 (deny): this is the least reversible act, and an
    unexpected failure is not a reason to let it through."""
    if "--selftest" in args:
        return _connector_selftest()
    try:
        try:
            payload = json.load(sys.stdin)
        except Exception:                                 # noqa: BLE001
            payload = None
        deny, reason = evaluate_connector(payload)
        if deny:
            sys.stderr.write(CONNECTOR_DENY_MESSAGE + "\n[guard_mail_send --connector: %s]\n" % reason)
            return 2
        return 0
    except BaseException as exc:                          # noqa: BLE001 - fail CLOSED
        try:
            sys.stderr.write("BLOCKED - guard_mail_send --connector failed (%s: %s); failing CLOSED.\n"
                             % (type(exc).__name__, exc))
        except BaseException:                             # noqa: BLE001
            pass
        return 2


def selftest():
    """Prove both branches against synthetic payloads. Loud, never blocking startup."""
    failures = []
    deny, _ = evaluate({"tool_name": GUARDED_MAIL_SEND_TOOLS[0]})
    if not deny:
        failures.append("send tool did not deny")
    deny, _ = evaluate({"tool_name": "mcp__plugin_gmail-multi_gmail-multi__gmail_search"})
    if deny:
        failures.append("read tool denied")
    deny, _ = evaluate(None)
    if not deny:
        failures.append("unreadable payload did not deny")
    if failures:
        print(json.dumps({"systemMessage":
                          "guard_mail_send SELFTEST FAILED (%s) — the draft-only guard "
                          "may be inert; treat sends as unguarded this session."
                          % "; ".join(failures)}))
        return 0  # never block startup; the message is the point
    return 0


def main():
    if "--connector" in sys.argv[1:]:
        return _main_connector(sys.argv[1:])
    if "--selftest" in sys.argv[1:]:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    deny, reason = evaluate(payload)
    if deny:
        sys.stderr.write(DENY_MESSAGE + "\n[guard_mail_send: %s]\n" % reason)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
