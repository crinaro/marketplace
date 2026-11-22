#!/usr/bin/env python3
"""reachouts.py -- the network block's weekly reach-out BUDGET (dev #834; jobsearch 0.86.0; design-network-first.md 9.1).

⭐ WHAT THIS REPLACES. The daily run's third invariant used to say "no speculative outreach": a reach-out was drafted only
after a role was pursued. Owner ruling 4 (network-first) replaces the ban with a BUDGET: the run drafts up to
`network.new_reachouts_per_week` new reach-outs (default 5) a week, to people the candidate has never contacted, at the
companies the candidate has chosen to target, and NEVER MORE. This script does the arithmetic and the selection, so the
model is handed exactly the lines it may draft and chooses nothing.

DEFINITIONS (every one derived from stores that already exist; nothing here is stored but the one `network` journal event)

  week          the ISO week, Monday to Sunday, of `--today` (default: today on this machine).
  new reach-out a `first-touch` with NO `opp_id`, to a person with no earlier SENT touch and no earlier message either
                way. A first touch that carries an `opp_id` (a recruiter about one role) is role-specific: it neither spends
                the budget nor counts here.
  open draft    an entry in `outreach/drafts.md` addressed `**To:** contact:<id>` whose `**Status:**` is not `sent`, `moot`
                or `do not send` (`warm_path.open_draft_recipients`, the one test). A draft records no `opp_id`, so an open
                draft to a person with no earlier contact is counted as a first-touch draft, whatever its age (CONSERVATIVE: it
                can only under-draft), which bounds the outstanding drafts to one week's budget.
  spent         new reach-outs SENT this week + open first-touch drafts of any age.
  remaining     `network.new_reachouts_per_week` - spent, floored at 0.

`--plan` lists at most `remaining` REACH-OUT lines, ranked: people at `active-target` companies the candidate knows and has never
contacted, by company `motivation` (highest first, none last), a person with stated `ties` first, then the company with the
fewest people already contacted (spread across targets), then id. A person with an open draft is never planned again.
Not budgeted: a LOOKUP line for each target company with nobody known and never contacted, a link the CANDIDATE opens. After
`record.py warm-lookup <co> --none-found` it is a LOOKED line (look date, return date) for `search.warm_lookup_days` (90). This
script reads; it never sends, never drafts, never opens LinkedIn. Its one write is `--journal <run id>`: one `network` journal
event for the run (`{week, budget, open_drafts, sent_this_week, planned}`), the record the funnel's weeks-at-budget reads.

3B7 (`--due`, criterion O1, design 9.1). A NEW reach-out (a `first-touch` with no `opp_id` to a person never in contact before) sent
to a person at an `active-target` company is the ANCHOR of a three-mark timetable counted in BUSINESS DAYS (the weekdays in
`network.workdays`, default Monday to Friday; holidays are not modelled; Saturday and Sunday are skipped):

    business days since the anchor   action                                                                   budgeted
    >= `network.followup_business_days[0]` (3)   second-contact: a first touch to the next-ranked known person at the
                                                 company, or a lookup-owed line for it when nobody else is known     yes
    >= `network.followup_business_days[1]` (7)   follow-up: a `chase` to the person reached                          no
    after the follow-up, no reply                quiet: shown, nothing drafted                                       --

An action is satisfied, and disappears, when its touch exists (a first touch to another person at the company on or after the anchor,
or an open draft to one; a `chase` to the person after the anchor, or an open draft to them). A reply from the person (an inbound
message on or after the anchor, or the anchor touch's own outcome `replied`, `meeting-booked` or `declined`) cancels both.
`--plan` takes the second contacts FIRST, out of the week's remaining budget. Nothing is stored: every run re-derives the same lines
from the stores, so a mark the candidate missed is still due tomorrow.

THE WINDOW (OURS, flagged UNDETERMINED in the design's 3B7 reading). A reach-out older than `WINDOW_MULTIPLE` x the second mark in
business days (21 with the defaults) is no longer on this timetable: it neither yields an action nor is `governed()`, so the first run
after an upgrade is not handed a flood of follow-ups for every old touch, and a thread that has gone cold for a month falls back to
`check_followups.py`'s ordinary silence check.

ONE ANCHOR PER COMPANY CYCLE (OURS; the design says "a second contact", never a chain). A new reach-out to a company whose earlier
anchor is still on the timetable and unanswered IS that anchor's second contact, not a new anchor: otherwise every second contact would
start its own 3B7 and draft a further person, and the week would never end. When the earlier anchor was answered, or has left the
window, the next reach-out there is a fresh anchor. A second contact is not itself followed up (the design's day-7 follow-up is to the
first person reached).

`governed(touch, ctx)` is the one question `check_followups.py` asks: is this touch on the 3B7 timetable (an anchor, or a `chase` to an
anchor's person after it)? Such a touch is not flagged by `communications.chase_after_days`, so the candidate is never told twice. It
is False whenever the profile is not ready for the network block (no 0.86.0 pin, or pinned ahead): then nothing runs 3B7, and the
ordinary check must keep covering the touch.

Exit codes: 0 ok · 2 a refusal (bad config value, bad date, no run id) · 3 the profile is not ready for the network block
(the 0.86.0 migration has not run, or the profile is pinned above this engine): the daily run prints the line and skips the
block's drafting.

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import sys
# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from reach.plan_text import render, render_due
from reach import standing_rows as _rows
# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from reach.weeks import iso_week, business_days_since
from reach import build as _build

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PENDING_LINE = ("network-first upgrade pending: the jobsearch 0.86.0 migration has not run on this profile (run "
                "`~/.claude/jobsearch/run migrate.py` and read what it says); nothing was drafted")


def _date(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def as_date(today):
    """The ONE boundary coercion for `today` (dev #834 verify): `reachouts.plan`/`due`/`context` take a `datetime.date`, and an ISO
    `YYYY-MM-DD` string (what `funnel_report` and the dashboard carry) is converted here, once. None is today on this machine.
    Anything else, or a string that is not a date, is a `ValueError` naming the value: a wrong type never reaches
    `.isocalendar()` as an AttributeError, and never reads as "today"."""
    if today is None:
        return datetime.date.today()
    if isinstance(today, datetime.datetime):
        return today.date()
    if isinstance(today, datetime.date):
        return today
    if isinstance(today, str) and _date(today) is not None:
        return _date(today)
    raise ValueError("today must be a date or a YYYY-MM-DD string, got %r" % (today,))


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def budget(root):
    """`network.new_reachouts_per_week` for the profile at `root`: the configured int 0..50, else the registered default (5).
    A value present but not an int in range raises `ValueError` naming the key (a typo never reads as the default)."""
    import config_keys as ck
    return ck.resolve_int(_config(root), ck.NETWORK_NEW_REACHOUTS_PER_WEEK)


class _History:
    """Who the candidate has been in contact with, by living person id (a merged id resolves to its survivor)."""

    def __init__(self, root):
        import graph as _graph
        self.g = _graph.Graph(os.path.join(root, "data"))
        self._graph = _graph

    def survivor(self, pid):
        try:
            row = self.g.resolve_person(pid)
        except self._graph.MergeCycleError:
            return None
        return row if row and row.get("status") != "merged" else None

    def sent_touches(self, person_id):
        return [t for t in self.g.touches_for_person(person_id) if t.get("status") == "sent"]

    def messages(self, person_id):
        return self.g.messages_for_person(person_id)

    def contacted_before(self, person_id, on, touch_id=None):
        """True when the person has an earlier SENT touch, or any earlier message either way, than `on` (a date). On the same
        date a touch with a smaller id is earlier, so two first touches on one day are not both 'first'."""
        for t in self.sent_touches(person_id):
            d = _date(t.get("date"))
            if d is None or t.get("id") == touch_id:
                continue
            if d < on or (d == on and touch_id is not None and str(t.get("id")) < str(touch_id)):
                return True
        for m in self.messages(person_id):
            d = _date(m.get("sent_on"))
            if d is not None and d < on:
                return True
        return False

    def ever_contacted(self, person_id):
        return bool(self.sent_touches(person_id) or self.messages(person_id))


def _open_first_touch_drafts(root, hist):
    """`{living person id: [draft titles]}` for the open drafts that would be a FIRST touch: addressed to a person with no
    contact yet (or to an id that resolves to no person: counted, conservatively)."""
    import warm_path as _wp
    out = {}
    for pid, titles in _wp.open_draft_recipients(root).items():
        row = hist.survivor(pid)
        living = (row or {}).get("id") or pid
        if row is not None and hist.ever_contacted(living):
            continue                       # a draft to someone already in contact is a reply or a chase, not a first touch
        out.setdefault(living, []).extend(titles)
    return out


WINDOW_MULTIPLE = 3                # OURS: a reach-out is on the 3B7 timetable for this many multiples of the second mark (see the docstring)
REPLY_OUTCOMES = ("replied", "meeting-booked", "declined")     # a touch outcome that says the person answered


def _config(root):
    p = os.path.join(root, "config.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


class _Context:
    """The stores a 3B7 question needs, read ONCE (read-only): the people and companies, the contact history, the open drafts, the
    timetable's marks and workdays, and the anchors. `active` is False when the profile is not ready for the network block (no 0.86.0
    pin, or pinned ahead), and then `governed()` is False and `due()` is empty: nothing runs 3B7 there."""

    def __init__(self, root, today=None):
        import config_keys as ck
        import warm_path as _wp
        self.root = root
        self.today = as_date(today)
        self.active = _gate(root) is None
        self.hist = _History(root)
        self.cfg = cfg = _config(root)
        self.warm_days, self.confirms = ck.resolve_int(cfg, ck.ACCESS_WARM_DAYS), ck.resolve_int(cfg, ck._rk.NETWORK_EMPLOYMENT_CONFIRMS_PER_RUN)
        self.first_mark, self.second_mark = ck.resolve_followup_days(cfg)
        self.workdays = ck.resolve_workdays(cfg)
        self.window = WINDOW_MULTIPLE * self.second_mark
        data = os.path.join(root, "data")
        self.companies = {c.get("id"): c for c in _load(os.path.join(data, "companies.jsonl"))}
        self.targets = {cid: c for cid, c in self.companies.items() if c.get("status") == "active-target"}
        self.people = [p for p in self.hist.g.stores["people"] if p.get("status") != "merged"]
        self.current = _rows.current_ids(self.people, self.today)    # 0.91.0: who is "known there" (design-build-reach 5.3)
        self.draft_people = set()            # living person ids with ANY open draft (a first touch, a chase, a reply)
        for pid in _wp.open_draft_recipients(root):
            row = self.hist.survivor(pid)
            self.draft_people.add((row or {}).get("id") or pid)
        self.anchors = self._anchors()
        self.anchor_ids = {a["touch_id"] for a in self.anchors}
        self.anchor_by_person = {a["person_id"]: a for a in self.anchors}

    def _anchors(self):
        """Every NEW reach-out (a sent `first-touch`, no `opp_id`, to a person never in contact before) to a person at a company that is
        an `active-target` now, oldest first. A touch carrying an `opp_id` is role-specific and is not on this timetable."""
        out = []
        for t in self.hist.g.stores["touches"]:
            if t.get("touch_type") != "first-touch" or t.get("status") != "sent" or t.get("opp_id"):
                continue
            d = _date(t.get("date"))
            row = self.hist.survivor(t.get("person_id"))
            if d is None or row is None or row.get("company_id") not in self.targets:
                continue
            if self.hist.contacted_before(row["id"], d, touch_id=t.get("id")):
                continue
            out.append({"touch_id": t.get("id"), "person_id": row["id"], "person_name": row.get("name"), "date": d,
                        "company_id": row["company_id"], "company_name": self.targets[row["company_id"]].get("name"),
                        "outcome": t.get("outcome"), "responded_on": t.get("responded_on")})
        out.sort(key=lambda a: (a["date"], str(a["touch_id"])))
        # THE TIMETABLE HAS ONE ANCHOR PER COMPANY CYCLE (design 9.1: "a second contact", never a chain). A new reach-out to a company
        # whose earlier anchor is still on the timetable and unanswered IS that anchor's second contact, not a new anchor: without this
        # every second contact would start its own 3B7 and draft a further person, and the week would never end. When the earlier
        # anchor was answered, or has left the window, the next reach-out there is a fresh anchor.
        primary = []
        for a in out:
            if not any(b["company_id"] == a["company_id"] and b["person_id"] != a["person_id"]
                       and self.in_window(b) and not self.replied(b) for b in primary):
                primary.append(a)
        return primary

    def age(self, anchor):
        return business_days_since(anchor["date"], self.today, self.workdays)

    def in_window(self, anchor):
        return self.age(anchor) < self.window

    def replied(self, anchor):
        if anchor["outcome"] in REPLY_OUTCOMES or anchor["responded_on"]:
            return True
        for m in self.hist.messages(anchor["person_id"]):
            d = _date(m.get("sent_on"))
            if m.get("direction") == "inbound" and d is not None and d >= anchor["date"]:
                return True
        return False

    def chases(self, anchor):
        """The sent `chase` touches to the anchor's person after the anchor."""
        return [t for t in self.hist.sent_touches(anchor["person_id"])
                if t.get("touch_type") == "chase" and (_date(t.get("date")) or datetime.date.min) > anchor["date"]]

    def second_contact_made(self, anchor):
        """A first touch to ANOTHER person at the company on or after the anchor (a same-day pair satisfies each other), or an open
        draft to one: the draft is the second contact being made, and re-listing it would draft a third person."""
        for p in self.people:
            if p.get("company_id") != anchor["company_id"] or p["id"] == anchor["person_id"] or p["id"] not in self.current:
                continue
            if p["id"] in self.draft_people:
                return True
            for t in self.hist.sent_touches(p["id"]):
                d = _date(t.get("date"))
                if t.get("touch_type") == "first-touch" and d is not None and d >= anchor["date"]:
                    return True
        return False

    def next_known(self, company_id, exclude):
        """The next-ranked known person at the company who has never been contacted and has no open draft: a stated tie first, then the
        id (the company is the same for every candidate, so its motivation does not rank them)."""
        cands = [p for p in self.people if p.get("company_id") == company_id and p["id"] in self.current and p["id"] not in exclude
                 and p["id"] not in self.draft_people and not self.hist.ever_contacted(p["id"])]
        cands.sort(key=lambda p: (0 if p.get("ties") else 1, str(p["id"])))
        return cands[0] if cands else None


def context(root, today=None):
    """The read-only 3B7 context for the profile at `root`, as of `today` (a date; default today on this machine)."""
    return _Context(root, today)


def governed(touch, ctx):
    """True when `touch` is ON the 3B7 timetable (design 9.1): the anchor itself, or a sent `chase` to an anchor's person dated after
    the anchor, while that anchor is inside the window. `check_followups.py` skips such a touch so `communications.chase_after_days`
    does not flag it a second time. Always False when the profile is not ready for the network block (nothing runs 3B7 there)."""
    if not ctx.active:
        return False
    if touch.get("id") in ctx.anchor_ids:
        a = next(x for x in ctx.anchors if x["touch_id"] == touch.get("id"))
        return ctx.in_window(a)
    if touch.get("touch_type") == "chase" and touch.get("status") == "sent":
        row = ctx.hist.survivor(touch.get("person_id"))
        a = ctx.anchor_by_person.get((row or {}).get("id"))
        d = _date(touch.get("date"))
        return a is not None and d is not None and d > a["date"] and ctx.in_window(a)
    return False


def due(root, today=None, ctx=None):
    """The 3B7 actions due as of `today`, oldest anchor first, read-only (design 9.1). Each is a dict with `kind`:

        second-contact  `person_id`/`person_name` (the next-ranked known person at the anchor's company, a DRAFT for the candidate to
                        send), `company_id`, `anchor_person_id`, `anchor_date`, `business_days`; BUDGETED
        lookup-owed     the same, with no person: nobody else is known at the company, so a link for the candidate to open
        follow-up       a `chase` DRAFT to the anchor's person; not budgeted
        quiet           the anchor's person has been chased and not answered: shown, nothing drafted

    Empty when the profile is not ready for the network block. Never raises on a store that does not exist."""
    ctx = ctx or _Context(root, today)
    if not ctx.active:
        return []
    import warm_path as _wp
    out, picked = [], set()
    for a in ctx.anchors:
        n = ctx.age(a)
        if not ctx.in_window(a) or ctx.replied(a):
            continue
        base = {"anchor_person_id": a["person_id"], "anchor_person_name": a["person_name"], "anchor_touch_id": a["touch_id"],
                "anchor_date": a["date"].isoformat(), "business_days": n, "company_id": a["company_id"],
                "company_name": a["company_name"]}
        chased = ctx.chases(a)
        if n >= ctx.first_mark and not ctx.second_contact_made(a):
            q = ctx.next_known(a["company_id"], exclude={a["person_id"]} | picked)
            if q is not None:
                picked.add(q["id"])
                out.append(dict(base, kind="second-contact", budgeted=True, person_id=q["id"], person_name=q.get("name"),
                                ties=q.get("ties") or [],
                                why="%d business days since the reach-out to %s at %s, no reply: a second person there"
                                    % (n, a["person_name"] or a["person_id"], a["company_name"] or a["company_id"])))
            else:
                out.append(dict(base, kind="lookup-owed", budgeted=False, person_id=None, person_name=None,
                                linkedin_url=_wp._linkedin_url(ctx.targets.get(a["company_id"])),
                                why="%d business days since the reach-out to %s at %s, no reply, and nobody else there is known: "
                                    "find a second person" % (n, a["person_name"] or a["person_id"],
                                                              a["company_name"] or a["company_id"])))
        if chased:
            out.append(dict(base, kind="quiet", budgeted=False, person_id=a["person_id"], person_name=a["person_name"],
                            why="chased on %s and no reply: nothing is drafted" % max(c.get("date") for c in chased)))
        elif n >= ctx.second_mark and a["person_id"] not in ctx.draft_people:
            out.append(dict(base, kind="follow-up", budgeted=False, person_id=a["person_id"], person_name=a["person_name"],
                            why="%d business days since the reach-out to %s, no reply: a short follow-up" % (n, a["person_name"]
                                                                                                            or a["person_id"])))
    return out


def _age_unknown_reason(e):
    """Why an open draft's age cannot be read, in the words the candidate sees. Four different states, kept apart: no `**Brief:**`
    line at all, an intentional `none` (the drafter could not brief it: `outreach-drafter.md`), a value that is not a brief id with
    a date (a hand edit, a typo), and an id whose date is not a real date."""
    brief = e.get("brief")
    if brief is None:
        return "it has no **Brief:** line"
    if brief.strip().lower() == "none":
        return "its **Brief:** is none, so there is no timestamp to read"
    if e.get("drafted_on") is None:
        return "its **Brief:** %r is not a brief id with a date" % brief[:60]
    return "the date %s in its **Brief:** id is not a real date" % e["drafted_on"]


def unobserved(root, today, hist=None):
    """`(list, unknown)`: the open FIRST-TOUCH drafts older than `network.draft_unobserved_days` (design 9.1, "Send unobserved"),
    oldest first, and the open first-touch drafts whose age CANNOT be read:

        [{"ref": <the entry title>, "person_id", "person": <name or id>, "drafted_on": "YYYY-MM-DD", "days": n}]
        unknown: [{"ref", "person_id", "person", "reason"}]

    DRAFT AGE. Design 9.1 is silent on where it comes from: it names `network.draft_unobserved_days` and no date field, and an
    `outreach/drafts.md` entry has none of its own (OURS, INFERRED). So: today minus the date in the entry's `**Brief:** brief:<ISO
    timestamp>-<hex>` id, which `brief.new_brief_id` stamps when the drafter writes the entry (`warm_path.open_draft_entries`).

    A draft whose age cannot be read is NEVER guessed old and NEVER silently dropped (CLAUDE.md: an unparseable value is loud): it
    goes in `unknown` with the reason (`_age_unknown_reason`), `plan` returns it as `age_unknown` and counts it in
    `undated_drafts`, and `render`, the strategy view and the funnel's network section each print it. It is not listed as a send
    unobserved, because nothing can say it is overdue, and it still counts against the budget. A draft to someone already in
    contact is a reply or a chase, not a first touch, and is in neither list. Read-only."""
    import config_keys as ck
    import warm_path as _wp
    today = as_date(today)
    hist = hist or _History(root)
    limit = ck.resolve_int(_config(root), ck.NETWORK_DRAFT_UNOBSERVED_DAYS)
    out, unknown = [], []
    for e in _wp.open_draft_entries(root):
        row = hist.survivor(e["person_id"])
        living = (row or {}).get("id") or e["person_id"]
        if row is not None and hist.ever_contacted(living):
            continue
        d = _date(e["drafted_on"]) if e["drafted_on"] else None
        who = (row or {}).get("name") or living
        if d is None:
            unknown.append({"ref": e["title"], "person_id": living, "person": who, "reason": _age_unknown_reason(e)})
            continue
        days = (today - d).days
        if days > limit:
            out.append({"ref": e["title"], "person_id": living, "person": who, "drafted_on": d.isoformat(), "days": days})
    out.sort(key=lambda u: (-u["days"], u["ref"]))
    return out, unknown


def reconnects(root, today, ctx):
    """The `reconnect` lines of design 9.1 (NOT budgeted): the people whose own `cadence` is due, from `your_move.classify_people`
    (the one owner of that membership; the owner set the cadence, so the line is not speculative):

        [{"kind": "reconnect", "person_id", "person_name", "company_id", "company_name", "why"}]

    A person with an open draft is left out (OURS: the rule that no person is drafted twice, applied here), so a due reconnect that
    has been drafted is not listed again tomorrow. Read-only; sorted by id."""
    import your_move as _ym
    out = []
    for person, state, why in _ym.classify_people(root, as_date(today).isoformat()):
        pid = person.get("id")
        if state != "due" or pid in ctx.draft_people:
            continue
        cid = person.get("company_id")
        out.append({"kind": "reconnect", "person_id": pid, "person_name": person.get("name"), "company_id": cid,
                    "company_name": (ctx.companies.get(cid) or {}).get("name"), "why": why})
    out.sort(key=lambda r: str(r["person_id"]))
    return out


def role_specific(root, today, ctx):
    """The role-specific first touches OWED (design 9.1, not budgeted): `warm_path`'s `draft-owed` actions, a first touch that
    carries an `opp_id` because a role was pursued. They are listed first among the unbudgeted lines because a pursue decision waits
    on them, and they neither spend the budget nor count as a new reach-out:

        [{"kind": "draft-owed", "person_id", "person_name", "company_id", "company_name", "opp_ids", "why"}]

    Read-only; a person with an open draft is never `draft-owed` (`warm_path` reports that state as `drafted`)."""
    import warm_path as _wp
    out = []
    for a in _wp.derive(root, as_date(today)):
        if a.get("state") != "draft-owed" or not a.get("person_id"):
            continue
        out.append({"kind": "draft-owed", "person_id": a["person_id"], "person_name": a.get("person_name"),
                    "company_id": a.get("company_id"),
                    "company_name": (ctx.companies.get(a.get("company_id")) or {}).get("name"),
                    "opp_ids": list(a.get("opp_ids") or []), "why": a.get("why")})
    return out


def plan(root, today=None):
    """The week's budget and what may be drafted against it, read-only over the stores under `root`:

        {"week": "2026-W46", "budget": 5, "sent_this_week": n, "open_drafts": n, "spent": n, "remaining": n,
         "lines": [{"kind": "second-contact" | "reach-out", "person_id", "person_name", "company_id", "company_name", "ties", "why"}],
         "lookups": [{"kind": "lookup-owed", "company_id", "company_name", "linkedin_url"}],
         "looked_none": [{"kind": "looked-none", "company_id", "company_name", "looked_on", "lookup_returns_on"}],
         "confirm": [{"kind": "confirm-employment", "company_id", "company_name", "person_ids", "why"}],   # 0.91.0, unbudgeted
         "reconnects": [{"kind": "reconnect", "person_id", ...}], "role_specific": [{"kind": "draft-owed", "person_id", "opp_ids", ...}],
         "followups": [{"kind": "follow-up", "person_id", ...}], "quiet": [{"kind": "quiet", ...}],
         "unobserved": [{"ref", "person_id", "person", "drafted_on", "days"}], "undated_drafts": n,
         "age_unknown": [{"ref", "person_id", "person", "reason"}]}

    `today` is a date or an ISO string (`as_date`). `unobserved` is the "send unobserved" list (`unobserved()`, design 9.1): open
    first-touch drafts older than `network.draft_unobserved_days`; they stay in `open_drafts` and `spent`.

    `lines` never has more than `remaining` entries (the whole point of the budget), and has none when the budget is spent. The 3B7
    SECOND CONTACTS come first (design 9.1), out of the remaining budget; the ranked first touches fill what is left. Follow-ups
    (a `chase` to a person already reached) are not new reach-outs, so they are listed beside the lines and spend nothing."""
    today = as_date(today)
    label, monday, sunday = iso_week(today)
    cap = budget(root)
    ctx = _Context(root, today)
    hist = ctx.hist

    sent = 0
    for t in hist.g.stores["touches"]:
        if t.get("status") != "sent" or not _build.counts_as_new_reachout(t):      # 0.91.0: + a side-door ask (design 6.4)
            continue
        d = _date(t.get("date"))
        row = hist.survivor(t.get("person_id"))
        if d is None or not (monday <= d <= sunday) or row is None:
            continue
        if not hist.contacted_before(row["id"], d, touch_id=t.get("id")):
            sent += 1
    drafts = _open_first_touch_drafts(root, hist)
    open_drafts = sum(len(v) for v in drafts.values())
    spent = sent + open_drafts
    remaining = max(0, cap - spent)

    targets = ctx.targets
    people = [p for p in ctx.people if p.get("company_id") in targets and p["id"] in ctx.current]    # 0.91.0: current only
    contacted_at = {}
    for p in people:
        if hist.ever_contacted(p["id"]):
            contacted_at[p["company_id"]] = contacted_at.get(p["company_id"], 0) + 1

    actions = due(root, today, ctx=ctx) if ctx.active else []
    second = [a for a in actions if a["kind"] == "second-contact"][:remaining]
    taken = {a["person_id"] for a in second}
    candidates = [p for p in people if not hist.ever_contacted(p["id"]) and p["id"] not in drafts and p["id"] not in taken]

    def rank(p):
        co = targets[p["company_id"]]
        motivation = co.get("motivation")
        m = motivation if isinstance(motivation, int) and not isinstance(motivation, bool) else None
        return (0 if m is not None else 1, -(m or 0), 0 if p.get("ties") else 1,
                contacted_at.get(p["company_id"], 0), str(p["id"]))

    lines = [{"kind": "second-contact", "person_id": a["person_id"], "person_name": a["person_name"],
              "company_id": a["company_id"], "company_name": a["company_name"], "ties": a.get("ties") or [], "why": a["why"],
              "anchor_person_id": a["anchor_person_id"]} for a in second]
    outs = []
    for p in sorted(candidates, key=rank):
        co = targets[p["company_id"]]
        why = "never contacted, at the target %s" % (co.get("name") or co["id"])
        if p.get("ties"):
            why += "; a stated tie"
        outs.append({"kind": "reach-out", "person_id": p["id"], "person_name": p.get("name"),
                     "company_id": co["id"], "company_name": co.get("name"), "ties": p.get("ties") or [], "why": why})
    # 0.91.0 (design-build-reach.md 6.1, 6.4): BUILD lines at path-none targets, interleaved with the reach-outs by motivation, inside
    # the same remaining units. A company with somebody current uncontacted, or a reach-out still on its 3B7 timetable, gets none.
    busy = {p["company_id"] for p in people if not hist.ever_contacted(p["id"])} | {
        a["company_id"] for a in ctx.anchors if ctx.in_window(a) and not ctx.replied(a)}
    built = _build.plan_lines(hist.g, root, ctx.cfg, ctx.warm_days, today, targets, outs, remaining - len(lines), busy)
    lines += built.pop("lines")

    import warm_path as _wp
    lookups, seen, looked_none, relook = [], set(), [], _wp._lookup_days(_config(root))
    for cid, co in sorted(targets.items()):
        if any(p["company_id"] == cid and not hist.ever_contacted(p["id"]) for p in people):
            continue                       # somebody known and uncontacted is there: no lookup is owed
        seen.add(cid)
        on = _date((co.get("warm_lookup") or {}).get("on")) if isinstance(co.get("warm_lookup"), dict) else None
        if on is not None and 0 <= (today - on).days <= relook:      # none-found recorded: not asked again yet (0.90.3)
            looked_none.append({"kind": "looked-none", "company_id": cid, "company_name": co.get("name"), "looked_on": on.isoformat(),
                                "lookup_returns_on": (on + datetime.timedelta(days=relook + 1)).isoformat()})
            continue
        lookups.append({"kind": "lookup-owed", "company_id": cid, "company_name": co.get("name"),
                        "linkedin_url": _wp._linkedin_url(co)})
    for a in actions:                      # a second contact with nobody known: the same link, once per company
        if a["kind"] == "lookup-owed" and a["company_id"] not in seen:
            lookups.append({"kind": "lookup-owed", "company_id": a["company_id"], "company_name": a["company_name"],
                            "linkedin_url": a.get("linkedin_url")})
            seen.add(a["company_id"])
    stale, unknown = unobserved(root, today, hist)
    return {"week": label, "budget": cap, "sent_this_week": sent, "open_drafts": open_drafts, "spent": spent,
            "remaining": remaining, "lines": lines, "lookups": lookups, "reconnects": reconnects(root, today, ctx),
            "role_specific": role_specific(root, today, ctx), "unobserved": stale, "undated_drafts": len(unknown),
            "age_unknown": unknown, "looked_none": looked_none, "confirm": _build.cap_confirms(ctx.people, targets, today, ctx.confirms),
            "followups": [a for a in actions if a["kind"] == "follow-up"],
            "quiet": [a for a in actions if a["kind"] == "quiet"], **built}


def _gate(root):
    """`None` when the profile is ready for the network block, else the line to print. Pinned above this engine: the pin's own
    refusal. No pin at or above 0.86.0: the migration has not run."""
    import journal
    refusal = journal.pin_refusal(root)
    if refusal:
        return refusal
    pin = journal.pin_scan(root)
    if pin is None or tuple(int(x) for x in pin.split(".")) < (0, 86, 0):
        return PENDING_LINE
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="the week's budget and the reach-outs it allows")
    ap.add_argument("--week", action="store_true", help="the budget arithmetic only")
    ap.add_argument("--due", action="store_true", help="the 3B7 actions due today: second contacts, follow-ups, quiet threads")
    ap.add_argument("--journal", metavar="RUN_ID", help="with --plan: append one `network` event for this run")
    ap.add_argument("--today", metavar="YYYY-MM-DD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not (args.plan or args.week or args.due):
        ap.error("one of --plan, --week or --due is required")
    today = _date(args.today) if args.today else None
    if args.today and today is None:
        print("--today %r is not a date" % args.today, file=sys.stderr)
        return 2
    from _root import profile_root
    root = profile_root()
    gate = _gate(root)
    if gate:
        print(gate)
        return 3
    if args.due:
        if args.journal:
            print("--journal goes with --plan", file=sys.stderr)
            return 2
        try:
            actions = due(root, today)
        except (ValueError, KeyError) as e:
            print("reachouts.py: %s" % e, file=sys.stderr)
            return 2
        print(json.dumps(actions, indent=2, sort_keys=True) if args.json else render_due(actions))
        return 0
    try:
        p = plan(root, today)
    except (ValueError, KeyError) as e:
        print("reachouts.py: %s" % e, file=sys.stderr)
        return 2
    if args.journal:
        if not args.plan:
            print("--journal goes with --plan", file=sys.stderr)
            return 2
        import journal
        try:
            journal.record_network(root, args.journal, week=p["week"], budget=p["budget"], open_drafts=p["open_drafts"],
                                   sent_this_week=p["sent_this_week"], planned=len(p["lines"]))
        except journal.JournalError as e:
            print("reachouts.py: the network event was refused: %s" % e, file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(p, indent=2, sort_keys=True))
    elif args.week:
        print(render(dict(p, lines=[], lookups=[], looked_none=[], reconnects=[], role_specific=[], confirm=[])))
    else:
        print(render(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
