"""Install-cache hygiene (dev #167): prune old installed copies of this plugin. Machine state, run by `migrate.py`.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import os
import shutil
from migrations.stamp import _SEMVER_RE_STR, ver


# ── install-cache hygiene (dev #167) — owned HERE, never by the launcher ─────────────────────
# A resolver that deletes is the wrong shape for a constantly-running sh script; pruning is a
# deliberate, logged act of the SessionStart hook, with the same envelope discipline as the
# heals above.
CACHE_KEEP_NEWEST = 2
CACHE_PRUNE_AFTER_DAYS = 7


def prune_install_cache(apply_it=True, home=None, now=None):
    """Delete long-superseded installed versions from the plugin cache. Hygiene, not
    correctness: resolution already ignores old versions (the launcher walks newest-complete),
    so nothing here changes what runs — it only stops the cache growing one directory per
    release forever, and shrinks the window in which a stale session can execute a very old
    copy's code.

    The rules, deliberately conservative (CACHE_KEEP_NEWEST / CACHE_PRUNE_AFTER_DAYS):
      - the newest two COMPLETE versions are always kept (complete: scripts/ AND
        .claude-plugin/plugin.json — the launcher's own test);
      - any other complete version is deleted only once it has been superseded for at least
        seven days, measured from the oldest NEWER complete version's manifest mtime — a
        session started before a release landed may legitimately run last week's copy, and
        pruning the code out from under a live session is exactly the failure-lands-hours-
        later shape this plugin keeps scars from;
      - an INCOMPLETE version directory is never touched: it may be mid-sync;
      - the copy running THIS process is never deleted, whatever its age — the trampoline
        normally guarantees pruning runs from the newest copy, but the trampoline fails open.

    Every deletion logs a `cache-pruned` machine event naming the version. `home`/`now` are
    test seams; real runs resolve `$HOME` and the clock. Returns (verdict, lines); verdict:
    pruned | nothing | error. Never raises past its own envelope in main().
    """
    import re
    import time
    import _root
    import install_launcher
    from _diag import log_machine as _diag_machine
    now = time.time() if now is None else now
    try:
        marketplace, plugin = install_launcher._install_identity()
    except Exception as e:                        # noqa: BLE001 — hygiene fails open
        return "error", ["  ⚠️ could not derive the install identity (%s) — nothing pruned."
                         % type(e).__name__]
    cache_root = (os.path.join(home, ".claude", "plugins", "cache") if home
                  else _root.CACHE_ROOT)
    base = os.path.join(cache_root, marketplace, plugin)
    if not os.path.isdir(base):
        return "nothing", []
    try:
        names = sorted((n for n in os.listdir(base) if re.match(_SEMVER_RE_STR, n)),
                       key=ver, reverse=True)
    except OSError:
        return "nothing", []

    def _complete(n):
        d = os.path.join(base, n)
        return (os.path.isdir(os.path.join(d, "scripts"))
                and os.path.isfile(os.path.join(d, ".claude-plugin", "plugin.json")))

    complete = [n for n in names if _complete(n)]
    # Snapshot every manifest mtime BEFORE any deletion: the supersession time of an older
    # version is derived from its newer siblings' manifests, and one of those siblings may
    # itself be pruned earlier in this very loop (newest-first order) — reading mtimes lazily
    # made the age test silently unanswerable for everything older than the first prune.
    mtimes = {}
    for n in complete:
        try:
            mtimes[n] = os.path.getmtime(
                os.path.join(base, n, ".claude-plugin", "plugin.json"))
        except OSError:
            mtimes[n] = None
    running = os.path.realpath(_root.engine_root())
    lines, pruned = [], []
    for i, n in enumerate(complete):
        if i < CACHE_KEEP_NEWEST:
            continue
        d = os.path.join(base, n)
        if os.path.realpath(d) == running:
            lines.append("  kept %s — it is the copy running this very process" % n)
            continue
        newer_times = [mtimes[m] for m in complete[:i] if mtimes[m] is not None]
        if not newer_times:
            continue
        superseded_at = min(newer_times)
        age_days = (now - superseded_at) / 86400.0
        if age_days < CACHE_PRUNE_AFTER_DAYS:
            continue
        if apply_it:
            try:
                shutil.rmtree(d)
            except OSError as e:
                lines.append("  ⚠️ could not prune %s (%s) — left in place" % (n, e))
                continue
            _diag_machine("cache-pruned", version=n, superseded_days=int(age_days))
        pruned.append(n)
    if pruned:
        lines.append("  %s %d superseded version(s) (kept the newest %d complete, pruned "
                     "only past %d days of supersession): %s"
                     % ("✅ pruned" if apply_it else "would prune", len(pruned),
                        CACHE_KEEP_NEWEST, CACHE_PRUNE_AFTER_DAYS, ", ".join(pruned)))
    return ("pruned" if pruned else "nothing"), lines
