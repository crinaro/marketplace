#!/usr/bin/env python3
"""check_ledger_reads.py — fails any shipped script (outside the ledger's own three readers)
that opens `data/briefs.jsonl` by its literal filename, or reads one of its derived-fact
fields (`days_since_in`, `last_word`, `latest_in`, `latest_out`, `register`) off ANY row.

WHY THIS EXISTS (Query or Citation C1, design-query-or-citation.md §3.6)
--------------------------------------------------------------------------
`brief.py`'s whole reason to exist is that a fact a run STATES comes out of the queryable
store at the moment it states it — never a snapshot trusted from when it was written. The
ledger (`data/briefs.jsonl`) exists to prove what a drafter SAW, never to BE a source of
state: `brief.py --check` and `precondition.py` recompute the register from stores + journal
at every read, so a stale snapshot can never be trusted past the store (§3.6, §20's own
"biggest risk" naming). The day some OTHER script reads `days_since_in` (or any of the other
four fields) off a ledger row instead of recomputing it, this design has reproduced #80 one
layer down — a number trusted from the moment it was written, exactly the defect the whole
mechanism exists to close. This gate is that day never arriving unnoticed.

WHAT COUNTS — AST, NOT REGEX, IN check_retired_reads.py's OWN SHAPE
------------------------------------------------------------------------
Two independent scans, same file, same discipline as `check_retired_reads.py` (ADR-031
§28.1 item 4's own precedent, reused here for a ledger instead of a retired array):

    (a) the string constant "briefs.jsonl" (an `ast.Constant`) anywhere in a file NOT in
        `brief.LEDGER_READERS` — the ledger's own three readers (`brief.py` itself,
        `validate_data.py` for shape, `make_fixture.py` for generation).
    (b) any `ast.Subscript` whose slice is one of `"days_since_in"`, `"last_word"`,
        `"latest_in"`, `"latest_out"`, `"register"`, or any `.get(<one of those>)` call —
        REGARDLESS of what the subscripted/called-on object is — outside `brief.py`.
        ⚠️ SCOPED HERE to all of `LEDGER_READERS`, not `brief.py` alone: the design's own
        text says "outside brief.py", but `validate_data.py`'s own shape check (is
        `register` in the closed vocabulary?) and `make_fixture.py`'s generation
        necessarily name these fields too — structurally, never to TRUST a stale value the
        way a business-logic caller would. Narrowing to `brief.py` alone would make §8's
        own required shape check impossible to write; this is stated here rather than
        silently narrowed.

(b) is the SAME precision loss `check_retired_reads.py` accepts on purpose, in the safe
direction: a caller reading `some_dict["register"]` where `some_dict` is not actually a
brief row is a false positive, five minutes and a `KNOWN_EXCEPTIONS` entry away — never a
false negative, which would be silent data loss reported as fact. `"register"` is generic
enough that a false positive is plausible; that is the cost of never missing a real hit.

(a) matches an EXACT `ast.Constant` string equal to `"briefs.jsonl"` — never a substring
scan (`check_narrative.py`'s 4-in-5 false-positive history is exactly why). A comment or a
docstring sentence mentioning the ledger BY NAME inside a larger string (`"...
data/briefs.jsonl ..."`, this very docstring included) is one `ast.Constant` node whose
VALUE is the whole surrounding text, not the substring — so it is not a hit at all, by
construction, with no exception needed to excuse it. Only a bare, standalone
`"briefs.jsonl"` literal (a dict key, a lone argument, a path component built with
`os.path.join(..., "briefs.jsonl")`) parses as that exact node.

KNOWN_EXCEPTIONS — ONE ENTRY PER FILE, NAMED UP FRONT, NEVER SILENT
------------------------------------------------------------------------
Printed every run; a stale entry (matches no real hit) FAILS the gate — the same
`check_engine_purity.py` discipline check_retired_reads.py already reuses. A suppression
cannot outlive its reason. Empty today: every real reader is covered by `LEDGER_READERS`
(rule a) or by being `brief.py` itself (rule b); nothing else has a legitimate exception yet.

Usage:
    python3 check_ledger_reads.py                  # scan every tracked plugins/jobsearch/scripts/*.py
    python3 check_ledger_reads.py --scan-dir DIR    # scan a scratch directory instead (the
                                                     # fail-on-purpose plant)

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

# `brief.py` owns the ledger's filename and its reader allowlist — imported, never
# hand-duplicated (the same "one definition" rule check_retired_reads.py follows for
# `active_retired_keys()`).
from brief import LEDGER_READERS  # noqa: E402

# Derived from `brief.LEDGER` (`"data/briefs.jsonl"`), never hardcoded a second time — this
# file's OWN reference to the bare filename would otherwise be a hit against its own rule (a).
LEDGER_FILENAME = os.path.basename(__import__("brief").LEDGER)

# The five derived-fact fields a ledger row carries that must never be trusted from a
# snapshot — recomputed from stores + journal at every read, everywhere but brief.py itself.
DERIVED_FIELDS = frozenset({"days_since_in", "last_word", "latest_in", "latest_out", "register"})

# ⚠️ A KNOWN EXCEPTION MUST NAME A REASON, AND A STALE ONE IS AN ERROR — check_engine_purity.py's
# own discipline, reused verbatim (check_retired_reads.py's own precedent). Each entry is
# (relative_path, matched_string): the one file, and the one literal, it is allowed to carry.
#
# `test_checks.py` / "briefs.jsonl" and / "register" — the SAME permanent-reader shape
# check_retired_reads.py's own KNOWN_EXCEPTIONS grants `test_checks.py` for `contacts`/
# `applications`: a test file directly constructs and inspects ledger rows (a synthetic
# person's `**Brief:**` citation, a planted `register` value) to prove brief.py's own
# mechanism — never a shipped script's write path, so this cannot reintroduce a production
# reader of the ledger.
KNOWN_EXCEPTIONS = (("test_checks.py", LEDGER_FILENAME), ("test_checks.py", "register"))


class Hit:
    """One finding: `path` relative to whatever root was scanned, 1-based `line`, and the
    matched string (`LEDGER_FILENAME` for rule (a), the field name for rule (b)). Equality/
    repr by value so tests can assert on hits directly."""
    __slots__ = ("path", "line", "matched")

    def __init__(self, path, line, matched):
        self.path = path
        self.line = line
        self.matched = matched

    def __eq__(self, other):
        return (isinstance(other, Hit)
                and (self.path, self.line, self.matched) == (other.path, other.line, other.matched))

    def __hash__(self):
        return hash((self.path, self.line, self.matched))

    def __repr__(self):
        return "Hit(%s:%d %r)" % (self.path, self.line, self.matched)


def _const_str(node):
    """The string value of an ast.Constant node, or None for anything else (a variable, an
    f-string, a non-string constant) — never a guess."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_source(text, path="<string>"):
    """Pure function — no disk access beyond parsing `text` itself. Returns every Hit for
    rule (a) (the literal filename "briefs.jsonl" as a string constant anywhere) or rule (b)
    (a Subscript/`.get()` naming one of DERIVED_FIELDS, `X` unconstrained in both cases —
    §3.6's own accepted precision loss).

    A file that does not parse is not this gate's finding (check_python_floor.py, or a plain
    SyntaxError at import, already owns that failure mode) — this returns no hits for it
    rather than raising, so one unparseable file cannot hide every other file's real hits."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return []
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == LEDGER_FILENAME:
            hits.append(Hit(path, node.lineno, LEDGER_FILENAME))
        elif isinstance(node, ast.Subscript):
            key = _const_str(node.slice)
            if key in DERIVED_FIELDS:
                hits.append(Hit(path, node.lineno, key))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
                key = _const_str(node.args[0])
                if key in DERIVED_FIELDS:
                    hits.append(Hit(path, node.lineno, key))
    return hits


def _git_tracked_py_files(scripts_dir):
    """Every tracked `.py` file under `scripts_dir`, from git's own object model — never a
    glob (check_engine_purity.py's rule: a hand-listed family silently scans less than it
    claims to)."""
    out = subprocess.run(["git", "-C", scripts_dir, "ls-files", "*.py"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return None
    return sorted(l for l in out.stdout.splitlines() if l.strip())


def _walk_py_files(scripts_dir):
    """Independent second enumeration (os.walk), used only to prove git's count is not
    silently under-reporting — check_engine_purity.py's 'scanned N of M' rule, applied to
    file COUNT."""
    found = []
    for dirpath, dirnames, filenames in os.walk(scripts_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        found += [os.path.relpath(os.path.join(dirpath, f), scripts_dir)
                  for f in filenames if f.endswith(".py")]
    return sorted(found)


def scan_tree(scripts_dir, allowed_readers=None, known_exceptions=()):
    """Scans every tracked `.py` file under `scripts_dir`. Returns
    `(hits, unresolved, stale, scanned, walked)` — same shape as check_retired_reads.py's own
    `scan_tree`.

    A rule (a) hit (the filename constant) is resolved by the FILE being in
    `allowed_readers` — never by a `KNOWN_EXCEPTIONS` entry (a reader is a reader; the
    allowlist is `brief.LEDGER_READERS`, not a per-hit exception). A rule (b) hit (a derived
    field) is resolved by the file being `brief.py` itself, OR by an explicit
    `KNOWN_EXCEPTIONS` entry naming that exact (path, field) pair."""
    allowed_readers = allowed_readers if allowed_readers is not None else LEDGER_READERS
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
        hits.extend(scan_source(text, path=rel))

    exc_set = set(known_exceptions)
    covered = set()
    unresolved = []
    for h in hits:
        if h.matched == LEDGER_FILENAME:
            if h.path in allowed_readers:
                covered.add((h.path, h.matched))
                continue
        # Rule (b): the design's own text says "outside brief.py"; `validate_data.py`'s SHAPE
        # check (does `register` sit in the closed vocabulary?) and `make_fixture.py`'s
        # generation necessarily name these fields too, structurally — never to TRUST a value
        # as current. Scoped to all of LEDGER_READERS (rule (a)'s own allowlist), not brief.py
        # alone, so the gate does not forbid the shape check §8/§3.6 themselves require.
        elif h.path in allowed_readers:
            covered.add((h.path, h.matched))
            continue
        if (h.path, h.matched) in exc_set:
            covered.add((h.path, h.matched))
        else:
            unresolved.append(h)
    stale = [e for e in known_exceptions if e not in covered]
    return hits, unresolved, stale, scanned, walked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan-dir", metavar="DIR",
                    help="scan DIR instead of plugins/jobsearch/scripts/ — the fail-on-purpose "
                         "plant target. NEVER this repo; KNOWN_EXCEPTIONS is not applied.")
    args = ap.parse_args()

    print("ledger: %s · readers: %s" % (LEDGER_FILENAME, ", ".join(sorted(LEDGER_READERS))))
    print("derived fields never read outside brief.py: %s" % ", ".join(sorted(DERIVED_FIELDS)))

    if args.scan_dir:
        scripts_dir = os.path.abspath(args.scan_dir)
        hits, unresolved, stale, scanned, walked = scan_tree(scripts_dir, known_exceptions=())
    else:
        scripts_dir = HERE
        hits, unresolved, stale, scanned, walked = scan_tree(scripts_dir,
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
        for path, matched in KNOWN_EXCEPTIONS:
            print("      %s carries %r" % (path, matched))

    if stale:
        print("\n  !! %d STALE KNOWN EXCEPTION(S) — matched no hit; delete the entry:"
              % len(stale))
        for path, matched in stale:
            print("      %s / %r" % (path, matched))
        return 1

    if unresolved:
        print("\n  !! %d LEDGER READ(S) OUTSIDE THE ALLOWLIST:" % len(unresolved))
        for h in unresolved:
            if h.matched == LEDGER_FILENAME:
                print("      %s:%d opens %r — not in brief.LEDGER_READERS"
                     % (h.path, h.line, h.matched))
            else:
                print("      %s:%d reads %r off a row — brief.py recomputes this at every "
                      "read; a snapshot must never be trusted (§80/#80)"
                     % (h.path, h.line, h.matched))
        return 1

    print("\n  CLEAN. The ledger has exactly its three readers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
