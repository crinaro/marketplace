#!/usr/bin/env python3
"""The connection strategy, rendered from the rows: `views/network_strategy.md`.

⭐ WHY THIS EXISTS (dev #834, design-network-first §8.4, criterion G2). The search is led by
relationships, and the owner needs the whole network on one page: the search plans, each target
company with the people known there, this week's reach-out budget, the suggestions waiting on a
decision, the proposals out, and the summary numbers. It is NOT a dashboard section (round 2: the
dashboard is the page of decisions and the owner removed its top region in 0.84.0 C7); the
dashboard's "Not on this page" note names this file instead.

⭐⭐ IT IS A VIEW, AND A VIEW HAS NO STATE OF ITS OWN (ADR-022: derive from the rows, never store a
count). Three rules, each with a test (`test_strategy_view.py`):

  1. REBUILT FROM ROWS ONLY. The text is a function of `data/*.jsonl` and the date. It reads no
     other file: not `outreach/network.md`, not `config.json`, not the previous copy of itself. A
     sentinel planted in any of them never reaches the page.
  2. WRITTEN WHOLE, EVERY TIME. `write()` replaces the file atomically; there is no merge with
     what was there. A hand edit to the view is overwritten by the next rebuild, which is why its
     first line says to edit the rows. (The failure this prevents: a "preserve the candidate's
     edits" path turns a derived view into a second copy of the facts, and the two then disagree.)
  3. THE CANDIDATE'S NOTES ARE NEVER TOUCHED. `outreach/network.md` stays the candidate's own
     file; several scripts read it (READ by grep: `check_followups.py`), so repurposing its path
     would change what they read. The view lives at its own path, `_tree` key `network_strategy`
     (OURS: a new path for the view, rather than a migration of a file the candidate writes).

⭐ A GREEN PAGE IS NEVER AN UNCHECKED ONE (the gate rule, applied to a view: a missing thing must
not read as an empty thing). Three kinds of "nothing here" are kept apart:

  * a store the profile does not have (`no data/plans.jsonl ...`: the migration has not run),
  * a store that is present and has no matching rows (`none`), and
  * a number this view cannot compute, which prints `NOT CHECKED: <what> (<why>)` and is also
    listed once in a closing `Not checked` section. The numbers owned by other modules
    (`reachouts`, `access`, `funnel_report`, `your_move`, `graph.warmth`) are asked for, never
    re-derived here: a second implementation of the 3B7 timing or the coverage annotation is the
    drift this repo keeps fighting. A module that is absent, raises, or answers in a shape this
    view does not know is NOT CHECKED, never an empty section.
  * an unreadable row (invalid JSON, not an object) is listed under `Data problems`, never
    skipped in silence.

The signatures consumed are design §16.1's, and each is INFERRED where the design leaves the
return shape open (`access.table` rows, the `reachouts.due` action keys): the view renders a row
generically and reads only the keys named below (`person_id`, and the first of `line`, `text`,
`action` for an action's words), so a module that answers differently produces text, not a crash.

Usage:
    python3 strategy_view.py [--root <profile>] [--today YYYY-MM-DD] [--stdout]

Exit 0 after a write (or `--stdout`); 2 on a bad argument; 1 when the file cannot be written
(printed, never silent). It reads the data directory of the profile it is given and no real profile
unless one is named: with no `--root` it resolves the profile exactly as every other script does.

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _atomic
import _tree

# An open suggestion older than this is shown as stale; nothing resolves it automatically (§8.2).
STALE_SUGGESTION_DAYS = 28

# The stores this view reads, and nothing else (rule 1 above).
STORES = ("plans", "companies", "people", "touches", "asks", "proposals")

_NOT_IN_ENGINE = "module not in this engine"


# ---- reading rows ------------------------------------------------------------------------------

class Rows:
    """Every store, loaded once. `absent` is the set of stores with no file (a state of its own:
    a profile the migration has not reached), `problems` every unreadable line."""

    def __init__(self, root):
        self.root = root
        self.rows = {}
        self.absent = set()
        self.problems = []
        for store in STORES:
            self.rows[store] = self._load(store)

    def _load(self, store):
        path = os.path.join(self.root, "data", store + ".jsonl")
        if not os.path.exists(path):
            self.absent.add(store)
            return []
        out = []
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError as e:
                    self.problems.append("data/%s.jsonl line %d: invalid JSON (%s)" % (store, n, e))
                    continue
                if not isinstance(row, dict):
                    self.problems.append("data/%s.jsonl line %d: not an object" % (store, n))
                    continue
                out.append(row)
        return out

    def __getitem__(self, store):
        return self.rows[store]

    def people_by_id(self):
        return {r.get("id"): r for r in self.rows["people"] if r.get("id")}

    def survivor(self, person_id, by_id=None):
        """The living person `person_id` resolves to through `merged_into`, or None (no such row,
        or a merge loop, which is reported once under Data problems)."""
        by_id = by_id if by_id is not None else self.people_by_id()
        seen = set()
        cur = by_id.get(person_id)
        while cur is not None and cur.get("status") == "merged" and cur.get("merged_into"):
            if cur.get("id") in seen:
                msg = "data/people.jsonl: merge loop through %r" % cur.get("id")
                if msg not in self.problems:
                    self.problems.append(msg)
                return None
            seen.add(cur.get("id"))
            cur = by_id.get(cur["merged_into"])
        return cur


# ---- the optional collaborators ----------------------------------------------------------------

def _optional(name):
    """The module `name`, or None when it is not part of this engine. A module that IS there but
    fails to import (a missing dependency of its own) raises: that is a defect, not an absence."""
    try:
        return importlib.import_module(name)
    except ImportError as e:
        if getattr(e, "name", None) == name:
            return None
        raise


class _Run:
    """One rebuild: the rows, the date, and every number this view could not compute."""

    def __init__(self, root, today, rows=None):
        self.root = root
        self.today = today
        self.rows = rows if rows is not None else Rows(root)
        self.unchecked = []

    def not_checked(self, what, why):
        self.unchecked.append((what, why))
        return "NOT CHECKED: %s (%s)" % (what, why)

    def ask(self, what, modname, fn, *args):
        """(True, value) from `modname.fn(*args)`, or (False, the NOT CHECKED line)."""
        try:
            mod = _optional(modname)
        except Exception as e:                                   # a broken module is not an absence
            return False, self.not_checked(what, "%s did not import: %s: %s"
                                           % (modname, type(e).__name__, e))
        if mod is None or not hasattr(mod, fn):
            return False, self.not_checked(what, "%s.%s: %s" % (modname, fn, _NOT_IN_ENGINE))
        try:
            return True, getattr(mod, fn)(*args)
        except Exception as e:
            return False, self.not_checked(what, "%s.%s raised %s: %s"
                                           % (modname, fn, type(e).__name__, e))


# ---- text helpers ------------------------------------------------------------------------------

def _t(v):
    """One line of free text from a row value."""
    return " ".join(str(v).split()) if v is not None else ""


def _stated(v):
    """A field the owner states: a missing or empty one reads `not stated`, never a guess."""
    return _t(v) or "not stated"


def _cell(v):
    if isinstance(v, (dict, list)):
        v = json.dumps(v, sort_keys=True, ensure_ascii=False)
    return _t(v).replace("|", "\\|")


def _date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _days_ago(today, s):
    d = _date(s)
    return None if d is None else (today - d).days


def _sort_key(row, *fields):
    return tuple(_t(row.get(f)).lower() for f in fields) + (_t(row.get("id")),)


def _ties(person):
    ties = person.get("ties")
    if ties is None:
        return "ties unknown"                       # absent means unknown, never "no ties" (§4.3)
    if not isinstance(ties, list) or not ties:
        return "no ties stated"
    out = []
    for t in ties:
        if isinstance(t, dict):
            out.append(_t(t.get("kind")) + (" via %s" % _t(t["via"]) if t.get("via") else ""))
        else:
            out.append(_t(t))
    return "ties: " + ", ".join(out)


def _action_words(a):
    if isinstance(a, dict):
        for k in ("line", "text", "action"):
            if a.get(k):
                return _t(a[k])
        return json.dumps(a, sort_keys=True, ensure_ascii=False)
    return _t(a)


def _unbudgeted_words(a):
    """One unbudgeted line (a reconnect or a role-specific draft owed) in words: who, where, and why."""
    if isinstance(a, dict) and a.get("person_id"):
        who = _t(a.get("person_name")) or _t(a["person_id"])
        where = _t(a.get("company_name")) or _t(a.get("company_id"))
        roles = a.get("opp_ids")
        return "%s (`%s`)%s: %s%s" % (who, _t(a["person_id"]), " at %s" % where if where else "", _t(a.get("why")),
                                      " [roles: %s]" % ", ".join(_t(o) for o in roles) if roles else "")
    return _action_words(a)


# ---- sections ----------------------------------------------------------------------------------

def _absent(run, store):
    return "No `data/%s.jsonl` in this profile (the 0.86.0 migration has not run)." % store


def _search_plans(run):
    out = ["## Search plans", ""]
    if "plans" in run.rows.absent:
        return out + [_absent(run, "plans"), ""]
    plans = [p for p in run.rows["plans"]
             if p.get("subject_kind") == "search" and (p.get("status") or "active") != "retired"]
    if not plans:
        return out + ["No active search plan.", ""]
    for p in sorted(plans, key=lambda r: _sort_key(r)):
        out.append("### %s" % _t(p.get("id")))
        out.append("- Outcomes: %s" % (", ".join(_t(o) for o in p.get("outcomes") or []) or "not stated"))
        out.append("- Goal: %s" % _stated(p.get("goal")))
        out.append("- Approach: %s" % _stated(p.get("approach")))
        out.append("")
    return out


def _targets(run, due_by_person, warmth):
    out = ["## Targets", ""]
    if "companies" in run.rows.absent:
        return out + [_absent(run, "companies"), ""]
    targets = [c for c in run.rows["companies"] if c.get("status") == "active-target"]
    if not targets:
        return out + ["No company is an active target.", ""]
    people = run.rows["people"]
    by_id = run.rows.people_by_id()
    last_touch = {}
    for t in run.rows["touches"]:
        s = run.rows.survivor(t.get("person_id"), by_id)
        d = _t(t.get("date"))
        if s is not None and d and d > last_touch.get(s.get("id"), ""):
            last_touch[s.get("id")] = d
    plans = [p for p in run.rows["plans"]
             if p.get("subject_kind") == "company" and (p.get("status") or "active") != "retired"]
    for c in sorted(targets, key=lambda r: _sort_key(r, "name")):
        cid = c.get("id")
        out.append("### %s (`%s`)" % (_t(c.get("name")) or _t(cid), _t(cid)))
        m = c.get("motivation")
        out.append("- Motivation: %s" % ("%s of 5" % m if m is not None else "not stated"))
        mine = [p for p in plans if p.get("subject_id") == cid]
        if not mine:
            out.append("- Plan: none")
        for p in sorted(mine, key=lambda r: _sort_key(r)):
            out.append("- Plan `%s`: goal %s; cadence %s"
                       % (_t(p.get("id")), _stated(p.get("goal")), _stated(p.get("cadence"))))
        here = [p for p in people if p.get("company_id") == cid and p.get("status") != "merged"]
        if not here:
            out.append("- People: none known")
        for p in sorted(here, key=lambda r: _sort_key(r, "name")):
            lt = last_touch.get(p.get("id"))
            ago = _days_ago(run.today, lt) if lt else None
            touch = ("last touch %s (%s days ago)" % (lt, ago) if ago is not None
                     else "last touch %s" % lt if lt else "no touch recorded")
            out.append("- %s (`%s`): warmth %s; %s; cadence %s; %s"
                       % (_t(p.get("name")), _t(p.get("id")), warmth(p.get("id")), _ties(p),
                          _stated(p.get("cadence")), touch))
            for a in due_by_person.get(p.get("id"), ()):
                out.append("  - 3B7 due: %s" % _action_words(a))
        out.append("")
    return out


def _week(run, due):
    out = ["## This week's reach-outs", ""]
    ok, plan = run.ask("this week's reach-out budget", "reachouts", "plan", run.root, run.today)
    if not ok:
        out.append(plan)
    elif not isinstance(plan, dict) or not isinstance(plan.get("remaining"), int):
        out.append(run.not_checked("this week's reach-out budget",
                                   "reachouts.plan answered without an integer `remaining`"))
    else:
        out.append("- Budget %s, spent %s, remaining %d" % (plan["budget"], plan["spent"], plan["remaining"])
                   if "budget" in plan and "spent" in plan else "- Remaining budget: %d" % plan["remaining"])
        for key in ("lines", "lookups", "reconnects", "role_specific"):
            v = plan.get(key)
            if isinstance(v, list) and v:                    # 0.90.3: a kind with nothing in it is no row of 0
                out.append("- %s: %d" % (key.replace("_", " ").capitalize(), len(v)))
                if key in ("reconnects", "role_specific"):       # design 9.1 and 16.1: the unbudgeted lines, each named
                    for item in v:
                        out.append("  - %s" % _unbudgeted_words(item))
        for u in plan.get("unobserved") or ():
            out.append("- Send unobserved: %s" % _action_words(u))
        for u in plan.get("age_unknown") or ():          # a draft whose age cannot be read is shown, never dropped
            out.append("- Draft age unknown: %s" % (
                "%s (%s), %s" % (_t(u.get("ref")), _t(u.get("person")), _t(u.get("reason"))) if isinstance(u, dict)
                else _action_words(u)))
    out.append("")
    ok, actions = due
    out.append("### Follow-ups due")
    out.append("")
    if not ok:
        out.append(actions)
    elif not isinstance(actions, list):
        out.append(run.not_checked("follow-ups due", "reachouts.due did not answer with a list"))
    elif not actions:
        out.append("Nothing due.")
    else:
        for a in actions:
            out.append("- %s" % _action_words(a))
    out.append("")
    return out


def _suggestions(run):
    out = ["## Open suggestions", ""]
    if "asks" in run.rows.absent:
        return out + [_absent(run, "asks"), ""]
    open_ = [a for a in run.rows["asks"]
             if a.get("kind") == "suggestion" and not a.get("resolved_on")]
    if not open_:
        return out + ["None waiting on a decision.", ""]
    for a in sorted(open_, key=lambda r: (_t(r.get("created")), _t(r.get("id")))):
        age = _days_ago(run.today, a.get("created"))
        if age is None:
            when = "created %s (date unreadable)" % (_t(a.get("created")) or "?")
            run.rows.problems.append("data/asks.jsonl: suggestion %r has no readable `created`"
                                     % a.get("id"))
        else:
            when = "created %s, %d days%s" % (_t(a.get("created")), age,
                                              ", STALE" if age > STALE_SUGGESTION_DAYS else "")
        out.append("- `%s` (%s): %s" % (_t(a.get("id")), when, _t(a.get("ask")) or _t(a.get("title"))))
        s = a.get("suggests")
        if isinstance(s, dict):
            out.append("  - suggests: %s %s %s %s" % (
                _t(s.get("store")), _t(s.get("op")), _t(s.get("id")),
                json.dumps(s.get("fields"), sort_keys=True, ensure_ascii=False)))
    out.append("")
    return out


def _proposals(run):
    out = ["## Proposals", ""]
    if "proposals" in run.rows.absent:
        return out + [_absent(run, "proposals"), ""]
    rows = sorted(run.rows["proposals"], key=lambda r: _sort_key(r))
    if not rows:
        return out + ["No proposal recorded.", ""]
    out += ["| Proposal | Opportunity | Status | Sent | Rate |", "|---|---|---|---|---|"]
    for p in rows:
        r = p.get("rate")
        rate = ("%s %s/%s" % (_t(r.get("amount")), _t(r.get("currency")), _t(r.get("per")))
                if isinstance(r, dict) else "not stated")
        out.append("| %s | %s | %s | %s | %s |" % (
            _cell(p.get("id")), _cell(p.get("opp_id")), _cell(p.get("status")),
            _cell(p.get("sent_on")) or "-", _cell(rate)))
    out.append("")
    return out


def _numbers(run):
    out = ["## Network numbers", ""]
    if "companies" not in run.rows.absent:
        targets = [c for c in run.rows["companies"] if c.get("status") == "active-target"]
        bare = [c for c in targets if c.get("motivation") is None]
        out.append("- Targets with no stated motivation: %d of %d" % (len(bare), len(targets)))
    ok, li = run.ask("look-into companies", "your_move", "classify_companies", run.root, run.today)
    if not ok:
        out.append("- " + li)
    elif not isinstance(li, dict):
        out.append("- " + run.not_checked("look-into companies",
                                          "your_move.classify_companies did not answer with a mapping"))
    else:
        out.append("- Look-into raised: %d; waiting: %s" % (len(li.get("look-into") or ()),
                                                           li.get("look-into-waiting", 0)))
    ok, text = run.ask("the network funnel (reach-outs, chats, intros, follow-ups)",
                       "funnel_report", "network_section", run.root, run.today)
    out.append("")
    if not ok:
        out.append(text)
    else:
        out += ["```text", str(text).rstrip("\n"), "```"]
    out.append("")
    return out


def _lamp(run):
    out = ["## LAMP table", ""]
    ok, table = run.ask("the LAMP table", "access", "table", run.root, run.today)
    if not ok:
        return out + [table, ""]
    if not isinstance(table, list) or not all(isinstance(r, dict) for r in table):
        return out + [run.not_checked("the LAMP table", "access.table did not answer with rows"), ""]
    if not table:
        return out + ["No target in the table.", ""]
    cols = []
    for r in table:
        for k in r:
            if k not in cols:
                cols.append(k)
    out.append("| " + " | ".join(_cell(c) for c in cols) + " |")
    out.append("|" + "---|" * len(cols))
    for r in table:
        out.append("| " + " | ".join(_cell(r.get(c)) for c in cols) + " |")
    out.append("")
    return out


# ---- the view ----------------------------------------------------------------------------------

def render(root, today=None, rows=None):
    """The whole view as text. Pure over the rows and `today`: it touches no file but the stores."""
    today = today or _today()
    run = _Run(root, today, rows)
    due = run.ask("follow-ups due", "reachouts", "due", root, today)
    due_by_person = {}
    if due[0] and isinstance(due[1], list):
        for a in due[1]:
            if isinstance(a, dict) and a.get("person_id"):
                s = run.rows.survivor(a["person_id"])
                due_by_person.setdefault(s.get("id") if s else a["person_id"], []).append(a)

    # graph.warmth reads the data directory the PROCESS resolved, not `root`: answering for a
    # different profile would be confidently wrong, so it is asked only when the two agree.
    warm_why, graph = None, None
    try:
        graph = _optional("graph")
    except Exception as e:
        warm_why = "graph did not import: %s: %s" % (type(e).__name__, e)
    if warm_why is None:
        if graph is None or not hasattr(graph, "warmth"):
            warm_why = "graph.warmth: %s" % _NOT_IN_ENGINE
        elif (os.path.abspath(getattr(graph, "DATA", "") or "")
              != os.path.abspath(os.path.join(root, "data"))):
            warm_why = "graph.warmth reads a different data directory than this profile's"
    warm_errors = []

    def warmth(person_id):
        if warm_why:
            return "NOT CHECKED"
        try:
            return _t(graph.warmth(person_id, today))
        except Exception as e:
            warm_errors.append("%s: %s" % (type(e).__name__, e))
            return "NOT CHECKED"

    body = _targets(run, due_by_person, warmth)
    if warm_why:
        run.not_checked("warmth", warm_why)
    if warm_errors:
        run.not_checked("warmth", "graph.warmth raised %s" % warm_errors[0])

    lines = ["> Generated by strategy_view.py from the rows in data/, as of %s. Edit the rows "
             "(record.py), not this file: every rebuild overwrites it whole." % today.isoformat(),
             "", "# Network strategy", ""]
    lines += _search_plans(run) + body + _week(run, due) + _suggestions(run) + _proposals(run)
    lines += _numbers(run) + _lamp(run)
    if run.unchecked:
        lines += ["## Not checked", ""]
        seen = set()
        for what, why in run.unchecked:
            if (what, why) not in seen:
                seen.add((what, why))
                lines.append("- %s: %s" % (what, why))
        lines.append("")
    if run.rows.problems:
        lines += ["## Data problems", ""] + ["- %s" % p for p in sorted(set(run.rows.problems))] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def view_path(root):
    """Where the view lives: `_tree` key `network_strategy`, never the candidate's notes."""
    return _tree.path(root, "network_strategy")


def write(root, today=None):
    """Rebuild the view and replace the file whole and atomically. Returns the path written."""
    text = render(root, today)
    dest = view_path(root)
    _atomic.write_text(dest, text)
    return dest


def _today():
    import _localzone
    tz = _localzone.local_zone()
    now = datetime.datetime.now(tz) if tz is not None else datetime.datetime.now().astimezone()
    return now.date()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="the profile root (default: resolved as every script does)")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today in the candidate's zone)")
    ap.add_argument("--stdout", action="store_true", help="print the view, write nothing")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    today = None
    if args.today:
        today = _date(args.today)
        if today is None:
            print("strategy_view: --today must be YYYY-MM-DD, got %r" % args.today)
            return 2
    root = args.root
    if not root:
        from _root import profile_root
        root = profile_root()
    if args.stdout:
        sys.stdout.write(render(root, today))
        return 0
    try:
        dest = write(root, today)
    except OSError as e:
        print("strategy_view: could not write the view: %s" % e)
        return 1
    print("strategy_view: wrote %s" % os.path.relpath(dest, root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
