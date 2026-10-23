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

⭐ ONE JOB-URL CANONICALIZATION, AND "KNOWN" COVERS ACTIVE ROWS TOO (dev #692 / public #140, N6).
`canonical_job_url()` below is the only definition of "the same posting by URL": the roles gate
(`deferred.py --add-roles`) uses it to decide whether a role it was shown is already in the
pipeline, to key the carry-forward item it creates (`ref`), and `--settle` uses it to close that
item once the role has a record. A tracking-parameter variant of a URL therefore resolves to one
posting everywhere, and an id-less LinkedIn URL is never "canonicalized" to a guess (it returns
None and the gate makes it a per-role gap). `find_known_match()` answers "does the pipeline already
hold this role?" for BOTH excluded rows (a passed role stays passed) and ACTIVE rows (not excluded,
not expired); an expired row never matches, because a repost of a vanished posting is a second
chance that must surface (`find_excluded_match`'s own rule, unchanged).

⭐ ONE REQUISITION LISTED AT SEVERAL PLACES IS ONE DECISION (dev #728 / public #158, jobsearch
0.70.0; docs/design-location-screen.md §5). A sibling listing is a `sightings[]` entry carrying a
`location`, on the row that already stands for the requisition -- never a second undecided row. The
helpers below are the ONE definition of it: `listing_places` (where a row is listed), `siblings` and
`earlier_sibling` (the matching rule: the same company and the same non-empty normalized title, minus
the vetoes a human recorded), `possible_sibling` (a near miss: never merged, only printed), and
`is_folded` (a legacy duplicate row folded into its canonical one by hand). `find_known_match` reads
them so a listing resolves to the canonical row by URL or by company + title.

Python 3.9+. Standard library only.
"""

import argparse
import collections
import json
import os
import re
import sys
import urllib.parse

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


# dev #692 / public #140 (N6) -- tracking parameters dropped from a NON-LinkedIn job URL. Fixed and
# short on purpose: a board's query string can BE the job's identity (an ATS `?gh_jid=` id), so
# only keys that exist to track a click are removed -- `utm_*` by prefix, the rest by name,
# compared case-insensitively. RFC 3986 §6 warns that dropping a query is not a generic
# normalization; it is done here for named keys only.
TRACKING_PARAMS = frozenset({"gclid", "fbclid", "msclkid", "trk", "trackingid", "refid", "ref",
                             "src"})

_LINKEDIN_VIEW_RE = re.compile(r"^/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d+)/?$")
_LINKEDIN_ID_RE = re.compile(r"^\d+$")


def canonical_job_url(url):
    """The ONE canonical form of a job posting URL, or None when there is none to give.

    * not `http`/`https`, or no host -> None (this is not a URL a posting can be matched on);
    * a LinkedIn host (`linkedin.com` or a subdomain): the job id alone identifies the posting
      (OURS, diverging from RFC 3986 §6's warning on purpose), taken from `/jobs/view/<id>`,
      `/jobs/view/<slug>-<id>`, `/comm/jobs/view/<id>` or the `currentJobId=<digits>` query
      parameter, and returned as `https://www.linkedin.com/jobs/view/<id>/`. NO id -> None: a
      LinkedIn URL with no job id is never canonicalized to a guess (the gate makes it a
      per-role gap);
    * any other host: scheme and host lower-cased, fragment dropped, `TRACKING_PARAMS` and
      `utm_*` removed, the remaining pairs sorted, one trailing `/` stripped from a non-root path.

    `urlsplit()` validates nothing, so the host and scheme are checked explicitly."""
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return None
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        m = _LINKEDIN_VIEW_RE.match(parts.path)
        job_id = m.group(1) if m else None
        if not job_id:
            for key, val in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
                if key == "currentJobId" and _LINKEDIN_ID_RE.match(val):
                    job_id = val
                    break
        return "https://www.linkedin.com/jobs/view/%s/" % job_id if job_id else None
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    netloc = host + (":%d" % parts.port if parts.port else "")
    return urllib.parse.urlunsplit((scheme, netloc, path, urllib.parse.urlencode(sorted(pairs)), ""))


def _urls_equal(a, b):
    """Same posting by URL: an identical non-empty string, or the same canonical form."""
    sa, sb = str(a or "").strip(), str(b or "").strip()
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    ca, cb = canonical_job_url(sa), canonical_job_url(sb)
    return ca is not None and ca == cb


def normalize_company(name):
    """casefold, punctuation to spaces, whitespace collapsed. NO suffix stripping and NO fuzzy
    match: 'Acme Corp.' and 'acme corp' agree, 'Acme' and 'Acme Corp' do not (a wrong merge
    costs a missed lead; a missed merge costs one more row to look at)."""
    return " ".join(re.sub(r"[^\w]+", " ", str(name or "").casefold()).split())


def company_candidates(name, companies):
    """The sorted ids of EVERY company whose normalized `name` or `id` equals the normalized `name`
    (dev #765). `resolve_company` is the one-hit view of this list; a caller that must tell "nothing
    matches" (create it) from "several match" (ask which) reads the list itself, so the two never
    use different matching rules."""
    want = normalize_company(name)
    if not want:
        return []
    return sorted({c.get("id") for c in companies or []
                   if c.get("id") and (normalize_company(c.get("name")) == want
                                       or normalize_company(c.get("id")) == want)})


def resolve_company(name, companies):
    """The `company_id` of the SINGLE company whose normalized `name` or `id` equals the
    normalized `name`, else None. Zero matches or several (two companies sharing a normalized
    name, or one's name equal to another's id) give None, and the caller then has NO company
    basis -- it never takes the first of several."""
    hits = company_candidates(name, companies)
    return hits[0] if len(hits) == 1 else None


def find_known_match(opps, url=None, company_id=None, title=None, applications=None):
    """The pipeline row a role seen in a pass duplicates, as `(row, basis, kind)`, or None.

    `kind` is `"excluded"` (a passed / declined row -- `find_excluded_match`, unchanged) or
    `"active"` (a row that is neither excluded nor expired). An EXPIRED row never matches: its
    posting vanished before any decision, so a repost is a second chance that must surface
    (module docstring). URL comparison is canonical (`canonical_job_url`) on the row's `jd_url`
    and every `sightings[].source_url`; the company basis needs a resolved `company_id` and an
    equal NON-EMPTY normalized title. Pure: it reads only what it is handed."""
    hit = find_excluded_match(opps, company_id=company_id, title=title, jd_url=url,
                              applications=applications)
    if hit:
        return hit[0], hit[1], "excluded"
    # dev #728: a FOLDED row (duplicate_of) never answers -- its listings now live on the canonical
    # row -- and a sighting stamped `split_to` no longer evidences this row (the undo of a false merge).
    active = [o for o in opps if not is_excluded(o) and not is_expired(o) and not is_folded(o)]
    if str(url or "").strip():
        for o in active:
            if _urls_equal(o.get("jd_url"), url):
                return o, "jd_url", "active"
            for s in o.get("sightings") or []:
                if not s.get("split_to") and _urls_equal(s.get("source_url"), url):
                    return o, "sighting url", "active"
    want_title = normalize_title(title)
    if company_id and want_title:
        for o in active:
            if o.get("company_id") == company_id and normalize_title(o.get("title")) == want_title:
                return o, "company + title", "active"
    return None


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
    excluded = [o for o in opps if is_excluded(o) and not is_folded(o)]
    if want_url:
        for o in excluded:
            # dev #692 (N6): identical, OR the same canonical posting -- one definition of "the
            # same URL" for this lookup, the roles gate and `--settle` alike.
            if _urls_equal(o.get("jd_url"), want_url):
                return o, "jd_url"
        # dev #728: a listing linked onto a PASSED row (a sibling sighting) is the same posting by
        # URL, so a re-run resolves it by URL and does not link it a second time.
        for o in excluded:
            for s in o.get("sightings") or []:
                if not s.get("split_to") and _urls_equal(s.get("source_url"), want_url):
                    return o, "sighting url"
    if want_req:
        for o in excluded:
            if want_req in reqs.get(o.get("id"), ()):
                return o, "req_id"
    if company_id and want_title:
        for o in excluded:
            if o.get("company_id") == company_id and normalize_title(o.get("title")) == want_title:
                return o, "company + title"
    return None


def is_folded(o):
    """True for a row folded into another by hand (`record.py link-sibling`): it carries
    `duplicate_of`, stands for no decision of its own, and is left out of the undecided lists and of
    every match. The one definition (dev #728); `is_excluded` is unchanged and a folded row is never
    `passed` (a passed duplicate would make the canonical row match it and screen `remove:passed`)."""
    return bool(o.get("duplicate_of"))


def first_seen(o):
    """The earliest `sightings[].seen_on` of a row, or "" when it has none -- the order two siblings
    are told apart in (the earlier is the canonical one; ties broken by id)."""
    dates = [str(s.get("seen_on"))[:10] for s in (o.get("sightings") or [])
             if isinstance(s, dict) and s.get("seen_on")]
    return min(dates) if dates else ""


def listing_places(o):
    """Every place a row is listed at, verbatim, in order: `location.primary`, then each
    `sightings[].location` that was not split away (`split_to`). Duplicates are dropped."""
    out = []
    loc = o.get("location")
    texts = [loc.get("primary") if isinstance(loc, dict) else None]
    texts += [s.get("location") for s in (o.get("sightings") or [])
              if isinstance(s, dict) and not s.get("split_to")]
    for t in texts:
        if isinstance(t, str) and t.strip() and t.strip() not in out:
            out.append(t.strip())
    return out


def siblings(a, b):
    """True when two ROWS are one requisition by the matching rule (dev #728; design §5.2): the same
    non-empty `company_id` and the same non-empty normalized title -- and neither names the other in
    `distinct_from` (a false merge somebody undid, or a `create --force` over a match). No fuzzy
    match and no suffix stripping (`normalize_company`'s stated policy): two genuinely separate
    openings with one title at one company WILL merge, and the undo is `record.py unlink-sibling`.
    The ATS requisition-id veto is NOT implemented: no stored field carries one (`--req-id` is
    never stored), so there is nothing to compare."""
    if not a.get("company_id") or a.get("company_id") != b.get("company_id"):
        return False
    ta = normalize_title(a.get("title"))
    if not ta or ta != normalize_title(b.get("title")):
        return False
    if b.get("id") in (a.get("distinct_from") or []) or a.get("id") in (b.get("distinct_from") or []):
        return False
    return True


def earlier_sibling(row, rows):
    """The EARLIEST other row that is the same requisition as `row` and is still a live, unfolded
    canonical candidate (neither excluded nor expired nor folded), provided it is EARLIER than `row`
    (by first `seen_on`, ties by id); else None. A row that is itself excluded, expired or folded has
    no earlier sibling here (it is not a duplicate decision). Because the canonical row is the
    earliest of its group it has no earlier sibling itself, so asking for ITS verdict cannot recurse."""
    if is_excluded(row) or is_expired(row) or is_folded(row):
        return None
    mine = (first_seen(row) or "9999-99-99", str(row.get("id")))
    cands = [o for o in rows if o is not row and o.get("id") != row.get("id")
             and not is_excluded(o) and not is_expired(o) and not is_folded(o) and siblings(row, o)
             and (first_seen(o) or "9999-99-99", str(o.get("id"))) < mine]
    return min(cands, key=lambda o: (first_seen(o) or "9999-99-99", str(o.get("id")))) if cands else None


def strip_trailing_place(title):
    """`title` without a trailing segment `places.parse_place` reads as a place ("Analyst - Austin, TX"
    -> "Analyst"; "Analyst (Austin, TX)" -> "Analyst"), else the title unchanged."""
    import places as _places
    text = str(title or "")
    for sep in (" - ", " \u2013 ", " \u2014 ", " | ", " ("):
        i = text.rfind(sep)
        if i > 0 and _places.parse_place(text[i + len(sep):].rstrip(") ")):
            return text[:i]
    return text


def possible_sibling(a_title, b_title):
    """True for a NEAR MISS: titles that differ, but are equal once a trailing place is removed from
    each. Record linkage's clerical-review rule (dev #728): printed as `POSSIBLE SIBLING`, counted,
    NEVER merged."""
    na, nb = normalize_title(a_title), normalize_title(b_title)
    if not na or not nb or na == nb:
        return False
    return (normalize_title(strip_trailing_place(a_title)) != ""
            and normalize_title(strip_trailing_place(a_title))
            == normalize_title(strip_trailing_place(b_title)))


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
