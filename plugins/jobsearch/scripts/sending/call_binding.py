"""call_binding: what a gmail-multi send or reply call may carry, and the hash that binds it to one outbox row (jobsearch 0.91.0,
design-build-reach.md 10.5 checks 1, 4, 5 and 7, R1 A3).

THE CLOSED ARGUMENT ALLOW-LIST, read from gmail-multi's own tool schemas (`plugins/gmail-multi/scripts/gmail_mcp_server.py`,
`gmail_send_message` and `gmail_reply`; `scripts/test_mail_guard_composition.py` pins this list to them):

    send    account, to, cc, bcc, subject, body           required: account, to (non-empty), subject, body
    reply   account, to, cc, bcc, subject, body, uid      required: the same, and uid

ANY OTHER KEY DENIES: `html_body` (text the hash does not cover), `reply_all` at ANY value (the server "carries the original
To/Cc into Cc": recipients nobody listed), and every name a later gmail-multi adds. `to` and `subject` are REQUIRED although the
reply schema makes them optional, because the server would derive them ("derives the recipient from Reply-To/From when `to` is
omitted") and a derived value is not a listed one. Types are strict: strings, and lists of bare addresses. `gmail_forward` is never
bound: a forward carries someone else's text.

The canonical form and its hash are `validation/outbox_rules.py`'s (`canonical_form`, `text_sha256`), the same function the row's
own `text_sha256` was made with, so a call binds to a row exactly when its text and recipients are the listed ones.

THE RECIPIENT, re-checked at send time (check 7): a row without `reply_uid` goes to exactly the recorded email of its person; a reply
goes only to addresses the answered message came from (the stored `messages` row of that uid on that account).

`SEND_TOOL_NAMES` is the same closed list of four exact names as `guard_mail_send.CONNECTOR_ENTRY_DEFERS` (an entry point, so it
is not imported; a test pins the two equal). Capability module of `sending/approval.py` and `outbox.py`. Python 3.9+, standard
library only."""

from validation.outbox_rules import ADDRESS_RE, UID_RE, _reply_from, text_sha256

SEND_TOOL_NAMES = {
    "mcp__plugin_gmail-multi_gmail-multi__gmail_send_message": "send",
    "mcp__plugin_gmail-multi_gmail-multi__gmail_reply": "reply",
    "mcp__gmail-multi__gmail_send_message": "send",
    "mcp__gmail-multi__gmail_reply": "reply",
}
BARE_TOOL = {"send": "gmail_send_message", "reply": "gmail_reply"}
SEND_ARGS = ("account", "to", "cc", "bcc", "subject", "body")
REPLY_ARGS = SEND_ARGS + ("uid",)
ALLOWED = {"send": frozenset(SEND_ARGS), "reply": frozenset(REPLY_ARGS)}
REQUIRED = {"send": ("account", "to", "subject", "body"), "reply": ("account", "to", "subject", "body", "uid")}


class BindingError(ValueError):
    """The call is not one an outbox row can bind: the reason is the deny text."""


def tool_kind(tool_name):
    """"send" or "reply" for one of the four exact names; BindingError for anything else, `gmail_forward` included."""
    kind = SEND_TOOL_NAMES.get(tool_name)
    if kind is None:
        if isinstance(tool_name, str) and tool_name.endswith("gmail_forward"):
            raise BindingError("%s is a forward: it carries someone else's text and is never bound" % tool_name)
        raise BindingError("%r is not gmail-multi's send or reply tool" % (tool_name,))
    return kind


def _addresses(name, value, required):
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(a, str) and ADDRESS_RE.match(a.strip()) for a in value):
        raise BindingError("`%s` must be a list of bare addresses, got %r" % (name, value))
    if required and not value:
        raise BindingError("`%s` is empty: a recipient is always explicit" % name)
    return value


def bind(tool_name, tool_input):
    """The `text_sha256` this call's canonical form hashes to. BindingError naming the first argument that breaks the closed
    allow-list, a missing required argument, or a wrong type."""
    kind = tool_kind(tool_name)
    if not isinstance(tool_input, dict):
        raise BindingError("the call's arguments are not visible to this hook (tool_input is %r)" % (tool_input,))
    extra = sorted(k for k in tool_input if k not in ALLOWED[kind])
    if extra:
        raise BindingError("argument(s) %s are not on the closed allow-list (%s): an argument the binding hash does not cover "
                           "must not exist" % (", ".join(extra), ", ".join(sorted(ALLOWED[kind]))))
    missing = [k for k in REQUIRED[kind] if k not in tool_input or tool_input[k] in (None, "")]
    if missing:
        raise BindingError("argument(s) %s are missing: the server would derive them, and a derived value is not a listed "
                           "one" % ", ".join(missing))
    for k in ("account", "subject", "body") + (("uid",) if kind == "reply" else ()):
        if not isinstance(tool_input[k], str):
            raise BindingError("`%s` must be a string, got %r" % (k, tool_input[k]))
    if not ADDRESS_RE.match(tool_input["account"].strip()):
        raise BindingError("`account` %r is not one mailbox address" % tool_input["account"])
    if kind == "reply" and not UID_RE.match(tool_input["uid"]):
        raise BindingError("`uid` %r is not a message uid" % tool_input["uid"])
    to = _addresses("to", tool_input.get("to"), True)
    cc = _addresses("cc", tool_input.get("cc"), False)
    bcc = _addresses("bcc", tool_input.get("bcc"), False)
    return text_sha256(kind, tool_input["account"], to, cc, bcc, tool_input["subject"], tool_input["body"],
                       tool_input.get("uid") if kind == "reply" else None)


def call_args(row):
    """`(bare tool name, arguments)`: exactly what `outbox.py call` prints for `row`. `to` and `subject` always explicit, never
    `html_body` or `reply_all`; `bind` of these arguments equals the row's own `text_sha256`."""
    kind = "reply" if row.get("reply_uid") else "send"
    args = {"account": row["account"], "to": list(row["to"]), "cc": list(row.get("cc") or []),
            "bcc": list(row.get("bcc") or []), "subject": row["subject"], "body": row["body"]}
    if kind == "reply":
        args["uid"] = str(row["reply_uid"])
    return BARE_TOOL[kind], args


def recipient_refusal(row, people, messages):
    """Why `row`'s recipients are not the recorded ones (check 7), or None. `people` is `{id: row}`, `messages` the stored list."""
    to = sorted(str(a).strip().lower() for a in (row.get("to") or []))
    person = people.get(row.get("person_id"))
    if person is None or person.get("status") == "merged":
        return "outbox %s names person %r, which is not a living people row" % (row.get("id"), row.get("person_id"))
    if row.get("reply_uid") in (None, ""):
        email = str(person.get("email") or "").strip().lower()
        if not email or to != [email]:
            return "outbox %s goes to %s, not %s's recorded email %s" % (row.get("id"), ", ".join(to), person.get("id"),
                                                                         email or "(none recorded)")
        return None
    came_from = _reply_from(messages, row.get("account"), row["reply_uid"])
    if not came_from:
        return "outbox %s answers message %s, which is not a stored message on %s" % (row.get("id"), row["reply_uid"],
                                                                                    row.get("account"))
    if not set(to) <= came_from:
        return "outbox %s goes to %s, not the reply address of message %s" % (row.get("id"), ", ".join(to), row["reply_uid"])
    return None
