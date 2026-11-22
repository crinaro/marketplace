"""places: the parts a recorded call may be read as in one place, and the derive readings that try them (design-adopt-parity-2
sections 4.5, 4.8 and 6, rule L6).

A build renders some places through a part of their own where the site's look writes one (`OPTIONAL_PARTS`), and through the
site-wide part where it does not. The recording is made under a look that writes none, so every such call is recorded as the
site-wide part; derive reads it as the place's own part only where the site-wide reading leaves the construct unmapped or
ambiguous, and keeps that reading only when it maps more (`derive.derive_look`). Three families, each one table:

    picture_places() (place construct, item part) whose picture renders through `<place>.image` (0.5.0's `PLACE_PICTURES`,
                     read from `lookgrammar.constructs.PLACE_PARTS`: the entries whose site-wide part is an `image` part);
                     picture_parts() the `(place, "image")` parts themselves
    card_places()    {place construct: its item part} whose reference card renders through `<place>.item` (0.6.0: `feed.item`,
                     `home-samples.item`, the entries of PLACE_PARTS whose site-wide part is `reference-card.wrap`)
    NAV_STATES       {navparts state: the optional `nav` part an item in that state renders through} (0.6.0, section 4.5: the
                     brand and the section mark). The recording tags each nav call with the part its state would take
                     (`renderlog.recording`), since its values cannot say which item is the brand.

    place_of(call)          the place construct whose card `call` (a `reference-card.wrap` call) is printed in, else None
    families(calls, files)  [(name, [(call, construct, part)])]: the readings L6 may try, in order, each only for a tree that may
                            hold its parts (a 0.6.0 part only in a schema-6 tree: a tree 0.5.x accepts derives as 0.5.x did)
"""

import functools
import json

import looks
from lookgrammar.constructs import PART_FIRST, PLACE_PARTS

NAV_STATES = {"brand": "brand", "brand-current": "brand-current", "section": "-section"}


@functools.lru_cache(maxsize=None)
def picture_places():
    return tuple(sorted((c, "item") for (c, p), (sc, _sp) in PLACE_PARTS.items() if sc == "image" and p == "image"))


@functools.lru_cache(maxsize=None)
def picture_parts():
    return frozenset((c, "image") for c, _p in picture_places())


def card_places():
    return dict((c, p) for (c, p), site in PLACE_PARTS.items() if site == ("reference-card", "wrap"))


def nav_own(base, state):
    """The optional `nav` part an item of `state` renders through where the look writes it (`building/navparts.part`), else None:
    `brand`, `brand-current`, or `<base>-section`."""
    own = NAV_STATES.get(state)
    if own is None:
        return None
    return base + own if own.startswith("-") else own


def place_of(call):
    """The place (`feed`, `home-samples`) whose card `call` is, by its nearest ancestor that is a place's wrap; None elsewhere."""
    if call.key != ("reference-card", "wrap"):
        return None
    p = call.parent
    while p is not None:
        if p.construct in card_places() and p.part == "wrap":
            return p.construct
        p = p.parent
    return None


def _schema(files):
    try:
        return int(json.loads(files["site/site.json"].decode("utf-8")).get("schema") or 0)
    except (KeyError, ValueError, TypeError, AttributeError):
        return 0


def families(calls, files):
    """The L6 readings to try, in order: [(name, [(call, construct, part)])], each non-empty. `cards` reads every reference card
    printed in a place as that place's item part; `nav` reads every nav item recorded with an own part (`call.own`) as it."""
    if _schema(files) < 6:
        return []
    out = []
    cards = [(c, place_of(c)) for c in calls]
    cards = [(c, p, card_places()[p]) for c, p in cards if p is not None]
    if cards:
        out.append(("cards", cards))
    nav = [(c, "nav", c.own) for c in calls if getattr(c, "own", None) and c.construct == "nav"
           and PART_FIRST.get(("nav", c.own)) and c.own in looks.CONSTRUCTS["nav"]["parts"]]
    if nav:
        out.append(("nav", nav))
    return out


def read_as(group):
    """Read each call of `group` as its own part; returns the undo."""
    for c, construct, part in group:
        c.as_part(construct, part)

    def undo():
        for c, _construct, _part in group:
            c.as_recorded()
    return undo
