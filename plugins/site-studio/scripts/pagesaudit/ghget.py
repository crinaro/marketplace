"""ghget.py -- the one place the Pages check starts a process: `_get`, one `gh api` GET (dev #835, AM10).

READ-ONLY BY CONSTRUCTION (AM10). The package starts a process in exactly ONE place, `_get`, which runs
`gh api --method GET -H "Accept: application/vnd.github+json" (--paginate | the headers flag) <path>` with
GH_PROMPT_DISABLED=1 and a 15 s timeout per call. `_refuse_writes` raises on any argv carrying `-X`,
`--method` with a value other than GET, `-f`, `-F`, `--field`, `--raw-field` or `--input` (`gh api` with
fields switches to POST on its own). tests/pagesaudit/test_ghget.py proves it three ways: an AST test that
the package and its entry point have one subprocess call site and it is inside `_get`; every argv a fake `gh` recorded across
every fixture is a GET; and `_refuse_writes` refuses each write form. TIME: up to ~15 calls, each
bounded by 15 s, plus at most two 5 s sleeps for the DNS-health retry; the whole report is therefore
bounded by about 4 minutes in the worst case and a few seconds normally. It is interactive, and it is
NEVER run from a hook (S7: no `gh` in SessionStart).

READS, in order (each a GET): repos/{o}/{r}; .../pages; .../pages/health (only when a custom domain is
set; 202 means GitHub is still checking, retried twice 5 s apart through the `sleep` seam);
.../rules/branches/main; .../rulesets?includes_parents=false&targets=branch and .../rulesets/{id};
.../branches/main/protection (only when permissions.admin); the writers: .../collaborators, .../teams
(organisation repos), .../keys, and `user` (organisation repos, to leave the person out).

"""

import json
import os
import re
import subprocess
from pagesaudit.values import GhError, Resp


GET_TIMEOUT = 15


WRITE_FLAGS = ("-X", "-f", "-F", "--field", "--raw-field", "--input")
_PATH_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_./~:{}%=&?,+-]*\Z")
_HTTP_RE = re.compile(r"HTTP[/ ]\S*\s+(\d{3})")
_ERR_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")


def build_argv(path, paginate=False):
    if not isinstance(path, str) or not _PATH_RE.match(path):
        raise ValueError("refusing an api path that is not a plain path: %r" % (path,))
    argv = ["gh", "api", "--method", "GET", "-H", "Accept: application/vnd.github+json",
            "--paginate" if paginate else "--include", path]  # retired-terms: ok (a GitHub / gh key, not the gmail-multi registry)
    _refuse_writes(argv)
    return argv


def _refuse_writes(argv):
    """Raise ValueError on any argument list that could send a write (AM10)."""
    toks = list(argv)
    for i, t in enumerate(toks):
        if not isinstance(t, str) or not t.startswith("-"):
            continue
        if t == "--method" or t.startswith("--method="):
            val = t.split("=", 1)[1] if "=" in t else (toks[i + 1] if i + 1 < len(toks) else "")
            if val.upper() != "GET":
                raise ValueError("pages_check is read-only: refusing --method %s" % val)
        elif t.startswith("-X") or t.startswith("-f") or t.startswith("-F") or t in WRITE_FLAGS \
                or t.startswith("--field") or t.startswith("--raw-field") or t.startswith("--input"):
            raise ValueError("pages_check is read-only: refusing %s" % t)


def _parse_docs(text):
    """Concatenated JSON documents (what `gh api --paginate` prints); lists are joined."""
    dec, i, out = json.JSONDecoder(), 0, []
    text = text.strip()
    while i < len(text):
        obj, j = dec.raw_decode(text, i)
        out.append(obj)
        while j < len(text) and text[j].isspace():
            j += 1
        i = j
    if not out:
        return None
    if all(isinstance(o, list) for o in out):
        return [x for o in out for x in o]
    return out[0] if len(out) == 1 else out


def _get(path, paginate=False):
    """The ONLY place this module starts a process. Returns Resp(status, data, message); raises GhError
    when `gh` is missing, logged out, times out, or says something this module cannot read."""
    argv = build_argv(path, paginate)
    env = dict(os.environ)
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        p = subprocess.run(argv, env=env, timeout=GET_TIMEOUT, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise GhError("gh is not installed; install the GitHub CLI from https://cli.github.com")
    except subprocess.TimeoutExpired:
        raise GhError("gh did not answer within %d s; check your connection, then run the check again" % GET_TIMEOUT)
    except OSError as e:
        raise GhError("could not run gh (%s); reinstall the GitHub CLI from https://cli.github.com, then run the check again" % e)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace").strip()
    status, body = None, out
    if not paginate:
        m = re.match(r"HTTP/\S+\s+(\d{3})", out)
        if m:
            status = int(m.group(1))
            parts = re.split(r"\r?\n\r?\n", out, maxsplit=1)
            body = parts[1] if len(parts) > 1 else ""
    try:
        data = _parse_docs(body) if body.strip() else None
    except ValueError:
        data = None
    if status is None:
        if p.returncode == 0:
            status = 200
        else:
            m = _ERR_STATUS_RE.search(err) or _HTTP_RE.search(err)
            if m:
                status = int(m.group(1))
            elif "gh auth login" in err or "not logged" in err.lower() or "authentication" in err.lower():
                raise GhError("gh is not logged in; run `gh auth login`")
            else:
                raise GhError(err.splitlines()[-1] if err else "gh exited %d" % p.returncode)
    message = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), str) else None
    if message is None and p.returncode != 0 and err:
        message = err.splitlines()[-1]
    return Resp(status, data, message)
