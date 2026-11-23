"""app_outcomes: the application funnel's arithmetic, moved out of `funnel_report.py`
(design-presence-report.md §11 B0): `pct`, which refuses a rate below `MIN_SAMPLE`, and
`buckets`, the APPLICATIONS section's ending buckets. `funnel_report` re-exports both."""

import collections
from pursuits.app_endings import ended_because
from reach.resolution import MIN_SAMPLE, days_since


def pct(n, d):
    """A rate, or an explicit refusal to compute one."""
    if d == 0:
        return "n/a"
    if d < MIN_SAMPLE:
        return "%d/%d (too few to rate)" % (n, d)
    return "%d/%d = %d%%" % (n, d, round(100.0 * n / d))


def buckets(opps_by_id, apps, silence_days):
    """The APPLICATIONS section's ending buckets (States & Views V1 §3c), newest application per
    role: {"heard", "closed-silence", "live", "withdrawn", "expired", "unrecorded"}, each a list of
    (opportunity, newest application). `apps` is [(opportunity, application)]; an application past
    `silence_days` that nobody closed is counted as closed on silence, the row never mutated."""
    by_opp_apps = collections.defaultdict(list)
    for _o, _a in apps:
        if _a.get("opp_id"):
            by_opp_apps[_a["opp_id"]].append(_a)
    heard, closed_silence = [], []
    live_bucket, withdrawn_b, expired_b, unrecorded_b = [], [], [], []
    for oid, opp_apps in by_opp_apps.items():
        o = opps_by_id.get(oid, {})
        newest = sorted(opp_apps, key=lambda a: str(a.get("date") or ""))[-1]
        reason = ended_because(o, opp_apps)
        status = newest.get("status")
        if reason == "rejected" or status == "advanced":
            heard.append((o, newest))
        elif reason == "closed-silence":
            closed_silence.append((o, newest))
        elif reason == "withdrawn":
            withdrawn_b.append((o, newest))
        elif reason == "expired":
            expired_b.append((o, newest))
        elif reason == "unrecorded":
            unrecorded_b.append((o, newest))
        elif status in ("submitted", "acknowledged"):
            anchor = newest.get("status_on") or newest.get("date")
            age = days_since(anchor) if anchor else None
            if age is not None and age >= silence_days:
                closed_silence.append((o, newest))   # resolved-aged — counted, not mutated
            else:
                live_bucket.append((o, newest))
    return {"heard": heard, "closed-silence": closed_silence, "live": live_bucket,
            "withdrawn": withdrawn_b, "expired": expired_b, "unrecorded": unrecorded_b}
