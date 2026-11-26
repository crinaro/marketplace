"""Migration 0.94.0: `m_0_94_0_role_first()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, frozen once released (§5.5). What it reads, selects and copies is
`support_role_first.py`."""

import os
import _root
from journaling.journal_file import read
from journaling.pins import ROLE_FIRST_MIGRATION, ROLE_FIRST_PIN, earliest_pin_at, earliest_pin_at_scan
from journaling.row_kinds import record_profile_schema
from journaling.tables import JournalError
from migrations import support_role_first as rf
from recording import profile_paths
from recording.withdraw_write import write_withdrawals

VERSION = "0.94.0"


# KEYED "0.94.0" (docs/design-role-first.md §11, §12 MG1; jobsearch group file docs/groups/jobsearch-0.94.0.md) -- 0.93.0 is the newest jobsearch release at the branch
# base (`jobsearch--v0.93.0` is tagged on origin). A profile stamped "0.93.0" (or lower) fires a migration keyed "0.94.0" through pending_for()'s strict `<`. The version
# appears literally in the migration's name, its registry key, the pin (`journaling.pins.ROLE_FIRST_PIN`), the `.pre-0.94.0` copies, its test files' names and the group
# file, so a re-key is one commit by release-manager before any tag. It runs LAST among the migrations. Its FIRST WRITE is the profile pin.


def m_0_94_0_role_first(profile, apply_it, _inject_fault=None, _cap=rf.SESSION_CAP):
    """0.94.0 -- the owner's criteria decide what a run reads (dev 1062), a read quotes the page (dev 1063), and a degraded search holds only what its card cannot answer
    (dev 1055). Held records need no transform: "held" is derived, so the PIN is what converts them (design 11). What this changes in stored data is two things, both
    corrections of what 0.93.0 wrote wrongly.

    WHAT IT DOES, IN THIS ORDER
      1. PREREQUISITE, read-only, PENDING naming the cause and writing NOTHING (never a false "0 done"): the journal reads cleanly; `data/opportunities.jsonl` is present and
         every line parses and every `jd_read` is one this engine reads; `data/companies.jsonl` and `data/pending_actions.jsonl` parse (absent is how their own readers say
         "empty"); and, when the next steps will write, the run lock is free and the session's profile root is this profile.
      2. THE PIN, FIRST: one `profile-schema` event, `min_engine: 0.94.0`, unless the journal already shows a pin at or above it (two machines: the EARLIEST pin is the
         release instant, `journaling.pins.earliest_pin_at`, so a second pin is never added). Success is a re-read of the file. An older engine now stops at its first
         journal reader, and this engine's rules (first look, bound, evidence) turn on.
      3. PRESERVE, only for a store the next steps will write: `data/opportunities.jsonl.pre-0.94.0` and `data/pending_actions.jsonl.pre-0.94.0`, byte-identical and
         sha1-checked. A copy already there is used only when it is proven to hold, byte for byte as it is now, every row about to change (each selected role, each queue
         item to release); otherwise it is left as it is and a NEW copy is written under the next free name (`.pre-0.94.0.1`, `.2`, ...), and the message names the copy
         that holds the originals. Nothing is ever overwritten.
      4. WITHDRAW every same-run contradiction of design 6.2 among undecided roles: a read via render that quotes no description and that a later failed render of the same
         page in the same run contradicts. ONE batch through `recording.withdraw_write.write_withdrawals`: one lock, one validation, one save; at most 50 a session, the rest
         PENDING with how many were done and how many are left. A role the owner decided is left alone and counted.
      5. RELEASE the pending capture items quarantined only by codes the card evidence now answers (`searching.card_evidence`): an append-only `_unquarantine` record each.
      6. SUCCESS IS THE RE-READ of the disk: the pin shows, no selectable contradiction is left, no releasable item is left. Otherwise PENDING with the counts.

    IDEMPOTENT: the pin exists and nothing is selected => `(True, "")`, nothing written. A read is withdrawn once (a withdrawn read no longer stands, so it is never selected
    again), and a released item is no longer quarantined. A pin present with the migration still pending (a kill after step 2, a cap, a refusal) is the stated state: the
    rules are on, some wrong reads still stand, and the next session resumes.

    UNDO: restore the copies the message names (`.pre-0.94.0`, or `.pre-0.94.0.<n>`); the pin stays, as every pin does. The hook has 30 seconds; the budget is 10 on 600 roles with 50 contradictions.

    `_inject_fault` is a TEST SEAM: "before-pin", "after-pin", "after-preserve" and "after-withdraw" raise at that point (a crash the next run must complete from). `_cap` is
    the session cap (a seam only so a test need not synthesize 51 roles for the window). Returns `(done, message)`."""
    pending = "  ⏳ 0.94.0 PENDING -- %s. Nothing was written. This runs again next session."

    # ---- 1. prerequisite (read-only) ------------------------------------------------------------------------------------------
    plan, why = _read_plan(profile)
    if why:
        return False, pending % why
    specs, releases, need_pin = plan["specs"], plan["releases"], plan["need_pin"]
    if not need_pin and not specs and not releases:
        return True, ""
    if not apply_it:
        return True, _would(plan, _cap)
    if specs or releases:
        why = _write_blocker(profile)
        if why:
            return False, pending % why
    if _inject_fault == "before-pin":
        raise RuntimeError("injected fault: before-pin")

    # ---- 2. the pin, FIRST -------------------------------------------------------------------------------------------------------
    if need_pin:
        failure = _write_pin(profile)
        if failure:
            return False, failure
    if _inject_fault == "after-pin":
        raise RuntimeError("injected fault: after-pin")
    pinned = ("pinned the profile to jobsearch %s" % ROLE_FIRST_PIN) if need_pin else "the profile was already pinned to jobsearch %s" % ROLE_FIRST_PIN
    if not specs and not releases:
        return True, "  ✅ 0.94.0 role-first -- %s; no read to withdraw and no held role to release%s." % (pinned, _decided_note(plan))
    return _transform(profile, plan, pinned, _inject_fault, _cap)


def _would(plan, cap):
    parts = []
    if plan["need_pin"]:
        parts.append("would pin the profile to jobsearch %s (one `profile-schema` journal event)" % ROLE_FIRST_PIN)
    if plan["specs"]:
        n = len(plan["specs"])
        parts.append("would withdraw %d read(s) that a failed render of the same page contradicts and that quote no description (%d this session, the rest next)"
                     % (n, min(n, cap)))
    if plan["releases"]:
        parts.append("would release %d capture item(s) the card evidence now answers" % len(plan["releases"]))
    return "  " + "; ".join(parts)


def _decided_note(plan):
    return ("; %d contradicted read(s) on roles you decided were left as they are" % plan["decided"]) if plan["decided"] else ""


def _read_plan(profile):
    """`(plan, None)` or `(None, the sentence naming what could not be read)`. Reads only."""
    runs = os.path.join(profile, "data", "runs.jsonl")
    try:
        recs = read(profile) if os.path.exists(runs) else []
    except JournalError as e:
        return None, "data/runs.jsonl does not read cleanly (%s)" % e
    except (OSError, UnicodeDecodeError) as e:
        return None, "data/runs.jsonl cannot be read (%s)" % e
    opps, err = rf.read_store(profile, "opportunities.jsonl")
    if err:
        return None, err
    if opps is None:
        return None, "data/opportunities.jsonl is missing (a profile this old always has it, so a missing file is not an empty store)"
    for name in ("companies.jsonl", "pending_actions.jsonl"):
        _rows, err = rf.read_store(profile, name)
        if err:
            return None, err
    queue = rf.read_store(profile, "pending_actions.jsonl")[0] or []
    try:
        specs, decided = rf.select_contradictions(opps)
    except rf.StoreError as e:
        return None, str(e)
    return {"need_pin": earliest_pin_at(recs) is None, "specs": specs, "decided": decided,
            "releases": rf.select_releases(queue, rf.evidence_for(profile))}, None


def _write_blocker(profile):
    """The sentence that stops the writes of steps 4 and 5, or None: the run lock is held, or the session's profile root is not this profile (the write API resolves the
    validator, the screen and the lock by the session's root, so it must not run against another profile's)."""
    if rf.lock_is_held(profile):
        return ("the run lock is held (%s): a run may be writing opportunities.jsonl; if no run is going, `runlock.py --steal` clears a stale lock"
                % os.path.basename(rf._readmit_lock_path(profile)))
    try:
        here = os.path.realpath(_root.profile_root())
    except Exception as e:          # noqa: BLE001 -- an unresolvable root is a reason not to write, never a crash
        return "the session's profile root cannot be resolved (%s)" % e
    if here != os.path.realpath(profile):
        return ("this session's profile root is %s, not the profile being migrated (%s): run the migration from inside that profile" % (here, profile))
    return None


def _write_pin(profile):
    """Append the pin and re-read the file. None, or the PENDING line. The body of `m_0_93_0_word_round_trip._write_pin` with this release's constants (a released migration
    is frozen and no migration imports another); the re-read is the TOLERANT scan, because a journal pinned above the running engine refuses `journal.read`, and this
    migration must be checkable in the tree that carries it before its release's plugin.json bump."""
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
        record_profile_schema(profile, ROLE_FIRST_PIN, ROLE_FIRST_MIGRATION)
    except (JournalError, OSError) as e:
        return "  ⏳ 0.94.0 PENDING -- the profile pin could not be recorded: %s. Nothing was written. This runs again next session." % e
    if earliest_pin_at_scan(profile) is None:
        return ("  ⏳ 0.94.0 PENDING -- the profile pin could not be recorded: the pin is not in the journal after the append. Nothing else was written; check "
                "data/runs.jsonl before this runs again next session.")
    return None


def _transform(profile, plan, pinned, fault, cap):
    """Steps 3 to 6 under the run lock. Returns `(done, message)`."""
    def after_pin(why):
        return False, ("  ⏳ 0.94.0 PENDING -- %s. The profile pin IS recorded (the 0.94.0 rules are on). This runs again next session." % why)

    try:
        lock_path, made_dir = rf.take_run_lock(profile)
    except rf.LockBusy:
        return after_pin("the run lock was taken while this was reading: a run may be writing")
    except OSError as e:
        return after_pin("the run lock could not be taken (%s)" % e)
    saved = (profile_paths.ROOT, profile_paths.DATA)
    try:
        # ---- 3. preserve what the next steps will write -----------------------------------------------------------------------------
        kept = []
        for ids, name, copy in (({sp[0] for sp in plan["specs"] if sp[0]}, "opportunities.jsonl", rf.PRE_OPPS),
                                (set(plan["releases"]), "pending_actions.jsonl", rf.PRE_QUEUE)):
            if not ids:
                continue
            made, bad = rf.preserve(profile, name, copy, ids)
            if bad:
                return after_pin(bad)
            kept.append(made)
        if fault == "after-preserve":
            raise RuntimeError("injected fault: after-preserve")

        # ---- 4. withdraw: one batch, one validation, one save ------------------------------------------------------------------------
        batch, refused, note = plan["specs"][:cap], 0, ""
        if batch:
            profile_paths.bind(profile)
            rc, results = write_withdrawals(batch, run=rf.RUN_ID, already_locked=True, wait=None, dry_run=False, now=None)
            bad = [r for r in results if not r["ok"]]
            refused = len(bad)
            if bad:
                note = "; refused: %s" % " | ".join(" ".join(r["text"].split())[:300] for r in bad[:2])
        if fault == "after-withdraw":
            raise RuntimeError("injected fault: after-withdraw")

        # ---- 5. release ---------------------------------------------------------------------------------------------------------------
        if plan["releases"]:
            rf.append_releases(profile, plan["releases"])
    finally:
        rf.release_run_lock(lock_path, made_dir)
        profile_paths.ROOT, profile_paths.DATA = saved

    # ---- 6. success is the re-read ----------------------------------------------------------------------------------------------------
    left_specs, left_releases, why = _re_read(profile)
    # what LANDED is what the disk says, never what the write reported: a batch the validator refused is rolled back whole, whatever its per-role results said
    landed = len([s for s in batch if (s[0], s[1]) not in {(o, a) for o, a, _w in left_specs}]) if why is None else 0
    summary = "withdrew %d read(s)%s, released %d held capture item(s)" % (landed, " (%d refused)" % refused if refused else "", len(plan["releases"]))
    if why:
        return after_pin("the disk could not be read back after the writes (%s); %s" % (why, summary))
    if left_specs or left_releases:
        return after_pin("%s; still to do: %d read(s) to withdraw (%d a session), %d item(s) to release%s"
                         % (summary + _kept_note(kept), len(left_specs), cap, left_releases, note))
    return True, "  ✅ 0.94.0 role-first -- %s; %s%s%s." % (pinned, summary, _decided_note(plan), _kept_note(kept))


def _kept_note(kept):
    """` (the originals are kept: data/<copy>, ...)`, naming the copy that holds each store's originals (a `.<n>` copy when an older one did not hold them)."""
    return " (the originals are kept: %s)" % ", ".join("data/" + c for c in kept) if kept else ""


def _re_read(profile):
    """`(specs still to withdraw, items still to release, why)` from what the disk says now; `why` is a sentence when it cannot be read, or the pin is not there."""
    if earliest_pin_at_scan(profile) is None:
        return [], 0, "the pin is not in the journal"
    opps, err = rf.read_store(profile, "opportunities.jsonl")
    queue, qerr = rf.read_store(profile, "pending_actions.jsonl")
    if err or qerr or opps is None:
        return [], 0, err or qerr or "data/opportunities.jsonl is missing"
    try:
        specs, _decided = rf.select_contradictions(opps)
    except rf.StoreError as e:
        return [], 0, str(e)
    return specs, len(rf.select_releases(queue or [], rf.evidence_for(profile))), None
