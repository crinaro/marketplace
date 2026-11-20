"""stepsview: the steps view, a portfolio index whose `page.md` says `view: steps` (design-movement-view section 4.1).

An ordered run of numbered steps, one per piece, in the portfolio's own piece order (its `sort`, as every index). A step
links its piece and shows, in the look's `steps-view.item` order:

    image    the picture, alt and position of section 5's step rule (`pictures.step_picture`: tileImage, photo, cover)
    number   its place in that order, from 1, printed as two digits (`07`; three or more as they are). The order is the
             pieces that build: a publish build loads no draft, so a draft is never counted there
    kicker   the value of the key `cardKicker` names, under that trigger (a list joined with ", ")
    title    `shortTitle`, else `title`; `fullTitle` is the piece's own `title` (step G, O4a: no default part holds it)
    role     `tileRole`, else `role` (a list joined with " / ", or with the site's own `steps-view.role-sep` literal
             when its look writes one: step G, O2), else none

The picture renders through the site's own `steps-view.image` part when its look writes one (step G, O3), else through
the site-wide `image` construct.

A portfolio with no pieces has no list, as a grid. Nothing here reads the clock or the network. Every element comes from
the look (`steps-view`, `kicker`), and the page that prints one links `schema-5.css` through the construct's own `assets`
entry. `views.index_html` dispatches here; the trigger of every value is the PIECE'S OWN portfolio's
(`model.portfolio(piece.portfolio)`), as the cards and tiles read theirs."""

import html

from contentmodel import frontmatter
from contentmodel.errors import ContentError
from contentmodel.keytables import active_triggers

import looks

from building import pictures


def step_number(place):
    """The printed number of the step at `place` (1 for the first): two digits, `07`; three or more as they are."""
    return "%02d" % place


def piece_triggers(builder, piece):
    """The schema-5 triggers of the piece's OWN portfolio (design-movement-view section 8 `GatedSlotsEmpty`): never the
    portfolio of the page the piece is shown on, and never another portfolio's."""
    return active_triggers(builder.model.portfolio(piece.portfolio).settings)


def kicker(builder, piece, out, triggers=None):
    """The `kicker` construct for `piece`, with the link to `schema-5.css`: the value of the key its own portfolio's
    `cardKicker` names (a list joined with ", "). "" when that trigger is off or the piece has no such key."""
    triggers = piece_triggers(builder, piece) if triggers is None else triggers
    if "cardKicker" not in triggers:
        return ""
    value = piece.meta.get(builder.model.portfolio(piece.portfolio).settings["cardKicker"])
    if value is None or value == [] or value == "":
        return ""
    return builder.assets(out, "kicker") + builder.r("kicker", "wrap", {"text": frontmatter.meta_text(value)},
                                                       piece.source)


def kicker_slot(builder, construct, part, piece, out):
    """The GATED `kicker` slot of an existing part (`card.wrap`, a roles card, a showcase or home showcase tile; rule
    L3a): `kicker`'s markup when the piece's own portfolio holds `cardKicker`, else "". The asset link is made only
    when the slot is filled, so no page of a tree without the trigger links `schema-5.css`."""
    triggers = piece_triggers(builder, piece)
    if "cardKicker" not in triggers:
        return ""
    return looks.gate(construct, part, "kicker", triggers, kicker(builder, piece, out, triggers))


def _one_line(piece, key):
    """0.4.0's check of a tile's one-line keys, kept where the steps view reads them (`views._tile` holds the same)."""
    value = piece.meta.get(key)
    if value is not None and (not isinstance(value, str) or not value.strip() or "\n" in value):
        raise ContentError("%s: front matter '%s' must be one line of text" % (piece.source, key),
                           path=piece.source, fix="write %s as one line of text, or remove it" % key)
    return value


def role_separator(builder):
    """What a step's list `role` is joined with: the literal text of the site's own `steps-view.role-sep` part (step G,
    O2; its entities read as the characters they name, since the role line is a text slot), else " / " as before."""
    own = looks.optional_part("steps-view", "role-sep", builder.look)
    return " / " if own is None else html.unescape(own)


def role_line(builder, piece):
    """`tileRole`, else `role` (text, or a list joined with `role_separator`), else "" (no role line)."""
    _one_line(piece, "tileAlt")
    role = _one_line(piece, "tileRole")
    if role is None and piece.meta.get("role") is not None:
        role = builder.views()._titles(piece)          # the check of `role`, and its value when it is text
        if isinstance(piece.meta["role"], list):
            role = role_separator(builder).join(x.strip() for x in piece.meta["role"])
    return role or ""


def step_html(builder, piece, place, out):
    picture = pictures.step_picture(builder, piece)
    image = pictures.place_html(builder, "steps-view", picture, out) if picture else ""
    role = role_line(builder, piece)
    line = builder.r("steps-view", "role", {"text": role}, piece.source) if role else ""
    url = builder.link(out, "%s/%s/index.html" % (piece.portfolio, piece.slug))
    return builder.r("steps-view", "item", {
        "url": url, "image": image,
        "number": builder.r("steps-view", "number", {"n": step_number(place)}, piece.source),
        "kicker": kicker(builder, piece, out),          # a new part's own slot: not gated, printed under cardKicker
        "title": piece.card_title, "fullTitle": piece.title, "role": line}, piece.source)


def steps_html(builder, portfolio, out):
    """The `cards` slot of a portfolio index under `view: steps`."""
    items = "".join(step_html(builder, piece, n, out) for n, piece in enumerate(portfolio.pieces, 1))
    return builder.assets(out, "steps-view") + builder.r(
        "steps-view", "wrap", {"items": items, "label": portfolio.title, "count": len(portfolio.pieces)})
