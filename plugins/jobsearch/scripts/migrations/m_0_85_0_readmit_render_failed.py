"""Migration 0.85.0: `m_0_85_0_readmit_render_failed()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_files import _readmit_lock_path, _sha1_file

VERSION = "0.85.0"


# ⭐⭐ KEYED "0.85.0" (dev #840 / public #181; design-hidden-pane-reads.md section 9) -- 0.84.0 is the newest jobsearch
# release at the branch base (`jobsearch--v0.84.0` is tagged; plugin.json read 0.84.0 on 2edc5d67). A profile that
# installed 0.84.0 is stamped exactly "0.84.0", and pending_for()'s strict `<` fires a migration keyed to "0.85.0".
# Re-verify at the moment 0.85.0 is cut. It runs LAST; it touches only data/runs.jsonl (ONE appended `readmit` event) and
# NEVER config.json: `search.posting_fetch` is the owner's opt-in (ruling D2) and no migration sets it.
READMIT_RENDER_FAILED_BY = "m_0_85_0_readmit_render_failed"
READMIT_RENDER_FAILED_PRE_COPY = "runs.jsonl.pre-0.85.0"
READMIT_RENDER_FAILED_OPT_IN = (
    "jobsearch 0.85.0: LinkedIn roles the Browser pane cannot read can be read from LinkedIn's public posting page "
    "instead. This is off by default (search.posting_fetch), and it is automated access that LinkedIn User Agreement "
    "section 8.2 restricts. To opt in: posting_fetch.py --set on.")


def _readmit_now():
    """The instant the `readmit` event takes effect (a seam: the test pins it, so its synthetic runs sit on either side)."""
    import datetime as _dtm
    return _dtm.datetime.now().replace(microsecond=0)


def m_0_85_0_readmit_render_failed(profile, apply_it, _inject_fault=None):
    """0.85.0 -- re-admit, once, the roles the retry-stop abandoned for `render-failed` (dev #840 / public #181;
    design-hidden-pane-reads.md section 9, owner ruling D2).

    WHY. Under 0.83.0 and 0.84.0 accounting a browser read that could not happen because the Browser pane was hidden was
    recorded `render-failed`, a ROLE-class cause, and two in a row stopped the unattended retry for good: an aggregator-only
    role was abandoned for a pane the engine cannot show. 0.85.0 records that case as `not-attempted` / `pane-hidden`
    (environment class, never counted toward a stop), so a role stopped by the old accounting would stay abandoned.

    WHAT IT DOES. Selects every role whose stage is `retry-stopped` and whose stopping chain is ONLY `render-failed`
    (`lifecycle.render_failed_stops`: the lifecycle's own selection, not a second reading of the journal) and appends ONE
    `readmit` event naming their ids (`journal.record_readmit`, the only writer). `lifecycle.Ctx.working` then drops the
    admissions planned at or before it, so each role waits as `waiting` / `readmitted` and is admitted in the class `held`
    (behind new roles' reserved share). A role whose chain also holds another cause (a challenge page) is left alone. A role
    that really has a bad page stops again after 2 more runs: at most 2K admissions for K roles, drawn from the held share.
    The result message says K.

    THE D2 LINE. On its FIRST application, whether or not anything was selected, the result message carries the one line
    that names `search.posting_fetch` and LinkedIn User Agreement section 8.2 (ruling OR3). It stores nothing to remember
    that it was said: the idempotent re-run returns done with no message. It NEVER writes `search.posting_fetch`.

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. The prerequisite is read first and is PENDING when it is not met, never a false
    "0 done": the run lock is held, or `runs.jsonl` / `opportunities.jsonl` / the other stores cannot be read (a 0.84.0-shaped
    journal CAN be: the 0.85.0 reader accepts it). Before the append `data/runs.jsonl` is copied byte for byte to
    `data/runs.jsonl.pre-0.85.0` (never over a copy already there: that is the true original of an earlier partial run) and the
    copy's sha1 is checked; a failed copy writes nothing. After the append the journal is RE-READ: the event must be on disk and
    no selected role may still be retry-stopped, else the append is taken back exactly and the result is PENDING.
    IDEMPOTENT: a `readmit` event by this migration already in the journal is the proof, and a second run changes nothing.
    TWO MACHINES: each may append its own event before they sync; the lifecycle reads events with the same `by` as one (the
    union of their ids, at the earliest `at`), so a role is never re-admitted twice.

    ⚠️ ROLLBACK RISK, STATED. An engine older than 0.85.0 raises on a journal holding a `readmit` event (`journal.read`
    refuses an unknown event), so after this runs on a profile with render-failed stops an older version cannot read its
    journal. It appends nothing when it selects nothing. Restoring `runs.jsonl.pre-0.85.0` undoes it only for a journal not
    written since. Upgrade every machine that shares the profile.

    `_inject_fault="shortfall"` is a TEST SEAM that makes the re-read check fail. Returns `(done, message)`."""
    import datetime as _dtm
    import journal as _journal
    import lifecycle as _lc
    runs_path = os.path.join(profile, "data", "runs.jsonl")
    lock_path = _readmit_lock_path(profile)
    pending = "  ⏳ 0.85.0 PENDING -- %s. Nothing was written. This runs again next session."

    # ---- prerequisite: no run is appending, and the stores read -------------------------------------
    if os.path.exists(lock_path):
        return False, pending % ("the run lock is held (%s): a run may be appending closes to the journal; if no run is "
                                 "going, `runlock.py --steal` clears a stale lock" % os.path.basename(lock_path))
    try:
        data = _lc.load_data(profile)
    except Exception as e:                      # noqa: BLE001 -- ANY unreadable store is PENDING, never a false "0 done"
        return False, pending % ("a store cannot be read (%s: %s), and re-admitting from a journal this could not fully read "
                                 "would be a guess" % (type(e).__name__, e))
    if any(r.get("event") == "readmit" and r.get("by") == READMIT_RENDER_FAILED_BY for r in data["journal"]):
        return True, ""                         # the event is the proof it ran: a true zero, with nothing to say
    now = _readmit_now()
    try:
        stops = _lc.render_failed_stops(_lc.Ctx(data, now))
    except Exception as e:                      # noqa: BLE001 -- a stage that cannot be derived is a prerequisite failure
        return False, pending % ("the role stages cannot be derived (%s: %s)" % (type(e).__name__, e))
    ids = list(dict.fromkeys(i for _key, ids_ in stops for i in ids_))
    if not stops:
        return True, ("  ✅ 0.85.0 -- no role is retry-stopped for render-failed, so none was re-admitted.\n  "
                      + READMIT_RENDER_FAILED_OPT_IN)
    if not apply_it:
        return True, ("  would re-admit %d role(s) the retry-stop gave up on for render-failed (one `readmit` event; the "
                      "journal is kept at data/%s first)" % (len(stops), READMIT_RENDER_FAILED_PRE_COPY))

    # ---- take the run lock for the write (non-blocking: a held lock was refused above) ---------------
    made_dir = False
    try:
        lock_dir = os.path.dirname(lock_path)
        if not os.path.isdir(lock_dir):
            os.makedirs(lock_dir)
            made_dir = True
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"who": "migrate 0.85.0", "pid": os.getpid(),
                       "taken_at": _dtm.datetime.now().isoformat(timespec="seconds")}, fh)
    except FileExistsError:
        return False, pending % "the run lock was taken while this was reading: a run may be appending closes"
    except OSError as e:
        return False, pending % ("the run lock could not be taken (%s)" % e)
    try:
        # ---- preserve --------------------------------------------------------------------------------
        copy_path = os.path.join(profile, "data", READMIT_RENDER_FAILED_PRE_COPY)
        if not os.path.exists(copy_path):
            try:
                shutil.copy2(runs_path, copy_path)
                if _sha1_file(copy_path) != _sha1_file(runs_path):
                    raise OSError("the copy does not match the original")
            except (OSError, shutil.Error) as e:
                try:
                    os.remove(copy_path)        # a copy that failed its check must not pass for the true original later
                except OSError:
                    pass
                return False, pending % ("runs.jsonl could not be preserved to %s (%s), so NOTHING was written"
                                         % (READMIT_RENDER_FAILED_PRE_COPY, e))

        # ---- transform: append ONE event, never rewrite -----------------------------------------------
        with open(runs_path, "rb") as fh:
            snapshot = fh.read()                # the bytes THIS run read; what a shortfall puts back
        try:
            if snapshot and not snapshot.endswith(b"\n"):
                with open(runs_path, "ab") as fh:
                    fh.write(b"\n")             # `journal.append` writes a whole line: never glue it onto an unterminated one
            _journal.record_readmit(profile, ids, READMIT_RENDER_FAILED_BY, "render-failed", at=now.isoformat())
        except (_journal.JournalError, OSError) as e:
            _readmit_take_back(runs_path, snapshot)
            return False, pending % ("the readmit event was refused (%s)" % e)

        # ---- query: the success condition is what the disk says now -----------------------------------
        short = []
        try:
            after = _lc.load_data(profile)
            mine = [r for r in after["journal"] if r.get("event") == "readmit" and r.get("by") == READMIT_RENDER_FAILED_BY]
            if not mine or not set(ids) <= set(i for r in mine for i in r.get("ids", ())):
                short.append("the readmit event")
            else:
                still = {k for k, _i in _lc.render_failed_stops(_lc.Ctx(after, now))}
                short += sorted(still & {k for k, _i in stops})
        except Exception as e:                  # noqa: BLE001
            short.append("the journal (unreadable after the write: %s)" % e)
        if _inject_fault == "shortfall":
            short = short or ["(injected)"]
        if short:
            _readmit_take_back(runs_path, snapshot)
            return False, pending % ("%s still not re-admitted after the write; the append was taken back exactly (the "
                                     "original is also at data/%s)" % (", ".join(short), READMIT_RENDER_FAILED_PRE_COPY))
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass
        if made_dir:
            try:
                os.rmdir(os.path.dirname(lock_path))    # only the empty directory this created: never a real `.git`
            except OSError:
                pass

    head = ("  ✅ re-admitted roles (0.85.0) -- %d role(s) the retry-stop gave up on for render-failed are back in intake, "
            "waiting in the class `held` behind new roles' reserved share (the original journal is kept at data/%s). A page "
            "that really fails stops again after 2 more runs." % (len(stops), READMIT_RENDER_FAILED_PRE_COPY))
    return True, head + "\n  " + READMIT_RENDER_FAILED_OPT_IN


def _readmit_take_back(runs_path, snapshot):
    """Put `data/runs.jsonl` back to exactly the bytes the migration read, when what is on disk still starts with them (so a
    line a run appended since is never cut off). Best effort: a failure here leaves the journal as it is."""
    try:
        with open(runs_path, "r+b") as fh:
            if fh.read(len(snapshot)) == snapshot:
                fh.truncate(len(snapshot))
    except OSError:
        pass
