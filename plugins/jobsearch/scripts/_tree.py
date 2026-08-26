#!/usr/bin/env python3
"""The profile tree, as data: the canonical layout, one resolver, and the structure audit.

⭐ WHY THIS EXISTS (public #28). The directory tree is a PRIMARY interface — the candidate
browses the markdown in the desktop app — and it was the only surface that was never designed:
25 entries at root mixing six unrelated categories, an application worksheet misfiled into the
interview-prep directory because applying had no home, and a `nonexistent/` directory nobody's
rules accounted for. The layout below is the six-phase structure the router already renders
(`generate_dashboard.PHASES`), applied to the tree itself.

⭐⭐ A FACT A RUN KNOWS GOES INTO THE QUERYABLE STORE, NEVER INTO NARRATIVE — including this
one. The layout is a TABLE, not prose: `migrate.py`'s tree migration moves what the table
names, every script resolves paths through it, and `--audit` classifies the tree against it.
Three consumers, one definition; they cannot disagree.

⭐ THE RESOLVER FALLS BACK, LOUDLY-AUDITABLY, NEVER SILENTLY-EMPTILY. `path()` returns the
canonical location when it exists — else the legacy location when THAT exists — else the
canonical location (for creation). A missing thing must never read as an empty thing (the
marketplace's trap #2): a profile the migration has not reached yet keeps working through the
fallback, and `--audit` is what says, mechanically, that it has not been migrated.

WHAT DELIBERATELY STAYS AT ROOT — each an anchor, not an oversight:
  config.json, user.json   the profile MARKERS (`_root.py`) and the targets of external
                           absolute-path pointers (gmail-multi's `include`). Moving them
                           silently breaks profile detection for every session and orphans
                           the mail connector — the worst failure shape this repo knows.
  data/                    the machine's queryable store, the second profile marker, and
                           cross-phase by construction. The human browses markdown; the
                           phase PAGES render pipeline state from here.
  CLAUDE.md, README.md,    the four #28 itself names as root's contents,
  handoff.md, log.md       plus the rulebook's install target.
  dashboard.html           a constant 159-byte TOMBSTONE (dev #233) whose entire purpose is
                           to be found at the OLD habit path.
  docs/                    the profile's own reference shelf (incident_archive.md), whose
                           anchors `check_rule_homes.py` resolves; nothing gained by moving.

⭐ WHY --audit WAS WIRED, AND WHY ITS TWO FINDINGS EXIT DIFFERENTLY (gate/tree-audit-wiring).
`--audit` existed since #28 shipped but nothing ran it — a detector nobody calls is not a
detector. It is wired into `coordinator.py`'s advisory GATES loop (every session, right after
`migrate.py --hook` has already had its chance to self-heal), and its two findings are NOT the
same severity:

  UNMIGRATED  a legacy name the tree migration will move — self-healing, and by the time this
              check runs in a real session, the SessionStart hook already tried. Exit 1 on this
              alone would show every user a red gate for something the engine is already fixing
              itself — the exact trap `trigger.py --check` sidestepped by being consumed
              advisorily rather than treated as always-fatal. tests/fixtures/profile is ITSELF
              legacy-shaped (born before this migration existed), so a hard fail here would also
              have wedged this repo's own CI the moment the fixture was touched by any check that
              runs `_tree.py` against it.
  UNKNOWN     the `nonexistent/` class — a root entry NO RULE ACCOUNTS FOR. This does not
              self-heal; nothing will ever move it because nothing named it. This is the actual
              finding `--audit` exists to make loud, and it is the only thing that fails the
              exit code.

So: `main()` returns 1 only when `unknown` is non-empty. An unmigrated-only tree prints its
listing (still loud — never silent) and exits 0.

Usage:
    python3 _tree.py --audit    # classify every root entry; exit 1 only on an UNKNOWN entry
    python3 _tree.py --plan     # print the move table (what a migration would do)

Python 3.9+. Standard library only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

# The six phases, as the router renders them (generate_dashboard.PHASES) — plus views/,
# which was already established for generated output before this layout existed.
PHASE_DIRS = ("configure", "presence", "pipeline", "applying", "conversations", "outreach")

# key -> (canonical relpath, (legacy relpaths, oldest last)). ⭐ Every key a script resolves
# and every move the tree migration makes comes from THIS table.
LAYOUT = {
    "strategy":              ("configure/strategy.md",            ("strategy.md",)),
    "setup":                 ("configure/SETUP.md",               ("SETUP.md",)),
    # public #28 + ADR-018, settled 2026-08-26: the claim union is named for what it IS.
    # `resume.md` asserted it was the printed artifact; it is the superset nobody sends.
    # The legacy chain covers both the unmigrated root file and any tree migrated by an
    # unreleased intermediate that moved it without renaming.
    "claims":                ("presence/claims.md",               ("presence/resume.md",
                                                                   "resume.md")),
    "projects":              ("presence/projects.md",             ("projects.md",)),
    "linkedin_profile":      ("presence/linkedin_profile.md",     ("linkedin_profile.md",)),
    "kb":                    ("pipeline/kb",                      ("kb",)),
    "cover_letters":         ("applying/cover_letters.md",        ("cover_letters.md",)),
    "call_preps":            ("conversations",                    ("call_preps",)),
    "drafts":                ("outreach/drafts.md",               ("drafts.md",)),
    "drafts_assets":         ("outreach/drafts_assets",           ("drafts_assets",)),
    "network":               ("outreach/network.md",              ("network.md",)),
    "process_archive":       ("archive/process_archive.md",       ("process_archive.md",)),
    "dashboard_artifact":    ("views/dashboard_artifact.html",    ("dashboard_artifact.html",)),
    "dashboard_artifact_url": ("views/dashboard_artifact_url.txt",
                              ("dashboard_artifact_url.txt",)),
}

# Root entries that BELONG at root (see the header for why each stays). Everything else a
# root listing shows is either a phase dir, a legacy name awaiting migration, or unknown.
ROOT_FILES = ("CLAUDE.md", "README.md", "config.json", "user.json", "handoff.md", "log.md",
              "dashboard.html", "CREDENTIALS.md")   # CREDENTIALS.md: init_profile's checklist
ROOT_DIRS = PHASE_DIRS + ("data", "docs", "archive", "views")

# Files whose presence at root is a RETIRED artifact: retirement becomes a MOVE (public #28
# item 3 — "retired" as prose left a live-looking file for every directory listing).
RETIRED_TO = {
    "focus.md":         "archive/retired-trackers/focus.md",
    "opportunities.md": "archive/retired-trackers/opportunities.md",
}

# Worksheets that belong to applying/ wherever they were filed. The 2026-08-24 application
# batch went into call_preps/ because applying/ did not exist — #28's clearest symptom.
APPLYING_PATTERN = "application_batch_"


def rel(key):
    """The canonical profile-relative path for `key`. KeyError on an unknown key — a typo'd
    key must fail at the call site, never resolve to a guess."""
    return LAYOUT[key][0]


def path(root, key):
    """Absolute path for `key` under `root`: canonical if it exists, else the first legacy
    location that exists, else canonical (the right place to CREATE it)."""
    new, legacies = LAYOUT[key]
    cand = os.path.join(root, new)
    if os.path.exists(cand):
        return cand
    for old in legacies:
        p = os.path.join(root, old)
        if os.path.exists(p):
            return p
    return cand


_BY_REL = {}
for _k, (_new, _olds) in LAYOUT.items():
    _BY_REL[_new] = _k
    for _o in _olds:
        _BY_REL[_o] = _k


def resolve_rel(root, relpath):
    """Absolute path for a profile-relative path, honoring the layout's fallback when the
    relpath names a moved item (by either its canonical or its legacy name). A relpath the
    layout does not know is joined verbatim — this must never invent locations."""
    key = _BY_REL.get(relpath.rstrip("/"))
    return path(root, key) if key else os.path.join(root, relpath)


def display(root, key):
    """The profile-relative path `path()` would resolve — for messages and rendered links."""
    return os.path.relpath(path(root, key), root)


def audit(root):
    """Classify every visible root entry. Returns (unmigrated, unknown):
    `unmigrated` — legacy names the tree migration will move; `unknown` — entries no rule
    accounts for (the `nonexistent/` class: nothing detected it for weeks)."""
    legacy_names = {old.split(os.sep)[0] for _new, olds in LAYOUT.values() for old in olds}
    legacy_names |= set(RETIRED_TO)
    known = set(ROOT_FILES) | set(ROOT_DIRS)
    unmigrated, unknown = [], []
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue                      # dotfiles are the machine's, not the tree's
        if name in known:
            continue
        # Root variant pages follow the union into presence/ — the migration moves them by
        # this same pattern, so they are "awaiting migration", never "unknown".
        legacy = (name in legacy_names
                  or (name.startswith("resume_") and name.endswith(".md")))
        (unmigrated if legacy else unknown).append(name)
    return unmigrated, unknown


def main(argv):
    # `os.getcwd()` alone would not walk up to find the profile root (every other check_*.py
    # in this engine resolves via `_root.profile_root()`, which does) — a session running from
    # a subdirectory of the profile would otherwise see an empty listing and report it as fact,
    # exactly the trap CLAUDE.md's trap #1/#2 describe.
    root = _profile_root()
    if "--plan" in argv:
        for key in sorted(LAYOUT):
            new, olds = LAYOUT[key]
            print("%-24s %s -> %s" % (key, " | ".join(olds), new))
        for old, new in sorted(RETIRED_TO.items()):
            print("%-24s %s -> %s (retired)" % ("-", old, new))
        return 0
    unmigrated, unknown = audit(root)
    if not unmigrated and not unknown:
        print("tree: every root entry matches the canonical layout.")
        return 0
    if unmigrated:
        # ⭐ Advisory, deliberately: self-healing (migrate.py's SessionStart hook already had
        # its chance before this ever runs in a real session), and every existing profile is
        # non-canonical until it does — a hard failure here would be a red gate for something
        # the engine is already fixing itself. See the module docstring.
        print("tree: %d legacy entr%s awaiting the tree migration (runs at session start):"
              % (len(unmigrated), "y" if len(unmigrated) == 1 else "ies"))
        for n in unmigrated:
            print("  %s" % n)
    if unknown:
        # ⭐ NOT advisory: nothing self-heals a name no rule accounts for. This is the one
        # finding that fails the exit code — the `nonexistent/` class #28 was filed over.
        print("tree: ⚠️ %d root entr%s NO RULE ACCOUNTS FOR — the `nonexistent/` class. "
              "File it, move it to its phase, or archive it:"
              % (len(unknown), "y" if len(unknown) == 1 else "ies"))
        for n in unknown:
            print("  %s" % n)
    return 1 if unknown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
