"""sameresource: parity's rule U, "the same resource" (design-adopt-parity-2 section 7.1; root cause E of section 1). Python 3.9,
standard library only. Pure functions over two `{path: bytes}` builds; no I/O, no browser.

A differing pair of URL-bearing attribute values (`href`, `src`, and each candidate of `srcset`) on two paired start tags is NOT
VISIBLE when one of these holds (the hunk is then classed `markup`, as a class-only difference is, by `parity_classes._pair_tokens`):

    U-a  the same address: both resolve, from the page's own path, to the same path, query and fragment. A root-absolute address
         (`/x`), and an absolute one on the site's own host when the caller names that host, is read under the BUILD'S OWN PATH:
         inside it, `/<path>/site.css` is `site.css` at the root of the build; outside it, the address is never the same as
         anything in the build. Each build is read under its own path: the plugin's under the configured path
         (`preview.base_path`), the old build's under `build_path(old files, configured path)`.
    U-b  a version in the query: the same path and fragment, only the query differs, the path is a stylesheet or a script, and
         the file at that path has equal bytes in both builds in parity's own normal form (`normal`, `parity_classes.normalise_file`).
    U-c  the same bytes at another address: two different same-site paths, the same query and fragment, whose files have equal
         bytes, each in its own build.

What U never does: an address the old build served and the plugin's does not stays its own visible difference (`only-local/<family>`
from `parity_classes.compare_builds`); U-c hides the changed attribute, never the vanished file. Everything else about a URL stays
visible: another host, another scheme (`mailto:`, `data:`), a `<base href>` (it moves every other address), an address outside
the build's path, a srcset whose candidates differ in number or descriptor. And as for a class token (rules 4 and 5 of
`parity_classes`): while either build's CSS selects on the attribute (`[href`), uses `attr(`, a script names the attribute, or
anything is loaded off-origin, no URL difference is invisible. That errs toward visible (the module's rule, dated 2026-11-20:
section 7.1 is silent on what can read the attribute's text; this reads it as section 7.1's "as a class-only difference is").

    build_path(files, configured)   the path a build's own output assumes (section 7.3; step 9b's `shots.py` calls it)
    resolve(page, address, path)    one address as (path in the build, query, fragment), OUTSIDE, or None
    Reading(local, plugin, ...)     the two builds read each under its own path; `.same(...)` is rule U for one pair
"""

import html.parser
import re
import urllib.parse

URL_ATTRS = ("href", "src", "srcset")
OUTSIDE = ("outside",)          # a same-site address that lies outside the build's path: never the same as anything in it
_STYLE_OR_SCRIPT = (".css", ".js", ".mjs", ".cjs")      # parity_classes' `style` and `script` families
_HOST = "site.invalid"          # a stand-in host for the join; never reaches an output
_ATTR_SELECTOR = dict((a, re.compile(r"\[\s*%s(?![\w-])" % a, re.I)) for a in URL_ATTRS)
_ATTR_SCRIPT = dict((a, re.compile(r"(?<![\w-])%s(?![\w-])" % a)) for a in URL_ATTRS)
_ATTR_FUNCTION = re.compile(r"\battr\s*\(", re.I)


def _strip(path):
    """A path in `preview.base_path`'s form: no leading or trailing slash, `""` for the root; None is the root."""
    return (path or "").strip("/")


def resolve(page, address, path, host=None):
    """One address as the build reads it, from the page at `page` (a key of the build, `work/index.html`) of a build served under
    `path` (`preview.base_path`'s form). Returns `(path in the build, query, fragment)`; OUTSIDE for a root-absolute or own-host
    address, or a relative one that climbs, outside the build's path; None for an address that is not the site's at all (another
    host, a scheme other than http and https, a protocol-relative address on another host). `host` is the site's own host, when
    known; without it an absolute `https:` address is never the site's."""
    s = urllib.parse.urlsplit((address or "").strip())
    if s.scheme or s.netloc:
        if not (host and s.scheme in ("http", "https", "") and s.netloc.lower() == host.lower()):
            return None
        address = urllib.parse.urlunsplit(("", "", s.path or "/", s.query, s.fragment))
    base = "/" + (_strip(path) + "/" if _strip(path) else "")
    joined = urllib.parse.urlsplit(urllib.parse.urljoin("http://%s%s%s" % (_HOST, base, page), address))
    full = joined.path or "/"
    if full == base.rstrip("/"):
        full = base
    if not full.startswith(base):
        return OUTSIDE
    return (full[len(base):], joined.query, joined.fragment)


def file_for(path, files):
    """The file of `files` a server answers `path` with (a directory is its `index.html`), or None."""
    if path in files and not path.endswith("/"):
        return path
    cand = (path + "index.html") if (path == "" or path.endswith("/")) else (path + "/index.html")
    return cand if cand in files else None


class _Addresses(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        self.found.extend(v for k, v in attrs if k in ("href", "src") and v)

    handle_startendtag = handle_starttag


def _root_addresses(files, host=None):
    """[(page, address)]: every root-absolute (or own-host) `href` and `src` of every page of a build."""
    out = []
    for page in sorted(files):
        if not page.lower().endswith((".html", ".htm")):
            continue
        p = _Addresses()
        p.feed(files[page].decode("utf-8", "replace"))
        p.close()
        for a in p.found:
            s = urllib.parse.urlsplit(a.strip())
            own = bool(host) and s.scheme in ("http", "https") and s.netloc.lower() == host.lower()
            if own or (not s.scheme and not s.netloc and s.path.startswith("/")):
                out.append((page, a))
    return out


def build_path(files, configured, host=None):
    """The path a build's own output assumes, in `preview.base_path`'s form (no slashes, `""` the root), the form
    `browser.LocalServer(base=...)` and `render.py --base` take. Stable signature: step 9b's `shots.py` calls it to serve the old
    build where its own pages load, and parity calls it to read the old build's addresses (rule U-a).

    `files` is a build (`{path: bytes}`); `configured` is the path the plugin's build is served under (`preview.base_path` of the
    converted `site.json`; None is the root); `host`, optional, is the site's own host. Of the two candidates, `configured` and the
    root, the one under which MORE of the build's root-absolute (and own-host) `href` and `src` addresses resolve to a file the
    build holds. A tie, or a build with no such address, is `configured`: a build whose addresses are all relative loads the same
    under any path."""
    configured = _strip(configured)
    if not configured:
        return ""
    found = _root_addresses(files, host)
    if not found:
        return configured

    def hits(path):
        n = 0
        for page, a in found:
            r = resolve(page, a, path, host)
            if r is not None and r is not OUTSIDE and file_for(r[0], files) is not None:
                n += 1
        return n
    return "" if hits("") > hits(configured) else configured


def srcset_candidates(value):
    """[(url, descriptor)] of a `srcset` value (the HTML parsing steps, without their error recovery): a URL runs to the next
    whitespace and loses its trailing commas; a descriptor runs to the next comma."""
    out, i, v = [], 0, value or ""
    while i < len(v):
        while i < len(v) and (v[i].isspace() or v[i] == ","):
            i += 1
        j = i
        while j < len(v) and not v[j].isspace():
            j += 1
        url = v[i:j]
        trailing = len(url) - len(url.rstrip(","))
        url = url.rstrip(",")
        i = j
        desc = ""
        if not trailing:
            k = v.find(",", i)
            k = len(v) if k < 0 else k
            desc, i = " ".join(v[i:k].split()), k
        if url:
            out.append((url, desc))
    return out


class Reading(object):
    """The two builds, each read under its own path. `local` is the old builder's output, `plugin` the plugin's; `site_path` is
    the path the plugin's build is served under (`preview.base_path`; None is the root); `host` the site's own host, when known;
    `normal(path, bytes)` parity's normal form of a file (U-b), raw bytes when not given."""

    def __init__(self, local, plugin, site_path=None, host=None, normal=None):
        self.local, self.plugin, self.host = local, plugin, host
        self.normal = normal or (lambda _p, data: data)
        self.plugin_path = _strip(site_path)
        self.local_path = build_path(local, site_path, host)

    def _one(self, page, a, b):
        if a == b:
            return True
        ra, rb = resolve(page, a, self.local_path, self.host), resolve(page, b, self.plugin_path, self.host)
        if ra is None or rb is None or ra is OUTSIDE or rb is OUTSIDE:
            return False
        if ra == rb:                                                                    # U-a
            return True
        fa, fb = file_for(ra[0], self.local), file_for(rb[0], self.plugin)
        if fa is None or fb is None or ra[2] != rb[2]:
            return False
        if ra[0] == rb[0]:                                                              # U-b
            return (fa.lower().endswith(_STYLE_OR_SCRIPT) and
                    self.normal(fa, self.local[fa]) == self.normal(fb, self.plugin[fb]))
        return ra[1] == rb[1] and self.local[fa] == self.plugin[fb]                     # U-c

    def same(self, page, element, attr, a, b, css=(), js=(), external=False):
        """Rule U for one pair: True when the `attr` values `a` (the old build's) and `b` (the plugin's) of the paired `element`
        on `page` name the same resource, so the difference is one no visitor meets. `css` and `js` are the texts of both builds'
        stylesheets and scripts and `external` whether either loads anything off-origin: any of those that can read the
        attribute's text makes the difference visible (module docstring)."""
        if attr not in URL_ATTRS or element == "base" or a is None or b is None or external:
            return False
        if any(_ATTR_SELECTOR[attr].search(t) or _ATTR_FUNCTION.search(t) for t in css):
            return False
        if any(_ATTR_SCRIPT[attr].search(t) for t in js):
            return False
        if attr != "srcset":
            return self._one(page, a, b)
        ca, cb = srcset_candidates(a), srcset_candidates(b)
        if not ca or len(ca) != len(cb) or [d for _u, d in ca] != [d for _u, d in cb]:
            return False
        return all(self._one(page, ua, ub) for (ua, _d), (ub, _e) in zip(ca, cb))
