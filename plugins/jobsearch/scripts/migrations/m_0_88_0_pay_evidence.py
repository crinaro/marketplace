"""Migration 0.88.0: `m_0_88_0_pay_evidence()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
import tempfile
from migrations.stamp import ver
from migrations.support_files import _readmit_lock_path, _sha1_file
from migrations.support_validate import _shadow_validate

VERSION = "0.88.0"


# ⭐⭐ KEYED "0.88.0" (dev #846 / dev #915 / dev #836; design-jobsearch-0.88.0.md sections 4 and 4.4) -- 0.87.0 is the newest
# jobsearch release at the branch base (`jobsearch--v0.87.0` is tagged). A profile that installed 0.87.0 is stamped exactly
# "0.87.0", and pending_for()'s strict `<` fires a migration keyed to "0.88.0". The version appears literally in the migration
# name, its test file, the pin's `min_engine` and the `.pre-0.88.0` copy, so a re-key is one commit, by release-manager, before any
# tag. It runs LAST; its FIRST WRITE is the pin; it touches only data/opportunities.jsonl (and the journal's one pin event).
PAY_EVIDENCE_BY = "m_0_88_0_pay_evidence"
PAY_EVIDENCE_PIN = "0.88.0"
PAY_EVIDENCE_PRE_COPY = "opportunities.jsonl.pre-0.88.0"


def _pay_evidence_pin_needed(profile, recs=None):
    """True when the profile's journal carries no pin at or above 0.88.0. `recs` is the journal as `journal.read` returned it,
    or None to scan (tolerantly, `journal.pin_scan`)."""
    import journal as _journal
    pin = _journal.profile_pin(recs) if recs is not None else _journal.pin_scan(profile)
    return pin is None or ver(pin) < ver(PAY_EVIDENCE_PIN)


def _pay_evidence_selected(row):
    """The 0.88.0 selection (design 4.1): a row whose `listed_pay` is a `none-shown` read from `listing-text` that carries no
    `none_basis`. Such a record says "the listing showed no pay" and nothing checked that against the description (dev #846).
    The CANDIDATE's own none (`source: candidate`) is untouched, and so is any none this release earned (it carries `none_basis`),
    which is what makes the selection idempotent."""
    lp = row.get("listed_pay") if isinstance(row, dict) else None
    return (isinstance(lp, dict) and lp.get("state") == "none-shown" and lp.get("source") == "listing-text"
            and "none_basis" not in lp)


def _pay_evidence_lines(profile):
    """`(path, raw bytes, lines, rows, error)`: the bytes of data/opportunities.jsonl, its lines split on b"\\n" (so every line
    can be re-emitted byte for byte), each line's parsed row (None for a blank one), and a string when the file is absent or a
    line does not parse (named by number). An absent file is NOT an empty one: the store is a 0.4.0 store."""
    path = os.path.join(profile, "data", "opportunities.jsonl")
    if not os.path.exists(path):
        return path, b"", [], [], "data/opportunities.jsonl is missing (a profile this old always has it, so a missing file is not an empty store)"
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return path, b"", [], [], "data/opportunities.jsonl cannot be read (%s)" % e
    lines = raw.split(b"\n")
    rows = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            rows.append(None)
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            return path, raw, lines, [], "data/opportunities.jsonl line %d does not parse: %s" % (n, e)
        if not isinstance(row, dict):
            return path, raw, lines, [], "data/opportunities.jsonl line %d is not an object" % n
        rows.append(row)
    return path, raw, lines, rows, None


def _pay_evidence_write(path, data):
    """Replace `path` with `data` atomically: a temp file in the same directory, fsync, then os.replace."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".migrate-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def m_0_88_0_pay_evidence(profile, apply_it, _inject_fault=None):
    """0.88.0 -- "none shown" needs positive evidence (dev #846; design-jobsearch-0.88.0.md sections 3 and 4; owner decision D2).
    The ONE migration of this release: every stored-record change in it is here.

    WHY. Before 0.88.0 a reader that did not find pay on a page had only the word `none` to say so, and the screen kept such a role
    (UNDISCLOSED). A `none-shown` read from `listing-text` therefore never meant "the whole description was read and states no
    pay". 0.88.0 records that claim only with `none_basis` (the route that checked it); the legacy ones are the records it cannot vouch for.

    WHAT IT DOES, IN THIS ORDER
      1. PREREQUISITES, read-only, each PENDING (never a false "0 done") naming its cause and writing NOTHING: the run lock is free;
         `data/opportunities.jsonl` exists and every line parses (a bad line is named); `validate_data.check_listed_pay` accepts every
         row it would select.
      2. THE PIN, as the FIRST write: one `profile-schema` event, `min_engine: 0.88.0` (`journal.record_profile_schema`), unless the
         journal already carries a pin at or above 0.88.0. The release adds shapes (`none_basis`, `listed_pay_prior`, `kind`,
         `later_on`, the start event's `machine` and `dirty_at_start`) that an engine older than 0.88.0 would misread, and the latest
         earlier pin is 0.86.0, so without this one a 0.86.x or 0.87.0 machine would run on. Its success condition is a RE-READ:
         `journal.profile_pin(journal.read(profile)) >= 0.88.0`; if that fails the result is PENDING and nothing else was written.
         The pin is written even when no row is selected.
      3. SELECT (`_pay_evidence_selected`): `listed_pay.state == none-shown`, `source == listing-text`, no `none_basis`. Zero selected
         is a true zero: the file was read in full.
      4. PRESERVE: byte-copy `data/opportunities.jsonl` to `data/opportunities.jsonl.pre-0.88.0`, never over a copy already there
         (that is the true original of an earlier partial run), and check the copy's sha1. A failed copy writes nothing more.
      5. TRANSFORM each selected row with `record.supersede_listed_pay` (the one shared function): its `listed_pay` is appended to the
         append-only `listed_pay_prior` with `superseded_on` and `superseded_by`, then `listed_pay` is deleted, so the field is ABSENT
         (NOT captured: `review:comp`, "re-read the listing before surfacing"). Every other line is re-emitted byte for byte. The new
         file is checked on a SHADOW copy with the real validator, then written through a temp file and `os.replace`.
      6. QUERY the success condition, by re-reading the disk: no row is still selected; each `listed_pay_prior[-1]` equals the value it
         superseded; the line count is unchanged; every unselected line is byte-identical. On a shortfall the file is restored to the
         bytes THIS run read and the result is PENDING, naming the failed clause.

    NOTHING IS DELETED: the old value is kept in `listed_pay_prior` (the expand step; the contract step is not in this release), and the
    original file is at `data/opportunities.jsonl.pre-0.88.0`. IDEMPOTENT: the pin exists and no row is selected => done, nothing
    written, nothing said. It does NOT re-check saved bodies (the body is not kept past 7 days).

    ⚠️ ROLLBACK, STATED. An engine older than 0.88.0 that has `journal.pin_refusal` (0.86.0 and 0.87.0) now stops before it writes or
    validates ("this profile was upgraded by jobsearch 0.88.0. Update the plugin on this machine before running it here. Nothing was
    written."), and so never reaches the validator that would refuse `none_basis`. An engine older than 0.86.0 stops at its first
    journal reader (the 0.86.0 pin's own mechanism). Upgrade every machine that shares the profile.

    `_inject_fault` is a TEST SEAM: "before-pin", "after-pin" and "after-preserve" raise at that point (a crash the next run must
    complete from), and "shortfall" makes the re-read fail. Returns `(done, message)`."""
    import datetime as _dtm
    import journal as _journal
    import validate_data as _vd
    pending = "  ⏳ 0.88.0 PENDING -- %s. Nothing was written. This runs again next session."
    lock_path = _readmit_lock_path(profile)

    # ---- prerequisites (read-only) -------------------------------------------------------------------------------
    if os.path.exists(lock_path):
        return False, pending % ("the run lock is held (%s): a run may be writing opportunities.jsonl; if no run is going, "
                                 "`runlock.py --steal` clears a stale lock" % os.path.basename(lock_path))
    path, raw, lines, rows, err = _pay_evidence_lines(profile)
    if err:
        return False, pending % err
    selected = [i for i, r in enumerate(rows) if r is not None and _pay_evidence_selected(r)]
    problems = []
    for i in selected:
        _vd.check_listed_pay(rows[i]["listed_pay"], "data/opportunities.jsonl line %d (%s)" % (i + 1, rows[i].get("id")), problems)
    if problems:
        return False, pending % ("the validator's listed-pay check refuses a row this would move (%s), and moving a record it "
                                 "cannot read would be a guess" % "; ".join(problems[:3]))
    try:
        recs = _journal.read(profile) if os.path.exists(os.path.join(profile, "data", "runs.jsonl")) else []
        need_pin = _pay_evidence_pin_needed(profile, recs)
    except _journal.JournalError:
        need_pin = _pay_evidence_pin_needed(profile)        # tolerant scan: a journal this engine cannot read fails the pin step below
    except (OSError, UnicodeDecodeError) as e:
        return False, pending % ("data/runs.jsonl cannot be read (%s)" % e)
    if not need_pin and not selected:
        return True, ""
    if not apply_it:
        parts = []
        if need_pin:
            parts.append("would pin the profile to jobsearch %s (one `profile-schema` journal event)" % PAY_EVIDENCE_PIN)
        if selected:
            parts.append("would flag %d role(s) whose \"none shown\" pay was never checked against the full description for a "
                         "re-read; the old value is kept in listed_pay_prior" % len(selected))
        return True, "  " + "; ".join(parts)

    # ---- the pin, as the first write -------------------------------------------------------------------------------
    if _inject_fault == "before-pin":
        raise RuntimeError("injected fault: before-pin")
    if need_pin:
        runs_path = os.path.join(profile, "data", "runs.jsonl")
        try:
            try:
                size = os.path.getsize(runs_path)
            except OSError:
                size = 0                        # no journal yet: `journal.append` creates it
            if size:
                with open(runs_path, "rb") as fh:
                    fh.seek(size - 1)
                    last = fh.read(1)
                if last != b"\n":
                    with open(runs_path, "ab") as fh:
                        fh.write(b"\n")          # `journal.append` writes a whole line: never glue one onto an unterminated one
            _journal.record_profile_schema(profile, PAY_EVIDENCE_PIN, PAY_EVIDENCE_BY)
            # The success condition is a RE-READ of the disk. It is the tolerant scan (`journal.pin_scan`), not `journal.read`: a
            # profile pinned above the RUNNING engine refuses `read` (`pin_refusal`), and this migration must be checkable in the
            # tree that carries it before its release's own plugin.json bump (the engine then still reads 0.87.0).
            if _pay_evidence_pin_needed(profile):
                raise _journal.JournalError("the pin is not in the journal after the append")
        except (_journal.JournalError, OSError) as e:
            return False, ("  ⏳ 0.88.0 PENDING -- the profile pin could not be recorded or confirmed: %s. opportunities.jsonl was "
                           "not changed. This runs again next session." % e)
    if _inject_fault == "after-pin":
        raise RuntimeError("injected fault: after-pin")
    pinned = "pinned the profile to jobsearch %s" % PAY_EVIDENCE_PIN
    if not selected:
        return True, "  ✅ 0.88.0 -- %s; no role's \"none shown\" pay needed a re-read." % pinned

    def after_pin(why):
        return ("  ⏳ 0.88.0 PENDING -- %s. The profile pin IS recorded; opportunities.jsonl was not changed. This runs again next "
                "session." % why)

    # ---- take the run lock for the write (non-blocking: a held lock was refused above) ------------------------------------
    made_dir = False
    try:
        lock_dir = os.path.dirname(lock_path)
        if not os.path.isdir(lock_dir):
            os.makedirs(lock_dir)
            made_dir = True
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"who": "migrate 0.88.0", "pid": os.getpid(),
                       "taken_at": _dtm.datetime.now().isoformat(timespec="seconds")}, fh)
    except FileExistsError:
        return False, after_pin("the run lock was taken while this was reading: a run may be writing")
    except OSError as e:
        return False, after_pin("the run lock could not be taken (%s)" % e)
    try:
        # ---- preserve ------------------------------------------------------------------------------------------------
        copy_path = os.path.join(profile, "data", PAY_EVIDENCE_PRE_COPY)
        if not os.path.exists(copy_path):
            try:
                shutil.copy2(path, copy_path)
                if _sha1_file(copy_path) != _sha1_file(path):
                    raise OSError("the copy does not match the original")
            except (OSError, shutil.Error) as e:
                try:
                    os.remove(copy_path)        # a copy that failed its check must not pass for the true original later
                except OSError:
                    pass
                return False, after_pin("opportunities.jsonl could not be preserved to %s (%s)" % (PAY_EVIDENCE_PRE_COPY, e))
        if _inject_fault == "after-preserve":
            raise RuntimeError("injected fault: after-preserve")

        # ---- transform: the selected rows, every other line byte for byte ---------------------------------------------------
        import record as _record
        on_iso = _dtm.date.today().isoformat()
        originals = {i: json.loads(json.dumps(rows[i]["listed_pay"])) for i in selected}
        new_lines = list(lines)
        new_rows = [dict(r) if r is not None else None for r in rows]
        for i in selected:
            moved = _record.supersede_listed_pay(new_rows[i], on_iso, PAY_EVIDENCE_BY)
            if not moved:
                return False, after_pin("line %d held no listed_pay to move" % (i + 1))
            new_lines[i] = json.dumps(new_rows[i], ensure_ascii=False).encode("utf-8")
        rc, probs, new = _shadow_validate(profile, {"opportunities.jsonl": [r for r in new_rows if r is not None]})
        if new is None or new:
            detail = "; ".join((new if new else (probs or []))[:8]) or ("validator exited %d with no problem list -- it crashed" % rc)
            return False, after_pin("the opportunities write was REFUSED (a new validation problem): %s" % detail)
        _pay_evidence_write(path, b"\n".join(new_lines))

        # ---- query: the success condition is what the disk says now -----------------------------------------------------------
        short = []
        _p, raw_after, lines_after, rows_after, err_after = _pay_evidence_lines(profile)
        if err_after:
            short.append("the file (unreadable after the write: %s)" % err_after)
        else:
            if len(lines_after) != len(lines):
                short.append("the line count (%d before, %d after)" % (len(lines), len(lines_after)))
            else:
                if any(r is not None and _pay_evidence_selected(r) for r in rows_after):
                    short.append("a role still selected")
                for i in range(len(lines)):
                    if i in originals:
                        row = rows_after[i] or {}
                        prior = row.get("listed_pay_prior")
                        last = ({k: v for k, v in prior[-1].items() if k not in ("superseded_on", "superseded_by")}
                                if isinstance(prior, list) and prior and isinstance(prior[-1], dict) else None)
                        if last != originals[i] or "listed_pay" in row:
                            short.append("the preserved value of line %d" % (i + 1))
                    elif lines_after[i] != lines[i]:
                        short.append("the unselected line %d (not byte-identical)" % (i + 1))
        if _inject_fault == "shortfall":
            short = short or ["(injected)"]
        if short:
            _pay_evidence_write(path, raw)        # put back exactly what this run read
            return False, ("  ⏳ 0.88.0 PENDING -- %s still wrong after the write; opportunities.jsonl was restored to the bytes this "
                           "run read (the original is also at data/%s). The profile pin IS recorded. This runs again next session."
                           % (", ".join(short[:4]), PAY_EVIDENCE_PRE_COPY))
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
    return True, ("  ✅ 0.88.0 -- %s; %d role(s) whose \"none shown\" pay was never checked against the full description are now NOT "
                  "captured and flagged for a re-read (review:comp; re-read before surfacing); the old values are kept in "
                  "listed_pay_prior (original file at data/%s)." % (pinned, len(selected), PAY_EVIDENCE_PRE_COPY))
