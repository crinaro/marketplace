"""guarding.matching -- which subcommands are a publish: `deploy.py` with `--confirm`, `adopt.py report --file` (with `--suggestion`:
the kind `suggestion`, 0.7.0), `adopt.py apply` (no
`--dry-run`), each abbreviation-tolerant (the conservative direction), recursing into quoted strings that hold a name
(`sh -c '...'`). Also the hooks.json early-gate patterns in Python (`_mentions_*`) and the `cd`/`pushd` the target follows.
"""
import os
from guarding.lexing import split_subcommands


MAX_DEPTH = 4


def _is_deploy_token(tok):
    return os.path.basename(tok).lower() == "deploy.py"


def _is_confirm_token(tok):
    return tok == "--confirm" or tok.startswith("--confirm=") or (
        len(tok) >= 4 and tok.startswith("--co") and "--confirm".startswith(tok))


def _has_confirm(tokens):
    return any(_is_confirm_token(t) for t in tokens)


def _mentions_deploy(text):
    return "deploy.py" in text.lower()


def _is_adopt_token(tok):
    return os.path.basename(tok).lower() == "adopt.py"


def _is_file_token(tok):
    """`--file`, `--file=<x>` or an abbreviation of it from `--f` up (the `report` subparser refuses one: matching it
    here is the conservative direction)."""
    return tok.startswith("--file=") or (len(tok) >= 3 and tok.startswith("--f") and "--file".startswith(tok))


def _has_report_file(tokens):
    """`adopt.py ... report ... --file`, in that order: the one adopt call that files issues."""
    i = next((k for k, t in enumerate(tokens) if _is_adopt_token(t)), None)
    if i is None:
        return False
    j = next((k for k in range(i + 1, len(tokens)) if tokens[k].lower() == "report"), None)
    return j is not None and any(_is_file_token(t) for t in tokens[j + 1:])


def _has_suggestion(tokens):
    """`adopt.py ... report ... --suggestion` (0.7.0, design-adopt-ownership-line 13.5): a report that files ONE look suggestion.
    Exact, as the `report` subparser takes it (allow_abbrev=False): an abbreviation is still a report, and asks as one."""
    i = next((k for k, t in enumerate(tokens) if _is_adopt_token(t)), None)
    j = next((k for k in range(i + 1, len(tokens)) if tokens[k].lower() == "report"), None) if i is not None else None
    return j is not None and any(t == "--suggestion" or t.startswith("--suggestion=") for t in tokens[j + 1:])


def _mentions_report(text):
    """The hooks.json pattern in Python: `adopt.py`, then `report` somewhere after it, in any case."""
    low = text.lower()
    i = low.find("adopt.py")
    return i >= 0 and "report" in low[i + len("adopt.py"):]


def _has_apply(tokens):
    """`adopt.py ... apply ...` with no exact `--dry-run` after it: the one adopt call that publishes and retires."""
    i = next((k for k, t in enumerate(tokens) if _is_adopt_token(t)), None)
    if i is None:
        return False
    j = next((k for k in range(i + 1, len(tokens)) if tokens[k].lower() == "apply"), None)
    return j is not None and "--dry-run" not in tokens[j + 1:]


def _mentions_apply(text):
    """The hooks.json pattern in Python: `adopt.py`, then `apply` somewhere after it, in any case."""
    low = text.lower()
    i = low.find("adopt.py")
    return i >= 0 and "apply" in low[i + len("adopt.py"):]


def _mentions_a_publish(text):
    return _mentions_deploy(text) or _mentions_report(text) or _mentions_apply(text)


def _cd_target(tokens, cwd):
    """The directory after a `cd` / `pushd` subcommand, or None when it cannot be resolved."""
    args = [t for t in tokens[1:] if not (t.startswith("-") and t != "-")]
    if not args:
        return os.path.expanduser("~")
    t = args[0]
    if t == "-":
        return None
    t = os.path.expandvars(os.path.expanduser(t))
    if "$" in t or "`" in t:
        return None
    if cwd is None:
        return os.path.abspath(t) if os.path.isabs(t) else None
    return os.path.abspath(os.path.join(cwd, t))


def scan(cmd, cwd, depth=0):
    """Every deploy.py-with-confirm and adopt.py-report-with-file subcommand in `cmd`, as (kind, cwd at that
    point, tokens), kind 'confirm' or 'report'. `cwd` is None when unresolvable. Recurses into quoted strings
    that hold either name (sh -c '...')."""
    found = []
    for tokens in split_subcommands(cmd):
        head = os.path.basename(tokens[0]) if tokens else ""
        if head in ("cd", "pushd"):
            cwd = _cd_target(tokens, cwd)
            continue
        if any(_is_deploy_token(t) for t in tokens) and _has_confirm(tokens):
            found.append(("confirm", cwd, tokens))
            continue
        if _has_report_file(tokens):
            found.append(("suggestion" if _has_suggestion(tokens) else "report", cwd, tokens))
            continue
        if _has_apply(tokens):
            found.append(("apply", cwd, tokens))
            continue
        if depth < MAX_DEPTH:
            for t in tokens:
                if (" " in t or "\n" in t or ";" in t or "&" in t) and _mentions_a_publish(t):
                    found.extend(scan(t, cwd, depth + 1))
    return found


def command_text(payload):
    """The text to scan: tool_input.command when there is one, else every string in tool_input
    (Monitor and terminal-panel tools carry the command under other keys)."""
    ti = payload.get("tool_input")
    if isinstance(ti, dict) and isinstance(ti.get("command"), str):
        return ti["command"]
    parts = []

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(ti)
    return "\n".join(parts)
