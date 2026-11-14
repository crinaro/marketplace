#!/usr/bin/env python3
"""publish_guard.py -- the PreToolUse hook that carries the human act of publishing (dev #835,
design 7.4; named changes S1, S3, S4, S10, M1, M5, M7). Python 3.9, standard library only.

WHAT IT DOES
------------
Reads one PreToolUse payload on stdin. If the command (or, for a tool that is not Bash, any
string in `tool_input`) RUNS `deploy.py` with `--confirm`, it decides:

  CLAUDE_CODE_REMOTE == "true"                        -> deny  (the policy sentence)
  permission_mode in default, acceptEdits, plan, auto -> ask   (text below)
  any other mode, or no mode field                    -> deny  (named reason)

and anything else gets NO decision: exit 0 with no output, which leaves the normal permission
flow alone. `ask` text: "Publish N files to <publicRepo>, public forever? Review: <verdict> on
<date>, <k> files opened, accepted <ids or none>. Digest <first 12>." Why `ask` and not a token:
any token a dry run prints, the model reads; the documented permission prompt is the one place a
person's click is required and the model cannot supply it.

THE MODE LIST IS AN ALLOWLIST (S4). Only the modes the P-7 probe covers get an `ask`. A mode the
harness adds later, or a payload with no `permission_mode` (an older Claude Code), is DENIED with
a reason that names it. The hooks page says in `auto` mode a PreToolUse `ask` "normally" goes to
the permission prompt; `auto` stays in the ask row CONDITIONALLY on P-7's auto case (DOCUMENTED-
HEDGED). The fetched hooks page does not say what `ask` does under `dontAsk`, or whether `deny`
is honoured in `bypassPermissions` (page truncated); those two modes get `deny` and the quotes are
UNDETERMINED until confirmed against the full page.

THE TARGET REPO COMES FROM THE COMMAND, NEVER FROM THE SESSION (S1, S10, M5(b))
------------------------------------------------------------------------------
The shell prefix in hooks.json starts this script only when the payload text contains `deploy.py`
(any case: macOS volumes are case-insensitive), whatever `CLAUDE_PROJECT_DIR` is. This script then
resolves the repo `deploy.py` will act on from the payload's `cwd` plus every `cd` / `pushd` that
precedes the match in the command, and a `--repo` argument; it climbs to the nearest
`site/site.json` and treats the repo as site-studio's when that file mentions `site-studio` in any
JSON spelling (the strict check belongs to siteconfig.py, which parses it). A `deploy.py
--confirm` whose target is not a site-studio repo gets no decision (another project's deploy
script is not ours). A target that cannot be resolved (`cd $(...)`, `cd "$X"`) is treated as ours:
the guard asks, or denies where it denies. `CLAUDE_PROJECT_DIR` is NEVER read here.
Label: that variable is exported to plugin hook commands (DOCUMENTED, hooks reference: "both
export them as the environment variables `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, and
`CLAUDE_PLUGIN_DATA` on the spawned process"), but it is "the project root where the session
started": it names the launch directory, not the repo a `cd` in the command reaches, which is why
nothing here keys on it. (Today's SessionStart prefix still uses it, correctly: that hook belongs
to the session's own project.)

WHAT MATCHES. A subcommand (split on `&&`, `||`, `;`, `|`, `&`, parentheses and unquoted
newlines, with shlex) matches when it has a token whose basename is `deploy.py` (any case) and a
token `--confirm`, `--confirm=<x>`, or any abbreviation of it from `--co` up. (deploy.py itself is
built with allow_abbrev=False, so an abbreviation is refused there; matching it here is the
conservative direction.) A token holding whitespace and `deploy.py`, as in `sh -c '...'`, is
scanned recursively. `--dry-run` and everything else: no decision. RESIDUAL, stated plainly:
`python3 -m deploy`, `python3 -c 'import deploy'`, a copy under another name, `bash run.sh`, a
`$VAR` holding the name, or a hand `git push` are not matched; no mechanism here contains a model
set on routing around a hook, and none is claimed.

N COMES FROM A RECORD, NOT FROM THE GUARD (M5(c)). This script never builds. `deploy.py --dry-run`
writes `.site-studio/review/dryrun.json` ({digest, files, ...}); the guard reads it and requires
its digest to equal the digest in the command. No record, or a record for another digest, is a
`deny`: "run deploy.py --dry-run first". The record is a file the model could write; the person's
click is the control, as design 7.2 says.

FAIL CLOSED (M1). Claude Code treats a hook crash, a timeout, bad output or any exit other than 2
as a NON-blocking error: the action goes ahead. So: (1) every exception in `main` (an unbalanced
quote, an unreadable or corrupt site.json, a corrupt reviews.jsonl line, a payload that is not
JSON) emits `deny` with the reason and exits 2; (2) an internal SIGALRM budget (10 s, between 1 and
30 s through SITE_STUDIO_GUARD_TIMEOUT) turns a hang into the same deny; (3) hooks.json sets
`"onFailure": "block"` on the PreToolUse entry, which makes a platform-side failure or timeout do
what exit 2 does. `onFailure` needs Claude Code v2.1.295 or later (DOCUMENTED, hooks reference).
On an older Claude Code the field is not understood and the first two layers still hold; the
third is UNDETERMINED there.

DECISION LOG (M7). When SITE_STUDIO_GUARD_LOG is set (any non-empty value) AND CLAUDE_PLUGIN_DATA
is set, one line is appended to `$CLAUDE_PLUGIN_DATA/guard-decisions.log`:
`<UTC time> mode=<m> decision=<ask|deny|none|deny-error> matched=<confirm|none|unresolved|error>`.
Used only for the P-7 and P-9 probes: it lets the owner show "fired, mode X, ask" next to "the
prompt appeared / did not". It never records a digest, a path or a message, and a failure to write
it never changes the decision.
"""
import json
import os
import shlex
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

REMOTE_POLICY = ("site-studio 0.1.0 publishes only from a session on your own computer. "
                 "Open this repo there and type /site-studio:publish.")
ASK_MODES = ("default", "acceptEdits", "plan", "auto")
NOT_ASKED_MODES = ("bypassPermissions", "dontAsk")
DENY_NO_ASK = ("Publishing asks you every time, and this session is set not to ask. "
               "Switch the permission mode and run /site-studio:publish.")
SEPARATORS = ("&&", "||", ";", "|", "&", "(", ")", ";;", "|&")
LOG_NAME = "guard-decisions.log"
MAX_DEPTH = 4


# ---------------------------------------------------------------- tokenising

def _newlines_to_semicolons(cmd):
    """Replace every UNQUOTED newline with ';' so shlex sees a separator."""
    out = []
    quote = None
    esc = False
    for ch in cmd:
        if esc:
            esc = False
            out.append(ch)
            continue
        if ch == "\\" and quote != "'":
            esc = True
            out.append(ch)
            continue
        if quote:
            if ch == quote:
                quote = None
            out.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        out.append(";" if ch == "\n" else ch)
    return "".join(out)


def split_subcommands(cmd):
    """The command as a list of token lists. ValueError on an unbalanced quote: the caller lets
    it propagate, which fails closed."""
    lex = shlex.shlex(_newlines_to_semicolons(cmd), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    subs, cur = [], []
    for tok in lex:
        if tok in SEPARATORS or (tok and set(tok) <= set("();&|")):
            if cur:
                subs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        subs.append(cur)
    return subs


def _is_deploy_token(tok):
    return os.path.basename(tok).lower() == "deploy.py"


def _is_confirm_token(tok):
    return tok == "--confirm" or tok.startswith("--confirm=") or (
        len(tok) >= 4 and tok.startswith("--co") and "--confirm".startswith(tok))


def _has_confirm(tokens):
    return any(_is_confirm_token(t) for t in tokens)


def _mentions_deploy(text):
    return "deploy.py" in text.lower()


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
    """Every deploy.py-with-confirm subcommand in `cmd`, as (cwd at that point, tokens). `cwd` is
    None when unresolvable. Recurses into quoted strings that hold `deploy.py` (sh -c '...')."""
    found = []
    for tokens in split_subcommands(cmd):
        head = os.path.basename(tokens[0]) if tokens else ""
        if head in ("cd", "pushd"):
            cwd = _cd_target(tokens, cwd)
            continue
        if any(_is_deploy_token(t) for t in tokens) and _has_confirm(tokens):
            found.append((cwd, tokens))
            continue
        if depth < MAX_DEPTH:
            for t in tokens:
                if (" " in t or "\n" in t or ";" in t or "&" in t) and _mentions_deploy(t):
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


# ---------------------------------------------------------------- the target repo

def _arg_value(tokens, name):
    for i, t in enumerate(tokens):
        if t == name and i + 1 < len(tokens):
            return tokens[i + 1]
        if t.startswith(name + "="):
            return t[len(name) + 1:]
    return None


def find_site_json(start):
    """The nearest `site/site.json` at or above `start`, or None."""
    d = os.path.abspath(start)
    while True:
        cand = os.path.join(d, "site", "site.json")
        if os.path.isfile(cand):
            return d, cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def resolve_target(cwd, tokens):
    """(repo dir or None, status) with status 'repo', 'unresolved' or 'other'. 'other' means the
    resolved directory is not a site-studio repo."""
    base = cwd
    repo_arg = _arg_value(tokens, "--repo")
    if repo_arg is not None:
        repo_arg = os.path.expandvars(os.path.expanduser(repo_arg))
        if "$" in repo_arg or "`" in repo_arg:
            return None, "unresolved"
        base = repo_arg if os.path.isabs(repo_arg) else (os.path.join(cwd, repo_arg) if cwd else None)
    if base is None:
        return None, "unresolved"
    hit = find_site_json(base)
    if hit is None:
        return None, "other"
    repo, site_json = hit
    with open(site_json, "rb") as fh:          # an unreadable file raises: fail closed
        text = fh.read().decode("utf-8", "replace")
    if "site-studio" not in text:
        return None, "other"
    return repo, "repo"


# ---------------------------------------------------------------- the decision

def _digest_and_message(tokens):
    val = None
    rest = []
    for i, t in enumerate(tokens):
        if t.startswith("--confirm="):
            val, rest = t[len("--confirm="):], tokens[i + 1:]
        elif _is_confirm_token(t) and i + 1 < len(tokens):
            val, rest = tokens[i + 1], tokens[i + 2:]
        if val is not None:
            break
    msg = None
    for t in rest:
        if not t.startswith("-"):
            msg = t
            break
    return val, msg


def _is_hex64(s):
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def decide(payload, env):
    """Returns (decision, reason, matched): decision is 'ask', 'deny' or None; matched is a short
    label for the decision log. Raises on anything it cannot read (the caller fails closed)."""
    if not isinstance(payload, dict):
        raise ValueError("the hook payload is not a JSON object")
    text = command_text(payload)
    if not _mentions_deploy(text):
        return None, "", "none"
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else None
    matches = scan(text, cwd)
    if not matches:
        return None, "", "none"
    repo = None
    unresolved = False
    for mcwd, tokens in matches:
        r, status = resolve_target(mcwd, tokens)
        if status == "repo":
            repo, chosen = r, tokens
            break
        if status == "unresolved":
            unresolved, chosen = True, tokens
    else:
        if not unresolved:
            return None, "", "none"
    matched = "confirm" if repo else "unresolved"

    if env.get("CLAUDE_CODE_REMOTE") == "true":
        return "deny", REMOTE_POLICY, matched
    mode = payload.get("permission_mode")
    if mode in NOT_ASKED_MODES:
        return "deny", DENY_NO_ASK, matched
    if mode not in ASK_MODES:
        shown = "no permission_mode in the hook payload" if mode is None else \
            "permission mode %r is not one the publish prompt has been verified in" % (mode,)
        return "deny", ("Publishing asks you every time, and %s. Run /site-studio:publish from a "
                        "session in default or acceptEdits mode." % shown), matched
    if repo is None:
        return "ask", ("Run deploy.py --confirm? site-studio could not tell which folder it acts on "
                       "(the command changes directory in a way it cannot follow). Check the target "
                       "before you allow this."), matched

    digest, msg = _digest_and_message(chosen)
    if not _is_hex64(digest):
        return "deny", ("deploy.py --confirm needs the full 64-character digest printed by "
                        "`deploy.py --dry-run`; run that first and pass its confirm line."), matched
    import review_record
    import siteconfig
    cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    rec = review_record.read_dryrun(repo)
    if rec is None or rec["digest"] != digest:
        return "deny", ("No dry run for this digest in %s: run `deploy.py --dry-run` first and pass "
                        "the digest it prints." % repo), matched
    status, row = review_record.verdict_for(digest, repo)
    if row is None:
        review = "Review: NONE for this digest (deploy.py will refuse)"
    else:
        ids = ", ".join(row["accepted"]) if row["accepted"] else "none"
        review = "Review: %s on %s, %d files opened, accepted %s" % (
            status.upper() if status == "blocked" else status, row["at"][:10], len(row["opened"]), ids)
    reason = "Publish %d files to %s, public forever? %s. Digest %s." % (
        rec["files"], cfg.publicRepo or "(no publicRepo set)", review, digest[:12])
    if msg:
        reason += " Message: %s" % (msg if len(msg) <= 120 else msg[:117] + "...")
    return "ask", reason, matched


# ---------------------------------------------------------------- output, log, entry point

def _emit(decision, reason):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision,
        "permissionDecisionReason": reason}}) + "\n")
    sys.stdout.flush()


def _log(env, mode, decision, matched):
    """One line to $CLAUDE_PLUGIN_DATA/guard-decisions.log when SITE_STUDIO_GUARD_LOG is set.
    Best effort: it never changes the decision."""
    try:
        if not env.get("SITE_STUDIO_GUARD_LOG") or not env.get("CLAUDE_PLUGIN_DATA"):
            return
        os.makedirs(env["CLAUDE_PLUGIN_DATA"], exist_ok=True)
        with open(os.path.join(env["CLAUDE_PLUGIN_DATA"], LOG_NAME), "a", encoding="utf-8") as fh:
            fh.write("%s mode=%s decision=%s matched=%s\n" % (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                mode if isinstance(mode, str) else "(missing)", decision or "none", matched))
    except Exception:
        pass


def _timeout_seconds(env):
    try:
        n = int(env.get("SITE_STUDIO_GUARD_TIMEOUT", "10"))
    except ValueError:
        n = 10
    return max(1, min(30, n))            # never 0: alarm(0) would switch the budget off


class GuardTimeout(BaseException):
    """Not an Exception (and not an OSError, which TimeoutError is): no `except OSError` or
    `except Exception` further down may swallow the alarm and carry on."""


def _on_alarm(signum, frame):
    raise GuardTimeout("the publish guard ran out of time")


def main(stdin=None, env=None):
    env = os.environ if env is None else env
    mode = None
    try:
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _on_alarm)
            signal.alarm(_timeout_seconds(env))
        raw = (stdin or sys.stdin).read()
        payload = json.loads(raw)
        if isinstance(payload, dict):
            mode = payload.get("permission_mode")
        decision, reason, matched = decide(payload, env)
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    except BaseException as exc:                      # fail CLOSED: see the docstring
        try:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
        except Exception:
            pass
        reason = ("The publish guard could not finish checking this command (%s: %s), so it is "
                  "blocked. Fix that and run /site-studio:publish." % (type(exc).__name__, exc))
        _emit("deny", reason)
        sys.stderr.write(reason + "\n")
        _log(env, mode, "deny-error", "error")
        return 2
    _log(env, mode, decision, matched)
    if decision:
        _emit(decision, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
