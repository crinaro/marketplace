#!/usr/bin/env python3
"""github_url.py -- the one normaliser for "which GitHub repo is this git URL?" (dev #835, design
amendment 1 section A4.2; named changes AS2 and AS5). Python 3.9, standard library only.

deploy.py's V1 (the dev repo's origin is not the public repo) and V3 (git will push to the pinned
repo) both ask this question, and a person's own git config decides what shape the answer comes in:
`git remote get-url` expands `insteadOf` and `pushInsteadOf`, so the SAME repo can arrive as

    https://github.com/owner/name.git        git\x40github.com:owner/name.git
    ssh://git\x40github.com/owner/name          https://github.com/Owner/Name

A string compare refuses the person who pushes over SSH, which works today. So this module parses.

ACCEPTED: host `github.com` (case-insensitive), in https, scp-like (`git\x40github.com:o/r`) or
`ssh://[user@]github.com/o/r` form; owner and name compare case-insensitively; `.git` and a trailing
slash are optional. REFUSED, never guessed at: any other host (an SSH host alias such as
`github-work:o/r` is named as one, because it cannot be resolved to a repo without ssh's own
config), `http://`, a port, a path that is not exactly owner/name, and anything that is not a URL (a
local path). The refusal is a GithubUrlError whose message names what was found; V1 and V3 add the
fix.

Nothing here reads the network, git config or the environment.
"""
import re

GITHUB_HOST = "github.com"

_SCP = re.compile(r"^(?:(?P<user>[^@/:\s]+)@)?(?P<host>[^@:/\s]+):(?P<path>[^/].*)$")
_URL = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?:(?P<user>[^@/]*)@)?(?P<host>[^/:?#]*)"
                  r"(?::(?P<port>[^/]*))?(?P<path>/.*)?$")


class GithubUrlError(ValueError):
    """The URL is not a github.com owner/name URL. `.host` is the host found, when there was one:
    the caller names it as a probable SSH host alias."""

    def __init__(self, message, host=None):
        ValueError.__init__(self, message)
        self.host = host


def redact(url):
    """The URL with any userinfo removed, for printing (a token in an https URL must not be echoed)."""
    return re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@]*@", r"\1", url or "")


def _owner_name(path, shown):
    p = path.strip("/")
    if p.lower().endswith(".git"):
        p = p[:-4]
    parts = p.split("/")
    if len(parts) != 2 or not all(parts) or any(re.search(r"[\s]", s) for s in parts):
        raise GithubUrlError("%s does not name one repository (expected github.com/<owner>/<name>)" % shown,
                             GITHUB_HOST)
    return parts[0], parts[1]


def parse(url):
    """(owner, name) of a github.com repo URL, original case; GithubUrlError otherwise."""
    text = (url or "").strip()
    shown = "'%s'" % redact(text)
    if not text:
        raise GithubUrlError("the URL is empty")
    m = _URL.match(text)
    if m:
        scheme, host = m.group("scheme").lower(), m.group("host").lower()
        if scheme not in ("https", "ssh"):
            raise GithubUrlError("%s uses %s://, and only https and ssh github.com URLs are accepted"
                                 % (shown, scheme), host or None)
        if host != GITHUB_HOST:
            raise GithubUrlError("%s has host '%s', not github.com%s"
                                 % (shown, host, " (an SSH host alias?)" if scheme == "ssh" else ""),
                                 host or None)
        if m.group("port"):
            raise GithubUrlError("%s carries a port, which is not a plain github.com URL" % shown, host)
        return _owner_name(m.group("path") or "", shown)
    m = _SCP.match(text)
    if m and "\\" not in text:
        host = m.group("host").lower()
        if host != GITHUB_HOST:
            raise GithubUrlError("%s has host '%s', not github.com (an SSH host alias?)" % (shown, host), host)
        return _owner_name(m.group("path"), shown)
    raise GithubUrlError("%s is not a github.com URL (a local path or an unknown form)" % shown)


def slug(url):
    """'owner/name' in the URL's own case."""
    return "%s/%s" % parse(url)


def same_repo(a, b):
    """True when both URLs name the same github.com repo, owner and name compared case-insensitively.
    Raises GithubUrlError when either is not a github.com repo URL."""
    return slug(a).lower() == slug(b).lower()


def slug_equals(url, owner_name):
    """True when `url` names the repo `owner_name` ('owner/name'), case-insensitively."""
    return slug(url).lower() == (owner_name or "").strip().lower()
