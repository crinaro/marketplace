#!/usr/bin/env python3
"""The ONE table of the claude.ai mail connectors jobsearch can read through (dev #799,
docs/design-mail-any-connector.md §2, §2.1, §14 M3).

`communications.mail_connector` selects one of five values. `gmail-multi` (the default) is the
standalone connector plugin and has no row here: it is not a claude.ai connector, its tools are named
by `guard_mail_scope.py`, and it is read over IMAP. The other four values have one row each:
`claude-gmail`, `claude-m365`, `claude-fastmail`, `claude-superhuman`.

⭐ EVERY ROW IS WRITTEN TO THE CONNECTOR'S PUBLISHED CONTRACT, NOT TO WHAT A PROBE SAW. The owner's
2026-10-30 release decision: "we can only write to the connector's contract". The committed listing
`spec/mail_connector_contracts.json` records, per connector, each source's url, who read it and
when, the tool names it lists, and a short excerpt; `scripts/tests/test_mail_connector_contracts.py`
fails when a name below is not in that listing. That test cannot detect a vendor change after a
source's `read_on` date: a vendor change is fixed by editing the listing and the row together, with
a new date. **Live behaviour against any connector is UNVERIFIED until a user reports it.**

⛔ This module has NO runtime dependency on the listing (the listing is dev-only and never ships)
and imports nothing from jobsearch: the send guard pins its own literal tuples equal to this table by
test, so that no ImportError here can open the guard. Standard library only, and not even that is
needed today.

Row fields:
  value             the stored `communications.mail_connector` value.
  label             what a user is told.
  search_tool       the tool that lists a window of messages.
  body_tool         the tool that reads one body.
  read_tools        every published read tool a fetch uses (suffixes; the server segment varies).
  send_names        the outbound names the vendor publishes (a send, a reply, a forward, a mail rule,
                    or an event write that sends invitations). The send guard denies these.
  contract_complete True only when the vendor's own pages list EVERY tool, so that an unlisted
                    outbound tool cannot exist. False makes the send guard fall back to its
                    mail-send floor, which fails closed.
  server_hints      lower-case fragments of a server name that mark this connector (a fail-closed
                    hint for registrations whose name is not published, such as a desktop-local
                    connector). They only ever ADD a server to what is treated as a connector.
  limit             a limit every doc and `/jobsearch:mailboxes` must state, or None.
  warning           a caution that goes with the limit, or None.
"""

GMAIL_MULTI = "gmail-multi"
DEFAULT = GMAIL_MULTI

# ⭐ The Microsoft 365 wording of design §14 S6 ("work/school only, say so", owner 2026-10-30).
M365_LIMIT = ("works only where your organisation's Entra administrator has consented to the Claude "
              "connector; an employee or student usually cannot grant this. It reads a work or school "
              "Microsoft account only: personal outlook.com, hotmail.com and live.com accounts are "
              "not covered.")
M365_WARNING = ("Reading through your employer's or school's tenant tracks your job search inside "
                "that organisation's mailbox. Know that before you choose it.")

CONNECTORS = {
    "claude-gmail": {
        "value": "claude-gmail",
        "label": "claude.ai Gmail",
        "search_tool": "search_threads",
        "body_tool": "get_message",
        "read_tools": ("search_threads", "get_thread", "get_message", "list_labels", "list_drafts",
                       "list_filters"),
        "send_names": ("send_message", "reply", "forward", "create_filter"),
        "contract_complete": False,        # the directory page shows 24 of 29 tools
        "server_hints": ("gmail",),
        "limit": None,
        "warning": None,
    },
    "claude-m365": {
        "value": "claude-m365",
        "label": "claude.ai Microsoft 365 (work or school accounts only)",
        "search_tool": "outlook_email_search",
        "body_tool": "read_resource",
        "read_tools": ("outlook_email_search", "read_resource"),
        "send_names": (),                  # the vendor publishes no write-tool name
        "contract_complete": False,        # its doc says write actions exist and names none
        "server_hints": ("microsoft", "m365", "outlook"),
        "limit": M365_LIMIT,
        "warning": M365_WARNING,
    },
    "claude-fastmail": {
        "value": "claude-fastmail",
        "label": "claude.ai Fastmail",
        "search_tool": "search_email",
        "body_tool": "read_email",
        "read_tools": ("search_email", "read_email", "read_thread", "list_folders",
                       "list_identities"),
        "send_names": ("compose_event",),
        "contract_complete": False,        # the directory page shows 24 of 29 tools
        "server_hints": ("fastmail",),
        "limit": None,
        "warning": None,
    },
    "claude-superhuman": {
        "value": "claude-superhuman",
        "label": "claude.ai Superhuman Mail",
        "search_tool": "list_threads",
        "body_tool": "get_message",
        "read_tools": ("list_threads", "get_thread", "get_message", "get_attachment",
                       "query_email_and_calendar", "get_read_statuses"),
        "send_names": ("send_draft", "undo_send", "unsubscribe", "create_or_update_event"),
        "contract_complete": True,         # the directory page shows all 19 tools
        "server_hints": ("superhuman",),
        "limit": None,
        "warning": None,
    },
}

# every value `communications.mail_connector` accepts, gmail-multi first (the default)
VALUES = (GMAIL_MULTI,) + tuple(CONNECTORS)


def row(value):
    """The row for a connector value, or None for `gmail-multi` / anything that is not a row."""
    return CONNECTORS.get(value)


def label(value):
    """What a user is told for any accepted value."""
    if value == GMAIL_MULTI:
        return "gmail-multi (the standalone connector plugin; also what the daily sweeps read)"
    r = row(value)
    return r["label"] if r else str(value)


def connectors_for_tool(tool_name):
    """The SET of connector values whose published read tools include this tool's name.

    A tool name maps to a set, never to one connector: `get_message` and `get_thread` belong to both
    claude.ai Gmail and Superhuman (design C2). The suffix after the last `__` is the tool name; the
    server segment is not consulted here. Pure."""
    name = tool_name if isinstance(tool_name, str) else ""
    suffix = name.rsplit("__", 1)[-1]
    return frozenset(v for v, r in CONNECTORS.items() if suffix in r["read_tools"])


def all_read_tools():
    """Every connector's read-tool suffixes, in table order, each once."""
    seen = []
    for r in CONNECTORS.values():
        for t in r["read_tools"]:
            if t not in seen:
                seen.append(t)
    return tuple(seen)
