"""The held roles on the page (jobsearch 0.92.0, dev #1002, criterion E1; docs/design-decision-surface.md §E, review round 2 G3):
a ready-or-held role is always visible.

    expected(opps, stage_of, matches) -> {"ids", "unmatched", "count"}
    check_held(page, ledger, exp, facts) -> (gaps, line)
    run(page, ledger, lifecycle_at, not_checked) -> (gaps, line)   what check_dashboard_coverage.check() calls

`expected` is the gate's OWN selection, written from the stage definition and importing nothing from the renderer's side
(`reach.held_roles`): the opportunities whose `stage_of(o)` is `held-for-company` with why `undecided` or `watching` and whose
title `matches`; `unmatched` when `matches` cannot answer (no target titles configured), and then no id is expected; `count`, every
held opportunity (any why). A wrong filter in `reach.held_roles.listing` disagrees with it. SHARED, and said: both sides call the
same `lifecycle` stage and `profile.title_matches`, so a defect inside either is not caught here.

| gap | fires when |
|---|---|
| `HELD ROLE HIDDEN` | an expected id is neither a rendered primary row (`data-rec="opp:<id>"`, ledgered `rendered`) nor in the `held-roles` remainder |
| `HELD COUNT` | the page's `data-held` differs from `count` (opportunities only, G3), or is absent while `count` is above zero |
| `HELD COUNT UNEXPLAINED` | `process_report().held_for_company` minus `data-held` minus `data-held-items` (the feed items not yet roles) is not 0 |
| `HELD LIST UNSAID` | `unmatched`, and the page lacks `data-held-list="unmatched"` |
| `HELD CAUSE` | (jobsearch 0.94.0, dev 1062) the page's `data-held-causes` (`title:2 pay:1`, the count line's WHY by the first criterion failed) differs from the gate's own count of the held opportunities' stage `cause` (`expected_causes`), or is absent while one is counted, or cannot be read |

`facts` is `{"held_all": process_report().held_for_company, "causes": expected_causes(...)}` (`causes` is optional: a caller that gives none
skips the `HELD CAUSE` check, as `run` never does). `page` is the html, `ledger` the ledger file's object. `run` takes
`lifecycle_at(now)`, the gate's `_lifecycle_facts` bound to the profile (`(data, report, ctx, your_move, matches)`), and the gate's
`NOT_CHECKED` list: a lifecycle that cannot be read appends its reason there and checks nothing, never a pass. The rest is pure."""
import datetime
import html as _html
import re

HELD = "held-for-company"
WHY = ("undecided", "watching", "passed", "pursued")      # 0.94.0 (dev 1062): `pursued` is counted, never listed (not `undecided`)
LISTED = ("undecided", "watching")
SET = "held-roles"
_HELD_RE = re.compile(r'data-held="(\d+)"')
_ITEMS_RE = re.compile(r'data-held-items="(\d+)"')
_GEN_RE = re.compile(r'data-generated="([^"]+)"')
_CAUSES_RE = re.compile(r'data-held-causes="([^"]*)"')


def page_now(page):
    """The page's own generation instant (`data-generated`); ValueError when it carries none that reads."""
    m = _GEN_RE.search(page)
    if not m:
        raise ValueError("the page carries no readable generation time")
    return datetime.datetime.fromisoformat(_html.unescape(m.group(1)))


def expected(opps, stage_of, matches):
    """The gate's own selection (the module docstring)."""
    ids, unmatched, count = [], False, 0
    for o in opps:
        st = stage_of(o)
        if getattr(st, "name", None) != HELD:
            continue
        count += 1
        if (st.detail if st.detail in WHY else "undecided") not in LISTED:
            continue
        m = matches(str(o.get("title") or ""))
        if m is None:
            unmatched = True
        elif m and o.get("id"):
            ids.append(o["id"])
    return {"ids": [] if unmatched else sorted(ids), "unmatched": unmatched, "count": count}


def expected_causes(opps, stage_of):
    """`{cause: n}` over the held opportunities, by the stage's own `cause` (the gate's selection, written here and not imported from the
    renderer's side); a held role with no cause (held for its company alone, as in 0.93.0) is in none."""
    out = {}
    for o in opps:
        st = stage_of(o)
        if getattr(st, "name", None) == HELD and getattr(st, "cause", None):
            out[st.cause] = out.get(st.cause, 0) + 1
    return out


def _page_causes(page):
    """`{cause: n}` the page's `data-held-causes` says ({} when it carries none); ValueError when it cannot be read."""
    m = _CAUSES_RE.search(page)
    out = {}
    for item in (m.group(1).split() if m else ()):
        name, _, n = item.partition(":")
        if not name or not n.isdigit() or name in out:
            raise ValueError("%r is not `cause:count`" % item)
        out[name] = int(n)
    return out


def _visible(key, page, records):
    rec = records.get(key) or {}
    if rec.get("disposition") == "rendered":
        return ('data-rec="%s"' % _html.escape(key, False)) in page
    return rec.get("disposition") == "remainder" and rec.get("where") == SET


def check_held(page, ledger, exp, facts):
    """(gaps, line): the four gaps of the module docstring."""
    records = (ledger or {}).get("records") or {}
    gaps = ["HELD ROLE HIDDEN -- held role opp:%s (its company undecided or watched, its title matching) is neither a primary "
            "row on the page nor counted in the %s remainder" % (oid, SET)
            for oid in exp["ids"] if not _visible("opp:%s" % oid, page, records)]
    m = _HELD_RE.search(page)
    shown = int(m.group(1)) if m else None
    if shown is None and exp["count"]:
        gaps.append("HELD COUNT -- %d role(s) are held for a company decision and the page shows no held count (data-held)"
                    % exp["count"])
    elif shown is not None and shown != exp["count"]:
        gaps.append("HELD COUNT -- the page shows %d held; the opportunities held for a company decision are %d"
                    % (shown, exp["count"]))
    items = int((_ITEMS_RE.search(page) or [0, 0])[1]) if shown is not None else 0
    if shown is not None and facts["held_all"] - shown - items != 0:
        gaps.append("HELD COUNT UNEXPLAINED -- process_report holds %d; the page counts %d role(s) and %d feed item(s), so %d "
                    "are explained nowhere" % (facts["held_all"], shown, items, facts["held_all"] - shown - items))
    if "causes" in facts:
        try:
            got = _page_causes(page)
        except ValueError as e:
            got = None
            gaps.append("HELD CAUSE -- the page's data-held-causes cannot be read: %s" % e)
        if got is not None and got != facts["causes"]:
            gaps.append("HELD CAUSE -- the page counts the held roles by criterion as %s; their stages say %s"
                        % (got or "nothing", facts["causes"] or "nothing"))
    if exp["unmatched"] and 'data-held-list="unmatched"' not in page:
        gaps.append("HELD LIST UNSAID -- no target titles are configured, so no held role can be listed, and the page does not "
                    "say so (data-held-list=\"unmatched\")")
    return gaps, "held roles: %d expected listed%s, page %s of %d held (%d feed item(s)), process_report %d" % (
        len(exp["ids"]), " (unmatched)" if exp["unmatched"] else "", "-" if shown is None else shown, exp["count"], items,
        facts["held_all"])


def run(page, ledger, lifecycle_at, not_checked):
    """(gaps, line) for `check_dashboard_coverage.check()`: the lifecycle at the page's own instant, then `check_held`."""
    try:
        data, rep, ctx, _ym, matches = lifecycle_at(page_now(page))
        exp = expected(data["opportunities"], ctx.stage_of_opp, matches)
    except Exception as e:                                       # noqa: BLE001 - said, never a pass
        not_checked.append("held roles (%s: %s)" % (type(e).__name__, str(e)[:100]))
        return [], "held roles: NOT CHECKED"
    return check_held(page, ledger, exp, {"held_all": rep.held_for_company,
                                          "causes": expected_causes(data["opportunities"], ctx.stage_of_opp)})
