"""navparts: the site nav's item states and the look part each one renders through (design-adopt-parity-2 section 4.5).

    state(key, to, current_out, brand)   "current", "section", "brand", "brand-current" or "" for one built-in item
    extra_entries(builder, current_out)  schema 6's `nav.extra` items, last, never current
    part(builder, base, state)           the `nav` part an item of that state renders through (`base` is `item` for
                                         `{{nav}}`, `link` for `{{navLinks}}`)

Default path, stated: a "section" item (the item whose page is an ancestor of this page, such as a piece's portfolio)
renders through `nav.item-section` / `nav.link-section` only where the site's own look writes that OPTIONAL part, else
through `item` / `link`, exactly as before; the default look writes none, and a look that writes one needs 0.6.0. The
brand states exist only under schema 6's `nav.home: "title"`. So no tree 0.5.x accepted changes by a byte."""

from configschema.configkeys import NAV_HOME_TITLE

import looks

from building.tokens import _page_dir


def state(key, to, current_out, brand):
    """The state of one built-in item: `key` its page key ("" for the home), `to` its output page, `brand` whether it
    is the home item under `nav.home: "title"`. The current page is "current" (`brand-current` for the brand); a page
    whose folder holds this page is "section" (never the home, which holds every page)."""
    if to == current_out:
        return "brand-current" if brand else "current"
    if brand:
        return "brand"
    if key and _page_dir(current_out).startswith(key + "/"):
        return "section"
    return ""


def home_label(cfg):
    """The home item's label, or None when the nav has no home item (`nav.home: false`, schema 4): the site title under
    `nav.home: "title"` (schema 6), else `Home`."""
    home = cfg.nav.get("home", True)
    if home is False:
        return None
    return cfg.siteTitle if home == NAV_HOME_TITLE else "Home"


def extra_entries(builder):
    """[(href, label, state)] of `nav.extra` (schema 6): each absolute address as written, last, in order, never current
    (an address outside the site is never this page)."""
    return [(item["url"], item["label"], "") for item in builder.cfg.nav.get("extra", ())]


def part(builder, base, st):
    """The `nav` part an item in state `st` renders through. "" is `base`; "current" is `base-current`. The others are
    OPTIONAL parts, used only where the site's own look writes one, else the part the same item had before 0.6.0: a
    section item `base-section`, else `base`; the brand `brand` (`brand-current` on the home page), else `base`
    (`base-current`)."""
    if not st:
        return base
    if st == "current":
        return base + "-current"
    if st == "section":
        own = base + "-section"
        return own if looks.optional_part("nav", own, builder.look) is not None else base
    own = "brand-current" if st == "brand-current" else "brand"
    if looks.optional_part("nav", own, builder.look) is not None:
        return own
    return base + ("-current" if st == "brand-current" else "")
