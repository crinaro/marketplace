"""Where a link may point: the URL as a browser reads it, the href rules, the video hosts and `esc`."""

import html
import re

from contentmodel.errors import ContentError


# ---------------------------------------------------------------- video embeds

_YT = re.compile(r"^https://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
                 r"([A-Za-z0-9_-]{11})(?:[&?#].*)?$")

_VIMEO = re.compile(r"^https://(?:www\.)?vimeo\.com/(\d+)(?:[/?#].*)?$")

_DRIVE = re.compile(r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)(?:/[^\s]*)?$")


# The private code of an unlisted Vimeo video (design-reference-layout section 2, dev 1060): 6 to 64 ASCII letters and digits holding a
# digit. Deliberately wide, and OURS: the form is documented nowhere readable; `comments` and `likes` hold no digit, so they are not one.
_VIMEO_CODE = re.compile(r"(?=[A-Za-z]*[0-9])[A-Za-z0-9]{6,64}")


def _vimeo_parts(url):
    """(the code the rule reads or None, whether the link holds a trailing segment or an `h` the rule does not read) for a vimeo.com
    link, None for any other URL. The code is the first path segment after the id, else the `h` parameter; the fragment is dropped."""
    m = _VIMEO.match(url)
    if not m:
        return None
    path, _, query = url[m.end(1):].split("#", 1)[0].partition("?")
    segs = [s for s in path.split("/") if s]
    h = [v for k, _, v in (q.partition("=") for q in query.split("&")) if k == "h"]
    seg = segs[0] if segs and _VIMEO_CODE.fullmatch(segs[0]) else None
    hp = h[0] if h and _VIMEO_CODE.fullmatch(h[0]) else None
    h_read = not h or (len(h) == 1 and hp is not None and (seg is None or seg == hp))
    return seg or hp, len(segs) > (1 if seg else 0) or not h_read


def vimeo_hash(url):
    """The private code of an unlisted vimeo.com link (`/<id>/<code>` or `?h=<code>`), or None."""
    parts = _vimeo_parts(url)
    return parts[0] if parts else None


def vimeo_unread(url):
    """True when a vimeo.com link holds a trailing path segment or an `h` that `vimeo_hash` does not read."""
    parts = _vimeo_parts(url)
    return bool(parts and parts[1])


def video_embed(url, keep_hash=False):
    """The iframe `src` for a YouTube, Vimeo or public Google Drive URL, or None. A Vimeo link's private code (`vimeo_hash`) is sent to
    the player as `?h=` only when `keep_hash` is true (the site's `blocks.unlistedVideos`); every caller that does not ask gets 0.8.0's."""
    m = _YT.match(url)
    if m:
        return "https://www.youtube-nocookie.com/embed/" + m.group(1)
    m = _VIMEO.match(url)
    if m:
        code = vimeo_hash(url) if keep_hash else None
        return "https://player.vimeo.com/video/" + m.group(1) + ("?h=" + code if code else "")
    m = _DRIVE.match(url)
    if m:
        return "https://drive.google.com/file/d/%s/preview" % m.group(1)
    return None


# ---------------------------------------------------------------- Markdown subset

def esc(s):
    return html.escape(s, quote=True)


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")

_URL_EDGE = re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")

_URL_TAB_NL = re.compile(r"[\t\n\r]")


def url_as_browser_reads(url):
    """`url` as a browser's URL parser sees it before reading its scheme (WHATWG URL standard, basic URL
    parser): leading and trailing C0 controls and spaces stripped, and ASCII tab and newline removed
    anywhere. A scheme decided on the raw text is not the scheme a click follows: ' javascript:x',
    'java<TAB>script:x' and '<U+0001>javascript:x' all run script (dev #912). Used only to DECIDE; what
    is written into the page is the person's text, unchanged."""
    return _URL_TAB_NL.sub("", _URL_EDGE.sub("", url))


def url_scheme(url):
    """The scheme a browser reads from `url`, lower-cased, or None for a relative or #anchor link."""
    m = _SCHEME.match(url_as_browser_reads(url))
    return m.group(1).lower() if m else None


def check_href(url, where):
    """Refuse a person-supplied link a page may not carry: any scheme but http, https and mailto (read as
    a browser reads it, `url_as_browser_reads`), and a root-absolute path. Every person-supplied URL that
    reaches an `href` goes through here (dev #912)."""
    seen = url_as_browser_reads(url)
    scheme = _SCHEME.match(seen)
    if scheme:
        if scheme.group(1).lower() not in ("http", "https", "mailto"):
            raise ContentError("%s: a link may be http(s), mailto, #anchor or relative, not '%s:'"
                               % (where, scheme.group(1)), fix="use an http(s), mailto, #anchor or relative link")
        return
    if seen.startswith("/"):
        raise ContentError("%s: root-absolute link '%s'; links must be relative so one build serves "
                           "at /<repo>/ and at /" % (where, url), fix="make the link relative, such as ../work/ or media/photo.jpg")


_URL_SCHEME_OR_PROTOREL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
