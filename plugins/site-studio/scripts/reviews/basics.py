"""reviews.basics -- what every part of the privacy-review record shares: `ReviewError` (a refusal, one line the person can act on), the
64-hex digest pattern, and `git`, the one way the record runs git (stdout text; a failure or a timeout raises `ReviewError`).
"""
import os
import re
import subprocess


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ReviewError(ValueError):
    """A refusal. The message is one line the person can act on."""


_REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE")


def git(repo, *args, **kw):
    """Run git in `repo`; return stdout text. Raises ReviewError (one line) on failure."""
    inp = kw.pop("input", None)
    timeout = kw.pop("timeout", 120)
    check = kw.pop("check", True)
    env = {k: v for k, v in os.environ.items() if k not in _REDIRECTING}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = subprocess.run(("git", "-C", repo) + tuple(args), input=inp, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise ReviewError("git %s timed out after %ds; check that git works in this repo, then record the review again" % (args[0], timeout))
    except OSError as e:
        raise ReviewError("could not run git (%s); install git, or check that `git --version` works in a terminal, then record the review again" % e)
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ReviewError("git %s failed: %s; fix what git reports, then record the review again" % (args[0], msg[-1] if msg else "exit %d" % p.returncode))
    out = p.stdout
    return out if kw.get("raw") else out.decode("utf-8", "replace")
