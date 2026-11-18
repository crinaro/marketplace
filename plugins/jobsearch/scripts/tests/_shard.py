# dev #926 — the regression suite, sharded across processes. Standard library only, Python 3.9+.
"""Runs the regression suite's tests in N long-lived worker processes instead of one.

WHY. The suite is latency-bound, not CPU-bound: most of its time is spent waiting on short child
processes (each about a second of interpreter start-up and endpoint scanning) started one after
another, so a whole run took 20-40 minutes at 0.4-9% CPU on an 18-core machine (measured
2026-11-17). Running independent tests side by side is the lever; nothing about a test changes.

THE UNIT OF WORK is the one `unittest` itself gives fixtures to, the same choice
`pytest-xdist --dist loadscope` and Django's `--parallel` make:
  * a module that defines `setUpModule`, `tearDownModule` or `load_tests` is ONE unit, so its
    module fixture runs exactly once, as in a serial run;
  * any other module is one unit per TestCase class bound in it (mirroring
    `TestLoader.loadTestsFromModule`, which iterates `dir(module)`), so `setUpClass` and
    `tearDownClass` keep their meaning;
  * a selective run (`TEST_CHECKS_SELECT`, dev #530) uses the selected ids as its units.

IDENTICAL COUNTS BY CONSTRUCTION. Before anything runs, the parent loads every unit and compares
the multiset of test ids with what `loader.discover` (the serial path) would run. Any difference
refuses the run, loudly, naming the ids; it never runs a different suite quietly.

ISOLATION. Workers run as `sys.executable` (never a PATH lookup). Each gets its own TMPDIR (under
the parent's, so a parity run's `/tmp` shape holds) and its own per-process lock and diagnostics
paths (the ones `_common` defaults per process, `_SUITE_DEFAULTED_ENV`). HOME and cwd are the
parent's, exactly as in a serial run. The parent holds `_fixture_locked_for_run()` for the whole
run; a worker applies the same copy patch (`_copies_stay_writable`) and does not self-heal the
fixture (it reads the parent's `TEST_CHECKS_FIXTURE_LOCKED`), so dev #444's tripwire covers
every worker.

A WORKER THAT DIES (a crash, `os._exit`, a kill) fails every test of the unit it was running with
an error naming the exit and its log, and a fresh worker takes the remaining units.

PROTOCOL. The parent writes one JSON request per line to a worker's stdin (`{"unit", "log"}`);
the worker points fds 1 and 2 at that unit's log file, runs it, and answers one JSON line on a
private duplicate of its original stdout, so nothing a test prints can corrupt the channel.

`TEST_CHECKS_JOBS=N` sets the worker count (default: the CPU count); `TEST_CHECKS_JOBS=1` runs
the suite in-process exactly as before this existed.
"""

import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import warnings

SEP1 = "=" * 70
SEP2 = "-" * 70


def requested_jobs(environ=None):
    """The worker count: `TEST_CHECKS_JOBS` when it is a positive integer, else the CPU count.
    An unreadable value is loud and falls back to 1 (the serial path), never to a guess."""
    environ = os.environ if environ is None else environ
    raw = environ.get("TEST_CHECKS_JOBS")
    if raw is None or raw == "":
        return os.cpu_count() or 1
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n < 1:
        print("TEST_CHECKS_JOBS=%r is not a positive integer; running unsharded" % raw,
              file=sys.stderr)
        return 1
    return n


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for t in _iter_tests(item):
                yield t
        else:
            yield item


def suite_ids(suite):
    return [t.id() for t in _iter_tests(suite)]


def _discovered_module_names(tests_dir, pattern="test_*.py"):
    """The module names `loader.discover(tests_dir, pattern, top_level_dir=tests_dir)` imports
    from the top level of `tests_dir`, in its own (sorted) order."""
    import fnmatch
    out = []
    for name in sorted(os.listdir(tests_dir)):
        path = os.path.join(tests_dir, name)
        if os.path.isfile(path) and fnmatch.fnmatch(name, pattern) and name.endswith(".py"):
            mod = name[:-3]
            if mod.isidentifier():
                out.append(mod)
    return out


def _module_units(loader, modname):
    """The units for one module (see the module docstring)."""
    try:
        __import__(modname)
    except Exception:
        return [modname]          # the worker reproduces the import failure under its own id
    mod = sys.modules[modname]
    if any(hasattr(mod, n) for n in ("setUpModule", "tearDownModule", "load_tests")):
        return [modname]
    units = []
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
            if loader.getTestCaseNames(obj):
                units.append("%s.%s" % (modname, name))
    return units


# ⭐ SERIAL UNITS — DECLARED, with the reason. These run after every other unit has finished, one
# at a time, in one worker: a test whose verdict depends on how much CPU it gets in a fixed
# wall-clock budget is measuring the machine's load, and running it beside 17 other workers turns
# a serial pass into a red (measured: 562 of 826 files in the budget, sharded, 2026-11-17).
# `test_checks.py`'s `TestShardDeclarations` fails on an entry that names no class.
SERIAL_UNITS = {
    "test_check_engine_purity.TestHookSlicesOfTheTrackedEngineComplete":
        "twelve 0.25 s wall-clock slices must cover the whole engine (dev #709); a CPU budget",
}


def plan_units(loader, tests_dir, select_ids=None):
    """`(units, expected_ids)`: the units to run and the test ids the serial path would run."""
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    if select_ids is not None:
        expected = unittest.TestSuite([loader.loadTestsFromName(i) for i in select_ids])
        # A selected whole module (test-impact CI selects modules) is split like discovery would
        # split it; a selected class or test runs as given.
        units = []
        for i in select_ids:
            units.extend(_module_units(loader, i) if "." not in i else [i])
        return units, suite_ids(expected)
    expected = loader.discover(tests_dir, pattern="test_*.py", top_level_dir=tests_dir)
    units = []
    for modname in _discovered_module_names(tests_dir):
        units.extend(_module_units(loader, modname))
    return units, suite_ids(expected)


def coverage_problem(loader, units, expected_ids):
    """None when the units run exactly `expected_ids` (as a multiset), else a description."""
    got = collections.Counter()
    sizes = {}
    for u in units:
        ids = suite_ids(loader.loadTestsFromName(u))
        sizes[u] = len(ids)
        got.update(ids)
    want = collections.Counter(expected_ids)
    if got == want:
        return None, sizes
    missing = sorted((want - got).elements())
    extra = sorted((got - want).elements())
    return ("the shard units would not run exactly the discovered tests: %d missing %s, %d extra "
            "%s" % (len(missing), missing[:10], len(extra), extra[:10])), sizes


# ── the aggregate result ──────────────────────────────────────────────────────────────────────

class ShardTest(object):
    """Stands in for a TestCase in the parent's aggregate result: `id()` and `str()` are the
    worker's own, so the dev #530 record and the printed failures carry the same ids a serial
    run does."""

    def __init__(self, tid, desc):
        self._id = tid
        self._desc = desc

    def id(self):
        return self._id

    def __str__(self):
        return self._desc

    def __repr__(self):
        return "<ShardTest %s>" % self._id


class ShardResult(object):
    """The parts of `unittest.TestResult` that `_run_with_skip_accounting` reads."""

    def __init__(self):
        self.testsRun = 0
        self.failures = []
        self.errors = []
        self.skipped = []
        self.expectedFailures = []
        self.unexpectedSuccesses = []

    def add_payload(self, p):
        self.testsRun += p["testsRun"]
        for key in ("failures", "errors", "expectedFailures"):
            getattr(self, key).extend((ShardTest(i, d), tb) for i, d, tb in p[key])
        self.skipped.extend((ShardTest(i, d), reason) for i, d, reason in p["skipped"])
        self.unexpectedSuccesses.extend(ShardTest(i, d) for i, d in p["unexpectedSuccesses"])

    def wasSuccessful(self):
        return (len(self.failures) == len(self.errors) == 0
                and not self.unexpectedSuccesses)


def _payload_from(result):
    def _d(t):
        return str(t)
    return {
        "testsRun": result.testsRun,
        "failures": [(t.id(), _d(t), tb) for t, tb in result.failures],
        "errors": [(t.id(), _d(t), tb) for t, tb in result.errors],
        "expectedFailures": [(t.id(), _d(t), tb) for t, tb in result.expectedFailures],
        "skipped": [(t.id(), _d(t), r) for t, r in result.skipped],
        "unexpectedSuccesses": [(t.id(), _d(t)) for t in result.unexpectedSuccesses],
    }


# ── the worker ───────────────────────────────────────────────────────────────────────────────

def worker_main(tests_dir):
    """Entry point of one shard worker (started by `run_sharded`). Never returns a verdict: it
    answers each request until stdin closes."""
    import _common
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    chan = os.fdopen(os.dup(1), "w", encoding="utf-8")   # PEP 446: not inherited by children
    # The requests arrive on a private duplicate of fd 0, and fd 0 itself becomes /dev/null: a
    # test's child that reads stdin (a SessionStart hook does) must see end-of-file, as under
    # parity, never block on this protocol pipe (measured: five 120 s timeouts before this).
    requests = os.fdopen(os.dup(0), "r", encoding="utf-8")
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    sys.stdin = open(os.devnull, encoding="utf-8")
    loader = unittest.TestLoader()
    with _common._copies_stay_writable():
        for line in requests:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            sys.stdout.flush()
            sys.stderr.flush()
            # dev #922 (docs/design-testing-model.md § 4b): the read audit, attributed per module.
            # What this process read so far belongs to the runner; what the unit (and the children
            # it starts) reads goes under unit/<module>/.
            audit = sys.modules.get("sitecustomize")
            audit_base = os.environ.get("READ_AUDIT_BASE") or os.environ.get("READ_AUDIT_DIR")
            unit_dir = None
            if audit is not None and hasattr(audit, "flush") and audit_base:
                os.environ["READ_AUDIT_BASE"] = audit_base
                audit.flush(audit_base)
                unit_dir = os.path.join(audit_base, "unit", req["unit"].split(".")[0])
                os.environ["READ_AUDIT_DIR"] = unit_dir
            fd = os.open(req["log"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            os.close(fd)
            start = time.monotonic()
            try:
                suite = loader.loadTestsFromName(req["unit"])
                stream = unittest.runner._WritelnDecorator(sys.stderr)
                result = unittest.TextTestResult(stream, True, 2)
                with warnings.catch_warnings():
                    if not sys.warnoptions:
                        warnings.simplefilter("default")
                    result.startTestRun()
                    try:
                        suite(result)
                    finally:
                        result.stopTestRun()
                payload = _payload_from(result)
            except BaseException:
                payload = {"crash": traceback.format_exc()}
            sys.stdout.flush()
            sys.stderr.flush()
            if unit_dir:
                audit.flush(unit_dir)
                os.environ["READ_AUDIT_DIR"] = audit_base
            payload["elapsed"] = time.monotonic() - start
            chan.write(json.dumps(payload) + "\n")
            chan.flush()
    return 0


# ── the parent ───────────────────────────────────────────────────────────────────────────────

class _Worker(object):
    def __init__(self, index, tests_dir, base_tmp, env):
        self.index = index
        self.tmp = tempfile.mkdtemp(prefix="s%d" % index, dir=base_tmp)
        wenv = dict(env)
        wenv["TMPDIR"] = self.tmp
        code = ("import sys; sys.path.insert(0, %r); import _shard; "
                "sys.exit(_shard.worker_main(%r))"
                % (os.path.dirname(os.path.abspath(__file__)), tests_dir))
        self.proc = subprocess.Popen([sys.executable, "-c", code], env=wenv,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def ask(self, unit, log):
        """The worker's answer for `unit`, or None when the worker died running it."""
        try:
            self.proc.stdin.write(json.dumps({"unit": unit, "log": log}) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except (OSError, ValueError):
            return None
        if not line:
            return None
        return json.loads(line)

    def close(self, kill=False):
        try:
            if kill:
                self.proc.kill()
            else:
                self.proc.stdin.close()
            self.proc.wait(timeout=60)
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=10)
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)


def _died_payload(loader, unit, rc, log):
    """A unit whose worker died: every one of its tests is an error, never a silent pass."""
    tb = ("shard worker exited (%s) while running %s; its output is in the log printed above "
          "(%s)\n" % (rc, unit, os.path.basename(log)))
    tests = list(_iter_tests(loader.loadTestsFromName(unit)))
    if not tests:
        tests = [None]
    errs = []
    for t in tests:
        tid = t.id() if t is not None else unit
        errs.append((tid, str(t) if t is not None else unit, tb))
    return {"testsRun": len(errs), "failures": [], "errors": errs, "expectedFailures": [],
            "skipped": [], "unexpectedSuccesses": []}


def _shard_env(defaulted):
    env = dict(os.environ)
    for k in defaulted:
        env.pop(k, None)
    for k in ("TEST_CHECKS_RECORD", "TEST_CHECKS_SELECT"):
        env.pop(k, None)
    env["TEST_CHECKS_SHARD_WORKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_sharded(loader, tests_dir, units, sizes, jobs, defaulted_env, out=None):
    """Runs `units` on `jobs` workers and returns a `ShardResult`. Each unit's log is printed in
    unit order (to `out`, default stderr, where a serial `TextTestRunner` writes), then the
    failures in `TextTestRunner`'s own format and its `Ran N tests` line."""
    out = out or sys.stderr
    base_tmp = tempfile.mkdtemp(prefix="shards")
    logs_dir = os.path.join(base_tmp, "logs")
    os.makedirs(logs_dir)
    env = _shard_env(defaulted_env)
    # Largest first: the biggest units start early instead of becoming the tail. Declared
    # SERIAL_UNITS wait for the parallel phase to finish, then run alone.
    order = sorted(range(len(units)), key=lambda i: (-sizes.get(units[i], 0), i))
    queue = collections.deque(i for i in order if units[i] not in SERIAL_UNITS)
    serial = collections.deque(i for i in order if units[i] in SERIAL_UNITS)
    lock = threading.Lock()
    done = {}
    printed = [0]
    result = ShardResult()
    start = time.monotonic()

    def _flush_in_order():
        while printed[0] < len(units) and printed[0] in done:
            i = printed[0]
            path = os.path.join(logs_dir, "u%d.log" % i)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                text = ""
            if text:
                out.write(text if text.endswith("\n") else text + "\n")
            result.add_payload(done[i])
            printed[0] += 1
        out.flush()

    def _drive(widx):
        worker = _Worker(widx, tests_dir, base_tmp, env)
        try:
            while True:
                with lock:
                    if not queue:
                        return
                    i = queue.popleft()
                log = os.path.join(logs_dir, "u%d.log" % i)
                payload = worker.ask(units[i], log)
                if payload is None or "crash" in payload:
                    rc = worker.proc.poll()
                    if payload is not None:
                        with open(log, "a", encoding="utf-8") as fh:
                            fh.write(payload["crash"])
                    payload = _died_payload(loader, units[i], rc, log)
                    if rc is not None:
                        worker.close(kill=True)
                        worker = _Worker(widx, tests_dir, base_tmp, env)
                with lock:
                    done[i] = payload
                    _flush_in_order()
        finally:
            worker.close()

    threads = [threading.Thread(target=_drive, args=(w,), daemon=True)
               for w in range(max(1, min(jobs, len(queue))))]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if serial:
            queue.extend(serial)
            _drive(len(threads))
    finally:
        shutil.rmtree(base_tmp, ignore_errors=True)
    elapsed = time.monotonic() - start
    for flavour, items in (("ERROR", result.errors), ("FAIL", result.failures)):
        for test, tb in items:
            out.write(SEP1 + "\n%s: %s\n" % (flavour, test) + SEP2 + "\n%s\n" % tb)
    out.write(SEP2 + "\n")
    out.write("Ran %d test%s in %.3fs (sharded: %d unit(s) on %d worker(s), dev #926)\n\n"
              % (result.testsRun, "" if result.testsRun == 1 else "s", elapsed, len(units),
                 len(threads)))
    infos = []
    if result.failures:
        infos.append("failures=%d" % len(result.failures))
    if result.errors:
        infos.append("errors=%d" % len(result.errors))
    if result.skipped:
        infos.append("skipped=%d" % len(result.skipped))
    if result.expectedFailures:
        infos.append("expected failures=%d" % len(result.expectedFailures))
    if result.unexpectedSuccesses:
        infos.append("unexpected successes=%d" % len(result.unexpectedSuccesses))
    out.write(("OK" if result.wasSuccessful() else "FAILED")
              + (" (%s)" % ", ".join(infos) if infos else "") + "\n")
    out.flush()
    return result

