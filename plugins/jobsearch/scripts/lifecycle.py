#!/usr/bin/env python3
"""lifecycle.py -- where a role is, as ONE function (dev #820 / public #175; design-role-pipeline.md
sections 2-4, 17).

WHY THIS EXISTS
---------------
Before 0.82.0 four modules each defined "reviewed", a role the system had not read sat in a stage the
candidate was asked about, and a drain that stopped halfway left nothing a surface could count. This
module owns the only function that says where a role is, `stage()`, and the only text any surface
prints about process state, `process_report()`. The stage is DERIVED, NEVER STORED: the facts it reads
are stored with strict parsers (`jd_read`, `journal`), and a second source of truth is what this
replaces.

THE INTERFACE (a change to it is a B0 STOP)
-------------------------------------------
  load_data(root=None) -> data         the snapshot every function below takes (an ADDITION: the loader)
  context(data, now) -> Ctx            run windows, the run-over rule, the cutover, admissions
  stage(row, ctx) -> Stage             `Stage(name, failure, since, cause, detail, key)`: one per role
                                       or open capture item
  pipeline(data, now) -> [(row, Stage)]   every opportunity AND every open capture item
  roles(data, now) -> [Unit]           the same, one per ROLE (the counting unit, N6)
  role_key(row, opps, companies=None)  the one identity of a role (N6)
  drain_plan(data, now, intake=None, render_route="yes", attended=False, run_id=None) -> Plan
  drain_close(data, run_id, now, by=None) -> {id: cause}      (`close_result` gives the full tally)
  process_report(data, now) -> Report  counts, failures, waiting, coverage; `headline`, `start_line`,
                                       `block_lines`, `conservation_line`, `run_lines`: THE only text
  first_seen(opp) -> date or None      the one first-sighting rule
  watch_missing(opp) -> list           [] when the role is `ready` or `decided`, else [stage name]
  version_tuple(s), closed_event(recs, run_id), STAGES, FAILURE_STATES, CAUSES, ADMISSION_ORDER and
  the constants RUN_LIVENESS_HOURS, DRAIN_BUDGET_S, PER_ROLE_S_DEFAULT, DRAIN_FANOUT.

`data` is a plain dict: `opportunities` (each with `_applications`), `applications`, `companies`,
`items` (the `deferred.replay` rows, every status), `journal` (the run journal records), `config`, and
optionally `root` (the profile, so the raw role count can be read straight off disk).

STAGES (section 2.2). Step 1, SETTLED, tried in order, none a failure: folded -- ended -- decided --
removed -- gone -- your-read -- ready. Step 2, UNFINISHED: a progress stage from the facts
(admitted/captured/reading/read/screened), which the admission rule turns into either that working stage
(the admitting run is still going) or the failure state (uncaptured/unread/read-failed/unscreened/
unresearched) with a cause from a closed vocabulary. A role NO run admitted is `waiting` (not a failure)
or, if it was first seen strictly before the cutover, a `legacy-backlog` failure (ruling 6: "stay
failures until read"). A row no rule matches is `unclassified`, a TERM of the conservation line and never
an exception (N6).

WHEN A RUN IS OVER (N1). Run R is over when the journal holds an `end` event for R, or R's OWN latest
journal record is more than RUN_LIVENESS_HOURS (8) before `now`. A `fired` record is never any run's
event, and a later `start` by another run never ends R. The window must exceed the longest legitimate
run (2 h 15 min measured, plus the drain budget of 3 h); `test_lifecycle.py` pins the inequality.

ONE COUNTING UNIT (N6): the ROLE, keyed by `role_key`. An open capture item that is a sighting of a
known role belongs to that role; two open items for one new role are one role. A folded row is a
duplicate of a counted role and is printed as a memo outside the sum.

A STORED SCREEN IS ONLY AS GOOD AS THE RULES IT WAS COMPUTED UNDER (dev #722 / #739 / #740, restored in
0.82.0). A role whose screen is title-stale (`profile.screen_is_title_stale`) or comp-stale
(`profile.screen_is_comp_stale`) against TODAY'S merged profile is not screened: it is at progress stage `read`,
exactly like a role with no screen, so the drain's `read-batch --fetch` re-screens it (`_store_screen` stores the
new keys, which ends the staleness). Because the owner editing their profile is not a process failure, a stale
role that no unfinished admission is holding is `waiting` with `detail == "rules-changed"`, never a failure
(`Ctx.working`). The merged profile is read ONCE per snapshot, by `load_data` (`data["profile"]`); an unreadable
or absent profile is None and makes nothing stale.

Imports `jd_read.py` (the read record's parser), `coverage.py` ("did not look") and, only when a snapshot carries a
profile, `profile.py` (the staleness hashes); all are named here by file because a bare `import` is invisible to
`publish_manifest.py`'s reachability closure, and a shipped script that imports an unpublished one crashes on the
user's machine.

Python 3.9+. Standard library only. Pure except `load_data`, `main()` and the CLI's locking.
"""

import argparse
import collections
import datetime
import json
import math
import os
import re
import subprocess
import sys
from typing import NamedTuple, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jd_read as _jd
import coverage as _coverage
import journal as _journal
import pipeline_index as _pidx
import config_keys as _ck

# ----------------------------------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------------------------------

RUN_LIVENESS_HOURS = 8
DRAIN_BUDGET_S = 10800                  # 3 h: the most a drain may be asked to do (N7)
PER_ROLE_S_DEFAULT = 270                # an ESTIMATE until `per_role_s` is measured (N7)
PER_ROLE_MIN_FINISHED = 5               # a close counts toward the measured rate only with this many finished
PER_ROLE_WINDOW = 5                     # the last N own closes whose median is the measured rate
# LONGEST_RUN_S: 2 h 15 min, the longest whole run measured (runlock.py docstring). The board batch loop
# (dev #830) now keeps a run open one batch after another until the script says stop, so a healthy run can
# outlast it: the figure UNDERSTATES a healthy run and is a "worth a look" line, not a bound. That is why the
# run generating the page is left out of `overlong_runs` (C7 / S5, `--run`); a DIFFERENT open run past it
# still alerts. The value is unchanged.
LONGEST_RUN_S = 8100
DRAIN_FANOUT = 1                        # readers/researchers at once. Raising it needs P-RP-1a (N3)
P_RP_1A_MIN_READS = 40
P_RP_1A_LINE_RE = re.compile(
    r"^- \*\*P-RP-1a\*\*: PASS (\d{4}-\d{2}-\d{2}), (\d+) interleaved reads, 0 cross-reads\s*$",
    re.MULTILINE)
FETCH_WORST_CASE_S = 51                 # 10 s timeout + 30 s Retry-After + 10 s retry + 1 s politeness (N7)
FETCH_CALL_S = 240                      # feed_poll.DEADLINE_S: one `read-batch --fetch` call
RETRY_STOP_RUN_CLASS = 3                # N4: consecutive run-class unfinished admissions
RETRY_STOP_ROLE_CLASS = 2               # section 4.5 IN4: consecutive role-class unfinished admissions
SKEW_DAYS = 14
ENGINE_CUTOVER = "0.82.0"
INTAKE_KEY = "search.intake_per_run"
INTAKE_NEW_PERCENT_KEY = "search.intake_new_percent"

# the order of the admission classes when there is NO reservation (N8). `new` is the waiting roles
# found on or after the cutover, `returned` is a role the candidate has read since its last admitting
# run closed (N9), `legacy` is the pre-0.82.0 backlog, `retry` an admitted role that is a failure now.
ADMISSION_CLASSES = ("retry", "returned", "legacy", "new")
ADMISSION_ORDER = ("retry", "returned", "legacy", "new")

# mirrored, never imported: validate_data/your_move resolve a profile at import. Pinned equal by tests.
SUBMITTED_APP_STATUS = frozenset({"submitted", "acknowledged", "rejected", "advanced", "closed"})
LIVE_OPP_STATUSES = ("active-pursuit", "needs-resolution", "in-motion")
OPP_STATUSES = LIVE_OPP_STATUSES + ("backlog", "passed", "expired")
# TERMINAL is what is left of the vocabulary once the live statuses and `backlog` are taken out
# (`validate_data.TERMINAL_OPP_STATUSES` is the ONE terminal set; a test pins this complement equal to it,
# because importing validate_data here would resolve a profile at import time).
NON_TERMINAL_STATUSES = LIVE_OPP_STATUSES + ("backlog",)
OPP_VERDICTS = ("pursue", "pass", "parked", "undecided")
CARD_SAFE_RULES = ("passed",)           # section 3.3: the only removal a card-input screen may stand on

SETTLED_STAGES = ("folded", "ended", "decided", "removed", "gone", "your-read", "ready")
PROGRESS_STAGES = ("admitted", "captured", "reading", "read", "screened")
FAILURE_STATES = ("uncaptured", "unread", "read-failed", "unscreened", "unresearched")
PROGRESS_TO_FAILURE = {"admitted": "uncaptured", "captured": "unread", "reading": "read-failed",
                       "read": "unscreened", "screened": "unresearched"}
STAGES = SETTLED_STAGES + PROGRESS_STAGES + ("waiting",) + FAILURE_STATES + ("unclassified",)

# cause -> (class, meaning, the action it points at). The CLOSED vocabulary (section 2.3, N4, N7).
# `retry-stopped`, `legacy-backlog` and `unclassified` are DERIVED: `stage()` produces them, and
# `journal.record_drain` refuses them in a `left` map.
CAUSE_TABLE = collections.OrderedDict([
    ("run-died", ("run", "the run that admitted it never ended",
                  "report it; a crash or a hang")),
    ("cause-not-recorded", ("run", "the run ended with no drain close on record",
                            "report it; the drain step was skipped")),
    ("not-dispatched", ("run", "it was admitted and needed a reader or researcher, and no dispatch "
                              "row names it", "report it; the run skipped a step")),
    ("deadline-reached", ("run", "the run ran out of its time bound before reaching it",
                          "report it if it repeats; lower search.intake_per_run")),
    ("agent-returned-nothing", ("role", "a reader or researcher was dispatched for it and recorded "
                                       "nothing", "report it; an agent failure")),
    ("capture-refused", ("role", "capture-batch refused the item", "fix the item, or report it")),
    ("challenge", ("role", "the posting showed a challenge page", "report it; retried first next run")),
    ("render-failed", ("role", "the page did not render", "report it; retried first next run")),
    ("surface-cannot-read", ("role", "the surface could not read the page",
                             "report it; retried first next run")),
    ("site-not-allowed", ("role", "the pane refused the site or asked for an approval that did not "
                                 "open", "approve the site in an attended session; the attended "
                                 "drain retries it")),
    ("retry-stopped", ("status", "left unfinished by repeated runs",
                       "left unfinished by three runs in a row: the likely reason is a page that "
                       "hangs the reader. Report it, or read it yourself (`read-jd --via "
                       "candidate`)")),
    ("legacy-backlog", ("status", "read by nothing before 0.82.0, not yet admitted",
                        "none: intake drains it oldest first")),
    ("unclassified", ("status", "no stage rule matches this row's values",
                      "report it; validate_data refuses the value at write")),
])
CAUSES = tuple(CAUSE_TABLE)
CAUSE_CLASS = {c: v[0] for c, v in CAUSE_TABLE.items()}
CAUSE_MEANING = {c: v[1] for c, v in CAUSE_TABLE.items()}
CAUSE_ACTION = {c: v[2] for c, v in CAUSE_TABLE.items()}
RUN_CLASS_CAUSES = tuple(c for c in CAUSES if CAUSE_CLASS[c] == "run")
ROLE_CLASS_CAUSES = tuple(c for c in CAUSES if CAUSE_CLASS[c] == "role")
# the causes `drain_close` may write: exactly what `journal.record_drain` accepts in `left`
CLOSE_CAUSES = RUN_CLASS_CAUSES + ROLE_CLASS_CAUSES

_SCREEN_RE = re.compile(r"^(review|remove):([a-z][a-z-]*(?:,[a-z][a-z-]*)*)$")


class LifecycleError(ValueError):
    """Input this module refuses. Loud on purpose."""


class _Unclassified(Exception):
    def __init__(self, detail):
        Exception.__init__(self, detail)
        self.detail = detail


class Stage(NamedTuple):
    """`name` is one of STAGES; `failure` is True for a failure state and for `unclassified`; `since`
    is a date (see section 2.2's table) or None; `cause` is one of CAUSES for a failure (and the
    OUTCOME for `gone` and `your-read`), else None; `detail` is text (for `retry-stopped` the
    underlying causes, `run-died x3`; for `waiting` the literal `returned` when the candidate read
    the role since its last admitting run closed); `key` is the role's identity."""
    name: str
    failure: bool = False
    since: Optional[datetime.date] = None
    cause: Optional[str] = None
    detail: str = ""
    key: str = ""


class Unit(NamedTuple):
    """One ROLE: its `key`, every `rows` that belong to it (the opportunity then its open items, or
    the open items of a new role), its `stage`, and whether it is a `folded` duplicate."""
    key: str
    rows: list
    stage: Stage
    folded: bool


# ----------------------------------------------------------------------------------------------
# small pure helpers
# ----------------------------------------------------------------------------------------------

def version_tuple(s):
    """`(0, 82, 0)` from `0.82.0`: engine versions compare as INTEGER tuples, never strings (N22:
    `(0, 9, 0) < (0, 82, 0)`). Raises `ValueError` on anything but three dot-separated integers."""
    parts = str(s).strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("engine version %r is not X.Y.Z" % (s,))
    return tuple(int(p) for p in parts)


def _dt(value):
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time())
    raise LifecycleError("`now` must be a datetime or date, got %r" % (value,))


def _parse_at(raw):
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def first_seen(opp):
    """The earliest readable `sightings[].seen_on` of an opportunity row (a `date`), else its
    `created` date, else None. `your_move.first_seen` delegates here."""
    days = [d for d in (_parse_date(s.get("seen_on")) for s in (opp.get("sightings") or [])
                        if isinstance(s, dict)) if d]
    if days:
        return min(days)
    return _parse_date(opp.get("created"))


def _item_first_seen(item):
    return _parse_date(item.get("queued_at"))


def closed_event(recs, run_id):
    """The ONE effective `drain closed` event of `run_id`: its own close when one exists, else the
    close written on its behalf (`on_behalf_of`), else None. The only reader of closes (N1)."""
    own = behalf = None
    for r in recs:
        if r.get("event") == "drain" and r.get("phase") == "closed" and r.get("run_id") == run_id:
            if r.get("on_behalf_of"):
                behalf = r
            else:
                own = r
    return own or behalf


def _is_item(row):
    return isinstance(row, dict) and row.get("kind") == "capture-role"


def _fmt_n(n):
    return "{:,}".format(int(n))


def _age(since, today):
    return (today - since).days if since is not None else None


# ----------------------------------------------------------------------------------------------
# the role's identity (N6)
# ----------------------------------------------------------------------------------------------

_WHAT_RE = re.compile(r"^Capture role: (?P<title>.+) at (?P<company>.+?) \((?P<loc>.*)\), seen .+? pass: \S+$",
                      re.DOTALL)


def item_company_title(item):
    """`(company, title)` read off a capture item's `what` text, or `(None, None)`. The item stores no
    structured pair; its `role.role_key` is the hash of the same normalised pair."""
    m = _WHAT_RE.match(str(item.get("what") or ""))
    if not m:
        return None, None
    return m.group("company").strip(), m.group("title").strip()


def item_urls(item):
    """Every address an open capture item is listed at: its `ref`, then each sibling listing."""
    urls = [item.get("ref")]
    urls += [s.get("url") for s in (item.get("siblings") or []) if isinstance(s, dict)]
    return [u for u in urls if isinstance(u, str) and u.strip()]


class RoleIndex(object):
    """The lookups `role_key` needs, built ONCE for a set of opportunity rows. A caller that keys many
    items builds one (`B1` imports this) instead of calling `role_key` per item with a fresh scan."""

    def __init__(self, opps, companies=None):
        self.opps = list(opps or [])
        self.companies = list(companies or [])
        self.by_url = collections.defaultdict(list)
        self.by_company = collections.defaultdict(list)
        for o in self.opps:
            if o.get("company_id"):
                self.by_company[o["company_id"]].append(o)
            urls = [o.get("jd_url")] + [s.get("source_url") for s in (o.get("sightings") or [])
                                         if isinstance(s, dict)]
            for u in urls:
                if isinstance(u, str) and u.strip():
                    self.by_url[u.strip()].append(o)
                    c = _pidx.canonical_job_url(u)
                    if c:
                        self.by_url[c].append(o)

    def _url_candidates(self, url):
        s = str(url).strip()
        out = list(self.by_url.get(s, ()))
        c = _pidx.canonical_job_url(s)
        if c:
            out += self.by_url.get(c, ())
        seen, uniq = set(), []
        for o in out:
            if id(o) not in seen:
                seen.add(id(o))
                uniq.append(o)
        return uniq

    def known_opportunity(self, item):
        """The opportunity row `pipeline_index.find_known_match` says this open item is a sighting
        of, or None: by URL first (the item's address, then each sibling's), then by company + title
        (needs the companies list to resolve the name)."""
        for u in item_urls(item):
            cands = self._url_candidates(u)
            if cands:
                hit = _pidx.find_known_match(cands, url=u)
                if hit:
                    return hit[0]
        company, title = item_company_title(item)
        if company and title and self.companies:
            cid = _pidx.resolve_company(company, self.companies)
            if cid:
                hit = _pidx.find_known_match(self.by_company.get(cid, []), company_id=cid, title=title)
                if hit:
                    return hit[0]
        return None

    def key(self, row):
        if not _is_item(row):
            return str(row.get("id") or "")
        o = self.known_opportunity(row)
        if o is not None:
            return o["id"]
        rk = (row.get("role") or {}).get("role_key") if isinstance(row.get("role"), dict) else None
        if isinstance(rk, str) and rk:
            return "item:" + rk
        company, title = item_company_title(row)
        if company and title:
            return "item:%s|%s" % (_pidx.normalize_company(company), _pidx.normalize_title(title))
        urls = item_urls(row)
        if urls:
            return "item:url:" + (_pidx.canonical_job_url(urls[0]) or urls[0].strip())
        return "item:id:" + str(row.get("id") or "")


def role_key(row, opps, companies=None, index=None):
    """The ONE identity of a role (N6). For an opportunity row it is the row's id. For an open capture
    item it is the id of the opportunity `pipeline_index.find_known_match` returns when there is one,
    else `item:` plus the item's normalised (company, title) key. `capture-batch --link-only` groups
    by it. Pass `companies` so a company + title match can resolve the name; pass `index` (a
    `RoleIndex`) when keying many items."""
    return (index or RoleIndex(opps, companies)).key(row)


# ----------------------------------------------------------------------------------------------
# the snapshot
# ----------------------------------------------------------------------------------------------

def _read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    raise LifecycleError("%s line %d is not valid JSON" % (path, n))
                if not isinstance(row, dict):
                    raise LifecycleError("%s line %d is not an object" % (path, n))
                rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def load_data(root=None):
    """The snapshot of a profile: reads the stores and nothing else, writes nothing. `root` defaults
    to the resolved profile. A missing store is empty; a line that is not JSON raises
    `LifecycleError` naming the file and line (a broken store must not read as an empty one)."""
    if root is None:
        from _root import profile_root
        root = profile_root()
    d = os.path.join(root, "data")
    opps = _read_jsonl(os.path.join(d, "opportunities.jsonl"))
    apps = _read_jsonl(os.path.join(d, "applications.jsonl"))
    by_opp = collections.defaultdict(list)
    for a in apps:
        if a.get("opp_id"):
            by_opp[a["opp_id"]].append(a)
    for o in opps:
        o["_applications"] = by_opp.get(o.get("id"), [])
    import deferred as _deferred
    items = _deferred.replay(_read_jsonl(os.path.join(d, "pending_actions.jsonl")))
    cfg = {}
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        pass
    except ValueError:
        raise LifecycleError("%s is not valid JSON" % os.path.join(root, "config.json"))
    try:
        recs = _journal.read(root)
    except _journal.JournalError as e:
        raise LifecycleError("the run journal cannot be read: %s" % e)
    return {"root": root, "opportunities": opps, "applications": apps,
            "companies": _read_jsonl(os.path.join(d, "companies.jsonl")), "items": items,
            "journal": recs, "config": cfg if isinstance(cfg, dict) else {},
            "profile": _read_profile(root)}


def _read_profile(root):
    """The merged profile `profile.load()` returns (config.json, then user.json over it), read from `root`, or
    None when either file is absent or unreadable. None makes NOTHING stale: an unreadable profile must never
    make every stored screen look stale (the 0.81 guard, kept). Called once per snapshot, by `load_data`."""
    merged = {}
    for name in ("config.json", "user.json"):
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(blob, dict):
            return None
        merged.update(blob)
    return merged


# ----------------------------------------------------------------------------------------------
# the context
# ----------------------------------------------------------------------------------------------

class Ctx(object):
    """Everything `stage()` reads besides the row itself. Build it with `context(data, now)`."""

    def __init__(self, data, now):
        self.data = data
        self.now = _dt(now)
        self.today = self.now.date()
        self.recs = list(data.get("journal") or [])
        self.cfg = data.get("config") or {}
        prof = data.get("profile")
        self.profile = prof if isinstance(prof, dict) else None     # the merged profile, built once per snapshot
        self.opps = [o for o in (data.get("opportunities") or []) if isinstance(o, dict)]
        self.opps_by_id = {o.get("id"): o for o in self.opps if o.get("id")}
        self.items = [i for i in (data.get("items") or []) if _is_item(i)]
        self.items_by_id = {i["id"]: i for i in self.items if i.get("id")}
        self.open_items = [i for i in self.items if i.get("status") == "pending"]
        self._build_runs()
        self._build_cutover()
        self._build_admissions()
        self.index = RoleIndex(self.opps, data.get("companies"))
        self._build_groups()
        self._stage_cache = {}
        self._unit_cache = None

    # --- runs (N1) -------------------------------------------------------------------------------
    def _build_runs(self):
        runs = {}
        for r in self.recs:
            rid = r.get("run_id")
            if not rid or r.get("event") == "fired":
                continue
            run = runs.setdefault(rid, {"id": rid, "start": None, "end": None, "planned": None,
                                        "own": [], "last_at": None})
            if r.get("on_behalf_of"):
                continue                       # a close written for a run is not the run's own event
            run["own"].append(r)
            at = _parse_at(r.get("at"))
            if at is not None and (run["last_at"] is None or at > run["last_at"]):
                run["last_at"] = at
            ev = r.get("event")
            if ev == "start":
                run["start"] = r
            elif ev == "end":
                run["end"] = r
            elif ev == "drain" and r.get("phase") == "planned":
                run["planned"] = r
        horizon = self.now - datetime.timedelta(hours=RUN_LIVENESS_HOURS)
        for rid, run in runs.items():
            closed = closed_event(self.recs, rid)
            run["closed"] = closed
            if run["end"] is not None:
                run["over"], run["over_reason"] = True, "end"
            elif run["last_at"] is None or run["last_at"] < horizon:
                run["over"], run["over_reason"] = True, "liveness"
            else:
                run["over"], run["over_reason"] = False, None
            run["done"] = run["over"] or closed is not None
            if closed is not None and not closed.get("on_behalf_of"):
                run["done_at"] = _parse_at(closed.get("at")) or run["last_at"]
            elif run["end"] is not None:
                run["done_at"] = _parse_at(run["end"].get("at")) or run["last_at"]
            elif closed is not None:
                run["done_at"] = _parse_at(closed.get("at")) or run["last_at"]
            else:
                run["done_at"] = run["last_at"]
            st = _parse_at((run["start"] or {}).get("at")) or _parse_at((run["planned"] or {}).get("at"))
            run["start_at"] = st
        self.runs = runs

    # --- the cutover (N15, N22) -------------------------------------------------------------------
    def _build_cutover(self):
        starts = [r for r in self.recs if r.get("event") == "start" and not r.get("on_behalf_of")]
        target = version_tuple(ENGINE_CUTOVER)

        def older(r):
            e = r.get("engine")
            if not e:
                return True
            try:
                return version_tuple(e) < target
            except ValueError:
                return True

        self.cutover_kind, self.cutover = "neg_inf", None
        if any(older(r) for r in starts):
            new = sorted((r for r in starts if not older(r)),
                         key=lambda r: str(r.get("at") or ""))
            new = [r for r in new if _parse_at(r.get("at"))]
            if new:
                self.cutover_kind, self.cutover = "date", _parse_at(new[0]["at"]).date()
            else:
                self.cutover_kind = "pos_inf"
        # engine skew (section 9.1): two engines among the starts of the last SKEW_DAYS days, or a
        # post-cutover start that names none
        recent = [r for r in starts if (_parse_at(r.get("at")) or datetime.datetime.min)
                  >= self.now - datetime.timedelta(days=SKEW_DAYS)]
        versions = set()
        none_after_cutover = False
        for r in recent:
            e = r.get("engine")
            if e:
                versions.add(str(e))
            elif self.cutover_kind == "date" and (_parse_at(r.get("at")) or datetime.datetime.min).date() \
                    >= self.cutover:
                none_after_cutover = True

        def vkey(v):
            try:
                return (0, version_tuple(v))
            except ValueError:
                return (1, (0, 0, 0), v)

        self.skew = []
        if len(versions) >= 2 or none_after_cutover:
            self.skew = sorted(versions, key=vkey) + (["(none)"] if none_after_cutover else [])

    def is_legacy(self, seen):
        """Was a role first seen strictly BEFORE the cutover's date? A role seen on the cutover day is
        not legacy (N22). With no cutover to measure from (-inf) nothing is legacy; while every start
        is older (+inf) everything is; an unknown first-seen date counts as old."""
        if self.cutover_kind == "neg_inf":
            return False
        if self.cutover_kind == "pos_inf":
            return True
        return seen is None or seen < self.cutover

    # --- admissions -------------------------------------------------------------------------------
    def _build_admissions(self):
        planned = []
        for i, r in enumerate(self.recs):
            if r.get("event") == "drain" and r.get("phase") == "planned" and not r.get("on_behalf_of"):
                planned.append((str(r.get("at") or ""), i, r))
        planned.sort(key=lambda t: (t[0], t[1]))
        self.admitted_by = collections.defaultdict(list)       # id -> [run id, oldest first]
        self.planned_order = [t[2] for t in planned]
        for _at, _i, r in planned:
            adm = r.get("admitted") or {}
            for i in list(adm.get("opps") or []) + list(adm.get("items") or []):
                if r["run_id"] not in self.admitted_by[i]:
                    self.admitted_by[i].append(r["run_id"])

    def admissions(self, ids):
        """The distinct run ids that admitted any of `ids`, oldest planned first."""
        order = {r["run_id"]: n for n, r in enumerate(self.planned_order)}
        runs = set()
        for i in ids:
            runs.update(self.admitted_by.get(i, ()))
        return sorted((r for r in runs if r in order), key=lambda r: order[r])

    # --- groups (N6) ------------------------------------------------------------------------------
    def _build_groups(self):
        self.item_key = {}
        self.groups = collections.OrderedDict()               # "item:..." key -> [items, oldest first]
        self.opp_items = collections.defaultdict(list)        # opp id -> [items that are its sightings]
        for it in sorted(self.open_items, key=lambda i: (str(i.get("queued_at") or ""), str(i.get("id")))):
            k = self.index.key(it)
            self.item_key[it["id"]] = k
            if k.startswith("item:") or k not in self.opps_by_id:
                self.groups.setdefault(k, []).append(it)
            else:
                self.opp_items[k].append(it)

    # --- facts ------------------------------------------------------------------------------------
    def attempts(self, opp):
        try:
            return _jd.attempts(opp)
        except _jd.JdReadError as e:
            raise _Unclassified("jd_read: %s" % e)

    def screen(self, opp):
        """`(kind, rules, inputs, on)` of the stored screen, or None when there is none.
        kind is keep | provisional | review | remove."""
        sc = opp.get("screen")
        if sc is None:
            return None
        if not isinstance(sc, dict) or not isinstance(sc.get("verdict"), str):
            raise _Unclassified("screen=%r" % (sc,))
        v = sc["verdict"]
        inputs = sc.get("inputs")
        if inputs is not None and inputs not in ("card", "jd", "candidate"):
            raise _Unclassified("screen.inputs=%r" % (inputs,))
        on = _parse_date(sc.get("on"))
        if v in ("keep", "provisional"):
            return v, (), inputs, on
        m = _SCREEN_RE.match(v)
        if not m:
            raise _Unclassified("screen.verdict=%r" % (v,))
        return m.group(1), tuple(m.group(2).split(",")), inputs, on

    # --- the working-stage mapping ----------------------------------------------------------------
    def run_start_date(self, rid):
        run = self.runs.get(rid)
        st = run["start_at"] if run else None
        return st.date() if st else None

    def outcome(self, rid, ids):
        """How the admission by run `rid` of the role identified by `ids` ENDED: None when it finished,
        else the cause. Only meaningful for a run that is done."""
        run = self.runs[rid]
        closed = run["closed"]
        if closed is not None:
            left = closed.get("left") or {}
            for i in ids:
                if i in left:
                    return left[i]
            return None
        return "cause-not-recorded" if run["end"] is not None else "run-died"

    def retry_stop(self, adm, ids):
        """`(True, text)` when the role's most recent ended admissions are a chain that stops the
        unattended retry (N4), else `(False, "")`. `adm` is the role's admitting runs, oldest first."""
        history = []
        for rid in adm:
            if not self.runs[rid]["done"]:
                continue
            history.append(self.outcome(rid, ids))
        run_chain, role_chain = [], []
        for c in reversed(history):
            if c is not None and CAUSE_CLASS.get(c) == "run":
                run_chain.append(c)
            else:
                break
        for c in reversed(history):
            if c is not None and CAUSE_CLASS.get(c) == "role" and c != "site-not-allowed":
                role_chain.append(c)
            else:
                break
        for chain, need in ((run_chain, RETRY_STOP_RUN_CLASS), (role_chain, RETRY_STOP_ROLE_CLASS)):
            if len(chain) >= need:
                counts = collections.Counter(chain)
                text = ", ".join("%s ×%d" % (c, n) for c, n in
                                 sorted(counts.items(), key=lambda t: (-t[1], t[0])))
                return True, text
        return False, ""

    def working(self, progress, ids, seen, key, latest_attempt, rules_changed=False):
        """Turn a role's PROGRESS stage into what a surface shows (section 2.2, "the admission rule").

        `rules_changed` is True for a role that is at `read` only because its stored screen is stale against
        today's profile. An admission that FINISHED it was about the old rules, so it is dropped (and with it
        the history before it): the owner editing their profile does not turn a finished admission into
        `cause-not-recorded`. What remains is admissions that left it unfinished, which are real failures,
        or nothing, and then the role is `waiting` with `detail == "rules-changed"`, never `legacy-backlog`."""
        adm = self.admissions(ids)
        if rules_changed:
            last_finished = -1
            for n, rid in enumerate(adm):
                if self.runs[rid]["done"] and self.outcome(rid, ids) is None:
                    last_finished = n
            adm = adm[last_finished + 1:]
        returned = False
        if latest_attempt is not None and latest_attempt["outcome"] == "read" \
                and latest_attempt["via"] == "candidate":
            at = _jd.parse_at(latest_attempt["at"])
            if not adm:
                returned = True
            else:
                done_at = self.runs[adm[-1]]["done_at"]
                returned = self.runs[adm[-1]]["done"] and (done_at is None or at > done_at)
        if adm:
            last = self.runs[adm[-1]]
            if not last["done"]:
                return Stage(progress, False, self.run_start_date(adm[-1]), None, "", key)
            if returned:
                return Stage("waiting", False, seen, None, "returned", key)
            since = self.run_start_date(adm[0]) or seen
            cause = self.outcome(adm[-1], ids) or "cause-not-recorded"
            stop, text = self.retry_stop(adm, ids)
            if stop:
                return Stage(PROGRESS_TO_FAILURE[progress], True, since, "retry-stopped", text, key)
            return Stage(PROGRESS_TO_FAILURE[progress], True, since, cause, "", key)
        if returned:
            return Stage("waiting", False, seen, None, "returned", key)
        if rules_changed:
            return Stage("waiting", False, seen, None, "rules-changed", key)
        if self.is_legacy(seen):
            return Stage(PROGRESS_TO_FAILURE[progress], True, seen, "legacy-backlog", "", key)
        return Stage("waiting", False, seen, None, "", key)

    # --- stage of an opportunity ------------------------------------------------------------------
    def opp_ids(self, opp):
        ids = [opp.get("id")]
        cap = opp.get("capture")
        if isinstance(cap, dict) and cap.get("item"):
            ids.append(cap["item"])
        return [i for i in ids if i]

    def rules_stale(self, opp):
        """Is the role's stored screen title- or comp-stale against today's merged profile? False with no
        profile (an unreadable one included), so a profile that cannot be read never makes every screen look
        stale. Cheap: the hashes are of one profile built once per snapshot, never one per role."""
        prof = self.profile
        if prof is None:
            return False
        import profile as _pf
        try:
            return bool(_pf.screen_is_title_stale(opp.get("screen"), prof)
                        or _pf.screen_is_comp_stale(opp.get("screen"), opp, prof))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise _Unclassified("screen staleness cannot be read: %s" % e)

    def settled_or_progress(self, opp):
        """`(Stage, None)` when a Step-1 row matches, else `(None, progress)`. Raises `_Unclassified`.
        A role whose screen is stale (`rules_stale`) is `(None, "read")` here, so the one re-screen path
        (`record.py read-batch`) and `close_result` see it as unfinished."""
        st, progress, _stale = self._settle(opp)
        return st, progress

    def _settle(self, opp):
        """`(Stage, None, False)`, or `(None, progress, rules_changed)`: `rules_changed` is True only when
        the role is at `read` BECAUSE its stored screen is stale."""
        key = str(opp.get("id") or "")
        if _pidx.is_folded(opp):
            return Stage("folded", False, None, None, str(opp.get("duplicate_of")), key), None, False
        status, verdict = opp.get("status"), opp.get("verdict")
        if status not in OPP_STATUSES:
            raise _Unclassified("status=%r" % (status,))
        if verdict is not None and verdict not in OPP_VERDICTS:
            raise _Unclassified("verdict=%r" % (verdict,))
        if status not in NON_TERMINAL_STATUSES or opp.get("stage") == "closed" or verdict == "pass":
            return Stage("ended", False, None, None, "", key), None, False
        apps = opp.get("_applications") or ()
        if (verdict in ("pursue", "parked") or status in LIVE_OPP_STATUSES
                or any(a.get("status") in SUBMITTED_APP_STATUS for a in apps)):
            return Stage("decided", False, None, None, "", key), None, False
        atts = self.attempts(opp)
        latest = _jd.latest_of(atts)
        reads = sorted((a for a in atts if a["outcome"] == "read"), key=lambda a: a["at"])
        latest_read = reads[-1] if reads else None
        legacy_read = latest_read is not None and latest_read["via"] == "legacy"
        sc = self.screen(opp)
        trusted_input = False                      # is the stored screen a JD-input screen?
        stale_removal = False
        if sc is not None:
            kind, rules, inputs, on = sc
            if inputs in ("jd", "candidate"):
                read_day = _jd.parse_at(latest_read["at"]).date() if latest_read else None
                trusted_input = latest_read is not None and (on is None or read_day is None
                                                             or on >= read_day)
            elif inputs is None:
                trusted_input = legacy_read
            # (card: never)
            if kind == "remove":
                if (inputs in ("jd", "candidate") or inputs is None
                        or all(r in CARD_SAFE_RULES for r in rules)):
                    if not self.rules_stale(opp):
                        return Stage("removed", False, None, None, ",".join(rules), key), None, False
                    stale_removal = True           # removed under other rules: re-screen it, do not trust it
        if latest is not None and latest["outcome"] != "read":
            cls = _jd.outcome_class(latest["outcome"])
            since = _jd.parse_at(latest["at"]).date()
            text = str((latest["evidence"] or {}).get("text") or (latest["evidence"] or {}).get("legacy") or "")
            if cls == "terminal":
                return Stage("gone", False, since, latest["outcome"], text, key), None, False
            if cls == "candidate":
                return Stage("your-read", False, since, latest["outcome"], text, key), None, False
        if latest_read is None:
            return None, ("captured" if not atts else "reading"), False
        if stale_removal:
            return None, "read", True
        if sc is not None and trusted_input:
            kind = sc[0]
            if kind in ("review", "keep") and self.rules_stale(opp):
                return None, "read", True          # computed under other title/comp rules: not screened
            if kind == "review":
                return Stage("ready", False, None, None, ",".join(sc[1]), key), None, False
            if kind == "keep":
                read_day = _jd.parse_at(latest_read["at"]).date()
                if self.researched(opp, read_day):
                    return Stage("ready", False, None, None, "", key), None, False
                return None, "screened", False
        return None, "read", False

    @staticmethod
    def researched(opp, read_day):
        fit = opp.get("fit")
        if not isinstance(fit, dict):
            return False
        req = fit.get("requirements")
        on = _parse_date(fit.get("analyzed_on"))
        return bool(isinstance(req, list) and req and on is not None and read_day is not None
                    and on >= read_day)

    def stage_of_opp(self, opp):
        k = ("opp", opp.get("id"), id(opp))
        if k in self._stage_cache:
            return self._stage_cache[k]
        key = str(opp.get("id") or "")
        try:
            st, progress, stale = self._settle(opp)
            if st is None:
                atts = self.attempts(opp)
                st = self.working(progress, self.opp_ids(opp), first_seen(opp), key,
                                  _jd.latest_of(atts), rules_changed=stale)
        except _Unclassified as e:
            st = Stage("unclassified", True, first_seen(opp), "unclassified", e.detail, key)
        self._stage_cache[k] = st
        return st

    # --- stage of an item group -------------------------------------------------------------------
    def stage_of_group(self, key):
        k = ("group", key)
        if k in self._stage_cache:
            return self._stage_cache[k]
        items = self.groups[key]
        ids = [i["id"] for i in items]
        seen = min((d for d in (_item_first_seen(i) for i in items) if d), default=None)
        st = self.working("admitted", ids, seen, key, None)
        self._stage_cache[k] = st
        return st

    def stage_of_item(self, item):
        k = self.item_key.get(item.get("id"))
        if k is None:
            k = self.index.key(item)
        if k in self.opps_by_id and not k.startswith("item:"):
            return self.stage_of_opp(self.opps_by_id[k])
        if k in self.groups:
            return self.stage_of_group(k)
        raise LifecycleError("capture item %r is not an open item of this snapshot" % item.get("id"))

    # --- units ------------------------------------------------------------------------------------
    def units(self):
        if self._unit_cache is None:
            out = []
            for o in self.opps:
                st = self.stage_of_opp(o)
                rows = [o] + list(self.opp_items.get(o.get("id"), ()))
                out.append(Unit(st.key, rows, st, st.name == "folded"))
            for k, items in self.groups.items():
                out.append(Unit(k, list(items), self.stage_of_group(k), False))
            self._unit_cache = out
        return self._unit_cache

    def unit_ids(self, unit):
        """The ids a drain plan admits for this role, as `(opps, items)`."""
        if unit.key in self.groups:
            return [], [i["id"] for i in unit.rows]
        return [unit.key], []


def context(data, now):
    """The `Ctx` for a snapshot at `now` (a datetime or date, passed in and never read from the clock)."""
    return Ctx(data, now)


def stage(row, ctx):
    """The `Stage` of one opportunity row or one OPEN capture item. An item that is a sighting of a
    known role has that role's stage."""
    if _is_item(row):
        return ctx.stage_of_item(row)
    return ctx.stage_of_opp(row)


def pipeline(data, now):
    """`[(row, Stage)]` for every opportunity AND every open capture item. A row no stage rule
    matches is `Stage("unclassified", failure=True, ...)`, never an exception (N6)."""
    ctx = Ctx(data, now)
    out = [(o, ctx.stage_of_opp(o)) for o in ctx.opps]
    out += [(i, ctx.stage_of_item(i)) for i in ctx.open_items]
    return out


def roles(data, now):
    """`[Unit]`: one per ROLE (N6). Every count a surface prints is a count of these."""
    return Ctx(data, now).units()


def watch_missing(opp):
    """`[]` when the role's stage, read WITHOUT journal context, is `ready` or `decided`; else
    `[stage name]`. The one input `posting_check.in_watch_list` takes."""
    ctx = Ctx({"opportunities": [opp], "journal": [], "items": [], "companies": [], "config": {}},
              datetime.datetime(2000, 1, 1))
    st = ctx.stage_of_opp(opp)
    return [] if st.name in ("ready", "decided") else [st.name]


# ----------------------------------------------------------------------------------------------
# intake: the plan (IN1, N2, N7, N8)
# ----------------------------------------------------------------------------------------------

def _setting(cfg, key):
    try:
        return _ck.describe(cfg, key)[0]
    except KeyError:
        return None


def intake_setting(cfg):
    """`search.intake_per_run` (1..300, default 40)."""
    v = _setting(cfg, INTAKE_KEY)
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 300 else 40


def new_percent_setting(cfg):
    """`search.intake_new_percent` (0..100, default 50)."""
    v = _setting(cfg, INTAKE_NEW_PERCENT_KEY)
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 else 50


def per_role_s(recs):
    """`(seconds, source)`: the median `per_role_s` of this profile's last PER_ROLE_WINDOW own `closed`
    events with `finished >= PER_ROLE_MIN_FINISHED` (source `measured`), else PER_ROLE_S_DEFAULT
    (source `default estimate`) until that many exist (N7)."""
    rows = [r for r in recs if r.get("event") == "drain" and r.get("phase") == "closed"
            and not r.get("on_behalf_of") and isinstance(r.get("per_role_s"), (int, float))
            and (r.get("finished") or 0) >= PER_ROLE_MIN_FINISHED]
    rows.sort(key=lambda r: str(r.get("at") or ""))
    rows = rows[-PER_ROLE_WINDOW:]
    if len(rows) < PER_ROLE_WINDOW:
        return PER_ROLE_S_DEFAULT, "default estimate"
    vals = sorted(r["per_role_s"] for r in rows)
    mid = vals[len(vals) // 2]
    return max(1, int(round(mid))), "measured"


class Plan(object):
    """What one run admits (section 4.5). `event_fields()` is the `drain planned` event."""

    def __init__(self, **kw):
        self.run_id = None
        self.intake = 0
        self.capacity = 0
        self.capacity_reason = None
        self.render_route = "yes"
        self.attended = False
        self.admitted_opps = []
        self.admitted_items = []
        self.fanout = DRAIN_FANOUT
        self.solo = []
        self.fetch_calls = 0
        self.reserved_new = 0
        self.admitted_by_class = {c: 0 for c in ADMISSION_CLASSES}
        self.excluded_open = {}
        self.waiting_count = 0
        self.waiting_oldest = None
        self.legacy_count = 0
        self.legacy_oldest = None
        self.retry_stopped = []
        self.per_role_s = PER_ROLE_S_DEFAULT
        self.per_role_source = "default estimate"
        self.available = 0
        self.for_fetch = 0
        self.__dict__.update(kw)

    @property
    def admitted(self):
        return {"opps": list(self.admitted_opps), "items": list(self.admitted_items)}

    @property
    def admitted_roles(self):
        return self.admitted_by_class_total()

    def admitted_by_class_total(self):
        return sum(self.admitted_by_class.values())

    def event_fields(self):
        """The keyword arguments `journal.record_drain(root, run_id, "planned", **fields)` takes."""
        return dict(intake=self.intake, capacity=self.capacity, capacity_reason=self.capacity_reason,
                    render_route=self.render_route, attended=self.attended, admitted=self.admitted,
                    waiting={"count": self.waiting_count,
                             "oldest": self.waiting_oldest.isoformat() if self.waiting_oldest else None},
                    retry_stopped=list(self.retry_stopped), fanout=self.fanout, solo=list(self.solo),
                    fetch_calls=self.fetch_calls, reserved_new=self.reserved_new,
                    admitted_by_class=dict(self.admitted_by_class),
                    excluded_open=dict(self.excluded_open))

    def lines(self):
        """The text `lifecycle.py --drain-plan` prints. `fanout: N` is what B8's prose reads."""
        n = self.admitted_by_class_total()
        out = ["drain-plan run=%s intake=%d capacity=%d render-route=%s attended=%s"
               % (self.run_id, self.intake, self.capacity, self.render_route,
                  "yes" if self.attended else "no")]
        out.append("admitted %d roles (%d new · %d retry · %d returned · %d legacy) "
                   "· reserved_new %d" % (n, self.admitted_by_class["new"],
                                              self.admitted_by_class["retry"],
                                              self.admitted_by_class["returned"],
                                              self.admitted_by_class["legacy"], self.reserved_new))
        out.append("fanout: %d" % self.fanout)
        out.append("fetch_calls: %d" % self.fetch_calls)
        out.append("solo: %s" % (",".join(self.solo) if self.solo else "-"))
        if self.capacity_reason == "no-render-route":
            out.append("capacity 0: no render route on this surface; run on the desktop")
        elif self.capacity_reason == "time-bound":
            out.append("intake capped at %d of %d by measured time (%d s/role, %s)"
                       % (self.capacity, self.intake, self.per_role_s, self.per_role_source))
        for run, n_ex in sorted(self.excluded_open.items()):
            out.append("excluded %d held by open run %s" % (n_ex, run))
        out.append("waiting: %d%s · legacy backlog: %d%s" % (
            self.waiting_count,
            " (oldest %s)" % self.waiting_oldest.isoformat() if self.waiting_oldest else "",
            self.legacy_count,
            " (oldest %s)" % self.legacy_oldest.isoformat() if self.legacy_oldest else ""))
        if self.retry_stopped:
            out.append("retry-stopped: %s" % ",".join(self.retry_stopped))
        return out


def _yes_no(value):
    if value in (True, "yes"):
        return "yes"
    if value in (False, "no"):
        return "no"
    raise LifecycleError("render route must be yes or no, got %r" % (value,))


def drain_plan(data, now, intake=None, render_route="yes", attended=False, run_id=None):
    """What this run admits, in order (section 4.5, N2, N7, N8). Pure: it writes nothing; the CLI
    appends the `planned` event under the write lock.

      capacity   min(intake, floor(DRAIN_BUDGET_S / per_role_s)), and 0 with no render route
      reserve    S = ceil(capacity x intake_new_percent / 100) slots go to NEW roles first while the
                 legacy backlog is non-empty (ruling 8); unused slots fall through
      order      ADMISSION_ORDER (retry, returned, legacy, new), oldest first within a class; the
                 reservation is applied before it
      exclusion  an id another OPEN run's plan already admitted is never admitted again (N2)
    """
    ctx = Ctx(data, now)
    cfg = ctx.cfg
    intake = intake_setting(cfg) if intake is None else intake
    if not isinstance(intake, int) or isinstance(intake, bool) or not 1 <= intake <= 300:
        raise LifecycleError("intake must be an integer 1..300, got %r" % (intake,))
    route = _yes_no(render_route)
    pct = new_percent_setting(cfg)
    prs, prs_src = per_role_s(ctx.recs)
    plan = Plan(run_id=run_id, intake=intake, render_route=route, attended=bool(attended),
                per_role_s=prs, per_role_source=prs_src)
    # --- who holds what right now: ids admitted by another OPEN run (N2) ---
    held = {}
    for r in ctx.planned_order:
        other = r["run_id"]
        if other == run_id or ctx.runs[other]["done"]:
            continue
        adm = r.get("admitted") or {}
        for i in list(adm.get("opps") or []) + list(adm.get("items") or []):
            held.setdefault(i, other)
    # --- candidates ---
    buckets = {c: [] for c in ADMISSION_CLASSES}
    waiting_left, legacy_left, stopped = [], [], []
    for u in ctx.units():
        st = u.stage
        if u.folded or st.name == "unclassified":
            continue
        if st.name == "waiting":
            cls = "returned" if st.detail == "returned" else "new"
        elif st.failure and st.cause == "legacy-backlog":
            cls = "legacy"
        elif st.failure:
            if st.cause == "retry-stopped":
                stopped.append(u.key)
                if not attended:
                    continue
            if st.cause == "site-not-allowed" and not attended:
                continue
            cls = "retry"
        else:
            continue
        opp_ids, item_ids = ctx.unit_ids(u)
        ids = opp_ids + item_ids + [i for o in opp_ids for i in ctx.opp_ids(ctx.opps_by_id[o])[1:]]
        holder = next((held[i] for i in ids if i in held), None)
        if holder is not None:
            plan.excluded_open[holder] = plan.excluded_open.get(holder, 0) + 1
            continue
        buckets[cls].append((st.since or ctx.today, u.key, u))
    for c in buckets:
        buckets[c].sort(key=lambda t: (t[0], t[1]))
    plan.retry_stopped = sorted(stopped)
    plan.available = sum(len(b) for b in buckets.values())
    # --- capacity ---
    time_cap = DRAIN_BUDGET_S // prs
    if route == "no":
        plan.capacity, plan.capacity_reason = 0, "no-render-route"
    elif time_cap < intake:
        plan.capacity, plan.capacity_reason = max(time_cap, 0), "time-bound"
    else:
        plan.capacity = intake
    cap = plan.capacity
    plan.reserved_new = int(math.ceil(cap * pct / 100.0)) if buckets["legacy"] else 0
    # --- admit ---
    chosen = []                                             # (class, unit)

    def take(cls, limit):
        n = 0
        while buckets[cls] and n < limit and len(chosen) < cap:
            chosen.append((cls, buckets[cls].pop(0)[2]))
            n += 1
        return n

    if buckets["legacy"]:
        take("new", plan.reserved_new)
        for cls in ADMISSION_ORDER:
            take(cls, cap)
    else:
        for cls in ADMISSION_ORDER:
            take(cls, cap)
    for cls, u in chosen:
        plan.admitted_by_class[cls] += 1
        o, i = ctx.unit_ids(u)
        plan.admitted_opps += o
        plan.admitted_items += i
        st = u.stage
        if cls == "retry" and st.cause in RUN_CLASS_CAUSES:
            plan.solo.append(u.key)
        if cls != "returned" and not _has_read(u, ctx):
            plan.for_fetch += 1
    plan.fetch_calls = int(math.ceil(plan.for_fetch * FETCH_WORST_CASE_S / float(FETCH_CALL_S)))
    left = [u for b in buckets.values() for (_s, _k, u) in b]
    wait = [u for u in left if u.stage.name == "waiting"]
    leg = [u for u in left if u.stage.cause == "legacy-backlog"]
    plan.waiting_count = len(wait)
    plan.waiting_oldest = min((u.stage.since for u in wait if u.stage.since), default=None)
    plan.legacy_count = len(leg)
    plan.legacy_oldest = min((u.stage.since for u in leg if u.stage.since), default=None)
    return plan


def _has_read(unit, ctx):
    if unit.key in ctx.groups:
        return False
    try:
        return any(a["outcome"] == "read" for a in ctx.attempts(ctx.opps_by_id[unit.key]))
    except _Unclassified:
        return False


# ----------------------------------------------------------------------------------------------
# close: did every admitted role finish? (IN2, N1, N7)
# ----------------------------------------------------------------------------------------------

class CloseResult(object):
    def __init__(self):
        self.admitted = 0
        self.finished = 0
        self.left = {}
        self.tally = collections.Counter()
        self.waiting_count = 0
        self.waiting_oldest = None
        self.elapsed_s = None
        self.per_role_s = None

    def summary_line(self, now_age_days=None):
        t = self.tally
        causes = collections.Counter(self.left.values())
        # A sighting folded into a role already known (`linked`) is admitted and finished like any
        # other; it is named whenever there is one, so the breakdown always adds up to `finished`.
        folded = " · %d folded" % t["linked"] if t["linked"] else ""
        out = ("drain: %d admitted · %d finished (%d ready · %d removed · %d gone · "
               "%d your-read%s) · %d left%s · %d waiting%s"
               % (self.admitted, self.finished, t["ready"], t["removed"], t["gone"], t["your-read"],
                  folded,
                  len(self.left),
                  " (%s)" % ", ".join("%s %d" % (c, n) for c, n in sorted(causes.items()))
                  if self.left else "", self.waiting_count,
                  " (oldest %dd)" % now_age_days if now_age_days else ""))
        return out


def _agent_rows(recs, run_id, kinds):
    ids = set()
    for r in recs:
        if (r.get("event") == "pass" and r.get("run_id") == run_id and r.get("kind") in kinds
                and r.get("phase") == "dispatched"):
            ids.update(r.get("ids") or [])
    return ids


def close_result(data, run_id, now, by=None):
    """Which roles `run_id` admitted did not finish, and why (section 4.5, N1). `by=None` is the run's
    own close; `by=<other run>` is a close written on its behalf, which raises `LifecycleError` unless
    the run is over (N1): a run with an event of its own inside the window is never closed by anyone
    else."""
    ctx = Ctx(data, now)
    run = ctx.runs.get(run_id)
    if run is None or run["planned"] is None:
        raise LifecycleError("run %r has no drain plan on record" % run_id)
    if by is not None and by != run_id and not run["over"]:
        raise LifecycleError(
            "run %r is not over (its own latest event is inside the %d-hour window and it has no end "
            "event), so run %r may not close it on its behalf" % (run_id, RUN_LIVENESS_HOURS, by))
    res = CloseResult()
    adm = run["planned"].get("admitted") or {}
    recs = ctx.recs
    capture_unreached = set()
    for r in recs:
        if (r.get("event") == "pass" and r.get("run_id") == run_id and r.get("kind") == "capture"
                and r.get("phase") == "done"):
            capture_unreached = set(r.get("unreached") or [])        # the LAST capture pass wins
    dispatched = _agent_rows(recs, run_id, ("reader", "research"))
    gap_scopes = {g.get("scope") for g in recs if g.get("event") == "gap" and g.get("run_id") == run_id}

    def settled_name(opp):
        st, _p = ctx.settled_or_progress(opp)
        return st.name if st is not None else None

    for oid in adm.get("opps") or []:
        res.admitted += 1
        opp = ctx.opps_by_id.get(oid)
        name = None
        if opp is not None:
            try:
                name = settled_name(opp)
            except _Unclassified:
                name = None
        if name is not None:
            res.finished += 1
            res.tally[name] += 1
            continue
        res.left[oid] = _left_cause(ctx, run, oid, opp, by, capture_unreached, dispatched, gap_scopes)
    for iid in adm.get("items") or []:
        res.admitted += 1
        item = ctx.items_by_id.get(iid)
        done_as = (item or {}).get("closed_as") if item and item.get("status") == "done" else None
        name = None
        if done_as and ":" in str(done_as):
            kind, _, target = str(done_as).partition(":")
            opp = ctx.opps_by_id.get(target)
            if kind == "linked" and opp is not None:
                name = "linked"
            elif kind == "created" and opp is not None:
                try:
                    name = settled_name(opp)
                except _Unclassified:
                    name = None
        if name is not None:
            res.finished += 1
            res.tally[name] += 1
            continue
        res.left[iid] = _left_cause(ctx, run, iid, None, by, capture_unreached, dispatched, gap_scopes,
                                    item=item)
    others = [u for u in ctx.units() if u.stage.name == "waiting"]
    res.waiting_count = len(others)
    oldest = min((u.stage.since for u in others if u.stage.since), default=None)
    res.waiting_oldest = (ctx.today - oldest).days if oldest else None
    start = run["planned"].get("at")
    st_at = _parse_at(start)
    if by is None and st_at is not None:
        res.elapsed_s = max(0, int((ctx.now - st_at).total_seconds()))
        res.per_role_s = round(res.elapsed_s / float(res.admitted), 1) if res.admitted else None
    return res


def _left_cause(ctx, run, rid_, opp, by, capture_unreached, dispatched, gap_scopes, item=None):
    """The cause of one admitted role left unfinished. On behalf of a dead run (`by`): its latest
    host-class attempt outcome, else `run-died` (N1)."""
    host = None
    if opp is not None:
        try:
            for a in reversed(ctx.attempts(opp)):
                if a["run"] == run["id"] and _jd.outcome_class(a["outcome"]) == "host":
                    host = a["outcome"]
                    break
        except _Unclassified:
            pass
    if host:
        return host
    if by is not None:
        return "run-died"
    if "jobsearch:capture-item:%s" % rid_ in gap_scopes:
        return "capture-refused"
    if rid_ in capture_unreached:
        return "deadline-reached"
    if rid_ in dispatched:
        return "agent-returned-nothing"
    return "not-dispatched"


def drain_close(data, run_id, now, by=None):
    """`{admitted id: cause}` for every role `run_id` admitted that is not at a settled stage.
    See `close_result` for the tally and for the rule on `by`."""
    return close_result(data, run_id, now, by=by).left


# ----------------------------------------------------------------------------------------------
# the report: the only text any surface prints about process state (LC2)
# ----------------------------------------------------------------------------------------------

class Report(object):
    """Counts and strings. Surfaces print the strings and never recompute the counts."""

    def __init__(self):
        self.counts = collections.Counter()          # stage name -> roles
        self.totals = {}
        self.failure = 0
        self.failure_oldest = None
        self.failure_causes = collections.OrderedDict()
        self.failure_ids = collections.OrderedDict()   # cause -> [role keys]
        self.failure_roles = []                       # (key, Stage)
        self.waiting = 0
        self.waiting_oldest = None
        self.legacy = 0
        self.legacy_oldest = None
        self.in_progress = 0
        self.ready = 0
        self.your_read = 0
        self.unclassified = 0
        self.folded = 0
        self.mismatch = False
        self.coverage_rows = []
        self.coverage = {}
        self.skew = []
        self.intake = 40
        self.reserved_new = 0
        self.no_render_route = False
        self.open_runs = []
        self.overlong_runs = []                      # C7: open runs older than LONGEST_RUN_S (not in to_json)
        self.partial_kinds = []
        self.headline = ""
        self.start_line = ""
        self.block_lines = []
        self.conservation_line = ""
        self.run_lines = []

    @property
    def partial_text(self):
        return ", ".join(self.partial_kinds)

    def to_json(self):
        return {"counts": dict(self.counts), "totals": self.totals, "failure": self.failure,
                "failure_oldest": self.failure_oldest, "failure_causes": dict(self.failure_causes),
                "waiting": self.waiting, "waiting_oldest": self.waiting_oldest,
                "legacy": self.legacy, "legacy_oldest": self.legacy_oldest,
                "ready": self.ready, "your_read": self.your_read, "in_progress": self.in_progress,
                "unclassified": self.unclassified, "folded": self.folded, "mismatch": self.mismatch,
                "did_not_look": self.coverage_rows, "skew": self.skew, "intake": self.intake,
                "reserved_new": self.reserved_new, "partial": self.partial_kinds,
                "open_runs": self.open_runs, "headline": self.headline,
                "start_line": self.start_line, "block_lines": self.block_lines,
                "conservation_line": self.conservation_line}


def raw_role_count(data, units=None):
    """The runtime total, counted INDEPENDENTLY of `pipeline()` (N6): the non-blank lines of
    `opportunities.jsonl` that name no `duplicate_of`, plus the distinct `item:` keys among the open
    capture items. Returns `(count, source)`; `source` is `file` when the line count came off disk
    (the profile `root` is in `data`) and `snapshot` when it could only be taken from the loaded rows."""
    root, path, n = data.get("root"), None, None
    if root:
        path = os.path.join(root, "data", "opportunities.jsonl")
        if os.path.exists(path):
            n = 0
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        n += 1                       # an unreadable line is still a row the file holds
                        continue
                    if not (isinstance(row, dict) and row.get("duplicate_of")):
                        n += 1
    source = "file"
    if n is None:
        n = sum(1 for o in data.get("opportunities") or [] if isinstance(o, dict) and not o.get("duplicate_of"))
        source = "snapshot"
    opps = [o for o in data.get("opportunities") or [] if isinstance(o, dict)]
    idx = RoleIndex(opps, data.get("companies"))
    keys = set()
    for it in data.get("items") or []:
        if _is_item(it) and it.get("status") == "pending":
            k = idx.key(it)
            if k.startswith("item:"):
                keys.add(k)
    return n + len(keys), source


def _elapsed_s(start, now):
    """Real seconds from `start` to `now`, DST-safe (C7, round-2 M5). The journal's `at` and `now` are
    NAIVE local datetimes, so subtracting them directly is off by an hour across a DST change; both are
    converted to UTC first (a naive value is read as the machine's local time). An hour that happens twice
    is read as its first occurrence, so the one remaining error is at most an hour inside that ambiguous
    hour, which is accepted."""
    utc = datetime.timezone.utc
    return (now.astimezone(utc) - start.astimezone(utc)).total_seconds()


def process_report(data, now, generating_run=None):
    """The `Report` every surface prints (section 2.4, N6, N8, N14, SUM1).

    `generating_run` is the id of the run that is producing the page being rendered (C7, round-2 S5). That
    run is open by definition, so it is left out of `overlong_runs`: a long healthy daily run must not alert
    about itself on the page it writes. It stays in `open_runs`."""
    ctx = Ctx(data, now)
    rep = Report()
    today = ctx.today
    rep.skew = list(ctx.skew)
    rep.intake = intake_setting(ctx.cfg)
    pct = new_percent_setting(ctx.cfg)
    rep.reserved_new = int(math.ceil(rep.intake * pct / 100.0))
    for u in ctx.units():
        st = u.stage
        if u.folded:
            rep.folded += 1
            continue
        if st.name == "unclassified":
            rep.unclassified += 1
            rep.counts["unclassified"] += 1
            rep.failure_roles.append((u.key, st))
            continue
        rep.counts[st.name] += 1
        if st.failure:
            rep.failure += 1
            rep.failure_causes[st.cause] = rep.failure_causes.get(st.cause, 0) + 1
            rep.failure_ids.setdefault(st.cause, []).append(u.key)
            rep.failure_roles.append((u.key, st))
            if st.cause == "legacy-backlog":
                rep.legacy += 1
        elif st.name == "waiting":
            rep.waiting += 1
        elif st.name in PROGRESS_STAGES:
            rep.in_progress += 1
    rep.ready, rep.your_read = rep.counts["ready"], rep.counts["your-read"]

    def oldest(pred):
        ages = [_age(st.since, today) for (_k, st) in
                [(u.key, u.stage) for u in ctx.units() if not u.folded] if pred(st)
                and st.since is not None]
        return max(ages) if ages else None

    rep.failure_oldest = oldest(lambda s: s.failure and s.name != "unclassified")
    rep.waiting_oldest = oldest(lambda s: s.name == "waiting")
    rep.legacy_oldest = oldest(lambda s: s.failure and s.cause == "legacy-backlog")
    rep.failure_causes = collections.OrderedDict(
        sorted(rep.failure_causes.items(), key=lambda t: (-t[1], t[0])))
    staged = (rep.counts["waiting"] + rep.in_progress + rep.failure + rep.your_read + rep.ready
              + rep.counts["decided"] + rep.counts["removed"] + rep.counts["gone"]
              + rep.counts["ended"] + rep.unclassified)
    raw, raw_source = raw_role_count(data)
    rep.mismatch = raw != staged
    rep.totals = {"roles": staged, "raw": raw, "raw_source": raw_source, "folded": rep.folded,
                  "unclassified": rep.unclassified, "staged": staged}
    # --- coverage, runs, intake wording ---
    rep.coverage_rows = _coverage.not_looked(data, ctx.now)
    rep.coverage = {k: list(v) for k, v in _coverage.summary(rep.coverage_rows).items()}
    plans = [r for r in ctx.planned_order]
    rep.no_render_route = bool(plans and plans[-1].get("capacity_reason") == "no-render-route")
    for run in sorted(ctx.runs.values(), key=lambda r: str(r["start_at"] or "")):
        if run["start"] is not None and not run["over"]:
            hrs = (ctx.now - run["last_at"]).total_seconds() / 3600.0 if run["last_at"] else None
            rep.open_runs.append({"run_id": run["id"],
                                  "since": run["start_at"].replace(microsecond=0).isoformat(" ")
                                  if run["start_at"] else None,
                                  "last_event_hours": None if hrs is None else int(hrs)})
            if run["id"] != generating_run:
                open_s = (None if run["start_at"] is None
                          else _elapsed_s(run["start_at"], ctx.now))
                if open_s is None or open_s > LONGEST_RUN_S:
                    rep.overlong_runs.append({"run_id": run["id"], "open_s": open_s})
    # --- PARTIAL (SUM1) ---
    cov = _coverage.summary(rep.coverage_rows)
    if "feed" in cov:
        rep.partial_kinds.append("feeds")
    if "mail" in cov:
        rep.partial_kinds.append("mail")
    last_close = [r for r in ctx.recs if r.get("event") == "drain" and r.get("phase") == "closed"]
    if last_close and (sorted(last_close, key=lambda r: str(r.get("at") or ""))[-1].get("left")):
        rep.partial_kinds.append("drain")
    # --- the strings ---
    _compose(rep, ctx)
    return rep


def _compose(rep, ctx):
    f_oldest = " (oldest %dd)" % rep.failure_oldest if rep.failure_oldest is not None else ""
    seg_fail = "PROCESS FAILURE: %s" % _fmt_n(rep.failure)
    if rep.failure:
        causes = ", ".join("%s %s" % (c, _fmt_n(n)) for c, n in rep.failure_causes.items())
        seg_fail += " (oldest %dd: %s)" % (rep.failure_oldest or 0, causes)
    w_old = " (oldest %dd)" % rep.waiting_oldest if rep.waiting_oldest is not None else ""
    seg_wait = "WAITING FOR INTAKE: %s%s" % (_fmt_n(rep.waiting), w_old)
    if rep.no_render_route:
        seg_wait += " — no render route on this surface; run on the desktop"
    parts = ["PIPELINE %s ready · %s your read" % (_fmt_n(rep.ready), _fmt_n(rep.your_read)),
             seg_fail, seg_wait]
    if rep.legacy:
        l_old = " (oldest %dd)" % rep.legacy_oldest if rep.legacy_oldest is not None else ""
        parts.append("LEGACY BACKLOG: %s%s" % (_fmt_n(rep.legacy), l_old))
    parts.append("intake %d/run%s" % (rep.intake, _reserve_text(rep)))
    if rep.unclassified:
        parts.append("UNCLASSIFIED: %s" % _fmt_n(rep.unclassified))
    if rep.mismatch:
        parts.append(_mismatch_text(rep))
    dnl = _coverage.describe(rep.coverage_rows)
    if dnl:
        parts.append("DID NOT LOOK: %s" % dnl)
    if rep.skew:
        parts.append("ENGINE SKEW: %s" % ", ".join(rep.skew))
    rep.start_line = " · ".join(parts)
    head = []
    if rep.failure:
        head.append("PROCESS FAILURE: %s%s" % (_fmt_n(rep.failure), f_oldest))
    if rep.waiting:
        head.append("WAITING: %s" % _fmt_n(rep.waiting))
    if rep.unclassified:
        head.append("UNCLASSIFIED: %s" % _fmt_n(rep.unclassified))
    if rep.mismatch:
        head.append(_mismatch_text(rep))
    if dnl:
        head.append("DID NOT LOOK: %s" % dnl)
    rep.headline = "".join(" · " + h for h in head)
    c = rep.counts
    rep.conservation_line = (
        "ROLES %s = waiting %s + in progress %s + FAILURE %s + your read %s + ready %s + decided %s "
        "+ removed %s + gone %s + ended %s + UNCLASSIFIED %s"
        % (_fmt_n(rep.totals["roles"]), _fmt_n(rep.waiting), _fmt_n(rep.in_progress),
           _fmt_n(rep.failure), _fmt_n(rep.your_read), _fmt_n(rep.ready), _fmt_n(c["decided"]),
           _fmt_n(c["removed"]), _fmt_n(c["gone"]), _fmt_n(c["ended"]), _fmt_n(rep.unclassified)))
    if rep.folded:
        rep.conservation_line += " (+ %s folded duplicates)" % _fmt_n(rep.folded)
    lines = []
    lines.append("Process failure: %s roles%s" % (_fmt_n(rep.failure), f_oldest))
    for cause, n in rep.failure_causes.items():
        lines.append("  %s %s: %s — %s" % (cause, _fmt_n(n), CAUSE_MEANING.get(cause, ""),
                                                CAUSE_ACTION.get(cause, "")))
    lines.append("Waiting for intake: %s%s · intake %d/run%s"
                 % (_fmt_n(rep.waiting), w_old, rep.intake, _reserve_text(rep)))
    if rep.legacy:
        lines.append("Legacy backlog: %s%s" % (_fmt_n(rep.legacy),
                                               " (oldest %dd)" % rep.legacy_oldest
                                               if rep.legacy_oldest is not None else ""))
    if rep.unclassified:
        lines.append("UNCLASSIFIED %s: no stage rule matches these rows" % _fmt_n(rep.unclassified))
    if rep.mismatch:
        lines.append(_mismatch_text(rep))
    if dnl:
        lines.append("Did not look: %s" % dnl)
    lines.append(rep.conservation_line)
    rep.block_lines = lines
    if rep.open_runs:
        rep.run_lines = ["RUN %s open since %s, last event %sh ago"
                         % (r["run_id"], r["since"], "?" if r["last_event_hours"] is None
                            else r["last_event_hours"]) for r in rep.open_runs]
    else:
        rep.run_lines = ["no run open"]


def _reserve_text(rep):
    """`, 20 reserved for new` -- said only while the legacy backlog is non-empty, which is the only time a
    share is reserved (N8): with no backlog every slot goes to whoever is next, and saying otherwise would
    describe a rule that is not acting."""
    return ", %d reserved for new" % rep.reserved_new if rep.legacy else ""


def _mismatch_text(rep):
    return "ROLES MISMATCH raw %s ≠ staged %s" % (_fmt_n(rep.totals["raw"]), _fmt_n(rep.totals["staged"]))


def pipeline_alerts(rep):
    """C7 (owner request 2026-11-12): what makes the pipeline NOT healthy, as a list of segments in a fixed
    order. An empty list is healthy. This is the ONE definition: the dashboard top reads it and so does
    `check_dashboard_coverage.py`, so the page and its gate cannot disagree about "not healthy".

    The four conditions, and only these (each from `process_report`):
      - process failure > 0 (every cause, `legacy-backlog` included, because `process_report` counts it);
      - UNCLASSIFIED > 0;
      - ROLES MISMATCH;
      - an open run older than `LONGEST_RUN_S`, other than the run generating the page.
    Deliberately NOT here: `Did not look`, PARTIAL kinds, waiting for intake (a queue, not a failure),
    clock skew, no render route. They stay in the dashboard's collapsed block."""
    segs = []
    if rep.failure > 0:
        seg = "%s %s stuck in the pipeline" % (_fmt_n(rep.failure), "role" if rep.failure == 1 else "roles")
        if rep.failure_oldest is not None:
            seg += " (oldest %dd)" % rep.failure_oldest
        segs.append(seg)
    if rep.unclassified > 0:
        segs.append("UNCLASSIFIED %s" % _fmt_n(rep.unclassified))
    if rep.mismatch:
        segs.append(_mismatch_text(rep))
    for r in rep.overlong_runs:
        if r["open_s"] is None:
            segs.append("run %s open (start time not recorded)" % r["run_id"])
        else:
            segs.append("run %s open %.1fh" % (r["run_id"], r["open_s"] / 3600.0))
    return segs


def alert_line(rep):
    """The segments of `pipeline_alerts` joined with ` · `, or None when the pipeline is healthy. No glyph:
    the dashboard template adds its `⚠ ` once, the run summary prints the bare text, and the gate compares
    exactly this string (round-2 M3, one alert form)."""
    segs = pipeline_alerts(rep)
    return " · ".join(segs) if segs else None


# ----------------------------------------------------------------------------------------------
# DRAIN_FANOUT's pin (N3)
# ----------------------------------------------------------------------------------------------

def fanout_pin_problem(deployment_text, fanout=None):
    """None when `DRAIN_FANOUT` may be what it is, else the problem. Above 1 the deployment doc must
    hold a `- **P-RP-1a**: PASS <date>, <N> interleaved reads, 0 cross-reads` line with N >= 40."""
    fanout = DRAIN_FANOUT if fanout is None else fanout
    if fanout <= 1:
        return None
    for m in P_RP_1A_LINE_RE.finditer(deployment_text or ""):
        if int(m.group(2)) >= P_RP_1A_MIN_READS:
            return None
    return ("DRAIN_FANOUT is %d but plugins/jobsearch/docs/deployment.md records no passing P-RP-1a "
            "line (`- **P-RP-1a**: PASS <YYYY-MM-DD>, <N> interleaved reads, 0 cross-reads`, N >= %d)"
            % (fanout, P_RP_1A_MIN_READS))


# ----------------------------------------------------------------------------------------------
# the CLI
# ----------------------------------------------------------------------------------------------

LOCK_SCRIPT = os.path.join(HERE, "runlock.py")


def _lock_held():
    r = subprocess.run([sys.executable, "-B", LOCK_SCRIPT, "--status"], capture_output=True, text=True)
    return r.returncode != 0


def _take_lock(who, wait=90):
    r = subprocess.run([sys.executable, "-B", LOCK_SCRIPT, "--take", who, "--wait", str(wait)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise LifecycleError((r.stdout or r.stderr).strip() or "could not take the write lock")


def _release_lock():
    subprocess.run([sys.executable, "-B", LOCK_SCRIPT, "--release"], capture_output=True)


class _Locked(object):
    """Hold the profile write lock for the plan or the close (runlock's rule: hold it for the write,
    not for the run), through runlock's own CLI. `already_locked` verifies a hold rather than taking one."""

    def __init__(self, who, already_locked):
        self.who, self.already = who, already_locked

    def __enter__(self):
        if self.already:
            if not _lock_held():
                raise LifecycleError("--already-locked, but NOBODY holds the run lock")
        else:
            _take_lock(self.who)
        return self

    def __exit__(self, *exc):
        if not self.already:
            _release_lock()
        return False


def _now_arg(raw):
    if raw:
        return _dt(datetime.datetime.fromisoformat(raw))
    return datetime.datetime.now().replace(microsecond=0)


def _cmd_report(args, root):
    data = load_data(root)
    rep = process_report(data, _now_arg(args.now))
    if args.json:
        print(json.dumps(rep.to_json(), indent=1, sort_keys=True))
    else:
        print(rep.start_line)
        for ln in rep.block_lines:
            print(ln)
        for ln in rep.run_lines:
            print(ln)
        if rep.totals.get("raw_source") != "file":
            print("(role count not independently checked: no profile root)")
    return 3 if rep.mismatch else 0


def _record_close(root, run_id, res, now, by):
    fields = dict(admitted=res.admitted, finished=res.finished, left=dict(res.left),
                  at=now.isoformat())
    if by is not None:
        fields["on_behalf_of"] = by
    else:
        fields["elapsed_s"] = res.elapsed_s
        fields["per_role_s"] = res.per_role_s
    _journal.record_drain(root, run_id, "closed", **fields)


def _close_the_dead(root, this_run, now, say):
    """Before planning: close, on the dead run's behalf, every over run that has a plan and no close
    (N1). The next run writes the cause."""
    data = load_data(root)
    ctx = Ctx(data, now)
    for rid, run in sorted(ctx.runs.items()):
        if rid == this_run or run["planned"] is None or run["closed"] is not None or not run["over"]:
            continue
        res = close_result(data, rid, now, by=this_run)
        _record_close(root, rid, res, now, by=this_run)
        say("closed run %s on its behalf: %d admitted · %d finished · %d left (%s)"
            % (rid, res.admitted, res.finished, len(res.left), run["over_reason"]))


def _cmd_plan(args, root):
    now = _now_arg(args.now)
    if not args.run:
        raise LifecycleError("--drain-plan needs --run <id>")
    if not args.render_route:
        raise LifecycleError("--drain-plan needs --render-route yes|no (the session's own declaration)")
    if args.intake is not None and not args.attended:
        raise LifecycleError("--intake is for an --attended drain: an unattended run uses "
                             "search.intake_per_run")
    with _Locked("lifecycle.py drain-plan %s" % args.run, args.already_locked):
        # read the journal INSIDE the lock: two plans cannot both read before either writes (N2)
        _close_the_dead(root, args.run, now, print)
        data = load_data(root)
        existing = Ctx(data, now).runs.get(args.run)
        if existing is not None and existing["planned"] is not None:
            ev = existing["planned"]
            print("drain-plan run=%s already planned: %d roles admitted (nothing written)"
                  % (args.run, len(ev["admitted"]["opps"]) + len(ev["admitted"]["items"])))
            # the prose reads all three values from this output, so a second call (a resumed session)
            # prints the STORED ones, not just the first (B10 task 4; the plan's own `lines()` shape)
            print("fanout: %d" % ev.get("fanout", DRAIN_FANOUT))
            print("fetch_calls: %d" % ev.get("fetch_calls", 0))
            solo = ev.get("solo") or []
            print("solo: %s" % (",".join(solo) if solo else "-"))
            return 0
        plan = drain_plan(data, now, intake=args.intake, render_route=args.render_route,
                          attended=args.attended, run_id=args.run)
        _journal.record_drain(root, args.run, "planned", at=now.isoformat(), **plan.event_fields())
    if args.json:
        print(json.dumps(dict(plan.event_fields(), run_id=args.run), indent=1, sort_keys=True))
    else:
        for ln in plan.lines():
            print(ln)
    return 0


def _cmd_close(args, root):
    now = _now_arg(args.now)
    if not args.run:
        raise LifecycleError("--drain-close needs --run <id>")
    with _Locked("lifecycle.py drain-close %s" % args.run, args.already_locked):
        data = load_data(root)
        ctx = Ctx(data, now)
        run = ctx.runs.get(args.run)
        if run is None or run["planned"] is None:
            print("drain: no plan was written for run %s (nothing admitted, nothing to close)" % args.run)
            return 0
        res = close_result(data, args.run, now)
        own = [r for r in ctx.recs if r.get("event") == "drain" and r.get("phase") == "closed"
               and r.get("run_id") == args.run and not r.get("on_behalf_of")]
        if own:
            left = own[-1].get("left") or {}
            print("drain: run %s was already closed (nothing written): %d left" % (args.run, len(left)))
            return 3 if left else 0
        _record_close(root, args.run, res, now, by=None)
    print(res.summary_line(res.waiting_oldest))
    for oid, cause in sorted(res.left.items()):
        print("  LEFT %s: %s — %s" % (oid, cause, CAUSE_MEANING.get(cause, "")))
    return 3 if res.left else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="print the start line, the process block "
                    "and the conservation line; exit 3 on a ROLES MISMATCH")
    ap.add_argument("--drain-plan", dest="drain_plan", action="store_true",
                    help="admit this run's intake and append the `planned` event under the write lock")
    ap.add_argument("--drain-close", dest="drain_close", action="store_true",
                    help="check every admitted role finished; exit 3 when any is left")
    ap.add_argument("--run", metavar="ID")
    ap.add_argument("--render-route", dest="render_route", choices=("yes", "no"),
                    help="whether THIS session has a render route (mcp__Claude_Browser__preview_start)")
    ap.add_argument("--attended", action="store_true")
    ap.add_argument("--intake", type=int, metavar="N", help="with --attended: roles this session admits "
                    "(1..300), named by the owner")
    ap.add_argument("--already-locked", dest="already_locked", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now", metavar="ISO", help="for tests: the clock")
    args = ap.parse_args(argv)
    from _root import profile_root
    root = profile_root()
    try:
        if args.report:
            return _cmd_report(args, root)
        if args.drain_plan:
            return _cmd_plan(args, root)
        if args.drain_close:
            return _cmd_close(args, root)
    except (LifecycleError, _journal.JournalError, ValueError) as e:
        print("⛔ %s" % e, file=sys.stderr)
        return 2
    ap.error("give --report, --drain-plan or --drain-close")


if __name__ == "__main__":
    sys.exit(main())
