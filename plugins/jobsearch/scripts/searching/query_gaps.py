"""query_gaps: the per-QUERY accounting of an accepted ROLES block, and the gaps it files (jobsearch 0.94.0, step P0; dev 1055, 1064,
1065; docs/design-role-first.md section 13). Moved out of `deferred.add_roles`, which calls here once the roles are resolved. No
behaviour change: the printed lines, their order and the gaps filed are the block's own.

`file_query_gaps(queries, surface, run_id, out, file_gap)` walks the parsed QUERY lines of one block. A query whose window did not
apply (or that was unreachable) files `jobsearch:query:<surface>:<geo>[:<channel>]` with the reason; one that showed fewer results
than its total is TRUNCATED; one whose filters were dropped, added or unread, or whose result count was not read, files a
`partial-results` gap of its own. `card_evidence` (0.94.0, dev 1055) only changes the sentence a dropped or added filter prints: its roles are
held only where the card does not answer it, never "unless a clean query also showed them". `out(text)` is the caller's printer and `file_gap(run_id, scope, reason, closes_when, out)` its
one gap filer (`deferred._file_gap`: once per `(run, scope)`, best-effort), both passed in because a package imports no entry point
(G5). It returns `(geos_ok, gaps_window, gaps_trunc, gaps_filters, q_reached, q_clean, q_unread, q_total_unknown,
q_degraded_queries, q_degraded)`.

Python 3.9+, standard library only."""


def file_query_gaps(queries, surface, run_id, out, file_gap, card_evidence=False):
    """Print and file the gaps of `queries`, and return the counts the `roles` event records (see the module docstring)."""
    geos_ok, gaps_window, gaps_trunc, gaps_filters = set(), 0, 0, 0
    # dev #722 / public #156 (R4) -- the per-query READ counts. Every reached query is exactly one of
    # clean (dropped=none, added=none, nothing degraded), unread (`?` on a filter slot, nothing
    # degraded) or degraded; `total=?` over a page is counted APART (it can sit under any of the
    # three). SHAPE, not enforced: these are counts of what the sweep SAID.
    q_reached = q_clean = q_unread = q_total_unknown = q_degraded_queries = 0
    q_degraded = {}
    for q in queries:
        scope = "jobsearch:query:%s:%s%s" % (surface, q["geo"],
                                              (":" + q["channel"]) if q.get("channel") else "")
        if q["status"] == "reached" and not q["window_gap"]:
            geos_ok.add(q["geo"])
        if q["status"] == "reached":
            q_reached += 1
            if "total-unknown" in q["unread"]:
                q_total_unknown += 1
            if q["degraded"]:
                q_degraded_queries += 1
                for code in q["degraded"]:
                    q_degraded[code] = q_degraded.get(code, 0) + 1
            elif "filters-unread" in q["unread"]:
                q_unread += 1
            else:
                q_clean += 1
        if q["window_gap"]:
            gaps_window += 1
            reason = q.get("reason") or "partial-results"
            out("QUERY GAP  %s (%s): %s" % (scope, reason,
                                            "unreachable" if q["status"] == "unreachable"
                                            else "window not applied"))
            file_gap(run_id, scope, reason, "the next pass applies its window on this query", out)
        elif q["truncated"]:
            gaps_trunc += 1
            out("QUERY TRUNCATED %s: shown %d of %s%s" % (scope, q["shown"], q["total"],
                                                          "+" if q.get("total_lower_bound") else ""))
            file_gap(run_id, scope, "partial-results",
                     "a narrower query shows every result", out)
        if q["status"] == "reached" and (q["dropped"] or q["added"] or q["dropped_unread"]
                                         or q["added_unread"]):
            gaps_filters += 1
            if q["dropped"] or q["added"]:
                named = [x for x in (
                    ("dropped=%s" % ",".join(q["dropped"])) if q["dropped"] else "",
                    ("added=%s" % ",".join(q["added"])) if q["added"] else "") if x]
                out("QUERY FILTERS %s: %s (%s)" % (scope, "; ".join(named), (
                    "its roles are held only where their own card does not answer it" if card_evidence else
                    "its roles are quarantined unless a clean query also showed them")))
            else:
                out("QUERY FILTERS %s: filters unread (dropped/added = ?): a gap, never a "
                    "quarantine" % scope)
            file_gap(run_id, scope, "partial-results",
                     "the next pass applies the requested filters on this query", out)
        if q["status"] == "reached" and "total-unknown" in q["unread"]:
            out("QUERY TOTAL UNKNOWN %s: shown %d, total not read (counted; never a quarantine)"
                % (scope, q["shown"]))
            file_gap(run_id, scope, "partial-results",
                     "the next pass reads the result count on this query", out)
    return (geos_ok, gaps_window, gaps_trunc, gaps_filters, q_reached, q_clean, q_unread, q_total_unknown,
            q_degraded_queries, q_degraded)


NO_PLAN_LINE = "SEARCHED WITHOUT AN ATTENDED PLAN"          # design-role-first.md 8.1: `--add-roles` of a search with no `scope: search` dispatch keeps the roles and says so
NO_PLAN_SCOPE = "jobsearch:query:%s:no-plan"
PLAN_GAP_SCOPE = "jobsearch:query:%s:not-attempted"      # ONE gap for every planned query a search pass did not read (design-role-first.md 5.3)


def file_plan_gaps(acct, surface, run_id, out, file_gap):
    """Print and file the accounting `query_plan.account` made of one ROLES block against its stored plan (jobsearch 0.94.0, dev 1055, LC3, LC4).
    With a plan: one `QUERY PLAN` line (planned, read, not attempted, extra), a `NOT-ATTEMPTED <geo> <title>` line for each planned pair with no reached
    QUERY line, listed or not, and ONE `partial-results` gap for all of them. `bounded: read 25 of 99+ on 2 queries` is printed for what a first page
    cut short; the rest is not read, never zero found. `out(text)` and `file_gap(run_id, scope, reason, closes_when, out)` are the caller's."""
    if acct["q_planned"] is not None:
        out("QUERY PLAN %d planned · %d read · %d NOT-ATTEMPTED · %d extra (a QUERY outside this pass's plan: accepted, counted)"
            % (acct["q_planned"], acct["q_planned"] - acct["q_not_attempted"], acct["q_not_attempted"], acct["extra"]))
        for geo, title, reason in acct["not_attempted"]:
            out("NOT-ATTEMPTED %s %s%s" % (geo, title, (" (listed unreachable: %s)" % reason) if reason else ""))
        if acct["not_attempted"]:
            file_gap(run_id, PLAN_GAP_SCOPE % surface, "partial-results", "the next search pass reads the planned queries", out)
    else:
        out(NO_PLAN_LINE + ": no `search-plan` dispatch of this run is on record, so no planned query can be held against what was read (the roles are kept)")
        file_gap(run_id, NO_PLAN_SCOPE % surface, "partial-results", "the next search is dispatched by `linkedin_sweep.py search-plan`", out)
    for text in acct["bounded_text"]:
        out("bounded: " + text)
