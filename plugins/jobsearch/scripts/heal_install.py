#!/usr/bin/env python3
"""Startup self-heal for the install manifest (marketplace issue #11, adr-014).

⭐ WHY THIS EXISTS
------------------
Neither `claude plugin install` nor `claude plugin update` rewrites the per-plugin manifest under
`~/.claude/plugins/.install-manifests/` — verified twice on consecutive releases on 2026-08-11,
including a full uninstall-then-reinstall cycle that left the manifest byte-identical (same mtime,
same `createdAt`, same file count). `installed_plugins.json` moves correctly — `installPath` and
`gitCommitSha` both update — while the manifest keeps describing the PREVIOUS version. The
release gate `the install verification` then reports drift on every release, and until this script the
repair was a hand edit — the exact "and then someone runs a command" failure the rulebook forbids.

So the engine heals it itself, at session start, from the same `SessionStart` hook that already
migrates profile data (`migrate.py --hook`): one mechanism keeps both the user's DATA and their
INSTALL current with the running version.

## ⭐⭐ THE SCOPE RULE: HEAL ONLY THE MISMATCH THAT IS EXPLAINED

The manifest exists to detect tampering and corruption. Regenerating whenever hashes mismatch
would turn `the install verification` into a script that erases its own failure. The one mismatch this
script repairs is the installer defect, stated as a testable condition:

    EXPLAINED (healed)      the manifest's recorded hash of `.claude-plugin/plugin.json` differs
                            from the file on disk — the version-carrying file itself moved —
                            AND `installed_plugins.json` records the same version the disk does
                            (i.e. the installer RAN and updated everything except the manifest).

    UNEXPLAINED (loud,      same version on both sides but hashes differ; or the version file
    never written)          was never recorded; or `installed_plugins.json` disagrees with the
                            disk. That is corruption or tampering, not the installer defect,
                            and it must stay visible until a human decides.

    MISSING MANIFEST        reported, never fabricated. First install demonstrably writes one,
    (loud, never written)   so absence is anomalous — inventing a baseline would stamp
                            install-time provenance on files this script cannot vouch for.

⚠️ The write target is a file OWNED BY CLAUDE CODE. Schema observed 2026-08-11:
`{pluginId, createdAt, files}`. A heal preserves every field it does not understand, replaces
only `files`, appends a `heals` audit record, and leaves the replaced content beside the manifest
as `<name>.json.bak-heal` — preserve, then transform. A future Claude Code build that rewrites
manifests itself simply finds nothing to heal.

⚠️ FAILS OPEN, ALWAYS — same rule as `migrate.py`: housekeeping must never block a session.
And silent when healthy: the hook output is for things a person should see.

The guard question (adr-010) is resolved deliberately in adr-014, not routed around: this script
is the ONE sanctioned writer of a manifest, and `guard_engine_writes.py` now denies Write/Edit
tool calls into `.install-manifests/` unconditionally, so a session cannot hand-"repair" the
tamper record the way it was hand-repaired twice on 2026-08-11.

## ⭐⭐ public #104 — a NARROWER, CLONE-VERIFIED repair inside the same-version case

The scope rule above was written as a strict binary: a version move is the one explained
mismatch, everything else stays loud. 0.49.0 found a third shape neither branch fits, diagnosed
by delivery-verifier (`…/scratchpad/drift-0-49-0.md`): the installer wrote
`scripts/generate_dashboard.py` and its manifest entry as two separate steps, and the manifest
hash was computed while the write was still in flight — the recorded hash was `sha256(b"")`, the
hash of zero bytes, while the file on disk was (a few minutes later) byte-identical to the
published release. Same version on both sides, so ADR-014's own test read this as corruption or
tampering and correctly refused to touch it — refusing was RIGHT given what the script could see,
and also left a genuinely truncated-or-stale-recorded file unrepaired every session after.

The fix is not widening the binary — it is a **third, independently verifiable** signal this
script did not have before: THIS MACHINE's own already-registered marketplace clone, at the exact
`gitCommitSha` `installed_plugins.json` already recorded for this install. `git show
<sha>:plugins/<name>/<path>` against that local clone costs no network (the clone is already on
disk, or it is not, and this stays loud when it is not — see below) and gives a THIRD value to
compare a drifted file's manifest-recorded hash and on-disk hash against. Per drifted path:

    disk == clone                        the manifest record is stale (the installer's own
                                          empty-file race, or any other bad recorded hash) —
                                          disk is verifiably the current release, so only the
                                          MANIFEST is rewritten for that path.
    disk is 0 bytes, manifest == clone   the file on disk is truncated — the ONE content shape
                                          that can never legitimately be a deliberate edit — and
                                          the manifest already correctly recorded the release, so
                                          only the FILE is re-copied from the clone.
    anything else                        including disk merely DIFFERENT from clone (a one-byte
                                          edit is exactly as explicable as tampering — "0 bytes"
                                          is the only content shape this script trusts as
                                          unintentional) — stays exactly as loud as the pre-#104
                                          behaviour, nothing written.

**All-or-nothing across the drifted set, on purpose.** If EVERY drifted path resolves to one of
the first two rows, the repair applies; if even one resolves to the third row (or the clone/commit
itself cannot answer — absent clone, unknown sha, the release commit never fetched), NOTHING is
written and the whole thing falls through to the original unexplained/loud path unchanged. A
mixed "some safely explained, one questionable" set is exactly the ambiguous case ADR-014 says
must stay loud, not a case to partially paper over. This also means `missing`/`vanished` entries
(a file absent from one side entirely) are never in scope for this repair — only same-path
content drift where the clone can arbitrate is, matching what was actually observed and
diagnosed; a file appearing or disappearing wholesale is a different question this script still
declines to answer on its own.

The guard question (adr-010) is the same guard as above — no session-side rewrite either way; this
is the same sanctioned mechanical writer, just able to tell two more shapes of drift apart.

Usage:
    python3 heal_install.py            # heal if explained; repair if clone-verified; loud if not
    python3 heal_install.py --check    # report only; writes nothing
    python3 heal_install.py --root P   # diagnose an explicit installed copy (test seam, and
                                       # lets release-manager point it at a cache path)

Exit codes: 0 healthy/healed/repaired/not-installed · 1 unexplained/no-manifest (so it can serve
as a check) — but `migrate.py` calls `heal()` in-process and keeps its own always-0 contract.

Python 3.9+. Standard library only.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _diag import log as diag

# Mirror scripts/the install verification in the marketplace repo: transient files the installer never
# records. Recording them would guarantee false drift on the very next session.
IGNORE_DIRS = ("__pycache__", ".git", ".in_use")
IGNORE_SUFFIX = (".pyc", ".pyo")
# Host-written metadata files: neither the installer's own defect nor an actor's tampering, just
# the filesystem doing what it always does (adr-014's residual-risk note, public #38). Named, not
# globbed, so this stays a deliberate allowlist rather than swallowing something that matters.
IGNORE_FILES = (".DS_Store",)
PLUGIN_JSON = os.path.join(".claude-plugin", "plugin.json")
MAX_HEAL_RECORDS = 10
# public #104: the sentinel a hasher produces for a file it read while the installer's own write
# to that same file was still in flight (open-for-write, not yet flushed) — the exact shape the
# 0.49.0 incident's manifest entry for `scripts/generate_dashboard.py` carried.
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
GIT_TIMEOUT = 10


def plugins_dir_default():
    """`CLAUDESEARCH_PLUGINS_DIR` is a test seam, same shape as CLAUDESEARCH_DIAG_LOG — the
    suite must exercise this against a synthetic plugins dir, never the live install."""
    return (os.environ.get("CLAUDESEARCH_PLUGINS_DIR")
            or os.path.join(os.path.expanduser("~"), ".claude", "plugins"))


def engine_root_default():
    """The installed copy this code is physically running from. realpath, like
    `_root.engine_root()`: the engine is where the FILE IS."""
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def interesting(rel):
    parts = rel.split(os.sep)
    if any(p in IGNORE_DIRS for p in parts):
        return False
    if os.path.basename(rel) in IGNORE_FILES:
        return False
    return not rel.endswith(IGNORE_SUFFIX)


def tree_hashes(root):
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            p = os.path.join(base, f)
            rel = os.path.relpath(p, root)
            if not interesting(rel):
                continue
            try:
                with open(p, "rb") as fh:
                    out[rel] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                pass
    return out


def disk_version(root):
    try:
        with open(os.path.join(root, PLUGIN_JSON), encoding="utf-8") as fh:
            return json.load(fh).get("version") or ""
    except Exception:
        return ""


def find_install(plugins_dir, root):
    """(plugin_id, entry) for the installed copy at `root`, or (None, None).

    Matching by realpath(installPath) is the safety property that matters most here: a checkout,
    a CI clone, or a test tree is never an installPath, so running this code from anywhere but a
    genuine install finds nothing and writes nothing.
    """
    try:
        with open(os.path.join(plugins_dir, "installed_plugins.json"), encoding="utf-8") as fh:
            plugins = json.load(fh).get("plugins") or {}
    except Exception:
        return None, None
    want = os.path.realpath(root)
    for plugin_id, entries in plugins.items():
        for entry in entries or []:
            path = (entry or {}).get("installPath")
            if path and os.path.realpath(path) == want:
                return plugin_id, entry
    return None, None


def clone_path_for(marketplace, plugins_dir, known_path=None):
    """THIS MACHINE's already-registered marketplace clone directory for `marketplace`, or None.

    The ONE resolver for "where is the local clone of this marketplace" — `check_update_available
    .py`'s `clone_plugin_version()` reads that clone's `plugin.json` for a version comparison,
    and `_try_clone_repair()` below reads a file's published bytes out of it via `git show`; both
    reuse this rather than each re-deriving the `known_marketplaces.json` -> `installLocation`
    lookup a second way (public #104's build note: "reuse that resolver, never a second")."""
    known_path = known_path or os.path.join(plugins_dir, "known_marketplaces.json")
    try:
        with open(known_path, encoding="utf-8") as fh:
            known = json.load(fh)
        clone_path = (known.get(marketplace) or {}).get("installLocation")
    except Exception:                                  # noqa: BLE001 — unreadable is "unresolved"
        return None
    if not clone_path or not os.path.isdir(clone_path):
        return None
    return clone_path


def _clone_file_bytes(clone_path, sha, repo_rel_path, timeout=GIT_TIMEOUT):
    """The published bytes of `repo_rel_path` at `sha`, read out of the already-registered LOCAL
    clone via `git show <sha>:<path>` — no network, no `git fetch`: only objects the clone
    already has. Returns (bytes, None) on success, or (None, reason) when the clone, the commit,
    or the path at that commit cannot be resolved — every one of those stays loud rather than
    guessing (public #104's build note: "if the clone or commit is absent -> stay loud,
    unchanged")."""
    if not sha:
        return None, "no gitCommitSha recorded for this install"
    spec = "%s:%s" % (sha, repo_rel_path.replace(os.sep, "/"))
    try:
        r = subprocess.run(["git", "-C", clone_path, "show", spec],
                           capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "git show failed (%s: %s)" % (type(e).__name__, e)
    if r.returncode != 0:
        detail = (r.stderr or b"").decode("utf-8", "replace").strip()
        return None, detail or ("git show exited %d" % r.returncode)
    return r.stdout, None


def _try_clone_repair(root, plugins_dir, plugin_id, entry, doc, disk, recorded, drifted,
                      apply_it):
    """public #104: a narrower repair INSIDE the same-version-drift case, verified against the
    marketplace clone rather than assumed. See the module docstring's "public #104" section for
    the three-way classification. Returns (verdict, lines) when every drifted path was safely
    classified (and, if `apply_it`, repaired); None when this repair does not apply at all — the
    caller falls through to the original unexplained/loud path, byte-for-byte unchanged.

    `doc` is the FULL loaded manifest document (mutated in place for any manifest-side repair,
    same object `_heal()` will then serialize) — never the filtered `recorded` copy, so every
    manifest entry this repair does not touch (including one for a file this script otherwise
    ignores) survives exactly as it was.
    """
    plugin_name, sep, marketplace = plugin_id.partition("@")
    if not sep:
        return None
    clone_path = clone_path_for(marketplace, plugins_dir)
    if not clone_path:
        return None
    sha = (entry or {}).get("gitCommitSha")
    if not sha:
        return None

    # path -> ("manifest", clone_hash) | ("disk", clone_bytes)
    classification = {}
    for path in drifted:
        repo_rel = "plugins/%s/%s" % (plugin_name, path)
        content, _reason = _clone_file_bytes(clone_path, sha, repo_rel)
        if content is None:
            return None                                # clone/commit/path unresolvable — stay loud
        clone_hash = hashlib.sha256(content).hexdigest()
        if disk[path] == clone_hash:
            classification[path] = ("manifest", clone_hash)
        elif disk[path] == EMPTY_SHA256 and recorded[path] == clone_hash:
            # ⚠️ scoped to the UNAMBIGUOUS truncation signature — an empty file — and nothing
            # broader. A disk file that is merely DIFFERENT from the clone (edited, one byte or
            # a whole rewrite) is NOT safely assumed to be "truncated": it is exactly as
            # explicable as a genuine edit, so it stays in the loud branch below. Only "0 bytes"
            # is a shape content can never legitimately take (public #104's own incident).
            classification[path] = ("disk", content)
        else:
            return None                                # ambiguous / looks edited — stay loud

    if not apply_it:
        diag("heal_install", verdict="would-repair", files=len(classification))
        return "would-repair", [
            "  would repair %d file(s) against the marketplace clone at the recorded "
            "gitCommitSha (public #104):" % len(classification),
            "  " + ", ".join(sorted(classification))]

    lines = []
    manifest_touched = []
    disk_touched = []
    for path in sorted(classification):
        kind, payload = classification[path]
        if kind == "manifest":
            doc.setdefault("files", {})[path] = payload      # payload: clone_hash == disk hash
            manifest_touched.append(path)
            lines.append("  ✅ manifest repaired: %s (installer recorded an empty file)" % path)
        else:
            target = os.path.join(root, path)
            tmp = target + ".tmp-heal"
            try:
                with open(tmp, "wb") as fh:
                    fh.write(payload)
                os.replace(tmp, target)
            except OSError as e:
                diag("heal_install", verdict="repair-write-failed", reason=type(e).__name__)
                return "error", [
                    "  ⚠️ could not repair %s (%s: %s) — nothing else in this repair pass was "
                    "written." % (path, type(e).__name__, e)]
            disk_touched.append(path)
            lines.append("  ✅ engine file repaired: %s (was truncated)" % path)

    if manifest_touched:
        man_path = os.path.join(plugins_dir, ".install-manifests", "%s.json" % plugin_id)
        try:
            with open(man_path, "rb") as fh:
                old_bytes = fh.read()
            with open(man_path + ".bak-heal", "wb") as fh:
                fh.write(old_bytes)
        except OSError as e:
            diag("heal_install", verdict="backup-failed", reason=type(e).__name__)
            return "error", ["  ⚠️ could not preserve the old manifest (%s) — healed nothing "
                             "in this repair pass." % e]
        ver = disk_version(root)
        heals = doc.setdefault("heals", [])
        heals.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "by": "jobsearch heal_install (public #104)", "toVersion": ver,
                      "reason": "clone-verified-repair", "manifestRepaired": len(manifest_touched),
                      "diskRepaired": len(disk_touched)})
        del heals[:-MAX_HEAL_RECORDS]
        tmp = man_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=1)
                fh.write("\n")
            os.replace(tmp, man_path)                  # atomic: never a half-written manifest
        except OSError as e:
            diag("heal_install", verdict="write-failed", reason=type(e).__name__)
            return "error", ["  ⚠️ manifest rewrite failed (%s) — old manifest left in place; "
                             "%d file(s) on disk were already repaired." % (e, len(disk_touched))]

    diag("heal_install", verdict="repaired", manifest_repaired=len(manifest_touched),
        disk_repaired=len(disk_touched))
    lines.insert(0, "  engine tree repaired: %d file(s)" % len(classification))
    return "repaired", lines


def heal(root, plugins_dir, apply_it=True):
    """Returns (verdict, lines). Never raises.

    verdict: not-installed | healthy | healed | would-heal | repaired | would-repair |
             unexplained | no-manifest | error
    """
    try:
        return _heal(root, plugins_dir, apply_it)
    except Exception as e:                     # noqa: BLE001 — fails open, deliberately
        diag("heal_install", verdict="error", reason=type(e).__name__)
        return "error", ["  ⚠️ install self-heal skipped (%s: %s)" % (type(e).__name__, e)]


def _heal(root, plugins_dir, apply_it):
    plugin_id, entry = find_install(plugins_dir, root)
    if not plugin_id:
        diag("heal_install", verdict="not-installed")
        return "not-installed", []

    man_path = os.path.join(plugins_dir, ".install-manifests", "%s.json" % plugin_id)
    try:
        with open(man_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        recorded = {k: v for k, v in (doc.get("files") or {}).items() if interesting(k)}
    except Exception:
        diag("heal_install", verdict="no-manifest")
        return "no-manifest", [
            "  ⚠️ no readable install manifest at %s" % man_path,
            "     First install writes one, so its absence is anomalous — nothing was invented",
            "     to replace it. `scripts/the install verification` (marketplace repo) shows the state;",
            "     a reinstall of the plugin is the only writer with install-time authority."]

    disk = tree_hashes(root)
    missing = sorted(k for k in disk if k not in recorded)
    drifted = sorted(k for k in disk if k in recorded and recorded[k] != disk[k])
    vanished = sorted(k for k in recorded if k not in disk)
    if not (missing or drifted or vanished):
        diag("heal_install", verdict="healthy", files=len(disk))
        return "healthy", []

    ver = disk_version(root)
    explained = (PLUGIN_JSON in recorded and PLUGIN_JSON in disk
                 and recorded[PLUGIN_JSON] != disk[PLUGIN_JSON]
                 and bool(ver) and entry.get("version") == ver)
    if not explained:
        # ⭐ public #104 — a narrower, clone-verified repair for the case that is neither the
        # version-move defect above nor genuinely unexplainable: pure content drift on files
        # both sides still agree exist, arbitrated against the marketplace clone at the exact
        # gitCommitSha this install already recorded. All-or-nothing across `drifted`, and
        # never attempted at all when a file appeared or vanished wholesale (`missing`/
        # `vanished` non-empty) — see `_try_clone_repair()`'s own docstring.
        if drifted and not missing and not vanished:
            repaired = _try_clone_repair(root, plugins_dir, plugin_id, entry, doc, disk,
                                         recorded, drifted, apply_it)
            if repaired is not None:
                return repaired
        diag("heal_install", verdict="unexplained", files_disk=len(disk),
             files_manifest=len(recorded), drifted=len(drifted))
        return "unexplained", [
            "  ⛔ install manifest disagrees with the installed files and the mismatch is NOT",
            "     explained by a version move (%d drifted · %d unrecorded · %d vanished, at "
            "version %s)." % (len(drifted), len(missing), len(vanished), ver or "unknown"),
            "     Same-version drift is corruption or tampering, not the installer defect, so",
            "     nothing was rewritten — this stays loud on purpose (adr-014). Compare with",
            "     `scripts/the install verification` in the marketplace repo; a reinstall of the plugin",
            "     is the honest repair once the cause is understood."]

    if not apply_it:
        diag("heal_install", verdict="would-heal", engine=ver)
        return "would-heal", [
            "  would rewrite the install manifest for %s — the installed version (%s) is not the"
            % (plugin_id, ver),
            "  one the manifest records (its recorded `.claude-plugin/plugin.json` differs), which",
            "  is the installer defect of marketplace issue #11 (adr-014)."]

    # ── PRESERVE, THEN TRANSFORM ─────────────────────────────────────────────────────────────
    try:
        with open(man_path, "rb") as fh:
            old_bytes = fh.read()
        with open(man_path + ".bak-heal", "wb") as fh:
            fh.write(old_bytes)
    except OSError as e:
        diag("heal_install", verdict="backup-failed", reason=type(e).__name__)
        return "error", ["  ⚠️ could not preserve the old manifest (%s) — healed nothing." % e]

    doc["files"] = {k: disk[k] for k in sorted(disk)}
    heals = doc.setdefault("heals", [])
    heals.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "by": "jobsearch heal_install (adr-014)", "toVersion": ver,
                  "reason": "version-moved", "filesBefore": len(recorded),
                  "filesAfter": len(disk)})
    del heals[:-MAX_HEAL_RECORDS]
    tmp = man_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
            fh.write("\n")
        os.replace(tmp, man_path)              # atomic: never a half-written manifest
    except OSError as e:
        diag("heal_install", verdict="write-failed", reason=type(e).__name__)
        return "error", ["  ⚠️ manifest rewrite failed (%s) — old manifest left in place." % e]
    diag("heal_install", verdict="healed", engine=ver, files=len(disk))
    return "healed", [
        "  ✅ install manifest healed to %s (%d file(s) recorded; previous content preserved as"
        % (ver, len(disk)),
        "     %s.bak-heal). The mismatch was explained by a version move — the installer" % os.path.basename(man_path),
        "     updates the files and `installed_plugins.json` but not the manifest (issue #11)."]


def heal_default(apply_it=True):
    """What `migrate.py --hook` calls: the running install, the real plugins dir."""
    return heal(engine_root_default(), plugins_dir_default(), apply_it=apply_it)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    ap.add_argument("--root", help="an installed copy to diagnose (default: the one running)")
    args = ap.parse_args()
    root = os.path.abspath(args.root) if args.root else engine_root_default()
    verdict, lines = heal(root, plugins_dir_default(), apply_it=not args.check)
    if lines:
        print("jobsearch: install self-heal (%s)" % verdict)
        print("\n".join(lines))
    elif verdict == "healthy":
        print("Install manifest matches the installed files (%s)." % root)
    elif verdict == "not-installed":
        print("Not an installed copy (%s) — nothing to heal." % root)
    return 1 if verdict in ("unexplained", "no-manifest") else 0


if __name__ == "__main__":
    sys.exit(main())
