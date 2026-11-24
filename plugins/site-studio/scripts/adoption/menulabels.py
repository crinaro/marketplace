"""adoption.menulabels -- the words the old site's menu uses for the About and Resume pages, and what adopt offers from them
(design-adopt-local-reach section 4 and 1.6; site-studio 0.8.0, schema 8; owner decision O-3 (a)).

Part of the `adoption` package behind the entry point `adopt.py`. Three settings read it:

  nav.labels.about, nav.labels.resume
                      absent (the default: the plugin's own `About` / `Resume`, `building.constants`) or the text of the old menu's
                      anchor to that page, read from the OLD BUILD'S OUTPUT (`old_menu_label`): the source snapshot holds tokens, not
                      anchors. Offered only when the word differs from the default; measured on every page's menu (`scoring`).
  resume.titleForm    `title` (the default) or `page`: the resume's `<title>` leads with the menu's word for the page instead of the
                      resume's own `title` (`site.json` `resume.titleForm`, schema 8, dev #1040). Offered only when the old resume page's
                      `<title>` starts with the old menu's word for it; measured on `resume/index.html`'s title.

With no old build (`local` None), or when no anchor of the old menu names the page, nothing is read and the candidates are the default
alone: there is nothing to choose, and nothing is guessed. Pure functions over `local`, {output path: bytes}.
"""

import html as html_mod
import posixpath
import re

from building.constants import ABOUT_MENU_LABEL, RESUME_MENU_LABEL
from configschema import sectioncheck
from configschema.diagnostics import SiteConfigError

PAGES = ("about", "resume")
DEFAULT_WORDS = {"about": ABOUT_MENU_LABEL, "resume": RESUME_MENU_LABEL}
LABEL_PREFIX = "nav.labels."
TITLE_FORM = "resume.titleForm"
TITLE_FORMS = ("title", "page")

_TAG = re.compile(r"<[^>]*>")
_NAV = re.compile(r"<nav\b[^>]*>(.*?)</nav\s*>", re.I | re.S)
_LINK = re.compile(r"<a\b[^>]*\bhref=\"([^\"]*)\"[^>]*>(.*?)</a\s*>", re.I | re.S)
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.I)


def _text(fragment):
    return " ".join(html_mod.unescape(_TAG.sub(" ", fragment)).split())


def _target(href, at):
    """The output path the address `href`, written on the old page at `at`, resolves to ("" for the site root), or None for an
    address that leaves the site or holds no page (a scheme, `//host`, a fragment alone)."""
    if _SCHEME.match(href.strip()):
        return None
    href = re.split(r"[?#]", href.strip(), maxsplit=1)[0]
    path = posixpath.normpath(posixpath.join("/", posixpath.dirname(at), href)) if not href.startswith("/") else posixpath.normpath(href)
    return path.lstrip("/")


def _names(target, page):
    """True when the output path `target` is the old page for `page`: `resume/index.html`, `resume.html` (or the folder or the
    stem, an address a server completes)."""
    return target in (page, page + "/index.html", page + ".html", page + ".htm", page + "/index.htm")


def old_menu_label(local, page):
    """The word the OLD site's menu prints for `page` (`about` or `resume`): the text of the anchor in the old `<nav>` whose address
    resolves to the old page, whitespace squashed, read from the old build's output `local` ({path: bytes}); None when `local` is None,
    no page's menu holds such an anchor, the anchor has no text (a picture), or two pages' menus disagree (a menu this setting
    cannot name; whether the word is right is measured, never assumed). The default word comes back as read: the caller decides
    whether it differs."""
    seen = set()
    for path in sorted(local or {}):
        if not path.lower().endswith((".html", ".htm")):
            continue
        nav = _NAV.search((local[path]).decode("utf-8", "replace"))
        if not nav:
            continue
        for href, inner in _LINK.findall(nav.group(1)):
            target = _target(href, path)
            if target is not None and _names(target, page):
                seen.add(_text(inner))
    seen.discard("")
    return next(iter(seen)) if len(seen) == 1 else None


def label_ok(text):
    """True for a label `site.json` accepts in `nav.labels` (`configschema.sectioncheck._one_line`, the check the build runs, asked here
    so the two can never disagree)."""
    try:
        sectioncheck._one_line(text, "nav.labels")
    except (SiteConfigError, TypeError, AttributeError):
        return False
    return isinstance(text, str)


def label_candidates(name, local):
    """`nav.labels.<page>`: [None, the old menu's word] when it differs from the plugin's own word and `site.json` accepts it, else
    [None] (nothing to choose)."""
    page = name[len(LABEL_PREFIX):]
    word = old_menu_label(local, page)
    return [None, word] if word and word != DEFAULT_WORDS[page] and label_ok(word) else [None]


def old_resume_title(local):
    """The text of the old resume page's `<title>` (`resume/index.html`, else `resume.html`), or None."""
    for path in ("resume/index.html", "resume.html"):
        m = _TITLE.search((local or {}).get(path, b"").decode("utf-8", "replace"))
        if m:
            return _text(m.group(1))
    return None


def title_form_candidates(local):
    """`resume.titleForm`: `["title", "page"]` when the old resume page's `<title>` starts with the old menu's word for it, else
    `["title"]`. With no old build, no resume page or no readable menu word there is nothing to choose."""
    word, title = old_menu_label(local, "resume"), old_resume_title(local)
    return list(TITLE_FORMS) if word and title and title.startswith(word) else [TITLE_FORMS[0]]


def candidates(name, local):
    """The candidates of the three settings above, default first."""
    return title_form_candidates(local) if name == TITLE_FORM else label_candidates(name, local)


def is_label(name):
    return name.startswith(LABEL_PREFIX) and name[len(LABEL_PREFIX):] in PAGES


def names(snap):
    """The settings of this module a converted tree has, in the order they are chosen: a menu label per built-in page the tree
    holds (an about page, a resume), and `resume.titleForm` where it holds a resume. The labels come first, so a `CV` site measures
    `resume.titleForm: page` under the label it chose."""
    about = "content/about.md" in snap or "content/about/index.md" in snap
    resume = "content/resume/resume.md" in snap or any(p.endswith("/resume.md") for p in snap)
    return (["nav.labels.about"] if about else []) + (["nav.labels.resume"] if resume else []), [TITLE_FORM] if resume else []
