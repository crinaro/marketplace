"""outcomes: the outcomes-by-variant section (design-presence-report.md §5.4, D-OUTCOME).

Applications are grouped by the newest application per role, through the funnel's own mechanism
(`pursuits.app_outcomes.buckets`, moved out of `funnel_report.py` in B0, never copied), and attributed to that row's
`resume_variant`. Rows with none form an `unattributed` line; a retired variant still shows, because `applications`
may name one forever.

- **Reply rate** = heard / (heard + closed on silence, including aged), the funnel's own definition.
- **Interview rate** = roles whose newest application is `advanced` / the same denominator (O13).

Both print through `pct()`, which returns `n/d (too few to rate)` below `MIN_SAMPLE` and never a percentage. Pure
over rows the caller read; nothing here reads a file or writes."""

import collections

from pursuits.app_outcomes import buckets, pct

UNATTRIBUTED = "unattributed"
RULE = ("  newest application per role; reply = heard / (heard + closed on silence, incl. aged); interview = advanced / "
        "the same; no rate below n=5")


def tallies(opps, apps, silence_days):
    """`{variant id or UNATTRIBUTED: {"heard", "closed", "advanced"}}` over the newest application per role."""
    by_id = {o.get("id"): o for o in opps if isinstance(o, dict)}
    pairs = [(by_id.get(a.get("opp_id"), {}), a) for a in apps if isinstance(a, dict)]
    out = collections.defaultdict(lambda: {"heard": 0, "closed": 0, "advanced": 0})
    b = buckets(by_id, pairs, silence_days)
    for _o, newest in b["heard"]:
        t = out[newest.get("resume_variant") or UNATTRIBUTED]
        t["heard"] += 1
        t["advanced"] += 1 if newest.get("status") == "advanced" else 0
    for _o, newest in b["closed-silence"]:
        out[newest.get("resume_variant") or UNATTRIBUTED]["closed"] += 1
    return out


def section_lines(opps, apps, silence_days, declared_ids):
    """One line per variant (declared ones, then any other an application names, then `unattributed`)."""
    t = tallies(opps, apps, silence_days)
    named = sorted(k for k in t if k != UNATTRIBUTED and k not in declared_ids)
    lines = [RULE]
    for vid in list(declared_ids) + named + [UNATTRIBUTED]:
        if vid == UNATTRIBUTED and vid not in t:
            continue
        row = t.get(vid, {"heard": 0, "closed": 0, "advanced": 0})
        d = row["heard"] + row["closed"]
        lines.append("  %s: reply rate %s; interview rate %s" % (vid, pct(row["heard"], d), pct(row["advanced"], d)))
    return lines
