"""capturing/platforms.py -- what an address says about where a page was seen and what it is (site-studio 0.9.0, dev 1061;
design-reference-layout section 1.5). Python 3.9, standard library only. A literal table, a PROPOSAL only: nothing here is stored
without the person's yes, and an address that matches nothing proposes nothing.

    guess(url)    -> Guess(channel, type, host_kind): the channel and type the address names, else None for each;
                     `host_kind` is "platform", "file" (a host that stores or plays files, so the address cannot say where the
                     page was seen: it never gives a channel) or "unknown"
    host_of(url)  -> the lower-cased host name of an address, or ""

A host matches a row only when it IS the row's host, or is that host behind exactly one of `www.`, `m.`, `mobile.` or a language or
country label (`ll` or `ll-ll`: `fr.linkedin.com`). So `netflix.com` is not `x.com`, `help.instagram.com` matches nothing and
`instagram.com.example.test` is not Instagram. A `*.substack.com` publication is Substack. The words are the starter words
(`configkeys.REFERENCE_TYPES_STARTER`, `REFERENCE_CHANNELS_STARTER`), pinned by test_platforms.py; `Website` is never proposed.
A `type` comes only from a path segment that says so (`reel`, `shorts`, `watch`, and TikTok's `video` give Video; `p`, `posts`
and `status` give Post).
"""
import collections
import re
import urllib.parse

Guess = collections.namedtuple("Guess", "channel type host_kind")

# (channel, the hosts it is served from). `bsky.app` is Bluesky, `twitter.com` and `x.com` are X.
PLATFORMS = (
    ("Instagram", ("instagram.com",)),
    ("Facebook", ("facebook.com", "fb.watch")),
    ("LinkedIn", ("linkedin.com",)),
    ("X", ("x.com", "twitter.com")),
    ("YouTube", ("youtube.com", "youtu.be")),
    ("TikTok", ("tiktok.com",)),
    ("Threads", ("threads.net", "threads.com")),
    ("Bluesky", ("bsky.app",)),
    ("Pinterest", ("pinterest.com",)),
    ("Medium", ("medium.com",)),
    ("Substack", ("substack.com",)),
)
# Hosts whose address cannot say where a page was seen: a host and a platform in one. No channel, ever.
FILE_HOSTS = ("drive.google.com", "docs.google.com", "dropbox.com", "box.com", "onedrive.live.com", "issuu.com", "wistia.com",
              "vimeo.com")
SUBDOMAIN_HOSTS = ("substack.com",)      # `*.substack.com`: any subdomain is the platform
PREFIX_LABELS = ("www", "m", "mobile")
_LANGUAGE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")
# A path segment that names a type, anywhere in the path.
VIDEO_SEGMENTS = ("reel", "shorts", "watch")
POST_SEGMENTS = ("p", "posts", "status")
TIKTOK_VIDEO_SEGMENT = "video"


def host_of(url):
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def _behind(host, row):
    """True when `host` is `row`, or `row` behind one allowed prefix label."""
    if host == row:
        return True
    label, dot, rest = host.partition(".")
    return bool(dot) and rest == row and (label in PREFIX_LABELS or bool(_LANGUAGE.match(label)))


def _subdomain(host, row):
    return host.endswith("." + row)


def _row_for(host):
    for channel, hosts in PLATFORMS:
        for row in hosts:
            if _behind(host, row) or (row in SUBDOMAIN_HOSTS and _subdomain(host, row)):
                return channel, row
    return None, None


def _type_of(channel, url):
    try:
        segments = [s.lower() for s in urllib.parse.urlsplit(url).path.split("/") if s]
    except ValueError:
        return None
    if any(s in VIDEO_SEGMENTS for s in segments) or (channel == "TikTok" and TIKTOK_VIDEO_SEGMENT in segments):
        return "Video"
    if any(s in POST_SEGMENTS for s in segments):
        return "Post"
    return None


def looks_disguised(url):
    """True for an address whose host a browser may read otherwise than `urlsplit` does, or that only passes a visitor on: a
    backslash anywhere, a user part (`a@host`), a port other than 80 or 443, or a share or redirect wrapper (a query value or path that holds another
    address, `sharer`, `redirect`, `redir`, `share`, `l.<host>`). Such an address names no platform: any doubt is the person's."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return True
    if "\\" in url or "@" in parts.netloc or port not in (None, 80, 443) or (parts.hostname or "").startswith(("l.", "lm.")):
        return True
    values = [v for _k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    if any(re.match(r"^(https?:)?//", v.strip(), re.I) for v in values):
        return True
    return any(s.lower() in WRAPPER_SEGMENTS for s in parts.path.split("/") if s)


WRAPPER_SEGMENTS = ("sharer", "sharer.php", "share", "redirect", "redir", "sharearticle", "intent")


def guess(url):
    """What the address names: `Guess(channel, type, host_kind)`. A file host gives neither word, and neither does an address that
    `looks_disguised`."""
    host = host_of(url)
    if not host or looks_disguised(url):
        return Guess(None, None, "unknown")
    if any(_behind(host, f) or _subdomain(host, f) for f in FILE_HOSTS):
        return Guess(None, None, "file")
    channel, _row = _row_for(host)
    if channel is None:
        return Guess(None, None, "unknown")
    return Guess(channel, _type_of(channel, url), "platform")
