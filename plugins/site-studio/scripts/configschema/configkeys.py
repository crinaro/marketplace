"""configkeys: the key tables and constants of `site/site.json` and of a page's front matter, schemas 1 to 9.

Constants only: the schema ceiling, the engine marker, each key table, the budget defaults and the patterns the
value checks use. No code runs here."""

import re


SCHEMA_MAX = 9
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
    "schema", "engine", "name", "siteTitle", "titleSeparator", "siteKind", "publicRepo", "previewUrl", "domain",
    "cutover", "publicEmails", "privateTerms", "work", "featuredFrom", "featuredView", "nav", "look", "lookLocal",
    "blocks", "references", "mediaPaths", "sizeCopies", "carried", "redirects", "resume", "budgets",
)
# Schema 4 adds these top-level keys (design-template-fidelity section 3.2), refused below 4.
V4_TOP_KEYS = ("nav", "look", "blocks")
# Schema 6 adds these top-level keys (design-adopt-parity-2 section 3.2), each a K reason: 0.5.x refuses every one as an
# unknown key, and each is stored only when it is not its default, so a schema-5 config's dict is what it was.
V6_TOP_KEYS = ("featuredView", "titleSeparator", "mediaPaths", "sizeCopies", "carried")
# Schema 7 adds one top-level key (design-adopt-ownership-line section 2.1), a K reason: 0.6.0 refuses it as an unknown
# key (TESTED at step 0, U-B1). `lookLocal` names the person's own look, laid over the look `look` names (or over the
# default look when there is none); it is exactly LOOK_LOCAL_PATH, and `look` may not name that file too.
V7_TOP_KEYS = ("lookLocal",)
# Schema 9 adds one top-level key (design-reference-layout section 1.3), a K reason: 0.8.0 refuses it as an unknown key.
# `references` holds the site's own vocabularies for a reference's `type` and `channel` (`REFERENCES_KEYS`); `{}` is the default
# and is written away.
V9_TOP_KEYS = ("references",)
LOOK_LOCAL_PATH = "site/looks/local.json"
# design-adopt-ownership-line 2.5, 2.6 and 3.1: the look derive writes, its stamp (committed with it, never read by a build) and
# adopt's two scratch files, which are never committed and are never a dirty path at the three dirty tests (parity's
# `preconditions`, `addresses._git_status`, `look.py use`).
DERIVED_LOOK_PATH = "site/looks/derived.json"
STAMP_REL = ".site-studio/derived-look.json"
CANDIDATES_REL = ".site-studio/look-candidates.json"
ADOPT_SCRATCH = (".site-studio/adopt-plan.json", CANDIDATES_REL)
# `featuredView`: how `{{featured}}` and the generated home's featured part print the selection. "flat" (the default,
# written away) is today's one run of cards; "grouped" is a filtered view of each portfolio's index (section 4.1).
FEATURED_VIEWS = ("flat", "grouped")
# `titleSeparator`: the text between a page's title and the site title in `<title>`: one to three punctuation marks or
# symbols (Unicode categories P* and S*), with at most one space on each side. The default is written away.
TITLE_SEPARATOR_DEFAULT = " | "
TITLE_SEPARATOR_MAX = 3
# `sizeCopies`: "any-format" lets a size copy have another raster extension than its original (section 4.6).
SIZE_COPIES = ("any-format",)
SIZE_COPY_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")
# `mediaPaths`: where a folder's media is published, one pattern per folder (section 4.6): two to four `/`-separated
# segments, each a slug or `{name}`, the last `{file}`; `references` holds `{name}` once, `home` and `about` hold none.
MEDIA_PATH_FOLDERS = ("references", "home", "about")
MEDIA_PATH_SEGMENTS = (2, 4)
# `carried`: one to 24 output paths, each served from `site/carried/<path>` byte for byte (section 4.7). A file the build
# owns for deployment is never carried, nor anything under `site-studio/`, nor a name the site gate never publishes. The
# last four tables are the site gate's own (`sitechecks/kinds.py` `FORBIDDEN_NAMES`, `FORBIDDEN_DIRS`, `JUNK_NAMES`,
# `JUNK_SUFFIXES`), copied because `configschema` may not import `sitechecks` (G6: the import would close a cycle between
# the two packages); `tests/configschema/test_sectioncheck.py` `CarriedNamesAreTheGates` holds each equal to the gate's.
CARRIED_MAX = 24
CARRIED_SOURCE = "site/carried/"
CARRIED_RESERVED = ("CNAME", ".nojekyll", "robots.txt", "sitemap.xml")
CARRIED_RESERVED_DIRS = ("site-studio",)
GATE_FORBIDDEN_NAMES = ("CLAUDE.md", "HANDOFF.md", "BRAND.md", "site.json", "layout.html", "text.md",
                        "reference.json", "package.json", "package-lock.json")
GATE_FORBIDDEN_DIRS = (".git", ".site-studio", ".github", "decisions", "originals", "node_modules",
                       "__MACOSX", "templates")
GATE_JUNK_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")
GATE_JUNK_SUFFIXES = ("~", ".bak", ".orig", ".part", ".tmp", ".swp", ".md", ".pdf.json", ".jsonl", ".py")
SITE_KINDS = ("portfolio", "hub", "custom")
FEATURED_FROM = ("home", "flags")
WORK_KEYS = ("label", "description", "required", "meta", "cardMeta", "groupBy", "groups", "labels",
             "cardNumber", "cardNumberFormat", "cardLabels", "backLink",
             "cardImage", "cardAlt", "cardKicker", "pieceLink", "pieceTeaser", "groupCount", "pieceRoles")
# The portfolio keys schema 4 adds (the last four of WORK_KEYS). Each is stored in a parsed `work` ONLY when it is
# not its default (cardNumber false, cardNumberFormat "padded", cardLabels true, no backLink), the way `labels` is,
# so a schema-3 site's settings stay what they were and `content.py`'s merge of site.json `work` with a page.md
# never carries a default key down to a schema that refuses it.
V4_WORK_KEYS = ("cardNumber", "cardNumberFormat", "cardLabels", "backLink")
# How the card's number prints: "padded" (the default) the order to two digits and the year, `02 / 2025`; "plain" the
# order as it is and the year, `2 / 2025`; "order" the order as it is and nothing else, `2`. The key says WHAT the
# card prints, so the third value is one more word for it, not a second key that only means something beside "plain".
CARD_NUMBER_FORMATS = ("padded", "plain", "order")
# The portfolio settings schema 5 adds (design-movement-view section 3.2; the last five of WORK_KEYS), each a K trigger:
# 0.4.x refuses every one, so no tree it accepted holds one. Each is stored in a parsed `work` only when the person set
# it, so a schema-4 settings dict is what it was. `cardImage` is the picture a card shows ("cover" or "photo"),
# `cardKicker` names the piece key printed as a card's kicker line, and `cardAlt`, `pieceLink` and `pieceTeaser` take
# `true` only. `cardImage: cover` is kept as written: under `view: roles` it is not the default (a roles card has no
# picture without it), so it is a reason by presence and never written away.
V5_WORK_KEYS = ("cardImage", "cardAlt", "cardKicker", "pieceLink", "pieceTeaser")
CARD_IMAGES = ("cover", "photo")
# The portfolio settings schema 6 adds (design-adopt-parity-2 section 3.2; the last two of WORK_KEYS), each `true` only and
# each a K trigger: `groupCount` (each group heading prints how many pieces it shows; refused without `groupBy`) and
# `pieceRoles` (a piece's `role` is a list of dated roles, `V6_PIECE_KEYS`). Schema 6 also adds a VALUE, `cardAlt: "title"`
# (a card picture's alt is the piece's title), and a `labels` part, `counts` (`V6_LABEL_PARTS`).
V6_WORK_KEYS = ("groupCount", "pieceRoles")
CARD_ALT_TITLE = "title"
# `blocks` (schema 4, a top-level object): the settings of the plugin's `:::` blocks and of the `ref:` lines a body holds. Its
# keys are `headingLevel` (the h-level of a heading inside a block), `loneReferenceGrid` (a lone `ref:` line prints inside
# the reference grid, as two or more do; the default, false, is a bare card) and `videoEmbed` (the address a video block and a gallery
# video carry: "facade", the default, adds Vimeo's `dnt=1`; "live" keeps the player's own address, as a site built elsewhere wrote it).
BLOCKS_KEYS = ("headingLevel", "loneReferenceGrid", "videoEmbed", "unlistedVideos", "headings")
# `blocks.headings` (schema 6): the h-level of a heading in every Markdown body but the resume's (which keeps
# `resume.headings`), with the resume's two values (`RESUME_HEADINGS`); "shift", the default, is written away.
V6_BLOCKS_KEYS = ("headings",)
# `blocks.unlistedVideos` (schema 9, design-reference-layout section 2, owner answer O-1 b): `true` only. When it is set, an unlisted
# Vimeo link's private code is sent to the player; absent, it is not, and the build says which links it leaves out. It sits before
# `headings` in `BLOCKS_KEYS` so the schema-6 key stays that table's tail (`V6_BLOCKS_KEYS`). A K reason: 0.8.0 refuses the key.
V9_BLOCKS_KEYS = ("unlistedVideos",)
VIDEO_EMBED_FORMS = ("facade", "live")
BLOCK_HEADING_LEVELS = (2, 3, 4, 5, 6)
LABEL_PARTS = ("meta", "groups")
# `labels.counts` (schema 6): the word after a group's count, per group value or `*`, under CLDR's plural category names.
# 0.6.0 prints two forms; CLDR's other four names are reserved (refused, naming the release), so a later release can read
# them as its own K reason without changing what a 0.6.0 tree means.
V6_LABEL_PARTS = ("counts",)
COUNT_ANY = "*"
COUNT_FORMS = ("one", "other")
COUNT_FORMS_RESERVED = ("zero", "two", "few", "many")
RESUME_KEYS = ("path", "pdf", "paper", "headings", "layout", "titleForm")
V4_RESUME_KEYS = ("headings", "layout")          # schema 4; stored only when not the default
RESUME_HEADINGS = ("shift", "as-written")
RESUME_LAYOUTS = ("plain", "cards")
# Schema 8 (design-adopt-local-reach section 1.1): `resume.titleForm`, what the resume page's `<title>` leads with: "title" (the
# default, written away: the resume's own `title`) or "page" (the label the site's menu prints for the resume page). A K
# reason: 0.7.0 refuses the key as unknown.
V8_RESUME_KEYS = ("titleForm",)
RESUME_TITLE_FORMS = ("title", "page")
NAV_KEYS = ("home", "extra", "labels")
# Schema 6 (design-adopt-parity-2 section 3.2): `nav.home` gains the value "title" (the first item's text is the site
# title), and `nav.extra` is one to four `{"label", "url"}` items after the built-in ones, each url an absolute `https:` or
# `mailto:` address.
V6_NAV_KEYS = ("extra",)
NAV_HOME_TITLE = "title"
# Schema 8 (design-adopt-local-reach section 1.6, owner decision O-3 a): `nav.labels`, an object with keys from `NAV_LABEL_KEYS`,
# each a non-empty one-line label the menu prints for the built-in About or Resume page; absent or `{}` is the default and is
# written away. A K reason: 0.7.0 refuses `nav.labels` as an unknown key.
V8_NAV_KEYS = ("labels",)
NAV_LABEL_KEYS = ("about", "resume")
NAV_EXTRA_MAX = 4
NAV_EXTRA_SCHEMES = ("https://", "mailto:")
PAPERS = ("Letter", "A4")
# `references` (schema 9, design-reference-layout section 1.3): the site's own vocabularies. `types` and `channels` are each one to
# `REFERENCE_WORDS_MAX` distinct one-line words (compared in NFC, case-sensitively); `unprinted` names, per key of
# `REFERENCE_UNPRINTED_KEYS`, the words that are stored but never printed. A word is at most `REFERENCE_WORD_MAX` characters, the
# limit of a `type` or `channel` value (a longer word could never be used).
REFERENCES_KEYS = ("types", "channels", "unprinted")
REFERENCE_UNPRINTED_KEYS = ("type", "channel")
REFERENCE_WORDS_MAX = 60
REFERENCE_WORD_MAX = 80
# The starter words (owner answer O-3 a): the words capture and adopt PROPOSE and the documentation shows, never a check and never
# stored without the person's yes. No starter `site.json` sets them (that would put every new site at schema 9), and a site's own
# list replaces them.
REFERENCE_TYPES_STARTER = ("Article", "Blog", "Case study", "Film", "Interview", "Podcast", "Post", "Presentation", "Press",
                           "Report", "Video", "Website")
REFERENCE_CHANNELS_STARTER = ("Bluesky", "Facebook", "Instagram", "LinkedIn", "Medium", "Pinterest", "Substack", "Threads",
                              "TikTok", "Website", "X", "YouTube")

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
# Schema 5 (design-movement-view section 3.2): the steps view, an ordered run of numbered steps. Neither tuple above is
# extended, so what reads them keeps its schema-3 or schema-4 meaning.
V5_PAGE_VIEWS = ("steps",)
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
# The reference keys schema 5 adds: the alt and the `object-position` of a reference's card picture (design section 5).
V5_REFERENCE_KEYS = ("imageAlt", "imagePosition")
# The reference keys schema 9 adds (design-reference-layout section 1.1): the piece a reference is for, what it is, and where its
# audience saw it. Each is one line of text, optional, and blank reads as absent. This table is S0's; the value rules are
# `contentmodel/referencelayout.py`'s. A K reason by presence: 0.8.0 refuses each key as unknown, a blank value included.
V9_REFERENCE_KEYS = ("project", "type", "channel")
# The most characters a `type` or `channel` value holds, after trimming (a `project` slug has no limit).
REFERENCE_VALUE_MAX = REFERENCE_WORD_MAX
# The home parts fixed at schema 4 and above: `{{home:<part>}}` names them without a `:::part` container, so they
# are the home KEYS' names. Below 4 each is a name a person may use for a custom part (design rule 7).
V4_PART_FIXED = V4_HOME_KEYS
V3_PAGE_DEFAULTS = {"order": None, "tagline": "", "sort": "date", "menuLinks": "index", "view": "grid"}
# A piece key the build already reads or shows, so a `meta`/`cardMeta` list that names one is refused at
# schema 3 (the build shows it already, and a second copy would print it twice). `featured` is reserved
# separately, only under `featuredFrom: flags`.
BUILTIN_PIECE_KEYS = ("shortTitle", "teaser", "coverPosition", "cover", "order", "title", "date", "draft")
