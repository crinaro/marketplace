"""The journal file itself: where it is, the clock, the machine id, the profile pin and the engine version it is
checked against, and `append` / `read`, the only writer and the strict reader.

Capability module of `journal.py` (S4a, moved unedited)."""

import datetime
import json
import os
import re
import subprocess
from _root import is_tracked_fixture, is_unbound, engine_root
from journaling.row_shapes import PIN_EVENT, _MACHINE_RE, _ROW_CHECKS, _pin_ver
from journaling.tables import CITATION_RE, DISPATCH_FIELDS, EVENTS, JOURNAL, JournalError


def normalize_citation(raw):
    """Validate and canonicalize a `--covered-by` citation. Loud on anything else — an
    unparseable value is worse than none, because it looks handled and is not (the same rule
    this marketplace states for `precondition.py`, applied here to #69)."""
    m = CITATION_RE.match(raw or "")
    if not m:
        raise JournalError(
            "--covered-by %r is not a recognised citation — use 'dev #N', 'public #N', "
            "'marketplace #N' or 'GitHub #N' (check_regression_links.py's own vocabulary)"
            % raw)
    return "%s #%s" % (m.group(1).lower(), m.group(2))


def head_sha(root):
    """dev #703 -- `git rev-parse HEAD` in the profile, or None when git cannot answer (not a
    repository, no commits yet, no git on PATH, a timeout). None is "could not ask", which the
    caller records as an ABSENT field rather than a guess."""
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "HEAD"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (r.stdout or "").strip()
    return sha if r.returncode == 0 and re.match(r"^[0-9a-f]{7,64}$", sha) else None


# ─────────────────────────────────────────────────────────────────────────────
# dev #836 (jobsearch 0.88.0, design 9.3): WHAT A RUN THAT DIED LEFT. A `start` event now also carries
#   `machine`        a random hex id of THIS machine's checkout (never a hostname or a user name), so a report read on
#                    another machine says "not measured here" instead of blaming this machine's dirty files on that run;
#   `dirty_at_start` the tracked profile paths that were already modified when the run began, so the NEXT start on the
#                    same machine can say what was left uncommitted before it;
#   `utc_offset`     the writer's offset (`+HH:MM`), because `at` is a naive local time and `git --before` takes an instant.
# Each is OMITTED when it cannot be had (never null, never a guess): absence is "not measured". `journal.py` never
# imports config_keys (config_keys imports check_followups, which imports this module): the liveness window is a PARAMETER
# of `run_states`, passed by lifecycle, check_runs and panel.
# ─────────────────────────────────────────────────────────────────────────────
MACHINE_FILE = "jobsearch-machine"


def _git_common_dir(root):
    """The absolute `git rev-parse --git-common-dir` of the profile, or None when git cannot answer (not a repository, no
    git on PATH, a timeout). The machine file lives THERE, which is never pushed, so a synced profile has one id per
    machine."""
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        return None
    return out if os.path.isabs(out) else os.path.normpath(os.path.join(root, out))


def machine_id(root, create=False):
    """This machine's id for the profile at `root`: the content of `<git common dir>/jobsearch-machine` (a random
    `uuid4().hex`), or None when absent / unreadable / not a repository. `create=True` writes it when absent, only
    when git names a common dir (N10); a write that fails is None, never fatal. STATED LIMIT: a profile directory COPIED
    to another machine copies this file with it, so two machines can share an id; only the profile's git remote
    (ADR-012) is the supported way to move a profile."""
    gdir = _git_common_dir(root)
    if gdir is None:
        return None
    p = os.path.join(gdir, MACHINE_FILE)
    try:
        with open(p, encoding="utf-8") as fh:
            v = fh.read().strip()
        if _MACHINE_RE.match(v):
            return v
    except OSError:
        pass
    if not create:
        return None
    try:
        import uuid
        v = uuid.uuid4().hex
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(v + "\n")
        return v
    except OSError:
        return None


def dirty_paths(root):
    """The TRACKED paths the profile has modified right now (`git status --porcelain --untracked-files=no -z`), minus the
    journal file itself, sorted; None when git cannot answer. None is "could not ask": the caller omits the field."""
    try:
        r = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=no", "-z"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    paths, parts = [], (r.stdout or "").split("\0")
    i = 0
    while i < len(parts):
        ent = parts[i]
        i += 1
        if len(ent) < 4:
            continue
        if ent[0] in "RC":                      # a rename or copy carries its source as the next NUL field
            i += 1
        paths.append(ent[3:])
    journal = JOURNAL.replace(os.sep, "/")
    return sorted(p for p in set(paths) if p != journal)


def utc_offset(now=None):
    """The writer's UTC offset as `+HH:MM`, from the local clock (`at` is local and naive)."""
    z = (now or datetime.datetime.now()).astimezone().strftime("%z")
    return "%s%s:%s" % (z[0], z[1:3], z[3:5]) if len(z) == 5 else None


def path(root):
    return os.path.join(root, JOURNAL)


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


# ⭐⭐ dev #313 — THE ONE CHOKE POINT, GUARDED ONCE. Every write site in this file — `--fired`,
# `--start`, `--note`, `--gap`, `--gap-closed`, `--end` (including its `footprint`), `--dispose`,
# `record_swept`, `record_probe` — funnels through this single `append()`, so a guard here covers
# all of them without touching each call site individually.
#
# `journal.py --fired` is the FIRST SessionStart hook, ahead of `migrate.py` — so it is the first
# shipped write of any session, and `scripts/run_shipped.py`'s DEFAULT (safe-by-construction) pin
# points `CLAUDESEARCH_ROOT` straight at the tracked, checked-in fixture
# (`plugins/jobsearch/tests/fixtures/profile`) precisely so a maintainer verification has
# somewhere synthetic to run against. That is exactly the path that triggers this: running the
# hook chain against the fixture the safe way silently created an untracked
# `tests/fixtures/profile/data/runs.jsonl` (issue #313).
#
# `_root.is_tracked_fixture()` is the existing, already-shared predicate (`check_engine_purity.py`,
# `check_profile_leakage.py`, `install_rulebook.py` all use it) — this file adds no new predicate,
# only a caller. Per `_root.py`'s own docstring ("this module resolves; it does not decide
# whether the resolution is safe to act on... every WRITE-capable caller decides that for
# itself"), the refusal lives HERE, in the write-capable caller, not inside `_root.py` itself.
#
# The guard is the TRACKED PATH, not the fixture's *shape* — `is_tracked_fixture` matches on
# `.../tests/fixtures/...` or `.../fixtures/...` appearing in the resolved path, so a scratch
# COPY of the fixture (no `fixtures` segment in its path — e.g. `check_shipped_package.py`'s own
# `tmp/profile` materialization) is a different path and is correctly left writable.
#
# ⭐⭐ dev #618 — AND THE SAME CHOKE POINT REFUSES AN UNBOUND ROOT. `profile_root()`'s last-resort
# fallback is the session's cwd, wrapped in `_root.UnboundRoot`; `--fired` is the first hook of
# every session, so before this check a session opened in ANY directory (an engine checkout, a
# scratch repo) created `data/runs.jsonl` there — and `data/` is a profile marker, so every later
# hook then resolved that directory as a profile and wrote `.jobsearch/` beside it. Refusing here
# covers `--fired` and every other journal write at once; a plain-`str` root (a real profile, a
# scratch profile a test built) is untouched.
def _refuse_if_unwritable(root):
    """The two write refusals every journal write shares (dev #618, dev #313): no profile bound,
    or the tracked fixture. Factored out so the coverage cache (dev #711) obeys the same rule."""
    if is_unbound(root):
        raise JournalError(
            "no job-search profile is bound to %s (no CLAUDESEARCH_ROOT, no profile at or above "
            "it) — journal refuses to create files there. Run from inside a profile, or pin "
            "CLAUDESEARCH_ROOT (dev #618)" % root)
    if is_tracked_fixture(root):
        raise JournalError(
            "%s is the tracked fixture — journal refuses to write; pin CLAUDESEARCH_ROOT to a "
            "scratch copy" % root)


_PIN_CACHE = {}


def pin_scan(root):
    """The highest `min_engine` of any `profile-schema` event in `<root>/data/runs.jsonl`, or None. TOLERANT: a line
    that does not parse, an event of any other name and a pin whose `min_engine` is not `X.Y.Z` are skipped, and
    nothing else is validated (see the note above). Cached per process on the file's identity (path, size, mtime),
    so a pin this engine's own migration writes is seen by the very next call and a hand edit is never missed."""
    p = path(root)
    try:
        st = os.stat(p)
    except OSError:
        return None
    key = (p, st.st_size, st.st_mtime_ns)
    hit = _PIN_CACHE.get(p)
    if hit and hit[0] == key:
        return hit[1]
    best = None
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if PIN_EVENT not in line:                    # cheap pre-filter: most lines are not a pin
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("event") != PIN_EVENT:
                    continue
                v = _pin_ver(rec.get("min_engine"))
                if v is not None and (best is None or v > _pin_ver(best)):
                    best = rec["min_engine"]
    except OSError:
        return None
    _PIN_CACHE[p] = (key, best)
    return best


def profile_pin(recs):
    """The highest `min_engine` among already-read `recs` (`read()`'s rows), or None."""
    best = None
    for r in recs or ():
        if isinstance(r, dict) and r.get("event") == PIN_EVENT:
            v = _pin_ver(r.get("min_engine"))
            if v is not None and (best is None or v > _pin_ver(best)):
                best = r["min_engine"]
    return best


def pin_refusal(root):
    """The refusal sentence when this profile is pinned ABOVE the running engine, else None. An engine whose own
    version cannot be read has nothing to compare against and refuses nothing (`engine_version()` raises there, and
    a housekeeping read must not become a second failure)."""
    pin = pin_scan(root)
    if pin is None:
        return None
    try:
        engine = engine_version()
    except JournalError:
        return None
    if _pin_ver(pin) > _pin_ver(engine):
        return ("jobsearch %s on this machine; this profile was upgraded by jobsearch %s. Update the plugin on "
                "this machine before running it here. Nothing was written." % (engine, pin))
    return None


def append(root, rec):
    _refuse_if_unwritable(root)
    refusal = pin_refusal(root)                  # dev #834: a profile pinned above this engine is read-only to it
    if refusal:
        raise JournalError(refusal)
    p = path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def read(root):
    refusal = pin_refusal(root)                  # dev #834: before any line is validated (see the pin note above `append`)
    if refusal:
        raise JournalError(refusal)
    out = []
    try:
        with open(path(root), encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    raise JournalError("%s line %d is not valid JSON — a journal that cannot be "
                                       "read is a journal that is not protecting anything"
                                       % (JOURNAL, n))
                if rec.get("event") not in EVENTS:
                    raise JournalError("%s line %d has unknown event %r"
                                       % (JOURNAL, n, rec.get("event")))
                if rec.get("event") in _ROW_CHECKS:
                    try:
                        _ROW_CHECKS[rec["event"]](rec)
                    except JournalError as e:
                        raise JournalError("%s line %d %s row: %s" % (JOURNAL, n, rec["event"], e))
                if rec.get("event") == "dispatch":
                    missing = [k for k in DISPATCH_FIELDS if k not in rec]
                    unknown = [k for k in rec if k not in DISPATCH_FIELDS]
                    if missing:
                        raise JournalError(
                            "%s line %d dispatch row missing field(s): %s"
                            % (JOURNAL, n, ", ".join(missing)))
                    if unknown:
                        raise JournalError(
                            "%s line %d dispatch row has unknown field(s): %s — this parser "
                            "refuses what it cannot read rather than ignoring it"
                            % (JOURNAL, n, ", ".join(unknown)))
                out.append(rec)
    except FileNotFoundError:
        pass
    return out


def new_run_id(kind, at):
    slug = re.sub(r"[^a-z0-9]+", "-", (kind or "run").lower()).strip("-") or "run"
    return "%s-%s" % (slug, re.sub(r"[^0-9]", "", at)[:14])


ENGINE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def engine_version():
    """The running engine's version, from its `.claude-plugin/plugin.json`. Raises `JournalError` when
    it cannot be read as `X.Y.Z`: a `start` written without one would read as an OLDER engine and print a
    bogus ENGINE SKEW, so `--start` refuses rather than write it (dev #820, G3)."""
    try:
        with open(os.path.join(engine_root(), ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            v = json.load(fh).get("version")
    except (OSError, ValueError):
        v = None
    if not isinstance(v, str) or not ENGINE_VERSION_RE.match(v):
        raise JournalError("cannot read this engine's version from .claude-plugin/plugin.json (got %r): a "
                           "run start without its engine cannot be told from a pre-0.82.0 run" % (v,))
    return v
