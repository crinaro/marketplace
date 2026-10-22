#!/usr/bin/env python3
"""The warm-path next action for every role that passed screening (dev #751; design-sourcing-feeds.md §4).

    warm_path.py                       # one line per action (read-only)
    warm_path.py --opp <opp_id>        # the action covering that role: what `outreach-drafter` is given
    warm_path.py --json [--opp <id>]   # the same, as data (the dashboard and any future mod read this)

⭐ WHY A SCRIPT, AND WHY DERIVED. Referrals are the evidenced lever: eleven ATS applications produced nine
auto-acks, one rejection and no human contact, while warm outreach replied half the time and produced
every advancing conversation (`daily-run/SKILL.md`, the rule this script absorbs). So EVERY role that
passes screening gets one next action toward an inside human, and which action is computable from stores
that already exist -- people, involvements, touches, messages, drafts and applications. ADR-022 ("derive
from evidence") applies: a stored copy would be a second record that could disagree. The ONE fact no store
holds is "the candidate looked and found nobody": `companies[].warm_lookup` (`record.py warm-lookup`).

    kind      referral-ask   the best-placed known person is not the hiring manager: ask for a referral or an
                             introduction to the hiring team, naming every role the candidate wants there
              hm-note        that person IS the hiring manager (their best involvement path_type): a short
                             direct note
              lookup         nobody is known at the company

    state     (first match wins)
              touched        a SENT touch to that person names one of these roles, or any sent touch to them is
                             within `warm_days` (180): the relationship was just worked, so no second ask
              drafted        an open (not sent, not moot) draft in outreach/drafts.md is addressed `**To:**` to
                             that person
              draft-owed     a person is chosen and a role is `verdict: pursue` or has a submitted application:
                             `outreach-drafter` is owed a draft
              ready          a person is chosen and every role is still undecided: the action is SHOWN and
                             drafting waits for the decision (design Q1: a draft per screened-in role would fill
                             drafts.md with asks for roles the candidate may pass on)
              looked-none    kind lookup, and `companies[].warm_lookup.on` is within `search.warm_lookup_days`
              lookup-owed    kind lookup otherwise

⭐ ONE ACTION PER (COMPANY, PERSON). Two eligible roles whose best person is the same yield ONE action whose
`opp_ids` lists both: a relationship is asked once, not once per requisition. A role whose best person is
someone else is its own action.

⭐ NO LINKEDIN STEP IS AUTOMATED (User Agreement §8.2, items 2 and 13; ADR-036). `kind: lookup` is a LINK the
candidate opens, built only from a `linkedin.com/company/<x>` URL already in the company row's
`research_log`; with none, the line says to search LinkedIn for the company's people and builds no URL from
a guess. This script opens nothing, reads nothing from LinkedIn, and writes nothing at all. NOTHING IN THIS
GROUP SENDS: a draft is saved to outreach/drafts.md for the candidate to send, as every draft is.

⭐ THE REFERRAL WORDING STAYS LICENSED ONLY BY THE EXISTING has-referral PREDICATE (`plays.py`, the `say`
list): this script decides WHO and WHICH KIND; what a draft may SAY to that person is still the play's
licence, read by `outreach-drafter` from its `play` packet section. A `referral-ask` is an ask for one, never
a claim that one exists.

Eligible roles: `status` not terminal, not folded (`duplicate_of`), a STORED `screen` whose verdict is not
`remove:*` (read off the stored screen, never re-derived), and `verdict` not `pass`. An applied role is
eligible, which is how the daily run's old "warm-path on every application" rule is absorbed.

Person: non-merged people whose `company_id` is the role's company, or who have an `involvements` row on an
opportunity at that company. A person's rank is their best usable involvement `path_type`: `warm-referral`
and `internal` first, then `hiring-manager`, then `hiring-context`; `recruiter` and `cold` are never a warm
path. An involvement on THIS role outranks one on a sibling role (so two roles can have different best
people); a person with a `company_id` and no involvement at all ranks last. Ties go to the most recent
inbound message, then to `id`.

Python 3.9+. Standard library only. Read-only.
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

ROOT = _profile_root()

KINDS = ("referral-ask", "hm-note", "lookup")
STATES = ("ready", "draft-owed", "drafted", "touched", "lookup-owed", "looked-none")
PATH_RANK = {"warm-referral": 0, "internal": 0, "hiring-manager": 1, "hiring-context": 2}
NOT_WARM = ("recruiter", "cold")
OTHER_ROLE_PENALTY = 10         # a sibling-role involvement ranks below any involvement on this role
NO_INVOLVEMENT_RANK = 30
WARM_DAYS = 180                 # your_move.classify_people's existing window
LINKEDIN_COMPANY_RE = re.compile(r"linkedin\.com/company/([A-Za-z0-9_%.\-]+)", re.I)
TO_RE = re.compile(r"^\*\*To:\*\*\s*contact:(\S+)", re.M | re.I)


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _date(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def eligible(o):
    """True for a role that passed screening and is still a live decision (see the module docstring)."""
    import validate_data as _vd
    scr = o.get("screen")
    verdict = scr.get("verdict") if isinstance(scr, dict) else None
    return (o.get("status") not in _vd.TERMINAL_OPP_STATUSES and not o.get("duplicate_of")
            and isinstance(verdict, str) and not verdict.startswith("remove")
            and o.get("verdict") != "pass")


def open_draft_recipients(root):
    """`{person_id: [entry titles]}` for the OPEN drafts in outreach/drafts.md: an entry with a
    `**To:** contact:<id>` line whose `**Status:**` does not open with `sent` and does not name it moot or
    do-not-send (`precondition.py`'s own tests), parsed with its own entry splitter."""
    import _tree
    import precondition as _pc
    try:
        with open(_tree.resolve_rel(root, _tree.rel("drafts")), encoding="utf-8") as fh:
            md = fh.read()
    except OSError:
        return {}
    out = {}
    for m in _pc.ENTRY_RE.finditer(md):
        title, body = m.group(1).strip(), m.group(2)
        sm = _pc.STATUS_RE.search(body)
        if sm and (_pc.SENT_RE.match(sm.group(1)) or _pc.MOOT_RE.search(sm.group(1))):
            continue
        tm = TO_RE.search(body)
        if tm:
            out.setdefault(tm.group(1), []).append(title)
    return out


def _linkedin_url(company):
    """The company-people page, only when a `linkedin.com/company/<x>` URL is ALREADY on record in the
    company row's `research_log`; never built from a guess."""
    for entry in (company or {}).get("research_log") or []:
        m = LINKEDIN_COMPANY_RE.search(str((entry or {}).get("note") or ""))
        if m:
            return "https://www.linkedin.com/company/%s/people/" % m.group(1).rstrip("/")
    return None


def derive(root=None, today=None, warm_days=WARM_DAYS, lookup_days=90):
    """The list of actions, one per (company, person) and one per company with nobody known, in a stable
    order (company, then first opp id). Each is

        {opp_ids: [...], company_id, kind, person_id | None, person_name | None, state, why,
         on | None (the touch / lookup date for `touched` / `looked-none`), linkedin_url | None}

    Read-only over the stores under `root`."""
    import graph as _graph
    root = root or ROOT
    today = _date(today) or datetime.date.today()
    data = os.path.join(root, "data")
    g = _graph.Graph(data)
    opps = [o for o in _load(os.path.join(data, "opportunities.jsonl")) if eligible(o)]
    companies = {c.get("id"): c for c in _load(os.path.join(data, "companies.jsonl"))}
    apps = _load(os.path.join(data, "applications.jsonl"))
    import validate_data as _vd
    applied = {a.get("opp_id") for a in apps if a.get("status") in _vd.SUBMITTED_APP_STATUS}
    all_opps = _load(os.path.join(data, "opportunities.jsonl"))
    opp_company = {o.get("id"): o.get("company_id") for o in all_opps}
    drafts_to = open_draft_recipients(root)
    drafts_to_resolved = {}
    for pid, titles in drafts_to.items():
        try:
            row = g.resolve_person(pid)
        except _graph.MergeCycleError:
            row = None
        drafts_to_resolved.setdefault((row or {}).get("id") or pid, []).extend(titles)

    def survivor(pid):
        try:
            row = g.resolve_person(pid)
        except _graph.MergeCycleError:
            return None
        return row if row and row.get("status") != "merged" else None

    def inbound_date(pid):
        best = None
        for m in g.messages_for_person(pid):
            if m.get("direction") == "inbound":
                d = _date(m.get("sent_on"))
                if d and d <= today and (best is None or d > best):
                    best = d
        return best

    def ranked_candidates(opp):
        """[(rank, -inbound ordinal, id, person row, best path_type)] for one role, best first."""
        cid = opp.get("company_id")
        out = []
        for p in g.stores["people"]:
            p = survivor(p.get("id"))
            if p is None or any(p["id"] == r[3]["id"] for r in out):
                continue
            invs = g.involvements_for_person(p["id"])
            at_company = [i for i in invs if opp_company.get(i.get("opp_id")) == cid]
            if p.get("company_id") != cid and not at_company:
                continue
            usable = [(0 if i.get("opp_id") == opp.get("id") else OTHER_ROLE_PENALTY)
                      + PATH_RANK[i.get("path_type")] for i in at_company if i.get("path_type") in PATH_RANK]
            if at_company and not usable and all(i.get("path_type") in NOT_WARM for i in at_company):
                continue                                  # recruiter / cold: never a warm path
            rank = min(usable) if usable else NO_INVOLVEMENT_RANK
            best = None
            for i in at_company:
                pt = i.get("path_type")
                if pt in PATH_RANK and (0 if i.get("opp_id") == opp.get("id") else OTHER_ROLE_PENALTY) \
                        + PATH_RANK[pt] == rank:
                    best = pt
            inb = inbound_date(p["id"])
            out.append((rank, -(inb.toordinal() if inb else 0), p["id"], p, best))
        return sorted(out, key=lambda r: (r[0], r[1], r[2]))

    groups = {}                          # (company_id, person_id | None) -> [opp ids, in order]
    chosen = {}
    for o in sorted(opps, key=lambda x: str(x.get("id"))):
        cands = ranked_candidates(o)
        key = (o.get("company_id"), cands[0][3]["id"] if cands else None)
        groups.setdefault(key, []).append(o["id"])
        if cands:
            chosen[key] = (cands[0][3], cands[0][4])
    by_id = {o["id"]: o for o in opps}

    actions = []
    for (company_id, person_id), opp_ids in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[1][0])):
        company = companies.get(company_id) or {}
        cname = company.get("name") or company_id or "this company"
        roles = ", ".join("%s (%s)" % (by_id[i].get("title") or i, i) for i in opp_ids)
        act = {"opp_ids": opp_ids, "company_id": company_id, "person_id": person_id,
               "person_name": None, "on": None, "linkedin_url": None}
        if person_id is None:
            wl = company.get("warm_lookup") if isinstance(company.get("warm_lookup"), dict) else None
            looked = _date((wl or {}).get("on"))
            act["kind"] = "lookup"
            act["linkedin_url"] = _linkedin_url(company)
            if looked and 0 <= (today - looked).days <= lookup_days:
                act["state"] = "looked-none"
                act["on"] = looked.isoformat()
                act["why"] = "looked %s, no one found at %s" % (looked.isoformat(), cname)
            else:
                act["state"] = "lookup-owed"
                if act["linkedin_url"]:
                    where = "Look on LinkedIn: %s" % act["linkedin_url"]
                else:
                    where = "Search LinkedIn for %s people" % cname
                act["why"] = ("No one known at %s. %s, then record who you found (a people row and "
                              "`record.py involve`), or `record.py warm-lookup %s --none-found`."
                              % (cname, where, company_id))
            actions.append(act)
            continue
        person, best = chosen[(company_id, person_id)]
        act["kind"] = "hm-note" if best == "hiring-manager" else "referral-ask"
        pname = person.get("name") or person_id
        act["person_name"] = pname
        touches = [t for t in g.touches_for_person(person_id) if t.get("status") == "sent"]
        recent = [t for t in touches if _date(t.get("date")) and 0 <= (today - _date(t.get("date"))).days <= warm_days]
        on_role = [t for t in touches if t.get("opp_id") in opp_ids]
        if on_role or recent:
            t = sorted(on_role or recent, key=lambda x: str(x.get("date")))[-1]
            act["state"] = "touched"
            act["on"] = str(t.get("date"))[:10]
            act["why"] = "asked %s on %s (%s)" % (pname, str(t.get("date"))[:10],
                                                  "this role" if on_role else "within %d days" % warm_days)
        elif drafts_to_resolved.get(person_id):
            act["state"] = "drafted"
            act["why"] = "a draft to %s is waiting in outreach/drafts.md (%s)" % (
                pname, drafts_to_resolved[person_id][0])
        elif any(by_id[i].get("verdict") == "pursue" or i in applied for i in opp_ids):
            act["state"] = "draft-owed"
            act["why"] = "%s for %s at %s: a draft is owed (`outreach-drafter`; nothing is sent)" % (
                "a note to the hiring manager" if act["kind"] == "hm-note" else "a referral ask",
                pname, cname)
        else:
            act["state"] = "ready"
            act["why"] = "%s is %s at %s; the draft waits for your pursue/pass decision on %s" % (
                pname, "the hiring manager" if act["kind"] == "hm-note" else "a known contact",
                cname, roles)
        actions.append(act)
    return actions


def for_opportunity(actions, opp_id):
    return next((a for a in actions if opp_id in a["opp_ids"]), None)


def format_line(a, titles=None):
    who = a["person_id"] or "nobody known"
    return "WARM %-12s %-11s %s -> %s: %s [roles: %s]" % (
        a["kind"], a["state"], a["company_id"], who, a["why"], ", ".join(a["opp_ids"]))


def _lookup_days(cfg):
    import config_keys as _ck
    return _ck.resolve_int(cfg, _ck.SEARCH_WARM_LOOKUP_DAYS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Derive the warm-path next action for each screened-in role.")
    ap.add_argument("--opp", metavar="OPP_ID")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--today", metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)
    try:
        import profile as _profile
        lookup_days = _lookup_days(_profile.config())
    except ValueError as e:
        print("⛔ %s" % e)
        return 1
    except Exception:                                                    # noqa: BLE001 - no readable config
        lookup_days = 90
    actions = derive(today=args.today, lookup_days=lookup_days)
    if args.opp:
        a = for_opportunity(actions, args.opp)
        if args.json:
            print(json.dumps(a, indent=1))
        elif a is None:
            print("WARM none: %s is not eligible (terminal, folded, removed by the screen, passed, or "
                  "not screened yet)" % args.opp)
        else:
            print(format_line(a))
        return 0
    if args.json:
        print(json.dumps(actions, indent=1))
        return 0
    for a in actions:
        print(format_line(a))
    if not actions:
        print("WARM none: no role has passed screening and is still open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
