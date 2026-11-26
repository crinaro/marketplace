"""The shapes of the role-first release's journal rows, ONE check each for the writer and the reader (jobsearch 0.94.0;
docs/design-role-first.md 0, 4.1, 5.3, 8.1, 19.5, 19.6):

  `scope: search`            a `pass linkedin` row: `dispatched` (always-present boolean `attended`, the stored query `plan`) or
                             `returned` (`jobsearch` and, when it was `unreachable`, a `reason`). Refused on any other kind or phase.
  `matching`                 the optional block of a `drain planned` row: the lane's own figures.
  `roles` optional fields    `pairs`, `q_planned`, `q_not_attempted`, `bounded`, `links`, `pane`, `mode` (surface `linkedin-jobsearch`).
  `linkedin-search-skip`     `{event, at, until, by}`, no run id, `until` at most 30 days on.
  `linkedin-warning`         `{event, at, run_id, kind, attended, n}` plus optional `at_utc`, `reason`, `page`: a warning ended a search pass (or, `page` posting or reply, a posting
                             or reply page). Never page text. `reason` is the judge's word for an `unclear` page (`no-cards`, `tool-error` ...).
  `linkedin-search-on`       `{event, at, warning, attended}` plus optional `at_utc`: the owner turned scheduled searching back on, naming the warning's date.
  `linkedin-search-page`     `{event, at, at_utc, run_id, n, step, count}`: one results page of a search judged ordinary (`step: page`, `count` its cards) or its links taken
                             (`step: links`, `count` the ids printed): what the per-page gate counts (20 searches a pass, one page a search, 25 links a search, 500 a pass).

A LEAF module: it imports only `journaling.tables`, so `row_shapes` (the reader's table) and the writers can both import it. It
checks SHAPE; whether a `linkedin-search-on` names the newest warning needs the rows around it and is `search_state`'s.

Capability module of `journal.py`. Python 3.9+, standard library only."""

import datetime
import re
from journaling.tables import (
    JOBSEARCH_TOKENS,
    JournalError,
    LINKEDIN_SWEEP_SURFACES,
    PASS_PANE_MODES,
    PASS_PANE_STATES,
    SEARCH_REASONS,
    SEARCH_SCOPE,
)

WARNING_KINDS = ("sign-in", "challenge", "unusual-activity", "usage-limit", "restricted", "unclear")
WARNING_PAGES = ("results", "posting", "reply")             # which LinkedIn page a `linkedin-warning` was judged on (absent: a results page)
SEARCH_PAGE_STEPS = ("page", "links")
SKIP_MAX_DAYS = 30
PLAN_KEYS = ("n", "geo", "title", "do", "last")
PLAN_LAST_NOT_RECORDED = "not-recorded"
PAIR_KEYS = ("geo", "title", "reached", "shown", "total")
LINKS_VERDICTS = ("matched", "unmatched", "no-ids", "not-loaded", "read-error", "partial")
MATCHING_KEYS = ("setting", "considered", "admitted", "waiting", "open", "in_flight", "bound")
MATCHING_SETTING_MAX = 100          # `search.matching_roles_per_run`'s upper bound (`reach/keys.py`; a test pins the two equal)
ROLES_NEW_FIELDS = ("pairs", "q_planned", "q_not_attempted", "bounded", "links", "pane", "mode")
ROLES_SEARCH_SURFACE = "linkedin-jobsearch"

_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAME_RE = re.compile(r"^\S+$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


def _int(v, lo=0, hi=None):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)


def _word(v):
    return isinstance(v, str) and bool(v.strip()) and "\n" not in v and len(v) <= 200


def _iso_at(label, v):
    if not isinstance(v, str) or not _AT_RE.match(v):
        raise JournalError("%s at=%r is not an ISO date and time" % (label, v))
    try:
        datetime.datetime.fromisoformat(v)
    except ValueError:
        raise JournalError("%s at=%r is not a real date and time" % (label, v))


def _utc_stamp(label, rec):
    """An optional `at_utc`: an ISO date and time WITH an offset. It is a stamp for the cadence and the turn-on check, never an order."""
    if "at_utc" not in rec:
        return
    v = rec["at_utc"]
    try:
        ok = isinstance(v, str) and datetime.datetime.fromisoformat(v).tzinfo is not None
    except ValueError:
        ok = False
    if not ok:
        raise JournalError("%s at_utc=%r is not an ISO date and time with a UTC offset" % (label, v))


def _date(label, field, v):
    try:
        if not isinstance(v, str) or not _DATE_RE.match(v):
            raise ValueError(v)
        return datetime.date.fromisoformat(v)
    except ValueError:
        raise JournalError("%s %s=%r is not a real date (YYYY-MM-DD)" % (label, field, v))


def _exact(label, rec, keys, optional=()):
    unknown, missing = sorted(set(rec) - set(keys) - set(optional)), [k for k in keys if k not in rec]
    if unknown:
        raise JournalError("%s has unknown field(s) %s" % (label, ", ".join(unknown)))
    if missing:
        raise JournalError("%s is missing field(s) %s" % (label, ", ".join(missing)))


# ---- pass linkedin, scope search ---------------------------------------------------------------------------------------

def check_plan(plan):
    """The stored query plan of a `scope: search` `dispatched` row (design 5.3): a non-empty list of `{n, geo, title, do, last}`, one per
    (title, geography) pair, `n` distinct integers from 1, `do` a boolean (the pair runs this pass; at least one does), `last` the
    date or date and time of the newest recorded run of the pair, or the literal `not-recorded` (never `never`, never null)."""
    if not isinstance(plan, list) or not plan:
        raise JournalError("a search pass plan must be a non-empty list of {%s} -- got %r" % (", ".join(PLAN_KEYS), plan))
    seen_n, seen_pair = set(), set()
    for i, e in enumerate(plan):
        if not isinstance(e, dict) or set(e) != set(PLAN_KEYS):
            raise JournalError("plan[%d] must be exactly {%s} -- got %r" % (i, ", ".join(PLAN_KEYS), e))
        if not _int(e["n"], 1) or e["n"] in seen_n:
            raise JournalError("plan[%d].n=%r is not a distinct integer from 1" % (i, e["n"]))
        seen_n.add(e["n"])
        if not _word(e["geo"]) or not _word(e["title"]):
            raise JournalError("plan[%d].geo and .title must be non-empty one-line strings -- got %r, %r" % (i, e["geo"], e["title"]))
        if (e["geo"], e["title"]) in seen_pair:
            raise JournalError("plan[%d] repeats the pair (%r, %r)" % (i, e["geo"], e["title"]))
        seen_pair.add((e["geo"], e["title"]))
        if not isinstance(e["do"], bool):
            raise JournalError("plan[%d].do=%r is not a boolean" % (i, e["do"]))
        last = e["last"]
        if last != PLAN_LAST_NOT_RECORDED and not (isinstance(last, str) and (_DATE_RE.match(last) or _AT_RE.match(last))):
            raise JournalError("plan[%d].last=%r is not a date, a date and time, or %r" % (i, last, PLAN_LAST_NOT_RECORDED))
    if not any(e["do"] for e in plan):
        raise JournalError("a search pass plan with no pair to run (every do is false) is not a dispatch")


def check_search_pass_row(rec):
    """The shape of a `pass` row's search half, for the writer and the reader alike. A row with no `scope` and no `plan` is none of this
    check's business (every pass row written before 0.94.0). Raises `JournalError` when `scope` is not `search`, when it sits on any kind
    but `linkedin` or any phase but `dispatched` and `returned`, when a `dispatched` row lacks its boolean `attended` or its `plan`,
    when a `returned` row lacks its `jobsearch` token, carries `attended` or `plan`, or has a `reason` that is not a `SEARCH_REASONS`
    code exactly when `jobsearch` is `unreachable`."""
    scope = rec.get("scope")
    if scope is None:
        if "plan" in rec:
            raise JournalError("pass: `plan` belongs to a scope: search dispatched row")
        return
    if scope != SEARCH_SCOPE:
        raise JournalError("pass scope=%r is not %r" % (scope, SEARCH_SCOPE))
    kind, phase = rec.get("kind"), rec.get("phase")
    if kind != "linkedin" or phase not in ("dispatched", "returned"):
        raise JournalError("pass scope: search is only for a linkedin pass with phase dispatched or returned (got kind=%r phase=%r)"
                           % (kind, phase))
    if phase == "dispatched":
        if not isinstance(rec.get("attended"), bool):
            raise JournalError("pass linkedin dispatched scope: search needs a boolean `attended` (always present) -- got %r"
                               % (rec.get("attended"),))
        if "plan" not in rec:
            raise JournalError("pass linkedin dispatched scope: search needs its `plan` (the stored query list)")
        check_plan(rec["plan"])
        if rec.get("reason") not in (None, ""):
            raise JournalError("pass linkedin dispatched scope: search carries a reason %r" % (rec["reason"],))
        return
    for k in ("attended", "plan"):
        if k in rec:
            raise JournalError("pass linkedin returned scope: search carries %s, which belongs to the dispatched row" % k)
    token, reason = rec.get("jobsearch"), rec.get("reason") or ""
    if token not in JOBSEARCH_TOKENS:
        raise JournalError("pass linkedin returned scope: search needs `jobsearch`, one of %s -- got %r"
                           % (", ".join(JOBSEARCH_TOKENS), token))
    if token == "unreachable":
        if reason not in SEARCH_REASONS:
            raise JournalError("a search that was unreachable needs a reason, one of %s -- got %r" % (", ".join(SEARCH_REASONS), reason))
    elif reason:
        raise JournalError("pass linkedin returned scope: search carries a reason %r with jobsearch=%s: a reason says why a "
                           "search was unreachable" % (reason, token))
    for label in ("reached", "unreachable", "not_attempted"):
        bad = sorted(set(rec.get(label) or []) - LINKEDIN_SWEEP_SURFACES)
        if bad:
            raise JournalError("pass %s=%r is not in LINKEDIN_SWEEP_SURFACES" % (label, bad))


# ---- drain planned: matching -------------------------------------------------------------------------------------------

def check_matching_block(m, rec):
    """The `matching` block of a `drain planned` row (design 4.1, 4.3): exactly `{setting, considered, admitted, waiting, open,
    in_flight, bound}`, every figure an integer, `setting` 1..100 (`search.matching_roles_per_run`), `bound` 1 or more
    (`search.open_decisions_max`), `admitted` no more than `considered` and no more than the row's own `intake` (the lane's roles
    are part of it). `rec` is the whole row."""
    if not isinstance(m, dict) or set(m) != set(MATCHING_KEYS):
        raise JournalError("drain planned matching must be exactly {%s} -- got %r" % (", ".join(MATCHING_KEYS), m))
    bad = [k for k in MATCHING_KEYS if not _int(m[k])]
    if bad:
        raise JournalError("drain planned matching.%s is not an integer >= 0 -- got %r" % (", ".join(bad), {k: m[k] for k in bad}))
    if not _int(m["setting"], 1, MATCHING_SETTING_MAX):
        raise JournalError("drain planned matching.setting=%r is not 1..%d" % (m["setting"], MATCHING_SETTING_MAX))
    if m["bound"] < 1:
        raise JournalError("drain planned matching.bound=%r is not 1 or more" % (m["bound"],))
    if m["admitted"] > m["considered"]:
        raise JournalError("drain planned matching.admitted=%d exceeds matching.considered=%d" % (m["admitted"], m["considered"]))
    intake = rec.get("intake")
    if _int(intake) and m["admitted"] > intake:
        raise JournalError("drain planned matching.admitted=%d exceeds intake=%d: the lane's roles are part of the intake"
                           % (m["admitted"], intake))


# ---- roles: the optional 0.94.0 fields ---------------------------------------------------------------------------------

def check_pairs(pairs):
    """`roles.pairs`: a list of `{geo, title, reached, shown, total}`, the pairs a search pass reported. `reached` is a boolean, `shown` the
    cards read (0 when the pair was not reached), `total` the result size LinkedIn gave or null when none was read; a pair is listed once."""
    if not isinstance(pairs, list):
        raise JournalError("roles pairs=%r is not a list" % (pairs,))
    seen = set()
    for i, p in enumerate(pairs):
        if not isinstance(p, dict) or set(p) != set(PAIR_KEYS):
            raise JournalError("roles pairs[%d] must be exactly {%s} -- got %r" % (i, ", ".join(PAIR_KEYS), p))
        if not _word(p["geo"]) or not _word(p["title"]):
            raise JournalError("roles pairs[%d].geo and .title must be non-empty one-line strings" % i)
        if not isinstance(p["reached"], bool) or not _int(p["shown"]) or not (p["total"] is None or _int(p["total"])):
            raise JournalError("roles pairs[%d] needs reached a boolean, shown an integer >= 0 and total an integer >= 0 or null -- "
                               "got %r" % (i, p))
        if not p["reached"] and p["shown"]:
            raise JournalError("roles pairs[%d] was not reached and still shows %d cards" % (i, p["shown"]))
        if p["total"] is not None and p["shown"] > p["total"]:
            raise JournalError("roles pairs[%d] shows %d cards of a total of %d" % (i, p["shown"], p["total"]))
        if (p["geo"], p["title"]) in seen:
            raise JournalError("roles pairs[%d] repeats the pair (%r, %r)" % (i, p["geo"], p["title"]))
        seen.add((p["geo"], p["title"]))


def check_links(links):
    """`roles.links`: how the link reader fared over a pass's results pages, `{verdict: count}` over `LINKS_VERDICTS` (the verdicts of
    design 7.4 and `LINKS-PARTIAL`; `matched` and `unmatched` count roles, the others pages), at least one entry, each an integer >= 0."""
    if (not isinstance(links, dict) or not links or set(links) - set(LINKS_VERDICTS)
            or any(not _int(v) for v in links.values())):
        raise JournalError("roles links must be a non-empty {verdict: integer >= 0} over %s -- got %r"
                           % (", ".join(LINKS_VERDICTS), links))


def check_roles_new_fields(rec):
    """The optional fields a `roles` event gained in 0.94.0, each checked when present: `pairs`, `q_planned` and `q_not_attempted`
    (integers >= 0, `q_not_attempted` no more than `q_planned`), `bounded` (integer >= 0: queries whose result was larger than the
    part read), `links`, and `pane` and `mode` (the vocabularies of a `recorded` pass row; `unreported` goes with `unreported` and a
    hidden pane with a hidden mode). They are for the `linkedin-jobsearch` surface only. `q_not_attempted` above 0 makes the pass
    `partial`, so a row that says otherwise is refused. A row carrying none of them is untouched (every `roles` event before 0.94.0)."""
    given = sorted(k for k in ROLES_NEW_FIELDS if rec.get(k) is not None)
    if not given:
        return
    if rec.get("surface") != ROLES_SEARCH_SURFACE:
        raise JournalError("roles %s are for surface %r only (got surface=%r)" % (", ".join(given), ROLES_SEARCH_SURFACE, rec.get("surface")))
    for k in ("q_planned", "q_not_attempted", "bounded"):
        if rec.get(k) is not None and not _int(rec[k]):
            raise JournalError("roles %s=%r is not an integer >= 0" % (k, rec[k]))
    if rec.get("q_not_attempted") is not None:
        if rec.get("q_planned") is None or rec["q_not_attempted"] > rec["q_planned"]:
            raise JournalError("roles q_not_attempted=%r needs q_planned, and is no more than it (got q_planned=%r)"
                               % (rec["q_not_attempted"], rec.get("q_planned")))
        if rec["q_not_attempted"] > 0 and rec.get("coverage") == "complete":
            raise JournalError("roles q_not_attempted=%d but coverage is complete: a planned query that was never run makes the pass "
                               "partial" % rec["q_not_attempted"])
    if rec.get("pairs") is not None:
        check_pairs(rec["pairs"])
    if rec.get("links") is not None:
        check_links(rec["links"])
    pane, mode = rec.get("pane"), rec.get("mode")
    if (pane is None) != (mode is None):
        raise JournalError("roles pane and mode go together (got pane=%r mode=%r)" % (pane, mode))
    if pane is not None:
        if pane not in PASS_PANE_STATES or mode not in PASS_PANE_MODES:
            raise JournalError("roles pane=%r mode=%r are not in %r, %r" % (pane, mode, PASS_PANE_STATES, PASS_PANE_MODES))
        if (pane == "unreported") != (mode == "unreported"):       # 0.94.0 N1: `hidden` + `normal` is a pass whose pages read in full
            raise JournalError("roles pane=%r mode=%r: `unreported` goes with `unreported` and only with it" % (pane, mode))


# ---- the three LinkedIn search events ----------------------------------------------------------------------------------

def check_skip_row(rec):
    """`linkedin-search-skip`: exactly `{event, at, until, by}`; `until` a real date from the day of `at` to 30 days after it, `by` a
    name without whitespace. No run id: the owner skips, not a run."""
    _exact("linkedin-search-skip", rec, ("event", "at", "until", "by"))
    _iso_at("linkedin-search-skip", rec["at"])
    day = datetime.datetime.fromisoformat(rec["at"]).date()
    until = _date("linkedin-search-skip", "until", rec["until"])
    if until < day or until > day + datetime.timedelta(days=SKIP_MAX_DAYS):
        raise JournalError("linkedin-search-skip until=%s is not within %d days of %s" % (rec["until"], SKIP_MAX_DAYS, day.isoformat()))
    if not isinstance(rec["by"], str) or not _NAME_RE.match(rec["by"]):
        raise JournalError("linkedin-search-skip by=%r is not a non-empty name without whitespace" % (rec["by"],))


def check_warning_row(rec):
    """`linkedin-warning`: exactly `{event, at, run_id, kind, attended, n}` and optionally `at_utc`, `reason` (a word) and `page` (`WARNING_PAGES`). `kind` is one of `WARNING_KINDS` (a word, never page text),
    `attended` a boolean, `n` the 1-based number of the plan entry whose page it was."""
    _exact("linkedin-warning", rec, ("event", "at", "run_id", "kind", "attended", "n"), ("at_utc", "reason", "page"))
    _iso_at("linkedin-warning", rec["at"])
    _utc_stamp("linkedin-warning", rec)
    if "reason" in rec and not (isinstance(rec["reason"], str) and _REASON_RE.match(rec["reason"])):
        raise JournalError("linkedin-warning reason=%r is not a lower-case word (a word, never page text)" % (rec["reason"],))
    if "page" in rec and rec["page"] not in WARNING_PAGES:
        raise JournalError("linkedin-warning page=%r is not one of %s" % (rec["page"], ", ".join(WARNING_PAGES)))
    if not isinstance(rec["run_id"], str) or not _NAME_RE.match(rec["run_id"]):
        raise JournalError("linkedin-warning run_id=%r is not a non-empty run id without whitespace" % (rec["run_id"],))
    if rec["kind"] not in WARNING_KINDS:
        raise JournalError("linkedin-warning kind=%r is not one of %s" % (rec["kind"], ", ".join(WARNING_KINDS)))
    if not isinstance(rec["attended"], bool) or not _int(rec["n"], 1):
        raise JournalError("linkedin-warning needs attended a boolean and n an integer >= 1 -- got %r, %r" % (rec["attended"], rec["n"]))


def check_search_on_row(rec):
    """`linkedin-search-on`: exactly `{event, at, warning, attended}`; `warning` the real date (YYYY-MM-DD) of the warning it turns the
    search back on after, `attended` exactly true (a typed word, PARTIAL, as everywhere). Whether that date names the newest warning is
    `search_state.search_on_problems`'s, because it needs the rows around this one."""
    _exact("linkedin-search-on", rec, ("event", "at", "warning", "attended"), ("at_utc",))
    _iso_at("linkedin-search-on", rec["at"])
    _utc_stamp("linkedin-search-on", rec)
    _date("linkedin-search-on", "warning", rec["warning"])
    if rec["attended"] is not True:
        raise JournalError("linkedin-search-on attended=%r is not true: only a person turns the scheduled search back on" % (rec["attended"],))


def check_search_page_row(rec):
    """`linkedin-search-page`: exactly `{event, at, at_utc, run_id, n, step, count}`. `step` is `page` (one results page judged ordinary, `count` its cards) or `links` (the ids a
    search printed, `count` how many); `n` the plan entry. The per-page gate counts these rows; nothing else reads them."""
    _exact("linkedin-search-page", rec, ("event", "at", "at_utc", "run_id", "n", "step", "count"))
    _iso_at("linkedin-search-page", rec["at"])
    _utc_stamp("linkedin-search-page", rec)
    if not isinstance(rec["run_id"], str) or not _NAME_RE.match(rec["run_id"]):
        raise JournalError("linkedin-search-page run_id=%r is not a non-empty run id without whitespace" % (rec["run_id"],))
    if rec["step"] not in SEARCH_PAGE_STEPS:
        raise JournalError("linkedin-search-page step=%r is not one of %s" % (rec["step"], ", ".join(SEARCH_PAGE_STEPS)))
    if not _int(rec["n"], 1) or not _int(rec["count"]):
        raise JournalError("linkedin-search-page needs n an integer >= 1 and count an integer >= 0 -- got %r, %r" % (rec["n"], rec["count"]))
