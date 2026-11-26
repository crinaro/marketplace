"""query_plan: the LinkedIn job search's query list, the one window rule, and the accounting of what a pass read against what it was given
(jobsearch 0.94.0, dev 1055; docs/design-role-first.md 5.2, 5.3, 19.7; criteria LC3, LC4). Pure: nothing here reads or writes a file.

THE PLAN (5.3). One entry per (title, geography) pair, `{n, geo, title, do, last}`, in the order a pass should run them; `n` counts from 1 in that
order and the `do` entries come first. Titles are `targets.titles`, geographies `remote` and, when the profile has a commute anchor, `local`
(the caller passes both, from the profile; `journal.jobsearch_geos`).

  do      `ceil(pairs / floor(7 / every_days))`, never above `per_pass` (`search.linkedin_queries_per_pass`) or the number of pairs, so at the defaults (every
          2 days, 20) every pair of up to 60 runs within the week: 28 pairs are 10 a pass, each pair every 6 days. Beyond 60 the cap holds and the late
          pairs wait longer: the summary counts them (`coverage_line`), the plan never hides them.
  order   the pair whose last REACHED run is oldest goes first (a pair with none is `not-recorded` and goes before any with one), taken from whichever
          geography has the older next pair; a tie goes to the geography picked fewer times so far, then to the first geography, so a cold start
          alternates remote, local, remote, local. Taking the oldest across both geographies, not the oldest of a fixed alternation, is what keeps an
          odd `do` from starving the geography that is picked second.
  last    the `at` of the newest `roles` event of the `linkedin-jobsearch` surface whose `pairs` entry reached that pair, or the literal `not-recorded`:
          never `never`, never null (a pair nobody recorded may have run before 0.94.0, which stored none).

`plan(...)` is what `linkedin_sweep.py search-plan` writes on the `dispatched` row (`search_rows.check_plan` is its shape); `--add-roles` reads that
stored plan with `stored_plan` and never recomputes it, so a second call names the same queries after the history moved.

THE WINDOW (5.3). `window(entries, now)`: LinkedIn's weekly bucket (`r604800`) unless every `do` pair was reached within the last 24 hours, then the daily
one (`r86400`). The 0.93.0 pair of functions that decided this from a weekly satisfied pass retired; a scheduled run could never satisfy them.

THE ACCOUNTING (5.2, 5.3). `account(entries, queries)` sets the QUERY lines of a ROLES block against the stored plan: `pairs` for the `roles` event,
`q_planned`, `q_not_attempted` (each `do` pair with no REACHED QUERY line, listed or not), the extra QUERY lines (a pair that is not a `do` pair: accepted,
counted), and what was `bounded` (a reached query whose result was larger than the part read: the first page only, OD-11, is "read 25 of 99+"; the rest
is counted as not read, never as zero found).

Python 3.9+, standard library only. It imports nothing of the plugin: the two bucket names and the defaults below are pinned equal to
`journaling.tables` and `reach.keys` by `tests/searching/test_query_plan.py`."""

import datetime
import math

SURFACE = "linkedin-jobsearch"
NOT_RECORDED = "not-recorded"
F_TPR_DAILY, F_TPR_WIDE = "r86400", "r604800"
WEEK_DAYS = 7
EVERY_DAYS_KEY, PER_PASS_KEY = "search.linkedin_search_every_days", "search.linkedin_queries_per_pass"
EVERY_DAYS_DEFAULT, EVERY_DAYS_RANGE = 2, (1, 7)
PER_PASS_DEFAULT, PER_PASS_RANGE = 20, (1, 20)


def _norm(text):
    return " ".join(str(text or "").casefold().split())


def pair_key(geo, title):
    """The identity of a (geography, title) pair: case and spacing do not make a second one."""
    return (_norm(geo), _norm(title))


def _at(text):
    """The naive `datetime` of an ISO date or date and time, or None."""
    try:
        d = datetime.datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return d.replace(tzinfo=None)


def _dotted(cfg, dotted):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _setting(cfg, key, default, bounds):
    v = _dotted(cfg, key)
    ok = isinstance(v, int) and not isinstance(v, bool) and bounds[0] <= v <= bounds[1]
    return v if ok else default


def settings(cfg):
    """`(every_days, per_pass)` from a loaded `config.json`: `search.linkedin_search_every_days` (1..7, default 2) and `search.linkedin_queries_per_pass`
    (1..20, default 20). A key that is absent, not an integer or out of its range reads its default."""
    return (_setting(cfg, EVERY_DAYS_KEY, EVERY_DAYS_DEFAULT, EVERY_DAYS_RANGE), _setting(cfg, PER_PASS_KEY, PER_PASS_DEFAULT, PER_PASS_RANGE))


def titles_of(cfg):
    """The non-blank `targets.titles` of a loaded `config.json`, stripped, one spelling a title, in order."""
    raw = _dotted(cfg, "targets.titles")
    seen, out = set(), []
    for t in raw if isinstance(raw, list) else []:
        if isinstance(t, str) and t.strip() and _norm(t) not in seen:
            seen.add(_norm(t))
            out.append(t.strip())
    return out


def do_count(pairs, every_days=EVERY_DAYS_DEFAULT, per_pass=PER_PASS_DEFAULT):
    """How many of `pairs` one pass runs: `ceil(pairs / floor(7 / every_days))`, at most `per_pass` and at most `pairs`; 0 for no pair."""
    if pairs <= 0:
        return 0
    passes = max(1, WEEK_DAYS // max(1, every_days))
    return min(max(1, per_pass), math.ceil(pairs / passes), pairs)


def last_reached(recs):
    """`{pair_key: at}`: the newest `at` of a `roles` event of the LinkedIn job search that REACHED the pair, from the `pairs` it stored (an event from
    before 0.94.0 stored none, so its pairs are not here: that is what `not-recorded` says)."""
    out = {}
    for e in recs or ():
        if not (isinstance(e, dict) and e.get("event") == "roles" and e.get("surface") == SURFACE and e.get("at")):
            continue
        for p in e.get("pairs") or ():
            if isinstance(p, dict) and p.get("reached"):
                k = pair_key(p.get("geo"), p.get("title"))
                if str(e["at"]) > out.get(k, ""):
                    out[k] = str(e["at"])
    return out


def plan(titles, geos, last, every_days=EVERY_DAYS_DEFAULT, per_pass=PER_PASS_DEFAULT):
    """The plan: `[{"n", "geo", "title", "do", "last"}, ...]` in run order, `do` entries first (see the module docstring). `titles` and `geos` are
    lists of text, `last` is `last_reached(recs)`. An empty list when there is no title or no geography."""
    titles = [t for t in titles if str(t or "").strip()]
    geos = list(geos)
    total = len(titles) * len(geos)
    if not total:
        return []
    queues = {}
    for g in geos:
        indexed = list(enumerate(titles))
        indexed.sort(key=lambda it: (last.get(pair_key(g, it[1]), ""), it[0]))
        queues[g] = [t for _i, t in indexed]
    taken = {g: 0 for g in geos}
    run, k = [], do_count(total, every_days, per_pass)
    while len(run) < total:
        live = [g for g in geos if taken[g] < len(queues[g])]
        g = min(live, key=lambda x: (last.get(pair_key(x, queues[x][taken[x]]), ""), taken[x], geos.index(x)))
        t = queues[g][taken[g]]
        taken[g] += 1
        run.append({"n": len(run) + 1, "geo": g, "title": t, "do": len(run) < k, "last": last.get(pair_key(g, t)) or NOT_RECORDED})
    return run


def window(entries, now):
    """`{"window", "f_tpr", "titles"}` for a pass planned `now` (an ISO string): the daily bucket (`r86400`, the configured titles) only when every `do` entry
    of `entries` was reached within the last 24 hours, else the weekly bucket (`r604800`, every title). No plan, or a `last` that is not a time, is weekly."""
    now_dt = _at(now)
    due = [e for e in entries or () if e.get("do")]
    ran = [_at(e.get("last")) for e in due]
    if now_dt is not None and due and all(r is not None and datetime.timedelta(0) <= now_dt - r < datetime.timedelta(hours=24) for r in ran):
        return {"window": "daily", "f_tpr": F_TPR_DAILY, "titles": "configured"}
    return {"window": "wide", "f_tpr": F_TPR_WIDE, "titles": "all"}


def stored_plan(recs, run_id):
    """The plan on the newest `pass linkedin dispatched` row with `scope: search` of run `run_id` (what `search-plan` wrote), or None. Never recomputed."""
    found = None
    for r in recs or ():
        if (isinstance(r, dict) and r.get("event") == "pass" and r.get("run_id") == run_id and r.get("kind") == "linkedin"
                and r.get("phase") == "dispatched" and r.get("scope") == "search" and isinstance(r.get("plan"), list)):
            found = r["plan"]
    return found


def coverage_line(titles, geos, recs, now):
    """`linkedin search: 18 of 28 title and place pairs searched in the last 7 days; oldest <date | not recorded before 0.94.0>`, or None when there is no
    pair. A pair is searched when its last reached run is under 7 days old; `oldest` is the oldest last run over ALL pairs, and says `not recorded before
    0.94.0` when any pair has none (it may never have run, or have run before the engine stored pairs)."""
    pairs = [(g, t) for g in geos for t in titles if str(t or "").strip()]
    if not pairs:
        return None
    last, now_dt = last_reached(recs), _at(now)
    times = [_at(last.get(pair_key(g, t))) for g, t in pairs]
    fresh = sum(1 for d in times if d is not None and now_dt is not None and now_dt - d < datetime.timedelta(days=WEEK_DAYS))
    oldest = "not recorded before 0.94.0" if any(d is None for d in times) else min(times).date().isoformat()
    return "linkedin search: %d of %d title and place pairs searched in the last %d days; oldest %s" % (fresh, len(pairs), WEEK_DAYS, oldest)


def account(entries, queries):
    """Set the parsed QUERY lines of one ROLES block against the stored plan `entries` (None: no stored plan). Returns

      pairs            `[{geo, title, reached, shown, total}]` for the `roles` event, a pair once (a reached line beats an unreachable one)
      q_planned        the `do` pairs of the plan, None with no plan
      q_not_attempted  the `do` pairs with no REACHED QUERY line, listed unreachable or not listed, None with no plan
      not_attempted    those pairs as `(geo, title, reason | None)`, in plan order (`reason` is an unreachable line's own)
      extra            QUERY lines whose pair is not a `do` pair of the plan, with no plan every line
      bounded          reached queries whose result was larger than the part read (a `<m>+` bound, or `shown` under `total`)
      bounded_text     `["read 25 of 99+ on 2 queries", ...]`, one entry per distinct (shown, total)"""
    by_key = {}
    for q in queries:
        k = pair_key(q["geo"], q["title"])
        if k not in by_key or (q["status"] == "reached" and by_key[k]["status"] != "reached"):
            by_key[k] = q
    pairs = []
    for k, q in by_key.items():
        if not str(q["title"]).strip():
            continue
        reached = q["status"] == "reached"
        total = q.get("total") if reached else None
        if total is not None and q.get("total_lower_bound"):
            total = max(total, q["shown"])
        pairs.append({"geo": q["geo"], "title": q["title"], "reached": reached, "shown": q["shown"] if reached else 0, "total": total})
    seen_bounds = {}
    for q in queries:
        if q["status"] == "reached" and q["truncated"]:
            key = (q["shown"], q.get("total"), bool(q.get("total_lower_bound")))
            seen_bounds[key] = seen_bounds.get(key, 0) + 1
    bounded_text = ["read %d of %s%s on %d quer%s" % (shown, total, "+" if lower else "", n, "y" if n == 1 else "ies")
                    for (shown, total, lower), n in sorted(seen_bounds.items())]
    out = {"pairs": pairs, "q_planned": None, "q_not_attempted": None, "not_attempted": [], "extra": len(queries),
           "bounded": sum(seen_bounds.values()), "bounded_text": bounded_text}
    if entries is None:
        return out
    do = [e for e in entries if e.get("do")]
    do_keys = {pair_key(e["geo"], e["title"]) for e in do}
    missing = [e for e in do if not (pair_key(e["geo"], e["title"]) in by_key and by_key[pair_key(e["geo"], e["title"])]["status"] == "reached")]
    out.update(q_planned=len(do), q_not_attempted=len(missing),
               not_attempted=[(e["geo"], e["title"], (by_key.get(pair_key(e["geo"], e["title"])) or {}).get("reason")) for e in missing],
               extra=sum(1 for q in queries if pair_key(q["geo"], q["title"]) not in do_keys))
    return out
