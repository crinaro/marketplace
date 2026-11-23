"""Migration 0.92.0: `m_0_92_0_decision_surface()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, frozen once released (§5.5)."""

import os
from journaling.journal_file import read
from journaling.row_kinds import record_profile_schema
from journaling.tables import JournalError
from migrations.support_pins import DECISION_SURFACE_PIN, _decision_surface_pin_needed

VERSION = "0.92.0"


# KEYED "0.92.0" (docs/design-decision-surface.md §M, review round 1 F1) -- 0.91.0 is the newest jobsearch release at the branch
# base (`jobsearch--v0.91.0` is tagged). A profile stamped "0.91.0" (or any lower version) fires a migration keyed "0.92.0" through
# pending_for()'s strict `<`. The version appears literally in the migration's name, its registry key, its test files' names, the pin
# (`DECISION_SURFACE_PIN`) and the group file, so a re-key is one commit by release-manager before any tag. It runs LAST among the
# migrations, and its one write is the profile pin that makes a 0.91.x engine stop at its first journal reader or `record.py` verb.
DECISION_SURFACE_BY = "m_0_92_0_decision_surface"


def m_0_92_0_decision_surface(profile, apply_it, _inject_fault=None):
    """0.92.0 -- the profile pin, and nothing else (docs/design-decision-surface.md §M; review round 1 F1). No data is
    transformed, no store is rewritten, so there is nothing to preserve first: the one write is an APPEND to data/runs.jsonl.

    WHY A PIN. 0.92.0 writes two shapes a 0.91.x engine does not know: the follow-control touch types (`stop-following`, with
    `inbound_seen`) and the optional `held` counts on a `companies-raised` journal row. Both writers refuse (or withhold the new
    field) below the pin (`recording.evidence_keys.shape_pin_refusal`, which reads `journal.pin_scan`), and an older engine refuses
    every journal read and append and every `record.py` verb on a profile pinned above it (`journal_file.pin_refusal`). So an old
    engine never meets a new shape: below the pin the new engine writes none, at the pin the old one writes nothing.

    WHAT IT DOES: one `profile-schema` journal event, `min_engine: 0.92.0`, through `journal.record_profile_schema`, unless the
    journal already carries a pin at or above 0.92.0 (then `(True, "")`, nothing written, nothing said). A dry run reports the one
    "would pin" line and writes nothing.

    PREREQUISITE, READ-ONLY: `data/runs.jsonl` reads cleanly through `journal.read`. If it does not, the result is PENDING naming the
    cause and NOTHING is written (never a false "0 done").

    SUCCESS IS THE RE-READ: `journal.profile_pin(journal.read(profile)) >= 0.92.0` after the append. An append that raises, or one
    the journal does not show, is PENDING. `pending_for` re-selects this migration whenever the stamp is at or above 0.92.0 and the
    journal's pin is below it (a restored `runs.jsonl`), so a lost pin is re-appended by the next hook.

    `_inject_fault` is a TEST SEAM: "before-pin" raises before the append (a crash the next run must complete from).
    Returns `(done, message)`."""
    pending = "  ⏳ 0.92.0 PENDING -- %s. Nothing was written. This runs again next session."

    # ---- prerequisite (read-only) ------------------------------------------------------------------------
    try:
        recs = read(profile)
    except JournalError as e:
        return False, pending % ("data/runs.jsonl does not read cleanly (%s)" % e)
    except (OSError, UnicodeDecodeError) as e:
        return False, pending % ("data/runs.jsonl cannot be read (%s)" % e)

    # ---- plan --------------------------------------------------------------------------------------------
    if not _decision_surface_pin_needed(recs):
        return True, ""
    if not apply_it:
        return True, ("  would pin the profile to jobsearch %s (one `profile-schema` journal event; no data is changed)"
                      % DECISION_SURFACE_PIN)

    # ---- the pin, the one write --------------------------------------------------------------------------
    if _inject_fault == "before-pin":
        raise RuntimeError("injected fault: before-pin")
    ok, message = _write_pin(profile, pending)
    if not ok:
        return False, message
    return True, ("  ✅ decision surface (0.92.0) -- pinned the profile to jobsearch %s: an older jobsearch on this profile now "
                  "stops and asks to be updated, so it never meets a stop-following row or a held count" % DECISION_SURFACE_PIN)


def _write_pin(profile, pending):
    """Append the pin and re-read it. `(True, None)`, or `(False, the PENDING line)`; `pending` is the plain PENDING template.
    The body of `m_0_90_0_browser_fallback._write_pin` with the constants swapped (a released migration module is frozen, and no
    migration imports another)."""
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
        record_profile_schema(profile, DECISION_SURFACE_PIN, DECISION_SURFACE_BY)
    except (JournalError, OSError) as e:
        return False, pending % ("the profile pin could not be recorded: %s" % e)
    # the success condition is the RE-READ, and it is stated apart from the append: the append may have landed even when
    # the read-back does not show it (a journal this engine refuses to read), so "nothing was written" is not claimed here
    try:
        shows_pin = not _decision_surface_pin_needed(read(profile))
        why_not = "the pin is not in the journal after the append"
    except (JournalError, OSError, UnicodeDecodeError) as e:
        shows_pin, why_not = False, "the journal does not read back after the append: %s" % e
    if not shows_pin:
        return False, ("  ⏳ 0.92.0 PENDING -- the profile pin could not be recorded: %s. Nothing else was written; check "
                       "data/runs.jsonl before this runs again next session." % why_not)
    return True, None
