"""Migration 0.69.0: `m_0_69_0_passed_backlog_terminal()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil
from migrations.support_uid import _uid_text_read

VERSION = "0.69.0"


# ⭐⭐ KEYED "0.69.0" -- 0.68.0 is the newest jobsearch release at the branch base (plugin.json read
# 0.68.0 on base 45c59c5; the 0.68.0 cut landed as PR #730). A profile that installed 0.68.0 is
# stamped exactly "0.68.0", and pending_for()'s strict `<` fires a migration keyed to "0.69.0".
# Re-verify when 0.69.0 is actually cut (dev #722 / public #156). It runs LAST: it reads and writes
# only data/opportunities.jsonl, which no earlier migration depends on it for.
PASSED_BACKLOG_PRE_COPY = "opportunities.jsonl.pre-0.69.0"


def _passed_backlog_rows(rows):
    """Indexes of the rows `decide pass` would have made terminal: a recorded `verdict: pass` on a
    role still `status: backlog`. The verdict is the owner's recorded decision, so the transform is
    not a guess at history; `status` is what the rest of the engine reads as ended."""
    return [i for i, r in enumerate(rows)
            if r.get("verdict") == "pass" and r.get("status") == "backlog"]


def m_0_69_0_passed_backlog_terminal(profile, apply_it):
    """0.69.0 -- a decided pass on a backlog role is TERMINAL (dev #722 / public #156,
    design-sourcing-scope.md §5).

    Until 0.69.0 `record.py decide <id> pass` set `verdict: pass` and left `status: backlog`: the
    role was excluded from new sightings but the rest of the engine still saw a live backlog row.
    `decide pass` now writes `status: passed`, `stage: closed` and `passed_from: {status, stage}` in
    the same write. This repairs the rows already written: every opportunity with `verdict: pass`
    and `status: backlog` gets exactly those three writes, `passed_from` holding the status and
    stage it was found in, so a later `decide pursue|park` restores it the way it restores a role
    passed after 0.69.0.

    Why a migration and not a reader change: schema.md already says a decided pass is `status:
    passed`. These rows are wrong data, not a different reading, and the `verdict: pass` is a
    recorded decision. (ADR-013 drew the line the other way for parked EXPIRY workarounds, which
    recorded no decision.)

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. Before the first write `data/opportunities.jsonl` is
    copied byte-for-byte to `data/opportunities.jsonl.pre-0.69.0` (never over a copy already there:
    that is the true original from an earlier partial run); a failed copy writes nothing. The store
    is read STRICTLY first (one line that does not parse is PENDING naming the line: rewriting a
    store this could not fully read would drop it). After the write the success condition is
    RE-READ from disk -- no `verdict: pass` role is left at `status: backlog`, and every changed
    row is `passed` at `closed` with its `passed_from` -- and a shortfall is PENDING with the
    preserved copy kept. IDEMPOTENT: a second run finds none and writes nothing. HONEST ZERO: an
    absent store, or one with no such row, is DONE with no output (there is no prerequisite to wait
    on, and nothing is claimed that was not counted). A row with no readable stage records the stage
    backlog rows are created at, `sourced`, in `passed_from`.

    ⚠️ ROLLBACK RISK. Downgrading to 0.68.0 after this runs leaves the rows `passed`; restoring
    `opportunities.jsonl.pre-0.69.0` undoes the migration only for rows not written since."""
    import _atomic
    import validate_data as _vd
    path = os.path.join(profile, "data", "opportunities.jsonl")
    rows, _raws, err = _uid_text_read(profile, "opportunities")
    if err:
        return False, ("  ⏳ 0.69.0 PENDING -- %s. Nothing was written: rewriting a store this "
                       "could not fully read would drop that line. Fix it and this runs again "
                       "next session." % err)
    todo = _passed_backlog_rows(rows)
    if not todo:
        return True, ""
    ids = [rows[i].get("id") for i in todo]
    if not apply_it:
        return True, ("  would make %d decided-pass backlog role(s) terminal (status passed, stage "
                      "closed, passed_from kept): %s" % (len(todo), ", ".join(map(str, ids))))
    copy_path = os.path.join(profile, "data", PASSED_BACKLOG_PRE_COPY)
    if not os.path.exists(copy_path):
        try:
            shutil.copy2(path, copy_path)
        except (OSError, shutil.Error) as e:
            return False, ("  ⚠️ opportunities.jsonl could not be preserved to %s (%s), so NOTHING "
                           "was changed." % (PASSED_BACKLOG_PRE_COPY, e))
    for i in todo:
        r = rows[i]
        stage = r.get("stage") if r.get("stage") in _vd.STAGES else "sourced"
        r["passed_from"] = {"status": "backlog", "stage": stage}
        r["status"], r["stage"] = "passed", "closed"
    _atomic.write_jsonl(path, rows)
    after, _r, err = _uid_text_read(profile, "opportunities")
    by_id = {r.get("id"): r for r in (after or [])}
    short = [i for i in ids
             if err or _passed_backlog_rows([by_id.get(i, {})])
             or by_id.get(i, {}).get("status") != "passed"
             or by_id.get(i, {}).get("stage") != "closed"
             or not isinstance(by_id.get(i, {}).get("passed_from"), dict)]
    if err or short or _passed_backlog_rows(after or []):
        return False, ("  ⏳ 0.69.0 PENDING -- the success condition did not hold after the write "
                       "(%s); the original is kept at data/%s. Offered again next session."
                       % (err or "still at backlog or unmarked: %s" % ", ".join(map(str, short)),
                          PASSED_BACKLOG_PRE_COPY))
    return True, ("  ✅ opportunities (0.69.0) -- made %d decided-pass backlog role(s) terminal "
                  "(status passed, stage closed, passed_from kept): %s (the original is kept at "
                  "data/%s)" % (len(todo), ", ".join(map(str, ids)), PASSED_BACKLOG_PRE_COPY))
