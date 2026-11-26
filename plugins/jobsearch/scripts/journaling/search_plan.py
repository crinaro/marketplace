"""search_plan: `linkedin_sweep.py search-plan`, the gate and the dispatch row of the LinkedIn job search (jobsearch 0.94.0, dev 1065, 1055; docs/design-role-first.md 8.1, 19.5, 19.6;
criteria LI1, LI2, LC3, LC4, WN2, WN3).

  linkedin_sweep.py search-plan (--attended | --scheduled) --browser yes|no --run <id>

THE ONE ENTRY TO A SEARCH. The search is its own dispatch (a `pass linkedin` row with `scope: search`, never a new pass kind). This call decides whether it may run, and when it may, WRITES the
`dispatched` row itself (`attended`, always present, and the stored `plan`), so the row cannot be forgotten and `--add-roles` never recomputes the plan. Nothing here opens a page.

  --attended   a person typed `/jobsearch:search linkedin attended` (PARTIAL: a typed word, as `boards attended`); no quota and no cadence apply
  --scheduled  the scheduled dispatch; refused unless due, not skipped, not off, not stopped, and no warning stands
  --browser    the session's own declaration from its tool list (the `--render-route` precedent: no script can see it); `no` is refused, and says where the step runs

EVERY REFUSAL prints one first line `SEARCH-PLAN REFUSED reason=<word>: <sentence>` and writes nothing (but `no-browser` on a scheduled call, which leaves the note the run summary reads). Exit 3 is a
refusal of a valid call (the run says NOT RUN and goes on); exit 2 is a malformed call:

  usage             both flags, neither, or `--browser` not yes or no (exit 2)
  no-pin            the profile has no 0.94.0 pin: this engine behaves as 0.93.0 did, where the reply pass searched (RF4)
  off               the `linkedin-jobsearch` source is retired
  linkedin-warning  a warning of ANY run stands that was appended after this RUN began (WN2: no LinkedIn page in a run that began before a warning, in any session), or, for `--scheduled`, the scheduled search is off
                    until the owner turns it on (WN3). An attended search in a LATER run is allowed and prints the warning first
  no-browser        `--browser no`
  stopped           `--scheduled`: three scheduled searches in a row came back unreachable (`search_state.scheduled_stopped`)
  skipped           `--scheduled`: the owner skipped it until a date
  not-due           `--scheduled`: under `search.linkedin_search_every_days` x 24 ELAPSED hours (UTC) since the later of the newest search DISPATCHED (its own `dispatched` row, written before
                    its first page, so a search that crashed still used its slot, and two scheduled runs on one day cannot both search) and the newest one that reached
  no-titles         `targets.titles` is empty: there is no query to run

A second call in the same run prints the STORED plan again and writes nothing (the plan is never recomputed after the history moved).

Python 3.9+, standard library only. A package imports no entry point: `linkedin_sweep.py` passes nothing, this module reads the journal itself."""

from journaling import search_state as ss
from journaling.journal_file import append, now_iso, read
from journaling.pins import pin_missing_line
from journaling.role_runs import jobsearch_geos
from journaling.search_pass import record_search_pass
from searching import query_plan as qp
from journaling import search_due as sd

REFUSED = "SEARCH-PLAN REFUSED"
EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
WHERE = "the LinkedIn job search needs the Browser pane of the desktop app: run /jobsearch:search linkedin attended there"


def _refuse(out, reason, sentence, code=EXIT_REFUSED):
    out("%s reason=%s: %s" % (REFUSED, reason, sentence))
    return code


def _print_plan(out, run_id, attended, entries, geos, now):
    w = qp.window(entries, now)
    do = [e for e in entries if e["do"]]
    out("--- SEARCH PLAN v1 run=%s attended=%s ---" % (run_id, "yes" if attended else "no"))
    out("JOBSEARCH window=%s f_TPR=%s titles=%s geo=%s" % (w["window"], w["f_tpr"], w["titles"], ",".join(geos)))
    for e in do:
        out('SEARCH n=%d geo=%s title="%s" last=%s' % (e["n"], e["geo"], str(e["title"]).replace('"', "'"), e["last"]))
    if len(entries) > len(do):
        out("LATER %d more title and place pair(s) wait for a later search, not this one" % (len(entries) - len(do)))
    out("LIMITS first results page of each search only, at most %d searches, one results page open at a time, no page reopened or retried, a warning ends the pass" % len(do))
    out("--- END SEARCH PLAN ---")


def run(root, run_id, attended, scheduled, browser, now=None, out=print):
    """Gate and dispatch. Returns the exit code (see the module docstring); `config.json` is read from `root`."""
    now = now or now_iso()
    cfg = sd.load_config(root)
    if attended == scheduled:
        return _refuse(out, "usage", "give --attended (a person typed the command) or --scheduled (the scheduled dispatch), never both and never neither", EXIT_USAGE)
    if browser not in ("yes", "no"):
        return _refuse(out, "usage", "--browser must be yes or no: your own declaration from your tool list", EXIT_USAGE)
    missing = pin_missing_line(root, "a LinkedIn search dispatch")
    if missing:
        return _refuse(out, "no-pin", missing)
    recs = read(root)
    if sd.source_state(root) == "off":
        return _refuse(out, "off", "the LinkedIn job search is off (record.py source on linkedin-jobs turns it back on)")
    began_before = ss.warning_for_run(recs, run_id)
    if began_before:
        return _refuse(out, "linkedin-warning", "LinkedIn warned at %s (%s) after this run began: this run opens no further LinkedIn page"
                       % (str(began_before.get("at"))[:16], began_before.get("kind")))
    if browser == "no":
        if scheduled:
            _note_no_browser(root, run_id)
        return _refuse(out, "no-browser", WHERE)
    every_days, per_pass = qp.settings(cfg)
    geos = jobsearch_geos(cfg)
    stored = qp.stored_plan(recs, run_id)
    if stored is not None:
        _print_plan(out, run_id, bool(ss.dispatched_search(recs, run_id).get("attended")), stored, geos, now)
        return EXIT_OK
    warning = sd.warning_line(recs)
    if scheduled:
        refusal = _scheduled_refusal(root, recs, cfg, now, warning)
        if refusal:
            return _refuse(out, *refusal)
    elif warning:
        out(warning)
    titles = qp.titles_of(cfg)
    entries = qp.plan(titles, geos, qp.last_reached(recs), every_days, per_pass)
    if not entries:
        return _refuse(out, "no-titles", "targets.titles is empty, so there is no query to run")
    record_search_pass(root, run_id, "linkedin", "dispatched", attended=attended, plan=entries, at=now)
    _print_plan(out, run_id, attended, entries, geos, now)
    return EXIT_OK


def _scheduled_refusal(root, recs, cfg, now, warning):
    """`(reason, sentence)` for the first rule a SCHEDULED search breaks, else None."""
    off, warn = ss.scheduled_search_off(recs)
    if off:
        return "linkedin-warning", warning
    stopped, n = ss.scheduled_stopped(recs)
    if stopped:
        return "stopped", "%d scheduled searches in a row came back unreachable: scheduled searching stays stopped until an attended search reaches LinkedIn" % n
    until = ss.skip_until(recs, now)
    if until:
        return "skipped", "skipped by you until %s" % until
    every_days, _per_pass = qp.settings(cfg)
    waiting = sd.not_due(recs, every_days, now)
    if waiting:
        return "not-due", ("not due until %s (every %d days is %d hours ELAPSED since the last search was dispatched or reached, due %s UTC; last searched %s)"
                           % (waiting[0], every_days, 24 * every_days, waiting[1].strftime("%Y-%m-%d %H:%M"), sd.last_label(recs)))
    return None


def _note_no_browser(root, run_id):
    """The one refusal the journal cannot otherwise say: a scheduled search that had no browser. One note a run."""
    if not any(r.get("event") == "note" and r.get("run_id") == run_id and r.get("text") == sd.NOT_RUN_NO_BROWSER for r in read(root)):
        append(root, {"event": "note", "run_id": run_id, "text": sd.NOT_RUN_NO_BROWSER, "at": now_iso()})
