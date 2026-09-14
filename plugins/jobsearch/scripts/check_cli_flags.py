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
code). Only whether every `--flag` token shown is one the script actually defines — plus, where
the flag's own `choices=` is statically readable, whether the VALUE shown is one of them.

## EXTENDED — public #90–#94's own review, dev #354 ────────────────────────────────────────────

Two gaps found building the fix for public #91 (`brief.py --probe --held` did not parse — the
flag existed, but the shown invocation could never actually reach it):

1. **A `.py` file can instruct the same way a `.md` file does.** `migrate.py` prints its own
   `next: ~/.claude/jobsearch/run brief.py --probe --held` — the exact defect class this file
   exists for, sitting in a SCRIPT, invisible to a scan that only ever opens `.md`. This is
   "scanned only markdown while the defect lived in a script" (CLAUDE.md trap 7) verbatim, so
   `plugins/jobsearch/scripts/*.py` is now scanned too — every literal string constant in the
   file (via `ast`, so an f-string's own literal segments are read but never a value plugged in
   at runtime), the same `_logical_commands` machinery applied to each one. `PY_EXCLUDE` below
   names the three files this deliberately skips, each for a stated, narrow reason — never a
   silent gap, the same discipline `KNOWN_EXCEPTIONS` holds in `check_engine_purity.py`.
2. **A flag can exist and still refuse the VALUE shown.** `--reason surface-unreachable` is a
   real flag with a real value that `journal.REASONS` (`choices=sorted(REASONS)`) refused for
   years (dev #354) — a check that only asks "does `--reason` exist" would call that CLEAN.
   `script_choices()` resolves a flag's `choices=` when it is a literal collection, or a bare/
   `sorted(...)`-wrapped module-level NAME that itself resolves to one **in the same file** —
   `journal.REASONS` is exactly this shape. Anything else (an imported name, a comprehension, a
   value built at runtime) is left unresolved — NOT CHECKABLE for that flag's value, never "it
   accepts anything."

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
PY_GLOB = os.path.join(SCRIPTS_DIR, "*.py")

# ⭐ Named, narrow, and each justified — the same discipline `check_engine_purity.py`'s
# `KNOWN_EXCEPTIONS` holds (printed every run; see main()). Never grown to "this file happens
# to fail today" — a real new false positive gets its own line here with its own reason, not a
# silent skip.
PY_EXCLUDE = {
    "check_cli_flags.py": "self-referential — its own module docstring quotes public #82's "
                          "ORIGINAL bad invocation (`--severity`/`--owner`) as the narrative "
                          "example of the defect this file exists to catch, not as a live "
                          "instruction. Scanning it would flag its own explanation.",
    "test_checks.py": "the regression suite, never an instructional surface a reader or agent "
                      "acts on — the same reasoning FAMILIES already states for excluding "
                      "docs/*.md, applied to the one script guaranteed to quote invocations "
                      "(including deliberately-broken ones) for reasons that have nothing to "
                      "do with what an agent should run.",
    "install_launcher.py": "`TEMPLATE` is the generated `~/.claude/jobsearch/run` shell "
                           "script's OWN text, embedded as one large string — its comments "
                           "show illustrative placeholder flags (`--flag`) no static scan can "
                           "tell apart from a real one.",
}

FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
RUN_RE = re.compile(r"~/\.claude/jobsearch/run\s+([A-Za-z0-9_]+\.py)\b")

# argparse adds these to every parser; a script never has to spell them itself.
IMPLICIT_FLAGS = frozenset({"--help"})

# ⭐ A `.py` literal (unlike a markdown fence) is often a %-format or f-string TEMPLATE — the
# value shown is filled in at runtime, not written down (`"--set-mode %s" % mode`,
# letter_out.py's own line). A token shaped like a bare printf/`.format`/f-string placeholder
# is therefore NOT a value this gate can check — skip it as unresolvable, never flag it as a
# bad choice (it is not a choice at all, real or fake).
_PLACEHOLDER_RE = re.compile(r"^(%[sdr]|\{[^{}]*\})$")


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
    """(script_name, [(flag, value_or_None)]) or (None, []) if this doesn't parse as a
    launcher invocation.

    Tokenizes with `shlex` (`comments=True` so a trailing `# explanatory prose` — this repo's
    own shipped convention right after a shown command — is never mistaken for real tokens, and
    a quoted value like `--symptom "a role below my comp floor"` stays one token) and stops
    collecting at a bare `--`, which hands the remainder to a wrapped subcommand this script's
    own argparse never sees.

    `value` is simply the NEXT token when it does not itself look like another flag — never
    validated against anything here (the caller decides, per-flag, whether a `choices=` value
    check even applies, via `script_choices()`). A boolean (`store_true`) flag's own next token
    is still captured this way; it is simply never looked up in `script_choices()`, which only
    ever holds entries for flags that actually declare `choices=` — so a boolean flag's
    incidental "value" here is inert, never checked, never reported."""
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
    rest = tokens[idx + 1:]
    n = len(rest)
    flags = []
    for i, tok in enumerate(rest):
        if tok == "--":
            break
        if not tok.startswith("--"):
            continue
        if "=" in tok:
            flag, val = tok.split("=", 1)
        else:
            flag = tok
            val = rest[i + 1] if (i + 1 < n and not rest[i + 1].startswith("--")) else None
        flags.append((flag, val))
    return script, flags


_FLAG_CACHE = {}
_TREE_CACHE = {}
_CHOICES_CACHE = {}


def _script_tree(name):
    """The parsed `ast` of `<name>.py`, cached — `script_flags` and `script_choices` both walk
    it, and a script this large is worth parsing once. None when the file cannot be found or
    does not parse (a syntax error is `check_marketplace.py`'s problem, not this gate's)."""
    if name in _TREE_CACHE:
        return _TREE_CACHE[name]
    path = os.path.join(SCRIPTS_DIR, name)
    tree = None
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError):
        tree = None
    _TREE_CACHE[name] = tree
    return tree


def script_flags(name):
    """The set of `--long-option` strings `<name>.py`'s own `argparse` defines, via `ast` —
    never by importing the module. Most of these scripts build their parser inside `main()`, so
    nothing module-level exposes it; importing 180 scripts just to read one attribute each would
    also run whatever else sits at module scope in every one of them. Returns None when the
    script cannot be found or parsed, which the caller treats as NOT CHECKABLE, never as zero
    flags — a script this gate cannot read must never be reported as accepting nothing."""
    if name in _FLAG_CACHE:
        return _FLAG_CACHE[name]
    tree = _script_tree(name)
    flags = None
    if tree is not None:
        flags = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                continue
            for arg in node.args:
                val = arg.value if isinstance(arg, ast.Constant) else None
                if isinstance(val, str) and val.startswith("--"):
                    flags.add(val)
    _FLAG_CACHE[name] = flags
    return flags


def _literal_str_collection(expr):
    """The frozenset of string constants a literal `{...}`/`[...]`/`(...)` or a
    `frozenset(...)`/`set(...)`/`tuple(...)`/`list(...)` call around one spells out, or None
    for anything else (a name, a comprehension, an f-string, a call to something else) — and
    None (never a partial set) the moment any single element is not itself a plain string
    constant, so a collection this cannot read in full is never reported as read at all."""
    if isinstance(expr, (ast.Set, ast.List, ast.Tuple)):
        elts = expr.elts
    elif (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
          and expr.func.id in ("frozenset", "set", "tuple", "list") and len(expr.args) == 1
          and not expr.keywords):
        return _literal_str_collection(expr.args[0])
    else:
        return None
    out = []
    for e in elts:
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            out.append(e.value)
        else:
            return None
    return frozenset(out)


def script_choices(name):
    """{flag: frozenset(allowed values)} for every `add_argument(..., choices=...)` in
    `<name>.py` whose choices are STATICALLY resolvable — a literal collection right there in
    the call, or a bare/`sorted(...)`-wrapped reference to a module-level NAME that itself
    resolves (in the SAME file, via `_literal_str_collection`) to one — `journal.REASONS` then
    `choices=sorted(REASONS)` is exactly this shape (dev #354). A flag whose `choices=` is
    anything else (an imported name, a comprehension, something computed) is simply ABSENT
    from the returned dict — the caller must read that as NOT CHECKABLE for this flag's value,
    never as "any value is accepted."""
    if name in _CHOICES_CACHE:
        return _CHOICES_CACHE[name]
    tree = _script_tree(name)
    result = {}
    if tree is not None:
        module_literals = {}
        for node in ast.iter_child_nodes(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                vals = _literal_str_collection(node.value)
                if vals is not None:
                    module_literals[node.targets[0].id] = vals

        def _resolve(expr):
            vals = _literal_str_collection(expr)
            if vals is not None:
                return vals
            if isinstance(expr, ast.Name):
                return module_literals.get(expr.id)
            if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
                    and expr.func.id in ("sorted", "list", "tuple", "set", "frozenset")
                    and len(expr.args) == 1 and not expr.keywords):
                return _resolve(expr.args[0])
            return None

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                continue
            flags = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    and a.value.startswith("--")]
            if not flags:
                continue
            resolved = None
            for kw in node.keywords:
                if kw.arg == "choices":
                    resolved = _resolve(kw.value)
                    break
            if resolved:
                for f in flags:
                    result[f] = resolved
    _CHOICES_CACHE[name] = result
    return result


# A flag whose own `action=`/`nargs=` means it NEVER takes a following value — a shown
# `--flag <next-flag>` is never mistaken for "no value given" against one of these.
_NO_VALUE_ACTIONS = frozenset({"store_true", "store_false", "count", "store_const",
                              "append_const", "help", "version"})

_ARITY_CACHE = {}


def script_arities(name):
    """{flag: "required"|"optional"} for every `add_argument` in `<name>.py` — never an entry
    for a flag whose `action=` means it takes NO value at all (`store_true` and siblings,
    `IMPLICIT_FLAGS`'s own `--help`); absence here means "this flag never expects a following
    token", the mirror image of `script_choices`'s absence meaning "unresolvable."

    ⭐ Public #91's own class, generalised: `--probe` (no `nargs=`, the argparse default of
    exactly one required value) followed immediately by ANOTHER recognised flag rather than a
    plain value — `--probe --held` — is a shown invocation `argparse` refuses outright
    ('expected one argument'), independent of whether `--probe` itself exists or `--held` is a
    real flag; checking flag-existence and `choices=` alone, as this file did before, missed
    this shape entirely. `nargs="?"`/`"*"` (this file's own post-#91 fix to `brief.py --probe`)
    is "optional" — a following flag or nothing at all is fine, by the SAME argparse rule that
    made the bug possible in the first place: `nargs="?"` explicitly declines to consume a
    token that looks like another option."""
    if name in _ARITY_CACHE:
        return _ARITY_CACHE[name]
    tree = _script_tree(name)
    result = {}
    if tree is not None:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                continue
            flags = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    and a.value.startswith("--")]
            if not flags:
                continue
            action = nargs = None
            for kw in node.keywords:
                if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                    action = kw.value.value
                elif kw.arg == "nargs":
                    nargs = kw.value.value if isinstance(kw.value, ast.Constant) else "?"
            if action in _NO_VALUE_ACTIONS or nargs == 0:
                continue                                   # never takes a value — no entry
            arity = "optional" if nargs in ("?", "*") else "required"
            for f in flags:
                result[f] = arity
    _ARITY_CACHE[name] = result
    return result


def _check_commands(commands):
    """Shared by `check_file` (markdown, fence-sourced) and `check_py_file` (`.py`, ast-sourced):
    given [(line_no, command_text)], the same flag-existence + choices-value + required-value
    checks, once. Returns ([(line_no, script, kind, detail)], checked_count) — `kind` is one of
    `"unknown-flag"` (`detail` unused), `"bad-value"` (`detail` the resolved choices frozenset),
    or `"missing-value"` (`detail` unused: the flag is shown with nothing after it that could be
    its value — end of command, or immediately followed by another recognised flag)."""
    problems = []
    checked = 0
    for line_no, command in commands:
        script, flags = _flags_used(command)
        if script is None or flags is None:
            continue
        known = script_flags(script)
        if known is None:
            continue                    # the script itself is check_pointers.py's problem
        checked += 1
        allowed_by_flag = script_choices(script)
        required_by_flag = script_arities(script)
        for flag, val in flags:
            if flag not in IMPLICIT_FLAGS and flag not in known:
                problems.append((line_no, script, "unknown-flag", flag, None))
                continue
            if val is None and required_by_flag.get(flag) == "required":
                problems.append((line_no, script, "missing-value", flag, None))
                continue
            allowed = allowed_by_flag.get(flag)
            if (allowed is not None and val is not None
                    and not _PLACEHOLDER_RE.match(val) and val not in allowed):
                problems.append((line_no, script, "bad-value", "%s %s" % (flag, val), allowed))
    return problems, checked


def check_file(path):
    """[(line_no, script, kind, what, detail)] and the count of invocations actually
    checked in this markdown/RULEBOOK file — commands sourced from FENCED code blocks only
    (see the module docstring's own narrow-scope reasoning)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return [], 0
    commands = []
    for fm in FENCE_RE.finditer(text):
        block = fm.group(1)
        block_start_line = text[:fm.start()].count("\n")
        for offset, command in _logical_commands(block):
            commands.append((block_start_line + offset + 1, command))
    return _check_commands(commands)


def check_py_file(path):
    """[(line_no, script, kind, what, detail)] and the count checked in this `.py` file —
    commands sourced from every literal STRING CONSTANT in the file (via `ast`, so an
    f-string's own literal segments are read, never a value only known at runtime), each run
    through the same `_logical_commands` machinery a fenced markdown block gets. See the
    module docstring's EXTENDED section for why this exists (public #91) and `PY_EXCLUDE` for
    the three files it deliberately does not scan."""
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return [], 0
    commands = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        base_line = getattr(node, "lineno", 1) - 1
        for offset, command in _logical_commands(node.value):
            commands.append((base_line + offset + 1, command))
    return _check_commands(commands)


def _tracked_files():
    files = []
    for _name, pattern in FAMILIES:
        files += sorted(glob.glob(pattern))
    if os.path.exists(RULEBOOK):
        files.append(RULEBOOK)
    return files


def _tracked_py_files():
    return sorted(p for p in glob.glob(PY_GLOB) if os.path.basename(p) not in PY_EXCLUDE)


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
    if not glob.glob(PY_GLOB):
        print("  !! FAMILY MATCHED NOTHING: scripts (%s) — a glob has gone stale." % PY_GLOB)
        return 1

    files = _tracked_files()
    py_files = _tracked_py_files()
    total_checked, total_problems, by_file = 0, 0, []
    for path, checker in [(p, check_file) for p in files] + \
                          [(p, check_py_file) for p in py_files]:
        rel = os.path.relpath(path, ENGINE_ROOT)
        problems, checked = checker(path)
        total_checked += checked
        if args.verbose:
            print("  %-46s %2d invocation(s) checked" % (rel, checked))
        if problems:
            by_file.append((rel, problems))
            total_problems += len(problems)

    # ⭐⭐ A SCAN THAT CHECKED NOTHING IS A FAILURE, NEVER A PASS — the same discipline
    # `check_engine_purity.py` and `check_verbatim_enums.py` both hold their coverage to. This
    # repo's shipped files carry dozens of `~/.claude/jobsearch/run` invocations; zero checked
    # means the fence/ast or launcher regex broke, not that everything is fine.
    print("\n  scanned %d markdown file(s) across %d famil(y/ies) + %d script(s) "
          "(%d excluded, named) · %d launcher invocation(s) checked"
          % (len(files), len(FAMILIES), len(py_files), len(PY_EXCLUDE), total_checked))
    if total_checked == 0:
        print("\n  !! ZERO INVOCATIONS CHECKED — this is a BROKEN GATE, not a clean result.")
        print("     Either the fence/ast/launcher regex no longer matches this repo's own")
        print("     shipped prose, or the family/script globs are stale. Do NOT read this as")
        print("     CLEAN.")
        return 1

    if not by_file:
        print("\n  CLEAN. Every shown invocation's flags — and every value shown for a flag "
              "whose\n  choices= this gate could resolve — are ones the target script actually "
              "accepts.")
        return 0

    print("\n  %d file(s), %d problem(s):" % (len(by_file), total_problems))
    for rel, problems in by_file:
        for line_no, script, kind, what, detail in problems:
            if kind == "unknown-flag":
                print("    %-46s %4d  %s does not define %s" % (rel, line_no, script, what))
            elif kind == "missing-value":
                print("    %-46s %4d  %s's %s requires a value — none is shown (end of "
                      "command, or immediately followed by another flag)"
                      % (rel, line_no, script, what))
            else:                                                    # bad-value
                print("    %-46s %4d  %s — %s is not one of {%s}"
                      % (rel, line_no, script, what, ", ".join(sorted(detail))))
    print("\n  A flag or value shown here is not one the target script's own argparse accepts —")
    print("  an agent following this instruction verbatim would have the command refused")
    print("  outright.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
