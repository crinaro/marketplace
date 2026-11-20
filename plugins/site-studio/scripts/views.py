#!/usr/bin/env python3
"""views.py -- the schema-4 portfolio index views, and the home page's showcase (template-fidelity step 1.5, design
section 8 V1 and R5.8). Python 3.9, standard library only. A module, not a command: `build.py` imports it the first
time a page needs it (`_Builder.views()`), so a build that holds no view never reads it.

    index_html(builder, portfolio, out)   the HTML that goes in a portfolio index page's `cards` slot, for a portfolio
                                          whose `page.md` says `view: roles`, `map` or `showcase`
    showcase_html(builder, entries, out)  the home page's `{{home:showcase}}`: one tile per (piece, image) entry

BUILT-IN VIEWS, NOT A RENDERER (design section 4). Each index is generated at build time from the committed pieces,
so adding a piece updates it, and the build stays a pure function of the committed tree and the plugin version:
nothing here reads the clock, the network or anything outside the build input and the plugin's own files. All
markup goes through `builder.r(construct, part, values)` (`looks.render`), so a site's look decides every element
and class, with ONE exception stated here: the map's `<svg>` is a drawing of the pieces' pins, which no look writes, so
it is made by this module and enters its look part through an `html` slot, as the Markdown renderer's own markup does.
(From 0.5.0 a look may hold an `<svg>` of its own only as a decoration, `lookgrammar/decoration.py`: an allow-listed
drawing with no slot, so it can never carry the map.) The steps view of schema 5 is `building/stepsview.py`, which
`index_html` dispatches to.

    roles       one card per employer. Pieces are grouped by their `employer`; a piece without one is refused naming
                the key. Groups follow the portfolio's own piece order (its `sort`, newest first by default, so a
                group sits where its newest piece sits), and a group that holds a `current: true` piece comes first
                and uses the look's `item-current` part (class `ss-employer-current`). A card links its newest piece
                and shows its `role` (a list is joined with " / ") and `period`; a group of more than one piece
                reads "N roles at Employer" and adds a "Previously" line linking the others.
    map         a dotted world map and, under it, a list of every piece as a link (the index works without the SVG
                and for assistive technology). One `<circle>` per land cell of the mask; one pin per piece that has
                `pin: lat, lon`, linking to it. No script, no tiles, nothing loaded from another address.
    showcase    one tile per piece: its image (`tileImage`, else `cover`), alt (`tileAlt`, else empty: the title
                is printed beside it) and role line (`tileRole`, else `role`). The home page's `showcase` list uses
                the same tile function, with an optional image of its own per entry.

THE MASK FORMAT (`parse_mask`; fixed here and in the content model). Rows of `.` (sea) and `#` (land), north to
south and west to east, one row per line, every row the same length, twice as many columns as rows (an
equirectangular world: 360 by 180 degrees). At most 720 columns and 360 rows. Anything else is refused naming the
file, the row and the fix. The plugin's own mask is `templates/data/land-mask.txt` (180 by 90, 2 degree cells,
derived by `spec/derive_land_mask.py`); a portfolio's `mapMask` names one of its own.

PINS. `pin: 48.85, 2.35` is `latitude, longitude` in degrees (a two-item list is read the same way). Latitude is
-90 to 90 and longitude -180 to 180; anything else is refused naming the piece. The map is drawn in a 360 by 180
box, one unit to a degree, so a pin sits at x = longitude + 180 and y = 90 - latitude.

Every refusal is a `ContentError` carrying the file, and the fix (the one exception type `build.accept` turns into a
problem for every stage), never a traceback.
"""
import functools
import os
import posixpath
import re

from building import pictures, stepsview
from contentmodel import frontmatter
from contentmodel.errors import ContentError
from contentmodel.links import esc

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
MASK_REL = "templates/data/land-mask.txt"
MASK_PATH = os.path.join(PLUGIN_ROOT, *MASK_REL.split("/"))
MAX_COLS, MAX_ROWS = 720, 360
VIEWBOX_W, VIEWBOX_H = 360, 180
PIN_RADIUS = 2.4

_NUMBER = re.compile(r"^-?\d{1,3}(?:\.\d{1,6})?$")


class Mask(object):
    """A parsed land mask: `cols` by `rows` cells, `land` the (column, row) of each `#`, in reading order."""

    def __init__(self, cols, rows, land):
        self.cols, self.rows, self.land = cols, rows, land


def parse_mask(text, where):
    """The `Mask` of a land-mask text, strictly: a ragged grid, a character other than `.` and `#`, a blank line,
    a grid that is not twice as wide as it is tall, or one larger than 720 by 360 is refused, never read as
    something close."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()                                   # the one newline that ends the last row
    if not lines:
        raise ContentError("%s: the land mask is empty" % where, path=where,
                           fix="write one row of . and # per line, twice as many columns as rows")
    cols = len(lines[0])
    for n, line in enumerate(lines, 1):
        if len(line) != cols:
            raise ContentError("%s:%d: the land mask is ragged (this row has %d characters, the first has %d)"
                               % (where, n, len(line), cols), path=where, lineno=n,
                               fix="make every row of the mask the same length")
        bad = sorted(set(line) - set(".#"))
        if bad:
            raise ContentError("%s:%d: the land mask holds %s; a row is only . (sea) and # (land)"
                               % (where, n, ", ".join(repr(b) for b in bad[:3])), path=where, lineno=n,
                               fix="write sea as . and land as #, and nothing else")
    rows = len(lines)
    if cols == 0:
        raise ContentError("%s: the land mask has blank rows" % where, path=where,
                           fix="remove the blank lines; every row is . and # characters")
    if cols != 2 * rows:
        raise ContentError("%s: the land mask is %d columns by %d rows; a world map is twice as wide as it is tall"
                           % (where, cols, rows), path=where,
                           fix="make the mask %d columns by %d rows, or %d by %d" % (2 * rows, rows, cols, cols // 2))
    if cols > MAX_COLS or rows > MAX_ROWS:
        raise ContentError("%s: the land mask is %d by %d; the most a map reads is %d by %d"
                           % (where, cols, rows, MAX_COLS, MAX_ROWS), path=where,
                           fix="use a coarser grid")
    land = [(i, j) for j, line in enumerate(lines) for i, ch in enumerate(line) if ch == "#"]
    return Mask(cols, rows, land)


@functools.lru_cache(maxsize=1)
def plugin_mask():
    """The plugin's own mask. A missing file is a refusal that says how to mend the install, never an empty map
    (a missing thing must not read as an empty thing)."""
    try:
        with open(MASK_PATH, "rb") as fh:
            raw = fh.read()
    except OSError:
        raise ContentError("the site-studio install is missing %s, which the map view draws" % MASK_REL,
                           fix="reinstall the site-studio plugin, which ships that file")
    return parse_mask(frontmatter.decode_text(raw, MASK_REL), MASK_REL)


def mask_for(builder, portfolio):
    """The mask a portfolio's map draws: the file its `page.md` `mapMask` names under the portfolio folder, else the
    plugin's."""
    ref = portfolio.settings.get("mapMask")
    if not ref:
        return plugin_mask()
    path = "content/%s/%s" % (portfolio.slug, ref)
    page = portfolio.page_source or "content/%s/page.md" % portfolio.slug
    raw = builder.files.get(path)
    if raw is None:
        raise ContentError("%s: mapMask %s is not a file in the build input" % (page, ref), path=page,
                           fix="commit the file at %s, or remove mapMask from the page for the plugin's own map" % path)
    return parse_mask(frontmatter.decode_text(raw, path), path)


def parse_pin(value, where):
    """(latitude, longitude) of a piece's `pin`, `lat, lon` text or a two-item list; a refusal names `where`."""
    if isinstance(value, list):
        bits = [str(v).strip() for v in value]
    elif isinstance(value, str):
        bits = [b.strip() for b in value.split(",")]
    else:
        bits = []
    if len(bits) != 2 or not all(_NUMBER.match(b) for b in bits):
        raise ContentError("%s: pin %r is not latitude, longitude (two numbers in degrees, such as 48.85, 2.35)"
                           % (where, value if not isinstance(value, list) else ", ".join(bits)), path=where,
                           fix="write pin as latitude, longitude, such as pin: 48.85, 2.35")
    lat, lon = float(bits[0]), float(bits[1])
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ContentError("%s: pin %s, %s is off the globe (latitude is -90 to 90, longitude -180 to 180; "
                           "latitude comes first)" % (where, bits[0], bits[1]), path=where,
                           fix="write pin as latitude, longitude, such as pin: 48.85, 2.35")
    return lat, lon


def _num(x):
    s = ("%.2f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def map_svg(mask, pins, label):
    """The inline SVG of the map: one `<circle>` per land cell, then one linked pin per `(url, title, lat, lon)`.
    Plugin-made (a look may not write an SVG) and fully escaped; it holds no script and loads nothing."""
    cw, ch = float(VIEWBOX_W) / mask.cols, float(VIEWBOX_H) / mask.rows
    radius = _num(min(cw, ch) * 0.35)
    dots = "".join('<circle cx="%s" cy="%s" r="%s"/>' % (_num((i + 0.5) * cw), _num((j + 0.5) * ch), radius)
                   for i, j in mask.land)
    marks = "".join('<a href="%s"><circle class="ss-map-pin" cx="%s" cy="%s" r="%s"/><title>%s</title></a>'
                    % (esc(url), _num(lon + 180.0), _num(90.0 - lat), _num(PIN_RADIUS), esc(title))
                    for url, title, lat, lon in pins)
    return ('<svg class="ss-map" viewBox="0 0 %d %d" role="img" aria-label="%s"><g class="ss-map-land">%s</g>%s</svg>'
            % (VIEWBOX_W, VIEWBOX_H, esc(label), dots, marks))


# ---------------------------------------------------------------------------------------------- piece fields
def _piece_url(builder, piece, out):
    return builder.link(out, "%s/%s/index.html" % (piece.portfolio, piece.slug))


def _titles(piece):
    """The role line of a piece: `role` (text, or a list joined with " / "), else its card title."""
    role = piece.meta.get("role")
    if role is None:
        return piece.card_title
    if isinstance(role, str) and role.strip():
        return role.strip()
    if isinstance(role, list) and role and all(isinstance(x, str) and x.strip() for x in role):
        return " / ".join(x.strip() for x in role)
    raise ContentError("%s: front matter 'role' must be text, or a list of text such as [Designer, Lead]"
                       % piece.source, path=piece.source,
                       fix="write role as one line of text, or as a list such as role: [Designer, Lead]")


def _period(piece):
    value = piece.meta.get("period")
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip() or "\n" in str(value):
        raise ContentError("%s: front matter 'period' must be one line, such as 2019 to 2023" % piece.source,
                           path=piece.source, fix="write period as one line of text, such as period: 2019 to 2023")
    return str(value).strip()


def _employer(piece, view):
    value = piece.meta.get("employer")
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise ContentError("%s: front matter 'employer' is required under view: %s (one line of text)"
                           % (piece.source, view), path=piece.source,
                           fix="add employer: <name> to the piece's front matter, or change the portfolio's view")
    return value.strip()


def _is_current(piece):
    value = piece.meta.get("current", False)
    if not isinstance(value, bool):
        raise ContentError("%s: front matter 'current' must be true or false" % piece.source, path=piece.source,
                           fix="write current: true, or remove the key")
    return value


# ---------------------------------------------------------------------------------------------- the views
def roles_html(builder, portfolio, out):
    groups, order = {}, []
    for piece in portfolio.pieces:                    # the portfolio's own order: a group sits at its newest piece
        name = _employer(piece, "roles")
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(piece)
    currents = dict((name, any(_is_current(p) for p in groups[name])) for name in order)
    order = [n for n in order if currents[n]] + [n for n in order if not currents[n]]
    items = []
    for name in order:
        newest, earlier = groups[name][0], groups[name][1:]
        if earlier:
            heading = builder.r("roles-view", "heading-multi", {"count": len(groups[name]), "employer": name},
                                newest.source)
            previously = builder.r("roles-view", "previously", {"items": "".join(
                builder.r("roles-view", "previously-item", {"url": _piece_url(builder, p, out),
                                                            "title": _titles(p), "period": _period(p)}, p.source)
                for p in earlier)}, newest.source)
        else:
            heading = builder.r("roles-view", "heading", {"employer": name}, newest.source)
            previously = ""
        part = "item-current" if currents[name] else "item"
        items.append(builder.r("roles-view", part,
                               {"heading": heading, "url": _piece_url(builder, newest, out),
                                "titles": _titles(newest), "period": _period(newest), "previously": previously,
                                "employer": name, "image": pictures.roles_image_slot(builder, part, newest, out),
                                "kicker": stepsview.kicker_slot(builder, "roles-view", part, newest, out)},
                               newest.source))
    return builder.assets(out, "roles-view") + builder.r("roles-view", "wrap", {"items": "".join(items)})


def map_html(builder, portfolio, out):
    mask = mask_for(builder, portfolio)
    pins, listed = [], []
    for piece in portfolio.pieces:
        url = _piece_url(builder, piece, out)
        listed.append(builder.r("map-view", "list-item", {"url": url, "title": piece.card_title}, piece.source))
        if piece.meta.get("pin") is not None:
            lat, lon = parse_pin(piece.meta["pin"], piece.source)
            who = [t for t in (_titles(piece) if piece.meta.get("role") is not None else "",
                               piece.meta.get("employer") if isinstance(piece.meta.get("employer"), str) else "")
                   if t]
            pins.append((url, ", ".join(who) or piece.card_title, lat, lon))
    return builder.assets(out, "map-view") + builder.r(
        "map-view", "wrap", {"map": map_svg(mask, pins, portfolio.title),
                             "list": builder.r("map-view", "list", {"items": "".join(listed)})})


def _tile(builder, construct, piece, out, image=None, home=None):
    """One tile: the piece's image (the entry's own `image` when the home page names one, else `tileImage`, else
    `cover`), its alt (`tileAlt`), its title and its role line (`tileRole`, else `role`). Step G (coordinator,
    2026-11-19): a HOME tile with no entry `image`, under the `cardImage` trigger of the piece's OWN portfolio, shows a
    card's picture instead (O4b, `pictures.card_picture`); a home tile's picture renders through the site's own
    `home-showcase.image` part when its look writes one (O3); `fullTitle` is the piece's own `title` (O4a)."""
    for key in ("tileAlt", "tileRole"):
        if piece.meta.get(key) is not None and (not isinstance(piece.meta[key], str)
                                                or not piece.meta[key].strip() or "\n" in piece.meta[key]):
            raise ContentError("%s: front matter '%s' must be one line of text" % (piece.source, key),
                               path=piece.source, fix="write %s as one line of text, or remove it" % key)
    settings = builder.model.portfolio(piece.portfolio).settings
    card = construct == "home-showcase" and not image and "cardImage" in stepsview.piece_triggers(builder, piece)
    if card:
        found = None
    elif image:
        full = posixpath.normpath(posixpath.join(posixpath.dirname(home), image))
        if full not in builder.media_out:
            raise ContentError("%s: showcase image '%s' is not a file in %s/media/"
                               % (home, image, posixpath.dirname(home)), path=home,
                               fix="put the image in %s/media/ and name it as media/<file>" % posixpath.dirname(home))
        found = (full, builder.media_out[full])
    elif piece.meta.get("tileImage") is not None:
        if not isinstance(piece.meta["tileImage"], str) or not piece.meta["tileImage"].strip():
            raise ContentError("%s: front matter 'tileImage' must be a path such as media/tile.jpg" % piece.source,
                               path=piece.source, fix="write tileImage as a path inside the piece's media/ folder")
        found = builder.cover_of(piece, "tileImage")
    else:
        found = builder.cover_of(piece)
    picture = (pictures.card_picture(builder, piece, settings) if card else
               pictures.Picture("tile", found[0], found[1], piece.meta.get("tileAlt", ""), None) if found else None)
    img = pictures.place_html(builder, construct, picture, out) if picture else ""
    role = piece.meta.get("tileRole")
    if role is None and piece.meta.get("role") is not None:
        role = _titles(piece)
    line = builder.r(construct, "role", {"text": role}, piece.source) if role else ""
    return builder.r(construct, "item", {"url": _piece_url(builder, piece, out), "image": img, "role": line,
                                         "title": piece.card_title, "fullTitle": piece.title,
                                         "kicker": stepsview.kicker_slot(builder, construct, "item", piece, out)},
                     piece.source)


def showcase_view_html(builder, portfolio, out):
    tiles = "".join(_tile(builder, "showcase-view", p, out) for p in portfolio.pieces)
    return builder.assets(out, "showcase-view") + builder.r(
        "showcase-view", "wrap", {"items": tiles, "label": portfolio.title})


VIEWS = {"roles": roles_html, "map": map_html, "showcase": showcase_view_html, "steps": stepsview.steps_html}


def index_html(builder, portfolio, out):
    """The cards slot of a portfolio index under a schema-4 view. A portfolio with no pieces has none, as a grid."""
    view = portfolio.settings["view"]
    if view not in VIEWS:
        raise ContentError("%s: view %r is not one of %s" % (portfolio.page_source or portfolio.slug, view,
                                                              ", ".join(sorted(VIEWS))),
                           fix="set view to roles, map or showcase, or remove it")
    if not portfolio.pieces:
        return ""
    return VIEWS[view](builder, portfolio, out)


def showcase_html(builder, entries, out):
    """The home page's showcase: `entries` is [(piece, image path or None)] in the order the page names them."""
    if not entries:
        return ""
    home = builder.model.home.source
    tiles = "".join(_tile(builder, "home-showcase", piece, out, image, home) for piece, image in entries)
    return builder.assets(out, "home-showcase") + builder.r("home-showcase", "wrap", {"items": tiles})
