#!/usr/bin/env python3
"""Employer-posting confirmation: the field's parser, its state machine, its label, and the zero-token
re-check (dev #776 / public #166; docs/design-employer-posting-confirmation.md, section 15 BINDING).

    posting_check.py --run <run_id> [--dry-run] [--today YYYY-MM-DD]

⭐ WHAT THIS MODULE IS. One optional object on a role, `opportunities[].employer_posting`, says whether
the role was SEEN on the employer's own posting, with the URL, the dates and the quoted evidence. This
file is every pure rule about that object, in one place, so no other script re-derives one:

    parse(value)            the STRICT parser (C2). Refuses what it cannot read; an absent field reads
                            as unconfirmed and never checked (C3, criterion M: no migration).
    observe(reading, obs, today)
                            the state machine T1-T10 (design 4.2): observations go in, the new value
                            comes out. A negative about a role nothing confirmed is REFUSED.
    closed_by(signals)      the two-signal rule as a predicate (L2): two distinct classes within
                            PAIR_WINDOW_DAYS, one of them a browser render. One failed fetch never
                            marks a role dead.
    due / live_pending      L3: a role not re-checked within RECHECK_DAYS is never reported live.
    label(opp, today)       the ONE label every surface renders, derived ONLY from the field (S3): prose,
                            a research log line and the look cache are never read.
    in_watch_list(opp, triage_missing)
                            which roles are re-checked (pursue, plus triaged decide-state roles). The
                            triage result is an ARGUMENT, so this module imports neither `your_move`
                            nor `validate_data` (N8: no import cycle; a test imports each alone).
    employer_owned / capture_confirms
                            is this URL the employer's own (C4): decided from the company's `ats`, its
                            career host and the channel `type` + `company_id` link, never a name match.
    parse_line / format_line
                            the EMPLOYER-POSTING line grammar the researcher and Step B hand back. Lines
                            travel in a FILE, never on argv (N1), so quoted text round-trips byte for byte.
    queue_order / top_up    which roles go to the browser queue, at most BROWSER_CHECKS_PER_RUN pending.
    robots_verdict          RFC 9309 section 2.3.1: a 4xx robots.txt means allowed, a 5xx or a network
                            failure means disallowed for this run (N5).

⭐ STEP A (`--run`). Zero tokens. For each role on the watch list that was not checked or looked at
today: (1) the feed signal from feed_poll's cache, no network; (2) for a confirmed role still due, ONE
GET of the stored employer URL after robots.txt, 1 s apart per host; (3) inside FETCH_DEADLINE_S; then it
tops up the `posting-check` browser queue. Every observation is written through
`record.py posting --from-file <file> --today <date>` (a subprocess that takes the lock itself), never
by this module. A fetch that is not a clear answer (no JobPosting, a 200 shell, an off-host redirect, a
timeout, a 5xx, a robots refusal) is INCONCLUSIVE: nothing is stored, `checked_on` does not move, and a
look is noted in `.jobsearch/posting_looks.json`.

⭐ A GREEN RUN IS NEVER AN EMPTY ONE (N13). The summary line leads with `examined N of W in watch list`,
and `examined + skipped today + unreadable + deadline = W` always holds. If W is 0 while roles carry the
verdict `pursue` and a live status, the run prints `POSTING CHECK NOT RUN` and exits 3: a watch list that
scans nothing must not print a clean line.

⭐ A DATE SEAM (N10). `--today YYYY-MM-DD` on `--run` is TEST-ONLY: it lets the dated rows run end to end
without waiting a week. It is passed through to the `record.py posting` subprocess. Production never
passes it.

⭐ WHAT THIS DOES NOT CLAIM. A `via render` observation and its quote are a MODEL ATTESTATION: no script
sees a render, and `closed_by` cannot tell a real render from a fetch labelled as one. The quote makes an
accident visible; it does not prevent dishonesty (design 11).

Exit codes: 0 ran clean; 4 ran with a refused write or a queue shortfall (stated); 3 not run.

Python 3.9+. Standard library only. Network only through `feed_poll.default_fetch`.
"""

import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ats_slug

# ---- constants (OURS, named; asserted by TestConstants) ------------------------------------------------
RECHECK_DAYS = 7                     # a role not checked within a week reads NOT CHECKED
PAIR_WINDOW_DAYS = 14                # two re-check periods: an older negative no longer "agrees"
BROWSER_CHECKS_PER_RUN = 5           # the most posting-check items pending at once
UNCONFIRMED_SHARE = 2                # the unconfirmed class's slice of those 5 while confirmed roles wait
FETCH_DEADLINE_S = 90                # Step A's network phase, inside its own 300 s Bash call
FEED_ABSENT_VENDORS = ("lever", "ashby")   # vendors whose list is DOCUMENTED as published-only
PATH_TENANT_HOSTS = ("jobs.smartrecruiters.com", "apply.workable.com", "boards.greenhouse.io",
                     "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com")

STATES = ("confirmed", "unconfirmed", "closed")
VIAS = ("feed", "fetch", "render")
EVIDENCE_MAX = 200
SIGNAL_CLASS = {"feed-absent": "feed", "http-404": "http", "http-410": "http",
                "valid-through-past": "markup", "render-unavailable": "render"}


def terminal_statuses():
    """`validate_data.TERMINAL_OPP_STATUSES`, the ONE terminal vocabulary (test_validate_data
    `test_no_script_carries_a_private_terminal_literal` refuses a private copy). Imported on first use,
    inside this function, so that importing this module pulls in neither `validate_data` nor `your_move`
    (N8: no import cycle at load time)."""
    import validate_data
    return validate_data.TERMINAL_OPP_STATUSES


# the look cache's outcome codes; a BROWSER look (a refusal or a failed render) holds a role out of the queue for
# the rest of the day, a fetch look (`inconclusive-*`) does not: the browser is exactly the remedy for it
LOOK_RE = re.compile(r"^(?:inconclusive-[a-z0-9][a-z0-9-]*|refused-not-owned|site-not-allowed|render-failed)$")
BROWSER_LOOKS = frozenset({"refused-not-owned", "site-not-allowed", "render-failed"})
LOOKED_CODES = {"site-not-allowed": "site-not-allowed", "render-failed": "render-failed",
                "inconclusive": "inconclusive-line"}

_ALL_KEYS = frozenset(("state", "checked_on", "url", "confirmed_on", "via", "evidence", "pending",
                       "closed_on", "signals"))
_KEYS_BY_STATE = {
    "unconfirmed": frozenset(("state", "checked_on")),
    "confirmed": frozenset(("state", "checked_on", "url", "confirmed_on", "via", "evidence", "pending")),
    "closed": frozenset(("state", "checked_on", "url", "confirmed_on", "via", "evidence", "closed_on",
                         "signals")),
}
_SIGNAL_KEYS = frozenset(("signal", "on", "evidence"))


class PostingFieldError(ValueError):
    """`parse` refused a stored value. `reason` is the one-sentence why."""

    def __init__(self, reason):
        ValueError.__init__(self, reason)
        self.reason = reason


class PostingLineError(ValueError):
    """`parse_line` refused a line outside the EMPLOYER-POSTING grammar."""

    def __init__(self, reason):
        ValueError.__init__(self, reason)
        self.reason = reason


class ObservationRefused(ValueError):
    """`observe` refused an observation the state machine does not allow (T3, T7, T8)."""

    def __init__(self, reason):
        ValueError.__init__(self, reason)
        self.reason = reason


# ---- dates: independent of the interpreter (N11) --------------------------------------------------------

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _real_date(v):
    """True for a `YYYY-MM-DD` string that is a real calendar date. The SHAPE is checked first, so
    `20261102` and `2026-W44-1` are refused on every Python: `date.fromisoformat` accepts both on 3.11 and
    later, and a parser that leaned on it would read a different set of values on 3.9 (N11). Same contract
    as `validate_data._real_date`, copied here so this module imports neither of its consumers (N8)."""
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return False
    try:
        datetime.date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except ValueError:
        return False
    return True


def _date(v):
    return datetime.date(int(v[0:4]), int(v[5:7]), int(v[8:10]))


def _need_date(v, what):
    if not _real_date(v):
        raise ValueError("%s %r is not a real YYYY-MM-DD date" % (what, v))
    return _date(v)


def _days_between(later, earlier):
    return (_date(later) - _date(earlier)).days


# ---- the reading ------------------------------------------------------------------------------------------

Reading = collections.namedtuple(
    "Reading", "state checked_on url confirmed_on via evidence pending closed_on signals")
_ABSENT = Reading("unconfirmed", None, None, None, None, None, (), None, ())


def _valid_url(u):
    if not isinstance(u, str) or not u or re.search(r"\s", u) or len(u) > 2000:
        return False
    try:
        parts = urllib.parse.urlsplit(u)
        return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


def _check_evidence(ev, where):
    if not isinstance(ev, str) or not (1 <= len(ev) <= EVIDENCE_MAX):
        raise PostingFieldError("%s evidence must be a string of 1 to %d characters" % (where, EVIDENCE_MAX))
    if re.search(r"[\x00-\x08\x0a-\x1f\x7f]", ev):
        raise PostingFieldError("%s evidence carries a control character" % where)


def _check_signal(entry, where):
    if not isinstance(entry, dict):
        raise PostingFieldError("%s is not an object" % where)
    extra = sorted(str(k) for k in entry if k not in _SIGNAL_KEYS)
    if extra:
        raise PostingFieldError("%s carries an unknown key %s" % (where, extra[0]))
    sig = entry.get("signal")
    if sig not in SIGNAL_CLASS:
        raise PostingFieldError("%s has an unknown signal %r" % (where, sig))
    if not _real_date(entry.get("on")):
        raise PostingFieldError("%s date %r is not a real YYYY-MM-DD date" % (where, entry.get("on")))
    if "evidence" in entry:
        _check_evidence(entry["evidence"], where)
    if sig == "render-unavailable" and "evidence" not in entry:
        raise PostingFieldError("%s render-unavailable needs the quoted visible text" % where)


def closed_by(signals):
    """The two-signal rule as a predicate (L2). True iff there are at least TWO DISTINCT CLASSES among the
    signals, ONE CLASS IS `render`, and every signal falls within PAIR_WINDOW_DAYS of the newest one. A
    list that cannot be read is False, never True.

    Consequences: one failed fetch never marks a role dead (it makes one `http` or `markup` signal); a feed
    absence plus a 404 are still no render; two renders on different days are ONE class."""
    if not isinstance(signals, (list, tuple)) or not signals:
        return False
    classes, dates = set(), []
    for s in signals:
        if not isinstance(s, dict) or s.get("signal") not in SIGNAL_CLASS or not _real_date(s.get("on")):
            return False
        classes.add(SIGNAL_CLASS[s["signal"]])
        dates.append(_date(s["on"]))
    if len(classes) < 2 or "render" not in classes:
        return False
    newest = max(dates)
    return all((newest - d).days <= PAIR_WINDOW_DAYS for d in dates)


def parse(value):
    """The STRICT parser (C2). `parse(None)` is the unconfirmed, never-checked reading (C3). Raises
    `PostingFieldError(reason)` for: a non-object or an unknown key; a `state` outside the set; a key that
    is not legal on that state (an `unconfirmed` value carrying `url`, `pending` off a `confirmed` value,
    `signals`/`closed_on` off a `closed` one); a `confirmed`/`closed` value missing `url`, `confirmed_on` or
    `via`, or missing `evidence` when `via` is not `feed` (and carrying it when it is); any date that is not
    a real `YYYY-MM-DD` (N11); `confirmed_on` after `checked_on`; two `pending` entries of one class; an
    unknown signal; a `render-unavailable` with no quote; a `closed` value whose signals fail `closed_by`."""
    if value is None:
        return _ABSENT
    if not isinstance(value, dict):
        raise PostingFieldError("employer_posting is not an object")
    unknown = sorted(str(k) for k in value if k not in _ALL_KEYS)
    if unknown:
        raise PostingFieldError("unknown key %s" % unknown[0])
    state = value.get("state")
    if state not in STATES:
        raise PostingFieldError("state %r is not one of %s" % (state, "/".join(STATES)))
    for k in sorted(value):
        if k not in _KEYS_BY_STATE[state]:
            raise PostingFieldError("%s is not legal on a value whose state is %s" % (k, state))
    if not _real_date(value.get("checked_on")):
        raise PostingFieldError("checked_on %r is not a real YYYY-MM-DD date" % (value.get("checked_on"),))
    if state == "unconfirmed":
        return Reading("unconfirmed", value["checked_on"], None, None, None, None, (), None, ())
    for k in ("url", "confirmed_on", "via"):
        if k not in value:
            raise PostingFieldError("a %s value needs %s" % (state, k))
    if not _valid_url(value["url"]):
        raise PostingFieldError("url %r is not an http(s) URL with a host" % (value["url"],))
    if not _real_date(value["confirmed_on"]):
        raise PostingFieldError("confirmed_on %r is not a real YYYY-MM-DD date" % (value["confirmed_on"],))
    if value["confirmed_on"] > value["checked_on"]:
        raise PostingFieldError("confirmed_on %s is after checked_on %s" % (value["confirmed_on"],
                                                                            value["checked_on"]))
    via = value["via"]
    if via not in VIAS:
        raise PostingFieldError("via %r is not one of %s" % (via, "/".join(VIAS)))
    if via == "feed":
        if "evidence" in value:
            raise PostingFieldError("evidence must be absent when via is feed")
    else:
        if "evidence" not in value:
            raise PostingFieldError("a via %s value needs the quoted evidence" % via)
        _check_evidence(value["evidence"], "the")
    pending, closed_on, signals = [], None, []
    if state == "confirmed" and "pending" in value:
        pend = value["pending"]
        if not isinstance(pend, list) or not pend:
            raise PostingFieldError("pending must be a non-empty list when present")
        seen = set()
        for i, e in enumerate(pend):
            _check_signal(e, "pending[%d]" % i)
            cls = SIGNAL_CLASS[e["signal"]]
            if cls in seen:
                raise PostingFieldError("pending carries two %s signals (one per class)" % cls)
            seen.add(cls)
        pending = [dict(e) for e in pend]
    if state == "closed":
        if "closed_on" not in value or "signals" not in value:
            raise PostingFieldError("a closed value needs closed_on and signals")
        if not _real_date(value["closed_on"]):
            raise PostingFieldError("closed_on %r is not a real YYYY-MM-DD date" % (value["closed_on"],))
        sigs = value["signals"]
        if not isinstance(sigs, list) or not sigs:
            raise PostingFieldError("signals must be a non-empty list")
        for i, e in enumerate(sigs):
            _check_signal(e, "signals[%d]" % i)
        if not closed_by(sigs):
            raise PostingFieldError("the closed signals do not satisfy the two-signal rule "
                                    "(two classes within %d days, one a render)" % PAIR_WINDOW_DAYS)
        closed_on, signals = value["closed_on"], [dict(e) for e in sigs]
    return Reading(state, value["checked_on"], value["url"], value["confirmed_on"], via,
                   value.get("evidence"), tuple(pending), closed_on, tuple(signals))


def to_value(reading):
    """The stored dict of a Reading, keys with no value omitted. The inverse of `parse` for a stored value."""
    if reading.checked_on is None:
        return None
    v = {"state": reading.state, "checked_on": reading.checked_on}
    if reading.state == "unconfirmed":
        return v
    v.update({"url": reading.url, "confirmed_on": reading.confirmed_on, "via": reading.via})
    if reading.evidence is not None:
        v["evidence"] = reading.evidence
    if reading.state == "confirmed" and reading.pending:
        v["pending"] = [dict(e) for e in reading.pending]
    if reading.state == "closed":
        v["closed_on"] = reading.closed_on
        v["signals"] = [dict(e) for e in reading.signals]
    return v


def _as_reading(x):
    return x if isinstance(x, Reading) else parse(x)


# ---- observations and the state machine ----------------------------------------------------------------

Observation = collections.namedtuple("Observation", "kind url via signal evidence")


def live(url, via, evidence=None):
    return Observation("live", url, via, None, evidence)


def negative(url, signal, evidence=None):
    return Observation("negative", url, None, signal, evidence)


def not_found():
    return Observation("not-found", None, None, None, None)


def looked(url, outcome):
    return Observation("looked", url, None, outcome, None)


def _canon(url):
    """The canonical form of a posting URL (`pipeline_index.canonical_job_url`), else the stripped string.
    Imported on first use so importing this module pulls nothing in (N8)."""
    try:
        import pipeline_index
    except ImportError:
        return (url or "").strip()
    return pipeline_index.canonical_job_url(url) or (url or "").strip()


def same_url(a, b):
    return bool(a) and bool(b) and _canon(a) == _canon(b)


def observe(reading, obs, today):
    """The state machine (design 4.2). `reading` is a Reading (or a stored value, parsed here), `obs` an
    Observation, `today` an ISO date. Returns the NEW stored value (a dict). Raises `ObservationRefused` for
    T3 (a negative about a role nothing confirmed), T7 (a negative on another URL), T8 (a confirmed
    posting that cannot be found: that is a negative with a render, so the evidence is quoted) and for a
    `looked` line, which is not an observation. The result is re-parsed before it is returned, so this
    function can never emit a value `parse` would refuse."""
    r = _as_reading(reading)
    _need_date(today, "today")
    kind = obs.kind
    if kind == "looked":
        raise ObservationRefused("a looked line is not an observation; it never changes the field")
    if kind == "live":
        if not _valid_url(obs.url):
            raise ObservationRefused("live needs an http(s) URL with a host")
        if obs.via not in VIAS:
            raise ObservationRefused("live needs via feed, fetch or render")
        if obs.via == "feed":
            if obs.evidence is not None:
                raise ObservationRefused("a feed observation carries no evidence")
        else:
            try:
                _check_evidence(obs.evidence, "the")
            except PostingFieldError as e:
                raise ObservationRefused("live via %s needs quoted evidence: %s" % (obs.via, e.reason))
        if r.state in ("confirmed", "closed") and same_url(r.url, obs.url):
            confirmed_on = r.confirmed_on                     # T4, and T9 on the same URL
        else:
            confirmed_on = today                              # T1, T5, T9 on a new URL
        new = {"state": "confirmed", "url": obs.url, "confirmed_on": confirmed_on, "checked_on": today,
               "via": obs.via}
        if obs.via != "feed":
            new["evidence"] = obs.evidence
    elif kind == "not-found":
        if r.state == "unconfirmed":
            new = {"state": "unconfirmed", "checked_on": today}           # T2
        elif r.state == "confirmed":
            raise ObservationRefused("a confirmed posting that cannot be found is a negative with a render "
                                     "(render-unavailable and its quoted text), not a not-found (T8)")
        else:
            raise ObservationRefused("a closed posting takes a live or a negative observation, not a "
                                     "not-found")
    elif kind == "negative":
        if obs.signal not in SIGNAL_CLASS:
            raise ObservationRefused("unknown signal %r" % (obs.signal,))
        if obs.signal == "render-unavailable":
            try:
                _check_evidence(obs.evidence, "render-unavailable")
            except PostingFieldError as e:
                raise ObservationRefused("render-unavailable needs the quoted visible text: %s" % e.reason)
        elif obs.evidence is not None:
            try:
                _check_evidence(obs.evidence, "the")
            except PostingFieldError as e:
                raise ObservationRefused(e.reason)
        if r.state == "unconfirmed":
            raise ObservationRefused("nothing is confirmed, so nothing can be dead (T3)")
        if not same_url(r.url, obs.url):
            raise ObservationRefused("a negative is about the stored posting only: %s is not %s (T7)"
                                     % (obs.url, r.url))
        if r.state == "closed":
            new = to_value(r._replace(checked_on=today))                   # T10
        else:                                                              # T6
            entry = {"signal": obs.signal, "on": today}
            if obs.evidence is not None:
                entry["evidence"] = obs.evidence
            cls = SIGNAL_CLASS[obs.signal]
            kept = [dict(e) for e in r.pending
                    if _days_between(today, e["on"]) <= PAIR_WINDOW_DAYS and SIGNAL_CLASS[e["signal"]] != cls]
            pend = kept + [entry]
            new = to_value(r._replace(checked_on=today, pending=()))
            if closed_by(pend):
                new["state"] = "closed"
                new["closed_on"] = today
                new["signals"] = pend
            else:
                new["pending"] = pend
    else:
        raise ObservationRefused("unknown observation kind %r" % (kind,))
    try:
        parse(new)
    except PostingFieldError as e:                                          # a defect here is ours, loudly
        raise ObservationRefused("internal: observe produced an unreadable value (%s)" % e.reason)
    return new


# ---- due, stale pending, the label (L3, S3) -------------------------------------------------------------

def due(reading, today):
    """True when `checked_on` is None or more than RECHECK_DAYS days old. Day 7 after a check is not due,
    day 8 is. A role that is due is never reported live."""
    r = _as_reading(reading)
    _need_date(today, "today")
    return r.checked_on is None or _days_between(today, r.checked_on) > RECHECK_DAYS


def live_pending(reading, today):
    """The `pending` entries no older than PAIR_WINDOW_DAYS on `today`. `label` reads ONLY these, so an old
    entry stops saying 'awaiting a second' when its window passes even though it stays stored."""
    r = _as_reading(reading)
    _need_date(today, "today")
    return [dict(e) for e in r.pending if _days_between(today, e["on"]) <= PAIR_WINDOW_DAYS]


# the label codes in their total order (design 8.1); the FIRST row that matches wins
LABEL_ORDER = ("unreadable", "never", "closed", "unconfirmed", "not-checked", "one-signal", "live")


def label(opp, today):
    """`(code, text)` for a role, from the FIELD ONLY (S3): `research_log`, `note`, every other prose field
    and the look cache are never read. The first matching row, top to bottom:

        unreadable   the stored value fails `parse`
        never        the field is absent
        closed       state closed
        unconfirmed  state unconfirmed (due: NOT CHECKED since <date> is appended)
        not-checked  confirmed and due
        one-signal   confirmed with a live pending entry (two non-render entries read 'Closed signals ...')
        live         confirmed otherwise

    Every code except `live` is a flag. The text carries its own checked date (L3 holds at render time)."""
    raw = opp.get("employer_posting") if isinstance(opp, dict) else None
    try:
        r = parse(raw)
    except PostingFieldError as e:
        return "unreadable", "POSTING FIELD UNREADABLE: %s" % e.reason
    if raw is None:
        return "never", "Unconfirmed: not checked on the employer's own posting"
    if r.state == "closed":
        return "closed", "CLOSED on employer posting %s (%s)" % (
            r.closed_on, " + ".join(s["signal"] for s in r.signals))
    stale = due(r, today)
    if r.state == "unconfirmed":
        text = "Not found on the employer's own posting (looked %s)" % r.checked_on
        if stale:
            text += " · NOT CHECKED since %s" % r.checked_on
        return "unconfirmed", text
    if stale:
        return "not-checked", "NOT CHECKED since %s" % r.checked_on
    lp = live_pending(r, today)
    if len(lp) == 1:
        return "one-signal", "One closed signal (%s, %s), awaiting a second" % (lp[0]["signal"], lp[0]["on"])
    if lp:
        return "one-signal", "Closed signals (%s), awaiting a browser render" % "; ".join(
            "%s, %s" % (e["signal"], e["on"]) for e in lp)
    return "live", "Live on employer posting · checked %s" % r.checked_on


def is_flag(code):
    """Every label code except `live` is a flag on the pursue surfaces."""
    return code != "live"


# ---- the watch list ---------------------------------------------------------------------------------------

def in_watch_list(opp, triage_missing):
    """Which roles are re-checked, defined once. A role is on the list when either holds:

      pursue   `verdict == "pursue"` and the status is not passed or expired;
      decide   `status == "backlog"`, `verdict == "undecided"` and the triage gate is empty.

    `triage_missing` is the RESULT of `your_move.triage_missing(opp)` (a list), passed in by the caller:
    this module imports neither `your_move` nor `validate_data` (N8). It is consulted only for a
    backlog+undecided role, where `None` is a ValueError: an unknown triage result must never be read as
    'triaged' or as 'not triaged'. A `triaging` role is not on the list (research reads it first)."""
    if not isinstance(opp, dict):
        return False
    status, verdict = opp.get("status"), opp.get("verdict")
    if verdict == "pursue" and status not in terminal_statuses():
        return True
    if status == "backlog" and verdict == "undecided":
        if triage_missing is None:
            raise ValueError("in_watch_list needs the triage result for a backlog undecided role (%s)"
                             % opp.get("id"))
        return len(triage_missing) == 0
    return False


# ---- ownership: is this URL the employer's own posting? (C4) ------------------------------------------------

def _host(url):
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _first_segment(url):
    try:
        segs = [s for s in urllib.parse.urlsplit(url).path.split("/") if s]
    except ValueError:
        return ""
    return segs[0].lower() if segs else ""


def _channel_urls(channel):
    """The page URLs a company-site channel row carries. Channels declare no URL key today (docs/schema.md);
    `url` and `board_url` are read when present and nothing is invented when they are not."""
    return [u for u in (channel.get("url"), channel.get("board_url")) if isinstance(u, str) and u.strip()]


def _ats_matches(url, ats):
    """Rule (a): `ats_slug.parse` reads the URL to the SAME board the company's `ats` object names."""
    if not isinstance(ats, dict):
        return False
    hit = ats_slug.parse(url)
    if hit is None:
        return False
    vendor, key, region = hit
    if vendor != ats.get("vendor"):
        return False
    if key != ats_slug.board_key(ats):
        return False
    return vendor != "lever" or region == ats.get("region")


def employer_owned(url, company, channels):
    """`(owned, basis)` -- is `url` the employer's own posting? Rule (a): `ats_slug` parses it to the board
    the company's `ats` names. Rule (b): its host equals the host of `companies[].career_url`, or of the page
    URL of the company-site channel linked by `company_id`; case-insensitive, one leading `www.` stripped;
    for a host in PATH_TENANT_HOSTS (a shared host that names the employer in the path) the first path
    segment must match too. `basis` is a dict `{"rule": "a"|"b"|None, "ats": "<vendor:key>"|None, "host":
    "<host>"|None}` that a refusal can print. A staffing agency's own board (a different slug, tenant or
    host) never passes. Vendors outside these rules are UNDETERMINED (design 2)."""
    company = company if isinstance(company, dict) else {}
    ats = company.get("ats")
    ats_name = None
    if isinstance(ats, dict):
        ats_name = "%s:%s" % (ats.get("vendor"), ats_slug.board_key(ats))
    refs = []
    if isinstance(company.get("career_url"), str) and company["career_url"].strip():
        refs.append(company["career_url"])
    for ch in channels or ():
        if isinstance(ch, dict) and ch.get("type") == "company-site" and company.get("id") \
                and ch.get("company_id") == company.get("id"):
            refs.extend(_channel_urls(ch))
    host = _host(url) if isinstance(url, str) else ""
    basis = {"rule": None, "ats": ats_name, "host": (_host(refs[0]) or None) if refs else None}
    if not _valid_url(url):
        return False, basis
    if _ats_matches(url, ats):
        return True, {"rule": "a", "ats": ats_name, "host": host}
    for ref in refs:
        if _host(ref) != host:
            continue
        if host in PATH_TENANT_HOSTS:
            seg = _first_segment(ref)
            if not seg or seg != _first_segment(url):
                continue
        return True, {"rule": "b", "ats": ats_name, "host": host}
    return False, basis


def capture_confirms(sighting, channels, opp):
    """C4: does a sighting confirm a role at capture? ONLY when its `channel_id` resolves to a channel of
    `type: company-site` whose `company_id` is the role's `company_id`. An `aggregator` or `job-board`
    channel never confirms, whatever host its `source_url` points at: the decision is made from data the
    store already holds, never from a name or a host match."""
    if not isinstance(sighting, dict) or not isinstance(opp, dict):
        return False
    cid, company = sighting.get("channel_id"), opp.get("company_id")
    if not cid or not company:
        return False
    for ch in channels or ():
        if isinstance(ch, dict) and ch.get("id") == cid:
            return ch.get("type") == "company-site" and ch.get("company_id") == company
    return False


# ---- the line grammar (N1: lines travel in a FILE, never on argv) ------------------------------------------

_ID = r"([A-Za-z0-9][A-Za-z0-9._-]{0,80})"
_SIGS = "|".join(sorted(re.escape(s) for s in SIGNAL_CLASS))
_LINE_LIVE_FEED = re.compile(r"^EMPLOYER-POSTING " + _ID + r" live (\S+) via feed$")
_LINE_LIVE_Q = re.compile(r'^EMPLOYER-POSTING ' + _ID + r' live (\S+) via (fetch|render) "(.*)"$')
_LINE_NEG = re.compile(r'^EMPLOYER-POSTING ' + _ID + r' negative (\S+) (' + _SIGS + r')(?: "(.*)")?$')
_LINE_NEG_SITE = re.compile(r"^EMPLOYER-POSTING " + _ID + r" negative (\S+) render-unavailable site-not-allowed$")
_LINE_NOTFOUND = re.compile(r"^EMPLOYER-POSTING " + _ID + r" not-found$")
_LINE_LOOKED = re.compile(r"^EMPLOYER-POSTING " + _ID + r" looked (\S+) (site-not-allowed|render-failed|inconclusive)$")


def parse_line(line):
    """`(opp_id, Observation)` from ONE EMPLOYER-POSTING line, strictly:

        EMPLOYER-POSTING <opp_id> live <url> via feed
        EMPLOYER-POSTING <opp_id> live <url> via fetch|render "<quoted visible text>"
        EMPLOYER-POSTING <opp_id> negative <url> <signal> ["<quoted visible text>"]
        EMPLOYER-POSTING <opp_id> not-found
        EMPLOYER-POSTING <opp_id> looked <url> site-not-allowed|render-failed|inconclusive

    The quote runs from the first `"` after the keyword to the LAST `"` on the line, so a quote may contain
    `'`, `"`, `$`, a backtick and `;` and comes back byte for byte (N1). Only a trailing newline is removed.
    A `live` line via fetch or render with no quote is refused; so is a `render-unavailable` with none.
    N2: `negative <url> render-unavailable site-not-allowed` (a site the pane refused) is read as a LOOK
    (`looked ... site-not-allowed`), never as a negative: a refusal is never counted toward a dead verdict.
    Raises `PostingLineError`."""
    if not isinstance(line, str):
        raise PostingLineError("the line is not text")
    text = line.rstrip("\r\n")
    if "\n" in text or "\r" in text:
        raise PostingLineError("one EMPLOYER-POSTING line per call")
    m = _LINE_LIVE_FEED.match(text)
    if m:
        return m.group(1), _checked_url(live(m.group(2), "feed"))
    m = _LINE_LIVE_Q.match(text)
    if m:
        return m.group(1), _checked_url(live(m.group(2), m.group(3), _line_evidence(m.group(4))))
    m = _LINE_NEG_SITE.match(text)
    if m:
        return m.group(1), _checked_url(looked(m.group(2), "site-not-allowed"))
    m = _LINE_NEG.match(text)
    if m:
        ev = m.group(4)
        if ev is not None:
            ev = _line_evidence(ev)
        if m.group(3) == "render-unavailable" and ev is None:
            raise PostingLineError("render-unavailable needs the quoted visible text")
        return m.group(1), _checked_url(negative(m.group(2), m.group(3), ev))
    m = _LINE_NOTFOUND.match(text)
    if m:
        return m.group(1), not_found()
    m = _LINE_LOOKED.match(text)
    if m:
        return m.group(1), _checked_url(looked(m.group(2), m.group(3)))
    if re.match(r"^EMPLOYER-POSTING \S+ live \S+ via (?:fetch|render)\s*$", text):
        raise PostingLineError("a live line via fetch or render needs the quoted visible text")
    raise PostingLineError("not an EMPLOYER-POSTING line in the grammar")


def _checked_url(obs):
    if not _valid_url(obs.url):
        raise PostingLineError("%r is not an http(s) URL with a host" % (obs.url,))
    return obs


def _line_evidence(ev):
    try:
        _check_evidence(ev, "the quoted")
    except PostingFieldError as e:
        raise PostingLineError(e.reason)
    return ev


def parse_lines(text):
    """`[(opp_id, Observation)]` for every EMPLOYER-POSTING line in a hand-back file's text; other lines are
    prose and are ignored. A line that starts EMPLOYER-POSTING and is not in the grammar RAISES: a malformed
    line is loud, never skipped."""
    out = []
    for raw in text.splitlines():
        if raw.startswith("EMPLOYER-POSTING"):
            out.append(parse_line(raw))
    return out


def format_line(opp_id, obs):
    """The canonical line for an observation: the inverse of `parse_line`."""
    head = "EMPLOYER-POSTING %s" % opp_id
    if obs.kind == "not-found":
        return "%s not-found" % head
    if obs.kind == "live":
        if obs.via == "feed":
            return "%s live %s via feed" % (head, obs.url)
        return '%s live %s via %s "%s"' % (head, obs.url, obs.via, obs.evidence)
    if obs.kind == "negative":
        tail = ' "%s"' % obs.evidence if obs.evidence is not None else ""
        return "%s negative %s %s%s" % (head, obs.url, obs.signal, tail)
    if obs.kind == "looked":
        return "%s looked %s %s" % (head, obs.url, obs.signal)
    raise ValueError("unknown observation kind %r" % (obs.kind,))


# ---- the look cache (a CACHE: unreadable reads as empty; no label reads it) -----------------------------------

def looks_path(root):
    return os.path.join(root, ".jobsearch", "posting_looks.json")


def read_looks(root):
    try:
        with open(looks_path(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def note_look(root, opp_id, outcome, today):
    """Record that a role was looked at today and the look settled nothing. Atomic (tmp, then `os.replace`,
    as `feed_poll.write_cache`). `outcome` is a code in LOOK_RE. Losing the file costs repeated looks, never
    a state."""
    if not LOOK_RE.match(str(outcome)):
        raise ValueError("unknown look outcome %r" % (outcome,))
    _need_date(today, "today")
    looks = read_looks(root)
    looks[opp_id] = {"on": today, "outcome": outcome}
    path = looks_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(looks, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return looks


# ---- the queue: which roles go to the browser ----------------------------------------------------------------

def _queue_class(reading):
    return "confirmed" if reading.state == "confirmed" else "unconfirmed"


def queue_order(roles, looks, today):
    """`[(opp_id, "confirmed"|"unconfirmed")]`, best first, for the roles that are still due or carry a live
    pending signal. Two classes, confirmed first; within a class the oldest `max(checked_on, look.on)` goes
    first and a role never looked at goes first of all. Left out: a role whose field is unreadable (it needs
    repair, not a render), a CLOSED role (the label already flags it and its status is the candidate's call),
    and a role a BROWSER look refused or failed today (`site-not-allowed`, `render-failed`,
    `refused-not-owned`): the same refusal is not retried the same day. A fetch look (`inconclusive-*`)
    does not hold a role out; the browser is the remedy for it."""
    looks = looks if isinstance(looks, dict) else {}
    ranked = []
    for opp in roles:
        try:
            r = parse(opp.get("employer_posting"))
        except PostingFieldError:
            continue
        if r.state == "closed":
            continue
        if not (due(r, today) or live_pending(r, today)):
            continue
        look = looks.get(opp.get("id")) if isinstance(looks.get(opp.get("id")), dict) else None
        if look and look.get("on") == today and look.get("outcome") in BROWSER_LOOKS:
            continue
        stamps = [d for d in (r.checked_on, look.get("on") if look else None) if _real_date(d)]
        newest = max(stamps) if stamps else ""
        klass = _queue_class(r)
        ranked.append((0 if klass == "confirmed" else 1, newest, str(opp.get("id")), klass))
    ranked.sort(key=lambda t: (t[0], t[1], t[2]))
    return [(t[2], t[3]) for t in ranked]


def top_up(order, pending_ids):
    """The opportunity ids to queue so that at most BROWSER_CHECKS_PER_RUN `posting-check` items are pending.
    `order` is `queue_order`'s result; `pending_ids` the ids already pending. The unconfirmed class is
    guaranteed UNCONFIRMED_SHARE of those slots (its already-pending items count) and never takes more
    while a confirmed role is left waiting; a slot a class cannot use flows to the other, so with no
    confirmed role waiting the unconfirmed class fills all of them. A role already pending is never queued
    twice."""
    pending = set(pending_ids)
    free = BROWSER_CHECKS_PER_RUN - len(pending)
    if free <= 0:
        return []
    klass = dict(order)
    conf = [i for i, k in order if k == "confirmed" and i not in pending]
    unconf = [i for i, k in order if k == "unconfirmed" and i not in pending]
    pending_u = sum(1 for i in pending if klass.get(i) == "unconfirmed")
    u_take = min(len(unconf), max(0, UNCONFIRMED_SHARE - pending_u), free)
    c_take = min(len(conf), free - u_take)
    rest = free - u_take - c_take
    u_take += min(len(unconf) - u_take, rest)
    return conf[:c_take] + unconf[:u_take]


# ---- robots.txt, RFC 9309 section 2.3.1 (N5) ----------------------------------------------------------------

def robots_verdict(status, body, fp=None):
    """`(mode, rules)` from the robots.txt answer, per RFC 9309 section 2.3.1:

      200..299   parsed (at most the first 500 KiB, section 2.5); an empty body allows all
      4xx        'unavailable' (2.3.1.3): the crawler MAY access any resource -> mode `allow`
      5xx, a network failure (`status` None), or anything else
                 'unreachable' (2.3.1.4): disallow for THIS run -> mode `deny`

    `mode` is `rules` (use `fp.robots_allows(rules, path)`), `allow` or `deny`. Fails closed on the
    unreachable case and on anything it cannot classify."""
    if status is None or not isinstance(status, int):
        return "deny", []
    if 200 <= status < 300:
        fp = fp or _fp()
        text = (body or b"")[:fp.ROBOTS_PARSE_LIMIT].decode("utf-8", "replace")
        groups, _sitemaps = fp.parse_robots(text)
        return "rules", fp.robots_rules_for(groups)
    if 400 <= status < 500:
        return "allow", []
    return "deny", []


def _fp():
    import feed_poll
    return feed_poll


# ---- Step A: the network half ---------------------------------------------------------------------------------

class _DeadlineHit(Exception):
    pass


class _Clock(object):
    def now(self):
        import time
        return time.monotonic()

    def sleep(self, seconds):
        import time
        time.sleep(seconds)


class _Net(object):
    """One run's politeness: a deadline, 1 s apart per host, robots.txt once per host per run."""

    def __init__(self, fetch, clock, deadline_s, fp):
        self.fetch, self.clock, self.deadline_s, self.fp = fetch, clock, deadline_s, fp
        self.t0 = clock.now()
        self.last, self.robots = {}, {}

    def expired(self):
        return self.clock.now() - self.t0 >= self.deadline_s

    def get(self, url):
        if self.expired():
            raise _DeadlineHit()
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        last = self.last.get(host)
        if last is not None:
            wait = self.fp.MIN_INTERVAL_S - (self.clock.now() - last)
            if wait > 0:
                self.clock.sleep(wait)
        self.last[host] = self.clock.now()
        req = self.fp.Request("GET", url, {"User-Agent": self.fp.USER_AGENT}, self.fp.TIMEOUT_S)
        return self.fetch(req)

    def robots_for(self, url):
        parts = urllib.parse.urlsplit(url)
        origin = "%s://%s" % (parts.scheme.lower(), parts.netloc.lower())
        if origin in self.robots:
            return self.robots[origin]
        try:
            resp = self.get(origin + "/robots.txt")
            verdict = robots_verdict(resp.status, resp.body, self.fp)
        except self.fp.FetchError:
            verdict = robots_verdict(None, b"", self.fp)
        self.robots[origin] = verdict
        return verdict


def _code(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "unknown"


def _valid_through(body):
    """The `validThrough` date (ISO, date part) of the page's single JobPosting, else None. Re-reads the
    JSON-LD with `feed_poll`'s own collector; called only after `parse_jobposting` accepted the page."""
    fp = _fp()
    try:
        coll = fp._LdCollector()
        coll.feed(body.decode("utf-8"))
        coll.close()
    except Exception:                                   # noqa: BLE001 - html.parser raises on some bad markup
        return None
    for raw in coll.scripts:
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        for node in fp._as_list(doc):
            if isinstance(node, dict) and fp._type_has(node, "JobPosting"):
                d = fp._iso_date(node.get("validThrough"))
                return d.isoformat() if d else None
    return None


def fetch_observation(url, today, net):
    """One employer URL, one GET, after robots.txt. Returns `("live"|"negative", Observation)` or
    `("inconclusive", code)`. A JobPosting with no past `validThrough` is live (evidence
    `JobPosting validThrough=<date or none>`); a 404 or 410 and a past `validThrough` are negatives; EVERYTHING
    else (no JobPosting, a 200 shell, an off-host or off-path redirect, a timeout, a 5xx, a refusing
    robots.txt) is inconclusive and stores nothing. Raises `_DeadlineHit` when the deadline passed."""
    fp = net.fp
    mode, rules = net.robots_for(url)
    if mode == "deny":
        return "inconclusive", "robots"
    if mode == "rules":
        parts = urllib.parse.urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        if not fp.robots_allows(rules, path):
            return "inconclusive", "robots"
    try:
        resp = net.get(url)
    except fp.FetchError as e:
        return "inconclusive", _code(e.code)
    if resp.status in (404, 410):
        return "negative", negative(url, "http-%d" % resp.status)
    if resp.status != 200:
        return "inconclusive", "http-%d" % resp.status
    final = getattr(resp, "final_url", None) or url
    if _host(final) != _host(url) or not same_url(final, url):
        return "inconclusive", "redirected"
    try:
        page = fp.parse_jobposting(resp.body, url, today)
    except fp.PageRefusal as e:
        return "inconclusive", _code(e.code)
    vt = _valid_through(resp.body)
    if page["expired"]:
        return "negative", negative(url, "valid-through-past", "JobPosting validThrough=%s" % (vt or "none"))
    return "live", live(url, "fetch", "JobPosting validThrough=%s" % (vt or "none"))


# ---- Step A: the feed signal (no network) -----------------------------------------------------------------------

def _feed_cache(root):
    try:
        with open(os.path.join(root, ".jobsearch", "feed_etags.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _listed_today(cache, ats, today):
    """The canonical URLs the vendor's list carried TODAY for this company's board, or None when the cache
    has nothing usable for today (a lost cache, an uncovered board, a stale `listed.on`)."""
    if not isinstance(ats, dict) or ats.get("vendor") not in ("greenhouse", "lever", "ashby"):
        return None
    key = "%s:%s:%s" % (ats["vendor"], ats.get("region") or "-", ats.get("slug"))
    entry = cache.get(key)
    listed = entry.get("listed") if isinstance(entry, dict) else None
    if not isinstance(listed, dict) or listed.get("on") != today or not isinstance(listed.get("urls"), list):
        return None
    return set(_canon(u) for u in listed["urls"] if isinstance(u, str))


def feed_observation(opp, reading, company, cache, today):
    """The feed's answer for one role, or None. A stored URL that satisfies rule (a) for the company's `ats`
    and is in today's list is `live via feed`. One absent from it is `negative feed-absent` ONLY when the
    role is already confirmed and the vendor is in FEED_ABSENT_VENDORS. A careers-host URL (rule b) never
    produces a feed observation, and neither does Workday. A lost cache produces nothing, never an absence."""
    ats = company.get("ats") if isinstance(company, dict) else None
    listed = _listed_today(cache, ats, today)
    if listed is None:
        return None
    if reading.state == "confirmed":
        urls = [reading.url]
    elif reading.state == "unconfirmed":
        urls = [u for u in [opp.get("jd_url")] + [s.get("source_url") for s in (opp.get("sightings") or [])
                                                  if isinstance(s, dict)] if isinstance(u, str)]
    else:
        return None
    for u in urls:
        if not _ats_matches(u, ats):
            continue
        if _canon(u) in listed:
            return live(u, "feed")
    if reading.state == "confirmed" and ats.get("vendor") in FEED_ABSENT_VENDORS \
            and _ats_matches(reading.url, ats):
        return negative(reading.url, "feed-absent")
    return None


# ---- Step A: the run ------------------------------------------------------------------------------------------------

class QueueUnavailable(Exception):
    pass


def _load_jsonl(root, name, required):
    path = os.path.join(root, "data", name)
    if not os.path.exists(path):
        if required:
            raise ValueError("data/%s is absent" % name)
        return []
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, ValueError) as e:
        raise ValueError("data/%s is unreadable (%s)" % (name, e))
    return rows


def _default_triage(opp):
    import your_move
    return your_move.triage_missing(opp)


def _default_record(root, today):
    def write(line):
        os.makedirs(os.path.join(root, ".jobsearch"), exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="posting_line.", suffix=".txt", dir=os.path.join(root, ".jobsearch"))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(line + "\n")
            env = dict(os.environ)
            env["CLAUDESEARCH_ROOT"] = root
            cmd = [sys.executable, os.path.join(HERE, "record.py"), "posting", "--from-file", path,
                   "--today", today]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
            except subprocess.TimeoutExpired:
                return 124, "record.py posting timed out"
            return r.returncode, " ".join((r.stdout + r.stderr).split())[-300:]
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    return write


def _default_queue():
    import deferred
    fn = getattr(deferred, "queue_posting_check", None)
    if fn is None:
        raise QueueUnavailable("deferred.queue_posting_check is not defined in this engine")
    return lambda opp_id: fn(opp_id)


def _default_pending():
    import deferred
    return [r.get("ref") for r in deferred.replay(deferred.load())
            if r.get("kind") == "posting-check" and r.get("status") == "pending"]


def run(run_id, root, today, fetch=None, clock=None, dry_run=False, out=print, record=None, queue=None,
        pending=None, triage=None, watch=None, deadline_s=FETCH_DEADLINE_S):
    """Step A. Returns the exit code (see the module docstring). Every collaborator is injectable
    (`fetch`, `clock`, `record`, `queue`, `pending`, `triage`, `watch`); the defaults are the real ones.
    `today` is the run date (the test-only `--today` seam passes it)."""
    if not _real_date(today):
        out("POSTING CHECK NOT RUN -- the run date %r is not a real YYYY-MM-DD date" % (today,))
        return 3
    try:
        opps = _load_jsonl(root, "opportunities.jsonl", True)
        companies = _load_jsonl(root, "companies.jsonl", False)
        channels = _load_jsonl(root, "channels.jsonl", False)
    except ValueError as e:
        out("POSTING CHECK NOT RUN -- %s" % e)
        return 3
    triage = triage or _default_triage
    watch = watch or in_watch_list
    wl = []
    try:
        for o in opps:
            if not isinstance(o, dict) or not o.get("id"):
                continue
            tm = triage(o) if (o.get("status") == "backlog" and o.get("verdict") == "undecided") else None
            if watch(o, tm):
                wl.append(o)
    except (OSError, ValueError, KeyError, ImportError) as e:
        out("POSTING CHECK NOT RUN -- the triage gate could not be read (%s)" % e)
        return 3
    pursuing = [o for o in opps if isinstance(o, dict) and o.get("verdict") == "pursue"
                and o.get("status") not in terminal_statuses()]
    if pursuing and not wl:
        out("POSTING CHECK NOT RUN -- the watch list is empty but %d role(s) carry the verdict pursue and a "
            "live status: a watch list that scans nothing must not print a clean line" % len(pursuing))
        return 3
    W = len(wl)
    fp = _fp()
    fetch = fetch or fp.default_fetch
    clock = clock or _Clock()
    record = record or _default_record(root, today)
    looks = read_looks(root)
    cache = _feed_cache(root)
    cos = dict((c.get("id"), c) for c in companies if isinstance(c, dict))
    net = _Net(fetch, clock, deadline_s, fp)
    c = collections.Counter()
    problems = []
    state = {}                       # opp id -> its stored value after this run's accepted observations

    def reading_of(o):
        return parse(state[o["id"]] if o["id"] in state else o.get("employer_posting"))

    def rank(o):
        try:
            r = parse(o.get("employer_posting"))
        except PostingFieldError:
            return (2, "", o["id"])
        look = looks.get(o["id"]) if isinstance(looks.get(o["id"]), dict) else {}
        stamps = [d for d in (r.checked_on, look.get("on")) if _real_date(d)]
        return (0 if r.state == "confirmed" else 1, max(stamps) if stamps else "", o["id"])

    def apply(o, obs):
        """Write one observation through record.py (or pretend, on a dry run); advance the in-memory value
        only when the write was accepted. Returns True when it was."""
        line = format_line(o["id"], obs)
        if not dry_run:
            rc, text = record(line)
            if rc != 0:
                c["refused"] += 1
                problems.append("POSTING CHECK REFUSED %s: %s" % (o["id"], text or "record.py exit %d" % rc))
                return False
        try:
            state[o["id"]] = observe(reading_of(o), obs, today)
        except ObservationRefused as e:
            c["refused"] += 1
            problems.append("POSTING CHECK REFUSED %s: %s" % (o["id"], e.reason))
            return False
        c["live" if obs.kind == "live" else "negative"] += 1
        return True

    def note(o, code):
        looks[o["id"]] = {"on": today, "outcome": code}
        if not dry_run:
            note_look(root, o["id"], code, today)
        c["inconclusive"] += 1

    for o in sorted(wl, key=rank):
        try:
            r = parse(o.get("employer_posting"))
        except PostingFieldError:
            c["unreadable"] += 1
            continue
        if net.expired():
            c["deadline"] += 1
            continue
        look = looks.get(o["id"]) if isinstance(looks.get(o["id"]), dict) else {}
        if r.checked_on == today or look.get("on") == today:
            c["skipped"] += 1
            continue
        try:
            obs = feed_observation(o, r, cos.get(o.get("company_id"), {}), cache, today)
            if obs is not None:
                apply(o, obs)
            r = reading_of(o)
            if r.state == "confirmed" and due(r, today) and _valid_url(r.url):
                kind, res = fetch_observation(r.url, today, net)
                if kind == "inconclusive":
                    note(o, "inconclusive-" + res)
                else:
                    apply(o, res)
        except _DeadlineHit:
            c["deadline"] += 1
            continue
        c["examined"] += 1

    rows = []
    for o in wl:
        rows.append(dict(o, employer_posting=state[o["id"]]) if o["id"] in state else o)
    order = queue_order(rows, looks, today)
    queued, pend_ids = 0, []
    try:
        pend_ids = list((pending or _default_pending)())
        picks = top_up(order, pend_ids)
        if dry_run:
            queued = len(picks)
        else:
            q = queue or _default_queue()
            for oid in picks:
                try:
                    q(oid)
                    queued += 1
                except Exception as e:                          # noqa: BLE001 - a refusal names the role, the run goes on
                    problems.append("POSTING CHECK QUEUE REFUSED %s: %s" % (oid, " ".join(str(e).split())[:200]))
    except QueueUnavailable as e:
        problems.append("POSTING CHECK QUEUE NOT RUN -- %s (nothing queued)" % e)
    except (OSError, ValueError, ImportError, AttributeError) as e:
        problems.append("POSTING CHECK QUEUE NOT RUN -- the pending items could not be read (%s)" % e)
    still_due = 0
    for o in rows:
        try:
            r = parse(o.get("employer_posting"))
        except PostingFieldError:
            continue
        if r.state != "closed" and due(r, today):
            still_due += 1
    for p in problems:
        out(p)
    out("POSTING CHECK: examined %d of %d in watch list · skipped today %d · unreadable %d · live %d · "
        "negative %d · inconclusive %d · refused %d · queued %d (pending %d) · not checked %d (deadline %d)"
        % (c["examined"], W, c["skipped"], c["unreadable"], c["live"], c["negative"], c["inconclusive"],
           c["refused"], queued, len(pend_ids) + queued, still_due, c["deadline"]))
    return 4 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-check the pursue list against the employer's own posting "
                                             "(Step A, zero tokens).")
    ap.add_argument("--run", metavar="RUN_ID", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="TEST-ONLY date seam; production never passes it")
    args = ap.parse_args(argv)
    from _root import profile_root
    root = profile_root()
    today = args.today or datetime.date.today().isoformat()
    return run(args.run, root, today, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
