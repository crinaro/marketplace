#!/usr/bin/env python3
"""outbox.py -- the outbox's verbs: stage a draft in the mailbox, detect that it was sent, list and discard rows (jobsearch 0.91.0,
design-build-reach.md 9; the store is `sending/outbox_store.py`, detection `sending/detect.py`).

    outbox.py stage <brief id>... [--account <address>]    stage those drafts (`you` mode): one `staged` row each, and the
                                                           exact draft-tool call to make, printed
    outbox.py stage --all-ready [--account <address>]      every sendable email draft that has no row yet
    outbox.py detect                                       send detection over the staged and sending rows
    outbox.py list [--ready]                               every open row and its state; --ready: the queued `me` batch, full text
    outbox.py discard <id>                                 a staged row the candidate will not send (the mailbox draft stays theirs)
    outbox.py approve <id>... --attended                   B7, email `me` only, attended only: queued -> approved, this session
    outbox.py call <id> --attended                         the exact send call to make, re-stamping approved_at (R2 N5)
    outbox.py cancel <id>  ·  --stats  ·  --sent-hook      back to queued · R2 N12 · the PostToolUse entry (hooks.json)

EMAIL `me` (B7, `sending/approval.py`; owner amendment 2026-11-21: ATTENDED ONLY). Under `actions.modes.email-send: me` `stage`
makes `queued` rows and prints no draft call. An unattended run (no `--attended`; attended is never inferred) leaves them queued
for the next attended session and calls nothing. Every verb first reverts an approval older than 600 s to queued, journaled.

STAGING (design 9.2, owner O7: on request; `auto` is an opt-in whose key is B7's). A draft is staged only when it is an `email-cold`
or `email-reply` draft that `precondition.py` reports `sendable` (so its **To:** and **Brief:** resolve and no precondition holds
it), its recipient has a recorded address, it carries a `**Subject:**` line (a subject is always explicit, design 10.5) and exactly
one quoted body, and no row exists for it yet. The session then makes the ONE printed call: `gmail_create_draft` under gmail-multi,
or the selected claude.ai connector's own published draft tool (`mail_connectors.py` `draft_tool`); a connector that publishes none
refuses with the reason. gmail-multi cannot delete a draft, so stage only text that is final. Nothing here sends.

An `email-reply` draft (B4c) also needs `**In-reply-to:** <account>:<uid>` (`outbox_store.in_reply_to`, strict): a stored message
from the recipient on that mailbox, which the row goes from, `reply_uid` set; the call gains `reply_to_uid` (gmail-multi only). A
malformed line is refused; a reply with no line is not staged (reason printed), never sent new. DETECTION writes no `swept` row,
never advances sweep coverage (R2 N1): `sending/detect.py`.

Python 3.9+, standard library only."""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(os.path.realpath(__file__))))
from _root import profile_root  # noqa: E402
import config_keys  # noqa: E402
import mail_client  # noqa: E402
import mail_connectors  # noqa: E402
from ledger import brief_rows as _ledger  # noqa: E402
from sending import approval as _approval  # noqa: E402
from sending import detect as _detect  # noqa: E402
from sending.detect import _entry_body, describe, quoted_body  # noqa: E402 -- moved there in B7
from sending import modes as _modes  # noqa: E402
from sending import outbox_store as store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
GMAIL_MULTI_DRAFT_TOOL = "gmail_create_draft"
STAGEABLE_MEDIA = ("email-cold", "email-reply")
TO_RE = re.compile(r"^\*\*To:\*\*\s*contact:(\S+)\s*$", re.M | re.I)
SUBJECT_RE = re.compile(r"^\*\*Subject:\*\*\s*(.+?)\s*$", re.M | re.I)


class Refused(Exception):
    pass


def _jsonl(root, name):
    try:
        with open(os.path.join(root, "data", name), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        return []


def sendability(root):
    """`{title: report row}` for drafts.md from `precondition.py --json`, the one owner of sendability (run, not imported)."""
    env = dict(os.environ, CLAUDESEARCH_ROOT=root)
    r = subprocess.run([sys.executable, os.path.join(HERE, "precondition.py"), "--json"], capture_output=True, text=True,
                       env=env, timeout=120)
    text = r.stdout[r.stdout.find("["):] if "[" in r.stdout else ""
    try:
        rows = json.loads(text)
    except ValueError:
        raise Refused("precondition.py --json could not be read (exit %d): %s" % (r.returncode, (r.stderr or r.stdout)[-300:]))
    return {x["title"]: x for x in rows if x.get("file", "").endswith("drafts.md")}


def build_row(root, draft_ref, account, rows, today, states, people, mode="you"):
    """The `staged` row for the entry citing `draft_ref`, or `Refused` naming why it cannot be staged."""
    text = open(_detect.drafts_path(root), encoding="utf-8").read() if os.path.exists(_detect.drafts_path(root)) else ""
    hits = _detect.entries_citing(text, draft_ref)
    if len(hits) != 1:
        raise Refused("%d drafts.md entries cite %s" % (len(hits), draft_ref))
    _s, _e, title, body = hits[0]
    if any(r.get("draft_ref") == draft_ref and r.get("state") not in ("discarded", "failed") for r in rows):
        raise Refused("it already has an outbox row")
    rep = states.get(title) or {}
    if rep.get("medium") not in STAGEABLE_MEDIA:
        raise Refused("its medium is %r; only %s drafts are staged" % (rep.get("medium"), ", ".join(STAGEABLE_MEDIA)))
    if rep.get("state") != "sendable":
        raise Refused("precondition.py reports it %r (%s)" % (rep.get("state"), rep.get("why", "")))
    m, subj = TO_RE.search(body), SUBJECT_RE.search(body)
    person = people.get(m.group(1)) if m else None
    if person is None or person.get("status") == "merged":
        raise Refused("its **To:** does not name a living people row")
    addr = (person.get("email") or "").strip()
    if not store.ADDRESS_RE.match(addr):
        raise Refused("%s has no recorded email address" % person.get("id"))
    if not subj:
        raise Refused("it has no **Subject:** line (a subject is always explicit)")
    reply = store.in_reply_to(body)                       # B4c: OutboxError, loud, on a malformed line
    if (rep["medium"] == "email-reply") != (reply is not None):
        raise Refused("an email-reply draft with no **In-reply-to:** <account>:<uid> line is not staged (never as a new send)"
                      if reply is None else "a %s draft carries no **In-reply-to:** line" % rep["medium"])
    account = pick_account(account, reply[0] if reply else None)
    if reply:                                             # OutboxError: an unknown uid, or not from this recipient
        store.check_reply(_jsonl(root, "messages.jsonl"), account, reply[1], [addr])
    row = {"id": store.mint_id(rows), "person_id": person["id"], "draft_ref": draft_ref, "medium": rep["medium"],
           "mode": mode, "account": account, "to": [addr], "cc": [], "bcc": [], "subject": subj.group(1),
           "body": quoted_body(body), "reply_uid": reply[1] if reply else None}
    row.update({"state": "queued", "queued_on": today} if mode == "me" else {"state": "staged", "staged_on": today})
    row["text_sha256"] = store.row_sha256(row)
    problems = store.check_row(row)
    if problems:
        raise Refused("; ".join(problems))
    return row, person


def draft_call(root, row):
    """`(tool, args)`: the one call the session makes to put the row's text in the mailbox's drafts."""
    connector = mail_client.selected_connector(root)
    if connector == mail_client.GMAIL_MULTI:
        args = {"account": row["account"], "to": row["to"], "cc": row["cc"], "subject": row["subject"], "body": row["body"]}
        return GMAIL_MULTI_DRAFT_TOOL, dict(args, reply_to_uid=row["reply_uid"]) if row.get("reply_uid") else args
    if row.get("reply_uid"):
        raise Refused("%s publishes no reply argument for its draft tool, so a reply is staged only under gmail-multi"
                      % mail_connectors.label(connector))
    tool = (mail_connectors.row(connector) or {}).get("draft_tool")
    if not tool:
        raise Refused("%s publishes no draft tool, so staging is refused there" % mail_connectors.label(connector))
    return tool, {"to": row["to"], "subject": row["subject"], "body": row["body"],
                  "_note": "argument names per %s's own tool schema" % mail_connectors.label(connector)}


def pick_account(given, reply_account=None):
    """`--account`, else the only registered one; a reply goes from the mailbox holding the message it answers."""
    if reply_account and given and given.lower() != reply_account.lower():
        raise Refused("the answered message is in %s; a reply goes from that mailbox, not %s" % (reply_account, given))
    given = given or reply_account
    accounts = mail_client.configured_accounts()
    if given:
        if given.lower() not in {a.lower() for a in accounts}:
            raise Refused("%s is not one of this profile's registered addresses (%s)" % (given, ", ".join(accounts) or "none"))
        return given
    if len(accounts) != 1:
        raise Refused("name the mailbox with --account (registered: %s)" % (", ".join(accounts) or "none"))
    return accounts[0]


def cmd_stage(root, refs, all_ready, account):
    try:
        mode = _modes.resolve(_approval.load_config(root), _modes.EMAIL_SEND)
        states = sendability(root)                        # the mailbox is picked per draft: a reply names its own
    except (Refused, ValueError, _approval.Refused) as exc:
        print("REFUSED: %s" % exc)
        return 1
    people = {p.get("id"): p for p in _jsonl(root, "people.jsonl")}
    if all_ready:
        text = open(_detect.drafts_path(root), encoding="utf-8").read() if os.path.exists(_detect.drafts_path(root)) else ""
        refs = [b for (_t, rep) in states.items() if rep.get("state") == "sendable" and rep.get("medium") in STAGEABLE_MEDIA
                for b in re.findall(r"^\*\*Brief:\*\*\s*(\S+)", _entry_body(text, _t), re.M)]
    if not refs:
        print("Nothing to stage.")
        return 0
    today, rc = datetime.date.today().isoformat(), 0
    for ref in refs:
        try:
            with store.lock(root, why="outbox.py stage"):
                rows = store.load(root)
                row, person = build_row(root, ref, account, rows, today, states, people, mode)
                tool, args = draft_call(root, row) if mode == "you" else (None, None)
                rows.append(row)
                store.save(root, rows)
        except (Refused, store.OutboxError, store.OutboxLocked, ValueError) as exc:
            print("NOT STAGED %s: %s" % (ref, exc))
            rc = 1
            continue
        print("%s %s: %s <%s> \"%s\"" % (row["id"], row["state"], person.get("name") or person["id"], row["to"][0],
                                         row["subject"]))
        print("  CALL %s %s" % (tool, json.dumps(args, ensure_ascii=False)) if tool else "  " + _approval.state_note(row, None))
    return rc


def cmd_detect(root):
    try:
        rows = store.load(root)
        cfg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8")) if os.path.exists(
            os.path.join(root, "config.json")) else {}
        days = config_keys.resolve_int(cfg, config_keys.NETWORK_DRAFT_UNOBSERVED_DAYS)
    except (store.OutboxError, ValueError) as exc:
        print("!! SEND DETECTION NOT CHECKED: %s" % exc)
        return 1
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    results = _detect.detect(root, rows, now)
    if not results:
        print("Send detection: no staged or sending rows.")
        return 0
    by_id = {r["id"]: r for r in rows}
    for rid, res in results.items():
        print(describe(by_id[rid], res, now.astimezone().date(), days))
    try:   # R2 N10: the BUILD step is the cited ledger row's nested `build`, never the row (ledger/brief_rows.build_step)
        for line in _detect.apply(root, results, now, ledger_lookup=_ledger.build_step):
            print(line)
    except (store.OutboxLocked, store.OutboxError) as exc:
        print("NOT RECORDED: %s" % exc)
        return 1
    n_nc = sum(1 for r in results.values() if r.kind == "not-checked")
    print("Send detection: %d checked, %d not checked." % (len(results) - n_nc, n_nc))
    return 0


def cmd_list(root, now):
    rows = [r for r in store.load(root) if r.get("state") in store.HOLDS_TEXT]
    if not rows:
        print("Outbox: no open rows.")
    for r in rows:
        print("%s %-8s %s <%s> %s · last check: %s%s" % (r["id"], r["state"], r.get("staged_on") or r.get("queued_on") or "",
                                                       r["to"][0], r["draft_ref"], r.get("last_checked_at") or "never",
                                                       (" · " + _approval.state_note(r, now)) if r["state"] != "staged" else ""))
    return 0


def cmd_discard(root, oid):
    with store.lock(root, why="outbox.py discard"):
        rows = store.load(root)
        row = store.find(rows, oid)
        if row is None:
            print("No outbox row %s." % oid)
            return 1
        store.transition(row, "discarded")
        store.save(root, rows)
    print("%s discarded (the draft in the mailbox, if any, stays yours to delete)." % oid)
    return 0


def dispatch(args, root, now):
    """One verb. Every verb first reverts a lapsed approval (R2 N12); `Refused` and store errors print REFUSED, exit 1."""
    for line in _approval.lapse(root, now):
        print(line)
    session = os.environ.get(_approval.SESSION_ENV)
    if args.stats:
        print("\n".join(_approval.stats(root)))
        return 0
    if args.verb == "stage":
        return cmd_stage(root, args.refs, args.all_ready, args.account)
    if args.verb == "detect":
        return cmd_detect(root)
    if args.verb == "list":
        return print("\n".join(_approval.ready_lines(root))) or 0 if args.ready else cmd_list(root, now)
    if args.verb == "approve":
        print("\n".join(_approval.approve(root, args.refs, args.attended, session, now)))
        return 0
    if args.verb is None or len(args.refs) != 1:
        print("usage: outbox.py %s <id>" % (args.verb or "<verb>"))
        return 2
    if args.verb == "call":
        tool, cargs = _approval.call(root, args.refs[0], args.attended, session, now)
        print("CALL %s %s" % (tool, json.dumps(cargs, ensure_ascii=False)))
        return 0
    if args.verb == "cancel":
        print(_approval.cancel(root, args.refs[0]))
        return 0
    return cmd_discard(root, args.refs[0])


def main(argv=None):
    ap = argparse.ArgumentParser(description="the outbox: stage, detect, list, discard, approve, call, cancel")
    ap.add_argument("verb", nargs="?", choices=("stage", "detect", "list", "discard", "approve", "call", "cancel"))
    ap.add_argument("refs", nargs="*", help="stage: brief ids; approve: outbox ids; discard, call, cancel: one outbox id")
    ap.add_argument("--attended", action="store_true", help="approve, call: the explicit attended form (never inferred)")
    ap.add_argument("--ready", action="store_true", help="list: the queued `me` rows to approve, with their full text")
    ap.add_argument("--stats", action="store_true", help="sending_at - approved_at per row and the lapse count")
    ap.add_argument("--sent-hook", dest="sent_hook", action="store_true", help="the PostToolUse entry (reads its payload)")
    ap.add_argument("--account", help="stage: the mailbox to stage in (default: the only registered one)")
    ap.add_argument("--all-ready", dest="all_ready", action="store_true",
                    help="stage: every sendable email draft with no outbox row")
    args = ap.parse_args(argv)
    if args.sent_hook:                                    # PostToolUse: the hook's cwd names the profile; exit 0 always
        try:
            print(_approval.sent_hook(json.load(sys.stdin)))
        except Exception as exc:                          # noqa: BLE001
            print("outbox sent-hook: payload unreadable (%s); nothing recorded" % exc)
        return 0
    try:
        return dispatch(args, profile_root(), datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0))
    except (_approval.Refused, store.OutboxError, store.OutboxLocked) as exc:
        print("REFUSED: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
