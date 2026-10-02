#!/usr/bin/env python3
"""PreToolUse guard: DENY a gmail-multi mailbox call whose `account` is not exactly one of
THIS PROFILE's own addresses. jobsearch never searches the machine's union.

⭐ WHY THIS EXISTS (design-manifest-heal.md § The boundary, item 1)
--------------------------------------------------------------------
`~/.claude/gmail-multi/accounts.json` is ONE FILE PER MACHINE — `m_0_29_0` appends every
profile's `user.json` to its `include` list and never removes one, and
`gmail_mcp_server._accounts_from_config()` unions every `accounts` literal and every include
into one list on every call. So `resolve_accounts(None)` / `resolve_accounts("all")` return
EVERY profile's mailboxes on that machine — two profile directories on one machine each get
both profiles' mail from any `gmail_search` that omits `account`. The deterministic sweeps
(`mail_client.py`) are not leaky: every sweep passes `account=<address>` per mailbox already.
The leak is confined to the interactive MCP path, and to what the model is told to type —
this hook is what makes "type `account=<address>`" a MECHANICAL requirement rather than a
convention the model can forget.

## The decision, in order (never re-ordered without re-reading this docstring)

    payload unreadable, or tool_name absent          -> DENY  (fail closed)
    tool_name not one of the four guarded tools      -> ALLOW (defensive; hooks.json's matcher
                                                         should never route anything else here)
    `tool_input` key ABSENT from the payload         -> ALLOW, + one `guard-blind` diag row
                                                         (r3, #67 — see below)
    no profile resolves from this hook's cwd         -> ALLOW, silently (nothing to scope to)
    profile resolves, but its mailbox list is        -> DENY, naming /jobsearch:mailboxes
      empty or unreadable
    tool_input.account absent, empty, or "all"       -> DENY, printing the address list
    tool_input.account present but not EXACTLY one   -> DENY, same message (no prefix match —
      of the profile's own addresses                    a prefix can collide with another
                                                         profile's address on a second domain)
    exact member                                     -> ALLOW

⭐⭐ #67 — `tool_input` DELIVERY WAS UNMEASURED, SO THIS GUARD MEASURES IT ITSELF. No code in
this tree had ever captured an argument arriving on a gmail-multi-served tool before this file
(`guard_mail_send.py` denies by `tool_name` alone and never looks at `tool_input`;
`guard_outbound_click.py` reads `tool_input` only for Claude Code's own browser tools). Rather
than a person measuring it once by hand, this guard measures it on every build it runs on:
`tool_input` ABSENT from the payload (the key is missing from the JSON object — a PRESENT
`tool_input` with no `account` inside it is the ordinary "unset" deny above, never blindness)
means this guard cannot see the argument at all on this build, and it fails OPEN — the
alternative, fail-closed, kills every mailbox read (the daily inbox scan) until the next
release for a hypothetical this guard cannot even confirm — plus writes ONE `guard-blind` diag
row, once per session (a flag under the profile's state dir, `drift_guard.py`'s own shape),
so the blindness is a queryable fact rather than an unmeasured assumption. The connector-side
fallback if that row ever appears on a real machine is recorded in design-manifest-heal.md
§ The boundary, item 2, decided now and built only if the row shows up.

⭐⭐ THE SELECTED MAIL CONNECTOR (dev #161, dev #524) — the same script ALSO enforces which connector
---------------------------------------------------------------------------------------------------
`config.json` `communications.mail_connector` is `gmail-multi` (default) or `claude-gmail` (the
claude.ai-managed Gmail connector). jobsearch ADHERES to the selection, enforced here, not advised:
this guard DENIES the UNSELECTED connector's mail tools, with a message that names the selection and
how to change it. Under `gmail-multi` it denies the claude.ai connector's tools; under `claude-gmail`
it denies gmail-multi's. The claude.ai connector's server name is a per-user UUID on desktop
(`mcp__<uuid>__search_threads`) and `mcp__claude_ai_Gmail__*` elsewhere, so it is matched by an
ANCHORED tool-name suffix under any server name, limited to that connector's own tool names — a
non-mail tool from another UUID-named connector (`mcp__<uuid>__search_files`) is never touched.
hooks.json routes it through a SECOND PreToolUse entry whose matcher is a regular expression (any
matcher with a character outside letters/digits/`_`/`-`/`,`/`|` is a JavaScript regex, unanchored —
code.claude.com/docs/en/hooks): `CONNECTOR_MATCHER` below, which `check_mail_scope_guard_matcher.py`
holds equal to the guard's own tuples AND runs against sample tool names. That entry passes
`--connector` and enforces ONLY the selection; the original exact-string entry keeps the
per-address scoping for gmail-multi UNCHANGED (and also checks the selection for its four tools).
⚠️ The claude.ai connector's tool names below are a LEAD, not an observation (UNDETERMINED in
docs/groups/mail-connector-selection.md): pin them to what a session with the connector enabled
actually lists. Several are generic, so ANOTHER UUID-named connector that exposes the same tool
name is treated the same way — the one limit of matching by name (documented in deployment.md).
No profile resolves from the hook's cwd -> the connector selection is not enforced (nothing to
select for), the same posture as the per-address scope.

Protocol: PreToolUse stdin is the hook payload; exit 2 blocks and stderr is shown to the model.
`--selftest` (run from SessionStart) proves every branch against synthetic payloads and a
synthetic profile — never a real one — so a syntax error or interpreter problem here is LOUD
at session start instead of silently letting an unscoped search through.

Python 3.9+, standard library only.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ⭐ SINGLE SOURCE OF TRUTH for what is guarded — hooks.json's PreToolUse matcher for this
# script must equal "|".join(GUARDED_MAIL_SCOPE_TOOLS) exactly (check_mail_scope_guard_matcher.py
# asserts that, in CI and inside the materialized shipped package, the same shape
# check_mail_guard_matcher.py already holds for GUARDED_MAIL_SEND_TOOLS). The three send tools
# are already denied outright by guard_mail_send.py; gmail_accounts reads no mailbox and is
# deliberately NOT in this tuple — it stays allowed.
GUARDED_MAIL_SCOPE_TOOLS = (
    # measured plugin-served spelling: mcp__plugin_<plugin>_<server>__<tool>
    "mcp__plugin_gmail-multi_gmail-multi__gmail_search",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_get_message",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_get_attachment",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_create_draft",
    # manual .mcp.json spelling of the same server
    "mcp__gmail-multi__gmail_search",
    "mcp__gmail-multi__gmail_get_message",
    "mcp__gmail-multi__gmail_get_attachment",
    "mcp__gmail-multi__gmail_create_draft",
)


# ⭐ dev #161 — THE TWO CONNECTORS' MAIL TOOLS, by name. Single source of truth for BOTH this guard's
# classification and hooks.json's second matcher (`CONNECTOR_MATCHER`, built from these, gated equal by
# check_mail_scope_guard_matcher.py). The key name is spelled out here rather than imported so a hook
# that cannot import config_keys still tells the user what to edit; a test pins it equal to
# config_keys.MAIL_CONNECTOR.
MAIL_CONNECTOR_KEY = "communications.mail_connector"
GMAIL_MULTI = "gmail-multi"
CLAUDE_GMAIL = "claude-gmail"

# gmail-multi's whole tool family (plugin_gmail-multi_gmail-multi is the measured plugin-served
# server name; gmail-multi is a manual .mcp.json wiring) — every tool the connector serves, the three
# send tools included (guard_mail_send.py denies those outright under either selection).
GMAIL_MULTI_SERVERS = ("plugin_gmail-multi_gmail-multi", "gmail-multi")
GMAIL_MULTI_TOOL_NAMES = ("gmail_search", "gmail_get_message", "gmail_get_attachment",
                          "gmail_create_draft", "gmail_accounts", "gmail_send_message",
                          "gmail_reply", "gmail_forward")

# the claude.ai Gmail connector's own tool names — UNDETERMINED, a lead from the connector's public
# page (see the module docstring). Matched as an anchored suffix under ANY server name.
CLAUDE_GMAIL_TOOL_NAMES = ("search_threads", "get_thread", "get_message", "list_labels",
                           "list_drafts", "create_draft", "send_message", "reply", "forward")

_GMAIL_MULTI_PATTERN = r"^mcp__(%s)__(%s)$" % ("|".join(GMAIL_MULTI_SERVERS),
                                              "|".join(GMAIL_MULTI_TOOL_NAMES))
_CLAUDE_GMAIL_PATTERN = r"^mcp__.+__(%s)$" % "|".join(CLAUDE_GMAIL_TOOL_NAMES)
# hooks.json's matcher for the connector entry: a regex (the `^`/`(`/`.` make it one), and unanchored by
# the platform's own rule, so each alternative anchors itself.
CONNECTOR_MATCHER = _GMAIL_MULTI_PATTERN + "|" + _CLAUDE_GMAIL_PATTERN
_GMAIL_MULTI_RE = re.compile(_GMAIL_MULTI_PATTERN)
_CLAUDE_GMAIL_RE = re.compile(_CLAUDE_GMAIL_PATTERN)


def connector_of(tool_name):
    """Which connector's mail tool `tool_name` is: GMAIL_MULTI, CLAUDE_GMAIL, or None (not a mail tool
    of either — never denied on connector grounds). Pure; the gate runs it against sample names."""
    name = tool_name if isinstance(tool_name, str) else ""
    if _GMAIL_MULTI_RE.search(name):
        return GMAIL_MULTI
    if _CLAUDE_GMAIL_RE.search(name):
        return CLAUDE_GMAIL
    return None


_FAMILY_LABEL = {GMAIL_MULTI: "gmail-multi", CLAUDE_GMAIL: "the claude.ai Gmail connector"}


def _how_to_change(wanted):
    return ('To use %s instead, set %s to "%s" in config.json (/jobsearch:mailboxes shows '
            'the current selection).' % (_FAMILY_LABEL[wanted], MAIL_CONNECTOR_KEY, wanted))


def _connector_verdict(name, connector, connector_error):
    """None when the connector selection allows `name`; else ("deny-connector", reason).
    `connector` is the resolved selection (None = nothing to select for: no profile); a non-empty
    `connector_error` means the selection could not be resolved or is not valid."""
    family = connector_of(name)
    if family is None:
        return None
    if connector_error:
        return "deny-connector", ("jobsearch could not determine which mail connector you selected "
                                  "(%s), so it will not use %s. Fix %s in config.json."
                                  % (connector_error, name, MAIL_CONNECTOR_KEY))
    if connector is None or family == connector:
        return None
    return "deny-connector", ("your mail connector is '%s' (%s in config.json; the default is '%s'), "
                              "and %s is %s's tool. jobsearch uses only the connector you selected. %s"
                              % (connector, MAIL_CONNECTOR_KEY, GMAIL_MULTI, name,
                                 _FAMILY_LABEL[family], _how_to_change(family)))


def _addr_list_message(accounts):
    return ("pass account=<one of>: %s — one call per address"
            % ", ".join(accounts))


def evaluate(payload, has_profile, accounts, connector=None, connector_error=None,
             scope=True):
    """Returns (verdict, reason). verdict is one of "deny" / "allow" / "allow-blind" /
    "deny-connector" — "allow-blind" is an ALLOW that the caller must also log (the #67 probe);
    "deny-connector" is a deny because the tool belongs to the UNSELECTED mail connector (dev #161).
    `accounts` is only consulted when `has_profile` is True; the caller resolves both exactly once
    per invocation. `connector` is the profile's resolved selection (None = not enforced, e.g. no
    profile); `connector_error` is why it could not be resolved. `scope=False` is the second hook
    entry (`--connector`): the selection only, never the per-address scoping."""
    if not isinstance(payload, dict):
        return "deny", "hook payload unreadable — failing CLOSED for a mailbox-scope matcher hit"
    name = payload.get("tool_name")
    if not name:
        return "deny", "hook payload carries no tool_name — failing CLOSED"
    if has_profile:
        denied = _connector_verdict(name, connector, connector_error)
        if denied:
            return denied
    if not scope:
        return "allow", "connector entry: %s is not the unselected connector's tool" % name
    if name not in GUARDED_MAIL_SCOPE_TOOLS:
        return "allow", "tool %s is not in GUARDED_MAIL_SCOPE_TOOLS" % name
    if "tool_input" not in payload:
        return "allow-blind", ("tool_input key is absent from the payload for %s — this build "
                               "cannot see the argument at all (#67)" % name)
    if not has_profile:
        return "allow", "no profile resolves from this hook's cwd — nothing to scope to"
    if not accounts:
        return "deny", ("this profile has no configured mailboxes (or the list could not be "
                        "read) — run /jobsearch:mailboxes")
    account = (payload.get("tool_input") or {}).get("account")
    if not account or account == "all":
        return "deny", _addr_list_message(accounts)
    if account not in accounts:
        return "deny", _addr_list_message(accounts)
    return "allow", "account %s is exactly one of this profile's addresses" % account


def _resolve_profile_and_accounts():
    """(has_profile, accounts) — has_profile is False only when NOTHING above this hook's cwd
    looks like a profile at all; once a profile is found, any further failure reading its
    mailbox list yields accounts=[] (which `evaluate()` DENYs, per the design's own
    "profile resolves, list unreadable -> DENY" branch — never conflated with "no profile")."""
    try:
        import _root
        root = _root.profile_root()
        if not _root.looks_like_profile(root):
            return False, []
    except Exception:                                     # noqa: BLE001 — unresolved = no profile
        return False, []
    try:
        import mail_client
        return True, (mail_client.configured_accounts() or [])
    except Exception:                                     # noqa: BLE001 — profile is real; list isn't
        return True, []


def _resolve_connector():
    """(connector, error) — the profile's mail connector selection. `error` is a plain-words reason
    when it could not be resolved or is not a valid value (the caller DENIES a connector tool then,
    naming it); never a coerced default for an invalid value (dev #161). Only called once a profile
    is known to resolve."""
    try:
        import mail_client
        return mail_client.selected_connector(), None
    except ValueError as exc:
        return None, str(exc)
    except Exception as exc:                              # noqa: BLE001 — a programming error must be loud
        return None, "%s: %s" % (type(exc).__name__, exc)


def _blind_flag_path(session_id):
    """`<state_root>/guard_mail_scope.blind-<session_id>` — the same per-session-marker shape
    `drift_guard.py`'s `_announce_once` already uses. Returns None when there is no session_id
    to key on — the caller then writes the row every time, because loud beats silent (#67)."""
    sess = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))[:64]
    if not sess:
        return None
    try:
        import _root
        return os.path.join(_root.state_root(), "guard_mail_scope.blind-%s" % sess)
    except Exception:                                     # noqa: BLE001
        return None


def _record_guard_blind(payload):
    """The #67 probe's write side: one `guard-blind` diag row, once per session. Never raises —
    a diagnostic must not turn an ALLOW into a broken hook."""
    session_id = None
    keys = []
    try:
        if isinstance(payload, dict):
            session_id = payload.get("session_id")
            keys = sorted(str(k) for k in payload.keys())
    except Exception:                                     # noqa: BLE001
        pass
    flag = _blind_flag_path(session_id)
    if flag:
        try:
            if os.path.exists(flag):
                return                                    # already announced this session
        except OSError:
            pass
    try:
        from _diag import log as diag
        diag("guard-blind", hook="guard_mail_scope",
            tool_name=(payload or {}).get("tool_name") if isinstance(payload, dict) else None,
            session_id=session_id, keys="+".join(keys)[:64])
    except Exception:                                     # noqa: BLE001 — never block a session
        pass
    if flag:
        try:
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            open(flag, "w", encoding="utf-8").close()
        except OSError:
            pass


def selftest():
    """Prove every branch against SYNTHETIC payloads and a synthetic profile — never a real
    one. Loud, never blocking startup (the same posture guard_mail_send.py's own selftest
    takes)."""
    failures = []
    tool = GUARDED_MAIL_SCOPE_TOOLS[0]
    accounts = ["acct-a@example.com", "acct-b@example.com"]

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": accounts[0]}},
                          True, accounts)
    if verdict != "allow":
        failures.append("exact-match account did not allow")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": "all"}}, True, accounts)
    if verdict != "deny":
        failures.append("account=all did not deny")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {}}, True, accounts)
    if verdict != "deny":
        failures.append("unset account did not deny")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": "acct-z@example.com"}},
                          True, accounts)
    if verdict != "deny":
        failures.append("a foreign account did not deny")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": "acct-b"}},
                          True, accounts)
    if verdict != "deny":
        failures.append("a prefix (not an exact address) did not deny")

    verdict, _ = evaluate({"tool_name": tool}, True, accounts)
    if verdict != "allow-blind":
        failures.append("tool_input absent did not classify as allow-blind")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": accounts[0]}},
                          False, [])
    if verdict != "allow":
        failures.append("no-profile context did not allow silently")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": accounts[0]}}, True, [])
    if verdict != "deny":
        failures.append("an empty mailbox list did not deny")

    verdict, _ = evaluate(
        {"tool_name": "mcp__plugin_gmail-multi_gmail-multi__gmail_accounts"}, True, accounts)
    if verdict != "allow":
        failures.append("gmail_accounts (not a guarded tool) did not allow")

    verdict, _ = evaluate(None, True, accounts)
    if verdict != "deny":
        failures.append("an unreadable payload did not deny")

    uuid_tool = "mcp__0a1b2c3d-0000-4000-8000-000000000000__%s" % CLAUDE_GMAIL_TOOL_NAMES[0]
    verdict, _ = evaluate({"tool_name": uuid_tool}, True, accounts, connector=GMAIL_MULTI,
                          scope=False)
    if verdict != "deny-connector":
        failures.append("gmail-multi selected did not deny a UUID-named claude.ai Gmail tool")
    verdict, _ = evaluate({"tool_name": uuid_tool}, True, accounts, connector=CLAUDE_GMAIL,
                          scope=False)
    if verdict != "allow":
        failures.append("claude-gmail selected did not allow a UUID-named claude.ai Gmail tool")
    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": accounts[0]}}, True,
                          accounts, connector=CLAUDE_GMAIL)
    if verdict != "deny-connector":
        failures.append("claude-gmail selected did not deny a gmail-multi tool")
    verdict, _ = evaluate({"tool_name": "mcp__0a1b2c3d-0000-4000-8000-000000000000__search_files"},
                          True, accounts, connector=GMAIL_MULTI, scope=False)
    if verdict != "allow":
        failures.append("a non-mail tool from another UUID-named connector was denied")
    verdict, _ = evaluate({"tool_name": uuid_tool}, True, accounts, connector_error="bad value",
                          scope=False)
    if verdict != "deny-connector":
        failures.append("an unresolvable selection did not deny a connector tool")

    if failures:
        print(json.dumps({"systemMessage":
                          "guard_mail_scope SELFTEST FAILED (%s) — the per-address scope guard "
                          "may be inert; treat gmail-multi mailbox reads as unscoped this "
                          "session." % "; ".join(failures)}))
        return 0                                          # never block startup; the message is the point
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:                                     # noqa: BLE001
        payload = None
    has_profile, accounts = _resolve_profile_and_accounts()
    connector, connector_error = _resolve_connector() if has_profile else (None, None)
    verdict, reason = evaluate(payload, has_profile, accounts, connector=connector,
                               connector_error=connector_error,
                               scope="--connector" not in sys.argv[1:])
    if verdict == "allow-blind":
        _record_guard_blind(payload)
        return 0
    if verdict == "deny-connector":
        sys.stderr.write("BLOCKED — %s\n\n[guard_mail_scope: connector selection]\n" % reason)
        return 2
    if verdict == "deny":
        sys.stderr.write(
            "BLOCKED — gmail-multi's config is machine-wide (design-manifest-heal.md § The "
            "boundary): every address in accounts.json and every included profile is searched "
            "by any call that omits account. This profile scopes every mailbox call to its own "
            "address(es).\n\n%s\n\n[guard_mail_scope: %s]\n" % (reason, reason))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
