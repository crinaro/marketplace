#!/usr/bin/env python3
"""PANEL — the one deterministic source of "where does the job search stand", for two renderers.

dev #750 part 1 (design `docs/design-local-surfaces-and-mods.md` §3.2): the mod
(`hooks/register.ts`) draws `--json` at zero model tokens; the mods-off / Remote-Control path
(`/jobsearch:status`) prints `--text`. There is ONE composer, so the two cannot disagree.

    panel.py --probe                   exit 0 and {"profile": true} only when the cwd is INSIDE a profile
    panel.py --json [--fast|--full]    one object (the contract below)
    panel.py --text [--fast|--full]    the same object as plain lines
    panel.py --json --today 2026-10-21 deterministic date, for tests

⛔ READ-ONLY BY CONSTRUCTION. This script writes nothing in the profile and takes no lock. It
never calls `coordinator.py` as a program (that re-marks the staleness watermark, which a
two-minute timer would then hide) and never `inbox.py --ack`. It composes read-only FUNCTIONS:
`coordinator.open_fit_questions`, `inbox.replay`, `runlock.read`, `check_runs.footprints`,
`check_dashboard_fresh.publish_state`, `channels_due.review_rows`, `conversations.report`,
`your_move.open_asks`, `knowledge.report`, `posture.load`. `test_panel.py` proves the profile's
tree hash is identical before and after. (Importing `_root.profile_root()` records the remembered
pointer under HOME, exactly as every other script does on every run; it touches no profile file.)

⭐ `--probe` never reads the remembered pointer: a session whose cwd is not inside a profile must
draw nothing, so one profile's data never appears in an unrelated directory's session.

THE CONTRACT (both renderers and `check_dashboard_coverage.py`'s ELSEWHERE test read these keys):

    needs_you[]   {kind, id, title, act_by}   roles waiting on you, open JD-fit questions, open asks
    rescreen_flags  {count, unreadable[], items[]}   roles whose stored comp removal jobsearch 0.73.0
                  would not repeat (dev #761); each item {id, title, status, old_verdict, new_verdict,
                  why, action}. FLAG, NEVER REOPEN (owner decision 2026-10-23): nothing here changes a
                  row; the candidate's own `record.py decide` / `record.py screened` ends the flag.
                  `unreadable[]` are roles whose re-run raised: said, never dropped.
    inbox         {unacked, urgent}           pending rows of data/inbox.jsonl (acks replayed)
    lock          {held, by, since, stale}    the write lock, read not taken
    runs          {last_at, last_task, next_at, next_task}
    runs_effect   {verdict, detail}           did the background runs do anything
    dashboard     {state, as_of}              published dashboard vs the repo           (full only)
    gates[]       {name, ok}                  the ORIENT gates                           (full only)
    elsewhere     {in_flight[], channels_due[], week[], preps_owed[], asks[], kb_index[]}   (full only)
    tasks         {daily, weekly}             the scheduled-task ids the Run buttons start
    band          one line for the status band

`--fast` omits the (full only) keys; the mod keeps its last full snapshot for them. A source that
cannot be read yields `{"error": "..."}` for that key and `NOT CHECKED (reason)` in the text,
never an empty value reported as a fact.

Python 3.9+. Standard library only.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TASKS = {"daily": "search-daily", "weekly": "search-strategy-weekly"}

FAST_KEYS = ("needs_you", "rescreen_flags", "inbox", "lock", "runs", "runs_effect", "tasks")
FULL_ONLY_KEYS = ("dashboard", "gates", "elsewhere")
ELSEWHERE_KEYS = ("in_flight", "channels_due", "week", "preps_owed", "asks", "kb_index")

# The text renderer's label for every top-level key. test_panel.py asserts that EVERY key of
# `--json --full` has its label in `--text`, so a section added to one renderer and not the other
# fails the build.
LABELS = {
    "needs_you": "Needs you",
    "rescreen_flags": "Roles to reconsider",
    "inbox": "Inbox",
    "lock": "Write lock",
    "runs": "Runs",
    "runs_effect": "Did the runs do anything",
    "dashboard": "Dashboard",
    "gates": "Gate health",
    "elsewhere": "Elsewhere",
    "tasks": "Run now",
    "band": "Band",
}

# The gates the coordinator's ORIENT step runs (scripts/coordinator.py section 4). Each is a
# read-only check; none writes.
GATES = (
    ("validate_data.py", [], "data integrity"),
    ("check_rule_homes.py", [], "no rule lost"),
    ("check_profile_leakage.py", [], "config is single-source"),
    ("resume_variants.py", ["--check"], "resume variants trace to the union"),
    ("trigger.py", ["--check"], "trigger/sequence links"),
    ("_tree.py", ["--audit"], "tree structure"),
)
GATE_TIMEOUT_S = 25

# The two pursuit states the DASHBOARD renders (design section 4): `new` (a decision is owed) and
# `not-sent` (pursuing, nothing sent). Every other live role is `in_flight` here.
DASHBOARD_STATES = ("new", "not-sent")


# ---- root resolution ---------------------------------------------------------------------------

def find_profile(start=None):
    """The profile the cwd is inside, via `CLAUDESEARCH_ROOT` or the cwd walk, or None.
    NEVER the remembered pointer, and never `_root.profile_root()` (which records one)."""
    import _root
    env = os.environ.get("CLAUDESEARCH_ROOT")
    if env:
        path = os.path.abspath(env)
        return path if _root.looks_like_profile(path) else None
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if _root.looks_like_profile(cur):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


# ---- small readers -----------------------------------------------------------------------------

def _jsonl(root, name):
    path = os.path.join(root, "data", name)
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        pass
    return rows


def _safe(fn, *args):
    """Run a section; an exception becomes {"error": ...}, never a silent empty value."""
    try:
        return fn(*args)
    except Exception as e:                                      # noqa: BLE001 - loud, not fatal
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}


def _company_names(root):
    return {c.get("id"): c.get("name") or c.get("id") for c in _jsonl(root, "companies.jsonl")}


# ---- the sections ------------------------------------------------------------------------------

def sec_needs_you(root, today):
    import coordinator
    import profile as _profile
    import your_move
    opps = _jsonl(root, "opportunities.jsonl")
    names = _company_names(root)
    owner = _profile.owner_token()
    out = []
    for o in opps:
        if o.get("next_action_owner") == owner and \
                o.get("status") in ("active-pursuit", "needs-resolution", "in-motion"):
            out.append({"kind": "role", "id": o.get("id"),
                        "title": "%s: %s" % (names.get(o.get("company_id"), "?"),
                                             o.get("title") or ""),
                        "act_by": o.get("next_action_date") or None})
    qs, _excluded = coordinator.open_fit_questions(opps)
    for by, o, r in qs:
        out.append({"kind": "question", "id": o.get("id"),
                    "title": "%s: %s" % (names.get(o.get("company_id"), "?"),
                                         str(r.get("question_for_candidate") or "")[:100]),
                    "act_by": None if by == "9999-99-99" else by})
    for a in your_move.open_asks(_jsonl(root, "asks.jsonl")):
        out.append({"kind": "ask", "id": a.get("id"),
                    "title": str(a.get("title") or a.get("ask") or a.get("id") or "")[:100],
                    "act_by": a.get("act_by") or None})
    out.sort(key=lambda r: (r["act_by"] or "9999-99-99", r["kind"], str(r["id"])))
    return out


def sec_rescreen_flags(root, today):
    """dev #761 (jobsearch 0.74.0): the roles `profile.comp_rescreen_flags` reports -- a stored comp
    removal that 0.73.0 would not repeat, on a role triage never reaches (decided or removed). READ-ONLY:
    it composes that one detector and writes nothing; the engine never reopens a row on its own. The
    flag leaves when the candidate runs `record.py screened <id>` or re-decides the role."""
    import profile as _profile
    names = _company_names(root)
    out = _profile.comp_rescreen_flags(_jsonl(root, "opportunities.jsonl"), _profile.load())
    items = []
    for f in out["flags"]:

        items.append({"id": f["id"], "status": f["status"],
                      "title": "%s: %s" % (names.get(f.get("company_id"), "?"), f.get("title") or ""),
                      "old_verdict": f["old_verdict"], "new_verdict": f["new_verdict"],
                      "why": f["why"], "action": f["action"]})
    return {"count": len(items), "unreadable": list(out["unreadable"]), "items": items}


def sec_inbox(root, today):
    import inbox
    rows = inbox.replay(_jsonl(root, "inbox.jsonl"))
    pending = [r for r in rows if r.get("status") == "pending"]
    return {"unacked": len(pending),
            "urgent": sum(1 for r in pending if r.get("urgency") == "high")}


def sec_lock(root, today):
    import runlock
    rec = runlock.read()
    if not rec:
        return {"held": False, "by": None, "since": None, "stale": False}
    age = runlock.age_minutes(rec)
    stale = age is None or age >= runlock.STALE_MINUTES
    return {"held": not stale, "by": rec.get("who"), "since": rec.get("taken_at"),
            "stale": bool(stale)}


def next_cron(expr, after):
    """The first minute strictly after `after` that matches a 5-field cron `expr` (lists, ranges,
    steps and `*` only), or None when it does not parse or matches nothing within 8 days."""
    try:
        fields = expr.split()
        if len(fields) != 5:
            return None
        bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
        sets = []
        for f, (lo, hi) in zip(fields, bounds):
            vals = set()
            for part in f.split(","):
                step = 1
                if "/" in part:
                    part, s = part.split("/", 1)
                    step = int(s)
                if part == "*":
                    a, b = lo, hi
                elif "-" in part:
                    a, b = (int(x) for x in part.split("-", 1))
                else:
                    a = b = int(part)
                if step < 1 or a < lo or b > hi or a > b:
                    return None
                vals.update(range(a, b + 1, step))
            sets.append(vals)
    except (ValueError, AttributeError):
        return None
    t = after.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    for _ in range(8 * 24 * 60):
        if t.minute in sets[0] and t.hour in sets[1] and t.month in sets[3] \
                and t.day in sets[2] and (t.isoweekday() % 7) in sets[4]:
            return t
        t += datetime.timedelta(minutes=1)
    return None


def sec_runs(root, now):
    import check_runs
    import posture
    fp = check_runs.footprints(root)
    starts = fp.get("run_starts") or []
    last = starts[0] if starts else {}
    nxt = None
    _name, p, err = posture.load()
    if p and p.get("cron"):
        n = next_cron(str(p["cron"]), now)
        nxt = n.isoformat(timespec="minutes") if n else None
    return {"last_at": last.get("at"), "last_task": last.get("kind"),
            "next_at": nxt, "next_task": TASKS["daily"],
            "next_weekly": "Sunday evening", "next_weekly_task": TASKS["weekly"]}


def sec_runs_effect(root, today):
    import check_runs
    fp = check_runs.footprints(root)
    starts = fp.get("run_starts") or []
    if not starts:
        return {"verdict": "no-runs-recorded",
                "detail": "no run has recorded a start in the journal"}
    last_day = str(starts[0].get("at") or "")[:10]
    latest = str(fp.get("latest") or "")
    flags = []
    if fp.get("end_missing_footprint"):
        flags.append("%d run(s) ended with no footprint" % len(fp["end_missing_footprint"]))
    if fp.get("summary_disagreements"):
        flags.append("%d summary disagreement(s)" % len(fp["summary_disagreements"]))
    if fp.get("board_all_clean_flag"):
        flags.append("the board has been all-clean for %d runs" % fp.get("board_all_clean_streak", 0))
    if latest and last_day and latest >= last_day:
        verdict, detail = "did-work", "the last run left a footprint on %s" % latest
    else:
        verdict, detail = "ran-quiet", "the last run (%s) left no log or inbox footprint" % last_day
    if flags:
        detail += "; " + "; ".join(flags)
    return {"verdict": verdict, "detail": detail}


def sec_dashboard(root, today):
    import check_dashboard_fresh
    state, _lines, per_page = check_dashboard_fresh.publish_state()
    as_of = None
    try:
        page = os.path.join(root, "views", "dashboard_artifact.html")
        if os.path.exists(page):
            as_of = datetime.datetime.fromtimestamp(
                check_dashboard_fresh.mtime(page)).isoformat(timespec="minutes")
    except Exception:                                           # noqa: BLE001 - no file yet
        as_of = None
    return {"state": state, "as_of": as_of}


def _run_gate(item, root):
    name, extra, label = item
    env = dict(os.environ, CLAUDESEARCH_ROOT=root)
    try:
        rc = subprocess.run([sys.executable, os.path.join(HERE, name)] + extra,
                            capture_output=True, text=True, env=env,
                            timeout=GATE_TIMEOUT_S).returncode
        return {"name": label, "ok": rc == 0}
    except subprocess.TimeoutExpired:
        return {"name": label, "ok": None, "error": "not checked (timed out)"}


def sec_gates(root, today):
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(GATES)) as ex:
        return list(ex.map(lambda g: _run_gate(g, root), GATES))


def sec_elsewhere(root, today):
    """The HOMES of every record the review-now dashboard no longer renders (design section 4/5).
    `scripts/check_dashboard_coverage.py` reads this object and refuses an `elsewhere:panel` record
    whose id is not in the list its kind maps to, so what is listed here is a CONTRACT:

        opp:<id>      -> in_flight   every live role that is neither `new` nor `not-sent` (the two states the
                                     dashboard renders), including triaging, parked and unclassifiable ones
        ask:<id>      -> asks        every open ask
        commit:<id>   -> week        every commitment still ahead, plus every one whose date cannot be placed
        chan:<id>     -> channels_due   EVERY channel, with its review state (the due ones first)
        prep:<rel>    -> kb_index    every call prep and company knowledge file
    """
    import applications as _apps
    import channels_due
    import conversations
    import knowledge
    import profile as _profile
    import validate_data
    import your_move
    out = {k: [] for k in ELSEWHERE_KEYS}
    names = _company_names(root)
    opps = _jsonl(root, "opportunities.jsonl")
    _apps.enrich_opportunities(root, opps)
    owner = _profile.owner_token()
    terminal = validate_data.TERMINAL_OPP_STATUSES
    roles = {o.get("id"): st for o, st, _w in your_move.classify_opportunities(opps, owner)
             if o.get("id")}
    for o in opps:
        if not o.get("id") or o.get("status") in terminal:
            continue
        try:
            st = your_move.pursuit_state(root, o, o.get("_applications") or []).get("state")
        except Exception:                                        # noqa: BLE001 - loud, never dropped
            st = "unclassifiable"
        if st == "new" and roles.get(o["id"]) == "triaging":
            st = "triaging"                                      # the run is still reading it
        if st in DASHBOARD_STATES:
            continue                                             # rendered on the dashboard
        out["in_flight"].append({"id": o.get("id"), "state": st,
                                 "title": "%s: %s" % (names.get(o.get("company_id"), "?"),
                                                      o.get("title") or ""),
                                 "kb_path": _kb_path_for(root, o.get("company_id"))})
    chans = _jsonl(root, "channels.jsonl")
    seen = set()
    for c, state, detail in sorted(channels_due.review_rows(chans, today),
                                   key=lambda r: (r[1] != "due", str(r[0].get("id")))):
        seen.add(c.get("id"))
        out["channels_due"].append({"id": c.get("id"), "title": c.get("name") or c.get("id"),
                                    "state": state, "why": detail.get("why")})
    for c in chans:                                              # relationship channels have no review row
        if c.get("id") and c.get("id") not in seen:
            out["channels_due"].append({"id": c.get("id"), "title": c.get("name") or c.get("id"),
                                        "state": "relationship", "why": "reviewed on inbound"})
    report = {r.get("id"): r for r in conversations.report(root, today=today) if r.get("id")}
    for c in _jsonl(root, "commitments.jsonl"):
        if not c.get("id") or str(c.get("status") or "") == "cancelled":
            continue
        raw = str(c.get("date") or "")
        try:
            ahead = datetime.date.fromisoformat(raw) >= today
        except ValueError:
            ahead = True                                         # unplaceable: an unknown, never a pass
        if not ahead:
            continue
        r = report.get(c["id"]) or {}
        row = {"id": c["id"], "date": raw, "time": c.get("time") or "",
               "title": c.get("title") or c["id"], "counterparty": r.get("counterparty_name") or "",
               "state": r.get("state") or conversations.BEYOND_HORIZON, "preps": r.get("preps") or []}
        out["week"].append(row)
        if r.get("state") in ("owed", "owed-partial"):
            out["preps_owed"].append(row)
    out["week"].sort(key=lambda r: (str(r["date"]), str(r["time"])))
    for a in your_move.open_asks(_jsonl(root, "asks.jsonl")):
        out["asks"].append({"id": a.get("id"), "kind": a.get("kind"),
                            "title": str(a.get("title") or a.get("ask") or a.get("id") or "")[:100],
                            "act_by": a.get("act_by") or None})
    for r in knowledge.report(root):
        out["kb_index"].append({"id": r.get("file"), "path": r.get("file"), "kind": r.get("kind"),
                                "state": r.get("state")})
    return out


def _kb_path_for(root, company_id):
    if not company_id:
        return None
    rel = os.path.join("pipeline", "kb", "%s.md" % company_id)
    return rel if os.path.exists(os.path.join(root, rel)) else None


# ---- composition -------------------------------------------------------------------------------

def collect(root, full=True, today=None, now=None, only=None):
    """The panel object. `only` (a set of top-level keys) computes just those sections - the dashboard
    coverage check asks for `elsewhere` alone, which skips the six gate subprocesses."""
    now = now or datetime.datetime.now()
    today = today or now.date()
    wanted = (lambda k: only is None or k in only)
    obj = {}
    if wanted("needs_you"):
        obj["needs_you"] = _safe(sec_needs_you, root, today)
    if wanted("rescreen_flags"):
        obj["rescreen_flags"] = _safe(sec_rescreen_flags, root, today)
    if wanted("inbox"):
        obj["inbox"] = _safe(sec_inbox, root, today)
    if wanted("lock"):
        obj["lock"] = _safe(sec_lock, root, today)
    if wanted("runs"):
        obj["runs"] = _safe(sec_runs, root, now)
    if wanted("runs_effect"):
        obj["runs_effect"] = _safe(sec_runs_effect, root, today)
    if only is None or "tasks" in only:
        obj["tasks"] = dict(TASKS)
    if full:
        if wanted("dashboard"):
            obj["dashboard"] = _safe(sec_dashboard, root, today)
        if wanted("gates"):
            obj["gates"] = _safe(sec_gates, root, today)
        if wanted("elsewhere"):
            obj["elsewhere"] = _safe(sec_elsewhere, root, today)
    obj["band"] = band_line(obj)
    return obj


def band_line(obj):
    """The one line under the prompt. Every number comes from `obj`; nothing is guessed."""
    parts = ["jobsearch"]
    ny = obj.get("needs_you")
    if isinstance(ny, list):
        dated = sorted(r["act_by"] for r in ny if r.get("act_by"))
        parts.append("%d need you%s" % (len(ny), " (next by %s)" % dated[0] if dated else ""))
    elif ny is not None:
        parts.append("needs-you NOT CHECKED")
    rf = obj.get("rescreen_flags")
    if isinstance(rf, dict) and rf.get("count"):
        parts.append("%d to reconsider" % rf["count"])
    elif isinstance(rf, dict) and "error" in rf:
        parts.append("reconsider NOT CHECKED")
    ib = obj.get("inbox")
    if isinstance(ib, dict) and "unacked" in ib:
        parts.append("inbox %d%s" % (ib["unacked"], " (%d urgent)" % ib["urgent"] if ib["urgent"] else ""))
    lk = obj.get("lock")
    if isinstance(lk, dict) and lk.get("held"):
        parts.append("lock held by %s" % (lk.get("by") or "?"))
    rn = obj.get("runs")
    if isinstance(rn, dict) and rn.get("last_at"):
        eff = obj.get("runs_effect")
        verdict = {"did-work": "did work", "ran-quiet": "quiet"}.get(
            (eff or {}).get("verdict"), "") if isinstance(eff, dict) else ""
        parts.append("last run %s%s" % (str(rn["last_at"])[11:16] or str(rn["last_at"]),
                                        " " + verdict if verdict else ""))
    return " · ".join(parts)


def _na(section):
    return "NOT CHECKED (%s)" % section["error"] if isinstance(section, dict) and "error" in section \
        else None


def render_text(obj):
    L = []
    add = L.append
    add("%s: %s" % (LABELS["band"], obj.get("band", "")))
    ny = obj.get("needs_you")
    add("")
    add("%s:" % LABELS["needs_you"])
    if _na(ny):
        add("  " + _na(ny))
    elif not ny:
        add("  nothing is waiting on you")
    else:
        for r in ny:
            add("  - [%s] %s %s: %s" % (r.get("act_by") or "no date", r["kind"], r.get("id"), r.get("title")))
    rf = obj.get("rescreen_flags")
    add("%s:" % LABELS["rescreen_flags"])
    if _na(rf):
        add("  " + _na(rf))
    elif not rf["count"] and not rf["unreadable"]:
        add("  none: no stored comp removal would be screened differently today")
    else:
        if rf["count"]:
            add("  %d role%s a stored comp removal that jobsearch 0.73.0 would not repeat. Nothing was "
                "changed: only you reopen or dismiss them." % (rf["count"], " has" if rf["count"] == 1
                                                                 else "s have"))
        if rf["unreadable"]:
            add("  NOT CHECKED: %d role(s) could not be re-screened: %s"
                % (len(rf["unreadable"]), ", ".join(map(str, rf["unreadable"]))))
        for r in rf["items"]:
            add("  - %s (%s): was %s, now %s. %s" % (r["title"], r["id"], r["old_verdict"],
                                                    r["new_verdict"], r["why"]))
            add("      to reopen: %s" % r["action"])
    ib = obj.get("inbox")
    add("%s: %s" % (LABELS["inbox"], _na(ib) or "%d pending, %d urgent" % (ib["unacked"], ib["urgent"])))
    lk = obj.get("lock")
    if _na(lk):
        add("%s: %s" % (LABELS["lock"], _na(lk)))
    elif lk.get("held"):
        add("%s: HELD by %s since %s" % (LABELS["lock"], lk.get("by"), lk.get("since")))
    else:
        add("%s: free%s" % (LABELS["lock"], " (a stale record from %s is ignorable)" % lk["since"]
                            if lk.get("stale") and lk.get("since") else ""))
    rn = obj.get("runs")
    if _na(rn):
        add("%s: %s" % (LABELS["runs"], _na(rn)))
    else:
        add("%s: last %s (%s); next %s (%s); weekly %s (%s)" % (
            LABELS["runs"], rn.get("last_at") or "none recorded", rn.get("last_task") or "-",
            rn.get("next_at") or "unknown", rn.get("next_task"),
            rn.get("next_weekly"), rn.get("next_weekly_task")))
    re_ = obj.get("runs_effect")
    add("%s: %s" % (LABELS["runs_effect"],
                    _na(re_) or "%s - %s" % (re_["verdict"], re_["detail"])))
    if "dashboard" in obj:
        db = obj["dashboard"]
        add("%s: %s" % (LABELS["dashboard"], _na(db) or "%s (generated %s)" % (db["state"], db.get("as_of") or "never")))
        gs = obj["gates"]
        if _na(gs):
            add("%s: %s" % (LABELS["gates"], _na(gs)))
        else:
            add("%s:" % LABELS["gates"])
            for g in gs:
                add("  - %s: %s" % (g["name"], "ok" if g["ok"] else
                                    ("not checked (timed out)" if g["ok"] is None else "FAILING")))
        el = obj["elsewhere"]
        add("%s:" % LABELS["elsewhere"])
        if _na(el):
            add("  " + _na(el))
        else:
            titles = {"in_flight": "In flight", "week": "This week", "channels_due": "Channels due",
                      "preps_owed": "Preps owed", "asks": "Open asks", "kb_index": "Knowledge index"}
            for k in ELSEWHERE_KEYS:
                add("  %s (%d):" % (titles[k], len(el[k])))
                rows = [r for r in el[k] if not (k == "channels_due" and r.get("state") != "due")]
                for r in rows[:12]:
                    add("    - %s" % (r.get("title") or r.get("id") or r.get("path")))
    else:
        add("(fast mode: %s, %s and %s are not computed; run with --full)" % (
            LABELS["dashboard"].lower(), LABELS["gates"].lower(), LABELS["elsewhere"].lower()))
    t = obj.get("tasks") or {}
    add("%s: daily = %s, weekly = %s (start from the Desktop app's Scheduled sidebar)" % (
        LABELS["tasks"], t.get("daily"), t.get("weekly")))
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="The one source of jobsearch status (read-only).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--text", action="store_true")
    mode.add_argument("--probe", action="store_true")
    speed = ap.add_mutually_exclusive_group()
    speed.add_argument("--fast", action="store_true")
    speed.add_argument("--full", action="store_true")
    ap.add_argument("--today", help="YYYY-MM-DD, for deterministic tests")
    ap.add_argument("--sections", help="comma-separated top-level keys to compute (default: all)")
    args = ap.parse_args(argv)

    root = find_profile()
    if args.probe:
        print(json.dumps({"profile": root is not None, "root": root}))
        return 0 if root else 1
    if root is None:
        # Not inside a profile: say so loudly and draw nothing. Never fall back to a pointer.
        msg = {"error": "no profile here: the cwd is not inside a jobsearch profile"}
        print(json.dumps(msg) if args.json else "jobsearch: NOT CHECKED - " + msg["error"])
        return 1
    os.environ["CLAUDESEARCH_ROOT"] = root
    today = datetime.date.fromisoformat(args.today) if args.today else None
    now = datetime.datetime.combine(today, datetime.time(0, 0)) if today else None
    only = set(s.strip() for s in args.sections.split(",") if s.strip()) if args.sections else None
    if only is not None and args.text:
        print("panel.py: --sections is for --json only", file=sys.stderr)
        return 2
    if only is not None and not only <= set(LABELS):
        print("panel.py: unknown section(s) %s" % ", ".join(sorted(only - set(LABELS))), file=sys.stderr)
        return 2
    obj = collect(root, full=not args.fast, today=today, now=now, only=only)
    if args.json:
        print(json.dumps(obj, ensure_ascii=False))
    else:
        sys.stdout.write(render_text(obj))
    return 0


if __name__ == "__main__":
    sys.exit(main())
