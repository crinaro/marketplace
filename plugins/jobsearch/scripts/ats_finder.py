#!/usr/bin/env python3
"""Find the job-board feed of a company the profile already tracks, and propose it (dev #770; docs/design-employer-discovery.md).

    ats_finder.py --resolve --attended [--limit N] [--company <id|name>] [--url <address>] [--run ID] [--today D]
    ats_finder.py --queue [--today D]            # NO network: the queue, the open proposals, the finder: line
    ats_finder.py --review                       # NO network: this machine's open proposals, numbered, with evidence
    ats_finder.py --decide <company_id>=accept|reject|skip [...] --attended [--run ID]    # writes through record.py only
    ats_finder.py --reconcile-ask [--today D]    # NO network: opens or resolves THIS cache's one ask
    ats_finder.py --reconcile-ask --attended --supersede <ask_id>

⭐ WHAT IT DOES. `feed_poll.py` polls a company only when `companies[].ats` is set, and `ats_slug.py` fills that
only by PARSING URLs the profile already holds. A company whose careers page is on its OWN domain, with the board
linked or embedded from that page, was therefore never polled. This script reads that ONE careers page (plus at most
one same-site link) of a TRACKED company, parses every board link on it with `ats_slug.parse`, confirms the slug with
the vendor's DOCUMENTED public list GET (and, for Greenhouse, its documented board-name GET), and records a PROPOSAL
in a per-machine cache (`.jobsearch/ats_finder.json`). It writes NOTHING to `companies[]`. The candidate accepts a
proposal with the existing `record.py ats <id> --url <board>` and rejects it with `record.py ats <id> --none`
(`ats: null`, which discovery never rewrites): there is no second writer and no rejection store.

⭐ ATTENDED ONLY. `--resolve` and `--decide` refuse (exit 3) without `--attended`; attended is never inferred, and
the only place that passes it is the explicit attended form of `/jobsearch:sourcing employers attended`. An employer
host is an arbitrary host, so the sandbox would prompt or refuse an unattended fetch, and a scheduled prompt is
not the candidate's consent (design A9, A10). `--queue`, `--review` and `--reconcile-ask` fetch nothing and are safe
in any run.

⭐ ONE GUARDED CHOKE POINT (design 3.2). Every request goes through `_guarded_get(ctx, url, kind)`, which calls
`feed_poll.default_fetch` (the only network code in the tree; here with `follow_redirects=False`). In this order,
before the request for that URL is made:

    G1  GET only, headers exactly `User-Agent` (an engine fault, an AssertionError, never a company outcome)
    G2  http/https, no user-info, no non-default port                                       refused-url
    G3  no path segment `embed`, on any host                                                 refused-url
    G4  never a vendor HTML host (`ats_slug._HOSTS`, `*.myworkdayjobs.com`): parsed, not fetched   refused-url
    G5  never a manual-candidate board host: the UNION the runtime guard builds
        (`guard_board_hosts.floor_channels()` + `profile_channels()`), FAILING CLOSED here     board-host
    G6  page and robots only on an EMPLOYER host (the career_url host, the domain and its
        sub-domains, or a host the candidate named with `--company --url`)                     refused-url
    G7  an API URL only if `feed_poll.list_url` / the Greenhouse board endpoint builds it;
        a robots URL only `/robots.txt`                                                        assertion
    G8  the host's robots.txt allows the path. robots.txt is ITSELF a guarded request (kind
        `robots`, the only I/O allowed for a host before its G8 decision)                      robots-disallowed / robots-unavailable

A redirect is never followed by the wire. A 3xx is returned and the hop is guarded again (G3, G6 and G8 run on the
target before it is requested), at most 2 hops, never across origins. Every accepted `Response` is asserted to have
`final_url == the URL asked`. Politeness is `feed_poll`'s, imported and never redefined: `MIN_INTERVAL_S` per host,
`TIMEOUT_S`, one `Retry-After` up to `RETRY_AFTER_CAP_S`, `DEADLINE_S` for the whole call.

⭐ G5 FAILS CLOSED. The runtime hook allows when its host set could not be read in full, because a hook that denies
wrongly stops a session. A fetch the engine starts itself has no such cost, so here a partial set means NO fetch:
`ATS FINDER NOT RUN: the blocked-host set could not be read (<code>)`, exit 3, nothing cached.

⭐ IDENTITY IS WHOLE-TOKEN WITH A MINIMUM LENGTH (design 3.4). Two names match when their token lists are equal, or when
the shorter list is a contiguous run of WHOLE tokens of the longer AND the shorter, joined, is at least
`IDENTITY_MIN_CHARS` (5) characters. "Ace" never matches "Ace Logistics Group"; "Robo" never matches "Roboworks".

⭐ NO BARE-NAME PROBE (owner ruling O1). A slug is never guessed from a company name; a company with no address on
file is `no-employer-url` and costs no request. The careers page MAY be read (O2): one page plus one same-site hop,
attended, every result accepted by the candidate.

⭐ GREEN IS NEVER UNCHECKED. A failing page or probe is a named UNRESOLVED code, never "zero roles"; a 200 with an empty
list is `api-empty`. When a host could not be reached from the session, ONE `ATS FINDER EGRESS` line says so, apart
from `no-board-link`. One `finder v1` journal `note` row per `--resolve` / `--decide` call (an existing event: a
new event name would make an older engine's `journal.read()` raise) and a `finder:` line make the finder's yield
measurable.

Exit codes: 0 done (or nothing to do); 1 a `--decide` pair was refused; 2 usage or an input that names nothing/many;
3 NOT RUN (unattended, blocked-host set unreadable, a store unreadable, the tracked fixture).

Python 3.9+. Standard library only.
"""

import argparse
import collections
import datetime
import hashlib
import html.parser
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _root import (profile_root as _profile_root, is_unbound as _is_unbound,
                   is_tracked_fixture as _is_tracked_fixture, looks_like_profile as _looks_like_profile)
import ats_slug
import board_hosts
import feed_poll
import guard_board_hosts
import journal as _journal
import pipeline_index

# ---- named constants (OURS unless a design section says otherwise) -----------------------------------------------
CACHE_VERSION = 1
DEFAULT_LIMIT = 5                 # companies read per attended call (about half a minute at 1 req/s/host)
RECHECK_DAYS = 30                 # a `days`-class unresolved code is retried after this many days
IDENTITY_MIN_CHARS = 5            # the shorter name, joined, must be at least this long to match inside a longer one
MAX_HOPS = 2                      # redirects followed on a page read, each one guarded again
ZERO_OVER_K = 4                   # zero proposals over this many page-reading attended calls prints the suspect line
NOTE_RUN_ID = "ats-finder"        # the run id of a finder note when the caller gave no `--run` (design U11: safe)
ASK_PREFIX = "ats-proposals-"
ASK_ID_RE = re.compile(r"^ats-proposals-(\d{4}-\d{2}-\d{2})-([0-9a-f]{8})$")
CACHE_ID_RE = re.compile(r"^[0-9a-f]{8}$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRACKED_STATUSES = ("active-target", "watching")
LINK_WORDS_RE = re.compile(r"careers|jobs|join-us|work-with-us", re.I)
LEGAL_FORM_TOKENS = frozenset(("inc", "llc", "ltd", "gmbh", "corp", "co", "company", "plc", "sa", "ag", "bv"))
KINDS = ("robots", "page", "api")
SUPERSEDE_RESOLUTION = "superseded: its finder cache is gone; proposals are re-found by --resolve"
ASK_TITLE = "Job-board feeds found for companies you track"

# The finder's own unresolved codes. Every `journal.FEED_FAILURES` code is imported, never redefined, and a test
# asserts the two sets are disjoint (design 3.4).
OWN_CODES = ("no-employer-url", "refused-url", "board-host", "no-board-link", "ambiguous", "api-empty",
             "identity-mismatch")
CODES = ("proposed",) + OWN_CODES + tuple(_journal.FEED_FAILURES)
# Recheck classes (design 3.4). `inputs`: retried only when the company's URLs change. `host`: retried on the next
# attended call. Everything else is `days`: retried after RECHECK_DAYS.
INPUT_CODES = ("no-employer-url", "refused-url", "board-host", "ambiguous", "identity-mismatch")
HOST_CODES = tuple(_journal.FEED_HOST_CODES)
EGRESS_CODES = ("egress-blocked", "timeout")
if set(OWN_CODES) & set(_journal.FEED_FAILURES):          # an engine fault, caught at import
    raise AssertionError("ats_finder.OWN_CODES collide with journal.FEED_FAILURES: %s"
                         % sorted(set(OWN_CODES) & set(_journal.FEED_FAILURES)))


class Unresolved(Exception):
    """A company outcome: `code` is in `CODES`, `detail` free text for the candidate."""

    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s %s" % (code, detail))
        self.code, self.detail = code, detail


class EngineFault(AssertionError):
    """A guard that can only trip through a programming error (G1, G7, a redirect followed outside the guard)."""


class StoreError(Exception):
    """A profile file the finder needs could not be read (a missing store is not an empty one)."""


class FinderNoteError(ValueError):
    """A `finder v1` journal note that does not parse: loud, never skipped."""


# ---- reading the profile ------------------------------------------------------------------------------------------

def _load_store(root, name, required=True):
    path = os.path.join(root, "data", name + ".jsonl")
    if not os.path.exists(path):
        if required:
            raise StoreError("data/%s.jsonl is missing" % name)
        return []
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    raise StoreError("data/%s.jsonl line %d is not JSON" % (name, n))
                if not isinstance(row, dict):
                    raise StoreError("data/%s.jsonl line %d is not an object" % (name, n))
                rows.append(row)
    except (OSError, UnicodeDecodeError) as e:
        raise StoreError("data/%s.jsonl could not be read (%s)" % (name, e))
    return rows


def _load_profile(root):
    """`(companies, opportunities)`, strict. A company store that is missing or has a bad line is `StoreError`."""
    return _load_store(root, "companies"), _load_store(root, "opportunities", required=False)


# ---- employer hosts and the start page ---------------------------------------------------------------------------

def _bare_domain(value):
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().lower()
    if "://" in v:
        v = board_hosts.host_of(v) or ""
    v = v.rstrip(".")
    return v if board_hosts.valid_host(v) else None


class EmployerHosts(object):
    """The hosts a company's own pages may be read on (design 3.3): the host of its `career_url`, its `domain`
    and any sub-domain of it, and a host the candidate named for it on the command line. Nothing else qualifies."""

    def __init__(self, exact=(), domains=()):
        self.exact = set(h for h in exact if h)
        self.domains = set(d for d in domains if d)

    @classmethod
    def for_company(cls, company, extra=()):
        exact = [board_hosts.host_of(company.get("career_url"))] + [h for h in extra]
        return cls(exact, [_bare_domain(company.get("domain"))])

    def matches(self, host):
        h = (host or "").lower().rstrip(".")
        if not h:
            return False
        return h in self.exact or any(h == d or h.endswith("." + d) for d in self.domains)


def employer_urls(company, opportunities, emp):
    """Every address the profile holds for this company that sits on an employer host, in the profile's order."""
    out = []
    for url, _origin in ats_slug.candidate_urls(company, opportunities):
        if isinstance(url, str) and url.strip() and emp.matches(board_hosts.host_of(url)) and url.strip() not in out:
            out.append(url.strip())
    return out


def fingerprint(company, opportunities):
    """12 hex digits over the sorted employer-host URLs, `career_url` and `domain`: a change to any of them
    invalidates a cached outcome (design 4.2)."""
    emp = EmployerHosts.for_company(company)
    material = json.dumps([sorted(employer_urls(company, opportunities, emp)),
                           company.get("career_url") or "", company.get("domain") or ""], sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def pick_start(company, opportunities, emp):
    """The company's start page (design 3.3), or None (`no-employer-url`, which costs no request): `career_url`;
    else a `jd_url` or sighting address on an employer host; else `https://<domain>/`."""
    cu = company.get("career_url")
    if isinstance(cu, str) and board_hosts.host_of(cu):
        return cu.strip()
    urls = employer_urls(company, opportunities, emp)
    if urls:
        return urls[0]
    dom = _bare_domain(company.get("domain"))
    return "https://%s/" % dom if dom else None


def third_party_hosts(company, opportunities, emp):
    """The hosts of the company's addresses that are NOT employer hosts (hints for `--review`: never fetched)."""
    hosts = []
    for url, _origin in ats_slug.candidate_urls(company, opportunities):
        h = board_hosts.host_of(url)
        if h and not emp.matches(h) and h not in hosts:
            hosts.append(h)
    return hosts


# ---- identity (design 3.4) ----------------------------------------------------------------------------------------

def name_tokens(name):
    """Case-folded alphanumeric tokens, trailing legal-form tokens dropped (never down to nothing)."""
    toks = [t for t in re.split(r"[^0-9a-z]+", str(name or "").casefold()) if t]
    while len(toks) > 1 and toks[-1] in LEGAL_FORM_TOKENS:
        toks.pop()
    return toks


def names_match(a, b):
    """Whole-token identity: equal token lists, or the shorter a contiguous run of whole tokens of the longer AND at
    least `IDENTITY_MIN_CHARS` characters joined. Below that only equality matches."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len("".join(short)) < IDENTITY_MIN_CHARS:
        return False
    n = len(short)
    return any(long_[i:i + n] == short for i in range(len(long_) - n + 1))


# ---- the guarded choke point --------------------------------------------------------------------------------------

class _Ctx(object):
    """One call's state: the injected fetch and clock, the blocked-host set, the employer hosts of the company being
    read, each host's robots decision, hosts that went down, and the egress tally."""

    def __init__(self, fetch, clock, channels):
        self.fetch = fetch
        self.clock = clock
        self.channels = channels
        self.emp = EmployerHosts()
        self.start = clock.now()
        self.last_at = {}
        self.robots = {}            # host -> ("rules", rules) | ("fail", code, detail)
        self.host_down = {}         # host -> code
        self.host_ok = set()
        self.egress = {}            # host -> code, for robots/page requests only
        self.requests = []          # (kind, url) in order, for the egress summary and tests
        self.env = os.environ

    def spent(self):
        return self.clock.now() - self.start


def _vendor_html_host(host):
    return host in ats_slug._HOSTS or host.endswith(ats_slug.WD_SUFFIX)


def _api_slug_ok(url):
    """True when `url` is exactly an address `feed_poll.list_url` builds (any vendor but Workday), or exactly the
    Greenhouse board-name endpoint: nothing else on an API host (G7)."""
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.fragment:
        return False
    slug_re = r"([A-Za-z0-9][A-Za-z0-9._-]{0,99})"
    for (vendor, region), (host, path) in feed_poll.ENDPOINTS.items():
        if vendor == "workday" or host != (p.hostname or "").lower():
            continue
        m = re.match("^" + re.escape(path).replace("%s", slug_re) + "$", p.path)
        if m and url in (feed_poll.list_url(vendor, region, m.group(1), 0, 1),
                         feed_poll.list_url(vendor, region, m.group(1))):
            return True
    host, path = feed_poll.GREENHOUSE_BOARD_ENDPOINT
    m = re.match("^" + re.escape(path).replace("%s", slug_re) + "$", p.path)
    return bool(m and (p.hostname or "").lower() == host and not p.query and not p.port
                and url == "https://%s%s" % (host, path % m.group(1)))


def _guarded_get(ctx, url, kind, method="GET", headers=None):
    """THE choke point (G1-G8, module docstring). Returns the `feed_poll.Response`, or raises `Unresolved` (a company
    outcome) or `EngineFault`. A URL a guard refuses is never requested."""
    if method != "GET":
        raise EngineFault("G1: method %r (GET only)" % (method,))
    wanted = {"User-Agent": feed_poll.USER_AGENT}
    if headers is not None and dict(headers) != wanted:
        raise EngineFault("G1: headers %s (exactly User-Agent)" % sorted(headers))
    if kind not in KINDS:
        raise EngineFault("unknown request kind %r" % (kind,))
    try:
        parts = urllib.parse.urlsplit(url)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        raise Unresolved("refused-url", "unreadable address")
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc \
            or port not in (None, {"http": 80, "https": 443}[parts.scheme]):
        raise Unresolved("refused-url", "scheme, user-info or port: %s" % url[:120])                    # G2
    segs = [urllib.parse.unquote(s).casefold() for s in parts.path.split("/")]
    if "embed" in segs:
        raise Unresolved("refused-url", "an /embed/ address is never requested: %s" % url[:120])         # G3
    if kind in ("robots", "page"):
        if _vendor_html_host(host):
            raise Unresolved("refused-url", "%s is a vendor page: parsed, never fetched" % host)         # G4
        blocked = board_hosts.blocked_channel(url, ctx.channels)
        if blocked is not None:
            raise Unresolved("board-host", "%s is the manual-candidate board %s (ADR-037)"
                             % (host, blocked.get("id") or blocked.get("channel_id") or "?"))            # G5
        if not ctx.emp.matches(host):
            raise Unresolved("refused-url", "%s is not an employer host of this company" % host)         # G6
    if kind == "api" and not _api_slug_ok(url):
        raise EngineFault("G7: %s is not an address feed_poll builds" % url[:120])
    if kind == "robots" and (parts.path != "/robots.txt" or parts.query):
        raise EngineFault("G7: a robots request is exactly /robots.txt, got %s" % url[:120])
    if host in ctx.host_down:
        raise Unresolved(ctx.host_down[host], "host %s already failed in this call" % host)
    if kind == "page":                                                                                    # G8
        _robots_gate(ctx, parts, host)
    return _send(ctx, url, host, kind)


def _robots_gate(ctx, parts, host):
    got = ctx.robots.get(host)
    if got is None:
        try:
            resp = _guarded_get(ctx, "%s://%s/robots.txt" % (parts.scheme, host), "robots")
        except Unresolved as u:
            ctx.robots[host] = ("fail", u.code, u.detail)
            raise
        if resp.status == 200 and not feed_poll._looks_like_html(resp.body):
            text = resp.body[:feed_poll.ROBOTS_PARSE_LIMIT].decode("utf-8", "replace")
            groups, _sitemaps = feed_poll.parse_robots(text)
            got = ("rules", feed_poll.robots_rules_for(groups, feed_poll.ROBOTS_PRODUCT_TOKEN))
        elif 400 <= resp.status < 500:
            got = ("rules", [])                       # RFC 9309: 4xx means the crawler MAY access any resource
        else:
            got = ("fail", "robots-unavailable", "robots.txt answered %d (%s)"
                   % (resp.status, "an HTML page" if resp.status == 200 else "not a usable file"))
        ctx.robots[host] = got
    if got[0] == "fail":
        raise Unresolved(got[1], got[2])
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    if not feed_poll.robots_allows(got[1], path):
        raise Unresolved("robots-disallowed", "robots.txt on %s disallows %s" % (host, path[:120]))


def _mark_down(ctx, host, code, kind):
    ctx.host_down[host] = code
    if kind in ("robots", "page") and code in EGRESS_CODES:
        ctx.egress[host] = code


def _send(ctx, url, host, kind):
    """The request itself: the deadline, the per-host interval, one capped `Retry-After`, the transport failures."""
    def one():
        if ctx.spent() >= feed_poll.DEADLINE_S:
            raise Unresolved("budget-exhausted", "the call's %d s deadline is spent" % feed_poll.DEADLINE_S)
        wait = feed_poll.MIN_INTERVAL_S - (ctx.clock.now() - ctx.last_at[host]) if host in ctx.last_at else 0
        if wait > 0:
            if ctx.spent() + wait > feed_poll.DEADLINE_S:
                raise Unresolved("budget-exhausted", "the call's deadline would pass first")
            ctx.clock.sleep(wait)
        ctx.last_at[host] = ctx.clock.now()
        ctx.requests.append((kind, url))
        try:
            resp = ctx.fetch(feed_poll.Request("GET", url, {"User-Agent": feed_poll.USER_AGENT},
                                               feed_poll.TIMEOUT_S))
        except feed_poll.FetchError as fe:
            if fe.code in ("redirected",):
                raise Unresolved(fe.code, fe.detail)
            _mark_down(ctx, host, fe.code, kind)
            raise Unresolved(fe.code, fe.detail)
        if resp.final_url != url:
            raise EngineFault("a redirect was followed outside the guard: asked %s, answered %s"
                              % (url, resp.final_url))
        return resp

    resp = one()
    if resp.status in (429, 503):
        wait = feed_poll.parse_retry_after(resp.headers.get("retry-after"))
        if wait is not None and wait <= feed_poll.RETRY_AFTER_CAP_S and ctx.spent() + wait <= feed_poll.DEADLINE_S:
            ctx.clock.sleep(wait)
            resp = one()
        if resp.status in (429, 503):
            _mark_down(ctx, host, "rate-limited", kind)
            raise Unresolved("rate-limited", "%s answered %d" % (host, resp.status))
    if resp.status == 403 and host not in ctx.host_ok and feed_poll._proxy_is_local(ctx.env):
        _mark_down(ctx, host, "egress-blocked", kind)                 # a 403 that may be the sandbox proxy refusing
        raise Unresolved("egress-blocked", "%s answered 403 through a local proxy" % host)
    ctx.host_ok.add(host)
    return resp


def _failure_code(status):
    """The `journal.FEED_FAILURES` code of a status that is not 200 (redirects included)."""
    if 300 <= status < 400:
        return "redirected"
    if status == 404:
        return "not-found"
    if status in (401, 403):
        return "auth-required"
    return "http-error"


# ---- reading a careers page ---------------------------------------------------------------------------------------

class _PageCollector(html.parser.HTMLParser):
    """Every `a[href]`, `iframe[src]`, `script[src]` and `link[href]` in document order, the text of each anchor, and the
    JSON-LD blocks (the standard library's `html.parser`, design A14; no regex over markup)."""

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.refs = []                    # every address, document order
        self.anchors = []                 # (href, text)
        self.ld = []
        self._a = None
        self._ld = None

    def _close_anchor(self):
        if self._a is not None:
            self.anchors.append((self._a[0], " ".join("".join(self._a[1]).split())))
            self._a = None

    def handle_starttag(self, tag, attrs):
        d = dict((k.lower(), v or "") for k, v in attrs)
        if tag == "a" and d.get("href", "").strip():
            self._close_anchor()
            self._a = [d["href"].strip(), []]
            self.refs.append(d["href"].strip())
        elif tag in ("iframe", "script") and d.get("src", "").strip():
            self.refs.append(d["src"].strip())
        elif tag == "link" and d.get("href", "").strip():
            self.refs.append(d["href"].strip())
        elif tag == "script" and d.get("type", "").split(";")[0].strip().lower() == "application/ld+json":
            self._ld = []

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
        elif self._a is not None:
            self._a[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self._close_anchor()
        elif tag == "script" and self._ld is not None:
            self.ld.append("".join(self._ld))
            self._ld = None

    def finish(self):
        self.close()
        self._close_anchor()


def _hiring_org(blocks):
    """The first JSON-LD `hiringOrganization.name` (schema.org JobPosting, design A6): evidence only."""
    def walk(node):
        if isinstance(node, dict):
            org = node.get("hiringOrganization")
            if isinstance(org, dict) and isinstance(org.get("name"), str) and org["name"].strip():
                return org["name"].strip()
            if isinstance(org, str) and org.strip():
                return org.strip()
            for v in node.values():
                got = walk(v)
                if got:
                    return got
        elif isinstance(node, list):
            for v in node:
                got = walk(v)
                if got:
                    return got
        return None
    for text in blocks:
        try:
            got = walk(json.loads(text))
        except ValueError:
            continue
        if got:
            return got
    return None


def _join(base, ref):
    try:
        u, _frag = urllib.parse.urldefrag(urllib.parse.urljoin(base, ref))
    except ValueError:
        return None
    return u if u.lower().startswith(("http://", "https://")) else None


def parse_page(page_url, text, emp):
    """`(boards, hop, hiring_org)`. `boards` is `[(triple, board_url)]`, distinct case-insensitively on the slug, each
    with the address as the page gave it (resolved against the page); `hop` is the first anchor in document order
    that resolves to an employer host and whose path or text names careers/jobs/join-us/work-with-us."""
    col = _PageCollector()
    try:
        col.feed(text)
        col.finish()
    except Exception as e:                                       # noqa: BLE001 - html.parser on hostile markup
        raise Unresolved("unparseable", "the page could not be parsed (%s)" % type(e).__name__)
    seen = collections.OrderedDict()
    for ref in col.refs:
        u = _join(page_url, ref)
        triple = ats_slug.parse(u) if u else None
        if triple is not None:
            seen.setdefault((triple[0], triple[1].lower(), triple[2]), (triple, u))
    hop = None
    for href, label in col.anchors:
        u = _join(page_url, href)
        if not u or u == page_url or not emp.matches(board_hosts.host_of(u)):
            continue
        if LINK_WORDS_RE.search(urllib.parse.urlsplit(u).path) or LINK_WORDS_RE.search(label):
            hop = u
            break
    return list(seen.values()), hop, _hiring_org(col.ld)


def _read_page(ctx, url):
    """`(final_url, text)` of one page, following at most `MAX_HOPS` same-origin redirects, each guarded again
    (G3, G6 and G8 run on the target before it is requested)."""
    hops = 0
    while True:
        resp = _guarded_get(ctx, url, "page")
        if 300 <= resp.status < 400:
            loc = (resp.headers.get("location") or "").strip()
            target = _join(url, loc) if loc else None
            if target is None:
                raise Unresolved("redirected", "a redirect with no usable Location")
            if feed_poll._origin(target) != feed_poll._origin(url):
                raise Unresolved("redirected", "to %s (set career_url to the address you reach)" % target[:200])
            hops += 1
            if hops > MAX_HOPS:
                raise Unresolved("redirected", "more than %d redirects (last to %s)" % (MAX_HOPS, target[:200]))
            url = target
            continue
        if resp.status != 200:
            raise Unresolved(_failure_code(resp.status), "%s answered %d" % (url[:120], resp.status))
        if len(resp.body) > feed_poll.MAX_BODY:
            raise Unresolved("unparseable", "the page is larger than %d bytes" % feed_poll.MAX_BODY)
        return url, resp.body.decode("utf-8", "replace")


# ---- from a parsed board to a proposal (design 3.4) ----------------------------------------------------------------

def _api_ok(resp, ctx, host, url):
    if resp.status == 200:
        return
    raise Unresolved(_failure_code(resp.status), "%s answered %d" % (url[:140], resp.status))


def probe_board(ctx, triple, company):
    """`(probe, identity)` for one parsed board, or `Unresolved`. Workday has no list API (its robots and sitemap
    belong to `feed_poll.py`'s first poll). An empty list is `api-empty`, never zero roles."""
    vendor, slug, region = triple
    if vendor == "workday":
        return None, {"checked": None, "reason": "not documented"}
    url = feed_poll.list_url(vendor, region, slug, 0, 1)
    host = feed_poll.ENDPOINTS[(vendor, region if vendor == "lever" else None)][0]
    resp = _guarded_get(ctx, url, "api")
    _api_ok(resp, ctx, host, url)
    try:
        postings, unlisted = feed_poll.PARSERS[vendor](resp.body)
    except feed_poll.Unparseable as e:
        raise Unresolved("unparseable", "the %s list is not the documented shape (%s)" % (vendor, e))
    count = len(postings) + unlisted
    if count == 0:
        raise Unresolved("api-empty", "%s:%s answered 200 with an empty list: an empty board carries no evidence "
                                      "of whose it is" % (vendor, slug))
    probe = {"url": url, "status": 200, "count": count}
    if vendor != "greenhouse":
        return probe, {"checked": None, "reason": "not documented"}
    ghost, gpath = feed_poll.GREENHOUSE_BOARD_ENDPOINT
    burl = "https://%s%s" % (ghost, gpath % slug)
    bresp = _guarded_get(ctx, burl, "api")
    _api_ok(bresp, ctx, ghost, burl)
    try:
        data = json.loads(bresp.body.decode("utf-8"))
        board_name = data.get("name") if isinstance(data, dict) else None
    except (ValueError, UnicodeDecodeError):
        board_name = None
    if not isinstance(board_name, str) or not board_name.strip():
        raise Unresolved("unparseable", "the Greenhouse board answered without a name")
    for mine in [company.get("name")] + list(company.get("aliases") or []):
        if isinstance(mine, str) and names_match(mine, board_name):
            return probe, {"checked": board_name.strip(), "reason": "matched %s" % mine.strip()}
    raise Unresolved("identity-mismatch", "the board %s:%s is named %r, not %r"
                     % (vendor, slug, board_name.strip(), company.get("name")))


def resolve_company(ctx, company, opportunities, today, start_url=None, extra_hosts=()):
    """`(entry, pages_read)`: the cache entry for one company, after reading its careers page (and at most one
    same-site hop) and probing the one board it names. Never raises `Unresolved`: that is the entry's `code`."""
    ctx.emp = EmployerHosts.for_company(company, extra_hosts)
    entry = {"checked_on": today, "inputs": fingerprint(company, opportunities), "outcome": "unresolved"}
    pages = 0
    start = start_url or pick_start(company, opportunities, ctx.emp)
    if not start:
        entry.update(code="no-employer-url", detail="no address on file for this company")
        return entry, pages
    try:
        page_url, text = _read_page(ctx, start)
        pages += 1
        boards, hop, org = parse_page(page_url, text, ctx.emp)
        evidence = page_url
        if not boards and hop:
            page_url, text = _read_page(ctx, hop)
            pages += 1
            boards, _hop2, org2 = parse_page(page_url, text, ctx.emp)
            evidence, org = page_url, org or org2
        if not boards:
            raise Unresolved("no-board-link", "no Greenhouse, Lever, Ashby or Workday link on %s%s"
                             % (evidence[:120], "" if hop else " (and no careers link to follow)"))
        if len(boards) > 1:
            raise Unresolved("ambiguous", " | ".join("%s:%s" % (t[0], t[1]) for t, _u in boards))
        triple, board_url = boards[0]
        probe, identity = probe_board(ctx, triple, company)
    except Unresolved as u:
        entry.update(code=u.code, detail=(u.detail or "")[:300])
        return entry, pages
    entry.update(outcome="proposed", code="proposed", board_url=board_url, key=list(triple), evidence_url=evidence,
                 probe=probe, identity=identity, hiring_org=org)
    return entry, pages


# ---- the cache: proposals and recent outcomes, one per machine (design 4.2) --------------------------------------------

def cache_path(root):
    return os.path.join(root, ".jobsearch", "ats_finder.json")


def _check_entry(cid, e):
    """Why a cache entry is not sound, or None."""
    if not isinstance(e, dict):
        return "company %s: not an object" % cid
    if not (isinstance(e.get("checked_on"), str) and ISO_DATE_RE.match(e["checked_on"])):
        return "company %s: checked_on is not a date" % cid
    if not (isinstance(e.get("inputs"), str) and FINGERPRINT_RE.match(e["inputs"])):
        return "company %s: inputs is not 12 hex digits" % cid
    if e.get("outcome") not in ("proposed", "unresolved") or e.get("code") not in CODES:
        return "company %s: outcome/code %r/%r" % (cid, e.get("outcome"), e.get("code"))
    if (e["outcome"] == "proposed") != (e["code"] == "proposed"):
        return "company %s: outcome and code disagree" % cid
    if e["outcome"] == "unresolved":
        return None if isinstance(e.get("detail", ""), str) else "company %s: detail is not text" % cid
    for k, kinds in (("board_url", str), ("evidence_url", str), ("key", list), ("identity", dict)):
        if not isinstance(e.get(k), kinds):
            return "company %s: %s is missing or the wrong type" % (cid, k)
    if e.get("probe") is not None and not (isinstance(e["probe"], dict) and isinstance(e["probe"].get("url"), str)):
        return "company %s: probe is neither null nor an object" % cid
    if not (isinstance(e["identity"].get("reason"), str) and "checked" in e["identity"]):
        return "company %s: identity lacks checked/reason" % cid
    if e.get("hiring_org") is not None and not isinstance(e["hiring_org"], str):
        return "company %s: hiring_org is not text" % cid
    if len(e["key"]) != 3 or ats_slug.parse(e["board_url"]) is None or list(ats_slug.parse(e["board_url"])) != e["key"]:
        return "company %s: key differs from what ats_slug.parse reads off board_url" % cid
    try:
        problems = ats_slug.check_ats(ats_slug.ats_object(tuple(e["key"]), "candidate", "2026-01-01"))
    except (ValueError, TypeError) as err:
        problems = [str(err)]
    return "company %s: key does not build a sound ats object (%s)" % (cid, problems[0]) if problems else None


def read_cache(root):
    """`("absent", None)`, `("ok", doc)` or `("unreadable", why)`. Strict: a wrong version, unparseable JSON, a missing
    or malformed `cache_id`, or an unsound entry is unreadable, never an empty cache."""
    path = cache_path(root)
    if not os.path.exists(path):
        return "absent", None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return "unreadable", "not readable JSON (%s)" % type(e).__name__
    if not isinstance(doc, dict) or doc.get("version") != CACHE_VERSION:
        return "unreadable", "version is not %d" % CACHE_VERSION
    if not (isinstance(doc.get("cache_id"), str) and CACHE_ID_RE.match(doc["cache_id"])):
        return "unreadable", "cache_id is missing or malformed"
    if not isinstance(doc.get("companies"), dict):
        return "unreadable", "companies is not an object"
    for cid in sorted(doc["companies"]):
        why = _check_entry(cid, doc["companies"][cid])
        if why:
            return "unreadable", why
    return "ok", doc


def write_cache(root, doc):
    path = cache_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def new_cache():
    return {"version": CACHE_VERSION, "cache_id": os.urandom(4).hex(), "companies": {}}


def keep_unreadable(root):
    """Rename an unreadable cache aside (kept for diagnosis); the next write gets a new `cache_id`. Returns the new name."""
    path = cache_path(root)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    dest, n = "%s.unreadable-%s" % (path, stamp), 1
    while os.path.exists(dest):
        n += 1
        dest = "%s.unreadable-%s-%d" % (path, stamp, n)
    os.replace(path, dest)
    return dest


# ---- the queue: derived each call, never stored (design 4.1) -----------------------------------------------------------

def latest_sighting(company_id, opportunities):
    best = ""
    for o in opportunities:
        if o.get("company_id") != company_id:
            continue
        for s in o.get("sightings") or []:
            if isinstance(s, dict) and isinstance(s.get("seen_on"), str):
                best = max(best, s["seen_on"])
    return best


def retry_due(entry, fingerprint_now, today):
    """Should this company be read again? (design 3.4: `inputs` codes only when the URLs change; `host` codes on the
    next attended call; the rest after RECHECK_DAYS.) A proposed entry with an unchanged fingerprint is kept."""
    if entry["inputs"] != fingerprint_now:
        return True
    if entry["outcome"] == "proposed":
        return False
    code = entry["code"]
    if code in INPUT_CODES:
        return False
    if code in HOST_CODES:
        return True
    due = datetime.date.fromisoformat(entry["checked_on"]) + datetime.timedelta(days=RECHECK_DAYS)
    return today >= due


def eligible(company, opportunities):
    """Why a company may not be queued, or None. `ats` ABSENT only: `null` is a remembered rejection and an object is
    already polled. A board its own URLs name is `feed_poll.discover_all`'s (found) or the candidate's (ambiguous)."""
    if company.get("status") not in TRACKED_STATUSES:
        return "status is %s" % (company.get("status") or "not set")
    if "ats" in company:
        return "ats is %s" % ("declined (null)" if company["ats"] is None else "already set")
    d = ats_slug.discover(company, opportunities)
    if d.found is not None:
        return "its own addresses already name a board (feed_poll discovers it)"
    if d.ambiguous:
        return "its own addresses name two boards (settle it with record.py ats)"
    return None


def build_queue(companies, opportunities, cache_doc, today):
    """The queued companies, newest sighting first then id: `[{id, name, start, sighted}]`. `start` None means
    `no-employer-url` (queued, never fetched)."""
    entries = (cache_doc or {}).get("companies", {})
    out = []
    for co in companies:
        if not co.get("id") or eligible(co, opportunities):
            continue
        entry = entries.get(co["id"])
        if entry is not None and not retry_due(entry, fingerprint(co, opportunities), today):
            continue
        emp = EmployerHosts.for_company(co)
        out.append({"id": co["id"], "name": co.get("name") or co["id"],
                    "start": pick_start(co, opportunities, emp),
                    "sighted": latest_sighting(co["id"], opportunities)})
    out.sort(key=lambda q: q["id"])
    out.sort(key=lambda q: q["sighted"], reverse=True)
    return out


def valid_proposals(cache_doc, companies, opportunities):
    """`(valid, stale)` id lists: a proposal is valid while the company's `ats` is still absent and its fingerprint is
    unchanged (design 4.3)."""
    by_id = dict((c.get("id"), c) for c in companies)
    valid, stale = [], []
    for cid, e in sorted((cache_doc or {}).get("companies", {}).items()):
        if e["outcome"] != "proposed":
            continue
        co = by_id.get(cid)
        if co is not None and "ats" not in co and e["inputs"] == fingerprint(co, opportunities):
            valid.append(cid)
        else:
            stale.append(cid)
    return valid, stale


# ---- telemetry: a versioned note, a strict parser, one line (design 4.6) ----------------------------------------------

_RESOLVE_NOTE = re.compile(r"^finder v1 resolve queued=(\d+) read=(\d+) proposed=(\d+) "
                           r"unresolved=(-|[a-z][a-z-]*:\d+(?:,[a-z][a-z-]*:\d+)*) egress=(\d+)$")
_DECIDE_NOTE = re.compile(r"^finder v1 decide accepted=(\d+) rejected=(\d+) skipped=(\d+)$")


def resolve_note(queued, read, proposed, unresolved, egress):
    pairs = ",".join("%s:%d" % (c, n) for c, n in sorted(unresolved.items())) or "-"
    return "finder v1 resolve queued=%d read=%d proposed=%d unresolved=%s egress=%d" % (
        queued, read, proposed, pairs, egress)


def decide_note(accepted, rejected, skipped):
    return "finder v1 decide accepted=%d rejected=%d skipped=%d" % (accepted, rejected, skipped)


def parse_finder_note(text):
    """The counts a `finder v1` note carries, strictly. Anything that starts `finder v1` and is not exactly the
    grammar raises `FinderNoteError` (an unparseable fact is loud, never skipped)."""
    m = _RESOLVE_NOTE.match(text)
    if m:
        unresolved = {}
        if m.group(4) != "-":
            for pair in m.group(4).split(","):
                code, n = pair.split(":")
                if code not in CODES or code == "proposed":
                    raise FinderNoteError("finder note names an unknown code %r: %s" % (code, text))
                unresolved[code] = unresolved.get(code, 0) + int(n)
        return {"kind": "resolve", "queued": int(m.group(1)), "read": int(m.group(2)),
                "proposed": int(m.group(3)), "unresolved": unresolved, "egress": int(m.group(5))}
    m = _DECIDE_NOTE.match(text)
    if m:
        return {"kind": "decide", "accepted": int(m.group(1)), "rejected": int(m.group(2)),
                "skipped": int(m.group(3))}
    raise FinderNoteError("a note starting 'finder v1' does not parse: %r" % text[:160])


def write_note(root, text, run_id):
    """Append the note row; a failure is printed by the caller, never swallowed."""
    _journal.append(root, {"event": "note", "run_id": run_id or NOTE_RUN_ID, "text": text,
                           "at": _journal.now_iso()})


def read_notes(root):
    """The parsed `finder v1` notes, oldest first. `JournalError` from `journal.read` and `FinderNoteError` propagate."""
    return [parse_finder_note(r["text"]) for r in _journal.read(root)
            if r.get("event") == "note" and isinstance(r.get("text"), str) and r["text"].startswith("finder v1")]


def finder_line(notes, queued, open_proposals):
    resolves = [n for n in notes if n["kind"] == "resolve"]
    decides = [n for n in notes if n["kind"] == "decide"]
    reading = [n for n in resolves if n["read"] >= 1][-ZERO_OVER_K:]
    if len(reading) == ZERO_OVER_K and sum(n["proposed"] for n in reading) == 0:
        return ("finder: 0 proposed over %d attended calls that read pages: suspect the finder (parser or page "
                "forms) before the employers" % ZERO_OVER_K)
    last = resolves[-ZERO_OVER_K:]
    by_code = collections.Counter()
    for n in last:
        by_code.update(n["unresolved"])
    line = "finder: queued %d, proposed %d open" % (queued, open_proposals)
    if last:
        line += ", last %d attended call%s read %d and proposed %d" % (
            len(last), "" if len(last) == 1 else "s", sum(n["read"] for n in last), sum(n["proposed"] for n in last))
        line += "; unresolved by code %s" % (",".join("%s:%d" % (c, n) for c, n in sorted(by_code.items())) or "none")
    else:
        line += ", no attended call yet"
    if decides:
        line += "; decided so far: accepted %d, rejected %d, skipped %d" % (
            sum(n["accepted"] for n in decides), sum(n["rejected"] for n in decides),
            sum(n["skipped"] for n in decides))
    return line


# ---- the one ask (design 4.3) ---------------------------------------------------------------------------------------

def _record_py(root, *args):
    """Run `record.py` against `root`: `(returncode, text)`. The only writer of `companies` and `asks` here."""
    env = dict(os.environ, CLAUDESEARCH_ROOT=root, CLAUDESEARCH_DATA_DIR=os.path.join(root, "data"))
    r = subprocess.run([sys.executable, os.path.join(HERE, "record.py")] + list(args),
                       capture_output=True, text=True, timeout=180, env=env, cwd=root)
    return r.returncode, " ".join(((r.stdout or "") + " " + (r.stderr or "")).split())


def _host_name():
    import whoami
    return whoami.worker_id({}).partition(":")[2] or "this machine"


def open_proposal_asks(root):
    return [a for a in _load_store(root, "asks", required=False)
            if str(a.get("id") or "").startswith(ASK_PREFIX) and not a.get("resolved_on")]


def _resolve_ask(root, ask_id, resolution, today):
    """Resolve an ask: `resolution` first, then `resolved_on`, because the validator refuses a `resolved_on` that has
    no `resolution` and each `record.py set` is its own validated write."""
    for field, value in (("resolution", resolution), ("resolved_on", today)):
        rc, text = _record_py(root, "set", ask_id, field, value, "--file", "asks")
        if rc != 0:
            return False, "record.py set %s exited %d: %s" % (field, rc, text[:200])
    return True, ""


def _ask_cache_id(ask_id):
    """The `cache_id` an ask id names (strict pattern), or None."""
    m = ASK_ID_RE.match(ask_id or "")
    return m.group(2) if m else None


def left_open_line(ask_id, why):
    return ("ATS PROPOSALS ASK %s LEFT OPEN: %s. Proposals are decided on the machine that found them." % (ask_id, why))


def reconcile(root, today, out, attended=False, supersede=None):
    """Open or resolve THIS cache's ask; never resolve from a cache that cannot vouch for it. Returns an exit code."""
    iso = today.isoformat()
    if supersede is not None:
        return _supersede(root, supersede, iso, attended, out)
    try:
        asks = open_proposal_asks(root)
    except StoreError as e:
        out("ATS PROPOSALS ASK NOT CHECKED: %s" % e)
        return 0
    state, doc = read_cache(root)
    if state != "ok":
        why = "no finder cache on this machine" if state == "absent" else "cache unreadable: %s" % doc
        if state == "unreadable":
            out("ATS FINDER CACHE UNREADABLE: %s" % doc)
        for a in asks:
            out(left_open_line(a["id"], why))
        return 0
    try:
        companies, opps = _load_profile(root)
    except StoreError as e:
        out("ATS PROPOSALS ASK NOT CHECKED: %s" % e)
        return 0
    valid, _stale = valid_proposals(doc, companies, opps)
    mine = [a for a in asks if _ask_cache_id(a["id"]) == doc["cache_id"]]
    for a in asks:
        if a not in mine:
            out(left_open_line(a["id"], "it belongs to another finder cache, not this machine's (%s)" % doc["cache_id"]))
    if valid and not mine:
        ask_id = "%s%s-%s" % (ASK_PREFIX, iso, doc["cache_id"])
        body = {"kind": "system", "title": ASK_TITLE, "created": iso,
                "ask": "Review them in a session you are present for, on the machine named %s: "
                       "/jobsearch:sourcing employers attended" % _host_name()}
        rc, text = _record_py(root, "create", ask_id, json.dumps(body), "--file", "asks")
        if rc == 0:
            out("ATS PROPOSALS ASK %s OPENED: %d proposal(s) wait for the candidate" % (ask_id, len(valid)))
        else:
            out("ATS PROPOSALS ASK %s NOT OPENED: record.py exited %d (%s)" % (ask_id, rc, text[:160]))
    elif not valid:
        for a in mine:
            ok, why = _resolve_ask(root, a["id"], "no proposals left", iso)
            out("ATS PROPOSALS ASK %s %s" % (a["id"], "RESOLVED: no proposals left" if ok else "NOT RESOLVED: " + why))
    return 0


def _supersede(root, ask_id, iso, attended, out):
    if not attended:
        out("ATS FINDER NOT RUN: closing another cache's ask is attended only")
        return 3
    try:
        asks = open_proposal_asks(root)
    except StoreError as e:
        out("ATS FINDER NOT RUN: %s" % e)
        return 3
    ask = next((a for a in asks if a["id"] == ask_id), None)
    if ask is None:
        out("ATS FINDER: %s is not an open %s ask" % (ask_id, ASK_PREFIX.rstrip("-")))
        return 2
    state, doc = read_cache(root)
    if state == "ok" and doc["cache_id"] == _ask_cache_id(ask_id):
        out("ATS FINDER: %s is THIS machine's ask; decide its proposals instead" % ask_id)
        return 2
    ok, why = _resolve_ask(root, ask_id, SUPERSEDE_RESOLUTION, iso)
    out("ATS PROPOSALS ASK %s %s" % (ask_id, "SUPERSEDED" if ok else "NOT RESOLVED: " + why))
    return 0 if ok else 3


# ---- the commands ---------------------------------------------------------------------------------------------------

def _blocked_set():
    """`(channels, error_code)`: the union the runtime guard builds, FAILING CLOSED (design 3.2)."""
    floor, err = guard_board_hosts.floor_channels()
    if err:
        return None, err
    rows, has_profile, err = guard_board_hosts.profile_channels()
    if err:
        return None, err
    if not has_profile:
        return None, "no-profile"
    return list(floor) + list(rows), None


def _iso_today(value):
    return datetime.date.fromisoformat(value) if value else datetime.date.today()


def _not_run(out, why):
    out("ATS FINDER NOT RUN: %s" % why)
    return 3


def _pick_company(companies, ident):
    """`(company, error)` for `--company <id|name>`: one hit is used; several or none are refused."""
    exact = [c for c in companies if c.get("id") == ident]
    hits = [c["id"] for c in exact] or pipeline_index.company_candidates(ident, companies)
    if len(hits) == 1:
        return next(c for c in companies if c.get("id") == hits[0]), None
    if hits:
        return None, "%r matches several companies (%s); name one id" % (ident, ", ".join(hits))
    return None, ("%r is not a tracked company. The finder never creates one: record it first "
                  "(record.py create <id> '<json>' --file companies)" % ident)


def _pick_by_url(companies, url):
    host = board_hosts.host_of(url)
    if not host:
        return None, "--url %r is not an http(s) address" % url
    hits = [c for c in companies if EmployerHosts.for_company(c).matches(host)]
    if len(hits) == 1:
        return hits[0], None
    if hits:
        return None, "%s matches several companies (%s); add --company <id>" % (host, ", ".join(c["id"] for c in hits))
    return None, "no tracked company has the host %s; add --company <id> to say whose page it is" % host


def cmd_resolve(root, args, out, fetch, clock, today):
    if not args.attended:
        return _not_run(out, "careers-page reads are attended only")
    if _is_unbound(root) or not _looks_like_profile(root):
        return _not_run(out, "no job-search profile is bound")
    if _is_tracked_fixture(root):
        return _not_run(out, "the profile root is the tracked fixture; pin CLAUDESEARCH_ROOT to a scratch copy")
    channels, err = _blocked_set()
    if err:
        return _not_run(out, "the blocked-host set could not be read (%s)" % err)
    try:
        companies, opps = _load_profile(root)
    except StoreError as e:
        return _not_run(out, str(e))
    state, doc = read_cache(root)
    if state == "unreadable":
        out("ATS FINDER CACHE UNREADABLE: %s" % doc)
        out("ATS FINDER CACHE KEPT AS %s; a fresh cache starts" % os.path.basename(keep_unreadable(root)))
    doc = doc if state == "ok" else new_cache()

    extra, start_override = (), None
    if args.company or args.url:
        if args.company:
            company, why = _pick_company(companies, args.company)
        else:
            company, why = _pick_by_url(companies, args.url)
        if company is None:
            out("ATS FINDER: %s" % why)
            return 2
        if args.url:
            host = board_hosts.host_of(args.url)
            if not host:
                out("ATS FINDER: --url %r is not an http(s) address" % args.url)
                return 2
            extra, start_override = (host,), args.url.strip()
        why = eligible(company, opps)
        if why:
            out("ATS FINDER: %s is not eligible: %s" % (company["id"], why))
            return 2
        targets = [{"id": company["id"], "start": start_override}]
        queued = len(build_queue(companies, opps, doc, today))
    else:
        queue = build_queue(companies, opps, doc, today)
        queued = len(queue)
        targets = [{"id": q["id"], "start": None} for q in queue[:args.limit]]
    by_id = dict((c["id"], c) for c in companies)

    ctx = _Ctx(fetch, clock, channels)
    iso = today.isoformat()
    read = proposed = 0
    unresolved = collections.Counter()
    for t in targets:
        co = by_id[t["id"]]
        entry, pages = resolve_company(ctx, co, opps, iso, start_url=t["start"], extra_hosts=extra)
        doc["companies"][co["id"]] = entry
        write_cache(root, doc)
        read += 1 if pages else 0
        if entry["outcome"] == "proposed":
            proposed += 1
            out("ATS FINDER %s: PROPOSED %s:%s (found on %s; %s; identity %s)" % (
                co["id"], entry["key"][0], entry["key"][1], entry["evidence_url"],
                "probe %d posting(s)" % entry["probe"]["count"] if entry["probe"] else "no probe",
                entry["identity"]["reason"]))
        else:
            unresolved[entry["code"]] += 1
            out("ATS FINDER %s: UNRESOLVED %s%s" % (co["id"], entry["code"],
                                                    " (%s)" % entry["detail"] if entry.get("detail") else ""))
    if ctx.egress:
        tally = collections.Counter(ctx.egress.values())
        out("ATS FINDER EGRESS: %d employer host(s) were not reachable from this session (%s)." % (
            len(ctx.egress), ", ".join("%s %d" % (c, tally[c]) for c in EGRESS_CODES if tally[c])))
        out("  The command sandbox refuses hosts outside sandbox.network.allowedDomains in auto mode, and asks in Manual mode.")
        out("  Approve the host when asked, add it to allowedDomains in the profile project's settings, or run this command")
        out("  with the sandbox off; then run /jobsearch:sourcing employers attended again.")
    out("ATS FINDER: read %d of %d queued, proposed %d, unresolved %d. Review them: ats_finder.py --review"
        % (read, queued, proposed, sum(unresolved.values())))
    try:
        write_note(root, resolve_note(queued, read, proposed, unresolved, len(ctx.egress)), args.run)
    except _journal.JournalError as e:
        out("ATS FINDER JOURNAL: the finder v1 note was not written (%s)" % e)
    return 0


def _telemetry(root, queued, open_proposals):
    """`(line, error)`: the `finder:` line, or why it could not be built (a journal or note that does not read)."""
    try:
        return finder_line(read_notes(root), queued, open_proposals), None
    except (_journal.JournalError, FinderNoteError) as e:
        return None, str(e)


def cmd_queue(root, args, out, today):
    try:
        companies, opps = _load_profile(root)
    except StoreError as e:
        return _not_run(out, str(e))
    state, doc = read_cache(root)
    if state == "unreadable":
        out("ATS FINDER CACHE UNREADABLE: %s (the queue treats it as empty; --resolve keeps the file and starts a new one)" % doc)
        doc = None
    queue = build_queue(companies, opps, doc, today)
    valid, stale = valid_proposals(doc, companies, opps)
    out("ATS FINDER QUEUE (no network): %d company(ies) queued" % len(queue))
    for i, q in enumerate(queue, 1):
        out("  %d. %s (%s): %s" % (i, q["id"], q["name"],
                                   "start %s" % q["start"] if q["start"] else "no-employer-url (no address of its own on file; never fetched)"))
    out("ATS FINDER PROPOSALS: %d open%s" % (len(valid), "" if not stale else " (+%d stale: --resolve re-reads them)" % len(stale)))
    line, err = _telemetry(root, len(queue), len(valid))
    if err:
        out("ATS FINDER NOTE UNREADABLE: %s" % err)
        return 3
    out(line)
    return 0


def cmd_review(root, args, out):
    try:
        companies, opps = _load_profile(root)
    except StoreError as e:
        return _not_run(out, str(e))
    state, doc = read_cache(root)
    if state != "ok":
        out("ATS FINDER REVIEW: %s" % ("no finder cache on this machine; proposals are decided on the machine that found them"
                                      if state == "absent" else "cache unreadable (%s)" % doc))
        return 0
    valid, stale = valid_proposals(doc, companies, opps)
    by_id = dict((c["id"], c) for c in companies)
    out("ATS FINDER REVIEW: %d proposal(s) in cache %s on this machine" % (len(valid), doc["cache_id"]))
    for i, cid in enumerate(valid, 1):
        e, co = doc["companies"][cid], by_id[cid]
        out("  %d. %s (%s): %s %s%s" % (i, cid, co.get("name") or cid, e["key"][0], e["key"][1],
                                       " (%s)" % e["key"][2] if e["key"][2] else ""))
        out("       found on: %s" % e["evidence_url"])
        out("       board:    %s" % e["board_url"])
        out("       probe:    %s" % ("%d posting(s) at %s" % (e["probe"]["count"], e["probe"]["url"]) if e["probe"]
                                    else "none (the first poll checks robots and sitemap)"))
        out("       identity: %s%s" % (e["identity"]["reason"],
                                       " (board named %r)" % e["identity"]["checked"] if e["identity"]["checked"] else
                                       " (the evidence is the employer's own page)"))
        if e.get("hiring_org"):
            out("       the page's hiringOrganization: %s" % e["hiring_org"])
    if stale:
        out("  (%d stale proposal(s) not shown: the company changed since; --resolve re-reads it)" % len(stale))
    for cid, e in sorted(doc["companies"].items()):
        co = by_id.get(cid)
        if co is None or e["outcome"] != "unresolved":
            continue
        if e["code"] == "no-employer-url":
            hosts = third_party_hosts(co, opps, EmployerHosts.for_company(co))
            out("  NEEDS A CAREERS ADDRESS: %s (%s)%s. Set career_url or domain to let the finder read it "
                "(record.py set %s career_url <address> --file companies)."
                % (cid, co.get("name") or cid, " has addresses only on " + ", ".join(hosts) if hosts else
                   " has no address on file", cid))
        elif e["code"] == "no-board-link":
            out("  NO BOARD LINK: %s. The finder reads English link words; set career_url to the careers page, or run "
                "--company %s --url <careers page>." % (cid, cid))
        elif e["code"] == "redirected":
            out("  REDIRECTED: %s %s" % (cid, e.get("detail", "")))
    try:
        for a in open_proposal_asks(root):
            if _ask_cache_id(a["id"]) != doc["cache_id"]:
                out("  ASK %s belongs to another finder cache. Close it with: ats_finder.py --reconcile-ask --attended "
                    "--supersede %s" % (a["id"], a["id"]))
    except StoreError:
        pass
    return 0


def cmd_decide(root, args, out, today):
    if not args.attended:
        return _not_run(out, "deciding a proposal is attended only")
    pairs = []
    for raw in args.decide:
        cid, sep, verb = raw.partition("=")
        if not sep or not cid or verb not in ("accept", "reject", "skip"):
            out("ATS FINDER: %r is not <company_id>=accept|reject|skip" % raw)
            return 2
        pairs.append((cid, verb))
    state, doc = read_cache(root)
    if state != "ok":
        out("ATS FINDER CACHE %s: %s" % ("MISSING" if state == "absent" else "UNREADABLE",
                                         "no finder cache on this machine; nothing can be decided here" if state == "absent" else doc))
        return 3
    try:
        companies, opps = _load_profile(root)
    except StoreError as e:
        return _not_run(out, str(e))
    by_id = dict((c["id"], c) for c in companies)
    counts = {"accept": 0, "reject": 0, "skip": 0}
    refused = 0
    for cid, verb in pairs:
        entry, co = doc["companies"].get(cid), by_id.get(cid)
        why = None
        if entry is None or entry["outcome"] != "proposed":
            why = "no proposal for it in this cache"
        elif co is None:
            why = "the company is no longer in the profile"
        elif "ats" in co:
            why = "its ats is already %s" % ("declined (null)" if co["ats"] is None else "set")
        elif entry["inputs"] != fingerprint(co, opps):
            why = "its addresses changed since the proposal; run --resolve again"
        if why:
            out("ATS FINDER DECIDE %s: REFUSED, %s" % (cid, why))
            refused += 1
            continue
        if verb == "skip":
            counts["skip"] += 1
            out("ATS FINDER DECIDE %s: SKIPPED (the proposal stays)" % cid)
            continue
        if verb == "accept":
            if list(ats_slug.parse(entry["board_url"]) or ()) != entry["key"]:
                out("ATS FINDER DECIDE %s: REFUSED, the cached key no longer matches its board address" % cid)
                refused += 1
                continue
            rc, text = _record_py(root, "ats", cid, "--url", entry["board_url"])
        else:
            rc, text = _record_py(root, "ats", cid, "--none")
        if rc != 0:
            out("ATS FINDER DECIDE %s: REFUSED, record.py exited %d (%s)" % (cid, rc, text[:200]))
            refused += 1
            continue
        counts[verb] += 1
        del doc["companies"][cid]
        write_cache(root, doc)
        out("ATS FINDER DECIDE %s: %s (%s)" % (cid, "ACCEPTED" if verb == "accept" else "REJECTED", text[:160]))
    try:
        write_note(root, decide_note(counts["accept"], counts["reject"], counts["skip"]), args.run)
    except _journal.JournalError as e:
        out("ATS FINDER JOURNAL: the finder v1 note was not written (%s)" % e)
    reconcile(root, today, out)
    return 1 if refused else 0


def cmd_reconcile(root, args, out, today):
    rc = reconcile(root, today, out, attended=args.attended, supersede=args.supersede)
    if rc or args.supersede:
        return rc
    try:
        companies, opps = _load_profile(root)
        state, doc = read_cache(root)
        queue = build_queue(companies, opps, doc if state == "ok" else None, today)
        valid, _stale = valid_proposals(doc if state == "ok" else None, companies, opps)
    except StoreError as e:
        out("finder: NOT CHECKED (%s)" % e)
        return 0
    line, err = _telemetry(root, len(queue), len(valid))
    out(line if line else "finder: NOT CHECKED (%s)" % err)
    return 0


# ---- the command line ----------------------------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(prog="ats_finder.py", description=__doc__.split("\n")[0])
    ap.add_argument("--resolve", action="store_true", help="read careers pages of queued companies (needs --attended)")
    ap.add_argument("--queue", action="store_true", help="print the derived queue (no network)")
    ap.add_argument("--review", action="store_true", help="print this machine's open proposals (no network)")
    ap.add_argument("--decide", nargs="+", metavar="ID=VERB", help="accept|reject|skip each proposal (needs --attended)")
    ap.add_argument("--reconcile-ask", dest="reconcile_ask", action="store_true",
                    help="open or resolve this cache's one ask (no network)")
    ap.add_argument("--supersede", metavar="ASK_ID", help="with --reconcile-ask --attended: close another cache's ask")
    ap.add_argument("--attended", action="store_true", help="the candidate is present (only the explicit attended form passes it)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="companies read per call (default %d)" % DEFAULT_LIMIT)
    ap.add_argument("--company", help="a tracked company, by id or name")
    ap.add_argument("--url", help="a careers address on that company's own site")
    ap.add_argument("--run", help="the run id the finder note is written under")
    ap.add_argument("--today", help="YYYY-MM-DD (tests)")
    return ap


def main(argv=None, fetch=None, clock=None, out=print):
    args = build_parser().parse_args(argv)
    modes = [m for m, on in (("--resolve", args.resolve), ("--queue", args.queue), ("--review", args.review),
                             ("--decide", bool(args.decide)), ("--reconcile-ask", args.reconcile_ask)) if on]
    if len(modes) != 1:
        out("ATS FINDER: exactly one of --resolve, --queue, --review, --decide, --reconcile-ask (got %s)"
            % (", ".join(modes) or "none"))
        return 2
    if args.supersede and not args.reconcile_ask:
        out("ATS FINDER: --supersede belongs with --reconcile-ask")
        return 2
    if args.limit < 1:
        out("ATS FINDER: --limit must be at least 1")
        return 2
    try:
        today = _iso_today(args.today)
    except ValueError:
        out("ATS FINDER: --today %r is not YYYY-MM-DD" % args.today)
        return 2
    root = _profile_root()
    if modes[0] == "--resolve":
        fetch = fetch or (lambda req: feed_poll.default_fetch(req, follow_redirects=False))
        return cmd_resolve(root, args, out, fetch, clock or feed_poll.RealClock(), today)
    if _is_unbound(root) or not _looks_like_profile(root):
        return _not_run(out, "no job-search profile is bound")
    if modes[0] == "--queue":
        return cmd_queue(root, args, out, today)
    if modes[0] == "--review":
        return cmd_review(root, args, out)
    if modes[0] == "--decide":
        return cmd_decide(root, args, out, today)
    return cmd_reconcile(root, args, out, today)


if __name__ == "__main__":
    sys.exit(main())
