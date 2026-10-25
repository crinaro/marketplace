#!/usr/bin/env python3
"""Poll the public job-board feeds of the companies the profile tracks (dev #751; design-sourcing-feeds.md).

    feed_poll.py --run <run_id> [--already-locked] [--dry-run] [--today YYYY-MM-DD]
    feed_poll.py --status                       # read-only: slugs, last outcome, ambiguities, unlinked channels

⭐ WHAT IT DOES. For each tracked company that carries `companies[].ats` (a Greenhouse, Lever or Ashby
board slug, or a Workday tenant/wdN/site -- `ats_slug.py` finds it, from the candidate's OWN URLs), it makes ONE
read-only GET of the vendor's documented public list endpoint (a Workday site: its robots.txt-advertised
sitemap, then only the NEW job pages -- see WORKDAY below), keeps the postings whose title matches a configured
`targets.titles` entry (the screen's own matcher, `profile.title_matches`), and resolves each through
the SAME per-role resolver a sweep uses (`deferred._resolve_roles`, surface `feed`): a posting already in
the pipeline appends nothing, a new one becomes a `capture-role` item carrying the company-site channel it
came from. The daily run's existing claim -> `record.py create --from-item` -> `profile.py --minimal-screen`
path captures and screens it. There is no second de-duplication and no second screen.

⭐ WORKDAY (dev #775, jobsearch 0.76.0; docs/design-workday-feed.md as amended, ADR-037's dated line). A Workday
career site is NOT a documented API: it is the sitemap the tenant's own robots.txt advertises plus the schema.org
JobPosting JSON-LD the employer embeds in each job page. It is read under five conditions: (1) tenant, wdN and
site come from a URL the candidate already has; (2) only robots.txt-allowed paths, robots.txt re-read each run and
matched by `robots_allows` (one RFC 9309 reading on Python 3.9 to 3.14, never the stdlib matcher); (3) each
sitemap document once per site per run, then only NEW job URLs (not known to the resolver's de-dup predicate, not
already `seen` in the feed cache), at most `WORKDAY_PAGES_PER_SITE` per site, 1 request/s/host, the User-Agent,
back-off on 429 or 403; (4) every failure is `not covered: <code>` per company, never zero roles; (5) the
`/wday/cxs/` JSON endpoint is NEVER requested (`_workday_get` refuses it; a test asserts it). Phase 1 reads every
company's listing before phase 2 reads any Workday job page, and phase 2 stops `WORKDAY_RESERVE_S` short of the
deadline so the bookkeeping after the network finishes inside the Bash timeout (B3). Coverage of a Workday site is
decided by the pure `workday_window_verdict`: a window under `WINDOW_FULL` is covered only as "sitemap window;
completeness assumed" (INFERRED, ruling R3). Coverage means titles in the tenant's DEFAULT locale (ruling R2).

⭐ GET ONLY. This script never POSTs. Greenhouse and Lever document an application POST; this group never
calls it (ADR-036, criterion X). The method is asserted against a real loopback server in the tests.

⭐ A FAILING FEED IS LOUD, NEVER ZERO ROLES. Only a 200 that parses into the documented list shape counts as
COVERED (a 304 is covered and unchanged). Anything else is NOT COVERED with a code from
`journal.FEED_FAILURES`: nothing is resolved, no `last_reviewed` is stamped, and `channels_due.py` lists the
page for the browser. The `feeds` event's identity (`polled = covered + not_covered`, ...) is enforced by
`journal.record_feeds`. A PAGED feed (Lever) is covered only when EVERY page returned 200 and parsed; a
failed page makes the whole feed not covered with that page's code and its earlier pages are NOT resolved
(review B6).

⭐ HOST BEFORE COMPANY (review B1). If the FIRST request to a host fails at transport level (DNS, connect,
TLS verification, a proxy refusing the CONNECT, a timeout, an unresolved rate limit), the host is marked down
for this run and NO further request goes to it: every company on it is not covered with that one code, one
gap `jobsearch:feeds:host:<host>` is filed, and those companies keep their NORMAL cadence (a machine that
cannot reach a vendor must not turn a monthly browser visit into a daily one). Per-board codes (404, not the
documented shape, redirect, odd status) keep the DUE-regardless fallback.

⭐ AN INTERNAL DEADLINE (review B3). `DEADLINE_S` bounds the whole network phase, safely below the Bash
timeout the daily run passes (`skills/daily-run/SKILL.md`: 300 s). Companies not reached by it are not
covered with `budget-exhausted`; the `feeds` event and the summary line are ALWAYS written.

⭐ THE FETCH CONTRACT (review B4). `fetch(Request) -> Response`, or raise `FetchError(code)`:

    Request   method, url, headers (a dict: exactly `User-Agent`, plus `If-None-Match` when an ETag is
              cached), timeout
    Response  status, headers (lower-cased names), body (bytes), final_url

`default_fetch` is the only code in this tree that touches the network; every other test injects a fake.
Its opener has NO cookie processor, follows a redirect only within the same origin (a cross-origin one is
`FetchError("redirected")`, not followed), keeps `urllib`'s default `ProxyHandler` (so a sandboxed request
reaches the proxy instead of failing on DNS), and sends GET only.

Politeness constants are named and asserted: `MIN_INTERVAL_S` per host, `TIMEOUT_S`, `RETRY_AFTER_CAP_S`,
`USER_AGENT`. No `Authorization`, no `Cookie`.

Exit codes: 0 every feed covered; 4 accepted with at least one NOT COVERED (the `--add-roles` precedent);
3 refused (`FEEDS NOT RUN`).

Python 3.9+. Standard library only.
"""

import argparse
import collections
import datetime
import email.utils
import functools
import gzip
import html
import html.parser
import http.client
import io
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.parsers.expat as _expat
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import ats_slug
import journal as _journal
from pipeline_index import canonical_job_url

ROOT = _profile_root()
HERE = os.path.dirname(os.path.abspath(__file__))

# ---- politeness (named, asserted by the tests) -------------------------------------------------
MIN_INTERVAL_S = 1.0        # per host (Lever's robots.txt says Crawl-delay: 1; applied to all hosts, OURS)
TIMEOUT_S = 10              # per request (OURS)
RETRY_AFTER_CAP_S = 30      # the longest Retry-After waited out, once (OURS)
DEADLINE_S = 240            # the whole network phase; the daily run's Bash timeout is 300 s (B3)
LEVER_PAGE = 100
MAX_PAGES = 50
MAX_BODY = 8 * 1024 * 1024


def _plugin_version():
    try:
        with open(os.path.join(os.path.dirname(HERE), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("version") or "0"
    except (OSError, ValueError):
        return "0"


USER_AGENT = "jobsearch-plugin/%s (+https://github.com/crinaro/marketplace)" % _plugin_version()

# vendor/region -> (host, path). Each cites the vendor's own page:
#   greenhouse  https://docs.greenhouse.io/job-board.html  (no authentication for any GET)
#   lever       https://github.com/lever/postings-api      (EU host api.eu.lever.co; skip/limit paging)
#   ashby       https://developers.ashbyhq.com/docs/public-job-posting-api
#   workday     NOT a documented API (dev #775): the host is a per-tenant TEMPLATE and no path is ever constructed
#               except `/robots.txt`; everything else is read from what robots.txt advertises and the sitemap lists.
#               Workday documents only the JSON-LD syndication to Google for Jobs (doc.workday.com, Recruiting admin
#               guide); the sitemap and robots shapes are OBSERVED. ADR-037's 2026-10-24 line records the ruling.
ENDPOINTS = {
    ("greenhouse", None): ("boards-api.greenhouse.io", "/v1/boards/%s/jobs"),
    ("lever", "global"): ("api.lever.co", "/v0/postings/%s"),
    ("lever", "eu"): ("api.eu.lever.co", "/v0/postings/%s"),
    ("ashby", None): ("api.ashbyhq.com", "/posting-api/job-board/%s"),
    ("workday", None): ("%(tenant)s.%(wd)s.myworkdayjobs.com", None),
}
FEED_HOSTS = tuple(sorted({h for (v, _r), (h, _p) in ENDPOINTS.items() if v != "workday"}))

Request = collections.namedtuple("Request", "method url headers timeout")
Response = collections.namedtuple("Response", "status headers body final_url")


class FetchError(Exception):
    """A transport-level failure: `code` is one of timeout / unreachable / tls-untrusted /
    egress-blocked / redirected (all in `journal.FEED_FAILURES`)."""

    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s %s" % (code, detail))
        self.code, self.detail = code, detail


class _CrossOrigin(Exception):
    pass


def _origin(url):
    p = urllib.parse.urlsplit(url)
    port = p.port or {"http": 80, "https": 443}.get(p.scheme)
    return (p.scheme, (p.hostname or "").lower(), port)


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only within the origin that was asked (review B4); a different host, port or
    scheme is `redirected`, not followed -- a vendor moving a board never sends the poller somewhere
    the design did not name."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != _origin(req.full_url):
            raise _CrossOrigin(newurl)
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


def build_opener():
    """The opener `default_fetch` uses: urllib's DEFAULT handlers (so `ProxyHandler` stays and a
    sandboxed request reaches the proxy) minus nothing, plus the same-origin redirect rule, and NO
    `HTTPCookieProcessor` -- `urllib` adds none by default, and none is added here."""
    return urllib.request.build_opener(_SameOriginRedirect)


def default_fetch(request):
    """The wire. See the module docstring's contract. Raises `FetchError`; never returns a Response
    for a transport failure. An HTTP error status (404, 429, ...) IS a Response."""
    req = urllib.request.Request(request.url, headers=dict(request.headers), method=request.method)
    opener = build_opener()
    try:
        resp = opener.open(req, timeout=request.timeout)
    except _CrossOrigin as e:
        raise FetchError("redirected", str(e))
    except urllib.error.HTTPError as e:
        body = e.read(MAX_BODY + 1) if e.fp is not None else b""
        return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, body, e.geturl())
    except (socket.timeout, TimeoutError) as e:
        raise FetchError("timeout", str(e))
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise FetchError("timeout", str(reason))
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise FetchError("tls-untrusted", str(reason))
        if "Tunnel connection failed" in str(reason):
            raise FetchError("egress-blocked", str(reason))
        raise FetchError("unreachable", str(reason))
    except ssl.SSLCertVerificationError as e:
        raise FetchError("tls-untrusted", str(e))
    except (OSError, http.client.HTTPException) as e:
        raise FetchError("unreachable", "%s: %s" % (type(e).__name__, e))
    try:
        body = resp.read(MAX_BODY + 1)
        status, headers, final = resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.geturl()
    except (socket.timeout, TimeoutError) as e:
        raise FetchError("timeout", str(e))
    except (OSError, http.client.HTTPException) as e:
        raise FetchError("unreachable", "%s: %s" % (type(e).__name__, e))
    finally:
        resp.close()
    return Response(status, headers, body, final)


class RealClock(object):
    def now(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


def parse_retry_after(value, now=None):
    """Seconds to wait from a `Retry-After` header (a whole number of seconds or an HTTP-date,
    RFC 9110 §10.2.3), or None when absent or unreadable. A date in the past is 0."""
    if value is None:
        return None
    v = str(value).strip()
    if re.match(r"^\d{1,9}$", v):
        return int(v)
    try:
        when = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    cur = now if now is not None else datetime.datetime.now(datetime.timezone.utc)
    return max(0, int((when - cur).total_seconds()))


# ---- parsing: the documented shape or nothing ----------------------------------------------------

class Unparseable(Exception):
    pass


def _s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _load_json(body):
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Unparseable("the body is not JSON")


# Lever's `salaryRange.interval` vocabulary is not enumerated in the docs (design U7), so only an
# interval recognised here becomes `pay=stated`; anything else is `pay=?`. OURS, widened only by a probe.
_PAY_UNITS = {"year": "yr", "yearly": "yr", "annual": "yr", "per-year-salary": "yr",
              "month": "mo", "monthly": "mo", "per-month-salary": "mo",
              "day": "day", "daily": "day",
              "hour": "hr", "hourly": "hr", "per-hour-wage": "hr"}


def _whole(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if float(v) == int(v) and v > 0 else None


def _pay_slot(lo, hi, unit_word, currency):
    """`stated:<min>-<max>/<unit>/<CUR>` or `?`: a figure is stated only when every part is read."""
    unit = _PAY_UNITS.get(str(unit_word or "").strip().lower())
    cur = currency if isinstance(currency, str) and re.match(r"^[A-Za-z]{3}$", currency) else None
    lo, hi = _whole(lo), _whole(hi)
    if not (unit and cur and lo and hi and lo <= hi):
        return "?"
    return "stated:%d-%d/%s/%s" % (lo, hi, unit, cur.upper())


def _date_slot(prefix, iso_or_ms):
    """`ats:YYYY-MM-DD` from an ISO timestamp or epoch milliseconds; `?` otherwise."""
    try:
        if isinstance(iso_or_ms, bool):
            return "?"
        if isinstance(iso_or_ms, (int, float)):
            d = datetime.datetime.fromtimestamp(iso_or_ms / 1000.0, datetime.timezone.utc).date()
        elif isinstance(iso_or_ms, str) and re.match(r"^\d{4}-\d{2}-\d{2}", iso_or_ms):
            d = datetime.date.fromisoformat(iso_or_ms[:10])
        else:
            return "?"
    except (ValueError, OverflowError, OSError):
        return "?"
    return "%s%s" % (prefix, d.isoformat())


def parse_greenhouse(body):
    """`(postings, unlisted)`. Greenhouse list: `{jobs: [{title, absolute_url, location{name}}], ...}`.
    `updated_at` is never a posted date; `first_published` and pay are single-job-only (D3), so
    `posted` and `pay` are `?`."""
    data = _load_json(body)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise Unparseable("no `jobs` list")
    out = []
    for j in data["jobs"]:
        if not isinstance(j, dict) or not _s(j.get("absolute_url")) or not _s(j.get("title")):
            raise Unparseable("a posting lacks `absolute_url` or `title`")
        loc = j.get("location")
        out.append({"url": j["absolute_url"].strip(), "title": j["title"].strip(),
                    "location": _s(loc.get("name")) if isinstance(loc, dict) else None,
                    "posted": "?", "pay": "?", "setting": "?"})
    return out, 0


def parse_lever(body):
    """`(postings, unlisted)`. Lever list: a top-level list of `{text, hostedUrl, categories{location,
    allLocations}, workplaceType, salaryRange{currency, interval, min, max}, createdAt?}`.
    `createdAt` is undocumented, so `posted` uses it only when present."""
    data = _load_json(body)
    if not isinstance(data, list):
        raise Unparseable("the body is not a list of postings")
    out = []
    for j in data:
        if not isinstance(j, dict) or not _s(j.get("hostedUrl")) or not _s(j.get("text")):
            raise Unparseable("a posting lacks `hostedUrl` or `text`")
        cats = j.get("categories") if isinstance(j.get("categories"), dict) else {}
        locs = cats.get("allLocations")
        if isinstance(locs, list) and len([x for x in locs if _s(x)]) > 1:
            location = "; ".join(x.strip() for x in locs if _s(x))
        else:
            location = _s(cats.get("location"))
        wt = _s(j.get("workplaceType"))
        sr = j.get("salaryRange") if isinstance(j.get("salaryRange"), dict) else None
        out.append({"url": j["hostedUrl"].strip(), "title": j["text"].strip(), "location": location,
                    "posted": _date_slot("ats:", j.get("createdAt")),
                    "pay": _pay_slot(sr.get("min"), sr.get("max"), sr.get("interval"),
                                     sr.get("currency")) if sr else "?",
                    "setting": ("none stated" if wt == "unspecified" else wt) if wt else "?"})
    return out, 0


def parse_ashby(body):
    """`(postings, unlisted)`. Ashby: `{jobs: [{title, jobUrl, location, secondaryLocations[],
    isListed, workplaceType, publishedAt, compensation?}]}`. `isListed: false` is counted `unlisted`
    and never captured. Compensation placement is documented inconsistently (D2), so it is read from
    the job first, then the top level, and is optional."""
    data = _load_json(body)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise Unparseable("no `jobs` list")
    out, unlisted = [], 0
    for j in data["jobs"]:
        if not isinstance(j, dict) or not _s(j.get("jobUrl")) or not _s(j.get("title")):
            raise Unparseable("a posting lacks `jobUrl` or `title`")
        if j.get("isListed") is False:
            unlisted += 1
            continue
        locs = [_s(j.get("location"))] + [
            _s(s.get("location")) for s in (j.get("secondaryLocations") or []) if isinstance(s, dict)]
        locs = [x for x in locs if x]
        pay = "?"
        comp = j.get("compensation") if isinstance(j.get("compensation"), dict) else \
            (data.get("compensation") if isinstance(data.get("compensation"), dict) else None)
        for c in ((comp or {}).get("summaryComponents") or []):
            if isinstance(c, dict) and c.get("compensationType") == "Salary":
                pay = _pay_slot(c.get("minValue"), c.get("maxValue"), c.get("interval"),
                                c.get("currencyCode"))
                break
        out.append({"url": j["jobUrl"].strip(), "title": j["title"].strip(),
                    "location": "; ".join(locs) or None,
                    "posted": _date_slot("ats:", j.get("publishedAt")), "pay": pay,
                    "setting": _s(j.get("workplaceType")) or "?"})
    return out, unlisted


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


# ---- Workday (dev #775, jobsearch 0.76.0; docs/design-workday-feed.md as amended) -------------------------------------
#
# A Workday-hosted career site is read from the robots.txt-advertised sitemap plus the employer's own
# schema.org JobPosting JSON-LD (an employer-published public feed under the five conditions of ADR-037's dated
# line). NO `/wday/cxs/` request is ever built: `_workday_get` refuses one before any I/O, a sitemap `<loc>` carrying
# one is `sitemap-malformed`, and `test_feed_poll.py` asserts no recorded request contains it.

FEED_HOST_FAMILIES = ("*.myworkdayjobs.com",)
WD_SUFFIX = ats_slug.WD_SUFFIX
# INFERRED (n=2 sitemaps, both exactly 100 entries; ruling R3). "A window under the cap lists every open job" is
# UNDETERMINED (probe U1, owner-run): until it is recorded a site under the cap is only
# "covered (sitemap window; completeness assumed)" in `--status` and the docs.
WINDOW_FULL = 100
WORKDAY_PAGES_PER_SITE = 25          # new job pages read per site per run (OURS); more -> budget-exhausted
# B3 -- the post-network reserve. Phase 2 (job pages) stops this many seconds short of `deadline_s`, so the work AFTER
# the network (the resolver writes, one `record.py` subprocess per covered stamp, `write_cache`) still finishes inside
# the daily run's 300 s Bash timeout. WALL-TIME BOUND (W Workday sites, G other feeds, one request <= TIMEOUT_S):
#   phase 1  <= G + (1 + 1) * W + children  requests, each >= MIN_INTERVAL_S apart on one host   (cheap: 2 per site)
#   phase 2  stops at DEADLINE_S - WORKDAY_RESERVE_S (+ one request in flight, <= TIMEOUT_S)
# so the tail has >= 300 - (DEADLINE_S - WORKDAY_RESERVE_S + TIMEOUT_S) = 130 s. 0.72.0's tail was 60 s.
WORKDAY_RESERVE_S = 60
ROBOTS_PARSE_LIMIT = 512000          # RFC 9309 section 2.5: a parser reads at least 500 KiB
ROBOTS_PRODUCT_TOKEN = "jobsearch-plugin"
SITEMAP_MAX_LOCS = 50000             # sitemaps.org: fewer than 50,000 URLs
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_BANNED_PATH = "/wday/cxs/"


def host_in_family(host):
    """True for exactly `<tenant>.<wdN>.myworkdayjobs.com` (two labels plus the suffix)."""
    h = str(host or "").lower()
    if not h.endswith(WD_SUFFIX):
        return False
    labels = h[:-len(WD_SUFFIX)].split(".")
    return len(labels) == 2 and bool(ats_slug.WD_TENANT_RE.match(labels[0]) and ats_slug.WD_RE.match(labels[1]))


def workday_host(ats):
    return "%s.%s%s" % (ats.get("tenant"), ats.get("wd"), WD_SUFFIX)


class WorkdayRequestRefused(RuntimeError):
    """A programming error, never a fetch: a request the ruling forbids was about to be built."""


def _workday_get(get, host, path, limit=None):
    """THE ONE builder of a Workday request (C10). It refuses, before any I/O, a host outside the family, a path that
    is not absolute, and a path containing `/wday/cxs/` (raw or percent-decoded: the JSON endpoint is banned by
    ADR-037 and robots.txt does not hold the ban, design W12). Otherwise it calls the shared `get` (the interval, the
    deadline, `USER_AGENT`, GET only, no `If-None-Match`). The scheme is always https."""
    if not host_in_family(host):
        raise WorkdayRequestRefused("host %r is outside *.myworkdayjobs.com" % (host,))
    if not isinstance(path, str) or not path.startswith("/"):
        raise WorkdayRequestRefused("path %r is not an absolute path" % (path,))
    if _BANNED_PATH in path.casefold() or _BANNED_PATH in urllib.parse.unquote(path).casefold():
        raise WorkdayRequestRefused("%s is never requested (ADR-037): %r" % (_BANNED_PATH, path))
    return get(host, "https://%s%s" % (host, path), None, limit)


# ---- robots.txt: fetched through fetch(), matched by this plugin's own RFC 9309 matcher --------------------------------
# The standard library's `urllib.robotparser` is NOT one behaviour across the supported Pythons (3.9.6 answers a
# first-match, 3.14 a longest-match, design Prior art C3), and its `read()` calls `urlopen` outside the named fetch
# contract. So robots.txt is fetched by `fetch()` and matched here, the same way on 3.9 to 3.14.

_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _norm_path(s):
    """RFC 9309 section 2.2.2 normalisation: a percent-encoded UNRESERVED ASCII octet is unencoded, every other
    escape keeps its octet (hex upper-cased), and an octet outside ASCII (or a control or space) is
    percent-encoded -- so `/a%7Eb` and `/a~b` compare equal and `/a%2Fb` does not equal `/a/b`."""
    data = str(s).encode("utf-8")
    out, i, n = [], 0, len(data)
    while i < n:
        b = data[i]
        if b == 0x25 and i + 2 < n:
            try:
                val = int(data[i + 1:i + 3], 16)
            except ValueError:
                val = None
            if val is not None:
                ch = chr(val)
                out.append(ch if ch in _UNRESERVED else "%%%02X" % val)
                i += 3
                continue
        if b >= 0x80 or b <= 0x20 or b == 0x7f:
            out.append("%%%02X" % b)
        else:
            out.append(chr(b))
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=1024)
def _robots_regex(npat):
    anchored = npat.endswith("$")
    body = npat[:-1] if anchored else npat
    rx = ".*".join(re.escape(piece) for piece in body.split("*"))
    return re.compile("^" + rx + (r"\Z" if anchored else ""), re.DOTALL)


def parse_robots(text):
    """`(groups, sitemaps)` from a robots.txt body. `groups` is `[{"agents": [lower-cased], "rules": [(allow,
    pattern)]}]`; `sitemaps` the `Sitemap:` values in file order. A rule before any `User-agent`, an empty
    `Allow:`/`Disallow:` and a pattern that starts with neither `/` nor `*` are ignored (RFC 9309 2.2.2: an empty
    `Disallow:` is no rule). Unknown fields (`Crawl-delay`) are ignored without ending a group."""
    groups, sitemaps, cur, last_agent = [], [], None, False
    for raw in re.split(r"\r\n|\r|\n", text.lstrip("﻿")):
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, _sep, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if cur is None or not last_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(value.lower())
            last_agent = True
        elif field in ("allow", "disallow"):
            last_agent = False
            if cur is not None and value and (value[0] in "/*"):
                cur["rules"].append((field == "allow", value))
        elif field == "sitemap":
            if value:
                sitemaps.append(value)
    return groups, sitemaps


def robots_rules_for(groups, token=ROBOTS_PRODUCT_TOKEN):
    """The rules that apply to `token`: every group naming it (case-insensitively, whole token), else every `*`
    group; merged. No applicable group means every path is allowed."""
    named = [g for g in groups if token.lower() in g["agents"]]
    use = named or [g for g in groups if "*" in g["agents"]]
    return [r for g in use for r in g["rules"]]


def robots_allows(rules, path):
    """RFC 9309 section 2.2.2: the matching rule with the MOST OCTETS wins; on a tie `allow` wins; no matching rule
    means allowed. `*` matches any run, a terminal `$` anchors the end. `path` includes the query. Never a stdlib
    matcher and never `RobotFileParser.read()`."""
    p = _norm_path(path)
    best = None
    for allow, pattern in rules:
        npat = _norm_path(pattern)
        if _robots_regex(npat).match(p):
            if best is None or len(npat) > best[0] or (len(npat) == best[0] and allow and not best[1]):
                best = (len(npat), allow)
    return best is None or best[1]


# ---- the sitemap: strict, bounded, same-site, safe to parse -------------------------------------------------------

class SitemapRefusal(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s %s" % (code, detail))
        self.code, self.detail = code, detail


def _looks_like_html(data):
    head = data[:64].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _require_utf8(body):
    """B6, layer 1: the body must be UTF-8 with no byte-order mark, no NUL byte (a UTF-16/32 body without a mark)
    and no XML declaration naming another encoding. Anything else is `sitemap-malformed`."""
    if (body[:3] == b"\xef\xbb\xbf" or body[:2] in (b"\xff\xfe", b"\xfe\xff")
            or body[:4] in (b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00")):
        raise SitemapRefusal("sitemap-malformed", "a byte-order mark: the body must be UTF-8 without one")
    if b"\x00" in body:
        raise SitemapRefusal("sitemap-malformed", "a NUL byte: not UTF-8")
    try:
        head = body[:256].decode("utf-8", "ignore")
        full_ok = body.decode("utf-8")
    except UnicodeDecodeError:
        raise SitemapRefusal("sitemap-malformed", "not valid UTF-8")
    del full_ok
    m = re.match(r"^\s*<\?xml[^>]*?\bencoding\s*=\s*[\"']([^\"']+)[\"']", head)
    if m and m.group(1).strip().lower().replace("_", "-") not in ("utf-8", "utf8"):
        raise SitemapRefusal("sitemap-malformed", "the XML declaration names encoding %r" % m.group(1))


def _parse_sitemap_xml(body, encoding="utf-8"):
    """B6, layer 2: `(root_kind, [loc text])` through `xml.parsers.expat` HANDLERS, which see the DECODED stream:
    any DOCTYPE, ENTITY declaration or external entity is refused (`sitemap-malformed`), whatever the encoding --
    a byte search for `<!DOCTYPE` is defeated by a UTF-16 body. Root must be `urlset` or `sitemapindex` in the
    sitemaps.org 0.9 namespace. `encoding=None` lets expat sniff the encoding (used by the test that proves the
    handlers hold even when layer 1 does not)."""
    def refuse(*_a, **_k):
        raise SitemapRefusal("sitemap-malformed", "a DOCTYPE, ENTITY or external entity")
    parser = _expat.ParserCreate(encoding, namespace_separator=" ")
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse
    parser.SkippedEntityHandler = refuse
    try:
        parser.SetParamEntityParsing(_expat.XML_PARAM_ENTITY_PARSING_NEVER)
    except AttributeError:
        pass
    state = {"root": None, "stack": [], "buf": None, "locs": []}
    ns = SITEMAP_NS + " "

    def start(name, _attrs):
        st = state["stack"]
        if not st:
            state["root"] = name
        elif name == ns + "loc" and len(st) == 2 and st[1] in (ns + "url", ns + "sitemap"):
            state["buf"] = []
        st.append(name)

    def end(name):
        st = state["stack"]
        st.pop()
        if name == ns + "loc" and state["buf"] is not None:
            state["locs"].append("".join(state["buf"]))
            state["buf"] = None
            if len(state["locs"]) >= SITEMAP_MAX_LOCS:
                raise SitemapRefusal("sitemap-malformed", "%d or more <loc> entries" % SITEMAP_MAX_LOCS)

    def chars(data):
        if state["buf"] is not None:
            state["buf"].append(data)

    parser.StartElementHandler, parser.EndElementHandler, parser.CharacterDataHandler = start, end, chars
    try:
        parser.Parse(body, True)
    except SitemapRefusal:
        raise
    except _expat.ExpatError as e:
        raise SitemapRefusal("sitemap-malformed", "not well-formed XML (%s)" % e)
    kinds = {ns + "urlset": "urlset", ns + "sitemapindex": "index"}
    if state["root"] not in kinds:
        raise SitemapRefusal("sitemap-malformed", "the root element is not urlset or sitemapindex in the 0.9 namespace")
    return kinds[state["root"]], state["locs"]


def parse_workday_sitemap(body, headers, host, site, gz=False, allow_index=True):
    """`(urls, children)` for ONE sitemap document (`urls` for a `urlset`, `children` for a `sitemapindex`), or a
    `SitemapRefusal`. Steps, in order (design 4.3 as amended by B6): (1) a block page is `blocked`; (2) a gzip body
    is decompressed in bounded chunks and `MAX_BODY` applies to the DECOMPRESSED bytes; (3) the body must be UTF-8
    (`_require_utf8`); (4) expat parses it, refusing DOCTYPE/ENTITY (`_parse_sitemap_xml`); (5) every `<loc>` must
    be https, on this host, under `/<site>/` (the case robots.txt advertised) and free of `/wday/cxs/`, one bad
    `<loc>` fails the whole sitemap; (6) zero `<loc>` is `sitemap-empty`."""
    if "challenge" in str(headers.get("cf-mitigated", "")).lower() or "text/html" in str(
            headers.get("content-type", "")).lower() or _looks_like_html(body):
        raise SitemapRefusal("blocked", "a block page, not a sitemap")
    if len(body) > MAX_BODY:
        raise SitemapRefusal("sitemap-malformed", "the body exceeds %d bytes" % MAX_BODY)
    if gz or body[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as fh:
                body = fh.read(MAX_BODY + 1)
        except (OSError, EOFError, zlib.error) as e:
            raise SitemapRefusal("sitemap-malformed", "not valid gzip (%s)" % e)
        if len(body) > MAX_BODY:
            raise SitemapRefusal("sitemap-malformed", "the decompressed body exceeds %d bytes" % MAX_BODY)
        if _looks_like_html(body):
            raise SitemapRefusal("blocked", "a block page, not a sitemap")
    _require_utf8(body)
    kind, locs = _parse_sitemap_xml(body)
    if not locs:
        raise SitemapRefusal("sitemap-empty", "zero <loc>")
    out, prefix = [], "/%s/" % site
    for loc in locs:
        if loc != loc.strip() or not loc or re.search(r"\s", loc):
            raise SitemapRefusal("sitemap-malformed", "a <loc> with whitespace: %r" % loc[:80])
        try:
            u = urllib.parse.urlsplit(loc)
            port = u.port
        except ValueError:
            raise SitemapRefusal("sitemap-malformed", "an unreadable <loc>: %r" % loc[:80])
        if (u.scheme != "https" or (u.hostname or "").lower() != host or port not in (None, 443)
                or u.fragment or not u.path.startswith(prefix)):
            raise SitemapRefusal("sitemap-malformed", "a <loc> off this site: %r" % loc[:120])
        if _BANNED_PATH in u.path.casefold() or _BANNED_PATH in urllib.parse.unquote(u.path).casefold():
            raise SitemapRefusal("sitemap-malformed", "a <loc> carrying %s" % _BANNED_PATH)
        out.append(loc)
    out = list(collections.OrderedDict.fromkeys(out))
    if kind == "index":
        if not allow_index:
            raise SitemapRefusal("sitemap-malformed", "a sitemap index inside a sitemap index")
        return [], out
    return out, []


# ---- the job page: strict JobPosting JSON-LD, mapped to the existing posting shape --------------------------------

class PageRefusal(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s %s" % (code, detail))
        self.code, self.detail = code, detail


class _LdCollector(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.scripts, self._buf = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            t = dict((k.lower(), v or "") for k, v in attrs).get("type", "")
            if t.split(";")[0].strip().lower() == "application/ld+json":
                self._buf = []

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._buf is not None:
            self.scripts.append("".join(self._buf))
            self._buf = None


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$")
_SCHEMA_CTX = re.compile(r"^https?://schema\.org/?$")


def _iso_date(v):
    """The `datetime.date` of a schema.org Date or DateTime string, else None."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not (_ISO_DATE.match(v) or _ISO_DT.match(v)):
        return None
    try:
        return datetime.date.fromisoformat(v[:10])
    except ValueError:
        return None


def _type_has(node, name):
    t = node.get("@type")
    return t == name or (isinstance(t, list) and name in t)


def _ctx_is_schema(ctx):
    if isinstance(ctx, list):
        return any(_ctx_is_schema(c) for c in ctx)
    return isinstance(ctx, str) and bool(_SCHEMA_CTX.match(ctx.strip()))


def _country_name(v):
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        return _s(v.get("name"))
    return None


def _as_list(v):
    return v if isinstance(v, list) else [v]


def _primary_language(v):
    if isinstance(v, dict):
        v = v.get("name") or v.get("alternateName")
    if isinstance(v, list):
        v = next((x for x in v if isinstance(x, str) and x.strip()), None)
    if not isinstance(v, str) or not v.strip():
        return None
    return re.split(r"[-_]", v.strip().lower())[0] or None


US_COUNTRIES = frozenset(("united states of america", "united states", "us", "usa"))


def parse_jobposting(body, loc_url, run_date):
    """The strict reading of one job page. Returns `{"posting", "expired", "in_language", "basesalary"}` or raises
    `PageRefusal(code)`. `posting` is the dict `parse_greenhouse` returns the shape of (url, title, location,
    posted, pay, setting). Exactly one JobPosting (schema.org context) is required; each required field has its
    accepted members (design 6.2) and anything else is `unparseable` by name. A past `validThrough` is `expired`
    (a readable posting that says it is closed): never captured, never a failure. `baseSalary` is NEVER read for
    pay (ruling); it is only reported."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise PageRefusal("unparseable", "the page is not UTF-8")
    coll = _LdCollector()
    try:
        coll.feed(text)
        coll.close()
    except Exception as e:                                  # noqa: BLE001 - html.parser raises on some bad markup
        raise PageRefusal("unparseable", "the page markup could not be read (%s)" % e)
    cands = []
    for raw in coll.scripts:
        try:
            doc = json.loads(raw)
        except ValueError:
            raise PageRefusal("unparseable", "an application/ld+json script is not JSON")
        for node in _as_list(doc):
            if not isinstance(node, dict):
                continue
            if "@graph" in node:
                raise PageRefusal("unparseable", "a top-level @graph (a shape not seen: refused by name)")
            if _type_has(node, "JobPosting") and _ctx_is_schema(node.get("@context")):
                cands.append(node)
    if not cands:
        raise PageRefusal("no-jsonld", "no JobPosting JSON-LD")
    if len(cands) > 1:
        raise PageRefusal("unparseable", "%d JobPosting objects (exactly one is required)" % len(cands))
    n = cands[0]
    title = _s(n.get("title"))
    if not title:
        raise PageRefusal("unparseable", "no title")
    title = " ".join(html.unescape(title).split())
    desc = n.get("description")
    if not (isinstance(desc, str) and desc.strip()):
        raise PageRefusal("unparseable", "no description")
    posted_d = _iso_date(n.get("datePosted"))
    if posted_d is None:
        raise PageRefusal("unparseable", "datePosted is absent or not an ISO date/date-time")
    org = n.get("hiringOrganization")
    if not (isinstance(org, dict) and (_type_has(org, "Organization") or _type_has(org, "Person"))
            and _s(org.get("name"))):
        raise PageRefusal("unparseable", "hiringOrganization is not an Organization/Person object with a name")
    ident = n.get("identifier")
    ok_id = (_s(ident) is not None) if isinstance(ident, str) else (
        isinstance(ident, dict) and ((_s(ident.get("value")) is not None) or (
            isinstance(ident.get("value"), int) and not isinstance(ident.get("value"), bool))))
    if not ok_id:
        raise PageRefusal("unparseable", "identifier is absent or has no value")
    jlt = n.get("jobLocationType")
    if jlt is not None and jlt != "TELECOMMUTE":
        raise PageRefusal("unparseable", "jobLocationType %r is not TELECOMMUTE" % (jlt,))
    telecommute = jlt == "TELECOMMUTE"
    places, countries = [], []
    if n.get("jobLocation") is not None:
        for jl in _as_list(n["jobLocation"]):
            addr = jl.get("address") if isinstance(jl, dict) else None
            country = _country_name(addr.get("addressCountry")) if isinstance(addr, dict) else None
            if not country:
                raise PageRefusal("unparseable", "a jobLocation has no address.addressCountry")
            countries.append(country)
            places.append(_s(addr.get("addressLocality")) or ", ".join(
                x for x in (_s(addr.get("addressRegion")), country) if x))
    app_names = []
    if telecommute:
        for req in _as_list(n.get("applicantLocationRequirements")):
            nm = _country_name(req)
            if nm:
                app_names.append(nm)
        if not app_names:
            raise PageRefusal("unparseable", "TELECOMMUTE with no applicantLocationRequirements")
    elif not places:
        raise PageRefusal("unparseable", "no jobLocation and not TELECOMMUTE")
    expired = False
    if n.get("validThrough") is not None:
        vt = _iso_date(n["validThrough"])
        if vt is None:
            raise PageRefusal("unparseable", "validThrough is present and not an ISO date/date-time")
        try:
            expired = vt < datetime.date.fromisoformat(run_date)
        except (TypeError, ValueError):
            expired = False
    location = "; ".join(collections.OrderedDict.fromkeys(places)) if places else "; ".join(
        collections.OrderedDict.fromkeys(app_names))
    posting = {"url": loc_url, "title": title, "location": location or None,
               "posted": _date_slot("ats:", n.get("datePosted").strip()),
               "pay": description_pay_slot(desc, countries + app_names),
               "setting": "Remote" if telecommute else "?"}
    return {"posting": posting, "expired": expired, "in_language": _primary_language(n.get("inLanguage")),
            "basesalary": n.get("baseSalary") not in (None, "")}


# ---- inferred pay: prose to the slot grammar, then the EXISTING parser -------------------------------------------

_PAY_CUES = ("pay range", "salary range", "base pay", "base salary", "compensation range", "hiring range",
             "pay rate", "hourly rate", "annual salary")
_PAY_CUE_INTERVAL = {"annual salary": "yr", "hourly rate": "hr"}
_PAY_BONUS = ("bonus", "commission", "stipend", "allowance", "equity", "sign-on", "signing", "relocation")
_PAY_INTERVALS = (("per year", "yr"), ("/year", "yr"), ("annually", "yr"), ("a year", "yr"), ("per annum", "yr"),
                  ("/yr", "yr"), ("per hour", "hr"), ("/hour", "hr"), ("an hour", "hr"), ("hourly", "hr"),
                  ("/hr", "hr"), ("per month", "mo"), ("/month", "mo"), ("monthly", "mo"))
_ISO_CURRENCIES = frozenset(("USD", "CAD", "EUR", "GBP", "AUD", "NZD", "CHF", "JPY", "INR", "SEK", "NOK", "DKK",
                             "PLN", "MXN", "BRL", "SGD", "HKD", "CNY", "ZAR", "ILS"))
_SYMBOL_CURRENCY = {"€": "EUR", "£": "GBP"}
_FIG = r"(?:(?P<c%(n)s>[$€£]|[A-Z]{3})\s?)?(?P<n%(n)s>\d{1,3}(?:,\d{3})+|\d+)(?P<d%(n)s>\.\d+)?(?P<k%(n)s>[kK]\b)?"
_RANGE_RE = re.compile(_FIG % {"n": "1"} + r"(?:\s*(?:-|–|—|to)\s*" + _FIG % {"n": "2"} + r")?")
_BREAK_TAGS = frozenset(("p", "li", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6"))


class _Segments(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.segs, self._cur = [], []

    def _flush(self):
        t = " ".join("".join(self._cur).replace("\xa0", " ").split())
        if t:
            self.segs.append(t)
        self._cur = []

    def handle_starttag(self, tag, attrs):
        if tag in _BREAK_TAGS:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag in _BREAK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _BREAK_TAGS:
            self._flush()

    def handle_data(self, data):
        self._cur.append(data)

    def close(self):
        html.parser.HTMLParser.close(self)
        self._flush()


def _figure(num, dec, k):
    """`(int amount, has_cents)`."""
    v = int(num.replace(",", ""))
    return (v * 1000 if k else v), bool(dec)


def description_pay_slot(description_html, countries):
    """`stated:<min>-<max>/<yr|mo|hr>/<CUR>[;...]` or `?` -- OURS, STRICT (design 6.4 steps 1-6). The slot then goes
    through the EXISTING `deferred.parse_pay_slot` (see `feed_role`); no second slot-to-`listed_pay` path exists.

    A segment (split at `<p> <li> <br> <div>` and headings) qualifies only if it holds a CUE (`pay range`, `base
    salary`, ...). Figures are read only AFTER the first cue, and a figure with a bonus-class word (`bonus`,
    `commission`, `equity`, `sign-on`, `relocation`, ...) between the cue and it is skipped. A figure needs a
    currency mark (a symbol, or a code adjacent to it) to qualify. Then: whole numbers only (a cent makes the whole
    pay `?`), an interval required (a word within 30 characters after the range, or the cue itself), a currency
    required (`$` is USD only when EVERY JSON-LD country is a US form), min <= max. ANY qualifying range that fails
    a step makes the whole slot `?`: never a partial pay. `?` means not read, never `none`."""
    desc = description_html if isinstance(description_html, str) else ""
    if "<" not in desc and "&lt;" in desc:
        desc = html.unescape(desc)
    seg = _Segments()
    try:
        seg.feed(desc)
        seg.close()
    except Exception:                                       # noqa: BLE001 - unreadable markup reads as no pay
        return "?"
    us = bool(countries) and all(str(c).strip().lower() in US_COUNTRIES for c in countries)
    slots = []
    for text in seg.segs:
        low = text.lower()
        hits = [(low.find(c), c) for c in _PAY_CUES if c in low]
        if not hits:
            continue
        at, cue = min(hits)
        tail, tail_low = text[at + len(cue):], low[at + len(cue):]
        for m in _RANGE_RE.finditer(tail):
            if any(b in tail_low[:m.start()] for b in _PAY_BONUS):
                continue
            c1, c2 = m.group("c1"), m.group("c2")
            after = tail[m.end():m.end() + 30]
            near = tail[max(0, m.start() - 4):m.start()] + " " + after[:8]
            code = next((c for c in (c1, c2) if c in _ISO_CURRENCIES), None) or next(
                (w for w in re.findall(r"\b[A-Z]{3}\b", near) if w in _ISO_CURRENCIES), None)
            symbol = next((c for c in (c1, c2) if c in ("$", "€", "£")), None)
            if not (code or symbol):
                continue                                    # a bare number is not a pay figure: not qualifying
            lo, cents1 = _figure(m.group("n1"), m.group("d1"), m.group("k1"))
            hi, cents2 = ((lo, cents1) if m.group("n2") is None
                          else _figure(m.group("n2"), m.group("d2"), m.group("k2")))
            if cents1 or cents2 or lo <= 0 or hi <= 0 or lo > hi:
                return "?"
            unit = next((u for w, u in _PAY_INTERVALS if w in after.lower()), None) or _PAY_CUE_INTERVAL.get(cue)
            cur = code or _SYMBOL_CURRENCY.get(symbol) or ("USD" if (symbol == "$" and us) else None)
            if not (unit and cur):
                return "?"
            slots.append("%d-%d/%s/%s" % (lo, hi, unit, cur))
    return "stated:" + ";".join(slots) if slots else "?"


# ---- the window verdict: pure (B4) --------------------------------------------------------------------------------

def _capped(today, reviewed):
    return {"state": "capped", "on": today, "reviewed_was": reviewed}


def _reviewed_since(base, last_reviewed):
    """True when the channel's `last_reviewed` is a date on or after the day the window was capped and differs from the
    value it had then -- evidence of a BROWSER review after the capping."""
    try:
        lr = datetime.date.fromisoformat(str(last_reviewed))
        on = datetime.date.fromisoformat(str(base.get("on")))
    except ValueError:
        return False
    return lr >= on and str(last_reviewed) != str(base.get("reviewed_was"))


def workday_window_verdict(W, P, baseline, channel_last_reviewed, today, all_decided=False):
    """`(code or None, new_baseline)` -- the ONE owner of the window rules (design 5.1 with R3), pure.

      W, P            this run's window and the cache's previous `window` (None when there is none: a first poll or
                      a lost cache), as collections of canonical URLs
      baseline        the cache entry's `baseline` (`{"state": "complete"}` or `{"state": "capped", "on", "reviewed_was"}`)
      channel_last_reviewed   `channels[].last_reviewed` of the company's channel, passed in by `run()` (`poll()` reads no store)
      all_decided     every URL in W is already known or seen (classified before any page request)

    |W| < WINDOW_FULL: complete (INFERRED, R3: completeness is assumed, not shown) -> covered, baseline complete.
    At or over it: no P -> `sitemap-capped`; P and W disjoint -> `sitemap-window-gap`; overlap with a capped baseline ->
    `sitemap-capped` until a browser review after the capping; overlap with a complete baseline -> covered ONLY when
    `all_decided`, else `sitemap-capped` (R3: a window at the cap is not covered unless every URL in it is already seen)."""
    W = set(W)
    if len(W) < WINDOW_FULL:
        return None, {"state": "complete"}
    if P is None:
        return "sitemap-capped", _capped(today, channel_last_reviewed)
    if not (W & set(P)):
        return "sitemap-window-gap", _capped(today, channel_last_reviewed)
    base = baseline if isinstance(baseline, dict) and baseline.get("state") in ("complete", "capped") \
        else _capped(today, channel_last_reviewed)
    if base["state"] == "capped":
        if not _reviewed_since(base, channel_last_reviewed):
            return "sitemap-capped", base
        base = {"state": "complete"}
    return (None if all_decided else "sitemap-capped"), base


# ---- the poll -------------------------------------------------------------------------------------

Outcome = collections.namedtuple(
    "Outcome", "company_id vendor slug status code postings unlisted total etag pages host wd", defaults=(None,))
# status: covered | unchanged | not-covered. `postings` are LISTED postings only; `total` counts every
# posting the feed showed (listed + unlisted); `etag` is None unless a single-page 200 sent one. `wd` (dev #775)
# is None for every vendor but Workday, whose Outcome carries `{"entry": <feed-cache entry or None>}`: a Workday
# not-covered outcome may still carry the postings parsed before the verdict (5.3: they are resolved).


def _not_covered(co, ats, host, code):
    return Outcome(co["id"], ats["vendor"], ats_slug.board_key(ats), "not-covered", code, [], 0, 0, None, 0, host)


class _Budget(Exception):
    pass


def _proxy_is_local(env):
    for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        v = (env or {}).get(k)
        if v:
            try:
                h = urllib.parse.urlsplit(v if "//" in v else "//" + v).hostname or ""
            except ValueError:
                continue
            if h in ("localhost", "127.0.0.1", "::1"):
                return True
    return False



class _WdFail(Exception):
    """A Workday site could not be covered: `code` is a `journal.FEED_FAILURES` code. `transport` is True when the
    failure was a transport failure or put the host down for the run -- the site's feed-cache entry is then NOT
    written (B4), because nothing about the window can be trusted from a run the host cut short."""

    def __init__(self, code, transport=False):
        Exception.__init__(self, code)
        self.code, self.transport = code, transport


def _board_host(ats):
    """The host a stored `ats` object names (for Workday, the per-tenant host)."""
    if ats["vendor"] == "workday":
        return workday_host(ats)
    return ENDPOINTS[(ats["vendor"], ats.get("region") if ats["vendor"] == "lever" else None)][0]


class _Workday(object):
    """The Workday vendor inside one `poll()`: it shares the poll's `get` (the interval, the deadline, the
    User-Agent, GET only), its `host_ok` / `host_down` and its clock, so a Workday host is held to exactly the rules
    every other feed host is (F3-F10). Two phases (design 4.1):

      phase 1 (`phase1`, in company order, beside every other vendor's feed): robots.txt once per tenant host per run,
              the sitemap document(s) once each, then the window is classified and the pure verdict computed;
      phase 2 (`phase2`, after every company's phase 1): only the NEW job pages, up to WORKDAY_PAGES_PER_SITE, and
              only until `limit2` (the deadline less WORKDAY_RESERVE_S, B3).

    It reads no store: `known` (the resolver's own de-dup predicate), `reviewed` (channel last_reviewed by company),
    `locales` and `cache` are handed in."""

    def __init__(self, get, clock, spent, deadline_s, host_ok, host_down, env, today, known, reviewed, locales,
                 cache, limit2):
        self.get, self.clock, self.host_ok, self.host_down, self.env = get, clock, host_ok, host_down, env
        self.spent, self.deadline_s = spent, deadline_s
        self.today, self.known, self.reviewed = today, known or (lambda _u: False), reviewed or {}
        self.locales, self.cache, self.limit2 = locales or {}, cache, limit2
        self.robots, self.sites = {}, {}

    # -- outcomes ---------------------------------------------------------------------------------------------

    def nc(self, co, ats, host, code):
        return Outcome(co["id"], "workday", ats_slug.board_key(ats), "not-covered", code, [], 0, 0, None, 0, host)

    def _finish(self, st, code):
        """The Outcome for a site that reached the end of its run. The cache entry is built ONLY when the window was
        read and the run was not cut short by a transport failure or a host-down (B4); it is written by `run()`
        after the resolver commits, for covered AND not-covered outcomes."""
        W = st.get("W")
        entry = None
        if W is not None and not st["transport"]:
            seen = (st["seen"] | st["decided"]) & set(W)
            entry = {"window": list(W), "seen": sorted(seen), "baseline": st["baseline"],
                     "basesalary_seen": st["bs_total"], "in_language": st["lang"], "at": self.today}
        co = st["co"]
        status = "covered" if code is None else "not-covered"
        return Outcome(co["id"], "workday", st["key"], status, code, st["postings"], st["expired"],
                       len(W) if W is not None else 0, None, st["pages"], st["host"], {"entry": entry})

    # -- requests ---------------------------------------------------------------------------------------------

    def fetch(self, host, path, limit=None):
        """One Workday GET through the shared `get`, with the F3/F5 classification; returns a Response or raises
        `_WdFail` (or `_Budget`, which the caller turns into `budget-exhausted`)."""
        try:
            resp = _workday_get(self.get, host, path, limit)
            if resp.status in (429, 503):
                wait = parse_retry_after(resp.headers.get("retry-after"))
                cap = self.deadline_s if limit is None else limit
                if wait is not None and wait <= RETRY_AFTER_CAP_S and self.spent() + wait <= cap:
                    self.clock.sleep(wait)
                    resp = _workday_get(self.get, host, path, limit)
        except FetchError as fe:
            if fe.code != "redirected" and host not in self.host_ok:
                self.host_down[host] = fe.code
            raise _WdFail(fe.code, transport=True)
        if resp.status in (429, 503):
            self.host_down[host] = "rate-limited"
            raise _WdFail("rate-limited", transport=True)
        egress = resp.status == 403 and host not in self.host_ok and _proxy_is_local(self.env)
        if not egress:
            self.host_ok.add(host)
        if egress:
            self.host_down[host] = "egress-blocked"
            raise _WdFail("egress-blocked", transport=True)
        if "challenge" in str(resp.headers.get("cf-mitigated", "")).lower() or resp.status == 403:
            self.host_down[host] = "blocked"
            raise _WdFail("blocked", transport=True)
        return resp

    @staticmethod
    def _status_code(status):
        if status in (404, 410):
            return "not-found"
        if status == 401:
            return "auth-required"
        return "http-error"

    def _robots(self, host):
        """`(rules, sitemaps)` for a host, fetched ONCE per host per run (and never cached across runs, W5)."""
        hit = self.robots.get(host)
        if hit is not None:
            if hit[0] == "fail":
                raise _WdFail(hit[1], hit[2])
            return hit[1], hit[2]
        try:
            resp = self.fetch(host, "/robots.txt")
            ctype = str(resp.headers.get("content-type", "")).lower()
            if resp.status != 200:
                raise _WdFail("robots-unavailable")
            if "text/html" in ctype or _looks_like_html(resp.body):
                self.host_down[host] = "blocked"
                raise _WdFail("blocked", transport=True)
            if not ctype.startswith("text/plain"):
                raise _WdFail("robots-unavailable")
            body = resp.body
            truncated = len(body) > ROBOTS_PARSE_LIMIT
            body = body[:ROBOTS_PARSE_LIMIT]
            m = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", ctype)
            charset = (m.group(1).lower() if m else "utf-8")
            if charset not in ("utf-8", "iso-8859-1", "us-ascii"):
                charset = "utf-8"
            try:
                text = body.decode(charset, "ignore" if truncated else "strict")
            except UnicodeDecodeError:
                raise _WdFail("robots-unavailable")
            groups, sitemaps = parse_robots(text)
            self.robots[host] = ("ok", robots_rules_for(groups), sitemaps)
            return self.robots[host][1], sitemaps
        except _WdFail as f:
            self.robots[host] = ("fail", f.code, f.transport)
            raise

    @staticmethod
    def _advertised(sitemaps, host, site):
        """`(site as advertised, the Sitemap: line verbatim, its path)` -- exactly ONE line, https, this host, path
        exactly `/<site>/siteMap.xml` (site and file name compared case-insensitively). Else `sitemap-not-advertised`."""
        found = []
        for line in sitemaps:
            try:
                u = urllib.parse.urlsplit(line)
                port = u.port
            except ValueError:
                continue
            if u.scheme != "https" or (u.hostname or "").lower() != host or port not in (None, 443) \
                    or u.query or u.fragment:
                continue
            segs = u.path.split("/")
            if len(segs) == 3 and segs[0] == "" and segs[1].casefold() == site.casefold() \
                    and segs[2].casefold() == "sitemap.xml":
                found.append((segs[1], line, u.path))
        if len(found) != 1:
            raise _WdFail("sitemap-not-advertised")
        return found[0]

    def _read_sitemap(self, host, adv, rules, url, child):
        path = urllib.parse.urlsplit(url).path
        if not robots_allows(rules, path):
            raise _WdFail("robots-disallowed")
        resp = self.fetch(host, path)
        if resp.status != 200:
            raise _WdFail(self._status_code(resp.status))
        try:
            return parse_workday_sitemap(resp.body, resp.headers, host, adv, gz=child and path.endswith(".gz"),
                                         allow_index=not child)
        except SitemapRefusal as r:
            if r.code == "blocked":
                self.host_down[host] = "blocked"
                raise _WdFail("blocked", transport=True)
            raise _WdFail(r.code)

    # -- phase 1 ----------------------------------------------------------------------------------------------

    def phase1(self, co, ats):
        """None when the site goes on to phase 2, else its final Outcome."""
        host = workday_host(ats)
        if ats_slug.check_ats(ats) or not host_in_family(host):
            return self.nc(co, ats, host, "unparseable")
        if host in self.host_down:
            return self.nc(co, ats, host, self.host_down[host])
        key = ats_slug.board_key(ats)
        entry = self.cache.get("workday:-:" + key)
        entry = entry if isinstance(entry, dict) else {}
        prev_window = entry.get("window") if isinstance(entry.get("window"), list) else None
        prev_seen = set(x for x in (entry.get("seen") or []) if isinstance(x, str)) \
            if isinstance(entry.get("seen"), list) else set()
        bs = entry.get("basesalary_seen")
        st = {"co": co, "ats": ats, "host": host, "key": key, "W": None, "raw": {}, "new": [], "rules": None,
              "adv": None, "seen": prev_seen, "decided": set(), "code": None, "transport": False,
              "postings": [], "expired": 0, "pages": 0, "baseline": None, "lang": None,
              "bs_total": bs if isinstance(bs, int) and not isinstance(bs, bool) and bs >= 0 else 0, "entry": entry}
        try:
            rules, sitemaps = self._robots(host)
            adv, sitemap_url, spath = self._advertised(sitemaps, host, ats["site"])
            st["adv"], st["rules"] = adv, rules
            if not (robots_allows(rules, "/%s/" % adv) and robots_allows(rules, spath)):
                raise _WdFail("robots-disallowed")
            urls, children = self._read_sitemap(host, adv, rules, sitemap_url, False)
            if children:
                if len(children) > MAX_PAGES:
                    raise _WdFail("sitemap-malformed")
                for child in children:
                    got, _none = self._read_sitemap(host, adv, rules, child, True)
                    urls += got
            raw = collections.OrderedDict()
            for loc in urls:
                canon = canonical_job_url(loc)
                if canon is None:
                    raise _WdFail("sitemap-malformed")
                raw.setdefault(canon, loc)
            if len(raw) >= SITEMAP_MAX_LOCS:
                raise _WdFail("sitemap-malformed")
            W = list(raw)
            st["W"], st["raw"] = W, raw
            st["baseline"] = entry.get("baseline") if isinstance(entry.get("baseline"), dict) \
                else _capped(self.today, self.reviewed.get(co["id"]))
            new = []
            for canon in W:
                p = urllib.parse.urlsplit(raw[canon])
                if not robots_allows(rules, p.path + ("?" + p.query if p.query else "")):
                    raise _WdFail("robots-disallowed")
                if self.known(canon) or canon in prev_seen:
                    continue
                new.append(canon)
            st["new"] = new
            code, baseline = workday_window_verdict(W, prev_window, entry.get("baseline"),
                                                    self.reviewed.get(co["id"]), self.today, all_decided=not new)
            st["code"], st["baseline"] = code, baseline
        except _Budget:
            return self.nc(co, ats, host, "budget-exhausted")
        except _WdFail as f:
            st["transport"] = st["transport"] or f.transport
            return self._finish(st, f.code)
        self.sites[co["id"]] = st
        return None

    # -- phase 2 ----------------------------------------------------------------------------------------------

    def phase2(self, co):
        st = self.sites[co["id"]]
        host = st["host"]

        def first(code):
            if st["code"] is None:
                st["code"] = code
        try:
            pages = st["new"][:WORKDAY_PAGES_PER_SITE]
            for canon in pages:
                if host in self.host_down:
                    st["transport"] = True
                    first(self.host_down[host])
                    break
                loc = st["raw"][canon]
                p = urllib.parse.urlsplit(loc)
                path = p.path + ("?" + p.query if p.query else "")
                try:
                    resp = self.fetch(host, path, limit=self.limit2)
                except _WdFail as f:
                    st["transport"] = st["transport"] or f.transport
                    first(f.code)
                    break
                st["pages"] += 1
                if resp.status != 200:
                    first(self._status_code(resp.status))
                    continue
                if urllib.parse.urlsplit(resp.final_url or loc).path.rstrip("/") != p.path.rstrip("/"):
                    first("no-jsonld")                    # a withdrawn job redirected to the site's search page
                    continue
                try:
                    got = parse_jobposting(resp.body, loc, self.today)
                except PageRefusal as r:
                    first(r.code)
                    continue
                st["decided"].add(canon)
                if got["basesalary"]:
                    st["bs_total"] += 1
                if got["in_language"]:
                    st["lang"] = got["in_language"]
                if got["expired"]:
                    st["expired"] += 1
                else:
                    st["postings"].append(got["posting"])
            if len(st["new"]) > WORKDAY_PAGES_PER_SITE:
                first("budget-exhausted")
        except _Budget:
            first("budget-exhausted")
        # R2 (locale rule b): coverage means titles in the tenant's DEFAULT locale. A careers URL whose language
        # differs from the pages' `inLanguage` is not covered. No Accept-Language is ever sent.
        url_locale = self.locales.get(co["id"])
        lang = st["lang"] or (st["entry"].get("in_language") if isinstance(st["entry"].get("in_language"), str)
                              else None)
        if url_locale and lang and url_locale.split("-")[0].lower() != lang:
            first("locale-mismatch")
        st["lang"] = lang
        return self._finish(st, st["code"])


def poll(companies, fetch=default_fetch, clock=None, cache=None, deadline_s=DEADLINE_S, env=None,
         known=None, reviewed=None, locales=None, today=None, reserve_s=WORKDAY_RESERVE_S):
    """`{company_id: Outcome}` (insertion-ordered) for each company in `companies` that carries an
    `ats` OBJECT -- and ONLY those (A1): a company with no `ats`, or `ats: null`, is never fetched.

    `fetch` and `clock` are injected (tests pass fakes; no sleeping, no socket). `cache` is
    `{"<vendor>:<region>:<slug>": {"etag", "pages", ...}}` (a Workday site's entry is keyed
    `workday:-:<tenant>.<wd>/<site>` and holds its window, `seen` set and baseline). This function reads no
    store and writes none: resolution, stamping and the cache write are `run`'s, after it. See the module
    docstring for the host-first rule, the deadline and the paging rule.

    The Workday vendor (dev #775) needs four things `poll` cannot read for itself, so `run` hands them in:
    `known(canonical_url) -> bool` (the resolver's own de-dup predicate), `reviewed` (`{company_id: the
    company's channel last_reviewed}`), `locales` (`{company_id: 'll-CC' from the candidate's URL}`), and `today`.
    Workday runs in TWO PHASES: every company's listing (every vendor) is read before any Workday job page, and
    phase 2 stops `reserve_s` short of `deadline_s` (B3)."""
    clock = clock or RealClock()
    cache = cache or {}
    env = os.environ if env is None else env
    start = clock.now()
    last_at, host_ok, host_down = {}, set(), {}
    outcomes = collections.OrderedDict()

    def spent():
        return clock.now() - start

    def get(host, url, etag, limit=None):
        cap = deadline_s if limit is None else limit
        if spent() >= cap:
            raise _Budget()
        wait = MIN_INTERVAL_S - (clock.now() - last_at[host]) if host in last_at else 0
        if wait > 0:
            if spent() + wait > cap:
                raise _Budget()
            clock.sleep(wait)
        headers = {"User-Agent": USER_AGENT}
        if etag:
            headers["If-None-Match"] = etag
        last_at[host] = clock.now()
        return fetch(Request("GET", url, headers, TIMEOUT_S))

    def classify(status, resp, host, sent_etag):
        """`(code, host_level)` for a response that is not a usable 200/304."""
        if status in (401, 403):
            if status == 403 and host not in host_ok and _proxy_is_local(env):
                return "egress-blocked", True
            return "auth-required", False
        if status == 404:
            return "not-found", False
        return "http-error", False

    wd = _Workday(get, clock, spent, deadline_s, host_ok, host_down, env,
                  today or datetime.date.today().isoformat(), known, reviewed, locales, cache,
                  max(0, deadline_s - reserve_s))
    wd_pending = []
    for co in companies:
        ats = co.get("ats")
        if not isinstance(ats, dict) or co.get("status") == "passed":
            continue
        if ats.get("vendor") == "workday":                    # phase 1; phase 2 follows the loop
            outcomes[co["id"]] = None
            oc = wd.phase1(co, ats)
            if oc is None:
                wd_pending.append(co)
            else:
                outcomes[co["id"]] = oc
            continue
        key = (ats["vendor"], ats.get("region") if ats["vendor"] == "lever" else None)
        host, path = ENDPOINTS[key]
        cache_key = "%s:%s:%s" % (ats["vendor"], ats.get("region") or "-", ats["slug"])
        if host in host_down:
            outcomes[co["id"]] = _not_covered(co, ats, host, host_down[host])
            continue
        if not ats_slug.SLUG_RE.match(str(ats.get("slug"))):
            outcomes[co["id"]] = _not_covered(co, ats, host, "unparseable")
            continue
        base = "https://%s%s" % (host, path % ats["slug"])
        entry = cache.get(cache_key) or {}
        postings, unlisted, total, etag_out, pages = [], 0, 0, None, 0
        outcome = None
        try:
            skip = 0
            while True:
                if ats["vendor"] == "lever":
                    url = "%s?mode=json&skip=%d&limit=%d" % (base, skip, LEVER_PAGE)
                elif ats["vendor"] == "ashby":
                    url = base + "?includeCompensation=true"
                else:
                    url = base
                # conditional GET: only for a feed known to be ONE page (page 1 unchanged does not
                # say page 2 is), and only on its first page
                send_etag = entry.get("etag") if (pages == 0 and entry.get("pages", 1) == 1) else None
                try:
                    resp = get(host, url, send_etag)
                    if resp.status in (429, 503):
                        wait = parse_retry_after(resp.headers.get("retry-after"))
                        if wait is not None and wait <= RETRY_AFTER_CAP_S and spent() + wait <= deadline_s:
                            clock.sleep(wait)
                            resp = get(host, url, send_etag)
                except FetchError as fe:
                    code = fe.code
                    first = host not in host_ok
                    if code == "redirected" or not first:
                        outcome = _not_covered(co, ats, host, code)
                    else:
                        host_down[host] = code
                        outcome = _not_covered(co, ats, host, code)
                    break
                if resp.status in (429, 503):
                    host_down[host] = "rate-limited"
                    outcome = _not_covered(co, ats, host, "rate-limited")
                    break
                if not (resp.status == 403 and host not in host_ok and _proxy_is_local(env)):
                    # ANY answer from the vendor proves the host is reachable (a 404 included); a 403
                    # that may be the local proxy refusing the host proves nothing (review B1).
                    host_ok.add(host)
                if resp.status == 304 and send_etag:
                    outcome = Outcome(co["id"], ats["vendor"], ats["slug"], "unchanged", None, [], 0,
                                      0, send_etag, entry.get("pages", 1), host)
                    break
                if resp.status != 200:
                    code, host_level = classify(resp.status, resp, host, send_etag)
                    if host_level:
                        host_down[host] = code
                    outcome = _not_covered(co, ats, host, code)
                    break
                try:
                    got, unl = PARSERS[ats["vendor"]](resp.body)
                except Unparseable:
                    outcome = _not_covered(co, ats, host, "unparseable")
                    break
                pages += 1
                postings += got
                unlisted += unl
                total += len(got) + unl
                if pages == 1:
                    etag_out = resp.headers.get("etag")
                # Lever pages until a short page; a vendor that always returns a full page is capped
                if ats["vendor"] == "lever" and len(got) >= LEVER_PAGE:
                    if pages >= MAX_PAGES:
                        outcome = _not_covered(co, ats, host, "unparseable")
                        break
                    skip += LEVER_PAGE
                    continue
                outcome = Outcome(co["id"], ats["vendor"], ats["slug"], "covered", None, postings,
                                  unlisted, total, etag_out if pages == 1 else None, pages, host)
                break
        except _Budget:
            outcome = _not_covered(co, ats, host, "budget-exhausted")
            # the deadline is spent: every company after this one is unreached too (set below)
        outcomes[co["id"]] = outcome
    for co in wd_pending:                                     # phase 2: only the NEW job pages (dev #775)
        outcomes[co["id"]] = wd.phase2(co)
    return outcomes


# ---- the run: discover, poll, resolve, stamp, journal ----------------------------------------------

def _load(name):
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _read_config():
    """config.json as a dict; unreadable or absent reads as {} (the switch then defaults to ON, as before 0.76.0)."""
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def cache_path():
    return os.path.join(ROOT, ".jobsearch", "feed_etags.json")


def read_cache():
    """The ETag cache. It is a CACHE: deleting it costs one full fetch per board, and an unreadable
    one is treated as empty (never trusted)."""
    try:
        with open(cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_cache(cache):
    path = cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _record_py(*args, **kw):
    cmd = [sys.executable, os.path.join(HERE, "record.py")] + list(args)
    if kw.get("already_locked"):
        cmd.append("--already-locked")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


def discover_all(companies, channels, opps, already_locked, dry_run, out):
    """Run `ats_slug.discover` for every company with no `ats` key (a present `null` or object is never
    touched), writing each unambiguous result through `record.py ats --discover` (the lock, the
    validator and the rollback apply). Returns `(discovered, ambiguous)` counts."""
    discovered = ambiguous = 0
    for co in companies:
        if "ats" in co or co.get("status") == "passed":
            continue
        d = ats_slug.discover(co, opps)
        if d.ambiguous:
            ambiguous += 1
            out("ATS AMBIGUOUS %s: %s" % (co["id"], " | ".join("%s:%s" % (t[0], t[1])
                                                                  for t in d.ambiguous)))
            continue
        if d.found is None:
            continue
        if dry_run:
            out("ATS WOULD DISCOVER %s %s:%s (%s)" % (co["id"], d.found[0], d.found[1], d.source))
            discovered += 1
            continue
        r = _record_py("ats", co["id"], "--discover", already_locked=already_locked)
        line = " ".join((r.stdout or "").split())
        if r.returncode == 0 and (r.stdout or "").lstrip().startswith("ATS "):
            discovered += 1
        out(line or "ATS discovery for %s: record.py exit %d" % (co["id"], r.returncode))
    return discovered, ambiguous


def _gap(run_id, scope, reason, closes_when, out):
    try:
        if any(g.get("scope") == scope for g in _journal.open_gaps(_journal.read(ROOT), run_id=run_id)):
            return
        _journal.record_gap(ROOT, run_id, scope, reason, closes_when=closes_when)
    except _journal.JournalError as e:
        out("⚠️ could not journal the gap %s (%s)" % (scope, e))


def _close_gaps(prefix_or_scope, out):
    try:
        recs = _journal.read(ROOT)
        for g in _journal.open_gaps(recs):
            if g.get("scope") == prefix_or_scope:
                _journal.append(ROOT, {"event": "gap-closed", "gap_id": g["gap_id"],
                                       "at": _journal.now_iso()})
    except _journal.JournalError as e:
        out("⚠️ could not close the gap %s (%s)" % (prefix_or_scope, e))


def feed_role(company, posting, vendor, channel_id, canonical_job_url, deferred):
    """The role dict `deferred._resolve_roles` takes for one feed posting: the SAME shape
    `parse_roles` builds, with the company named by the polled company's own name (so the resolver's
    company match is the company the slug belongs to, never a string from the vendor) and the
    company-site channel + `feed:<vendor>` source (B7)."""
    pay, _why = deferred.parse_pay_slot(posting["pay"])
    if vendor == "workday" and pay and pay.get("state") == "employer-stated":
        # dev #775 (6.4): a Workday figure was READ out of the description text, not stated in a field. The marker
        # says so; it is legal only with employer-stated + listing-text (validate_data.check_listed_pay).
        pay = dict(pay, inferred_from="description")
    kind, value, why = deferred.parse_posted_slot(posting["posted"])
    if why:
        kind, value = "unknown", None
    return {"url": posting["url"], "title": posting["title"], "company": company.get("name") or company["id"],
            "location": posting.get("location") or "?", "posted": posting["posted"],
            "pay": pay, "posted_parsed": (kind, value), "setting": posting.get("setting") or "?",
            "slots": {"pay": posting["pay"], "posted": posting["posted"],
                      "setting": posting.get("setting") or "?"},
            "q": [], "canonical": canonical_job_url(posting["url"]),
            "channel_id": channel_id, "source": "feed:%s" % vendor}


def run(run_id, fetch=default_fetch, clock=None, today=None, already_locked=False, dry_run=False,
        out=print, deadline_s=DEADLINE_S):
    """The whole job; returns the exit code. See the module docstring."""
    import config_keys as _config_keys
    import deferred as _deferred
    import profile as _profile
    from pipeline_index import find_known_match
    # dev #774: the whole poller is one switch. Checked FIRST -- a profile with no title keys is still asked, and the
    # honest answer to "are feeds on" does not depend on whether the titles are configured.
    on, problem = _config_keys.feeds_enabled(_read_config())
    if problem:
        out("⚠️ " + problem)
    if not on:
        out("FEEDS OFF (sourcing.feeds.enabled)")
        if not dry_run:
            try:
                _journal.record_feeds(ROOT, run_id, polled=0, covered=0, unchanged=0, not_covered=0, failures={},
                                      companies_not_covered={}, postings=0, unlisted=0, selected=0, captured=0,
                                      known=0, carried=0, role_gaps=0, off=True)
            except _journal.JournalError as e:
                out("⚠️ could not journal the feeds-off event (%s)" % e)
        return 0
    companies, channels, opps = _load("companies.jsonl"), _load("channels.jsonl"), _load("opportunities.jsonl")
    try:
        prof = _profile.load()
    except Exception as e:                                    # noqa: BLE001 - any unreadable profile
        prof = {}
        out("⚠️ the profile could not be read (%s)" % e)
    if _profile.title_matches("probe", prof) is None:
        out("⛔ FEEDS NOT RUN: no readable title keys (targets.titles is empty, or screen.title_floor / "
            "screen.likely_pass_signals cannot be read). Capturing every opening at every company is "
            "not a safe default.")
        if not dry_run:
            _gap(run_id, "jobsearch:feeds", "other",
                 "targets.titles is configured and the title keys read, then feed_poll.py runs", out)
        return 3
    starts = [r for r in _journal.read(ROOT) if r.get("event") == "start" and r.get("run_id") == run_id]
    run_date = today or (str(starts[0].get("at"))[:10] if starts else datetime.date.today().isoformat())

    discovered, ambiguous = discover_all(companies, channels, opps, already_locked, dry_run, out)
    if discovered and not dry_run:
        companies, channels = _load("companies.jsonl"), _load("channels.jsonl")
    chan_of = {c.get("company_id"): c.get("id") for c in channels
               if c.get("type") == "company-site" and c.get("company_id")}
    to_poll = [c for c in companies if isinstance(c.get("ats"), dict) and c.get("status") != "passed"]

    cache = read_cache()

    def known(canon):
        """The resolver's OWN de-dup predicate (`pipeline_index.find_known_match`, URL basis), called -- never a
        second URL test (dev #775, C5): a URL it knows is not fetched."""
        return find_known_match(opps, url=canon) is not None
    reviewed = {c.get("company_id"): c.get("last_reviewed") for c in channels
                if c.get("type") == "company-site" and c.get("company_id")}
    locales = {}
    for c in to_poll:
        if c["ats"].get("vendor") == "workday":
            lc = ats_slug.workday_locale_for(c, opps, c["ats"])
            if lc:
                locales[c["id"]] = lc
    outcomes = poll(to_poll, fetch=fetch, clock=clock, cache=cache, deadline_s=deadline_s, known=known,
                    reviewed=reviewed, locales=locales, today=run_date)
    # companies the deadline never reached are not silently absent: they are NOT COVERED
    for co in to_poll:
        if co["id"] not in outcomes:
            a = co["ats"]
            outcomes[co["id"]] = Outcome(co["id"], a["vendor"], ats_slug.board_key(a), "not-covered",
                                         "budget-exhausted", [], 0, 0, None, 0, _board_host(a))

    apps = _load("applications.jsonl")
    recs = _journal.read(ROOT)
    rows = _deferred.replay(_deferred.load())
    totals = {"captured": 0, "known": 0, "carried": 0, "role_gaps": 0, "quarantined": 0}
    postings_n = unlisted_n = selected_n = sightings = 0
    failures, not_covered_map, hosts_down = {}, {}, {}
    covered_n = unchanged_n = 0
    by_id = {c["id"]: c for c in to_poll}
    stamp_ids = []

    def resolve(co, oc, channel):
        """Select the postings whose title matches and resolve each through the SAME per-role resolver a sweep
        uses. Shared by a covered feed and (dev #775, 5.3) a Workday site that is NOT covered but fully parsed
        some pages: those are real postings, and not resolving them would re-fetch them next run."""
        nonlocal selected_n, sightings
        roles = []
        for p in oc.postings:
            m = _profile.title_matches(p["title"], prof)
            if m:
                roles.append(feed_role(co, p, oc.vendor, channel, canonical_job_url, _deferred))
        selected_n += len(roles)
        if roles and not dry_run:
            res = _deferred._resolve_roles(
                roles, run_id, "feed", [], run_date, "feed", opps, companies, apps, recs, rows,
                out, already_locked)
            for k in totals:
                totals[k] += res["counts"][k]
            sightings += res["siblings"]
        elif roles:
            out("DRY RUN %s: %d posting(s) match a configured title (nothing resolved)"
                % (co["id"], len(roles)))

    for cid, oc in outcomes.items():
        co = by_id[cid]
        channel = chan_of.get(cid)
        if oc.status == "not-covered":
            failures[oc.code] = failures.get(oc.code, 0) + 1
            not_covered_map[cid] = oc.code
            if oc.code in _journal.FEED_HOST_CODES and oc.code != "budget-exhausted":
                hosts_down[oc.host] = oc.code
            if oc.postings or oc.unlisted:                   # Workday only: pages parsed before the verdict
                postings_n += len(oc.postings) + oc.unlisted
                unlisted_n += oc.unlisted
                resolve(co, oc, channel)
            continue
        covered_n += 1
        postings_n += oc.total
        unlisted_n += oc.unlisted
        if oc.status == "unchanged":
            unchanged_n += 1
        else:
            resolve(co, oc, channel)
        stamp_ids.append((cid, channel, oc))

    # bookkeeping: stamp each covered feed's channel (the feed IS its review), THEN the ETag --
    # an ETag is written only after that body's roles were resolved and committed.
    if not dry_run:
        for cid, channel, oc in stamp_ids:
            if channel:
                r = _record_py("set", channel, "last_reviewed", run_date, "--file", "channels",
                               already_locked=already_locked)
                if r.returncode != 0:
                    out("⚠️ could not stamp %s reviewed (%s)" % (channel, " ".join(
                        (r.stdout + r.stderr).split())[-200:]))
            key = "%s:%s:%s" % (oc.vendor, by_id[cid]["ats"].get("region") or "-", oc.slug)
            if oc.vendor == "workday":
                pass                   # a Workday entry is not an ETag: it is written below for EVERY decided outcome
            elif oc.etag:
                cache[key] = {"etag": oc.etag, "pages": max(oc.pages, 1), "at": run_date}
            else:
                cache.pop(key, None)
            _close_gaps(_journal.FEED_COMPANY_GAP_SCOPE % cid, out)
        # dev #775 (B4): a Workday site's cache entry (window, seen, baseline) is written for covered AND
        # not-covered outcomes, AFTER the resolver committed, and never for a run a transport failure or a
        # host-down cut short (such an outcome carries no entry).
        for cid, oc in outcomes.items():
            if oc.vendor == "workday" and oc.wd and oc.wd.get("entry"):
                cache["workday:-:" + oc.slug] = oc.wd["entry"]
        try:
            write_cache(cache)
        except OSError as e:
            out("⚠️ could not write the ETag cache (%s); the next poll fetches in full" % e)
        reached = {oc.host for oc in outcomes.values() if oc.status != "not-covered"}
        for h in reached:
            _close_gaps(_journal.FEED_HOST_GAP_SCOPE % h, out)

    n_nc = len(not_covered_map)
    for cid, code in not_covered_map.items():
        oc = outcomes[cid]
        out("FEED NOT COVERED %s %s:%s %s" % (cid, oc.vendor, oc.slug, code))
        if not dry_run and code in _journal.FEED_BOARD_CODES:
            _gap(run_id, _journal.FEED_COMPANY_GAP_SCOPE % cid, _journal.FEED_FAILURES[code],
                 "a later poll covers it", out)
    for host, code in sorted(hosts_down.items()):
        skipped = sum(1 for oc in outcomes.values() if oc.host == host and oc.code == code)
        out("FEED HOST DOWN %s %s (%d compan%s not polled)" % (host, code, skipped,
                                                                "y" if skipped == 1 else "ies"))
        if not dry_run:
            _gap(run_id, _journal.FEED_HOST_GAP_SCOPE % host, _journal.FEED_FAILURES[code],
                 "a later poll reaches %s" % host, out)
    if failures.get("budget-exhausted") and not dry_run:
        _gap(run_id, "jobsearch:feeds:budget", "timeout",
             "a later poll finishes inside its %d s deadline" % deadline_s, out)

    if not dry_run:
        try:
            _journal.record_feeds(
                ROOT, run_id, polled=len(outcomes), covered=covered_n, unchanged=unchanged_n,
                not_covered=n_nc, failures=failures, companies_not_covered=not_covered_map,
                postings=postings_n, unlisted=unlisted_n, selected=selected_n,
                captured=totals["captured"], known=totals["known"], carried=totals["carried"],
                role_gaps=totals["role_gaps"], sightings_added=sightings, discovered=discovered,
                ambiguous=ambiguous, quarantined=totals["quarantined"], hosts_down=hosts_down)
        except _journal.JournalError as e:
            out("⚠️ could not journal the feeds event (%s)" % e)
    out("FEEDS polled %d · covered %d (%d unchanged) · NOT COVERED %d%s · selected %d → %d captured, "
        "%d known, %d carried, %d role gap(s) · %d discovered · %d ambiguous"
        % (len(outcomes), covered_n, unchanged_n, n_nc,
           (" (%s)" % ", ".join("%s ×%d" % (c, n) for c, n in sorted(failures.items())))
           if failures else "", selected_n, totals["captured"], totals["known"], totals["carried"],
           totals["role_gaps"], discovered, ambiguous))
    return 4 if n_nc else 0


def coverage_summary(companies, recs):
    """Pure (dev #774): `{fed, covered, not_covered, not_checked}` over the tracked companies that carry an `ats` slug --
    the SAME per-company answer `journal.feed_company_state` gives the board report, counted. A company the last
    poll proves nothing about (never polled, attached after it, or the feeds were turned off) is `not_checked`, never
    `covered`. `sources.py` composes this; it computes no coverage of its own."""
    out = {"fed": 0, "covered": 0, "not_covered": 0, "not_checked": 0}
    for co in companies:
        if not isinstance(co.get("ats"), dict) or co.get("status") == "passed":
            continue
        out["fed"] += 1
        st = _journal.feed_company_state(recs, co)["state"]
        out[{"covered": "covered", "not-covered": "not_covered"}.get(st, "not_checked")] += 1
    return out


def status(out=print):
    """Read-only: what is slugged, what each company's last poll said, what discovery cannot settle, and
    which company-site channels are not linked to a company."""
    companies, channels, opps = _load("companies.jsonl"), _load("channels.jsonl"), _load("opportunities.jsonl")
    try:
        recs = _journal.read(ROOT)
    except _journal.JournalError as e:
        recs = []
        out("⚠️ the journal cannot be read (%s): last outcomes are UNKNOWN" % e)
    ev = (_journal.feeds_events(recs) or [None])[-1]
    import config_keys as _config_keys
    _on, _problem = _config_keys.feeds_enabled(_read_config())
    if not _on:
        out("FEEDS ARE OFF (sourcing.feeds.enabled is false): nothing is polled. `record.py source on company-feeds` "
            "turns them back on.")
    chan_of = {c.get("company_id"): c.get("id") for c in channels if c.get("company_id")}
    slugged = [c for c in companies if isinstance(c.get("ats"), dict)]
    out("FEEDS — %d compan%s polled, %d declined (ats: null), %d with no slug"
        % (len(slugged), "y" if len(slugged) == 1 else "ies",
           sum(1 for c in companies if "ats" in c and c["ats"] is None),
           sum(1 for c in companies if "ats" not in c)))
    cache = read_cache()
    for c in slugged:
        a = c["ats"]
        last = "never polled"
        if ev is not None:
            code = (ev.get("companies_not_covered") or {}).get(c["id"])
            if code:
                last = "%s: NOT COVERED %s" % (str(ev.get("at"))[:10], code)
            elif a.get("vendor") == "workday":
                # ruling R3: until probe U1 is recorded, "the window lists every open job" is ASSUMED, not shown
                last = "%s: covered (sitemap window; completeness assumed)" % str(ev.get("at"))[:10]
            else:
                last = "%s: covered" % str(ev.get("at"))[:10]
        out("  %-24s %s:%s%s (%s) -> %s · %s" % (
            c["id"], a.get("vendor"), ats_slug.board_key(a), (" " + a["region"]) if a.get("region") else "",
            a.get("source"), chan_of.get(c["id"], "NO CHANNEL"), last))
        if a.get("vendor") == "workday":
            wc = cache.get("workday:-:" + str(ats_slug.board_key(a)))
            if isinstance(wc, dict):
                base = wc.get("baseline") if isinstance(wc.get("baseline"), dict) else {}
                out("      window %d (cap %d) · baseline %s · seen %d · baseSalary present on %d page(s) "
                    "(never read for pay)" % (len(wc.get("window") or []), WINDOW_FULL, base.get("state", "unknown"),
                                              len(wc.get("seen") or []), wc.get("basesalary_seen") or 0))
            else:
                out("      no window recorded yet (the first Workday poll writes one)")
    for c in companies:
        if "ats" in c:
            continue
        d = ats_slug.discover(c, opps)
        if d.ambiguous:
            out("ATS AMBIGUOUS %s: %s -- settle it with `record.py ats %s --url <the right board>`"
                % (c["id"], " | ".join("%s:%s" % (t[0], t[1]) for t in d.ambiguous), c["id"]))
        elif d.found:
            out("ATS FOUND %s %s:%s (%s) -- the next poll writes it" % (c["id"], d.found[0],
                                                                         d.found[1], d.source))
    unlinked = [ch for ch in channels if ch.get("type") == "company-site" and not ch.get("company_id")]
    for ch in unlinked:
        out("UNLINKED company-site channel %s -- link it with `record.py set %s company_id <company id> "
            "--file channels`" % (ch.get("id"), ch.get("id")))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Poll the public job-board feeds of tracked companies.")
    ap.add_argument("--run", metavar="RUN_ID")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--already-locked", action="store_true")
    ap.add_argument("--today", metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)
    if args.status:
        return status()
    if not args.run:
        ap.error("--run <run_id> is required (or --status)")
    return run(args.run, today=args.today, already_locked=args.already_locked, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
