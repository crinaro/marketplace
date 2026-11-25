"""adoption.settings -- the measured settings, and writing one into the converted tree (design 8, "Measured settings").

Part of the `adoption` package behind the entry point `adopt.py`.

A conversion that chooses a value from a finite set is a SETTING. The plan holds each as `settings[<name>] = {value, how,
reason}` (plan schema 2, design 3.5); `converted_site_files(..., settings={name: value})` writes it into the tree, and
`adoption.choose` decides it by measurement. The names, in the order they are chosen (`SETTING_ORDER`, greedy: each
choice fixes the one before it; interactions beyond that are design UNDETERMINED U-4):

  look                the site's look: `site-studio` (the default, no key) or `derived` (a look file vendored at
                      `site/looks/derived.json`, derived from the old builder's own pages, R6)
  featuredFrom        `home` (the default) or `flags` (a piece's `featured: true` feeds the home page), or adopt's own `showcase`
                      (step 5c-4): the pieces the home features (its `featured` list, else the flags) written as its `showcase`
                      list, which prints tiles where `featured` prints cards; offered only for a home with no `showcase` of its own
  sort.<portfolio>    `date` (the default) or `order` (every piece carries an integer `order`), in that portfolio's page.md
  nav.home            true (the default) or false: the nav without a Home item (`nav: {"home": false}`)
  nav.labels.about    absent (the default: the plugin's `About`) or the word the old menu prints for the about page (schema 8, `site.json`
  nav.labels.resume   `nav.labels`; `adoption.menulabels` reads it from the old build's own menu); `nav.labels.resume` is the same for `Resume`.
                      A site whose old menu says the default word writes no key
  resume.headings     `shift` (the default) or `as-written`
  resume.titleForm    `title` (the default) or `page` (schema 8, `resume.titleForm`): the resume's `<title>` leads with the menu's word for it
                      (`nav.labels.resume`) in place of the resume's own `title`; offered when the old resume `<title>` starts with that word
  cardLabels          true (the default) or false: card values without their labels
  resume.layout       `plain` (the default) or `cards`: the resume's roles as one card each (`resume.layout`, schema 4), for an old resume
                      page that sets each role in its own section
  workKeys            `work` (the default) or `all`: site.json's `work` object configures the portfolio named `work` ONLY, so an old site whose
                      one configuration (`meta`, `cardMeta`) applies to every portfolio needs those keys in each other portfolio's page.md
  cardNumber          false (the default) or true: a number on each card (P03: the piece's `order` and `year`), written into EVERY
                      portfolio's page.md (a page.md configures its own portfolio, and site.json's `work` the portfolio named `work` only)
  cardNumberFormat    `padded` (the default, `02 / 2025`), `plain` (`2 / 2025`) or `order` (`2`): what the number prints (schema 4)
  cardImage.<p>       absent (the default), `photo`, or `cover` under a roles view: the picture a card of portfolio <p> shows (schema 5,
                      design-movement-view 6.3); the five below are written into that portfolio's page.md, and absent writes no key
  cardAlt.<p>         absent or true: a card's picture carries its own alt key (schema 5)
  cardKicker.<p>      absent or the name of a piece key nothing reads: one line with each card and tile (schema 5)
  pieceLink.<p>       absent or true: a piece page prints the piece's `link` (schema 5)
  pieceTeaser.<p>     absent or true: a piece page prints the piece's `teaser` under its title (schema 5)
  backLink            absent (the default) or one line of text: a link to the portfolio index above the piece title (P06), with the
                      text the old builder's own piece pages carry (`work.backLink`); the candidate is read from the local build.
                      Schema 6's adopt measures it per portfolio, `backLink.<p>` (design-adopt-parity-2 section 7.6: the text THAT
                      portfolio's old piece pages share, written into its page.md); the site-wide name stays a setting a person may
                      have chosen, and writes what it wrote
  blocks.headingLevel absent (the default) or 2 to 6: the h-level of a heading inside a carousel slide (schema 4), `blocks.headingLevel`;
                      the candidates are the levels the old builder's own pages print headings at
  blocks.loneReferenceGrid
                      false (the default) or true: a `ref:` line that stands alone in a body prints inside the reference grid, as two or more do
                      (schema 4, `blocks.loneReferenceGrid`, site.json), for an old site that wraps a lone reference in a grid of one; offered
                      only where a body of the converted tree holds a lone `ref:` line
  blocks.videoEmbed   `facade` (the default) or `live` (schema 4, `blocks.videoEmbed`, site.json): a video's player address as the plugin writes it
                      (Vimeo's with `dnt=1`), or the player's own address with nothing added, for an old site whose pages hold live players;
                      offered only where the converted tree holds a `:::videos` block or a gallery video row. It changes the ADDRESS only:
                      whether a player loads with the page is the look's markup, so it is measured under the look derived for it
  blocks.unlistedVideos
                      absent (the default) or true (schema 9, `blocks.unlistedVideos`, site.json): the private code of an unlisted Vimeo link
                      (`vimeo.com/<id>/<code>`) is sent to the player, as the old site's player address carried it; the code is then in the
                      page, where a visitor can read it. Offered only where an old page's player address carries an `h`; judged with
                      `blocks.videoEmbed`, whose candidates are each scored under the better value of this one
  referenceLayout     absent (the default) or the list of reference keys written, of `project`, `type` and `channel` (schema 9, `reference.json`; dev
                      1061, the owner's answer O-2): the sure ones `adoption.referencepropose` suggests, written by default where no page gets
                      worse and site-studio is the publisher; `adopt.py setting referenceLayout none` (an empty list) or a part is the person's
                      word. Written by `convert` after the dispositions, so a reference the accounting archives is not one
  menuLinks.<p>       `index` (the default) or `single-piece`: a portfolio that builds exactly one piece has its menu link go to that piece
                      (V06), written as `menuLinks` in the portfolio's page.md; offered only for a one-piece portfolio
  onePieceIndex.<p>   `redirect` (the default) or `listing`: what the index of a one-piece portfolio under `menuLinks: single-piece` is (schema 4):
                      a page that sends the visitor to the piece, or the portfolio's listing as the old site had it; offered only for a
                      one-piece portfolio, written as `onePieceIndex` in the portfolio's page.md
  titleForm           `site` (the default) or `page` (schema 4): the home page's `<title>` is the site title alone, or the page's own title
                      and then the site title as on every other page; written in the home page's front matter
  introScope          `body` (the default) or `first-block` (schema 4): the generated home's intro holds the whole body, or its first block
                      beside the photo; offered only for a home body with more than one block outside its `:::part` blocks
  partOrder           absent (the default) or the list of the home page's parts in the order the OLD home page shows them (schema 4); the
                      candidate is read from the old build (`adoption.homeparts`) and kept only when the build agrees (it is measured)
  view.<portfolio>    the portfolio's `view`: `grid`, `page`, or a built-in index (`roles`, `map`, `showcase`)

Each setting names the OUTPUT PATHS it can touch (`setting_paths`), exact or ending in `/`, or `*`: a candidate is judged on
those pages only, so an unrelated difference elsewhere never counts against it. A setting that touches no page is never
measured. Every function here is pure over a tree-like object and the dicts it is handed.
"""

import json
import posixpath
import re
import unicodedata

from configschema import sectioncheck
from configschema.configkeys import (BUILTIN_PIECE_KEYS, COUNT_ANY, MEDIA_PATH_FOLDERS, NAV_HOME_TITLE, SIZE_COPIES,
                                     TITLE_SEPARATOR_DEFAULT, TITLE_SEPARATOR_MAX, V9_REFERENCE_KEYS, WORK_KEYS)
from configschema.diagnostics import SiteConfigError
from contentmodel.keytables import KEY_RE, piece_keys_read

from adoption import carry, lookwrite, menulabels
from adoption.base import Refused
from adoption.accounting import stale_line
from adoption.plan import _current_base, _plan_for, save_plan
from adoption.homeparts import HOME_PATHS, front_values
from adoption.template import _emit, _list_entry, _yaml, entries, home_path, scalar, split_front

# The five schema-5 portfolio settings (design-movement-view 6.3), in the order they are chosen, after `cardNumberFormat`.
V5_PORTFOLIO_SETTINGS = ("cardImage", "cardAlt", "cardKicker", "pieceLink", "pieceTeaser")
SETTING_ORDER = ("look", "featuredFrom", "sort", "nav.home", "nav.labels.about", "nav.labels.resume", "resume.headings", "resume.layout",
                 "resume.titleForm", "workKeys", "cardLabels", "cardNumber", "cardNumberFormat",
                 "cardImage", "cardAlt", "cardKicker", "pieceLink", "pieceTeaser",       # a literal: test_routing reads it by `ast`
                 "backLink", "menuLinks", "onePieceIndex", "blocks.headingLevel", "blocks.loneReferenceGrid", "blocks.videoEmbed",
                 "blocks.unlistedVideos",        # dev 1060
                 "referenceLayout",              # dev 1061, S7b: measured by `referencepropose`, written by `convert` over the finished tree
                 "titleForm", "introScope",
                 "partOrder", "view")
# The schema-6 settings (design-adopt-parity-2 section 7.6), chosen among the others by `candidates.setting_names`: `featuredView`
# (`flat` or `grouped`), `nav.extra` (the menu's `https:` and `mailto:` items after the built-in ones), `titleSeparator` (the text
# between a page's title and the site title), `blocks.headings` (`shift` or `as-written`: the h-level of a heading in every
# Markdown body but the resume's), `mediaPaths.<folder>` (where `references`, `home` or `about` media is published: a pattern,
# section 4.6), `sizeCopies` (`any-format`: a size copy may carry another raster extension), `carried` (the old build's own pages
# served byte for byte, section 4.7: `adoption.carry` offers them and writes them from the bytes the measurement put in `hints`;
# step 10b), and per portfolio `groupCount`
# (true, or {"counts": <the `labels.counts` words read from the old headings>}: each group heading prints its count; step 8b folds
# step 8's separate `countWords` into it, the design's one row of cap 2) and `pieceRoles` (true: a piece's `role` is a list of
# dated roles). `nav.home` gains `"title"`, `cardAlt` gains `"title"`, `view` gains `roles`, `map`, `steps` and `showcase` by the
# pieces' keys, and `backLink` is measured per portfolio. A separate literal from SETTING_ORDER: the adopt skill names both, and
# test_routing's skill-names gate reads both by `ast` (step 14a).
V6_SETTING_ORDER = ("featuredView", "nav.extra", "titleSeparator", "groupCount", "pieceRoles", "blocks.headings", "mediaPaths",
                    "sizeCopies", "carried")
V6_PORTFOLIO_SETTINGS = ("groupCount", "pieceRoles")
_KEYED = ("mediaPaths",)                  # a setting per folder, `mediaPaths.<folder>`: not a portfolio's
HOME_KEYS = ("titleForm", "introScope", "partOrder")       # the settings written into the home page's own front matter
PORTFOLIO_KEYS = ("cardNumber", "cardNumberFormat", "cardLabels", "backLink")     # the portfolio keys written into every page.md
SHARED_WORK_KEYS = ("meta", "cardMeta")                                          # the `work` keys `workKeys: all` copies
BACK_LINK_MAX = 60
_PER_PORTFOLIO = ("sort", "view", "menuLinks", "onePieceIndex") + V5_PORTFOLIO_SETTINGS + V6_PORTFOLIO_SETTINGS + ("backLink",)
_CARD_PAGES = ("cardImage", "cardAlt", "cardKicker")       # a card or a tile: the portfolio's index and the home page
_FM = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):")
PERSON_ROWS = ("look.", "reads.")       # plan schema 4's measured rows of the person's look entries: evidence, never a setting to write


def setting_family(name):
    """`sort.work` is of the family `sort`, `mediaPaths.home` of `mediaPaths`; `look` of `look`, `backLink` of `backLink`."""
    return name.split(".", 1)[0] if name.split(".", 1)[0] in _PER_PORTFOLIO + _KEYED else name


def setting_paths(name):
    """The output paths the setting can change: exact paths, prefixes ending in `/`, or `*` for every page. Never empty."""
    fam = setting_family(name)
    if fam in ("look", "nav.home", "nav.extra", "titleSeparator", "blocks.headings", "mediaPaths", "sizeCopies"):
        return ["*"]
    if fam in ("featuredFrom", "featuredView"):
        return ["index.html"]
    if fam in ("resume.headings", "resume.layout", "resume.titleForm"):
        return ["resume/index.html"]
    port = name.split(".", 1)[1] if "." in name and fam in _PER_PORTFOLIO else None
    if fam == "menuLinks":      # the menu is on every page, and the portfolio's index becomes a redirect page
        return ["*"]
    if fam == "onePieceIndex" and port:
        return ["%s/index.html" % port]            # the one page it changes: the index, a redirect or the listing
    if fam in HOME_KEYS:
        return ["index.html"]
    if fam == "view" and port:
        return ["%s/index.html" % port]            # the portfolio's own index: the home page is no view's to change
    if fam == "sort" and port:
        return ["%s/index.html" % port, "index.html"]
    if fam in _CARD_PAGES + ("groupCount",) and port:
        return ["%s/index.html" % port, "index.html"]
    if fam in ("pieceLink", "pieceTeaser", "pieceRoles", "backLink") and port:
        return ["%s/" % port]                      # the portfolio's pages: its piece pages are the ones that change
    if fam in ("cardLabels", "cardNumber", "cardNumberFormat", "backLink", "workKeys", "blocks.headingLevel",
               "blocks.loneReferenceGrid"):
        return ["*"]                          # cards on the home and the indexes; the back link on every piece page; a block on any page
    return ["*"]


def _set_front_key(text, key, value):
    """The page's text with front-matter key `key` set to `value` (a one-line scalar), replacing an existing line or
    adding one after the others. A page with no front matter gets one."""
    front, body, had = split_front(text)
    ents = entries(front)
    line = "%s: %s" % (key, value)
    done = False
    for e in ents:
        if e[0] == key:
            e[1] = [line]
            done = True
    if not done:
        ents.append([key, [line]])
    lines = ["---"] + [l for _k, raw in ents for l in raw] + ["---"] + (body if had else text.replace("\r\n", "\n").split("\n"))
    return "\n".join(lines)


def _front_value(value):
    """One setting value as a front-matter scalar: `true`, a number, or text quoted only when it must be."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    return _yaml(str(value))


def _page_text(view, files, path):
    """The page's text as the tree being written holds it: an earlier setting's change is kept, never written over."""
    return files[path].decode("utf-8") if path in files else view.text(path)


def set_in_portfolios(view, files, key, value, only=None, missing_only=False):
    """Write front-matter `key` into every portfolio's `content/<p>/page.md` (a page.md configures its own portfolio; the
    site.json `work` object configures only the one named `work`). `only` restricts the portfolios, `missing_only` leaves a page.md
    that already has the key. Returns the portfolios written."""
    done = []
    for p in sorted(view.paths()):
        parts = p.split("/")
        if len(parts) != 3 or parts[0] != "content" or parts[2] != "page.md" or parts[1].startswith("_"):
            continue
        if only is not None and parts[1] not in only:
            continue
        cur = _page_text(view, files, p)
        front, _body, _had = split_front(cur)
        if missing_only and any(e[0] == key for e in entries(front)):
            continue
        files[p] = _set_front_key(cur, key, value).encode("utf-8")
        done.append(parts[1])
    return done


_SHOWN_BY = ("view",) + V5_PORTFOLIO_SETTINGS + V6_PORTFOLIO_SETTINGS     # the settings whose triggers make the build show a piece key


def keys_the_build_shows(view, files, settings, port):
    """The `meta`/`cardMeta` keys the build refuses for portfolio `port` because it shows them itself: the keys
    `contentmodel.keytables.piece_keys_read` reports for the settings the portfolio ends with (its page.md as written so far, then
    the person's `<setting>.<port>` rows, which are laid after `workKeys`), less the `cardKicker` key and the built-in keys, exactly
    as `contentmodel.pagefiles._check_v5_piece_keys` excludes them (dev #983: `role` under `view: steps` or `pieceRoles: true`)."""
    cfg = {}
    try:
        front, _body, _had = split_front(_page_text(view, files, "content/%s/page.md" % port))
    except KeyError:
        front = []
    for e in entries(front):
        if e[0] in _SHOWN_BY:
            v = scalar(e)
            cfg[e[0]] = _BOOL.get(v, v) if v is not None else True      # a map (a typed groupCount) is a value that is on
    for fam in _SHOWN_BY:
        name = "%s.%s" % (fam, port)
        if name in settings:
            if settings[name] in (None, False, ""):
                cfg.pop(fam, None)
            else:
                cfg[fam] = settings[name]
    read = piece_keys_read(cfg)
    kicker = cfg.get("cardKicker")
    return set(k for k in read if k != kicker and k not in BUILTIN_PIECE_KEYS)


def page_view(text):
    """The `view` a portfolio's page.md names, or None."""
    front, _body, _had = split_front(text)
    for e in entries(front):
        if e[0] == "view":
            return scalar(e)
    return None


def showcase_pieces(view, settings):
    """{`portfolio/slug`}: the pieces whose tile keys the build reads, so a template `tilePhoto` there is the plugin's
    `tileImage` rather than `cover` (design 8 V1): every piece of a portfolio whose view is `showcase` (as written, or as
    the person's `view.<portfolio>` setting says). A piece the HOME page's `showcase` names in another portfolio is not here:
    its card keeps `cover` (the template's card picture) and its tile falls back to it."""
    out = set()
    for p in view.paths():
        parts = p.split("/")
        if len(parts) == 3 and parts[0] == "content" and parts[2] == "page.md":
            v = settings.get("view." + parts[1])
            if v is None:
                try:
                    v = page_view(view.text(p))
                except KeyError:
                    v = None
            if v == "showcase":
                out.update("%s/%s" % (parts[1], q.split("/")[2]) for q in view.paths()
                           if q.startswith("content/%s/" % parts[1]) and q.count("/") == 3 and q.split("/")[3] in ("work.md", "index.md"))
    return out


_NOT_PORTFOLIOS = ("home", "about", "resume", "references", "media")


def featured_shelf(read, paths, settings):
    """(home path, [`portfolio/slug`]): the home `showcase` list `featuredFrom: showcase` writes (step 5c-4), or (path, []) when it is
    not offered. The pieces the home features: its own `featured` list (the names of pieces, `portfolio/slug`), else every piece whose
    front matter says `featured: true`, in the order the plugin prints flagged pieces (portfolios by folder name; in each, newest
    `date` or `year` first, then by folder name, or by `order` under that portfolio's `sort: order`). Never offered when the home
    already names a `showcase`. `read(path)` is a page's text in the converted tree, `paths` its paths, `settings` the values judged."""
    paths = set(paths)
    hp = next((p for p in HOME_PATHS if p in paths), None)
    if hp is None:
        return None, []
    vals = front_values(split_front(read(hp))[0])
    if vals.get("showcase"):
        return hp, []
    listed = vals.get("featured")
    listed = [x.strip() for x in listed.split(",")] if isinstance(listed, str) else listed if isinstance(listed, list) else []
    if [n for n in listed if n]:
        return hp, [n for n in listed if "/" in n] if all("/" in n for n in listed if n) else []
    flagged = {}
    for p in sorted(paths):
        parts = p.split("/")
        if (len(parts) == 4 and parts[0] == "content" and parts[3] == "index.md" and not parts[1].startswith("_")
                and not parts[2].startswith("_") and parts[1] not in _NOT_PORTFOLIOS):
            fm = front_values(split_front(read(p))[0])
            if str(fm.get("featured", "")).lower() in ("true", "yes"):
                flagged.setdefault(parts[1], []).append((parts[2], fm))
    out = []
    for port in sorted(flagged):
        ps = sorted(sorted(flagged[port]), key=lambda x: str(x[1].get("date") or x[1].get("year") or ""), reverse=True)
        page = "content/%s/page.md" % port
        sort = settings.get("sort." + port) or (front_values(split_front(read(page))[0]).get("sort") if page in paths else None)
        if sort == "order":
            ps = sorted(ps, key=lambda x: (0, int(x[1]["order"])) if re.match(r"^-?\d+$", str(x[1].get("order", ""))) else (1, 0))
        out += ["%s/%s" % (port, slug) for slug, _fm in ps]
    return hp, out


def _write_shelf(view, files, settings, notes):
    """`featuredFrom: showcase`: the pieces the home features become its `showcase` list, in place of its `featured` list (the flags
    stay in the pieces, read by nothing). The plugin prints a `showcase` piece as a tile, a `featured` one as a card."""
    hp, names = featured_shelf(lambda p: _page_text(view, files, p), view.paths(), settings)
    if not names:
        return
    front, body, _had = split_front(_page_text(view, files, hp))
    ents, done = entries(front), False
    for i, ent in enumerate(ents):
        if ent[0] == "featured":
            ents[i], done = _list_entry("showcase", names), True
    ents = ents if done else ents + [_list_entry("showcase", names)]
    files[hp] = _emit(ents, body).encode("utf-8")
    notes["settings"].append("featuredFrom: showcase (the featured pieces as the home page's showcase tiles: %s)" % ", ".join(names))


def apply_settings(view, files, d, settings, hints, notes, portfolios):
    """Lay the settings over the converted tree: `d` (site.json's dict) and `files` ({path: bytes}) are changed in place;
    `notes["settings"]` gains one line per setting applied."""
    order = SETTING_ORDER + V6_SETTING_ORDER
    lookwrite.carry(view, files, d, settings.get("look"), notes)     # both look files, as adopt's own (step 8)
    for name in sorted(settings, key=lambda n: (order.index(setting_family(n)) if setting_family(n) in order else 99, n)):
        value, fam = settings[name], setting_family(name)
        if name.startswith(PERSON_ROWS):
            continue
        if name == "carried":                  # section 7.4's `carried` row: the bytes from `hints`, checked against their sha256
            if value and carry.HINT in (hints or {}):
                carry.write(files, d, value, hints, notes)       # refuses a path the measured bytes do not cover
            elif value:
                # a command that holds no measurement of the old build (`check`: every 0.6.0 measurement stores the member, empty
                # or not, `adoption.measure`) cannot write the page, and says so rather than refuse the tree for it
                notes["settings"].append("carried: %s (not written by this command, which holds no measurement of your old site; "
                                         "`adopt.py parity` measures the pages and `apply` writes them)" % ", ".join(value))
            continue
        if fam in V6_SETTING_ORDER:
            _apply_v6(view, files, d, settings, name, value, notes)
            continue
        if fam == "look":               # laid by `lookwrite.carry` below; `look.<construct>` and `reads.<target>` rows write nothing
            continue
        if fam == "featuredFrom":
            if value == "showcase":
                _write_shelf(view, files, settings, notes)
            elif value != "home":
                d["featuredFrom"] = value
                notes["settings"].append("featuredFrom: %s" % value)
        elif name == "nav.home":
            if value is False:
                d["nav"] = dict(d.get("nav") or {}, home=False)
                notes["settings"].append("nav.home: false (no Home item in the nav)")
            elif value == NAV_HOME_TITLE:
                d["nav"] = dict(d.get("nav") or {}, home=NAV_HOME_TITLE)
                notes["settings"].append("nav.home: title (the menu's first item is the site title)")
        elif name == "resume.headings":
            if value != "shift" and isinstance(d.get("resume"), dict):
                d["resume"]["headings"] = value
                notes["settings"].append("resume.headings: %s" % value)
        elif name == "resume.layout":
            if value != "plain" and isinstance(d.get("resume"), dict):
                d["resume"]["layout"] = value
                notes["settings"].append("resume.layout: %s" % value)
        elif menulabels.is_label(name):          # schema 8: written into `nav.labels`, which raises the site to schema 8
            page = name[len(menulabels.LABEL_PREFIX):]
            if value not in (None, "", menulabels.DEFAULT_WORDS[page]):          # the plugin's own word writes no key
                nav = dict(d.get("nav") or {})
                nav["labels"] = dict(nav.get("labels") or {}, **{page: value})
                d["nav"] = nav
                notes["settings"].append("%s: %s (the menu's word for the %s page)" % (name, json.dumps(value, ensure_ascii=False), page))
        elif name == menulabels.TITLE_FORM:
            if value != "title" and isinstance(d.get("resume"), dict):
                d["resume"]["titleForm"] = value
                notes["settings"].append("resume.titleForm: %s (the resume page's title tag leads with the menu's word for it)" % value)
        elif name == "workKeys":
            if value == "all":
                work = d.get("work") or {}
                for p in (p for p in portfolios if p != "work"):
                    shown = keys_the_build_shows(view, files, settings, p)       # the build refuses a meta that lists one of these
                    for key in SHARED_WORK_KEYS:
                        keys = [k for k in (work.get(key) or ()) if k not in shown]
                        if keys:
                            set_in_portfolios(view, files, key, "[%s]" % ", ".join(keys), only=[p], missing_only=True)
                        left = [k for k in (work.get(key) or ()) if k in shown]
                        if left:
                            notes["settings"].append("workKeys: all leaves %s out of %s's %s (the build prints it there itself)"
                                                     % (", ".join(left), p, key))
                notes["settings"].append("workKeys: all (the work portfolio's %s apply to every portfolio)" % " and ".join(SHARED_WORK_KEYS))
        elif name == "blocks.headingLevel":
            if isinstance(value, int) and not isinstance(value, bool):
                d["blocks"] = dict(d.get("blocks") or {}, headingLevel=value)
                notes["settings"].append("blocks.headingLevel: %d (a heading inside a carousel slide)" % value)
        elif name == "blocks.loneReferenceGrid":
            if value is True:
                d["blocks"] = dict(d.get("blocks") or {}, loneReferenceGrid=True)
                notes["settings"].append("blocks.loneReferenceGrid: true (a lone reference prints inside the reference grid)")
        elif name == "blocks.videoEmbed":
            if value == "live":
                d["blocks"] = dict(d.get("blocks") or {}, videoEmbed="live")
                notes["settings"].append("blocks.videoEmbed: live (a video keeps the player's own address, nothing added)")
        elif name == "blocks.unlistedVideos":                 # schema 9 (dev 1060): the link's private code is sent to the player, and is on the page
            if value is True:
                d["blocks"] = dict(d.get("blocks") or {}, unlistedVideos=True)
                notes["settings"].append("blocks.unlistedVideos: true (the private code of an unlisted Vimeo link is sent to the player; "
                                         "it is then in the page, where a visitor can read it)")
        elif name == "referenceLayout":
            continue                                        # dev 1061: written by `convert` over the finished tree (`referencepropose.run`)
        elif fam in HOME_KEYS:
            hp = home_path(view)                       # the converted home: a renamed one is read where the rename put it
            default = {"titleForm": "site", "introScope": "body", "partOrder": None}[fam]
            if hp and value not in (None, "", [], default):
                text = "[%s]" % ", ".join(value) if fam == "partOrder" else _front_value(value)
                files[hp] = _set_front_key(_page_text(view, files, hp), fam, text).encode("utf-8")
                notes["settings"].append("%s: %s" % (fam, ", ".join(value) if fam == "partOrder" else value))
        elif fam == "backLink" and "." in name:
            _write_back_link(view, files, d, name.split(".", 1)[1], value, notes)
        elif fam in PORTFOLIO_KEYS:
            default ={"cardLabels": True, "cardNumber": False, "cardNumberFormat": "padded", "backLink": None}[fam]
            if value not in (None, "", default):
                work = dict(d.get("work") or {})
                work[fam] = value
                d["work"] = work                                  # the portfolio named `work`, when it has no page.md of its own
                set_in_portfolios(view, files, fam, _front_value(value))
                notes["settings"].append({"cardNumber": "cardNumber: true (a number on each card)",
                                          "cardNumberFormat": "cardNumberFormat: %s" % json.dumps(value),
                                          "cardLabels": "cardLabels: false", "backLink": "backLink: %s" % json.dumps(value)}[fam])
        elif fam in _PER_PORTFOLIO and "." in name:
            if ((fam == "menuLinks" and value == "index") or (fam == "onePieceIndex" and value == "redirect")
                    or (fam in V5_PORTFOLIO_SETTINGS and value in (None, False, ""))):
                continue                     # the default writes no key
            port = name.split(".", 1)[1]
            path = "content/%s/page.md" % port
            if not view.exists(path):
                _write_work_json(view, files, d, port, fam, value, notes)      # dev #1007: a `work` with no page.md
                continue
            cur = _page_text(view, files, path)
            files[path] = _set_front_key(cur, fam, _front_value(value) if fam in V5_PORTFOLIO_SETTINGS else value).encode("utf-8")
            notes["settings"].append("%s of %s: %s" % (fam, port, _front_value(value) if fam in V5_PORTFOLIO_SETTINGS else value))


def separator_ok(sep):
    """True for a `titleSeparator` site.json accepts (design-adopt-parity-2 section 3.2): one to three punctuation marks or
    symbols (Unicode categories P* and S*) with at most one space on each side."""
    core = sep.strip(" ")
    if not core or len(core) > TITLE_SEPARATOR_MAX or sep.startswith("  ") or sep.endswith("  ") or " " in core:
        return False
    return all(unicodedata.category(ch)[0] in "PS" for ch in core)


def _write_back_link(view, files, d, port, value, notes):
    """`backLink.<p>` (schema 6's adopt, section 7.6): the text into that portfolio's page.md, or into site.json's `work` for the
    portfolio named `work` when it has no page.md of its own; the default (absent) writes nothing."""
    if value in (None, ""):
        return
    path = "content/%s/page.md" % port
    if view.exists(path):
        files[path] = _set_front_key(_page_text(view, files, path), "backLink", _front_value(value)).encode("utf-8")
    elif port == "work":
        d["work"] = dict(d.get("work") or {}, backLink=value)
    else:
        return
    notes["settings"].append("backLink of %s: %s" % (port, json.dumps(value, ensure_ascii=False)))


def media_pattern_ok(folder, pattern):
    """True for a `mediaPaths.<folder>` pattern site.json accepts (section 4.6; `configschema.sectioncheck._media_pattern`, the
    check the build runs, asked here so the two can never disagree)."""
    if folder not in MEDIA_PATH_FOLDERS or not isinstance(pattern, str):
        return False
    try:
        sectioncheck._media_pattern(pattern, "mediaPaths.%s" % folder, folder)
    except SiteConfigError:
        return False
    return True


def work_count_words(view, files, d, counts):
    """(the `labels.counts` value site.json's `work` can hold for the portfolio named `work`, None), or (None, why not). The
    schema-6 validator reads site.json's `work` on its own (`configschema.workcheck`: a group named in `labels.counts` must be one
    of `work.groups`, or "*"), and a page.md's front matter cannot hold `labels.counts` at all (it reads two levels; the words are
    four). So: groups in site.json's `work` keep one entry per group, as the old headings show; groups in `content/work/page.md`
    take the one entry "*" when every group there has the same words, and otherwise the words are not written. Found at step 9a2
    on template-portfolio-a, whose groups are in its page.md and whose two groups have two words: step 8's writer put the group
    entries into site.json, and the validator refused the whole converted tree."""
    if (d.get("work") or {}).get("groups"):
        return counts, None
    path = "content/work/page.md"
    front = front_values(split_front(_page_text(view, files, path))[0]) if (path in files or view.exists(path)) else {}
    if "labels" in front:
        return None, "the portfolio's page.md holds its own labels, which replace site.json's"
    groups, forms = front.get("groups") or [], [counts[g] for g in sorted(counts)]
    if groups and sorted(counts) == sorted(groups) and all(f == forms[0] for f in forms):
        return {COUNT_ANY: forms[0]}, None
    return None, ("its groups are in content/work/page.md, which cannot hold labels.counts, and site.json's work may name a "
                  "group only when it lists the groups itself; each group's words differ, so no one entry \"*\" holds them")


def _apply_v6(view, files, d, settings, name, value, notes):
    """Write one schema-6 setting (`V6_SETTING_ORDER`); the default writes nothing. `groupCount.<p>` writes `groupCount: true`
    into the portfolio's page.md, and the words of a {"counts": ...} value into site.json's `work` for the portfolio named `work`
    only, in the form the validator accepts there (`work_count_words`): a page.md's front matter reads two levels and refuses a
    third (`contentmodel.frontmatter`), and `labels.counts.<group>.<form>` is four, so another portfolio's count prints the number
    alone (a finding of step 8, stated in the note)."""
    fam = setting_family(name)
    port = name.split(".", 1)[1] if fam in V6_PORTFOLIO_SETTINGS else None
    if value in (None, False, "", [], {}):
        return
    if name == "blocks.headings":
        if value != "shift":
            d["blocks"] = dict(d.get("blocks") or {}, headings=value)
            notes["settings"].append("blocks.headings: %s (a heading in a page's body keeps the level it is written at)" % value)
        return
    if fam == "mediaPaths":
        folder = name.split(".", 1)[1]
        d["mediaPaths"] = dict(d.get("mediaPaths") or {}, **{folder: value})
        notes["settings"].append("mediaPaths.%s: %s (the %s media at the old addresses)" % (folder, value, folder))
        return
    if name == "sizeCopies":
        d["sizeCopies"] = value
        notes["settings"].append("sizeCopies: %s (a size copy in another format joins its picture)" % value)
        return
    if fam == "groupCount" and isinstance(value, dict):
        _apply_v6(view, files, d, settings, name, True, notes)
        counts, why = ((None, "a page.md cannot hold labels.counts") if port != "work"
                       else work_count_words(view, files, d, value["counts"]))
        if counts is None:
            notes["settings"].append("groupCount of %s: the words are not written (%s; the count prints alone)" % (port, why))
            return
        work = dict(d.get("work") or {})
        work["labels"] = dict(work.get("labels") or {}, counts=counts)
        d["work"] = work
        notes["settings"].append("groupCount of work: the words %s" % json.dumps(counts, ensure_ascii=False))
        return
    if name == "featuredView":
        if value != "flat":
            d["featuredView"] = value
            notes["settings"].append("featuredView: %s (the featured pieces in their portfolio's groups)" % value)
    elif name == "nav.extra":
        d["nav"] = dict(d.get("nav") or {}, extra=[{"label": x["label"], "url": x["url"]} for x in value])
        notes["settings"].append("nav.extra: %s" % ", ".join("%s (%s)" % (x["label"], x["url"]) for x in value))
    elif name == "titleSeparator":
        if value != TITLE_SEPARATOR_DEFAULT:
            d["titleSeparator"] = value
            notes["settings"].append("titleSeparator: %s" % json.dumps(value, ensure_ascii=False))
    else:                                                  # groupCount, pieceRoles: `true` in the portfolio's page.md
        path = "content/%s/page.md" % port
        if view.exists(path):
            files[path] = _set_front_key(_page_text(view, files, path), fam, "true").encode("utf-8")
            notes["settings"].append("%s of %s: true" % (fam, port))
        else:
            _write_work_json(view, files, d, port, fam, True, notes)          # dev #1007: a `work` with no page.md


def _write_work_json(view, files, d, port, fam, value, notes):
    """dev #1007 (0.7.0): the portfolio named `work` with no `content/work/page.md` is configured by site.json's `work` object
    (`contentmodel/layout.py` exempts it), so a per-portfolio setting is written THERE when site.json's `work` holds that key
    (`WORK_KEYS`). dev #1041 (0.8.0): a key only a page.md holds (`sort`, `view`, `menuLinks`, `onePieceIndex`) is written into a
    `content/work/page.md` that holds only that key (the content model merges a page.md over site.json's `work` key by key, and
    the template's own builder ignores the file), listed in the commit with the other written files; a later setting of the same
    portfolio joins that file. A portfolio other than `work` has no site.json object to fall back on: the note says it is not
    written (`unwritten_reason` is the same fact for the parity row)."""
    path = "content/work/page.md"
    if port != "work":
        notes["settings"].append("%s of %s: not written (%s)" % (fam, port, unwritten_reason({}, "%s.%s" % (fam, port), value)))
    elif path in files:                         # an earlier setting of this run created it: this one joins it
        files[path] = _set_front_key(_page_text(view, files, path), fam, _front_value(value)).encode("utf-8")
        notes["settings"].append("%s of work: %s (in the page.md written for the portfolio)" % (fam, _front_value(value)))
    elif view.exists(path):
        return
    elif fam in WORK_KEYS:
        d["work"] = dict(d.get("work") or {}, **{fam: value})
        notes["settings"].append("%s of work: %s (in site.json's work: the portfolio has no page.md)" % (fam, json.dumps(value)))
    else:
        files[path] = _set_front_key("", fam, _front_value(value)).encode("utf-8")
        notes["settings"].append("%s of work: %s (written into a new content/work/page.md that holds only this key: only a page.md "
                                 "holds %s, and the portfolio had none)" % (fam, _front_value(value), fam))


def unwritten_reason(paths, name, value):
    """None when the per-portfolio candidate `name` = `value` can be written into the converted tree whose paths `paths` holds, else
    why not, with the way out (dev #1041): a portfolio other than `work` with no `content/<p>/page.md` has no place for the key
    (`work` always has one: site.json's `work` object or a page.md `_write_work_json` creates). The parity row says this, never
    "no candidate changes what a visitor sees", which reads as measured."""
    fam = setting_family(name)
    if fam not in _PER_PORTFOLIO or "." not in name:
        return None
    port = name.split(".", 1)[1]
    if port == "work" or "content/%s/page.md" % port in paths:
        return None
    return "needs content/%s/page.md with %s: %s" % (port, fam, _front_value(value) if isinstance(value, (str, bool, int)) else "...")


_BOOL = {"true": True, "false": False}
_CHOICES = {"featuredFrom": ("home", "flags", "showcase"), "sort": ("date", "order"), "resume.headings": ("shift", "as-written"),
            "resume.layout": ("plain", "cards"),
            "view": ("grid", "page", "roles", "map", "showcase"), "look": ("site-studio",), "menuLinks": ("index", "single-piece"),
            "workKeys": ("work", "all"), "cardNumberFormat": ("padded", "plain", "order"), "onePieceIndex": ("redirect", "listing"),
            "titleForm": ("site", "page"), "introScope": ("body", "first-block"), "blocks.videoEmbed": ("facade", "live"),
            "cardImage": ("cover", "photo"), "resume.titleForm": menulabels.TITLE_FORMS}
_V5_TRUE = ("cardAlt", "pieceLink", "pieceTeaser")          # true, or false for absent (no key)
_BOOLEAN = ("nav.home", "cardLabels", "cardNumber", "blocks.loneReferenceGrid")


def parse_chosen(name, text):
    """The value for `adopt.py setting NAME TEXT`, or Refused naming what the setting takes. `look` takes only the default
    (a derived look is measured, never chosen: it is a file adopt writes); `backLink` takes one line of text."""
    fam = setting_family(name)
    portfolio_form = "." in name and name.split(".", 1)[0] in _PER_PORTFOLIO
    if (fam not in SETTING_ORDER + V6_SETTING_ORDER or ((fam in _PER_PORTFOLIO) != portfolio_form and fam != "backLink")
            or (fam == "mediaPaths" and name.split(".", 1)[-1] not in MEDIA_PATH_FOLDERS)):
        raise Refused("%s is not a setting adopt measures; the settings are %s (sort and view take a portfolio: `sort.work`; "
                      "mediaPaths a folder: `mediaPaths.home`); pass one of those names" % (name, ", ".join(SETTING_ORDER + V6_SETTING_ORDER)))
    if text == NAV_HOME_TITLE and (name == "nav.home" or fam == "cardAlt"):
        return NAV_HOME_TITLE                                # schema 6: the site title (nav.home), the piece's title (cardAlt)
    if fam in ("groupCount", "pieceRoles"):
        if text not in _BOOL:
            raise Refused("%s takes true or false; pass one of those" % name)
        return True if _BOOL[text] else None                 # a typed groupCount prints the number alone: the words are measured
    if name in ("featuredView", "blocks.headings", "sizeCopies"):
        allowed = {"featuredView": ("flat", "grouped"), "blocks.headings": ("shift", "as-written"),
                   "sizeCopies": SIZE_COPIES + ("false",)}[name]
        if text not in allowed:
            raise Refused("%s takes one of: %s" % (name, ", ".join(allowed)))
        return None if text == "false" else text
    if fam == "mediaPaths":
        if not media_pattern_ok(name.split(".", 1)[1], text):
            raise Refused("%s takes a pattern of two to four segments, the last {file}; use one such as `refs/{name}/{file}` "
                          "(references) or `media/{file}` (home, about)" % name)
        return text
    if name == "titleSeparator":
        if not separator_ok(text or ""):
            raise Refused("titleSeparator takes one to three punctuation marks or symbols, with at most one space on each side; "
                          "use one such as ` · `")
        return text
    if fam == "nav.extra":
        raise Refused("%s is read from your old pages and measured, never typed; run `adopt.py parity` to measure it" % name)
    if menulabels.is_label(name):                  # schema 8: the menu's word for the page, one line (`false` is the plugin's own word)
        if text == "false":
            return None
        if not menulabels.label_ok(text):
            raise Refused("%s takes one non-empty line of text, the word your menu prints, or false for the plugin's own; "
                          "pass one such as `CV`" % name)
        return text
    if name == "carried":
        return carried_value(text)
    if name in _BOOLEAN or fam in _V5_TRUE or name == "blocks.unlistedVideos":
        if text not in _BOOL:
            raise Refused("%s takes true or false; pass one of those" % name)
        return _BOOL[text] if name in _BOOLEAN else (True if _BOOL[text] else None)      # false is the absent key
    if fam == "cardKicker":
        if not KEY_RE.match(text or "") or text in BUILTIN_PIECE_KEYS:
            raise Refused("%s takes the name of a piece key that is not built in (%s); pass a key your pieces carry"
                          % (name, ", ".join(BUILTIN_PIECE_KEYS)))
        return text
    if fam == "backLink":
        if not text or "\n" in text or len(text) > BACK_LINK_MAX:
            raise Refused("backLink takes one line of text, at most %d characters; shorten it to one line" % BACK_LINK_MAX)
        return text
    if name == "blocks.headingLevel":
        if text not in ("2", "3", "4", "5", "6"):
            raise Refused("blocks.headingLevel takes a whole number from 2 to 6; pass one of 2, 3, 4, 5 or 6")
        return int(text)
    if name == "partOrder":
        parts = [t.strip() for t in text.split(",") if t.strip()]
        if not parts or any(not re.match(r"^[a-z0-9][a-z0-9-]*$", t) for t in parts) or len(set(parts)) != len(parts):
            raise Refused("partOrder takes the home page's parts once each, lower-case and comma-separated: `intro,showcase,feed`")
        return parts
    if name == "referenceLayout":                  # dev 1061: `all`, `none` (an empty list: the person said no) or keys with commas
        given = [t.strip() for t in (text or "").split(",") if t.strip()]
        if text not in ("all", "none") and (not given or len(set(given)) != len(given) or any(g not in V9_REFERENCE_KEYS for g in given)):
            raise Refused("referenceLayout takes all, none, or keys of %s with commas between them; pass one such as `project,channel`"
                          % ", ".join(V9_REFERENCE_KEYS))
        return list(V9_REFERENCE_KEYS) if text == "all" else [] if text == "none" else [k for k in V9_REFERENCE_KEYS if k in given]
    if text not in _CHOICES[fam]:
        raise Refused("%s takes one of: %s" % (name, ", ".join(_CHOICES[fam])))
    return text


def carried_value(text):
    """`adopt.py setting carried 404.html[,other.html]`: the output paths, each once, each one the `carried` key accepts
    (`sectioncheck._carried_path`, the check the build runs); `false` is the absent key. The bytes are the measurement's: the
    next `adopt.py parity` stores them for every chosen path the old build serves (`adoption.measure`)."""
    if text == "false":
        return None
    paths = [t.strip() for t in (text or "").split(",") if t.strip()]
    if not paths or len(set(paths)) != len(paths):
        raise Refused("carried takes the old site's own pages: give them comma-separated and each once, such as `404.html`, "
                      "or false")
    for p in paths:
        try:
            sectioncheck._carried_path(p, "carried")
        except SiteConfigError as e:
            raise Refused("carried cannot name %s: %s; leave it out of the list" % (p, str(e).split("never carried: ", 1)[-1]))
    return sorted(paths)


def cmd_setting(repo, name, text, clear=False):
    """`adopt.py setting NAME VALUE` (or `--clear`): the person's choice for one measured setting, recorded in the plan as
    `how: chosen`, which `parity` keeps and never measures over (design 3.5, 8). `--clear` forgets the choice, so the next
    `parity` measures it again."""
    plan = _plan_for(repo, _current_base(repo), print)
    if clear:
        if name not in plan["settings"] or plan["settings"][name]["how"] != "chosen":
            raise Refused("%s has no chosen value to clear; it is measured already, so leave it, or choose a value with "
                          "`adopt.py setting %s <value>`" % (name, name))
        del plan["settings"][name]
        save_plan(repo, plan)
        return "\n".join(["adopt: %s is measured again at the next `adopt.py parity`" % name] + [l for l in (stale_line(plan),) if l])
    value = parse_chosen(name, text)
    plan["settings"][name] = {"value": value, "how": "chosen", "reason": "chosen with `adopt.py setting`"}
    save_plan(repo, plan)
    return "\n".join(["adopt: %s = %s (chosen: `adopt.py parity` keeps it and does not measure it)" % (name, json.dumps(value))]
                     + [l for l in (stale_line(plan),) if l])
