#!/usr/bin/env python3
"""Where is the USER'S profile? (Not: where is the engine?)

⭐ THE DISTINCTION THIS MODULE EXISTS TO ENFORCE (2026-08-05)
------------------------------------------------------------
Every script used to derive its root as `dirname(dirname(abspath(__file__)))` — the directory
above `scripts/`. That is correct only when the engine and the data live in the same tree, which
was true exactly once: the original single-user installation.

**As a PLUGIN they are never the same tree.** The engine installs under `${CLAUDE_PLUGIN_ROOT}`
somewhere in Claude's plugin directory; the user's resume, config and pipeline live in whatever
directory they run from. Deriving the data root from `__file__` points every script at the
PLUGIN, which contains no data.

That failure is not loud. On 2026-08-05 a symlinked install did exactly this and
`generate_dashboard.py` regenerated the dashboard with ZERO opportunities and overwrote the real
one — exit 0, valid HTML, no data. **A wrong root produces empty results, not errors.**

Resolution order:
  1. `CLAUDESEARCH_ROOT`  — explicit; also what lets an AGENCY point the engine at one candidate's
     profile out of many, and what the test suite uses for isolation.
  2. the current working directory, walking UP to find a profile marker.
  3. ⭐ the REMEMBERED profile (`~/.claude/jobsearch/profile_root`).

⭐⭐ WHY (3) EXISTS — AN MCP SERVER HAS NEITHER OF THE FIRST TWO (2026-08-05).
A long-lived MCP server is spawned by the Claude runtime, not from a shell: it inherits no
`CLAUDESEARCH_ROOT` and no guarantee about its working directory. `mail_client.py` therefore
resolved a non-profile directory, found no `user.json`, and served ZERO mailboxes for the life of
the process — and a mailbox-blind search returns the same empty result as a genuinely empty
mailbox. It reported "no new mail" while the deterministic per-call sweeps, which DO start from a
shell in the profile, reached both accounts fine.

The pointer is maintained automatically: any resolution that finds a genuine profile records it.
So a single normal run from the profile directory repairs it for every process that cannot see one.

⚠️ **dev #87 — A LOUD DOWNSTREAM MESSAGE IS THE LAST LINE OF DEFENCE, NOT THE DESIGN.**
`profile_root()`'s own fallback — "return the CWD rather than guessing" a few lines below — means
it CAN legitimately land on the engine's own root: a maintenance session with no
`CLAUDESEARCH_ROOT`, no profile anywhere above the CWD, and nothing remembered has nothing better
to offer than CWD, and CWD is sometimes this very engine checkout. That happened for real (a
read-only `check_engine_purity.py` run) and was harmless only because that particular caller
handles a missing `user.json` by printing a loud `NOT CHECKED` and exiting 0 — the SAME shape as
#81, where a write-capable caller trusted the identical class of resolution (the checked-in test
fixture, not the engine root, but the same "wrong-but-plausible directory" mistake) and it was
caught only because the write itself was noticed.

**The general rule: this module resolves; it does not decide whether the resolution is safe to
act on.** Every caller decides that for itself, and a caller that only reads can survive a wrong
answer by reporting it loudly (`check_engine_purity.py`'s pattern); a caller that WRITES cannot —
it must refuse outright, using a predicate like `is_engine_root()` or `is_tracked_fixture()`
below, before it ever opens a file for writing. Do not assume a downstream message makes a wrong
resolution safe just because it did, once, somewhere else in the codebase.

A "profile" is a directory containing `config.json` or `data/`. Walking up means you can run from
a subdirectory, the way git does.
"""

import os

MARKERS = ("config.json", "data")

# Written whenever a real profile is resolved; read when nothing else can identify one.
POINTER = os.path.join(os.path.expanduser("~"), ".claude", "jobsearch", "profile_root")
# ⭐ The ENGINE's own location — LEGACY, informational only since the launcher's
# TEMPLATE_GENERATION 3 (dev #167, closing #249). Nothing resolves through this file any more:
# `~/.claude/jobsearch/run` resolves the newest COMPLETE installed version itself (with
# `engine_root.override` — written only by an explicit install_launcher.py run — as the one
# deliberate exception), then repairs this file after resolution for anything that still opens
# it. This module used to write it AT IMPORT, which made every import of every engine script a
# pointer writer, and every copy not carrying the newest write-guard a live poisoning route —
# the guard stack that grew here (ephemeral rejection, checkout-vs-install ranking, version
# recency) was three patches on that one symptom, and gen 3 removed the symptom instead: the
# import-time write is gone, and `run --where` is the supported way to read the engine path.
ENGINE_POINTER = os.path.join(os.path.expanduser("~"), ".claude", "jobsearch", "engine_root")


# ⭐⭐ A TEST FIXTURE AND A TEMP DIRECTORY LOOK EXACTLY LIKE A PROFILE — and must never be
# recorded as one. Both have `config.json` and `data/`, which is the whole test for a profile.
#
# Observed 2026-08-06: running the suite left the remembered pointer aimed at
# `tests/fixtures/profile`. The next 46 tests skipped, which is the LOUD symptom — the quiet one
# is far worse. **An MCP server has no cwd and no env; the pointer is all it has.** With the
# pointer aimed at a fixture, a real run resolves a store containing synthesized rows and reports
# it as the user's pipeline. That is the same shape as the engine-pointer bug fixed in 0.2.1:
# a durable pointer must never be allowed to name something disposable.
_FIXTURE_MARKERS = (
    os.sep + "tests" + os.sep + "fixtures" + os.sep,
    os.sep + "fixtures" + os.sep,
)
_TEMP_MARKERS = (
    os.sep + "Temp" + os.sep,
    os.sep + "tmp" + os.sep,
)
_NOT_A_REAL_PROFILE = _FIXTURE_MARKERS + _TEMP_MARKERS


def is_tracked_fixture(path):
    """Is this path (or does it sit inside) a GENERATED, checked-in test fixture?

    ⭐ dev #81 — narrower than `is_disposable_profile` ON PURPOSE. A `tempfile.mkdtemp()` scratch
    profile is a legitimate, safe target for a self-heal WRITE — that is exactly how the test
    suite exercises `install_rulebook.py`'s own writer, and those directories are meant to be
    written into and thrown away. The checked-in fixture under `tests/fixtures/` is different in
    kind: it is TRACKED, generated by `make_fixture.py`, and read by dozens of tests as a stand-in
    for a real profile. A write into it is exactly the drift this predicate exists to catch —
    `install_rulebook.py`'s self-heal wrote a stray ~38KB CLAUDE.md there when profile resolution
    (deliberately, for READS — see `_FIXTURE`/`USING_FIXTURE` in test_checks.py) pointed
    `CLAUDESEARCH_ROOT` straight at it and a write-capable call ran against the same pointer with
    no write-side guard at all.
    """
    p = os.path.realpath(path or "")
    if not p.endswith(os.sep):
        p += os.sep
    return any(marker in p for marker in _FIXTURE_MARKERS)


def is_disposable_profile(path):
    """Would recording this path aim the pointer at a fixture or a temp tree?

    Conservative: a false negative only preserves today's behaviour, while a false positive would
    refuse to remember a legitimate profile and leave an MCP server with nothing to resolve.

    ⚠️ ASK THE PLATFORM WHERE TEMP IS — a hardcoded list is not enough, and this was caught the
    same day the check was written. macOS puts temp under
    `/var/folders/<hash>/T/`, which contains neither `/tmp/` nor `/Temp/`, so a literal-marker
    check waved it straight through and a test run left the pointer aimed at a temp directory
    that no longer existed. `tempfile.gettempdir()` is the authoritative answer on every platform;
    the literal markers stay as a backstop for paths that are temp-shaped but not the default.

    ⚠️ Includes temp directories, which `is_tracked_fixture` deliberately does NOT — see that
    function's docstring for why the two must stay separate rather than merged into one check.
    """
    import tempfile
    p = os.path.realpath(path or "")
    if not p.endswith(os.sep):
        p += os.sep
    try:
        tmp = os.path.realpath(tempfile.gettempdir())
        if not tmp.endswith(os.sep):
            tmp += os.sep
        if p.startswith(tmp):
            return True
    except Exception:
        pass
    return is_tracked_fixture(path) or any(marker in p for marker in _TEMP_MARKERS)


def _remember(path):
    """Record a resolved profile. Best-effort and silent: never break a run over a cache."""
    try:
        if not looks_like_profile(path):
            return
        if is_disposable_profile(path):
            return
        if os.path.exists(POINTER):
            with open(POINTER, encoding="utf-8") as fh:
                if fh.read().strip() == path:
                    return                      # unchanged; avoid rewriting on every import
        os.makedirs(os.path.dirname(POINTER), exist_ok=True)
        with open(POINTER, "w", encoding="utf-8") as fh:
            fh.write(path)
    except OSError:
        pass


def remembered_profile():
    """The last profile a run resolved, if it still looks like one."""
    try:
        with open(POINTER, encoding="utf-8") as fh:
            path = fh.read().strip()
        return path if path and looks_like_profile(path) else None
    except OSError:
        return None


def looks_like_profile(path):
    return any(os.path.exists(os.path.join(path, m)) for m in MARKERS)


# ⭐ dev #151 — PER-PROFILE STATE BELONGS WITH THE PROFILE; only what is needed to FIND a
# profile belongs under $HOME. The diagnostics log and the drift markers used to live in
# `~/.claude/jobsearch/` keyed by session, so two profiles on one machine interleaved in one
# file with no way to tell them apart — which made guard_status()'s own question ("has THIS
# install had an inert guard for two days?") unanswerable the moment a second profile existed.
STATE_DIRNAME = ".jobsearch"
_HOME_STATE = os.path.join(os.path.expanduser("~"), ".claude", "jobsearch")


def state_root(start=None):
    """Where per-profile engine STATE lives: `<profile>/.jobsearch` when a genuine profile is
    resolvable, else the machine-global `~/.claude/jobsearch` fallback.

    Resolution uses the FULL `profile_root()` chain — env, cwd walk, remembered pointer —
    deliberately: state placement is not the binding question (`binding.py` owns that). A
    PreToolUse hook in a scheduled run has neither env nor a profile cwd, and its guard_status
    events still belong with the profile the pointer names, or `doctor` cannot see them.

    A disposable resolution (test fixture, temp tree) must never grow a state directory —
    `is_disposable_profile` already encodes that judgement — so those fall back to $HOME, which
    the test suite redirects. Events from a context with NO resolvable profile also land in the
    $HOME fallback: they are machine state, not any profile's."""
    root = profile_root(start)
    if looks_like_profile(root) and not is_disposable_profile(root):
        return os.path.join(root, STATE_DIRNAME)
    return _HOME_STATE


def profile_root(start=None):
    """The USER's profile directory. Never the engine's."""
    env = os.environ.get("CLAUDESEARCH_ROOT")
    if env:
        root = os.path.abspath(env)
        _remember(root)
        return root
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if looks_like_profile(cur):
            _remember(cur)
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            # Nothing above the CWD is a profile. Before giving up, use the profile a previous
            # run recorded — this is the ONLY thing an MCP server has to go on.
            been_here = remembered_profile()
            if been_here:
                return been_here
            # Still nothing. Return the CWD rather than guessing: a caller that needs data will
            # fail visibly on a missing file, which is far better than silently reading the
            # engine's own directory and reporting an empty pipeline as fact.
            return os.path.abspath(start or os.getcwd())
        cur = parent


# ⭐⭐ EPHEMERAL ENGINE LOCATIONS — the desktop app materialises a plugin PER SESSION.
#
# Observed 2026-08-05 on the desktop, which is how most people will run this: `engine_root` had
# been overwritten with
#
#   ~/Library/Application Support/Claude/local-agent-mode-sessions/<session-id>/…/rpm/plugin_<id>
#
# That path is real and works — for the life of that session. At the time, the launcher read
# this pointer on EVERY call, so once the session was gone every scheduled run failed at its
# first script call. **The failure lands hours later, in an unattended run, far from the session
# that caused it**, which is the worst shape a bug can have here.
#
# The cause was `_remember_engine` recording whatever copy happened to run last (removed with
# dev #167 — see the block above `engine_root()`). The predicate remains load-bearing on the one
# deliberate write left: `install_launcher.record_deliberate_override()` refuses an ephemeral
# engine, because a pointer meant to outlive sessions must never point INTO one.
_EPHEMERAL_MARKERS = (
    os.sep + "local-agent-mode-sessions" + os.sep,
    os.sep + "rpm" + os.sep + "plugin_",
    os.sep + "Temp" + os.sep,
    os.sep + "tmp" + os.sep,
)


def is_ephemeral_engine(path):
    """Would recording this path leave a pointer that dies with a session?

    Conservative on purpose: a false NEGATIVE leaves today's behaviour, while a false POSITIVE
    would refuse to record a legitimate engine and strand a user with no pointer at all.

    ⚠️ ASK THE PLATFORM WHERE TEMP IS — the same lesson `is_disposable_profile` above already
    carries, applied to one of the pair only until dev #167: macOS puts temp under
    `/var/folders/<hash>/T/`, which contains neither `/tmp/` nor `/Temp/`, so a literal-marker
    check waved a maintainer tool's temp-dir engine copy straight through — and the gen-2
    launcher, seeing an out-of-cache path with a scripts/ dir, honored it.
    `tempfile.gettempdir()` is the authoritative answer on every platform; the literal markers
    stay as a backstop for paths that are temp-shaped but not the default.
    """
    import tempfile
    p = os.path.realpath(path or "")
    if not p.endswith(os.sep):
        p += os.sep
    try:
        tmp = os.path.realpath(tempfile.gettempdir())
        if not tmp.endswith(os.sep):
            tmp += os.sep
        if p.startswith(tmp):
            return True
    except Exception:
        pass
    return any(marker in p for marker in _EPHEMERAL_MARKERS)


# ⭐⭐ dev #199 — CACHE_ROOT is the fixed half; the marketplace segment directly under it is NOT.
#
# `is_installed_engine()` used to test a path against `INSTALL_CACHE`, which hardcoded the
# marketplace's own NAME ("careers-plugins"). That name is not this plugin's identity — the
# marketplace rename to `crinaro/marketplace` was approved — and the moment it landed, a
# literal-name test would return False for a genuinely INSTALLED copy. So the test is
# STRUCTURAL — `~/.claude/plugins/cache/<any one marketplace segment>/jobsearch/...` — never
# the marketplace's literal name. `jobsearch` genuinely IS fixed: it is this file's own
# identity, the same literal already hardcoded throughout this module (`POINTER`,
# `ENGINE_POINTER`, `STATE_DIRNAME`). The marketplace segment is read structurally and never
# compared against a value, so a rename cannot break this file at all.
#
# The callers that still depend on this predicate: `drift_guard.py` (announcing a
# non-installed engine), `migrate.py`'s trampoline (never second-guessing a deliberate
# checkout), and `install_launcher.record_deliberate_override()` (an explicit run from the
# installed copy clears the checkout override rather than setting one).
#
# `INSTALL_CACHE` is kept — nothing in this module reads it any more, but `is_installed_engine`'s
# own tests, and anyone reading this file, still want the concrete default path spelled out.
CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache")
_INSTALLED_PLUGIN_NAME = "jobsearch"  # this engine's own identity — fixed, unlike the marketplace
INSTALL_CACHE = os.path.join(CACHE_ROOT, "crinaro-marketplace", _INSTALLED_PLUGIN_NAME)


def is_installed_engine(path):
    """Is this a marketplace-installed copy rather than a working tree?

    Deliberately a path test and not a content test: a checkout and an installed copy hold the
    same files, so nothing INSIDE them can tell the two apart. Where it sits is the only signal.

    ⭐⭐ dev #199 — STRUCTURAL: `~/.claude/plugins/cache/<anything>/jobsearch/...`. The marketplace
    segment (`rest[0]`) is read and ignored, never matched against a literal — see the comment
    above `CACHE_ROOT` for why a name-pinned test was the bug.
    """
    p = os.path.realpath(path or "")
    if not p:
        return False
    root = os.path.realpath(CACHE_ROOT)
    if not (p == root or p.startswith(root + os.sep)):
        return False
    rest = p[len(root):].lstrip(os.sep).split(os.sep)
    return len(rest) >= 2 and rest[1] == _INSTALLED_PLUGIN_NAME


# ⭐⭐ dev #167 (closing #249) — THE IMPORT-TIME POINTER WRITE IS GONE, AND SO IS ITS GUARD
# STACK. `_remember_engine(_ENGINE_AT_IMPORT)` used to run at the bottom of this module, which
# made every import of every engine script a writer of `ENGINE_POINTER`. Three generations of
# guards accumulated on that one write — ephemeral-session rejection, installed-outranks-
# checkout, version recency — and each closed one observed poisoning route while every engine
# copy NOT carrying the newest guard remained a live one (a stale session's copy, by
# construction, never carries it). The launcher meanwhile stopped trusting the file at all:
# since TEMPLATE_GENERATION 3 it resolves the newest complete installed version itself, honours
# only the explicit `engine_root.override` (written by `install_launcher.py` alone, as a
# deliberate act), and repairs `ENGINE_POINTER` after resolution for legacy readers. A guarded
# write protecting a file nothing resolves through is complexity without a customer, so the
# write and its guards were removed together rather than patched a fourth time.
def engine_root():
    """Where the ENGINE physically lives — for schemas, prompts and templates that ship with it.

    ⭐ realpath, NOT abspath — the OPPOSITE of profile_root, deliberately.
    A development install may reach the engine through a symlink (`scripts -> ../engine/scripts`).
    `abspath` would then answer with the SYMLINK's directory, i.e. the user's profile, and every
    engine-structure lookup would search the wrong tree. The engine is where the FILE IS, so we
    resolve. The profile is where the USER IS, so we never resolve. Getting these backwards is
    the whole class of bug this module exists to prevent."""
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def is_engine_root(path):
    """Would this resolution land ON the engine's own root — never a real profile.

    dev #87. `profile_root()`'s fallback path can legitimately answer with the CWD when nothing
    above it looks like a profile and nothing is remembered, and the CWD is sometimes this very
    engine checkout (a maintenance session, a CI runner, a bare clone with no profile at all).
    That landing is not itself a bug — `profile_root()` has nothing better to offer — but a
    WRITE-capable caller must never treat it as a place safe to write into. A read-only caller
    (`check_engine_purity.py`) already survives the identical landing by finding no `user.json`
    and printing a loud `NOT CHECKED`; this predicate is for the callers where the correct
    response is to refuse outright, matching `is_tracked_fixture`'s role for the sibling case
    (dev #81 — a write landing in the checked-in test fixture instead of the engine root).

    ⭐ Compares by `realpath` on BOTH sides, matching `engine_root()`'s own resolution rather than
    `profile_root()`'s `abspath` — so a symlinked engine checkout is still recognised as itself.
    Do NOT blur this with `is_tracked_fixture`: the engine's own root and a checked-in test
    fixture are two different dangerous landings with two different remedies (refuse because
    writing here corrupts the engine's own working tree, vs. refuse because the fixture is
    generated and any drift is silent). Keeping them as separate predicates keeps each refusal
    message honest about which mistake it is refusing.
    """
    p = os.path.realpath(path or "")
    return bool(p) and p == os.path.realpath(engine_root())


def profile_or_fixture(start=None):
    """The user's profile, or the test fixture when there is none.

    ⭐ CI runs from a bare engine checkout with no profile at all. A gate that cannot execute
    proves nothing, so the gates fall back to `tests/fixtures/profile` — synthetic, containing no
    real person, employer, address or figure. Locally this always returns the real profile, so the
    gates keep testing real data where it exists."""
    import os as _o
    r = profile_root(start)
    if _o.path.exists(_o.path.join(r, "config.json")):
        return r
    fx = _o.path.join(engine_root(), "tests", "fixtures", "profile")
    return fx if _o.path.exists(_o.path.join(fx, "config.json")) else r
