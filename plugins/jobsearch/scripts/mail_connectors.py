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
  draft_tool        the tool that saves a message to the mailbox's drafts, unsent (`outbox.py stage`, design-build-reach.md
                    9.2), or None when the vendor publishes none: staging is then refused with that reason.
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
  attach_read_on    the `read_on` of the connector's `tool-arguments` source row in the listing (a page showing the
                    draft tool's arguments), or None when the listing holds no such row. Copied from the listing and
                    pinned equal to it by test; it only dates the by-hand line (`attach_by_hand_line`). jobsearch
                    never passes an attachment to a claude.ai connector, whatever this holds (design-resume-docx.md §7.3).
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
# Why a connector with no `draft_tool` has none, read 2026-11-23 (spec listing): Microsoft lists drafting, names no tool.
NO_DRAFT_WHY = {"claude-m365": ("Microsoft's connector page says Outlook can draft email but names no tool for it, and "
                                "jobsearch builds only to a published tool name")}


def no_draft_why(value):
    """The published reason a connector has no draft tool, or the generic one."""
    return NO_DRAFT_WHY.get(value, "%s publishes no draft tool" % label(value))

CONNECTORS = {
    "claude-gmail": {
        "value": "claude-gmail",
        "label": "claude.ai Gmail",
        "search_tool": "search_threads",
        "body_tool": "get_message",
        "read_tools": ("search_threads", "get_thread", "get_message", "list_labels", "list_drafts",
                       "list_filters"),
        "draft_tool": "create_draft",
        "send_names": ("send_message", "reply", "forward", "create_filter"),
        "contract_complete": False,        # the directory page shows 24 of 29 tools
        "server_hints": ("gmail",),
        "limit": None,
        "warning": None,
        "attach_read_on": None,            # no tool-arguments row: the directory page lists tool names only
    },
    "claude-m365": {
        "value": "claude-m365",
        "label": "claude.ai Microsoft 365 (work or school accounts only)",
        "search_tool": "outlook_email_search",
        "body_tool": "read_resource",
        "read_tools": ("outlook_email_search", "read_resource"),
        "draft_tool": None,                # "manage drafts" is published; no tool name is
        "send_names": (),                  # the vendor publishes no write-tool name
        "contract_complete": False,        # its doc says write actions exist and names none
        "server_hints": ("microsoft", "m365", "outlook"),
        "limit": M365_LIMIT,
        "warning": M365_WARNING,
        "attach_read_on": None,            # no draft tool at all, so no by-hand line; its refusal gains the path sentence
    },
    "claude-fastmail": {
        "value": "claude-fastmail",
        "label": "claude.ai Fastmail",
        "search_tool": "search_email",
        "body_tool": "read_email",
        "read_tools": ("search_email", "read_email", "read_thread", "list_folders",
                       "list_identities"),
        "draft_tool": "draft_email",
        "send_names": ("compose_event",),
        "contract_complete": False,        # the directory page shows 24 of 29 tools
        "server_hints": ("fastmail",),
        "limit": None,
        "warning": None,
        "attach_read_on": None,            # no tool-arguments row: the directory page lists tool names only
    },
    "claude-superhuman": {
        "value": "claude-superhuman",
        "label": "claude.ai Superhuman Mail",
        "search_tool": "list_threads",
        "body_tool": "get_message",
        "read_tools": ("list_threads", "get_thread", "get_message", "get_attachment",
                       "query_email_and_calendar", "get_read_statuses"),
        "draft_tool": "create_or_update_draft",
        "send_names": ("send_draft", "undo_send", "unsubscribe", "create_or_update_event"),
        "contract_complete": True,         # the directory page shows all 19 tools
        "server_hints": ("superhuman",),
        "limit": None,
        "warning": None,
        "attach_read_on": None,            # no tool-arguments row: the directory page lists tool names only
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


# ── the file a claude.ai draft cannot carry (jobsearch 0.93.0, design-resume-docx.md §7.3) ─────────────────────────
# The draft is still made, with no attachment argument, and the person adds the file. The line is printed, never stored.
# It names "the computer running this session", never a hostname (§R2 S2-7: on macOS the hostname is not the name the
# person sees, and it often holds their name).

# the only arguments a claude.ai draft call carries: an attachment is never one, whatever the live schema shows
CLAUDE_AI_DRAFT_KEYS = ("to", "subject", "body")
ON_THIS_COMPUTER = "On the computer running this session: %s"
ADD_IT = "Add the file to the draft before you press Send."


def path_sentence(path):
    """The fixed sentence that makes a by-hand path usable from a phone driving this session (S5)."""
    return ON_THIS_COMPUTER % path


def claude_ai_draft_args(value, fields):
    """The argument dict of a claude.ai connector's draft call: `to`, `subject`, `body` from `fields`, and nothing else.

    `fields` may hold anything an outbox row holds, `attachments` included; only `CLAUDE_AI_DRAFT_KEYS` pass. Raises
    ValueError for a value with no published draft tool (`gmail-multi` builds its own call)."""
    r = row(value)
    if not r or not r.get("draft_tool"):
        raise ValueError("%s has no claude.ai draft tool" % label(value))
    args = {k: fields[k] for k in CLAUDE_AI_DRAFT_KEYS}
    args["_note"] = "argument names per %s's own tool schema" % label(value)
    return args


def attach_by_hand_line(value, outbox_id, path, table=None):
    """The ATTACH BY HAND line printed with a claude.ai connector's draft call, for the file at `path`.

    Dated with exactly the row's `attach_read_on` when the listing holds a `tool-arguments` row for the connector,
    undated otherwise. Raises ValueError for a value with no draft tool: `claude-m365` makes no draft and its refusal
    gains `path_sentence(path)` instead; `gmail-multi` carries the file. `table` defaults to `CONNECTORS`."""
    r = (CONNECTORS if table is None else table).get(value)
    if not r or not r.get("draft_tool"):
        raise ValueError("%s has no claude.ai draft tool, so there is no draft to attach to" % label(value))
    name, tool, read_on = r["label"], r["draft_tool"], r.get("attach_read_on")
    if read_on:
        head = "%s's %s publishes no attachment argument (read %s)." % (name, tool, read_on)
    else:
        head = "this plugin records no attachment argument for %s's %s." % (name, tool)
    return "ATTACH BY HAND %s: %s %s %s" % (outbox_id, head, ADD_IT, path_sentence(path))
