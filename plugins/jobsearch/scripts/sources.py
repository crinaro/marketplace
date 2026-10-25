#!/usr/bin/env python3
"""sources.py -- every job SOURCE this search uses, whether each is on, how it is reached and whether it is covered
(dev #774; jobsearch 0.76.0; docs/design-source-catalog.md section 7).

    sources.py --text [--kind K] [--today YYYY-MM-DD]      the view, as plain lines
    sources.py --json [--kind K] [--today YYYY-MM-DD]      the same rows as one JSON object

THE ONE VIEW. Until 0.76.0 the pieces existed and were scattered: each channel row had its own off bit, the
LinkedIn job search had none, company feeds could only be declined one company at a time (and that discards the
slug), and nothing listed all of them. This lists them all, from the stores, and COMPOSES the readers that already
know each answer instead of computing anything new:

    column     comes from
    id, label  the channel row, or `company-feeds` for the feed policy
    kind       the stamp's catalog entry; a HAND row's kind is derived (alert-email -> alert-sender; job-board with
               `portfolio_of` -> portfolio; job-board with manual-candidate access -> curated; else swept-board)
    origin     `catalog:<entry>@<state>` (the reconcile's own state function) or `yours`
    on         the one off bit for the kind (design section 4.1): a channel row is OFF when
               `relationship_status: retired`; the feed policy is OFF when `sourcing.feeds.enabled` is false
    reached    `route.py`'s resolver for a channel row (requirement -> ordered mechanisms, or "candidate: you
               open it"); "your mailbox (alert_sweep)" for an `alert_sender`; "feed GET" for the policy
    coverage   `channels_due.review_rows` for a channel row, `portfolio_boards.coverage` for a `portfolio_of` row,
               and `feed_poll.coverage_summary` for the policy

A fact this cannot know prints `NOT CHECKED (why)` and never `0`. An alert sender's per-sender yield is measured by
no existing reader, so its coverage says "swept daily; not measured per sender".

WHAT AN ABSENT ROW MEANS (review R1 / B5), stated per kind so the view and the readers cannot disagree:
    portfolio, curated, alert-sender   no row = not in use (nothing is swept or reviewed)
    swept-board                        depends on the entry's `absence_reads_as`: the LinkedIn job search reads
                                       "on" (an install older than 0.76.0 never held the row and its search ran), so a
                                       profile with no `linkedin-jobsearch` row is shown as ON with origin
                                       "no row", never under "You could turn on"
    feed-policy                        no `sourcing.feeds.enabled` key = ON (0.72.0's behaviour)

READ-ONLY BY CONSTRUCTION: writes nothing, takes no lock. `record.py source on|off` is the only writer.
`test_sources.py` proves the profile's tree hash is identical before and after.

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

KIND_ORDER = ("swept-board", "alert-sender", "feed-policy", "curated", "portfolio")
SOURCE_TYPES = ("job-board", "aggregator", "alert-email")
FEEDS_ID = "company-feeds"


class SourcesError(Exception):
    """A store the view needs cannot be read. A refusal is never an empty report."""


# ---- strict readers --------------------------------------------------------------------------------

def _rows(root, name):
    path = os.path.join(root, "data", name)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [l for l in fh if l.strip()]
    except FileNotFoundError:
        return []
    except OSError as e:
        raise SourcesError("%s cannot be read (%s)" % (name, e))
    out = []
    for n, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            raise SourcesError("%s has a row that is not valid JSON (row %d)" % (name, n))
        if not isinstance(row, dict):
            raise SourcesError("%s row %d is not an object" % (name, n))
        out.append(row)
    return out


def _config(root):
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise SourcesError("config.json cannot be read (%s)" % e)
    if not isinstance(cfg, dict):
        raise SourcesError("config.json is not an object")
    return cfg


# ---- the query template (SC3, ruled run-time: design section 3.3) ----------------------------------------

def fill_query(template, profile, config):
    """The `query_template` with its closed vocabulary filled from the profile as it stands NOW:

        {titles}     `targets.titles` of the profile, each quoted, joined with OR
        {geo}        `journal.jobsearch_geos` of the config: `remote`, plus `local` when commute anchors exist
        {seniority}  `screen.title_floor` of the config

    A value the profile does not state renders as the literal `{titles:UNSET}` (or `{geo:UNSET}`, `{seniority:UNSET}`),
    NEVER a guess: board-sweeper's own rule is that a malformed query and an empty board look identical. The template
    is stored on the row unfilled; this runs when `source on` prints "this will search" and when `route.py --channel`
    prints the `QUERY` line, so a changed title list reaches the next sweep without a rewrite."""
    if template is None:
        return None
    import journal as _journal
    titles = [t for t in (((profile or {}).get("targets") or {}).get("titles") or []) if isinstance(t, str) and t.strip()]
    cfg = config or {}
    geos = _journal.jobsearch_geos(cfg) if (cfg.get("geography") or {}).get("commute_anchors") is not None else []
    floor = (cfg.get("screen") or {}).get("title_floor")
    values = {"titles": " OR ".join('"%s"' % t for t in titles) if titles else None,
              "geo": ", ".join(geos) if geos else None,
              "seniority": floor if isinstance(floor, str) and floor.strip() else None}
    out = template
    for name, value in values.items():
        out = out.replace("{%s}" % name, value if value else "{%s:UNSET}" % name)
    return out


# ---- kinds, origins, reach and coverage ---------------------------------------------------------------

def derive_kind(row):
    """The kind of a HAND-made source row (no stamp to name it)."""
    import portfolio_boards as _pb
    if row.get("type") == "alert-email":
        return "alert-sender"
    if _pb.FIRM_LINK_FIELD in row:
        return "portfolio"
    if row.get("access") == "manual-candidate":
        return "curated"
    return "swept-board"


def is_source_row(row):
    return row.get("type") in SOURCE_TYPES


def _reach(row, cfg, entry=None):
    """(text, problem). `route.py`'s own resolver; never a mechanism it did not return."""
    import route as _route
    parts = []
    problem = None
    access = row.get("access") if row else (entry or {}).get("access")
    if access == "n/a" or (row and row.get("type") == "alert-email"):
        pass
    else:
        try:
            req, _legacy = _route.parse_access(access)
            if req == "manual-candidate":
                parts.append("candidate: you open it")
            else:
                mechs = _route.route(req, _route.preference(cfg), (row or {}).get("id") or (entry or {}).get("channel_id"), cfg)
                parts.append("%s (%s)" % (" -> ".join(mechs), req) if mechs else "no browsable route (%s)" % req)
        except _route.RouteError as e:
            problem = "NOT CHECKED (%s)" % e
    if row and row.get("alert_sender"):
        parts.append("your mailbox (alert_sweep: %s)" % row["alert_sender"])
    elif row is None and entry and entry.get("alert_sender"):
        parts.append("your mailbox (alert_sweep: %s)" % entry["alert_sender"])
    return ("; ".join(parts) if parts else (problem or "NOT CHECKED (nothing resolves it)")), problem


def _coverage(row, today):
    import channels_due as _cd
    import portfolio_boards as _pb
    if row.get("type") == "alert-email":
        return "swept daily; not measured per sender" if row.get("relationship_status") != "retired" else "RETIRED: not swept"
    if _pb.FIRM_LINK_FIELD in row:
        return _pb.coverage(row, today)["text"]
    rows = _cd.review_rows([row], today)
    if not rows:
        return "NOT CHECKED: this channel type is not in the review queue"
    _c, state, detail = rows[0]
    if state == "retired":
        return "RETIRED: not reviewed by design"
    if state in ("due", "current"):
        return ("DUE: %s" if state == "due" else "COVERED: %s") % detail.get("why")
    return "NOT CHECKED: %s" % detail.get("why")


def _feeds_row(root, cfg, today, catalog):
    import config_keys as _ck
    import feed_poll as _fp
    import journal as _journal
    on, problem = _ck.feeds_enabled(cfg)
    entry = next((e for e in (catalog or {}).get("entries", []) if e.get("kind") == "feed-policy"), None)
    companies = _rows(root, "companies.jsonl")
    try:
        recs = _journal.read(root)
        cov = _fp.coverage_summary(companies, recs)
        if not on:
            cov_text = "OFF: no company's feed is polled or counted as covering its page"
        elif cov["fed"] == 0:
            cov_text = "0 companies carry a feed slug (nothing to poll yet)"
        else:
            cov_text = "%d fed · %d covered at the last poll · %d NOT COVERED%s" % (
                cov["fed"], cov["covered"], cov["not_covered"],
                (" · %d NOT CHECKED" % cov["not_checked"]) if cov["not_checked"] else "")
    except _journal.JournalError as e:
        cov_text = "NOT CHECKED (the journal cannot be read: %s)" % e
    return {"id": (entry or {}).get("id", FEEDS_ID), "channel_id": None, "label": (entry or {}).get("label", "Company job-board feeds"),
            "kind": "feed-policy", "origin": "catalog:%s" % (entry or {}).get("id", FEEDS_ID) if entry else "engine",
            "on": on, "state": "on" if on else "off", "reached": "feed GET (the vendors' documented public APIs)",
            "coverage": cov_text, "note": problem}


def report(root, today=None, catalog=None, kind=None):
    """The view as data: {"today", "sources": [...], "turn_on": [...], "not_checked": [...], "counts": {...}}."""
    import channel_catalog as _cc
    today = today or datetime.date.today()
    cfg = _config(root)
    channels = _rows(root, "channels.jsonl")
    companies = _rows(root, "companies.jsonl")
    opps = _rows(root, "opportunities.jsonl")
    not_checked = []
    if catalog is None:
        try:
            catalog = _cc.load_catalog()
        except _cc.CatalogError as e:
            catalog = None
            not_checked.append("the channel catalog cannot be read (%s): origins and 'You could turn on' are not available" % e)
    entries = _cc.by_id(catalog) if catalog else {}
    cat_rev = catalog["revision"] if catalog else 0
    out = []
    held_entries = set()
    for row in channels:
        if not is_source_row(row):
            continue
        entry = entries.get(row.get("channel_catalog_entry")) if _cc.has_stamp(row) else None
        state = _cc.row_state(row, entries, cat_rev) if catalog and _cc.has_stamp(row) else None
        if entry is not None:
            held_entries.add(entry["id"])
        kind_of = entry["kind"] if entry is not None else derive_kind(row)
        retired = row.get("relationship_status") == "retired"
        if retired and entry is not None and _cc.is_retired(entry):
            on_state = "retired by the catalog: %s" % entry["retired"].get("reason")
        else:
            on_state = "off" if retired else "on"
        reach, _p = _reach(row, cfg)
        out.append({"id": row.get("id"), "channel_id": row.get("id"), "label": row.get("label") or row.get("id"),
                    "kind": kind_of, "origin": ("catalog:%s@%s" % (entry["id"], state)) if entry is not None else "yours",
                    "on": not retired, "state": on_state, "reached": reach, "coverage": _coverage(row, today),
                    "note": None})
    # a swept board whose reader treats an ABSENT row as ON (the LinkedIn job search) is shown as on, not offered
    present_ids = {r.get("id") for r in channels}
    for e in entries.values():
        if (e["kind"] == "swept-board" and e.get("absence_reads_as") == "on" and not _cc.is_retired(e)
                and e["channel_id"] not in present_ids and e["id"] not in held_entries):
            reach, _p = _reach(None, cfg, entry=e)
            out.append({"id": e["channel_id"], "channel_id": e["channel_id"], "label": e["label"], "kind": "swept-board",
                        "origin": "no row (reads as on; catalog entry %s)" % e["id"], "on": True, "state": "on",
                        "reached": "%s; read by %s" % (reach, e.get("route_by")),
                        "coverage": "NOT CHECKED: there is no row to review", "note": "turn it off with: record.py source off %s" % e["channel_id"]})
            held_entries.add(e["id"])
    try:
        out.append(_feeds_row(root, cfg, today, catalog))
    except SourcesError:
        raise
    except Exception as e:                                       # noqa: BLE001 -- loud, not fatal
        not_checked.append("company feeds: %s: %s" % (type(e).__name__, str(e)[:120]))
    out.sort(key=lambda r: (KIND_ORDER.index(r["kind"]), str(r["id"])))
    if kind:
        out = [r for r in out if r["kind"] == kind]
    turn_on = []
    if catalog:
        offers, tips = _cc.offer(catalog, channels, companies, opps)
        for e, reasons in offers:
            if e["id"] in held_entries or (kind and e["kind"] != kind):
                continue
            turn_on.append({"id": e["id"], "kind": e["kind"], "label": e["label"], "why": reasons,
                            "command": "record.py source on %s" % e["id"]})
        for e, cid in tips:
            if kind and e["kind"] != kind:
                continue
            attach = _cc.plan_add(catalog, [e["id"]], channels, companies, today.isoformat(), attach=cid)[0]
            if attach["status"] == "attach":
                turn_on.append({"id": e["id"], "kind": e["kind"], "label": e["label"],
                                "why": ["you already have it as %s" % cid],
                                "command": "record.py channel-catalog add %s --attach %s" % (e["id"], cid),
                                "tip": "matches catalog entry %s: channel-catalog add %s --attach %s to receive its updates"
                                       % (e["id"], e["id"], cid)})
    counts = {"on": sum(1 for r in out if r["on"]), "off": sum(1 for r in out if not r["on"]), "total": len(out)}
    return {"today": today.isoformat(), "sources": out, "turn_on": turn_on, "not_checked": not_checked, "counts": counts}


def render_text(rep):
    L = []
    c = rep["counts"]
    L.append("SOURCES: %d in all · %d on · %d off" % (c["total"], c["on"], c["off"]))
    for r in rep["sources"]:
        L.append("  %s  [%s]  %s  (%s)" % (r["id"], r["kind"], r["state"].upper() if r["on"] or r["state"] == "off" else r["state"],
                                          r["origin"]))
        L.append("      label:    %s" % r["label"])
        L.append("      reached:  %s" % r["reached"])
        L.append("      coverage: %s" % r["coverage"])
        if r.get("note"):
            L.append("      note:     %s" % r["note"])
    if not rep["sources"]:
        L.append("  none: this profile holds no source row yet")
    L.append("You could turn on:")
    if rep["turn_on"]:
        for t in rep["turn_on"]:
            L.append("  %s  [%s]  %s%s" % (t["id"], t["kind"], t["label"], ("  -  " + "; ".join(t["why"])) if t["why"] else ""))
            L.append("      %s" % (t.get("tip") or t["command"]))
    else:
        L.append("  nothing the catalog offers matches this profile")
    for nc in rep["not_checked"]:
        L.append("NOT CHECKED: %s" % nc)
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Every job source, whether it is on, how it is reached and covered (read-only).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--text", action="store_true")
    mode.add_argument("--json", action="store_true")
    ap.add_argument("--kind", choices=KIND_ORDER, help="only sources of one kind")
    ap.add_argument("--today", help="YYYY-MM-DD, for deterministic tests")
    args = ap.parse_args(argv)
    import _root
    root = _root.profile_root()
    if not _root.looks_like_profile(root):
        print("NOT CHECKED: %r does not look like a job-search profile (no config.json, no data/ directory)." % str(root))
        return 3
    today = datetime.date.fromisoformat(args.today) if args.today else None
    try:
        rep = report(str(root), today, kind=args.kind)
    except SourcesError as e:
        print("NOT CHECKED: %s" % e)
        return 1
    if args.json:
        print(json.dumps(rep, ensure_ascii=False))
    else:
        sys.stdout.write(render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
