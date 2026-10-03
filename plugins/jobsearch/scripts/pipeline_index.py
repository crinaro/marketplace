#!/usr/bin/env python3
"""
A compact one-line-per-role index of the pipeline — the cheap answer to
"is this role already tracked?"

WHY THIS EXISTS
---------------
`inbox-scan` runs on haiku with a ~650-word brief, and its job is to decide whether a role
in an alert is new. To do that it was being pointed at `data/opportunities.jsonl` — 161 full
records with research logs, outreach arrays and application history — which is the single
largest unnecessary read in the daily flow. The question is "have we seen this?", and that
is answerable from one line per record.

Same principle as `alert_sweep.py`: deterministic work belongs in a query, not in a model
summary (CLAUDE.md token discipline).

Usage:
    python3 scripts/pipeline_index.py                # active roles (the default view)
    python3 scripts/pipeline_index.py --all          # every record, including passed
    python3 scripts/pipeline_index.py --excluded     # ONLY the exclusion list
    python3 scripts/pipeline_index.py --company acme # filter by company id substring
    python3 scripts/pipeline_index.py --contacts     # include contact names
    python3 scripts/pipeline_index.py --match --company <company_id> --title "Sr. Eng Manager"
                                                     # is this sourced role an already-passed one
                                                     # under a different id? (also --jd-url / --req-id)

THE EXCLUSION LIST is `verdict: pass` OR `status: passed`. That definition lives here and in
`docs/schema.md`; agents should call this script rather than re-deriving it, because an agent
that invents its own definition of "already excluded" will re-surface roles the candidate has declined.

⭐ `status: expired` (issue #6) is terminal but is NOT on the exclusion list. Excluded means
the candidate DECLINED — never resurface. Expired means the posting vanished before any decision
was made, so a NEW sighting of an expired role is a repost and must surface as a fresh signal,
not be auto-dropped as "already ruled out". Expired rows are hidden from the default (active)
view — they are not live work — and counted separately in the footer.

⭐ A PASSED ROLE STAYS PASSED UNDER A NEW ID (dev #670 / public #136). A role re-sourced with a
different id or slug is the SAME role. `find_excluded_match()` below is the one definition of
"is this sourced role an excluded one?" — the same `company_id` plus a normalized title
(`normalize_title`), or an identical `jd_url`, or an identical ATS requisition id. `record.py
create` calls it before it writes an opportunity row, and `--match` here answers it for a
caller that has no row yet. Do not re-derive it elsewhere: a second copy of the normalization
table is how two paths come to disagree about which roles are the same.

Python 3.9+. Standard library only.
"""

import argparse
import collections
import json
import os
import re
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

ROOT = _profile_root()
DATA = os.path.join(ROOT, "data")


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def is_excluded(o):
    """The one definition of 'already ruled out'. Do not re-derive this elsewhere.

    Deliberately does NOT include `status: expired` — see the module docstring: a re-sighting
    of an expired role is a repost, and treating it as 'already ruled out' would silently drop
    the second chance the candidate never declined."""
    return o.get("verdict") == "pass" or o.get("status") == "passed"


# dev #670 — job-title abbreviations, expanded to full words so "Sr. Eng Manager" and "Senior
# Engineering Manager" compare equal. Deliberately short and fixed: the O*NET alternate-titles
# data is a whole taxonomy (a dependency decision); this covers the abbreviations a posting
# title actually shortens. An ambiguous one ("dev": developer or development) is left OUT —
# a wrong expansion would merge two genuinely different roles, which costs a missed lead.
TITLE_ABBREVIATIONS = {
    "sr": "senior", "jr": "junior", "eng": "engineering", "engr": "engineer",
    "mgr": "manager", "mngr": "manager", "dir": "director",
    "vp": "vice president", "svp": "senior vice president",
    "evp": "executive vice president", "avp": "assistant vice president",
    "asst": "assistant", "assoc": "associate", "ops": "operations", "mktg": "marketing",
    "&": "and",
}


def normalize_title(title):
    """casefold, punctuation to spaces, abbreviations expanded, whitespace collapsed.

    'Sr. Eng Manager' and 'Senior Engineering Manager' both give 'senior engineering manager'.
    Returns '' for a missing title, and an empty result NEVER matches anything (see
    find_excluded_match) — a blank title is not evidence two roles are the same."""
    t = str(title or "").casefold().replace("&", " & ")
    words = []
    for tok in re.split(r"[^\w&]+", t):
        if tok:
            words.extend(TITLE_ABBREVIATIONS.get(tok, tok).split())
    return " ".join(words)


def find_excluded_match(opps, company_id=None, title=None, jd_url=None, req_id=None,
                        applications=None):
    """The excluded row a sourced role duplicates, as `(row, basis)`, or None.

    A match is any of, strongest first: an identical non-empty `jd_url`; an identical ATS
    requisition id (the excluded opportunity's own `req_id`, read from `applications`, where
    that value lives); the same non-empty `company_id` plus an equal NON-EMPTY normalized
    title. Only rows `is_excluded` counts — an expired or active row is never a match
    (module docstring: a repost of an expired role must surface). `basis` names which test hit,
    so the caller can say why. Pure: it reads only what it is handed.
    """
    reqs = collections.defaultdict(set)
    for a in applications or []:
        if a.get("opp_id") and a.get("req_id"):
            reqs[a["opp_id"]].add(str(a["req_id"]).strip().casefold())
    want_url = str(jd_url or "").strip()
    want_req = str(req_id or "").strip().casefold()
    want_title = normalize_title(title)
    excluded = [o for o in opps if is_excluded(o)]
    if want_url:
        for o in excluded:
            if str(o.get("jd_url") or "").strip() == want_url:
                return o, "jd_url"
    if want_req:
        for o in excluded:
            if want_req in reqs.get(o.get("id"), ()):
                return o, "req_id"
    if company_id and want_title:
        for o in excluded:
            if o.get("company_id") == company_id and normalize_title(o.get("title")) == want_title:
                return o, "company + title"
    return None


def describe_match(row, basis):
    """One line naming the existing row — the 'previously passed, pointing at the existing row'
    report. Never a stored field: it is output only (dev #670)."""
    return ("PREVIOUSLY PASSED — matches existing opportunity %r (company %s, title %r, "
            "status %s, verdict %s) on %s."
            % (row.get("id"), row.get("company_id") or "?", row.get("title") or "?",
               row.get("status") or "?", row.get("verdict") or "?", basis))


def is_expired(o):
    """Terminal without a decision: the posting vanished before the candidate ruled on it."""
    return o.get("status") == "expired"


def main():
    ap = argparse.ArgumentParser(description="Compact pipeline index.")
    ap.add_argument("--all", action="store_true", help="Include excluded/closed records.")
    ap.add_argument("--excluded", action="store_true", help="Show ONLY the exclusion list.")
    ap.add_argument("--company", metavar="SUBSTR", help="Filter by company_id substring.")
    ap.add_argument("--contacts", action="store_true", help="Append contact names.")
    ap.add_argument("--match", action="store_true",
                    help="Is a sourced role (--company <company_id> --title, and/or --jd-url, "
                         "--req-id) an already-passed one under a different id? dev #670.")
    ap.add_argument("--title", metavar="TITLE", help="With --match: the sourced role's title.")
    ap.add_argument("--jd-url", dest="jd_url", metavar="URL", help="With --match.")
    ap.add_argument("--req-id", dest="req_id", metavar="ID",
                    help="With --match: the ATS requisition id, when the posting carries one.")
    ap.add_argument("--person", metavar="NAME",
                    help="Everything known about one person, across every opportunity.")
    args = ap.parse_args()

    opps = load("opportunities.jsonl")
    import applications as _apps                # ADR-031 B2 — o["_applications"], never nested
    _apps.enrich_opportunities(ROOT, opps)
    import touches as _touches                  # ADR-031 B3 — o["_touches"], never nested
    _touches.enrich_opportunities(ROOT, opps)
    companies = {c["id"]: c.get("name", c["id"]) for c in load("companies.jsonl")}

    if args.match:
        # dev #670 / public #136 — the exclusion list asked about ONE sourced role, not listed.
        # A query: rc 0 either way, the first line is the answer.
        if not (args.jd_url or args.req_id or (args.company and args.title)):
            print("--match needs --company <company_id> with --title, or --jd-url, or --req-id.")
            return 2
        hit = find_excluded_match(opps, company_id=args.company, title=args.title,
                                  jd_url=args.jd_url, req_id=args.req_id,
                                  applications=load("applications.jsonl"))
        print(describe_match(*hit) if hit else
              "NOT EXCLUDED — no already-passed opportunity matches; this role is new.")
        return 0

    if args.person:
        # "What is the whole history with this person?" — the question that was
        # unanswerable until outreach[] gained a contact_id joining it to contacts[]
        # (2026-08-02), and ADR-031 B1 promoted the join to a GLOBAL `people` store: a
        # recruiter or warm contact spans several opportunities, or none (a relationship
        # anchored only to a channel) — `people`/`involvements` is where that lives now.
        needle = args.person.lower()
        people = {p["id"]: p for p in load("people.jsonl")}
        involvements = load("involvements.jsonl")
        opps_by_id = {o.get("id"): o for o in opps}
        found = False
        for pid, p in people.items():
            if needle not in (p.get("name") or "").lower():
                continue
            found = True
            print("%s — %s" % (p.get("name"), companies.get(p.get("company_id"),
                                                             p.get("company_id") or "—")))
            print("  email    : %s" % (p.get("email") or "— none on record"))
            print("  linkedin : %s" % (p.get("linkedin") or "—"))
            if p.get("status") == "merged":
                print("  status   : merged into %s" % p.get("merged_into"))
            for inv in involvements:
                if inv.get("person_id") != pid:
                    continue
                o = opps_by_id.get(inv.get("opp_id"))
                if o:
                    print("  role     : %s" % (inv.get("role") or inv.get("path_type") or "?"))
                    print("  opp      : %s  [%s / %s]" % (o["id"], o.get("status"),
                                                          o.get("stage")))
                    touches = [r for r in (o.get("_touches") or [])
                              if r.get("person_id") == pid]
                    if not touches:
                        print("  touches  : none recorded")
                    for r in sorted(touches, key=lambda x: x.get("date") or ""):
                        print("    %s  %-14s %-24s %s" % (r.get("date"), r.get("outcome"),
                                                         r.get("medium"), r.get("touch_type")))
                        if r.get("responded_on"):
                            print("               replied %s" % r["responded_on"])
                elif inv.get("channel_id"):
                    print("  channel  : %s  role=%s" % (inv["channel_id"],
                                                        inv.get("role") or inv.get("path_type") or "?"))
                if inv.get("note"):
                    print("  notes    : %s" % str(inv["note"])[:220])
            if p.get("note"):
                print("  notes    : %s" % str(p["note"])[:220])
            print()
        if not found:
            print("No person matching %r. Names come from data/people.jsonl (ADR-031 B1)."
                  % args.person)
            return 1
        return 0

    rows = opps
    if args.excluded:
        rows = [o for o in rows if is_excluded(o)]
    elif not args.all:
        rows = [o for o in rows if not is_excluded(o) and not is_expired(o)]
    if args.company:
        rows = [o for o in rows if args.company.lower() in (o.get("company_id") or "").lower()]

    if args.excluded:
        header = "EXCLUSION LIST — already ruled out (verdict: pass OR status: passed)"
    elif args.all:
        header = "FULL PIPELINE"
    else:
        header = "ACTIVE PIPELINE — excluded records hidden (use --all or --excluded)"
    print("%s — %d of %d record(s)" % (header, len(rows), len(opps)))
    print("=" * 130)
    # `play` added with dev #95's follow-on: a session asking "is this tracked?" could not
    # see the post-application play position, so the field existed and no reader met it.
    print("  %-42s | %-20s | %-15s | %-11s | %-23s | %-5s | %s"
          % ("title", "company", "status", "stage", "play", "A=app T=touch", "verdict"))
    print("-" * 130)

    # ADR-031 B4 (design §19) — the `play` column is now DERIVED, per pursuit, from the play
    # engine, never a hand-set cursor. One Context, built once, reused across every row.
    import plays as _plays_mod
    import validate_data as _vd_mod
    _play_ctx = _plays_mod.Context(ROOT)
    _today_iso = __import__("datetime").date.today().isoformat()

    def _play_label(o):
        plan = _play_ctx.plans_by_id.get(o.get("plan_id"))
        play = _play_ctx.plays_by_id.get((plan or {}).get("play_id"))
        ns = _plays_mod.next_step(plan, play, o, _play_ctx, _today_iso)
        if ns.kind == "step":
            return ns.step
        return ns.kind

    # ADR-031 B1 — `--contacts` joins through `involvements`, not a nested `contacts[]` array.
    _people_by_id = {p["id"]: p for p in load("people.jsonl")} if args.contacts else {}
    _person_ids_by_opp = collections.defaultdict(list)
    if args.contacts:
        for inv in load("involvements.jsonl"):
            if inv.get("opp_id"):
                _person_ids_by_opp[inv["opp_id"]].append(inv.get("person_id"))

    for o in sorted(rows, key=lambda x: ((x.get("company_id") or ""), x.get("id"))):
        # ⭐ ACTIVITY COLUMN — added 2026-08-03. `stage` is a MODEL of where a role is; this is
        # the RECEIPT of what was actually sent. On 2026-08-03 I read `research_log: 0` on three
        # records and reported them to the candidate as "never researched, sitting unexamined" — while
        # each had an application filed 07/31 WITH a cover letter and four outreach touches the
        # same day. The candidate corrected me. An empty research_log is not an unworked role, and `stage:
        # contacted` did not disambiguate it. **Never infer that nothing was done from ONE array.**
        napp = len(o.get("_applications") or [])
        nout = len([r for r in (o.get("_touches") or []) if r.get("status") == "sent"])
        act = ("A%d" % napp if napp else "  ") + " " + ("T%d" % nout if nout else "  ")
        line = "%-42s | %-20s | %-15s | %-11s | %-23s | %-5s | %s" % (
            (o.get("title") or "?")[:42],
            (companies.get(o.get("company_id"), o.get("company_id") or "?"))[:20],
            (o.get("status") or "?")[:15],
            (o.get("stage") or "?")[:11],
            (_play_label(o) or "—")[:23],
            act,
            (o.get("verdict") or "?"),
        )
        print("  " + line)
        if args.contacts:
            names = [_people_by_id.get(pid, {}).get("name")
                    for pid in _person_ids_by_opp.get(o.get("id"), [])]
            names = [n for n in names if n]
            reached = [r.get("to") for r in (o.get("_touches") or []) if r.get("to")]
            if names or reached:
                print("      contacts: %s" % (", ".join(names) or "none"))
                if reached:
                    print("      contacted: %s" % ", ".join(reached))

    if not args.excluded and not args.all:
        n_excl = sum(1 for o in opps if is_excluded(o))
        print("\n  (%d excluded record(s) hidden — see --excluded before treating a role as new)"
              % n_excl)
        n_exp = sum(1 for o in opps if is_expired(o) and not is_excluded(o))
        if n_exp:
            print("  (%d expired record(s) hidden — terminal but NEVER declined; a re-sighting "
                  "is a repost and should surface)" % n_exp)
    # ADR-031 B4 (design §19) — `play_stage 'unresolved'`'s successor is a STALLED play,
    # visible via `plays.py --check` (a check that can actually fire, unlike a hand-set marker
    # nobody was forced to update).
    n_stalled = sum(1 for o in opps if o.get("status") not in _vd_mod.TERMINAL_OPP_STATUSES
                    and _plays_mod.next_step(
                        _play_ctx.plans_by_id.get(o.get("plan_id")),
                        _play_ctx.plays_by_id.get(
                            (_play_ctx.plans_by_id.get(o.get("plan_id")) or {}).get("play_id")),
                        o, _play_ctx, _today_iso).kind == "stalled")
    if n_stalled:
        print("  ⚠️ %d role(s) have a STALLED play — see plays.py --check" % n_stalled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
