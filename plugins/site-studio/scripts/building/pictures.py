"""pictures: the ONE resolver of design-movement-view section 5, "one rule for a picture, its alt and its position".

A picture a key names has two optional companions, an alt (one line) and a position (a CSS `object-position` value), and
the alt and position that print are the ones of the picture that prints:

    picture                         its alt      its position
    cover                           coverAlt     coverPosition
    photo                           photoAlt     photoPosition
    tileImage                       tileAlt      tilePosition
    a reference's `image` or card   imageAlt     imagePosition     (in its reference.json)

Which picture prints, and whether its alt does:

    a step (`view: steps`)          tileImage, photo, cover    the picture's own alt, else ""
    a card, `cardImage: photo`      photo, cover               "" ; under `cardAlt: true` the picture's own alt, else ""
    a card, no `cardImage`          cover                      the same rule
    a roles card under `cardImage`  the group's newest piece, as a card (`roles_picture`)
    a reference card                the reference's picture    imageAlt, else ""

A picture given as `ref:<name>` uses the piece's own alt and position keys when present, else the reference's `imageAlt`
and `imagePosition` (schema-5 keys of `reference.json`, so no tree 0.4.x accepted holds one). The showcase tiles are not
here: they read no picture key of section 3.3 at any schema (rule 5), and keep 0.4.0's code in `views.py`, with one
exception the coordinator approved on 2026-11-19 (step G, O4b): under the `cardImage` trigger of the piece's OWN portfolio,
a HOME showcase tile's picture is a card's (`card_picture`). That tile follows the card row exactly (coordinator's
ruling on review F4): `photo` under `cardImage: photo`, else `cover`; alt "" unless `cardAlt`, then that picture's own
alt key; `tileImage` and `tileAlt` are not consulted. `place_html` renders a step's or a home tile's picture
through that place's own picture part when the site's look writes one (step G, O3).

Every key read here is a row of `contentmodel.keytables.V5_PIECE_KEYS` (or a 0.4.x built-in or view key), and is read
only where the caller's trigger, from the piece's OWN portfolio, says so: `step_picture` is called by the steps view only,
`card_picture` reads `photo` only under the `cardImage` trigger and an alt only under `cardAlt`."""

from building.outcomes import BuildError
from contentmodel.errors import ContentError
from contentmodel.keytables import active_triggers
from lookgrammar import optionalparts

import looks

# picture key -> (alt key, position key): the first table of section 5
COMPANIONS = {
    "cover": ("coverAlt", "coverPosition"),
    "photo": ("photoAlt", "photoPosition"),
    "tileImage": ("tileAlt", "tilePosition"),
}
REFERENCE_COMPANIONS = ("imageAlt", "imagePosition")

# the place -> the picture keys it tries, first that the piece has: the second table of section 5
STEP_ORDER = ("tileImage", "photo", "cover")
CARD_ORDER = ("cover",)
CARD_PHOTO_ORDER = ("photo", "cover")


class Picture(object):
    """A picture that prints: the key that named it, its (repo path, output path), and the alt and position that go
    with it ("" and None when it has none)."""

    def __init__(self, key, repo_path, out_path, alt, position):
        self.key, self.repo_path, self.out_path, self.alt, self.position = key, repo_path, out_path, alt, position

    def html(self, builder, from_out):
        """The `<img>`, through the look's `image` construct (its `-pos` part when the picture has a position)."""
        return builder.img_tag(self.repo_path, self.alt, from_out, out_path=self.out_path, focus=self.position)

    def values(self, builder, from_out):
        """The slot values `html` fills the site-wide `image` part with (src, alt, and width, height, srcset, sizes and
        focus where the picture has them), computed once, by `img_tag` itself (`_Capture`)."""
        capture = _Capture(builder)
        type(builder).img_tag(capture, self.repo_path, self.alt, from_out, out_path=self.out_path, focus=self.position)
        return capture.values


class _Capture(object):
    """Stands in for the builder inside `img_tag`, keeping the values it renders the `image` part with instead of
    rendering it: a place's own picture part is filled with exactly the values the site-wide one would get."""

    def __init__(self, builder):
        self._builder, self.values = builder, None

    def __getattr__(self, name):
        return getattr(self._builder, name)

    def r(self, construct, part, values, source=None):
        self.values = dict(values)
        return ""


def place_html(builder, construct, picture, from_out):
    """A picture at a place that may have its own picture part (step G, O3: `steps-view.image`, `home-showcase.image`).
    Where the site's own look writes that part, the picture renders through it, filled with the values the site-wide
    `image` construct would get; the own attribute of a slot the picture has no value for (`width` of a file with no
    pixel size, `srcset` with no copies, `focus` with no position) is left out, as the site-wide construct's smaller
    parts leave it out. Where it does not (the default look never does), `picture.html`: byte for byte as before.

    Review F1: which attribute is a slot's own is read by the grammar's own part parser (`looks.check_part`, through
    `lookgrammar.optionalparts`), never by a pattern on the raw markup, and the markup left after the removal is checked
    again before it renders (a `BuildError` on any problem), so nothing unchecked reaches the page."""
    markup = looks.optional_part(construct, "image", builder.look)
    if markup is None:
        return picture.html(builder, from_out)
    values = picture.values(builder, from_out)
    parsed = []
    problems = looks.check_part(construct, "image", markup, parsed=parsed)
    if not problems:
        markup = optionalparts.strip(*parsed[0], keep=set(values))
        problems = looks.check_part(construct, "image", markup)
    if problems:
        raise BuildError("%s: %s" % (builder.look.where, problems[0][0]), path=builder.look.where,
                         fix="fix the look's %s.image markup: %s" % (construct, problems[0][1]))
    own = looks.Look({construct: {"image": markup}}, [], {}, builder.look.where)
    try:
        return looks.render(construct, "image", values, own)
    except looks.LookError as e:
        raise BuildError("%s: %s" % (builder.look.where, e), path=builder.look.where,
                         fix="fix the look's %s.image markup" % construct)


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def reference_companions(ref):
    """(alt, position) a reference's own `reference.json` gives its card picture: `imageAlt`, `imagePosition`."""
    data = ref.data if ref is not None else {}
    return _text(data.get(REFERENCE_COMPANIONS[0])), _text(data.get(REFERENCE_COMPANIONS[1]))


def _named(piece, key):
    """The piece's value for the picture key `key`, or None when it has none. `tileImage` keeps 0.4.0's check where it is
    read (a path, never another type), as `views._tile` does; `cover` and `photo` were checked when the content was read."""
    value = piece.meta.get(key)
    if value is None:
        return None
    if key == "tileImage" and (not isinstance(value, str) or not value.strip()):
        raise ContentError("%s: front matter 'tileImage' must be a path such as media/tile.jpg" % piece.source,
                           path=piece.source, fix="write tileImage as a path inside the piece's media/ folder")
    return value if isinstance(value, str) and value else None


def resolve(builder, piece, order, with_alt):
    """The `Picture` of the first key in `order` the piece has, or None. Its alt is the picture's own alt key when
    `with_alt`, else ""; its position is the picture's own position key. A `ref:<name>` picture takes the reference's
    `imageAlt` and `imagePosition` for whichever of the two the piece does not give."""
    for key in order:
        value = _named(piece, key)
        if value is None:
            continue
        found = builder.cover_of(piece, key)
        if not found:
            continue
        alt_key, pos_key = COMPANIONS[key]
        alt = _text(piece.meta.get(alt_key)) if with_alt else None
        position = _text(piece.meta.get(pos_key))
        if value.startswith("ref:"):
            ref_alt, ref_position = reference_companions(builder.model.references.get(value[4:]))
            alt = alt if alt is not None or not with_alt else ref_alt
            position = position if position is not None else ref_position
        return Picture(key, found[0], found[1], alt or "", position)
    return None


def step_picture(builder, piece):
    """A step's picture (`view: steps`): `tileImage`, else `photo`, else `cover`, with that picture's own alt."""
    return resolve(builder, piece, STEP_ORDER, True)


def card_picture(builder, piece, settings):
    """A grid or featured card's picture under the piece's own portfolio `settings`: `photo`, else `cover`, when the
    `cardImage` trigger is on with the value `photo`; else `cover`. Its alt is "" unless `cardAlt` is on."""
    on = active_triggers(settings)
    order = CARD_PHOTO_ORDER if ("cardImage" in on and settings.get("cardImage") == "photo") else CARD_ORDER
    return resolve(builder, piece, order, "cardAlt" in on)


def roles_picture(builder, newest, settings):
    """A roles card's picture, only under the `cardImage` trigger (either value, under `view: roles`): the group's
    newest piece's picture, as a card's. None without the trigger: a roles card has had no picture."""
    if "cardImage" not in active_triggers(settings):
        return None
    return card_picture(builder, newest, settings)


def roles_image_slot(builder, part, newest, out):
    """The GATED `image` slot of a roles card (`roles-view.item` or `item-current`, rule L3a): the `card-picture`
    construct holding the group's newest piece's picture, with the link to `schema-5.css`, when that piece's own
    portfolio holds `cardImage`; else ""."""
    settings = builder.model.portfolio(newest.portfolio).settings
    picture = roles_picture(builder, newest, settings)
    if picture is None:
        return ""
    markup = builder.assets(out, "card-picture") + builder.r(
        "card-picture", "wrap", {"image": picture.html(builder, out)}, newest.source)
    return looks.gate("roles-view", part, "image", active_triggers(settings), markup)
