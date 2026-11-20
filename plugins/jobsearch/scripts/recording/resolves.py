"""resolves: what a landed write resolves under the same lock hold: the asks that declared this action answers them
(dev #133) and a plan whose goal the write reached.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import os
import tempfile
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, validate
from recording.store_files import STORES, find, load


ASKS_FILE = "asks.jsonl"
# ADR-031 B2/B3 — "applications" and (now) "outreach" both left this mapping empty: each named
# an ARRAY LEAF on the opportunities record, and neither array exists there any more (each
# promoted to its own top-level store). Both actions' ask-resolution now fire from their own
# store's write site directly (`_applications_action_evidence`/`_touches_action_evidence` and
# the two matching write-completion blocks in `main()`), never through this array-leaf mapping.
# Left EMPTY rather than removed: a future nested array with a declared `resolves_when` action
# would use exactly this shape again, and an empty dict documents the mechanism still exists
# for one, rather than a caller having to reconstruct why it disappeared.
ASK_ACTION_FOR_ARRAY = {}


def _asks_path():
    return os.path.join(_paths.DATA, ASKS_FILE)


def _load_asks():
    try:
        with open(_asks_path(), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return None          # no asks store at all — legal (pre-0.25.0 profiles)


def _applications_action_evidence(opp_id):
    """The newest dated evidence of an "application" action on `opp_id`, read from the
    TOP-LEVEL `applications` store (ADR-031 B2) — the promoted successor to a function that
    once read a nested array that no longer exists."""
    dates = []
    for ap in load("applications"):
        if ap.get("opp_id") == opp_id and ap.get("date"):
            dates.append(str(ap["date"]))
    return max(dates) if dates else None


def _touches_action_evidence(opp_id):
    """The newest dated evidence of an "outreach" action on `opp_id`, read from the TOP-LEVEL
    `touches` store (ADR-031 B3) — the promoted successor to a function that once read
    `rec.get("outreach")`, a nested array that no longer exists. Same funnel
    check_action_claims.opp_action_evidence() trusts: any touch with status == "sent" and a
    date. A drafted touch is not evidence — the ask asked for the touch, not the intention."""
    dates = []
    for t in load("touches"):
        if t.get("opp_id") == opp_id and t.get("status") == "sent" and t.get("date"):
            dates.append(str(t["date"]))
    return max(dates) if dates else None


def linked_asks(rid, action, asks):
    """The OPEN asks this write could resolve: opp_id matches, resolves_when matches."""
    return [a for a in (asks or [])
            if not a.get("resolved_on") and a.get("opp_id") == rid
            and a.get("resolves_when") == action]


def resolve_linked_asks_dated(rid, when, action):
    """Resolve every declared-linkage ask this write's action answers, GIVEN its evidence date
    directly. Returns [(id, title)]. ADR-031 B2 (2026-09-11): extracted from the old
    `resolve_linked_asks(rid, rec, array_leaf)` — deriving `when`/`action` used to be this
    function's own job when both the outreach evidence AND the application evidence lived on
    one opportunity record; `applications` now lives in its own top-level store, so the two
    call sites (the opportunities-file write path, and the applications-file write path) each
    derive their own `when` and call this shared core, rather than this function knowing about
    either store's shape.

    Runs INSIDE the caller's lock hold, after the write that produced `when` validated clean.
    Evidence must be dated on/after the ask's `created` — an action that predates the ask is
    what the ask was written about, not the answer to it (same baseline as
    check_action_claims.py).

    ⚠️ Failure honesty: the write that produced `when` has already landed and validated. If the
    asks write then fails, we roll back ONLY asks.jsonl and say so loudly — the state degrades
    to exactly what it was before this change existed (action recorded, ask open), which the
    detection backstop catches. Never let an asks problem un-land a valid action record."""
    if not action or not when:
        return []
    asks = _load_asks()
    if asks is None:
        return []
    hit = []
    for a in linked_asks(rid, action, asks):
        created = str(a.get("created") or "")
        if created and when < created:
            continue
        a["resolved_on"] = when
        a["resolution"] = "done"
        stamp = "auto-resolved with the write that recorded its %s (record.py, dev #133)" % action
        a["note"] = ("%s · %s" % (a["note"], stamp)) if a.get("note") else stamp
        hit.append((a.get("id"), a.get("title") or ""))
    if not hit:
        return []

    before = None
    try:
        with open(_asks_path(), "rb") as fh:
            before = fh.read()
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=_paths.DATA, prefix=".record-asks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for a in asks:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, _asks_path())
    except Exception as e:
        if os.path.exists(tmp):
            os.unlink(tmp)
        print("  ⚠️ the action WROTE, but resolving its ask(s) failed: %s" % e)
        print("  The ask(s) remain OPEN — check_action_claims.py will flag the drift.")
        return []
    rc, out, err, _problems = validate()
    if rc != 0:
        # Only this file can be guilty: the store validated clean two steps ago.
        ok = False
        if before is not None:
            fd2, tmp2 = tempfile.mkstemp(dir=_paths.DATA, prefix=".rollback-asks-", suffix=".tmp")
            try:
                with os.fdopen(fd2, "wb") as fh:
                    fh.write(before)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp2, _asks_path())
                with open(_asks_path(), "rb") as fh:
                    ok = fh.read() == before
            except Exception:
                if os.path.exists(tmp2):
                    os.unlink(tmp2)
        print("  ⚠️ the action WROTE, but the ask resolution broke the validator and was %s."
              % ("rolled back" if ok else "NOT VERIFIABLY ROLLED BACK — restore asks.jsonl "
                 "from git"))
        print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
        return []
    return hit


def _resolve_plan_goal(opp_id, new_stage):
    """ADR-031 B4 (design §17) — [(plan_id, resolution)] for the ONE plan this write may have
    resolved: `new_stage` at screening or beyond, on a governing plan whose `resolves_when` is
    'goal-reached' and is not already resolved. The exact best-effort shape
    `resolve_linked_asks_dated` already uses — the primary write already landed and validated;
    a failure here is loud and never un-lands it."""
    if new_stage not in ("screening", "interviewing", "offer"):
        return []
    opps = load("opportunities")
    opp = find(opps, opp_id)
    if opp is None or not opp.get("plan_id"):
        return []
    plans = load("plans")
    plan = find(plans, opp["plan_id"])
    if plan is None or plan.get("resolved_on") or plan.get("resolves_when") != "goal-reached":
        return []
    today_iso = datetime.date.today().isoformat()
    plan["resolved_on"] = today_iso
    plan["resolution"] = "goal reached — %s advanced to stage %r on %s" % (opp_id, new_stage,
                                                                          today_iso)
    fd, tmp = tempfile.mkstemp(dir=_paths.DATA, prefix=".record-plans-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for p in plans:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, os.path.join(_paths.DATA, STORES["plans"]))
    except Exception as e:                                        # noqa: BLE001
        if os.path.exists(tmp):
            os.unlink(tmp)
        print("  ⚠️ the write landed, but resolving its plan failed: %s" % e)
        return []
    rc, _out, _err, _problems = validate()
    if rc != 0:
        print("  ⚠️ the write landed, but resolving the plan left the store invalid — check "
              "data/plans.jsonl.")
        return []
    return [(plan.get("id"), plan.get("resolution"))]
