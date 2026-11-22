"""The tables of names the content model reads: slugs, dates, the keys each page and reference may carry
at each schema."""

import re

from configschema.configkeys import V4_HOME_PAGE_KEYS, V4_REFERENCE_KEYS, V4_RESUME_PAGE_KEYS, V5_REFERENCE_KEYS


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

POSITION_RE = re.compile(r"^[a-z0-9% .-]{1,40}$")

SHA_RE = re.compile(r"^[0-9a-f]{64}$")

RESERVED_PORTFOLIO_NAMES = ("media", "resume", "references", "about", "home")

CARD_EXTS = (".jpg", ".jpeg", ".png", ".webp")

REFERENCE_KEYS = ("url", "title", "description", "site", "published", "kind", "captured")

# Schema 4 (template-fidelity 1.3, design section 3.2). The 0.3.x tuples above are NOT extended: a key a tuple
# names is accepted at every schema, and what a tuple does not name 0.3.x refused. `siteconfig` owns the names
# (it lists them for its schema-4 reasons); the readers below add them at schema 4 and above only.
REFERENCE_KEYS_V4 = V4_REFERENCE_KEYS

REFERENCE_KEYS_V5 = V5_REFERENCE_KEYS

TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".md", ".txt", ".xml", ".svg",
             ".webmanifest")

HOME_KEYS = ("title", "description", "featured", "feed", "endorsement", "photo", "photoAlt",
             "contact")

HOME_KEYS_V4 = V4_HOME_PAGE_KEYS

# The home keys the model reads as a LIST of names (design-movement-view section 6.2, dev #964): the one table the
# page check reads, and adopt's home rewrite after it. `showcase` and `samples` are schema-4 keys; a key that is not
# allowed at the page's schema is refused by the key check before any list check runs.
HOME_LIST_KEYS = ("featured", "feed", "showcase", "samples")

ABOUT_KEYS = ("title", "description", "endorsement", "photo", "photoAlt", "contact")

RESUME_PAGE_KEYS = ("title", "description")

RESUME_PAGE_KEYS_V4 = V4_RESUME_PAGE_KEYS

PORTFOLIO_PAGE_KEYS = ("title",)

# The piece keys a SETTING reads (design R4 row 6): a key `build` reads or shows only under a view or a
# portfolio setting, so `stray_warnings` does not call it unpublished where it is read. The key is the setting
# (`roles`, `map` and `showcase` are `view` values; `cardNumber` is the setting of that name). `showcase` is
# also read from a piece the home page's `showcase` list names, wherever its portfolio's view is.
VIEW_PIECE_KEYS = {
    "roles": ("employer", "role", "current", "period"),
    "map": ("pin",),
    "showcase": ("tileImage", "tileAlt", "tileRole", "role"),
    "cardNumber": ("year",),
}

# The piece keys schema 5 reads, each ONLY under one of its triggers (design-movement-view sections 3.1 rule 2 and
# 3.3): a trigger is a `view` value (`steps`) or a schema-5 portfolio setting, so no tree 0.4.x accepted has one, and
# without it the key is what it was (a free key: a stray warning, no output). Every reader, the stray check, the
# generated reference and the names corpus read this table; none types a key of its own (`PieceKeyReadsAreTabled`).
# The key `cardKicker` names is the person's own, so it is not a row: `piece_keys_read` adds it.
V5_PIECE_KEYS = {
    "tileImage": ("steps",),
    "tileAlt": ("steps",),
    "tileRole": ("steps",),
    "role": ("steps",),
    "tilePosition": ("steps",),
    "photo": ("steps", "cardImage"),
    "photoAlt": ("steps", "cardImage"),
    "photoPosition": ("steps", "cardImage"),
    "coverAlt": ("steps", "cardAlt"),
    "teaser": ("pieceTeaser",),
    "link": ("pieceLink",),
    "linkLabel": ("pieceLink",),
}

# The piece keys schema 6 reads, each ONLY under its K trigger `pieceRoles` (design-adopt-parity-2 sections 3.1 rule 3 and
# 3.2), the successor table of `V5_PIECE_KEYS`, read the same way by the same readers. Under the trigger `role` is a list
# of dated roles, `current: true` marks the piece current, and `currentRole` (a whole number from 1) names which entry
# of `role` is the current one (absent, the first). Without the trigger each is what it was in 0.5.x: `role` and
# `current` keep the readings a view gives them, and `currentRole` is a free key.
V6_PIECE_KEYS = {
    "role": ("pieceRoles",),
    "current": ("pieceRoles",),
    "currentRole": ("pieceRoles",),
}


def active_triggers(settings):
    """The schema-5 triggers a portfolio's settings turn on, as a set of `V5_PIECE_KEYS` trigger names: its `view` when
    that is `steps`, `cardImage` when a card reads `photo` (the value `photo`, or either value under `view: roles`, where
    a card has no picture without it), `cardAlt` when it is `true` (under schema 6's `cardAlt: "title"` the alt is the
    piece's title, so no alt key is read), `cardKicker`, `pieceLink`, `pieceTeaser` when set, and schema 6's
    `pieceRoles` (`V6_PIECE_KEYS`) and `groupCount` (the trigger of the gated `group.wrap` `count` slot; it reads no
    piece key). Empty for every settings dict 0.4.x could load."""
    on = set()
    view = settings.get("view")
    if view == "steps":
        on.add("steps")
    image = settings.get("cardImage")
    if image == "photo" or (image is not None and view == "roles"):
        on.add("cardImage")
    if settings.get("cardAlt") is True:
        on.add("cardAlt")
    for key in ("cardKicker", "pieceLink", "pieceTeaser", "pieceRoles", "groupCount"):
        if settings.get(key):
            on.add(key)
    return on


def piece_keys_read(settings):
    """{piece key: the triggers it is read under here} for the schema-5 and schema-6 keys this portfolio's settings read:
    every `V5_PIECE_KEYS` and `V6_PIECE_KEYS` row with an active trigger (a key in both tables, `role`, carries the
    triggers of both, schema 5's first), and the key `cardKicker` names."""
    on = active_triggers(settings)
    out = {}
    for table in (V5_PIECE_KEYS, V6_PIECE_KEYS):
        for key, triggers in table.items():
            hit = tuple(t for t in triggers if t in on)
            if hit:
                out[key] = out.get(key, ()) + hit
    if "cardKicker" in on:
        out.setdefault(settings["cardKicker"], ("cardKicker",))
    return out


def home_keys(schema):
    """The front matter keys a home page reads at `schema`: the 0.3.x set, and from schema 4 the five parts and `titleForm`."""
    return HOME_KEYS + (HOME_KEYS_V4 if schema >= 4 else ())


def resume_page_keys(schema):
    """The front matter keys the resume page reads at `schema` (`contact` from 3, `tagline` and `links` from 4)."""
    return RESUME_PAGE_KEYS + (("contact",) if schema >= 3 else ()) + (RESUME_PAGE_KEYS_V4 if schema >= 4 else ())


def reference_keys(schema):
    """The `reference.json` keys read at `schema` (`imageAlt` and `imagePosition` from 5)."""
    return REFERENCE_KEYS + (REFERENCE_KEYS_V4 if schema >= 4 else ()) + (REFERENCE_KEYS_V5 if schema >= 5 else ())
