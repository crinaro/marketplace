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
third is UNDETERMINED there. One case sits outside `main`: since S1b the guard's code is the
`guarding/` package, and a module of it that fails to import stops this script before `main`
runs (exit 1, no deny line). hooks.json's command turns any non-zero exit into exit 2, so the
command is still blocked (independent review of S1b, a planted import fault).

DECISION LOG (M7). When SITE_STUDIO_GUARD_LOG is set (any non-empty value) AND CLAUDE_PLUGIN_DATA
is set, one line is appended to `$CLAUDE_PLUGIN_DATA/guard-decisions.log`:
`<UTC time> mode=<m> decision=<ask|deny|none|deny-error> matched=<confirm|report|none|unresolved|error>`.
Used only for the P-7 and P-9 probes: it lets the owner show "fired, mode X, ask" next to "the
prompt appeared / did not". It never records a digest, a path or a message, and a failure to write
it never changes the decision.
"""
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from guarding import decision as decider  # noqa: E402
from guarding.decision import _said  # noqa: E402
from guarding.lexing import CommandParseError  # noqa: E402
from guarding.texts import KINDS  # noqa: E402

LOG_NAME = "guard-decisions.log"


def decide(payload, env, ctx=None):
    """`guarding.decision.decide`, with the confirm ask built here: the import is inside the entry point's dispatch on purpose, so
    only a `deploy.py --confirm` that matched pays for the review rows and the config parser (the hook has a timeout)."""
    got = decider.decide(payload, env, ctx)
    if isinstance(got, decider.ConfirmAsk):
        from guarding import confirmask
        return confirmask.ask(got)
    return got


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
