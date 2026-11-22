"""adoption.candidates -- what each measured setting is OFFERED: its candidates, default first, and the order the settings are chosen
in (design 8, "Measured settings"; design-movement-view 6.3; step 1.9).

Part of the `adoption` package behind the entry point `adopt.py`; moved out of `adoption.choose` unedited by split_module.py
(design-adopt-parity-2 step 1). `adoption.choose` decides; this module reads the converted tree (and, for `backLink`,
`blocks.headingLevel` and `partOrder`, the old builder's own output) and says what may be tried:

  * `candidates_for(name, snap, data, local=None, settings=None)`: the values to try, DEFAULT FIRST; one value means there is nothing
    to choose. The five card and piece settings of a portfolio are offered only when their "offered when" holds (`v5_candidates`).
  * `setting_names(snap)`: the settings a tree has, in the order the greedy loop chooses them.
  * `partner` and `look_partner`: the setting whose best value a candidate is scored under (A DEPENDENT VALUE in `adoption.choose`).
  * `DEFAULTS` and `BUILT_IN_VIEWS`: each setting's default and the views the plugin builds.
  * Schema 6 (design-adopt-parity-2 section 7.6, step 8), each offered only where adopt measures it: `view.<p>` gains `roles`,
    `map`, `steps` and `showcase` by the pieces' keys (`view_candidates`, at most `VIEW_CAP`); `nav.home` gains `"title"`;
    `cardAlt.<p>` gains `"title"` where an old card picture is named by its piece's title (`titled_cards`, owner decision 5);
    `featuredView`, `titleSeparator`, `nav.extra`, and per portfolio `groupCount` (its `true` carries the `labels.counts` words read
    from the old group headings, `{"counts": ...}`) and `pieceRoles` (`v6_candidates`). Step 8b adds the rest of section 7.6 but
    `carried` (step 10's): `blocks.headings` where a body holds a heading, `mediaPaths.<folder>` (the one pattern every file of that
    folder fits, read by matching bytes to the old build's paths: `media_pattern`), `sizeCopies` where a size copy has another
    extension than its picture, and `backLink.<p>` (the one text THAT portfolio's old piece pages share, replacing the site-wide
    setting in `setting_names`). Step 10b adds `carried`: absent, or the pages `adoption.carry.offer_for` offers (with no old
    build, nothing), named last.
"""

import html as html_mod
import posixpath
import re

from configschema.configkeys import (BUILTIN_PIECE_KEYS, MEDIA_PATH_FOLDERS, NAV_EXTRA_MAX, NAV_EXTRA_SCHEMES, NAV_HOME_TITLE,
                                     SIZE_COPY_EXTS, TITLE_SEPARATOR_DEFAULT)
from contentmodel.keytables import VIEW_PIECE_KEYS, piece_keys_read

from adoption import carry, homeparts
from adoption.convert import PIECE_KEY_SYNONYMS
from adoption.facts import links_above_title
from adoption.keycover import synonym_sources
from adoption.settings import (BACK_LINK_MAX, V5_PORTFOLIO_SETTINGS, V6_PORTFOLIO_SETTINGS, featured_shelf, media_pattern_ok,
                               separator_ok, setting_family)
from adoption.template import split_front


DEFAULTS = {"look": "site-studio", "featuredFrom": "home", "nav.home": True, "resume.headings": "shift", "resume.layout": "plain",
            "cardLabels": True,
            "cardNumber": False, "cardNumberFormat": "padded", "backLink": None, "blocks.headingLevel": None, "blocks.loneReferenceGrid": False,
            "blocks.videoEmbed": "facade", "workKeys": "work",
            "titleForm": "site", "introScope": "body", "partOrder": None,
            "featuredView": "flat", "titleSeparator": None, "nav.extra": None,          # schema 6 (design-adopt-parity-2 section 7.6)
            "blocks.headings": "shift", "sizeCopies": None, "carried": None}
BUILT_IN_VIEWS = ("grid", "page", "roles", "map", "showcase", "steps")        # `steps` at schema 5 (design-movement-view 6.1)


def partner(name, cand, snap=None):
    """The setting whose best value a candidate of `name` is scored under, or None: the two settings do not separate on the page."""
    if name == "cardNumber" and cand is True:
        return "cardNumberFormat"
    if name == "featuredFrom" and cand == "showcase" and snap is not None:   # step 5c-4: under `cardImage` a home tile shows the card's
        shelf = featured_shelf(lambda p: snap[p].decode("utf-8", "replace"), snap, {})[1]    # picture (O4b), chosen after this one
        return "cardImage." + shelf[0].split("/")[0] if shelf else None
    return {"resume.headings": "resume.layout", "resume.layout": "resume.headings"}.get(name)


def look_partner(name, cand):
    """Under a DERIVED look only (step 5c-3): `pieceTeaser.<p>: true` is scored under the best `pieceLink.<p>` and the other way
    round. A derived look reads a piece page only when every paragraph on it is explained, so the summary paragraph and the outbound
    link each leave the page as different as the other does until both print (finding 1064's shape)."""
    fam, _dot, port = name.partition(".")
    return ({"pieceTeaser": "pieceLink.", "pieceLink": "pieceTeaser."}[fam] + port) if cand is True and fam in (
        "pieceTeaser", "pieceLink") and port else None


VIDEO_EMBED = "blocks.videoEmbed"              # the same: its look is derived FOR the candidate, since only the live address lets the derive map a player


_FM = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):[ \t]*(.*?)[ \t]*$")
_ANCHOR = re.compile(r"<a\b[^>]*\bhref=\"([^\"#?]*)\"[^>]*>\s*([^<]{1,%d}?)\s*</a>" % BACK_LINK_MAX, re.I)   # 0.5.x's (HELD)


def _front(text):
    if not text.startswith("---\n"):
        return {}
    out = {}
    for line in text.split("\n")[1:]:
        if line.rstrip() == "---":
            break
        m = _FM.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def portfolio_facts(snap):
    """{portfolio: {"pieces": [front matter dicts], "view": value or None, "sort": value or None}} from the converted tree."""
    out = {}
    for path in sorted(snap):
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "content" and parts[2] == "page.md" and not parts[1].startswith("_"):
            fm = _front(snap[path].decode("utf-8", "replace"))
            out.setdefault(parts[1], {"pieces": [], "view": fm.get("view") or None, "sort": fm.get("sort") or None})
    for path in sorted(snap):
        parts = path.split("/")
        if (len(parts) == 4 and parts[0] == "content" and parts[1] in out and parts[3] == "index.md"
                and not parts[2].startswith("_")):
            out[parts[1]]["pieces"].append(_front(snap[path].decode("utf-8", "replace")))
    return out


def heading_levels(local):
    """The heading levels (2 to 6) the old builder's own pages use, sorted: the candidates for `blocks.headingLevel`, because a
    heading inside a block can only be one of the levels the old site prints headings at."""
    found = set()
    for path, blob in (local or {}).items():
        if path.lower().endswith((".html", ".htm")):
            found.update(int(m) for m in re.findall(r"<h([2-6])\b", blob.decode("utf-8", "replace")))
    return sorted(found)


def uses_block_headings(snap):
    """True when some page of the converted tree holds a `:::carousel`: the only block the plugin writes headings inside."""
    return any(p.endswith(".md") and b":::carousel" in b for p, b in snap.items())


_REF_LINE = re.compile(r"^ref:\s*[A-Za-z0-9_-]+\s*$")


def has_lone_reference(snap):
    """True when a page body of the converted tree holds a `ref:` line standing alone: the run of adjacent `ref:` lines it belongs to
    is one line long. The build prints one reference as a bare card and two or more inside the reference grid, so only such a body
    can differ from a builder that wraps a lone reference in a grid of one. A captured reference's own `text.md` is never rendered."""
    for path, blob in snap.items():
        if not path.startswith("content/") or not path.endswith(".md") or path.startswith("content/references/"):
            continue
        run = 0
        for line in blob.decode("utf-8", "replace").replace("\r\n", "\n").split("\n") + [""]:
            if _REF_LINE.match(line):
                run += 1
                continue
            if run == 1:
                return True
            run = 0
    return False


def _lands_on(page, href, port):
    """True when `href`, read from the output page `page`, is the index of portfolio `port` (`/work/`, `../`, `../index.html`)."""
    if not href or re.match(r"^[a-z][a-z0-9+.-]*:|^//", href, re.I):
        return False
    target = posixpath.normpath(href.lstrip("/") if href.startswith("/") else posixpath.join(posixpath.dirname(page), href))
    return re.sub(r"(?:^|/)index\.html$", "", target).strip("/") == port


def back_link_texts(snap, local, port=None):
    """The link text the old builder's own piece pages put above the piece title for a link to the portfolio's index: the set of
    distinct texts over every piece page of `local` ({output path: bytes}) of every portfolio, or of portfolio `port` alone (schema
    6's `backLink.<p>`). One text is the candidate; none, or more than one, is no candidate (adopt cannot say which words are the
    person's).

    For `backLink.<p>` each page's text is its first link, in `content` before the first `h1` there, that lands on the index and
    holds only text (at most `BACK_LINK_MAX` characters): `adoption.facts.links_above_title`, the region `backLink.<p>` is judged
    in, so the site menu's link to the portfolio (`chrome`) is never read (step 8d: on template-variant-a it offered the menu's
    words). HELD (step 8d): the site-wide `backLink` of 0.5.x keeps 0.5.x's reading, the first anchor that lands on the index in
    the HTML before the first `<h1`, menu or not: reading it the new way moves the 0.5.0 pin of six fixtures and a held-out
    settings digest while `BACK_LINK_PER_PORTFOLIO` is False, and the site-wide name leaves `setting_names` at the switch."""
    found = set()
    for each in ([port] if port else portfolio_facts(snap)):
        for path in sorted(local or {}):
            parts = path.split("/")
            if len(parts) != 3 or parts[0] != each or parts[2] != "index.html":
                continue
            html = local[path].decode("utf-8", "replace")
            if port:
                links = [(h, t) for h, t in links_above_title(html) or () if t and len(t) <= BACK_LINK_MAX]
            else:
                head = re.split(r"<h1\b", html, maxsplit=1, flags=re.I)
                links = [(h, " ".join(t.split())) for h, t in _ANCHOR.findall(head[0])] if len(head) == 2 else []
            for href, text in links:
                if _lands_on(path, href, each):
                    found.add(text)
                    break
    return sorted(found)


_VIDEO_BLOCK = re.compile(r"^:::videos\b", re.M)
_GALLERY_VIDEO_ROW = re.compile(r"^!\[[^\]\n]*\]\([^)\s\n]+(?:\s+\"[^\"\n]*\")?\)[ \t]+\S", re.M)


def has_video(snap):
    """True when a page body of the converted tree holds a `:::videos` block or a gallery video row (an image line followed by the
    video's address). Only such a body writes a player address, so only such a site can differ in it."""
    for path, blob in snap.items():
        if path.startswith("content/") and path.endswith(".md") and not path.startswith("content/references/"):
            text = blob.decode("utf-8", "replace")
            if _VIDEO_BLOCK.search(text) or _GALLERY_VIDEO_ROW.search(text):
                return True
    return False


KICKER_MAX = 4                       # cardKicker's piece keys tried after the default (design-movement-view 6.3)
TEASER_SOURCES = tuple(src for src, dst in PIECE_KEY_SYNONYMS if dst == "teaser")    # what a pending conversion makes `teaser`


def _front_list(snap, port, key):
    """The names a list key of portfolio `port`'s page.md holds (`meta: [a, b]` or a block list), [] when it has none."""
    text = snap.get("content/%s/page.md" % port, b"").decode("utf-8", "replace")
    out, inside = [], False
    for line in text.split("\n")[1:] if text.startswith("---\n") else ():
        if line.rstrip() == "---":
            break
        m = _FM.match(line)
        if m:
            inside = m.group(1) == key
            if inside and m.group(2):
                out += [t.strip().strip("'\"") for t in m.group(2).strip("[]").split(",") if t.strip()]
        elif inside and line.strip().startswith("- "):
            out.append(line.strip()[2:].strip().strip("'\""))
    return out


def portfolio_settings(port, snap, settings=None):
    """The portfolio-level settings `port` is judged under, as `keytables.active_triggers` reads them: its `view` (the setting when
    one is chosen, else as written) and each of the five card and piece settings that has a value. `cardKicker` is left out: the
    key it names is the one being chosen."""
    s = settings or {}
    out = {"view": s.get("view." + port) or portfolio_facts(snap).get(port, {}).get("view")}
    for fam in V5_PORTFOLIO_SETTINGS:
        if fam != "cardKicker" and s.get("%s.%s" % (fam, port)) not in (None, False):
            out[fam] = s["%s.%s" % (fam, port)]
    return out


def read_keys(port, snap, data, settings=None):
    """The piece keys of portfolio `port` that something reads under `settings` (the stray check's own sources,
    `strays.piece_known_keys`): the built-in keys and `description`, what `meta`, `cardMeta` and `groupBy` name (site.json's `work`
    object for the portfolio named `work`, or every portfolio under `workKeys: all`), `featured` under `featuredFrom: flags`, the
    keys of its view and of `cardNumber`, the schema-5 keys its settings read, and every key a pending conversion renames."""
    s = settings or {}
    known = set(BUILTIN_PIECE_KEYS) | {"description"} | synonym_sources()
    work = (data or {}).get("work") or {}
    for key in ("meta", "cardMeta"):
        known.update(_front_list(snap, port, key))
        if port == "work" or s.get("workKeys") == "all":
            known.update(work.get(key) or ())
    known.update(_front_list(snap, port, "groupBy"))
    if s.get("featuredFrom") == "flags":
        known.add("featured")
    ps = portfolio_settings(port, snap, s)
    known.update(VIEW_PIECE_KEYS.get(ps["view"], ()))
    if s.get("cardNumber"):
        known.update(VIEW_PIECE_KEYS["cardNumber"])
    known.update(piece_keys_read(ps))
    return known


def unread_keys(port, snap, data, settings=None):
    """cardKicker's candidates for `port`: each piece key nothing reads (`read_keys`), most-used first, name order on a tie, at most
    `KICKER_MAX`. A key a piece holds as `true` or `false` is never one: the build refuses to print a yes-or-no value as a kicker
    ("must be text, a number, or a list of them, because cardKicker: <key> reads it", `contentmodel.pagefiles`), so that candidate
    builds nothing. Found at step 9a2 on template-portfolio-a, where `featured: true` was measured as the kicker and parity's own
    build then refused the tree."""
    known = read_keys(port, snap, data, settings)
    shown, uses, yes_no = showcased(snap), {}, set()
    for path in sorted(snap):
        parts = path.split("/")
        if len(parts) != 4 or parts[:2] != ["content", port] or parts[3] != "index.md" or parts[2].startswith("_"):
            continue
        tile = VIEW_PIECE_KEYS["showcase"] if "%s/%s" % (port, parts[2]) in shown else ()
        for key, value in _front(snap[path].decode("utf-8", "replace")).items():
            if (value or "").strip() in ("true", "false"):
                yes_no.add(key)
            if key not in known and key not in tile:
                uses[key] = uses.get(key, 0) + 1
    return sorted((k for k in uses if k not in yes_no), key=lambda k: (-uses[k], k))[:KICKER_MAX]


def showcased(snap):
    """{`portfolio/slug`}: the pieces the converted home page's `showcase` list names. Their tile keys are read wherever their
    portfolio's view is (`strays.piece_known_keys`, design R4 row 6), so none of them is a kicker's key."""
    path = homeparts.home_in(snap)
    if path is None:
        return set()
    show = homeparts.front_values(split_front(snap[path].decode("utf-8", "replace"))[0]).get("showcase")
    return set("/".join(i.split("|")[0].strip().split("/")[:2]) for i in show if "/" in i) if isinstance(show, list) else set()


def v5_candidates(name, snap, data, settings=None, local=None):
    """The candidates of one of the five card and piece settings (design-movement-view 6.3), absent first; [None] when its
    "offered when" does not hold. `cardAlt` also offers schema 6's `"title"` where an old card picture's alt is its piece's title
    (`titled_cards`, read from `local`: owner decision 5, offered only by measurement)."""
    fam, port = name.split(".", 1)
    pieces = portfolio_facts(snap).get(port, {}).get("pieces", ())

    def has(*keys):
        return any(k in fm for fm in pieces for k in keys)
    if fam == "cardImage":
        if portfolio_settings(port, snap, settings)["view"] == "roles" and has("photo", "cover"):
            return [None, "photo", "cover"]
        return [None, "photo"] if has("photo") else [None]
    if fam == "cardAlt":
        return [None] + ([True] if has("coverAlt", "photoAlt") else []) + (["title"] if titled_cards(port, snap, local) else [])
    if fam == "cardKicker":
        return [None] + unread_keys(port, snap, data, settings)
    if fam == "pieceLink":
        return [None, True] if has("link") else [None]
    return [None, True] if has("teaser", *TEASER_SOURCES) else [None]          # pieceTeaser


def candidates_for(name, snap, data, local=None, settings=None):
    """The values to try for one setting, DEFAULT FIRST; a single value means there is nothing to choose (not measured). `local`
    is the old builder's output, which `backLink` (its text) and `partOrder` (the order of the old home's parts) read; `settings` the
    values the setting is judged under, which `partOrder` reads for `introScope` (`rest` is a part only under `first-block`) and the
    card and piece settings for what the portfolio reads."""
    fam = setting_family(name)
    if name == "carried":                   # section 7.6: the pages only the old build has, as `adoption.carry` offers them
        paths = carry.offer_for(snap, local).paths if local is not None else []
        return [None, paths] if paths else [None]
    if fam in V5_PORTFOLIO_SETTINGS and "." in name:
        return v5_candidates(name, snap, data, settings, local)
    if fam in V6_PORTFOLIO_SETTINGS or name in V6_SITE_SETTINGS or fam == "mediaPaths":
        return v6_candidates(name, snap, data, local, settings)
    facts = portfolio_facts(snap)
    if name == "titleForm":
        return ["site", "page"] if homeparts.home_in(snap) else ["site"]
    if name == "introScope":
        return ["body", "first-block"] if homeparts.block_count(snap) > 1 else ["body"]
    if name == "partOrder":
        order = homeparts.old_order(snap, local, (settings or {}).get("introScope", "body"))
        return [None, order] if order else [None]
    if fam == "onePieceIndex":
        port = name.split(".", 1)[1]
        return ["redirect", "listing"] if port in facts and len(facts[port]["pieces"]) == 1 else ["redirect"]
    if fam == "cardNumber":
        has = any(re.match(r"^-?\d+$", fm.get("order", "")) or re.match(r"^\d{4}$", fm.get("year", "")) for f in facts.values()
                  for fm in f["pieces"])
        return [False, True] if has else [False]
    if fam == "backLink":                   # `backLink.<p>` reads that portfolio's piece pages; the site-wide name, every portfolio's
        texts = back_link_texts(snap, local, name.split(".", 1)[1] if "." in name else None)
        return [None, texts[0]] if len(texts) == 1 else [None]
    if name == "cardNumberFormat":
        ints = any(re.match(r"^-?\d+$", fm.get("order", "")) for f in facts.values() for fm in f["pieces"])
        return ["padded", "plain", "order"] if ints else ["padded"]
    if name == "blocks.headingLevel":
        levels = heading_levels(local)
        return [None] + levels if levels and uses_block_headings(snap) else [None]
    if name == "blocks.loneReferenceGrid":
        return [False, True] if has_lone_reference(snap) else [False]
    if name == VIDEO_EMBED:
        return ["facade", "live"] if has_video(snap) else ["facade"]
    if name == "workKeys":
        work = (data or {}).get("work") or {}
        shared = work.get("meta") or work.get("cardMeta")
        others = [p for p, f in facts.items() if p != "work" and f["pieces"]]
        return ["work", "all"] if shared and others else ["work"]
    if fam == "look":
        return ["site-studio"]               # the derived candidate is added by the caller when the default fails
    if fam == "featuredFrom":
        flagged = any(fm.get("featured", "").lower() in ("true", "yes") for f in facts.values() for fm in f["pieces"])
        shelf = featured_shelf(lambda p: snap[p].decode("utf-8", "replace"), snap, settings or {})[1]
        return ["home"] + (["flags"] if flagged else []) + (["showcase"] if shelf else [])
    if fam == "nav.home" or name == "nav.home":
        return [True, False, NAV_HOME_TITLE]          # schema 6's "title": the first item's text is the site title (section 7.6)
    if name in ("resume.headings", "resume.layout"):
        has = "content/resume/resume.md" in snap or any(p.endswith("/resume.md") for p in snap)
        return (["shift", "as-written"] if name == "resume.headings" else ["plain", "cards"]) if has else [DEFAULTS[name]]
    if fam == "cardLabels":
        work = (data or {}).get("work") or {}
        return [True, False] if (work.get("meta") or work.get("cardMeta")) else [True]
    port = name.split(".", 1)[1] if "." in name else None
    f = facts.get(port)
    if fam == "sort" and f:
        ints = f["pieces"] and all(re.match(r"^-?\d+$", fm.get("order", "")) for fm in f["pieces"])
        return ["date", "order"] if ints else ["date"]
    if fam == "menuLinks" and f:
        return ["index", "single-piece"] if len(f["pieces"]) == 1 else ["index"]
    if fam == "view" and f:
        return view_candidates(f)
    return [DEFAULTS.get(name)]


VIEW_CAP = 5                         # section 7.6: `view.<p>` tries at most five views
TILE_KEYS = ("tileImage", "tileAlt", "tileRole")      # a steps or showcase tile's own keys (contentmodel.keytables)


def view_candidates(f):
    """`view.<p>` (design-adopt-parity-2 section 7.6): the written view (or `grid`), `grid`, `page`, then each built-in index the
    pieces carry the keys of: `roles` when EVERY piece has `employer`, `map` when one has `pin`, `steps` and `showcase` when one has a
    tile key; at most `VIEW_CAP`, default first. A view the person wrote stays first (it loses only to EQUAL: `choose.decide`)."""
    written = f["view"]
    first = written if written in BUILT_IN_VIEWS else "grid"
    pieces = f["pieces"]
    extra = []
    if pieces and all(fm.get("employer") for fm in pieces):
        extra.append("roles")
    if any("pin" in fm for fm in pieces):
        extra.append("map")
    if any(k in fm for fm in pieces for k in TILE_KEYS):
        extra += ["steps", "showcase"]
    out = [first]
    for v in ["grid", "page"] + extra:
        if v not in out:
            out.append(v)
    return out[:VIEW_CAP]


# ---- the schema-6 candidates (design-adopt-parity-2 section 7.6), each offered only where adopt measures it ----------------------
V6_SITE_SETTINGS =("featuredView", "titleSeparator", "nav.extra", "blocks.headings", "sizeCopies")    # and `mediaPaths.<folder>`
_TAG = re.compile(r"<[^>]*>")
_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
_IMG_ALT = re.compile(r"<img\b[^>]*?\balt=\"([^\"]*)\"", re.I)
_NAV = re.compile(r"<nav\b[^>]*>(.*?)</nav\s*>", re.I | re.S)
_NAV_LINK = re.compile(r"<a\b[^>]*\bhref=\"([^\"]*)\"[^>]*>(.*?)</a\s*>", re.I | re.S)


def _text(fragment):
    return " ".join(html_mod.unescape(_TAG.sub(" ", fragment)).split())


def _page(local, path):
    blob = (local or {}).get(path)
    return blob.decode("utf-8", "replace") if blob is not None else ""


def _page_front(snap, port):
    return _front(snap.get("content/%s/page.md" % port, b"").decode("utf-8", "replace"))


def group_values(port, snap, data):
    """The group values of portfolio `port` in order (its `groups`, else the values of its `groupBy` key the pieces carry), or []
    when it has no `groupBy` (in its page.md, or site.json's `work` for the portfolio named `work`)."""
    work = ((data or {}).get("work") or {}) if port == "work" else {}
    key = _page_front(snap, port).get("groupBy") or work.get("groupBy")
    if not key:
        return []
    listed = _front_list(snap, port, "groups") or list(work.get("groups") or ())
    seen = []
    for fm in portfolio_facts(snap).get(port, {}).get("pieces", ()):
        v = fm.get(str(key).strip("[]'\" "))
        if v and v not in seen:
            seen.append(v)
    return listed or seen


def old_count_headings(port, snap, data, local, page=None):
    """[(group value, number, word or "")] for each heading of the old index of `port` (or of the old page `page`) that starts with a
    group value and then a number: `Buildings 2 projects`, `Objects (1 object)`."""
    out = []
    groups = group_values(port, snap, data)
    for _lvl, inner in _HEADING.findall(_page(local, page or "%s/index.html" % port)):
        text = _text(inner)
        for g in groups:
            m = re.match(r"^%s\W*(\d+)\s*([^\W\d_][\w-]*)?" % re.escape(g), text, re.U)
            if m:
                out.append((g, int(m.group(1)), m.group(2) or ""))
                break
    return out


def count_words(port, snap, data, local):
    """`labels.counts` read from the old group headings (section 7.6): {group: {"one": word, "other": word}}, the word after the
    number; a form not on the old pages is written as the form that is (so the adopted page prints what the old one did). {}
    when no heading holds a word. The headings are read from EVERY old page whose group heading holds a count, the portfolio's
    index first and then the others by path (step 11, dev 986): a home shelf that shows the featured `1 project` is where a
    group's `one` form is, when the index shows that group only with more. The first page that shows a group's form names it."""
    out = {}
    pages = ["%s/index.html" % port] + sorted(p for p in (local or {}) if p.lower().endswith((".html", ".htm"))
                                               and p != "%s/index.html" % port)
    for g, n, word in [h for p in pages for h in old_count_headings(port, snap, data, local, p)]:
        if word:
            forms = out.setdefault(g, {})
            forms.setdefault("one" if n == 1 else "other", word)
    for forms in out.values():
        seen = forms.get("other") or forms.get("one")
        forms.setdefault("one", seen)
        forms.setdefault("other", seen)
    return out


def titled_cards(port, snap, local):
    """True when a card picture on the old index of `port` is named by its piece's title (`alt="<title>"`): the case
    `cardAlt: "title"` exists for (owner decision 5)."""
    titles = set(fm.get("title", "").strip("'\"") for fm in portfolio_facts(snap).get(port, {}).get("pieces", ()))
    titles.discard("")
    return any(html_mod.unescape(a).strip() in titles for a in _IMG_ALT.findall(_page(local, "%s/index.html" % port)))


def featured_grouped(snap, data):
    """True when a featured piece (`featured: true`) belongs to a portfolio with `groupBy`: where `featuredView: grouped` can
    differ from the flat shelf."""
    return any(group_values(port, snap, data) and any(fm.get("featured", "").lower() in ("true", "yes") for fm in f["pieces"])
               for port, f in portfolio_facts(snap).items())


def old_titles(local):
    return [_text(m) for path in sorted(local or {}) if path.lower().endswith((".html", ".htm"))
            for m in re.findall(r"<title\b[^>]*>(.*?)</title\s*>", _page(local, path), re.I | re.S)]


def title_separator(local, data):
    """The separator every old `<title>` that names the site after a page's title shares (`Kiln House · Tern Studio` gives ` · `),
    when it is one value, differs from the default and is one `site.json` accepts (section 3.2); else None."""
    site = ((data or {}).get("siteTitle") or (data or {}).get("name") or "").strip()
    if not site:
        return None
    seps = set()
    for t in old_titles(local):
        if t != site and t.endswith(site):
            m = re.match(r"^.*?\w(\W*)$", t[:-len(site)], re.U)
            if m and m.group(1):
                seps.add(m.group(1))
    if len(seps) != 1:
        return None
    sep = seps.pop()
    return sep if sep != TITLE_SEPARATOR_DEFAULT and separator_ok(sep) else None


def nav_extra(local):
    """`nav.extra` (section 7.6): the `https:` and `mailto:` links the old pages' menus hold after their other items, at most
    `NAV_EXTRA_MAX`, as [{"label", "url"}]; None when two menus that hold such links disagree, when none does, or when one holds
    another kind of address there (an `http:` one, which the site gate refuses: section 3.2). A menu with no such link (a hand-made
    page's own menu, which `nav.extra` does not print into) proposes nothing; whether the candidate is right is measured."""
    found = None
    for path in sorted(local or {}):
        if not path.lower().endswith((".html", ".htm")):
            continue
        nav = _NAV.search(_page(local, path))
        if not nav:
            continue
        tail = []
        for href, label in reversed(_NAV_LINK.findall(nav.group(1))):
            if not re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I):
                break
            tail.insert(0, {"label": _text(label), "url": href})
        if any(not t["url"].startswith(NAV_EXTRA_SCHEMES) for t in tail) or len(tail) > NAV_EXTRA_MAX:
            return None
        if not tail:
            continue
        if found is not None and tail != found:
            return None
        found = tail
    return found or None


_MD_HEADING = re.compile(r"^#{1,6}[ \t]+\S")
_FENCE = re.compile(r"^(```|~~~)")


def body_headings(snap):
    """True when a Markdown body the build renders with `blocks.headings` (every one but the resume's, and never a captured
    reference's `text.md`) holds a heading line outside a code fence: only such a body can differ between `shift` and
    `as-written`."""
    for path in sorted(snap):
        if (not path.startswith("content/") or not path.endswith(".md") or path.startswith("content/references/")
                or path.endswith("/resume.md")):
            continue
        fence = False
        for line in split_front(snap[path].decode("utf-8", "replace"))[1]:
            if _FENCE.match(line):
                fence = not fence
            elif not fence and _MD_HEADING.match(line):
                return True
    return False


MEDIA_DEFAULTS = {"references": "references/{name}/media/{file}", "home": "home/media/{file}", "about": "about/media/{file}"}


def media_files(folder, snap):
    """[(path under the folder's `media/`, the reference's name or None, bytes)] of folder `references`, `home` or `about` of the
    converted tree (`building.mediapaths`' three sources)."""
    out = []
    for path in sorted(snap):
        parts = path.split("/")
        if folder == "references":
            if len(parts) >= 5 and parts[:2] == ["content", "references"] and parts[3] == "media":
                out.append(("/".join(parts[4:]), parts[2], snap[path]))
        elif len(parts) >= 4 and parts[:3] == ["content", folder, "media"]:
            out.append(("/".join(parts[3:]), None, snap[path]))
    return out


def media_pattern(folder, snap, local):
    """`mediaPaths.<folder>`'s candidate (section 7.6): the one pattern every file of that folder fits, read by matching bytes to
    the old build's paths. A file is matched by the old paths that hold its very bytes and end in its path under `media/`; what is
    before that is the pattern, with the reference's own folder name read as `{name}` (exactly once). An old path where the plugin
    publishes ANOTHER media file anyway (its address without the key: the repo path less `content/`) is that file's, never a match: two
    pictures with the same bytes are not one file. A file the old build does not serve is no evidence either way. None when no file
    is matched, when two files fit no one pattern, when the pattern is where the plugin publishes the folder anyway, or when site.json
    would refuse it (`settings.media_pattern_ok`)."""
    files = media_files(folder, snap)
    if not files or not local:
        return None
    by_bytes = {}
    for path, blob in local.items():
        by_bytes.setdefault(blob, []).append(path)
    served = set(p[len("content/"):] for p in snap if p.startswith("content/") and "/media/" in p)
    fits = None
    for under, ref, blob in files:
        pats = set()
        own = (MEDIA_DEFAULTS[folder].replace("{name}", ref or "").replace("{file}", under))
        for old in by_bytes.get(blob, ()):
            if not old.endswith("/" + under) or (old in served and old != own):
                continue
            segs = old[:-len(under) - 1].split("/")
            if ref is not None:
                if segs.count(ref) != 1:
                    continue
                segs = ["{name}" if s == ref else s for s in segs]
            pats.add("/".join(segs + ["{file}"]))
        if not pats:
            continue
        fits = pats if fits is None else fits & pats
        if not fits:
            return None
    if not fits or len(fits) != 1:
        return None
    pattern = fits.pop()
    return pattern if pattern != MEDIA_DEFAULTS[folder] and media_pattern_ok(folder, pattern) else None


_SIZE_COPY = re.compile(r"^(?P<stem>.+)\.w\d+(?P<ext>\.[A-Za-z0-9]+)$")


def other_format_copies(snap):
    """True when a media file of the converted tree is a size copy (`<stem>.wNNN<ext>`) whose picture has another raster extension
    (`<stem>.png` beside `<stem>.w480.jpg`) and none with its own: the copy `sizeCopies: any-format` admits (section 4.6)."""
    for path in snap:
        m = _SIZE_COPY.match(path) if path.startswith("content/") else None
        if m is None or m.group("ext").lower() not in SIZE_COPY_EXTS or (m.group("stem") + m.group("ext")) in snap:
            continue
        if any((m.group("stem") + e) in snap for e in SIZE_COPY_EXTS if e != m.group("ext").lower()):
            return True
    return False


def media_folders(snap):
    """The media folders of the converted tree that hold a file, in `MEDIA_PATH_FOLDERS` order."""
    return [f for f in MEDIA_PATH_FOLDERS if media_files(f, snap)]


def v6_candidates(name, snap, data, local=None, settings=None):
    """The candidates of a schema-6 setting, default first; one value when its "offered when" does not hold (section 7.6).
    `groupCount`'s second candidate carries the words its count prints, `{"counts": ...}`, when the old headings show any."""
    fam = setting_family(name)
    port = name.split(".", 1)[1] if fam in V6_PORTFOLIO_SETTINGS else None
    if fam == "groupCount":
        if not any(n for _g, n, _w in old_count_headings(port, snap, data, local)):
            return [None]
        words = count_words(port, snap, data, local)
        return [None, {"counts": words} if words else True]
    if name == "blocks.headings":
        return ["shift", "as-written"] if body_headings(snap) else ["shift"]
    if fam == "mediaPaths":
        pattern = media_pattern(name.split(".", 1)[1], snap, local)
        return [None, pattern] if pattern else [None]
    if name == "sizeCopies":
        return [None, "any-format"] if other_format_copies(snap) else [None]
    if fam == "pieceRoles":
        roles = [fm.get("role", "") for fm in portfolio_facts(snap).get(port, {}).get("pieces", ())]
        return [None, True] if any("(" in r or ";" in r for r in roles) else [None]
    if name == "featuredView":
        return ["flat", "grouped"] if featured_grouped(snap, data) else ["flat"]
    if name == "titleSeparator":
        sep = title_separator(local, data)
        return [None, sep] if sep else [None]
    extra = nav_extra(local)                                          # nav.extra
    return [None, extra] if extra else [None]


# `backLink.<p>` replaces the site-wide `backLink` in the names (section 7.6; built at step 8b, held until step 8h2's held-out reader
# judged the move on both held-out fixtures and moved their digests, with the 0.5.0 pin's MOVED rows, in the switching commit). Off,
# the names are 0.5.0's one site-wide `backLink`; a site-wide `backLink` a person chose is still kept as chosen (`choose.choose`).
BACK_LINK_PER_PORTFOLIO = True


def setting_names(snap):
    """The settings this tree has, in the order they are chosen."""
    names = ["look", "featuredFrom", "featuredView"]
    names += ["mediaPaths.%s" % f for f in media_folders(snap)] + (["sizeCopies"] if other_format_copies(snap) else [])
    names += ["sort.%s" % p for p in sorted(portfolio_facts(snap))]
    names += ["nav.home", "nav.extra", "titleSeparator", "resume.headings", "resume.layout", "workKeys", "cardLabels", "cardNumber",
              "cardNumberFormat"]
    names += ["%s.%s" % (fam, p) for fam in V5_PORTFOLIO_SETTINGS + V6_PORTFOLIO_SETTINGS for p in sorted(portfolio_facts(snap))]
    if BACK_LINK_PER_PORTFOLIO:
        names += ["backLink.%s" % p for p in sorted(portfolio_facts(snap))]      # schema 6: per portfolio (section 7.6)
    else:
        names += ["backLink"] if portfolio_facts(snap) else []
    names += ["menuLinks.%s" % p for p in sorted(portfolio_facts(snap))]
    names += ["onePieceIndex.%s" % p for p in sorted(portfolio_facts(snap))]
    names += ["blocks.headingLevel", "blocks.headings", "blocks.loneReferenceGrid", "blocks.videoEmbed", "titleForm", "introScope",
              "partOrder"]          # `blocks.headings` after the level a block's heading takes (choose.JUDGED_LAST, step 8b)
    names += ["view.%s" % p for p in sorted(portfolio_facts(snap))]
    return names


def measured_names(snap):
    """The settings a measurement with an old build chooses: `setting_names`, then `carried` (step 10b), whose candidates come from
    the old build alone. Last: its scope is its own pages, which no other setting's candidate changes, so the first pass judges
    every other setting as before it existed, and the next pass judges them with the carried pages in both builds."""
    return setting_names(snap) + ["carried"]
