"""What the journal says about the LinkedIn job search, folded from its rows (jobsearch 0.94.0, dev 1065; docs/design-role-first.md 8.1,
19.5, 19.6). Pure: every function takes the rows `journal.read` returned and touches no file.

  `newest_warning`          the newest `linkedin-warning` row, or None.
  `scheduled_search_off`    `(off, warning)`: the scheduled search is OFF while a `linkedin-warning` stands after the last VALID `linkedin-search-on` in FILE
                            ORDER (WN3). A turn-on is valid when it is attended, names the date of the newest warning before it, and is not stamped (UTC)
                            before that warning. Nothing else clears it: not a later good search, not time, not an update.
  `search_on_problems`      the `linkedin-search-on` rows that name no matching newest warning. The writer refuses such a row; a hand edit or
                            a merged journal can still carry one, and the reader REPORTS it here instead of raising (a journal that cannot be
                            read protects nothing). `scheduled_search_off` ignores such a row, so it never clears the stop.
  `warning_for_run`         the warning that applies to a run: the newest one APPENDED after the run's `start` row, by ANY run (WN2: a run that began
                            before a warning opens no LinkedIn page after it, whoever recorded it). A run whose start is not on record is treated as
                            started before every warning, the safe direction.
  `last_searched`           the newest `roles` event of the `linkedin-jobsearch` surface with a reached query (design 8.1 "last searched");
                            an event from before 0.94.0 counts.
  `newest_search_pass`      the newest `pass linkedin returned` row with `scope: search`, whose `jobsearch` token says how the search went.
  `dispatched_search`       the newest `pass linkedin dispatched` row with `scope: search` of one run: its `attended` and its stored `plan`.
  `scheduled_stopped`       `(stopped, n)`: scheduled searching is STOPPED after `STOP_AFTER` scheduled searches in a row came back `unreachable` (19.5; a warning is
                            the separate, immediate stop of WN3), until a search that REACHED LinkedIn, attended or scheduled, ends the streak. An attended search
                            that was itself unreachable neither counts nor ends it.
  `skip_until`              the last day of the newest `linkedin-search-skip` still in force on a day, or None.
  `last_dispatched_search`  the newest `pass linkedin dispatched` row with `scope: search` of ANY run: the search's own slot, written before its first page.
  `next_due_utc`            the later of `last_dispatched_search` and `last_searched`, plus `every_days` x 24 hours (the cadence is ELAPSED hours, never a calendar day), or None.
  `reason_note`, `reason_short`   the sentence and the few words a warning's `reason` earns (a layout-ish `unclear` page, a page that could not be judged).

ORDER IS APPEND POSITION, NEVER THE CLOCK (dev 1065, review 2026-11-25). "Newest" is the LAST row in file order: a clock set back, another time zone or a copied profile
stamps a later-appended row EARLIER, and ordering by `at` then ignored a new warning and turned search back on. `at_utc` (an offset-aware stamp, `stamp_utc`) is stored on the
new rows and is used only to refuse a turn-on stamped before its warning and to count the cadence in elapsed hours; it never orders rows.

Capability module of `journal.py`. Python 3.9+, standard library only."""

import datetime

WARNING = "linkedin-warning"
SEARCH_ON = "linkedin-search-on"
SKIP = "linkedin-search-skip"
LAYOUT_REASONS = ("no-cards", "cards-without-text", "no-dismiss", "no-about", "no-main", "shape", "language")          # the judge's words for an `unclear` page that may be LinkedIn's layout, not a warning
UNJUDGED_REASONS = ("tool-error", "empty-result", "unparsable-verdict", "judge-error")      # the page could not be judged at all
LAYOUT_NOTE = "This may be a LinkedIn layout change or a search with no results rather than a warning; it is treated as a warning."
UNJUDGED_NOTE = "The page could not be judged (a tool error or an answer nobody could read), which counts as a warning."
STOP_AFTER = 3                     # scheduled searches in a row that returned `unreachable` (design 19.5)


def stamp_utc(at=None):
    """The offset-aware UTC stamp (`2026-11-26T08:00:00+00:00`) stored as `at_utc`: now when `at` is None, else the naive local `at` converted (a replayed or test time)."""
    d = datetime.datetime.now(datetime.timezone.utc) if at is None else datetime.datetime.fromisoformat(str(at)).astimezone(datetime.timezone.utc)
    return d.replace(microsecond=0).isoformat()


def utc_of(row):
    """The aware UTC `datetime` of a row: its `at_utc` when it has a valid one, else its naive `at` read as machine-local time; None when neither reads."""
    for field in ("at_utc", "at"):
        try:
            d = datetime.datetime.fromisoformat(str(row.get(field)))
        except (TypeError, ValueError):
            continue
        if field == "at_utc" and d.tzinfo is None:
            continue
        return d.astimezone(datetime.timezone.utc)
    return None


def _last(recs, wanted):
    """The LAST row (file order) `wanted` accepts, or None. Position, never the clock."""
    best = None
    for r in recs or ():
        if isinstance(r, dict) and wanted(r):
            best = r
    return best


def _newest(recs, wanted):
    return _last(recs, wanted)


def newest_warning(recs):
    """The newest `linkedin-warning` row in `recs`, or None."""
    return _newest(recs, lambda r: r.get("event") == WARNING)


def reason_note(warn):
    """The sentence a warning's `reason` earns, or "": a layout-ish `unclear` page says it may be a layout change; a page that could not be judged says so. Never silent: the search is off either way."""
    reason = (warn or {}).get("reason")
    return LAYOUT_NOTE if reason in LAYOUT_REASONS else UNJUDGED_NOTE if reason in UNJUDGED_REASONS else ""


def _day(row):
    return str(row.get("at") or "")[:10]


def _stamped_before(on, warn):
    """True when the turn-on `on` is stamped (UTC) before the warning `warn` it names: a clock set back, or a profile copied from another zone. Unreadable stamps are not 'before'."""
    a, b = utc_of(on), utc_of(warn)
    return a is not None and b is not None and a < b


def _valid_on(on, warn):
    return on.get("attended") is True and on.get("warning") == _day(warn) and not _stamped_before(on, warn)


def scheduled_search_off(recs):
    """`(off, warning)`: `off` True and the warning row that stands, else `(False, None)`. Walks the rows in FILE ORDER: a warning turns it off, a VALID `linkedin-search-on`
    (`_valid_on`: attended, naming the date of the newest warning before it, not stamped before it) turns it on, anything else changes nothing. So any warning appended after
    the last valid turn-on means off, whatever either row's clock says."""
    warn, off = None, False
    for r in recs or ():
        if not isinstance(r, dict):
            continue
        if r.get("event") == WARNING:
            warn, off = r, True
        elif r.get("event") == SEARCH_ON and warn is not None and _valid_on(r, warn):
            off = False
    return (True, warn) if off else (False, None)


def search_on_problems(recs):
    """One sentence per `linkedin-search-on` row that names no matching newest warning, in file order: a row with no warning before it, one whose date is not the newest warning's
    at that point, or one stamped (UTC) before that warning."""
    problems, seen = [], []
    for r in recs or ():
        if not isinstance(r, dict):
            continue
        if r.get("event") == WARNING:
            seen.append(r)
        elif r.get("event") == SEARCH_ON:
            newest = newest_warning(seen)
            if newest is None:
                problems.append("linkedin-search-on at %s names the warning of %s, and no linkedin-warning precedes it"
                                % (r.get("at"), r.get("warning")))
            elif r.get("warning") != _day(newest):
                problems.append("linkedin-search-on at %s names the warning of %s, but the newest warning then was of %s"
                                % (r.get("at"), r.get("warning"), _day(newest)))
            elif _stamped_before(r, newest):
                problems.append("linkedin-search-on at %s is stamped before the warning it names (%s): it clears nothing" % (r.get("at"), newest.get("at")))
    return problems


def warning_for_run(recs, run_id):
    """The warning row that applies to run `run_id`, or None: the newest `linkedin-warning`, by ANY run, appended AFTER the run's earliest `start` row. A run that began after the
    newest warning is not affected (the scheduled SEARCH is what stays off, `scheduled_search_off`). A run with no `start` row on record is treated as started before the warning,
    so the newest warning applies. Position in the file decides, never a stamp."""
    last_warning, first_start = None, None
    for i, r in enumerate(recs or ()):
        if not isinstance(r, dict):
            continue
        if r.get("event") == WARNING:
            last_warning = (i, r)
        elif r.get("event") == "start" and r.get("run_id") == run_id and first_start is None:
            first_start = i
    if last_warning is None:
        return None
    return last_warning[1] if first_start is None or last_warning[0] > first_start else None


def last_searched(recs):
    """The newest `roles` event of surface `linkedin-jobsearch` with a reached query (`q_reached` above zero), or None."""
    return _newest(recs, lambda r: r.get("event") == "roles" and r.get("surface") == "linkedin-jobsearch"
                   and isinstance(r.get("q_reached"), int) and r["q_reached"] > 0)


def newest_search_pass(recs):
    """The newest `pass linkedin returned` row carrying `scope: search`, or None."""
    return _newest(recs, lambda r: r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "returned"
                   and r.get("scope") == "search")


def dispatched_search(recs, run_id):
    """The newest `pass linkedin dispatched` row with `scope: search` of run `run_id`, or None."""
    return _newest(recs, lambda r: r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "dispatched"
                   and r.get("scope") == "search" and r.get("run_id") == run_id)


def scheduled_stopped(recs, after=STOP_AFTER):
    """`(stopped, n)`: `n` is the trailing run of scheduled searches that returned `unreachable`, and `stopped` is `n >= after`. A search that returned `reached` (either kind) ends the
    run; an attended search that was not reached, and a `not-attempted` one, change nothing. A returned row whose run has no dispatched row is read as scheduled (the safe direction)."""
    rows = [r for r in recs or () if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin"
            and r.get("phase") == "returned" and r.get("scope") == "search"]
    n = 0
    for r in rows:
        if r.get("jobsearch") == "reached":
            n = 0
        elif r.get("jobsearch") == "unreachable":
            dispatched = dispatched_search(recs, r.get("run_id"))
            if not (dispatched and dispatched.get("attended") is True):
                n += 1
    return n >= after, n


def skip_until(recs, today):
    """The `until` (YYYY-MM-DD) of the newest `linkedin-search-skip` row when it is still in force on `today` (YYYY-MM-DD), else None."""
    row = _newest(recs, lambda r: r.get("event") == SKIP)
    until = str(row.get("until") or "") if row else ""
    return until if until and until >= str(today)[:10] else None


def last_dispatched_search(recs):
    """The newest `pass linkedin dispatched` row with `scope: search`, of ANY run, or None: the search's own slot. `search-plan` writes it before the first page, so a search that
    crashed on its first page still used its slot."""
    return _newest(recs, lambda r: r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "dispatched" and r.get("scope") == "search")


def next_due_utc(recs, every_days):
    """The aware UTC `datetime` a scheduled search is next due: `every_days` x 24 ELAPSED hours after the later of the newest DISPATCHED search (its own slot: a search that crashed on its first
    page still used it) and the newest search that REACHED (`last_searched`, which is all a profile that searched before 0.94.0 has); None when neither is on record. Instants are compared here
    only to measure elapsed time, never to order rows."""
    stamps = [utc_of(r) for r in (last_dispatched_search(recs), last_searched(recs)) if r]
    stamps = [t for t in stamps if t is not None]
    return max(stamps) + datetime.timedelta(hours=24 * every_days) if stamps else None


def kind_label(warn):
    """`<kind>` or `<kind>, reason=<word>`: how a warning is named in the WN4 line, the run summary and the STOP line."""
    reason = (warn or {}).get("reason")
    return "%s, reason=%s" % (warn.get("kind"), reason) if reason else str(warn.get("kind"))


def reason_short(warn):
    """A few words for the one-line summary: the reason word and what it means, or "" when there is no reason."""
    reason = (warn or {}).get("reason")
    if not reason:
        return ""
    meaning = "may be a LinkedIn layout change" if reason in LAYOUT_REASONS else "the page could not be judged" if reason in UNJUDGED_REASONS else ""
    return "reason=%s%s" % (reason, ("; " + meaning) if meaning else "")
