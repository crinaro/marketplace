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


def _addr_list_message(accounts):
    return ("pass account=<one of>: %s — one call per address"
            % ", ".join(accounts))


def evaluate(payload, has_profile, accounts):
    """Returns (verdict, reason). verdict is one of "deny" / "allow" / "allow-blind" — the last
    is an ALLOW that the caller must also log (the #67 probe). `accounts` is only consulted when
    `has_profile` is True; the caller resolves both exactly once per invocation."""
    if not isinstance(payload, dict):
        return "deny", "hook payload unreadable — failing CLOSED for a mailbox-scope matcher hit"
    name = payload.get("tool_name")
    if not name:
        return "deny", "hook payload carries no tool_name — failing CLOSED"
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
    verdict, reason = evaluate(payload, has_profile, accounts)
    if verdict == "allow-blind":
        _record_guard_blind(payload)
        return 0
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
