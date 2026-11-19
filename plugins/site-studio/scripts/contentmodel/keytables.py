"""The tables of names the content model reads: slugs, dates, the keys each page and reference may carry
at each schema."""

import re

from configschema.configkeys import V4_HOME_PAGE_KEYS, V4_REFERENCE_KEYS, V4_RESUME_PAGE_KEYS


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

TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".md", ".txt", ".xml", ".svg",
             ".webmanifest")

HOME_KEYS = ("title", "description", "featured", "feed", "endorsement", "photo", "photoAlt",
             "contact")

HOME_KEYS_V4 = V4_HOME_PAGE_KEYS

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


def home_keys(schema):
    """The front matter keys a home page reads at `schema`: the 0.3.x set, and from schema 4 the five parts and `titleForm`."""
    return HOME_KEYS + (HOME_KEYS_V4 if schema >= 4 else ())


def resume_page_keys(schema):
    """The front matter keys the resume page reads at `schema` (`contact` from 3, `tagline` and `links` from 4)."""
    return RESUME_PAGE_KEYS + (("contact",) if schema >= 3 else ()) + (RESUME_PAGE_KEYS_V4 if schema >= 4 else ())


def reference_keys(schema):
    """The `reference.json` keys read at `schema`."""
    return REFERENCE_KEYS + (REFERENCE_KEYS_V4 if schema >= 4 else ())
