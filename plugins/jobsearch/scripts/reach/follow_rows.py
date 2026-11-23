"""follow_rows: who is listed under the Network's "They wrote back" and "Awaiting a reply", and why (jobsearch 0.92.0, dev #1003,
#951, #1002; docs/design-decision-surface.md B.4, owner decisions 2, 3 and 5).

`plan_people(g, people, skip, today, failed, **facts)` replaces `your_move._plan_people`. `g` is the Graph `communication_plan`
already built (passed as an object, never imported); `facts` are `reach.follow_facts.facts(...)`. Per non-merged person with any
touch or message, in order, each person ends as exactly one of: a row, in hand, not listed (one reason), or nothing.

  1. T: the person's threads whose axis is reply-owed, accepted, silent or silence-unverified. Empty: nothing.
  2. In hand (X1): `person:<id>` in `skip` (a staged draft, or a subject an earlier group took) or an open outbox row: no row.
  3. Stopped (B5): `follow_stop.in_force` is true: not listed, `stopped`.
  4. Drop each thread whose `ended_of` is not None (B2), and each reply-owed thread whose newest inbound is more than
     `reply_owed_days` days before today (B1; exactly N days old is still listed).
  5. Pick among what is left: axis rank, newest event, thread id. Nothing left: not listed, and the reason (`ended` or `aged`) is
     the rule that dropped the thread this step would have picked from T.
  6. The linked opportunity (B4): the thread's own; for a person or channel thread, the person's involvements with an opp_id,
     live ones first, then newest sighting; none is legal.
  7. `serves`, first match: application · pursuit · role-undecided · target-company (no live role, the person `current` at an
     `active-target` company by `reach.standing.standing`; `unknown` and `former` never count, X1) · ended-role · relationship.
  8. Clusters (B3): the connected components of `dup_pairs` among people who produced a row. One row per cluster, the best by
     step 5's order; the others give no row and are named in its `duplicates` with their pair `kind` and their own standing.

A row keeps `_plan_people`'s keys and adds `opp_id`, `opp_live`, `opp_title`, `opp_company`, `opp_ending`, `serves`, `age_days`,
`standing`, `duplicates` and `reopened` (`{"stopped_on", "on"}` when a stop was reopened). The text helpers at the bottom are the
Network renderer's words for those keys. Takes rows and functions; imports no entry point and no Graph. Python 3.9+, stdlib only."""

import datetime

from reach import follow_stop
from reach.standing import standing

AXES = {"reply-owed": 0, "accepted": 1, "silent": 2, "silence-unverified": 2}     # the pick, best first
LIVE_SERVES = ("application", "pursuit", "role-undecided")
SERVES_TEXT = {"application": "your application for %(title)s", "pursuit": "the role you are pursuing",
               "role-undecided": "a role you have not decided on", "target-company": "a way in at %(company)s, a target company",
               "ended-role": "the relationship; %(title)s has ended", "relationship": "the relationship"}
KIND_TEXT = {"email": "same email, different name", "name-company": "same name, same employer of record", "name": "same name"}


def _day(value):
    try:
        return datetime.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _newest(events, direction=None):
    return max((str(e.get("date") or "") for e in events if direction is None or e.get("direction") == direction), default="")


def _ranked(axes):
    """The person's candidate threads, best first: axis rank, then the newest event, then the thread id (never the hash-seeded
    order of `axes`)."""
    cand = sorted(((str(t), a, ev) for t, (a, ev) in axes.items() if a in AXES), key=lambda c: c[0])
    cand.sort(key=lambda c: _newest(c[2]), reverse=True)
    cand.sort(key=lambda c: AXES[c[1]])
    return cand


def _dropped(cand, ended_of, today, days):
    """Why step 4 drops thread `cand`: `("ended", None)`, `("aged", the newest inbound day)`, or None when it is kept."""
    tid, axis, events = cand
    if ended_of(tid) is not None:
        return "ended", _newest(events) or None
    if axis == "reply-owed":
        last_in = _day(_newest(events, "inbound"))
        if last_in is not None and (today - last_in).days > days:
            return "aged", last_in.isoformat()
    return None


def _sighted(opp):
    return max((str(s.get("seen_on") or "") for s in opp.get("sightings") or () if isinstance(s, dict)), default="")


def linked_opp(g, pid, tid, opps, ended_of):
    """Step 6: the opportunity a row is about, or None."""
    if tid in opps:
        return tid
    ids = sorted({i.get("opp_id") for i in g.involvements_for_person(pid) if i.get("opp_id") in opps})
    ids.sort(key=lambda o: _sighted(opps[o]), reverse=True)
    ids.sort(key=lambda o: ended_of(o) is not None)
    return ids[0] if ids else None


def serves_of(person, oid, opp, live, today, applied_of, companies):
    """Step 7: what a reply to this person serves."""
    if oid and live:
        if applied_of(oid):
            return "application"
        return "pursuit" if opp.get("verdict") == "pursue" else "role-undecided"
    cid = person.get("company_id")
    if cid and standing(person, cid, today) == "current" and (companies.get(cid) or {}).get("status") == "active-target":
        return "target-company"
    return "ended-role" if oid else "relationship"


def _row(g, pid, person, cand, reopened, f, today):
    """One row for the pick `cand` (steps 6 and 7), with `_plan_people`'s keys and the B.4 ones."""
    tid, axis, events = cand
    last = _newest(events) or None
    group = "reply-owed" if axis == "reply-owed" else "awaiting-reply"
    why, step = {"reply-owed": ("they wrote back on %s and no reply is drafted" % (last or "?"), "reply"),
                 "accepted": ("they accepted your connection", "send the note now that they accepted")}.get(
        axis, ("no reply in %d days%s" % (f["chase"], "" if axis == "silent" else " (not yet verified in your mailbox)"), "nudge"))
    oid = linked_opp(g, pid, tid, f["opps"], f["ended_of"])
    opp = f["opps"].get(oid) or {}
    ending = f["ended_of"](oid) if oid else None
    co = (f["companies"].get(opp.get("company_id")) or {}) if oid else (f["companies"].get(person.get("company_id")) or {})
    day = _day(last)
    return {"key": "person:%s" % pid, "subject": "person:%s" % pid, "group": group, "state": axis,
            "who": person.get("name") or pid, "why": why, "last_touch": last, "next_step": step,
            "actions": [{"action": "draft-message", "rec_id": "person:%s" % pid, "label": "Draft it"}],
            "opp_id": oid, "opp_live": (ending is None) if oid else None, "opp_title": opp.get("title") or oid,
            "opp_company": co.get("name") or opp.get("company_id") or person.get("company_id"), "opp_ending": ending,
            "serves": serves_of(person, oid, opp, oid is not None and ending is None, today, f["applied_of"], f["companies"]),
            "age_days": (today - day).days if day else None, "standing": _standing(person, today), "duplicates": [],
            "reopened": reopened}


def _standing(person, today):
    try:
        return standing(person, person.get("company_id"), today)
    except ValueError:
        return None


def _hidden(pid, person, why, on, opp=None, companies=None):
    co = ((companies or {}).get((opp or {}).get("company_id")) or {}).get("name") or (opp or {}).get("company_id")
    return {"id": pid, "name": person.get("name") or pid, "why": why, "on": on,
            "title": (opp or {}).get("title"), "company": co}


def _one(g, pid, person, skip, today, failed, f):
    """Steps 1 to 7 for one person: `("row", rank, row)`, `("hidden", entry)`, or None (nothing, or in hand)."""
    if "person:%s" % pid in skip:
        return None
    try:
        axes = f["axes_of"](pid)
    except Exception as e:                                     # noqa: BLE001 - said, never an empty group
        failed.append("awaiting-reply %s: %s: %s" % (pid, type(e).__name__, str(e)[:80]))
        return None
    cands = _ranked(axes)
    if not cands or pid in f["outbox_open"]:
        return None
    on, stop, reopened = follow_stop.in_force(g.touches_for_person(pid), g.messages_for_person(pid))
    if on:
        return ("hidden", _hidden(pid, person, "stopped", stop.get("date")))
    kept = [c for c in cands if _dropped(c, f["ended_of"], today, f["reply_owed_days"]) is None]
    if not kept:
        why, when = _dropped(cands[0], f["ended_of"], today, f["reply_owed_days"])
        return ("hidden", _hidden(pid, person, why, when, f["opps"].get(cands[0][0]), f["companies"]))
    back = {"stopped_on": stop.get("date"), "on": reopened["on"]} if stop is not None and reopened else None
    pick = kept[0]
    return ("row", (AXES[pick[1]], _inv(_newest(pick[2])), pid), _row(g, pid, person, pick, back, f, today))


def _inv(s):
    """A sort key that orders ISO strings newest first under an ascending sort (an empty one last)."""
    return (0, tuple(-ord(ch) for ch in s)) if s else (1, ())


def _clusters(rows, pairs):
    """`{pid: [other pid, ...]}` for the best row of each duplicate cluster, and the set of pids folded into one (B3)."""
    adj = {}
    for p in pairs:
        if p["a"] in rows and p["b"] in rows:
            adj.setdefault(p["a"], set()).add(p["b"])
            adj.setdefault(p["b"], set()).add(p["a"])
    best, folded, seen = {}, set(), set()
    for start in sorted(adj):
        if start in seen:
            continue
        comp, todo = set(), [start]
        while todo:
            x = todo.pop()
            if x not in comp:
                comp.add(x)
                todo.extend(adj.get(x, ()) - comp)
        seen |= comp
        top = min(comp, key=lambda q: rows[q][0])
        best[top] = sorted(comp - {top})
        folded |= comp - {top}
    return best, folded


def _kind(pairs, a, b):
    for p in pairs:
        if {p["a"], p["b"]} == {a, b}:
            return p["kind"]
    return next((p["kind"] for p in pairs if b in (p["a"], p["b"])), None)


def plan_people(g, people, skip, today, failed, **f):
    """`(owed_rows, awaiting_rows, not_listed)`: the reply-owed and awaiting-reply rows, each oldest last message first, and
    `{"days": N, "people": [{"id", "name", "why", "on", "title", "company"}]}` (the module docstring). `today` is an ISO day."""
    day = _day(today)
    talked = ({t.get("person_id") for t in follow_stop.ordinary(g.stores["touches"])}
              | {m.get("person_id") for m in g.stores["messages"]})
    rows, hidden = {}, []
    for pid in sorted(x for x in talked if x in people and people[x].get("status") != "merged"):
        got = _one(g, pid, people[pid], skip, day, failed, f)
        if got and got[0] == "row":
            rows[pid] = got[1:]
        elif got:
            hidden.append(got[1])
    best, folded = _clusters(rows, f["dup_pairs"])
    out = {"reply-owed": [], "awaiting-reply": []}
    for pid, (_rank, row) in rows.items():
        if pid in folded:
            continue
        row["duplicates"] = [{"id": o, "name": (people.get(o) or {}).get("name") or o, "kind": _kind(f["dup_pairs"], pid, o),
                              "standing": _standing(people.get(o) or {}, day)} for o in best.get(pid, ())]
        out[row["group"]].append((row["last_touch"] or "9999", row))
    order = {"aged": 0, "ended": 1, "stopped": 2}
    hidden.sort(key=lambda h: (order[h["why"]], str(h["name"]), h["id"]))
    return (tuple([r for _d, r in sorted(out[k], key=lambda t: (t[0], t[1]["key"]))] for k in ("reply-owed", "awaiting-reply"))
            + ({"days": f["reply_owed_days"], "people": hidden},))


# ── the renderer's words (dashboard/network.py) ─────────────────────────────────────────────────────────────────────────────────

def why_text(row):
    """A row's first line after the name. It carries the row's date, so the renderer prints no separate `last touch` line for it
    (a wording cut that keeps the busy page inside its open-word budget, tests/test_dashboard_budget.py)."""
    last, state = row.get("last_touch") or "?", row.get("state")
    if state == "reply-owed":
        age = row.get("age_days")
        return "wrote back on %s%s; no reply drafted" % (
            last, (" (%d day%s ago)" % (age, "" if age == 1 else "s")) if isinstance(age, int) else "")
    if state == "accepted":
        return "accepted your connection on %s" % last
    if state in ("silent", "silence-unverified"):
        return "no reply since %s%s" % (last, "" if state == "silent" else " (not yet verified in your mailbox)")
    return row.get("why") or ""


def about_text(row):
    """What the row is about: `about <title> at <company> (live | ended: <ending>)`, or `no role`."""
    if not row.get("opp_id"):
        return "no role"
    return "about %s at %s (%s)" % (row.get("opp_title"), row.get("opp_company") or "?",
                                    "live" if row.get("opp_live") else "ended: %s" % row.get("opp_ending"))


def serves_text(row):
    """What a reply (or a nudge) serves, in the page's words."""
    verb = "a reply" if row.get("state") == "reply-owed" else "a nudge" if row.get("next_step") == "nudge" else "a note"
    return "%s serves %s" % (verb, SERVES_TEXT.get(row.get("serves"), "the relationship")
                             % {"title": row.get("opp_title") or "the role", "company": row.get("opp_company") or "the company"})


def duplicate_text(row):
    """The possible-duplicate line, or "" when the row has none. It states the flag and stops (design F4, F16)."""
    out = []
    for d in row.get("duplicates") or ():
        words = {row.get("standing"), d.get("standing")}
        stand = ("both recorded as working there now" if words == {"current"} else
                 "one formerly there" if "former" in words else "employment unconfirmed")
        out.append("possible duplicate of %s (%s; %s)" % (d.get("name"), KIND_TEXT.get(d.get("kind"), "same person?"), stand))
    return "; ".join(out)


def back_text(row):
    """The reopened line, or ""."""
    r = row.get("reopened")
    return ("back on this list: they wrote on %s, after you stopped following on %s" % (r["on"], r["stopped_on"])) if r else ""
