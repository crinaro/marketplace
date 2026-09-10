#!/usr/bin/env python3
"""Does a shipped skill's shown CLI invocation actually match the target script's own flags?

⭐ WHY THIS EXISTS — public #82, found by `docs-steward` auditing wave 1c documentation drift.
-----------------------------------------------------------------------------------------------
`coordinator/SKILL.md` told the running agent to file an engine defect with:

    ~/.claude/jobsearch/run report_issue.py \\
      --title "..." --symptom "..." --severity high --owner gate-keeper

`--severity`/`--owner` belong to `scripts/intake.py` — a DIFFERENT script, in the marketplace's
own private repo, that this shipped file used to name before `report_issue.py` replaced it.
`report_issue.py` defines exactly four flags (`--title`, `--symptom`, `--evidence`, `--file`);
nothing else. An agent following the shown invocation would have had `argparse` reject the
command outright — the exact same defect class public #73 found four times over (a shipped file
pointing a reader at something that does not actually exist on the other end), except the dead
end here is a FLAG rather than a whole file.

**Fix the class, not the instance.** Trimming that one invocation leaves every other shown
command free to drift the same way the moment a script's own `argparse` changes shape.

## THE MECHANISM — deliberately narrow, for the same reason `check_verbatim_enums.py` is

⚠️ A gate that scans prose for a flag-shaped substring has the exact failure history
`check_narrative.py` already lived through in this repo: wrong four times out of five, because a
field or flag NAMED in passing prose, or inside an illustrative sentence, is not an instruction.
So this reads ONLY:

  - text inside a FENCED code block (```...```) — never inline prose, never a bullet that merely
    LOOKS like a command.
  - a line matching the engine's own real invocation idiom, `~/.claude/jobsearch/run <script>.py`
    — the one convention every shipped agent, skill and command in this plugin actually uses.
  - flags on that same logical command — the invocation line plus any lines it continues onto via
    a trailing backslash — up to (never past) a bare `--` token, which hands the rest of the line
    to a wrapped subcommand (`runlock.py --run "..." --wait 60 -- bash -c '...'`) that is not
    this script's own argument surface at all.

Anything else — an inline single-backtick command span (RULEBOOK.md's own idiom), a flag typed
into a code comment or a docstring's own `Usage:` block, a multi-command shell pipeline, a flag
whose unquoted VALUE happens to itself start with `--` — is deliberately UNCHECKED. Extending
into any of those shapes is exactly how `check_narrative.py` earned its record; a check that
finds fewer real defects but never invents one is worth more than the reverse.

**What "the target script's own flags" means:** the real, long-option (`--foo`) strings passed as
positional arguments to an `add_argument(...)` call anywhere in `plugins/jobsearch/scripts/
<name>.py` — found via `ast`, never by importing the module (most of these scripts build their
parser inside `main()`, so nothing module-level exposes it, and importing 180 scripts just to
read one attribute each would run whatever module-level code each one happens to have). `-h`/
`--help` is always allowed — argparse adds it to every parser whether or not the script's own
source ever spells it.

**What this does NOT check** (say what is excluded, per this repo's own standing rule for a new
gate): whether the named SCRIPT exists at all — `check_pointers.py` already owns that, via its
own `scripts/<name>.py` pointer check, and duplicating it here would just be two gates disagreeing
about whose job a stale script name is; whether a POSITIONAL argument's VALUE is well-formed;
whether the invocation as a whole would actually succeed (working directory, profile state, exit
code). Only whether every `--flag` token shown is one the script actually defines.

Usage:
    python3 plugins/jobsearch/scripts/check_cli_flags.py            # exit 1 on any unknown flag
    python3 plugins/jobsearch/scripts/check_cli_flags.py --verbose  # show every invocation checked

Python 3.9+. Standard library only.
"""

import argparse
import ast
import glob
import os
import re
import shlex
import sys

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _root import engine_root as _engine_root

ENGINE_ROOT = _engine_root()

# ⭐ THE FOUR FAMILIES an agent actually READS to decide what command to run — same reasoning
# `check_engine_purity.py`'s ENGINE_FAMILIES gives, narrowed to the instructional surfaces where
# a shown invocation is something a reader (human or agent) is meant to act on. `docs/*.md` is
# deliberately OUT: it is reference/rationale material, not an instruction an agent follows —
# extending here is a reasonable future step, not a silent gap in what this gate claims to cover.
FAMILIES = (
    ("agents", os.path.join(ENGINE_ROOT, "agents", "*.md")),
    ("skills", os.path.join(ENGINE_ROOT, "skills", "*", "SKILL.md")),
    ("commands", os.path.join(ENGINE_ROOT, "commands", "*.md")),
)
RULEBOOK = os.path.join(ENGINE_ROOT, "RULEBOOK.md")

SCRIPTS_DIR = os.path.join(ENGINE_ROOT, "scripts")

FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
RUN_RE = re.compile(r"~/\.claude/jobsearch/run\s+([A-Za-z0-9_]+\.py)\b")

# argparse adds these to every parser; a script never has to spell them itself.
IMPLICIT_FLAGS = frozenset({"--help"})


# A chain operator joins two INDEPENDENT commands on one line (`applying.py && trigger.py
# --check` is a real shipped example) — each side gets its own script and its own flags, never
# shared. Splitting happens AFTER backslash-continuation joining, so a continued invocation still
# reassembles correctly before being split into its (usually one) chained segments.
_CHAIN_SPLIT_RE = re.compile(r"\s*(?:&&|;|\|)\s*")


def _logical_commands(block_text):
    """[(0-based line offset within the block, command segment)] for every launcher invocation in
    this fenced block — one entry per chain-operator-separated segment, after joining a trailing
    backslash continuation onto the next physical line (report_issue.py's own shown invocation,
    `--title ... \\` / `--symptom ...`, is exactly this shape)."""
    lines = block_text.split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        start = i
        parts = [lines[i]]
        cur = lines[i]
        while cur.rstrip().endswith("\\") and i + 1 < n:
            i += 1
            cur = lines[i]
            parts.append(cur)
        joined = " ".join(p.rstrip().rstrip("\\").strip() for p in parts)
        for segment in _CHAIN_SPLIT_RE.split(joined):
            if RUN_RE.search(segment):
                out.append((start, segment))
        i += 1
    return out


def _flags_used(command_text):
    """(script_name, [flags]) or (None, []) if this doesn't parse as a launcher invocation.

    Tokenizes with `shlex` (`comments=True` so a trailing `# explanatory prose` — this repo's
    own shipped convention right after a shown command — is never mistaken for real tokens, and
    a quoted value like `--symptom "a role below my comp floor"` stays one token) and stops
    collecting at a bare `--`, which hands the remainder to a wrapped subcommand this script's
    own argparse never sees."""
    m = RUN_RE.search(command_text)
    if not m:
        return None, []
    script = m.group(1)
    try:
        tokens = shlex.split(command_text, comments=True)
    except ValueError:
        return script, None            # unbalanced quoting — not checkable, not a violation
    try:
        idx = tokens.index(script)
    except ValueError:
        return script, None
    flags = []
    for tok in tokens[idx + 1:]:
        if tok == "--":
            break
        if tok.startswith("--"):
            flags.append(tok.split("=", 1)[0])
    return script, flags


_FLAG_CACHE = {}


def script_flags(name):
    """The set of `--long-option` strings `<name>.py`'s own `argparse` defines, via `ast` —
    never by importing the module. Most of these scripts build their parser inside `main()`, so
    nothing module-level exposes it; importing 180 scripts just to read one attribute each would
    also run whatever else sits at module scope in every one of them. Returns None when the
    script cannot be found or parsed, which the caller treats as NOT CHECKABLE, never as zero
    flags — a script this gate cannot read must never be reported as accepting nothing."""
    if name in _FLAG_CACHE:
        return _FLAG_CACHE[name]
    path = os.path.join(SCRIPTS_DIR, name)
    flags = None
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        flags = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                continue
            for arg in node.args:
                val = arg.value if isinstance(arg, ast.Constant) else None
                if isinstance(val, str) and val.startswith("--"):
                    flags.add(val)
    except (OSError, SyntaxError):
        flags = None
    _FLAG_CACHE[name] = flags
    return flags


def check_file(path):
    """[(line_no, script, bad_flag)] and the count of invocations actually checked in this file."""
    problems = []
    checked = 0
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return problems, checked
    for fm in FENCE_RE.finditer(text):
        block = fm.group(1)
        block_start_line = text[:fm.start()].count("\n")
        for offset, command in _logical_commands(block):
            script, flags = _flags_used(command)
            if script is None or flags is None:
                continue
            known = script_flags(script)
            if known is None:
                continue                # the script itself is check_pointers.py's problem
            checked += 1
            for flag in flags:
                if flag in IMPLICIT_FLAGS or flag in known:
                    continue
                problems.append((block_start_line + offset + 1, script, flag))
    return problems, checked


def _tracked_files():
    files = []
    for _name, pattern in FAMILIES:
        files += sorted(glob.glob(pattern))
    if os.path.exists(RULEBOOK):
        files.append(RULEBOOK)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true",
                    help="show every invocation checked, matching or not")
    args = ap.parse_args()

    print("CLI FLAGS — does a shown invocation match the target script's own argparse?")
    print("=" * 78)

    empty = [name for name, pat in FAMILIES if not glob.glob(pat)]
    if empty:
        print("  !! FAMILY MATCHED NOTHING: %s — a glob has gone stale." % ", ".join(empty))
        return 1

    files = _tracked_files()
    total_checked, total_problems, by_file = 0, 0, []
    for path in files:
        rel = os.path.relpath(path, ENGINE_ROOT)
        problems, checked = check_file(path)
        total_checked += checked
        if args.verbose:
            print("  %-46s %2d invocation(s) checked" % (rel, checked))
        if problems:
            by_file.append((rel, problems))
            total_problems += len(problems)

    # ⭐⭐ A SCAN THAT CHECKED NOTHING IS A FAILURE, NEVER A PASS — the same discipline
    # `check_engine_purity.py` and `check_verbatim_enums.py` both hold their coverage to. This
    # repo's shipped files carry dozens of `~/.claude/jobsearch/run` invocations; zero checked
    # means the fence or launcher regex broke, not that everything is fine.
    print("\n  scanned %d file(s) across %d famil(y/ies) · %d launcher invocation(s) checked"
          % (len(files), len(FAMILIES), total_checked))
    if total_checked == 0:
        print("\n  !! ZERO INVOCATIONS CHECKED — this is a BROKEN GATE, not a clean result.")
        print("     Either the fence/launcher regex no longer matches this repo's own shipped")
        print("     prose, or the family globs are stale. Do NOT read this as CLEAN.")
        return 1

    if not by_file:
        print("\n  CLEAN. Every shown invocation's flags exist on the script it names.")
        return 0

    print("\n  %d file(s), %d unknown flag(s):" % (len(by_file), total_problems))
    for rel, problems in by_file:
        for line_no, script, flag in problems:
            print("    %-46s %4d  %s does not define %s" % (rel, line_no, script, flag))
    print("\n  A flag shown here is not one the target script's own argparse accepts — an agent")
    print("  following this instruction verbatim would have the command refused outright.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
