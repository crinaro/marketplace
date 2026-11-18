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

HEREDOC BODIES ARE DATA, NOT COMMANDS (dev #875, 0.3.1). `shlex` has no here-document handling
(DOCUMENTED, Python docs: "short of a full parser for shells"), so a heredoc body holding an
apostrophe (a commit message: `git commit -F - <<'EOF' ... don't ... EOF`) used to raise `No
closing quotation`; the guard blocked a command that was not a publish and told the person to run
/site-studio:publish. Now `strip_heredocs` removes every body (`<<X`, `<<'X'`, `<<"X"`, `<<-X`,
from the line after the operator up to the delimiter line, POSIX 2.7.4: quoting any part of the
delimiter is removed from the word, and `<<-` strips leading tabs from body and delimiter lines)
BEFORE the text reaches the lexer, and the decision follows from what is left:
  - no token names `deploy.py` outside a body -> no decision (a body that merely MENTIONS it, as a
    commit message does, is not a publish);
  - it names `deploy.py` and cannot be lexed -> deny, fail closed, and the message says what was
    blocked and why, WITHOUT pointing at /site-studio:publish (the command may not be a publish);
  - a real `deploy.py --confirm`, with or without a heredoc, is decided exactly as before.
One body is NOT stripped: a heredoc on a line that feeds a shell (`bash <<EOF`, `sh`, `zsh`, `eval`,
`source`, `... | bash`): that body IS commands and is scanned. `<<` inside `$(( ))` / `(( ))`
arithmetic, `<<<`, and a "delimiter" that does not start with a letter, underscore or quote are not
heredocs. RESIDUAL: `python3 - <<EOF` with a publish inside the Python source is not matched, as
`python3 -c` is not (see WHAT MATCHES).

N COMES FROM A RECORD, NOT FROM THE GUARD (M5(c)). This script never builds. `deploy.py --dry-run`
writes `.site-studio/review/dryrun.json` ({digest, files, released, ...}); the guard reads it and requires
its digest to equal the digest in the command. No record, or a record for another digest, is a
`deny`: "run deploy.py --dry-run first". The record is a file the model could write; the person's
click is the control, as design 7.2 says.

THE ASK NAMES THE RELEASED ADDRESSES (template-fidelity step 1.6r, design R2-1, R2-4). The record is v2 and carries
`released`, the published addresses this publish ends on purpose (`review_record.check_dryrun` is its strict reader;
a v1 record, or one without the list, is a loud deny: run the dry run again). When the list is not empty the ask says
"and release K published addresses (<first few>, +M more)", so the person's yes is a yes to those addresses.
`deploy.py --confirm` itself refuses a list that is not the one the dry run recorded
(`review_record.released_refusal`).

`adopt.py report --file` IS A PUBLISH TOO (design 8 RP, Q1.1, Q1.10, R4 row 22). Filing blocker reports opens public
issues, so it gets the same decision as a deploy: ask in an ask mode, deny in every other mode, deny in a cloud
session. A subcommand matches when a token has the basename `adopt.py` (any case), a LATER token is `report`, and a
token after that is `--f`, `--fi`, `--fil`, `--file` or `--file=...` (abbreviation-tolerant, the conservative
direction: the `report` subparser sets allow_abbrev=False). `adopt.py report` alone prints and `--decline` records
a decision: neither matches. The rule sits in the SAME early gate as deploy.py, after `strip_heredocs`: a commit
message body that quotes `adopt.py report --file` is not a publish, a body fed to `bash` is still scanned. The
hooks.json shell prefix reaches it with a second, narrow, case-insensitive pattern (`adopt.py` followed later by
`report`); every other adopt call starts no python. The ask text cannot name a count: this script does not read the
reports record, and the adopt skill prints the reports before it asks.

`adopt.py apply` IS A PUBLISH TOO (template-fidelity step 1.9f; owner rulings 26 and 27, "one-process apply"). With no
`--dry-run`, `apply` runs the whole adoption in one process: it publishes the converted site to the public repo through
`deploy.py`, waits for Pages, archives the old builder and pushes that commit to the dev repo's main. The person's yes at
THIS command is their yes to all of it, so it is decided exactly as `deploy.py --confirm` is: ask in an ask mode, deny in
every other mode and in a cloud session. A subcommand matches when a token has the basename `adopt.py` (any case), a LATER
token is `apply` (any case: the conservative direction) and no token after it is exactly `--dry-run` (`apply --dry-run`
writes nothing and publishes nothing; the `apply` subparser sets allow_abbrev=False, so `--dry` is no way to spell it and
the guard reads it as a publish). An `apply` aimed at a folder that is not yet a site-studio repo still asks: adopt is what
makes it one. The ask names the public repo when `site/site.json` can be read as JSON and says so plainly when it cannot.
The hooks.json shell prefix reaches it with a third pattern (`adopt.py` followed later by `apply`); it also starts the guard
for `apply --dry-run`, which the guard then lets through (a shell pattern cannot tell the two apart without being fooled by
a `--dry-run` elsewhere in the payload).

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
`<UTC time> mode=<m> decision=<ask|deny|none|deny-error> matched=<confirm|report|none|unresolved|error>`.
Used only for the P-7 and P-9 probes: it lets the owner show "fired, mode X, ask" next to "the
prompt appeared / did not". It never records a digest, a path or a message, and a failure to write
it never changes the decision.
"""
import json
import os
import re
import shlex
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

REMOTE_POLICY = ("site-studio publishes only from a session on your own computer. "
                 "Open this repo there and type /site-studio:publish.")
ASK_MODES = ("default", "acceptEdits", "plan", "auto")
NOT_ASKED_MODES = ("bypassPermissions", "dontAsk")
DENY_NO_ASK = ("Publishing asks you every time, and this session is set not to ask. "
               "Switch the permission mode and run /site-studio:publish.")
REPORT_REMOTE_POLICY = ("site-studio files reports only from a session on your own computer. "
                        "Open this repo there and run adopt.py report --file.")
REPORT_DENY_NO_ASK = ("Filing a report asks you every time, and this session is set not to ask. Run adopt.py "
                      "report to print the reports, then switch the permission mode to file them.")
REPORT_ASK = ("File the pending site-studio adopt reports as public issues on the marketplace? Each carries "
              "structure and version numbers only, never your site's text, names or paths. `adopt.py report` "
              "prints exactly what would be filed.")
APPLY_REMOTE_POLICY = ("site-studio adopts a site only from a session on your own computer. "
                       "Open this repo there and run adopt.py apply.")
APPLY_DENY_NO_ASK = ("Adopting publishes your site and retires your old builder, so it asks you every time, and this session "
                     "is set not to ask. Run adopt.py apply --dry-run to see what it would do, then switch the permission "
                     "mode to run it.")
APPLY_ASK = ("Adopt this site: publish it to %s (public forever), wait for GitHub Pages to build it, then archive your old "
             "builder and push that commit to this repo's main branch? Nothing is published or pushed if a step before "
             "the push stops. If no review covers the build, parity EQUAL and the automated privacy scans stand in for one, and "
             "the run says so. `adopt.py apply --dry-run` shows what it would do.")
APPLY_ASK_NO_REPO = "the public repo named in site/site.json (it could not be read here)"
KINDS = {                     # what each match is called in the texts that name the command
    "confirm": {"name": "deploy.py", "does": "publishes", "not": "a publish", "run": "run /site-studio:publish",
                "unknown": "Run /site-studio:publish from a session in default or acceptEdits mode.",
                "who": "Publishing", "cmd": "deploy.py --confirm"},
    "report": {"name": "adopt.py report", "does": "files reports", "not": "one that files reports",
               "run": "run the command again",
               "unknown": "Run adopt.py report --file from a session in default or acceptEdits mode.",
               "who": "Filing a report", "cmd": "adopt.py report --file"},
    "apply": {"name": "adopt.py apply", "does": "adopts the site (publishes it and retires the old builder)",
              "not": "an adoption", "run": "run adopt.py apply again",
              "unknown": "Run adopt.py apply from a session in default or acceptEdits mode.",
              "who": "Adopting", "cmd": "adopt.py apply"},
}
RANK = {"report": 0, "apply": 1, "confirm": 2}      # when one command holds several, the larger publish decides
RELEASED_SHOWN = 3            # released addresses the ask names before "+N more"
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


class CommandParseError(ValueError):
    """The command names deploy.py and could not be lexed (an unbalanced quote). A ValueError, so
    the caller's fail-closed handling still applies; a class of its own so the message can say the
    command may not be a publish."""


_SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "ash", "eval", "source", ".")
_DELIM_END = set(" \t\n;&|<>()")


def _heredoc_delimiter(cmd, j):
    """(delimiter word after quote removal, index after the raw word) from `cmd[j:]`, or None when
    what follows `<<` is not a delimiter this scanner trusts (it must start with a letter,
    underscore, quote or backslash: `1 << 2` is arithmetic, not a heredoc)."""
    n = len(cmd)
    if j >= n or not (cmd[j].isalpha() or cmd[j] in "_'\"\\"):
        return None
    word = []
    while j < n and cmd[j] not in _DELIM_END:
        ch = cmd[j]
        if ch in "'\"":
            k = cmd.find(ch, j + 1)
            if k < 0:
                return None
            word.append(cmd[j + 1:k])
            j = k + 1
        elif ch == "\\" and j + 1 < n:
            word.append(cmd[j + 1])
            j += 2
        else:
            word.append(ch)
            j += 1
    return "".join(word), j


def _line_feeds_a_shell(out, cmd, i):
    """True when the physical line that holds the heredoc operator at cmd[i] runs a shell on its
    input (`bash <<EOF`, `cat <<EOF | sh`): that body is commands, not data."""
    start = "".join(out).rsplit("\n", 1)[-1]
    end = cmd.find("\n", i)
    line = start + cmd[i:(len(cmd) if end < 0 else end)]
    for seg in re.split(r"[;&|()]", line):
        for w in seg.split():
            if "=" in w and not w.startswith(("-", "=")):
                continue                    # a VAR=value prefix
            if os.path.basename(w) in _SHELLS:
                return True
            break
    return False


def strip_heredocs(cmd):
    """`cmd` with every heredoc body (and its delimiter line) removed; see HEREDOC BODIES. Quote
    aware: an operator inside quotes is text. Never raises."""
    out, pending = [], []
    i, n = 0, len(cmd)
    quote, arith = None, 0
    while i < n:
        ch = cmd[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                out.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(cmd[i:i + 2])
            i += 2
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if arith:
            arith += (ch == "(") - (ch == ")")
            out.append(ch)
            i += 1
            continue
        if cmd.startswith("$((", i) or cmd.startswith("((", i):
            k = 3 if cmd[i] == "$" else 2
            out.append(cmd[i:i + k])
            arith = 2
            i += k
            continue
        if ch == "\n":
            out.append(ch)
            i += 1
            for delim, tabs in pending:
                while i < n:
                    end = cmd.find("\n", i)
                    line = cmd[i:(n if end < 0 else end)]
                    i = n if end < 0 else end + 1
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
            pending = []
            continue
        if cmd.startswith("<<<", i):
            out.append("<<<")
            i += 3
            continue
        if cmd.startswith("<<", i):
            j = i + 2
            tabs = j < n and cmd[j] == "-"
            if tabs:
                j += 1
            while j < n and cmd[j] in " \t":
                j += 1
            parsed = _heredoc_delimiter(cmd, j)
            if parsed is None:
                out.append("<<")
                i += 2
                continue
            delim, j2 = parsed
            if not _line_feeds_a_shell(out, cmd, i):
                pending.append((delim, tabs))
            out.append(cmd[i:j2])
            i = j2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_subcommands(cmd):
    """The command as a list of token lists, heredoc bodies removed first. CommandParseError (a
    ValueError) on an unbalanced quote: the caller lets it propagate, which fails closed."""
    lex = shlex.shlex(_newlines_to_semicolons(strip_heredocs(cmd)), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    subs, cur = [], []
    try:
        for tok in lex:
            if tok in SEPARATORS or (tok and set(tok) <= set("();&|")):
                if cur:
                    subs.append(cur)
                cur = []
            else:
                cur.append(tok)
    except ValueError as exc:
        raise CommandParseError(str(exc))
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
            found.append(("report", cwd, tokens))
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


def _names(seen):
    """The commands the early gate found in `seen` (heredoc bodies already removed): kinds in KINDS."""
    return [k for k, hit in (("confirm", _mentions_deploy(seen)), ("report", _mentions_report(seen)),
                             ("apply", _mentions_apply(seen))) if hit]


def _said(kinds, field):
    return " and ".join(KINDS[k][field] for k in kinds)


def _refusal_by_mode(payload, env, kind):
    """(decision, reason) when the environment or the permission mode forbids asking, else None."""
    if env.get("CLAUDE_CODE_REMOTE") == "true":
        return "deny", {"confirm": REMOTE_POLICY, "report": REPORT_REMOTE_POLICY, "apply": APPLY_REMOTE_POLICY}[kind]
    mode = payload.get("permission_mode")
    if mode in NOT_ASKED_MODES:
        return "deny", {"confirm": DENY_NO_ASK, "report": REPORT_DENY_NO_ASK, "apply": APPLY_DENY_NO_ASK}[kind]
    if mode not in ASK_MODES:
        shown = "no permission_mode in the hook payload" if mode is None else \
            "permission mode %r is not one the publish prompt has been verified in" % (mode,)
        return "deny", "%s asks you every time, and %s. %s" % (KINDS[kind]["who"], shown, KINDS[kind]["unknown"])
    return None


def _apply_target(cwd, tokens):
    """The folder an `adopt.py apply` acts on when it is not (yet) a site-studio repo: `--repo` or the cwd, climbed to the nearest
    `site/site.json`, else the folder itself. Only used to name the public repo in the ask."""
    base = _arg_value(tokens, "--repo")
    if base is not None:
        base = os.path.expandvars(os.path.expanduser(base))
        base = base if os.path.isabs(base) else os.path.join(cwd or "", base)
    else:
        base = cwd or ""
    hit = find_site_json(base) if base else None
    return hit[0] if hit else base


def _public_repo_of(repo):
    """`publicRepo` from site/site.json read as plain JSON, or None: a folder adopt has not converted may hold a file this
    plugin's parser refuses, and the ask must still be made."""
    try:
        with open(os.path.join(repo, "site", "site.json"), "rb") as fh:
            value = json.loads(fh.read().decode("utf-8", "replace")).get("publicRepo")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", value) else None


def released_clause(rec):
    """The ask's words for the addresses the dry run recorded as released ('' when none): the count and the first
    few paths, so the person's yes is a yes to them (R2-1)."""
    paths = [p if len(p) <= 60 else p[:57] + "..." for p, _r in rec["released"]]
    if not paths:
        return ""
    more = ", +%d more" % (len(paths) - RELEASED_SHOWN) if len(paths) > RELEASED_SHOWN else ""
    return " and release %d published address%s (%s%s)" % (
        len(paths), "" if len(paths) == 1 else "es", ", ".join(paths[:RELEASED_SHOWN]), more)


def decide(payload, env, ctx=None):
    """Returns (decision, reason, matched): decision is 'ask', 'deny' or None; matched is a short
    label for the decision log. Raises on anything it cannot read (the caller fails closed). `ctx`,
    when given, says what the caller's error message needs: `names` (the commands the early gate
    found, so a command that could not be lexed is named), and once a command has matched, `publish`
    = True and `fix` (what to run after fixing the fault), so a blocked publish and a blocked command
    that only names deploy.py are told apart."""
    if not isinstance(payload, dict):
        raise ValueError("the hook payload is not a JSON object")
    text = command_text(payload)
    kinds = _names(strip_heredocs(text))        # a body that only mentions a command is not a publish
    if not kinds:
        return None, "", "none"
    if ctx is not None:
        ctx["names"] = kinds
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else None
    matches = scan(text, cwd)
    if not matches:
        return None, "", "none"
    if ctx is not None:
        ctx["publish"], ctx["fix"] = True, KINDS[matches[0][0]]["run"]
    repo, unresolved, chosen, kind = None, False, None, None
    for mkind, mcwd, tokens in matches:
        r, status = resolve_target(mcwd, tokens)
        if mkind == "apply" and status == "other":
            r, status = _apply_target(mcwd, tokens), "repo"     # adopt makes a folder a site-studio repo: it still asks
        if status == "repo" and (repo is None or RANK[mkind] > RANK[kind]):
            repo, chosen, kind = r, tokens, mkind      # a deploy confirm outranks an apply, an apply a report
        elif status == "unresolved" and not unresolved:
            unresolved, ukind = True, mkind
    if repo is None and not unresolved:
        return None, "", "none"
    if repo is None:
        kind = ukind
    if ctx is not None:
        ctx["publish"], ctx["fix"] = True, KINDS[kind]["run"]
    matched = kind if repo else "unresolved"

    denied = _refusal_by_mode(payload, env, kind)
    if denied:
        return denied[0], denied[1], matched
    if repo is None:
        return "ask", ("Run %s? site-studio could not tell which folder it acts on (the command changes "
                       "directory in a way it cannot follow). Check the target before you allow this."
                       % KINDS[kind]["cmd"]), matched
    if kind == "report":
        return "ask", REPORT_ASK, matched
    if kind == "apply":
        reason = APPLY_ASK % (_public_repo_of(repo) or APPLY_ASK_NO_REPO)
        if any(m[0] == "report" for m in matches):
            reason += " The same command also files site-studio adopt reports."
        return "ask", reason, matched

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
    review = ("Review: NONE for this digest (deploy.py will refuse)" if row is None else          # a stand-in row says so (reviews.rows)
              "Review: " + review_record.review_rows.describe(status.upper() if status == "blocked" else status, row))
    reason = "Publish %d files to %s%s, public forever? %s. Digest %s." % (
        rec["files"], cfg.publicRepo or "(no publicRepo set)", released_clause(rec), review, digest[:12])
    if msg:
        reason += " Message: %s" % (msg if len(msg) <= 120 else msg[:117] + "...")
    if any(m[0] == "report" for m in matches):
        reason += " The same command also files site-studio adopt reports."
    if any(m[0] == "apply" for m in matches):
        reason += " The same command also runs adopt.py apply, which publishes and retires the old builder."
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
    ctx = {}
    try:
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _on_alarm)
            signal.alarm(_timeout_seconds(env))
        raw = (stdin or sys.stdin).read()
        payload = json.loads(raw)
        if isinstance(payload, dict):
            mode = payload.get("permission_mode")
        decision, reason, matched = decide(payload, env, ctx)
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    except BaseException as exc:                      # fail CLOSED: see the docstring
        try:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
        except Exception:
            pass
        if isinstance(exc, CommandParseError):
            kinds = ctx.get("names") or ["confirm"]
            tail = ("It names %s, so it is blocked in case it %s. If it is not %s, take the name %s out of "
                    "the command line (long text belongs in a file or a heredoc body) and run it again."
                    % (_said(kinds, "name"), " or ".join(KINDS[k]["does"] for k in kinds),
                       KINDS[kinds[0]]["not"] if len(kinds) == 1 else "either", _said(kinds, "name")))
        elif ctx.get("publish"):
            tail = "Fix that and %s." % ctx["fix"]
        else:
            tail = "Fix that and run the command again."
        reason = ("The publish guard could not finish checking this command (%s: %s), so it is "
                  "blocked. %s" % (type(exc).__name__, exc, tail))
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
