#!/usr/bin/env python3
"""PreToolUse guard: DENY a gmail-multi mailbox call whose `account` is not exactly one of
THIS PROFILE's own addresses. jobsearch never searches the machine's union.

⭐ WHY THIS EXISTS (design-manifest-heal.md § The boundary, item 1)
--------------------------------------------------------------------
`~/.claude/gmail-multi/accounts.json` is ONE FILE PER MACHINE — it is gmail-multi's registry of
every account on the machine, whichever profile uses it. So a `gmail_search` that omits
`account` (or passes `all`) would reach EVERY account on that machine — two profile directories
on one machine each get both profiles' mail. (Since gmail-multi 0.5.0 its own server refuses an
unset `account`; this guard still narrows `all` and any address outside the profile's subset,
because only jobsearch's hook knows the subset.) The deterministic sweeps (`mail_client.py`)
are not leaky: every sweep passes `account=<address>` per mailbox already. The leak is confined
to the interactive MCP path, and to what the model is told to type — this hook is what makes
"type `account=<address>`" a MECHANICAL requirement rather than a convention the model can
forget.

⭐⭐ dev #469 — THE ALLOWED SET IS THE PROFILE'S DECLARED SUBSET THE REGISTRY HOLDS
-----------------------------------------------------------------------------------
The profile's `user.json` lists addresses BY REFERENCE into gmail-multi's registry
(`mail_client.declared_accounts()` returns `(members, unregistered)`). The allowed set is
`members`. An address the profile declares but the registry lacks is DENIED with the fix
(`/gmail-multi:accounts`), never silently passed through and never searched.

**"A profile session" means any profile this guard resolves — INCLUDING the remembered pointer**
(`~/.claude/jobsearch/profile_root`, which an installed copy consults when nothing above the cwd is a
profile; F2: fail toward narrowing). The consequence is deliberate and stated: on a machine where
jobsearch is installed and enabled and a profile pointer is remembered, gmail-multi's tools are
narrowed to that profile's declared subset EVEN WHEN THE SESSION IS NOT DOING JOB-SEARCH WORK. The
user reaches their other accounts by starting the session where no profile resolves (a directory
that is not under a profile, with `CLAUDESEARCH_ROOT` unset), or by disabling jobsearch for that
session.

`gmail_accounts` (the diagnostic that lists the registry's every address) is GUARDED and DENIED
whenever a profile resolves, with a pointer to `/jobsearch:mailboxes`, which shows the declared
subset and each address's registry state.

**The registry can be in four states** (`mail_client.registry_accounts`):
  ok       -> the rule above.
  absent / malformed (`RegistryError`) -> DENY every guarded mailbox call with the registry's own
           message (the server would refuse them anyway: no accounts).
  schema 1 (`RegistryPending`, the bounded window while the two plugins update in either order) ->
           ALLOW on the OLD rule (an exact member of the raw declared list), and say so LOUDLY:
           the hook's JSON `systemMessage` (shown to the user — stderr of an exit-0 hook is
           never seen by anyone) plus a durable `mail-registry-pending` diag row, once per session
           (F1). Never silent.

## The decision, in order (never re-ordered without re-reading this docstring)

    payload unreadable, or tool_name absent          -> DENY  (fail closed)
    tool_name not one of the guarded tools           -> ALLOW (defensive; hooks.json's matcher
                                                         should never route anything else here)
    `gmail_accounts`, a profile resolves             -> DENY, naming /jobsearch:mailboxes
    `tool_input` key ABSENT from the payload         -> ALLOW, + one `guard-blind` diag row
                                                         (r3, #67 — see below)
    no profile resolves from this hook's cwd         -> ALLOW, silently (nothing to scope to)
    registry absent or malformed                     -> DENY, the registry's message
    profile resolves, but no member address          -> DENY, naming /jobsearch:mailboxes (or, when
      (list empty/unreadable, or all unregistered)      declared addresses are unregistered, the
                                                         /gmail-multi:accounts fix)
    tool_input.account absent, empty, or "all"       -> DENY, printing the address list
    tool_input.account declared but unregistered     -> DENY, naming /gmail-multi:accounts
    tool_input.account present but not EXACTLY one   -> DENY, same list (no prefix match —
      of the members                                    a prefix can collide with another
                                                         profile's address on a second domain)
    exact member, registry ok                        -> ALLOW
    exact member, registry schema 1 (pending)        -> ALLOW, + `systemMessage` + diag row (F1)

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
# are already denied outright by guard_mail_send.py. ⭐ dev #469: `gmail_accounts` IS in this tuple
# now — it reads no mailbox, but it lists the registry's EVERY address, which is exactly what a
# profile session must not learn; it is denied whenever a profile resolves (it has no `account`).
GUARDED_MAIL_SCOPE_TOOLS = (
    # measured plugin-served spelling: mcp__plugin_<plugin>_<server>__<tool>
    "mcp__plugin_gmail-multi_gmail-multi__gmail_search",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_get_message",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_get_attachment",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_create_draft",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_accounts",
    # manual .mcp.json spelling of the same server
    "mcp__gmail-multi__gmail_search",
    "mcp__gmail-multi__gmail_get_message",
    "mcp__gmail-multi__gmail_get_attachment",
    "mcp__gmail-multi__gmail_create_draft",
    "mcp__gmail-multi__gmail_accounts",
)

# the guarded tools that take NO `account` argument: denied outright in a profile session.
ACCOUNTS_LISTING_TOOLS = tuple(t for t in GUARDED_MAIL_SCOPE_TOOLS if t.endswith("__gmail_accounts"))


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


def _unregistered_message(address):
    return ("%s is declared in this profile but is NOT in gmail-multi's registry, so it is not "
            "searchable. Add it with /gmail-multi:accounts, or remove it from the profile with "
            "/jobsearch:mailboxes." % address)


def _no_members_message(unregistered):
    if unregistered:
        return ("none of this profile's mailboxes are in gmail-multi's registry (%s). Add them "
                "with /gmail-multi:accounts, or run /jobsearch:mailboxes to see each address's "
                "state." % ", ".join(unregistered))
    return ("this profile has no configured mailboxes (or the list could not be read) — run "
            "/jobsearch:mailboxes")


ACCOUNTS_DENIED = ("gmail_accounts lists every account on this machine, and a job-search profile "
                   "session works only with its own mailboxes. Run /jobsearch:mailboxes: it shows "
                   "this profile's declared addresses and whether each is in gmail-multi's "
                   "registry.")

# F1 — the loud signal for the bounded mixed-version window. Carried in the hook's JSON
# `systemMessage` (a "Warning message shown to the user"); an exit-0 hook's stderr reaches no one.
PENDING_MESSAGE = ("gmail-multi registry not migrated yet — scoping to the profile list until it "
                   "is. Update the gmail-multi plugin, or start a new session, to finish the "
                   "move; until then this profile's mailbox scope rests on its own list.")


def evaluate(payload, has_profile, accounts, connector=None, connector_error=None,
             scope=True, unregistered=(), registry_pending=False, registry_error=None):
    """Returns (verdict, reason). verdict is one of "deny" / "allow" / "allow-blind" /
    "allow-pending" / "deny-connector" — "allow-blind" is an ALLOW that the caller must also log
    (the #67 probe); "allow-pending" is an ALLOW on the OLD rule while gmail-multi's registry is
    still schema 1, which the caller must announce (F1); "deny-connector" is a deny because the
    tool belongs to the UNSELECTED mail connector (dev #161).
    `accounts` is only consulted when `has_profile` is True; the caller resolves all of it exactly
    once per invocation. dev #469: `accounts` is the profile's MEMBERS (declared AND registered),
    `unregistered` the declared addresses the registry lacks, `registry_pending` says the registry
    is schema 1 (then `accounts` is the raw declared list), `registry_error` is the plain-words
    reason it is absent or malformed. `connector` is the profile's resolved selection (None = not
    enforced, e.g. no profile); `connector_error` is why it could not be resolved. `scope=False` is
    the second hook entry (`--connector`): the selection only, never the per-address scoping."""
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
    if name in ACCOUNTS_LISTING_TOOLS:
        # takes no argument, so it is decided BEFORE the blind probe: there is nothing to see.
        if not has_profile:
            return "allow", "no profile resolves from this hook's cwd — nothing to scope to"
        return "deny", ACCOUNTS_DENIED
    if "tool_input" not in payload:
        return "allow-blind", ("tool_input key is absent from the payload for %s — this build "
                               "cannot see the argument at all (#67)" % name)
    if not has_profile:
        return "allow", "no profile resolves from this hook's cwd — nothing to scope to"
    if registry_error:
        return "deny", registry_error
    unregistered = list(unregistered or ())
    if not accounts:
        return "deny", _no_members_message(unregistered)
    account = (payload.get("tool_input") or {}).get("account")
    if not account or account == "all":
        return "deny", _addr_list_message(accounts)
    if account not in accounts:
        if account.lower() in {u.lower() for u in unregistered}:
            return "deny", _unregistered_message(account)
        return "deny", _addr_list_message(accounts)
    if registry_pending:
        return "allow-pending", ("account %s is on this profile's own list; gmail-multi's registry "
                                 "is still schema 1" % account)
    return "allow", "account %s is exactly one of this profile's addresses" % account


def _resolve_scope():
    """The scope facts `evaluate()` needs, resolved once: `(has_profile, accounts, extras)`, where
    `extras` carries `unregistered`, `registry_pending` and `registry_error`. `has_profile` is False
    only when NOTHING above this hook's cwd looks like a profile at all (a remembered pointer
    counts as a profile — F2); once a profile is found, any further failure reading its mailbox
    list yields accounts=[] (which `evaluate()` DENYs, per the design's own "profile resolves,
    list unreadable -> DENY" branch — never conflated with "no profile")."""
    extras = {"unregistered": [], "registry_pending": False, "registry_error": None}
    try:
        import _root
        root = _root.profile_root()
        if not _root.looks_like_profile(root):
            return False, [], extras
    except Exception:                                     # noqa: BLE001 — unresolved = no profile
        return False, [], extras
    try:
        import mail_client
    except Exception:                                     # noqa: BLE001 — profile is real; list isn't
        return True, [], extras
    try:
        members, unregistered = mail_client.declared_accounts()
        extras["unregistered"] = list(unregistered)
        return True, list(members), extras
    except mail_client.RegistryPending as exc:
        extras["registry_pending"] = True
        return True, list(exc.declared), extras
    except mail_client.RegistryError as exc:
        extras["registry_error"] = str(exc)
        return True, [], extras
    except Exception:                                     # noqa: BLE001 — profile is real; list isn't
        return True, [], extras


def _resolve_profile_and_accounts():
    """(has_profile, accounts) — the pre-#469 two-value view of `_resolve_scope()`, kept for any
    caller that only needs the members."""
    has_profile, accounts, _extras = _resolve_scope()
    return has_profile, accounts


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


def _pending_flag_path(session_id):
    """`<state_root>/guard_mail_scope.pending-<session_id>` — the blind probe's once-per-session
    marker shape; None when there is no session_id (the row is then written every time: loud beats
    silent)."""
    sess = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))[:64]
    if not sess:
        return None
    try:
        import _root
        return os.path.join(_root.state_root(), "guard_mail_scope.pending-%s" % sess)
    except Exception:                                     # noqa: BLE001
        return None


def _record_registry_pending(payload):
    """F1's durable half: one `mail-registry-pending` diag row, once per session (the shown half is
    the `systemMessage` `main()` prints). The row carries a tool name and a session id only — the
    diag log may never hold a mailbox. Never raises: a diagnostic must not break a hook."""
    session_id = None
    tool = None
    try:
        if isinstance(payload, dict):
            session_id = payload.get("session_id")
            tool = payload.get("tool_name")
    except Exception:                                     # noqa: BLE001
        pass
    flag = _pending_flag_path(session_id)
    if flag:
        try:
            if os.path.exists(flag):
                return
        except OSError:
            pass
    try:
        from _diag import log as diag
        diag("mail-registry-pending", hook="guard_mail_scope", tool_name=tool,
             session_id=session_id)
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

    accounts_tool = "mcp__plugin_gmail-multi_gmail-multi__gmail_accounts"
    verdict, _ = evaluate({"tool_name": accounts_tool}, True, accounts)
    if verdict != "deny":
        failures.append("gmail_accounts did not deny in a profile session")
    verdict, _ = evaluate({"tool_name": accounts_tool}, False, [])
    if verdict != "allow":
        failures.append("gmail_accounts did not allow when no profile resolves")

    verdict, reason = evaluate({"tool_name": tool, "tool_input": {"account": "acct-u@example.com"}},
                               True, accounts, unregistered=["acct-u@example.com"])
    if verdict != "deny" or "/gmail-multi:accounts" not in reason:
        failures.append("a declared-but-unregistered account did not deny with the fix")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": accounts[0]}}, True,
                          accounts, registry_pending=True)
    if verdict != "allow-pending":
        failures.append("a member on a schema-1 registry did not classify as allow-pending")

    verdict, _ = evaluate({"tool_name": tool, "tool_input": {"account": accounts[0]}}, True,
                          accounts, registry_error="registry missing")
    if verdict != "deny":
        failures.append("an absent registry did not deny")

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
    has_profile, accounts, extras = _resolve_scope()
    connector, connector_error = _resolve_connector() if has_profile else (None, None)
    verdict, reason = evaluate(payload, has_profile, accounts, connector=connector,
                               connector_error=connector_error,
                               scope="--connector" not in sys.argv[1:], **extras)
    if verdict == "allow-blind":
        _record_guard_blind(payload)
        return 0
    if verdict == "allow-pending":
        # F1 — the shown half (`systemMessage`) and the durable half (a diag row), never stderr.
        _record_registry_pending(payload)
        print(json.dumps({"systemMessage": PENDING_MESSAGE}))
        return 0
    if verdict == "deny-connector":
        sys.stderr.write("BLOCKED — %s\n\n[guard_mail_scope: connector selection]\n" % reason)
        return 2
    if verdict == "deny":
        sys.stderr.write(
            "BLOCKED — gmail-multi's registry is machine-wide (design-mail-boundary.md): it "
            "holds every account on this machine, whichever profile uses it. This profile scopes "
            "every mailbox call to its own address(es) that the registry holds.\n\n%s\n\n"
            "[guard_mail_scope: %s]\n" % (reason, reason))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
