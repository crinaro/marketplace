"""The `outbox` store as `validate_data` checks it (jobsearch 0.91.0, design-build-reach.md 9.1): every row's shape (`check_row`:
the fields, the states and the binding hash; the ONE definition `sending/outbox_store.py`'s writers import and re-export, kept
here so the validator never imports the writer), plus the references only the other stores can answer.

    person_id   resolves to a people row that is not merged
    to          without `reply_uid`: exactly the person's recorded email. With it: addresses that message came from
    reply_uid   names a stored message (a mail source tag ending in that uid) on the row's own account
    touch_id    a sent row's touch exists, is `sent`, and is to the same person
    medium      one of the touch media
    id          unique

The attachment fields (jobsearch 0.93.0, design-resume-docx.md §6.2), both optional and absent when the draft names none:

    attachments     a list of at most `MAX_ATTACHMENTS` items, each exactly `ATTACH_KEYS`: `ref` (`<kind>:<variant id>`,
                    kind `resume`); `file` ("/"-separated, relative to the profile root), `sha256` and `bytes`, stamped
                    together when the draft call is printed, else all null; `carried` null (printed, no result recorded),
                    true (only with a stamp) or false; `why` the reason exactly when `carried` is false
    attach_sha256   64 hex of the refs joined by newline (`refs_sha256`), present exactly when `attachments` is, in every
                    state, so a `ref` edited after approval is red here. A hand edit rewriting both together is not seen
                    (the text hash's own limit)

An absent `outbox.jsonl` is an empty outbox (the store's docstring says why), so it is checked as zero rows, said on the summary
line. A present file that does not parse is a problem, never zero rows.

Capability module of `validate_data.py`. Python 3.9+, standard library only."""

import hashlib
import json
import os
import re
from validation.vocab import MEDIA

STORE_FILE = "outbox.jsonl"
STATES = ("queued", "staged", "approved", "sending", "sent", "discarded", "failed")
HOLDS_TEXT = frozenset({"queued", "staged", "approved", "sending"})
MODES = ("you", "me")
CHECK_RESULTS = ("none-found", "ambiguous", "sent")
FIELDS = ("id", "person_id", "draft_ref", "medium", "mode", "account", "to", "cc", "bcc", "subject", "body", "reply_uid",
          "text_sha256", "state", "queued_on", "staged_on", "date", "approved_at", "approved_session", "sending_at", "touch_id",
          "last_checked_at", "check_result", "none_found_checks", "note", "attachments", "attach_sha256")
REQUIRED = ("id", "person_id", "draft_ref", "medium", "mode", "account", "to", "cc", "bcc", "reply_uid", "text_sha256", "state")
# the field each state must carry once a row is in it (design 9.1's validator rules)
STATE_STAMP = {"queued": "queued_on", "staged": "staged_on", "approved": "approved_at", "sending": "sending_at", "sent": "date"}

ID_RE = re.compile(r"^o-([1-9][0-9]*)$")
ADDRESS_RE = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
UID_RE = re.compile(r"^[0-9]+$")
# design-resume-docx.md §6.2, §7.1 step 1: at most one attachment, kind `resume`, in this release
ATTACH_KEYS = ("ref", "file", "sha256", "bytes", "carried", "why")
ATTACH_KINDS = ("resume",)
MAX_ATTACHMENTS = 1
REF_RE = re.compile(r"^(?P<kind>[a-z][a-z0-9-]*):(?P<id>[A-Za-z0-9][A-Za-z0-9._-]*)$")
UNSTAMPED = frozenset({"queued", "approved"})     # no draft call has been printed for a row in these states


class OutboxError(ValueError):
    """The store, or a row of it, cannot be read or does not hold. Loud by design: an unreadable outbox is never an empty one."""


def load_file(p):
    """`load` for an explicit file path (the validator's data directory need not be `<root>/data`)."""
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise OutboxError("%s cannot be read (%s: %s)" % (p, type(exc).__name__, exc))
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise OutboxError("%s line %d is not JSON (%s)" % (p, n, exc))
        if not isinstance(row, dict):
            raise OutboxError("%s line %d is not a JSON object" % (p, n))
        rows.append(row)
    return rows


def _addresses(values):
    return sorted({str(v).strip().lower() for v in (values or [])})


def canonical_form(tool, account, to, cc, bcc, subject, body, uid):
    """Design 10.5: ONE JSON object, keys sorted, UTF-8. `tool` is send or reply; addresses lower-cased, de-duplicated and sorted
    (absent cc and bcc are []); subject exact; body with line endings normalized and nothing else changed; uid or null."""
    if tool not in ("send", "reply"):
        raise OutboxError("canonical form: tool must be send or reply, got %r" % (tool,))
    text = (body if isinstance(body, str) else "").replace("\r\n", "\n").replace("\r", "\n")
    obj = {"tool": tool, "account": str(account or "").strip().lower(), "to": _addresses(to), "cc": _addresses(cc),
           "bcc": _addresses(bcc), "subject": subject if isinstance(subject, str) else "", "body": text,
           "uid": None if uid in (None, "") else str(uid)}
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def text_sha256(tool, account, to, cc, bcc, subject, body, uid):
    return hashlib.sha256(canonical_form(tool, account, to, cc, bcc, subject, body, uid).encode("utf-8")).hexdigest()


def row_sha256(row):
    """The hash a row's own text and recipients produce. Only meaningful while the row holds its text."""
    tool = "reply" if row.get("reply_uid") else "send"
    return text_sha256(tool, row.get("account"), row.get("to"), row.get("cc"), row.get("bcc"), row.get("subject"),
                       row.get("body"), row.get("reply_uid"))


def refs_sha256(items):
    """`attach_sha256`: the hash of the items' refs joined by newline (§6.2)."""
    return hashlib.sha256("\n".join(str(i.get("ref")) for i in items).encode("utf-8")).hexdigest()


def rel_file_ok(value):
    """A "/"-separated path relative to the profile root: no backslash, not absolute, no empty, `.` or `..` segment."""
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    return all(seg not in ("", ".", "..") for seg in value.split("/"))


def _check_item(item, where, state, out):
    if not isinstance(item, dict) or set(item) != set(ATTACH_KEYS):
        out.append("%s must hold exactly %s, got %r" % (where, ", ".join(ATTACH_KEYS), item))
        return
    m = REF_RE.match(item["ref"]) if isinstance(item["ref"], str) else None
    if m is None or m.group("kind") not in ATTACH_KINDS:
        out.append("%s: ref %r is not %s:<variant id>" % (where, item["ref"], "|".join(ATTACH_KINDS)))
    if any(item[k] is not None for k in ("file", "sha256", "bytes")):
        if not rel_file_ok(item["file"]):
            out.append("%s: file %r is not a \"/\"-separated path relative to the profile root" % (where, item["file"]))
        if not SHA_RE.match(str(item["sha256"])):
            out.append("%s: sha256 is not 64 hex characters" % where)
        if isinstance(item["bytes"], bool) or not isinstance(item["bytes"], int) or item["bytes"] < 0:
            out.append("%s: bytes must be a count" % where)
        if state in UNSTAMPED:
            out.append("%s: a %s row has printed no draft call, so it holds no file stamp" % (where, state))
    if item["carried"] not in (None, True, False):
        out.append("%s: carried %r is not null, true or false" % (where, item["carried"]))
    if item["carried"] is True and item["sha256"] is None:
        out.append("%s: carried is true with no stamp to have matched" % where)
    if item["carried"] is not None and state in UNSTAMPED:
        out.append("%s: a %s row has printed no draft call, so carried is null" % (where, state))
    if item["carried"] is False and not (isinstance(item["why"], str) and item["why"].strip()):
        out.append("%s: carried is false, so why names the reason" % where)
    if item["carried"] is not False and item["why"] is not None:
        out.append("%s: why is set only when carried is false" % where)


def _check_attachments(row, label, out):
    """§6.2: `attachments` and `attach_sha256` together or not at all, and the hash equal to the row's own refs."""
    if ("attachments" in row) != ("attach_sha256" in row):
        out.append("%s: attachments and attach_sha256 are present together or not at all" % label)
        return
    if "attachments" not in row:
        return
    items = row["attachments"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ATTACHMENTS:
        out.append("%s: attachments must be a list of 1 to %d items" % (label, MAX_ATTACHMENTS))
        return
    for j, item in enumerate(items):
        _check_item(item, "%s: attachments[%d]" % (label, j), row.get("state"), out)
    if row["attach_sha256"] != refs_sha256([i for i in items if isinstance(i, dict)]):
        out.append("%s: attach_sha256 does not match the row's own refs: an attachment was changed without "
                   "re-staging it" % label)


def _check_lists(row, label, out):
    for f in ("to", "cc", "bcc"):
        v = row.get(f)
        if not isinstance(v, list) or not all(isinstance(a, str) and ADDRESS_RE.match(a) for a in v):
            out.append("%s: %s must be a list of bare addresses, got %r" % (label, f, v))
    if isinstance(row.get("to"), list) and not row["to"]:
        out.append("%s: to is empty: a recipient is always explicit (design 10.5)" % label)


def _check_state(row, label, out):
    state = row.get("state")
    if state not in STATES:
        out.append("%s: state %r is not one of %s" % (label, state, ", ".join(STATES)))
        return
    stamp = STATE_STAMP.get(state)
    if stamp and row.get(stamp) in (None, ""):
        out.append("%s: a %s row needs %s" % (label, state, stamp))
    if state == "sending" and row.get("approved_at") in (None, ""):
        out.append("%s: a sending row needs approved_at (the guard passes only an approved row)" % label)
    holds = state in HOLDS_TEXT
    for f in ("subject", "body"):
        if holds and not isinstance(row.get(f), str):
            out.append("%s: a %s row holds its %s as text" % (label, state, f))
        if not holds and row.get(f) is not None:
            out.append("%s: a %s row holds no %s (the text moves to messages when sent; design 9.1)" % (label, state, f))
    if state == "sent" and not row.get("touch_id"):
        out.append("%s: a sent row names the touch it wrote (touch_id)" % label)
    if holds and isinstance(row.get("body"), str) and isinstance(row.get("subject"), str):
        if row.get("text_sha256") != row_sha256(row):
            out.append("%s: text_sha256 does not match the row's own text and recipients: the text was changed without "
                       "re-staging it" % label)


def check_row(row, label=None):
    """Every shape problem of one row, as text. `[]` means the row holds. Cross-store references are `validation/outbox_rules`."""
    label = label or "outbox[%s]" % row.get("id", "?")
    out = []
    for f in REQUIRED:
        if f not in row:
            out.append("%s: missing %s" % (label, f))
    for k in row:
        if k not in FIELDS:
            out.append("%s: unknown key %r (known: %s)" % (label, k, ", ".join(FIELDS)))
    if not ID_RE.match(str(row.get("id") or "")):
        out.append("%s: id %r is not o-<n>" % (label, row.get("id")))
    if row.get("mode") not in MODES:
        out.append("%s: mode %r is not you or me" % (label, row.get("mode")))
    if not (isinstance(row.get("account"), str) and ADDRESS_RE.match(row["account"])):
        out.append("%s: account %r is not an address" % (label, row.get("account")))
    _check_lists(row, label, out)
    if row.get("reply_uid") is not None and not UID_RE.match(str(row["reply_uid"])):
        out.append("%s: reply_uid %r is not digits" % (label, row.get("reply_uid")))
    if not SHA_RE.match(str(row.get("text_sha256") or "")):
        out.append("%s: text_sha256 is not 64 hex characters" % label)
    for f in ("queued_on", "staged_on", "date"):
        if row.get(f) is not None and not DATE_RE.match(str(row[f])):
            out.append("%s: %s %r is not an ISO date" % (label, f, row[f]))
    for f in ("approved_at", "sending_at", "last_checked_at"):
        if row.get(f) is not None and not INSTANT_RE.match(str(row[f])):
            out.append("%s: %s %r is not an offset-bearing timestamp" % (label, f, row[f]))
    if row.get("check_result") is not None and row["check_result"] not in CHECK_RESULTS:
        out.append("%s: check_result %r is not one of %s" % (label, row["check_result"], ", ".join(CHECK_RESULTS)))
    n = row.get("none_found_checks")
    if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 0):
        out.append("%s: none_found_checks must be a count" % label)
    _check_state(row, label, out)
    _check_attachments(row, label, out)
    return out


_ADDR_RE = re.compile(r"[\w.+'-]+@[\w.-]+\.\w+")


def _rows(data_dir, name):
    try:
        with open(os.path.join(data_dir, name), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except (OSError, ValueError):
        return []


def _reply_from(messages, account, uid):
    """The addresses the message with `uid` on `account` came from, or None when no stored message is that one."""
    out = None
    for m in messages:
        src = str(m.get("source") or "")
        parts = src.split(":")
        if len(parts) == 3 and parts[2] == str(uid) and parts[1].lower() == str(account).lower():
            out = (out or set()) | {a.lower() for a in _ADDR_RE.findall(str(m.get("from") or ""))}
    return out


def _refs(r, label, people, messages, touches, problems):
    person = people.get(r.get("person_id"))
    if person is None:
        problems.append("%s: person_id %r resolves to no people row" % (label, r.get("person_id")))
    elif person.get("status") == "merged":
        problems.append("%s: person_id %r was merged into %r" % (label, r.get("person_id"), person.get("merged_into")))
    to = [str(a).lower() for a in (r.get("to") or [])] if isinstance(r.get("to"), list) else []
    if r.get("reply_uid") in (None, ""):
        email = str((person or {}).get("email") or "").strip().lower()
        if person is not None and to != [email]:
            problems.append("%s: to %r is not the person's recorded email %r" % (label, r.get("to"), email or None))
    else:
        came_from = _reply_from(messages, r.get("account"), r["reply_uid"])
        if came_from is None:
            problems.append("%s: reply_uid %r names no stored message on %s" % (label, r["reply_uid"], r.get("account")))
        elif not set(to) <= came_from:
            problems.append("%s: to %r is not the reply address of message %s" % (label, r.get("to"), r["reply_uid"]))
    if r.get("medium") not in MEDIA:
        problems.append("%s: medium %r is not a touch medium" % (label, r.get("medium")))
    if r.get("state") == "sent" and r.get("touch_id"):
        t = touches.get(r["touch_id"])
        if t is None:
            problems.append("%s: touch_id %r resolves to no touches row" % (label, r["touch_id"]))
        elif t.get("status") != "sent" or t.get("person_id") != r.get("person_id"):
            problems.append("%s: touch %r is not a sent touch to %s" % (label, r["touch_id"], r.get("person_id")))


def check_outbox(data_dir, problems):
    """Check `outbox.jsonl` beside the other stores in `data_dir`, appending each problem. Returns the summary line."""
    try:
        rows = load_file(os.path.join(data_dir, STORE_FILE))
    except OutboxError as exc:
        problems.append("outbox.jsonl: %s" % exc)
        return "Outbox: NOT CHECKED -- the store does not parse (a problem above)"
    if not rows:
        return "Outbox: 0 rows (%s)" % ("absent: an empty outbox" if not os.path.exists(os.path.join(data_dir, STORE_FILE))
                                        else "empty")
    people = {p.get("id"): p for p in _rows(data_dir, "people.jsonl")}
    touches = {t.get("id"): t for t in _rows(data_dir, "touches.jsonl")}
    messages = _rows(data_dir, "messages.jsonl")
    seen = set()
    for r in rows:
        label = "outbox[%s]" % r.get("id", "?")
        problems.extend(check_row(r, label))
        if r.get("id") in seen:
            problems.append("%s: duplicate id" % label)
        seen.add(r.get("id"))
        _refs(r, label, people, messages, touches, problems)
    return "Outbox: %d rows checked (%s)" % (len(rows), ", ".join(
        "%d %s" % (sum(1 for r in rows if r.get("state") == s), s) for s in STATES
        if any(r.get("state") == s for r in rows)))
