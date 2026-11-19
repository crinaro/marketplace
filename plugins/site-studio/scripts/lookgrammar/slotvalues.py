"""slotvalues: the value rule of each slot kind -- the URL rule, `srcset`, embed, position and int checks (moved
out of looks.py unchanged, S1b). Slot VALUES are untrusted: each `safe_*` returns the value or raises
`LookError`. `safe_url` is built on `contentmodel.links.url_as_browser_reads` (dev #912, R5N-4)."""

import re
import urllib.parse
from contentmodel.links import url_as_browser_reads, url_scheme
from lookgrammar.errors import LookError


_INTLIT = re.compile(r"^\d{1,6}$")


POSITION_RE = re.compile(r"^[a-z0-9% .-]{1,40}$")      # equals content.POSITION_RE (a test pins it)
EMBED_HOSTS = {"www.youtube-nocookie.com": "/embed/", "player.vimeo.com": "/video/",
               "drive.google.com": "/file/d/"}


# ------------------------------------------------------------------------------------- the URL rule
_BASE_URL = "https://base.invalid/a/"      # a fixed base: a package module's import runs no code (G3), so it is split in classify_url


def url_text(value):
    """`value` as a browser's URL parser reads it before looking for a scheme: leading and trailing C0
    control and space stripped, tab and newline removed (`contentmodel.links.url_as_browser_reads`, the WHATWG
    steps), and a backslash read as a slash, as a browser does for http and https (R5N-4)."""
    return url_as_browser_reads(value).replace("\\", "/")


def classify_url(value):
    """('relative' | 'http' | 'https' | 'mailto' | 'other:<scheme>' | 'off-origin', text). 'relative' means no
    scheme AND, resolved against a fixed base, the result keeps the base's origin (so `//host/x`, `/\\host/x`
    and `\\\\host` are 'off-origin', R5N-4)."""
    seen = url_text(value)
    scheme = url_scheme(seen)
    if scheme is not None:
        return (scheme if scheme in ("http", "https", "mailto") else "other:" + scheme), seen
    base = urllib.parse.urlsplit(_BASE_URL)
    joined = urllib.parse.urlsplit(urllib.parse.urljoin(base.geturl(), seen))
    if (joined.scheme, joined.netloc) != (base.scheme, base.netloc):
        return "off-origin", seen
    return "relative", seen


def safe_url(value, allow_mailto=False, relative_only=False):
    """Return `value` unchanged when a browser would read it as a relative link, or an http(s) link (or
    mailto, when `allow_mailto`); raise LookError otherwise. Decided on the normalised text, as a browser
    reads it (dev #912); what is written into the page is the person's own text. `relative_only` refuses
    every scheme (a literal in a look file, and every `srcset` candidate)."""
    if not isinstance(value, str):
        raise LookError("a url slot needs text, not %s" % type(value).__name__)
    kind, _seen = classify_url(value)
    if kind == "relative":
        return value
    if kind == "off-origin":
        raise LookError("the link %r reads as a link to another host (a protocol-relative or backslash "
                        "form)" % value[:60], fix="make the link relative, such as ../work/ or media/photo.jpg")
    if relative_only:
        raise LookError("the link %r is not relative; a look file may carry only relative links" % value[:60],
                        fix="use a {{url}} slot, or a relative path")
    if kind in ("http", "https") or (kind == "mailto" and allow_mailto):
        return value
    scheme = kind.split(":", 1)[1] if kind.startswith("other:") else kind
    raise LookError("a link may be http(s) or relative%s, not '%s:'" % (", or mailto here" if allow_mailto else "", scheme),
                    fix="use an http(s) or relative link")


def safe_srcset(value):
    """A `srcset` value: comma-separated candidates, each a RELATIVE url with an optional `Nw` or `Nx`
    descriptor. Every candidate is checked (R5N-4: an off-origin second candidate is refused)."""
    if not isinstance(value, str) or not value.strip():
        raise LookError("a srcset slot needs a non-empty list of candidates")
    for cand in value.split(","):
        bits = cand.split()
        if not bits:
            raise LookError("a srcset candidate is empty in %r; remove the stray comma or fill the candidate in" % value[:80])
        safe_url(bits[0], relative_only=True)
        if len(bits) > 2 or (len(bits) == 2 and not re.match(r"^\d+(\.\d+)?[wx]$", bits[1])):
            raise LookError("a srcset candidate %r has a descriptor that is not like 480w or 2x; write a whole number "
                            "followed by w or x" % cand.strip()[:60])
    return value


def safe_embed(value):
    """An https embed address on one of the three embed hosts (`content.video_embed`'s forms), nothing else."""
    if not isinstance(value, str):
        raise LookError("an embed slot needs text")
    seen = url_text(value)
    p = urllib.parse.urlsplit(seen)
    host = (p.hostname or "").lower()
    ok = (p.scheme == "https" and host in EMBED_HOSTS and p.username is None and p.port is None
          and p.path.startswith(EMBED_HOSTS[host]) and seen == value)
    if not ok:
        raise LookError("the embed address %r is not an https YouTube, Vimeo or Google Drive embed" % value[:80],
                        fix="the embed address comes from content.video_embed, never from a look or a person's text")
    return value


def safe_position(value):
    if not isinstance(value, str) or not POSITION_RE.match(value):
        raise LookError("the position %r is not a CSS position such as 'center 30%%'" % (value if isinstance(value, str) else "")[:60],
                        fix="write a CSS position such as center 30%")
    return value


def safe_int(value):
    if isinstance(value, bool):
        raise LookError("an int slot needs a whole number, not a boolean")
    if isinstance(value, int) and 0 <= value <= 999999:
        return str(value)
    if isinstance(value, str) and _INTLIT.match(value):
        return value
    raise LookError("an int slot needs a whole number from 0 to 999999, got %r" % (value,))
