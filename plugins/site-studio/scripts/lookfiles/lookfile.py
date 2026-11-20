"""Looks as files: the shipped looks, finding and reading a look file, and the literal words a look carries."""

import html.parser
import looks
import os
import re
from lookfiles.pagedom import _NOT_TEXT_ATTRS, _SLOT, _collapse
from lookfiles.refusals import LookCommandError


LOOKS_REL = "site/looks/"
SHIPPED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates", "looks")


_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def literals(look):
    """[(construct, part, text)]: the words a look carries itself (text nodes, and attributes that hold text such as
    alt, title and aria-label), slots removed. These are the person's own words in a derived look."""
    out = []
    for cid, parts in sorted(look.constructs.items()):
        for pn, text in sorted(parts.items()):
            p = _Literals()
            p.feed(_SLOT.sub("", text))
            for t in p.found:
                out.append((cid, pn, t))
    return out


class _Literals(html.parser.HTMLParser):
    """The literal words of one part. A decoration's attribute values (an `<svg>` subtree: a path's `d`, a `fill`; design-movement-
    view 9.2) are drawing, never words a visitor reads: `look.py use` and `check` list the decoration on its own line instead."""

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.found = []
        self.svg = 0                    # how deep inside a decoration's `<svg>` subtree the parser is

    def handle_starttag(self, tag, attrs):
        if tag == "svg" or self.svg:
            self.svg += 1
            return
        self._words(attrs)

    def handle_startendtag(self, tag, attrs):
        if tag != "svg" and not self.svg:
            self._words(attrs)

    def handle_endtag(self, tag):
        if self.svg:
            self.svg -= 1

    def _words(self, attrs):
        for name, v in attrs:
            if v and name not in _NOT_TEXT_ATTRS and not name.startswith("data-") and re.search(r"[A-Za-z]", v):
                self.found.append(v.strip())

    def handle_data(self, data):
        if re.search(r"[A-Za-z]", data):
            self.found.append(_collapse(data).strip())


# ======================================================================================== list, use and check
def shipped_ids():
    try:
        names = sorted(n[:-5] for n in os.listdir(SHIPPED_DIR) if n.endswith(".json"))
    except OSError:
        names = []
    return names


def _read_look(path, where, shipped=False):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return raw, looks.parse(raw.decode("utf-8"), where, shipped=shipped)
    except (OSError, UnicodeDecodeError) as e:
        raise LookCommandError("%s cannot be read (%s); check the path" % (where, e.__class__.__name__))
    except looks.LookError as e:
        raise LookCommandError("%s is refused:\n%s\nfix: %s" % (where, e, e.fix or "fix the lines above"))


def _find_source(source):
    """(kind, look path, display, slug) for a `use` argument."""
    if source in shipped_ids():
        return "shipped", os.path.join(SHIPPED_DIR, source + ".json"), "templates/looks/%s.json" % source, source
    if os.sep in source or "/" in source or source.endswith(".json") or os.path.exists(source):
        path = os.path.abspath(source)
        slug = os.path.basename(path)[:-5] if path.endswith(".json") else os.path.basename(path)
        if not os.path.isfile(path):
            raise LookCommandError("%s is not a file; give the path of a look file, or one of: %s"
                                   % (source, ", ".join(shipped_ids())))
        if not _SLUG.match(slug):
            raise LookCommandError("the look file name %r must be lower-case letters, digits and hyphens before .json; "
                                   "copy it to such a name first" % os.path.basename(path))
        return "path", path, os.path.basename(path), slug
    raise LookCommandError("%r is not a look site-studio ships (%s) and not a file; give one of them, or the path of a "
                           "look file" % (source, ", ".join(shipped_ids())))


def _repo_root_of(look_path):
    """The repository root a look file at `<root>/site/looks/<name>.json` belongs to, else None."""
    d = os.path.dirname(look_path)
    if os.path.basename(d) == "looks" and os.path.basename(os.path.dirname(d)) == "site":
        return os.path.dirname(os.path.dirname(d))
    return None
