#!/usr/bin/env python3
"""coverage.py -- "did not look", as one function (dev #813 / public #168; design-role-pipeline.md
section 5, R4, CV1).

Coverage used to reach only `run_summary`. A feed that was never reached, a query that came back
degraded, a channel the pass could not open and a status mail nothing matched were each counted by
the script that noticed it and shown by none of the surfaces that matter. `not_looked(data, now)`
returns every one of them as a row, and `summary(rows)` turns the rows into the counts a surface
prints. `lifecycle.process_report` is the only caller that formats them.

THE ROWS: `{kind, id, cause, since, count, age}`

  kind     id                 source (the run journal, `data["journal"]`)              cause
  -------  -----------------  -------------------------------------------------------  ---------------
  feed     company id         the LATEST `feeds` event's `companies_not_covered`         the feed code
  feed     the run id         a `pass feeds dispatched` row whose run has no `feeds`     not-polled
                              event: the poll was started and never journaled
  query    the surface        the latest `roles` event per surface: each degraded        the code
                              code in `q_degraded`, and `queries - q_reached`            (or surface-unreachable)
  channel  the channel id     that event's `channels_unreachable`,                       the code
                              `channels_not_attempted`, `channels_unaccounted`           (or unaccounted)
  mail     the mailbox        the latest `mail-status` event per mailbox: `unmatched`    unmatched-status-mail

`since` is an ISO date (`YYYY-MM-DD`) and `age` the whole days from it to `now` (calendar days, `now`
passed in, never read from the clock). A feed's `since` is the date it was last covered
(`journal.feed_last_covered`); a feed never covered has the date of the first event that listed it.

THE ONE RULE THIS FILE EXISTS TO KEEP: A POLL THAT NEVER JOURNALED IS NOT THE PREVIOUS POLL. When the
latest `pass feeds dispatched` has no `feeds` event of its own and is newer than the latest `feeds`
event, the rows say `not-polled` and the older event's numbers are NOT reported as current -- a missing
thing must not read as the last thing. A `feeds` event written with `off: true` (the owner switched
company feeds off) polled nothing on purpose and yields no feed rows.

Round 0's `held` kind is withdrawn: a quarantined item is now a role in the lifecycle (waiting or
legacy-backlog), and counting it here would count it twice.

Python 3.9+. Standard library only. Pure: reads only what it is handed.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal as _journal

KINDS = ("feed", "query", "channel", "mail")
NOT_POLLED = "not-polled"
UNMATCHED_STATUS_MAIL = "unmatched-status-mail"


def _day(at):
    s = str(at or "")[:10]
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def _today(now):
    if isinstance(now, datetime.datetime):
        return now.date()
    if isinstance(now, datetime.date):
        return now
    raise ValueError("coverage: `now` must be a date or datetime, got %r" % (now,))


def _row(kind, rid, cause, since, count, today):
    since_d = _day(since) if not isinstance(since, datetime.date) else since
    age = (today - since_d).days if since_d is not None else None
    return {"kind": kind, "id": rid, "cause": cause,
            "since": since_d.isoformat() if since_d is not None else None,
            "count": count, "age": age}


def _recs(data):
    return list((data or {}).get("journal") or [])


def _feed_rows(recs, today):
    events = [r for r in recs if r.get("event") == "feeds"]
    events.sort(key=lambda r: str(r.get("at") or ""))
    dispatched = sorted((r for r in recs if r.get("event") == "pass" and r.get("kind") == "feeds"
                         and r.get("phase") == "dispatched"), key=lambda r: str(r.get("at") or ""))
    have_run = {r.get("run_id") for r in events}
    latest_event = events[-1] if events else None
    unmatched = [d for d in dispatched if d.get("run_id") not in have_run]
    stale = [d for d in unmatched
             if latest_event is None or str(d.get("at") or "") > str(latest_event.get("at") or "")]
    if stale:
        d = stale[-1]
        return [_row("feed", d.get("run_id"), NOT_POLLED, d.get("at"), 1, today)]
    if latest_event is None or latest_event.get("off"):
        return []
    covered_on = _journal.feed_last_covered(recs)
    first_listed = {}
    for ev in events:
        if ev.get("off"):
            continue
        for cid in (ev.get("companies_not_covered") or {}):
            first_listed.setdefault(cid, ev.get("at"))
    rows = []
    for cid, code in sorted((latest_event.get("companies_not_covered") or {}).items()):
        rows.append(_row("feed", cid, code, covered_on.get(cid) or first_listed.get(cid)
                         or latest_event.get("at"), 1, today))
    return rows


def _latest_per(recs, event, key):
    out = {}
    for r in sorted((r for r in recs if r.get("event") == event), key=lambda r: str(r.get("at") or "")):
        out[r.get(key)] = r
    return out


def _roles_rows(recs, today):
    rows = []
    latest = _latest_per(recs, "roles", "surface")
    if "board" in latest and latest["board"].get("run_id"):
        # dev #830 / public #180 (0.84.0): a board run handed out in batches holds one event per batch, so "the latest
        # board event" is the run of that event FOLDED (`journal.board_roles_run`), and the "did not look" rows carry
        # every batch's unreachable and not-attempted channels. A run with no `batch` key folds to its latest event.
        folded = _journal.board_roles_run(recs, latest["board"]["run_id"])
        if folded is not None:
            latest["board"] = folded
    for surface, ev in sorted(latest.items(), key=lambda t: str(t[0])):
        at = ev.get("at")
        for code, n in sorted((ev.get("q_degraded") or {}).items()):
            if n:
                rows.append(_row("query", surface, code, at, n, today))
        unreachable = int(ev.get("queries") or 0) - int(ev.get("q_reached") or 0)
        if unreachable > 0:
            rows.append(_row("query", surface, "surface-unreachable", at, unreachable, today))
        for cid, code in sorted((ev.get("channels_unreachable") or {}).items()):
            rows.append(_row("channel", cid, code, at, 1, today))
        for cid, code in sorted((ev.get("channels_not_attempted") or {}).items()):
            rows.append(_row("channel", cid, code, at, 1, today))
        for cid in sorted(ev.get("channels_unaccounted") or []):
            rows.append(_row("channel", cid, "unaccounted", at, 1, today))
    return rows


def _mail_rows(recs, today):
    rows = []
    for mailbox, ev in sorted(_latest_per(recs, "mail-status", "mailbox").items(),
                              key=lambda t: str(t[0])):
        n = len(ev.get("unmatched") or [])
        if n:
            rows.append(_row("mail", mailbox, UNMATCHED_STATUS_MAIL, ev.get("at"), n, today))
    return rows


def not_looked(data, now):
    """Every place the search did not look, as rows (see the module docstring). `data` is the
    lifecycle snapshot (only `data["journal"]` is read); `now` a date or datetime. Raises `ValueError`
    on a `now` that is neither."""
    today = _today(now)
    recs = _recs(data)
    return _feed_rows(recs, today) + _roles_rows(recs, today) + _mail_rows(recs, today)


def summary(rows):
    """`{kind: (n, oldest_days)}` over `rows`: `n` is the sum of the rows' `count` (51 feeds are 51,
    two degraded queries on one surface are 2) and `oldest_days` the greatest `age`, or None when no
    row of that kind could be dated. A kind with no row is absent -- never a zero."""
    out = {}
    for r in rows:
        n, oldest = out.get(r["kind"], (0, None))
        n += int(r.get("count") or 0)
        age = r.get("age")
        if age is not None and (oldest is None or age > oldest):
            oldest = age
        out[r["kind"]] = (n, oldest)
    return out


def describe(rows):
    """The one text for a coverage summary: `feeds 51 (oldest 6d), queries 2`, or `` when there is
    none. The plural names are the surfaces' own words."""
    names = {"feed": "feeds", "query": "queries", "channel": "channels", "mail": "mail"}
    parts = []
    s = summary(rows)
    for kind in KINDS:
        if kind in s:
            n, oldest = s[kind]
            parts.append("%s %d%s" % (names[kind], n, " (oldest %dd)" % oldest if oldest else ""))
    return ", ".join(parts)
