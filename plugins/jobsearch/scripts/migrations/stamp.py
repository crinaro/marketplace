"""The schema stamp a profile carries (`.jobsearch-schema`), the engine version, and the housekeeping commit of what
a migration run changed.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import json
import os
import subprocess
from migrations.paths import HERE


STAMP = ".jobsearch-schema"


# The profile's substantive, known-shape content — the same conservative, explicit-by-name list
# m_0_17_0's initial commit stages (never `git add -A`: a concurrent writer's in-flight work must
# never ride along in a commit this migration did not make and cannot describe). Reused by
# commit_migrated_paths() (public #52) so a migration's own data/config rewrite is committed
# alongside the schema stamp, not left to whichever later, unrelated commit happens to notice it.
KNOWN_PROFILE_ARTIFACTS = ("config.json", "user.json", "data", "kb", "call_preps", "archive")


def engine_version():
    try:
        with open(os.path.join(os.path.dirname(HERE), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("version") or "0.0.0"
    except Exception:
        return "0.0.0"


def ver(s):
    try:
        return tuple(int(x) for x in str(s).split(".")[:3])
    except Exception:
        return (0, 0, 0)


def read_stamp(profile):
    """The schema version this profile has been migrated to.

    ⭐ ACCEPTS BOTH SHAPES. The stamp was a bare version string; it is now a small JSON
    record that also carries the last ATTEMPT (see write_stamp). A profile written by an
    older engine still holds the bare string, and must keep working untouched — the record
    is an addition, never a precondition."""
    try:
        with open(os.path.join(profile, STAMP), encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return "0.0.0"
    if raw.startswith("{"):
        try:
            return str(json.loads(raw).get("schema") or "0.0.0")
        except ValueError:
            return "0.0.0"
    return raw or "0.0.0"


def read_attempt(profile):
    """The last migration ATTEMPT, or None if this profile has never recorded one.

    ⭐⭐ THIS IS THE POINT OF GitHub #41. The stamp recorded only the version ACHIEVED, so
    `nothing to migrate` and `never looked` were the same observation — a stamp eleven
    minors behind, a hook present the whole time, and no way to tell whether it had ever
    run. An attempt record makes the difference visible: a run that found nothing still
    writes one, so an ABSENT record means the hook genuinely never fired."""
    try:
        with open(os.path.join(profile, STAMP), encoding="utf-8") as fh:
            raw = fh.read().strip()
        if raw.startswith("{"):
            return json.loads(raw).get("last_attempt") or None
    except (OSError, ValueError):
        pass
    return None


def write_stamp(profile, version):
    """Write the schema stamp. Never raises (see module docstring: FAILS OPEN, ALWAYS) — but
    an OSError here used to be swallowed silently and reported as though it had succeeded
    (GitHub #8). That reproduces this project's worst-case shape: work gets APPLIED, the profile
    is left recording the OLD schema version, and every subsequent session re-applies the same
    migrations forever, with nothing anywhere saying so. Returns (ok, error) instead — the
    caller in main() is responsible for being LOUD about a failure; this function only reports
    one, it never hides it."""
    return write_stamp_record(profile, version, None)


def write_stamp_record(profile, version, attempt):
    """Write the stamp, optionally recording what the last attempt DID.

    ⭐ `attempt` is written even when nothing needed doing — that is the whole value. A run
    that found nothing to do leaves `{"result": "no-op"}`, so a MISSING record means the
    migration never ran at all, which is the condition #41 could not distinguish."""
    doc = {"schema": version}
    prior = read_attempt(profile)
    if attempt is not None:
        doc["last_attempt"] = attempt
    elif prior is not None:
        doc["last_attempt"] = prior
    try:
        with open(os.path.join(profile, STAMP), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        return True, None
    except OSError as e:
        return False, e


def commit_migrated_paths(profile, paths, message):
    """⭐ public #52 — a rewrite nobody commits sits as an uncommitted diff forever.

    `migrate.py` rewrites the profile's CLAUDE.md (`install_rulebook.refresh_if_stale`) and the
    schema stamp (`write_stamp_record`) from a SessionStart hook, entirely outside the normal
    end-of-run commit step — a candidate who never reaches the end of a run (or whose run fails
    before that step) is left with those changes sitting uncommitted, invisible to `git status`
    only until someone thinks to look, and one `git stash`/`git checkout` away from being lost.

    ⚠️ COMMIT ONLY ON APPLIED, NEVER ON A NO-OP. `record_noop()`'s own rate-limit comment
    already states why: the profile is usually a git repository, and stamping (let alone
    committing) every SessionStart would put a one-line commit's worth of churn in the user's
    history for the rest of time. This is called ONLY from the genuine-change paths in main()
    (a real rulebook refresh, or migrations that actually applied) — never from record_noop().

    ⭐ EXPLICIT PATHS, NEVER `git add -A` — the same rule m_0_17_0's initial commit follows,
    for the same reason: the profile may have a concurrent writer (a scheduled run, another
    session), and a blanket add would bundle whatever that writer has in flight into a commit
    this migration did not make and cannot describe.

    Fails open, always: no git binary, not a repo, nothing staged, or the commit itself failing
    are all silently fine — a housekeeping commit must never block or fail a session, and the
    change is still on disk either way, ready for the next normal commit to pick up.
    """
    try:
        import sync as _sync
        state = _sync.git_state(profile)
        if not state["git"] or not state["repo"]:
            return
        existing = [p for p in paths if os.path.exists(os.path.join(profile, p))]
        if not existing:
            return
        add = subprocess.run(["git", "-C", profile, "add", "--"] + existing,
                             capture_output=True, text=True, timeout=30)
        if add.returncode != 0:
            return
        # Nothing staged (the rewrite left the file byte-identical, e.g. a rulebook refresh
        # that only touched the provenance stamp to the same value) — nothing to commit.
        diff = subprocess.run(["git", "-C", profile, "diff", "--cached", "--quiet"],
                              capture_output=True, timeout=30)
        if diff.returncode == 0:
            return
        ident = []
        if not (subprocess.run(["git", "-C", profile, "config", "user.email"],
                               capture_output=True, text=True, timeout=15).stdout or "").strip():
            # No git identity on this machine — a neutral one for THIS commit only via -c,
            # same fallback m_0_17_0 uses. Never written into the user's config.
            ident = ["-c", "user.name=jobsearch-migrate", "-c", "user.email=migrate@localhost"]
        subprocess.run(["git", "-C", profile] + ident + ["commit", "-q", "-m", message],
                       capture_output=True, text=True, timeout=30)
    except Exception:                                   # noqa: BLE001 — never blocks a session
        pass


def attempt_record(engine, result, detail=""):
    import datetime
    rec = {"at": datetime.datetime.now().replace(microsecond=0).isoformat(),
           "engine": engine, "result": result}
    if detail:
        rec["detail"] = detail[:200]
    return rec


def record_noop(profile, engine):
    """Record that a migration run happened and found nothing to do.

    ⚠️ RATE-LIMITED ON PURPOSE. The profile is usually a git repository, and stamping every
    single SessionStart would put a one-line commit's worth of churn in the user's own
    history for the rest of time. Once per (engine version, day) is enough to answer the
    only question this record exists for — did it EVER run — without becoming noise."""
    prior = read_attempt(profile) or {}
    today = attempt_record(engine, "no-op")["at"][:10]
    if prior.get("engine") == engine and str(prior.get("at", ""))[:10] == today:
        return True, None
    return write_stamp_record(profile, read_stamp(profile),
                              attempt_record(engine, "no-op"))


_SEMVER_RE_STR = r"^\d+\.\d+\.\d+$"
