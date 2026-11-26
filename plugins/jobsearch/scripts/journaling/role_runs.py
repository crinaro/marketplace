"""Role passes: recording roles, coverage of the channel map, what is missing, and closing the board loop. (The LinkedIn search's
window is `searching/query_plan.py`'s since 0.94.0, dev 1055.)

Capability module of `journal.py` (S4a, moved unedited)."""

import re
from journaling.board_runs import board_batches
from journaling.journal_file import append, now_iso, read
from journaling.passes import _check_ids, _is_count, record_pass
from journaling.pins import require_pin
from journaling.search_rows import check_roles_new_fields
from journaling.tables import (
    F_TPR_BUCKETS,
    F_TPR_DAILY,             # re-exported by journal.py (`deferred.add_roles` reads `journal.F_TPR_WIDE`)
    F_TPR_WIDE,
    JournalError,
    REASONS,
    ROLES_COVERAGE,
    ROLES_SURFACES,
    ROLES_WINDOWS,
)


def record_roles(root, run_id, surface, window, f_tpr, queries, geos_ok, query_gaps_window,
                 query_gaps_truncated, distinct, captured, known, carried, role_gaps, at=None,
                 quarantined=0, quarantine_reasons=None, query_gaps_filters=0,
                 captured_degraded=0, q_reached=0, q_clean=0, q_unread=0, q_total_unknown=0,
                 q_degraded=None, q_degraded_queries=0, *, coverage=None, line_faults=None,
                 channels_worklist=None, channels_reached=None, channels_unreachable=None,
                 channels_not_attempted=None, channels_unaccounted=None, batch=None,
                 channels_reached_ids=None, pairs=None, q_planned=None, q_not_attempted=None, bounded=None, links=None,
                 pane=None, mode=None):
    """dev #692 / public #140 -- the ONE writer of a `roles` event: one per ACCEPTED `ROLES v1`
    block (`deferred.add_roles`). Validated at write, loud: an unknown surface or window, a
    bucket outside `F_TPR_BUCKETS`, a negative count, or an identity that does not hold
    (`distinct = captured + known + carried + quarantined + role_gaps`, dev #722 / public #156) is
    refused, so a row that claims a number it cannot account for never reaches the store. `f_tpr`
    is None for the board.
    The two query-gap counts are SEPARATE fields on purpose: a per-query gap (a window not
    applied, a query unreachable, a result truncated) moves what a wide re-scan may claim, a
    per-role gap (a URL that could not be exposed) moves conservation, and one must never hide
    the other.

    ⭐ dev #722 / public #156 -- the QUARANTINE and READ counts. `quarantined` (roles held because
    every query that showed them reported a degradation) is a term of the identity;
    `quarantine_reasons` is `{code: roles}` over `deferred.DEGRADED_CODES` (a role with two codes
    counts once under each). The query-read counts (R4) say how each REACHED query read, and are a
    partition: `q_reached = q_clean + q_unread + q_degraded_queries`, refused when it does not hold;
    `q_total_unknown` is counted apart (it can sit under any of the three) and `q_degraded` is
    `{code: queries}`. They are the sweep's SELF-REPORT (SHAPE, not enforced): they make a sweep
    that never looks countable (`check_runs.py`), they cannot prove it looked. An event written
    before 0.69.0 lacks every one of these fields and readers use `.get(k, 0)`.

    ⭐ dev #811 / public #170 + dev #812 / public #169 (design §6, 0.82.0) -- PARTIAL versus COMPLETE.
    The keyword-only `coverage` (`complete` | `partial`) and its accounting are written together or
    not at all (an event from before 0.82.0 has none, and readers treat the absence as "not
    recorded"): `line_faults` (an int, REQUIRED with `coverage`); `channels_worklist` (the board
    worklist's size, or None when none is on record); `channels_reached` (an int, or None);
    `channels_unreachable` and `channels_not_attempted` (each `{channel_id: REASONS code}`);
    `channels_unaccounted` (a list of ids). The channel fields are null or empty off the board.
    THE IDENTITY, refused when it breaks (the `feeds` event's own discipline): `coverage` is
    `partial` EXACTLY when `line_faults > 0`, or any QUERY was unreachable (`queries - q_reached > 0`:
    every QUERY line is reached or unreachable, so the difference is the unreachable count), or any
    channel map or list is non-empty. A truncated or filter-degraded query DID produce a recorded
    subset, keeps its own fields, and does not by itself make a pass partial.

    dev #830 / public #180 (0.84.0) -- the keyword-only `batch` (an int >= 0; board only) says which batch of the board
    loop the event was written from (`0` is the script's closing event), and `channels_reached_ids` (a list of distinct
    channel ids; board only) names the channels whose QUERY lines were reached, so the next batch order can put the
    longest-unattempted first. Both are additive: an event without them is today's (`batch` key None).

    dev 1055, 1064, 1065 (0.94.0; design-role-first.md 0, 5, 7.4, 8) -- seven optional keyword fields of a `linkedin-jobsearch` event:
    `pairs`, `q_planned`, `q_not_attempted` (above zero makes the pass `partial`: a term of the coverage identity), `bounded`, `links`,
    `pane` and `mode`. Not `queries`, which stays the integer count. Checked by `search_rows.check_roles_new_fields`, the reader's check,
    and written only on a profile pinned at 0.94.0 (`pins.require_pin`)."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_roles requires run_id")
    if surface not in ROLES_SURFACES:
        raise JournalError("record_roles surface %r is not in %r" % (surface, ROLES_SURFACES))
    if window not in ROLES_WINDOWS:
        raise JournalError("record_roles window %r is not in %r" % (window, ROLES_WINDOWS))
    if f_tpr is not None and f_tpr not in F_TPR_BUCKETS:
        raise JournalError("record_roles f_tpr %r is not one of LinkedIn's UI buckets %r "
                           "(R5: no computed window)" % (f_tpr, F_TPR_BUCKETS))
    counts = {"queries": queries, "query_gaps_window": query_gaps_window,
              "query_gaps_truncated": query_gaps_truncated, "distinct": distinct,
              "captured": captured, "known": known, "carried": carried,
              "role_gaps": role_gaps, "quarantined": quarantined,
              "query_gaps_filters": query_gaps_filters, "captured_degraded": captured_degraded,
              "q_reached": q_reached, "q_clean": q_clean, "q_unread": q_unread,
              "q_total_unknown": q_total_unknown, "q_degraded_queries": q_degraded_queries}
    for k, v in counts.items():
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise JournalError("record_roles %s=%r is not a non-negative integer" % (k, v))
    accounted = captured + known + carried + quarantined + role_gaps
    if distinct != accounted:
        raise JournalError(
            "record_roles: distinct=%d but captured+known+carried+quarantined+role_gaps=%d -- a "
            "pass's roles are all accounted for or the event is not written"
            % (distinct, accounted))
    quarantine_reasons = dict(quarantine_reasons or {})
    q_degraded = dict(q_degraded or {})
    for name, table in (("quarantine_reasons", quarantine_reasons), ("q_degraded", q_degraded)):
        for code, n in table.items():
            if not isinstance(n, int) or isinstance(n, bool) or n < 0:
                raise JournalError("record_roles %s[%r]=%r is not a non-negative integer"
                                   % (name, code, n))
    if q_reached != q_clean + q_unread + q_degraded_queries:
        raise JournalError(
            "record_roles: q_reached=%d but q_clean+q_unread+q_degraded_queries=%d -- every "
            "reached query reads as exactly one of clean, unread or degraded"
            % (q_reached, q_clean + q_unread + q_degraded_queries))
    rec = {"event": "roles", "run_id": run_id, "surface": surface, "window": window,
           "f_tpr": f_tpr, "queries": queries, "geos_ok": sorted(set(geos_ok or [])),
           "query_gaps_window": query_gaps_window, "query_gaps_truncated": query_gaps_truncated,
           "distinct": distinct, "captured": captured, "known": known, "carried": carried,
           "role_gaps": role_gaps, "quarantined": quarantined,
           "quarantine_reasons": quarantine_reasons, "query_gaps_filters": query_gaps_filters,
           "captured_degraded": captured_degraded, "q_reached": q_reached, "q_clean": q_clean,
           "q_unread": q_unread, "q_total_unknown": q_total_unknown, "q_degraded": q_degraded,
           "q_degraded_queries": q_degraded_queries, "at": at}
    rec.update(_roles_coverage(surface, queries, q_reached, coverage, line_faults, channels_worklist,
                               channels_reached, channels_unreachable, channels_not_attempted,
                               channels_unaccounted, q_not_attempted or 0))
    if batch is not None:
        if surface != "board" or not _is_count(batch):
            raise JournalError("record_roles batch=%r is a non-negative integer for surface 'board' only (got "
                               "surface=%r)" % (batch, surface))
        rec["batch"] = batch
    if channels_reached_ids is not None:
        if surface != "board":
            raise JournalError("record_roles: channels_reached_ids is for surface 'board' only")
        _check_ids("channels_reached_ids", channels_reached_ids, nonempty=False)
        rec["channels_reached_ids"] = sorted(channels_reached_ids)
    new = {k: v for k, v in dict(pairs=pairs, q_planned=q_planned, q_not_attempted=q_not_attempted, bounded=bounded, links=links,
                                 pane=pane, mode=mode).items() if v is not None}
    if new:
        require_pin(root, "a `roles` event's %s" % ", ".join(sorted(new)))
        rec.update(new)
        check_roles_new_fields(rec)
    return append(root, rec)


def _check_channel_map(label, table):
    if not isinstance(table, dict):
        raise JournalError("record_roles %s=%r is not a {channel_id: REASONS code} map"
                           % (label, table))
    for cid, code in table.items():
        if not isinstance(cid, str) or not cid or re.search(r"\s", cid):
            raise JournalError("record_roles %s has the channel id %r (a non-empty string without "
                               "whitespace)" % (label, cid))
        if code not in REASONS:
            raise JournalError("record_roles %s[%r]=%r is not a REASONS code" % (label, cid, code))


def _roles_coverage(surface, queries, q_reached, coverage, line_faults, worklist, reached,
                    unreachable, not_attempted, unaccounted, q_not_attempted=0):
    """The `coverage` half of `record_roles`: validate it, and return the fields to store ({} when
    `coverage` is not given -- and then none of the others may be). See `record_roles`."""
    given = dict(line_faults=line_faults, channels_worklist=worklist, channels_reached=reached,
                 channels_unreachable=unreachable, channels_not_attempted=not_attempted,
                 channels_unaccounted=unaccounted)
    if coverage is None:
        extra = sorted(k for k, v in given.items() if v is not None)
        if extra:
            raise JournalError("record_roles: %s need coverage= (they are written together)"
                               % ", ".join(extra))
        return {}
    if coverage not in ROLES_COVERAGE:
        raise JournalError("record_roles coverage=%r is not one of %r" % (coverage, ROLES_COVERAGE))
    if not _is_count(line_faults):
        raise JournalError("record_roles line_faults=%r is not a non-negative integer "
                           "(required with coverage)" % (line_faults,))
    for label, v in (("channels_worklist", worklist), ("channels_reached", reached)):
        if v is not None and not _is_count(v):
            raise JournalError("record_roles %s=%r is neither None nor a non-negative integer"
                               % (label, v))
    unreachable = {} if unreachable is None else unreachable
    not_attempted = {} if not_attempted is None else not_attempted
    unaccounted = [] if unaccounted is None else unaccounted
    _check_channel_map("channels_unreachable", unreachable)
    _check_channel_map("channels_not_attempted", not_attempted)
    if (not isinstance(unaccounted, (list, tuple)) or any(not isinstance(c, str) or not c or re.search(r"\s", c) for c in unaccounted)
            or len(set(unaccounted)) != len(unaccounted)):
        raise JournalError("record_roles channels_unaccounted=%r is not a list of distinct channel "
                           "ids" % (unaccounted,))
    if surface != "board" and (worklist is not None or reached or unreachable or not_attempted
                               or unaccounted):
        raise JournalError("record_roles: the channel fields are for surface 'board' only (got "
                           "surface=%r)" % surface)
    query_unreachable = queries - q_reached
    if query_unreachable < 0:
        raise JournalError("record_roles: q_reached=%d exceeds queries=%d" % (q_reached, queries))
    partial = bool(line_faults > 0 or query_unreachable > 0 or unreachable or not_attempted
                   or unaccounted or q_not_attempted > 0)
    if (coverage == "partial") != partial:
        raise JournalError(
            "record_roles: coverage=%r but line_faults=%d, unreachable queries=%d (queries - "
            "q_reached), channels_unreachable=%d, channels_not_attempted=%d, "
            "channels_unaccounted=%d, q_not_attempted=%d -- a pass is partial exactly when any of them is non-zero"
            % (coverage, line_faults, query_unreachable, len(unreachable), len(not_attempted),
               len(unaccounted), q_not_attempted))
    return {"coverage": coverage, "line_faults": line_faults, "channels_worklist": worklist,
            "channels_reached": reached, "channels_unreachable": dict(unreachable),
            "channels_not_attempted": dict(not_attempted), "channels_unaccounted": list(unaccounted)}


def roles_events(recs, run_id=None, surface=None):
    rows = [r for r in recs if r.get("event") == "roles"]
    if run_id is not None:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if surface is not None:
        rows = [r for r in rows if r.get("surface") == surface]
    return rows


def roles_missing(recs, run_id):
    """dev #692 / public #140 (N5, R3, R4) -> the surfaces whose pass RETURNED in this run with
    no accepted `roles` event, in `ROLES_SURFACES` order.

    * `linkedin-jobsearch`: a LinkedIn `pass … returned` row whose explicit `jobsearch` token reads
      `reached` (R4). `unreachable` and `not-attempted` do not trip it: no search ran. A returned
      row that carries NO token is not guessed at (an old row, or a caller that did not report):
      it trips nothing, and daily-run is told to always pass one.
    * `board`: a `pass` row of kind `board`, phase `dispatched` or `returned`, written by the
      dispatching script (R3) -- never a folded `dispatch` row (`--fold-dispatches` reads a
      transcript, which is model-dependent; a fact a run knows goes into a script-written row).
      A `refused` board pass trips nothing."""
    have = {r.get("surface") for r in roles_events(recs, run_id=run_id)}
    passes = [r for r in recs if r.get("event") == "pass" and r.get("run_id") == run_id]
    missing = []
    if (any(r.get("kind") == "linkedin" and r.get("phase") == "returned"
            and r.get("jobsearch") == "reached" for r in passes)
            and "linkedin-jobsearch" not in have):
        missing.append("linkedin-jobsearch")
    if any(r.get("kind") == "board" and r.get("phase") in ("dispatched", "returned") for r in passes):
        # dev #830 / public #180: a run that handed its worklist out in batches owes ONE block per batch, so each
        # open batch is `board:b<n>` (its gap is `jobsearch:roles:board:b<n>`); a run with no batch row owes the one
        # `board` block, as before. The closing `batch: 0` event accounts for no batch, so it never hides an open one.
        b = board_batches(recs, run_id)
        if b is not None and b["batches"]:
            missing.extend("board:b%d" % n for n in b["open_batches"])
        elif "board" not in have:
            missing.append("board")
    return missing


def close_board_loop(root, run_id, at=None):
    """dev #830 / public #180 (design §2.4.4, round-2 M1) -- close a board batch loop the run left open. Returns the
    text it printed, or None when there was nothing to close. Written by `journal --end` (a script, once, at the end of
    the run); `run_summary` and `check_runs` read an open loop themselves, so nothing relies on this having run.

    A run with at least one `batch` row and no `batch-end` row is closed in one of two ways:
      * every id of the worklist WAS handed out (the model went from the last hand-back straight to the summary without
        the extra call that would have printed `done`): write `batch-end state=done` and NOTHING else. A closing `roles`
        event with no id to account for would be refused (`partial` with nothing partial), and no sweep was abandoned.
        A batch with no hand-back is still reported by `roles_missing` as `board:b<n>`.
      * ids were never handed out: write `batch-end state=abandoned code=run-ended` and ONE closing `roles` event
        (`batch=0`, `partial`, each unhanded id `not-attempted reason=run-ended`).
    Idempotent: a run that already has a `batch-end` row writes nothing."""
    recs = read(root)
    b = board_batches(recs, run_id)
    if b is None or not b["batches"] or b["terminal"] is not None:
        return None
    at = at or now_iso()
    if not b["unhanded"]:
        record_pass(root, run_id, "board", "batch-end", at=at, state="done", handed=len(b["handed"]),
                    worklist=len(b["worklist"]))
        return "BOARD BATCHES %d of %d (every channel handed out)" % (len(b["batches"]), b["of"])
    record_pass(root, run_id, "board", "batch-end", at=at, state="abandoned", code="run-ended",
                handed=len(b["handed"]), worklist=len(b["worklist"]))
    record_closing_roles(root, run_id, b["unhanded"], "run-ended", len(b["worklist"]), at=at)
    return ("BOARD BATCHES LEFT OPEN %d of %d: %d ids never handed"
            % (len(b["batches"]), b["of"], len(b["unhanded"])))


def record_closing_roles(root, run_id, remaining, code, worklist_size, at=None):
    """The script's closing board `roles` event (`batch=0`): every id in `remaining` recorded `not-attempted` under
    `code` (`run-budget`, `run-ended`, `browser-unavailable`, `route-refused`). `queries=0`, `coverage="partial"`,
    `channels_worklist` the whole worklist's size. Written through `record_roles`, the writer `deferred.add_roles`
    uses, so it holds every identity that one does. `remaining` must be non-empty (an empty one would be a `partial`
    event with nothing partial, and `record_roles` refuses it)."""
    return record_roles(root, run_id, "board", "none", None, 0, [], 0, 0, 0, 0, 0, 0, 0, at=at, coverage="partial",
                        line_faults=0, channels_worklist=worklist_size, channels_reached=0,
                        channels_unreachable={}, channels_not_attempted={c: code for c in remaining},
                        channels_unaccounted=[], batch=0)


def jobsearch_geos(cfg):
    """The geographies a LinkedIn search covers, computed from config -- never self-reported by
    the runner: `remote` always, plus `local` when `geography.commute_anchors` is non-empty."""
    anchors = ((cfg or {}).get("geography") or {}).get("commute_anchors") or []
    return ["remote", "local"] if anchors else ["remote"]
