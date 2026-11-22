#!/usr/bin/env python3
"""build_reach.py -- the BUILD view: a way in at each target company where the network has none (jobsearch 0.91.0,
design-build-reach.md 6).

    python3 build_reach.py [--json] [--as-of YYYY-MM-DD]
    python3 build_reach.py --measures [--json] [--as-of YYYY-MM-DD]

For every `active-target` company whose path is `none` (current employees only), the ranked BUILD lines `reach/build.py` derives
(an advice ask to a former employee, an affiliation search, the side-door play's next step, pointers, the plain lookup), the
company's vertical and stated motivation, and, on EVERY target, an adopted side-door play's pending step and the side-door asks
still awaiting (`side_asks_open`: an ask is never a way in, owner O17). The weekly strategy turn reads `--json` for the verticals of
the path-none targets it suggests public events for (`agents/search-strategist.md`); the daily run's network block drafts from
`reachouts.py --plan`, which spends the week's units on the same lines.

`--measures` prints the WEEK's network counts (conversations held against `network.conversations_per_week`, asks sent by kind,
people added with a stated tie, targets with a new way in, side-door asks awaiting, follow-ups on time, events attended, employment
confirmed), the side-door chain, and the reply rate per ask kind over a trailing 12-week cohort of RESOLVED asks (design 8, R2 N11,
N13a; owner O17, O20): `reach/measures.py` replays them from the rows and `access.py --json --since <the Sunday before the week>`;
nothing is stored. `measures_text(root, today)` is the same text, for `strategy_view.py` and the weekly review.

It is a VIEW over `access.py --json` (the derived `reach` block on each row), run as its own process so this entry point imports
no other entry point: the table, the path and the lines are computed once, by `access.py`, and nothing is stored. It sends nothing,
drafts nothing, opens no link and searches for no person (ADR-037).

Exit codes: 0 the view (or NO TARGETS DECLARED), 1 NOT CHECKED (no profile data: never "no BUILD lines"), 2 a malformed argument
or an unreadable input (passed through from `access.py`). Python 3.9+, standard library only.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config_keys as _ck  # noqa: E402
from _root import is_unbound, profile_root  # noqa: E402
from measuring import mail_coverage as _mc  # noqa: E402
from reach import keys as _rk, measures as _ms  # noqa: E402


def view(doc):
    """`{"as_of", "status", "message", "thin": [...], "side_doors": [...], "side_asks_open": n}` from `access.py --json`'s document:
    `thin` is one entry per path-none target (`company_id`, `name`, `vertical`, `motivation`, `build`), in the table's order."""
    rows = doc.get("rows") or []
    thin = [{"company_id": r["company_id"], "name": r.get("name"), "vertical": r.get("vertical"), "motivation": r.get("motivation"),
             "build": r["reach"]["build"]} for r in rows if r["reach"]["path"] == "none"]
    doors = [dict(r["reach"]["side_door"], company_id=r["company_id"]) for r in rows if r["reach"].get("side_door")]
    return {"as_of": doc.get("as_of"), "status": doc.get("status"), "message": doc.get("message"), "thin": thin,
            "side_doors": doors, "side_asks_open": sum(r["reach"]["side_asks_open"] for r in rows),
            "verticals": sorted({t["vertical"] for t in thin if t["vertical"]})}


def render(v):
    if v["status"] != "ok":
        return v["message"] or "NO TARGETS DECLARED"
    out = ["BUILD  as of %s  (%d target%s with no way in; side-door asks awaiting: %d)"
           % (v["as_of"], len(v["thin"]), "" if len(v["thin"]) == 1 else "s", v["side_asks_open"])]
    for t in v["thin"]:
        out.append("%s  (M %s, %s)" % (t["name"] or t["company_id"], "?" if t["motivation"] is None else t["motivation"],
                                       t["vertical"] or "no vertical"))
        for i, l in enumerate(t["build"]):
            mark = "best" if i == 0 else "    "
            words = " -- ".join(x for x in (l.get("words"), l.get("link")) if x)
            out.append("  %s %d %-18s %s%s" % (mark, l["rank"], l["kind"], l["why"], (" -- " + words) if words else ""))
    for d in v["side_doors"]:
        out.append("SIDE-DOOR %s %s: next step %s%s" % (d["company_id"], d["opp_id"], d["step"],
                                                       " (waiting on %s)" % d["waiting_on"] if d.get("waiting_on") else ""))
    if not v["thin"]:
        out.append("every target has a way in (a warm current employee, or an introduction open)")
    return "\n".join(out)


def _access_json(root, as_of, since=None):
    """`access.py --json` for the profile at `root` (named to the child, never resolved twice), or raise `NotChecked`/`ValueError`
    with the child's own words."""
    cmd = [sys.executable, os.path.join(HERE, "access.py"), "--json", "--as-of", as_of.isoformat()]
    p = subprocess.run(cmd + (["--since", since.isoformat()] if since else []), capture_output=True, text=True,
                       env=dict(os.environ, CLAUDESEARCH_ROOT=root, CLAUDESEARCH_DATA_DIR=os.path.join(root, "data")))
    if p.returncode == 1:
        raise _ms.NotChecked(p.stdout.strip())
    if p.returncode != 0:
        raise ValueError("access.py: %s" % (p.stderr.strip() or p.stdout.strip()))
    return json.loads(p.stdout)


def measures(root, today):
    """The week's measures for the profile at `root` as of `today` (a date): `reach.measures.week` over the rows and the replayed
    access table. Raises `reach.measures.NotChecked` (no profile data) or `ValueError` (an unreadable row, date or setting)."""
    stores = _ms.load(root)
    stores["coverage"], stores["journal_problem"] = _mc.coverage(root)      # the reply-rate hole check (R2 N11)
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        cfg = {}
    _label, monday, _sunday = _ms.iso_week(today)
    rows = _access_json(root, today, monday - datetime.timedelta(days=1)).get("rows") or []
    return _ms.week(stores, rows, today, target=_ck.resolve_int(cfg, _rk.NETWORK_CONVERSATIONS_PER_WEEK),
                    marks=_ck.resolve_followup_days(cfg), workdays=_ck.resolve_workdays(cfg),
                    side_asks_open=sum(r["reach"]["side_asks_open"] for r in rows), tz=_mc.declared_zone())


def measures_text(root, today):
    """The `--measures` text for the profile at `root` as of `today` (what `strategy_view.py` asks for)."""
    return _ms.render(measures(root, _ms.to_date(today)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="The BUILD view: a way in at each target with none (derived; nothing is stored).")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD", help="the date to compute for (default today)")
    ap.add_argument("--measures", action="store_true", help="the week's network counts and the trailing reply rates")
    args = ap.parse_args(argv)
    if args.measures:
        try:
            today = _ms.to_date(args.as_of) if args.as_of else datetime.date.today()
            if is_unbound(profile_root()):
                raise _ms.NotChecked("nothing identified a profile here")
            w = measures(profile_root(), today)
        except _ms.NotChecked as e:
            print("NOT CHECKED: the weekly measures cannot be answered (%s). This is not a week of zeros." % e)
            return 1
        except ValueError as e:
            print("build_reach.py: %s" % e, file=sys.stderr)
            return 2
        print(json.dumps(w, indent=2, default=str) if args.json else _ms.render(w))
        return 0
    cmd = [sys.executable, os.path.join(HERE, "access.py"), "--json"] + (["--as-of", args.as_of] if args.as_of else [])
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr.replace("access.py:", "build_reach.py (from access.py):"))
        return p.returncode
    v = view(json.loads(p.stdout))
    print(json.dumps(v, indent=2, default=str) if args.json else render(v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
