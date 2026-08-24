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

Protocol: PreToolUse stdin is the hook payload; exit 2 blocks and stderr is shown to
the model. `--selftest` (run from SessionStart) proves the deny and allow branches
against synthetic payloads, so a syntax error or interpreter problem in this file is
LOUD at session start instead of silently letting sends through.

Python 3.9+, standard library only.
"""

import json
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
