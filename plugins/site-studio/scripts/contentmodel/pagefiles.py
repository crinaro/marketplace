"""Reading one page or one piece file: the keys it may carry, its links, its contact and showcase entries."""

import posixpath
import re

from contentmodel.errors import ContentError
from contentmodel.frontmatter import _check_keys, _need_str, _str_list, decode_text, parse_front_matter
from contentmodel.grammar import body_start_line
from contentmodel.keytables import DATE_RE, POSITION_RE
from contentmodel.links import check_href
from contentmodel.models import Page, Piece
from configschema.configkeys import HOME_INTRO_SCOPES, HOME_TITLE_FORMS


def _check_contact(meta, path):
    c = meta["contact"]
    if not isinstance(c, dict) or not c or not all(isinstance(v, str) and v for v in c.values()):
        raise ContentError("%s: 'contact' must be a map of label: value" % path, fix="write contact as a map of label: value lines")


_SHOWCASE_ENTRY = re.compile(r"^([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)(?:\s*\|\s*(\S.*?))?$")


def parse_showcase_entry(entry):
    """(piece key `portfolio/slug`, image path or None) of one home `showcase` entry, `piece` or
    `piece | media/image.jpg`; None for a text that is neither."""
    m = _SHOWCASE_ENTRY.match(entry.strip())
    return (m.group(1), m.group(2)) if m else None


def _one_line(meta, key, path):
    v = _need_str(meta, key, path)
    if "\n" in v:
        raise ContentError("%s: front matter '%s' must be one line" % (path, key), path=path,
                           fix="write '%s' as one line of text" % key)
    return v


def _check_links(meta, path, key="links"):
    """`links`: a map of label to an https address (schema 4). The same href check every link takes."""
    v = meta[key]
    if not isinstance(v, dict) or not v or not all(isinstance(a, str) and a for a in v.values()):
        raise ContentError("%s: '%s' must be a map of label: https address" % (path, key), path=path,
                           fix="write %s as a map of label: https address lines, such as LinkedIn: "
                               "https://www.example.test/in/name" % key)
    for label, url in v.items():
        if not url.startswith("https://"):
            raise ContentError("%s: '%s' entry '%s' must start with https://" % (path, key, label), path=path,
                               fix="start the address with https://")
        check_href(url, "%s: '%s' entry '%s'" % (path, key, label))


def _check_v4_page_keys(meta, path):
    """The value rules of the schema-4 home and resume keys (design section 3.2)."""
    for k in ("eyebrow", "role", "tagline"):
        if k in meta:
            _one_line(meta, k, path)
    for k in ("showcase", "samples"):
        if k in meta:
            _str_list(meta, k, path)
    for entry in meta.get("showcase", []):
        if parse_showcase_entry(entry) is None:
            raise ContentError("%s: 'showcase' entry %r is not a piece" % (path, entry), path=path,
                               fix="write each entry as portfolio/piece, or portfolio/piece | media/image.jpg")
    if "links" in meta:
        _check_links(meta, path)
    if "titleForm" in meta and meta["titleForm"] not in HOME_TITLE_FORMS:
        names = " or ".join('"%s"' % f for f in HOME_TITLE_FORMS)
        raise ContentError("%s: 'titleForm' must be %s" % (path, names), path=path,
                           fix="set titleForm to %s (\"site\" is the site title alone, \"page\" is the home title, then the site title)" % names)
    if "introScope" in meta and meta["introScope"] not in HOME_INTRO_SCOPES:
        names = " or ".join('"%s"' % f for f in HOME_INTRO_SCOPES)
        raise ContentError("%s: 'introScope' must be %s" % (path, names), path=path,
                           fix="set introScope to %s (\"body\" is the whole body, \"first-block\" is its first block, "
                               "the rest being the part `rest`)" % names)
    if "partOrder" in meta:
        _check_part_order(meta["partOrder"], path)


_PART_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _check_part_order(order, path):
    """`partOrder` (schema 4): a non-empty list of part names, each a lower-case name once. Whether each names a part the
    page has is the build's to say (it knows the body's `:::part` blocks and the page's keys)."""
    if not isinstance(order, list) or not order or not all(isinstance(x, str) and _PART_NAME_RE.match(x) for x in order):
        raise ContentError("%s: 'partOrder' must be a list of part names (lower-case letters, digits and hyphens)" % path,
                           path=path, fix="write partOrder as a list of part names, each once, such as partOrder: [intro, showcase, feed]")
    for name in order:
        if order.count(name) > 1:
            raise ContentError("%s: 'partOrder' names '%s' twice" % (path, name), path=path,
                               fix="name each part once in partOrder; remove the repeated '%s'" % name)


def _page(files, path, allowed, where_name, schema=3):
    text = decode_text(files[path], path)
    meta, body = parse_front_matter(text, path)
    _check_keys(meta, allowed, path)
    if schema >= 4:
        _check_v4_page_keys(meta, path)
    if "title" in meta:
        _need_str(meta, "title", path)
    if "description" in meta:
        _need_str(meta, "description", path)
    if "photo" in meta:
        _need_str(meta, "photo", path)
        _need_str(meta, "photoAlt", path, required=True)
    if "endorsement" in meta:
        e = meta["endorsement"]
        if not isinstance(e, dict) or "quote" not in e or set(e) - {"quote", "by"}:
            raise ContentError("%s: 'endorsement' must be a map with 'quote' and optionally 'by'" % path, fix="write endorsement as a map with quote: and optionally by:")
    if "contact" in meta:
        _check_contact(meta, path)
    for k in ("featured", "feed"):
        if k in meta:
            _str_list(meta, k, path)
    return Page(path, meta, body, body_start_line(text))


def _validate_piece(portfolio, slug, path, files, drafts, media_paths, featured_from="home"):
    text = decode_text(files[path], path)
    meta, body = parse_front_matter(text, path)
    if "draft" in meta and not isinstance(meta["draft"], bool):
        raise ContentError("%s: front matter 'draft' must be true or false" % path, fix="write draft: true or draft: false")
    if meta.get("draft") and not drafts:
        return None
    _need_str(meta, "title", path, required=True)
    if featured_from == "flags" and "featured" in meta and not isinstance(meta["featured"], bool):
        raise ContentError("%s: front matter 'featured' must be true or false (featuredFrom is flags)" % path, fix="write featured: true or featured: false")
    for k in portfolio.settings["required"]:
        v = meta.get(k)
        if v is None or v == "" or v == []:
            raise ContentError("%s: front matter '%s' is required in the %s portfolio"
                               % (path, k, portfolio.slug), fix="add the required key to the front matter")
    for k in ("shortTitle", "teaser", "description"):
        if k in meta:
            _need_str(meta, k, path)
    if "date" in meta and not (isinstance(meta["date"], str) and DATE_RE.match(meta["date"])):
        raise ContentError("%s: front matter 'date' must look like 2026-03-04" % path, fix="write the date as YYYY-MM-DD, such as 2026-03-04")
    if portfolio.settings.get("sort") == "order" and "order" in meta:     # read only under sort: "order" (schema 3)
        o = meta["order"]
        if isinstance(o, bool) or not isinstance(o, int):
            raise ContentError("%s: front matter 'order' must be a whole number (the %s portfolio sorts by order)"
                               % (path, portfolio.slug), path=path,
                               fix="write order as a whole number, such as order: 2, or remove it")
    gb = portfolio.settings["groupBy"]
    if gb:
        g = meta.get(gb)
        if g not in portfolio.settings["groups"]:
            raise ContentError("%s: '%s' must be one of %s (the %s portfolio's groups), got %r"
                               % (path, gb, ", ".join(portfolio.settings["groups"]),
                                  portfolio.slug, g), fix="set it to one of the groups listed")
    if "coverPosition" in meta:
        cp = meta["coverPosition"]
        if not isinstance(cp, str) or not POSITION_RE.match(cp):
            raise ContentError("%s: front matter 'coverPosition' must be a CSS position such as "
                               "'center 30%%'" % path, fix="write a CSS position such as center 30%")
    if "cover" in meta:
        cv = _need_str(meta, "cover", path)
        if not cv.startswith("ref:"):
            full = posixpath.normpath(posixpath.join(posixpath.dirname(path), cv))
            if full not in media_paths or not full.startswith(posixpath.dirname(path) + "/media/"):
                raise ContentError("%s: cover '%s' is not a file in this piece's media/ folder" % (path, cv), fix="put the cover image in this piece's media/ folder and name it media/<file>")
    return Piece(portfolio.slug, slug, path, meta, body, body_start_line(text))
