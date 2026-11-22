"""detect: send detection for outbox rows, through the mailbox seam, with ONE matcher over both backends (jobsearch 0.91.0,
design-build-reach.md 9.3, R2 N1, N9, N10, N13b, N16).

Two phases, never interleaved (R2 N9):

    read_account(account, rows, now)   SEARCH, no lock held. For each staged or sending row it runs, through
                                       `mail_client.Mailbox(account)` (ImapMailbox under gmail-multi, BundleMailbox under a
                                       claude.ai connector), `in:sent to:<address> after:<the row's day, less one>` and reads each
                                       hit with `fetch_full`. Returns, per row, the candidates or a `NotChecked(reason)`.
    match(rows, found)                 THE matcher, pure: the same function decides for both backends.
    apply(root, rows, results, now)    LOCK, then WRITE: one outbox-lock hold for the check stamps, and for a sent match one
                                       run-lock hold around the whole sent write (touches, messages, drafts.md, outbox).

| match                                                                     | result                                        |
|---------------------------------------------------------------------------|-----------------------------------------------|
| exactly one candidate, same normalized subject (or the thread of reply_uid) | sent; the messages row takes the SENT body  |
| two or more candidates for one row, or one candidate for two rows         | ambiguous: listed, nothing recorded           |
| the search ran over the row's window and found none                       | none found                                    |
| the mailbox could not be read                                             | not checked: <reason>, the row untouched      |

"NOT CHECKED" IS NEVER "NONE FOUND". The reasons are `mail_client`'s own classes: `credential-missing` (a CredentialError),
`timeout` (MailTimeout), `no sent bundle` on a connector route with no kept bundle or one that does not reach back over the row's
window (R2 N16), and `N sent candidate(s) need a body fetch` when a bundle record that could be the sent copy has no fetched body,
or could not be evaluated at all (`mail_query` answered UNKNOWN). A candidate dated before the row's own day is not this draft's
sent copy and is set aside, so an older message with the same subject neither matches nor blocks.

DETECT NEVER CALLS `mail_client.sweep_accounts` AND NEVER WRITES A `swept` ROW (R2 N1). A narrow `in:sent to:` query is not
mailbox-wide coverage; recording it as such would advance `journal.covered_through` and silence every other thread's follow-up
check. Its own success is stamped on the outbox row instead (`last_checked_at`, `check_result`, `none_found_checks`), the way
`brief.py`'s D1 probe row records a probe and not a sweep. It still prints `connector_line`, or `skip_line` when the selection has
no backend.

THE SENT WRITE (design 9.1). One run-lock hold (`recording.store_files.take_lock`, wait `RUN_LOCK_WAIT_S`) with the outbox lock
nested once inside it, both taken AFTER every mailbox call: the `touches` row (status sent, `date` = the sent message's own
`Date:` day, so `reachouts.py --due` anchors 3B7 on the real send), the outbound `messages` row (the sent body), the drafts.md
entry's `**Status:**` line (`sent <date>`), and the outbox row (state sent, `date`, `touch_id`, text cleared). The validator runs
before and after; a new problem restores all four byte-for-byte. The BUILD fields of the brief ledger row `draft_ref` names
(`BUILD_FIELDS`, R2 N10) are copied onto the touch when the caller supplies that row (`ledger_lookup`).

Capability module of `outbox.py`. Python 3.9+, standard library only."""

import collections
import datetime
import hashlib
import os
import re

import _atomic
import _tree
import mail_client
import mail_query
from recording import profile_paths as _paths
from recording.ids import mint_touch_id
from recording.persons import _load_involvements
from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.store_files import LockError, _load_or_empty, release_lock, save_atomic, take_lock
from sending import outbox_store as store

RUN_LOCK_WAIT_S = 3
# R2 N10: the BUILD step's fields, persisted on the brief ledger row (B4) and copied onto the sent touch under the same names.
# B4b: all nine of `reach/build.step_for` (data_model `briefs.build`): without `touch_type` a side-door ask was written
# `first-touch` and the validator rolled the sent write back (`build_kind 'side-door' belongs on a intro-request touch`).
BUILD_FIELDS = ("build_kind", "play_step", "touch_type", "opp_id", "plan_id", "trigger_kind", "trigger_ref", "object_person_id",
                "object_company_id")
# mail_query's after:/before: day boundary is taken in the account's zone (UTC-12..UTC+14): a sent copy of a draft made on day D
# is no earlier than D's midnight in the earliest zone.
_ZONE_SLACK_HOURS = 14


class _Record(object):
    """A small value object: positional arguments name `FIELDS` in order."""
    FIELDS = ()

    def __init__(self, *values):
        if len(values) != len(self.FIELDS):
            raise TypeError("%s takes %d values" % (type(self).__name__, len(self.FIELDS)))
        for k, v in zip(self.FIELDS, values):
            setattr(self, k, v)

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join("%s=%r" % (k, getattr(self, k)) for k in self.FIELDS))


class Candidate(_Record):
    """One message a search found in Sent."""
    FIELDS = ("account", "uid", "subject", "body", "body_known", "sent_at", "thread_refs")


class NotChecked(_Record):
    """A row whose mailbox could not be read: never a miss."""
    FIELDS = ("reason",)


class Result(_Record):
    """The matcher's answer for one row: kind is sent, ambiguous, none-found or not-checked."""
    FIELDS = ("kind", "reason", "candidate", "candidates", "edited")

_PREFIX_RE = re.compile(r"^\s*(?:(?:re|fwd?|aw|wg)\s*:\s*)+", re.I)
_ENTRY_RE = re.compile(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", re.M | re.S)
_BRIEF_RE = re.compile(r"^\*\*Brief:\*\*\s*(.+?)\s*$", re.M | re.I)
_STATUS_RE = re.compile(r"^\*\*Status:\*\*.*$", re.M | re.I)
_TRIGGER_OPP_RE = re.compile(r"^\*\*Triggered by:\*\*\s*opp:(\S+)", re.M | re.I)


def anchor_day(row):
    """The row's own day: the day it was staged, or the day the guard passed it (`sending_at`)."""
    raw = row.get("staged_on") or str(row.get("sending_at") or "")[:10]
    return datetime.date.fromisoformat(raw)


def earliest(row):
    d = anchor_day(row)
    return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc) - datetime.timedelta(hours=_ZONE_SLACK_HOURS)


def search_query(row):
    """`in:sent to:<address> after:<day less one>`: only `in`, `to` and `after`, all in mail_query's grammar (READ)."""
    after = anchor_day(row) - datetime.timedelta(days=1)
    return "in:sent to:%s after:%s" % (row["to"][0], after.strftime("%Y/%m/%d"))


def norm_subject(s):
    return " ".join(_PREFIX_RE.sub("", s or "").split()).casefold()


def norm_body(s):
    lines = (s or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(l.rstrip() for l in lines).strip()


def _sha(s):
    return hashlib.sha256(norm_body(s).encode("utf-8")).hexdigest()


def _reason(exc):
    if isinstance(exc, mail_client.BundleError):
        return "no sent bundle"
    if isinstance(exc, mail_client.ConnectorNotSelected):
        return "connector not selected"
    if isinstance(exc, mail_client.MailTimeout):
        return "timeout"
    if isinstance(exc, mail_client.CredentialError):
        return "credential-missing"
    return mail_client._classify_failure("%s: %s" % (type(exc).__name__, exc))


def _thread_refs(msg, rec):
    refs = set()
    if rec is not None:
        refs.update([rec.get("in_reply_to") or ""] + list(rec.get("references") or []))
    elif msg is not None:
        for h in ("In-Reply-To", "References"):
            refs.update(str(msg.get(h) or "").split())
    refs.discard("")
    return frozenset(refs)


def _bundle_record(mb, uid):
    b = getattr(mb, "bundle", None)
    key = b.by_uid.get(str(uid)) if b is not None else None
    return b.by_key.get(key) if key else None


def _unknown_count(mb, query, row, now):
    """Bundle records `mail_query` cannot answer for this query (UNKNOWN), dated on or after the row's day. IMAP: 0, Gmail answers."""
    if not isinstance(mb, mail_client.BundleMailbox):
        return 0
    floor = earliest(row)
    n = 0
    for rec in mb.bundle.records:
        if mail_query.evaluate(query, rec, now) is None:
            try:
                when = datetime.datetime.fromisoformat(str(rec.get("date")).replace("Z", "+00:00"))
            except ValueError:
                when = None
            n += 1 if (when is None or when.tzinfo is None or when >= floor) else 0
    return n


def _covers(mb, row):
    """A bundle must reach back over the row's whole window (R2 N16); IMAP asks Gmail itself and always does."""
    if not isinstance(mb, mail_client.BundleMailbox):
        return True
    since = earliest(row) - datetime.timedelta(days=1)
    cov = mb.coverage(since)
    return cov.ok_from is not None and cov.ok_from <= since


def _candidates(mb, account, row, now):
    query = search_query(row)
    if not _covers(mb, row):
        return NotChecked("no sent bundle")
    uids = mb.search(query)
    unknown = _unknown_count(mb, query, row, now)
    out, need_body = [], unknown
    for uid in uids:
        msg = mb.fetch_full(uid)
        if msg is None:
            return NotChecked("sent message %s could not be fetched" % uid)
        sent_at = mail_client.header_date(msg)
        if sent_at is None:
            return NotChecked("sent message %s has no readable Date header" % uid)
        if sent_at < earliest(row):
            continue
        rec = _bundle_record(mb, uid)
        known = rec is None or rec.get("body_text") is not None
        out.append(Candidate(account, str(uid), mail_client.decode_header_value(msg.get("Subject")),
                             mail_client.body_text(msg) if known else None, known, sent_at, _thread_refs(msg, rec)))
    return (out, need_body)


def read_account(account, rows, now, opener=None):
    """Phase 1 for one account: `{row id: (candidates, unknown) | NotChecked}`. No lock is held, nothing is written."""
    opener = opener or mail_client.Mailbox
    found = {}
    try:
        with opener(account) as mb:
            for row in rows:
                parent = None
                if row.get("reply_uid"):
                    head = mb.fetch_headers(row["reply_uid"])
                    parent = str(head.get("Message-ID") or "").strip() if head is not None else None
                got = _candidates(mb, account, row, now)
                found[row["id"]] = got if isinstance(got, NotChecked) else (got[0], got[1], parent)
    except Exception as exc:  # noqa: BLE001 -- every failure is a classified NOT CHECKED, never a miss
        # a mailbox that failed part-way has not been read: every row of this account is NOT CHECKED, none half-answered
        return {row["id"]: NotChecked(_reason(exc)) for row in rows}
    return found


def match(rows, found):
    """THE matcher (one, for both backends). `found` is `read_account`'s answer, merged over accounts. -> {row id: Result}."""
    hits, results = {}, {}
    for row in rows:
        got = found.get(row["id"], NotChecked("not searched"))
        if isinstance(got, NotChecked):
            results[row["id"]] = Result("not-checked", got.reason, None, (), False)
            continue
        cands, unknown, parent = got
        want = norm_subject(row.get("subject"))
        mine = [c for c in cands if norm_subject(c.subject) == want or (parent and parent in c.thread_refs)]
        blind = unknown + sum(1 for c in mine if not c.body_known)
        if blind:
            results[row["id"]] = Result("not-checked", "%d sent candidate%s need a body fetch"
                                        % (blind, "" if blind == 1 else "s"), None, tuple(mine), False)
        elif not mine:
            results[row["id"]] = Result("none-found", None, None, (), False)
        elif len(mine) > 1:
            results[row["id"]] = Result("ambiguous", "%d sent messages match one draft" % len(mine), None, tuple(mine), False)
        else:
            hits.setdefault((mine[0].account.lower(), mine[0].uid), []).append(row["id"])
            results[row["id"]] = Result("sent", None, mine[0], tuple(mine), _sha(mine[0].body) != _sha(row.get("body")))
    for key, ids in hits.items():
        if len(ids) > 1:
            for rid in ids:
                c = results[rid].candidate
                results[rid] = Result("ambiguous", "one sent message matches %d drafts (%s)" % (len(ids), ", ".join(ids)),
                                      None, (c,), False)
    return results


def detect(root, rows, now, opener=None, out=print):
    """Phases 1 and 2 of the matcher for every DETECTABLE row: connector line, per-account search, one match. -> {id: Result}."""
    todo = [r for r in rows if r.get("state") in store.DETECTABLE]
    try:
        connector = mail_client.selected_connector(root)
    except ValueError as exc:
        out("!! SEND DETECTION NOT CHECKED: %s" % exc)
        return {r["id"]: Result("not-checked", "connector selection unreadable", None, (), False) for r in todo}
    if connector != mail_client.GMAIL_MULTI and not mail_client.is_bundle_backed(root):
        out(mail_client.skip_line(connector))
        return {r["id"]: Result("not-checked", "no-backend", None, (), False) for r in todo}
    out(mail_client.connector_line(connector))
    found = {}
    by_account = collections.OrderedDict()
    for r in todo:
        by_account.setdefault(r["account"], []).append(r)
    for account, group in by_account.items():
        found.update(read_account(account, group, now, opener))
    return match(todo, found)


# ── phase 2: lock, then write ───────────────────────────────────────────────────────────────────────────────────────────────

def drafts_path(root):
    return _tree.path(root, "drafts")


def entries_citing(text, draft_ref):
    """`[(start, end, title, body)]` for every drafts.md entry whose `**Brief:**` line is `draft_ref`."""
    out = []
    for m in _ENTRY_RE.finditer(text or ""):
        b = _BRIEF_RE.search(m.group(2))
        if b and b.group(1).strip() == draft_ref:
            out.append((m.start(2), m.end(2), m.group(1).strip(), m.group(2)))
    return out


def mark_sent(text, draft_ref, line):
    """drafts.md with the ONE entry citing `draft_ref` given the Status line `line` (rewritten, or inserted after the Brief
    line). `(text, None)` unchanged when no entry cites it; `(None, why)` when two do."""
    hits = entries_citing(text, draft_ref)
    if not hits:
        return text, None
    if len(hits) > 1:
        return None, "%d drafts.md entries cite %s" % (len(hits), draft_ref)
    start, end, _title, body = hits[0]
    if _STATUS_RE.search(body):
        body = _STATUS_RE.sub(lambda _m: line, body, count=1)
    else:
        b = _BRIEF_RE.search(body)
        body = body[:b.end()] + "\n" + line + body[b.end():]
    return text[:start] + body + text[end:], None


def _opp_anchor(entry_body, person_id, involvements):
    m = _TRIGGER_OPP_RE.search(entry_body or "")
    opp = m.group(1) if m else None
    if opp and any(i.get("person_id") == person_id and i.get("opp_id") == opp for i in involvements):
        return opp
    return None


def _touch(row, cand, touches, msgs, person, opp_id, ledger_row, message_id):
    pid = row["person_id"]
    earlier = any(t.get("person_id") == pid and t.get("status") == "sent" for t in touches) or any(
        m.get("person_id") == pid and m.get("direction") == "outbound" for m in msgs)
    t = {"id": mint_touch_id(pid, touches), "person_id": pid, "opp_id": opp_id, "channel_id": None,
         "object_person_id": None, "object_company_id": None, "status": "sent", "date": _day(cand.sent_at),
         "medium": row["medium"], "to": person.get("name") or pid, "outcome": "awaiting",
         "touch_type": "reply" if row.get("reply_uid") else ("unknown" if earlier else "first-touch"),   # B4c: never 3B7's anchor
         "recipient_role": "unknown", "address_status": "unknown",
         "delivery": "unknown", "message_ref": message_id}
    for f in BUILD_FIELDS:
        if ledger_row and ledger_row.get(f) is not None:
            t[f] = ledger_row[f]
    return t


def _day(instant):
    return instant.astimezone().date().isoformat()


def _snapshot(paths):
    out = {}
    for p in paths:
        try:
            with open(p, "rb") as fh:
                out[p] = fh.read()
        except FileNotFoundError:
            out[p] = None
    return out


def _restore(snap):
    for p, blob in snap.items():
        if blob is None:
            if os.path.exists(p):
                os.unlink(p)
        else:
            with open(p, "wb") as fh:
                fh.write(blob)


def _sent_write(root, row, cand, ledger_row, checked_at):
    """Inside both locks: write the four stores for one sent match, validator before and after, all-or-nothing."""
    data = os.path.join(root, "data")
    touches, msgs = _load_or_empty("touches"), _load_or_empty("messages")
    people = {p.get("id"): p for p in _load_or_empty("people")}
    dpath = drafts_path(root)
    try:
        with open(dpath, encoding="utf-8") as fh:
            dtext = fh.read()
    except FileNotFoundError:
        dtext = None
    hits = entries_citing(dtext, row["draft_ref"])
    entry_body = hits[0][3] if len(hits) == 1 else ""
    opp_id = _opp_anchor(entry_body, row["person_id"], _load_involvements())
    tag = "mail:%s:%s" % (cand.account, cand.uid)
    twin = next((m for m in msgs if m.get("source") == tag), None)
    message_id = twin["id"] if twin else "msg-outbox-%s" % row["id"]
    touch = _touch(row, cand, touches, msgs, people.get(row["person_id"]) or {}, opp_id, ledger_row, message_id)
    status = "**Status:** sent %s (seen in Sent; outbox %s)" % (touch["date"], row["id"])
    new_text, why = mark_sent(dtext, row["draft_ref"], status) if dtext is not None else (None, None)
    if why:
        return "%s: NOT RECORDED: %s" % (row["id"], why)
    snap = _snapshot([os.path.join(data, "touches.jsonl"), os.path.join(data, "messages.jsonl"), dpath, store.path(root)])
    pre_rc, _o, _e, pre = validate(data)
    if not twin:
        msgs.append({"id": message_id, "opp_id": opp_id, "channel_id": None, "person_id": row["person_id"],
                     "direction": "outbound", "medium": row["medium"], "sent_on": touch["date"], "from": row["account"],
                     "to": row["to"][0], "subject": cand.subject, "body": cand.body, "source": tag, "variant": None,
                     "answers": None})
        save_atomic("messages", msgs)
    touches.append(touch)
    save_atomic("touches", touches)
    if new_text is not None and new_text != dtext:
        _atomic.write_text(dpath, new_text)
    rows = store.load(root)
    live = store.find(rows, row["id"])
    store.transition(live, "sent", date=touch["date"], touch_id=touch["id"], last_checked_at=checked_at, check_result="sent")
    store.save(root, rows)
    rc, vout, verr, post = validate(data)
    if rc != 0 and not (pre_rc != 0 and new_problems(pre, post) == []):
        _restore(snap)
        return "%s: NOT RECORDED: the sent write broke the store; rolled back\n  %s" % (
            row["id"], "\n  ".join(_diagnostic_lines(rc, vout, verr)))
    return "%s: sent %s, recorded as touch %s%s" % (row["id"], touch["date"], touch["id"],
                                                     "" if new_text is not None else " (no drafts.md entry to retire)")


def _stamp_checks(rows, results, checked_at):
    for r in rows:
        res = results.get(r["id"])
        if res is None or res.kind not in ("none-found", "ambiguous") or r.get("state") not in store.DETECTABLE:
            continue
        r["last_checked_at"] = checked_at
        r["check_result"] = res.kind
        r["none_found_checks"] = (int(r.get("none_found_checks") or 0) + 1) if res.kind == "none-found" else 0


def apply(root, results, now, ledger_lookup=None, out=print, run_lock_wait=RUN_LOCK_WAIT_S):
    """Phase 2: every mailbox call is already over. Stamps successful checks under the outbox lock; a sent match takes the run
    lock ONCE, with the outbox lock nested ONCE, around every sent write. -> list of printed lines."""
    checked_at = store.now_instant(lambda: now)
    sent = [rid for rid, res in results.items() if res.kind == "sent"]
    lines = []
    if sent:
        _paths.bind(root)
        try:
            take_lock("outbox.py detect (sent write)", wait=run_lock_wait)
        except LockError as exc:
            return ["NOT RECORDED: the run lock was not free within %d s (%s); the sent matches stay staged, the next detect "
                    "records them" % (run_lock_wait, exc)]
    try:
        with store.lock(root, why="outbox.py detect"):
            rows = store.load(root)
            _stamp_checks(rows, results, checked_at)
            store.save(root, rows)
            for rid in sent:
                live = store.find(store.load(root), rid)
                if live is None or live.get("state") not in store.DETECTABLE:
                    lines.append("%s: changed state while detect searched; not recorded" % rid)
                    continue
                ledger_row = ledger_lookup(root, live["draft_ref"]) if ledger_lookup else None
                lines.append(_sent_write(root, live, results[rid].candidate, ledger_row, checked_at))
    finally:
        if sent:
            release_lock()
    return lines


class NotStageable(ValueError):
    """A drafts.md entry whose text cannot be staged as one message (`quoted_body`, moved from `outbox.py`)."""


def quoted_body(body):
    """The one `> ` quoted message of an entry, paragraphs joined by a blank line. A campaign entry (`###`) is refused."""
    if re.search(r"^###", body, re.M):
        raise NotStageable("it is a multi-recipient entry (### headings): stage one message per entry")
    runs, cur = [], []
    for line in body.splitlines():
        if line.lstrip().startswith(">"):
            cur.append(line.lstrip()[1:].lstrip() if line.lstrip()[1:2] == " " else line.lstrip()[1:])
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if len(runs) != 1:
        raise NotStageable("it has %d quoted bodies, not one" % len(runs))
    return "\n".join(runs[0]).strip()


def _entry_body(text, title):
    for m in _ENTRY_RE.finditer(text or ""):
        if m.group(1).strip() == title:
            return m.group(2)
    return ""


def describe(row, res, today, unobserved_days):
    """One line per detectable row. A row never checked since staging says so, with this run's reason."""
    since = row.get("staged_on") or str(row.get("sending_at") or "")[:10]
    head = "%s %s %s <%s>" % (row["id"], row["state"], since, row["to"][0])
    if res.kind == "not-checked":
        last = row.get("last_checked_at")
        return "%s · not checked%s: %s" % (head, (" since %s" % last[:10]) if last else " since staging", res.reason)
    if res.kind == "ambiguous":
        return "%s · ambiguous, nothing recorded: %s (%s)" % (head, res.reason, ", ".join(
            "%s %s" % (c.uid, c.sent_at.date()) for c in res.candidates))
    if res.kind == "none-found":
        age = (today - datetime.date.fromisoformat(since)).days
        tail = " · send unobserved (%d days)" % age if age >= unobserved_days else ""
        return "%s · none found (%d successful check%s)%s" % (head, (row.get("none_found_checks") or 0) + 1,
                                                              "" if not row.get("none_found_checks") else "s", tail)
    return "%s · found in Sent%s" % (head, " (text edited before sending)" if res.edited else "")
