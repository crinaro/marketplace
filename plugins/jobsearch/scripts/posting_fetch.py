#!/usr/bin/env python3
"""posting_fetch.py -- the automatic, logged-out read of a LinkedIn job posting (jobsearch 0.85.0; automatic for everyone from 0.90.0).

dev #840 / public #181 (0.85.0: design-hidden-pane-reads.md section 3, 4 and 16, ADR-038) and dev 858 (0.90.0: owner rulings D-A (a)
everyone, (a2) no migration widens any sandbox, D-B an explicit `off` wins; design-browser-fallback.md section 6).

WHAT IT IS, AND WHEN IT RUNS
----------------------------
`record.py read-batch --fallback --run <id> [--ids <opp id> ...] [--deadline-s N]` imports this module, lazily. It is the
FALLBACK of the drain's read stage, never its first move:

  * `record.py read-batch --fetch` (the first pass) never sends a GET to a LinkedIn address. A LinkedIn role goes to the
    render residue as `RESIDUE <id> (render): browser-first`, whatever the key says.
  * `jd-reader` reads every `(render)` role in the Browser pane first, then, for an attended run, in Claude in Chrome. Only a role
    whose browser reads could not happen (design 6.1, applied by `record.py`) can reach the fallback, and only when `auto_gate`
    says go: the key is not `off` or unreadable, the host is `admitted`, and, for an `absent` key, the notice row exists.
  * It GETs ONE public address per eligible role, `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<job id>`,
    and records only what it can read in full: `read` (a pinned setting label and a derivable pay) or `closed` (the
    page's own closed marker, on the page that is the role). Everything else records NO outcome about the role: a 429, any
    other HTTP status (401, 403, 404, 410, 999 and 5xx included), a shape change, a wrong page, the cap, a closed host. The
    role keeps the outcome the browser gave it. Since 0.90.0 a fetch that did not read leaves one more fact, never about the
    role: `record.py` appends one `via fetch` `pane-hidden` attempt naming why (`evidence.fallback.fetch`). The endpoint is
    UNDOCUMENTED by the vendor (a published scraping pattern only), so no answer from it is ever evidence about the role.

WHAT IT SENDS (stated so a test can fail on it)
-----------------------------------------------
One request object built HERE (`build_request`): method GET, scheme https, host exactly `www.linkedin.com`, a path that
matches `^/jobs-guest/jobs/api/jobPosting/\\d+$`, no query, and ONE header, `User-Agent` (`feed_poll.USER_AGENT`, which
names the plugin and its repository). The HTTP stack adds `Host`, `Accept-Encoding: identity` and `Connection: close`.
No cookie, no `Authorization`, no sign-in. `feed_poll.default_fetch` has no cookie processor and refuses a cross-origin
redirect (`FetchError("redirected")`). The module configures no proxy of its own: urllib's default `ProxyHandler` stays,
so when the environment sets a proxy (the command sandbox's, when it is on) the request goes through it. It never uses a
proxy to change its address or to get round a limit.

PACING, BACKOFF, CAP (per host, kept across the fallback calls of one run in `cache/posting_fetch.json`)
--------------------------------------------------------------------------------------------------------
  `MIN_INTERVAL_S` 3.0 s plus jitter `U(0, JITTER_MAX_S)`, measured from the run's `last_request_at`, a WALL-CLOCK value
  (`time.time()`, never a monotonic reading, which is not comparable across a reboot or a sleep). The computed wait is
  CLAMPED to `[0, MIN_INTERVAL_S + JITTER_MAX_S]`, so a persisted time far in the future or the past cannot make a run
  sleep for hours or skip the pause.
  One backoff: a 429 is retried once, after its `Retry-After` (up to `RETRY_AFTER_CAP_S`; a longer one closes the host
  for the run) or after `BACKOFF_S` when it has none. A 429 that survives the retry is `rate-limited`, and records nothing.
  The host closes for the run after `HOST_CLOSE_AFTER` such answers, or `HOST_CLOSE_AFTER` other non-200 answers, or at
  once on a cross-origin redirect or a transport failure. A closed host makes no request.
  `POSTING_FETCH_CAP` GETs per run per machine. The bound is per machine and per run: machines behind one address add
  up, and so do two processes on one machine (each writes the state atomically after every GET, and a lost update can let
  each make the remaining cap: at worst 2 x `POSTING_FETCH_CAP`).

FILES (never a store; `_root.state_root()` of the bound profile, or the seam `_STATE_DIR` in a test)
----------------------------------------------------------------------------------------------------
  `cache/posting_fetch.json`   {"clock": "wall", "runs": {run_id: {requests, rate_limited, http_errors, closed,
                               closed_reason, last_request_at, started_at, tried, summary_lines_shown}}}. A cache: lost,
                               the run's cap resets once. Entries older than 7 days are pruned at write.
  `cache/bodies/<opp_id>.txt`  the description text exactly as parsed (public posting text, not personal data), saved only
                               for a role the script could not settle and the reader must read. `cache/bodies/index.json`
                               holds {opp_id: {run, sha1, chars, url, title, place, fetched_at, reason}}.
                               Files older than 7 days, or whose role now has a `read` attempt, are pruned.
  With no bound profile (`state_root()` falls back to the machine-global directory) the fallback prints
  `FALLBACK: off (no profile state directory)` and makes no GET.

THE KEY AND THE SETTER: `python3 posting_fetch.py --set on|auto|off` (jobsearch 0.90.0, dev 858)
-------------------------------------------------------------------------------------------------
The key's tri-state (`absent` = automatic, `on`, `off` = NO fetch ever, `unreadable` = NO fetch), the sandbox admission check, the
notice row and the gate are in `browser_fallback/` (`fetch_key`, `fetch_sandbox`, `fetch_notice`, `fetch_gate`); this file passes
them its seams. The setter is the only writer of the key and of the notice row: `--set on` prints the terms (`TERMS_LINES`) FIRST,
adds `www.linkedin.com` to the profile project's sandbox allowedDomains (`support_ats_feeds._ats_feeds_settings_step`) and writes
`"on"`; `--set auto` prints the terms and REMOVES the key; `--set off` writes `"off"`. No migration ever touches a sandbox setting.

Python 3.9+. Standard library only. Stdout only; the one write path is the setter and the two state files above.
"""

import argparse
import collections
import datetime
import hashlib
import html
import html.parser
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _atomic
import _root
import board_hosts as _bh
import feed_poll as _fp
from browser_fallback import fetch_gate as _gate, fetch_notice as _notice, fetch_sandbox as _sandbox
from browser_fallback.fetch_limits import MIN_INTERVAL_S, POSTING_FETCH_CAP  # pacing and the cap (pace-by-test seams keep these names)
from browser_fallback.fetch_key import KEY, KEY_DEFAULT, KEY_VALUES, SET_VALUES, key_value, write_key  # noqa: F401
from browser_fallback.closed_wordings import CLOSED_MARKER, CLOSED_MARKERS, closed_hit  # noqa: F401  -- the closed phrases (0.94.0, dev 1063, design 6.4); English only

# ---- what is sent -------------------------------------------------------------------------------------------------
_BASE = "https://www.linkedin.com"                       # a seam: the tests point it at a 127.0.0.1 loopback server
HOST = "www.linkedin.com"
LINKEDIN = "linkedin.com"                                # `board_hosts.host_matches` base: a sub-domain counts
ENDPOINT_PATH = "/jobs-guest/jobs/api/jobPosting/%s"
ENDPOINT_PATH_RE = re.compile(r"^/jobs-guest/jobs/api/jobPosting/\d+$", re.ASCII)
_HTTP = _fp.default_fetch                                # a seam: `(Request) -> feed_poll.Response`; raises FetchError

# ---- pacing, backoff, cap (OURS; design section 3.4, with the reasons stated there) --------------------------------------
JITTER_MAX_S = 1.0
BACKOFF_S = 30                                           # a 429 with no Retry-After: wait this, once
RETRY_AFTER_CAP_S = _fp.RETRY_AFTER_CAP_S                # the longest Retry-After waited out; a longer one closes the host
HOST_CLOSE_AFTER = 3                                     # rate-limit answers, or other non-200 answers, in one run
REQUEST_TIMEOUT_S = _fp.TIMEOUT_S
# pacing at its maximum + a timeout + the backoff + the retry's timeout: asserted equal to that sum by a test, so a
# changed constant that forgets this one is red. `--deadline-s` stops between roles below it.
ROLE_WORST_CASE_S = 54
BODY_MAX_AGE_S = 7 * 24 * 3600                           # a saved body, and a run's state, live this long

# seams (the shipped verb never replaces them)
_WALL = time.time                                        # `() -> wall-clock seconds`, the persisted pacing clock
_CLOCK = None                                            # an object with now() and sleep(s); None means the real one
_JITTER = None                                           # `() -> float`; None means random.uniform(0, JITTER_MAX_S)
_STATE_DIR = None                                        # an explicit state directory; None means `_root.state_root()`

# ---- what is read (OURS: the class names are a published scraping pattern, not a vendor contract) ----------------------
DESCRIPTION_CLASS = "show-more-less-html__markup"
TITLE_CLASS = "topcard__title"
PLACE_CLASS = "topcard__flavor--bullet"
SETTING_LABEL_CLASS = None                               # UNDETERMINED: the workplace-type element is not yet pinned.
#                                                          While it is None every parsed role takes the `(body)` route.

# ---- the key, the audience and the terms --------------------------------------------------------------------------------------
# OWNER RULING D-A (a), 2026-11-16 (dev 858): the automatic fetch is for EVERY installer, told first by `notice_row` (the owner
# knew LinkedIn's robots.txt and User Agreement restrict it). The seam `"opted-in"` keeps the record executable; shipped: "everyone".
AUDIENCES = ("everyone", "opted-in")
AUTO_FETCH_AUDIENCE = "everyone"
SANDBOX_PRE_COPY = "pre-posting-fetch"
TERMS_LINES = (
    "posting_fetch: the logged-out posting fetch for LinkedIn roles neither the Browser pane nor Claude in Chrome could read.",
    "  Sent: one GET per role to https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>, with only a User-Agent "
    "naming this plugin. No cookie, no sign-in.",
    "  Pace: at most 40 per run on this machine, at least 3 s apart. Machines behind one address add up.",
    "  LinkedIn's robots.txt disallows this path, and LinkedIn User Agreement section 8.2 restricts automated access. "
    "Using this is your decision.",
    "  Terms: docs/user/jobsearch/posting-fetch.md in https://github.com/crinaro/marketplace",
)

SUMMARY_HTTP = "POSTING FETCH: host answered HTTP %s; closed for this run"
SUMMARY_REDIRECT = "POSTING FETCH: redirected; closed for this run"
SUMMARY_UNREACHABLE = ("POSTING FETCH: host unreachable (%s): check sandbox.network.allowedDomains")
SUMMARY_RATE = "POSTING FETCH: rate-limited %d times; closed for this run"
SUMMARY_RETRY_AFTER = "POSTING FETCH: rate-limited, Retry-After %s s is over the %d s cap; closed for this run"


class PostingRefusal(Exception):
    """The page is not in the shape this parser knows. `code` is `shape-changed`, `not-utf8` or `too-large`."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


# ---- addresses --------------------------------------------------------------------------------------------------------------

_VIEW_RE = re.compile(r"^/jobs/view/(?:[^/?#]*-)?([0-9]+)/?$")
_QUERY_ID_RE = re.compile(r"^[0-9]+$")


def is_linkedin(url):
    """True when `url`'s host is `linkedin.com` or a sub-domain of it (`board_hosts.host_matches`, the one comparison)."""
    return _bh.host_matches(_bh.host_of(url), LINKEDIN)


def posting_id(url):
    """The LinkedIn job id of `url` (a digit string), or None. Reads `/jobs/view/<digits>`, `/jobs/view/<slug>-<digits>`
    and `?currentJobId=<digits>` on a `linkedin.com` host; anything else is None, so a search-results page or a profile
    never becomes a fetch."""
    if not is_linkedin(url):
        return None
    import urllib.parse
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    m = _VIEW_RE.match(parts.path or "")
    if m:
        return m.group(1)
    for key, vals in urllib.parse.parse_qs(parts.query).items():
        if key == "currentJobId" and len(vals) == 1 and _QUERY_ID_RE.match(vals[0]):
            return vals[0]
    return None


def endpoint_url(job_id):
    return _BASE + ENDPOINT_PATH % job_id


def build_request(job_id):
    """The ONE request object this module sends: GET, the fixed endpoint of `job_id`, the single header `User-Agent`.
    The caller never adds a header. Raises ValueError for anything but a digit string."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9]+", job_id):
        raise ValueError("a job id is a digit string -- %r" % (job_id,))
    return _fp.Request("GET", endpoint_url(job_id), {"User-Agent": _fp.USER_AGENT}, REQUEST_TIMEOUT_S)


# ---- the parse contract (design section 3.2) --------------------------------------------------------------------------------

_BLOCK_TAGS = frozenset(("p", "br", "li", "ul", "ol", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "hr"))
_SKIP_TAGS = frozenset(("script", "style"))


def _tidy(text):
    """One line per block: each line's whitespace collapsed, empty lines dropped. Nothing is dropped but whitespace."""
    lines = [" ".join(l.split()) for l in text.split("\n")]
    return "\n".join(l for l in lines if l)


class _Capture(object):
    __slots__ = ("tag", "depth", "start", "end", "text")

    def __init__(self, tag, start):
        self.tag, self.depth, self.start, self.end, self.text = tag, 1, start, None, []


class _Page(html.parser.HTMLParser):
    """Finds the elements of the parse contract by CLASS TOKEN (never by position), keeps the description's source
    text verbatim and every element's visible text, and notes whether the closed marker appears in the page's text."""

    def __init__(self, source):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.src = source
        self._line_starts = [0]
        for m in re.finditer("\n", source):
            self._line_starts.append(m.end())
        self.want = {DESCRIPTION_CLASS: "description", TITLE_CLASS: "title", PLACE_CLASS: "place"}
        if SETTING_LABEL_CLASS:
            self.want[SETTING_LABEL_CLASS] = "setting"
        self.found = collections.defaultdict(list)          # kind -> [_Capture]
        self._open = []                                     # [(kind, _Capture)]
        self._skip = 0
        self.page_text = []                                 # the visible text OUTSIDE the description element

    def _offset(self):
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text() or ""
        if tag in _SKIP_TAGS:
            self._skip += 1
        for _kind, cap in self._open:
            if cap.tag == tag:
                cap.depth += 1
        classes = set()
        for k, v in attrs:
            if k == "class" and v:
                classes.update(v.split())
        for cls, kind in self.want.items():
            if cls in classes:
                cap = _Capture(tag, self._offset() + len(raw))
                self.found[kind].append(cap)
                self._open.append((kind, cap))
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in _BLOCK_TAGS:
            self._break()
        still = []
        for kind, cap in self._open:
            if cap.tag == tag:
                cap.depth -= 1
                if cap.depth == 0:
                    cap.end = self._offset()
                    continue
            still.append((kind, cap))
        self._open = still

    def _in_description(self):
        return any(kind == "description" for kind, _cap in self._open)

    def _break(self):
        for _kind, cap in self._open:
            cap.text.append("\n")
        self.page_text.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        for _kind, cap in self._open:
            cap.text.append(data)
        if not self._in_description():                      # the marker is the page's own, never the employer's prose
            self.page_text.append(data)


def parse(body):
    """`{title, place, description_html, description_text, closed, setting_label}` for a guest posting page (`bytes`), or
    raises `PostingRefusal(code)`. Nothing is summarised: `description_html` is the description element's own source,
    byte for byte, and `description_text` is the same text with tags turned into line breaks and entities decoded.
    `place` and `setting_label` are None when absent; `closed` is True only when the marker is present (its absence never
    means the role is open, only that the marker was not seen)."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > _fp.MAX_BODY:
        raise PostingRefusal("too-large")
    try:
        source = body.decode("utf-8")
    except UnicodeDecodeError:
        raise PostingRefusal("not-utf8")
    page = _Page(source)
    try:
        page.feed(source)
        page.close()
    except Exception:                                       # noqa: BLE001 -- unreadable markup is a shape this does not know
        raise PostingRefusal("shape-changed")
    desc, title = page.found.get("description", []), page.found.get("title", [])
    if len(desc) != 1 or not title or desc[0].end is None:
        raise PostingRefusal("shape-changed")
    description_html = source[desc[0].start:desc[0].end]
    title_text = " ".join("".join(title[0].text).split())
    if not title_text:
        raise PostingRefusal("shape-changed")
    place = None
    if page.found.get("place"):
        place = " ".join("".join(page.found["place"][0].text).split()) or None
    setting = None
    if SETTING_LABEL_CLASS and page.found.get("setting"):
        setting = " ".join("".join(page.found["setting"][0].text).split()) or None
    text = _tidy("".join(desc[0].text))
    closed = closed_hit("".join(page.page_text))
    return {"title": title_text, "place": place, "description_html": description_html, "description_text": text,
            "closed": closed, "setting_label": setting}


def decide(parsed, names, countries):
    """What a parsed posting becomes (design section 3.3), the title check first so a closed marker on the wrong page
    settles nothing. Returns one of
        {"kind": "wrong-page"}
        {"kind": "closed"}
        {"kind": "read", "pay": <slot>, "setting": <label>, "place": <place or None>}
        {"kind": "body", "reason": <why the script could not settle it>}
    `names` is the set of words that name the role (its title, its company); `countries` the JSON-LD-style country list
    `description_pay_slot` reads a `$` against."""
    words = set(re.findall(r"[^\W\d_]{3,}", str(parsed["title"] or "").casefold()))
    if not (words & set(names)):
        return {"kind": "wrong-page"}
    if parsed["closed"]:
        return {"kind": "closed"}
    label = parsed["setting_label"]
    slot = _fp.description_pay_slot(parsed["description_html"], countries)
    if label is not None and slot != "?":
        return {"kind": "read", "pay": slot, "setting": label, "place": parsed["place"]}
    return {"kind": "body", "reason": "no-setting-label" if label is None else "pay-not-derivable"}


# ---- state (a cache: lost, the run's cap resets once) -----------------------------------------------------------------------

def state_dir():
    """The directory this run's state lives in, or None when no profile is bound. The seam `_STATE_DIR` wins; otherwise
    `_root.state_root()`, and its machine-global fallback means NO state directory (never a state file shared by every
    profile on the machine)."""
    if _STATE_DIR is not None:
        return _STATE_DIR
    d = _root.state_root()
    if d == getattr(_root, "_HOME_STATE", None):
        return None
    return d


def _clock():
    return _CLOCK if _CLOCK is not None else _fp.RealClock()


def _jitter():
    if _JITTER is not None:
        v = _JITTER()
    else:
        v = random.uniform(0, JITTER_MAX_S)
    return max(0.0, min(float(v), JITTER_MAX_S))


def _state_path(sdir):
    return os.path.join(sdir, "cache", "posting_fetch.json")


def _bodies_dir(sdir):
    return os.path.join(sdir, "cache", "bodies")


def _blank_entry(now):
    return {"requests": 0, "rate_limited": 0, "http_errors": 0, "closed": False, "closed_reason": None,
            "last_request_at": None, "started_at": now, "tried": [], "summary_lines_shown": []}


def load_state(sdir):
    try:
        with open(_state_path(sdir), encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return {"clock": "wall", "runs": {}}
    if not isinstance(st, dict) or not isinstance(st.get("runs"), dict):
        return {"clock": "wall", "runs": {}}
    st["clock"] = "wall"
    return st


def save_state(sdir, st, now):
    st["clock"] = "wall"
    st["runs"] = {rid: e for rid, e in st["runs"].items()
                  if isinstance(e, dict) and now - float(e.get("started_at") or 0) < BODY_MAX_AGE_S}
    path = _state_path(sdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic.write_json(path, st)


Result = collections.namedtuple("Result", "kind status body detail")


class Session(object):
    """One run's fetching on one machine: the pacing, the one backoff, the cap, the host breaker, and the state those need
    across calls, written after every GET. `get(job_id)` returns a `Result` whose `kind` is `ok` (a 200), `rate-limited`,
    `http` (any other status, in `status`), `redirected`, `unreachable` (the FetchError code in `detail`), `capped` or
    `host-closed`. It never records anything about a role."""

    def __init__(self, sdir, run_id, say=print):
        self.sdir, self.run_id, self._say = sdir, run_id, say
        self.state = load_state(sdir)
        self.e = self.state["runs"].setdefault(run_id, _blank_entry(_WALL()))
        for k, v in _blank_entry(_WALL()).items():
            self.e.setdefault(k, v)

    # -- persistence ---------------------------------------------------------------------------------------------------
    def save(self):
        save_state(self.sdir, self.state, _WALL())

    def say_once(self, key, text):
        if key not in self.e["summary_lines_shown"]:
            self.e["summary_lines_shown"].append(key)
            self._say(text)

    def tried(self, opp_id):
        return opp_id in self.e["tried"]

    def mark_tried(self, opp_id):
        if opp_id not in self.e["tried"]:
            self.e["tried"].append(opp_id)
        self.save()

    @property
    def closed(self):
        return bool(self.e["closed"])

    def _close(self, reason, line_key, line):
        self.e["closed"], self.e["closed_reason"] = True, reason
        self.say_once(line_key, line)
        self.save()

    # -- the wire ------------------------------------------------------------------------------------------------------
    def _pace(self):
        last = self.e.get("last_request_at")
        if last is None:
            return
        interval = MIN_INTERVAL_S + _jitter()
        wait = interval - (_WALL() - float(last))
        wait = max(0.0, min(wait, MIN_INTERVAL_S + JITTER_MAX_S))      # the clamp (R2-M1): a stale clock never sleeps long
        if wait > 0:
            _clock().sleep(wait)

    def _send(self, job_id):
        """One paced GET. Counts it and saves BEFORE the request goes out, so a crash cannot hide it from the cap."""
        self._pace()
        self.e["requests"] += 1
        self.e["last_request_at"] = _WALL()
        self.save()
        try:
            resp = _HTTP(build_request(job_id))
        finally:
            self.e["last_request_at"] = _WALL()
            self.save()
        return resp

    def get(self, job_id):
        if self.closed:
            return Result("host-closed", None, None, self.e["closed_reason"])
        if self.e["requests"] >= POSTING_FETCH_CAP:
            return Result("capped", None, None, None)
        try:
            resp = self._send(job_id)
            if resp.status == 429:
                ra = _fp.parse_retry_after((resp.headers or {}).get("retry-after"))
                if ra is not None and ra > RETRY_AFTER_CAP_S:
                    self.e["rate_limited"] += 1
                    self._close("retry-after", "retry-after", SUMMARY_RETRY_AFTER % (ra, RETRY_AFTER_CAP_S))
                    return Result("rate-limited", 429, None, "retry-after %s" % ra)
                if self.e["requests"] >= POSTING_FETCH_CAP:
                    self.e["rate_limited"] += 1
                    self.save()
                    return Result("rate-limited", 429, None, "cap reached before the retry")
                _clock().sleep(BACKOFF_S if ra is None else ra)
                resp = self._send(job_id)
                if resp.status == 429:
                    self.e["rate_limited"] += 1
                    if self.e["rate_limited"] >= HOST_CLOSE_AFTER:
                        self._close("rate-limited", "rate-limited", SUMMARY_RATE % self.e["rate_limited"])
                    self.save()
                    return Result("rate-limited", 429, None, None)
        except _fp.FetchError as e:
            if e.code == "redirected":
                self._close("redirected", "redirected", SUMMARY_REDIRECT)
                return Result("redirected", None, None, e.code)
            self._close("unreachable", "unreachable", SUMMARY_UNREACHABLE % e.code)
            return Result("unreachable", None, None, e.code)
        if resp.status == 200:
            return Result("ok", 200, resp.body, None)
        self.e["http_errors"] += 1
        if self.e["http_errors"] >= HOST_CLOSE_AFTER:
            self._close("http-%s" % resp.status, "http", SUMMARY_HTTP % resp.status)
        self.save()
        return Result("http", resp.status, None, None)


# ---- saved bodies (a role the script could not settle, for the reader) ---------------------------------------------------

def _sha1_text(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_index(sdir):
    try:
        with open(os.path.join(_bodies_dir(sdir), "index.json"), encoding="utf-8") as fh:
            idx = json.load(fh)
    except (OSError, ValueError):
        return {}
    return idx if isinstance(idx, dict) else {}


def save_body(sdir, opp_id, run_id, url, parsed, reason):
    """Write `description_text` to `bodies/<opp_id>.txt` and its entry to `bodies/index.json`. Returns `(path, sha1)`."""
    bdir = _bodies_dir(sdir)
    os.makedirs(bdir, exist_ok=True)
    text = parsed["description_text"]
    path = os.path.join(bdir, "%s.txt" % opp_id)
    _atomic.write_text(path, text)
    sha1 = _sha1_text(text)
    idx = _load_index(sdir)
    idx[opp_id] = {"run": run_id, "sha1": sha1, "chars": len(text), "url": url, "title": parsed["title"],
                   "place": parsed["place"], "fetched_at": _WALL(), "reason": reason}
    _atomic.write_json(os.path.join(bdir, "index.json"), idx)
    return path, sha1


def saved_body(sdir, opp_id):
    """`(path, entry)` of a body saved for `opp_id` that is younger than `BODY_MAX_AGE_S` and whose file still hashes to
    the index's sha1, else None. A run that died after the fetch and before the reader recorded costs no second GET."""
    entry = _load_index(sdir).get(opp_id)
    if not isinstance(entry, dict):
        return None
    path = os.path.join(_bodies_dir(sdir), "%s.txt" % opp_id)
    try:
        age = _WALL() - float(entry["fetched_at"])
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not 0 <= age < BODY_MAX_AGE_S or _sha1_text(text) != entry.get("sha1"):
        return None
    return path, entry


def prune(sdir, is_read):
    """Delete saved bodies older than `BODY_MAX_AGE_S`, those whose role `is_read(opp_id)`, and files the index does not
    name. Returns how many files it removed. Never raises on a missing directory."""
    bdir = _bodies_dir(sdir)
    if not os.path.isdir(bdir):
        return 0
    idx, keep, removed = _load_index(sdir), {}, 0
    now = _WALL()
    for name in sorted(os.listdir(bdir)):
        if not name.endswith(".txt"):
            continue
        opp_id = name[:-len(".txt")]
        entry = idx.get(opp_id)
        try:
            fresh = isinstance(entry, dict) and 0 <= now - float(entry["fetched_at"]) < BODY_MAX_AGE_S
        except (ValueError, KeyError, TypeError):
            fresh = False
        if fresh and not is_read(opp_id):
            keep[opp_id] = entry
            continue
        try:
            os.remove(os.path.join(bdir, name))
            removed += 1
        except OSError:
            pass
    if keep != idx:
        _atomic.write_json(os.path.join(bdir, "index.json"), keep)
    return removed


# ---- the key, the sandbox check, the notice row and the gate: `browser_fallback/` (design-browser-fallback.md 6.1-6.4) ---------
PROXY_VARS = _sandbox.PROXY_VARS
_USER_SETTINGS = None                                    # seam: an explicit path for the user's settings file
_MANAGED_SETTINGS = None                                 # seam: a list of managed-settings paths; None means the OS's documented one
NOTICE_ID, NOTICE_VALUES, NOTICE_REMEDY = _notice.NOTICE_ID, _notice.NOTICE_VALUES, _notice.NOTICE_REMEDY
NOTICE_TEXTS = _notice.notice_texts()
notice_exists = _notice.notice_exists


def admitted(root):
    """`(bool, why)`: may a GET to HOST go out (`fetch_sandbox.admitted`)?"""
    return _sandbox.admitted(root, HOST, _USER_SETTINGS, _MANAGED_SETTINGS)


def notice_row(value, today=None, created=None):
    """The ONE notice row for the key value `value` (`fetch_notice.notice_row`), dated `today` (default: now)."""
    return _notice.notice_row(value, today or datetime.date.fromtimestamp(_WALL()).isoformat(), created)


def write_notice_row(root, value):
    """Write the notice row for `value` by id (`fetch_notice.write_notice_row`)."""
    _notice.write_notice_row(root, value, datetime.date.fromtimestamp(_WALL()).isoformat())


def auto_gate(root):
    """`(go, code, remedy)` for one `read-batch --fallback` call (`fetch_gate.auto_gate`)."""
    return _gate.auto_gate(root, HOST, AUTO_FETCH_AUDIENCE, admitted)


# ---- the setter -------------------------------------------------------------------------------------------------------------

def set_key(root, value, out=print):
    """The setter's whole logic (`--set on|auto|off`). Returns the exit code: 0 written, 1 refused, 2 a value it does not take. Every
    value writes the notice row for its new state, by id; only `on` writes a sandbox setting (design 6.3)."""
    if value not in SET_VALUES:
        out("posting_fetch: --set takes on, auto or off (got %r). Nothing was written." % (value,))
        return 2
    if _root.is_unbound(root) or not _root.looks_like_profile(root):
        out("posting_fetch: no profile is bound here (%s), so there is nothing to set. Nothing was written." % root)
        return 1
    notice_value = {"on": "on", "auto": "absent", "off": "off"}[value]
    if value != "off":
        for line in TERMS_LINES:                             # the terms, BEFORE anything is written (R2-S2)
            out(line)
    if value in ("off", "auto"):
        try:
            write_notice_row(root, notice_value)
            write_key(root, value)
        except ValueError as e:
            out("posting_fetch: REFUSED -- %s. Nothing was written." % e)
            return 1
        out("posting_fetch: off. No fetch of any kind will run. %s stays in .claude/settings.json sandbox.network.allowedDomains "
            "if it was there; remove it by hand if you no longer want it." % HOST if value == "off" else
            "posting_fetch: auto. %s is no longer set, so a LinkedIn role neither the Browser pane nor Claude in Chrome could read "
            "is read from its public posting when the host is allowed (at most %d per run). Turn it off with "
            "`posting_fetch.py --set off`." % (KEY, POSTING_FETCH_CAP))
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from migrations import support_ats_feeds as _ats_feeds
    ok, line = _ats_feeds._ats_feeds_settings_step(root, True, hosts=(HOST,), label="posting-fetch",
                                                 pre_copy=SANDBOX_PRE_COPY)
    if line:
        out(line)
    if not ok:
        out("posting_fetch: %s was NOT turned on, because the sandbox host could not be allowed (see above). Fix that "
            "and run `posting_fetch.py --set on` again." % KEY)
        return 1
    try:
        write_notice_row(root, notice_value)
        write_key(root, "on")
    except ValueError as e:
        out("posting_fetch: REFUSED -- %s. %s was not turned on." % (e, KEY))
        return 1
    out("posting_fetch: on. A LinkedIn role neither the Browser pane nor Claude in Chrome could read is now read from its public "
        "posting (at most %d per run). Turn it off with `posting_fetch.py --set off`." % POSTING_FETCH_CAP)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Set the logged-out LinkedIn posting fetch: automatic (the default), on, or off.")
    ap.add_argument("--set", dest="value", metavar="on|auto|off", required=True,
                    help="on: print the terms, allow www.linkedin.com for the command sandbox, then turn search.posting_fetch "
                         "on. auto: print the terms and remove the key (the automatic fetch; the default). off: turn it off "
                         "(no fetch at all; the sandbox entry stays). Each writes the notice row.")
    args = ap.parse_args(argv)
    return set_key(_root.profile_root(), args.value.strip().lower())


if __name__ == "__main__":
    sys.exit(main())
