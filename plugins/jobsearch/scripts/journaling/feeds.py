"""Feed records and the per-company feed state read back from them.

Capability module of `journal.py` (S4a, moved unedited)."""

import datetime
from journaling.journal_file import append, now_iso
from journaling.passes import _check_ids
from journaling.row_shapes import _is_int
from journaling.tables import FEED_BOARD_CODES, FEED_FAILURES, FEED_HOST_CODES, JournalError


def record_feeds(root, run_id, polled, covered, unchanged, not_covered, failures,
                 companies_not_covered, postings, unlisted, selected, captured, known, carried,
                 role_gaps, sightings_added=0, discovered=0, ambiguous=0, quarantined=0,
                 hosts_down=None, at=None, off=False, *, covered_ids=None, attempted_ids=None):
    """dev #751 -- the ONE writer of a `feeds` event: one per `feed_poll.py --run`. Validated at
    write, loud: a row that claims a number it cannot account for never reaches the store.

      polled     = covered + not_covered         (every company the poll was asked about; a company the
                                                  deadline did not reach, or on a host marked down, is
                                                  NOT COVERED, never silently absent)
      unchanged <= covered                       (a 304 counts as covered: nothing changed)
      not_covered = sum(failures.values()) = len(companies_not_covered)
      selected   = captured + known + carried + role_gaps (+ quarantined, asserted 0: a feed is a
                                                  complete listing, so no role is held degraded)

    `failures` is `{code: companies}` over `FEED_FAILURES`; `companies_not_covered` is
    `{company_id: code}` (a dict, not the bare list the design first sketched: `channels_due.py` has
    to tell a BOARD failure from a HOST failure per company, B1); `hosts_down` is `{host: code}`, the
    hosts the poller stopped sending requests to for this run. ⚠️ ROLLBACK RISK, as for `roles`: an
    engine older than 0.72.0 refuses a journal holding a `feeds` row.

    `off=True` (dev #774): the run was asked to poll and `sourcing.feeds.enabled` is false, so NOTHING was polled. The
    row carries `off: true` and every count is 0 -- a switched-off feed is a row that says so, never an absent one,
    so `channels_due.py` cannot read the silence as coverage.

    dev #820 / public #175 (0.82.0, B0.2) -- the keyword-only `covered_ids` is the list of company ids
    this poll COVERED (distinct; as many as `covered`; none of them also in `companies_not_covered`).
    The event stored a count of covered companies and a map of the not-covered ones, so "when was this
    company last covered" had no answer; `feed_last_covered` reads this list to order the next poll's
    rotation and to age a "did not look" row. Omitted from an older event and from `off`.

    dev #832 (public #178, 0.84.0) -- the keyword-only `attempted_ids` is the list of company ids this poll ATTEMPTED:
    at least one request for the company was sent (a covered company is always attempted; a company skipped because
    its host was already down, or reached by the budget before its first request, sent nothing). `feed_last_attempted`
    reads it to order the next poll, so a feed that is reached but can never cover stops heading the order every run.
    Refused when: it is not a list of distinct ids; a covered company is not in it; it names a company the event does
    not account for (neither covered nor not covered); or `off` is set (a switched-off poll attempted nothing)."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_feeds requires run_id")
    counts = dict(polled=polled, covered=covered, unchanged=unchanged, not_covered=not_covered,
                  postings=postings, unlisted=unlisted, selected=selected, captured=captured,
                  known=known, carried=carried, role_gaps=role_gaps, quarantined=quarantined,
                  sightings_added=sightings_added, discovered=discovered, ambiguous=ambiguous)
    for k, v in counts.items():
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise JournalError("record_feeds %s=%r is not a non-negative integer" % (k, v))
    if polled != covered + not_covered:
        raise JournalError("record_feeds: polled=%d but covered+not_covered=%d -- every company "
                           "polled is covered or not covered, never neither"
                           % (polled, covered + not_covered))
    if unchanged > covered:
        raise JournalError("record_feeds: unchanged=%d exceeds covered=%d -- a 304 is a covered "
                           "feed, so it cannot outnumber them" % (unchanged, covered))
    failures = dict(failures or {})
    companies_not_covered = dict(companies_not_covered or {})
    for code, n in failures.items():
        if code not in FEED_FAILURES:
            raise JournalError("record_feeds failure code %r is not in FEED_FAILURES %r"
                               % (code, sorted(FEED_FAILURES)))
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise JournalError("record_feeds failures[%r]=%r is not a non-negative integer"
                               % (code, n))
    for cid, code in companies_not_covered.items():
        if code not in FEED_FAILURES:
            raise JournalError("record_feeds: company %r has failure code %r, not in FEED_FAILURES"
                               % (cid, code))
    if sum(failures.values()) != not_covered or len(companies_not_covered) != not_covered:
        raise JournalError(
            "record_feeds: not_covered=%d but sum(failures)=%d and companies_not_covered=%d -- every "
            "not-covered feed has a code and a name" % (not_covered, sum(failures.values()),
                                                         len(companies_not_covered)))
    by_code = {}
    for code in companies_not_covered.values():
        by_code[code] = by_code.get(code, 0) + 1
    if by_code != {c: n for c, n in failures.items() if n}:
        raise JournalError("record_feeds: failures %r disagrees with the per-company codes %r"
                           % (failures, by_code))
    if quarantined != 0:
        raise JournalError("record_feeds: quarantined=%d but a feed is a complete listing and "
                           "holds no role as degraded (must be 0)" % quarantined)
    if selected != captured + known + carried + role_gaps + quarantined:
        raise JournalError(
            "record_feeds: selected=%d but captured+known+carried+role_gaps=%d -- every selected "
            "posting resolves to exactly one outcome"
            % (selected, captured + known + carried + role_gaps + quarantined))
    hosts_down = dict(hosts_down or {})
    for host, code in hosts_down.items():
        if code not in FEED_HOST_CODES:
            raise JournalError("record_feeds: host %r down with %r, which is not a HOST code %r"
                               % (host, code, FEED_HOST_CODES))
    if covered_ids is not None:
        _check_ids("covered_ids", covered_ids, nonempty=False)
        if len(covered_ids) != covered:
            raise JournalError("record_feeds: covered=%d but covered_ids names %d company(ies)"
                               % (covered, len(covered_ids)))
        both = sorted(set(covered_ids) & set(companies_not_covered))
        if both:
            raise JournalError("record_feeds: %s is both covered and not covered" % ", ".join(both))
    if attempted_ids is not None:
        _check_ids("attempted_ids", attempted_ids, nonempty=False)
        if covered_ids is not None:
            unattempted = sorted(set(covered_ids) - set(attempted_ids))
            if unattempted:
                raise JournalError("record_feeds: %s is covered but not in attempted_ids -- a feed cannot be covered "
                                   "without a request for it having been sent" % ", ".join(unattempted))
            stray = sorted(set(attempted_ids) - (set(covered_ids) | set(companies_not_covered)))
            if stray:
                raise JournalError("record_feeds: attempted_ids names %s, which the event neither covers nor lists "
                                   "as not covered" % ", ".join(stray))
    rec = {"event": "feeds", "run_id": run_id, "polled": polled, "covered": covered,
           "unchanged": unchanged, "not_covered": not_covered,
           "failures": {c: n for c, n in sorted(failures.items()) if n},
           "companies_not_covered": dict(sorted(companies_not_covered.items())),
           "hosts_down": dict(sorted(hosts_down.items())), "postings": postings,
           "unlisted": unlisted, "selected": selected, "captured": captured, "known": known,
           "carried": carried, "role_gaps": role_gaps, "quarantined": quarantined,
           "sightings_added": sightings_added, "discovered": discovered, "ambiguous": ambiguous,
           "at": at}
    if off:
        if any(counts.values()) or failures or companies_not_covered or hosts_down or attempted_ids:
            raise JournalError("record_feeds: off=True but the row claims work was done -- a switched-off feed polls nothing")
        rec["off"] = True
    if covered_ids is not None:
        rec["covered_ids"] = sorted(covered_ids)
    if attempted_ids is not None:
        rec["attempted_ids"] = sorted(attempted_ids)
    return append(root, rec)


def feeds_events(recs, run_id=None, on=None):
    """Every `feeds` event, oldest first; `run_id` narrows to one run, `on` (an ISO date) to the
    events written that day -- how `channels_due.py` reads "this run" without a run id."""
    rows = [r for r in recs if r.get("event") == "feeds"]
    if run_id is not None:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if on is not None:
        rows = [r for r in rows if str(r.get("at") or "")[:10] == str(on)[:10]]
    return sorted(rows, key=lambda r: r.get("at") or "")


def feed_last_covered(recs):
    """`{company_id: 'YYYY-MM-DD'}`: the date of the latest `feeds` event whose `covered_ids` names the
    company. A switched-off event (`off`) covered nothing, and an event written before `covered_ids`
    existed says nothing about who was covered, so neither contributes. `feed_poll.poll` orders its
    companies by this (never-covered first) and `coverage` ages a "did not look" feed row from it."""
    out = {}
    for ev in feeds_events(recs):
        if ev.get("off"):
            continue
        day = str(ev.get("at") or "")[:10]
        for cid in ev.get("covered_ids") or []:
            out[cid] = day
    return out


def feed_last_attempted(recs):
    """`{company_id: ordinal}` (dev #832 / public #178, jobsearch 0.84.0): the 0-BASED position, among the `feeds`
    events in FILE order, of the latest event that ATTEMPTED the company -- the key `feed_poll.rotation_order` sorts on,
    so a company never attempted comes first and then the one attempted longest ago. An ordinal, not a date: two polls
    on one day (a manual rerun) tie on a date and would repeat the same head, while the position in the append-only
    journal is a total order that needs no clock.

    An event that carries `attempted_ids` contributes them. An event written before 0.84.0 has none, so it contributes
    its `covered_ids` (a covered company was necessarily attempted). A switched-off event (`off`) contributes nothing.
    `feed_last_covered` is unchanged: `coverage` still ages a "did not look" row from it."""
    out = {}
    for i, ev in enumerate(r for r in recs if r.get("event") == "feeds"):
        if ev.get("off"):
            continue
        ids = ev["attempted_ids"] if isinstance(ev.get("attempted_ids"), list) else ev.get("covered_ids") or []
        for cid in ids:
            out[cid] = i
    return out


def feed_repeat_failures(recs, code, n):
    """The sorted company ids that were NOT covered with failure `code` in EACH of the latest `n`
    polls (a switched-off event is not a poll). Fewer than `n` polls give `[]`: two failures need
    two polls to have happened. `channels_due` lists these companies DUE for the browser after a
    repeated `budget-exhausted` (n=2), which the host-code rule would otherwise leave on a normal
    cadence forever."""
    if code not in FEED_FAILURES:
        raise JournalError("feed_repeat_failures code %r is not in FEED_FAILURES" % (code,))
    if not _is_int(n, 1):
        raise JournalError("feed_repeat_failures n=%r is not a positive integer" % (n,))
    polls = [e for e in feeds_events(recs) if not e.get("off")]
    if len(polls) < n:
        return []
    sets = [{cid for cid, c in (e.get("companies_not_covered") or {}).items() if c == code}
            for e in polls[-n:]]
    return sorted(set.intersection(*sets))


def feed_board_failure_since(recs, company_id, today=None):
    """The ISO date a company's CURRENT run of consecutive BOARD failures began, or None when its
    latest feed outcome is not a board failure (B1): the streak runs back through `feeds` events
    that name the company with a `FEED_BOARD_CODES` code and stops at the first event that covered
    it, held it to a host/budget code, or did not name it as failed. `channels_due.py` lists a
    channel DUE only while its `last_reviewed` is older than this date, so one browser review ends
    the daily pull instead of every day of a streak repeating it."""
    since = None
    for ev in reversed(feeds_events(recs)):
        code = (ev.get("companies_not_covered") or {}).get(company_id)
        if code in FEED_BOARD_CODES:
            since = str(ev.get("at") or "")[:10]
        else:
            break
    return since


def feed_company_state(recs, company):
    """dev #765 (design B5) -- what the LAST `feeds` event says about ONE company's own feed, as a dict
    `{state, vendor, code, kind, poll, reason}`. It is the one reader `portfolio_boards.py` uses, and it
    exists because the event does not store who was covered: it stores a COUNT of covered companies and a
    map of the NOT-covered ones (`record_feeds`). "Covered" is therefore never read off absence alone. A
    company is covered only when the event could have polled it AND did not list it as failed:

      state          meaning
      no-feed        the company has no `ats` key: browser-routed, no feed to cover
      declined       `ats: null`: the candidate declined a feed
      not-checked    an `ats` feed exists but the last poll proves nothing about it. `reason` says why:
                     no `feeds` event at all · the company is `passed` (never polled) · its `ats.since`
                     is not before the poll's date (attached the day of, or after, the poll: it may not
                     have been in it) · `ats.since` unreadable
      not-covered    the last poll listed it with `code`; `kind` is `board` (this board is wrong:
                     `FEED_BOARD_CODES`) or `host` (the machine or the poll's own budget, not this board)
      covered        polled, and not listed as failed

    The poll used is the LATEST `feeds` event overall, and `poll` is its ISO date, so a stale poll is
    shown with its age rather than hidden. Pure: reads only `recs` and `company`."""
    ats = company.get("ats") if isinstance(company, dict) else None
    out = {"state": None, "vendor": None, "code": None, "kind": None, "poll": None, "reason": None}
    if not isinstance(company, dict) or "ats" not in company:
        out["state"] = "no-feed"
        return out
    if ats is None:
        out["state"] = "declined"
        return out
    out["vendor"] = ats.get("vendor") if isinstance(ats, dict) else None
    events = feeds_events(recs or [])
    if not events:
        out.update(state="not-checked", reason="no feeds event recorded: the feed has not been polled")
        return out
    ev = events[-1]
    poll = str(ev.get("at") or "")[:10]
    out["poll"] = poll or None
    if ev.get("off"):
        # dev #774: a switched-off run lists no company as failed, and "not listed as failed" must NOT read as covered
        out.update(state="not-checked", reason="company feeds are turned off (sourcing.feeds.enabled): the last "
                                                "feeds event, %s, polled nothing" % (poll or "undated"))
        return out
    cid = company.get("id")
    failed = ev.get("companies_not_covered") or {}
    if cid in failed:
        code = failed[cid]
        out.update(state="not-covered", code=code,
                   kind="board" if code in FEED_BOARD_CODES else "host")
        return out
    if company.get("status") == "passed":
        out.update(state="not-checked", reason="the company is passed, so its feed is not polled")
        return out
    since = ats.get("since") if isinstance(ats, dict) else None
    try:
        attached, polled_on = datetime.date.fromisoformat(str(since)), datetime.date.fromisoformat(poll)
    except ValueError:
        out.update(state="not-checked", reason="ats.since %r or the poll date %r is unreadable"
                   % (since, poll))
        return out
    if attached >= polled_on:
        out.update(state="not-checked",
                   reason="the feed was attached %s, not before the last poll (%s), so that poll may "
                          "not have included it" % (attached.isoformat(), poll))
        return out
    out["state"] = "covered"
    return out
