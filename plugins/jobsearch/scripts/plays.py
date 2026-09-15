#!/usr/bin/env python3
"""plays.py — the play engine (ADR-031 B4, design-connected-entities.md §18-§27.1).

A play is data: an ordered list of steps, each gated by a conjunction of predicates drawn from
one closed, 15-token vocabulary (§18), every one derivable from the stores as of a date.
"What's next" is the first step in order whose `when` holds and whose own effect is not already
on the record — routing is order plus conditions, never a `goto`.

WHAT THIS FILE OWNS
--------------------
The predicate vocabulary and its evaluator (`evaluate`); `next_step()`; the whole CLI surface
(`--options` / `--show` / `--adopt` / `--confirm` / `--unconfirm` / `--manual` / `--check` /
`--late` / `--brief` / `--all`). `plans.py` owns loading/joining the two stores; this module
imports it rather than re-reading them. `plays.py --brief` COMPOSES from `brief.py --json`
(ADR-032's correction to ADR-031's own B4 row) — it never recomputes a register or a silence
window; `check_ledger_reads.py` stays green because nothing here opens `briefs.jsonl` by name.

THE VOCABULARY (design §18, §24, §25) — 15 tokens, every one `as_of`-dated
------------------------------------------------------------------------------
application-submitted · insider-known · recruiter-known · decider-known · has-referral ·
referral-declined · done:<step> · replied:<step> · silent:<step>:<param> · role-open ·
pitch-ready · referral-resolved:<wait>:<search> · interview-scheduled · pursuit-closed ·
recruiter-first

Parsing is strict (§18): an unknown token, an undeclared `<param>`, a `<step>` not in the play,
or a `:` argument on a token that takes none, fails loudly — `validate_when()` is the one
function both `validate_data.py` and this module's own evaluator call, so the two can never
disagree about what parses.

Usage:
    python3 plays.py --options
    python3 plays.py --show default-plan
    python3 plays.py --adopt referral-first --plan default-plan [--replace]
    python3 plays.py --confirm default-plan | --unconfirm default-plan | --manual default-plan
    python3 plays.py --check
    python3 plays.py --late
    python3 plays.py --brief <opp_id>
    python3 plays.py --all [--dry-run]

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root                                     # noqa: E402
import plans as _plans                                             # noqa: E402
import validate_data as _vd                                        # noqa: E402
import posture as _posture                                         # noqa: E402
import config_keys as _ck                                          # noqa: E402

ENGINE_PLAYS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "plays")

# ---- the closed predicate vocabulary (§18, §24, §25) ---------------------------------------

# name -> number of `:`-separated arguments it takes.
TOKEN_ARITY = {
    "application-submitted": 0, "insider-known": 0, "recruiter-known": 0, "decider-known": 0,
    "has-referral": 0, "referral-declined": 0, "done": 1, "replied": 1, "silent": 2,
    "role-open": 0, "pitch-ready": 0, "referral-resolved": 2, "interview-scheduled": 0,
    "pursuit-closed": 0, "recruiter-first": 0,
}
# Tokens whose argument is a STEP id (declared in the play's own steps).
STEP_ARG_TOKENS = {"done": (0,), "replied": (0,), "silent": (0,)}
# Tokens whose argument is a PARAMETER name (declared in the play's own params).
PARAM_ARG_TOKENS = {"silent": (1,), "referral-resolved": (0, 1)}

# §18/§26.2 — the class an involvement's `path_type` (or, absent one, a touch's own
# `recipient_role` through this one bridge) resolves to. `RECIPIENT_ROLES` stays the touch's
# vocabulary, `PATH_TYPES` the involvement's — this is the ONE mapping between them (§26.2's
# own withdrawal of §20's "one vocabulary" sentence).
PATH_TYPE_CLASS = {"recruiter": "recruiter", "warm-referral": "insider", "internal": "insider",
                   "hiring-manager": "decider"}
ROLE_TO_PATH = {"talent-acquisition": "recruiter", "recruiter-agency": "recruiter",
               "warm-contact": "warm-referral", "peer-network": "warm-referral",
               "hiring-manager": "hiring-manager", "hiring-line": "hiring-manager"}
DO_TO_CLASSES = {"insider", "recruiter", "decider"}

# §18 — the closed `say` slug vocabulary.
SAY_SLUGS = {"referral", "fit", "ask-conversation", "ask-open", "referral-ask", "reconnect"}
DO_KINDS = {"apply", "research", "touch"}
RESEARCH_FINDS = {"insider", "recruiter", "decider"}

# §26.4 — the closed, `\b`-anchored, case-insensitive pronoun list a shipped pattern's `why`
# may never contain (a possessive NOUN is legal; only these are refused).
_PRONOUNS = ("I", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
            "he", "him", "his", "she", "her", "hers", "they", "them", "their", "theirs")
PRONOUN_RE = re.compile(r"\b(?:%s)\b" % "|".join(_PRONOUNS), re.IGNORECASE)


class PlayError(ValueError):
    """An unreadable play/pattern — grammar the evaluator refuses to guess over."""


def parse_token(tok):
    """'!done:reach-insider' -> (True, 'done', ['reach-insider']). Raises PlayError on
    anything the closed grammar does not admit — arity checked here structurally; step/param
    membership is checked by `validate_when` against a specific play."""
    s = str(tok)
    neg = s.startswith("!")
    body = s[1:] if neg else s
    parts = body.split(":")
    name = parts[0]
    args = parts[1:]
    if name not in TOKEN_ARITY:
        raise PlayError("unknown predicate token %r" % tok)
    if len(args) != TOKEN_ARITY[name]:
        raise PlayError("%r takes %d argument(s), got %d" % (name, TOKEN_ARITY[name], len(args)))
    return neg, name, args


def validate_when(tokens, play, problems, label):
    """Strict parse of a `when` list against ONE play's own steps/params. Appends to
    `problems` (validate_data.py's own list shape) and returns True iff every token parsed."""
    ok = True
    step_ids = {s.get("id") for s in (play.get("steps") or [])}
    param_names = set((play.get("params") or {}).keys())
    for tok in tokens or []:
        try:
            _neg, name, args = parse_token(tok)
        except PlayError as e:
            problems.append("%s: %s" % (label, e))
            ok = False
            continue
        for idx in STEP_ARG_TOKENS.get(name, ()):
            if args[idx] not in step_ids:
                problems.append("%s: token %r names step %r, not declared in this play's steps"
                                % (label, tok, args[idx]))
                ok = False
        for idx in PARAM_ARG_TOKENS.get(name, ()):
            if args[idx] not in param_names:
                problems.append("%s: token %r names parameter %r, not declared in this play's "
                                "params" % (label, tok, args[idx]))
                ok = False
    return ok


# ---- fact-gathering context — loaded ONCE per call site, reused across every predicate ------

class Context:
    """Every store `evaluate()` reads, loaded once. Not persisted — a fresh Context per CLI
    invocation, the same discipline `graph.Graph` states for itself."""

    def __init__(self, root):
        self.root = root
        import graph as _graph
        import touches as _touches
        import applications as _apps
        self.graph = _graph.Graph(os.path.join(root, "data"))
        self.opps = self.graph.stores["opportunities"]
        self.opps_by_id = {o.get("id"): o for o in self.opps if o.get("id")}
        touch_rows, _e, _p = _touches.load(root)
        self.touches_by_opp = _touches.group_by_opp(touch_rows)
        app_rows, _e2, _p2 = _apps.load(root)
        self.apps_by_opp = _apps.group_by_opp(app_rows)
        self.involvements_by_opp = {}
        for inv in self.graph.stores["involvements"]:
            oid = inv.get("opp_id")
            if oid:
                self.involvements_by_opp.setdefault(oid, []).append(inv)
        self.plans, _e3, _p3 = _plans.load(root)
        self.plans_by_id = _plans.by_id(self.plans)
        self.plays, _e4, _p4 = _plans.load_plays(root)
        self.plays_by_id = _plans.by_id(self.plays)


def _involvement_class(opp_id, person_id, ctx):
    for inv in ctx.involvements_by_opp.get(opp_id, ()):
        if inv.get("person_id") == person_id:
            c = PATH_TYPE_CLASS.get(inv.get("path_type"))
            if c:
                return c
    return None


def touch_class(touch, ctx):
    """§26.2 — the recipient's class for one touch: the involvement's `path_type` first, the
    touch's own `recipient_role` through `ROLE_TO_PATH` second. Two stored facts, in order,
    never a guess."""
    opp_id, person_id = touch.get("opp_id"), touch.get("person_id")
    c = _involvement_class(opp_id, person_id, ctx) if opp_id and person_id else None
    if c:
        return c
    pt = ROLE_TO_PATH.get(touch.get("recipient_role"))
    return PATH_TYPE_CLASS.get(pt) if pt else None


def class_known(opp_id, cls, ctx):
    for inv in ctx.involvements_by_opp.get(opp_id, ()):
        if PATH_TYPE_CLASS.get(inv.get("path_type")) == cls:
            return True
    return False


def _submitted_apps(opp_id, ctx, as_of):
    return [a for a in ctx.apps_by_opp.get(opp_id, ())
           if a.get("status") in _vd.SUBMITTED_APP_STATUS and (a.get("date") or "") <= as_of]


def application_date(opp_id, ctx, as_of=None):
    """The earliest submitted application's date, or None."""
    apps = ctx.apps_by_opp.get(opp_id, ())
    dates = [a.get("date") for a in apps if a.get("status") in _vd.SUBMITTED_APP_STATUS
            and a.get("date") and (as_of is None or a["date"] <= as_of)]
    return min(dates) if dates else None


def anchor_date(opp, ctx, as_of=None):
    """§26.1(b) — every application-anchored clock reads `max(applications.date,
    plan_assigned_on)`. On a fresh post-B4 pursuit these coincide or plan_assigned_on precedes
    the application; on a migrated one the search window starts on migration day."""
    ad = application_date(opp.get("id"), ctx, as_of)
    pa = opp.get("plan_assigned_on")
    cands = [d for d in (ad, pa) if d]
    return max(cands) if cands else None


def _step_by_id(play, step_id):
    for s in play.get("steps") or []:
        if s.get("id") == step_id:
            return s
    return None


def _matching_touches(opp_id, step_id, play, ctx, as_of):
    """§26.1(a) — every SENT touch on this opp that counts for `step_id`: it names the step
    directly, or it cannot name one (`play_step` null/unresolved) and its recipient's class
    equals the step's `do.to` class."""
    step = _step_by_id(play, step_id)
    do_to = (step or {}).get("do", {}).get("to")
    out = []
    for t in ctx.touches_by_opp.get(opp_id, ()):
        if t.get("status") != "sent":
            continue
        d = t.get("date") or ""
        if d[:10] > as_of:
            continue
        ps = t.get("play_step")
        if ps == step_id:
            out.append(t)
        elif ps in (None, "unresolved") and do_to and touch_class(t, ctx) == do_to:
            out.append(t)
    out.sort(key=lambda t: str(t.get("date") or ""))
    return out


def _resolve_param_days(play, name, opp, ctx, as_of, _stack=None):
    """The parameter's value as of today: first arm (in order) whose `when` holds, else the
    base `days` (§24.1's grammar — first that holds wins)."""
    spec = (play.get("params") or {}).get(name)
    if spec is None:
        raise PlayError("parameter %r is not declared on this play" % name)
    if isinstance(spec, (int, float)):
        return int(spec)
    for arm in spec.get("unless") or []:
        if all(evaluate(tok, opp, play, ctx, as_of, _stack) for tok in arm.get("when") or []):
            return int(arm.get("days"))
    return int(spec.get("days"))


def _referral_resolved(opp, wait_name, search_name, play, ctx, as_of):
    """(resolved, close_date, governing) for `referral-resolved:<wait>:<search>` (§25.2) —
    also the shape `--late`/`--check`'s waiting line reads, so the answer to "waiting for
    what, until when" is always a date, never silence."""
    opp_id = opp.get("id")
    if evaluate("has-referral", opp, play, ctx, as_of):
        return True, None, "has-referral"
    if evaluate("referral-declined", opp, play, ctx, as_of):
        return True, None, "referral-declined"
    insider_touches = _matching_touches(opp_id, "reach-insider", play, ctx, as_of)
    if insider_touches:
        ask = insider_touches[-1]
        replied = ask.get("responded_on") and str(ask["responded_on"])[:10] <= as_of
        wait_days = _resolve_param_days(play, wait_name, opp, ctx, as_of)
        close = _add_days(ask.get("date"), wait_days)
        if not replied and close and close <= as_of:
            return True, close, "silent:reach-insider:%s" % wait_name
        if not replied:
            return False, close, "response window (%s)" % wait_name
        # replied but not accepted/declined -> ambiguous outcome; not yet resolved either way
        return False, close, "response window (%s)" % wait_name
    # No ask exists yet — the search clause, evidence-gated (§26.3): a research_log entry
    # naming `find: insider`, dated on or after the anchor, is required before the window can
    # be read as having elapsed at all.
    if evaluate("insider-known", opp, play, ctx, as_of):
        return False, None, "insider known, ask not yet sent"
    anchor = anchor_date(opp, ctx, as_of)
    if not anchor:
        return False, None, "no application yet"
    attempts = [e for e in (opp.get("research_log") or [])
               if e.get("find") == "insider" and (e.get("date") or "") >= anchor
               and (e.get("date") or "") <= as_of]
    if not attempts:
        return False, None, "search window (%s) — no research_log attempt recorded yet" % search_name
    search_days = _resolve_param_days(play, search_name, opp, ctx, as_of)
    close = _add_days(anchor, search_days)
    if close and close <= as_of:
        return True, close, "nobody-found:%s" % search_name
    return False, close, "search window (%s)" % search_name


def _add_days(iso_date, n):
    if not iso_date:
        return None
    try:
        d = datetime.date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return None
    return (d + datetime.timedelta(days=int(n))).isoformat()


def _elapsed_days(iso_date, as_of):
    if not iso_date:
        return None
    try:
        d = datetime.date.fromisoformat(str(iso_date)[:10])
        a = datetime.date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return None
    return (a - d).days


def evaluate(tok, opp, play, ctx, as_of, _stack=None):
    """True/False for one predicate token, `as_of` a fact date, over `opp` under `play`. Raises
    PlayError on a token this play's own grammar does not admit (validate_when should already
    have refused it at write time; this is the runtime backstop)."""
    neg, name, args = parse_token(tok)
    _stack = _stack or set()
    key = (name, tuple(args))
    if key in _stack:
        raise PlayError("predicate %r is self-referential" % (tok,))
    result = _evaluate_body(name, args, opp, play, ctx, as_of, _stack | {key})
    return (not result) if neg else result


def _evaluate_body(name, args, opp, play, ctx, as_of, _stack):
    opp_id = opp.get("id")
    if name == "application-submitted":
        return bool(_submitted_apps(opp_id, ctx, as_of))
    if name in ("insider-known", "recruiter-known", "decider-known"):
        return class_known(opp_id, name.split("-")[0], ctx)
    if name == "has-referral":
        return any(t.get("touch_type") == "referral-ask" and t.get("outcome") == "accepted"
                  and (t.get("responded_on") or "")[:10] <= as_of
                  for t in ctx.touches_by_opp.get(opp_id, ()))
    if name == "referral-declined":
        return any(t.get("touch_type") == "referral-ask" and t.get("outcome") == "declined"
                  and (t.get("date") or "")[:10] <= as_of
                  for t in ctx.touches_by_opp.get(opp_id, ()))
    if name == "done":
        return bool(_matching_touches(opp_id, args[0], play, ctx, as_of))
    if name == "replied":
        return any(t.get("responded_on") and str(t["responded_on"])[:10] <= as_of
                  for t in _matching_touches(opp_id, args[0], play, ctx, as_of))
    if name == "silent":
        step_id, param = args
        matches = _matching_touches(opp_id, step_id, play, ctx, as_of)
        if not matches:
            return False
        latest = matches[-1]
        if latest.get("responded_on") and str(latest["responded_on"])[:10] <= as_of:
            return False
        days = _resolve_param_days(play, param, opp, ctx, as_of, _stack)
        elapsed = _elapsed_days(latest.get("date"), as_of)
        return elapsed is not None and elapsed >= days
    if name == "role-open":
        return (evaluate("replied:verify-open", opp, play, ctx, as_of, _stack)
               and not evaluate("pursuit-closed", opp, play, ctx, as_of, _stack))
    if name == "pitch-ready":
        return (evaluate("has-referral", opp, play, ctx, as_of, _stack)
               or evaluate("role-open", opp, play, ctx, as_of, _stack))
    if name == "referral-resolved":
        resolved, _close, _why = _referral_resolved(opp, args[0], args[1], play, ctx, as_of)
        return resolved
    if name == "interview-scheduled":
        return opp.get("stage") in ("screening", "interviewing", "offer")
    if name == "pursuit-closed":
        return opp.get("status") in _vd.TERMINAL_OPP_STATUSES
    if name == "recruiter-first":
        recruiter_sent = [t for t in ctx.touches_by_opp.get(opp_id, ())
                          if t.get("status") == "sent" and (t.get("date") or "")[:10] <= as_of
                          and touch_class(t, ctx) == "recruiter"]
        if not recruiter_sent:
            return False
        earliest_recruiter = min(str(t.get("date") or "") for t in recruiter_sent)
        insider_touches = _matching_touches(opp_id, "reach-insider", play, ctx, as_of)
        if not insider_touches:
            return True
        ask_date = str(insider_touches[0].get("date") or "")
        return earliest_recruiter <= ask_date
    raise PlayError("unimplemented predicate %r" % name)     # pragma: no cover — arity table
                                                              # keeps this unreachable


# ---- next_step() — "the answer is a date, not silence" (§18) -------------------------------

class NextStep:
    __slots__ = ("kind", "step", "due", "expires", "why", "detail")

    def __init__(self, kind, step=None, due=None, expires=None, why=None, detail=None):
        self.kind = kind
        self.step = step
        self.due = due
        self.expires = expires
        self.why = why
        self.detail = detail

    def as_dict(self):
        return {"kind": self.kind, "step": self.step, "due": self.due, "expires": self.expires,
               "why": self.why, "detail": self.detail}


def _step_due(step, opp, play, ctx, as_of):
    """Best-effort 'the date this step's entry condition became true' — the anchor that makes
    the step's own positive facts hold, or the plan's own assignment date as a floor. Exact for
    the two clocks `referral-resolved` reads; an approximation (the anchor date) for a plain
    apply/research step, named here rather than left silent."""
    when = step.get("when") or []
    for tok in when:
        try:
            _neg, name, args = parse_token(tok)
        except PlayError:
            continue
        if name == "referral-resolved" and not tok.startswith("!"):
            _resolved, close, _why = _referral_resolved(opp, args[0], args[1], play, ctx, as_of)
            if close:
                return close
    return anchor_date(opp, ctx, as_of) or opp.get("plan_assigned_on")


def next_step(plan, play, opp, ctx, as_of):
    """The single answer §18 defines: `step` (carrying `due`), `waiting(until)`, `goal-reached`,
    `closed`, `manual`, `no-play`, or `stalled(why)` — never a quiet empty return."""
    if opp.get("status") in _vd.TERMINAL_OPP_STATUSES:
        return NextStep("closed")
    if plan is None:
        return NextStep("no-plan", why="no plan governs this pursuit")
    play_id = plan.get("play_id")
    if play_id is None:
        return NextStep("no-play", why="plan %r has not chosen a play yet" % plan.get("id"))
    if play_id == _plans.MANUAL_PLAY:
        return NextStep("manual")
    if play is None:
        return NextStep("stalled", why="play %r not found in plays.jsonl" % play_id)
    goal_tok = play.get("goal")
    try:
        if goal_tok and evaluate(goal_tok, opp, play, ctx, as_of):
            return NextStep("goal-reached")
    except PlayError as e:
        return NextStep("stalled", why="goal predicate unreadable: %s" % e)
    for step in play.get("steps") or []:
        try:
            holds = all(evaluate(tok, opp, play, ctx, as_of) for tok in step.get("when") or [])
        except PlayError as e:
            return NextStep("stalled", why="step %r: %s" % (step.get("id"), e))
        if holds:
            due = _step_due(step, opp, play, ctx, as_of)
            return NextStep("step", step=step.get("id"), due=due,
                            detail=step.get("do"))
    # Nothing runnable. Is something merely waiting on a clock, or genuinely stalled?
    for step in play.get("steps") or []:
        for tok in step.get("when") or []:
            try:
                _neg, name, args = parse_token(tok)
            except PlayError:
                continue
            if name == "referral-resolved":
                resolved, close, why = _referral_resolved(opp, args[0], args[1], play, ctx, as_of)
                if not resolved and close:
                    return NextStep("waiting", until=close, why=why)
    return NextStep("stalled", why="no runnable step and no known clock will flip it")


# ---- pattern loading / adoption / fork detection (§20, §27.1, §28.2) -----------------------

def load_patterns():
    """{pattern_id: parsed json} for every shipped `plugins/jobsearch/plays/*.json` file."""
    out = {}
    if not os.path.isdir(ENGINE_PLAYS_DIR):
        return out
    for fn in sorted(os.listdir(ENGINE_PLAYS_DIR)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(ENGINE_PLAYS_DIR, fn), encoding="utf-8") as fh:
            pat = json.load(fh)
        out[pat["id"]] = pat
    return out


def canonical_structure(play_or_pattern):
    """§28.2 row 4 — STRUCTURE only: `steps[]`, `goal`, and per parameter `min`/`max`/`anchor`
    and each arm's `when` (never `days`/`why`/`set_on`, never an arm's own `days`/`why`). An
    ADDED arm is a fork — it changes the arm LIST, which is structure."""
    params = {}
    for name, spec in (play_or_pattern.get("params") or {}).items():
        if isinstance(spec, (int, float)):
            params[name] = {"min": None, "max": None, "anchor": None, "arms": []}
            continue
        arms = [{"when": a.get("when")} for a in (spec.get("unless") or [])]
        params[name] = {"min": spec.get("min"), "max": spec.get("max"),
                        "anchor": spec.get("anchor"), "arms": arms}
    return {"steps": play_or_pattern.get("steps"), "goal": play_or_pattern.get("goal"),
           "params": params}


def pattern_sha(play_or_pattern):
    blob = json.dumps(canonical_structure(play_or_pattern), sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def drift_state(row, patterns=None):
    """'ok' | 'stale' | 'unstamped' | 'unreadable' | 'forked' — §20's drift report."""
    patterns = patterns if patterns is not None else load_patterns()
    try:
        validate_when_play(row)
    except PlayError:
        return "unreadable"
    pid = row.get("pattern")
    if not pid:
        return "unstamped"
    pat = patterns.get(pid)
    if pat is None:
        return "stale"
    if canonical_structure(row) != canonical_structure(pat):
        return "forked"
    if pattern_sha(pat) != row.get("pattern_sha"):
        return "stale"
    return "ok"


def validate_when_play(play):
    """Parse-check every `when` in a play's own steps/goal against ITS OWN grammar — raises
    PlayError on the first unreadable token (the runtime backstop `validate_data.py`'s own,
    more informative check duplicates at data-validation time)."""
    problems = []
    for step in play.get("steps") or []:
        validate_when(step.get("when") or [], play, problems, "step %r" % step.get("id"))
    if play.get("goal"):
        validate_when([play["goal"]], play, problems, "goal")
    if problems:
        raise PlayError("; ".join(problems))
    return True


def adopt(root, pattern_id, plan_id, replace=False):
    """§20 — copy a shipped pattern's structure into `data/plays.jsonl`, stamped. Returns
    (ok, message). The plan's own `play_id`/`play_confirmed` are the CALLER's to set — this
    only writes the play row (via record.py, so the write is atomic and validated)."""
    patterns = load_patterns()
    pat = patterns.get(pattern_id)
    if pat is None:
        return False, ("unknown pattern %r — have: %s"
                       % (pattern_id, ", ".join(sorted(patterns)) or "none"))
    row = {"id": pattern_id if not replace else pattern_id, "pattern": pattern_id,
          "pattern_sha": pattern_sha(pat), "pattern_reconciled_on":
          datetime.date.today().isoformat(), "params": pat.get("params") or {},
          "steps": pat.get("steps") or [], "goal": pat.get("goal"), "status": "active",
          "note": None}
    return True, row


# ---- --brief — composes from brief.py, NEVER recomputes (ADR-032's correction) -------------

def compose_brief(root, opp_id, plan, play, ctx, as_of):
    """The current step's `say` resolved against predicates, plus `brief.py --json`'s own
    register for this pursuit's people — a COMPOSITION, never a second computation of what
    brief.py already owns (ADR-032; `check_ledger_reads.py` stays green because this never
    opens `briefs.jsonl` by name — it calls `brief.py`'s own Python API)."""
    opp = ctx.opps_by_id.get(opp_id)
    if opp is None:
        return {"error": "no such opportunity %r" % opp_id}
    ns = next_step(plan, play, opp, ctx, as_of)
    say = []
    if ns.kind == "step" and play is not None:
        step = _step_by_id(play, ns.step) or {}
        for entry in step.get("say") or []:
            if isinstance(entry, str):
                say.append(entry)
            elif all(evaluate(t, opp, play, ctx, as_of) for t in entry.get("when") or []):
                say.append(entry.get("content"))
    import brief as _brief
    people = [inv.get("person_id") for inv in ctx.involvements_by_opp.get(opp_id, ())
             if inv.get("person_id")]
    registers = []
    for pid in people:
        try:
            b = _brief.compute(root, pid, counterpart="opp:%s" % opp_id, today=as_of)
        except Exception as e:                                    # noqa: BLE001 — advisory only
            b = {"error": str(e)}
        registers.append({"person_id": pid, "brief": b})
    return {"opp_id": opp_id, "next_step": ns.as_dict(), "say": say,
           "approach": (plan or {}).get("approach"), "registers": registers}


# ---- --confirm / --unconfirm / --manual — the write itself, through record.py's own atomic
# primitives (§26.1(d): "adopting is choosing"; the owner running the command IS the decision,
# so the command performs the write rather than printing one for the owner to run — CLAUDE.md
# "a change ships as a version, never an instruction" / "never mechanical work the engine can
# do", applied to the ENGINE'S OWN confirmation step, not only to a migration) -----------------

def _write_plan_fields(plan_id, fields):
    """Atomically set one or more fields on one `data/plans.jsonl` row, using record.py's own
    write primitives (take_lock/load/find/snapshot/save_atomic/validate/new_problems/restore) —
    the same lock-read-mutate-verify-write-rollback discipline record.py's own `set` verb runs
    inline in its `main()`, factored here as a direct IN-PROCESS call (import, not subprocess:
    the only two subprocess calls this makes are the ones record.py's own helpers already make,
    to `runlock.py` and `validate_data.py`, exactly as every other caller of those helpers
    does). Returns (ok, message)."""
    import record as _record
    try:
        _record.take_lock("plays.py set plan:%s %s" % (plan_id, ",".join(sorted(fields))))
    except _record.LockError as e:
        return False, str(e)
    try:
        rows = _record.load("plans")               # re-read INSIDE the lock
        rec = _record.find(rows, plan_id)
        if rec is None:
            return False, "plan %r vanished between read and lock" % plan_id
        for k, v in fields.items():
            rec[k] = v
        before = _record.snapshot("plans")
        pre_rc, _o, _e, pre_problems = _record.validate()
        _record.save_atomic("plans", rows)
        rc, out, err, problems = _record.validate()
        if rc != 0:
            added = _record.new_problems(pre_problems, problems)
            # Mirror record.py's own G9 carve-out: keep the write only when every problem after
            # it was already there before it (added == []); anything else — a genuinely new
            # problem, or an unknowable comparison (added is None, a validator crash) — rolls
            # back rather than risk landing a write nobody can tell is safe.
            if not (pre_rc != 0 and added == []):
                _record.restore("plans", before)
                return False, ("write refused — " +
                               ("; ".join(added) if added else
                                "; ".join(problems or []) or "validator failed"))
        return True, ", ".join("%s=%r" % (k, v) for k, v in sorted(fields.items()))
    finally:
        _record.release_lock()


def cmd_confirm(root, plan_id, confirmed):
    """§26.1(d)/§26.4 — `--confirm`/`--unconfirm` PERFORM the write (never print a command for
    the owner to run): flip `play_confirmed` on a plan whose `play_id` already names a real,
    resolvable play. Refuses a plan with no play to (un)confirm (`play_id` null or the literal
    `manual` — `--manual` is the separate verb for that state, §26.4 point 1) and a plan whose
    `play_id` does not resolve in `data/plays.jsonl`. Prints what confirming unleashes: every
    non-terminal pursuit this plan governs, with the position `next_step` now computes for it —
    the same read `--check` gives, scoped to this one plan (§26.1's own report line, for a
    single plan rather than the whole store)."""
    ctx = Context(root)
    plan = ctx.plans_by_id.get(plan_id)
    if plan is None:
        print("no such plan %r" % plan_id)
        return 1
    play_id = plan.get("play_id")
    if play_id in (None, _plans.MANUAL_PLAY):
        print("⛔ plan %r has no play to %s (play_id=%r) — `--adopt <pattern>` first, or "
             "use `--manual` for a plan the owner drives by hand"
             % (plan_id, "confirm" if confirmed else "unconfirm", play_id))
        return 1
    if ctx.plays_by_id.get(play_id) is None:
        print("⛔ plan %r names play %r, which is not in data/plays.jsonl — nothing to %s"
             % (plan_id, play_id, "confirm" if confirmed else "unconfirm"))
        return 1
    if plan.get("play_confirmed") == confirmed:
        print("%s: play_confirmed already %s — nothing to do" % (plan_id, confirmed))
        return 0
    ok, msg = _write_plan_fields(plan_id, {"play_confirmed": confirmed})
    if not ok:
        print("⛔ %s" % msg)
        return 1
    print("%s: play_confirmed = %s" % (plan_id, confirmed))
    if not confirmed:
        return 0
    # What this unleashes — the position `next_step` now computes for every pursuit this plan
    # governs, the same read `--check` gives (§26.1's migration-report line, per plan).
    ctx = Context(root)                             # re-read after the write
    play = ctx.plays_by_id.get(play_id)
    as_of = _today()
    governed = [o for o in ctx.opps if o.get("plan_id") == plan_id
               and o.get("status") not in _vd.TERMINAL_OPP_STATUSES]
    if not governed:
        print("  (this plan governs no non-terminal pursuit yet)")
        return 0
    print("  now runnable/waiting under %s:" % plan_id)
    for o in sorted(governed, key=lambda x: x.get("id") or ""):
        ns = next_step(plan, play, o, ctx, as_of)
        if ns.kind == "step":
            print("    %s — %s %s, due %s" % (o.get("id"), (ns.detail or {}).get("kind"),
                                              ns.step, ns.due))
        elif ns.kind == "waiting":
            print("    %s — waiting until %s (%s)" % (o.get("id"), ns.until, ns.why))
        elif ns.kind == "stalled":
            print("    %s — STALLED: %s" % (o.get("id"), ns.why))
        elif ns.kind == "goal-reached":
            print("    %s — goal reached" % o.get("id"))
    return 0


def cmd_manual(root, plan_id):
    """§26.4 point 1 — `--manual` sets `play_id: "manual"` AND `play_confirmed: true` in one
    atomic write: a manual plan is confirmed by definition (the owner has chosen to drive every
    step by hand, which is itself the decision `play_confirmed` records — there is no
    unconfirmed-manual state for `next_step` to distinguish: it returns `manual` regardless of
    `play_confirmed`, and `--all`/`--late` skip `play_id == manual` outright). Refused for a
    `person`-subject plan (design §17 — it governs no pursuit, so `play_id` must stay null)."""
    ctx = Context(root)
    plan = ctx.plans_by_id.get(plan_id)
    if plan is None:
        print("no such plan %r" % plan_id)
        return 1
    if plan.get("subject_kind") == "person":
        print("⛔ plan %r is subject_kind 'person' — it governs no pursuit, so play_id must "
             "stay null (design §17)" % plan_id)
        return 1
    if plan.get("play_id") == _plans.MANUAL_PLAY and plan.get("play_confirmed") is True:
        print("%s: already manual — nothing to do" % plan_id)
        return 0
    ok, msg = _write_plan_fields(plan_id, {"play_id": _plans.MANUAL_PLAY,
                                          "play_confirmed": True})
    if not ok:
        print("⛔ %s" % msg)
        return 1
    print("%s: play_id = manual, play_confirmed = True — next action is yours on every "
         "pursuit this plan governs" % plan_id)
    return 0


# ---- CLI -------------------------------------------------------------------------------------

def _today():
    return datetime.date.today().isoformat()


def cmd_options(root):
    patterns = load_patterns()
    ctx = Context(root)
    print("ADJUSTABLE")
    for plan in ctx.plans:
        if plan.get("subject_kind") not in _plans.GOVERNING_SUBJECT_KINDS:
            continue
        play_id = plan.get("play_id")
        play = ctx.plays_by_id.get(play_id) if play_id else None
        state = drift_state(play, patterns) if play else "—"
        print("  plan %s, play %s (%s)" % (plan.get("id"), play_id or "none", state))
        if play:
            for name, spec in sorted((play.get("params") or {}).items()):
                if isinstance(spec, (int, float)):
                    print("    %-22s %s  (fixed)" % (name, spec))
                    continue
                bound = "[%s–%s]" % (spec.get("min"), spec.get("max"))
                print("    %-22s %s  %s  from the %s"
                     % (name, spec.get("days"), bound, spec.get("anchor")))
                for arm in spec.get("unless") or []:
                    print("      unless %s -> %s" % (arm.get("when"), arm.get("days")))
        print("    play                 %s · manual   (plays.py --adopt <id> | --manual)"
             % " · ".join(sorted(patterns)))
        print("    play_confirmed       %s   (plays.py --confirm | --unconfirm)"
             % plan.get("play_confirmed"))
        print("    goal · approach      %r · %r   (record.py set plan:%s goal \"...\")"
             % (plan.get("goal"), plan.get("approach"), plan.get("id")))
    print("\nFIXED BY THE ENGINE — a change here is a report to the plugin team, not a setting:")
    print("  the %d predicates · %d step kinds · %d say slugs · MIN_SAMPLE = 5"
         % (len(TOKEN_ARITY), len(DO_KINDS), len(SAY_SLUGS)))
    return 0


def cmd_show(root, plan_id):
    ctx = Context(root)
    plan = ctx.plans_by_id.get(plan_id)
    if plan is None:
        print("no such plan %r" % plan_id)
        return 1
    play = ctx.plays_by_id.get(plan.get("play_id"))
    print("plan %s — subject %s:%s — outcomes %s" % (plan_id, plan.get("subject_kind"),
                                                     plan.get("subject_id"),
                                                     plan.get("outcomes")))
    print("  play: %s (confirmed=%s)" % (plan.get("play_id"), plan.get("play_confirmed")))
    if not play:
        return 0
    print("  stamp: %s (pattern=%s, reconciled %s)"
         % (drift_state(play), play.get("pattern"), play.get("pattern_reconciled_on")))
    for name, spec in sorted((play.get("params") or {}).items()):
        if isinstance(spec, (int, float)):
            print("  %-22s value=%s  (fixed)" % (name, spec))
            continue
        readers = [s.get("id") for s in play.get("steps") or []
                  if any(name in tok for tok in (s.get("when") or []))]
        prov = ("owner-set %s, was pattern default" % spec.get("set_on")
               if spec.get("set_on") else "pattern default")
        print("  %-22s value=%s  bound=[%s–%s]  anchor=%s  %s"
             % (name, spec.get("days"), spec.get("min"), spec.get("max"), spec.get("anchor"),
                prov))
        print("      why: %s" % spec.get("why"))
        for arm in spec.get("unless") or []:
            print("      unless %s -> %s  why: %s" % (arm.get("when"), arm.get("days"),
                                                       arm.get("why")))
        print("      read by steps: %s" % ", ".join(readers) or "(none)")
    return 0


def cmd_check(root, as_of=None):
    ctx = Context(root)
    as_of = as_of or _today()
    n_stalled = n_waiting = n_manual = n_ok = 0
    for o in ctx.opps:
        if o.get("status") in _vd.TERMINAL_OPP_STATUSES:
            continue
        plan = ctx.plans_by_id.get(o.get("plan_id"))
        play = ctx.plays_by_id.get((plan or {}).get("play_id"))
        ns = next_step(plan, play, o, ctx, as_of)
        if ns.kind == "stalled":
            n_stalled += 1
            print("STALLED %s — %s" % (o.get("id"), ns.why))
        elif ns.kind == "waiting":
            n_waiting += 1
            print("waiting %s — until %s (%s)" % (o.get("id"), ns.until, ns.why))
        elif ns.kind == "manual":
            n_manual += 1
        else:
            n_ok += 1
    print("\n%d runnable/goal · %d waiting · %d manual · %d stalled" % (n_ok, n_waiting,
                                                                       n_manual, n_stalled))
    posture_name, posture_cfg, _err = _posture.load()
    if posture_cfg:
        gap_h = 48.0 / max(1, posture_cfg.get("runs_per_day") or 1)
        # shortest temporal budget over every ACTIVE, CONFIRMED play's declared params
        shortest = None
        for plan in ctx.plans:
            if not plan.get("play_confirmed"):
                continue
            play = ctx.plays_by_id.get(plan.get("play_id"))
            if not play:
                continue
            for spec in (play.get("params") or {}).values():
                if isinstance(spec, dict):
                    vals = [spec.get("days")] + [a.get("days") for a in spec.get("unless") or []]
                    for v in vals:
                        if v is not None and (shortest is None or v < shortest):
                            shortest = v
        if shortest is not None and gap_h >= (shortest * 24) / 2.0:
            print("declared cron %r: longest gap ~%.0fh against a %dh budget — a missed run "
                 "costs at least half the window" % (posture_cfg.get("cron"), gap_h,
                                                     shortest * 24))
    return 1 if n_stalled else 0


def cmd_late(root, as_of=None):
    ctx = Context(root)
    as_of = as_of or _today()
    n = 0
    for o in ctx.opps:
        if o.get("status") in _vd.TERMINAL_OPP_STATUSES:
            continue
        plan = ctx.plans_by_id.get(o.get("plan_id"))
        play = ctx.plays_by_id.get((plan or {}).get("play_id"))
        ns = next_step(plan, play, o, ctx, as_of)
        if ns.kind == "step" and ns.due and ns.due < as_of:
            days = _elapsed_days(ns.due, as_of)
            print("%s — step %s, due %s (%s day(s) late)" % (o.get("id"), ns.step, ns.due, days))
            n += 1
    print("\n%d pursuit(s) late" % n)
    return 0


def cmd_all(root, dry_run=False):
    """§26.8 — one step is one transaction; caps on research/draft steps per tick; unconfirmed
    plays act on nothing outward (§26.1 d)."""
    ctx = Context(root)
    as_of = _today()
    posture_name, posture_cfg, _err = _posture.load()
    max_agents = (posture_cfg or {}).get("max_agents_per_run", 0)
    max_drafts = (posture_cfg or {}).get("max_drafts_per_run", 0)
    research_done = drafts_done = 0
    deferred_research = deferred_drafts = 0
    acted = []
    candidates = []
    for o in sorted(ctx.opps, key=lambda x: x.get("id") or ""):
        if o.get("status") in _vd.TERMINAL_OPP_STATUSES:
            continue
        plan = ctx.plans_by_id.get(o.get("plan_id"))
        if not plan or not plan.get("play_confirmed") or plan.get("play_id") in (None, "manual"):
            continue
        play = ctx.plays_by_id.get(plan.get("play_id"))
        if not play:
            continue
        ns = next_step(plan, play, o, ctx, as_of)
        if ns.kind != "step":
            continue
        candidates.append((ns.due or "", o, ns))
    candidates.sort(key=lambda t: t[0])
    for _due, o, ns in candidates:
        kind = (ns.detail or {}).get("kind")
        cap_name = None
        if kind in ("apply",):
            continue           # the owner's own act — never automated
        if kind == "research":
            capability = "linkedin" if (ns.detail or {}).get("find") in ("insider", "recruiter") \
                else "research"
            if not _posture.may(capability):
                deferred_research += 1
                continue
            if research_done >= max_agents:
                deferred_research += 1
                continue
            research_done += 1
            acted.append((o.get("id"), ns.step, "research"))
        elif kind == "touch":
            if not _posture.may("drafting"):
                deferred_drafts += 1
                continue
            if drafts_done >= max_drafts:
                deferred_drafts += 1
                continue
            drafts_done += 1
            acted.append((o.get("id"), ns.step, "draft"))
    print("plays --all — posture %r" % posture_name)
    for oid, step, act in acted:
        print("  %s %s: %s" % (act, oid, step))
    print("  %d research step(s), %d draft(s) — %d research and %d draft(s) deferred by "
         "budget/posture" % (research_done, drafts_done, deferred_research, deferred_drafts))
    if dry_run:
        print("  --dry-run: nothing recorded.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--options", action="store_true")
    ap.add_argument("--show", metavar="PLAN_ID")
    ap.add_argument("--adopt", metavar="PATTERN_ID")
    ap.add_argument("--plan", metavar="PLAN_ID", help="the plan --adopt/--confirm/--unconfirm/"
                    "--manual targets")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--confirm", metavar="PLAN_ID")
    ap.add_argument("--unconfirm", metavar="PLAN_ID")
    ap.add_argument("--manual", metavar="PLAN_ID")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--late", action="store_true")
    ap.add_argument("--brief", metavar="OPP_ID")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--as-of", default=None, help="test seam — ISO date to evaluate as of")
    args = ap.parse_args()

    root = profile_root()

    if args.options:
        return cmd_options(root)
    if args.show:
        return cmd_show(root, args.show)
    if args.check:
        return cmd_check(root, args.as_of)
    if args.late:
        return cmd_late(root, args.as_of)
    if args.brief:
        ctx = Context(root)
        opp = ctx.opps_by_id.get(args.brief)
        plan = ctx.plans_by_id.get((opp or {}).get("plan_id"))
        play = ctx.plays_by_id.get((plan or {}).get("play_id"))
        print(json.dumps(compose_brief(root, args.brief, plan, play, ctx,
                                       args.as_of or _today()), indent=2, default=str))
        return 0
    if args.all:
        return cmd_all(root, dry_run=args.dry_run)
    if args.confirm:
        return cmd_confirm(root, args.confirm, True)
    if args.unconfirm:
        return cmd_confirm(root, args.unconfirm, False)
    if args.manual:
        return cmd_manual(root, args.manual)
    if args.adopt:
        ok, result = adopt(root, args.adopt, args.plan, replace=args.replace)
        if not ok:
            print("⛔ %s" % result)
            return 1
        print(json.dumps(result, indent=2))
        print("\nwrite it: python3 record.py create %s '%s' --file plays"
             % (result["id"], json.dumps(result)))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
