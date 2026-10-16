#!/usr/bin/env python3
"""Flag drafts/letters that have ALREADY BEEN SENT OR USED but are still shown as pending.

⭐ WHY THIS EXISTS (2026-08-03). The candidate, looking at the dashboard: *"on your move, i'm still seeing
the drafts for <an employer> (what's wrong)"*. The candidate was right. They had sent the email and
applied with the cover letter attached; both facts were correctly written into `data/*.jsonl`, and
**both entries were still sitting in `drafts.md` / `cover_letters.md` as "awaiting approval."**

The failure is structural, not careless. Recording a send touches the JSON; retiring the markdown
entry is a SECOND, SEPARATE step, and anything that depends on remembering a second step
eventually does not happen. It is the same shape as the lock bug fixed earlier the same day
(`runlock.py --run`), and the same shape as the stale-dashboard bug before that.

**What it costs when it slips:** the candidate's Your Move panel is their queue. An item that is actually
DONE sitting in it is worse than noise — they either re-do the work, or they start distrusting the
panel, and a queue they distrust stops being a queue.

Heuristic and deliberately conservative: it matches a pending entry's heading against contact
names and role titles that already carry a `sent` outreach row or a `submitted`/`rejected`
application. It reports SUSPECTS, not verdicts, and **always exits 0** — this is run-start hygiene
and must never wedge an unattended run. `validate_data.py` remains the only hard gate.

⭐ AN ENTRY IS MATCHED ONLY WITHIN ITS OWN BLOCK (dev #705 / public #153). The first version
matched a heading against EVERY marker in the profile, so a contact who had been written to about
one opportunity "matched" a pending draft about another, and a shared title prefix at another
company matched that company's draft. The output then told the reader to RETIRE the entry, an
instruction that deletes live work on a false positive. Now (design-jobsearch-0.66.0 §6, R5):

  1. the block is the opportunity the entry DECLARES (`**Triggered by:** opp:<id>`, parsed by
     `trigger.TRIGGER_FIELD_RE`, resolved by `precondition._opp_anchor`), else
  2. the ONE company whose name the heading contains (two candidates is none), else
  3. the entry has no block and is listed as NOT CHECKED, never silently treated as clean.

A marker is considered only when it belongs to that block, and a hit says to VERIFY against the
named opportunity, never to retire the entry. The anchor hint printed for an unanchored entry is
built from `trigger.py`'s own documented example line, so it cannot drift from the parser; when
that example is unavailable (a run under `python -OO` strips docstrings) the hint says so instead
of printing a guess.

⚠️ A legitimately half-sent entry is normal: a connection request can be out while the follow-up
message waits on acceptance. Say so IN THE HEADING (e.g. "PART A SENT · part B pending") and this
check will still flag it — read the flag, confirm the pending half is real, and move on.

Python 3.9+, stdlib only.
"""

import json
import os
import re
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import _tree
import applications as _apps
import touches as _touches
import precondition as _precondition
import trigger as _trigger

ROOT = _profile_root()
OPPS = os.path.join(ROOT, "data", "opportunities.jsonl")
COMPANIES = os.path.join(ROOT, "data", "companies.jsonl")
FILES = (_tree.rel("drafts"), _tree.rel("cover_letters"))


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def load_opps():
    rows = _load_jsonl(OPPS)
    _apps.enrich_opportunities(ROOT, rows)      # ADR-031 B2 — r["_applications"], never nested
    _touches.enrich_opportunities(ROOT, rows)    # ADR-031 B3 — r["_touches"], never nested
    return rows


def load_companies():
    return _load_jsonl(COMPANIES)


def sent_markers(opps):
    """-> list of marker dicts for anything already sent or submitted.

    Each carries `label` and `why` (what the heading is matched against, and what happened) plus
    the BLOCK it belongs to: `opp_id`, `company_id` and `title` of the opportunity record it was
    read from. dev #705 / public #153 — the block is what stops a marker from one opportunity
    matching an entry about another."""
    out = []
    for r in opps:
        block = {"opp_id": r.get("id"), "company_id": r.get("company_id"),
                 "title": r.get("title", "")}
        for o in r.get("_touches") or []:
            if o.get("status") == "sent" and o.get("to"):
                out.append(dict(block, label=o["to"],
                                why="outreach sent %s (%s)"
                                % (o.get("date", "?"), o.get("medium", "?"))))
        for a in r.get("_applications") or []:
            if a.get("status") in ("submitted", "acknowledged", "rejected", "advanced", "closed"):
                out.append(dict(block, label=r.get("title", ""),
                                why="application %s %s" % (a.get("status"), a.get("date", "?"))))
    return out


def pending_entries(path):
    """-> [(lineno, heading, body)] for '## ' entries. A '_..._' status note is NOT pending.
    `body` is the text up to the next '## ' heading: where an entry's meta lines live."""
    p = _tree.resolve_rel(ROOT, path)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## ") and not line.startswith("## ⚠️ Questions"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            out.append((i + 1, line[3:].strip(), "\n".join(lines[i + 1:j])))
            i = j
        else:
            i += 1
    return out


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())


def _words(s):
    return " ".join(norm(s).split())


def entry_block(heading, body, companies):
    """-> ("opp", opp_id) | ("company", company_id) | (None, None).

    The opportunity the entry declares wins (and only counts when it resolves, which
    `_opp_anchor` checks); otherwise the entry's heading must contain the name of exactly ONE
    company. Two candidates, or none, leave the entry without a block."""
    opp_id = _precondition._opp_anchor(ROOT, body)
    if opp_id:
        return "opp", opp_id
    h = " %s " % _words(heading)
    found = set()
    for c in companies:
        name = _words(c.get("name"))
        if name and " %s " % name in h and c.get("id"):
            found.add(c["id"])
    if len(found) == 1:
        return "company", found.pop()
    return None, None


def anchor_hint():
    """The line that anchors an entry to an opportunity, spelled the way the parser reads it.

    Built from the first `opp:` example line in `trigger.py`'s own docstring, cut at the value
    `trigger.TRIGGER_FIELD_RE` captures, so the spelling can never drift from the parser (R5,
    dev #705). -> None when the example is unavailable; the caller then points at trigger.py
    rather than print a retyped guess."""
    for line in (_trigger.__doc__ or "").splitlines():
        line = line.strip()
        m = _trigger.TRIGGER_FIELD_RE.match(line)
        if m and m.group(1).startswith("opp:"):
            return line[:m.start(1)] + "opp:<id>"
    return None


def main():
    opps = load_opps()
    companies = load_companies()
    markers = sent_markers(opps)
    hits = []
    unchecked = []
    n_opp = n_company = 0
    for path in FILES:
        for lineno, heading, body in pending_entries(path):
            kind, block_id = entry_block(heading, body, companies)
            if kind is None:
                unchecked.append((path, lineno, heading))
                continue
            if kind == "opp":
                n_opp += 1
                in_block = [m for m in markers if m["opp_id"] == block_id]
            else:
                n_company += 1
                in_block = [m for m in markers if m["company_id"] == block_id]
            h = norm(heading)
            for m in in_block:
                lab = norm(m["label"])
                if len(lab) < 5:
                    continue
                # Match on a distinctive multi-word label (a person's name or a role title).
                parts = [w for w in lab.split() if len(w) > 3]
                if len(parts) >= 2 and all(w in h for w in parts[:2]):
                    hits.append((path, lineno, heading, m))
                    break

    total = n_opp + n_company + len(unchecked)
    print("Sent-but-still-pending check — drafts.md / cover_letters.md")
    print("\n  Scanned %d pending entr%s: %d anchored to an opportunity, %d to a company, %d not checked."
          % (total, "y" if total == 1 else "ies", n_opp, n_company, len(unchecked)))
    if hits:
        print("\n  ⚠️ %d entr%s ALREADY SENT/USED but still render as pending on Your Move:\n"
              % (len(hits), "y looks" if len(hits) == 1 else "ies look"))
        for path, lineno, heading, m in hits:
            print("  %s:%d" % (path, lineno))
            print("     %s" % heading[:96])
            print("     matched: %r — %s" % (m["label"], m["why"]))
            print("     verify against opportunity %s (%s) before changing this entry"
                  % (m["opp_id"], m["title"] or "untitled"))
        print("\n  A match is a SUSPECT, not a verdict. Open the named opportunity and confirm the send")
        print("  or submission is for THIS entry before you change it. If only HALF is sent")
        print("  (e.g. connection request out, follow-up message waiting on acceptance), that is")
        print("  legitimate — say so in the heading and leave it.")
    elif total == 0:
        print("\n  NOT CHECKED: no pending entries were found in drafts.md or cover_letters.md.")
    elif not unchecked:
        print("\n  Clean. Nothing shown as pending has already been sent or submitted.")
    else:
        print("\n  No match within the entries that could be checked.")
    if unchecked:
        print("\n  %d pending entr%s name no opportunity or company — not checked:"
              % (len(unchecked), "y" if len(unchecked) == 1 else "ies"))
        for path, lineno, heading in unchecked[:10]:
            print("     %s:%d  %s" % (path, lineno, heading[:80]))
        if len(unchecked) > 10:
            print("     … and %d more" % (len(unchecked) - 10))
        hint = anchor_hint()
        if hint:
            print("  To check one, anchor it to its opportunity with a line in the entry:  %s" % hint)
        else:
            print("  To check one, anchor it to its opportunity with a Triggered-by line"
                  " (spelling: see trigger.py).")
    return 0   # advisory only, never wedges a run


if __name__ == "__main__":
    sys.exit(main())
