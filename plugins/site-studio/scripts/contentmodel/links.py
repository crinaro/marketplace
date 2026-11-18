"""Where a link may point: the URL as a browser reads it, the href rules, the video hosts and `esc`."""

import html
import re

from contentmodel.errors import ContentError


# ---------------------------------------------------------------- video embeds

_YT = re.compile(r"^https://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
                 r"([A-Za-z0-9_-]{11})(?:[&?#].*)?$")

_VIMEO = re.compile(r"^https://(?:www\.)?vimeo\.com/(\d+)(?:[/?#].*)?$")

_DRIVE = re.compile(r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)(?:/[^\s]*)?$")


def video_embed(url):
    """The iframe `src` for a YouTube, Vimeo or public Google Drive URL, or None."""
    m = _YT.match(url)
    if m:
        return "https://www.youtube-nocookie.com/embed/" + m.group(1)
    m = _VIMEO.match(url)
    if m:
        return "https://player.vimeo.com/video/" + m.group(1)
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
