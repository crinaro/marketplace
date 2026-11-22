"""build: BUILD lines, a way in at a target company where the network has none (jobsearch 0.91.0, design-build-reach.md 6.1-6.5).

WHEN A COMPANY GETS ONE (6.1). An `active-target` company whose `path` is `none` (`reach/way_in.py`, current employees only), where
nobody current is known and uncontacted (that is an ordinary reach-out) and no reach-out there is still on its 3B7 timetable. One
BUILD line per company per plan: the best available. The kinds, ranked within a company (6.2):

    rank kind                when it is available                                                         spends a budget unit
    1    advice-ask          a person has the company in `formerly`, and no sent touch to them within      yes
                             `access.warm_days` (owner O11: a named person who knows the company)
    2    affiliation-lookup  `user.json.affiliations` is non-empty (7.2: a link or words, the candidate     holds a slot
                             opens it and records whom they find)
    3    side-door           a live role being pursued (`verdict: pursue`) and nobody current known; the    step `ask-side` (O10);
                             play's next step (`reach/sidedoor.state`)                                     `find` holds a slot
    4    hm-note             a current hiring manager on a live role: a POINTER to the warm-path line        no
    5    recruiter-direct    an application submitted and a current recruiter on the role: a POINTER        no
    6    plain-lookup        always: the company's people link, "nobody known; no affiliation stated"       holds a slot

Weekly, once under the plan and unbudgeted (neither is a reach-out): `event` (a `kind: event` commitment in the next 14 days, not
cancelled) and `career-services` (a school or bootcamp affiliation with `career_services`, when a target has no way in).

NO KIND SEARCHES FOR A PERSON (ADR-037, ADR-031 decision 5): every recipient is a `people` row the candidate recorded, and an
affiliation only angles a link the candidate opens. A link is printed only from an address already on record (a company's LinkedIn
page in its `research_log`, an affiliation's stored `linkedin_url`), with no search keyword: P-ALUMNI-URL is unanswered, so the bare
page ships (7.2).

THE BUDGET (6.4, the group invariant: not raised). `counts_as_new_reachout` is the widened rule: a `first-touch` OR an
`intro-request`, with no `opp_id` OR with `build_kind: side-door`. `fill` puts second contacts first, then reach-outs to current
people and BUILD lines interleaved by company motivation (highest first, unstated last; a reach-out before a BUILD line at equal
motivation), never more than the week's remaining units in all.

`step_for` is the BUILD step a brief records (R2 N10): the touch fields (`build_kind`, `play_step`, `touch_type`, the object and
trigger fields) for a person the plan's BUILD line names, under the touches store's own field names, so the sent write copies them.

Imports no entry point: the caller hands in a `graph.Graph` (`g`), the profile root and the loaded config. Capability module of
`reachouts.py`. Python 3.9+, standard library only."""

import datetime
import json
import os
import re

from _dates import date_or_none, to_date
from reach import affiliations as _aff
from reach import keys as _rk
from reach import way_in as _paths
from reach import sidedoor as _sd
from reach import standing_rows as _rows
from reach.standing import standing

KINDS = ("advice-ask", "affiliation-lookup", "side-door", "hm-note", "recruiter-direct", "plain-lookup")
WEEKLY_KINDS = ("event", "career-services")
ALL_KINDS = KINDS + WEEKLY_KINDS
RANK = {"advice-ask": 1, "affiliation-lookup": 2, "side-door": 3, "hm-note": 4, "recruiter-direct": 5, "plain-lookup": 6}
EVENT_DAYS = 14                                    # 6.2: an event dated in the next 14 days
# == access.LIVE_OPP_STATUSES, == validation.vocab.SUBMITTED_APP_STATUS: mirrored (importing either is an entry point or a cycle),
# and pinned equal by test_access.TestBuildMirrors.
LIVE_OPP_STATUSES = frozenset(("active-pursuit", "needs-resolution", "in-motion", "backlog"))
SUBMITTED_APP_STATUS = frozenset(("submitted", "acknowledged", "rejected", "advanced", "closed"))
# == warm_path.LINKEDIN_COMPANY_RE (pinned by the same test): a company's people page only from an address already on record.
LINKEDIN_COMPANY_RE = re.compile(r"linkedin\.com/company/([A-Za-z0-9_%.\-]+)", re.I)
AFFILIATION_VERB = "record.py affiliations '<json>'"
SAY = {"advice-ask": ["ask-advice"], _sd.ASK_STEP: ["ask-open", "ask-who"],
       _sd.NOTE_STEP: ["named-referral", "fit", "ask-conversation"]}


class BuildError(ValueError):
    """A BUILD input that does not read (a config value, a store line, `user.json`): loud, never read as "nothing to build"."""


def kinds_off(cfg):
    """`reach.kinds_off` for a loaded `config.json` dict: a list of names from ALL_KINDS, [] when absent. Anything else raises."""
    value = _rk._get_dotted(cfg, _rk.REACH_KINDS_OFF)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v in ALL_KINDS for v in value):
        raise BuildError("config.json %s is %r -- not a list of BUILD kind names (%s). Remove the key to get every kind."
                         % (_rk.REACH_KINDS_OFF, value, ", ".join(ALL_KINDS)))
    return list(value)


def counts_as_new_reachout(touch):
    """6.4's widened shape: a `first-touch` or `intro-request` with no `opp_id`, or with `build_kind: side-door` (its step (a)
    spends a unit although it names a role; step (b), the landing, does not). The caller still checks "never in contact before"."""
    if touch.get("touch_type") not in ("first-touch", "intro-request"):
        return False
    return not touch.get("opp_id") or touch.get("build_kind") == _sd.BUILD_KIND


def _jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    raise BuildError("%s line %d is not JSON: the BUILD lines cannot be derived" % (path, n))
    return out


def load_user(root):
    """`<root>/user.json` as a dict ({} when absent). An unreadable file raises: affiliations are never read as "not asked"."""
    path = os.path.join(root, "user.json") if root else None
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
    except ValueError:
        raise BuildError("%s is not valid JSON: affiliations cannot be read" % path)
    return user if isinstance(user, dict) else {}


def company_people_url(company):
    """The company's LinkedIn people page when its address is ALREADY on record in its `research_log`, else None."""
    for entry in (company or {}).get("research_log") or []:
        m = LINKEDIN_COMPANY_RE.search(str((entry or {}).get("note") or ""))
        if m:
            return "https://www.linkedin.com/company/%s/people/" % m.group(1).rstrip("/")
    return None


class Facts:
    """The rows BUILD reads, once: from a `graph.Graph` plus the three stores it does not load (applications, plans, plays),
    `user.json`'s affiliations (None when never asked, [] when asked and none) and the config (`kinds_off`, `warm_days`)."""

    def __init__(self, g, root, cfg, warm_days):
        data = g.data_dir
        self.g = g
        self.people = [p for p in g.stores["people"] if isinstance(p, dict) and p.get("status") != "merged"]
        self.touches = g.stores["touches"]
        self.commitments = g.stores["commitments"]
        self.warm_days = int(warm_days)
        self.off = set(kinds_off(cfg))
        self.invs_by_opp, self.touches_by_opp, self.apps_by_opp = {}, {}, {}
        for inv in g.stores["involvements"]:
            self.invs_by_opp.setdefault(inv.get("opp_id"), []).append(inv)
        for t in self.touches:
            self.touches_by_opp.setdefault(t.get("opp_id"), []).append(t)
        for a in _jsonl(os.path.join(data, "applications.jsonl")):
            self.apps_by_opp.setdefault(a.get("opp_id"), []).append(a)
        plays = {p.get("id"): p for p in _jsonl(os.path.join(data, "plays.jsonl"))}
        door_plans = {p.get("id") for p in _jsonl(os.path.join(data, "plans.jsonl"))
                      if (plays.get(p.get("play_id")) or {}).get("pattern") == _sd.PATTERN}
        self.door_opps = {o.get("id") for o in g.stores["opportunities"] if o.get("plan_id") in door_plans}
        user = load_user(root)
        self.affiliations = _aff.parse(user["affiliations"]) if "affiliations" in user else None

    def live_roles(self, cid):
        return sorted((o for o in self.g.opportunities_for_company(cid) if o.get("status") in LIVE_OPP_STATUSES
                       and not o.get("duplicate_of") and o.get("stage") != "closed"), key=lambda o: str(o.get("id")))

    def touched_within(self, pid, today):
        floor = today - datetime.timedelta(days=self.warm_days)
        for t in self.g.touches_for_person(pid):
            d = date_or_none(t.get("date"))
            if t.get("status") == "sent" and d is not None and floor <= d <= today:
                return True
        return False


def _name(company):
    return (company or {}).get("name") or (company or {}).get("id")


def _affiliation_line(f, company):
    a = f.affiliations[0]                        # the list order is the candidate's own ranking (7.1)
    co, page = _name(company), company_people_url(company)
    if a["kind"] in _aff.CAREER_SERVICES_KINDS:
        link, words = a.get("linkedin_url"), "On LinkedIn, search people at %s who attended %s" % (co, a["name"])
    elif a["kind"] == "employer":
        link, words = page, "On LinkedIn, search people at %s who worked at %s" % (co, a["name"])
    else:
        link, words = None, "Ask in %s who works at %s" % (a["name"], co)
    return {"kind": "affiliation-lookup", "affiliation": a["name"], "link": link, "words": words, "budgeted": True,
            "why": "an affiliation search; you open it and record whom you find (with `ties`), nothing is searched for you"}


def _side_door_line(f, opp, today):
    st = _sd.state(opp, f.touches_by_opp.get(opp.get("id"), ()), f.invs_by_opp.get(opp.get("id"), ()), f.people, today)
    if st is None:
        return None
    step, waiting = st["step"], st["waiting_on"]
    line = {"kind": "side-door", "opp_id": opp.get("id"), "step": step, "waiting_on": waiting,
            "adopted": opp.get("id") in f.door_opps, "say": [] if waiting else list(SAY.get(step, [])),
            "budgeted": waiting is None and step in (_sd.FIND_STEP, _sd.ASK_STEP)}
    if step == _sd.FIND_STEP:
        line["why"] = ("a live role you are pursuing, nobody known inside: find a recruiting, HR or talent person who is not the "
                       "role's lead and record them on the role with path_type side-contact")
    elif step == _sd.ASK_STEP:
        line["why"] = "ask the side contact whether the role is open and who the right person is (an intro-request, build_kind side-door)"
    elif waiting == "referrer-named":
        x = st.get("referrer")
        line["why"] = ("%s replied on %s; if %s named someone, record them with `ties introduced via person:%s`; if not, %s's name "
                       "must not be used" % (x, st.get("replied_on"), x, x, x))
    elif waiting:
        line["why"] = "the side-door ask is out; waiting on a reply"
    else:
        line["person_ids"], line["referrer"] = st.get("named", []), st.get("referrer")
        line["why"] = "write to the person the side contact named, naming who pointed the way"
    if not line["adopted"]:
        line["why"] += " (adopt the play for this role: `plays.py --adopt side-door --plan <the role's plan>`)"
    return line


def company_lines(f, company, today):
    """Every BUILD line available at `company` on `today` (a date), ranked (rank, then the order within it), kinds the candidate
    turned off left out. The caller has already decided the company is path none; the first budgeted line is its slot."""
    cid, co, out = company.get("id"), _name(company), []
    current = [p for p in f.people if standing(p, cid, today) == "current"]
    former = [p for p in f.people if standing(p, cid, today) == "former"]
    for p in sorted(former, key=lambda r: (0 if r.get("ties") else 1, str(r.get("id")))):
        if not f.touched_within(p["id"], today):
            out.append({"kind": "advice-ask", "person_id": p["id"], "person_name": p.get("name"), "say": list(SAY["advice-ask"]),
                        "budgeted": True, "why": "formerly at %s; no touch in %d days" % (co, f.warm_days)})
    if f.affiliations:
        out.append(_affiliation_line(f, company))
    roles = f.live_roles(cid)
    if not current:
        for opp in (o for o in roles if o.get("verdict") == "pursue"):
            line = _side_door_line(f, opp, today)
            if line:
                out.append(line)
                break
    cur_ids = {p["id"] for p in current}
    for opp in roles:
        invs = [i for i in f.invs_by_opp.get(opp.get("id"), ()) if i.get("person_id") in cur_ids]
        for i in invs:
            if i.get("path_type") == "hiring-manager":
                out.append({"kind": "hm-note", "opp_id": opp.get("id"), "person_id": i["person_id"], "budgeted": False,
                            "why": "a note to the hiring manager: see the warm-path line for this role"})
        apps = [a for a in f.apps_by_opp.get(opp.get("id"), ()) if a.get("status") in SUBMITTED_APP_STATUS]
        for i in invs:
            if apps and i.get("path_type") == "recruiter":
                out.append({"kind": "recruiter-direct", "opp_id": opp.get("id"), "person_id": i["person_id"], "budgeted": False,
                            "why": "applied; a current recruiter is on the role: see the recruiter-direct play's next step"})
    out.append({"kind": "plain-lookup", "link": company_people_url(company), "budgeted": True,
                "words": "nobody known" + ("" if f.affiliations else "; no affiliation stated"),
                "why": "nobody known at %s: find someone there%s" % (
                    co, "" if f.affiliations is not None else " (or say which schools, employers and communities you are "
                                                               "part of: `%s`)" % AFFILIATION_VERB)})
    ranked = sorted(enumerate(out), key=lambda iv: (RANK[iv[1]["kind"]], iv[0]))
    return [dict(l, rank=RANK[l["kind"]], company_id=cid, company_name=company.get("name"))
            for _i, l in ranked if l["kind"] not in f.off]


def best(lines):
    """`(slot, pointers)`: the first budgeted line (the company's one BUILD line in the budget), and every unbudgeted line (the
    pointers of ranks 4 and 5, and a side-door step that is waiting), listed outside the budget."""
    slot = next((l for l in lines if l["budgeted"]), None)
    return slot, [l for l in lines if not l["budgeted"]]


def _motivation(company):
    m = (company or {}).get("motivation")
    return m if isinstance(m, int) and not isinstance(m, bool) else None


def fill(reachouts, slots, remaining, targets):
    """6.4: `(lines, build)` within `remaining` units in all. `reachouts` are the ranked reach-out lines (each with `company_id`),
    `slots` the BUILD lines (one per company). Interleaved by company motivation, highest first and unstated last; a reach-out
    before a BUILD line at equal motivation; each list keeps its own order otherwise."""
    pool = []
    for kind, items in ((0, reachouts), (1, slots)):
        for i, l in enumerate(items):
            m = _motivation(targets.get(l.get("company_id")))
            pool.append(((0 if m is not None else 1, -(m or 0), kind, i), kind, l))
    pool.sort(key=lambda e: e[0])
    taken = pool[:max(0, remaining)]
    return [l for _k, kind, l in taken if kind == 0], [l for _k, kind, l in taken if kind == 1]


def cap_confirms(people, targets, as_of, cap):
    """The plan's confirm lines (`standing_rows.confirm_lines`), naming at most `cap` people in all
    (`network.employment_confirms_per_run`, 5.5): highest company motivation first, unstated last, then company id. A company whose
    people do not all fit names the first ones by id; the rest wait for a later run, never dropped from the table's own count."""
    order = sorted(targets, key=lambda c: (_motivation(targets[c]) is None, -(_motivation(targets[c]) or 0), c))
    picked = []
    for cid in order:
        picked += _rows.unconfirmed_ids(people, cid, as_of)[:max(0, cap - len(picked))]
    keep = set(picked)
    lines = _rows.confirm_lines([p for p in people if p.get("id") in keep], targets, as_of)
    return sorted(lines, key=lambda l: order.index(l["company_id"]))


def weekly(f, today, thin_names):
    """The two weekly kinds (6.2), unbudgeted: events in the next EVENT_DAYS days, and one career-services line per school or
    bootcamp affiliation with `career_services` when `thin_names` (the path-none targets) is non-empty. The 28-day pacing of 6.2
    has no stored anchor yet (no field links an office to a people row), so the line shows every week; INFERRED gap, reported."""
    out, end = [], today + datetime.timedelta(days=EVENT_DAYS)
    for c in sorted(f.commitments, key=lambda r: (str(r.get("date")), str(r.get("id")))):
        d = date_or_none(c.get("date"))
        if c.get("kind") == "event" and c.get("status") != "cancelled" and d is not None and today <= d <= end:
            out.append({"kind": "event", "commitment_id": c.get("id"), "date": d.isoformat(), "title": c.get("title"),
                        "source": c.get("source"), "budgeted": False,
                        "why": "%s: %s" % (d.strftime("%a %d %b"), c.get("title") or c.get("id"))})
    for a in f.affiliations or ():
        if thin_names and a.get("career_services") and a["kind"] in _aff.CAREER_SERVICES_KINDS:
            out.append({"kind": "career-services", "affiliation": a["name"], "budgeted": False,
                        "contact": a["career_services"] if isinstance(a["career_services"], str) else None,
                        "companies": list(thin_names),
                        "why": "Ask %s career services for alumni at: %s" % (a["name"], ", ".join(thin_names))})
    return [l for l in out if l["kind"] not in f.off]


def plan_lines(g, root, cfg, warm_days, today, targets, reachouts, remaining, busy):
    """`reachouts.plan`'s one call: `{lines, build, build_pointers, weekly}` for the week. `targets` is {id: company row},
    `reachouts` the ranked reach-out lines, `remaining` the week's units after second contacts, `busy` the companies that already
    have a way being worked (somebody current uncontacted, or a reach-out on its 3B7 timetable): they get no BUILD line."""
    f = Facts(g, root, cfg, warm_days)
    day = to_date(today)
    landed = _paths.landings(g, day)
    slots, pointers, thin = [], [], []
    for cid in sorted(targets):
        if cid in busy or _paths.company_path(g, cid, day, f.warm_days, landed) != "none":
            continue
        thin.append(_name(targets[cid]))
        slot, more = best(company_lines(f, targets[cid], day))
        if slot:
            slots.append(slot)
        pointers.extend(more)
    lines, build = fill(reachouts, slots, remaining, targets)
    return {"lines": lines, "build": build, "build_pointers": pointers, "weekly": weekly(f, day, thin)}


def step_for(g, root, cfg, warm_days, person_id, opp_id, today):
    """The BUILD step a brief for `person_id` (and `opp_id`) records, or None (R2 N10). Derived from the stores, never from text:

        side-door ask-side   the person is a side contact on `opp_id` and the role's side-door step is `ask-side`
        side-door named-note the person is one the side contact named, on `opp_id`, and the step can run
        advice-ask           no `opp_id`; the person is formerly at a path-none `active-target` company and its advice-ask line
                             names them (the highest-motivation such company)

    The dict carries the touches store's own field names, so the sent write copies it unchanged. An input that does not read
    (`reach.kinds_off`, `user.json`, a store line) gives `{"not_checked": <why>}`: loud on the brief, never a crash of every
    caller of `brief.compute`, and never read as "not a BUILD step"."""
    try:
        return _step(Facts(g, root, cfg, warm_days), g, person_id, opp_id, to_date(today))
    except ValueError as e:                              # BuildError, an unreadable affiliation, a bad date
        return {"not_checked": str(e)}


def _step(f, g, person_id, opp_id, day):
    targets = {c.get("id"): c for c in g.stores["companies"] if c.get("status") == "active-target" and c.get("id")}
    base = dict.fromkeys(("build_kind", "play_step", "touch_type", "opp_id", "plan_id", "object_company_id", "object_person_id",
                          "trigger_kind", "trigger_ref"))
    if opp_id:
        opp = g.by_id["opportunities"].get(opp_id) or {}
        line = _side_door_line(f, opp, day) if opp else None
        if not line or line["waiting_on"] or "side-door" in f.off:
            return None
        if line["step"] == _sd.ASK_STEP and person_id in _sd.side_contact_ids(f.invs_by_opp.get(opp_id, ())):
            return dict(base, build_kind=_sd.BUILD_KIND, play_step=_sd.ASK_STEP, touch_type="intro-request", opp_id=opp_id,
                        plan_id=opp.get("plan_id"), object_company_id=opp.get("company_id"))
        if line["step"] == _sd.NOTE_STEP and person_id in line.get("person_ids", ()):
            ask = next((t for t in sorted(f.touches_by_opp.get(opp_id, ()), key=lambda t: str(t.get("date")))
                        if t.get("person_id") == line["referrer"] and t.get("status") == "sent"), {})
            return dict(base, play_step=_sd.NOTE_STEP, touch_type="first-touch", opp_id=opp_id, plan_id=opp.get("plan_id"),
                        object_person_id=line["referrer"], trigger_kind="introduction", trigger_ref="touch:%s" % ask.get("id"))
        return None
    if "advice-ask" in f.off:
        return None
    landed = _paths.landings(g, day)
    order = sorted(targets, key=lambda c: (_motivation(targets[c]) is None, -(_motivation(targets[c]) or 0), c))
    for cid in order:
        if _paths.company_path(g, cid, day, f.warm_days, landed) != "none":
            continue
        if any(l["kind"] == "advice-ask" and l["person_id"] == person_id for l in company_lines(f, targets[cid], day)):
            return dict(base, build_kind="advice-ask", touch_type="first-touch", object_company_id=cid)
    return None
