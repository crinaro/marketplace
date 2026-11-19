"""guarding.decision -- what the guard decides for one payload: the command read, the target resolved, the mode checked.

`decide` returns `(decision, reason, matched)` for every case but one: a `deploy.py --confirm` with a full digest returns a
`ConfirmAsk`, and the entry point asks `guarding.confirmask` for the words (so the review rows and the config parser are
imported only on that path).
"""

import os
from collections import namedtuple
from guarding.lexing import strip_heredocs
from guarding.matching import (
    _is_confirm_token,
    _mentions_apply,
    _mentions_deploy,
    _mentions_report,
    command_text,
    scan,
)
from guarding.targeting import _apply_target, _public_repo_of, resolve_target
from guarding.texts import (
    APPLY_ASK,
    APPLY_ASK_NO_REPO,
    APPLY_DENY_NO_ASK,
    APPLY_REMOTE_POLICY,
    ASK_MODES,
    DENY_NO_ASK,
    KINDS,
    NOT_ASKED_MODES,
    RANK,
    RELEASED_SHOWN,
    REMOTE_POLICY,
    REPORT_ASK,
    REPORT_DENY_NO_ASK,
    REPORT_REMOTE_POLICY,
)


ConfirmAsk = namedtuple("ConfirmAsk", "repo digest msg matches matched")


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
    return ConfirmAsk(repo, digest, msg, matches, matched)
