"""The shadow validation two or more migrations run before they write (`_shadow_validate`).

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import json
import os
import shutil
import tempfile


def _shadow_validate(profile, overrides):
    """Run `validate_data.py` against a SHADOW copy of `profile` — every non-`data` sibling
    symlinked in (so authored-file checks like resume_variants' still resolve correctly, the
    exact `dirname(DATA)` shape record.py's own `dry_run_validate` established for the same
    reason — public #61), every EXISTING `data/*.jsonl` file copied in unchanged, and each
    `{filename: [rows...]}` in `overrides` written in its place instead. Returns
    `(returncode, problems, new_problems)`:

      problems      the shadow's own full problem list (never re-parsed from printed text),
                    or None when the validator crashed before writing its sidecar
      new_problems  `problems` MINUS whatever the REAL, UNMODIFIED profile already reports
                    right now (record.py's own G9 "new_problems" comparison, dev/audit
                    2026-09-02) — None when either side is unknown (a crash), else a list

    ⭐⭐ WHY THE COMPARISON IS BY PROBLEM SET, NOT BY rc (ADR-031 B2, 2026-09-11). A stage's
    own migration must refuse only what IT introduces — never an unrelated, pre-existing
    problem the profile already had. Confirmed as a real, not hypothetical, failure mode: a
    profile pending BOTH 0.44.0 and 0.45.0 runs 0.44.0 FIRST (`migrate.py`'s pending-migration
    loop is strictly sequential), and AT THAT MOMENT `applications[]` is still nested — 0.45.0
    has not run yet — so once 0.45.0's own retired-key guard is active in the shipped code
    (the same commit, `active_retired_keys()`'s own stage-gating), 0.44.0's OLD blanket
    `if rc != 0: refuse` check would refuse EVERY SUCH PROFILE's 0.44.0 migration for a defect
    0.44.0 has nothing to do with and cannot fix — the exact "a migration that refuses has not
    shipped either" trap, at the migration-CHAINING layer rather than the single-migration one
    B1 first solved it for. The fix is exactly record.py's own: compare problem SETS, refuse
    only on a genuinely NEW one, and let a pre-existing problem stand (loudly reported by the
    caller) for a LATER stage's own migration to resolve.

    The REAL profile is never touched by this function — it only ever reads it (to copy and to
    measure its own current problems), and only ever writes into a throwaway temp directory."""
    import record as _record
    real_data = os.path.join(profile, "data")
    _pre_rc, _, _, pre_problems = _record.validate(data_dir=real_data)
    with tempfile.TemporaryDirectory(prefix="migrate-b1-shadow-") as shadow:
        if os.path.isdir(profile):
            for name in os.listdir(profile):
                if name == "data":
                    continue
                try:
                    os.symlink(os.path.join(profile, name), os.path.join(shadow, name))
                except OSError:
                    pass
        shadow_data = os.path.join(shadow, "data")
        os.makedirs(shadow_data, exist_ok=True)
        if os.path.isdir(real_data):
            for name in os.listdir(real_data):
                if name.endswith(".jsonl") and name not in overrides:
                    shutil.copy2(os.path.join(real_data, name), os.path.join(shadow_data, name))
        for name, rows in overrides.items():
            with open(os.path.join(shadow_data, name), "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        rc, _out, _err, problems = _record.validate(data_dir=shadow_data)
        new = _record.new_problems(pre_problems, problems)
        return rc, problems, new
