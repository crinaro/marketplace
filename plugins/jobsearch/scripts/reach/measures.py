"""measures: the week's network counts, the side-door chain and the trailing reply rates, REPLAYED from dated rows (jobsearch 0.91.0,
design-build-reach.md 8; R2 N11, N13a; owner O17, O20).

NOTHING IS STORED. Every figure is a function of the stores, the mailbox coverage and a date; `build_reach.py --measures` prints it, the
weekly review reads it, and `strategy_view.py` asks `build_reach.measures_text` for the same text. The week is the ISO week of
`today` (`reach.weeks.iso_week`), counted from its Monday through `today`. **The weekly view is counts only** (O20): a week's whole
reach-out budget is 5 (`network.new_reachouts_per_week`), so no single ask kind could reach `MIN_SAMPLE` in a week.

    conversations held      `kind: chat` commitments, not cancelled, `attendance: held`, dated in the week, against
                            `network.conversations_per_week`; a chat dated before today with no `attendance` makes it `N+` (access.py)
    asks sent, by kind      sent touches dated in the week, by STORED fields only (`ask_kind`): `build_kind` first (advice-ask,
                            side-door), then `trigger_kind: introduction` (a landing), then `touch_type` (intro-request, a first-touch
                            with no `opp_id` = reach-out, one with an `opp_id` = role-specific, referral-ask, chase, reconnect). A reply,
                            a thank-you or an apply-path is not an ask. Each kind is its own count; nothing is summed across kinds
    people added            `people` rows whose `created` (stamped by `record.py create --file people`, B1) is in the week and whose
                            `ties` hold a stated tie. An older row has no stamp: it was added "before measuring", never this week
    a new way in            `access.table` replayed between the Sunday before the week and `today` (the caller passes
                            `access.py --json --since`): a `path none -> direct|via-intro` move. A move caused ONLY by an employment
                            confirmation (N13a: the newly warm people were not counted at the start, and nothing else with them is dated
                            in the week) is not counted as a way in; it is shown on the "employment confirmed" line, and the way-in line
                            says how many it leaves out. A side-door ask is never a way in (O17): `access` does not count it as an open
                            introduction, so it cannot make a move; it is counted under "side-door asks awaiting" instead
    follow-ups on time      every 3B7 follow-up mark (the second mark of `network.followup_business_days` after a new reach-out, the
                            anchors `reachouts.py` times) that fell in the week and was still owed (no reply by the mark): on time when a
                            `chase` to that person is dated after the reach-out and on or before the mark plus `GRACE_BUSINESS_DAYS`. The
                            reach-out's `date` is the day it was SENT (since B6 the outbox's sent write copies the sent message's date
                            onto the touch), so the clock starts at the send, never at the draft
    events attended         `kind: event` commitments (B4), `attendance: held`, in the week
    employment confirmed    people whose `employment` is `current` with `source: stated` and whose `as_of` or `confirmed_on` is in the
                            week, or with a `formerly` entry whose `as_of` is. Both are WRITE dates (design 5.2): B1 built no
                            `employment` journal event, so the dated fields are the record, and work done this week counts this week

THE SIDE-DOOR CHAIN, cumulative to `today`: asked (sent `build_kind: side-door`), answered (`responded_on`), named someone (the asked
person is the `via` of an `introduced` tie on someone current at the ask's company, `reach.sidedoor.named`), notes sent (touches whose
`trigger_ref` is `touch:<the ask>`), notes answered.

REPLY RATES (O20, R2 N11), one line per ask kind over a TRAILING COHORT of `RATE_WINDOW_WEEKS` ISO weeks ending this week, never a
week. The classification is the funnel's own (`reach.resolution.touch_resolution`, moved out of `funnel_report.py`): the denominator
is the RESOLVED asks of the kind (a terminal outcome, or `awaiting` past `NO_RESPONSE_AFTER` days), the numerator those that are a win
(`touch_is_win`); `awaiting` prints as pending, a bounce and an unverifiable address are excluded and say so. Below `MIN_SAMPLE`
resolved asks the line gives the counts and "too few for a rate". When an email ask's outcome still depends on silence (`awaiting`
or `resolved-aged`) and the mailbox coverage (the merged `swept` intervals `covered_through` reads, per mailbox, passed in by the
caller as `stores["coverage"]`, from `measuring.mail_coverage`: this module does not import `journaling`, which would put `reach/` in the plugin's largest import
cycle) has a hole over its reply
window (the ask's date to `NO_RESPONSE_AFTER` days later, through yesterday), the line is `not checked: mailbox not swept <dates>`,
never a rate: a reply may be sitting in an unswept day. LIMIT, stated: an ask over LinkedIn is not checked for a hole (no LinkedIn
coverage reader is a capability module yet), so its silence is read as the funnel reads it.

`REPLY_OUTCOMES` and `WINDOW_MULTIPLE` mirror `reachouts.py` (an entry point this module may not import); `tests/test_build_reach.py`
pins them equal. Rows come from `load(root)` or the caller. Capability module of `build_reach.py`. Python 3.9+, standard library only."""

import datetime
import json
import os

from _dates import date_or_none, to_date
from reach import resolution as _res
from reach import sidedoor as _sd
from reach.weeks import business_days_since, iso_week

RATE_WINDOW_WEEKS = 12            # OURS (design 8): the trailing cohort a reply rate is computed over
GRACE_BUSINESS_DAYS = 2           # OURS (design 8): a follow-up is on time up to this many business days after its mark
REPLY_OUTCOMES = ("replied", "meeting-booked", "declined")       # mirrors reachouts.REPLY_OUTCOMES (pinned)
WINDOW_MULTIPLE = 3                                              # mirrors reachouts.WINDOW_MULTIPLE (pinned)
STORES = ("people", "touches", "commitments", "messages", "companies")
ASK_KINDS = ("advice-ask", "side-door", "intro-request", "reach-out", "introduction", "role-specific", "referral-ask", "chase",
             "reconnect")
SHOWN_ALWAYS = ("advice-ask", "side-door", "intro-request", "reach-out")     # printed at 0; the rest only when present
_PLAIN_ASKS = ("referral-ask", "chase", "reconnect")


class NotChecked(Exception):
    """The measures cannot be answered (no profile data on disk). Never rendered as a week of zeros."""


# ---- reading ------------------------------------------------------------------------------------

def _rows(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                raise ValueError("%s line %d is not valid JSON" % (path, n))
            if not isinstance(row, dict):
                raise ValueError("%s line %d is not an object" % (path, n))
            out.append(row)
    return out


def load(root):
    """`{store: [rows]}` for the profile at `root`, with `coverage` `{}` and `journal_problem` None until the caller adds the mailbox
    coverage (`measuring.mail_coverage.coverage`). A root with no `data/` raises `NotChecked`; an unreadable store line raises `ValueError`."""
    data = os.path.join(root or "", "data")
    if not root or not os.path.isdir(data):
        raise NotChecked("no data directory at %s" % data)
    out = {s: _rows(os.path.join(data, s + ".jsonl")) for s in STORES}
    out["coverage"], out["journal_problem"] = {}, None
    return out


# ---- small readers --------------------------------------------------------------------------------

def _in(d, start, end):
    return d is not None and start <= d <= end


def _sent_on(t):
    return date_or_none(t.get("date")) if t.get("status") == "sent" else None


def _has_tie(p):
    return any(isinstance(t, dict) and t.get("kind") for t in p.get("ties") or ())


def _survivor(by_id, pid):
    """The living people row `pid` resolves to through `merged_into`, or None (no row, or a merge loop)."""
    seen, cur = set(), by_id.get(pid)
    while cur is not None and cur.get("status") == "merged" and cur.get("merged_into"):
        if cur.get("id") in seen:
            return None
        seen.add(cur.get("id"))
        cur = by_id.get(cur["merged_into"])
    return cur if cur is not None and cur.get("status") != "merged" else None


def add_business_days(start, n, workdays):
    """The date `n` business days after `start` (the day `reach.weeks.business_days_since` first reaches `n`)."""
    d, k = start, 0
    while k < n:
        d += datetime.timedelta(days=1)
        if d.isoweekday() in workdays:
            k += 1
    return d


def ask_kind(t):
    """Which ask a touch is, from its stored fields only (module docstring), or None when it is not an ask."""
    if t.get("build_kind") in ("advice-ask", "side-door"):
        return t["build_kind"]
    if t.get("trigger_kind") == "introduction":
        return "introduction"
    tt = t.get("touch_type")
    if tt == "intro-request":
        return "intro-request"
    if tt == "first-touch":
        return "role-specific" if t.get("opp_id") else "reach-out"
    return tt if tt in _PLAIN_ASKS else None


# ---- the week's counts ----------------------------------------------------------------------------

def conversations(commitments, kind, start, end, today):
    """`{"held": n, "unrecorded": [ids]}` for the non-cancelled `kind` commitments dated in [start, end]."""
    held, unrecorded = 0, []
    for c in commitments:
        d = date_or_none(c.get("date"))
        if c.get("kind") != kind or c.get("status") == "cancelled" or not _in(d, start, end):
            continue
        if c.get("attendance") == "held":
            held += 1
        elif not c.get("attendance") and d < today:
            unrecorded.append(c.get("id"))
    return {"held": held, "unrecorded": sorted(str(i) for i in unrecorded)}


def asks_by_kind(touches, start, end):
    """`{kind: n}` over the sent touches dated in [start, end], every kind of `ASK_KINDS` present (0 when none)."""
    out = dict.fromkeys(ASK_KINDS, 0)
    for t in touches:
        k = ask_kind(t)
        if k and _in(_sent_on(t), start, end):
            out[k] += 1
    return out


def people_added(people, start, end):
    """Sorted ids of the living people created in [start, end] with a stated tie."""
    return sorted(str(p.get("id")) for p in people if p.get("status") != "merged" and _has_tie(p)
                  and _in(date_or_none(p.get("created")), start, end))


def employment_confirmed(people, start, end):
    """Sorted ids of the living people whose employment was stated in [start, end] (module docstring)."""
    out = []
    for p in people:
        if p.get("status") == "merged":
            continue
        emp = p.get("employment") if isinstance(p.get("employment"), dict) else {}
        stated = emp.get("status") == "current" and emp.get("source") == "stated" and any(
            _in(date_or_none(emp.get(f)), start, end) for f in ("as_of", "confirmed_on"))
        left = any(isinstance(f, dict) and _in(date_or_none(f.get("as_of")), start, end) for f in p.get("formerly") or ())
        if stated or left:
            out.append(str(p.get("id")))
    return sorted(out)


def _activity(stores, since, end):
    """`(people, toward)`: the living ids with a touch sent or answered, a message or a chat dated in (since, end], and the company and person
    ids an introduction was asked (`intro-request`) or offered (`intros_given`, dated by its `on` or the chat) toward in that span."""
    by_id = {p.get("id"): p for p in stores["people"] if p.get("id")}
    acts, intro_to = set(), set()

    def person(pid):
        row = _survivor(by_id, pid)
        return (row or {}).get("id") or pid
    for t in stores["touches"]:
        d, answered = _sent_on(t), date_or_none(t.get("responded_on"))
        if answered is not None and since < answered <= end:
            acts.add(person(t.get("person_id")))       # an older touch answered this week is a result too
        if d is not None and since < d <= end:
            acts.add(person(t.get("person_id")))
            if t.get("touch_type") == "intro-request":
                intro_to.update(x for x in (t.get("object_company_id"), t.get("object_person_id")) if x)
    for m in stores["messages"]:
        d = date_or_none(m.get("sent_on"))
        if d is not None and since < d <= end:
            acts.add(person(m.get("person_id")))
    for c in stores["commitments"]:
        d = date_or_none(c.get("date"))
        if c.get("kind") == "chat" and d is not None and since < d <= end:
            acts.add(person(c.get("person_id")))
        for e in c.get("intros_given") or () if c.get("status") != "cancelled" else ():
            on = date_or_none(e.get("on")) or d if isinstance(e, dict) else None
            if on is not None and since < on <= end:
                intro_to.update(x for x in (e.get("company_id"), e.get("person_id")) if x)
    return acts, intro_to


def way_in(rows, stores, since, end):
    """`{"result": [names], "confirmation_only": [names]}` over the replayed access rows (each with `moved` since `since`): every
    target whose path moved off `none`, split by N13a (module docstring)."""
    acts, intro_to = _activity(stores, since, end)
    out = {"result": [], "confirmation_only": []}
    for r in rows:
        mv = [m for m in r.get("moved") or () if m.get("what") == "path" and m.get("from") == "none" and m.get("to") != "none"]
        if not mv:
            continue
        newly = {m.get("person_id") for m in r["moved"] if m.get("what") == "standing" and m.get("to") == "current"}
        if mv[0]["to"] == "direct":
            warm = {pid for pid, w in (r.get("people") or {}).items() if w == "warm"}
            only = bool(newly) and not (warm - newly) and not (warm & acts)
        else:
            only = bool(newly) and r.get("company_id") not in intro_to and not (newly & intro_to)
        out["confirmation_only" if only else "result"].append(r.get("name") or r.get("company_id"))
    return out


def _anchors(stores, targets, today, second, workdays):
    """The 3B7 anchors `reachouts.py` times: sent `first-touch`, no `opp_id`, to a person never contacted before, at a company that is
    an `active-target` now; one per company cycle (a later reach-out while an earlier one is unanswered and in its window is that
    anchor's second contact). Mirrors `reachouts._Context._anchors`, over rows."""
    by_id = {p.get("id"): p for p in stores["people"] if p.get("id")}
    touches, msgs = {}, {}
    for t in stores["touches"]:
        row = _survivor(by_id, t.get("person_id"))
        if row is not None and t.get("status") == "sent":
            touches.setdefault(row["id"], []).append(t)
    for m in stores["messages"]:
        row = _survivor(by_id, m.get("person_id"))
        if row is not None:
            msgs.setdefault(row["id"], []).append(m)

    def before(pid, d, tid):                      # reachouts._History.contacted_before
        for t in touches.get(pid, ()):
            td = date_or_none(t.get("date"))
            if td is not None and t.get("id") != tid and (td < d or (td == d and str(t.get("id")) < str(tid))):
                return True
        return any((date_or_none(m.get("sent_on")) or d) < d for m in msgs.get(pid, ()))

    def replied(a):
        return a["t"].get("outcome") in REPLY_OUTCOMES or bool(a["t"].get("responded_on")) or any(
            m.get("direction") == "inbound" and (date_or_none(m.get("sent_on")) or datetime.date.min) >= a["date"]
            for m in msgs.get(a["pid"], ()))
    out = []
    for t in stores["touches"]:
        d, row = _sent_on(t), _survivor(by_id, t.get("person_id"))
        if t.get("touch_type") != "first-touch" or t.get("opp_id") or d is None or row is None or row.get("company_id") not in targets:
            continue
        if not before(row["id"], d, t.get("id")):
            out.append({"t": t, "pid": row["id"], "date": d, "company_id": row["company_id"]})
    out.sort(key=lambda a: (a["date"], str(a["t"].get("id"))))
    primary = []
    for a in out:
        if not any(b["company_id"] == a["company_id"] and b["pid"] != a["pid"] and not replied(b)
                   and business_days_since(b["date"], today, workdays) < WINDOW_MULTIPLE * second for b in primary):
            primary.append(a)
    return primary, touches, msgs


def followups(stores, start, end, today, marks, workdays):
    """`{"on_time": n, "late": n, "grace": n}` for the 3B7 follow-up marks that fell in [start, end] and were still owed."""
    targets = {c.get("id") for c in stores["companies"] if c.get("status") == "active-target"}
    anchors, touches, msgs = _anchors(stores, targets, today, marks[1], workdays)
    out = {"on_time": 0, "late": 0, "grace": 0}
    for a in anchors:
        mark = add_business_days(a["date"], marks[1], workdays)
        if not _in(mark, start, end):
            continue
        t = a["t"]
        answered = date_or_none(t.get("responded_on"))
        if (answered is not None and answered <= mark) or (answered is None and t.get("outcome") in REPLY_OUTCOMES) or any(
                m.get("direction") == "inbound" and _in(date_or_none(m.get("sent_on")), a["date"], mark) for m in msgs.get(a["pid"], ())):
            continue                                   # answered by the mark: no follow-up was owed
        deadline = add_business_days(mark, GRACE_BUSINESS_DAYS, workdays)
        if any(c.get("touch_type") == "chase" and a["date"] < (date_or_none(c.get("date")) or a["date"]) <= deadline
               for c in touches.get(a["pid"], ())):
            out["on_time"] += 1
        else:
            out["grace" if today <= deadline else "late"] += 1
    return out


def side_door_chain(stores, today):
    """`{"asked", "answered", "named", "notes", "notes_answered"}`, cumulative to `today` (module docstring)."""
    asks = [t for t in stores["touches"] if t.get("build_kind") == _sd.BUILD_KIND and _in(_sent_on(t), datetime.date.min, today)]
    refs = {"touch:%s" % t.get("id") for t in asks}
    notes = [t for t in stores["touches"] if t.get("trigger_ref") in refs and _in(_sent_on(t), datetime.date.min, today)]
    named = [t for t in asks if _sd.named(stores["people"], t.get("object_company_id"), {t.get("person_id")}, today)]

    def answered(ts):
        return sum(1 for t in ts if _in(date_or_none(t.get("responded_on")), datetime.date.min, today))
    return {"asked": len(asks), "answered": answered(asks), "named": len(named), "notes": len(notes),
            "notes_answered": answered(notes)}


# ---- the trailing rates -----------------------------------------------------------------------------

def _day_span(day, tz):
    nxt = day + datetime.timedelta(days=1)

    def at(d):
        n = datetime.datetime(d.year, d.month, d.day)
        return n.replace(tzinfo=tz) if tz is not None else n.astimezone()
    return at(day).astimezone(datetime.timezone.utc), at(nxt).astimezone(datetime.timezone.utc)


def mail_holes(coverage, first, last, tz=None):
    """The days in [first, last] that some swept mailbox does not cover whole. `coverage` is `{mailbox: [(from, through)]}` of merged
    aware intervals; every mailbox must cover the day, and no mailbox at all is every day uncovered."""
    days = [first + datetime.timedelta(days=i) for i in range((last - first).days + 1)] if last >= first else []
    if not coverage:
        return days
    merged = [coverage[mb] for mb in sorted(coverage)]
    out = []
    for d in days:
        s, e = _day_span(d, tz)
        if not all(any(f <= s and t >= e for f, t in iv) for iv in merged):
            out.append(d)
    return out


def _spans(days):
    """`2026-11-10..2026-11-12, 2026-11-14` for a sorted list of dates."""
    runs = []
    for d in days:
        if runs and (d - runs[-1][1]).days == 1:
            runs[-1][1] = d
        else:
            runs.append([d, d])
    return ", ".join(a.isoformat() if a == b else "%s..%s" % (a.isoformat(), b.isoformat()) for a, b in runs)


def rates(stores, today, tz=None):
    """`[{kind, sent, resolved, wins, pending, bounced, unverifiable, not_checked, rate}]`, one per ask kind with any ask in the trailing
    `RATE_WINDOW_WEEKS` cohort. `rate` is a percentage only at `MIN_SAMPLE` resolved or more and no hole; `not_checked` names why not."""
    _label, monday, _sun = iso_week(today)
    first = monday - datetime.timedelta(weeks=RATE_WINDOW_WEEKS - 1)
    yesterday = today - datetime.timedelta(days=1)
    out = []
    for kind in ASK_KINDS:
        ts = [t for t in stores["touches"] if ask_kind(t) == kind and _in(_sent_on(t), first, today)]
        if not ts:
            continue
        c = {"kind": kind, "sent": len(ts), "resolved": 0, "wins": 0, "pending": 0, "bounced": 0, "unverifiable": 0,
             "not_checked": None, "rate": None}
        holes = set()
        for t in ts:
            r = _res.touch_resolution(t, today)
            if r in ("resolved", "resolved-aged"):
                c["resolved"] += 1
                c["wins"] += 1 if _res.touch_is_win(t) else 0
            else:
                c[{"awaiting": "pending", "bounced": "bounced"}.get(r, "unverifiable")] += 1
            if r in ("awaiting", "resolved-aged") and (t.get("medium") or "").startswith("email"):
                if stores.get("journal_problem"):
                    c["not_checked"] = stores["journal_problem"]
                d = _sent_on(t)
                holes.update(mail_holes(stores.get("coverage") or {}, d, min(d + datetime.timedelta(days=_res.NO_RESPONSE_AFTER),
                                                                         yesterday), tz))
        if holes and not c["not_checked"]:
            c["not_checked"] = "mailbox not swept %s" % _spans(sorted(holes))
        if not c["not_checked"] and c["resolved"] >= _res.MIN_SAMPLE:
            c["rate"] = round(100.0 * c["wins"] / c["resolved"])
        out.append(c)
    return out


# ---- the whole week ----------------------------------------------------------------------------------

def week(stores, rows, today, target=2, marks=(3, 7), workdays=(1, 2, 3, 4, 5), side_asks_open=0, tz=None):
    """The week's measures as a dict (module docstring). `rows` are `access.table` rows replayed since the Sunday before the week
    (`moved` on each); `side_asks_open` is their summed `reach.side_asks_open`; `target` is `network.conversations_per_week`."""
    today = to_date(today)
    label, monday, sunday = iso_week(today)
    end = min(sunday, today)
    since = monday - datetime.timedelta(days=1)
    work = set(workdays)
    return {"week": label, "from": monday.isoformat(), "through": end.isoformat(), "as_of": today.isoformat(),
            "conversations": dict(conversations(stores["commitments"], "chat", monday, end, today), target=target),
            "events": conversations(stores["commitments"], "event", monday, end, today),
            "asks": asks_by_kind(stores["touches"], monday, end),
            "people_added": people_added(stores["people"], monday, end),
            "way_in": way_in(rows, stores, since, end), "side_asks_open": side_asks_open,
            "followups": followups(stores, monday, end, today, tuple(marks), work),
            "employment_confirmed": employment_confirmed(stores["people"], monday, end),
            "side_door": side_door_chain(stores, today), "rates": rates(stores, today, tz)}


def _rate_line(c, as_of):
    head = "  %s, last %d weeks: " % (c["kind"], RATE_WINDOW_WEEKS)
    if c["not_checked"]:
        return head + "not checked: %s (%d sent; no rate)" % (c["not_checked"], c["sent"])
    extra = "".join(" · %d %s" % (c[k], w) for k, w in (("pending", "pending"), ("bounced", "bounced (excluded)"),
                                                        ("unverifiable", "unverifiable address (excluded)")) if c[k])
    if c["rate"] is None:
        return head + "%d sent, %d resolved, %d answered%s (too few for a rate: %d resolved, need %d)" % (
            c["sent"], c["resolved"], c["wins"], extra, c["resolved"], _res.MIN_SAMPLE)
    return head + "%d of %d resolved answered = %d%%%s (as of %s; recent asks may still be answered)" % (
        c["wins"], c["resolved"], c["rate"], extra, as_of)


def render(w):
    """The text `build_reach.py --measures` prints. The week block carries no percentage, ever."""
    conv, ev, fu, wi = w["conversations"], w["events"], w["followups"], w["way_in"]
    plus = "+" if conv["unrecorded"] else ""
    out = ["WEEK %s (%s to %s): counts only; rates are over the trailing %d weeks below" % (w["week"], w["from"], w["through"],
                                                                                        RATE_WINDOW_WEEKS),
           "  conversations held: %d%s of %d (network.conversations_per_week)%s" % (
               conv["held"], plus, conv["target"], "; not recorded yet: %s" % ", ".join(conv["unrecorded"]) if plus else ""),
           "  asks sent: " + " · ".join("%s %d" % (k, n) for k, n in w["asks"].items() if n or k in SHOWN_ALWAYS),
           "  people added with a stated tie: %d" % len(w["people_added"]),
           "  targets with a new way in: %d%s%s" % (len(wi["result"]), " (%s)" % ", ".join(wi["result"]) if wi["result"] else "",
                                                    "; not counting %d that moved only on an employment confirmation (below)"
                                                    % len(wi["confirmation_only"]) if wi["confirmation_only"] else ""),
           "  side-door asks awaiting: %d (an ask is never a way in)" % w["side_asks_open"]]
    owed = fu["on_time"] + fu["late"] + fu["grace"]
    out.append("  follow-ups on time: %s" % ("%d of %d%s" % (fu["on_time"], owed, " (%d still within the %d-day grace)" % (
        fu["grace"], GRACE_BUSINESS_DAYS) if fu["grace"] else "") if owed else "no follow-up fell due this week"))
    out.append("  events attended: %d%s" % (ev["held"], "+ (not recorded yet: %s)" % ", ".join(ev["unrecorded"])
                                            if ev["unrecorded"] else ""))
    ec = w["employment_confirmed"]
    out.append("  employment confirmed this week: %d%s%s" % (
        len(ec), " (%s)" % ", ".join(ec) if ec else "",
        "; moved a target off path none on that alone: %s" % ", ".join(wi["confirmation_only"]) if wi["confirmation_only"] else ""))
    s = w["side_door"]
    out.append("SIDE-DOOR since the first ask: %d asked · %d answered · %d named someone · %d notes sent · %d note%s answered"
               % (s["asked"], s["answered"], s["named"], s["notes"], s["notes_answered"], "" if s["notes_answered"] == 1 else "s"))
    out.append("REPLY RATES by ask kind, last %d weeks (resolved asks only; pending and bounces are not in a rate):" % RATE_WINDOW_WEEKS)
    out += [_rate_line(c, w["as_of"]) for c in w["rates"]] or ["  no asks sent in the last %d weeks" % RATE_WINDOW_WEEKS]
    return "\n".join(out)
