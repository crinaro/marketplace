"""Migration 0.17.0: `m_0_17_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import subprocess
from migrations.stamp import KNOWN_PROFILE_ARTIFACTS

VERSION = "0.17.0"


def m_0_17_0(profile, apply_it):
    """0.17.0 — adr-012: the profile is always a git repository; `config.sync.mode` declares
    the remote.

    Seeds the declaration FROM WHAT THE PROFILE ACTUALLY IS — never a default that overwrites
    an existing one: repo with an origin -> "remote"; repo without -> "local-only"; plain
    folder -> ⭐ PRESERVE, THEN TRANSFORM: `git init`, then an initial commit staging the
    profile's known artifacts BY EXPLICIT PATH (never `git add -A` — the list of what the
    initial commit contains is also documentation of what a profile is), then "local-only".
    Additive and reversible by deleting `.git/`; a plain folder has no second writer, so the
    shared-tree scar behind the explicit-path rule cannot recur here, and the rule is kept
    anyway.

    git absent from PATH: report loudly, apply NOTHING, and return not-ok so the schema is
    never stamped — the unstamped migration retries every session, so the condition cannot go
    quiet (adr-012's defined behaviour for its residual uncertainty). An unreadable declared
    mode is likewise refused, never guessed over: `sync.py --set` is the fix, and it validates.
    """
    import sync as _sync
    from _atomic import write_json as _write_json
    cfgpath = os.path.join(profile, "config.json")
    if not os.path.exists(cfgpath):
        return True, ""                 # a data/-only tree; nothing to declare a mode in yet
    try:
        with open(cfgpath, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as e:
        return False, "  ⚠️ config.json is unreadable, so no sync mode was seeded: %s" % e
    try:
        if _sync.parse_mode(cfg):
            return True, ""             # already declared — never overwritten, valid by parse
    except _sync.SyncError as e:
        return False, ("  ⚠️ config.sync.mode exists but cannot be read (%s).\n"
                       "     Nothing was overwritten — fix it with `sync.py --set "
                       "remote|local-only`, which validates first." % str(e)[:120])

    state = _sync.git_state(profile)
    if not state["git"]:
        return False, ("  ⚠️ git is not on PATH, so this profile cannot become a repository and\n"
                       "     no sync mode was seeded. Marketplace installs require git — this\n"
                       "     machine changed since install. Restore git; this retries every "
                       "session.")

    def _git(*a):
        return subprocess.run(["git", "-C", profile] + list(a),
                              capture_output=True, text=True, timeout=30)

    if not apply_it:
        if not state["repo"]:
            return True, ("  would `git init`, commit the profile's known artifacts by explicit "
                          "path, and seed sync.mode: local-only")
        return True, ("  would seed sync.mode: %s (from what the repository is)"
                      % ("remote" if state["origin"] else "local-only"))

    steps = []
    if not state["repo"]:
        r = _git("init", "-q")
        if r.returncode != 0:
            return False, ("  ⚠️ `git init` failed; nothing changed: %s"
                           % (r.stderr.strip() or "unknown")[:160])
        steps.append("git init")
        state = _sync.git_state(profile)

    # An initial commit when the repository has none — covers both the fresh `git init` above
    # and a half-completed earlier attempt. A repo that already has commits is the user's own
    # history; nothing here stages into it.
    if _git("rev-parse", "-q", "--verify", "HEAD").returncode != 0:
        known = list(KNOWN_PROFILE_ARTIFACTS)
        try:
            known += sorted(n for n in os.listdir(profile)
                            if n.endswith(".md") and os.path.isfile(os.path.join(profile, n)))
        except OSError:
            pass
        paths = [p for p in known if os.path.exists(os.path.join(profile, p))]
        r = _git("add", "--", *paths)
        if r.returncode != 0:
            return False, ("  ⚠️ staging the initial commit failed; not stamped: %s"
                           % (r.stderr.strip() or "unknown")[:160])
        ident = []
        if not (_git("config", "user.email").stdout or "").strip():
            # No git identity on this machine. Use a neutral one for THIS commit only via -c —
            # never written into the user's config, and their real identity takes over the
            # moment they set one.
            ident = ["-c", "user.name=jobsearch-migrate", "-c", "user.email=migrate@localhost"]
        r = subprocess.run(["git", "-C", profile] + ident +
                           ["commit", "-q", "-m",
                            "profile becomes a git repository (adr-012 migration)"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, ("  ⚠️ the initial commit failed; not stamped (retries next session): %s"
                           % (r.stderr.strip() or r.stdout.strip() or "unknown")[:160])
        steps.append("initial commit (%d path(s), each named)" % len(paths))

    mode = "remote" if state["origin"] else "local-only"
    cfg.setdefault("sync", {})["mode"] = mode
    _write_json(cfgpath, cfg)           # atomic — never a half-written config.json
    steps.append("sync.mode seeded: %s" % mode)
    return True, "  ✅ " + "; ".join(steps)
