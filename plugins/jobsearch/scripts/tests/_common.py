# Shared preamble for the split regression suite (dev #399 SS1) -- imports, path
# resolution, and cross-area helpers used by more than one tests/test_*.py module.
# Every test module does `from _common import *`. HERE/ENGINE_SCRIPTS below are
# redefined one level up from where test_checks.py computed them, because this file
# lives in scripts/tests/ -- one directory deeper than test_checks.py did.

"""
Regression tests for the hygiene/reporting scripts. Standard library `unittest`,
no third-party packages, no network, no mailbox access — so this runs unattended
in any scheduled run.

    python3 scripts/test_checks.py            # or: python3 -m unittest discover scripts

WHY THIS EXISTS
---------------
Until 2026-08-02 there was no test suite at all: correctness was established by
running scripts against live data and reading the output. That is exactly how
`funnel_report.py` shipped a **hardcoded sentence** claiming "`stage` never goes
past 'contacted' on any record" — true the day it was written, false by the day it
was read, and printed every run as though it had been measured. The weekly review
then quoted it back as a finding and nearly caused a "backfill" of records that
were already correct.

The tests below are deliberately anchored to REAL BUGS THIS REPO HAS SHIPPED, not
to hypothetical ones. Each names its incident. When a new one is found, add a case
here rather than only writing a paragraph about it — a rule in prose is re-read and
re-interpreted every run; a test fails loudly and for free.
"""

import ast
import collections
import contextlib
import datetime
import glob
import hashlib
import inspect
import json
import io
import os
import re
import shutil
import pathlib
import subprocess
import sys
import tempfile
import unittest

# ⭐ THE TEST SUITE USES ITS OWN LOCK FILE. Fourteen call sites exercise real lock acquisition;
# against the production lock they failed whenever any session legitimately held it, which is
# exactly the false-RED flakiness that made "take the lock before the gate sweep" self-defeating.
# A test that exercises a lock must use its own.
#
# ⭐ dev #442: "its own" must mean per-PROCESS, not merely per-suite-file. A fixed filename here
# is shared by every concurrently-running Python process on the machine, not just by tests
# within ONE process — unittest itself runs a process's own tests serially, so nothing inside a
# single `test_checks.py` run ever raced. What actually raced was TWO full-suite runs (or a
# full-suite run alongside `check_ci_parity.py`/`check_unfalsifiable_skips.py`'s own in-process
# re-run of one test) sharing this SAME `/tmp/claudesearch-test-lock.json` path: reproduced by
# running `TestLockReleaseIsStructural` 20x in a loop while two more full-suite processes ran
# concurrently in the background — 8/20 iterations failed, with exactly the shapes a shared lock
# file predicts ("precondition: lock must be free" when a concurrent process's subprocess was
# mid-hold; "lock leaked after a failing command" when a concurrent process's own release raced
# ours; "the command's exit code must propagate" seeing 7 instead of 1 when a concurrent
# process's release freed OUR refused-take's lock out from under the assertion). The same shared
# file also produced `check_engine_purity.hook_step()`'s "store-busy" decline
# (`runlock.read() is not None`) firing under a concurrent process's hold, which is what dev #442
# separately named as `check_unfalsifiable_skips.py`'s "1 in 11" flake. A per-process suffix
# (`os.getpid()`) keeps every subprocess call WITHIN one process on the one shared file the
# take/release contract needs to exercise, while giving every concurrently-running process (two
# full-suite runs, or a full-suite run plus a gate's own re-run) its own — no shared resource
# left to contend over.
os.environ.setdefault("CLAUDESEARCH_LOCK_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "claudesearch-test-lock-%d.json" % os.getpid()))

# ⭐ SAME SHAPE, FOR THE DIAGNOSTICS LOG (GitHub #9). Migrations here are exercised against
# synthetic temp fixtures, never a real profile — a run against `_diag`'s hard-coded production
# path would append "applied" events for schema versions never actually applied to anyone's real
# data, and a diagnostic that cannot be trusted is worse than none (it actively misled a
# diagnosis once already). Set before `_diag` is first imported by anything in this process, so
# every in-process call inherits it; a subprocess picks the same override up fresh from the
# environment. Individual test classes may still re-point `_diag.LOG` at their OWN per-test temp
# file for tighter isolation (clean event counts) — this is the suite-wide floor underneath that.
os.environ.setdefault("CLAUDESEARCH_DIAG_LOG",
                      os.path.join(tempfile.gettempdir(), "claudesearch-test-diagnostics.log"))

# ⭐ SAME SHAPE, FOR THE MACHINE-GLOBAL TWIN (`_diag.log_machine` / `_diag.MACHINE_LOG`) — engine
# pointer and launcher-repair events. Without this override a suite run on a real machine would
# read (and, via any in-process call, potentially write) the OWNER'S OWN
# `~/.claude/jobsearch/diagnostics.log`, which is exactly the class of leakage
# CLAUDESEARCH_DIAG_LOG above already exists to prevent for the profile-preferring log.
os.environ.setdefault("CLAUDESEARCH_MACHINE_DIAG_LOG",
                      os.path.join(tempfile.gettempdir(), "claudesearch-test-machine-diagnostics.log"))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # up from scripts/tests/ to scripts/
# ⭐ ENGINE vs PROFILE (2026-08-05). As a PLUGIN these are different trees: the engine installs
# under ${CLAUDE_PLUGIN_ROOT}, the user's data lives where they run. Tests that check STRUCTURE
# (agents, skills, CI, CLAUDE.md) use ENGINE; tests that read a pipeline use ROOT, the profile.
# Conflating them is the bug that silently emptied the dashboard on 2026-08-05.
import sys as _s
_s.path.insert(0, HERE)
from _root import profile_root as _pr, engine_root as _er
import _tree
ENGINE = _er()
ENGINE_SCRIPTS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # up from scripts/tests/ to scripts/
# ⭐ FIXTURE FALLBACK (2026-08-05). The suite reads a profile — data stores, config, narrative — so
# from a bare engine clone it collapsed (18 failures / 55 errors) and CI could never be green.
# A guard nobody can run is a guard nobody has.
#   real profile  -> test against real data (what the owner does; catches drift)
#   anywhere else -> tests/fixtures/profile, synthetic, no real person or figure in it
_real = _pr()
_FIXTURE = os.path.join(ENGINE, "tests", "fixtures", "profile")

# ⭐⭐ dev #507 — SELF-HEAL A POISONED FIXTURE, AT IMPORT TIME, BEFORE ANYTHING COPIES IT.
#
# `_run_with_skip_accounting()` below (`test_checks.py`'s own entry point) wraps a full suite
# run in `_fixture_locked_for_run()`, which strips the write bit from every tracked fixture
# path for the run and restores it in `finally` — "even on a crash", per that function's own
# docstring, but that claim is only true for a Python exception. A process KILLED mid-run (a
# dispatch hitting its tool-use/time cap while `runner.run(suite)` is still executing — the
# full suite is ~1850 tests) never reaches ANY `finally`: no signal handler and no `atexit`
# hook runs for SIGKILL. The tracked fixture is then left write-stripped ON DISK, in THAT ONE
# worktree, invisible to `git status` (git tracks the executable bit only, never read/write) —
# permanently, until something notices and repairs it by hand.
#
# Left uncorrected, every OTHER `shutil.copytree(_FIXTURE, scratch)` call site in this suite
# (dozens of them — `_fixture_locked_for_run()`'s own docstring names the count) silently
# inherits the same read-only bits onto its scratch copy (`shutil.copystat`'s default
# behavior), so an unrelated write inside that scratch copy fails with a bare `OSError` a
# caller three layers up reads as a real, structural verdict —
# `check_engine_purity.hook_step()`'s persistent-state probe reads it as `no-persistent-state`,
# and `TestPurityHookStep`'s tests then read `verdict != "hit"` and skip, UNCITED. That is a
# RED `check_ci_parity.py`'s own fresh `git clone --no-local` never reproduces (a clone writes
# every blob's bytes fresh from the object database and never inherits a SOURCE WORKING TREE's
# own on-disk-only permission mutation) — the exact "passes only in a clone, never in the
# worktree that actually ran the killed suite" shape dev #507 was opened to explain.
#
# So: BEFORE anything else in this process touches `_FIXTURE`, repair it if it is currently not
# fully writable, loudly (the same "state the gap, do not paper over it" convention this file's
# own "maintainer checkout — not remembering" print already uses below) — never silently.
def _self_heal_fixture_writability():
    unwritable = []
    for dirpath, dirs, files in os.walk(_FIXTURE):
        for name in dirs + files:
            p = os.path.join(dirpath, name)
            try:
                if not os.access(p, os.W_OK):
                    unwritable.append(p)
            except OSError:
                pass
    if not os.access(_FIXTURE, os.W_OK):
        unwritable.append(_FIXTURE)
    if not unwritable:
        return
    print("jobsearch: %d path(s) under the tracked fixture were left read-only by a prior "
          "run that never reached its own restore (dev #507) — repairing before use: %s"
          % (len(unwritable), _FIXTURE), file=sys.stderr)
    for p in unwritable:
        try:
            os.chmod(p, os.stat(p).st_mode | 0o200)
        except OSError as exc:
            print("jobsearch: could not repair %s: %s" % (p, exc), file=sys.stderr)


if os.path.isdir(_FIXTURE):
    _self_heal_fixture_writability()

# ⭐ SOME TESTS ASSERT THE MAINTAINER'S LAYOUT, NOT THE PRODUCT — GitHub #56.
#
# A handful of checks below shell out to `git ls-files` against the engine, or expect the
# marketplace's own `scripts/` directory to sit beside it. Both are true in a checkout and
# false in an installed plugin, which is a COPY with no .git and no sibling marketplace.
# Run from an install they failed 4 tests, and the failure read as a defect in the engine
# rather than as the suite being pointed somewhere it does not describe.
#
# The suite no longer ships (publish_manifest classifies `test_` as maintenance), so this
# cannot normally happen — but a guard that states the requirement is better than four
# confusing failures if it ever does. It SKIPS rather than passes: a test that cannot run
# has not run, and must never be counted as green.
def _has_git_entry(path):
    """True if `path` has a `.git` entry at its own root — a DIRECTORY for a primary checkout,
    or a FILE (a `gitdir: <common-dir>/worktrees/<name>` pointer) for a linked worktree.

    ⚠️ dev #333: this used to be `os.path.isdir(os.path.join(path, ".git"))`, which reads a
    worktree as "not a checkout" (its `.git` is a file) and silently SKIPPED every test this
    guard exists to run — the four `git ls-files` / sibling-`scripts/` assertions this comment
    block describes are exactly as valid from a worktree as from the primary clone, since a
    worktree shares the common `.git` and the same tracked files. `os.path.exists` accepts
    either shape; nothing here needs to actually run git."""
    return os.path.exists(os.path.join(path, ".git"))


IS_CHECKOUT = _has_git_entry(ENGINE) or _has_git_entry(
    os.path.dirname(os.path.dirname(ENGINE)))
_NEEDS_CHECKOUT = "asserts the maintainer's repo layout (git + sibling marketplace scripts/); \
this is an installed plugin, which is a copy with neither — see GitHub #56"
ROOT = _real if os.path.exists(os.path.join(_real, "data", "opportunities.jsonl")) else _FIXTURE
USING_FIXTURE = ROOT == _FIXTURE
if USING_FIXTURE:
    # subprocesses must see the SAME profile, or half the suite tests one dataset and half another
    os.environ["CLAUDESEARCH_ROOT"] = ROOT
    os.environ["CLAUDESEARCH_DATA_DIR"] = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)

import profile as _profile
# The `next_action_owner` value meaning "the candidate must act" — this profile's own token,
# never a hardcoded name (issue #35; see profile.owner_token()).
OWNER_TOKEN = _profile.owner_token()


def load_jsonl(name):
    with open(os.path.join(ROOT, "data", name), encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def load_opps():
    return load_jsonl("opportunities.jsonl")



def _norm_invocations(text):
    """Strip plugin-path decoration so command assertions survive a layout change.

    `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/x.py" --flag` -> `python3 scripts/x.py --flag`
    Added 2026-08-05 with the plugin restructure: assertions should encode WHAT the run does,
    never WHERE the engine happens to be installed."""
    text = text.replace('${CLAUDE_PLUGIN_ROOT}/', '')
    # `$ENGINE` replaced it 2026-08-05: ${CLAUDE_PLUGIN_ROOT} is not set inside a Bash tool call,
    # so the skills resolve the engine from a file instead.
    text = text.replace('"$ENGINE/', '"').replace('$ENGINE/', '')
    # The launcher replaced $ENGINE 2026-08-05: a compound, quoted command could not be
    # allowlisted, so unattended runs stopped for approval on every script call.
    text = text.replace('~/.claude/jobsearch/run ', 'python3 scripts/')
    return re.sub(r'"(scripts/[A-Za-z0-9_]+\.(?:py|sh))"', r'\1', text)


class _SyntheticStore(unittest.TestCase):
    """Run validate_data.py against a synthetic one-opportunity store.

    Enum/coherence rules are exercised by INDUCING the failure (this repo's standing
    discipline), against a temp store so no live data is ever touched — the lesson
    TestDataModelIsEnforced paid for."""

    BASE_OPP = {
        "id": "acme-cto", "company_id": "acme", "title": "CTO",
        "status": "backlog", "stage": "sourced", "verdict": "undecided",
        "jd_url": None, "location": {"type": "remote", "primary": "Remote"},
        "sightings": [{"channel_id": "board", "seen_on": "2026-08-11"}],
        "next_action_owner": OWNER_TOKEN,
        # ADR-031 B4 (design §17) — required on every LIVE opportunity. A play-less plan, so
        # every existing subclass here stays valid without any opinion about plays.
        "plan_id": "default-plan", "plan_assigned_on": "2026-08-11",
    }
    # The plan BASE_OPP's plan_id resolves to — one row, reused by every subclass.
    BASE_PLAN = {"id": "default-plan", "subject_kind": "search", "subject_id": "default",
                "outcomes": ["role"], "goal": None, "approach": None, "cadence": None,
                "status": "active", "play_id": None, "play_confirmed": None,
                "resolves_when": None, "resolved_on": None, "resolution": None,
                "targets": None, "note": None}

    def _validate(self, **opp_overrides):
        # ADR-031 B2 — `applications` is a top-level store, not an opportunity field any
        # more; a caller passing `applications=[...]` (the pre-B2 calling convention every
        # existing subclass here still uses) gets it promoted to `applications.jsonl`
        # instead of written onto the opportunity record.
        applications = opp_overrides.pop("applications", None)
        opp = dict(self.BASE_OPP)
        opp.update(opp_overrides)
        tmp = tempfile.mkdtemp(prefix="jobsearch-test-store-")
        self.addCleanup(shutil.rmtree, tmp, True)
        app_rows = [dict(a, id=a.get("app_id") or "%s-a%d" % (opp["id"], i + 1),
                         opp_id=opp["id"])
                   for i, a in enumerate(applications or [])]
        for a in app_rows:
            a.pop("app_id", None)
        rows = {
            "companies.jsonl": [{"id": "acme", "name": "Acme", "vertical": "other",
                                 "status": "watching"}],
            "channels.jsonl": [{"id": "board", "label": "Board", "type": "job-board",
                                "review_cadence": "weekly"}],
            "opportunities.jsonl": [opp],
            "messages.jsonl": [],
            "applications.jsonl": app_rows,
            "plans.jsonl": [self.BASE_PLAN],
        }
        for name, recs in rows.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
        env = dict(os.environ, CLAUDESEARCH_DATA_DIR=tmp)
        return subprocess.run([sys.executable, os.path.join(HERE, "validate_data.py")],
                              capture_output=True, text=True, env=env)


class _SyntheticCoverage(unittest.TestCase):
    """Shared scaffolding for the dev #321 test classes below: a synthetic profile with a
    controlled mailbox list and a controlled coverage ledger. No test_ methods of its own —
    TestLoader collects it as an empty suite, the same pattern `_SyntheticStore` already uses
    for validate_data.py's synthetic-store tests."""

    IDENTITY = {"full_name": "Synth Example", "display_name": "Synth",
               "primary_email": "synth.mctesterson@example.com",
               "preferred_reference": "Synth"}

    def setUp(self):
        sys.path.insert(0, os.path.join(ENGINE, "scripts"))
        import journal
        import mail_client
        self.J = journal
        self.M = mail_client
        self.tmp = tempfile.mkdtemp(prefix="coverage-ledger-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, "data"))

    def _profile(self, root=None, mailboxes=("cand@example.com",), opps=()):
        root = root or self.tmp
        with open(os.path.join(root, "user.json"), "w", encoding="utf-8") as fh:
            json.dump({"identity": self.IDENTITY,
                      "mailboxes": [{"address": a} for a in mailboxes]}, fh)
        with open(os.path.join(root, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        # ADR-031 B3 — `touches` is a top-level store now; promote each opportunity's nested
        # `outreach` into it, since `check_followups.load_opps()` enriches via
        # `touches.enrich_opportunities()`, which reads `data/touches.jsonl` off disk.
        opps = [dict(o) for o in opps]
        touch_rows = []
        for o in opps:
            legacy = o.pop("outreach", None)
            for i, t in enumerate(legacy or []):
                t = dict(t, id="%s-t%d" % (o["id"], i + 1), opp_id=o["id"])
                touch_rows.append(t)
        with open(os.path.join(root, "data", "opportunities.jsonl"), "w", encoding="utf-8") as fh:
            for o in opps:
                fh.write(json.dumps(o) + "\n")
        with open(os.path.join(root, "data", "touches.jsonl"), "w", encoding="utf-8") as fh:
            for t in touch_rows:
                fh.write(json.dumps(t) + "\n")
        return root

    def _silent_opp(self, oid, sent_on):
        return {"id": oid, "company_id": oid + "-co", "title": "Staff Engineer",
               "status": "active-pursuit", "stage": "contacted",
               "outreach": [{"status": "sent", "date": sent_on, "outcome": "awaiting"}]}

    def _run_followups(self, root, days=7):
        env = dict(os.environ, CLAUDESEARCH_ROOT=root)
        return subprocess.run(
            [sys.executable, os.path.join(ENGINE, "scripts", "check_followups.py"),
            "--days", str(days)], capture_output=True, text=True, env=env, cwd=root)


class _SyncFixtures(unittest.TestCase):
    """Shared fixtures for the ADR-012 classes below -- no tests of its own, so inheriting it
    never re-runs another class's cases. Every test uses a real
    `tempfile.TemporaryDirectory()` and, where a git repo is needed, a real local `git init` --
    never the owner's actual profile. `no-git` is the one state that cannot be built with a
    real directory: it is simulated by pointing the CHILD PROCESS's PATH at an empty
    directory, not by touching this machine's git install.
    """

    def setUp(self):
        sys.path.insert(0, HERE)
        import sync
        self.sync = sync
        self._fakebin = tempfile.mkdtemp(prefix="claudesearch-nogit-")

    def tearDown(self):
        shutil.rmtree(self._fakebin, ignore_errors=True)

    def _profile(self, d, cfg=None):
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg if cfg is not None else {}, fh)

    def _git(self, d, *args):
        return subprocess.run(["git", "-C", d] + list(args),
                              capture_output=True, text=True, timeout=15)

    def _repo(self, d, origin=None):
        """A REAL local git repo -- `git init`, optionally with a (never-fetched) origin URL.
        sync.py only ever reads `git remote get-url origin` locally, so the URL need not resolve.
        """
        self._git(d, "init", "-q")
        if origin:
            self._git(d, "remote", "add", "origin", origin)

    def _cli(self, root, *args, **kw):
        no_git = kw.pop("no_git", False)
        env = dict(os.environ, CLAUDESEARCH_ROOT=root)
        if no_git:
            env["PATH"] = self._fakebin            # empty dir: shutil.which("git") -> None
        return subprocess.run([sys.executable, os.path.join(HERE, "sync.py")] + list(args),
                              capture_output=True, text=True, timeout=15, env=env)


class _WriteApiHarness(unittest.TestCase):
    """A disposable FULL profile for exercising record.py end to end (create, locking).

    record.py resolves the profile via CLAUDESEARCH_ROOT and its validate subprocess reads
    CLAUDESEARCH_DATA_DIR, so both point at the same throwaway tree. The lock is a per-test
    file (a test that exercises a lock must use its own — the suite-wide rule), and these tests
    additionally assert on the lock file's own existence, so sharing even the suite-wide test
    lock would race."""

    NEW_OPP = {"company_id": "acme", "title": "COO", "status": "backlog", "stage": "sourced",
               "verdict": "undecided", "jd_url": None,
               "location": {"type": "remote", "primary": "Remote"},
               # public #83 rule 1 — "board" is type job-board (URL-bearing); a fresh sighting
               # from it now needs source_url at capture time, unrelated to what these tests
               # are actually exercising.
               "sightings": [{"channel_id": "board", "seen_on": "2026-08-12",
                             "source_url": "https://board.example/acme-coo"}],
               "plan_id": "default-plan", "plan_assigned_on": "2026-08-12"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobsearch-test-writeapi-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        data = os.path.join(self.tmp, "data")
        os.makedirs(data)
        for f in ("config.json", "user.json"):
            shutil.copy(os.path.join(ROOT, f), os.path.join(self.tmp, f))
        rows = {
            "companies.jsonl": [{"id": "acme", "name": "Acme", "vertical": "other",
                                 "status": "watching"}],
            "channels.jsonl": [{"id": "board", "label": "Board", "type": "job-board",
                                "review_cadence": "weekly"}],
            "opportunities.jsonl": [dict(_SyntheticStore.BASE_OPP)],
            "messages.jsonl": [],
            "plans.jsonl": [dict(_SyntheticStore.BASE_PLAN)],
        }
        for name, recs in rows.items():
            with open(os.path.join(data, name), "w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
        self.lock = os.path.join(self.tmp, "test-lock.json")
        self.env = dict(os.environ, CLAUDESEARCH_ROOT=self.tmp, CLAUDESEARCH_DATA_DIR=data,
                        CLAUDESEARCH_LOCK_PATH=self.lock)
        self.new_opp = dict(self.NEW_OPP, next_action_owner=OWNER_TOKEN)

    def record(self, *argv):
        return subprocess.run([sys.executable, os.path.join(HERE, "record.py")] + list(argv),
                              capture_output=True, text=True, env=self.env, cwd=self.tmp)

    def runlock(self, *argv):
        return subprocess.run([sys.executable, os.path.join(HERE, "runlock.py")] + list(argv),
                              capture_output=True, text=True, env=self.env, cwd=self.tmp)

    def opp_rows(self):
        with open(os.path.join(self.tmp, "data", "opportunities.jsonl"),
                  encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]


def _synthetic_dashboard_profile(opp_rows, promote_applications=True, promote_touches=True):
    """A minimal, fully synthetic profile a dashboard/index/your_move subprocess can run
    against. Every identifier is invented at writing time — never drawn from a real profile.

    ⭐ ADR-031 B2 (2026-09-11): any nested `applications` a caller still sets on a row (the
    pre-B2 shape most callers here were written against) is promoted to the top-level
    `applications.jsonl` store instead by default — the same shim `_audit_profile` applies
    (and threads its own `promote_applications` through to here, so passing `False` there
    does not get silently overridden back to `True` at this layer) — pushed down here so a
    caller that builds a profile directly (bypassing `_audit_profile`) still gets a profile
    the current engine can actually read applications from. `promote_applications=False` is
    for the one legitimate exception: a test exercising a migration that expects the PRE-B2
    nested shape as its own input (e.g. `m_0_36_0_derive_from_applications`).

    ⭐ ADR-031 B3 (2026-09-13): the same move, one store wider — a nested `outreach` a caller
    still sets is promoted to the top-level `touches.jsonl` store, `id` minted `<person_id>-tN`
    per resolved person_id (record.py's own scheme), `opp_id` = the record it came from.
    `promote_touches=False` is for the one legitimate exception: a test exercising a migration
    that expects the PRE-B3 nested shape as its own input."""
    opp_rows = [dict(r) for r in opp_rows]
    # ADR-031 B4 — `plan_id` is required on every LIVE opportunity (design §17). Most callers
    # here were written before B4 and have no opinion about plans; default a bare, minimal,
    # play-less plan so their rows stay valid without every one of them having to know this
    # store exists. A test that explicitly wants a row with NO plan_id passes plan_id=None
    # itself and this leaves that alone (.setdefault never overrides an explicit key —
    # explicit None counts as "already has the key").
    for r in opp_rows:
        r.setdefault("plan_id", "default-plan")
        r.setdefault("plan_assigned_on", "2026-01-01")
    plan_rows = [{"id": "default-plan", "subject_kind": "search", "subject_id": "default",
                 "outcomes": ["role"], "goal": None, "approach": None, "cadence": None,
                 "status": "active", "play_id": None, "play_confirmed": None,
                 "resolves_when": None, "resolved_on": None, "resolution": None,
                 "targets": None, "note": None}]
    app_rows = []
    if promote_applications:
        for r in opp_rows:
            legacy = r.pop("applications", None)
            for i, a in enumerate(legacy or []):
                a = dict(a)
                aid = a.pop("app_id", None) or ("%s-a%d" % (r.get("id"), i + 1))
                a["id"] = aid
                a["opp_id"] = r.get("id")
                app_rows.append(a)
    touch_rows = []
    if promote_touches:
        _touch_counters = {}
        for r in opp_rows:
            legacy = r.pop("outreach", None)
            for t in (legacy or []):
                t = dict(t)
                t.pop("contact_id", None)
                pid = t.get("person_id") or "unknown"
                n = _touch_counters.get(pid, 0) + 1
                _touch_counters[pid] = n
                t.setdefault("id", "%s-t%d" % (pid, n))
                t["opp_id"] = r.get("id")
                touch_rows.append(t)
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"dashboard": {"title_template": "T"}}, fh)
    with open(os.path.join(d, "user.json"), "w", encoding="utf-8") as fh:
        json.dump({"identity": {"full_name": "Ada Q", "preferred_reference": "ada"}}, fh)
    os.makedirs(os.path.join(d, "data"))
    with open(os.path.join(d, "data", "opportunities.jsonl"), "w", encoding="utf-8") as fh:
        for r in opp_rows:
            fh.write(json.dumps(r) + "\n")
    with open(os.path.join(d, "data", "companies.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "c1", "name": "Northwind"}) + "\n")
    with open(os.path.join(d, "data", "applications.jsonl"), "w", encoding="utf-8") as fh:
        for a in app_rows:
            fh.write(json.dumps(a) + "\n")
    with open(os.path.join(d, "data", "touches.jsonl"), "w", encoding="utf-8") as fh:
        for t in touch_rows:
            fh.write(json.dumps(t) + "\n")
    with open(os.path.join(d, "data", "plans.jsonl"), "w", encoding="utf-8") as fh:
        for p in plan_rows:
            fh.write(json.dumps(p) + "\n")
    for extra in ("channels.jsonl", "messages.jsonl", "cover_letters.jsonl", "plays.jsonl"):
        open(os.path.join(d, "data", extra), "w").close()
    for md in ("focus.md", "drafts.md", "cover_letters.md", "network.md"):
        open(os.path.join(d, md), "w").close()
    return d


def _asks_profile(asks=(), commitments=(), opps=(), handoff=None):
    """A minimal synthetic profile for the asks/commitments surfaces."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"))
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"dashboard": {"title_template": "T"}}, fh)
    with open(os.path.join(d, "user.json"), "w", encoding="utf-8") as fh:
        json.dump({"identity": {"full_name": "Ada Q", "preferred_reference": "ada"}}, fh)
    for rel, recs in (("asks.jsonl", asks), ("commitments.jsonl", commitments),
                      ("opportunities.jsonl", opps), ("companies.jsonl",
                       [{"id": "c1", "name": "Northwind", "vertical": "other",
                         "status": "watching"}]),
                      ("channels.jsonl", ()), ("messages.jsonl", ())):
        with open(os.path.join(d, "data", rel), "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    for md in ("drafts.md", "cover_letters.md", "network.md"):
        open(os.path.join(d, md), "w").close()
    if handoff is not None:
        with open(os.path.join(d, "handoff.md"), "w", encoding="utf-8") as fh:
            fh.write(handoff)
    return d


def _trigger_profile():
    """A minimal synthetic profile for the trigger/sequence/form-answer surfaces
    (public #27). Every identifier synthesized."""
    d = tempfile.mkdtemp(prefix="jobsearch-test-triggers-")
    os.makedirs(os.path.join(d, "data"))
    opp = {"id": "veldmark-coo", "company_id": "veldmark", "title": "COO",
           "status": "active-pursuit", "stage": "contacted", "verdict": "pursue",
           "jd_url": "https://example.test/jobs/9",
           "location": {"type": "remote"}, "next_action_owner": "me",
           "sightings": [{"channel_id": "boardlike", "seen_on": "2026-08-18"}],
           "plan_id": "default-plan", "plan_assigned_on": "2026-08-18"}
    opp2 = {"id": "quorlane-cpo", "company_id": "quorlane", "title": "CPO",
            "status": "active-pursuit", "stage": "contacted", "verdict": "pursue",
            "jd_url": None,
            "location": {"type": "remote"}, "next_action_owner": "me",
            "sightings": [{"channel_id": "boardlike", "seen_on": "2026-08-17"}],
            "plan_id": "default-plan", "plan_assigned_on": "2026-08-17"}
    with open(os.path.join(d, "data", "opportunities.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(opp) + "\n" + json.dumps(opp2) + "\n")
    # ADR-031 B2 — the two applications are now top-level `applications` store rows (`id`
    # was `app_id`, unchanged value), never nested on the opportunity record.
    with open(os.path.join(d, "data", "applications.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "veldmark-coo-a1", "opp_id": "veldmark-coo",
                             "date": "2026-08-20", "method": "company-ats",
                             "status": "submitted"}) + "\n")
        fh.write(json.dumps({"id": "quorlane-cpo-a1", "opp_id": "quorlane-cpo",
                             "date": "2026-08-19", "method": "email",
                             "status": "submitted"}) + "\n")
    open(os.path.join(d, "data", "cover_letters.jsonl"), "w").close()
    # ADR-031 B3 — the touch is a top-level `touches` store row now (`id` minted
    # `<person_id>-tN`), never nested on the opportunity record.
    with open(os.path.join(d, "data", "touches.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "sable-quennet-t1", "opp_id": "veldmark-coo",
                             "channel_id": None, "object_person_id": None,
                             "object_company_id": None,
                             "date": "2026-08-21", "medium": "linkedin-connection-note",
                             "status": "sent", "to": "sable", "person_id": "sable-quennet",
                             "touch_type": "first-touch", "recipient_role": "recruiter-agency",
                             "delivery": "delivered", "outcome": "awaiting",
                             "address_status": "unknown", "responded_on": None,
                             "message_ref": None, "campaign_id": None, "variant": None,
                             "note": None,
                             "trigger_kind": "application", "trigger_ref": "veldmark-coo-a1",
                             "sequence_id": "veldmark-recruiter", "sequence_step": 1}) + "\n")
    with open(os.path.join(d, "data", "companies.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "veldmark", "name": "Veldmark", "vertical": "other",
                             "status": "active-target"}) + "\n")
        fh.write(json.dumps({"id": "quorlane", "name": "Quorlane", "vertical": "other",
                             "status": "active-target"}) + "\n")
    with open(os.path.join(d, "data", "channels.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "boardlike", "label": "Boardlike",
                             "type": "job-board",
                             "review_cadence": "weekly"}) + "\n")
    for rel in ("messages.jsonl", "asks.jsonl"):
        open(os.path.join(d, "data", rel), "w").close()
    # ADR-031 B1 — "sable-quennet" is now a `people` row plus one `involvements` row, promoted
    # from what was `veldmark-coo.contacts[0]`.
    with open(os.path.join(d, "data", "people.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "sable-quennet", "name": "Sable Quennet",
                             "status": "active"}) + "\n")
    with open(os.path.join(d, "data", "involvements.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"person_id": "sable-quennet", "opp_id": "veldmark-coo",
                             "channel_id": None}) + "\n")
    # ADR-031 B4 — every live opportunity is governed by a plan (design §17); a play-less
    # plan, so this fixture stays valid without any opinion about plays.
    with open(os.path.join(d, "data", "plans.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "default-plan", "subject_kind": "search",
                             "subject_id": "default", "outcomes": ["role"], "goal": None,
                             "approach": None, "cadence": None, "status": "active",
                             "play_id": None, "play_confirmed": None, "resolves_when": None,
                             "resolved_on": None, "resolution": None, "targets": None,
                             "note": None}) + "\n")
    open(os.path.join(d, "data", "plays.jsonl"), "w").close()
    with open(os.path.join(d, "user.json"), "w", encoding="utf-8") as fh:
        json.dump({"identity": {"full_name": "Fixture Person",
                                "preferred_reference": "me-fixture"}}, fh)
    # Query or Citation C1 — the recipient/brief gate runs before `**Blocked until:**`, so
    # this entry (whose `state` several tests read back through `trigger.py`) needs a
    # resolvable `**To:**` AND a CURRENT brief; the join it actually tests is
    # `**Blocked until:**` itself, which bypasses the register check once addressed
    # (brief.verdict()'s own rule) — `_restamp_trigger_profile()` re-stamps the brief after a
    # test mutates the underlying outreach row, the same `--rebrief` a real session would run.
    with open(os.path.join(d, "drafts.md"), "w", encoding="utf-8") as fh:
        fh.write("# Drafts\n\n"
                 "## Relationship ask — Halloway Partners\n"
                 "%s\n"
                 "**Medium:** email\n"
                 "**Triggered by:** opp:veldmark-coo app:veldmark-coo-a1\n"
                 "**Sequence:** veldmark-recruiter step:2\n"
                 "**Blocked until:** contact:sable-quennet outcome:accepted|replied\n\n"
                 "> Do you hold a relationship with them?\n"
                 % _stamp_brief(d, "sable-quennet", opp_id="veldmark-coo"))
    open(os.path.join(d, "cover_letters.md"), "w").close()
    return d


def _audit_profile(opps=(), asks=(), commitments=(), messages=(), channels=(), preps=None,
                   drafts=None, people=(), involvements=(), promote_applications=True,
                   promote_touches=True):
    """A synthetic profile for the build's end-to-end tests. Preps go to the canonical
    conversations/ directory; drafts.md to the legacy root (both resolve through _tree).
    `people`/`involvements` — ADR-031 B1 — default to empty; a caller whose opportunities or
    messages reference a `person_id` must supply the matching rows itself, the same way it
    already supplies `opps`/`messages`.

    ⭐ ADR-031 B2 (2026-09-11): `applications` is a top-level store now, not a nested array —
    but many existing callers still build their opportunities via `_live_role(...,
    applications=[...])`, the pre-B2 shape. `promote_applications=True` (the default) strips
    any nested `applications` off each opportunity here and writes it to `applications.jsonl`
    instead (id = the row's own `app_id` if it names one, else minted `<opp_id>-aN`) — so most
    existing test bodies keep working unchanged against the NEW store. Pass
    `promote_applications=False` for the one legitimate exception: a test exercising a
    migration that itself expects the PRE-B2 nested shape as its input (e.g.
    `m_0_36_0_derive_from_applications`, which always runs before B2's own promotion in the
    migration chain).

    ⭐ ADR-031 B3 (2026-09-13): the same move, one store wider — `promote_touches=True` (the
    default) strips any nested `outreach` off each opportunity and writes it to
    `touches.jsonl` instead (id minted `<person_id>-tN`, `opp_id` = the record it came from).
    `promote_touches=False` for a migration test that expects the PRE-B3 nested shape."""
    opps = [dict(o) for o in opps]
    app_rows = []
    if promote_applications:
        for o in opps:
            legacy = o.pop("applications", None)
            for i, a in enumerate(legacy or []):
                a = dict(a)
                aid = a.pop("app_id", None) or ("%s-a%d" % (o.get("id"), i + 1))
                a["id"] = aid
                a["opp_id"] = o.get("id")
                app_rows.append(a)
    touch_rows = []
    if promote_touches:
        _touch_counters = {}
        for o in opps:
            legacy = o.pop("outreach", None)
            for t in (legacy or []):
                t = dict(t)
                t.pop("contact_id", None)
                pid = t.get("person_id") or "unknown"
                n = _touch_counters.get(pid, 0) + 1
                _touch_counters[pid] = n
                t.setdefault("id", "%s-t%d" % (pid, n))
                t["opp_id"] = o.get("id")
                touch_rows.append(t)
    d = _synthetic_dashboard_profile(opps, promote_applications=promote_applications,
                                     promote_touches=promote_touches)
    # Validation-complete stores, so a test may assert validate_data CLEAN: the company
    # carries vertical/status, and one job-board channel exists for sightings to resolve.
    channels = list(channels) + [{"id": "ch-board", "label": "Board", "type": "job-board",
                                  "review_cadence": "weekly", "access": "public"}]
    with open(os.path.join(d, "data", "companies.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "c1", "name": "Northwind", "vertical": "other",
                             "status": "watching"}) + "\n")
    for rel, recs in (("asks.jsonl", asks), ("commitments.jsonl", commitments),
                      ("messages.jsonl", messages), ("channels.jsonl", channels),
                      ("people.jsonl", people), ("involvements.jsonl", involvements),
                      ("applications.jsonl", app_rows), ("cover_letters.jsonl", ()),
                      ("touches.jsonl", touch_rows)):
        with open(os.path.join(d, "data", rel), "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    if preps:
        os.makedirs(os.path.join(d, "conversations"), exist_ok=True)
        for name, body in preps.items():
            with open(os.path.join(d, "conversations", name), "w", encoding="utf-8") as fh:
                fh.write(body)
    if drafts is not None:
        with open(os.path.join(d, "drafts.md"), "w", encoding="utf-8") as fh:
            fh.write(drafts)
    return d


def _audit_run(script, prof, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, script)] + list(args),
                          capture_output=True, text=True, cwd=prof,
                          env=dict(os.environ, CLAUDESEARCH_ROOT=prof,
                                   CLAUDESEARCH_DATA_DIR=os.path.join(prof, "data")))


def _audit_page(prof):
    with open(os.path.join(prof, "views", "dashboard_artifact.html"), encoding="utf-8") as fh:
        return fh.read()


def _audit_ledger(prof):
    with open(os.path.join(prof, "views", "dashboard_coverage.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _live_role(rid, title, **kw):
    r = {"id": rid, "company_id": "c1", "title": title, "status": "active-pursuit",
         "stage": "contacted", "verdict": "pursue", "jd_url": None,
         "next_action_owner": "me", "location": {"type": "remote", "primary": "Anywhere"},
         "sightings": [{"channel_id": "ch-board", "seen_on": "2026-01-01"}]}
    r.update(kw)
    return r


@contextlib.contextmanager
def _root_env(prof):
    """Query or Citation C1 — `mail_client.configured_accounts()` (and therefore
    `brief.py`'s email evidence) resolves the profile AMBIENTLY, via `_root.profile_root()` /
    `$CLAUDESEARCH_ROOT` — the one-profile-per-process convention this engine's modules all
    follow for a real run, never a `root` function argument. A subprocess (`_audit_run`) gets
    this for free; an IN-PROCESS call against an arbitrary temp profile (`precondition.report()`,
    `your_move.ready_staged_without_ask()`, `brief.compute()`, …) needs the same override or it
    reads whichever profile this TEST PROCESS happens to be ambiently pointed at instead —
    harmless (always the tracked fixture or a temp dir, never a real one) but wrong for the
    profile actually in hand. Restored unconditionally, even on an exception."""
    old = os.environ.get("CLAUDESEARCH_ROOT")
    os.environ["CLAUDESEARCH_ROOT"] = prof
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("CLAUDESEARCH_ROOT", None)
        else:
            os.environ["CLAUDESEARCH_ROOT"] = old


def _stamp_brief(prof, person_id, opp_id=None, channel_id=None, person_name=None,
                 confirmed_empty=True):
    """Query or Citation C1 test helper. `**To:**`/`**Brief:**` gate EVERY entry in
    `outreach/drafts.md` now (design-query-or-citation.md §3.4/§3.5) — a pre-C1 fixture that
    exercises `**Blocked until:**` (or a plain sendable body) needs a resolvable recipient and
    a CURRENT, non-stale brief citing it before it ever reaches that older logic. This:

      1. ensures `person_id` resolves in `people.jsonl` (appending a minimal row if absent);
      2. when `confirmed_empty` (the default — most fixtures have no real conversation data
         and are not testing cold-outreach evidence at all), configures one mailbox account
         and writes an `empty` probe row for this person, so a `nothing-sent` axis resolves to
         register `cold` (sendable-track) rather than `unverified-cold` (WAITS_ON_SURFACE) —
         the honest way to reach a pre-C1 test's own intended state, never by weakening the
         gate itself (a genuinely unverified cold draft is EXACTLY what §5.1 holds);
      3. stamps a ledger row via `brief.compute()`'s own fresh computation, so
         `brief.is_stale()` sees a row identical to what a fresh read produces right now.

    Returns the two-line block a test splices into its draft body:

        **To:** contact:<person_id>
        **Brief:** <the row's id>
    """
    import brief as _brief
    import journal as _journal
    people_path = os.path.join(prof, "data", "people.jsonl")
    existing_ids = set()
    if os.path.exists(people_path):
        with open(people_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    existing_ids.add(json.loads(line).get("id"))
    if person_id not in existing_ids:
        with open(people_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": person_id,
                                 "name": person_name or person_id.replace("-", " ").title(),
                                 "status": "active"}) + "\n")
    if confirmed_empty:
        user_path = os.path.join(prof, "user.json")
        try:
            with open(user_path, encoding="utf-8") as fh:
                user = json.load(fh)
        except (OSError, ValueError):
            user = {}
        if not user.get("mailboxes"):
            user["mailboxes"] = [{"address": "probe@example.com"}]
            with open(user_path, "w", encoding="utf-8") as fh:
                json.dump(user, fh)
        thread = "contact:%s" % person_id
        _journal.record_probe(prof, thread, thread, "empty", medium="email",
                              mailbox="probe@example.com")
        # A draft's own `**Medium:**` line (not the person's history) selects which evidence
        # `register_for()` checks for a `nothing-sent` axis (brief.py's own §3.7 rule) — a
        # fixture whose entry is medium=linkedin-* needs LinkedIn evidence too, since most
        # fixtures using this helper are not testing cold-outreach evidence at all.
        _journal.record_probe(prof, thread, thread, "empty", medium="linkedin")
    with _root_env(prof):
        b = _brief.compute(prof, person_id, opp_id, channel_id)
    brief_id = _brief.new_brief_id()
    row = dict(b)
    row["id"] = brief_id
    row["computed_at"] = brief_id.split("brief:", 1)[1].rsplit("-", 1)[0]
    del row["events"]
    _brief.append_ledger(prof, row)
    return "**To:** contact:%s\n**Brief:** %s" % (person_id, brief_id)


def _raw(path):
    """The file's bytes — byte-identity is how 'wrote nothing' is asserted below."""
    with open(path, "rb") as fh:
        return fh.read()


def _c1_profile(opportunities=(), people=(), involvements=(), messages=(), asks=(),
               mailboxes=("acct-a@example.com",)):
    # ADR-031 B3 — `graph.Graph` (which `conversation_axis()`/`opportunity_conversation_axis()`
    # use) reads `touches.jsonl` directly off disk; a nested `outreach` key on an opportunity
    # dict here is never read by anything any more. Promote it to the top-level store the
    # same way `_synthetic_dashboard_profile`/`_audit_profile` do, so every `_c1_opp(...,
    # outreach=[...])` caller keeps working unchanged against the NEW store.
    opportunities = [dict(o) for o in opportunities]
    touch_rows = []
    _touch_counters = {}
    for o in opportunities:
        legacy = o.pop("outreach", None)
        for t in (legacy or []):
            t = dict(t)
            pid = t.get("person_id") or "unknown"
            n = _touch_counters.get(pid, 0) + 1
            _touch_counters[pid] = n
            t.setdefault("id", "%s-t%d" % (pid, n))
            t["opp_id"] = o.get("id")
            t.setdefault("object_person_id", None)
            t.setdefault("object_company_id", None)
            t.setdefault("campaign_id", None)
            t.setdefault("sequence_id", None)
            t.setdefault("sequence_step", None)
            t.setdefault("trigger_kind", None)
            t.setdefault("trigger_ref", None)
            touch_rows.append(t)
    d = tempfile.mkdtemp(prefix="jobsearch-test-c1-")
    os.makedirs(os.path.join(d, "data"))
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
        json.dump({}, fh)
    with open(os.path.join(d, "user.json"), "w", encoding="utf-8") as fh:
        json.dump({"identity": {"full_name": "Fixture Person", "preferred_reference": "me-fixture"},
                   "mailboxes": [{"address": a} for a in mailboxes]}, fh)
    stores = {"opportunities.jsonl": opportunities, "people.jsonl": people,
             "involvements.jsonl": involvements, "messages.jsonl": messages,
             "asks.jsonl": asks, "commitments.jsonl": (), "channels.jsonl": (),
             "companies.jsonl": (), "resume_variants.jsonl": (), "applications.jsonl": (),
             "cover_letters.jsonl": (), "touches.jsonl": touch_rows, "briefs.jsonl": (),
             "runs.jsonl": (), "inbox.jsonl": (), "pending_actions.jsonl": ()}
    for name, rows in stores.items():
        with open(os.path.join(d, "data", name), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    return d


def _c1_person(pid, name=None, email=None):
    return {"id": pid, "name": name or pid.replace("-", " ").title(), "email": email,
           "email_status": None, "linkedin": None, "company_id": None, "title": None,
           "cadence": None, "status": "active", "merged_into": None, "not_same_as": [],
           "created": None, "note": None}


def _c1_involvement(pid, opp_id=None, channel_id=None):
    return {"person_id": pid, "opp_id": opp_id, "channel_id": channel_id,
           "path_type": "recruiter", "role": "Recruiter", "status": "contacted", "note": None}


def _c1_touch(pid, date, outcome="awaiting", responded_on=None, medium="email-cold",
             delivery="delivered", message_ref=None):
    return {"to": pid, "person_id": pid, "channel_id": None, "status": "sent", "date": date,
           "medium": medium, "touch_type": "first-touch", "recipient_role": "hiring-manager",
           "address_status": "verified-published", "delivery": delivery, "outcome": outcome,
           "responded_on": responded_on, "message_ref": message_ref, "variant": None,
           "note": "fixture"}


def _c1_opp(oid, outreach=()):
    return {"id": oid, "company_id": None, "title": "Fixture Role", "status": "active-pursuit",
           "stage": "contacted", "outreach": list(outreach)}


import guard_outbound_click


def _pane_test_profile():
    """A throwaway profile for pane-lock/journal correlation tests. Both `CLAUDESEARCH_ROOT`
    and `CLAUDESEARCH_PANE_LOCK_PATH` point inside it (see `_pane_env`), so a --take/--stalled/
    --release call here can never reach a real `.git` anywhere, including this checkout's own."""
    d = tempfile.mkdtemp(prefix="jobsearch-test-pane-")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    return d


def _pane_env(d):
    return dict(os.environ, CLAUDESEARCH_ROOT=d,
               CLAUDESEARCH_PANE_LOCK_PATH=os.path.join(d, "pane_lock.json"))


def _runlock_pane(d, *argv):
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "runlock.py"), "--resource", "pane"] + list(argv),
        capture_output=True, text=True, env=_pane_env(d))


def _journal(d, *argv):
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "journal.py")] + list(argv),
        capture_output=True, text=True, env=_pane_env(d))


class _VariantOutFixture(unittest.TestCase):
    """Shared scaffolding for the variant-renderer (#64) test classes below. No test_ methods
    of its own — collected as an empty suite, same pattern `_SyntheticCoverage` uses. Every
    profile is a disposable tempfile.mkdtemp() tree; every identifier is synthesized."""

    IDENTITY = {"full_name": "Rowan Ibarra", "phone": "555-0142",
               "primary_email": "rowan.ibarra@example.com"}

    # public #59/ADR-027 shape: a public claim, its private original nested beneath it (the
    # twin pairing is PARENT public / CHILD private — resume_variants.union_claim_tags()'s own
    # rule), plus one addenda-only claim with no public twin at all.
    CLAIMS = (
        "# Claims\n\n"
        "- [public] Cut deployment time by half through a rebuilt pipeline\n"
        "- [public] Rebuilt the onboarding flow end to end\n\n"
        "## Additional Detail — private\n\n"
        "- [public] Ran a vendor security review and closed the finding\n"
        "  - [private] Ran a vendor security review that found a real gap\n")

    def setUp(self):
        sys.path.insert(0, HERE)
        import resume_variants
        import variant_out
        self.rv = resume_variants
        self.vo = variant_out
        self.tmp = tempfile.mkdtemp(prefix="variant-out-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # variant_out.py (and resume_variants.py, profile.py underneath it) resolve the
        # profile through profile_root(), which reads this env var directly — every call in
        # this class is IN-PROCESS, never a subprocess, so the var must be set here rather
        # than passed as a subprocess env (contrast TestResumeVariants's _run_cli()).
        old_root = os.environ.get("CLAUDESEARCH_ROOT")
        os.environ["CLAUDESEARCH_ROOT"] = self.tmp

        def _restore_root():
            if old_root is None:
                os.environ.pop("CLAUDESEARCH_ROOT", None)
            else:
                os.environ["CLAUDESEARCH_ROOT"] = old_root
        self.addCleanup(_restore_root)

        # ⚠️ profile.py resolves its own ROOT/USER_PATH/CONFIG_PATH ONCE, at import time
        # (`_profile_or_fixture()`), never per-call — an env var set after another test has
        # already imported `profile` has no effect on it. `variant_out.py`'s identity lookup
        # (`prof.user()`) goes through this same cached module, so these three attributes are
        # patched directly for the duration of each test in this class and restored after.
        import profile as _profile_mod
        self._old_profile_paths = (_profile_mod.ROOT, _profile_mod.USER_PATH,
                                   _profile_mod.CONFIG_PATH)
        _profile_mod.ROOT = self.tmp
        _profile_mod.USER_PATH = os.path.join(self.tmp, "user.json")
        _profile_mod.CONFIG_PATH = os.path.join(self.tmp, "config.json")

        def _restore_profile_paths():
            _profile_mod.ROOT, _profile_mod.USER_PATH, _profile_mod.CONFIG_PATH = \
                self._old_profile_paths
        self.addCleanup(_restore_profile_paths)

        os.makedirs(os.path.join(self.tmp, "data"))
        os.makedirs(os.path.join(self.tmp, "presence"))
        self._write("user.json", json.dumps({"identity": dict(self.IDENTITY), "mailboxes": []}))
        self._write("config.json", json.dumps({}))
        self._write("presence/claims.md", self.CLAIMS)

    def _write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _union_sha(self):
        with open(os.path.join(self.tmp, "presence", "claims.md"), encoding="utf-8") as fh:
            return self.rv.union_hash(fh.read())

    def _write_store(self, rows):
        with open(os.path.join(self.tmp, "data", "resume_variants.jsonl"), "w",
                  encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def _declare(self, body_md, surface="print", vid="v1"):
        sha = self._union_sha()
        self._write("variant.md", body_md)
        self._write_store([{"id": vid, "archetype": "exec", "file": "variant.md",
                            "status": "active", "surface": surface, "union_sha": sha,
                            "union_reconciled_on": "2026-09-01"}])
        return vid

    def _set_identity(self, **overrides):
        ident = dict(self.IDENTITY)
        ident.update(overrides)
        self._write("user.json", json.dumps({"identity": ident, "mailboxes": []}))

    def _set_config(self, cfg):
        self._write("config.json", json.dumps(cfg))

    def _snapshot(self):
        h = {}
        for dirpath, _dirs, files in os.walk(self.tmp):
            for f in files:
                p = os.path.join(dirpath, f)
                with open(p, "rb") as fh:
                    h[p] = fh.read()
        return h

    def _rendered_path(self, vid="v1"):
        return os.path.join(self.tmp, "resumes", self.vo._filename(vid))


def _ats_fixture_profile(tmp, receipt_domains=("example.com",),
                         status_phrases=None):
    """A disposable copy of the tracked fixture, with `ats.receipt_sender_domains` and
    `ats.status_phrases` set — the tracked fixture deliberately has NO status_phrases (design
    §5's own Fixture note: 'the fixture proves the old name never migrated'), so every test
    that needs the sweep to actually classify anything builds its own config, never hand-edits
    the fixture."""
    shutil.copytree(_FIXTURE, tmp, dirs_exist_ok=True)
    with open(os.path.join(tmp, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["ats"]["receipt_sender_domains"] = list(receipt_domains)
    cfg["ats"]["status_phrases"] = status_phrases or {
        "acknowledged": ["we have received your application"],
        "rejected": ["we have decided not to move forward"],
        "advanced": ["schedule a call"],
    }
    with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return tmp


class _FakeAtsMailbox(object):
    """A `Mailbox` stand-in keyed by account -> {uid: (headers_dict, body_text)}. Raises
    `CredentialError` for an account named in `FAIL_ACCOUNTS`, mirroring a revoked app
    password — the same shape `_fake_mailbox` in `TestSweepAccountsWiredIntoTheFourCallers`
    already establishes for the other four sweep callers, extended here with real
    header/body content since this sweep actually reads the mail."""
    STORE = {}
    FAIL_ACCOUNTS = frozenset()
    _CredentialError = None

    def __init__(self, account):
        self.account = account
        if account in self.FAIL_ACCOUNTS:
            raise self._CredentialError("stub: app password revoked for %s" % account)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def search(self, query):
        return list(self.STORE.get(self.account, {}).keys())

    def _msg(self, uid, with_body):
        import email.message
        headers, body = self.STORE[self.account][uid]
        m = email.message.EmailMessage()
        for k, v in headers.items():
            m[k] = v
        if with_body:
            m.set_content(body)
        return m

    def fetch_headers(self, uid):
        return self._msg(uid, with_body=False)

    def fetch_full(self, uid):
        return self._msg(uid, with_body=True)


class _AtsSweepProfile(unittest.TestCase):
    """Shared scaffolding: a disposable ATS-configured fixture, `reconcile`'s module-level
    `ROOT`/`DATA`/`Mailbox`/`configured_accounts` patched for in-process calls (the same
    `_patch()`-by-hand convention `TestSweepAccountsWiredIntoTheFourCallers` establishes),
    and every env var a `record.py` subprocess call needs to land on THIS profile rather than
    a stale one (dev #259/#278's own caution, applied to a test harness this time)."""

    ACCOUNT = "acct-a@example.com"

    def setUp(self):
        sys.path.insert(0, HERE)
        import reconcile
        import mail_client
        import journal
        self.rc = reconcile
        self.mc = mail_client
        self.J = journal
        self.tmp = tempfile.mkdtemp(prefix="ats-sweep-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _ats_fixture_profile(self.tmp)
        self._env_saved = {k: os.environ.get(k) for k in
                           ("CLAUDESEARCH_ROOT", "CLAUDESEARCH_DATA_DIR",
                            "CLAUDESEARCH_LOCK_PATH")}
        os.environ["CLAUDESEARCH_ROOT"] = self.tmp
        os.environ["CLAUDESEARCH_DATA_DIR"] = os.path.join(self.tmp, "data")
        os.environ["CLAUDESEARCH_LOCK_PATH"] = os.path.join(self.tmp, ".lock")
        self.addCleanup(self._restore_env)
        self._patch(self.rc, ROOT=self.tmp, DATA=os.path.join(self.tmp, "data"))
        self.fake_mailbox = type("FakeMailbox", (_FakeAtsMailbox,),
                                 {"STORE": {}, "FAIL_ACCOUNTS": frozenset(),
                                  "_CredentialError": self.mc.CredentialError})
        self._patch(self.rc, Mailbox=self.fake_mailbox,
                   configured_accounts=lambda: [self.ACCOUNT])

    def _restore_env(self):
        for k, v in self._env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _patch(self, mod, **attrs):
        saved = {k: getattr(mod, k) for k in attrs}
        for k, v in attrs.items():
            setattr(mod, k, v)
        self.addCleanup(lambda: [setattr(mod, k, v) for k, v in saved.items()])

    def _mail(self, uid, headers, body, account=None):
        self.fake_mailbox.STORE.setdefault(account or self.ACCOUNT, {})[uid] = (headers, body)

    def _apps(self):
        with open(os.path.join(self.tmp, "data", "applications.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def _set_app(self, app_id, **fields):
        rows = self._apps()
        for r in rows:
            if r["id"] == app_id:
                r.update(fields)
        with open(os.path.join(self.tmp, "data", "applications.jsonl"), "w",
                 encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def _add_app(self, row):
        rows = self._apps()
        rows.append(row)
        with open(os.path.join(self.tmp, "data", "applications.jsonl"), "w",
                 encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def _messages(self):
        with open(os.path.join(self.tmp, "data", "messages.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def _asks(self):
        with open(os.path.join(self.tmp, "data", "asks.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def _bytes(self, *names):
        out = {}
        for n in names:
            with open(os.path.join(self.tmp, "data", n), "rb") as fh:
                out[n] = fh.read()
        return out

    def _seed_swept(self, account=None, by="reconcile-ats"):
        """A prior REAL sweep row, so `is_first_run_for_mailbox` reads False — isolates a
        test from the first-run/historical carve-out (design §5) when it wants to exercise
        the ordinary apply/propose/ask path instead."""
        self.J.record_swept(self.tmp, account or self.ACCOUNT, "2020-01-01T00:00:00",
                            "2020-01-02T00:00:00", by, True, at="2020-01-02T00:00:01")

    def _ats(self, already_locked=False, days=0, as_of=None):
        import argparse
        return self.rc.cmd_ats(argparse.Namespace(already_locked=already_locked, days=days,
                                                   as_of=as_of))

    def _verify(self, days=30):
        import argparse
        return self.rc.cmd_verify(argparse.Namespace(days=days))


def _write_cascade_profile(tmp, **stores):
    """Write only the jsonl stores a test actually needs, in a from-scratch tmp profile —
    TestSilentApplicationClass._write's own convention, generalised to every store this
    block's tests touch. A store not passed is simply never written; every reader exercised
    here already treats an absent file as EMPTY, never broken (applications.py/touches.py's
    own `_load_jsonl` docstrings)."""
    data = os.path.join(tmp, "data")
    os.makedirs(data, exist_ok=True)
    for name, rows in stores.items():
        with open(os.path.join(data, "%s.jsonl" % name), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")


def _rs_git(d, *args):
    return subprocess.run(["git", "-C", d] + list(args),
                          capture_output=True, text=True, timeout=15)


def _rs_profile():
    """A real, minimal, synthetic profile: a git repo with `data/runs.jsonl` and
    `data/inbox.jsonl` TRACKED (empty) from the first commit, so a later journal append shows
    up as a real `git diff --stat` hit rather than an untracked file `diff --stat` cannot see —
    exactly how a real profile's own `data/` is tracked."""
    d = tempfile.mkdtemp(prefix="jobsearch-test-runsummary-")
    os.makedirs(os.path.join(d, "data"))
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
        json.dump({}, fh)
    with open(os.path.join(d, "user.json"), "w", encoding="utf-8") as fh:
        json.dump({"identity": {"full_name": "Fixture Person",
                                "preferred_reference": "me-fixture"}}, fh)
    for name in ("runs.jsonl", "inbox.jsonl"):
        open(os.path.join(d, "data", name), "w", encoding="utf-8").close()
    _rs_git(d, "init", "-q")
    _rs_git(d, "add", "-A")
    _rs_git(d, "-c", "user.name=t", "-c", "user.email=t@t",
           "commit", "-q", "-m", "baseline")
    return d


def _rs_journal(*args, root):
    env = dict(os.environ, CLAUDESEARCH_ROOT=root)
    return subprocess.run([sys.executable, os.path.join(HERE, "journal.py")] + list(args),
                          capture_output=True, text=True, timeout=20, env=env)


class _B5Profile(unittest.TestCase):
    """A throwaway copy of the tracked fixture profile, plus the helpers both B5 classes share."""

    def _profile(self):
        d = tempfile.mkdtemp(prefix="jobsearch-test-b5-")
        self.addCleanup(shutil.rmtree, d, True)
        shutil.rmtree(d)
        shutil.copytree(_FIXTURE, d)
        return d

    def _env(self, d):
        return dict(os.environ, CLAUDESEARCH_ROOT=d, CLAUDESEARCH_DATA_DIR=os.path.join(d, "data"))

    def _run(self, d, script, *args):
        return subprocess.run([sys.executable, "-B", os.path.join(HERE, script)] + list(args),
                              capture_output=True, text=True, cwd=d, env=self._env(d))

    @staticmethod
    def _rows(path):
        return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

    @staticmethod
    def _write_rows(path, rows):
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")


def scratch_profile(testcase=None):
    """dev #444 — a throwaway copy of the tracked `tests/fixtures/profile` fixture, made
    under `tempfile`, never the tracked tree itself. A serial suite run leaves the tracked
    fixture clean even when a test writes into it in place and restores byte-identically
    after — the whole point of that issue — because nothing ever diffs the MIDDLE of a run.
    Any test that used to point CLAUDESEARCH_ROOT (or a bare `cwd=`) at `_FIXTURE`/`ROOT`
    directly and then exercised a writer (`journal.py`, `migrate.py`, `record.py`,
    `_atomic`/`os.replace` writes, ...) copies here first instead.

    Registers cleanup on `testcase` (anything with unittest's `addCleanup`) when given;
    otherwise the caller owns `shutil.rmtree(path, ignore_errors=True)` itself. Returns the
    copy's root — callers set `CLAUDESEARCH_ROOT`/`CLAUDESEARCH_DATA_DIR` themselves (see
    `scratch_env()` below), matching every other scratch-profile helper in this file
    (`_B5Profile._profile`, `_ats_fixture_profile`, `_c1_profile`, ...) rather than mutating
    process-wide `os.environ` for an in-process call that may not want that."""
    d = tempfile.mkdtemp(prefix="jobsearch-test-scratch-")
    shutil.rmtree(d)
    shutil.copytree(_FIXTURE, d)
    if testcase is not None:
        testcase.addCleanup(shutil.rmtree, d, True)
    return d


def scratch_env(root, **extra):
    """The env dict a subprocess needs to actually land on `root` (a `scratch_profile()`
    copy) rather than the tracked fixture `_common.py` already points process-wide
    `CLAUDESEARCH_ROOT` at when `USING_FIXTURE` — dev #444. `profile_root()`'s own resolution
    order (`_root.py`) checks `CLAUDESEARCH_ROOT` before it ever looks at `cwd`, so passing
    `cwd=root` alone to `subprocess.run` is not enough; every writer test migrated for
    dev #444 uses this (or the equivalent inline dict) instead of `env=os.environ`."""
    env = dict(os.environ, CLAUDESEARCH_ROOT=root,
              CLAUDESEARCH_DATA_DIR=os.path.join(root, "data"))
    env.update(extra)
    return env


def scratch_fixture_tree(testcase=None):
    """dev #444 — a throwaway copy of the WHOLE tracked `tests/fixtures/` tree (every case
    `make_fixture.CASES` can produce — `base` plus every frozen `migrations/pre-*` snapshot —
    not just the one a test cares about), laid out the same way under the copy as it is under
    `ENGINE` (`<copy>/tests/fixtures/...`). `check_fixture_generated.py` always scans every
    case in one run, so a test exercising its hand-edit detection against a scratch copy needs
    every case present, not only the one it plants a defect into, or every OTHER case reads
    back as an empty store and fails on an unrelated mismatch.

    Pass the returned root as `CLAUDESEARCH_FIXTURE_ENGINE_ROOT` (`make_fixture.
    case_output_dir()`'s own override, same dev #444) to redirect a `check_fixture_generated.py`
    subprocess here instead of the tracked tree."""
    d = tempfile.mkdtemp(prefix="jobsearch-test-fixture-tree-")
    shutil.rmtree(d)
    shutil.copytree(os.path.join(ENGINE, "tests", "fixtures"),
                    os.path.join(d, "tests", "fixtures"))
    if testcase is not None:
        testcase.addCleanup(shutil.rmtree, d, True)
    return d


def _fixture_roots():
    """Every tracked fixture tree dev #444's tripwire protects — the live `base` profile plus
    every frozen migration snapshot, all of it under one directory so a stray NEW file
    anywhere in it (dev #313's own incident shape) is caught the same way a changed one is."""
    return [os.path.join(ENGINE, "tests", "fixtures")]


def _fixture_snapshot():
    """sha256 of every file under `_fixture_roots()` — dev #444's tripwire baseline, taken
    before and after the run so an end-state drift is reported even if something bypassed the
    read-only window below (e.g. running as root, which ignores file-mode bits)."""
    out = {}
    for root in _fixture_roots():
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                with open(p, "rb") as fh:
                    out[p] = hashlib.sha256(fh.read()).hexdigest()
    return out


def force_tree_writable(path):
    """dev #507 — force the owner-write bit back on for `path` and everything under it.

    A scratch COPY of the tracked fixture must never silently inherit an unwritable SOURCE.
    `shutil.copytree`'s default `copy_function` propagates the source's own permission bits
    onto the destination (`shutil.copystat`) — so if the tracked fixture was ever left
    write-stripped on disk (a crashed run inside `_fixture_locked_for_run()` below: a SIGKILL
    or a dispatch hitting its cap mid-`with` skips the `finally` restore, same as any other
    process kill — no `finally`, no `atexit`, and no signal handler catches SIGKILL), every
    ONE OF THE DOZENS of legitimate `shutil.copytree(_FIXTURE, scratch)` call sites elsewhere
    in this suite would silently produce an unwritable scratch copy too. `TestPurityHookStep`
    and `TestPurityHookDecisionResolution` (`test_check_engine_purity.py`) hit this concretely:
    `check_engine_purity.hook_step()`'s own persistent-state probe
    (`os.makedirs(state_dir); open(probe, "w")`) then fails with a bare `OSError`, which
    `hook_step()` reads as `no-persistent-state` — a real, structural decline — rather than as
    what it actually is: a POISONED LOCAL WORKING TREE, unrelated to the commit under test.
    Two of that class's tests then read `verdict != "hit"` and `skipTest`, uncited — a RED
    `check_unfalsifiable_skips.py` never reproduces from `check_ci_parity.py`'s clone (a fresh
    `git clone --no-local` is immune: it writes every blob's bytes fresh from the object
    database, never carrying over a SOURCE WORKING TREE's own on-disk-only, un-tracked
    permission mutation — git tracks the executable bit, never read/write). This is the fix:
    every fixture-copying `setUp()` calls this immediately after `copytree`, so the class of
    copy is unconditionally writable regardless of what state the source happened to be left
    in — the same "force writable after copy" pattern `_fixture_locked_for_run()` already
    proved out for its own patched `copystat`/`copymode`, generalized to a plain call site that
    is not inside that context manager's `with` block at all."""
    os.chmod(path, os.stat(path).st_mode | 0o200)
    for dirpath, dirs, files in os.walk(path):
        for name in dirs + files:
            p = os.path.join(dirpath, name)
            try:
                os.chmod(p, os.stat(p).st_mode | 0o200)
            except OSError:
                pass


@contextlib.contextmanager
def _fixture_locked_for_run():
    """dev #444's tripwire. Strips the write bit from every file AND directory under
    `_fixture_roots()` for the duration of the `with` block — restored (original mode,
    including any directory's own) in `finally`, even on a crash — so a test that still
    writes into the tracked fixture in place, even one that restores byte-identically
    afterward, fails LOUDLY and immediately with its own PermissionError, right there in its
    traceback, instead of leaving a transient bad state that a serial run never notices and a
    concurrent reader (a second test process, a gate loop, check_unfalsifiable_skips.py's
    second pass, a coordinator running parity beside a dispatch) can be corrupted by.

    Every writer test dev #444 found (`scripts/tests/test_binding.py`,
    `scripts/tests/test__docx.py`) was moved onto `scratch_profile()`/`scratch_fixture_tree()`
    before this landed — see their own dev #444 citations — so this should never fire in a
    clean run; it is the mechanical backstop for the NEXT one, not a check any test here is
    meant to trip on purpose.

    ⭐ WITHOUT the patch below, this lock is not safe to land: dozens of OTHER, perfectly
    legitimate tests elsewhere in this suite already do `shutil.copytree(_FIXTURE, scratch)`
    or `shutil.copy(os.path.join(ROOT, f), ...)` to build their OWN scratch profile — the
    sanctioned pattern, unrelated to dev #444's writers. `shutil.copy`/`copy2`/`copytree`'s
    default `copy_function` all replicate the SOURCE file's permission bits onto the
    destination (`shutil.copystat`/`copymode`) — so a source made read-only here makes every
    one of those scratch COPIES read-only too, and every one of *those* tests then fails with
    the exact same PermissionError this lock exists to produce, for a reason that has nothing
    to do with them (measured directly: landing the raw chmod-only version of this lock
    turned 4 real dev #444 failures into 166). `shutil.copystat`/`copymode` are patched for
    the lock's duration to keep doing everything they normally do and then force the
    destination's owner-write bit back on — a copy's CONTENT still comes from the source
    exactly as before; only the destination's own writability is no longer inherited."""
    saved = []
    for root in _fixture_roots():
        for dirpath, dirs, files in os.walk(root):
            for name in files + dirs:
                p = os.path.join(dirpath, name)
                mode = os.stat(p).st_mode
                saved.append((p, mode))
                os.chmod(p, mode & ~0o222)
        mode = os.stat(root).st_mode
        saved.append((root, mode))
        os.chmod(root, mode & ~0o222)

    _orig_copystat = shutil.copystat
    _orig_copymode = shutil.copymode

    def _force_writable(path):
        try:
            st = os.stat(path)
            os.chmod(path, st.st_mode | 0o200)
        except OSError:
            pass

    def _copystat_then_writable(src, dst, *, follow_symlinks=True):
        _orig_copystat(src, dst, follow_symlinks=follow_symlinks)
        _force_writable(dst)

    def _copymode_then_writable(src, dst, *, follow_symlinks=True):
        _orig_copymode(src, dst, follow_symlinks=follow_symlinks)
        _force_writable(dst)

    shutil.copystat = _copystat_then_writable
    shutil.copymode = _copymode_then_writable
    try:
        yield
    finally:
        shutil.copystat = _orig_copystat
        shutil.copymode = _orig_copymode
        for p, mode in saved:
            try:
                os.chmod(p, mode)
            except OSError:
                pass


SKIP_BASELINE = {
    True: {   # no real profile on this machine — this is CI, always, and any bare checkout
        # 37 -> 35 (gate-keeper, dev #165 item 1/2, 2026-09-02): two of these skips are gone,
        # both deliberately. test_the_ooo_row_carries_its_evidence no longer skips at all — it
        # was rewritten to exercise reconcile.py's guard against fully synthesized data (no real
        # profile needed, so it now runs under the fixture too), removing a real company id and
        # a hardcoded date that had been pinned directly in this file. And
        # test_relocation_basis_still_flagged_unconfirmed was retired outright: the owner's real
        # profile.json has since confirmed the comp-tier flag the test asserted was unconfirmed,
        # exactly as its own failure message said would happen ("update profile.json AND drop
        # this test").
        # 35 -> 34 (gate-keeper, ADR-031 B1, 2026-09-10): TestNoPlaceholderContactData's
        # test_the_api_refuses_a_duplicate_id no longer skips against the fixture. `contacts[]`
        # (the array whose id-duplicate check it exercised) is RETIRED — refused outright before
        # a duplicate-id check ever runs — so the test was rewritten to build its own throwaway
        # profile and assert the successor property (`involvements` duplicate-pair refusal)
        # directly, which needs no real profile at all. One fewer real-profile-only skip.
        # 34 -> 2 (gate-keeper, dev #411 piece 3, design-purity-at-startup.md §2.10 — the
        # 40-skip disposition table). `SKIP_BASELINE[False]` retires below: under the owner's
        # rule (CLAUDE.md, dev #411) no engine-team run ever binds this suite to a real
        # profile again, so that branch is categorically unreachable and every one of its
        # skips was an unfalsifiable green one layer above the property it claimed to guard.
        # 32 of the 34 landed this piece, one class/commit at a time (fixture gains
        # `strategy.md` sections, a 200-entry `log.md`, `archive/README.md`,
        # `pipeline/kb/`, `conversations/`, a retired-channel pair, an open dated fit
        # question, a second sent touch, and two config.json leaves synthesized to a
        # geo/enum SHAPE instead of an ALL-CAPS placeholder); one
        # (`test_no_engine_file_carries_profile_data`) is RETIRED outright — it is dev #411
        # itself, and `TestPurityHookStep`/`TestPurityHookRetiredFlagsRefuseLoudly`/
        # `TestPurityHookDecisionResolution` already exercise its replacement. Two remain,
        # named rather than silently carried: `TestNoPlaceholderContactData.
        # test_no_contact_stores_a_placeholder_address` and `TestValidateData.
        # test_delivery_is_never_INFERRED` each need a NEW `validate_data.py` rule the
        # design table calls for but this piece did not build — the placeholder-email rule
        # in particular collides with the fixture's OWN synthetic `@example.com` addresses,
        # a real design question next piece's author should not resolve by accident.
        "asserts the OWNER's real profile content; the synthetic fixture cannot satisfy it, and "
        "weakening the assertion would weaken a real guard": 2,
        # `TestFixtureMirrorsTheRealProfile`'s 6 `skipTest`s (design §2.10's three "I" rows —
        # `docs/profile_shape.json` generation plus the install-side profile-shape self-check
        # this piece did not build) are UNCHANGED — named in the same design row, deferred
        # for the same reason: real engineering the fixture-infra half of this piece did not
        # have budget for, not something to carry silently.
        "no real profile here to compare against": 6,
        "archive not created yet": 1,
    },
    False: {  # a real profile is present — a maintainer's own machine; dev #411 (CLAUDE.md)
              # makes this branch categorically unreachable from an engine-team run, kept
              # only so `_run_with_skip_accounting()` has a defined baseline if anyone ever
              # points this suite at real data again by mistake, which is itself now a defect.
        "archive not created yet": 1,
    },
}


def _run_with_skip_accounting():
    """Run the suite and turn its skip count into a first-class, reported, ENFORCED outcome.

    Returns True only when every test that ran either passed, or skipped for a reason and a
    count this file has explicitly declared as expected in this environment. A skip that is
    undeclared, or whose count moved, is treated the same as a failure — see SKIP_BASELINE above
    for why, and dev #107 for the incident this exists to close.

    ⭐ dev #444 — the run itself is wrapped in `_fixture_locked_for_run()`: every tracked
    fixture tree is read-only while `runner.run(suite)` executes, so a test that still writes
    into it in place fails loudly, right there, instead of leaving an invisible transient
    write a serial run never notices. A before/after `_fixture_snapshot()` diff is reported
    too, as a second, independent signal — it would catch a write that somehow bypassed the
    read-only bits (running as root, for instance), which the lock alone cannot.
    """
    loader = unittest.TestLoader()
    suite = loader.discover(TESTS_DIR, pattern="test_*.py", top_level_dir=TESTS_DIR)
    runner = unittest.TextTestRunner(verbosity=2)
    before_fixture = _fixture_snapshot()
    with _fixture_locked_for_run():
        result = runner.run(suite)
    after_fixture = _fixture_snapshot()
    if before_fixture != after_fixture:
        changed = sorted(set(before_fixture) ^ set(after_fixture)
                         | {p for p in before_fixture
                            if p in after_fixture and before_fixture[p] != after_fixture[p]})
        print("!! dev #444: THE TRACKED FIXTURE CHANGED DURING THIS RUN — %d path(s):"
             % len(changed))
        for p in changed:
            print("   - " + p)
        return False

    reason_counts = collections.Counter(reason for _, reason in result.skipped)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - skipped

    print("=" * 72)
    print("RUN SUMMARY: %d ran, %d passed, %d failed, %d skipped" % (total, passed, failed, skipped))
    if reason_counts:
        print("SKIPPED IS NOT PASSED — %d assertion(s) never ran this time:" % skipped)
        for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
            print("  %3d  %s" % (count, reason))
    print("=" * 72)

    baseline = SKIP_BASELINE[USING_FIXTURE]
    drift = []
    for reason, count in reason_counts.items():
        expected = baseline.get(reason)
        if expected is None:
            drift.append("UNDECLARED skip reason (%d occurrence(s)): %r" % (count, reason))
        elif expected != count:
            drift.append("skip count drifted for %r: SKIP_BASELINE says %d, this run produced %d"
                         % (reason, expected, count))
    for reason, expected in baseline.items():
        if expected and reason not in reason_counts:
            drift.append("expected skip %r (%d) did not occur this run — if a test started "
                         "running instead of skipping, update SKIP_BASELINE deliberately rather "
                         "than letting this pass silently" % (reason, expected))

    if drift:
        print("!! SKIP BASELINE DRIFT (dev #107) — unchecked outcome changed shape:")
        for d in drift:
            print("   - " + d)
        print("!! Update SKIP_BASELINE above ONLY if you can name why the shift is correct.")
        return False

    return result.wasSuccessful()


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

__all__ = [
    'HERE',
    'ROOT',
    'ENGINE',
    'TESTS_DIR',
    'ast',
    'collections',
    'contextlib',
    'datetime',
    'glob',
    'hashlib',
    'inspect',
    'json',
    'io',
    'os',
    're',
    'shutil',
    'pathlib',
    'subprocess',
    'sys',
    'tempfile',
    'unittest',
    '_s',
    '_pr',
    '_er',
    '_tree',
    'ENGINE_SCRIPTS',
    '_real',
    '_FIXTURE',
    '_has_git_entry',
    'IS_CHECKOUT',
    '_NEEDS_CHECKOUT',
    'USING_FIXTURE',
    '_profile',
    'OWNER_TOKEN',
    'load_jsonl',
    'load_opps',
    '_norm_invocations',
    '_SyntheticStore',
    '_SyntheticCoverage',
    '_SyncFixtures',
    '_WriteApiHarness',
    '_synthetic_dashboard_profile',
    '_asks_profile',
    '_trigger_profile',
    '_audit_profile',
    '_audit_run',
    '_audit_page',
    '_audit_ledger',
    '_live_role',
    '_root_env',
    '_stamp_brief',
    '_raw',
    '_c1_profile',
    '_c1_person',
    '_c1_involvement',
    '_c1_touch',
    '_c1_opp',
    'guard_outbound_click',
    '_pane_test_profile',
    '_pane_env',
    '_runlock_pane',
    '_journal',
    '_VariantOutFixture',
    '_ats_fixture_profile',
    '_FakeAtsMailbox',
    '_AtsSweepProfile',
    '_write_cascade_profile',
    '_rs_git',
    '_rs_profile',
    '_rs_journal',
    '_B5Profile',
    'scratch_profile',
    'scratch_env',
    'scratch_fixture_tree',
    '_fixture_roots',
    '_fixture_snapshot',
    '_fixture_locked_for_run',
    'force_tree_writable',
    'SKIP_BASELINE',
    '_run_with_skip_accounting',
]
