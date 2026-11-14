#!/usr/bin/env python3
"""sync_main.py -- keep the dev repo's `main` checkout current, and nothing else (dev #835, design
6.1, named changes S2 and S7). Python 3.9, standard library only. A port of this marketplace's own
`scripts/sync_main.py` (dev #664), adapted for the S1 desktop app, which puts every new session in
a git WORKTREE on a `claude/<name>` branch.

    sync_main.py [--hook] [--repo R]

WHERE MAIN LIVES (S2). A port that fast-forwarded the CURRENT branch would do nothing useful in a
worktree session. This finds the checkout that holds `main` the way git documents it: the FIRST
entry of `git worktree list --porcelain`, run from the session's folder (the primary checkout is
listed first, then each linked worktree). It works from the primary and from any linked worktree.
The folder searched from is `--repo`, else CLAUDE_PROJECT_DIR, else the current folder.

WHAT IT DOES. Refuses, printing ONE line and changing nothing, when that checkout is not on `main`
(or is detached), when it is DIRTY (any change, untracked included: `.claude/worktrees/` is in the
starter's .gitignore so the app's own worktrees never count), or when `main` has diverged from or is
ahead of `origin/main`. Otherwise it runs `git fetch origin main` and `git merge --ff-only
origin/main` THERE. It never resets, rebases, stashes, switches, cleans or repairs anything: a
refusal is information for the person.

AS A SESSIONSTART HOOK (`--hook`, named change S7). Nobody is at the keyboard on S2 (scheduled
runs), where a call that waits for a human stalls the session. So the hook path (a) makes no `gh`
call at all (this script never uses `gh`); (b) bounds every git call: 5 s each, the one network
call (the fetch) 10 s, with prompting for credentials switched off so a fetch fails instead of
waiting; (c) prints at most ONE line, and nothing when already current; (d) ALWAYS exits 0, since a
hook cannot block a session and a refusal here is information. Any unexpected failure is itself one
line, never a traceback. The S2 start-up path is UNVERIFIED alongside probe P-9.
"""
import argparse
import os
import subprocess
import sys

GIT_TIMEOUT = 5
FETCH_TIMEOUT = 10
BRANCH = "main"
PREFIX = "site-studio sync_main: "

_REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE")


class Refused(Exception):
    """A condition that stops the sync and is reported as ONE line. Never an error."""


def _git(cwd, *args, **kw):
    timeout = kw.get("timeout", GIT_TIMEOUT)
    env = {k: v for k, v in os.environ.items() if k not in _REDIRECTING}
    env["GIT_TERMINAL_PROMPT"] = "0"       # a fetch must fail, never wait for a credential
    env["GCM_INTERACTIVE"] = "never"
    try:
        return subprocess.run(["git", "-C", cwd] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise Refused("git %s timed out after %ds; %s left alone" % (args[0], timeout, BRANCH))
    except OSError as exc:
        raise Refused("could not run git (%s); %s left alone" % (exc, BRANCH))


def _out(cwd, *args):
    r = _git(cwd, *args)
    return r.stdout.strip() if r.returncode == 0 else None


def main_checkout(start):
    """The first entry of `git worktree list --porcelain` run from `start`."""
    r = _git(start, "worktree", "list", "--porcelain")
    if r.returncode != 0:
        raise Refused("not inside a git checkout; %s left alone" % BRANCH)
    first = r.stdout.split("\n\n", 1)[0].splitlines()
    path = None
    for line in first:
        if line.startswith("worktree "):
            path = line[len("worktree "):]
    if not path:
        raise Refused("could not read main's checkout from git worktree list; %s left alone" % BRANCH)
    if "bare" in first:
        raise Refused("the first worktree entry is a bare repository, which has no working tree; "
                      "%s left alone" % BRANCH)
    return path


def sync(start):
    """The ONE line to print, or None when already current. May raise Refused."""
    primary = main_checkout(start)
    branch = _out(primary, "symbolic-ref", "--short", "-q", "HEAD")
    if branch != BRANCH:
        raise Refused("the checkout that holds main is %s, not %s; left alone"
                      % ("on %s" % branch if branch else "on a detached HEAD", BRANCH))
    status = _git(primary, "status", "--porcelain")
    if status.returncode != 0:
        raise Refused("could not read the main checkout's status; %s left alone" % BRANCH)
    if status.stdout.strip():
        raise Refused("the checkout that holds main (%s) has uncommitted changes (%d paths); %s left alone"
                      % (primary, len(status.stdout.strip().splitlines()), BRANCH))
    fetch = _git(primary, "fetch", "--quiet", "origin", BRANCH, timeout=FETCH_TIMEOUT)
    if fetch.returncode != 0:
        raise Refused("git fetch origin %s failed; %s left alone" % (BRANCH, BRANCH))
    local = _out(primary, "rev-parse", "--verify", "-q", "refs/heads/" + BRANCH)
    remote = _out(primary, "rev-parse", "--verify", "-q", "refs/remotes/origin/" + BRANCH)
    if not local or not remote:
        raise Refused("cannot resolve %s and origin/%s; left alone" % (BRANCH, BRANCH))
    if local == remote:
        return None
    if _git(primary, "merge-base", "--is-ancestor", remote, local).returncode == 0:
        ahead = _out(primary, "rev-list", "--count", "origin/%s..%s" % (BRANCH, BRANCH)) or "some"
        raise Refused("local %s is %s commits ahead of origin/%s; left alone" % (BRANCH, ahead, BRANCH))
    if _git(primary, "merge-base", "--is-ancestor", local, remote).returncode != 0:
        raise Refused("local %s has diverged from origin/%s; left alone" % (BRANCH, BRANCH))
    merge = _git(primary, "merge", "--ff-only", "--quiet", "origin/" + BRANCH)
    if merge.returncode != 0:
        raise Refused("git merge --ff-only origin/%s refused; %s left alone" % (BRANCH, BRANCH))
    count = _out(primary, "rev-list", "--count", "%s..%s" % (local, remote)) or "?"
    return "fast-forwarded main by %s commits to %s" % (count, remote[:7])


def run(start):
    """sync(), with every outcome as one printable line (or None). Never raises."""
    try:
        line = sync(start)
    except Refused as exc:
        line = str(exc)
    except Exception as exc:       # never fail a session: report it
        line = "unexpected %s: %s; %s left alone" % (type(exc).__name__, exc, BRANCH)
    return None if line is None else PREFIX + line


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sync_main.py", allow_abbrev=False)
    ap.add_argument("--hook", action="store_true", help="SessionStart mode: silent when current")
    ap.add_argument("--repo", help="the folder to search from (default CLAUDE_PROJECT_DIR, else here)")
    args = ap.parse_args(argv)
    start = args.repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    line = run(start)
    if line:
        print(line)
    elif not args.hook:
        print(PREFIX + "main is already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
