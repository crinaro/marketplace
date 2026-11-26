"""search_due: when the LinkedIn job search is due, what a run that did not search says, what one that did search says, and the lines the owner is shown (jobsearch 0.94.0, dev 1065;
docs/design-role-first.md 8.1, 19.5, 19.6; criteria LI1, LI2, WN4, WN5). Capability module of `coordinator.py` and `run_summary.py` (the lines), and of `search_plan` (the refusals).

Everything here is DERIVED from the journal rows `recs` the caller already read, plus two small files (`config.json`, `data/channels.jsonl`); it keeps no state of its own and writes nothing.

  `warning_line`      WN4: `LINKEDIN WARNING <date> (<kind>): scheduled LinkedIn search is OFF. Open LinkedIn yourself and look. To turn it back on: ~/.claude/jobsearch/run journal.py
                      --linkedin-search-on --attended --warning <date>`, while the newest warning has not been turned back on. The FIRST line of the run summary and of the coordinator's start.
  `due_line`          `LINKEDIN JOB SEARCH DUE: last <date>. It needs you in the desktop app: /jobsearch:search linkedin attended. Skip: journal.py --linkedin-search-skip --until <date>`,
                      only when the profile is asked (the source row is present and on, or a search is on record), the search is neither off nor skipped, and scheduled searching cannot
                      do it: the newest search came back `unreachable`, or it is STOPPED, or a warning turned it off, or nothing has searched for twice `every_days`.
  `not_run_reason`    why a run that did not search did not: `off`, `LinkedIn warning (<kind>)`, `stopped`, `skipped by you until <date>`, `not due until <date>`, `no browser`, or
                      the reason its own unreachable search gave (`not-readable`, `sign-in`, `challenge`, `refused`, `linkedin-warning`).
  `not_run_line`      `linkedin job search: NOT RUN (<reason>; last <date>)`. Never zero found.
  `counts_line`       WN5: `20 planned · 18 read · 412 cards · 390 ids · 31 recorded · 4 held · 6 cut short · 3 filters dropped · stopped by none`, the nine counts of a search that ran.
  `search_line`       the summary's line for a run: the counts of the search that ran since the run began, else NOT RUN.
  `start_lines`       the coordinator's start: the warning first, the lines it already prints, the due line, the first five scheduled searches' counts.
  `first_scheduled_lines`  WN5: the counts of the first five scheduled searches, shown at the coordinator's start while the newest of them is under 14 days old.

A profile with no 0.94.0 pin gets NONE of these (RF4): `journaling.pins.pin_missing_line`'s caller decides; every function here that reads a root says so by taking `pinned`.

Python 3.9+, standard library only."""

import datetime
import json
import os

from journaling import search_state as ss
from journaling.journal_file import now_iso, read
from journaling.pins import pin_missing_line
from journaling.tables import JournalError
from searching import query_plan as qp

CHANNEL = "linkedin-jobsearch"
FIRST_SCHEDULED = 5
FIRST_SCHEDULED_DAYS = 14
SKIP_SUGGEST_DAYS = 7
RUN_COMMAND = "~/.claude/jobsearch/run journal.py"
NOT_RUN_NO_BROWSER = "linkedin search not run: no browser"          # the note text `search_plan` writes for the one reason the journal cannot otherwise say


def load_config(root):
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def source_state(root):
    """`on`, `off` or `absent`: the `linkedin-jobsearch` channel row (`retired` is off; no row, or an unreadable store, is `absent`, which is not off)."""
    try:
        with open(os.path.join(root, "data", "channels.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id") == CHANNEL:
                    return "off" if row.get("relationship_status") == "retired" else "on"
    except OSError:
        return "absent"
    return "absent"


def _day(at):
    return str(at or "")[:10]


def _dt(text):
    try:
        return datetime.datetime.fromisoformat(str(text)).replace(tzinfo=None)
    except ValueError:
        return None


def last_label(recs):
    """`<date>`, `<date> (before 0.94.0)` (the newest reached search stored no `pairs`) or `none recorded`."""
    row = ss.last_searched(recs)
    if row is None:
        return "none recorded"
    return _day(row.get("at")) + ("" if row.get("pairs") else " (before 0.94.0)")


def warning_line(recs):
    """WN4: the line shown first, every start and every summary, until the owner turns the search back on; None while no warning stands."""
    off, warn = ss.scheduled_search_off(recs)
    if not off:
        return None
    day = _day(warn.get("at"))
    note = ss.reason_note(warn)         # a layout-ish `unclear` page, or a page that could not be judged, says so in words: never a silent off
    return ("LINKEDIN WARNING %s (%s): scheduled LinkedIn search is OFF. %sOpen LinkedIn yourself and look. To turn it back on: %s --linkedin-search-on --attended --warning %s"
            % (day, ss.kind_label(warn), (note + " ") if note else "", RUN_COMMAND, day))


def not_due(recs, every_days, now):
    """`(date, instant)` while a scheduled search is NOT due at `now`, else None: `instant` the aware UTC `datetime` it is due (`every_days` x 24 ELAPSED hours after the later of the newest
    dispatched search and the newest reached one, `search_state.next_due_utc`), `date` its local calendar date as the summary says it. `now` is an ISO time (naive: this machine's local time)."""
    due, current = ss.next_due_utc(recs, every_days), ss.utc_of({"at": now})
    if due is None or current is None or current >= due:
        return None
    return due.astimezone().date().isoformat(), due


def _asked(root, recs):
    return source_state(root) == "on" or ss.last_searched(recs) is not None


def due_line(root, recs, now):
    """The attended step's due line, or None (see the module docstring). `now` is an ISO time."""
    if source_state(root) == "off" or not _asked(root, recs) or ss.skip_until(recs, now):
        return None
    every_days, _per_pass = qp.settings(load_config(root))
    stopped, _n = ss.scheduled_stopped(recs)
    newest = ss.newest_search_pass(recs)
    last, now_dt = ss.last_searched(recs), _dt(now)
    last_dt = _dt(last.get("at")) if last else None
    stale = last_dt is None or (now_dt is not None and now_dt - last_dt > datetime.timedelta(days=2 * every_days))
    failed = bool(newest and newest.get("jobsearch") == "unreachable")
    if not (failed or stopped or ss.scheduled_search_off(recs)[0] or stale):
        return None
    skip = (now_dt + datetime.timedelta(days=SKIP_SUGGEST_DAYS)).date().isoformat() if now_dt else "YYYY-MM-DD"
    return ("LINKEDIN JOB SEARCH DUE: last %s. It needs you in the desktop app: /jobsearch:search linkedin attended. Skip: journal.py --linkedin-search-skip --until %s"
            % (last_label(recs), skip))


def not_run_reason(root, recs, now, run_ids=()):
    """Why no search ran, first match wins: the channel is off, a warning stands, scheduled searching is stopped, the owner skipped it, a note of one of `run_ids` says `no browser`,
    the newest search came back unreachable (its own reason), else it is not due until a date."""
    if source_state(root) == "off":
        return "off"
    off, warn = ss.scheduled_search_off(recs)
    if off:
        short = ss.reason_short(warn)
        return "LinkedIn warning (%s%s)" % (warn.get("kind"), ("; %s" % short) if short else "")
    if ss.scheduled_stopped(recs)[0]:
        return "stopped"
    until = ss.skip_until(recs, now)
    if until:
        return "skipped by you until %s" % until
    if any(r.get("event") == "note" and r.get("run_id") in run_ids and r.get("text") == NOT_RUN_NO_BROWSER for r in recs):
        return "no browser"
    newest = ss.newest_search_pass(recs)
    if newest and newest.get("jobsearch") == "unreachable" and newest.get("reason"):
        return newest["reason"]
    every_days, _per_pass = qp.settings(load_config(root))
    waiting = not_due(recs, every_days, now)
    if waiting:
        return "not due until %s" % waiting[0]
    return "not started"


def not_run_line(root, recs, now, run_ids=()):
    return "linkedin job search: NOT RUN (%s; last %s)" % (not_run_reason(root, recs, now, run_ids), last_label(recs))


def counts_line(recs, run_id):
    """WN5's nine counts for the search of run `run_id`, from its dispatched row (planned), its latest `roles` event (read, cards, ids, recorded, held, cut short, filters dropped) and its
    returned row (stopped by). None when the run has no search dispatch. A search that ended before it filed a block counts zeros, never a blank."""
    disp = ss.dispatched_search(recs, run_id)
    if disp is None:
        return None
    events = [r for r in recs if isinstance(r, dict) and r.get("event") == "roles" and r.get("run_id") == run_id and r.get("surface") == CHANNEL]
    e = events[-1] if events else {}
    planned = e.get("q_planned") if e.get("q_planned") is not None else sum(1 for p in disp.get("plan") or () if p.get("do"))
    read = max(0, planned - (e.get("q_not_attempted") or 0)) if events else 0
    cards = sum(p.get("shown") or 0 for p in e.get("pairs") or () if p.get("reached"))
    ids = (e.get("links") or {}).get("matched", 0)
    returned = [r for r in recs if r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "returned" and r.get("scope") == "search"
                and r.get("run_id") == run_id]
    stopped_by = (returned[-1].get("reason") or "none") if returned and returned[-1].get("jobsearch") == "unreachable" else "none"
    return ("%d planned · %d read · %d cards · %d ids · %d recorded · %d held · %d cut short · %d filters dropped · stopped by %s"
            % (planned, read, cards, ids, (e.get("captured") or 0) + (e.get("carried") or 0), e.get("quarantined") or 0, e.get("bounded") or 0,
               e.get("query_gaps_filters") or 0, stopped_by))


def search_line(root, recs, now, run_id, run_start):
    """The run summary's line: the counts of the newest search dispatched since `run_start` (this run's own, or the `search` run a daily run started after its reply pass), else NOT RUN.
    A run with no start on record (`run_start` None) counts only a search of its own run id."""
    rows = [r for r in recs if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "dispatched"
            and r.get("scope") == "search" and ((str(r.get("at") or "") >= str(run_start)) if run_start else r.get("run_id") == run_id)]
    if rows:
        line = counts_line(recs, rows[-1].get("run_id"))
        return "linkedin job search: " + line
    return not_run_line(root, recs, now, (run_id,))


def start_lines(root, recs, existing, now=None):
    """The coordinator's start lines: the WN4 warning FIRST, then `existing` (the pipeline's lines and the hidden-pane lines, untouched), then the due line and the first scheduled searches'
    counts. `recs` are the journal rows the caller already read (None: read them here). A profile with no 0.94.0 pin, or a journal that cannot be read, gets `existing` unchanged."""
    existing = list(existing)
    if pin_missing_line(root, "the LinkedIn search lines"):
        return existing
    try:
        recs = read(root) if recs is None else recs
    except JournalError:
        return existing
    now = now or now_iso()
    warning, due = warning_line(recs), due_line(root, recs, now)
    return ([warning] if warning else []) + existing + ([due] if due else []) + first_scheduled_lines(recs, now)


def first_scheduled_lines(recs, now):
    """WN5: `linkedin job search (scheduled <date>): <counts>` for each of the first five scheduled searches on record (oldest first), while the newest of the five is under 14 days old;
    `[]` otherwise. A scheduled search is a `scope: search` dispatch with `attended: false`."""
    rows = [r for r in recs if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "dispatched"
            and r.get("scope") == "search" and r.get("attended") is False]
    first = sorted(rows, key=lambda r: str(r.get("at") or ""))[:FIRST_SCHEDULED]
    now_dt, newest = _dt(now), _dt(first[-1].get("at")) if first else None
    if not first or now_dt is None or newest is None or now_dt - newest > datetime.timedelta(days=FIRST_SCHEDULED_DAYS):
        return []
    return ["linkedin job search (scheduled %s): %s" % (_day(r.get("at")), counts_line(recs, r.get("run_id"))) for r in first]
