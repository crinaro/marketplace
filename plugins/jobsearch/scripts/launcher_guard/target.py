"""May this engine copy write the launcher and `engine_root` under this home? (dev #988 / public #242, trap 10)

A test ran `migrate.py --hook` from a temp fixture copy with the caller's real `HOME`, and the launcher heal rewrote the
owner's `~/.claude/jobsearch/run` and `engine_root` to fixture paths: every later run exited "No usable engine". Isolating
`HOME` in each test is discipline per call site and failed twice (dev #165, this issue), so the writer refuses instead:

1. An engine copy under the platform's temp directory never writes a home that is not under it. A test that isolates
   `HOME` puts both under temp and is unaffected; a test that forgot is refused. Temp is `tempfile.gettempdir()` alone,
   no literal `/tmp/` markers, so a child given its own `TMPDIR` sees one consistent answer on every platform.
2. A heal never bakes a `CACHE` directory that does not exist under the home it writes: the launcher it would leave
   resolves nothing there, so replacing whatever is on disk can only make a run worse. Explicit installs skip this one
   (`cache_dir=None`): a checkout install may legitimately precede any cache.

Pure: reads the filesystem's shape only, writes nothing, logs nothing; the caller records the refusal.
"""

import os
import tempfile


def _under(path, root):
    """Is `path` (realpath'd) `root` or inside it?"""
    p, r = os.path.realpath(path), os.path.realpath(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def is_temp(path):
    """Is `path` under the platform's temp directory, as `tempfile.gettempdir()` answers it?"""
    try:
        return _under(path, tempfile.gettempdir())
    except Exception:                                  # noqa: BLE001 — no temp dir is "not temp"
        return False


def cache_dir(home_dir, marketplace, plugin):
    """The `CACHE` directory a launcher rendered for (marketplace, plugin) resolves under the home whose
    `.claude/jobsearch` is `home_dir`."""
    return os.path.join(os.path.dirname(home_dir), "plugins", "cache", marketplace, plugin)


def refusal(home_dir, engine, cache=None):
    """Why writing under `home_dir` from `engine` must not happen, or None when it may."""
    if is_temp(engine) and not is_temp(home_dir):
        return ("the engine copy %s is under the temp directory but %s is not: a test or tool running from a temp "
                "copy must give it a scratch HOME" % (engine, home_dir))
    if cache is not None and not os.path.isdir(cache):
        return ("the launcher would name %s, which does not exist under this home, so it would resolve no engine"
                % cache)
    return None
