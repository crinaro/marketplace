"""outbox_store: the `outbox` store, `data/outbox.jsonl` (jobsearch 0.91.0, design-build-reach.md 9.1, 10.4, 10.5, R2 N1, N9, N13b).

One row per message that left "drafted" for the mailbox (`staged`, the candidate sends it) or for an approved send (`queued`, the
engine sends it after the platform's prompt; B7). A draft's TEXT stays in `outreach/drafts.md`; what a run KNOWS about that draft's
journey to sent is a fact, so it lives here (CLAUDE.md principle 4). An open draft with no row is exactly today's draft.

    id                 "o-<n>", minted by `mint_id`
    person_id          the recipient's people id (resolves, not merged: `validation/outbox_rules.py`)
    draft_ref          the drafts.md entry's `**Brief:**` id, the existing citation key
    medium             the entry's `**Medium:**` value
    mode               "you" | "me": the mode in force when the row was made
    account            the mailbox it goes from: one of this profile's own registered addresses
    to, cc, bcc        lists of bare addresses; `to` is always explicit and non-empty, cc and bcc default []
    subject, body      the exact text, held ONLY while the state is queued, staged, approved or sending
    reply_uid          the uid of the message being answered (an email-reply draft's `**In-reply-to:**` line), or null
    text_sha256        the binding hash over `canonical_form` (design 10.5); kept after the text is cleared
    state              queued | staged | approved | sending | sent | discarded | failed
    queued_on, staged_on   ISO dates the row entered that state
    date               the ISO date the message was SENT (the sent message's own `Date:` header). Named `date`, not the design's
                       `sent_on`: `sent_on` is a banned alias for `date` in docs/data_model.json, and `touches`, `applications` and
                       `proposals` already name the day an action went out `date` (the 0.86.0 proposals precedent)
    approved_at, approved_session, sending_at   B7: aware UTC timestamps (seconds) and the approving session (R2 N4, N5)
    touch_id           the touches row written when the state became sent
    last_checked_at    aware UTC timestamp of the last send-detection check that SUCCEEDED (R2 N1); never written by a check that
                       could not read the mailbox
    check_result       that check's answer: none-found | ambiguous | sent
    none_found_checks  how many successful checks in a row found nothing (R2 N9: after enough of them, detect offers cancel)
    note               free text

`sent_as` is not a field (R2 N13b): the sent body is stored on the `messages` row whatever it was.

THE LOCK (R2 N9). Every write of this store is a read-modify-write under ONE outbox-only lock, `data/.outbox.lock`, taken with a
short acquisition deadline (`LOCK_DEADLINE_S`, 3 s): a writer that cannot have it in time raises `OutboxLocked` and writes nothing,
never waits on a hook's 10 s budget. Nobody holds it across a mailbox search (the detect step searches first, then locks and
writes). A lock file older than `LOCK_STALE_S` is a crashed writer's and is broken, said in the exception text of the next waiter
only when it cannot be broken.

AN ABSENT FILE IS AN EMPTY OUTBOX (OURS, design 9.1: "no migration"). Only `outbox.py` of an engine at 0.91.0 or later writes a
row, so a profile with no file has never staged or queued anything: exactly today's state, and nothing a reader could lose by
reading it as empty. A file that is present and does not parse raises `OutboxError` naming the line: never read as empty.

Capability module of `outbox.py`, `check_sent_drafts.py` and `validate_data.py`. Python 3.9+, standard library only."""

import contextlib
import datetime
import os
import re
import time

import _atomic
from validation.outbox_rules import (  # noqa: F401 -- the store's shape lives with its rules; re-exported for its writers
    ADDRESS_RE, CHECK_RESULTS, FIELDS, HOLDS_TEXT, ID_RE, MODES, REQUIRED, STATE_STAMP, STATES, STORE_FILE, OutboxError,
    _reply_from, canonical_form, check_row, load_file, row_sha256, text_sha256)

# B4c: the drafts.md meta line naming the message a reply answers, `**In-reply-to:** <account>:<uid>`: the mailbox holding the
# original and its uid there, the two arguments gmail-multi's `gmail_reply` (`account`, `uid`) and `gmail_create_draft`
# (`account`, `reply_to_uid`) take. It becomes the row's `reply_uid`; the row's `account` is that mailbox.
IN_REPLY_TO_RE = re.compile(r"^\*\*In-reply-to:\*\*[ \t]*(.*?)[ \t]*$", re.M | re.I)
IN_REPLY_TO_VALUE_RE = re.compile(r"^(?P<account>[^@\s<>,;:\"]+@[^@\s<>,;:\"]+\.[^@\s<>,;:\"]+):(?P<uid>[0-9]+)$")

LOCK_NAME = ".outbox.lock"
LOCK_DEADLINE_S = 3.0
LOCK_STALE_S = 120.0
LOCK_POLL_S = 0.05

# what send detection looks for in Sent: a staged draft (the candidate sends it) and a send the guard passed (B7)
DETECTABLE = frozenset({"staged", "sending"})
# design 9.1 / 10.4 / 10.5: every move a row may make. A sent, discarded or failed row is over; a failed row's text is cleared,
# so a retry is a new row with a new approval, never a resend of this one.
TRANSITIONS = {
    "queued": frozenset({"approved", "discarded"}),
    "staged": frozenset({"sent", "discarded"}),
    "approved": frozenset({"sending", "queued", "discarded"}),
    "sending": frozenset({"sent", "failed", "queued"}),
    "sent": frozenset(),
    "discarded": frozenset(),
    "failed": frozenset(),
}

class OutboxLocked(RuntimeError):
    """The outbox lock could not be had within its acquisition deadline; nothing was written."""


def path(root):
    return os.path.join(root, "data", STORE_FILE)


def lock_path(root):
    return os.path.join(root, "data", LOCK_NAME)


def load(root):
    """Every row, in file order. Absent file: `[]` (see the module docstring). A line that is not a JSON object raises."""
    return load_file(path(root))


def save(root, rows):
    _atomic.write_jsonl(path(root), [{k: r[k] for k in sorted(r)} for r in rows])


def mint_id(rows):
    """`o-<n>`, one past the highest number ever minted (never count-plus-one: a removed row must not free its id)."""
    n = 0
    for r in rows:
        m = ID_RE.match(str(r.get("id") or ""))
        if m:
            n = max(n, int(m.group(1)))
    return "o-%d" % (n + 1)


def find(rows, oid):
    for r in rows:
        if r.get("id") == oid:
            return r
    return None


def in_reply_to(entry_body):
    """`(account, uid)` from a drafts.md entry's one `**In-reply-to:**` line; None when it carries none. Strict: two such lines,
    or a value that is not exactly `<account>:<uid>` (free text after it included), raise OutboxError, never a guess."""
    values = IN_REPLY_TO_RE.findall(entry_body or "")
    if not values:
        return None
    if len(values) > 1:
        raise OutboxError("it has %d **In-reply-to:** lines; a reply answers one message" % len(values))
    m = IN_REPLY_TO_VALUE_RE.match(values[0])
    if not m:
        raise OutboxError("its **In-reply-to:** %r is not <account>:<uid> (the mailbox holding the answered message, and that "
                          "message's uid there)" % values[0])
    return m.group("account"), m.group("uid")


def check_reply(messages, account, uid, to):
    """OutboxError unless a reply to message `uid` on `account`, addressed to `to`, can be made: the uid names a stored message
    (a `messages` row whose `source` ends `<account>:<uid>`) and `to` is addresses it came from, the validator's own rule."""
    came_from = _reply_from(messages, account, uid)
    if not came_from:
        raise OutboxError("its **In-reply-to:** %s:%s names no stored message on that mailbox (the inbound message is recorded "
                          "in messages.jsonl, with that source, before its reply is staged)" % (account, uid))
    if not {a.strip().lower() for a in to} <= came_from:
        raise OutboxError("the answered message %s:%s did not come from %s" % (account, uid, ", ".join(to)))


def now_instant(clock=None):
    """Aware UTC, seconds, as the `...Z`-free offset form the rest of the store uses."""
    d = clock() if clock else datetime.datetime.now(datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def transition(row, new_state, **fields):
    """Move `row` to `new_state` in place, setting `fields`. Refuses a move `TRANSITIONS` does not allow. Leaving a text-holding
    state clears subject and body (the hash stays), so the text is never in two stores at once."""
    old = row.get("state")
    if new_state not in TRANSITIONS.get(old, ()):
        raise OutboxError("outbox %s: %s -> %s is not a move this store allows" % (row.get("id"), old, new_state))
    row["state"] = new_state
    row.update(fields)
    if new_state not in HOLDS_TEXT:
        row["subject"] = None
        row["body"] = None
    return row


def _break_if_stale(p, now):
    try:
        age = now - os.path.getmtime(p)
    except OSError:
        return
    if age > LOCK_STALE_S:
        try:
            os.unlink(p)
        except OSError:
            pass


@contextlib.contextmanager
def lock(root, deadline_s=LOCK_DEADLINE_S, why="outbox write"):
    """The outbox-only lock (R2 N9): a file created exclusively, held for the write and removed after it. Past `deadline_s`
    without it, `OutboxLocked` and no write."""
    p = lock_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    give_up = time.monotonic() + deadline_s
    while True:
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            _break_if_stale(p, time.time())
            if time.monotonic() >= give_up:
                try:
                    with open(p, encoding="utf-8") as fh:
                        holder = fh.read().strip() or "unknown"
                except OSError:
                    holder = "unknown"
                raise OutboxLocked("the outbox lock (%s) is held by %s past the %.0f s deadline; nothing was written"
                                   % (p, holder, deadline_s))
            time.sleep(LOCK_POLL_S)
    try:
        os.write(fd, ("%s pid %d" % (why, os.getpid())).encode("utf-8"))
        os.close(fd)
        yield
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass
