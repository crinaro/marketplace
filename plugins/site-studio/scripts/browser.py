#!/usr/bin/env python3
"""browser.py -- site-studio's whole browser layer: a Chrome DevTools client over the pipe transport,
plus the small local web server every browser script uses (dev #835; design 5.1 ADR-001 and 5.2;
named changes M3, M8). Python 3.9, standard library only. Nothing here installs anything.

WHY THIS FILE EXISTS (ADR-001, accepted: option A). The marketplace rule is Python 3.9+, stdlib
only. The browser is driven over `--remote-debugging-pipe` with a ~300-line client we own, instead of
Node + Playwright, so a person's install is git, `gh` and Chrome. P-1 (tests/probes/P1-RESULT.md)
measured that this works on a Mac with Chrome 157; the CI and cloud legs are owner/coordinator runs.

THE CONTRACT (design 5.1; the callers: resize.py, render.py, capture.py, resume_pdf.py)
    find_chrome() -> path | None            CHROME_PATH, the two Mac app paths, then PATH names
    require_chrome() -> path                raises ChromeNotFound (a loud refusal, never a skip)
    Browser()    a context manager; one fresh temporary profile per launch; .version is the Chrome
                 product string ("Chrome/157.0.8103.79"), recorded in every capture and PDF packet
    Browser.new_page(width, height, scale, dark) -> Page
    Page.goto(url)  Page.evaluate(js)  Page.screenshot()  Page.pdf(paper)  Page.content_size()
    Page.network()  Page.scroll_through()
    LocalServer(directory, base=, routes=)  127.0.0.1 only, ephemeral port, optional base path
    launch_flags(profile, platform, env, euid) -> (flags, no_sandbox_case)   pure, tested

TRANSPORT. `subprocess.Popen([chrome, *flags], pass_fds=(3, 4))`. The parent's two pipe ends are
first moved above fd 20 (F_DUPFD_CLOEXEC) so the child's `dup2` onto fds 3 (commands in) and 4
(events out) cannot collide with them; the dup2 runs in `preexec_fn` and `pass_fds=(3, 4)` keeps
the results across `close_fds`. Each message is JSON terminated by NUL; reads use `select`.
`pass_fds` and `fcntl` are POSIX-only, which is one reason Windows is refused (below).
(preexec_fn runs two `os.dup2` calls and nothing else. The interpreter's documentation warns that
preexec_fn is unsafe with threads; the local server is a thread, but the child touches no lock or
allocator before exec, and every launch in tests/ runs beside a live server without trouble.)

THE METHOD SURFACE, in full (design 5.1): Target.createTarget, Target.attachToTarget (flatten: true,
then every page command carries sessionId), Page.enable, Page.setLifecycleEventsEnabled,
Page.navigate, Emulation.setDeviceMetricsOverride, Emulation.setEmulatedMedia, Page.getLayoutMetrics,
Page.captureScreenshot, Page.printToPDF, Network.enable (+ loadingFinished.encodedDataLength),
Runtime.evaluate, Browser.close; Browser.getVersion for the version. Nothing else is called.

TWO MEASURED FACTS (P-1, 2026-11-12, both in tests/probes/P1-RESULT.md)
  1. A new target starts at about:blank, which fires its own `load` and `networkIdle`. The wait after
     Page.navigate matches the navigation's `loaderId`, or it returns before the page has loaded.
  2. `captureBeyondViewport: true` with NO clip captures the whole document; with the flag off it
     is the viewport alone. (A clip taller than the viewport extends the capture whatever the flag
     says, so this client passes no clip.)

LAUNCH FLAGS, per environment (design 5.1, OURS policy; flags from Puppeteer's defaults):
    every launch   --headless --remote-debugging-pipe --user-data-dir=<fresh temp dir>
                   --no-first-run --no-default-browser-check --hide-scrollbars
                   (--hide-scrollbars: a classic, non-overlay scrollbar, which Linux Chrome draws
                   and macOS does not, takes 15 px of layout width, so a 390 px phone render laid
                   out at 375 and media queries saw the wrong width; CI run 43468467791. Phones use
                   overlay scrollbars, so hiding them is the faithful render on every OS. It is
                   one of Puppeteer's default arguments.)
    macOS          --use-mock-keychain          (a fresh profile never prompts for the keychain)
    Linux          --password-store=basic --disable-dev-shm-usage
    --no-sandbox   ONLY (a) in a cloud session (CLAUDE_CODE_REMOTE=true) running as root, a
                   disposable VM; or (b) in CI (GITHUB_ACTIONS=true), where only the local fixture
                   is loaded. On a person's own machine it is NEVER added: if Chrome there cannot
                   start with its sandbox (root, or a Linux user-namespace restriction) the launch is
                   refused naming the cause. `Browser.no_sandbox` is None, "cloud" or "ci"; capture.py
                   refuses a non-local URL under "ci" and prints that it ran without the sandbox
                   under "cloud".

CHROME IS FOUND, in order (design 5.2): `CHROME_PATH`; /Applications/Google Chrome.app/...;
~/Applications/Google Chrome.app/... (a Mac user without admin rights); `google-chrome`,
`google-chrome-stable`, `chromium`, `chromium-browser` on PATH. A `CHROME_PATH` that is set but is
not an executable file is a refusal that names it (2026-11-12 decision: an explicit setting that
points nowhere must not be silently replaced by another browser). Every launch uses a fresh
temporary profile, never the person's logged-in browser and never the desktop app's pane.

WINDOWS is unsupported in 0.1.0: `os.name == "nt"` is checked first, everywhere, and refuses in one
sentence. Nothing else runs.

Never `file://` for a canvas: a canvas that draws a file:// image is tainted (P-1 item h). Callers
serve what they draw through `LocalServer`.
"""
import base64
import errno
import hashlib
import http.server
import json
import mimetypes
import os
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

WINDOWS_REFUSAL = "site-studio 0.1.0 runs on macOS and Linux; Windows is not supported yet."
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MAC_CHROME_HOME = "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
LOAD_TIMEOUT = 45          # the design's cap, for `load` and then `networkIdle`
PAPERS = {"Letter": (8.5, 11.0), "A4": (8.27, 11.69)}   # inches, for Page.printToPDF


class BrowserError(RuntimeError):
    """Every refusal or failure of this layer; the message is for the person."""


class ChromeNotFound(BrowserError):
    pass


def refuse_windows():
    if os.name == "nt":
        raise BrowserError(WINDOWS_REFUSAL)


# ---------------------------------------------------------------------------------------------
# finding Chrome
# ---------------------------------------------------------------------------------------------

def _is_exe(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def lookup_chrome(env=None, which=None, is_exe=None):
    """(path, why): the path found, or None and the reason, so a caller can name it."""
    refuse_windows()
    env = os.environ if env is None else env
    which = which or (lambda n: shutil.which(n, path=env.get("PATH")))
    is_exe = is_exe or _is_exe
    explicit = env.get("CHROME_PATH")
    if explicit:
        if is_exe(explicit):
            return explicit, None
        return None, "Chrome not found: CHROME_PATH is set to %s, which is not an executable file" % explicit
    for cand in (MAC_CHROME, os.path.expanduser(MAC_CHROME_HOME)):
        if is_exe(cand):
            return cand, None
    for name in PATH_NAMES:
        found = which(name)
        if found:
            return found, None
    return None, ("Chrome not found: not in CHROME_PATH, not under /Applications or ~/Applications, "
                  "and none of %s is on PATH" % ", ".join(PATH_NAMES))


def find_chrome(env=None, which=None, is_exe=None):
    return lookup_chrome(env, which, is_exe)[0]


def require_chrome(env=None, which=None, is_exe=None):
    path, why = lookup_chrome(env, which, is_exe)
    if path is None:
        raise ChromeNotFound("%s. Install Google Chrome (or Chromium on Linux), or set CHROME_PATH to "
                             "it; /site-studio:setup says how. Photos and page captures need Chrome."
                             % why)
    return path


# ---------------------------------------------------------------------------------------------
# launch flags (pure)
# ---------------------------------------------------------------------------------------------

def launch_flags(profile, platform=None, env=None, euid=None):
    """(flags, no_sandbox) for a launch with the profile dir `profile`. `no_sandbox` is None,
    "cloud" or "ci": see the module docstring. Pure, so the policy is tested without Chrome."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if euid is None:
        euid = os.geteuid() if hasattr(os, "geteuid") else 1
    flags = ["--headless", "--remote-debugging-pipe", "--user-data-dir=" + profile,
             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars"]
    if platform == "darwin":
        flags.append("--use-mock-keychain")
    else:
        flags += ["--password-store=basic", "--disable-dev-shm-usage"]
    case = None
    if env.get("CLAUDE_CODE_REMOTE") == "true" and euid == 0:
        case = "cloud"
    elif env.get("GITHUB_ACTIONS") == "true":
        case = "ci"
    if case:
        flags.append("--no-sandbox")
    return flags, case


def _start_failure(code, stderr_text, euid):
    """The refusal for a Chrome that did not come up, naming the cause where it is knowable."""
    low = (stderr_text or "").lower()
    last = ""
    for line in (stderr_text or "").splitlines():
        if line.strip():
            last = line.strip()
    if euid == 0 or "running as root" in low:
        why = ("you are running as root, and Chrome will not start its sandbox as root; run site-studio "
               "as your normal user (site-studio never turns the sandbox off on your own machine)")
    elif "sandbox" in low or "namespace" in low or "no usable" in low:
        why = ("Chrome could not start its sandbox here (a Linux user-namespace restriction, such as "
               "AppArmor or kernel.unprivileged_userns_clone=0); site-studio never turns the sandbox "
               "off on your own machine, so allow unprivileged user namespaces or use a different machine")
    else:
        why = "Chrome exited at start-up (exit code %s)" % code
    return BrowserError("Chrome would not start: %s.%s" % (why, (" Chrome said: " + last[:200]) if last else ""))


# ---------------------------------------------------------------------------------------------
# the client
# ---------------------------------------------------------------------------------------------

def _high_fd(fd):
    import fcntl
    return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 20)


class Browser(object):
    """One Chrome process on a fresh temporary profile. Use as a context manager."""

    def __init__(self, chrome=None, env=None, platform=None, euid=None, startup_timeout=20):
        refuse_windows()
        self.env = os.environ if env is None else env
        self.exe = chrome or require_chrome(self.env)
        self.platform = sys.platform if platform is None else platform
        self.euid = euid if euid is not None else (os.geteuid() if hasattr(os, "geteuid") else 1)
        self.startup_timeout = startup_timeout
        self.profile = None
        self.proc = None
        self.version = None          # "Chrome/157.0.8103.79"
        self.user_agent = None
        self.flags = None            # the launch flags, without the profile path
        self.no_sandbox = None       # None, "cloud" or "ci"
        self._w = self._r = None
        self._buf = b""
        self._events = []
        self._id = 0
        self._stderr = None

    # -- lifecycle --------------------------------------------------------------------------
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def start(self):
        self.profile = tempfile.mkdtemp(prefix="site-studio-chrome-")
        flags, self.no_sandbox = launch_flags(self.profile, self.platform, self.env, self.euid)
        self.flags = [f for f in flags if not f.startswith("--user-data-dir=")]
        r_cmd, w_cmd = os.pipe()          # parent writes w_cmd; the child reads it as fd 3
        r_evt, w_evt = os.pipe()          # the child writes fd 4; the parent reads r_evt
        child_r, child_w = _high_fd(r_cmd), _high_fd(w_evt)
        os.close(r_cmd)
        os.close(w_evt)

        def child_setup():
            os.dup2(child_r, 3)
            os.dup2(child_w, 4)

        self._stderr = tempfile.TemporaryFile()
        try:
            self.proc = subprocess.Popen([self.exe] + flags, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=self._stderr,
                                         pass_fds=(3, 4), preexec_fn=child_setup, env=dict(self.env))
        except OSError as e:
            for fd in (child_r, child_w, w_cmd, r_evt):
                os.close(fd)
            self._cleanup_profile()
            raise BrowserError("could not start Chrome at %s: %s" % (self.exe, e.strerror or e))
        os.close(child_r)
        os.close(child_w)
        self._w, self._r = w_cmd, r_evt
        try:
            v = self.send("Browser.getVersion", timeout=self.startup_timeout)
        except BrowserError:
            code = self.proc.poll()
            if code is None:
                try:
                    code = self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    code = None
            self._stderr.seek(0)
            text = self._stderr.read().decode("utf-8", "replace")
            self._teardown(kill=True)
            if code is None:
                raise BrowserError("Chrome did not answer within %d seconds" % self.startup_timeout)
            raise _start_failure(code, text, self.euid)
        self.version = (v.get("product") or "").strip() or "Chrome/unknown"
        self.user_agent = v.get("userAgent")
        return self

    def packet(self):
        """What every capture and PDF packet records about the browser (named change M8): a later
        Chrome version change then shows."""
        return {"chrome": self.version, "platform": self.platform}

    def close(self):
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self.send("Browser.close", timeout=5)
        except BrowserError:
            pass
        self._teardown(kill=False)

    def _teardown(self, kill):
        p = self.proc
        if p is not None:
            if kill and p.poll() is None:
                p.kill()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for fd in (self._w, self._r):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._w = self._r = None
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None
        self._cleanup_profile()
        self.proc = None

    def _cleanup_profile(self):
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None

    # -- the wire ---------------------------------------------------------------------------
    def _next_message(self, timeout):
        end = time.time() + timeout
        while True:
            if b"\0" in self._buf:
                raw, self._buf = self._buf.split(b"\0", 1)
                return json.loads(raw.decode("utf-8"))
            left = end - time.time()
            if left <= 0:
                return None
            rl, _, _ = select.select([self._r], [], [], min(left, 0.5))
            if rl:
                try:
                    chunk = os.read(self._r, 262144)
                except OSError as e:
                    raise BrowserError("lost the connection to Chrome: %s" % e)
                if not chunk:
                    raise BrowserError("Chrome closed the connection")
                self._buf += chunk

    def send(self, method, params=None, session=None, timeout=30):
        if self._w is None:
            raise BrowserError("the browser is not running")
        self._id += 1
        mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        try:
            os.write(self._w, json.dumps(msg).encode("utf-8") + b"\0")
        except OSError as e:
            if e.errno == errno.EPIPE:
                raise BrowserError("Chrome closed the connection")
            raise
        end = time.time() + timeout
        while True:
            m = self._next_message(max(0.05, end - time.time()))
            if m is None:
                if time.time() >= end:
                    raise BrowserError("Chrome did not answer %s within %d seconds" % (method, timeout))
                continue
            if m.get("id") == mid:
                if "error" in m:
                    raise BrowserError("%s failed: %s" % (method, m["error"].get("message", m["error"])))
                return m.get("result", {})
            if "method" in m:
                self._events.append(m)

    def wait_event(self, method, session=None, pred=None, timeout=LOAD_TIMEOUT):
        end = time.time() + timeout
        while True:
            for i, e in enumerate(self._events):
                if e["method"] == method and (session is None or e.get("sessionId") == session) \
                        and (pred is None or pred(e)):
                    return self._events.pop(i)
            m = self._next_message(max(0.05, end - time.time()))
            if m is None:
                if time.time() >= end:
                    return None
                continue
            if "method" in m:
                self._events.append(m)

    def drain(self, session):
        """Every pending event of one session, removed and returned in order."""
        mine = [e for e in self._events if e.get("sessionId") == session]
        self._events = [e for e in self._events if e.get("sessionId") != session]
        return mine

    # -- pages ------------------------------------------------------------------------------
    def new_page(self, width=None, height=800, scale=1, dark=None):
        tid = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        page = Page(self, sid)
        self.send("Page.enable", session=sid)
        self.send("Page.setLifecycleEventsEnabled", {"enabled": True}, session=sid)
        self.send("Network.enable", session=sid)
        if width:
            page.set_viewport(width, height, scale)
        if dark is not None:
            page.set_dark(dark)
        return page


class Page(object):
    def __init__(self, browser, session):
        self.b = browser
        self.sid = session
        self.idle = None             # did networkIdle arrive within the cap, for the last goto
        self.status = None           # HTTP status of the main document, for the last goto
        self.url = None
        self._net = {}               # requestId -> {"url", "bytes"}
        self._loader = None

    def _send(self, method, params=None, timeout=30):
        return self.b.send(method, params, session=self.sid, timeout=timeout)

    def set_viewport(self, width, height=800, scale=1):
        self._send("Emulation.setDeviceMetricsOverride", {"width": int(width), "height": int(height),
                                                           "deviceScaleFactor": scale, "mobile": False})

    def set_dark(self, dark):
        self._send("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-color-scheme", "value": "dark" if dark else "light"}]})

    def goto(self, url, timeout=LOAD_TIMEOUT):
        """Navigate and wait for `load`, then `networkIdle` (the design's 45-second cap on each).
        A load that does not come in time raises; a networkIdle that does not just sets
        `self.idle` False. Sets `self.status`."""
        self.b.drain(self.sid)
        self._net = {}
        self.status = None
        nav =self._send("Page.navigate", {"url": url}, timeout=timeout)
        if nav.get("errorText"):
            raise BrowserError("could not load %s: %s" % (url, nav["errorText"]))
        loader = nav.get("loaderId")

        def life(name):
            return lambda e: e["params"].get("name") == name and (
                loader is None or e["params"].get("loaderId") == loader)
        if self.b.wait_event("Page.lifecycleEvent", self.sid, life("load"), timeout) is None:
            raise BrowserError("%s did not finish loading within %d seconds" % (url, timeout))
        self.idle = self.b.wait_event("Page.lifecycleEvent", self.sid, life("networkIdle"), timeout) is not None
        self.url = url
        self._loader = loader
        self._collect_network(loader)
        return self

    def _collect_network(self, loader):
        for e in self.b.drain(self.sid):
            m, p = e["method"], e.get("params", {})
            if m == "Network.requestWillBeSent":
                self._net[p["requestId"]] = {"url": p["request"]["url"], "bytes": 0}
            elif m == "Network.responseReceived":
                if p.get("type") == "Document" and p.get("requestId") == loader and self.status is None:
                    self.status = int(p["response"]["status"])
            elif m == "Network.loadingFinished":
                rec = self._net.setdefault(p["requestId"], {"url": "", "bytes": 0})
                rec["bytes"] = int(p.get("encodedDataLength", 0))

    def network(self):
        """{"bytes": total encoded bytes of the last goto, "requests": [(url, bytes)]}. Events that
        arrived after goto returned (a lazy image after the scroll) are folded in on each call."""
        self.b.wait_event("Network.__none__", self.sid, timeout=0.3)   # let late events arrive
        self._collect_network(self._loader)
        reqs = [(r["url"], r["bytes"]) for r in self._net.values() if r["url"]]
        return {"bytes": sum(b for _u, b in reqs), "requests": reqs}

    def evaluate(self, expression, timeout=30):
        r = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                            "awaitPromise": True}, timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            text = (d.get("exception") or {}).get("description") or d.get("text") or "script error"
            raise BrowserError("the page script failed: %s" % text.splitlines()[0][:300])
        return r.get("result", {}).get("value")

    def content_size(self):
        lm = self._send("Page.getLayoutMetrics")
        s = lm.get("cssContentSize") or lm.get("contentSize")
        return int(round(s["width"])), int(round(s["height"]))

    def screenshot(self, full=True, fmt="png", quality=None, timeout=60):
        """Image bytes. `full` (the default): the whole document, captureBeyondViewport true and no
        clip (P-1 item d). `full=False`: the viewport alone (a card image). `fmt` png or jpeg."""
        params = {"format": fmt, "captureBeyondViewport": bool(full)}
        if quality is not None and fmt in ("jpeg", "webp"):
            params["quality"] = int(quality)
        r = self._send("Page.captureScreenshot", params, timeout=timeout)
        return base64.b64decode(r["data"])

    def pdf(self, paper="Letter", timeout=60):
        if paper not in PAPERS:
            raise BrowserError("paper must be Letter or A4, not %r" % (paper,))
        w, h = PAPERS[paper]
        r = self._send("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": False,
                                           "paperWidth": w, "paperHeight": h,
                                           "displayHeaderFooter": False}, timeout=timeout)
        return base64.b64decode(r["data"])

    def scroll_through(self, step=600, pause=0.08, limit=200):
        """One slow scroll from the top to the bottom, so lazy images load, then back to the top.
        Returns the number of steps taken."""
        n = 0
        while n < limit:
            more = self.evaluate("(function(){var y=window.scrollY,h=document.documentElement.scrollHeight,"
                                 "v=window.innerHeight;window.scrollBy(0,%d);return y+v<h-1;})()" % step)
            n += 1
            time.sleep(pause)
            if not more:
                break
        self.evaluate("window.scrollTo(0,0)")
        return n


# ---------------------------------------------------------------------------------------------
# the local server
# ---------------------------------------------------------------------------------------------

_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
          ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
          ".gif": "image/gif", ".pdf": "application/pdf", ".xml": "application/xml",
          ".txt": "text/plain; charset=utf-8", ".ico": "image/x-icon"}


def _ctype(path):
    ext = os.path.splitext(path)[1].lower()
    return _TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


class LocalServer(object):
    """A `http.server` bound to 127.0.0.1 on an ephemeral port (or `port`), serving `directory` under `base`
    (for example "site": the page is then at http://127.0.0.1:PORT/site/), plus in-memory `routes`
    ({"/path": (content_type, bytes)}). A missing path answers the directory's 404.html with status
    404, as GitHub Pages does. `requests` records (path, status) for tests. Bound to loopback only:
    the constructor refuses anything else."""

    def __init__(self, directory=None, base="", routes=None, host="127.0.0.1", port=0):
        if host != "127.0.0.1":
            raise BrowserError("the local server binds to 127.0.0.1 only")
        self.directory = os.path.realpath(directory) if directory else None
        self._want_port = int(port)
        self.base = base.strip("/")
        self.routes = dict(routes or {})
        self.requests = []
        self._httpd = None
        self._thread = None
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, status, ctype, body, extra=None, head=False):
                outer.requests.append((self.path, status))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if not head:
                    self.wfile.write(body)

            def _serve(self, head):
                path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                if path in outer.routes:
                    ctype, body = outer.routes[path]
                    return self._send(200, ctype, body, head=head)
                rel = path
                if outer.base:
                    prefix = "/" + outer.base
                    if path == "/" or path == prefix:
                        return self._send(301, "text/plain", b"", {"Location": prefix + "/"}, head)
                    if not path.startswith(prefix + "/"):
                        return self._not_found(head)
                    rel = path[len(prefix):]
                if outer.directory is None:
                    return self._not_found(head)
                full = os.path.realpath(os.path.join(outer.directory, *[p for p in rel.split("/") if p]))
                if full != outer.directory and not full.startswith(outer.directory + os.sep):
                    return self._not_found(head)
                if os.path.isdir(full):
                    full = os.path.join(full, "index.html")
                if not os.path.isfile(full):
                    return self._not_found(head)
                with open(full, "rb") as fh:
                    body = fh.read()
                self._send(200, _ctype(full), body, head=head)

            def _not_found(self, head):
                page = os.path.join(outer.directory, "404.html") if outer.directory else None
                if page and os.path.isfile(page):
                    with open(page, "rb") as fh:
                        return self._send(404, "text/html; charset=utf-8", fh.read(), head=head)
                self._send(404, "text/plain; charset=utf-8", b"not found", head=head)

            def do_GET(self):
                self._serve(False)

            def do_HEAD(self):
                self._serve(True)

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

        self._server_cls, self._handler = Server, Handler

    def start(self):
        self._httpd = self._server_cls(("127.0.0.1", self._want_port), self._handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False

    @property
    def origin(self):
        return "http://127.0.0.1:%d" % self.port

    def url(self, path=""):
        """The URL of `path` (relative to the base) on this server."""
        prefix = "/" + self.base if self.base else ""
        return self.origin + prefix + "/" + path.lstrip("/")


def is_local_url(url):
    """True for http(s) URLs on loopback, and file: (capture.py uses it under the CI case)."""
    p = urllib.parse.urlsplit(url)
    return p.scheme in ("http", "https") and (p.hostname or "") in ("127.0.0.1", "localhost", "::1")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    """`python3 browser.py` : find Chrome, launch it, print its version. A check for setup/doctor."""
    try:
        with Browser() as b:
            print("Chrome: %s (%s)" % (b.version, b.exe))
            print("flags: %s%s" % (" ".join(b.flags), "" if not b.no_sandbox else
                                   "  [no sandbox: %s case]" % b.no_sandbox))
        return 0
    except BrowserError as e:
        print("browser: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
