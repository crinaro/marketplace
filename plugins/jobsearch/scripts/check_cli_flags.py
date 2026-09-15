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


# ══════════════════════════════════════════════════════════════════════════════════════════════
# DECLARED-BUT-UNREAD FLAGS — public #91's class, one level deeper (dev #368, release-blocker)
# ══════════════════════════════════════════════════════════════════════════════════════════════
#
# Everything above answers "does a SHOWN invocation match the script's own argparse". This
# answers a different question about the SAME script: a flag `add_argument`'d in `main()` and
# never read anywhere is not a documentation drift, it is a NO-OP BY CONSTRUCTION — `argparse`
# accepts it, parses it, and nothing downstream ever looks at `args.<dest>`. `plays.py --confirm
# default-plan` was exactly this: the flag parsed, `main()`'s own if/elif chain never checked
# `args.confirm` at all, and the call fell through to `ap.print_help(); return 0` — exit 0, the
# owner reads success, and the play never turns on. `check_cli_flags.py` above was silent
# because a SHOWN invocation matching the target's argparse was never the question that mattered
# here; nothing upstream of "is the flag readable" checks whether it is ever actually read.
#
# THE MECHANISM — every `--flag` declared via `add_argument(...)` INSIDE a script's own `main()`
# must be read somewhere in that file as `<args-var>.<dest>` — `dest` computed the way argparse
# itself computes it (an explicit `dest=` kwarg, else the first `--long-option` string with `-`
# turned into `_`). "Somewhere in that file", never "somewhere in main() itself": `record.py`
# passes its own `args` object to `cmd_touched(args)`/`cmd_answered(args)`, functions defined
# elsewhere in the same file, and every field either of them reads off `args` is a real read —
# scoping the SEARCH to main() while scoping the DECLARATION to main() is deliberate and
# asymmetric, matching how these scripts are actually shaped.
#
# THE ESCAPE HATCH, NAMED: `vars(<args-var>)` or `getattr(<args-var>, <non-literal>)` anywhere in
# the file means the script reads its flags DYNAMICALLY — by iterating every field, or by name
# built at runtime — which this static check cannot trace through. Either shape allowlists EVERY
# declared dest for that args variable (never a per-flag guess at what a dynamic read might
# reach): a script doing this has opted out of the one thing this check can verify, exactly the
# way `check_cli_flags.py`'s own `script_choices()` leaves an unresolvable `choices=` absent
# rather than reporting a false "accepts anything" or a false "accepts nothing".
#
# WHAT THIS DOES NOT CHECK, STATED: a short-option-only flag (`-x` with no `--long` form) is
# skipped — `check_cli_flags.py` itself only ever tracks `--long-option` strings, the same scope
# this shares. A script whose shape this cannot read at all (no `def main()`, no single
# `X = argparse.ArgumentParser(...)` assignment inside it, no `Y = X.parse_args(...)` from that
# same `X`) returns None — NOT CHECKABLE, counted and printed as such, never silently "clean".
# A `--flag` string built at runtime rather than written as a literal is likewise unreadable for
# ITS OWN dest and is skipped for that one entry, never guessed at.

_UNREAD_TREE_CACHE = {}


def _unread_script_tree(name):
    """Same contract as `_script_tree`, but keyed on the FULL PATH rather than the basename —
    this scan runs over every `.py` under `SCRIPTS_DIR` (no `PY_EXCLUDE`: that list narrows the
    shown-invocation scan above for reasons specific to THAT check; a script can be exempt from
    'does this file quote a bad invocation' and still owe a real answer to 'is every flag it
    declares ever read'), and `_script_tree`'s own cache is keyed by basename against
    `SCRIPTS_DIR` alone — wrong the moment a test repoints `SCRIPTS_DIR` mid-suite (the existing
    `TestCliInvocationsMatchArgparse` pattern), which this reuses via `path` directly instead."""
    if name in _UNREAD_TREE_CACHE:
        return _UNREAD_TREE_CACHE[name]
    path = os.path.join(SCRIPTS_DIR, name)
    tree = None
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        tree = None
    _UNREAD_TREE_CACHE[name] = tree
    return tree


def _find_main(tree):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    return None


def _parser_vars(main_fn):
    """Every name assigned `argparse.ArgumentParser(...)` (or a bare `ArgumentParser(...)`, for
    a script that did `from argparse import ArgumentParser`) inside `main()`, as a set. The
    caller distinguishes ZERO (this `main()` uses no argparse at all — vacuously nothing to
    check) from MORE THAN ONE (a subparser shape this check does not attempt to disentangle —
    genuinely not checkable) from exactly one (the normal, checkable shape)."""
    names = set()
    for node in ast.walk(main_fn):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        v = node.value
        is_parser_call = (isinstance(v, ast.Call) and (
            (isinstance(v.func, ast.Attribute) and v.func.attr == "ArgumentParser") or
            (isinstance(v.func, ast.Name) and v.func.id == "ArgumentParser")))
        if is_parser_call:
            names.add(node.targets[0].id)
    return names


def _single_args_var(main_fn, parser_name):
    """The ONE name assigned `<parser_name>.parse_args(...)` inside `main()`, or None."""
    names = set()
    for node in ast.walk(main_fn):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        v = node.value
        if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                and v.func.attr == "parse_args" and isinstance(v.func.value, ast.Name)
                and v.func.value.id == parser_name):
            names.add(node.targets[0].id)
    return next(iter(names)) if len(names) == 1 else None


def _add_argument_dest(call):
    """(flag, dest) for one `add_argument(...)` call, or (flag, None) when `dest` cannot be
    read (no `--long-option` literal among the positional args — a short-option-only flag, or
    one built at runtime) — `flag` itself is None only when there is no `--`-prefixed literal
    argument at all (nothing here to report)."""
    dest_kw = None
    for kw in call.keywords:
        if kw.arg == "dest" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            dest_kw = kw.value.value
    flag = None
    for a in call.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("--"):
            flag = a.value
            break
    if flag is None:
        return None, None
    return flag, (dest_kw if dest_kw is not None else flag[2:].replace("-", "_"))


def declared_but_unread(name):
    """[(flag, dest)] declared in `<name>.py`'s own `main()` and never read anywhere in the
    file — or None when this script's shape is not one the check can read at all (see the
    module-level comment above). An empty list is a genuine CLEAN, not "nothing checked"."""
    tree = _unread_script_tree(name)
    if tree is None:
        return None
    main_fn = _find_main(tree)
    if main_fn is None:
        return None
    parser_names = _parser_vars(main_fn)
    if not parser_names:
        return []                          # main() uses no argparse — nothing to check, CLEAN
    if len(parser_names) != 1:
        return None                        # ambiguous multi-parser shape — not checkable
    parser_name = next(iter(parser_names))
    args_name = _single_args_var(main_fn, parser_name)
    if args_name is None:
        return None

    declared = {}                          # dest -> flag, first flag wins (printing only)
    for node in ast.walk(main_fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == parser_name):
            continue
        flag, dest = _add_argument_dest(node)
        if flag is None or dest is None:
            continue
        declared.setdefault(dest, flag)
    if not declared:
        return []

    # THE ESCAPE HATCH — vars(args)/getattr(args, <non-literal>) anywhere in the WHOLE FILE,
    # not just main(): a script that reads its flags dynamically is checked nowhere near as
    # precisely, so it is allowlisted wholesale rather than false-flagged per field.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (isinstance(node.func, ast.Name) and node.func.id == "vars" and node.args
                and isinstance(node.args[0], ast.Name) and node.args[0].id == args_name):
            return []
        if (isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name) and node.args[0].id == args_name
                and not (isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str))):
            return []

    read = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == args_name):
            read.add(node.attr)
        # `getattr(args, 'confirm', ...)` with a LITERAL attribute name is an ordinary read of
        # that one dest, not the dynamic escape hatch above (which only fires for a non-literal
        # second argument) — real, if unusual, shape: a caller reading one flag with a default.
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2
              and isinstance(node.args[0], ast.Name) and node.args[0].id == args_name
              and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            read.add(node.args[1].value)

    return [(flag, dest) for dest, flag in declared.items() if dest not in read]


def check_unread_flags(py_files):
    """(problems, checked, not_checkable) across every `.py` in `py_files` — `problems` is
    [(basename, [(flag, dest), ...])] for a script with at least one genuinely unread flag,
    UNFILTERED (the allowlist below is applied by the caller, so a stale entry can be detected
    against the raw finding, never against an already-filtered one)."""
    problems, checked, not_checkable = [], 0, []
    for path in py_files:
        name = os.path.basename(path)
        hits = declared_but_unread(name)
        if hits is None:
            not_checkable.append(name)
            continue
        checked += 1
        if hits:
            problems.append((name, hits))
    return problems, checked, not_checkable


# ⭐ Named, narrow, printed every run — the same discipline `check_engine_purity.py`'s
# `KNOWN_EXCEPTIONS` and this file's own `PY_EXCLUDE` hold: never a silent skip, and a STALE
# entry (naming a (script, dest) this scan no longer finds unread) FAILS the gate — see
# `_apply_unread_allowlist` — so a fix cannot silently outlive its own exemption. Two shapes,
# both found running this check across every shipped script (issue #368):
#   documented no-op   the flag's own help text (or its unambiguous shape — every other flag
#                       absent reaches the identical branch) already says it changes nothing;
#                       the flag exists so a caller can be explicit, never to gate behavior.
#   filed, not fixed   a real gap this pass did not close — what the flag SHOULD do was never
#                       specified, and guessing risks a check that quietly changes what it
#                       flags. Named against the issue that tracks it, never left to rot.
UNREAD_ALLOWLIST = {
    ("check_profile_leakage.py", "strict"):
        "documented no-op — its own help text: '(default) exit 1 on drift'; omitting --report "
        "already reaches this behavior (issue #368).",
    ("coordinator.py", "no_take"):
        "documented no-op — its own help text: 'Deprecated no-op; not taking the lock is now "
        "the default.' (issue #368).",
    ("init_profile.py", "check"):
        "documented no-op — its own help text ('Report what exists; change nothing.') names "
        "exactly the `not args.scaffold` fallthrough, reached whether or not --check is passed "
        "(issue #368).",
    ("letter_out.py", "status"):
        "documented-shape no-op — the un-flagged fallthrough (`return status()`) reached when "
        "neither --set-mode nor --render is given — the same shape as mailboxes.py/sync.py "
        "below (issue #368).",
    ("variant_out.py", "status"):
        "documented-shape no-op — same shape as letter_out.py's own --status above, its twin "
        "renderer (public #64): the un-flagged fallthrough (`return status()`) is reached "
        "whether or not --status is given, whenever neither --set-mode nor --render is.",
    ("mailboxes.py", "status"):
        "documented-shape no-op — its own help text ('what is configured and what works') is "
        "the un-flagged fallthrough reached when neither --add nor --remove is given "
        "(issue #368).",
    ("sync.py", "status"):
        "documented no-op — its own help text: 'human-readable report (default)'; the "
        "un-flagged fallthrough reached when none of --json/--set/--end-of-run is given "
        "(issue #368).",
    ("check_action_claims.py", "verbose"):
        "FILED, not fixed — genuinely unread, and what it should print was never specified; "
        "guessing risks a check that quietly changes what it flags. Follow-up: issue #368.",
    ("check_engine_purity.py", "all"):
        "FILED, not fixed — genuinely unread ('Audit every class, advisory only' was never "
        "wired to anything); implementing a guess at 'every class' risks masking a real purity "
        "finding rather than surfacing one. Follow-up: issue #368.",
}


def _apply_unread_allowlist(problems):
    """(filtered_problems, matched_keys) — `problems` (as `check_unread_flags` returns them,
    unfiltered) with every `UNREAD_ALLOWLIST`-covered (script, dest) removed; `matched_keys` is
    every allowlist entry that actually matched something, for the staleness check in `main()`
    (an entry matching NOTHING is stale — the flag it names is no longer unread, so keeping the
    exemption around would hide the NEXT real regression on that same flag)."""
    filtered = []
    matched = set()
    for name, hits in problems:
        remaining = []
        for flag, dest in hits:
            key = (name, dest)
            if key in UNREAD_ALLOWLIST:
                matched.add(key)
            else:
                remaining.append((flag, dest))
        if remaining:
            filtered.append((name, remaining))
    return filtered, matched


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
        invocations_rc = 0
    else:
        print("\n  %d file(s), %d problem(s):" % (len(by_file), total_problems))
        for rel, problems in by_file:
            for line_no, script, kind, what, detail in problems:
                if kind == "unknown-flag":
                    print("    %-46s %4d  %s does not define %s" % (rel, line_no, script, what))
                elif kind == "missing-value":
                    print("    %-46s %4d  %s's %s requires a value — none is shown (end of "
                          "command, or immediately followed by another flag)"
                          % (rel, line_no, script, what))
                else:                                                # bad-value
                    print("    %-46s %4d  %s — %s is not one of {%s}"
                          % (rel, line_no, script, what, ", ".join(sorted(detail))))
        print("\n  A flag or value shown here is not one the target script's own argparse "
              "accepts —")
        print("  an agent following this instruction verbatim would have the command refused")
        print("  outright.")
        invocations_rc = 1

    # ── declared-but-unread flags — a different question about the same scripts (see the
    # module-level comment above `declared_but_unread`) ─────────────────────────────────────
    print()
    print("DECLARED-BUT-UNREAD — every add_argument() in a script's own main() actually read?")
    print("=" * 78)
    all_py = sorted(glob.glob(PY_GLOB))
    unread_raw, unread_checked, not_checkable = check_unread_flags(all_py)
    unread_problems, matched_allow = _apply_unread_allowlist(unread_raw)
    # Staleness is only meaningful for an entry whose named SCRIPT was actually part of this
    # scan — a synthetic/partial tree (a test's own throwaway `SCRIPTS_DIR`) legitimately
    # scans none of the real files UNREAD_ALLOWLIST names, and that is not the same claim as
    # "this flag is read again now, delete the entry". Silently irrelevant, never silently
    # stale.
    scanned_names = {os.path.basename(p) for p in all_py}
    stale_allow = sorted((name, dest) for (name, dest) in UNREAD_ALLOWLIST
                         if name in scanned_names and (name, dest) not in matched_allow)
    print("  %d script(s) checked · %d not checkable (no main()/single parser+args shape) · "
         "%d allowlisted (documented no-op / filed, named) · %d with a live hit"
         % (unread_checked, len(not_checkable), len(matched_allow), len(unread_problems)))
    if args.verbose:
        if not_checkable:
            print("  not checkable: %s" % ", ".join(not_checkable))
        if matched_allow:
            print("  allowlisted:")
            for name, dest in sorted(matched_allow):
                print("    %-30s %-14s %s" % (name, dest, UNREAD_ALLOWLIST[(name, dest)]))
    unread_rc = 0
    if unread_checked == 0:
        print("\n  !! ZERO SCRIPTS CHECKED — this is a BROKEN GATE, not a clean result.")
        print("     Either PY_GLOB has gone stale or every script's main()/parser shape")
        print("     changed underneath this scan. Do NOT read this as CLEAN.")
        unread_rc = 1
    if stale_allow:
        print("\n  !! %d STALE ALLOWLIST ENTRY(IES) — named, but no longer found unread:"
             % len(stale_allow))
        for name, dest in stale_allow:
            print("    %-30s %s" % (name, dest))
        print("  Either the flag is read again (good — delete the entry) or this scan's own")
        print("  shape changed under it (bad — the exemption may now be covering something")
        print("  else). A suppression cannot outlive its defect (check_engine_purity.py's own")
        print("  KNOWN_EXCEPTIONS discipline, applied here).")
        unread_rc = 1
    if unread_problems:
        print("\n  %d script(s), flag(s) declared and never read:" % len(unread_problems))
        for name, hits in unread_problems:
            for flag, dest in hits:
                print("    %-30s %s  (args.%s never appears in the file — argparse accepts "
                     "and silently drops it)" % (name, flag, dest))
        print("\n  A flag argparse accepts but nothing ever reads is a NO-OP BY CONSTRUCTION —")
        print("  the exact shape `plays.py --confirm` shipped with (issue #368): it parsed,")
        print("  and main()'s own dispatch never checked it, so the call fell through to")
        print("  --help and exited 0. Read args.<dest> somewhere, allowlist it with a named")
        print("  reason, or drop the flag.")
        unread_rc = 1
    if unread_rc == 0 and unread_checked:
        print("\n  CLEAN. Every declared flag this gate could resolve is either read somewhere "
              "in its own file, or allowlisted above with a named reason.")

    return 1 if (invocations_rc or unread_rc) else 0


if __name__ == "__main__":
    sys.exit(main())
