#!/usr/bin/env python3
"""Which web hosts is a board's terms-of-use line drawn around? (dev #765; design-portfolio-boards.md B1)

A `manual-candidate` channel is a site whose terms forbid automated access (ADR-037): the CANDIDATE opens
it, and the engine never visits it. That promise has a gap this module closes. A role the candidate
recorded from such a board, or that arrived in a board's alert email, can carry a URL on the board's own
host (some portfolio boards link a job to an on-board page rather than the employer's own site). The daily
run's triage step then reads each new role's JD by fetch or by the browser, and on a scheduled run nobody
is there to notice that it just opened the very page the terms forbid. So the host has to be a FACT on the
channel, not a sentence in `scope_notes`:

    channels[].board_hosts   a non-empty list of bare host names ("jobs.example.org"), legal only on a
                             channel whose `access` is `manual-candidate`. A URL on a listed host, or on
                             any sub-domain of one, is "on that board".

Three callers share the one definition below and none restates it:

    record.py board-sighting   refuses a `--url` on a board host and names what it needs instead: the
                               posting's OWN outbound URL (the employer's career site or ATS);
    your_move.py --triage-queue marks each role's read: the first URL that is NOT on a board host, or
                               "blocked" with the host named, so the run records
                               `unavailable: manual-board` instead of fetching;
    record.py (the write gate) refuses to record a JD as READ when every URL the role carries is on a
                               board host.

Pure: it reads only what it is handed, imports nothing that can reach a network, and writes nothing.

Python 3.9+. Standard library only.
"""

import re
from urllib.parse import urlsplit

HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
MANUAL_ACCESS = "manual-candidate"


def host_of(url):
    """The lower-cased host of an http(s) URL, or None for anything else (no scheme, no host, a
    `mailto:`, a bare path). A trailing dot is dropped."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    return host.lower().rstrip(".") or None


def valid_host(host):
    """True for a bare host name this module can match: lower-case labels, at least one dot, no scheme,
    path, port or whitespace. `validate_data.check_portfolio_links` refuses anything else."""
    return isinstance(host, str) and bool(HOST_RE.match(host))


def host_matches(host, board_host):
    """`host` is `board_host` or a sub-domain of it."""
    return bool(host) and bool(board_host) and (host == board_host or host.endswith("." + board_host))


def blocked_channel(url, channels):
    """The first `manual-candidate` channel whose `board_hosts` cover `url`'s host, else None. A retired
    channel still counts: retiring a source does not change the site's terms."""
    host = host_of(url)
    if host is None:
        return None
    for ch in channels or []:
        if not isinstance(ch, dict) or ch.get("access") != MANUAL_ACCESS:
            continue
        hosts = ch.get("board_hosts")
        if isinstance(hosts, list) and any(host_matches(host, h) for h in hosts if isinstance(h, str)):
            return ch
    return None


def read_urls(opp):
    """Every URL a JD read could use for this role, in the order the triage step tries them: the
    role's `jd_url`, then each sighting's `source_url` that is not a split-away listing. De-duplicated,
    empty values dropped."""
    out = []
    for u in [opp.get("jd_url")] + [s.get("source_url") for s in (opp.get("sightings") or [])
                                    if isinstance(s, dict) and not s.get("split_to")]:
        if isinstance(u, str) and u.strip() and u.strip() not in out:
            out.append(u.strip())
    return out


def jd_read_plan(opp, channels):
    """What the triage step may do to read this role's JD (the one definition; `your_move.py` prints
    it and `record.py`'s write gate reads it):

        {"url": <the first URL not on a board host, or None>,
         "blocked": [{"url", "host", "channel_id"}, ...]}      # every URL that IS on a board host

    `url` None with `blocked` non-empty means the ONLY readable address is a board the engine never
    opens: record `unavailable: manual-board`. `url` None with `blocked` empty is the old `no-url`."""
    url, blocked = None, []
    for u in read_urls(opp):
        ch = blocked_channel(u, channels)
        if ch is not None:
            blocked.append({"url": u, "host": host_of(u), "channel_id": ch.get("id")})
        elif url is None:
            url = u
    return {"url": url, "blocked": blocked}
