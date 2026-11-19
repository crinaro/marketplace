"""The ownership question for a published host (R5.4(d), decision 33; NOT ENFORCED): the person's Pages hosts, and the confirmation read from
their own terminal."""

import os
from pagesaudit import values
import shlex
import sys
import urllib.parse
from lookfiles.refusals import LookCommandError


def owned_host_command(repo, host, url=None):
    """The command the person runs in their own terminal to confirm a host: every part absolute and quoted, built
    fresh from the running install (R5N-16), never stored."""
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "look.py")
    cmd = [os.path.abspath(sys.executable), script, "derive", "--owned-host", host]
    if url:
        cmd += ["--url", url]
    return "cd %s && %s" % (shlex.quote(os.path.abspath(repo)), " ".join(shlex.quote(c) for c in cmd))


def _gh_class(message):
    low = message.lower()
    if "not installed" in low:
        return "missing"
    if "not logged in" in low:
        return "auth"
    return "network"


def pages_host_set(public_repo, env):
    """(the person's Pages hosts, the Pages address) for `publicRepo`, read with gh. Each failure is its own refusal."""
    if not public_repo:
        raise LookCommandError("site.json has no publicRepo, so there is no published site to read; run /site-studio:setup "
                               "to set it, or derive from your local build with --build <folder of built pages>")
    try:
        resp = env.get("repos/%s/pages" % public_repo)
    except values.GhError as e:
        kind = _gh_class(str(e))
        if kind == "missing":
            raise LookCommandError("the GitHub CLI (gh) is not installed, so your Pages address cannot be read; install "
                                   "it from https://cli.github.com, or derive from your local build with --build", )
        if kind == "auth":
            raise LookCommandError("gh is not logged in, so your Pages address cannot be read; run `gh auth login`, then "
                                   "run derive again")
        raise LookCommandError("GitHub could not be reached (error class: network); check your connection, then run "
                               "derive again, or derive from your local build with --build")
    if resp.status == 404:
        raise LookCommandError("GitHub Pages is not enabled for %s, so there is no published site to read; turn it on "
                               "under the repository's Settings, then Pages, or derive from your local build with "
                               "--build" % public_repo)
    if resp.status != 200 or not isinstance(resp.data, dict):
        raise LookCommandError("GitHub could not be read (error class: HTTP %s); try again later, or derive from your "
                               "local build with --build" % resp.status)
    html_url = resp.data.get("html_url") if isinstance(resp.data.get("html_url"), str) else ""
    cname = resp.data.get("cname") if isinstance(resp.data.get("cname"), str) else ""
    hosts = set()
    for u in (html_url, cname):
        h = (urllib.parse.urlsplit(u if "//" in u else "//" + u).hostname or "").lower() if u else ""
        if h:
            hosts.add(h)
    return hosts, html_url


def settle_ownership(url_host, hosts_from_pages, owned_flag, repo, url, env):
    """The owned host set after the ownership question for `url_host`, and whether the person's word was needed.
    Returns (owned set, on_word)."""
    if url_host in hosts_from_pages:
        return set(hosts_from_pages), False
    if not owned_flag:
        raise LookCommandError("deriving a look from a site you do not publish is not supported. A site you publish "
                               "from another host: confirm it in your own terminal with --owned-host %s" % url_host)
    if owned_flag.lower() != url_host:
        raise LookCommandError("--owned-host names %s, but the address is on %s; name the host the pages come from"
                               % (owned_flag, url_host))
    if not env.isatty():
        raise LookCommandError("this needs you at your own terminal to confirm that you publish %s. Run this in your own "
                               "terminal: %s" % (url_host, owned_host_command(repo, url_host, url)))
    typed = (env.ask("Type the host %s to confirm that you publish it: " % url_host) or "").strip().lower()
    if typed != url_host:
        raise LookCommandError("that is not the host; nothing was fetched. Run derive again and type %s" % url_host)
    return set(hosts_from_pages) | {url_host}, True
