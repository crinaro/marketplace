"""deploying.gitrun -- the one way the publish path runs git (`_git`), and the two refusals it raises.

`DeployError` is a refusal or a red result whose message is the line the person reads; `NotChecked` is a read that could
not be made (no `gh`, not logged in, a timeout), which `deploy.py --preflight` alone tells apart from a refusal.
"""
import os
import subprocess


GIT_TIMEOUT = 300


class DeployError(Exception):
    """A refusal or a red result. The message is the line the person reads."""


class NotChecked(DeployError):
    """A read that could not be made (no `gh`, not logged in, a timeout, an unreadable answer): the question was
    never answered. A DeployError to `run_dry` and `run_confirm`, which refuse on it; `--preflight` alone tells it
    apart, because there it is NOT CHECKED rather than a refusal."""


def _git(cwd, *args, **kw):
    inp = kw.get("input")
    check = kw.get("check", True)
    timeout = kw.get("timeout", GIT_TIMEOUT)
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = subprocess.run(("git", "-C", cwd) + args, input=inp, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise DeployError("git %s timed out after %ds; check that git works in this repo (no prompt waiting for a credential), then publish again" % (args[0], timeout))
    except OSError as e:
        raise DeployError("could not run git (%s); install git, or check that `git --version` works in a terminal, then publish again" % e)
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DeployError("git %s failed: %s; fix what git reports, then publish again" % (args[0], msg[-1] if msg else "exit %d" % p.returncode))
    if kw.get("full"):
        return p
    return p.stdout if kw.get("raw") else p.stdout.decode("utf-8", "replace")


def _toplevel(repo):
    return os.path.realpath(_git(repo, "rev-parse", "--show-toplevel").strip())
