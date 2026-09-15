#!/usr/bin/env python3
"""The loud line, in the owner's own session — dev #351.

⭐⭐ THE FAILURE THIS EXISTS FOR — three releases (0.44.0, 0.46.0, 0.47.0) shipped, were
verified on the artifact, and never reached the owner's machine. The registered marketplace
clone was stuck at 0.43.0 because `autoUpdate` was OFF for it — a documented, legitimate
per-machine setting (third-party marketplaces default to off) — and NOTHING on the owner's own
machine said so between releases. `scripts/check_install.py` already detects the exact gap (its
AUTO-UPDATE SETTING section, dev #84) and `scripts/check_delivery.py` already reports it, but
both are MAINTAINER tools: neither runs on the owner's machine between releases, and
`delivery-verifier` saw the gap at 0.46.0 and it was read as expected lifecycle rather than acted
on. This is the mechanism half of the fix: a check that runs in the owner's own SessionStart,
from `migrate.py`'s existing hook, the same way `heal_install.py` and `install_launcher.py`
already do for install state.

⚠️ NO NETWORK, EVER. A SessionStart hook runs on every single session; a `git ls-remote` or
`git fetch` there would make every session pay a network round trip (or hang, or fail loudly) for
a courtesy line. So the "newer" version this reports is never the true published latest — it is
only what THIS MACHINE's already-registered marketplace clone happens to have on disk right now,
which can itself be stale (dev #125's own lifecycle: a desktop-app-spawned session's clone
refreshes only at app (re)start). Say that honestly: the line always phrases the clone's version
as "at least" a floor, never a confirmed ceiling.

⭐ SELF-CONTAINED ON PURPOSE. `scripts/check_install.py` (marketplace repo `scripts/`) already
has this exact AUTO-UPDATE SETTING read — `autoupdate_state()` — and `scripts/check_delivery.py`
already reads a marketplace clone's published catalog the same shape `clone_plugin_version()`
below does, one hop further out (a fresh clone of the REMOTE, not the local clone already on
disk). Neither is imported here: both live in the marketplace repo's own `scripts/`, which does
NOT ship with the plugin (`scripts/publish_manifest.py`'s `DEV_ONLY_SCRIPTS`/classification), so a
shipped hook that imported either would work in this checkout and crash on every real install —
exactly the shape `publish_manifest.py`'s "a shipped file may not instruct a script that does not
ship" gate (GitHub #58) exists to catch. The ~15-line local-settings read is duplicated here
instead: that is the one kind of duplication this repo's own scripts explicitly tolerate — the
banned duplication is remote GIT PLUMBING (`check_install.py`'s own docstring, on why it reuses
`check_delivery.ls_remote_head()` instead of re-shelling out itself), and there is none here.

Reuses `heal_install.py`'s own `find_install()` / `disk_version()` / `plugins_dir_default()` /
`engine_root_default()` rather than re-deriving "is this actually an installed copy, and which
one" a second way — that predicate (matching `installed_plugins.json` by realpath) is exactly
adr-014's own evidence for "this is a real install, not a checkout, CI clone or test tree," and
`plugin_id`'s `name@marketplace` shape hands back the marketplace identity for free.

⭐ public #104 also reuses `heal_install.py`'s `clone_path_for()` — the `known_marketplaces.json`
-> `installLocation` lookup below used to be inlined here a second time; `heal_install.py`'s own
truncation repair needs the identical lookup to find a clone to `git show` against, so it moved
there and this module calls it instead of re-deriving it. One resolver, not two.

FAILS OPEN, ALWAYS — same rule as every other SessionStart housekeeping step in this hook chain.
`check()` itself does NOT swallow its own exceptions (unlike `heal_install.heal()`): dev #351's
own plant forces it to raise, and the failure the plant exists to prove is that migrate.py's
OUTER envelope catches it, prints something a person can see, and still exits 0 — a check
wrapping its own exceptions would make that plant untestable from the outside.

Silent (empty `lines`) whenever there is nothing to say: current with the local clone AND
autoUpdate confirmed on, or nothing installed here to compare, or the local state needed to
answer at all is not resolvable. Never blocks, never exits non-zero on its own (the CLI's exit
code is always 0 — this is a courtesy notice, not a gate).

Usage:
    python3 check_update_available.py                    # the real install, if this is one
    python3 check_update_available.py --root P --plugins-dir D --settings S --known K
                                                          # test seam — every path explicit

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import heal_install  # noqa: E402 — reuse find_install()/disk_version(), never re-derive

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _semver(s):
    """A comparable tuple, or None when `s` does not look like plain semver — never guesses at
    an ordering between two things this cannot actually compare."""
    if not s or not _SEMVER_RE.match(str(s).strip()):
        return None
    try:
        return tuple(int(x) for x in str(s).strip().split("."))
    except Exception:                                  # noqa: BLE001
        return None


def autoupdate_state(name, settings_path, known_path):
    """Is auto-update ON for marketplace `name`, per THIS machine's local settings — no network.

    Deliberately duplicated from `scripts/check_install.py`'s `autoupdate_state()` (dev #84)
    rather than imported — see this module's own docstring for why a shipped hook cannot import
    a script that does not ship. Same contract: True/False/None, where None means "registered in
    neither file," never "off." Either file naming the marketplace counts; only the settings.json
    key differs (`extraKnownMarketplaces`) from known_marketplaces.json's own top-level shape.
    """
    sources = []
    for path, key in ((settings_path, "extraKnownMarketplaces"), (known_path, None)):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            sources.append((data.get(key) or {}) if key else (data or {}))
        except Exception:                              # noqa: BLE001 — absent/unreadable is "unseen"
            pass
    seen = [src[name] for src in sources if name in src]
    return None if not seen else any(bool(e.get("autoUpdate")) for e in seen)


def clone_plugin_version(clone_path, plugin_name):
    """The version `plugin_name`'s plugin.json names at THIS machine's already-registered
    marketplace clone's CURRENT checkout — no `git fetch`, no `git ls-remote`, nothing network:
    only files this clone already has on disk. The local-disk twin of
    `check_delivery.py`'s `step_published_catalog` (which reads a fresh clone of the remote); the
    one hop this function stops short of is exactly the hop a SessionStart hook may never take
    (dev #351: no network in a hook, ever).

    Returns (version, None) or (None, reason) — never guesses when the clone cannot answer.
    """
    mp = os.path.join(clone_path, ".claude-plugin", "marketplace.json")
    try:
        with open(mp, encoding="utf-8") as fh:
            cat = json.load(fh)
    except (OSError, ValueError) as e:
        return None, "could not read %s: %s" % (mp, e)
    entry = next((p for p in cat.get("plugins") or [] if p.get("name") == plugin_name), None)
    if entry is None:
        return None, ("the local clone's marketplace.json (%s) lists no plugin named %r"
                      % (mp, plugin_name))
    src = (entry.get("source") or "").lstrip("./").rstrip("/") or ("plugins/%s" % plugin_name)
    pj = os.path.join(clone_path, src, ".claude-plugin", "plugin.json")
    try:
        with open(pj, encoding="utf-8") as fh:
            version = json.load(fh).get("version")
    except (OSError, ValueError) as e:
        return None, "could not read %s: %s" % (pj, e)
    if not version:
        return None, "%s names no version" % pj
    return version, None


def build_line(marketplace, plugin_name, installed, clone_version, au_state):
    """The one line to print, or None when there is nothing worth saying.

    Silent ONLY when both hold: this machine's clone names nothing newer than what is running,
    AND autoUpdate is CONFIRMED on for `marketplace`. Every other combination — behind, OFF, or
    simply unconfirmed — gets a line, because each of those alone is worth an owner seeing it:
    dev #351's own repro had versions EQUAL with autoUpdate off, and the off half alone is the
    thing worth saying (a later release will not arrive on its own either)."""
    behind = False
    inst_t, clone_t = _semver(installed), _semver(clone_version)
    if inst_t is not None and clone_t is not None:
        behind = inst_t < clone_t

    if au_state is True:
        au_clause = None
    elif au_state is False:
        au_clause = ("autoUpdate is OFF for %s — releases will not arrive on their own"
                     % marketplace)
    else:
        au_clause = ("autoUpdate could not be confirmed for %s (not registered in "
                     "settings.json or known_marketplaces.json)" % marketplace)

    if not behind and au_clause is None:
        return None

    # ⚠️ "at least" — this machine never asks the network here (dev #351), so the clone's own
    # version is a FLOOR on the true published latest, never a confirmed ceiling. Say only what
    # is actually known: the clone itself can be behind the real published remote.
    where = ("%s is running; at least %s is in the marketplace clone" % (installed, clone_version)
             if behind else
             "%s is running, matching the marketplace clone" % installed)

    if au_clause:
        msg = "⚠️ %s %s and %s." % (plugin_name, where, au_clause)
    else:
        msg = ("⚠️ %s %s — autoUpdate is on for %s, so this should have "
              "arrived already and has not yet." % (plugin_name, where, marketplace))
    msg += (" Update: claude plugin marketplace update %s && claude plugin update %s@%s"
           % (marketplace, plugin_name, marketplace))
    return msg


def check(plugins_dir=None, root=None, settings_path=None, known_path=None):
    """(verdict, lines). Does NOT swallow its own exceptions — see this module's docstring on
    why the caller (migrate.py) owns the try/except, and dev #351's own plant.

    verdict: not-installed | no-version | no-clone | clone-unreadable | current | flagged
    """
    plugins_dir = plugins_dir or heal_install.plugins_dir_default()
    root = root or heal_install.engine_root_default()

    plugin_id, entry = heal_install.find_install(plugins_dir, root)
    if not plugin_id or "@" not in plugin_id:
        return "not-installed", []
    plugin_name, marketplace = plugin_id.split("@", 1)

    installed = heal_install.disk_version(root) or (entry or {}).get("version")
    if not installed:
        return "no-version", []

    known_path = known_path or os.path.join(plugins_dir, "known_marketplaces.json")
    settings_path = settings_path or os.path.join(os.path.expanduser("~"), ".claude",
                                                  "settings.json")
    clone_path = heal_install.clone_path_for(marketplace, plugins_dir, known_path)
    if not clone_path:
        return "no-clone", []

    clone_version, _reason = clone_plugin_version(clone_path, plugin_name)
    if not clone_version:
        return "clone-unreadable", []

    au = autoupdate_state(marketplace, settings_path, known_path)
    line = build_line(marketplace, plugin_name, installed, clone_version, au)
    if not line:
        return "current", []
    return "flagged", [line]


def check_default():
    """What `migrate.py --hook` calls: the running install, the real plugins dir and settings."""
    return check()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="an installed copy to diagnose (default: the one running)")
    ap.add_argument("--plugins-dir", help="default: CLAUDESEARCH_PLUGINS_DIR or ~/.claude/plugins")
    ap.add_argument("--settings", help="default: ~/.claude/settings.json")
    ap.add_argument("--known", help="default: <plugins-dir>/known_marketplaces.json")
    args = ap.parse_args()
    root = os.path.abspath(args.root) if args.root else None
    verdict, lines = check(plugins_dir=args.plugins_dir, root=root,
                           settings_path=args.settings, known_path=args.known)
    if lines:
        print("\n".join(lines))
    else:
        print("jobsearch: update-availability check (%s) — nothing to report." % verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
