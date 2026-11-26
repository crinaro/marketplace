"""roles_parts: the pieces of the run summary's `roles` lines that read only a journal event (jobsearch 0.94.0, step P0; dev 1055,
1064, 1065; docs/design-role-first.md section 13). Moved out of `run_summary.py` unchanged by `split_module.py move`, which keeps
every name importable from there: `quarantine clause`, `query reads line`, `feeds line`, the partial causes, `board attended`, the
board coverage line and the pane account.

WHAT DID NOT MOVE, and why (measured 2026-11-25 with `scripts/check_segmentation.py`). `roles_lines` and the six definitions it
calls that read the journal (`_geos`, `latest_roles_events`, `_sweep_line`, `_board_batches_line`, `_owned_by_lines`, itself) stay in
`run_summary.py`: moved whole, the fourteen of them import `journal` and `linkedin_sweep`, entry points, which a package may not
(G5.L2 +1) and which grew the plugin's largest import cycle from 39 to 40 (G6). The definitions here call nothing but each other.

Python 3.9+, standard library only."""


def _quarantine_clause(e):
    """dev #722 / public #156 -- ` · N quarantined (truncated ×a, filter-dropped ×b)` for a `roles`
    event that held any role, else the empty string. COMPUTED from the event's own counts. An event
    written before 0.69.0 has no `quarantined` field and prints nothing."""
    n = e.get("quarantined", 0)
    if not n:
        return ""
    reasons = e.get("quarantine_reasons") or {}
    why = ", ".join("%s ×%d" % (code, reasons[code]) for code in sorted(reasons))
    return " · %d quarantined%s" % (n, (" (%s)" % why) if why else "")


def _query_reads_line(e, label=None):
    """dev #722 / public #156 (R4) -- how each REACHED query read, from the event's own counts:
    `query reads (board): 12 reached · 10 clean · 1 filters unread · 1 degraded (truncated ×1) · 2
    total unknown`. Empty for an event written before 0.69.0 (no `q_reached`), which is not the
    same as a pass that reached nothing. SHAPE, not enforced: these count what the sweep SAID, so a
    sweep that never looks reads all-clean here, and `check_runs.py` flags a week of that."""
    if "q_reached" not in e:
        return None
    degraded = e.get("q_degraded") or {}
    why = (" (%s)" % ", ".join("%s ×%d" % (c, degraded[c]) for c in sorted(degraded))
           if degraded else "")
    return ("query reads%s: %d reached · %d clean · %d filters unread · %d degraded%s · %d total "
            "unknown" % ((" (%s)" % label) if label else " (wide)", e.get("q_reached", 0),
                         e.get("q_clean", 0), e.get("q_unread", 0), e.get("q_degraded_queries", 0),
                         why, e.get("q_total_unknown", 0)))


def feeds_line(e):
    """dev #751 -- the company-feed line, COMPUTED from a `feeds` event's own counts and never composed:

      feeds: 12 polled · 11 covered (7 unchanged) · NOT COVERED 1 (not-found ×1) · 4 selected -> 1 captured · 1 known · 2 carried · 0 role gaps

    A not-covered count of zero is printed as such and a not-covered feed is NEVER read as "0 roles":
    the failure codes and, when a host was marked down, the host and its code are on the line. An
    event that polled nothing says `0 polled` (no tracked company carries a slug), not silence."""
    if e.get("off"):
        return "feeds: OFF (sourcing.feeds.enabled is false) · nothing polled, no company's feed is covered"
    nc = e.get("not_covered", 0)
    why = e.get("failures") or {}
    line = ("feeds: %d polled · %d covered (%d unchanged) · NOT COVERED %d%s · %d selected -> %d captured "
            "· %d known · %d carried · %d role gap%s"
            % (e.get("polled", 0), e.get("covered", 0), e.get("unchanged", 0), nc,
               (" (%s)" % ", ".join("%s ×%d" % (c, why[c]) for c in sorted(why))) if why else "",
               e.get("selected", 0), e.get("captured", 0), e.get("known", 0), e.get("carried", 0),
               e.get("role_gaps", 0), "" if e.get("role_gaps", 0) == 1 else "s"))
    hosts = e.get("hosts_down") or {}
    if hosts:
        line += " · host down: %s" % ", ".join("%s (%s)" % (h, hosts[h]) for h in sorted(hosts))
    return line


def _plural(n, word, many=None):
    return "%d %s" % (n, word if n == 1 else (many or word + "s"))


def _partial_causes(e):
    """The reasons a `roles` event reads PARTIAL, as short phrases, in a fixed order."""
    out = []
    if e.get("line_faults"):
        out.append(_plural(e["line_faults"], "line fault"))
    unreachable_queries = e.get("queries", 0) - e.get("q_reached", 0)
    if e.get("coverage") == "partial" and unreachable_queries > 0:
        out.append(_plural(unreachable_queries, "query", "queries") + " unreachable")
    return out


def _board_attended(recs, run_id):
    """True when the run's latest board `dispatched` row is an attended one: an attended pass spends
    no scheduled slot, so a 'slot spent' clause would be false."""
    rows = [(str(r.get("at", "")), i, r) for i, r in enumerate(recs)
            if r.get("event") == "pass" and r.get("kind") == "board"
            and r.get("phase") == "dispatched" and r.get("run_id") == run_id]
    return bool(rows) and bool(max(rows, key=lambda t: (t[0], t[1]))[2].get("attended"))


def _board_coverage_line(e, label, tail, attended):
    """The `sourcing (board)` line of a 0.82.0+ event: PARTIAL or complete, then the channel
    accounting, then the existing counts. See the design §6 for the five shapes."""
    partial = e.get("coverage") == "partial"
    worklist, reached = e.get("channels_worklist"), e.get("channels_reached") or 0
    unreachable = e.get("channels_unreachable") or {}
    not_attempted = e.get("channels_not_attempted") or {}
    unaccounted = e.get("channels_unaccounted") or []
    unr = "%s unreachable" % len(unreachable)
    if unreachable:
        unr += " (%s)" % ", ".join("%s %s" % (cid, unreachable[cid]) for cid in sorted(unreachable))
    na = "%d not attempted" % len(not_attempted)
    if not_attempted:
        na += " (%s)" % ", ".join(sorted(set(not_attempted.values())))
    una = "%d unaccounted (%s)" % (len(unaccounted), ", ".join(sorted(unaccounted)))
    causes = _partial_causes(e)
    head = "sourcing (%s): %s" % (label, "PARTIAL" if partial else "complete")
    if worklist is None:
        chan = "channels not checked (no worklist on record)"
    else:
        chan = "%d of %d channels reached" % (reached, worklist)
    if partial and worklist and reached == 0 and not e.get("distinct"):
        # nothing was read: the counts would be a row of zeros. Say what happened, and that the slot
        # is gone (the dispatch row spent it), so the user knows these channels wait.
        parts = [chan] + [x for x, n in ((unr, len(unreachable)), (na, len(not_attempted)),
                                         (una, len(unaccounted))) if n] + causes
        if not attended:
            if e.get("batch") == 0:
                # dev #830: only the script's closing event exists, so NO batch came back and the slot is NOT spent
                # (`posture.board_spent_on`): the next run in the slot dispatches again
                parts.append("no batch came back: the next run in the slot dispatches again")
            else:
                parts.append("slot spent: these channels wait for the next board slot")
        return head + " · " + " · ".join(parts)
    parts = [chan]
    if partial:
        parts += [unr, na]
        if unaccounted:
            parts.append(una)
        parts += causes
    return head + " · " + " · ".join(parts) + " · " + tail


def _pane_account(row):
    """`(partial surfaces, notes)` -- what a `recorded` pass row says about the Browser pane (dev #826 / public #177,
    jobsearch 0.83.0). `partial` is the row's list of surfaces read from a pane that was not painting; `notes` are the
    phrases a summary line carries so a hidden-mode or unreported-pane pass never reads as an ordinary complete one.
    A row written before 0.83.0 carries none of the three fields and yields `([], [])`: its line is unchanged. A
    malformed `partial` (not a list of strings) is ignored here; the writer (`journal.record_pass`) refuses one."""
    raw = row.get("partial")
    partial = [t for t in raw if isinstance(t, str)] if isinstance(raw, list) else []
    notes = []
    if partial:
        notes.append("read from a Browser pane that was not painting: %s" % ", ".join(partial))
    if row.get("mode") == "hidden":
        notes.append("hidden mode")
    if row.get("pane") == "unknown":
        notes.append("Browser pane state unknown")
    elif row.get("pane") == "unreported":
        notes.append("Browser pane state not reported")
    return partial, notes
