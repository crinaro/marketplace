"""selftest: the SessionStart selftest bodies of `guard_mail_send.py`'s two entries (jobsearch 0.91.0, design-build-reach.md 12:
moved out of the entry point, which is over the 300-line budget; since 0.93.0, ADR-043, both entries deny every send).

Each function takes the guard's own verdict functions as arguments (a package module never imports an entry point), proves the
deny and allow branches against synthetic payloads, prints one `systemMessage` line naming every failure, and returns 0: never
blocking startup, and never letting its own exception escape as a silent pass.

Capability module of `guard_mail_send.py`. Python 3.9+, standard library only."""

import json
import re
import types

from sending import guard_routes

UUID = "0a1b2c3d-0000-4000-8000-000000000000"
# jobsearch 0.93.0 (ADR-043): the connector entry carves nothing out, so it denies gmail-multi's own send family too.
GMAIL_MULTI_SENDS = tuple("mcp__%s__gmail_%s" % (server, tool) for server in ("plugin_gmail-multi_gmail-multi", "gmail-multi")
                          for tool in ("send_message", "reply", "forward"))


def _report(failures, label, what):
    if failures:
        print(json.dumps({"systemMessage": "%s SELFTEST FAILED (%s) - %s" % (label, "; ".join(failures), what)}))
    return 0


def guard(evaluate, guarded_tools):
    """The gmail-multi entry (E1): EVERY send, reply and forward tool denies (jobsearch 0.93.0, ADR-043: no send path exists, so
    nothing turns a deny into anything else), a read tool does not, an unreadable payload denies."""
    failures = []
    try:
        for name in guarded_tools:
            if not evaluate({"tool_name": name, "session_id": "selftest", "cwd": "/"})[0]:
                failures.append("%s did not deny" % name)
        if evaluate({"tool_name": "mcp__plugin_gmail-multi_gmail-multi__gmail_search"})[0]:
            failures.append("read tool denied")
        if evaluate({"tool_name": "mcp__plugin_gmail-multi_gmail-multi__gmail_create_draft"})[0]:
            failures.append("the draft tool denied")
        if not evaluate(None)[0]:
            failures.append("unreadable payload did not deny")
    except BaseException as exc:                          # noqa: BLE001 - a broken selftest is a loud one
        failures = ["selftest raised %s: %s" % (type(exc).__name__, exc)]
    return _report(failures, "guard_mail_send", "the draft-only guard may be inert; treat sends as unguarded this session.")


def connector(evaluate_connector, matcher, verbs=None):
    """The connector entry (E2): the published names and the floor deny, the read and non-mail names do not; and, given the
    guard's `CONNECTOR_SEND_VERBS`, the matcher literal equals the one recomputed from them (`guard_routes`, the gate's own
    derivation), so a verb edited in one place only is loud at session start, not only in CI."""
    failures = []
    try:
        for name in ("mcp__%s__send_message" % UUID, "mcp__%s__outlook_send_mail" % UUID,
                     "mcp__claude_ai_Gmail__reply", "mcp__outlook-work__sendMail",
                     "mcp__%s__send-email" % UUID, "mcp__%s__Send_Mail" % UUID,
                     "mcp__%s__unsubscribe" % UUID, "mcp__%s__compose_event" % UUID) + GMAIL_MULTI_SENDS:
            if not evaluate_connector({"tool_name": name})[0]:
                failures.append("did not deny %s" % name)
        for name in ("mcp__%s__create_reply_draft" % UUID, "mcp__%s__get_senders" % UUID,
                     "mcp__%s__slack_send_message" % UUID, "mcp__%s__search_threads" % UUID,
                     "mcp__ccd_session_mgmt__send_message"):
            if evaluate_connector({"tool_name": name})[0]:
                failures.append("denied %s" % name)
        if not evaluate_connector(None)[0]:
            failures.append("unreadable payload did not deny")
        if not (matcher.startswith("^mcp__") and "(?" not in matcher):
            failures.append("CONNECTOR_SEND_MATCHER is not a plain anchored regex")
        elif not re.search(matcher, "mcp__%s__send_message" % UUID):
            failures.append("CONNECTOR_SEND_MATCHER does not route send_message")
        if verbs is not None and matcher != guard_routes.expected_connector_matcher(
                types.SimpleNamespace(CONNECTOR_SEND_VERBS=verbs)):
            failures.append("CONNECTOR_SEND_MATCHER is not the matcher recomputed from CONNECTOR_SEND_VERBS")
    except BaseException as exc:                          # noqa: BLE001 - a broken selftest is a loud one
        failures = ["selftest raised %s: %s" % (type(exc).__name__, exc)]
    return _report(failures, "guard_mail_send --connector", "the draft-only guard for claude.ai mail connectors may be inert; "
                   "treat connector sends as unguarded this session.")
