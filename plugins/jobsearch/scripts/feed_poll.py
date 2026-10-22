#!/usr/bin/env python3
"""Poll the public job-board feeds of the companies the profile tracks (dev #751; design-sourcing-feeds.md).

    feed_poll.py --run <run_id> [--already-locked] [--dry-run] [--today YYYY-MM-DD]
    feed_poll.py --status                       # read-only: slugs, last outcome, ambiguities, unlinked channels

⭐ WHAT IT DOES. For each tracked company that carries `companies[].ats` (a Greenhouse, Lever or Ashby
board slug -- `ats_slug.py` finds it, from the candidate's OWN URLs), it makes ONE read-only GET of the
vendor's documented public list endpoint, keeps the postings whose title matches a configured
`targets.titles` entry (the screen's own matcher, `profile.title_matches`), and resolves each through
the SAME per-role resolver a sweep uses (`deferred._resolve_roles`, surface `feed`): a posting already in
the pipeline appends nothing, a new one becomes a `capture-role` item carrying the company-site channel it
came from. The daily run's existing claim -> `record.py create --from-item` -> `profile.py --minimal-screen`
path captures and screens it. There is no second de-duplication and no second screen.

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
import http.client
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import ats_slug
import journal as _journal

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
ENDPOINTS = {
    ("greenhouse", None): ("boards-api.greenhouse.io", "/v1/boards/%s/jobs"),
    ("lever", "global"): ("api.lever.co", "/v0/postings/%s"),
    ("lever", "eu"): ("api.eu.lever.co", "/v0/postings/%s"),
    ("ashby", None): ("api.ashbyhq.com", "/posting-api/job-board/%s"),
}
FEED_HOSTS = tuple(sorted({h for h, _p in ENDPOINTS.values()}))

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


# ---- the poll -------------------------------------------------------------------------------------

Outcome = collections.namedtuple(
    "Outcome", "company_id vendor slug status code postings unlisted total etag pages host")
# status: covered | unchanged | not-covered. `postings` are LISTED postings only; `total` counts every
# posting the feed showed (listed + unlisted); `etag` is None unless a single-page 200 sent one.


def _not_covered(co, ats, host, code):
    return Outcome(co["id"], ats["vendor"], ats["slug"], "not-covered", code, [], 0, 0, None, 0, host)


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


def poll(companies, fetch=default_fetch, clock=None, cache=None, deadline_s=DEADLINE_S, env=None):
    """`{company_id: Outcome}` (insertion-ordered) for each company in `companies` that carries an
    `ats` OBJECT -- and ONLY those (A1): a company with no `ats`, or `ats: null`, is never fetched.

    `fetch` and `clock` are injected (tests pass fakes; no sleeping, no socket). `cache` is
    `{"<vendor>:<region>:<slug>": {"etag", "pages", ...}}`. This function reads no store and writes
    none: resolution, stamping and the ETag write are `run`'s, after it. See the module docstring for
    the host-first rule, the deadline and the paging rule."""
    clock = clock or RealClock()
    cache = cache or {}
    env = os.environ if env is None else env
    start = clock.now()
    last_at, host_ok, host_down = {}, set(), {}
    outcomes = collections.OrderedDict()

    def spent():
        return clock.now() - start

    def get(host, url, etag):
        if spent() >= deadline_s:
            raise _Budget()
        wait = MIN_INTERVAL_S - (clock.now() - last_at[host]) if host in last_at else 0
        if wait > 0:
            if spent() + wait > deadline_s:
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

    for co in companies:
        ats = co.get("ats")
        if not isinstance(ats, dict) or co.get("status") == "passed":
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
    return outcomes


# ---- the run: discover, poll, resolve, stamp, journal ----------------------------------------------

def _load(name):
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


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
    import deferred as _deferred
    import profile as _profile
    from pipeline_index import canonical_job_url
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
    outcomes = poll(to_poll, fetch=fetch, clock=clock, cache=cache, deadline_s=deadline_s)
    # companies the deadline never reached are not silently absent: they are NOT COVERED
    for co in to_poll:
        if co["id"] not in outcomes:
            a = co["ats"]
            outcomes[co["id"]] = Outcome(co["id"], a["vendor"], a["slug"], "not-covered",
                                         "budget-exhausted", [], 0, 0, None, 0,
                                         ENDPOINTS[(a["vendor"], a.get("region")
                                                    if a["vendor"] == "lever" else None)][0])

    apps = _load("applications.jsonl")
    recs = _journal.read(ROOT)
    rows = _deferred.replay(_deferred.load())
    totals = {"captured": 0, "known": 0, "carried": 0, "role_gaps": 0, "quarantined": 0}
    postings_n = unlisted_n = selected_n = sightings = 0
    failures, not_covered_map, hosts_down = {}, {}, {}
    covered_n = unchanged_n = 0
    by_id = {c["id"]: c for c in to_poll}
    stamp_ids = []

    for cid, oc in outcomes.items():
        co = by_id[cid]
        if oc.status == "not-covered":
            failures[oc.code] = failures.get(oc.code, 0) + 1
            not_covered_map[cid] = oc.code
            if oc.code in _journal.FEED_HOST_CODES and oc.code != "budget-exhausted":
                hosts_down[oc.host] = oc.code
            continue
        covered_n += 1
        postings_n += oc.total
        unlisted_n += oc.unlisted
        channel = chan_of.get(cid)
        if oc.status == "unchanged":
            unchanged_n += 1
        else:
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
                    % (cid, len(roles)))
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
            if oc.etag:
                cache[key] = {"etag": oc.etag, "pages": max(oc.pages, 1), "at": run_date}
            else:
                cache.pop(key, None)
            _close_gaps(_journal.FEED_COMPANY_GAP_SCOPE % cid, out)
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
    chan_of = {c.get("company_id"): c.get("id") for c in channels if c.get("company_id")}
    slugged = [c for c in companies if isinstance(c.get("ats"), dict)]
    out("FEEDS — %d compan%s polled, %d declined (ats: null), %d with no slug"
        % (len(slugged), "y" if len(slugged) == 1 else "ies",
           sum(1 for c in companies if "ats" in c and c["ats"] is None),
           sum(1 for c in companies if "ats" not in c)))
    for c in slugged:
        a = c["ats"]
        last = "never polled"
        if ev is not None:
            code = (ev.get("companies_not_covered") or {}).get(c["id"])
            last = ("%s: NOT COVERED %s" % (str(ev.get("at"))[:10], code)) if code else \
                   ("%s: covered" % str(ev.get("at"))[:10])
        out("  %-24s %s:%s%s (%s) -> %s · %s" % (
            c["id"], a.get("vendor"), a.get("slug"), (" " + a["region"]) if a.get("region") else "",
            a.get("source"), chan_of.get(c["id"], "NO CHANNEL"), last))
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
