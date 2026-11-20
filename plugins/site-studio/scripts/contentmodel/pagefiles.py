"""Reading one page or one piece file: the keys it may carry, its links, its contact and showcase entries."""

import posixpath
import re

from contentmodel.errors import ContentError
from contentmodel.frontmatter import _check_keys, _need_str, _str_list, decode_text, parse_front_matter
from contentmodel.grammar import body_start_line
from contentmodel.keytables import DATE_RE, HOME_LIST_KEYS, POSITION_RE, piece_keys_read
from contentmodel.links import check_href
from contentmodel.models import Page, Piece
from configschema.configkeys import BUILTIN_PIECE_KEYS, HOME_INTRO_SCOPES, HOME_TITLE_FORMS


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
    for k in HOME_LIST_KEYS:
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
    for k in HOME_LIST_KEYS:
        if k in meta:
            _str_list(meta, k, path)
    return Page(path, meta, body, body_start_line(text))


_LINK_RE = re.compile(r"^https?://")
_PICTURE = "must be a file in this piece's media/ folder, or ref:<name>"


def _trigger_text(trigger, settings):
    """A trigger as the person wrote it: `view: steps`, `cardImage: photo`, `pieceLink: true`."""
    if trigger == "steps":
        return "view: steps"
    v = settings.get(trigger)
    return "%s: %s" % (trigger, "true" if v is True else v)


def _v5_value_problem(key, val, path, media_paths):
    """What is wrong with the value of a schema-5 piece key read under its trigger, as a phrase, or None (design-movement-
    view section 3.3). `tileImage`, `tileAlt`, `tileRole`, `role` and `teaser` keep the checks they have where they are
    read (as in 0.4.0)."""
    if key == "photo":
        if not isinstance(val, str) or not val.strip():
            return _PICTURE
        if val.startswith("ref:"):
            return None
        full = posixpath.normpath(posixpath.join(posixpath.dirname(path), val))
        if full not in media_paths or not full.startswith(posixpath.dirname(path) + "/media/"):
            return _PICTURE
        return None
    if key in ("tilePosition", "photoPosition"):
        return None if isinstance(val, str) and POSITION_RE.match(val) else "must be a CSS position such as center 30%"
    if key in ("photoAlt", "coverAlt", "linkLabel"):
        return None if isinstance(val, str) and val.strip() and "\n" not in val else "must be one line of text"
    if key == "link":
        if not isinstance(val, str) or not _LINK_RE.match(val):
            return "must be an http or https address"
        try:
            check_href(val, "%s: front matter 'link'" % path)
        except ContentError:
            return "must be an http or https address"
    return None


def _kicker_problem(val):
    """A kicker's value: text, a number, or a list of them."""
    def one(v):
        return (isinstance(v, str) and v.strip() and "\n" not in v) or (isinstance(v, (int, float))
                                                                        and not isinstance(v, bool))
    if one(val) or (isinstance(val, list) and val and all(one(v) for v in val)):
        return None
    return "must be text, a number, or a list of them"


def _check_v5_piece_keys(portfolio, meta, path, media_paths):
    """Rule 6 of design-movement-view section 3.1: under a schema-5 trigger of the piece's own portfolio, a value that is
    not what its key now means is refused with the way out ("move that value to another key and list the new key in
    meta, or remove <trigger>"), and a `meta` or `cardMeta` list naming a key the trigger reads is refused (the build
    shows it already). Without a trigger nothing here runs: the key is what it was in 0.4.x."""
    settings = portfolio.settings
    read = piece_keys_read(settings)
    if not read:
        return
    kicker = settings.get("cardKicker")
    shown = set(settings.get("meta", ())) | set(settings.get("cardMeta", ()))
    for key in sorted(read):
        if key in shown and key != kicker and key not in BUILTIN_PIECE_KEYS:
            where = portfolio.page_source or "site/site.json"
            trig = _trigger_text(read[key][0], settings)
            raise ContentError("%s: meta or cardMeta lists '%s', which %s reads: the build shows it already; list "
                               "another key" % (where, key, trig), path=where,
                               fix="remove '%s' from meta and cardMeta; the build shows it already under %s"
                                   % (key, trig))
    for key in sorted(read):
        if key not in meta:
            continue
        if key == kicker and read[key] == ("cardKicker",):
            problem = _kicker_problem(meta[key])
        else:
            problem = _v5_value_problem(key, meta[key], path, media_paths)
        if problem:
            trig = _trigger_text(read[key][0], settings)
            raise ContentError("%s: front matter '%s' %s, because %s reads it" % (path, key, problem, trig), path=path,
                               fix="move that value to another key and list the new key in meta, or remove %s" % trig)


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
    _check_v5_piece_keys(portfolio, meta, path, media_paths)
    return Piece(portfolio.slug, slug, path, meta, body, body_start_line(text))
