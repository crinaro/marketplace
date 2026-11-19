"""guarding.targeting -- the repo a matched command acts on, from the command and never from the session (S1, S10, M5(b)): `--repo` or the
cwd plus every `cd`, climbed to the nearest `site/site.json` that mentions site-studio. `CLAUDE_PROJECT_DIR` is never read.
"""
import json
import os
import re


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
