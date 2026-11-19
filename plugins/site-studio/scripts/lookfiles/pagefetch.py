"""Where derive's pages come from: a folder of built pages, or the person's published pages fetched with the SSRF guard (R5N-15): every
connection pinned to a checked address, every redirect checked against the owned hosts."""

import contextlib
import html.parser
import http.client
import ipaddress
import os
import posixpath
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from lookfiles.refusals import FetchError, LookCommandError


FETCH_PAGES, FETCH_BYTES, FETCH_SECONDS = 40, 2 * 1024 * 1024, 10
ROBOTS_TOKEN = "site-studio"


# ============================================================================================= the fetch (SSRF)
def host_allowed(address):
    """True when `address` (a resolved IP literal) is one a public site is served from. THE test seam: every
    connection, and every redirect, resolves its host and asks this about each answer. Loopback, link-local, private,
    shared (100.64.0.0/10), multicast, unspecified and reserved addresses are refused (R5N-15)."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(ip.is_global) and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local
                                       or ip.is_private or ip.is_unspecified)


def _resolve(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise FetchError("the address %s could not be found; check it, then run derive again" % host, "dns")
    if not infos:
        raise FetchError("the address %s could not be found; check it, then run derive again" % host, "dns")
    for info in infos:
        if not host_allowed(info[4][0]):
            raise FetchError("%s resolves to a private, loopback or link-local address, which derive will not "
                             "fetch; derive from your local build with --build" % host, "blocked")
    return infos[0]


def _pinned_socket(host, port, timeout):
    fam, typ, proto, _cn, addr = _resolve(host, port)
    sock = socket.socket(fam, typ, proto)
    sock.settimeout(timeout)
    sock.connect(addr)
    return sock


class _PinnedHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _pinned_socket(self.host, self.port, self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = _pinned_socket(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTP, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPS, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, owned):
        self.owned = owned

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if target.scheme not in ("http", "https") or (target.hostname or "").lower() not in self.owned:
            raise FetchError("a page redirects away from the hosts you publish on; derive will not follow it. Derive "
                             "from your local build with --build", "redirect")
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def make_opener(owned):
    """The one opener derive fetches with: no proxy, every connection pinned to a checked address, every redirect
    checked against the owned hosts first."""
    proxies = urllib.request.getproxies()
    if any(proxies.get(s) for s in ("http", "https")):
        raise FetchError("a proxy is configured: derive with --build <folder of built pages> (a connection made by a "
                         "proxy cannot be checked here)", "proxy")
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _HTTPHandler(), _HTTPSHandler(),
                                       _Redirects(frozenset(owned)))


def fetch(opener, url, owned, limit=None):
    """GET `url`. Returns (status, content type, bytes or None, final address). A body past `limit` (default
    FETCH_BYTES) is None. Raises FetchError when the address leaves the owned hosts or cannot be reached."""
    limit = FETCH_BYTES if limit is None else limit
    req = urllib.request.Request(url, headers={"User-Agent": "site-studio-derive", "Accept": "text/html"})
    try:
        resp = opener.open(req, timeout=FETCH_SECONDS)
    except urllib.error.HTTPError as e:
        with contextlib.closing(e):
            if (urllib.parse.urlsplit(e.geturl()).hostname or "").lower() not in owned:
                raise FetchError("a page was served from a host you do not publish on; derive stops. Derive from your "
                                 "local build with --build", "redirect")
            body = e.read(limit + 1) if 200 <= e.code < 300 else b""
            return e.code, (e.headers.get("Content-Type") or ""), (None if len(body) > limit else body), e.geturl()
    except FetchError:
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, FetchError):
            raise e.reason
        raise FetchError("%s could not be reached (%s); check your connection, or derive from your local build with "
                         "--build" % (urllib.parse.urlsplit(url).hostname, e.reason.__class__.__name__), "network")
    except (OSError, http.client.HTTPException) as e:
        raise FetchError("%s could not be reached (%s); check your connection, or derive from your local build with "
                         "--build" % (urllib.parse.urlsplit(url).hostname, e.__class__.__name__), "network")
    with contextlib.closing(resp):
        final = resp.geturl()
        if (urllib.parse.urlsplit(final).hostname or "").lower() not in owned:
            raise FetchError("a page was served from a host you do not publish on; derive stops. Derive from your "
                             "local build with --build", "redirect")
        body = resp.read(limit + 1)
        return resp.status, (resp.headers.get("Content-Type") or ""), (None if len(body) > limit else body), final


class _Links(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def _page_key(base_path, path):
    """The key a fetched page is filed under: its path under the site's base, `index.html` for a folder."""
    rel = path[len(base_path):] if path.startswith(base_path) else path.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return rel


def _is_html_path(path):
    last = posixpath.basename(path)
    return path.endswith("/") or "." not in last or last.lower().endswith((".html", ".htm"))


def fetch_pages(start_url, owned, wanted_keys, out):
    """Read the published pages: the start page, then each page the content built (`wanted_keys`, output paths), then
    pages linked from those, to FETCH_PAGES. Returns ({key: html}, [keys never read]). Raises FetchError for the
    refusals R5.4(e) names."""
    opener = make_opener(owned)
    start = urllib.parse.urlsplit(start_url)
    if start.scheme not in ("http", "https") or not start.hostname:
        raise FetchError("%s is not a web address; give an https address, or derive from your local build with --build"
                         % "that" , "url")
    base_path = start.path if start.path.endswith("/") else posixpath.dirname(start.path.rstrip("/")) + "/"
    origin = "%s://%s" % (start.scheme, start.netloc)
    # robots.txt first: 2xx honoured, 404 allows all, anything else refuses
    rstatus, _rt, rbody, _rf = fetch(opener, origin + "/robots.txt", owned, 512 * 1024)
    rules = urllib.robotparser.RobotFileParser()
    if rstatus == 404:
        rules.parse([])
    elif 200 <= rstatus < 300 and rbody is not None:
        rules.parse(rbody.decode("utf-8", "replace").splitlines())
    else:
        raise FetchError("robots.txt answered %s: nothing was fetched; derive from your local build with --build"
                         % rstatus, "robots")

    def allowed(url):
        return rules.can_fetch(ROBOTS_TOKEN, url)

    def url_of(key):
        rel = key[:-len("index.html")] if key.endswith("index.html") else key
        return origin + urllib.parse.urljoin(base_path, rel)

    pages, queue, queued = {}, [], set()
    sstatus, stype, sbody, sfinal = fetch(opener, start_url, owned)
    if not (200 <= sstatus < 300) or "text/html" not in stype.lower() or sbody is None:
        raise FetchError("the start page answered %s (%s), not a page of HTML; check the address, or derive from your "
                         "local build with --build" % (sstatus, (stype or "no type").split(";")[0] or "no type"), "start")
    if not allowed(sfinal):
        raise FetchError("robots.txt asks robots not to read the start page: nothing was fetched; derive from your "
                         "local build with --build", "robots")
    pages[_page_key(base_path, urllib.parse.urlsplit(sfinal).path)] = sbody.decode("utf-8", "replace")
    queued.add(sfinal)
    disallowed = [k for k in wanted_keys if not allowed(url_of(k))]
    if disallowed:
        raise FetchError("robots.txt asks robots not to read %d of the pages your content built: nothing more was "
                         "fetched; derive from your local build with --build" % len(disallowed), "robots")
    for k in wanted_keys:
        u = url_of(k)
        if u not in queued:
            queued.add(u)
            queue.append(u)
    i = 0
    while i < len(queue) and len(pages) < FETCH_PAGES:
        url = queue[i]
        i += 1
        st, ty, body, final = fetch(opener, url, owned)
        if not (200 <= st < 300) or "text/html" not in ty.lower() or body is None:
            continue
        parts = urllib.parse.urlsplit(final)
        key = _page_key(base_path, parts.path)
        if key in pages:
            continue
        text = body.decode("utf-8", "replace")
        pages[key] = text
        lp = _Links()
        lp.feed(text)
        for href in lp.hrefs:
            t = urllib.parse.urlsplit(urllib.parse.urljoin(final, href))
            if t.scheme != parts.scheme or (t.hostname or "").lower() != (parts.hostname or "").lower():
                continue
            if not t.path.startswith(base_path) or not _is_html_path(t.path):
                continue
            u = urllib.parse.urlunsplit((t.scheme, t.netloc, t.path, "", ""))
            if u not in queued and allowed(u):
                queued.add(u)
                queue.append(u)
    never = [k for k in wanted_keys if k not in pages]
    return pages, never


# ========================================================================================== reading the pages
def read_build_dir(path):
    """{key: html} for every page under `path` (a folder of built pages). A page larger than the fetch cap is skipped."""
    if not os.path.isdir(path):
        raise LookCommandError("%s is not a folder; give the folder your site was built into" % path)
    pages = {}
    for d, _dirs, names in os.walk(path):
        for n in sorted(names):
            if n.lower().endswith((".html", ".htm")):
                full = os.path.join(d, n)
                if os.path.getsize(full) > FETCH_BYTES:
                    continue
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                with open(full, "rb") as fh:
                    pages[rel] = fh.read().decode("utf-8", "replace")
    if not pages:
        raise LookCommandError("%s holds no HTML page; give the folder your site was built into" % path)
    return pages
