"""Migration 0.26.0: `m_0_26_0_state_home()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil

VERSION = "0.26.0"


def m_0_26_0_state_home(profile, apply_it, home=None):
    """0.26.0 — per-profile engine state moves from `~/.claude/jobsearch/` into the profile
    (dev #151).

    `diagnostics.log` and `drift/` were machine-global and keyed by SESSION, so two profiles
    on one machine interleaved in one file with no way to separate them — which made
    `guard_status()`'s own question ("has THIS install had an inert guard for two days?")
    unanswerable the moment a second profile existed. The line that holds: per-profile STATE
    belongs with the profile; only what is needed to FIND a profile (`run`, `profile_root`,
    `engine_root`) stays under `$HOME`. Those three are deliberately untouched.

    ⭐ PRESERVE, THEN TRANSFORM. `diagnostics.log` is the store `doctor`/`whoami` read for
    guard status, so its rows are merged into `<profile>/.jobsearch/diagnostics.log` — global
    rows first, then any the new code already wrote there — and the source is removed only
    after the destination is verified readable. The rows carry no identifiers by `_diag.py`'s
    own contract, so with one known profile they are all attributable to it; a second profile
    migrating later finds nothing left to claim and no-ops. `drift/` markers move the same
    way. `.jobsearch/` is added to the profile's `.gitignore`: the state is machine-local and
    data-free, and committing ring-buffer churn would pollute every commit.

    SAFE (nothing is discarded; everything is relocated), so it applies automatically.
    `home` is a test seam; real runs resolve `$HOME`.
    """
    home = home or os.path.expanduser("~")
    src_dir = os.path.join(home, ".claude", "jobsearch")
    src_log = os.path.join(src_dir, "diagnostics.log")
    src_drift = os.path.join(src_dir, "drift")
    dest_dir = os.path.join(profile, ".jobsearch")
    dest_log = os.path.join(dest_dir, "diagnostics.log")
    dest_drift = os.path.join(dest_dir, "drift")

    have_log = os.path.exists(src_log)
    have_drift = os.path.isdir(src_drift)
    gi_path = os.path.join(profile, ".gitignore")
    try:
        with open(gi_path, encoding="utf-8") as fh:
            gi_lines = [l.strip() for l in fh.read().splitlines()]
    except OSError:
        gi_lines = None                       # no .gitignore yet
    need_gi = not gi_lines or ".jobsearch/" not in gi_lines
    if not (have_log or have_drift or need_gi):
        return True, ""                       # nothing global left, ignore rule in place

    if not apply_it:
        bits = []
        if have_log:
            bits.append("merge ~/.claude/jobsearch/diagnostics.log into .jobsearch/")
        if have_drift:
            bits.append("move ~/.claude/jobsearch/drift/ into .jobsearch/")
        if need_gi:
            bits.append("gitignore .jobsearch/")
        return True, "  would %s" % "; ".join(bits)

    try:
        os.makedirs(dest_dir, exist_ok=True)
        if have_log:
            # PRESERVE: merge, oldest provenance first — the global rows predate anything the
            # relocated writer has appended here — capped at the ring buffer's own size.
            merged = []
            with open(src_log, encoding="utf-8") as fh:
                merged.extend(l for l in fh.readlines() if l.strip())
            if os.path.exists(dest_log):
                with open(dest_log, encoding="utf-8") as fh:
                    merged.extend(l for l in fh.readlines() if l.strip())
            merged = merged[-500:]
            tmp = dest_log + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.writelines(l if l.endswith("\n") else l + "\n" for l in merged)
            os.replace(tmp, dest_log)
            # verify before removing the source — a move that lost the guard history would be
            # exactly the destructive outcome this migration exists to avoid
            with open(dest_log, encoding="utf-8") as fh:
                if len([l for l in fh if l.strip()]) != len(merged):
                    return False, ("  ⚠️ diagnostics.log merge could not be verified; the "
                                   "global log was left in place (retries next session).")
            os.remove(src_log)
        if have_drift:
            os.makedirs(dest_drift, exist_ok=True)
            for name in sorted(os.listdir(src_drift)):
                s, d = os.path.join(src_drift, name), os.path.join(dest_drift, name)
                if os.path.isfile(s):
                    if os.path.exists(d):     # merge marker lines rather than clobbering
                        with open(d, encoding="utf-8") as fh:
                            seen = fh.read().splitlines()
                        with open(s, encoding="utf-8") as fh:
                            extra = [l for l in fh.read().splitlines()
                                     if l and l not in seen]
                        if extra:
                            with open(d, "a", encoding="utf-8") as fh:
                                fh.write("\n".join(extra) + "\n")
                    else:
                        shutil.copy2(s, d)
                    os.remove(s)
            try:
                os.rmdir(src_drift)           # only if now empty
            except OSError:
                pass
        if need_gi:
            existing = ""
            if gi_lines is not None:
                with open(gi_path, encoding="utf-8") as fh:
                    existing = fh.read()
            with open(gi_path + ".tmp", "w", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                fh.write(existing + ".jobsearch/\n")
            os.replace(gi_path + ".tmp", gi_path)
    except Exception as e:                    # noqa: BLE001 — preserve on ANY miss
        return False, ("  ⚠️ could not relocate engine state (%s) — nothing was deleted; it "
                       "will retry next session." % e)

    bits = []
    if have_log:
        bits.append("diagnostics.log")
    if have_drift:
        bits.append("drift/")
    what = " and ".join(bits) if bits else "nothing left to move"
    return True, ("  ✅ per-profile engine state (%s) now lives in .jobsearch/ inside this "
                  "profile (gitignored); ~/.claude/jobsearch keeps only the run launcher and "
                  "the two locator pointers." % what)
