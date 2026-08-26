#!/usr/bin/env python3
"""The trigger and sequence joins for drafts and follow-up work. Public #27.

⭐ THE DEFECT THIS CLOSES (public #27, part C/D)
------------------------------------------------
Submitting an application CREATES work — ask a retained firm whether they hold a relationship
with that employer, chase after N days of silence. The data model had an applications[] array
and an outreach[] array on the same record and nothing expressing that one CAUSED the other.
MEASURED: the drafted-messages file referenced eight opportunity ids and NOT the one whose
application generated the single highest-value ask in it. The draft and its trigger sat in the
same repository, unlinked, and stayed correct only because a human remembered.

And a multi-step play — "part A sent, part B held until the connection is accepted" — was a
state machine living entirely in prose inside a markdown heading, so "which sequences are
unblocked today" (exactly the daily question) could not be asked at all.

This module is `precondition.py`'s shape applied to those two joins, deliberately: a named
field, a strict parser that refuses what it cannot read, and a resolver against data that
already exists. The record-side halves (`trigger_kind`/`trigger_ref`, `sequence_id`/
`sequence_step` on outreach[] rows and asks) are validated by `validate_data.py`; this module
owns the DRAFT-side fields and every cross-file question.

## The fields

Meta lines in a drafts.md / cover_letters.md entry, alongside `**Medium:**` and
`**Blocked until:**`:

    **Triggered by:** opp:meridian-vp-eng app:meridian-vp-eng-a1
    **Triggered by:** reply:msg-2026-08-12-004
    **Triggered by:** elapsed:2026-08-14
    **Triggered by:** manual
    **Sequence:** recruiter-reach step:2

`opp:` is an opportunity id. `app:` names an applications[] row on that opportunity by
`app_id` (or by date, for rows predating the app_id backfill); with exactly one application
on the record `app:` may be omitted and resolves to it — with several, omitting it is LOUD,
never guessed. `reply:` is a message id in data/messages.jsonl. `elapsed:` is the ISO date
the clock started. `manual` means a human decided with no recorded cause.

`**Sequence:**` groups a staged draft into a multi-step play with the outreach[] rows already
sent under the same `sequence_id`. ⭐ A sequence adds GROUPING, never a second way to spell a
hold — the hold on a staged step stays in `**Blocked until:**` and is resolved by
`precondition.py`; this module only reads that verdict back.

⚠️ An unparseable value is reported, never guessed (the precondition.py rule). `--check`
fails on an unreadable field or a dangling ref, so a typo surfaces at run start rather than
by a draft silently staying unlinked — which is the exact defect this exists to close.

## Sequence states (derived, with a terminal state — D2)

Per step: `sent` (an outreach row), or the draft's precondition state (`sendable` / `blocked`
/ `unresolved` / `unreadable`). Per sequence, from the lowest unsent step:

    unblocked    the next step is sendable NOW — the daily answer
    waiting      the next step is blocked on someone else
    unresolved   the next step's hold or link cannot be read — loud, never "waiting"
    complete     every known step is sent — TERMINAL; a sequence whose remaining drafts
                 were deleted is complete by construction, not stuck

Usage:
    python3 trigger.py                 # every draft's trigger/sequence link state
    python3 trigger.py --sequences     # sequences with per-step state; unblocked first
    python3 trigger.py --untriggered   # submitted applications no follow-up work names
    python3 trigger.py --json
    python3 trigger.py --check         # exit 1 on unreadable/dangling links

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import precondition

TRIGGER_FIELD_RE = re.compile(r"^\*\*Triggered by:\*\*\s*(.+?)\s*$", re.M | re.I)
SEQUENCE_FIELD_RE = re.compile(r"^\*\*Sequence:\*\*\s*(.+?)\s*$", re.M | re.I)
TOKEN_RE = re.compile(r"(opp|app|reply|elapsed|step)\s*:\s*([A-Za-z0-9_./#-]+)")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Application statuses that prove a submission happened and can therefore generate follow-up
# work. Mirrored from validate_data.SUBMITTED_APP_STATUS minus the closed outcomes: a
# rejected or withdrawn application generates no ask.
FOLLOWUP_APP_STATUS = ("submitted", "acknowledged", "advanced")


class TriggerError(ValueError):
    """Unparseable. Deliberately loud — see the module docstring."""


def parse_trigger(raw):
    """Field text -> {'kind': ..., 'opp': ..., 'ref': ...}. Raises TriggerError."""
    raw = (raw or "").strip()
    if raw.lower() == "manual":
        return {"kind": "manual", "opp": None, "ref": None}
    found = dict(TOKEN_RE.findall(raw))
    if "reply" in found:
        return {"kind": "reply", "opp": found.get("opp"), "ref": found["reply"]}
    if "elapsed" in found:
        if not DATE_RE.match(found["elapsed"]):
            raise TriggerError("elapsed:%r is not an ISO date — the clock has no start"
                              % found["elapsed"])
        return {"kind": "elapsed", "opp": found.get("opp"), "ref": found["elapsed"]}
    if "opp" in found:
        return {"kind": "application", "opp": found["opp"], "ref": found.get("app")}
    raise TriggerError(
        "no `opp:`, `reply:`, `elapsed:` or `manual` in %r — a trigger nobody can read "
        "looks linked and is not" % raw)


def parse_sequence(raw):
    """'<sequence_id> step:<n>' -> {'sequence_id': ..., 'step': int}. Raises TriggerError."""
    raw = (raw or "").strip()
    m = re.match(r"^([A-Za-z0-9_-]+)\s+step\s*:\s*(\d+)\s*$", raw)
    if not m:
        raise TriggerError("expected `<sequence_id> step:<n>`, got %r" % raw)
    sid, step = m.group(1), int(m.group(2))
    if not SLUG_RE.match(sid):
        raise TriggerError("sequence id %r must be a lowercase slug" % sid)
    if step < 1:
        raise TriggerError("step %d must be >= 1" % step)
    return {"sequence_id": sid, "step": step}


def load_jsonl(root, name):
    rows = []
    try:
        with open(os.path.join(root, "data", name), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def app_handles(opp):
    """Every handle a trigger may use for this record's applications: app_id and date."""
    out = {}
    for ap in opp.get("applications") or []:
        for h in (ap.get("app_id"), ap.get("date")):
            if isinstance(h, str) and h.strip():
                out[h] = ap
    return out


def resolve_trigger(t, opps_by_id, message_ids):
    """(ok, why). Evidence names what it resolved to; failure names what dangles."""
    if t["kind"] == "manual":
        return True, "manual — no recorded cause"
    if t["kind"] == "elapsed":
        return True, "clock started %s" % t["ref"]
    if t["kind"] == "reply":
        if t["ref"] in message_ids:
            return True, "reply to message %s" % t["ref"]
        return False, "reply:%s resolves to no message in data/messages.jsonl" % t["ref"]
    opp = opps_by_id.get(t["opp"])
    if opp is None:
        return False, "opp:%s resolves to no opportunity" % t["opp"]
    handles = app_handles(opp)
    if t["ref"] is None:
        apps = opp.get("applications") or []
        if len(apps) == 1:
            return True, "the one application on %s (%s)" % (t["opp"],
                                                             apps[0].get("date") or "undated")
        if not apps:
            return False, ("opp:%s has no applications[] row — a trigger naming an "
                           "application that is not there is the unlinked-draft defect "
                           "inverted" % t["opp"])
        return False, ("opp:%s has %d applications and no `app:` — which one? Ambiguity is "
                       "reported, never guessed" % (t["opp"], len(apps)))
    if t["ref"] in handles:
        ap = handles[t["ref"]]
        return True, "application %s on %s (%s)" % (t["ref"], t["opp"],
                                                    ap.get("status") or "?")
    return False, "app:%s resolves to no applications[] row on %s" % (t["ref"], t["opp"])


def entries(root, filename):
    """(title, body) per `## ` entry — same split as precondition.drafts_with_preconditions,
    duplicated (3 lines) rather than exported, so neither module's parse changes the other's."""
    try:
        import _tree
        with open(_tree.resolve_rel(root, filename), encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return []
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", md, re.M | re.S)]


def draft_rows(root, opps_by_id, message_ids):
    """One row per draft entry across precondition.FILES: its trigger link and sequence
    membership, each `linked`/`none`/`unlinked`/`unreadable` — states, never booleans."""
    rows = []
    for filename in precondition.FILES:
        for title, body in entries(root, filename):
            row = {"file": filename, "title": title,
                   "trigger": "none", "trigger_why": "no **Triggered by:** field",
                   "sequence": None, "step": None, "sequence_state": "none"}
            tm = TRIGGER_FIELD_RE.search(body)
            if tm:
                try:
                    t = parse_trigger(tm.group(1))
                    ok, why = resolve_trigger(t, opps_by_id, message_ids)
                    row["trigger"] = "linked" if ok else "unlinked"
                    row["trigger_why"] = why
                    row["trigger_kind"] = t["kind"]
                    row["trigger_opp"] = t["opp"]
                except TriggerError as e:
                    row["trigger"] = "unreadable"
                    row["trigger_why"] = str(e)
            sm = SEQUENCE_FIELD_RE.search(body)
            if sm:
                try:
                    s = parse_sequence(sm.group(1))
                    row["sequence"] = s["sequence_id"]
                    row["step"] = s["step"]
                    row["sequence_state"] = "member"
                except TriggerError as e:
                    row["sequence_state"] = "unreadable"
                    row["trigger_why"] = (row["trigger_why"] + "; sequence: " + str(e)
                                          if tm else "sequence: " + str(e))
            rows.append(row)
    return rows


def sequence_report(root, opps, drafts):
    """sequence_id -> {'steps': [...], 'state': ...}. Steps merge sent outreach[] rows and
    staged drafts; a draft step's own state is precondition.py's verdict, read back — never
    re-derived here."""
    pre = {(p["file"], p["title"]): p["state"] for p in precondition.report(root)}
    seqs = {}
    for opp in opps:
        for o in opp.get("outreach") or []:
            sid = o.get("sequence_id")
            if not sid:
                continue
            seqs.setdefault(sid, []).append({
                "step": o.get("sequence_step"), "kind": "outreach",
                "where": "%s outreach[]" % opp.get("id"),
                "state": "sent" if o.get("status") == "sent" else (o.get("status") or "?"),
                "date": o.get("date")})
    for d in drafts:
        if d.get("sequence") and d["sequence_state"] == "member":
            seqs.setdefault(d["sequence"], []).append({
                "step": d["step"], "kind": "draft",
                "where": "%s › %s" % (d["file"], d["title"][:60]),
                "state": pre.get((d["file"], d["title"]), "sendable")})
    out = {}
    for sid, steps in sorted(seqs.items()):
        steps.sort(key=lambda s: (s["step"] is None, s["step"] or 0))
        pending = [s for s in steps if s["state"] != "sent"]
        if not pending:
            state = "complete"          # TERMINAL — every known step went out (D2)
        elif pending[0]["state"] == "sendable":
            state = "unblocked"
        elif pending[0]["state"] == "blocked":
            state = "waiting"
        else:
            state = "unresolved"        # loud: an unreadable step must never read as waiting
        out[sid] = {"steps": steps, "state": state}
    return out


def untriggered_applications(root, opps, drafts, asks):
    """Submitted applications that NO follow-up work names as its trigger — the feed for
    'you applied to X, so ask Y': generated, not remembered."""
    named = set()          # (opp_id, handle) pairs any trigger anywhere points at
    for opp in opps:
        for o in opp.get("outreach") or []:
            if o.get("trigger_kind") == "application" and o.get("trigger_ref"):
                named.add((opp.get("id"), o["trigger_ref"]))
    for a in asks:
        if a.get("trigger_kind") == "application" and a.get("trigger_ref"):
            named.add((a.get("opp_id"), a["trigger_ref"]))
    for d in drafts:
        if d.get("trigger") == "linked" and d.get("trigger_kind") == "application":
            # a linked draft names a resolvable app; count every handle of that opp's rows
            named.add((d.get("trigger_opp"), "*"))
    rows = []
    for opp in opps:
        for ap in opp.get("applications") or []:
            if ap.get("status") not in FOLLOWUP_APP_STATUS:
                continue
            handles = {h for h in (ap.get("app_id"), ap.get("date"))
                       if isinstance(h, str) and h.strip()}
            oid = opp.get("id")
            if (oid, "*") in named or any((oid, h) in named for h in handles):
                continue
            rows.append({"opp_id": oid, "title": opp.get("title"),
                         "app_id": ap.get("app_id"), "date": ap.get("date"),
                         "status": ap.get("status")})
    return rows


def report(root):
    opps = load_jsonl(root, "opportunities.jsonl")
    asks = load_jsonl(root, "asks.jsonl")
    message_ids = {m.get("id") for m in load_jsonl(root, "messages.jsonl") if m.get("id")}
    opps_by_id = {o.get("id"): o for o in opps}
    drafts = draft_rows(root, opps_by_id, message_ids)
    return {"drafts": drafts,
            "sequences": sequence_report(root, opps, drafts),
            "untriggered": untriggered_applications(root, opps, drafts, asks)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sequences", action="store_true")
    ap.add_argument("--untriggered", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on an unreadable field or a dangling ref")
    args = ap.parse_args()

    rep = report(profile_root())
    if args.json:
        print(json.dumps(rep, indent=1))
    elif args.sequences:
        print("SEQUENCES — multi-step plays, next actionable first\n")
        order = {"unblocked": 0, "unresolved": 1, "waiting": 2, "complete": 3}
        for sid, s in sorted(rep["sequences"].items(),
                             key=lambda kv: order.get(kv[1]["state"], 9)):
            mark = {"unblocked": "✅", "waiting": "⏳", "complete": "🏁",
                    "unresolved": "⛔"}[s["state"]]
            print("  %s %-10s %s" % (mark, s["state"], sid))
            for st in s["steps"]:
                print("      step %s  %-9s %s" % (st["step"], st["state"], st["where"]))
        if not rep["sequences"]:
            print("  (none — no outreach row or draft carries a sequence id)")
    elif args.untriggered:
        print("APPLICATIONS WITH NO LINKED FOLLOW-UP — each one is work the submission")
        print("created that nothing has generated yet\n")
        for u in rep["untriggered"]:
            print("  ▸ %s (%s, %s) — application %s" %
                  (u["title"] or u["opp_id"], u["opp_id"], u["status"],
                   u["app_id"] or u["date"] or "?"))
        if not rep["untriggered"]:
            print("  (none — every submitted application has follow-up work naming it)")
    else:
        print("TRIGGER LINKS — what caused each staged draft\n")
        for d in rep["drafts"]:
            mark = {"linked": "✅", "none": "·", "unlinked": "⛔",
                    "unreadable": "⛔"}[d["trigger"]]
            seq = (" [seq %s step %s]" % (d["sequence"], d["step"])) if d["sequence"] else ""
            print("  %s %-10s %s › %s%s" % (mark, d["trigger"], d["file"],
                                            d["title"][:60], seq))
            print("        %s" % d["trigger_why"])

    if args.check:
        bad = [d for d in rep["drafts"]
               if d["trigger"] in ("unlinked", "unreadable")
               or d["sequence_state"] == "unreadable"]
        for d in bad:
            print("⛔ %s › %s: %s" % (d["file"], d["title"][:60], d["trigger_why"]),
                  file=sys.stderr)
        bad_seq = [sid for sid, s in rep["sequences"].items() if s["state"] == "unresolved"]
        for sid in bad_seq:
            print("⛔ sequence %s: next step is unresolved/unreadable — it must not sit "
                  "looking like it is merely waiting" % sid, file=sys.stderr)
        return 1 if (bad or bad_seq) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
