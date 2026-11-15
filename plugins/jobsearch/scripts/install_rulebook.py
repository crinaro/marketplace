#!/usr/bin/env python3
"""Copy the engine's rulebook into the user's profile, where it is actually loaded.

⭐ THE PROBLEM THIS SOLVES — a plugin CANNOT ship project context.
`claude plugin tag` says it plainly: *"CLAUDE.md at the plugin root is not loaded as project
context."* Claude Code loads `CLAUDE.md` from the **working directory**, and a run's working
directory is the user's PROFILE, never the plugin. So the rulebook that every rule in this system
depends on reaches a session only if a copy exists in the profile.

Until now each installation solved that by hand — a symlink, or a bespoke sync script.

⭐ THE SOURCE IS `RULEBOOK.md` AT THE PLUGIN ROOT; IT INSTALLS AS THE PROFILE'S `CLAUDE.md`.
The engine-side file is a TEMPLATE and is deliberately not named CLAUDE.md — a CLAUDE.md at the
plugin root is never loaded as project context (the validator warns on exactly that), and naming
a template after the job it cannot do from that location misled two separate reviews into filing
it as inert. The name changes at install time; the content does not.

⚠️⚠️ AND A SYMLINK IS THE ONE SOLUTION THAT MUST NOT BE USED. A committed symlink pointing out of
its own repo **dangles in every clone**, and a dangling symlink reads as an ABSENT FILE — so the
session starts with no rulebook, no agents, and NO ERROR. That is exactly how a job-search session
came up with nothing on 2026-08-05. This script therefore copies a REAL FILE, always.

## What it writes, and why the stamp matters

A copy plus a provenance line naming the engine version it came from. Without the stamp there is
no way to tell a current copy from one made three releases ago — and a stale rulebook is worse
than an absent one, because it is read as authoritative. `--check` compares the stamp and says
whether a re-copy is needed; `doctor.py` can call it.

Usage:
    python3 install_rulebook.py            # copy into the profile (walks up from cwd)
    python3 install_rulebook.py --check    # exit 1 if missing or stale, print why
    python3 install_rulebook.py --dest DIR # explicit profile directory

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root, engine_root, is_tracked_fixture, is_engine_root, looks_like_profile

# ⭐⭐ dev #834 (jobsearch 0.86.0; design-network-first.md section 14.2) -- THE PROVENANCE MARKER CHANGED, ON PURPOSE.
#
# An engine older than 0.86.0 reads a CLAUDE.md for `<!-- installed-from: jobsearch ` in its first 400 characters, and
# a file without it is "unmanaged": its SessionStart hook neither writes nor commits (it prints one line). A file that
# DID carry the old marker, stamped with a version below the older engine's own, it REWRITES to its own rulebook and
# COMMITS ("jobsearch: rulebook refreshed to 0.83.0", measured on the extracted v0.83.0 tag). So on a profile shared
# by two machines, an older machine would silently downgrade this machine's rulebook. 0.86.0 therefore stamps a
# NEW marker that an older engine reads as unmanaged, and its own reader accepts both.
#
# Two invariants, each a test (`test_rulebook_marker.py`): the new stamp does NOT contain `LEGACY_MARKER` (else the
# older engine recognises it), and it is shorter than 400 characters (both readers read 400). The stamp's own text
# tells a person on the older machine what to do, because that engine's line ("move it aside and run
# install_rulebook.py") would be the wrong advice.
STAMP = ("<!-- jobsearch-rulebook %s | managed by the jobsearch plugin; do not edit here, edit the plugin's "
         "RULEBOOK.md. A jobsearch older than 0.86.0 reports this file as not installed by the plugin: update "
         "jobsearch on that machine, do not replace this file. -->")
MARKER = "<!-- jobsearch-rulebook "
LEGACY_MARKER = "<!-- installed-from: jobsearch "

# ⭐ dev #81 — a ~38KB CLAUDE.md landed in the checked-in tests/fixtures/profile/ TWICE during
# the 0.24.0 work. profile_root() legitimately resolves to that fixture when nothing else looks
# like a profile (test_checks.py's own fallback, deliberately, for READS) or when
# CLAUDESEARCH_ROOT is explicitly pointed there — but this script writes, and the fixture is
# GENERATED (make_fixture.py) and must never be hand- or self-edited. `_root.is_tracked_fixture`
# already carried this exclusion for the remembered pointer (`_remember`); this script never
# inherited it. See that module's docstring for why the check stays narrower than
# `is_disposable_profile` — a tempfile.mkdtemp() scratch profile stays a legitimate write target.
_FIXTURE_REFUSAL = (
    "  ⛔ %s is the checked-in test fixture (or lives inside one), not a real profile — "
    "the rulebook writer refuses to read or write there. It is GENERATED, not hand-maintained; "
    "a self-heal write would be silent drift indistinguishable from the real thing.")

# ⭐ dev #87 — the sibling case. `profile_root()`'s own "return CWD" fallback can legitimately
# answer with the ENGINE'S OWN ROOT (a maintenance session, a CI runner, any run with no profile
# anywhere above it and nothing remembered) — and this script WRITES a stamped CLAUDE.md over
# whatever is at `dest_dir`. Landing there and writing would overwrite the engine's OWN
# maintenance rulebook (this repository's real, hand-maintained `CLAUDE.md`) with the profile
# template, in the one checkout every session here depends on. `refresh_if_stale()`'s "unmanaged"
# branch happens to catch this too (the real CLAUDE.md carries no install stamp) — but that
# safety is incidental to a stamp format, not a designed refusal, and `main()`'s direct-write path
# does not check for "unmanaged" at all. Refuse explicitly, the same shape as the fixture case.
_ENGINE_ROOT_REFUSAL = (
    "  ⛔ %s IS THE ENGINE'S OWN ROOT, not a profile — the rulebook writer refuses to read or "
    "write there. profile_root() found no profile anywhere above the working directory and "
    "nothing remembered, and fell back to the CWD, which is this engine checkout. Run this from "
    "inside a real profile, or pass --dest.")

# ⭐ dev #155 — the GENERAL case, of which #81 (fixture) and #87 (engine root) turned out to be
# two instances. `profile_root()`'s last-resort fallback — "return the CWD rather than guessing"
# — is sound for a READER (a caller needing data fails visibly on a missing file). It is not sound
# for a WRITER: a wrong guess doesn't fail visibly, it creates a file in a directory nobody
# nominated. That happened for real — a 38KB stamped CLAUDE.md landed in $HOME, where every
# Claude Code session on the machine loaded job-search rules as its own project context.
#
# The fixture and engine-root guards above are DENYLIST entries: two specific wrong destinations,
# added one incident at a time. $HOME is a third, and a denylist only ever catches the incidents
# already had. This check is the ALLOWLIST instead: refuse unless the destination positively
# carries a profile marker (`config.json` or `data/` — the same test `profile_root()` itself
# walks up looking for). A genuine profile carries one by definition, so any directory that lacks
# both was never a positive identification — it was a fallback guess, and a writer must not act on
# a guess.
#
# ⚠️ This does NOT replace `is_tracked_fixture` or `is_engine_root`, even though the engine root
# currently has neither marker (so it would already be caught below) — the checked-in test
# fixture DOES carry both (it is a synthesized profile by design, generated by make_fixture.py to
# be structurally indistinguishable from a real one) and would sail straight through a
# marker-only test. The two specific guards refuse for reasons this generic one cannot see
# (tracked/generated; identity with the engine's own checkout); this one closes the class they
# don't cover — any OTHER destination profile_root() might fall back to that simply isn't a
# profile at all. Keep all three: allowlist first, then the two denylist entries for the
# marker-carrying exceptions.
_NOT_A_PROFILE_REFUSAL = (
    "  ⛔ %s does not look like a profile (no config.json, no data/) — the rulebook writer "
    "refuses to create one there. This directory was never positively identified as a profile; "
    "it is where profile_root() landed after its last-resort fallback (no CLAUDESEARCH_ROOT, "
    "nothing profile-shaped above the working directory, nothing remembered). Writing a stamped "
    "rulebook into an unclaimed directory is dev #155 — it put a 38KB CLAUDE.md in $HOME, where "
    "every Claude Code session on the machine loaded job-search rules as its own project "
    "context. Run this from inside a real profile (or after 'init_profile.py --scaffold' has "
    "created one), or pass --dest.")


def engine_version():
    path = os.path.join(engine_root(), ".claude-plugin", "plugin.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("version") or "unversioned"
    except Exception:
        return "unversioned"


def source_text():
    src = os.path.join(engine_root(), "RULEBOOK.md")
    with open(src, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_head(dest_file):
    try:
        with open(dest_file, "r", encoding="utf-8") as fh:
            return fh.read(400)
    except OSError:
        return None


def _stamp_of(head):
    """`(kind, version)` of a file's first 400 characters: `("new", v)`, `("legacy", v)`, or `(None, "")` when neither
    marker is there. The new marker is looked for first."""
    i = head.find(MARKER)
    if i != -1:
        return "new", head[i + len(MARKER):].split("|")[0].strip()
    j = head.find(LEGACY_MARKER)
    if j != -1:
        return "legacy", head[j + len(LEGACY_MARKER):].split("|")[0].strip()
    return None, ""


def installed_stamp(dest_file):
    """The version a CLAUDE.md was installed from, finding EITHER marker: `None` when the file is missing, `""` when
    it exists but carries neither marker (not made by this script)."""
    head = _read_head(dest_file)
    if head is None:
        return None
    return _stamp_of(head)[1]


def stamp_kind(dest_file):
    """`"new"` (0.86.0's marker), `"legacy"` (the marker an engine older than 0.86.0 reads) or None (no file, or neither
    marker). It is the KIND alone that makes a legacy file refresh at the engine's own version."""
    head = _read_head(dest_file)
    return None if head is None else _stamp_of(head)[0]


def _vt(v):
    """`(major, minor, patch)` for an `X.Y.Z` string, else None (an `unversioned` engine compares as nothing)."""
    import re
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v or "")
    return tuple(int(g) for g in m.groups()) if m else None


def _is_ahead(have, version):
    a, b = _vt(have), _vt(version)
    return a is not None and b is not None and a > b


_AHEAD_LINE = ("  the rulebook was installed by jobsearch %s, newer than this engine (%s); not replaced")
_PIN_LINE = "  ⛔ %s"


def _pin_refusal(dest_dir):
    """The journal's pin refusal for this profile (a profile pinned above this engine is not written to), or None."""
    try:
        import journal
        return journal.pin_refusal(dest_dir)
    except Exception:                                   # noqa: BLE001 -- the pin is a guard, never a new way to fail
        return None


def refresh_if_stale(dest_dir=None, apply_it=True):
    """Keep the installed rulebook current, unattended — returns (verdict, lines).

    ⭐⭐ WHY THIS EXISTS: A RULEBOOK INSTALL WAS "AND THEN THE USER RUNS THIS SCRIPT".
    That is the one thing this marketplace says a change may never be. Nothing called this
    script from any hook, so the only thing keeping a profile's rulebook current was
    somebody remembering — and on 2026-08-13 a live profile was found running rules from
    **0.17.0 while the engine was 0.21.0**. Four minors of rules the sessions never read,
    with no error anywhere, which is precisely the failure this file's own docstring names:
    a stale rulebook is worse than an absent one, because it is read as authoritative.

    Called from the SessionStart hook beside the migration and the install self-heal, so the
    three things that must track the running version now do so together.

    ⚠️ THE UNMANAGED CASE IS A REFUSAL, NOT A REPAIR. A CLAUDE.md with no provenance stamp
    was written by someone, not by this script. Overwriting it unattended would be silent
    data loss of the exact kind `SAFE APPLIES, DESTRUCTIVE REPORTS` forbids — so it says so
    and changes nothing. Same for a symlink, for the same reason.

    ⭐ dev #155 — a FOURTH refusal, `not looks_like_profile(dest_dir)`. `dest_dir` is a WRITER's
    resolution of a READER's fallback chain (`profile_root()`'s own docstring says the CWD
    fallback is sound for a caller that fails visibly on a missing file — never for one that
    creates a file). Before this, an unresolved first run (no env, no profile above the cwd,
    nothing remembered yet) landed on the fallback CWD and this function wrote straight into it —
    once, for real, into $HOME. The fixture and engine-root refusals above do not cover this: they
    are destination-specific denylist entries for two directories that DO carry profile markers
    (the fixture) or are matched by identity (the engine root); this is the allowlist rule that
    subsumes every OTHER wrong landing profile_root() could fall back to.
    """
    dest_dir = dest_dir or profile_root()
    dest_file = os.path.join(dest_dir, "CLAUDE.md")
    version = engine_version()

    if is_tracked_fixture(dest_dir):
        return "fixture", [_FIXTURE_REFUSAL % dest_dir]
    if is_engine_root(dest_dir):
        return "engine-root", [_ENGINE_ROOT_REFUSAL % dest_dir]
    if not os.path.isdir(dest_dir):
        return "no-profile", []
    if not looks_like_profile(dest_dir):
        return "not-a-profile", [_NOT_A_PROFILE_REFUSAL % dest_dir]
    if os.path.islink(dest_file):
        return "symlink", [
            "  ⛔ %s is a SYMLINK — not replaced. Remove it and re-run install_rulebook.py."
            % dest_file]

    have = installed_stamp(dest_file)
    kind = stamp_kind(dest_file)
    if have == "":
        return "unmanaged", [
            "  ⚠️ %s was not installed by this plugin, so it was NOT replaced." % dest_file,
            "     It may hold local edits. Move it aside and run install_rulebook.py to adopt",
            "     the shipped rulebook, or leave it and accept that engine rules are not loaded."]
    # dev #834: a profile pinned above this engine is read-only to it, and a rulebook installed by a NEWER engine is
    # never replaced by this older one (it would be the downgrade the new marker exists to prevent).
    refusal = _pin_refusal(dest_dir)
    if refusal:
        return "pinned-ahead", [_PIN_LINE % refusal]
    if kind == "new" and have == version:
        return "current", []
    if kind == "new" and _is_ahead(have, version):
        return "ahead", [_AHEAD_LINE % (have, version)]

    if not apply_it:
        return ("missing" if have is None else "stale"), [
            "  would install the rulebook into %s (have %s, engine %s)"
            % (dest_file, have or "nothing", version)]

    text = source_text()
    if MARKER in text[:400] or LEGACY_MARKER in text[:400]:
        return "bad-source", ["  ⛔ the engine's RULEBOOK.md already carries a stamp; not installed"]
    try:
        tmp = dest_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(STAMP % version + "\n" + text)
        os.replace(tmp, dest_file)
    except OSError as e:
        return "failed", ["  ⚠️ could not write %s (%s) — rules stay at %s"
                          % (dest_file, e, have or "none")]
    return ("installed" if have is None else "refreshed"), [
        "  rulebook %s -> %s. ⚠️ It loads at SESSION START, so THIS session still has the old one."
        % (have or "none", version)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report staleness; write nothing")
    ap.add_argument("--dest", help="the profile directory (default: resolved from cwd)")
    args = ap.parse_args()

    dest_dir = args.dest or profile_root()
    dest_file = os.path.join(dest_dir, "CLAUDE.md")
    version = engine_version()

    if is_tracked_fixture(dest_dir):
        print(_FIXTURE_REFUSAL % dest_dir, file=sys.stderr)
        return 2

    if is_engine_root(dest_dir):
        print(_ENGINE_ROOT_REFUSAL % dest_dir, file=sys.stderr)
        return 2

    # dev #155 — same guard as refresh_if_stale(): this is a writer too, reachable the same way
    # (no --dest means profile_root(), and that can fall back to an unclaimed CWD on a first run).
    if os.path.isdir(dest_dir) and not looks_like_profile(dest_dir):
        print(_NOT_A_PROFILE_REFUSAL % dest_dir, file=sys.stderr)
        return 2

    have = installed_stamp(dest_file)
    kind = stamp_kind(dest_file)

    # dev #834: a writer checks the pin BEFORE it writes, and never replaces a rulebook a NEWER engine installed.
    refusal = _pin_refusal(dest_dir) if os.path.isdir(dest_dir) else None
    if refusal and not args.check:
        print(_PIN_LINE % refusal, file=sys.stderr)
        return 2
    if kind == "new" and _is_ahead(have, version) and not args.check:
        print(_AHEAD_LINE % (have, version), file=sys.stderr)
        return 2

    if args.check:
        if have is None:
            print("MISSING  %s\n  The session will start with NO rulebook and no error." % dest_file)
            return 1
        if have == "":
            print("UNMANAGED  %s\n  A CLAUDE.md exists but was not installed by this script — it "
                  "may be hand-written or a stale copy. Re-run without --check to replace it, or "
                  "move it aside first if it holds local edits." % dest_file)
            return 1
        if kind == "new" and _is_ahead(have, version):
            print("AHEAD  %s\n%s" % (dest_file, _AHEAD_LINE % (have, version)))
            return 0
        if have != version or kind != "new":
            print("STALE  %s\n  installed from %s (%s marker), engine is %s. A stale rulebook is worse than an "
                  "absent one: it is read as authoritative." % (dest_file, have, kind, version))
            return 1
        print("OK  %s is current (jobsearch %s)." % (dest_file, version))
        return 0

    if os.path.islink(dest_file):
        # Refuse rather than overwrite: the link may be someone's deliberate dev setup, and
        # silently converting it would hide the change. Say what to do.
        print("⛔ %s is a SYMLINK. Remove it first, then re-run.\n"
              "   A symlink out of the repo dangles in every clone, and a dangling symlink reads "
              "as an absent file — the session starts with no rulebook and no error."
              % dest_file, file=sys.stderr)
        return 2

    if not os.path.isdir(dest_dir):
        print("No such directory: %s" % dest_dir, file=sys.stderr)
        return 2

    text = source_text()
    if MARKER in text[:400] or LEGACY_MARKER in text[:400]:
        print("Refusing to install a copy as the source — %s already carries a provenance stamp."
              % os.path.join(engine_root(), "RULEBOOK.md"), file=sys.stderr)
        return 2

    with open(dest_file, "w", encoding="utf-8") as fh:
        fh.write(STAMP % version + "\n" + text)
    print("✅ Installed the rulebook into %s (from jobsearch %s)." % (dest_file, version))
    print("   ⚠️ It loads at SESSION START — this session still has the old one, if any.")
    print("   Edit the PLUGIN's RULEBOOK.md and re-run this; edits here are overwritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
