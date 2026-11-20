"""Runs: which started and never ended, run states, open gaps, fired events and one run's events.

Capability module of `journal.py` (S4a, moved unedited)."""

import datetime
from journaling.journal_file import ENGINE_VERSION_RE, append, engine_version, new_run_id, now_iso
from journaling.row_shapes import _check_start_row
from journaling.tables import JournalError


def unfinished(recs):
    """Runs with a start and no end. ⭐ Their notes are the recoverable work.

    ⭐ public #72 — a dead run also carries whether its stranded notes were REVIEWED
    (`dispose`), so `--check` can tell "nobody has looked at this yet" from "looked at, nothing
    to write" instead of flagging both as an unresolved failure forever."""
    started, ended, disposed = {}, set(), {}
    for r in recs:
        if r["event"] == "start":
            started[r["run_id"]] = r
        elif r["event"] == "end":
            ended.add(r["run_id"])
        elif r["event"] == "dispose":
            disposed[r["run_id"]] = r          # last dispose wins if it ever happens twice
    out = []
    for rid, s in started.items():
        if rid in ended:
            continue
        notes = [r for r in recs if r.get("run_id") == rid and r["event"] == "note"]
        gaps = [r for r in recs if r.get("run_id") == rid and r["event"] == "gap"]
        d = disposed.get(rid)
        out.append({"run_id": rid, "at": s.get("at"), "kind": s.get("kind"),
                    "notes": [n.get("text") for n in notes], "gaps": len(gaps),
                    "disposed": bool(d), "disposed_at": d.get("at") if d else None,
                    "disposed_because": d.get("because") if d else None})
    return sorted(out, key=lambda x: x.get("at") or "")


def _parse_at(raw):
    try:
        return datetime.datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def run_states(recs, now, hours):
    """dev #836 (design 9.2): every `start` with no `end`, classified against the liveness window `hours` (a PARAMETER,
    passed by the caller from `config_keys`; this module never imports it). One classifier, lifecycle's own edge:

        `last_at` readable and `last_at >= now - hours`      running
        `last_at < now - hours` (strictly past the window)   died-mid-run
        `last_at` unreadable or no record at all              died-mid-run, `last record time unreadable`

    `last_at` is the run's newest OWN record (`run_events`: never a `fired` record, never a close written on its behalf),
    the rule `lifecycle.Ctx` uses. Each row: {run_id, at, kind, last_at, state, why, start_sha, machine, utc_offset,
    dirty_at_start, notes, gaps, disposed}. Oldest first."""
    horizon = now - datetime.timedelta(hours=hours)
    out = []
    for u in unfinished(recs):
        rid = u["run_id"]
        start = next(r for r in recs if r.get("event") == "start" and r.get("run_id") == rid)
        times = [t for t in (_parse_at(r.get("at")) for r in run_events(recs, rid)) if t is not None]
        last = max(times) if times else None
        if last is None:
            state, why = "died-mid-run", "last record time unreadable"
        elif last < horizon:
            state, why = "died-mid-run", "silent since %s" % last.isoformat()
        else:
            state, why = "running", None
        out.append({"run_id": rid, "at": u["at"], "kind": u["kind"], "last_at": last.isoformat() if last else None,
                    "state": state, "why": why, "start_sha": start.get("start_sha"), "machine": start.get("machine"),
                    "utc_offset": start.get("utc_offset"), "dirty_at_start": start.get("dirty_at_start"),
                    "notes": u["notes"], "gaps": u["gaps"], "disposed": u["disposed"]})
    return out


def open_gaps(recs, run_id=None):
    """Every open (not `gap-closed`) `gap` event, oldest first — journal-wide by default.

    `run_id`, added for design-linkedin-runner-resilience.md §4 (closes D-5's sibling): when
    given, restricts to gaps opened by THAT run. `--end` uses this to report `gaps_open` (this
    run's own count, so a pass that opened nothing ends clean) alongside the unfiltered
    `gaps_open_all` — an older gap standing elsewhere must stay visible, just not blamed on a
    run that never touched it."""
    closed = {r.get("gap_id") for r in recs if r["event"] == "gap-closed"}
    gaps = [r for r in recs if r["event"] == "gap" and r.get("gap_id") not in closed]
    if run_id is not None:
        gaps = [g for g in gaps if g.get("run_id") == run_id]
    return sorted(gaps, key=lambda g: g.get("at") or "")


def split_gaps(gaps):
    """⭐ public #69 — (uncovered, covered). An uncovered gap is unexplained and is what ages
    into `--check`'s stale list; a covered one names the issue that already explains it and is
    reported every run (queryable, never silent) but never chased as if it were new."""
    uncovered = [g for g in gaps if not g.get("covered_by")]
    covered = [g for g in gaps if g.get("covered_by")]
    return uncovered, covered


def fired_events(recs):
    """Every `fired` record — proof a SessionStart hook ran, independent of whether the run's
    own `--start` ever followed it. See the module docstring, public #65."""
    return sorted((r for r in recs if r.get("event") == "fired"), key=lambda r: r.get("at") or "")


def run_events(recs, run_id):
    """dev #820 / public #175 (N1) -- the records that are `run_id`'s OWN: those whose `run_id` field
    names it (`start`, `note`, `gap`, `pass`, `drain`, `roles`, `feeds`, `end`, ...). A `fired` record
    is never anyone's: it carries only a session id and a cwd, and every SessionStart on the machine
    writes one, a compaction or resume of the run's own session included. A close written ON BEHALF of
    a run (`on_behalf_of`) names that run in `run_id` but is the CLOSING run's act, not this run's, so
    it is not counted either: if it were, closing a dead run would make it look alive again.
    `lifecycle` decides a run is over from the latest of these."""
    return [r for r in recs if r.get("run_id") == run_id and r.get("event") != "fired"
            and not r.get("on_behalf_of")]


def record_start(root, kind, at=None, engine=None, start_sha=None, machine=None, dirty_at_start=None,
                 offset=None):
    """dev #820 / public #175 -- the ONE writer of a `start` event. It carries `engine`, the plugin
    version that began the run (read from `plugin.json` when not given), which `lifecycle` reads for the
    cutover (nothing is legacy before the first 0.82.0 start) and for ENGINE SKEW. A missing or
    malformed engine is refused. `start_sha` (dev #703) is omitted when None. Returns the run id."""
    at = at or now_iso()
    if not kind or not isinstance(kind, str):
        raise JournalError("record_start requires a kind")
    engine = engine_version() if engine is None else engine
    if not isinstance(engine, str) or not ENGINE_VERSION_RE.match(engine):
        raise JournalError("record_start engine=%r is not X.Y.Z" % (engine,))
    rid = new_run_id(kind, at)
    rec = {"event": "start", "run_id": rid, "kind": kind, "at": at, "engine": engine}
    if start_sha:
        rec["start_sha"] = start_sha
    if machine:
        rec["machine"] = machine
    if dirty_at_start is not None:
        rec["dirty_at_start"] = dirty_at_start
    if offset:
        rec["utc_offset"] = offset
    _check_start_row(rec)                        # dev #836: a malformed field is refused at the writer, never stored
    append(root, rec)
    return rid
