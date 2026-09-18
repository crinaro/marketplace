#!/usr/bin/env python3
"""check_retired_reads.py — fails any shipped script that reads a RETIRED nested-array key by
its literal string name: `outreach`, `contacts`, `applications`.

WHY THIS EXISTS (ADR-031 §28.1 item 4; gates-connected-entities.md §1)
-----------------------------------------------------------------------
ADR-031's connected-entities design retires `opportunities.contacts[]`/`outreach[]`/
`applications[]` (and `channels.contacts[]`) one stage at a time, promoting each to its own
store. The design's own §6 names the biggest risk of that plan: a reader nobody re-points does
not error when the array it reads is removed — it reads `[]` and reports that as fact, silently,
forever. `validate_data.py`'s unknown-key guard (`active_retired_keys()`) catches the key
surviving in STORED DATA; this file catches the key surviving in SHIPPED SOURCE CODE, which is
the half a data validator cannot see at all.

WHAT COUNTS AS A READ — AST, NOT REGEX, AND THIS IS THE GATE REVIEW'S OWN CORRECTION
--------------------------------------------------------------------------------------
The design's prose says the gate should fail on "any outreach/contacts/applications key access
against an opportunity or channel record." That clause is not mechanically decidable: nothing
in this codebase types a `dict` as "an opportunity", so a checker cannot know what a variable
holds. What CAN be built, and is honest about what it does (gates-connected-entities.md §1):

    every `ast.Subscript` whose slice is the string constant "outreach"/"contacts"/
    "applications", and every `X.get("outreach"/"contacts"/"applications", ...)` call —
    REGARDLESS of what `X` is.

This is a precision loss accepted on purpose, in the safe direction: it will never MISS a real
hit (the property the "biggest risk" section asks for — a false negative here is silent data
loss reported as fact), and a false positive is a five-minute, must-justify-in-writing
`KNOWN_EXCEPTIONS` entry, the same mechanism `check_engine_purity.py` already uses. That
asymmetry is deliberate, not an oversight.

WHY THIS AVOIDS check_narrative.py's 4-IN-5 FALSE-POSITIVE HISTORY
---------------------------------------------------------------------
`outreach` appears constantly in this codebase as legitimate, unrelated text: the agent name
`outreach-drafter`, the paths `outreach/drafts.md` / `outreach/cover_letters.md`, ordinary
prose. A substring scan would drown in this repo's own vocabulary — exactly what sank
`check_narrative.py`'s first version. Matching the exact string literal used as a dict key or a
`.get()` argument, via the parser, never confuses "outreach/drafts.md" (a different string
constant) with "outreach" (a dict key), and never treats the identifier `outreach_summary` as a
string at all.

STAGE-AWARE, NEVER ALL OF RETIRED_KEYS AT ONCE
-------------------------------------------------
The scanning set is `validate_data.active_retired_keys()` — the SAME function, imported, that
gates `validate_data.py`'s own guard — never a second hand-typed tuple (the exact
`docs/data_model.json` field-list drift `validate_data.py:548`'s own comment already names) and
never this file's own copy of "which stage has shipped". It resolves to `{}` until B1 ships
(`graph.py` lands with the migration), which is provably correct against `main` as it stands —
see `test_checks.py`'s plant for this file, which asserts zero hits from `contacts` on the
CURRENT tree specifically because `contacts` is still legal pre-B1.

KNOWN_EXCEPTIONS — ONE ENTRY PER STAGE, NAMED UP FRONT, NEVER SILENT
------------------------------------------------------------------------
Each stage's OWN migration handler legitimately reads its retired key exactly once — to
transform it. That module is the one file each stage is allowed to name here, with the same
discipline `check_engine_purity.py`'s own `KNOWN_EXCEPTIONS` already has: printed every run, and
an entry that no longer matches any real hit (a migration whose transform is done and should
have dropped the read) FAILS the gate — a suppression cannot outlive its reason. Empty today: no
migration handler exists yet (that is the next dispatch's work).

Usage:
    python3 check_retired_reads.py                  # scan every tracked plugins/jobsearch/scripts/*.py
    python3 check_retired_reads.py --scan-dir DIR    # scan a scratch directory instead (the
                                                      # fail-on-purpose plant; KNOWN_EXCEPTIONS
                                                      # and the tracked-file enumeration are both
                                                      # bypassed — DIR is never this repo)

Python 3.9+. Standard library only. No profile, no network — reads only tracked source under
plugins/jobsearch/scripts/ (or an explicit scratch --scan-dir).
"""
import argparse
import ast
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# validate_data owns RETIRED_KEYS/active_retired_keys() — imported, never hand-duplicated. See
# validate_data.py's own block comment on RETIRED_KEYS for why this must be the SAME function.
from validate_data import RETIRED_KEYS, active_retired_keys  # noqa: E402


# ⚠️ A KNOWN EXCEPTION MUST NAME A STAGE, AND A STALE ONE IS AN ERROR — check_engine_purity.py's
# own discipline, reused verbatim. Each entry is (relative_path, key): the one file that stage's
# migration handler lives in, and the one retired key it is allowed to read.
#
# `migrate.py` / `contacts` — B1's own migration handler (`m_0_44_0_people_involvements`)
# reads `opportunities.jsonl`/`channels.jsonl`'s `contacts[]` EXACTLY ONCE, to transform it
# into `people`/`involvements` rows and then `.pop()` it off the record (a `.pop()` call is not
# `.get()`/a `Subscript` and is not what this scanner matches anyway — the TWO real hits here
# are the `.get("contacts")` reads that WALK the array to build migration candidates). This
# entry is added in the SAME commit that ships `graph.py` and the migration itself, per this
# file's own module docstring — never added ahead of the handler that justifies it.
#
# `test_checks.py` / `contacts` — a SECOND, PERMANENT legitimate reader, unlike the migration
# handler above (which reads the key once, to retire it). `tests/fixtures/migrations/pre-b1/`
# is B1's own golden migration INPUT and is frozen FOREVER, by design
# (design-connected-entities.md §28.1: "never — frozen") — specifically so it keeps holding
# the PRE-migration shape no matter how many later stages ship. `TestPreB1CoverageFixture`'s
# `_opp_contacts`/`_chan_contacts` accessors (and `_pre_b1_model()`, which patches the schema
# back to what it was for exactly this fixture) read that frozen `contacts[]` shape to prove
# the fixture's own coverage properties hold — a read that does not shrink to zero as later
# stages ship, since a frozen historical fixture is not "a reader nobody re-pointed," it is the
# thing the design commits to never re-pointing. `test_checks.py` is a test file, never a
# shipped script's write path, so this cannot reintroduce `contacts[]` into a real profile.
#
# `migrate.py` / `applications` — B2's own migration handler
# (`m_0_45_0_applications_cover_letters`) reads `opportunities.jsonl`'s `applications[]` EXACTLY
# ONCE, to promote it into `applications`/`cover_letters` rows and then `.pop()` it off the
# record. It ALSO covers `m_0_36_0_derive_from_applications` (0.36.0, pre-dates B2 and always
# runs earlier in MIGRATIONS — its own docstring explains why it keeps a small inline copy of
# the submitted/play-stage predicates rather than depending on `your_move`'s post-B2 promoted-
# store API): the same one file, same discipline as B1's `contacts` entry above.
#
# `test_checks.py` / `applications` — same permanent-reader shape as `test_checks.py` /
# `contacts`: `tests/fixtures/migrations/pre-b2/` is B2's own golden migration INPUT, frozen
# forever, and its own coverage tests read the frozen nested `applications[]` shape to prove
# the fixture's coverage properties hold.
#
# `migrate.py` / `outreach` — B3's own migration handler (`m_0_48_0_touches`) reads
# `opportunities.jsonl`'s `outreach[]` EXACTLY ONCE, to promote it into `touches` rows and
# then drop it from the record. Same discipline as the two entries above.
#
# `test_checks.py` / `outreach` — same permanent-reader shape as the two `test_checks.py`
# entries above: `tests/fixtures/migrations/pre-b3/` is B3's own golden migration INPUT,
# frozen forever, and its own coverage tests read the frozen nested `outreach[]` shape to
# prove the fixture's coverage properties hold.
#
# `make_fixture.py` / `outreach` — NOT a migration handler; a THIRD kind of legitimate
# reader this design's own fixture-generation route (gates-connected-entities.md §Fixture
# mechanism (b)) requires. `_patched_model_for()` restores the RETIRED pre-B3 schema shape
# (contact_id-named outreach fields, before B1's rename) onto `docs/data_model.json`'s own
# in-memory copy so `pre-b1`'s frozen case can still be CHECKED against the schema it was
# actually written against — the exact same "historical shape must survive" reasoning as the
# two `test_checks.py` entries above, applied to the SCHEMA half rather than the DATA half.
# It reads `spec["arrays"]["outreach"]` to rename that array's fields, never a real profile's
# data row — permanent, like `test_checks.py`'s own entries, never scoped to one stage's
# transform-then-drop lifecycle the way `migrate.py`'s entries are.
#
# `precondition.py` / `outreach` — a FOURTH kind, and the only one that reads a REAL profile's
# data row outside a migration handler itself. `_sent_row_exists()` is called by
# `plan_prune()`, which `m_0_47_0_drafts_working_set` (keyed 0.47.0, strictly BEFORE B3's
# 0.48.0) calls directly. Migrations run in strict version order, so at the moment 0.47.0
# executes on a real upgrading profile, `outreach[]` is STILL nested — B3 has not run yet.
# Reading only the top-level `touches` store there would make `_sent_row_exists` silently
# blind on exactly that (common, real) profile shape, turning a genuine "already sent" fact
# into a false negative (the CLAUDE.md trap: a missing thing reading as an empty one) and a
# relocate into a needless duplicate — measured directly: `TestV1bMigrationGoldenOutput`
# reported 9 relocated where 7 was correct until this fallback was added. So
# `_sent_row_exists` checks the top-level store FIRST and falls back to the nested array
# SECOND, permanently — not scoped to one release the way `migrate.py`'s own entries are,
# because a profile can be paused mid-upgrade (mid-migration-chain) indefinitely between two
# session starts, and this function must read either shape correctly whenever it runs.
#
# `migrate.py` / `play_stage` and `migrate.py` / `next_action` — TWO kinds of legitimate B4
# reader in the SAME file. `m_0_25_0_play_stage` (historical, keyed 0.25.0, runs BEFORE B4 in
# the migration chain) reads `next_action` to detect a numbered play marker and writes
# `play_stage` — both fields are still legally nested/present at that point in an upgrading
# profile's replay, exactly the ordering `_sent_row_exists`'s own KNOWN_EXCEPTIONS entry above
# already established for a pre-B3 migration reading a still-nested shape. `m_0_49_0_plans_
# plays` (B4's OWN migration handler) reads both EXACTLY ONCE each, to relocate/derive them
# and then drop them — the same transform-then-drop shape every other stage's own entry has.
#
# `test_checks.py` / `play_stage` and `test_checks.py` / `next_action` — the same permanent-
# reader shape as every other `test_checks.py` entry above: `tests/fixtures/migrations/pre-b4/`
# is B4's own golden migration INPUT, frozen forever, and its own coverage tests read the
# frozen pre-migration shape (`play_stage`/`next_action` still present) to prove the fixture's
# own coverage properties hold.
# dev #399 §1 — every single `test_checks.py` entry above split into several, one per
# tests/test_*.py file the relevant classes actually landed in by dependency (not all in one
# place), same reason as before per file: each is the frozen pre-migration golden-fixture
# coverage the comment above already describes, never a shipped reader. Re-derived from the
# real tracked tree after the split (`check_retired_reads.scan_tree` against `known_exceptions
# =()`), not guessed — 14 pairs across 12 files.
KNOWN_EXCEPTIONS = (("migrate.py", "contacts"),
                    ("tests/test_migrate_2.py", "contacts"),
                    ("tests/test_resume_variants.py", "contacts"),
                    ("migrate.py", "applications"),
                    ("tests/test_check_dashboard_coverage.py", "applications"),
                    ("tests/test_migrate_2.py", "applications"),
                    ("tests/test_record.py", "applications"),
                    ("migrate.py", "outreach"),
                    ("tests/test__docx.py", "outreach"),
                    ("tests/test_check_dashboard_coverage.py", "outreach"),
                    ("tests/test_check_engine_purity.py", "outreach"),
                    ("tests/test_heal_install.py", "outreach"),
                    ("tests/test_migrate_2.py", "outreach"),
                    ("tests/test_misc.py", "outreach"),
                    ("tests/test_validate_data.py", "outreach"),
                    ("make_fixture.py", "outreach"), ("precondition.py", "outreach"),
                    ("migrate.py", "play_stage"),
                    ("tests/test_migrate_1.py", "play_stage"),
                    ("migrate.py", "next_action"),
                    ("tests/test_migrate_1.py", "next_action"))


class Hit:
    """One retired-key read: `path` relative to whatever root was scanned, 1-based `line`, and
    the retired `key` literal matched. Equality/repr by value so tests can assert on hits
    directly rather than re-deriving them from printed text."""
    __slots__ = ("path", "line", "key")

    def __init__(self, path, line, key):
        self.path = path
        self.line = line
        self.key = key

    def __eq__(self, other):
        return (isinstance(other, Hit)
                and (self.path, self.line, self.key) == (other.path, other.line, other.key))

    def __hash__(self):
        return hash((self.path, self.line, self.key))

    def __repr__(self):
        return "Hit(%s:%d %r)" % (self.path, self.line, self.key)


def _const_str(node):
    """The string value of an ast.Constant node, or None for anything else (a variable, an
    f-string, a non-string constant) — never a guess."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_source(text, retired_keys=None, path="<string>"):
    """Pure function — no disk access beyond parsing `text` itself. Returns every Hit for a
    retired-key `ast.Subscript` (`x["contacts"]`) or `.get("contacts", ...)` call anywhere in
    `text`, `X` unconstrained in both cases (§1's own accepted precision loss).

    `retired_keys` defaults to `active_retired_keys()` — the ACTIVE, stage-gated set, {} until
    B1 ships. Pass an explicit dict (e.g. RETIRED_KEYS, or {"outreach": "B3"}) to test a stage
    that has not shipped yet without waiting for it to.

    A file that does not parse is not this gate's finding — check_python_floor.py (or plain
    SyntaxError at import) already owns that failure mode; this returns no hits for it rather
    than raising, so one unparseable file cannot hide every other file's real hits behind a
    crash."""
    if retired_keys is None:
        retired_keys = active_retired_keys()
    if not retired_keys:
        return []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return []
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            key = _const_str(node.slice)
            if key in retired_keys:
                hits.append(Hit(path, node.lineno, key))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
                key = _const_str(node.args[0])
                if key in retired_keys:
                    hits.append(Hit(path, node.lineno, key))
    return hits


def _git_tracked_py_files(scripts_dir):
    """Every tracked `.py` file under `scripts_dir`, from git's own object model — never a glob
    (`check_engine_purity.py`'s rule: a hand-listed family silently scans less than it claims
    to). `git -C scripts_dir ls-files "*.py"` scopes to files inside that directory and returns
    paths relative to it, which is exactly plugins/jobsearch/scripts/*.py when scripts_dir is
    this file's own directory — __pycache__ is untracked and never appears; git-hooks/ is shell,
    not .py, and the "*.py" pathspec already excludes it, so nothing needs excluding by name."""
    out = subprocess.run(["git", "-C", scripts_dir, "ls-files", "*.py"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return None
    return sorted(l for l in out.stdout.splitlines() if l.strip())


def _walk_py_files(scripts_dir):
    """Independent second enumeration (os.walk), used only to prove git's count is not silently
    under-reporting — check_engine_purity.py's 'scanned N of M, fail if they don't add up' rule,
    applied here to file COUNT rather than file readability."""
    found = []
    for dirpath, dirnames, filenames in os.walk(scripts_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        found += [os.path.relpath(os.path.join(dirpath, f), scripts_dir)
                  for f in filenames if f.endswith(".py")]
    return sorted(found)


def scan_tree(scripts_dir, retired_keys=None, known_exceptions=()):
    """Scans every tracked `.py` file under `scripts_dir`. Returns
    `(hits, unresolved, stale, scanned, walked)`:

      hits        every Hit found, regardless of KNOWN_EXCEPTIONS
      unresolved  hits not covered by a KNOWN_EXCEPTIONS entry — these fail the gate
      stale       KNOWN_EXCEPTIONS entries that matched NO hit at all — these also fail
      scanned     how many files were actually read and parsed
      walked      the independent os.walk count, for the coverage-adds-up check

    `known_exceptions` is `((relative_path, key), ...)`; a hit is "covered" when its own
    (path, key) pair names an entry here — never by path alone (a legitimate migration read of
    `contacts` does not license that same file reading `outreach` too)."""
    if retired_keys is None:
        retired_keys = active_retired_keys()
    tracked = _git_tracked_py_files(scripts_dir)
    walked = _walk_py_files(scripts_dir)
    if tracked is None:
        tracked = walked  # not a git checkout (installed copy) — os.walk is the real path there

    hits = []
    scanned = 0
    for rel in tracked:
        full = os.path.join(scripts_dir, rel)
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        hits.extend(scan_source(text, retired_keys=retired_keys, path=rel))

    exc_set = set(known_exceptions)
    covered = set()
    unresolved = []
    for h in hits:
        if (h.path, h.key) in exc_set:
            covered.add((h.path, h.key))
        else:
            unresolved.append(h)
    stale = [e for e in known_exceptions if e not in covered]
    return hits, unresolved, stale, scanned, walked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan-dir", metavar="DIR",
                    help="scan DIR instead of plugins/jobsearch/scripts/ — the fail-on-purpose "
                         "plant target. NEVER this repo; KNOWN_EXCEPTIONS is not applied "
                         "(a scratch plant has no stage-migration file to except).")
    ap.add_argument("--force-retired-key", action="append", default=[], metavar="KEY=STAGE",
                    help="TEST-ONLY, requires --scan-dir: force KEY active for this scan "
                         "regardless of active_retired_keys(). Proves the SCANNER mechanism "
                         "against a stage that has not shipped yet (e.g. outreach/B3) without "
                         "waiting for it to — never available against the real tracked tree.")
    args = ap.parse_args()

    if args.force_retired_key and not args.scan_dir:
        ap.error("--force-retired-key requires --scan-dir — never overrides the real tree's "
                 "stage-aware set")

    active = active_retired_keys()
    if args.scan_dir and args.force_retired_key:
        active = dict(active)
        for item in args.force_retired_key:
            k, _, stage = item.partition("=")
            active[k] = stage or "?"
    print("retired keys known to this design: %s" % (dict(RETIRED_KEYS) or "{}"))
    print("active (stage has shipped) today: %s"
          % (dict(active) or "{} — no stage has shipped yet; this gate fires on nothing"))

    if args.scan_dir:
        scripts_dir = os.path.abspath(args.scan_dir)
        hits, unresolved, stale, scanned, walked = scan_tree(scripts_dir, retired_keys=active,
                                                             known_exceptions=())
    else:
        scripts_dir = HERE
        hits, unresolved, stale, scanned, walked = scan_tree(scripts_dir, retired_keys=active,
                                                             known_exceptions=KNOWN_EXCEPTIONS)

    print("  scanned %d of %d tracked .py file(s) under %s"
          % (scanned, len(walked), os.path.relpath(scripts_dir, os.path.dirname(HERE))
             if not args.scan_dir else scripts_dir))
    if scanned == 0 and walked:
        print("\n  !! SCANNED ZERO OF %d — every file failed to read/decode. NOT CHECKED, not "
              "clean." % len(walked))
        return 1

    if KNOWN_EXCEPTIONS and not args.scan_dir:
        print("  KNOWN_EXCEPTIONS (%d):" % len(KNOWN_EXCEPTIONS))
        for path, key in KNOWN_EXCEPTIONS:
            print("      %s reads %r (stage migration handler)" % (path, key))

    # dev #399 §1 — same fix as check_ledger_reads.py's identical shape: `if stale: return 1`
    # used to run BEFORE `if unresolved:` was ever checked, so a stale KNOWN_EXCEPTIONS entry
    # masked real unresolved hits instead of surfacing them. The split produced exactly this
    # (5 stale entries hiding what were, before repointing them, real unresolved hits) and the
    # "CLEAN" the early return implied for the unresolved half was never actually checked.
    problems = False
    if unresolved:
        problems = True
        print("\n  !! %d RETIRED-KEY READ(S) — a reader was not re-pointed:" % len(unresolved))
        for h in unresolved:
            print("      %s:%d reads retired key %r" % (h.path, h.line, h.key))

    if stale:
        problems = True
        print("\n  !! %d STALE KNOWN EXCEPTION(S) — matched no hit; delete the entry:"
              % len(stale))
        for path, key in stale:
            print("      %s / %r" % (path, key))

    if problems:
        return 1

    print("\n  CLEAN. No unresolved retired-key read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
