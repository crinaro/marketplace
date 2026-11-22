"""approval: the attended email `me` send path (jobsearch 0.91.0, design-build-reach.md 10.3-10.5, R2 N4, N5, N8, N9, N12, owner
O5, O18, O19, O21 and the 2026-11-21 amendment: email `me` ships ATTENDED ONLY).

    queued --approve (attended, this session)--> approved --call (attended, same session: approved_at re-stamped)-->
    approved --the guard, E1: bound, in window, same session--> sending --PostToolUse error--> failed
                                                                          (a Sent copy, `outbox.py detect`) --> sent
    approved --older than APPROVAL_WINDOW_S at any verb--> queued, journaled as an `outbox-lapse` event

ATTENDED ONLY. A run is unattended by default and attended is never inferred (`posture.py`): the only attended form is the explicit
`--attended` a person's own run passes. `approve` and `call` refuse without it, so in an unattended or scheduled run a `me` row
stays `queued` for the next attended session and nothing is ever called; and the guard passes only a row that an attended
`approve` and `call` of THE SAME SESSION made live (`approved_session` = `$CLAUDE_CODE_SESSION_ID`, the hook payload's
`session_id`, R2 N4, owner O21) within `APPROVAL_WINDOW_S` of the `call` (R2 N5). The window bounds reaching the prompt; the
click itself is unbounded by design. `/clear` changes the session id, so an approval made before it lapses. `--attended` is
self-asserted (a session can pass it), so it narrows what reaches a prompt and is NOT the security boundary: the platform's
per-call prompt for gmail-multi's flagged send tools is the approval (design 10.4 step 3). `SEND_PROMPT_UNATTENDED` (design 10.2)
is not built: the amendment replaced that probe gate with this attended-only rule.

`decide(payload)` IS E1's verdict for gmail-multi's send and reply (`guard_mail_send.py`). Every check of design 10.5, in order,
and any failure, unknown argument or exception is ("deny", reason); it never answers "allow":

    1  the tool is one of the four exact send/reply names (`call_binding.tool_kind`); a forward denies
    2  the profile resolves from the hook payload's `cwd` ONLY (walk up for a profile marker), never the remembered pointer
    3  `actions.modes.email-send` resolves to `me` (`sending/modes.py`: and so the connector is gmail-multi)
    4  the closed argument allow-list (`call_binding.bind`)
    5  the canonical form hashes to the `text_sha256` of exactly one live outbox row
    6  that row is `approved`, by this payload's `session_id`, `approved_at` within APPROVAL_WINDOW_S by this clock
    7  `account` is one of this profile's registered addresses (`mail_client.declared_accounts`: gmail-multi's registry, named
       by `GMAIL_MULTI_CONFIG` when set; absent or not schema 2 denies, R2 N8) and the recipients are the recorded ones
    then, under the outbox-only lock (3 s acquisition deadline, its own deny reason past it, R2 N9), the row is re-read, the checks
    5-6 repeated, and it moves to `sending` (stamping `sending_at`) in the same write, before ("ask", reason). A second identical
    call finds no `approved` row and denies, so nothing is sent twice.

`sending` IS NAMED HONESTLY (R2 N9): the guard passed it; the outcome depends on the other hooks and on the prompt. The
PostToolUse entry (`sent_hook`) moves it to `failed` on an error result. A successful result is NOT written as `sent` here: the
tool's answer names no message uid (gmail-multi `_sent_report`), and a sent row names the touch and the outbound `messages` row it
wrote from the Sent copy, so the row stays `sending`, noted, and `outbox.py detect` records `sent` from the Sent copy (the P-POST
fallback of design 13). A row left `sending` is never re-sent without a new approval.

Capability module of `guard_mail_send.py` and `outbox.py`. Python 3.9+, standard library only."""

import datetime
import json
import os

import _root
import mail_client
from journaling.journal_file import append as journal_append
from journaling.journal_file import now_iso
from journaling.journal_file import read as journal_read
from sending import call_binding, modes
from sending import outbox_store as store

APPROVAL_WINDOW_S = 600
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
LAPSE_EVENT = "outbox-lapse"
UNATTENDED = ("this run is unattended (no --attended): a `me` send is queued for the next attended session and never called "
              "here")


class Refused(Exception):
    """A verb that cannot run as asked; the text says why and what stays as it was."""


def _instant(value):
    s = str(value or "")
    d = datetime.datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    if d.tzinfo is None:
        raise ValueError("%r carries no offset" % s)
    return d


def age_s(row, now):
    """Seconds since `approved_at`, or None when the row has none that parses."""
    try:
        return (now - _instant(row.get("approved_at"))).total_seconds()
    except (TypeError, ValueError):
        return None


def in_window(row, now):
    a = age_s(row, now)
    return a is not None and 0 <= a <= APPROVAL_WINDOW_S


def profile_from_cwd(cwd):
    """The profile at or above `cwd`, or None. Deliberately never the remembered pointer (the `migrate.py` rule)."""
    if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        return None
    cur = os.path.abspath(cwd)
    while True:
        if _root.looks_like_profile(cur):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def load_config(root):
    p = os.path.join(root, "config.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise Refused("config.json at %s cannot be read (%s: %s)" % (p, type(exc).__name__, exc))


def require_me(root):
    try:
        mode = modes.resolve(load_config(root), modes.EMAIL_SEND)
    except modes.ModeError as exc:
        raise Refused(str(exc))
    if mode != "me":
        raise Refused("%s.%s is you: jobsearch stages the draft and you send it (outbox.py stage)" % (modes.KEY,
                                                                                                    modes.EMAIL_SEND))


def _jsonl(root, name):
    try:
        with open(os.path.join(root, "data", name), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return []


def lapse(root, now):
    """Revert every `approved` row older than the window to `queued`, journal one `outbox-lapse` event each (R2 N12), and return
    the lines to print. Every outbox verb runs this first; the guard never depends on it (it checks the age itself)."""
    if not any(r.get("state") == "approved" and not in_window(r, now) for r in store.load(root)):
        return []                                         # the common case takes no lock and writes nothing
    with store.lock(root, why="outbox lapse sweep"):
        rows = store.load(root)
        lapsed = []
        for r in rows:
            if r.get("state") == "approved" and not in_window(r, now):
                lapsed.append({"outbox_id": r["id"], "approved_at": r.get("approved_at"),
                               "approved_session": r.get("approved_session")})
                store.transition(r, "queued", approved_at=None, approved_session=None)
        if lapsed:
            store.save(root, rows)
    out = []
    for ev in lapsed:
        out.append("%s: approval of %s lapsed after %d s; back to queued (approve it again to send)"
                   % (ev["outbox_id"], ev["approved_at"], APPROVAL_WINDOW_S))
        try:
            journal_append(root, dict(ev, event=LAPSE_EVENT, at=now_iso()))
        except Exception as exc:                          # noqa: BLE001 - the lapse itself is written; say the journal is not
            out.append("!! the lapse of %s was NOT journaled (%s: %s)" % (ev["outbox_id"], type(exc).__name__, exc))
    return out


def approve(root, ids, attended, session_id, now):
    """queued -> approved for each of `ids` (all or none), bound to `session_id`. Refused unattended, with no session id, with
    mode `you`, or for a row that is not a queued `me` row."""
    if not attended:
        raise Refused(UNATTENDED + "; nothing was approved")
    if not session_id:
        raise Refused("$%s is not set, so the approval cannot be bound to this session; nothing was approved" % SESSION_ENV)
    require_me(root)
    if not ids:
        raise Refused("name the rows to approve (outbox.py list --ready)")
    with store.lock(root, why="outbox.py approve"):
        rows = store.load(root)
        picked = []
        for oid in ids:
            row = store.find(rows, oid)
            if row is None or row.get("state") != "queued" or row.get("mode") != "me":
                raise Refused("%s is not a queued `me` row (%s); nothing was approved"
                              % (oid, "no such row" if row is None else row.get("state")))
            picked.append(row)
        for row in picked:
            store.transition(row, "approved", approved_at=store.now_instant(lambda: now), approved_session=session_id)
        store.save(root, rows)
    return ["%s approved in this session for %d s: run outbox.py call %s --attended, then make that one call" % (
        r["id"], APPROVAL_WINDOW_S, r["id"]) for r in picked]


def call(root, oid, attended, session_id, now):
    """`(bare tool, arguments)` for an approved row of THIS session, re-stamping `approved_at` to now (R2 N5). Refused unattended
    (the row stays as it is, nothing to call), from another session, or for a row that is not live."""
    if not attended:
        raise Refused(UNATTENDED + "; %s stays as it is" % oid)
    require_me(root)
    with store.lock(root, why="outbox.py call"):
        rows = store.load(root)
        row = store.find(rows, oid)
        if row is None or row.get("state") != "approved":
            raise Refused("%s is not approved (%s): approve it first" % (oid, "no such row" if row is None else row.get("state")))
        if not session_id or row.get("approved_session") != session_id:
            raise Refused("%s was approved in another session; approve it again in this one" % oid)
        if not in_window(row, now):
            raise Refused("%s's approval is older than %d s; approve it again" % (oid, APPROVAL_WINDOW_S))
        row["approved_at"] = store.now_instant(lambda: now)
        store.save(root, rows)
    return call_binding.call_args(row)


def cancel(root, oid):
    """approved or sending -> queued (design 10.5: a row left `sending` is resolved by detect or by the candidate). The row is
    never re-sent without a new approval; `approved_at` and `sending_at` stay for `stats`."""
    with store.lock(root, why="outbox.py cancel"):
        rows = store.load(root)
        row = store.find(rows, oid)
        if row is None or row.get("state") not in ("approved", "sending"):
            raise Refused("%s is not approved or sending (%s)" % (oid, "no such row" if row is None else row.get("state")))
        store.transition(row, "queued", approved_session=None)
        store.save(root, rows)
    return "%s back to queued: it is sent only after a new approval (check Sent first if it was sending)" % oid


def ready_lines(root):
    """design 10.4 step 1: the batch to approve, each queued `me` row with its id, person, address, subject and full text."""
    people = {p.get("id"): p for p in _jsonl(root, "people.jsonl")}
    out = []
    for r in store.load(root):
        if r.get("state") != "queued" or r.get("mode") != "me":
            continue
        out.append("%s · to %s <%s> · \"%s\"" % (r["id"], (people.get(r["person_id"]) or {}).get("name") or r["person_id"],
                                                ", ".join(r["to"]), r["subject"]))
        if r.get("reply_uid"):
            out.append("  answers message %s on %s; gmail-multi quotes that original below this text" % (r["reply_uid"],
                                                                                                     r["account"]))
        out.extend("  | " + line for line in (r.get("body") or "").splitlines())
    return out or ["Outbox: nothing queued to approve."]


def state_note(row, now):
    """The honest name of an in-flight state for `outbox.py list` (R2 N9)."""
    if row.get("state") == "sending":
        try:
            age = int((now - _instant(row.get("sending_at"))).total_seconds())
        except (TypeError, ValueError):
            age = -1
        return ("sending %d s: the guard passed it; the outcome depends on other hooks and the prompt. Not confirmed: check "
                "Sent (outbox.py detect), or outbox.py cancel %s" % (age, row["id"]))
    if row.get("state") == "approved":
        return "approved, %d s of %d left" % (max(0, APPROVAL_WINDOW_S - int(age_s(row, now) or 0)), APPROVAL_WINDOW_S)
    if row.get("state") == "queued":
        return "queued: approve it in an attended run (outbox.py list --ready)"
    return ""


def _live_match(rows, sha):
    return [r for r in rows if r.get("text_sha256") == sha and r.get("state") in store.HOLDS_TEXT]


def _gate(row, payload, now):
    if row.get("state") != "approved":
        return "outbox %s is %s, not approved: list it, approve it and call it in an attended run" % (row["id"], row["state"])
    if not payload.get("session_id") or row.get("approved_session") != payload.get("session_id"):
        return "outbox %s was approved in a different session (R2 N4): approve it again in this one" % row["id"]
    if not in_window(row, now):
        return "outbox %s's approval is older than %d s (or dated ahead of this clock): approve it again" % (
            row["id"], APPROVAL_WINDOW_S)
    return None


def decide(payload, now=None, lock_deadline_s=store.LOCK_DEADLINE_S):
    """E1's verdict: ("ask", reason) for a bound, approved, in-window, same-session call, having moved its row to `sending`;
    ("deny", reason) for everything else. Never raises; never "allow"."""
    try:
        return _decide(payload, now or datetime.datetime.now(datetime.timezone.utc), lock_deadline_s)
    except BaseException as exc:                          # noqa: BLE001 - the least reversible act fails CLOSED
        return "deny", "the send check failed (%s: %s); failing CLOSED" % (type(exc).__name__, exc)


def _decide(payload, now, lock_deadline_s):
    if not isinstance(payload, dict):
        return "deny", "hook payload unreadable"
    try:
        call_binding.tool_kind(payload.get("tool_name"))
    except call_binding.BindingError as exc:
        return "deny", str(exc)
    root = profile_from_cwd(payload.get("cwd"))
    if root is None:
        return "deny", "no jobsearch profile resolves from this hook's cwd %r (the remembered pointer is never used)" % (
            payload.get("cwd"),)
    try:
        require_me(root)
        sha = call_binding.bind(payload.get("tool_name"), payload.get("tool_input"))
    except (Refused, call_binding.BindingError) as exc:
        return "deny", str(exc)
    matches = _live_match(store.load(root), sha)
    if len(matches) != 1:
        return "deny", ("the call's text and recipients match %d listed outbox rows, not exactly one: only the exact listed "
                        "text, to the listed recipients, is sent" % len(matches))
    row = matches[0]
    why = _gate(row, payload, now)
    if why:
        return "deny", why
    try:
        members, _unregistered = mail_client.declared_accounts(root=root)
    except (mail_client.RegistryError, mail_client.RegistryPending) as exc:
        return "deny", "the sending account cannot be checked against gmail-multi's registry: %s" % exc
    account = payload["tool_input"]["account"].strip().lower()
    if account not in {a.lower() for a in members}:
        return "deny", "account %s is not one of this profile's registered addresses (%s)" % (account, ", ".join(members)
                                                                                              or "none")
    people = {p.get("id"): p for p in _jsonl(root, "people.jsonl")}
    why = call_binding.recipient_refusal(row, people, _jsonl(root, "messages.jsonl"))
    if why:
        return "deny", why
    try:
        with store.lock(root, deadline_s=lock_deadline_s, why="guard_mail_send E1"):
            rows = store.load(root)
            live = _live_match(rows, sha)
            why = "the row changed while the guard checked it" if len(live) != 1 or live[0]["id"] != row["id"] else _gate(
                live[0], payload, now)
            if why:
                return "deny", why
            store.transition(live[0], "sending", sending_at=store.now_instant(lambda: now))
            store.save(root, rows)
    except store.OutboxLocked as exc:
        return "deny", "the outbox lock was not had within %.0f s, so the row could not be moved to sending: %s" % (
            lock_deadline_s, exc)
    person = people.get(row["person_id"]) or {}
    return "ask", ("jobsearch %s · to %s <%s> · \"%s\" · text matches what was listed (%s…)" % (
        row["id"], person.get("name") or row["person_id"], ", ".join(row["to"]), row["subject"], sha[:4]))


def _failed(response):
    if isinstance(response, dict):
        if response.get("isError") is True or response.get("is_error") is True or "error" in response:
            return True
        text = json.dumps(response)
    else:
        text = response if isinstance(response, str) else json.dumps(response)
    return "SENT from " not in text                       # gmail-multi `_sent_report`: "SENT from", "REPLY SENT from"


def sent_hook(payload, now=None):
    """The PostToolUse entry: the `sending` row this call binds moves to `failed` on an error result; on a reported send it is
    noted and stays `sending` until detect records the Sent copy (module docstring). Returns the line to print, never raises."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        root = profile_from_cwd(payload.get("cwd")) if isinstance(payload, dict) else None
        if root is None:
            return "outbox sent-hook: no profile resolves from this hook's cwd; nothing recorded"
        sha = call_binding.bind(payload.get("tool_name"), payload.get("tool_input"))
        with store.lock(root, why="outbox.py --sent-hook"):
            rows = store.load(root)
            live = [r for r in rows if r.get("text_sha256") == sha and r.get("state") == "sending"]
            if len(live) != 1:
                return "outbox sent-hook: %d sending rows match this call; nothing recorded" % len(live)
            row, stamp = live[0], store.now_instant(lambda: now)
            if _failed(payload.get("tool_response")):
                store.transition(row, "failed", note="the send tool returned an error at %s" % stamp)
                line = "%s: the send tool returned an error; the row is failed (a retry is a new row and a new approval)"
            else:
                row["note"] = "the send tool reported a send at %s; detect records sent from the Sent copy" % stamp
                line = "%s: the send tool reported a send; outbox.py detect records it from the Sent copy"
            store.save(root, rows)
        return line % row["id"]
    except BaseException as exc:                          # noqa: BLE001 - a PostToolUse hook cannot block; say what failed
        return "outbox sent-hook: nothing recorded (%s: %s)" % (type(exc).__name__, exc)


def stats(root):
    """R2 N12: `sending_at - approved_at` per row that reached the guard, and the lapse count, so O18 can be revised from data."""
    lines, spans = [], []
    for r in store.load(root):
        if r.get("sending_at") and r.get("approved_at"):
            s = (_instant(r["sending_at"]) - _instant(r["approved_at"])).total_seconds()
            spans.append(s)
            lines.append("%s %s: sending_at - approved_at = %d s" % (r["id"], r["state"], s))
    try:
        lapses = sum(1 for rec in journal_read(root) if rec.get("event") == LAPSE_EVENT)
        lapse_line = "approval lapses journaled: %d (window %d s)" % (lapses, APPROVAL_WINDOW_S)
    except Exception as exc:                              # noqa: BLE001 - an unreadable journal is NOT CHECKED, never 0
        lapse_line = "approval lapses: NOT CHECKED (the journal cannot be read: %s)" % exc
    spans.sort()
    head = ("rows that reached the guard: %d · median %d s · max %d s" % (len(spans), spans[len(spans) // 2], spans[-1])
            if spans else "rows that reached the guard: 0")
    return [head] + lines + [lapse_line]
