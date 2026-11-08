#!/usr/bin/env python3
"""PreToolUse guard: a jobsearch browsing agent must name its OWN browser tab on every pane call.

⭐ WHY THIS EXISTS (dev #820 / public #175, design-role-pipeline.md §6 TB1, §17 N5, N11, N23)
------------------------------------------------------------------------------------------------
The in-app Browser pane is one shared surface. A pane tool called without a `tabId` acts on whichever
tab is in front, and another task (a second agent, the candidate's own browsing) may have changed it
between two calls. Run in parallel, two agents each reading "their" page can read each other's: the
page text lands in the wrong role's record, and nothing marks it wrong. The remedy is that every
browsing agent opens its own tab (`preview_start` returns a `tabId`), passes that `tabId` on every
call, and closes it. The agents' prompts say so; this guard is the mechanical backstop that makes a
missing `tabId` loud instead of a silent cross-read.

## The test, stated once

    agent_type is a jobsearch browsing agent (TAB_AGENTS), bare or `jobsearch:<name>`,
    AND tool_name is in TAB_TOOLS,
    AND tool_input.tabId is absent or empty                      -> DENY (exit 2, stderr)
    for browser_batch: ANY step whose short name is a TAB_TOOLS
    name and whose input.tabId is absent or empty                -> DENY
    anything else                                                -> ALLOW (exit 0, no output)
    a TAB_AGENT's call whose tool_input is not visible           -> ALLOW + a `tab-guard-degraded`
                                                                    diag row + one shown message
    a payload that does not parse, or a crash anywhere           -> ALLOW + a diag row, exit 0

"Anything else" includes: no `agent_type` (every main session, which is where the daily run and the
coordinator live), an `agent_type` of any other plugin's or the user's own agent, and the exempt tools
(`preview_start`, `tabs_*`, `preview_list/logs/stop`), which open, list or close a tab and act on no
page content. A `browser_batch` step is matched on the suffix after its last `__`, as
`guard_board_hosts.py` matches one, so a step spelled `get_page_text` and one spelled
`mcp__Claude_Browser__get_page_text` are the same step.

## SCOPE: the caller's `agent_type`, never a profile, never `agent_id` (N5, N23)

⭐ This guard does NOT resolve a profile, read the remembered-profile pointer, or look at the cwd. A
version that bound on "a jobsearch profile resolves from here" would bind on any machine that merely
has a remembered pointer, and would deny an unrelated session's browsing. Keying on `agent_type` means
unrelated work never meets it: it never carries a jobsearch agent name.

⭐ STATED DIVERGENCE FROM AG-3 (docs/design-isolation-from-the-harness.md §5.3, N23). AG-3 forbids a
rule keyed on `agent_type`, because the field is also present in an `--agent` MAIN session and a rule
keyed on it would misclassify that session. Here such a misclassification can only TIGHTEN: an
`--agent jobsearch:<TAB_AGENT>` session IS jobsearch browsing and must pass `tabId` anyway. When the
field is absent, renamed or no longer sent, the answer is ALLOW, which is the 0.81 baseline with no
guard at all. So this guard is only ever stricter than the baseline, fails open to the prose rule, and never
fails closed on unrelated work. It never reads `agent_id` (dev #595, #616: no deny decision may), and a
payload carrying `agent_id` and no `agent_type` is an ALLOW; tests pin both directions.

DOCUMENTED (https://code.claude.com/docs/en/hooks, fetched 2026-11-07): plugin hooks run inside
subagents, and the input carries `agent_id` and `agent_type`. UNDETERMINED: whether a plugin
subagent's `agent_type` is scoped (`jobsearch:jd-reader`) or bare (`jd-reader`); both are accepted,
and probe P-RP-1b records the literal string after release. No branch dispatch can exercise the
installed hook (trap 1): pre-release evidence is the in-process and subprocess tests, live evidence is
that probe.

## WHAT THIS DOES NOT COVER (stated, not implied)

- **A main session.** The daily run and the coordinator carry no `agent_type`; for them the rule is
  prose ("open your own tab, pass its tabId"), pinned shape-only in a test. Never a machine-wide deny.
- **A new vendor tab-acting tool FAILS OPEN**: it is not in TAB_TOOLS until someone adds it.
  `check_board_guard_matcher.py` states the rule ("every listed tool takes tabId; every exempt tool
  acts on no page content") and compares hooks.json with TAB_TOOLS, so a tool dropped from one copy is
  caught; a tool the vendor adds tomorrow is not, and that is accepted.
- **`mcp__remote-devices__Claude_Browser__*`** (a cloud session linked to a computer) and the Chrome
  extension's `mcp__claude-in-chrome__*` tools are not matched. The extension requires a tab on every
  call by its own contract.
- **Whether the agent's tab is its OWN.** The guard proves a `tabId` was named, not whose it is.

Protocol: PreToolUse stdin is the hook payload; exit 2 blocks and stderr is shown to the model.
`--selftest` (run from SessionStart) calls `decide()`, the real function, with synthetic payloads and
proves the scoping both ways, so a broken guard is LOUD at session start. It never takes an injected
flag. `hooks.json`'s matcher must equal "|".join(TAB_TOOLS) (an exact-name list, not a regular
expression): `check_board_guard_matcher.py` asserts it in CI and inside the materialized package.

Python 3.9+, standard library only.
"""

import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ⭐ SINGLE SOURCE OF TRUTH for what is guarded. hooks.json's PreToolUse matcher for this script must
# equal "|".join(TAB_TOOLS) exactly (check_board_guard_matcher.py). Every name is an exact tool name:
# the matcher is a plain alternation, not a regular expression.
TAB_TOOLS = (
    "mcp__Claude_Browser__navigate",
    "mcp__Claude_Browser__get_page_text",
    "mcp__Claude_Browser__read_page",
    "mcp__Claude_Browser__find",
    "mcp__Claude_Browser__form_input",
    "mcp__Claude_Browser__computer",
    "mcp__Claude_Browser__javascript_tool",
    "mcp__Claude_Browser__read_console_messages",
    "mcp__Claude_Browser__read_network_requests",
    "mcp__Claude_Browser__resize_window",
    "mcp__Claude_Browser__browser_batch",
)

# The tools that open, list or close a tab. They act on no page content, so they take no `tabId` and
# are never matched (a `preview_start` that demanded a tabId could never open the first tab).
EXEMPT_TOOLS = (
    "mcp__Claude_Browser__preview_start",
    "mcp__Claude_Browser__tabs_context",
    "mcp__Claude_Browser__tabs_create",
    "mcp__Claude_Browser__tabs_select",
    "mcp__Claude_Browser__tabs_close",
    "mcp__Claude_Browser__preview_list",
    "mcp__Claude_Browser__preview_logs",
    "mcp__Claude_Browser__preview_stop",
)

# The jobsearch agents that drive the browser pane (N5). Matched bare or as `jobsearch:<name>`.
TAB_AGENTS = ("board-sweeper", "opportunity-researcher", "jd-reader", "linkedin-runner")
PLUGIN_PREFIX = "jobsearch"

# What each guarded name does, decided by the name's last segment (trap 8: by what it DOES).
BATCH_TOOLS = frozenset(t for t in TAB_TOOLS if t.endswith("browser_batch"))
# N11: a batch step is compared on its short name, i.e. the suffix after the last `__`.
STEP_TOOLS = frozenset(t.split("__")[-1] for t in TAB_TOOLS if t not in BATCH_TOOLS)

DEGRADED_EVENT = "tab-guard-degraded"
TOOL_INPUT_NOT_VISIBLE = "tool-input-not-visible"
PAYLOAD_UNREADABLE = "payload-unreadable"
HOOK_CRASHED = "hook-crashed"

DENY_REASON = ("Name the tab: open your own tab with preview_start (it returns a tabId) and pass tabId on "
               "this call. Without it the call acts on whichever tab is in front, which another task may "
               "have changed.")


def tab_agent(agent_type):
    """The bare TAB_AGENTS name `agent_type` denotes, or None. `jd-reader` and `jobsearch:jd-reader`
    both denote `jd-reader`; `other-plugin:jd-reader`, an unrelated name, a non-string and an absent
    field all denote nothing. Reads the one field it is given and nothing else."""
    if not isinstance(agent_type, str):
        return None
    at = agent_type.strip()
    if ":" in at:
        prefix, _, name = at.partition(":")
        if prefix != PLUGIN_PREFIX:
            return None
        at = name
    return at if at in TAB_AGENTS else None


def _has_tab(tool_input):
    """True when `tool_input` names a tab: a non-empty string, or an integer (some servers number their
    tabs). Absent, None, an empty or blank string, an empty container and a boolean are not a tab."""
    if not isinstance(tool_input, dict):
        return False
    v = tool_input.get("tabId")
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, str):
        return bool(v.strip())
    return False


def decide(payload):
    """(verdict, info) for one call. Pure: no I/O, no profile, no environment.

    verdict is "deny" (info: label, agent), "allow-blind" (info: reason, agent: a TAB_AGENT's call whose
    `tool_input` this build did not show) or "allow" (info None). Reads `agent_type`, `tool_name` and
    `tool_input` only; never `agent_id`, never the cwd."""
    if not isinstance(payload, dict):
        return "allow", None
    agent = tab_agent(payload.get("agent_type"))
    if agent is None:
        return "allow", None                              # not a jobsearch browsing agent: not ours
    name = payload.get("tool_name")
    if name not in TAB_TOOLS:
        return "allow", None                              # an exempt tool, or one the vendor added
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return "allow-blind", {"reason": TOOL_INPUT_NOT_VISIBLE, "agent": agent}
    if name in BATCH_TOOLS:
        actions = tool_input.get("actions")
        for i, action in enumerate(actions if isinstance(actions, list) else []):
            if not isinstance(action, dict):
                continue
            step = str(action.get("name") or "").split("__")[-1]
            if step in STEP_TOOLS and not _has_tab(action.get("input")):
                return "deny", {"label": "%s step %d (%s)" % (name, i + 1, step), "agent": agent}
        return "allow", None
    if not _has_tab(tool_input):
        return "deny", {"label": name, "agent": agent}
    return "allow", None


def deny_message(info):
    return ("BLOCKED: %s was called without a tabId.\n\n%s\n\n[guard_browser_tab: %s]\n"
            % (info["label"], DENY_REASON, info["agent"]))


# ---------------------------------------------------------------------------------------
# The loud half of a degraded allow. Nothing here resolves a profile.
# ---------------------------------------------------------------------------------------

def _flag_path(session_id):
    sess = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))[:64]
    if not sess:
        return None
    return os.path.join(tempfile.gettempdir(), "jobsearch-guard-browser-tab-%s" % sess)


def record_degraded(payload, reason):
    """One `tab-guard-degraded` diag row per session. True when a row was written now, False when this
    session already announced it. Coded scalars only: the diag log refuses prose. Never raises."""
    session_id = tool = None
    try:
        if isinstance(payload, dict):
            session_id = payload.get("session_id")
            tool = payload.get("tool_name")
    except Exception:                                     # noqa: BLE001
        pass
    flag = _flag_path(session_id)
    if flag:
        try:
            if os.path.exists(flag):
                return False
        except OSError:
            pass
    try:
        from _diag import log as diag
        diag(DEGRADED_EVENT, hook="guard_browser_tab", tool_name=tool, session_id=session_id,
             reason=reason)
    except Exception:                                     # noqa: BLE001 - never block a session
        pass
    if flag:
        try:
            open(flag, "w", encoding="utf-8").close()
        except OSError:
            pass
    return True


def degraded_message(info):
    return ("guard_browser_tab could not see this %s call's input, so it was ALLOWED without checking "
            "that it names a tab. Open your own tab with preview_start and pass its tabId on every "
            "browser call anyway." % info.get("agent", "browsing agent"))


# ---------------------------------------------------------------------------------------
# selftest and main
# ---------------------------------------------------------------------------------------

def selftest():
    """Call decide(), the real function, with synthetic payloads, and prove the scoping in both
    directions. Loud, never blocking startup."""
    failures = []
    tool = "mcp__Claude_Browser__get_page_text"

    def verdict(**kw):
        return decide(kw)[0]

    cases = (
        ("a scoped agent without a tabId was not denied",
         dict(agent_type="jobsearch:jd-reader", tool_name=tool, tool_input={}), "deny"),
        ("a bare agent name without a tabId was not denied",
         dict(agent_type="jd-reader", tool_name=tool, tool_input={"tabId": ""}), "deny"),
        ("a scoped agent that named its tab was denied",
         dict(agent_type="jobsearch:jd-reader", tool_name=tool, tool_input={"tabId": "t1"}), "allow"),
        ("a call with no agent_type (a main session) was not allowed",
         dict(tool_name=tool, tool_input={}), "allow"),
        ("another plugin's agent of the same name was not allowed",
         dict(agent_type="other-plugin:jd-reader", tool_name=tool, tool_input={}), "allow"),
        ("an agent_id with no agent_type was not allowed",
         dict(agent_id="agent-synth-1", tool_name=tool, tool_input={}), "allow"),
        ("an exempt tool was denied",
         dict(agent_type="jd-reader", tool_name="mcp__Claude_Browser__preview_start",
              tool_input={"url": "https://x.example"}), "allow"),
        ("a batch step without a tabId was not denied",
         dict(agent_type="jd-reader", tool_name="mcp__Claude_Browser__browser_batch",
              tool_input={"actions": [{"name": "get_page_text", "input": {}}]}), "deny"),
        ("a batch whose steps all name a tab was denied",
         dict(agent_type="jd-reader", tool_name="mcp__Claude_Browser__browser_batch",
              tool_input={"actions": [{"name": "get_page_text", "input": {"tabId": "t1"}}]}), "allow"),
        ("a scoped agent's call with no tool_input was not reported blind",
         dict(agent_type="jd-reader", tool_name=tool), "allow-blind"),
    )
    for what, payload, want in cases:
        try:
            got = decide(payload)[0]
        except Exception as e:                            # noqa: BLE001
            failures.append("%s (decide raised %s)" % (what, type(e).__name__))
            continue
        if got != want:
            failures.append(what)
    if failures:
        print(json.dumps({"systemMessage":
                          "guard_browser_tab SELFTEST FAILED (%s) - the browser tab guard may be inert "
                          "or too wide; treat browser tab discipline as prose-only this session."
                          % "; ".join(failures)}))
    return 0                                              # never block startup; the message is the point


def _run(payload):
    verdict, info = decide(payload)
    if verdict == "deny":
        sys.stderr.write(deny_message(info))
        return 2
    if verdict == "allow-blind":
        if record_degraded(payload, info["reason"]):
            print(json.dumps({"systemMessage": degraded_message(info)}))
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:                                     # noqa: BLE001
        payload = None
    if not isinstance(payload, dict):
        record_degraded(None, PAYLOAD_UNREADABLE)         # not evidence of a violation: allow, with a row
        return 0
    try:
        return _run(payload)
    except Exception:                                     # noqa: BLE001 - never a crash that blocks a tool
        try:
            record_degraded(payload, HOOK_CRASHED)
        except Exception:                                 # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
