"""Listed pay, posted dates, employer postings, commute minutes, title floor and non-employee compensation: the
vocabularies and the checks.

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.basics import is_date
from validation.vocab import CURRENCY_RE, TERMINAL_OPP_STATUSES


LISTED_PAY_STATES = ("employer-stated", "board-estimate", "none-shown")
LISTED_PAY_SOURCES = ("listing-text", "ats-api", "json-ld", "board-widget", "candidate")
PAY_INTERVALS = ("year", "month", "day", "hour")          # R2: the four units postings in scope use
# dev #820 / public #175 (0.82.0): WHERE a figure came from -- the capture card, the JD read, or the
# candidate. Absent on a legacy row (not rewritten). `source` says what FORM the figure took.
PROVENANCES = ("card", "jd", "candidate")
LISTED_PAY_KEYS = ("state", "ranges", "source", "captured_on", "inferred_from", "provenance", "none_basis")
# dev #846 (0.88.0, design 4.4): `none_basis` says HOW a `none-shown` was earned -- the route of the read (`record.py read-jd --via`)
# that stated the description holds no pay. Legal only on a `none-shown` whose source is `listing-text`: a legacy none-shown has
# none (the 0.88.0 migration moves those to `listed_pay_prior`), and the candidate's own none (`source: candidate`) needs no basis.
NONE_BASES = ("fetch", "render", "feed", "ats-api")
# A superseded `listed_pay` kept in `listed_pay_prior` (append-only) carries two more keys: when and by what it was moved.
SUPERSEDED_KEYS = ("superseded_on", "superseded_by")
# dev #915 (0.88.0, design 6.3, 6.4): what a company IS, by the candidate's own word (`record.py company-kind`). Absent means
# `your_move.company_kind()` derives it from a channel of that name, then a name heuristic, else `employer`.
COMPANY_KINDS = ("employer", "staffing", "aggregator")
INFERRED_FROM = ("description",)             # dev #775: how a figure was READ, not what the listing showed
PAY_RANGE_KEYS = ("min", "max", "currency", "interval", "label")
POSTED_SOURCES = ("ats-posted", "board-relative", "profile-document-date", "unknown")
POSTED_KEYS = ("date", "source", "recorded_on")
COMMUTE_MINUTES_KEYS = ("minutes", "anchor", "source")
COMMUTE_MINUTES_SOURCES = ("candidate", "map-estimate", "config-place")


def _real_date(v):
    """True for an ISO `YYYY-MM-DD` string that is a real calendar date."""
    if not is_date(v):
        return False
    import datetime as _dt
    try:
        _dt.date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _unknown_keys(obj, allowed, label, problems):
    for k in obj:
        if k not in allowed:
            problems.append("%s: unknown key %r (known: %s)" % (label, k, ", ".join(allowed)))


def check_listed_pay(lp, label, problems, prior=False):
    """`listed_pay` (design §3.1, R2): `{state, ranges?, source, captured_on}`. Refuses an unknown
    state, source or interval; an empty `ranges` on a stated or estimated pay; ranges on a
    none-shown pay; `min` above `max`; a range with neither figure; a currency that is not three
    capitals; `board-estimate` from anywhere but a board's own widget; `ats-api` or `json-ld`
    behind anything but an employer-stated pay.

    dev #846 (0.88.0): `none_basis` is one of `NONE_BASES` and legal only on a `none-shown` read from `listing-text`. With
    `prior=True` the object is an entry of `listed_pay_prior` (a superseded `listed_pay`): it also carries `superseded_on` (an ISO
    date) and `superseded_by` (a non-empty string), both REQUIRED there and refused anywhere else."""
    if not isinstance(lp, dict):
        problems.append("%s: listed_pay must be an object (state, ranges, source, captured_on) -- "
                        "got %s" % (label, type(lp).__name__))
        return
    _unknown_keys(lp, LISTED_PAY_KEYS + (SUPERSEDED_KEYS if prior else ()), label + " listed_pay", problems)
    if prior:
        if not _real_date(lp.get("superseded_on")):
            problems.append("%s: listed_pay_prior entry superseded_on not an ISO date -- %r" % (label, lp.get("superseded_on")))
        if not (isinstance(lp.get("superseded_by"), str) and lp["superseded_by"].strip()):
            problems.append("%s: listed_pay_prior entry superseded_by must be a non-empty string (the migration or the read that "
                            "moved it) -- %r" % (label, lp.get("superseded_by")))
    state, source = lp.get("state"), lp.get("source")
    if "none_basis" in lp:
        if lp["none_basis"] not in NONE_BASES:
            problems.append("%s: listed_pay.none_basis %r not in {%s}" % (label, lp["none_basis"], ", ".join(NONE_BASES)))
        elif state != "none-shown" or source != "listing-text":
            problems.append("%s: listed_pay.none_basis is legal only with state 'none-shown' and source 'listing-text' -- got %r "
                            "and %r" % (label, state, source))
    if state not in LISTED_PAY_STATES:
        problems.append("%s: listed_pay.state %r not in {%s}" % (label, state,
                                                                 ", ".join(LISTED_PAY_STATES)))
    if source not in LISTED_PAY_SOURCES:
        problems.append("%s: listed_pay.source %r not in {%s}" % (label, source,
                                                                   ", ".join(LISTED_PAY_SOURCES)))
    if state == "board-estimate" and source in LISTED_PAY_SOURCES and source != "board-widget":
        problems.append("%s: listed_pay.state 'board-estimate' requires source 'board-widget' "
                        "(an estimate is the board's own panel, never the listing text) -- got %r"
                        % (label, source))
    if source in ("ats-api", "json-ld") and state in LISTED_PAY_STATES \
            and state != "employer-stated":
        problems.append("%s: listed_pay.source %r requires state 'employer-stated' -- got %r"
                        % (label, source, state))
    if "inferred_from" in lp:
        # dev #775 (design-workday-feed.md 6.4): a marker, not a new state. Legal only on a figure the
        # reader took from listing text (`employer-stated` + `listing-text`): a Workday JobPosting carries
        # no `baseSalary`, so the figure is read out of the description and says so.
        if lp["inferred_from"] not in INFERRED_FROM:
            problems.append("%s: listed_pay.inferred_from %r not in {%s}"
                            % (label, lp["inferred_from"], ", ".join(INFERRED_FROM)))
        elif state != "employer-stated" or source != "listing-text":
            problems.append("%s: listed_pay.inferred_from is legal only with state 'employer-stated' "
                            "and source 'listing-text' -- got %r and %r" % (label, state, source))
    if "provenance" in lp and lp["provenance"] not in PROVENANCES:
        problems.append("%s: listed_pay.provenance %r not in {%s}"
                        % (label, lp["provenance"], ", ".join(PROVENANCES)))
    if not _real_date(lp.get("captured_on")):
        problems.append("%s: listed_pay.captured_on not an ISO date -- %r"
                        % (label, lp.get("captured_on")))
    ranges = lp.get("ranges")
    if state == "none-shown":
        if ranges:
            problems.append("%s: listed_pay.state 'none-shown' carries no ranges -- a listing "
                            "that showed no pay has nothing to range over" % label)
        return
    if state not in LISTED_PAY_STATES:
        return
    if not isinstance(ranges, list) or not ranges:
        problems.append("%s: listed_pay.ranges must be a non-empty list for state %r"
                        % (label, state))
        return
    for i, rg in enumerate(ranges):
        rl = "%s listed_pay.ranges[%d]" % (label, i)
        if not isinstance(rg, dict):
            problems.append("%s: must be an object (min, max, currency, interval, label)" % rl)
            continue
        _unknown_keys(rg, PAY_RANGE_KEYS, rl, problems)
        mn, mx = rg.get("min"), rg.get("max")
        for name, v in (("min", mn), ("max", mx)):
            if v is not None and not (_is_number(v) and v > 0):
                problems.append("%s: %s must be a positive number or null -- %r" % (rl, name, v))
        if mn is None and mx is None:
            problems.append("%s: min and max are both null -- a range needs at least one figure"
                            % rl)
        elif _is_number(mn) and _is_number(mx) and mn > mx:
            problems.append("%s: min %s > max %s" % (rl, mn, mx))
        if not (isinstance(rg.get("currency"), str) and CURRENCY_RE.match(rg["currency"])):
            problems.append("%s: currency %r is not an ISO 4217 code (three capitals)"
                            % (rl, rg.get("currency")))
        if rg.get("interval") not in PAY_INTERVALS:
            problems.append("%s: interval %r not in {%s}" % (rl, rg.get("interval"),
                                                              ", ".join(PAY_INTERVALS)))
        lb = rg.get("label")
        if lb is not None and not (isinstance(lb, str) and lb.strip()):
            problems.append("%s: label must be a non-empty string or null" % rl)


def check_posted(p, label, problems):
    """`posted` (design §3.3): `{date, source, recorded_on}`. `date` is null EXACTLY when `source`
    is `unknown`; a source outside the closed four, a date that is not a real calendar date and a
    missing `recorded_on` are refused."""
    if not isinstance(p, dict):
        problems.append("%s: posted must be an object (date, source, recorded_on) -- got %s"
                        % (label, type(p).__name__))
        return
    _unknown_keys(p, POSTED_KEYS, label + " posted", problems)
    src, date = p.get("source"), p.get("date")
    if src not in POSTED_SOURCES:
        problems.append("%s: posted.source %r not in {%s}" % (label, src, ", ".join(POSTED_SOURCES)))
    elif src == "unknown" and date is not None:
        problems.append("%s: posted.source 'unknown' carries no date -- got %r (a date has a "
                        "source that earned it)" % (label, date))
    elif src != "unknown" and date is None:
        problems.append("%s: posted.date is null but posted.source is %r -- null is exactly the "
                        "'unknown' source" % (label, src))
    if date is not None and not _real_date(date):
        problems.append("%s: posted.date %r is not a real ISO date" % (label, date))
    if not _real_date(p.get("recorded_on")):
        problems.append("%s: posted.recorded_on not an ISO date -- %r"
                        % (label, p.get("recorded_on")))


def check_employer_posting(ep, label, problems):
    """`employer_posting` (dev #776 / public #166, design-employer-posting-confirmation.md §3.3 and
    §15 N8, N12): whether the role is confirmed on the EMPLOYER'S OWN posting. OPTIONAL, and ABSENT
    means "never checked" (the validator does not look at a row without the key: no rewrite of any
    stored row is needed). A PRESENT value must be an object that `posting_check.parse` accepts.

    ⭐ THE RULES LIVE IN ONE PLACE. This function only CALLS the parser every reader calls, so the
    validator and the surfaces cannot disagree about what a readable value is. It does not re-run
    the ownership resolver (design §3.3: ownership is a write-time check, and a later change to
    `companies[].ats` must not turn a valid historical row invalid).

    ⭐ A PRESENT value is never skipped quietly. An explicit `null` is refused (absent is how an
    unchecked role reads; a stored null is a value nothing wrote on purpose), and if the parser
    cannot be imported the row is reported as a PROBLEM saying it was NOT CHECKED, because a green
    run that validated nothing reads as a valid row. The import is lazy and inside this function so
    that `posting_check` never has to import this module at load time (N8: no import cycle), and so
    a profile that stores no such value never touches it."""
    if not isinstance(ep, dict):
        problems.append("%s: employer_posting must be an object (state, checked_on, ...) or ABSENT -- "
                        "got %s (absent reads as never checked; a stored null is refused)"
                        % (label, type(ep).__name__))
        return
    try:
        import posting_check as _posting_check
    except ImportError as exc:
        problems.append("%s: employer_posting is present but NOT CHECKED -- posting_check could not "
                        "be imported (%s)" % (label, exc))
        return
    try:
        _posting_check.parse(ep)
    except _posting_check.PostingFieldError as exc:
        problems.append("%s: employer_posting %s" % (label, exc))


def check_commute_minutes(cm, label, problems):
    """`location.commute_minutes` (design §3.5): `{minutes, anchor, source}`."""
    if not isinstance(cm, dict):
        problems.append("%s: location.commute_minutes must be an object (minutes, anchor, "
                        "source) -- got %s" % (label, type(cm).__name__))
        return
    _unknown_keys(cm, COMMUTE_MINUTES_KEYS, label + " location.commute_minutes", problems)
    m = cm.get("minutes")
    if not (isinstance(m, int) and not isinstance(m, bool) and m >= 0):
        problems.append("%s: location.commute_minutes.minutes must be a whole number of minutes "
                        ">= 0 -- %r" % (label, m))
    if not (isinstance(cm.get("anchor"), str) and cm["anchor"].strip()):
        problems.append("%s: location.commute_minutes.anchor must name the anchor place" % label)
    if cm.get("source") not in COMMUTE_MINUTES_SOURCES:
        problems.append("%s: location.commute_minutes.source %r not in {%s}"
                        % (label, cm.get("source"), ", ".join(COMMUTE_MINUTES_SOURCES)))


def check_title_floor(screen_cfg, problems):
    """`screen.title_floor` of `config.json` (dev #722 / public #156): absent or null, or exactly one
    level of `config_keys.SENIORITY_LEVELS`. Returns 1 when a floor is set. The validator is
    `config_keys.validate_title_floor`'s, one copy."""
    if not isinstance(screen_cfg, dict) or screen_cfg.get("title_floor") is None:
        return 0
    import config_keys as _ck
    for why in _ck.validate_title_floor(screen_cfg.get("title_floor")):
        problems.append("config %s" % why)
    return 1


def check_non_employee_comp(compensation, problems):
    """`compensation.non_employee` of `config.json` (dev #740 / public #160, E4): absent or null, or
    exactly `{floors: {<unit>: <positive int>}, note?}`. Returns 1 when a block is set. The validator
    is `config_keys.validate_non_employee`'s, one copy: a block the screen cannot read is refused
    here, loudly, never read as absent."""
    import config_keys as _ck
    if not isinstance(compensation, dict) or compensation.get("non_employee") is None:
        return 0
    for why in _ck.validate_non_employee(compensation.get("non_employee")):
        problems.append("config %s" % why)
    return 1


def _live(opp):
    return opp.get("status") not in TERMINAL_OPP_STATUSES


def _has_pay(opp):
    comp = opp.get("comp")
    if isinstance(comp, dict) and _is_number(comp.get("max")):
        return True
    return isinstance(opp.get("listed_pay"), dict)


def check_pay_captured(opps):
    """One line per LIVE opportunity with neither a `listed_pay` nor a `comp.max` (dev #715 / public
    #143, P5): the role's pay was never captured, so the screen reports NOT CAPTURED for it and a
    person should re-read the listing. Legacy rows appear here after the upgrade. That is the point."""
    return ["opportunities[%s]: live, and its pay was never captured (no listed_pay, no comp.max) "
            "-- re-read the listing, then record.py listed-pay" % o.get("id", "?")
            for o in opps if isinstance(o, dict) and _live(o) and not _has_pay(o)]
