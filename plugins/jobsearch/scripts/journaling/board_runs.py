"""Board worklists and batches within one run.

Capability module of `journal.py` (S4a, moved unedited)."""

from journaling.passes import _check_channels
from journaling.tables import JournalError


def _latest_dispatched(recs, run_id):
    """`(index, row)` of the run's LATEST board `dispatched` row (by `at`, ties by file order), or None."""
    rows = [(i, r) for i, r in enumerate(recs)
            if r.get("event") == "pass" and r.get("kind") == "board"
            and r.get("phase") == "dispatched" and r.get("run_id") == run_id]
    if not rows:
        return None
    return max(rows, key=lambda t: (str(t[1].get("at", "")), t[0]))


def board_worklist_dispatched(recs, run_id):
    """dev #811 / public #170 (design §5.3) -- the combined worklist of the run's LATEST board
    `dispatched` row (by `at`, ties by file order), as a list of channel ids. `None` when the run
    has no such row, or the latest one lacks the field (written before 0.82.0): "no worklist on
    record" is a state the caller prints as NOT CHECKED, never an empty worklist. A repeated
    `--board-decision` in one run therefore supersedes the earlier call. Raises `JournalError` on a
    `channels` value that is present and unreadable (a hand-edited journal). (Until 0.84.0 this was `board_worklist`;
    `channels_due.py --board-batch` reads the whole worklist through it.)"""
    got = _latest_dispatched(recs, run_id)
    if got is None:
        return None
    latest = got[1]
    if "channels" not in latest:
        return None
    channels = latest["channels"]
    try:
        _check_channels(channels)
    except JournalError as e:
        raise JournalError("the board dispatched row of run %r carries an unreadable worklist: %s"
                           % (run_id, e))
    return list(channels)


def _batch_rows(recs, run_id):
    """`(batch rows, batch-end rows)` of the run written AFTER its latest board `dispatched` row, in file order."""
    got = _latest_dispatched(recs, run_id)
    if got is None:
        return [], []
    after = [r for i, r in enumerate(recs) if i > got[0] and r.get("event") == "pass"
             and r.get("kind") == "board" and r.get("run_id") == run_id]
    return ([r for r in after if r.get("phase") == "batch"], [r for r in after if r.get("phase") == "batch-end"])


def board_batch_current(recs, run_id):
    """dev #830 / public #180 -- `(n, channels)` of the run's latest board `batch` row written after its latest
    `dispatched` row, or None when the run has none (the attended path, a 0.83.0-shaped run, or a run whose loop never
    started). `deferred.add_roles` reads it to know which batch a hand-back belongs to."""
    batches, _ends = _batch_rows(recs, run_id)
    if not batches:
        return None
    last = max(batches, key=lambda r: r.get("batch", 0))
    return last.get("batch"), list(last.get("channels") or [])


def board_worklist(recs, run_id):
    """The ids a board hand-back is checked against: the run's latest `batch` row's `channels` when the run has a batch
    row after its latest `dispatched` row (dev #830 / public #180, 0.84.0), otherwise the `dispatched` row's whole
    worklist exactly as before (`board_worklist_dispatched`). `None` = no worklist on record (NOT CHECKED)."""
    cur = board_batch_current(recs, run_id)
    if cur is not None:
        return cur[1]
    return board_worklist_dispatched(recs, run_id)


def board_batches(recs, run_id):
    """dev #830 / public #180 (design §2.4.4) -- the board loop of one run, as a dict, or None when the run has no
    board `dispatched` row:

      worklist       the `dispatched` row's channels (``[]`` when it carries none)
      batches        ``[(n, channels)]`` in batch order
      of             the planned batch count the last `batch` row stated (0 with no batch)
      handed         the ids of every batch, in hand-out order
      unhanded       worklist ids no batch handed out
      open_batches   batch numbers with no board `roles` event carrying that `batch` (a sweeper that crashed, or a
                     hand-back never added)
      terminal       the run's latest `batch-end` row, or None
    """
    got = _latest_dispatched(recs, run_id)
    if got is None:
        return None
    batches, ends = _batch_rows(recs, run_id)
    wl = got[1].get("channels") if isinstance(got[1].get("channels"), list) else []
    ordered = sorted(batches, key=lambda r: r.get("batch", 0))
    handed = []
    for r in ordered:
        for c in r.get("channels") or []:
            if c not in handed:
                handed.append(c)
    have = {e.get("batch") for e in recs if e.get("event") == "roles" and e.get("surface") == "board"
            and e.get("run_id") == run_id}
    return {"worklist": list(wl), "batches": [(r.get("batch"), list(r.get("channels") or [])) for r in ordered],
            "of": max([r.get("of", 0) for r in ordered] or [0]), "handed": handed,
            "unhanded": [c for c in wl if c not in set(handed)],
            "open_batches": [r.get("batch") for r in ordered if r.get("batch") not in have],
            "terminal": ends[-1] if ends else None}


_ROLES_SUM_FIELDS = ("queries", "query_gaps_window", "query_gaps_truncated", "distinct", "captured", "known", "carried",
                     "role_gaps", "quarantined", "query_gaps_filters", "captured_degraded", "q_reached", "q_clean",
                     "q_unread", "q_total_unknown", "q_degraded_queries", "line_faults", "channels_reached")


def board_roles_run(recs, run_id):
    """dev #830 / public #180 (design §2.4.3) -- THE ONE FOLD of a run's board `roles` events, or None when it has
    none. Every reader of the board's coverage (run_summary, coverage, check_runs, add_roles) reads the run through it.

    A board event written from a batch carries `batch: n` (>= 1); the script's closing event (budget spent, a pass-wide
    stop, a loop left open) carries `batch: 0`; an event with no `batch` key (written before 0.84.0, or on the attended
    path) belongs to key None. (1) The run's events are grouped by `(window, batch)` and the LATEST of each group kept
    (by `at`, ties by file order), so a corrected re-submission still supersedes within ONE batch. (2) The kept events are
    folded: counters are summed, per-code maps (`q_degraded`, `quarantine_reasons`) summed per code, channel maps
    unioned, lists concatenated, `geos_ok` unioned, `channels_worklist` is the dispatched worklist's own length.
    (3) `coverage` is `partial` when any kept event is, when `board_batches` has unhanded ids or an open batch, or when
    the terminal state is not `done`. A role listed on two channels in two batches is counted twice in `distinct`
    (named, accepted: `captured` and `known` are resolved per role). A run whose events all lack `batch` returns its
    latest event UNCHANGED, which is today's latest-wins."""
    evs = [(i, e) for i, e in enumerate(recs) if e.get("event") == "roles" and e.get("surface") == "board"
           and e.get("run_id") == run_id]
    if not evs:
        return None
    best = {}
    for i, e in evs:
        key = (e.get("window"), e.get("batch"))
        rank = (str(e.get("at", "")), i)
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, e)
    kept = [e for _rank, e in sorted(best.values(), key=lambda t: t[0])]
    if all(e.get("batch") is None for e in kept):
        return kept[-1]
    out = dict(kept[-1])
    for f in _ROLES_SUM_FIELDS:
        out[f] = sum(int(e.get(f) or 0) for e in kept)
    for f in ("q_degraded", "quarantine_reasons"):
        m = {}
        for e in kept:
            for code, n in (e.get(f) or {}).items():
                m[code] = m.get(code, 0) + n
        out[f] = m
    for f in ("channels_unreachable", "channels_not_attempted"):
        m = {}
        for e in kept:
            m.update(e.get(f) or {})
        out[f] = m
    for f in ("channels_unaccounted", "channels_reached_ids"):
        out[f] = [c for e in kept for c in (e.get(f) or [])]
    out["batch"] = max(int(e.get("batch") or 0) for e in kept)       # 0 only when NO batch returned (closing event alone)
    out["geos_ok"] = sorted({g for e in kept for g in (e.get("geos_ok") or [])})
    out["at"] = max(str(e.get("at", "")) for e in kept)
    b = board_batches(recs, run_id)
    partial = any(e.get("coverage") == "partial" for e in kept)
    if b is not None:
        out["channels_worklist"] = len(b["worklist"]) or out["channels_worklist"]
        term = b["terminal"]
        partial = partial or bool(b["unhanded"]) or bool(b["open_batches"]) or (
            term is not None and term.get("state") != "done")
    out["coverage"] = "partial" if partial else "complete"
    return out
