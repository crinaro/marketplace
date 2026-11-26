"""adoption.base -- the constants shared by more than one module, the three exceptions and the git helpers.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

THE INPUT DOMAIN (named change S9(b)). Adopt converts a repo built from the examples' engine
layout: `site/site.json` carrying `name`, `siteTitle` and `publicRepo`. Anything else (a Jekyll or
Eleventy repo, no `site/site.json`, a `site.json` without those keys) is refused naming
`/site-studio:setup`; a repo that already has `schema` and `engine` is refused as already
converted.
"""

import os
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLAN_REL = ".site-studio/adopt-plan.json"
PARITY_RECORD_REL = ".site-studio/adopt-parity.json"
RECORD_SCHEMA = 1
FACT_KINDS = ("context", "voice", "rule")
UNIT_DISPOSITIONS = ("person-data", "keep", "rule", "covered")       # `rule` is NOT the `rule` fact kind: it goes to CLAUDE.md; `covered` is "the plugin covers this, drop it" (plan schema 6, dev 1068)
# What the person may decide for a content/ folder that has no page.md (design 7.2): the default,
# `source`, renames it to content/_<name> (kept as source material, not built); `portfolio` adds a page.md.
FOLDER_CHOICES = ("source", "portfolio")
_REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE")


class Refused(Exception):
    """A refusal; the message is one line. Nothing was changed."""


class NeedsAnswer(Refused):
    """The person must answer a question before adopt can go on."""


class PlanError(ValueError):
    """The plan file cannot be read."""


def _env(extra=None):
    env = dict((k, v) for k, v in os.environ.items() if k not in _REDIRECTING)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


def git(repo, *args, **kw):
    """Run git in `repo`; return stdout bytes. `input` bytes, `env` extra vars, `check` (default True)."""
    check = kw.pop("check", True)
    p = subprocess.run(["git", "-C", repo] + list(args), input=kw.pop("input", None),
                       env=_env(kw.pop("env", None)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=kw.pop("timeout", 120))
    if check and p.returncode != 0:
        raise Refused("git %s failed: %s; run `git status` in the repo to see why git refuses, fix that, then run "
                      "adopt again" % (args[0], p.stderr.decode("utf-8", "replace").strip().split("\n")[0]))
    if not check:
        return p
    return p.stdout


def gitt(repo, *args, **kw):
    """Like git(), returning stripped text; with check=False a failure reads as an empty string."""
    out = git(repo, *args, **kw)
    if not isinstance(out, bytes):
        out = out.stdout if out.returncode == 0 else b""
    return out.decode("utf-8", "replace").strip()
