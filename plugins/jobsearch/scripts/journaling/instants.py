"""Instants and coverage: parsing aware timestamps, coverage intervals, covered-through and triaged uids.

Capability module of `journal.py` (S4a, moved unedited)."""

import datetime
from journaling.tables import JournalError, TRIAGE_TTL_DAYS


def _parse_iso(raw):
    try:
        return datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# ⭐ dev #807 — coverage windows are INSTANTS, read by ONE parser
# --------------------------------------------------------------------------
# A `swept` row's `from`/`through` used to be naive local wall time. In the fall-back hour that names
# two instants, and `01:10` (before the change) and `01:50` (after it) compared with the wrong order:
# a real 1h40m hole merged away and printed as covered. The writer now stores a numeric offset, and
# every reader goes through `parse_instant`. Rows written before 0.83.0 stay naive on disk (the journal
# is append-only, and a rewrite could only apply the same rule the reader does: design-sweep-misfires
# section 4.2), so `parse_instant` carries the stated legacy interpretation too.
_UTC = datetime.timezone.utc
INSTANT_ROLES = ("from", "through", "point")


def _declared_zone():
    """The tzinfo `_localzone` resolves (declared `geography.timezone`, then `TZ`), or None when only
    the host zone is known. Never raises: a zone we cannot load is the host zone, not a crash."""
    try:
        import _localzone
        return _localzone.local_zone()
    except Exception:
        return None


def _fromiso(raw):
    """`fromisoformat` that accepts a trailing `Z` (3.9 and 3.10 refuse it); None on anything else."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def is_offset_bearing(raw):
    """True when `raw` is an ISO string that names ONE instant (it carries a numeric offset or `Z`).
    The predicate `record_swept` uses: `parse_instant` cannot be, because it deliberately reads a naive
    legacy value as an instant by the legacy rule."""
    d = _fromiso(raw)
    return d is not None and d.tzinfo is not None and d.utcoffset() is not None


def coverage_iso(dt):
    """An AWARE datetime as the ISO string a `swept` row stores: its offset, in the zone `_localzone`
    resolves (declared `geography.timezone`, then `TZ`, then the host), e.g. `2026-11-01T01:05:00-06:00`.
    The instant is correct in any zone; the declared zone only decides which offset is printed, so the
    ledger reads in the owner's clock even when the host is elsewhere. Never emits `Z` (3.9 cannot parse
    it back). Raises on a naive datetime: that is the defect this exists to end."""
    if not isinstance(dt, datetime.datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise JournalError("coverage_iso needs an AWARE datetime, got %r — a naive local time in the "
                           "fall-back hour names two instants (dev #807)" % (dt,))
    tz = _declared_zone()
    local = dt.astimezone(tz) if tz is not None else dt.astimezone()
    return local.replace(microsecond=0).isoformat()


def _coverage_field(value, name):
    """The stored form of a `swept` window end: an aware datetime through `coverage_iso`, or a string
    that already carries an offset (kept verbatim). Anything naive is refused."""
    if isinstance(value, datetime.datetime):
        return coverage_iso(value)
    if not is_offset_bearing(value):
        raise JournalError(
            "record_swept(ok=True) %s=%r carries no UTC offset. A naive local time in the fall-back hour "
            "names two instants, so a coverage window must be an instant: pass an aware datetime or "
            "journal.coverage_iso(dt) (dev #807)." % (name, value))
    return value


def _journal_at(at):
    """`at` keeps the journal-wide naive-local convention: an aware datetime becomes naive host-local."""
    if isinstance(at, datetime.datetime):
        if at.tzinfo is not None:
            at = at.astimezone().replace(tzinfo=None)
        return at.replace(microsecond=0).isoformat()
    return at


def parse_instant(raw, role="point"):
    """⭐ dev #807 — THE ONE parser for a coverage timestamp: an aware UTC datetime, or None when `raw`
    cannot be read. `role` is one of `INSTANT_ROLES`.

    An offset-bearing value is exact. A NAIVE value is a legacy row (written before 0.83.0 as wall time
    on the writing machine's zone), read by the stated rule of design-sweep-misfires section 4.2:
      * the candidate zones are this host's zone and the declared zone (`_localzone`);
      * in each candidate, BOTH readings of the wall time are built (`fold=0` and `fold=1`);
      * `from` takes the LATEST reading and `through` the EARLIEST, so coverage can only shrink: a
        real hole is never merged away, and a false hole is closed by the next sweep reaching back;
      * `point` takes `fold=0` in the declared zone (the host zone when none is declared).
    Outside a fold, with one zone, every reading is equal and nothing changes. When the candidate zones
    differ, a legacy row shrinks by their difference, so a legacy row SHORTER than that difference reads
    inverted and contributes no coverage (`coverage_intervals` drops it)."""
    if role not in INSTANT_ROLES:
        raise JournalError("parse_instant role must be one of %r, got %r" % (INSTANT_ROLES, role))
    d = _fromiso(raw)
    if d is None:
        return None
    if d.tzinfo is not None:
        return d.astimezone(_UTC)
    declared = _declared_zone()
    readings = []
    point = None
    for fold in (0, 1):
        naive = d.replace(fold=fold)
        candidates = [("host", naive)]
        if declared is not None:
            candidates.append(("declared", naive.replace(tzinfo=declared)))
        for kind, cand in candidates:
            try:
                utc = cand.astimezone(_UTC)
            except (OverflowError, OSError, ValueError):
                continue
            readings.append(utc)
            if fold == 0 and kind == ("declared" if declared is not None else "host"):
                point = utc
    if not readings:
        return None
    if role == "from":
        return max(readings)
    if role == "through":
        return min(readings)
    return point if point is not None else readings[0]


def coverage_intervals(recs, mailbox, by=None):
    """⭐ dev #807 — `[(from_utc, through_utc), ...]` for every `ok: true` `swept` row of `mailbox` (and
    of sweep kind `by`, when given), read through `parse_instant`. A row that cannot be read, or whose
    `from` is at or after its `through` (a legacy row wholly inside the fold, or shorter than the zone
    difference), contributes NOTHING: its hour reads as not covered, never as a crash. The one place a
    `swept` window is turned into intervals; `covered_through` and `mail_client.uncovered_spans` share it."""
    out = []
    for r in recs:
        if r.get("event") != "swept" or r.get("mailbox") != mailbox or not r.get("ok"):
            continue
        if by is not None and r.get("by") != by:
            continue
        fd, td = parse_instant(r.get("from"), "from"), parse_instant(r.get("through"), "through")
        if fd is None or td is None or fd >= td:
            continue
        out.append((fd, td))
    return out


def _as_of_instant(as_of):
    """`covered_through`'s `as_of` (a datetime or a string) as an aware UTC instant, or None."""
    if isinstance(as_of, datetime.datetime):
        if as_of.tzinfo is not None:
            return as_of.astimezone(_UTC)
        return parse_instant(as_of.isoformat(), "point")
    return parse_instant(as_of, "point")


def _merge_intervals(intervals):
    """[(from_dt, through_dt), ...] (aware datetimes) -> the same list with every overlapping or
    touching pair merged into one. Adjacency is guaranteed across a healthy run history by the
    ledger-derived lookback in `mail_client.py` (each sweep reaches back to the end of the last covered
    interval), so a gap that survives this merge is a REAL hole, not a rounding artefact. An empty or
    inverted pair is dropped (dev #807), never raised."""
    merged = []
    for f, t in sorted((p for p in intervals if p[0] < p[1]), key=lambda p: p[0]):
        if merged and f <= merged[-1][1]:
            if t > merged[-1][1]:
                merged[-1] = (merged[-1][0], t)
        else:
            merged.append((f, t))
    return merged


def covered_through(recs, mailbox, as_of=None, by=None):
    """⭐⭐ dev #321 (V0) — THE READER every silence consumer imports. The end (ISO string) of
    the contiguous VERIFIED-coverage interval for `mailbox` that CONTAINS `as_of` — or, with no
    `as_of`, the newest merged interval's end. Returns `None` when nothing verifies coverage
    there: no `swept` rows at all, or `as_of` falls in a gap between them. `None` is the honest
    default on an empty ledger — the caller's job (check_followups.py) is to render "unverified"
    rather than fall back to the wall clock, which is dev #321 itself.

    Coverage is the union of `[from, through]` windows from `ok: true` swept rows for this
    mailbox; a `swept ok: false` row (a failed account) contributes nothing, which is what makes
    a partial failure mark that account uncovered rather than merely annotated.

    ⭐ design-inbound-resolution.md §5 amendment D3 (surface pass 2026-09-14) — `by`, optional,
    filters to rows written by that sweep kind ONLY. Before this fix `by` was ignored entirely,
    so `covered_through(recs, mailbox)` merged EVERY sweep's coverage regardless of which one
    wrote it — a mailbox the daily `alert_sweep` has been covering every day reads as covered
    through today even though `reconcile-ats` has never once run there, so the very first
    `--ats` run saw the daily's 3-day floor instead of the 30-day first-run backfill, and a
    25-day-old decline (public #55) was never even in the searched window. `by=None` keeps the
    old, cross-sweep-kind merge every EXISTING caller relies on (check_followups.verified_as_of,
    the plain `mail_client.lookback_days(..., by=None)` call `watch.py`/`alert_sweep.py`/
    `meeting_check.py` already make) — only a caller that asks for its OWN sweep kind's history
    gets the narrower answer.

    ⭐ dev #807 — the windows are INSTANTS, read by `parse_instant` (a legacy naive row by its stated
    rule), merged as instants, and the answer is an offset-bearing ISO string in the declared zone,
    not a naive one: `01:05-05:00` and `01:05-06:00` are two different answers. `as_of` is read as a
    `point`. A row whose `from` is at or after its `through` contributes nothing.
    """
    intervals = coverage_intervals(recs, mailbox, by=by)
    if not intervals:
        return None
    merged = _merge_intervals(intervals)
    if as_of is None:
        return coverage_iso(merged[-1][1])
    as_of_dt = _as_of_instant(as_of)
    if as_of_dt is None:
        return None
    for f, t in merged:
        if f <= as_of_dt <= t:
            return coverage_iso(t)
    return None


def triaged_uids(recs, mailbox, by=None, as_of=None, ttl_days=TRIAGE_TTL_DAYS):
    """⭐ public #99 — the set of uid strings already triaged for `mailbox`, within the last
    `ttl_days` of `as_of` (default: now) — what a sweep should SKIP rather than re-fetch and
    re-screen. Read BEFORE any mailbox fetch, exactly the way `covered_through()` is read before
    a sweep decides its own search window.

    `by`, optional, narrows to one sweep kind's own history — the same filter
    `covered_through(..., by=...)` already carries (design-inbound-resolution.md §5 amendment
    D3), so a second sweep that someday triages the same mailbox for a different purpose does
    not silently cover for this one. `mailbox` is matched exactly, never merged across accounts
    — two mailboxes sharing an IMAP uid number are two different rows here, filtered apart the
    same way `covered_through()` never merges two mailboxes' coverage.

    A row older than `ttl_days` is treated as though it were never written — see
    `TRIAGE_TTL_DAYS`'s own docstring for why an aged-out disposition is correct rather than a
    leak: the uid can only be re-found inside a sweep's own bounded search window, so a
    disposition that has outlived every window a sweep could plausibly run can never be checked
    against a live hit anyway."""
    if as_of is None:
        as_of_dt = datetime.datetime.now()
    elif isinstance(as_of, datetime.datetime):
        as_of_dt = as_of
    else:
        as_of_dt = _parse_iso(as_of) or datetime.datetime.now()
    floor = as_of_dt - datetime.timedelta(days=ttl_days)
    out = set()
    for r in recs:
        if r.get("event") != "triaged" or r.get("mailbox") != mailbox:
            continue
        if by is not None and r.get("by") != by:
            continue
        at_dt = _parse_iso(r.get("at"))
        if at_dt is None or at_dt < floor:
            continue
        uid = r.get("uid")
        if uid:
            # dev #704 / public #154 (D1) — a uid stored before 0.66.0 is the REPR of a bytes
            # object ("b'101'"); the fresh uid a sweep now holds is "101". Same message.
            import validate_data as _vd
            out.add(str(_vd.normalize_uid(str(uid))))
    return out


def probe_covered_through(recs, thread, medium):
    """⭐ dev #321 item 2 (V0), medium-filtered by Query or Citation C1 (D1) — the newest
    `probe` row's `at` for this `thread` ON THIS MEDIUM, or `None`. A probe is pointwise (see
    `record_probe`), so the newest one alone verifies coverage through its own timestamp; no
    interval merge applies.

    `medium` carries NO DEFAULT on purpose: V0 had exactly one caller and none existed yet, so a
    default was harmless; C1 adds the first real consumers (`your_move.conversation_axis()`),
    and a caller that does not say which medium it means would silently accept an email probe
    as LinkedIn coverage of the same `contact:<id>` thread (or vice versa) — the exact
    cross-medium confusion D1 exists to prevent."""
    ats = [r.get("at") for r in recs
          if r.get("event") == "probe" and r.get("thread") == thread
          and r.get("medium") == medium and r.get("at")]
    return max(ats) if ats else None
