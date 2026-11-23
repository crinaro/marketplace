"""held_roles: the roles held for a company decision, ranked, listed and counted (jobsearch 0.92.0, dev #1005, #950, #1002;
docs/design-decision-surface.md §C, review round 2 G3, G4 and G6).

A role is HELD (`lifecycle` stage `held-for-company`) while its company waits on the candidate's decision: `undecided` (raised,
not answered), `watching` (the candidate chose to watch it) or `passed`. This module answers four questions about them, and
takes only what its callers already loaded (rows, a stage map, functions), so it imports no entry point (G4, G5.L2):

  rank      `title_matcher`, `title_fields`, `newest_sighting`, `candidate_key`, `look_into_key`: `your_move.company_candidates`
            puts a company holding a role whose title matches the candidate's target titles above one without (C1), then its
            old order (Alumni, live roles, newest sighting, id); `classify_companies` lists a raised one with a match first.
  list      `listing`: every held role at an `undecided` or `watching` company whose title matches, role first (C2). `passed`
            is counted, never listed. A matcher that cannot answer (no target titles configured) lists nothing and says so.
  count     `held_counts`: by why, OPPORTUNITIES ONLY (G3): a capture-item group the lifecycle also holds is not a role yet,
            and the page names those as their own remainder.
  change    `baseline` and `count_state`: the count a week ago, from the `companies-raised` journal row that carries `held`
            (§C.3), and the four states the count line can be in when there is none (G6, H5).

WHY `reach/` AND NOT `measuring/`, where §C.1 and G4 put it (measured 2026-11-22 with scripts/check_segmentation.py, G6). The
`measuring` package collapses into its one top-level importer, `build_reach.py`, which sits outside the plugin's largest import
cycle; `measuring/mail_coverage.py` imports the journal, which is inside it. Any cycle member importing `measuring` (`your_move`,
`recording/network_verbs.py`, `dashboard/held.py`) therefore pulls `build_reach.py`, or `measuring/` itself once it has a second
top-level importer, into the cycle: 39 -> 40, a G6 violation no waiver may excuse. `reach/` is already imported by all three and
is not in the cycle; this module imports nothing, so it adds no edge back.

Pure: no I/O, no clock (every `today` is passed in). Python 3.9+, standard library only."""

import datetime

HELD = "held-for-company"
WHY = ("undecided", "watching", "passed")
LISTED = ("undecided", "watching")
BASELINE_DAYS = 7


def title_matcher(title_matches, cfg):
    """`matches(title)`: `title_matches(title, cfg)` (`profile.title_matches` over the profile's config), so a caller binds the
    profile once. It answers True, False or None (None: no target titles are configured)."""
    return lambda title: title_matches(title, cfg)


def matching(titles, matches):
    """The titles for which `matches(title)` is True, in order; None when any answer is None (the matcher cannot answer)."""
    out = []
    for t in titles:
        m = matches(t)
        if m is None:
            return None
        if m:
            out.append(t)
    return out


def title_fields(titles, matches):
    """A candidate item's three title keys: `titles` (as given), `title_match` (how many match; None for none or no answer)
    and `titles_matching` (those titles, `[]` for none)."""
    hits = matching(titles, matches)
    return {"titles": list(titles), "title_match": len(hits) if hits else None, "titles_matching": hits or []}


def newest_sighting(roles):
    """The newest readable `sightings[].seen_on` across `roles` (a date), else None."""
    days = [_day(s.get("seen_on")) for o in roles for s in (o.get("sightings") or ()) if isinstance(s, dict)]
    return max((d for d in days if d), default=None)


def candidate_key(pair):
    """The sort key of `(item, newest sighting ordinal)` in `company_candidates`: a title match first (C1), then Alumni desc,
    live roles desc, newest sighting desc, id."""
    item, ordinal = pair
    return (0 if item.get("title_match") else 1, -item["alumni"], -item["roles"], -ordinal, item["id"])


def look_into_key(item):
    """The sort key of the raised companies in `classify_companies`: a title match first (C1), then the oldest raise."""
    return (0 if item.get("title_match") else 1, item["raised_on"])


def _day(value):
    try:
        return datetime.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _why(stage):
    return stage.detail if stage.detail in WHY else "undecided"


def held_counts(stages):
    """`{"undecided", "watching", "passed": n}` over `stages` (the opportunities' lifecycle stages, an iterable): every
    `held-for-company` stage counted by its why, as `lifecycle.process_report` counts it, but for opportunities only (G3)."""
    out = dict.fromkeys(WHY, 0)
    for st in stages:
        if getattr(st, "name", None) == HELD:
            out[_why(st)] += 1
    return out


def listing(opps, stages, companies, matches, first_seen):
    """`{"rows": [row], "unmatched": bool}` (C2). A row is a held opportunity at an `undecided` or `watching` company whose
    title matches: `{"id", "opp", "company_id", "company", "why", "first_seen"}`. `stages` is `{opp id: Stage}`, `companies`
    `{id: row}`, `first_seen(opp)` a date or None. Order: `undecided` first, then the newest first sighting, then id.
    `unmatched` is True when `matches` answered None: then no row is listed."""
    held = [o for o in opps if o.get("id") and getattr(stages.get(o["id"]), "name", None) == HELD
            and _why(stages[o["id"]]) in LISTED]
    rows = []
    for o in held:
        m = matches(str(o.get("title") or ""))
        if m is None:
            return {"rows": [], "unmatched": True}
        if m:
            seen = first_seen(o)
            cid = o.get("company_id")
            rows.append({"id": o["id"], "opp": o, "company_id": cid,
                         "company": str((companies.get(cid) or {}).get("name") or cid or ""), "why": _why(stages[o["id"]]),
                         "first_seen": seen.isoformat() if seen else None})
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["first_seen"] or "", reverse=True)
    rows.sort(key=lambda r: LISTED.index(r["why"]))
    return {"rows": rows, "unmatched": False}


def _raised(recs):
    return [r for r in recs if isinstance(r, dict) and r.get("event") == "companies-raised"]


def _total(held):
    return sum(held.get(k) or 0 for k in WHY)


def baseline(recs, today):
    """`(date, total)` from the newest `companies-raised` row that carries `held` and whose `at[:10]` is on or before
    `today` minus seven days; None when there is none. A 0.91 row without `held` is skipped, never read as zero."""
    cut = today - datetime.timedelta(days=BASELINE_DAYS)
    for r in reversed(_raised(recs)):
        day = _day(r.get("at"))
        if isinstance(r.get("held"), dict) and day is not None and day <= cut:
            return day.isoformat(), _total(r["held"])
    return None


def count_state(recs, today, pinned):
    """The count line's state (G6, H5), first match:
        ("pending", None, None)       the profile is not pinned at 0.92.0, so no run records a count (an update step is pending)
        ("unrecorded", None, None)    the newest `companies-raised` row carries no `held`
        ("since", date, total)        `baseline` found the count from a week ago
        ("counting", date, None)      rows carry `held`, none seven days old; counting since the oldest
        ("none", None, None)          no row carries `held` yet"""
    if not pinned:
        return "pending", None, None
    raised = _raised(recs)
    if raised and not isinstance(raised[-1].get("held"), dict):
        return "unrecorded", None, None
    found = baseline(recs, today)
    if found:
        return ("since",) + found
    bearing = [r for r in raised if isinstance(r.get("held"), dict) and _day(r.get("at"))]
    if bearing:
        return "counting", _day(bearing[0]["at"]).isoformat(), None
    return "none", None, None
