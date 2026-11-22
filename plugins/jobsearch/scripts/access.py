#!/usr/bin/env python3
"""access.py — the reach table: how far into each target company the candidate's network gets, DERIVED
from the rows every time, never stored (ADR-031 B5b / design-network-first.md sections 4.2 and 10.2, dev #834).

    python3 scripts/access.py [--since YYYY-MM-DD] [--by vertical] [--json] [--as-of YYYY-MM-DD]

THE QUESTION. "Is my access to the companies I want improving?" has to cash out as numbers that move when
the candidate does the work and do not move when they do not. One row per `active-target` company:

    company   M  alumni  known  contacted  warm  chats_held  open_intros  path       posting        last_contact
    globex    4       1      3          2     1           1            0  direct     2 · 2026-11-03  2026-11-06
    initech   ?       0      0          0     0           0            1  via-intro  0 · —          2026-10-20

  M            STATED by the candidate (`companies.motivation`, 1-5), passed through. `?` is "not stated",
               counted under the table ("N targets have no stated motivation"), never guessed.
  alumni       DERIVED (LAMP's A): the people at the company with a stated tie (`people.ties`, non-empty).
               The engine never asserts whom a contact knows (ADR-031 decision 5); ties are the candidate's.
  known / contacted / warm
               DERIVED per person by `graph.warmth()` and counted by tier. The tiers are exclusive: each
               person is in exactly one, so the three add up to the CURRENT employees the table knows there.
  unconf       people whose employment there is unconfirmed (0.91.0, design-build-reach.md 5.3): not counted
               in any column, listed above the table with the verb. A former employee is never counted either
               (`standing.former` in --json). Every column above reads `reach.standing_rows` at the row's date.
  chats_held   DERIVED: `kind: chat` commitments with `attendance: held` with a person at the company. A
               chat in the past with no `attendance` is UNRECORDED and is never counted as not held: the
               cell reads `N+` and the table names the unrecorded ids (design section 0 item 7).
  open_intros  DERIVED: introductions asked for or offered toward the company, not yet landed (below).
  path         `direct` if anyone there is warm; else `via-intro` if an introduction is open; else `none`.
               It counts only what is recorded: the engine does not know whom your contacts know.
  posting      DERIVED (LAMP's P): `<live roles> · <newest sighting date>`, from `opportunities.sightings`.
  last_contact the newest dated exchange with anyone there (a sent touch, a reply date, a message, a held chat).

NOTHING HERE IS A STORED COUNT. Alumni, posting and every tier are read from the rows on each call, so there
is no second copy of a fact to drift (ADR-022, ADR-001). A change that makes any column come from a stored
field is the defect this file exists to refuse (test_access.py plants it).

OPEN INTRODUCTIONS, as the design states them (section 10.1 rows (b) and (c), and section 12 of
design-connected-entities.md):
  * an `intro-request` touch, `status: sent`, still `awaiting` as of the date, whose object is the company
    or a person at it; or
  * an `intros_given` entry on a non-cancelled chat naming the company or a person at it;
  and in both cases NOT YET LANDED: a touch with `trigger_kind: introduction` whose `trigger_ref` is
  `touch:<the request id>` or `commitment:<the chat id>` (for an offer naming a person, the landing touch
  is to that person; naming a company, to someone at it) and dated on or before the date.
  Never a side-door ask (`build_kind: side-door`, 0.91.0, owner O17): an ask to a stranger is an action, not an
  introduction, so the company stays `path none`. `--json` adds each row's derived `reach` block (`reach/block.py`).

MOVEMENT BY REPLAY. `--since D` recomputes the same table AS OF `D` from the same dated rows (a touch's
`date`, a message's `sent_on`, a reply's `responded_on`, a chat's `date` and `attendance_on`) and prints what
moved: `path none -> via-intro`, a person `contacted -> warm`. No snapshot is stored. LIMITS, stated so a
reader is not misled: a role's `status` and a person's `ties` carry no date, so Posting as of `D` is "the
roles live NOW whose sightings predate D" and Alumni changes only when a person is added; a company whose
`status_on` falls after `D` is reported as a NEW TARGET, and a company that WAS a target and no longer is
cannot be replayed (its status was overwritten), so it is absent. Employment (0.91.0) is replayed by its learned
dates: a person confirmed after `D` was unconfirmed at `D`, and one marked former after `D` still counted there.
Its limits: (1) a replay to before the 0.91.0 stamp uses the new rule at both ends, so the upgrade is never a move
and pre-upgrade counts are not reproduced; (2) `moved --to` a company in `formerly` removes that entry, so the
earlier spell is no longer replayable; (3) a merged person replays with the survivor's fields.

LOUD, NEVER EMPTY. No `active-target` company prints `NO TARGETS DECLARED` and says how to declare one,
never an empty table. A profile with no `data/` directory is `NOT CHECKED` (exit 1), never "no targets". An
unreadable date is exit 2.

CONFIG. `access.warm_days` (default 180, 30..365) is how long an answer keeps a person warm. It is a registered
key (`config_keys.ACCESS_WARM_DAYS`) resolved from `<root>/config.json` by `config_keys.resolve_int`: a present
value that is not an integer in range is a loud `ValueError`, never the default. `warm_days=` overrides the config.

Exit codes: 0 (a table, or NO TARGETS DECLARED, printed loudly), 1 NOT CHECKED, 2 a malformed argument.
Python 3.9+, standard library only, no network.

    import access
    access.table(root_or_graph, as_of, since=None, warm_days=None)  -> [row]
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config_keys as _ck  # noqa: E402
import graph as _graph  # noqa: E402
# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from reach.render import PATHS, NO_VERTICAL, by_vertical, unstated_motivation, _grid, _fmt_move, standing_lines
from reach import standing_rows as _rows  # noqa: E402
# 0.91.0 B4: the path and open introductions moved to reach/way_in.py (reachouts and brief ask the same question); the reach block
from reach.way_in import chat_dates as _chat_dates, landings as _landings, open_intros as _open_intros, path_word  # noqa: E402
from reach import block as _block, keys as _rk  # noqa: E402

WARM_DAYS_KEY = _ck.ACCESS_WARM_DAYS
WARM_DAYS_DEFAULT = _graph.WARM_DAYS     # test_access pins this equal to the registered default

# A role is live while its status is not terminal. The LIVE side is mirrored, never the terminal side
# (test_validate_data_records refuses a private copy of the terminal set), and never imported: `validate_data`
# needs a profile's user.json at import, and importing `lifecycle` would make this module a registered
# lifecycle surface. test_access pins this equal to `OPP_STATUS - TERMINAL_OPP_STATUSES`, and to
# `lifecycle.NON_TERMINAL_STATUSES`.
LIVE_OPP_STATUSES = frozenset(("active-pursuit", "needs-resolution", "in-motion", "backlog"))

NO_TARGETS = ("NO TARGETS DECLARED: no company has status active-target, so there is no access to measure. "
              "Declare the companies you most want to work at with `record.py company-status <id> "
              "active-target`; this is not an empty table, it is a missing list.")


class NotChecked(Exception):
    """The table cannot be answered (no profile data on disk). Never rendered as 'no targets'."""


# ---------------------------------------------------------------------------------------------------
# the context: a profile root, a Graph, or a lifecycle-style ctx
# ---------------------------------------------------------------------------------------------------

def _open(ctx_or_root):
    """`(graph, root_or_None)` for a profile root (a path), an already-built `Graph`, or a dict/object
    carrying one (`{"root": ...}` or a `lifecycle.Ctx` whose `.data` has the root). A root whose `data/`
    directory is missing raises `NotChecked`: a missing store must not read as an empty one."""
    if isinstance(ctx_or_root, _graph.Graph):
        root = os.path.dirname(os.path.abspath(ctx_or_root.data_dir))
        return ctx_or_root, root
    root = ctx_or_root
    if not isinstance(root, str):
        data = ctx_or_root if isinstance(ctx_or_root, dict) else getattr(ctx_or_root, "data", None)
        root = (data or {}).get("root") if isinstance(data, dict) else None
    if not isinstance(root, str) or not root:
        raise NotChecked("no profile root was given")
    data_dir = os.path.join(root, "data")
    if not os.path.isdir(data_dir):
        raise NotChecked("no data directory at %s" % data_dir)
    return _graph.Graph(data_dir), root


def _read_config(root):
    if not root:
        return {}
    path = os.path.join(root, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return {}
    except ValueError:
        raise ValueError("%s is not valid JSON" % path)
    return cfg if isinstance(cfg, dict) else {}


# ---------------------------------------------------------------------------------------------------
# one company, as of one date
# ---------------------------------------------------------------------------------------------------

def _iso(d):
    return d.isoformat() if d else None


def _has_ties(person):
    ties = person.get("ties")
    return isinstance(ties, list) and any(isinstance(t, dict) and t.get("kind") for t in ties)


def _posting(g, cid, as_of):
    """`{"live": n, "newest": iso|None}`: the company's non-terminal, non-folded roles that have a sighting
    on or before `as_of`, and the newest such sighting date."""
    live, newest = 0, None
    for o in g.opportunities_for_company(cid):
        if o.get("duplicate_of") or o.get("status") not in LIVE_OPP_STATUSES or o.get("stage") == "closed":
            continue
        seen = [d for d in (_graph.date_or_none(s.get("seen_on")) for s in (o.get("sightings") or [])
                            if isinstance(s, dict)) if d is not None and d <= as_of]
        if not seen:
            continue
        live += 1
        newest = max(newest, max(seen)) if newest else max(seen)
    return {"live": live, "newest": _iso(newest)}


def _row(g, company, as_of, warm_days, landings, recheck_days=_rows.RECHECK_DAYS):
    cid = company.get("id")
    tiers = {"warm": 0, "contacted": 0, "known": 0}
    people, alumni, held, unrecorded, dates = {}, 0, 0, [], []
    by = _rows.split(g.people_for_company(cid, standing=None, as_of=as_of), cid, as_of, recheck_days)   # 0.91.0: only `current` counts
    for p in by["current"]:
        pid = p["id"]
        w = g.warmth(pid, as_of, warm_days=warm_days)
        if w is None:
            continue
        people[pid] = w
        tiers[w] += 1
        if _has_ties(p):
            alumni += 1
        for t in g.touches_for_person(pid):
            for field in ("date", "responded_on"):
                d = _graph.date_or_none(t.get(field))
                if d is not None and d <= as_of and (field == "responded_on" or t.get("status") == "sent"):
                    dates.append(d)
        for m in g.messages_for_person(pid):
            d = _graph.date_or_none(m.get("sent_on"))
            if d is not None and d <= as_of:
                dates.append(d)
        for c in g.commitments_for_person(pid):
            cd = _chat_dates(c)
            if cd is None:
                continue
            d, recorded = cd
            if c.get("attendance") == "held" and max(d, recorded) <= as_of:
                held += 1
                dates.append(d)
            elif not c.get("attendance") and d < as_of:
                unrecorded.append(c.get("id"))
    intros = _open_intros(g, cid, as_of, landings)
    path = path_word(tiers["warm"], intros)
    return {"company_id": cid, "name": company.get("name") or cid,
            "vertical": company.get("vertical"), "motivation": company.get("motivation"),
            "alumni": alumni, "known": tiers["known"], "contacted": tiers["contacted"],
            "warm": tiers["warm"], "chats_held": held, "chats_unrecorded": sorted(unrecorded),
            "open_intros": intros, "path": path, "posting": _posting(g, cid, as_of),
            "last_contact": _iso(max(dates)) if dates else None, "people": people, "standing": _rows.ids(by)}


# ---------------------------------------------------------------------------------------------------
# the table, and what moved since a date
# ---------------------------------------------------------------------------------------------------

def _moved(before, now, company, since):
    out = []
    status_on = _graph.date_or_none(company.get("status_on"))
    if status_on is not None and status_on > since:
        out.append({"what": "target", "from": None, "to": "active-target", "on": _iso(status_on)})
    if before["path"] != now["path"]:
        out.append({"what": "path", "from": before["path"], "to": now["path"]})
    for pid in sorted(set(now["people"]) | set(before["people"])):      # a departure leaves `now`: it is a move too
        was, is_ = before["people"].get(pid), now["people"].get(pid)
        if was != is_:
            out.append({"what": "person", "person_id": pid, "from": was, "to": is_})
    out += _rows.moves(before["standing"], now["standing"])
    for key in ("alumni", "chats_held", "open_intros"):
        if before[key] != now[key]:
            out.append({"what": key, "from": before[key], "to": now[key]})
    if before["posting"]["live"] != now["posting"]["live"]:
        out.append({"what": "posting", "from": before["posting"]["live"], "to": now["posting"]["live"]})
    return out


def table(ctx_or_root, as_of, since=None, warm_days=None):
    """One row per `active-target` company as of `as_of`, sorted by vertical then name. With `since`, each
    row also carries `since` (the ISO date) and `moved`: what changed between `since` and `as_of`, replayed
    from the same rows (module docstring). Returns [] when no company is a target; the CALLER says
    NO TARGETS DECLARED. Raises `NotChecked` for a profile with no data, `ValueError` for an unreadable
    date, a `since` after `as_of`, or a bad `access.warm_days`."""
    g, root = _open(ctx_or_root)
    days = warm_days if warm_days is not None else _ck.resolve_int(_read_config(root), WARM_DAYS_KEY)
    recheck = _ck.resolve_int(_read_config(root), _rk.ACCESS_EMPLOYMENT_RECHECK_DAYS)     # 0.91.0: a stale `current` is re-confirmed
    today = _graph.to_date(as_of)
    then = _graph.to_date(since) if since else None
    if then is not None and then > today:
        raise ValueError("--since %s is after the as-of date %s" % (then.isoformat(), today.isoformat()))
    now_landings = _landings(g, today)
    then_landings = _landings(g, then) if then else None
    rows = []
    for company in g.stores["companies"]:
        if company.get("status") != "active-target":
            continue
        row = _row(g, company, today, days, now_landings, recheck)
        if then is not None:
            before = _row(g, company, then, days, then_landings, recheck)
            row["since"] = then.isoformat()
            row["moved"] = _moved(before, row, company, then)
        rows.append(row)
    rows.sort(key=lambda r: (str(r["vertical"] or ""), str(r["name"]), str(r["company_id"])))
    return rows


# ---------------------------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------------------------

def render(rows, as_of, since=None, warm_days=WARM_DAYS_DEFAULT, vertical=False):
    if not rows:
        return NO_TARGETS
    today = _graph.to_date(as_of).isoformat()
    out = ["ACCESS  as of %s  (%d target%s; warm = answered or a chat held within %d days)"
           % (today, len(rows), "" if len(rows) == 1 else "s", warm_days)]
    if vertical:
        header = ["vertical", "companies", "alumni", "known", "contacted", "warm", "chats_held",
                  "open_intros", "direct", "via-intro", "none", "posting"]
        body = [[a["vertical"], a["companies"], a["alumni"], a["known"], a["contacted"], a["warm"],
                 a["chats_held"], a["open_intros"], a["paths"]["direct"], a["paths"]["via-intro"],
                 a["paths"]["none"], "%d · %s" % (a["posting_live"], a["posting_newest"] or "—")]
                for a in by_vertical(rows)]
    else:
        header = ["company", "M", "alumni", "known", "contacted", "warm", "unconf", "chats_held", "open_intros",
                  "path", "posting", "last_contact"]
        body = [[r["name"], r["motivation"] if r["motivation"] is not None else "?", r["alumni"],
                 r["known"], r["contacted"], r["warm"], len(r["standing"]["unconfirmed"]),
                 ("%d+" % r["chats_held"]) if r["chats_unrecorded"] else r["chats_held"],
                 r["open_intros"], r["path"],
                 "%d · %s" % (r["posting"]["live"], r["posting"]["newest"] or "—"),
                 r["last_contact"] or "—"] for r in rows]
    out.extend(standing_lines(rows))                     # 0.91.0: above the table, so the drop never reads as lost work
    out.extend(_grid(header, body, left=(0, 9, 10, 11) if not vertical else (0, 11)))
    unrecorded = [(r["name"], cid) for r in rows for cid in r["chats_unrecorded"]]
    if unrecorded:
        out.append("UNRECORDED CHATS (counted as 'N+', never as not held): %s -- record each with "
                   "`record.py attended <id> held|no-show`." % ", ".join("%s (%s)" % (c, n) for n, c in unrecorded))
    missing = unstated_motivation(rows)
    if missing:
        out.append("%d target%s no stated motivation (M = ?): %s" % (
            len(missing), " has" if len(missing) == 1 else "s have", ", ".join(missing)))
    thin = {}
    for r in rows:
        if r["path"] == "none":
            thin.setdefault(r["vertical"] or NO_VERTICAL, []).append(r["name"])
    if thin:
        out.append("THIN (path none), by vertical: " + "; ".join(
            "%s: %s" % (v, ", ".join(thin[v])) for v in sorted(thin)))
    if since:
        out.append("")
        out.append("MOVED since %s:" % _graph.to_date(since).isoformat())
        any_moved = False
        for r in rows:
            if r.get("moved"):
                any_moved = True
                out.append("  %s: %s" % (r["name"], "; ".join(_fmt_move(m) for m in r["moved"])))
        if not any_moved:
            out.append("  nothing moved: no company changed path, tier, chats, introductions or postings.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The reach table: access to each target company, derived.")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="also print what moved since this date (replayed)")
    ap.add_argument("--by", choices=["vertical"], help="roll the table up by vertical")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD", help="the date to compute for (default today)")
    args = ap.parse_args(argv)
    try:
        as_of = _graph.to_date(args.as_of) if args.as_of else datetime.date.today()
        since = _graph.to_date(args.since) if args.since else None
    except ValueError as e:
        print("access.py: %s" % e, file=sys.stderr)
        return 2
    try:
        from _root import is_unbound
        if is_unbound(_graph.ROOT):
            raise NotChecked("nothing identified a profile here")
        if not os.path.isdir(_graph.DATA):
            raise NotChecked("no data directory at %s" % _graph.DATA)
        days = _ck.resolve_int(_read_config(_graph.ROOT), WARM_DAYS_KEY)
        rows = table((g := _graph.Graph(_graph.DATA)), as_of, since=since, warm_days=days)
        if args.json:                                       # 0.91.0: the derived reach block (reach/block.py), never stored
            _block.attach(g, _graph.ROOT, _read_config(_graph.ROOT), days, rows, as_of)
    except NotChecked as e:
        print("NOT CHECKED: the access table cannot be answered (%s). This is not 'no targets'." % e)
        return 1
    except ValueError as e:
        print("access.py: %s" % e, file=sys.stderr)
        return 2
    if args.json:
        doc = {"as_of": as_of.isoformat(), "since": since.isoformat() if since else None,
               "warm_days": days, "targets": len(rows),
               "status": "ok" if rows else "no-targets", "message": None if rows else NO_TARGETS,
               "unstated_motivation": unstated_motivation(rows), "rows": rows}
        if args.by:
            doc["rollup"] = by_vertical(rows)
        print(json.dumps(doc, indent=2, default=str))
        return 0
    print(render(rows, as_of, since=since, warm_days=days, vertical=bool(args.by)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
