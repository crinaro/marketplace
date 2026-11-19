"""configkeys: the key tables and constants of `site/site.json` and of a page's front matter, schemas 1 to 4.

Constants only: the schema ceiling, the engine marker, each key table, the budget defaults and the patterns the
value checks use. No code runs here."""

import re


SCHEMA_MAX = 4
ENGINE_MARKER = "site-studio"
CANONICAL_MARKER_LINE = '  "engine": "site-studio",'

KEY_ORDER = (
    "schema", "engine", "name", "siteTitle", "publicRepo", "previewUrl", "domain", "cutover",
    "publicEmails", "privateTerms", "work", "redirects", "resume", "budgets",
)
# Schema 2 adds these two top-level keys (and `labels` inside WORK_KEYS). KEY_ORDER stays the
# schema-1 key set; CANON_ORDER is the written order with the schema-2 keys placed in it.
V2_TOP_KEYS = ("siteKind", "featuredFrom")
CANON_ORDER = (
    "schema", "engine", "name", "siteTitle", "siteKind", "publicRepo", "previewUrl", "domain",
    "cutover", "publicEmails", "privateTerms", "work", "featuredFrom", "nav", "look", "blocks", "redirects",
    "resume", "budgets",
)
# Schema 4 adds these top-level keys (design-template-fidelity section 3.2), refused below 4.
V4_TOP_KEYS = ("nav", "look", "blocks")
SITE_KINDS = ("portfolio", "hub", "custom")
FEATURED_FROM = ("home", "flags")
WORK_KEYS = ("label", "description", "required", "meta", "cardMeta", "groupBy", "groups", "labels",
             "cardNumber", "cardNumberFormat", "cardLabels", "backLink")
# The portfolio keys schema 4 adds (the last four of WORK_KEYS). Each is stored in a parsed `work` ONLY when it is
# not its default (cardNumber false, cardNumberFormat "padded", cardLabels true, no backLink), the way `labels` is,
# so a schema-3 site's settings stay what they were and `content.py`'s merge of site.json `work` with a page.md
# never carries a default key down to a schema that refuses it.
V4_WORK_KEYS = ("cardNumber", "cardNumberFormat", "cardLabels", "backLink")
# How the card's number prints: "padded" (the default) the order to two digits and the year, `02 / 2025`; "plain" the
# order as it is and the year, `2 / 2025`; "order" the order as it is and nothing else, `2`. The key says WHAT the
# card prints, so the third value is one more word for it, not a second key that only means something beside "plain".
CARD_NUMBER_FORMATS = ("padded", "plain", "order")
# `blocks` (schema 4, a top-level object): the settings of the plugin's `:::` blocks and of the `ref:` lines a body holds. Its
# keys are `headingLevel` (the h-level of a heading inside a block), `loneReferenceGrid` (a lone `ref:` line prints inside
# the reference grid, as two or more do; the default, false, is a bare card) and `videoEmbed` (the address a video block and a gallery
# video carry: "facade", the default, adds Vimeo's `dnt=1`; "live" keeps the player's own address, as a site built elsewhere wrote it).
BLOCKS_KEYS = ("headingLevel", "loneReferenceGrid", "videoEmbed")
VIDEO_EMBED_FORMS = ("facade", "live")
BLOCK_HEADING_LEVELS = (2, 3, 4, 5, 6)
LABEL_PARTS = ("meta", "groups")
RESUME_KEYS = ("path", "pdf", "paper", "headings", "layout")
V4_RESUME_KEYS = ("headings", "layout")          # schema 4; stored only when not the default
RESUME_HEADINGS = ("shift", "as-written")
RESUME_LAYOUTS = ("plain", "cards")
NAV_KEYS = ("home",)
PAPERS = ("Letter", "A4")

# The performance limits of design 4.3 (B's numbers), overridable in `budgets`.
BUDGET_DEFAULTS = {
    "sizeCopyOverKB": 250,    # an image over this needs size copies
    "firstViewMaxMB": 1.5,    # first-view images per page, at 2x
    "pageImagesMaxMB": 5,     # all images per page, at 2x
    "treeMaxMB": 200,         # whole published tree (the Pages limit is 1 GB)
}

DEFAULT_RESUME_PATH = "content/resume/resume.md"
DEFAULT_RESUME_PDF = "content/resume/resume.pdf"

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_LOOK_RE = re.compile(r"^site/looks/[a-z0-9][a-z0-9-]*\.json$")
ADDRESSES_RECORD = ".site-studio/addresses.json"


V3_PAGE_KEYS = ("order", "tagline", "sort", "menuLinks", "view")
# What each key takes, and what a portfolio is without it (0.2.0's behaviour; design-site-fidelity section 6.2).
PAGE_SORTS = ("date", "order")
PAGE_MENU_LINKS = ("index", "single-piece")
PAGE_VIEWS = ("grid", "page")
# Schema 4 (design-template-fidelity section 3.2): three more `view` values, and one more page.md key. The 0.3.x
# tuple above is NOT extended, so what reads PAGE_VIEWS keeps the schema-3 meaning (adopt's page.md check).
V4_PAGE_VIEWS = ("roles", "map", "showcase")
V4_PAGE_KEYS = ("mapMask", "onePieceIndex")
V4_PAGE_DEFAULTS = {"mapMask": None, "onePieceIndex": "redirect"}
# `onePieceIndex` (schema 4): what a portfolio's index is when `menuLinks: "single-piece"` has the menu link its one
# piece. "redirect" (the default, and what schema 3 always does) serves the index address as a redirect page to the
# piece; "listing" builds the index as the listing it is for any other portfolio, so a site whose old index listed its
# one piece keeps that page. The menu links the piece either way. Read only where `menuLinks` is "single-piece" and
# exactly one piece builds.
ONE_PIECE_INDEXES = ("redirect", "listing")
# The home, resume and reference keys schema 4 adds. `content.py` owns reading them; they are listed here only so
# that `schema_4_reasons` can say a tree holding one needs schema 4 (this module cannot import content).
V4_HOME_KEYS = ("eyebrow", "role", "showcase", "samples", "links")
# The home key that is a SETTING, not a part: `titleForm` chooses the form of the home page's `<title>`. "site" (the
# default, and what every schema writes) is the site title alone; "page" is `<home title> | <site title>`, the form
# every other page's title has. It is not in V4_HOME_KEYS, which is the list of fixed PART names (`{{home:<part>}}`).
V4_HOME_SETTING_KEYS = ("titleForm", "introScope", "partOrder")
V4_HOME_PAGE_KEYS = V4_HOME_KEYS + V4_HOME_SETTING_KEYS
HOME_TITLE_FORMS = ("site", "page")
# `introScope` (schema 4) is what the generated home's intro holds: "body" (the default, and the only reading below 4)
# is the whole body, a `:::part` block printed where it stands; "first-block" is the body's first block, with every other
# block outside the `:::part` blocks the part `rest`. `partOrder` (schema 4) is the order the generated home prints its
# parts in: the names below, and the name of each `:::part` block of the body. Either key makes a `:::part` block a part
# of its own (placed by the order, or after `rest` in the file's order), instead of printing where it stands. A part the
# order does not name follows the named ones, in the default order below, with the body's own parts after `rest`.
HOME_INTRO_SCOPES = ("body", "first-block")
HOME_SECTIONS = ("intro", "rest", "featured", "showcase", "feed", "samples", "links", "contact")
V4_RESUME_PAGE_KEYS = ("tagline", "links")
V4_REFERENCE_KEYS = ("image", "role", "fetched", "author")
# The home parts fixed at schema 4 and above: `{{home:<part>}}` names them without a `:::part` container, so they
# are the home KEYS' names. Below 4 each is a name a person may use for a custom part (design rule 7).
V4_PART_FIXED = V4_HOME_KEYS
V3_PAGE_DEFAULTS = {"order": None, "tagline": "", "sort": "date", "menuLinks": "index", "view": "grid"}
# A piece key the build already reads or shows, so a `meta`/`cardMeta` list that names one is refused at
# schema 3 (the build shows it already, and a second copy would print it twice). `featured` is reserved
# separately, only under `featuredFrom: flags`.
BUILTIN_PIECE_KEYS = ("shortTitle", "teaser", "coverPosition", "cover", "order", "title", "date", "draft")
