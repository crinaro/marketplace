"""adoption.choose -- choose each measured setting by building the plugin's side once per candidate (design 8, "Measured settings";
R5.3, R6; step 1.9).

Part of the `adoption` package behind the entry point `adopt.py`. The settings and what writes them are `adoption.settings`; this
module DECIDES them:

  * ORDER. `look` first, then `featuredFrom`, `sort`, `nav.home`, `resume.headings`, `cardLabels` and the `view` of each portfolio,
    each with the earlier choices fixed. Greedy; interactions beyond that are design UNDETERMINED U-4.
  * MEASURE. Per candidate the plugin side alone is built IN MEMORY (`build.accept` over the converted tree: no git, no node, no
    disk) and compared, on the pages the setting can touch (`settings.setting_paths`), with the ONE local build. The first candidate
    whose touched pages are EQUAL or MARKUP-ONLY is the conversion (`how: measured`). When none qualifies, the candidate with the
    FEWEST visible differences on those pages is the conversion if it has strictly fewer than the default (`how: measured`, the
    reason says "fewest visible differences" and how many); when none is strictly better the setting is `you decide`, naming each
    candidate's first visible difference, and it keeps its default (`how: not measured`).
  * FIXED POINT (step 1.9f). A setting is judged with every OTHER setting at the value chosen for it, so a setting that only makes
    sense under the right look (the nav's Home item, a card number, a menu link) is judged under that look, and the look is
    judged with those settings applied. One pass in order cannot do that, so passes repeat until no value changes, at most
    `MAX_PASSES` (3); the cost bound below counts passes. Without the fixed point every setting was judged against the default
    look on every page, no candidate could qualify, and the plan kept the default look (G3 on template-variant-a: 14 of 14
    `not measured`).
  * NO LOCAL BUILD, NO CHOICE (R1, S6). With no local build (node missing, a template that needs a network install, any other
    reason P1 gives) no setting is chosen: every one is `you decide: not measured (<the reason>)`, the reason printed once, and `look`
    is NEVER defaulted to a candidate. A setting the person CHOSE (`how: chosen`) is kept and not measured.
  * LOOK. Candidates in order: the default look; then, only if it does not qualify, a look DERIVED from the local build's own pages
    against the converted content (`look.derive_look`, R5.4, R6): vendored as `site/looks/derived.json`. EQUAL under a derived look is
    evidence of page assembly on the person's current content, not of template fidelity (R5.3); a construct it could not map stays
    DIFFERENT and is a `look/unmapped/<construct>` cause (`Chosen.look_status`).
  * THE LOOK FOLLOWS THE CANDIDATE (step G3 flip). A derived look is made FROM the converted content, and a setting changes that content
    (a card number the plugin now prints is a slot the old card's number can be mapped to; a card label that is off makes the card's
    value the text the old page shows, so a year is no longer a literal). So while a derived look is the look in play, every
    candidate of every other setting is judged under the look derived FOR THAT CANDIDATE (`derive_under(settings)`), and the look
    the plan keeps is derived once more under the settings finally chosen. Without this a setting that only helps once the look
    can carry what it adds (cardNumber, cardLabels) is judged against a look made without it, ties, and stays `not measured`.
  * A SETTING THAT CHANGES NOTHING A VISITOR SEES. When every candidate, the default included, leaves exactly the same visible
    differences on the pages the setting touches, the setting has no effect there: the default is kept, `how: measured`, and the
    reason says so. (A tie with different differences is still `not measured`: the person decides.)
  * SORT IS JUDGED BY ORDER. `sort.<portfolio>` changes the ORDER of the pieces on the portfolio's index and nothing else, and a look
    that cannot map cards that stand in another order hides the right value (the cards of a portfolio sorted by `order` do not
    form the run the date order builds). So it is scored by the order of the piece links on the index page, old against
    candidate (`link_order`), never by the page's other differences.
  * A DEPENDENT VALUE. A card number prints in a format, and a number in the wrong format is worse than none, so the candidate
    `cardNumber: true` is scored under the best `cardNumberFormat` (`partner`); the format is then chosen on its own. The resume's
    headings and its layout are two halves of one page (role cards under headings written as the old page wrote them), and each
    alone leaves the page as different as the other does, so each is scored under the best value of the other.
  * A VIEW AS WRITTEN. A built-in `view` the old page.md names (`roles`, `showcase`) is what the person wrote: another view wins
    only by being EQUAL, never by having fewer differences (a grid has fewer differences from a page it does not look like).
  * WHAT A SETTING IS NOT JUDGED ON. A difference no visitor of the page meets (`not_seen`: the `<meta name="description">` text a search
    engine reads, and the plugin's own stylesheet and script files, which change nothing on a page that does not use them) is in every
    candidate's pages, so it can never decide between them, and it made every setting that touches a page with one a tie. The publish
    gate still counts them (parity says DIFFERENT); only the choice of a setting ignores them.
  * THE HOME'S AND THE INDEX'S OPTIONS (G3 adopt link). `titleForm`, `introScope` and `partOrder` (the home page's front matter) and
    `onePieceIndex.<portfolio>` (a one-piece portfolio's page.md) are schema-4 build options, measured like the rest, each on the
    one page it touches. The candidate for `partOrder` is READ from the old build (`adoption.homeparts`: the order the old home page
    prints the parts of the converted home in) and kept only when the plugin's build agrees: a reading is a guess where two parts
    share their only text, the measurement is not. `introScope` is offered for a home whose body has a second block outside its
    `:::part` blocks, and `rest` is a part of a `partOrder` only under `first-block`. The home's options are judged under every other
    setting but no other setting is judged under them (a `partOrder` naming `featured` made `featuredFrom` unmeasurable in the second
    pass), and each is judged under a refined look (`look.derive_look` reads again while an instance stays ambiguous, up to four
    times), because one reading leaves a wrapped part of the home ambiguous.
  * THE LONE REFERENCE (G3, the last link). `blocks.loneReferenceGrid` (site.json, schema 4) is offered only where a body of the
    converted tree holds a `ref:` line that stands alone (`has_lone_reference`: the build writes one reference as a bare card and two
    or more as a grid), and measured on every page like any other: the old builder's grid of one is what a candidate has to equal.
  * THE LIVE PLAYER (owner ruling 2026-11-18). `blocks.videoEmbed` (site.json, schema 4) is offered only where the converted tree
    holds a `:::videos` block or a gallery video row (`has_video`), and judged like `blocks.loneReferenceGrid`: last, on every page,
    under the look derived FOR the candidate. Only the live address lets the look derive map a player (the page's own address is the
    value a slot is found by), so the plugin's click-to-load address (`facade`, the default) is judged first and the live one wins
    when it leaves fewer visible differences. The key is the ADDRESS; the look's markup says whether a player loads with the page.
  * A LOOK THAT LOSES CONTENT IS NOT THE CONVERSION (D2, dev 941). A derived look is a look of FEWEST differences when no candidate is
    EQUAL, and fewest is not the same as nothing taken away: a look that leaves out a piece's summary or an `<img>` leaves few
    differences and a visitor with less to see. Once every other setting has its value, the look the plan keeps is checked with
    `lost_content` (an image or video of an old page that the plugin's page has fewer of, or a text of the old page's content, `main`
    or the body without its chrome, that the plugin's page does not hold); one that loses any is `you decide`, never kept, and says
    what it loses. It is judged LAST, never while the look is a candidate: a card number, a label or a featured piece's picture is
    another setting's to put back, and a look judged before them would lose what they supply.
  * THE CARD AND PIECE SETTINGS (design-movement-view 6.3, schema 5). `cardImage`, `cardAlt`, `cardKicker`, `pieceLink` and
    `pieceTeaser` of each portfolio are offered only when their "offered when" holds (`v5_candidates`): a piece has `photo` (or, under
    a roles view, `photo` or `cover`); a piece has `coverAlt` or `photoAlt`; a piece key nothing reads exists (`unread_keys`: not built
    in, not in `meta`, `cardMeta` or `groupBy`, not read by the view or another setting the portfolio is judged under, not renamed by a
    pending conversion), most-used first, name order on a tie, at most `KICKER_MAX`; a piece has `link`; a piece has `teaser`, or a key a
    pending conversion makes `teaser` (`summary`). Each is judged like every setting, under the look derived for the candidate.
  * COST. One `accept` per candidate per pass, and a second pass runs only when the first moved a value off its default: the cost case
    (`test_choose.Cost`) bounds the whole at `3 x (candidates + 1) x` one `accept`, which is the pass cap times one pass. The five card
    and piece settings add at most 3 + 2 + 5 + 2 + 2 = 14 candidates per portfolio per pass, and none where nothing is offered: the
    gate counts them (`test_choose.CostSchema5`).

`evaluate(settings) -> {path: bytes}` is the plugin output for a settings dict, supplied by the caller (so the greedy loop is tested
over fakes and the real one is `accept`-backed in `adoption.measure`).
"""

import html.parser
import json
import posixpath
import re

import parity_classes
from configschema.configkeys import BUILTIN_PIECE_KEYS
from contentmodel.keytables import VIEW_PIECE_KEYS, piece_keys_read

from adoption import homeparts
from adoption.convert import PIECE_KEY_SYNONYMS
from adoption.keycover import synonym_sources
from adoption.settings import BACK_LINK_MAX, SETTING_ORDER, V5_PORTFOLIO_SETTINGS, featured_shelf, setting_family, setting_paths
from adoption.template import split_front

MAX_PASSES = 3
DEFAULTS = {"look": "site-studio", "featuredFrom": "home", "nav.home": True, "resume.headings": "shift", "resume.layout": "plain",
            "cardLabels": True,
            "cardNumber": False, "cardNumberFormat": "padded", "backLink": None, "blocks.headingLevel": None, "blocks.loneReferenceGrid": False,
            "blocks.videoEmbed": "facade", "workKeys": "work",
            "titleForm": "site", "introScope": "body", "partOrder": None}
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

HOME_OPTIONS = ("titleForm", "introScope", "partOrder")    # the home page's own options: each is judged under a refined look (read up to four times; one reading
#                                                            leaves the home's wrapped parts ambiguous), and no other setting under them
LONE_REFERENCE = "blocks.loneReferenceGrid"    # judged under every other setting, and no other setting under it (see JUDGED_LAST)
VIDEO_EMBED = "blocks.videoEmbed"              # the same: its look is derived FOR the candidate, since only the live address lets the derive map a player
JUDGED_LAST = HOME_OPTIONS + (LONE_REFERENCE, VIDEO_EMBED)   # judged under every other setting; no setting that is not one of these is judged under them
NEEDS_LOCAL = ("look", "backLink")          # settings whose candidates come from the old builder's own output
_FM = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):[ \t]*(.*?)[ \t]*$")
_ANCHOR = re.compile(r"<a\b[^>]*\bhref=\"([^\"#?]*)\"[^>]*>\s*([^<]{1,%d}?)\s*</a>" % BACK_LINK_MAX, re.I)


class Row(object):
    """One setting's result: `value`, `how` (`measured`, `chosen`, `not measured`), `reason`, and `tried` ([(candidate, first
    visible difference)] for a setting no candidate satisfied)."""

    def __init__(self, name, value, how, reason, tried=()):
        self.name, self.value, self.how, self.reason, self.tried = name, value, how, reason, list(tried)

    def plan_row(self):
        return {"value": self.value, "how": self.how, "reason": self.reason}


class Chosen(object):
    def __init__(self):
        self.rows, self.lines, self.look_status, self.passes = {}, [], {}, 0

    def values(self):
        return dict((n, r.value) for n, r in self.rows.items() if r.how in ("measured", "chosen") and r.value is not None
                    and r.value != DEFAULTS.get(n))

    def plan_rows(self):
        return dict((n, r.plan_row()) for n, r in self.rows.items())


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


def back_link_texts(snap, local):
    """The link text the old builder's own piece pages put above the piece title for a link to the portfolio's index: the set of
    distinct texts over every piece page of `local` ({output path: bytes}), read from the HTML before the first `<h1`. One text
    is the candidate; none, or more than one, is no candidate (adopt cannot say which words are the person's)."""
    found = set()
    for port in portfolio_facts(snap):
        for path in sorted(local or {}):
            parts = path.split("/")
            if len(parts) != 3 or parts[0] != port or parts[2] != "index.html":
                continue
            html = local[path].decode("utf-8", "replace")
            head = re.split(r"<h1\b", html, maxsplit=1, flags=re.I)
            if len(head) < 2:
                continue
            for href, text in _ANCHOR.findall(head[0]):
                if _lands_on(path, href, port):
                    found.add(" ".join(text.split()))
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
    `KICKER_MAX`."""
    known = read_keys(port, snap, data, settings)
    shown, uses = showcased(snap), {}
    for path in sorted(snap):
        parts = path.split("/")
        if len(parts) != 4 or parts[:2] != ["content", port] or parts[3] != "index.md" or parts[2].startswith("_"):
            continue
        tile = VIEW_PIECE_KEYS["showcase"] if "%s/%s" % (port, parts[2]) in shown else ()
        for key in _front(snap[path].decode("utf-8", "replace")):
            if key not in known and key not in tile:
                uses[key] = uses.get(key, 0) + 1
    return sorted(uses, key=lambda k: (-uses[k], k))[:KICKER_MAX]


def showcased(snap):
    """{`portfolio/slug`}: the pieces the converted home page's `showcase` list names. Their tile keys are read wherever their
    portfolio's view is (`strays.piece_known_keys`, design R4 row 6), so none of them is a kicker's key."""
    path = homeparts.home_in(snap)
    if path is None:
        return set()
    show = homeparts.front_values(split_front(snap[path].decode("utf-8", "replace"))[0]).get("showcase")
    return set("/".join(i.split("|")[0].strip().split("/")[:2]) for i in show if "/" in i) if isinstance(show, list) else set()


def v5_candidates(name, snap, data, settings=None):
    """The candidates of one of the five card and piece settings (design-movement-view 6.3), absent first; [None] when its
    "offered when" does not hold."""
    fam, port = name.split(".", 1)
    pieces = portfolio_facts(snap).get(port, {}).get("pieces", ())

    def has(*keys):
        return any(k in fm for fm in pieces for k in keys)
    if fam == "cardImage":
        if portfolio_settings(port, snap, settings)["view"] == "roles" and has("photo", "cover"):
            return [None, "photo", "cover"]
        return [None, "photo"] if has("photo") else [None]
    if fam == "cardAlt":
        return [None, True] if has("coverAlt", "photoAlt") else [None]
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
    if fam in V5_PORTFOLIO_SETTINGS and "." in name:
        return v5_candidates(name, snap, data, settings)
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
    if fam == "backLink":
        texts = back_link_texts(snap, local)
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
        return [True, False]
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
        written = f["view"]
        first = written if written in BUILT_IN_VIEWS else "grid"
        return [first] + [v for v in ("grid", "page") if v != first]
    return [DEFAULTS.get(name)]


def setting_names(snap):
    """The settings this tree has, in the order they are chosen."""
    names = ["look", "featuredFrom"]
    names += ["sort.%s" % p for p in sorted(portfolio_facts(snap))]
    names += ["nav.home", "resume.headings", "resume.layout", "workKeys", "cardLabels", "cardNumber", "cardNumberFormat"]
    names += ["%s.%s" % (fam, p) for fam in V5_PORTFOLIO_SETTINGS for p in sorted(portfolio_facts(snap))]
    names += ["backLink"] if portfolio_facts(snap) else []
    names += ["menuLinks.%s" % p for p in sorted(portfolio_facts(snap))]
    names += ["onePieceIndex.%s" % p for p in sorted(portfolio_facts(snap))]
    names += ["blocks.headingLevel", "blocks.loneReferenceGrid", "blocks.videoEmbed", "titleForm", "introScope", "partOrder"]
    names += ["view.%s" % p for p in sorted(portfolio_facts(snap))]
    return names


def _subset(files, paths):
    if "*" in paths:
        return files
    return dict((p, b) for p, b in files.items()
                if any(p == q or (q.endswith("/") and p.startswith(q)) for q in paths))


def not_seen(d):
    """True for a hunk of `classify_differences` no visitor of the page meets: the meta description (read by search engines, shown
    on no page) and a file of the plugin's own `site-studio/` assets (a stylesheet or script a page uses only where it carries the
    markup that needs it, and THAT markup is a difference of its own). Used to choose a setting, never to say two builds agree."""
    if d.path.startswith("site-studio/") and d.kind.startswith("only-plugin/"):
        return True
    return d.kind == "attribute/content" and any('name="description"' in line for line in list(d.local) + list(d.plugin))


def score(local, plugin, name):
    """(ok, first visible difference line, how many visible differences, the pages built, the differences themselves) for one
    candidate: the setting's pages in the two builds. The last is what two candidates are compared by when they have the same count."""
    if setting_family(name) == "sort":
        by_order = score_order(local, plugin, name)
        if by_order is not None:
            return by_order
    paths = setting_paths(name)
    theirs = _subset(plugin, paths)
    res = parity_classes.classify_differences(_subset(local, paths), theirs)
    built = frozenset(p for p in theirs if not p.startswith("site-studio/"))      # the PAGES: the plugin's own assets are no page a candidate drops
    if res["verdict"] in ("EQUAL", "MARKUP-ONLY"):
        return True, "", 0, built, ()
    shown = [d for d in res["visible"] or () if not not_seen(d)]
    if not shown and res["visible"]:
        return True, "", 0, built, ()
    seen = tuple(sorted((d.path, d.kind, tuple(d.local), tuple(d.plugin)) for d in shown))
    d = (shown or [None])[0]
    return (False, (("%s: %s" % (d.path, d.kind)) if d is not None else "a difference"), len(shown) or 1,
            built, seen)


_MEDIA = ("img", "video")
_SKIP_TEXT = ("script", "style", "title", "head", "template", "noscript")
_CHROME = ("nav", "footer")             # the menu and footer are the nav's and the footer's settings; a look is not judged on them here


class _Reading(html.parser.HTMLParser):
    """What one page SHOWS in its content area: the text nodes and the number of images and videos. The area is `<main>` where the page
    has one, else the body without its `header`, `nav` and `footer` elements (the page's chrome, never its content)."""

    def __init__(self, page):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.stack, self.texts, self.media, self.has_main = [], [], 0, "<main" in page.lower()
        self.feed(page)
        self.close()

    def live(self):
        tags = self.stack
        if any(t in _SKIP_TEXT or t in _CHROME for t in tags):
            return False
        if self.has_main:
            return "main" in tags
        return "header" not in tags or any(t in ("article", "section", "aside") for t in tags)

    def handle_starttag(self, tag, attrs):
        if tag in _MEDIA and self.live():
            self.media += 1
        if tag not in ("br", "hr", "img", "input", "meta", "link", "source", "wbr"):
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in _MEDIA and self.live():
            self.media += 1

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and re.search(r"[A-Za-z0-9]", text) and self.live():
            self.texts.append(text)


def lost_content(local, plugin, name):
    """The first thing the plugin's pages LOSE that the old builder's pages show, as a sentence, or "" when nothing is lost (D2, dev 941):
    on each page both builds write that the setting touches, an `<img>` or `<video>` the old page has and the plugin's page has no
    counterpart for (fewer of them), or a piece of text of the old page's content that the plugin's page does not hold. A candidate that
    loses content is never the one with 'fewest differences': a page that is missing what a visitor saw is not a page that differs a
    little. Asked last (`choose`), with every other setting at its chosen value: a card number, a label or a featured piece's picture is
    another setting's to supply, so a look judged earlier would lose what a setting not yet chosen puts back."""
    paths = setting_paths(name)
    for path in sorted(_subset(local, paths)):
        if not path.lower().endswith((".html", ".htm")) or path not in plugin:
            continue
        old, new = (_Reading(b[path].decode("utf-8", "replace")) for b in (local, plugin))
        if old.media > new.media:
            return "%s: %d image(s) or video(s) of the old page are not on the plugin's page" % (path, old.media - new.media)
        held = " ".join(new.texts)
        for words in old.texts:
            if words not in held:
                return "%s: the old page's text %r is not on the plugin's page" % (path, words[:40])
    return ""


_PIECE_HREF = re.compile(r"<a\b[^>]*\bhref=\"([^\"#?]+)\"", re.I)


def link_order(html, port, page):
    """The pieces `page` (an output path) links to, in order, as `<portfolio>/<slug>` (a piece appears once)."""
    seen = []
    for href in _PIECE_HREF.findall(html):
        if re.match(r"^[a-z][a-z0-9+.-]*:|^//", href, re.I):
            continue
        target = posixpath.normpath(href.lstrip("/") if href.startswith("/") else posixpath.join(posixpath.dirname(page), href))
        parts = re.sub(r"(?:^|/)index\.html$", "", target).strip("/").split("/")
        if len(parts) == 2 and parts[0] == port and "/".join(parts) not in seen:
            seen.append("/".join(parts))
    return seen


def score_order(local, plugin, name):
    """`score` for `sort.<portfolio>`: the order of the piece links on the portfolio's index page. ok when the two orders are the
    same; otherwise the count is the number of places where they differ. A page that links no piece in either build, or one that
    is not there, is no judgement (None): the caller keeps the default-first rule."""
    port = name.split(".", 1)[1]
    page = "%s/index.html" % port
    if page not in local or page not in plugin:
        return None
    want, got = (link_order(b[page].decode("utf-8", "replace"), port, page) for b in (local, plugin))
    if not want or sorted(want) != sorted(got):
        return None
    if want == got:
        return True, "", 0, frozenset((page,)), ()
    n = sum(1 for a, b in zip(want, got) if a != b)
    return False, "%s: the pieces are in another order" % page, n, frozenset((page,)), (tuple(got),)


def drop_lossy_look(res, local, evaluate):
    """A LOOK THAT LOSES CONTENT IS NOT THE CONVERSION (D2, dev 941): with every other setting at its chosen value, a derived look whose
    pages still miss a picture or a text the old pages show is not kept, however few differences it leaves: `look` becomes `you decide`
    and says what is lost. Changes `res` in place."""
    row = res.rows.get("look")
    if local is None or row is None or row.how != "measured" or not isinstance(row.value, dict):
        return
    final = dict((k, r.value) for k, r in res.rows.items()
                 if k != "look" and r.how in ("measured", "chosen") and r.value is not None and r.value != DEFAULTS.get(k))
    plugin = evaluate(dict(final, look=row.value))
    lost = "" if score(local, plugin, "look")[0] else lost_content(local, plugin, "look")
    if lost:
        res.rows["look"] = Row("look", None, "not measured", "the derived look loses content: " + lost, [("derived", "loses content: " + lost)])
        res.lines.append("you decide: look -- %s" % res.rows["look"].reason)


def judge(local, plugin, name):
    """(ok, first visible difference line) for one candidate (`score` without the count)."""
    ok, why, _n, _paths, _seen = score(local, plugin, name)
    return ok, why


def _reason(name, picked, is_default, snap, partly=None):
    reason = ("the default leaves the pages it touches the same" if is_default
              else "the first candidate whose pages are EQUAL or MARKUP-ONLY")
    if partly == "none":
        return "no candidate changes what a visitor sees on the pages it touches: the default stays"
    if partly:
        return "the fewest visible differences on the pages it touches (%d, the default has %d); the rest is not this setting's" % partly
    if name == "featuredFrom" and picked == "flags":
        n = sum(1 for f in portfolio_facts(snap).values() for fm in f["pieces"] if fm.get("featured", "").lower() in ("true", "yes"))
        reason = ("without `featuredFrom: flags` the home page loses its featured pieces (%d piece(s) flagged; `{{featured}}` "
                  "renders none)" % n)
    elif setting_family(name) == "sort" and picked == "order":
        reason = "every piece carries an integer `order`; without `sort: order` your pieces are sorted by date, then title"
    return reason


def choose(snap, data, evaluate, local, previous=None, no_local_reason=None, derive=None, names=None, derive_under=None):
    """Choose every setting. `snap` is the converted tree ({path: bytes}), `evaluate(settings)` the plugin output for a settings
    dict, `local` the old builder's output (or None), `previous` the plan's settings (a `chosen` row is kept as it is), `derive()`
    returns (look dict {"id","file"}, status {construct: status}) or raises when nothing can be derived. `derive_under(settings)` is
    the same for the converted tree under `settings` (the non-look settings): when it is given, a derived look is made again for
    every candidate (see the module docstring, THE LOOK FOLLOWS THE CANDIDATE) and `derive` is not used. Returns a `Chosen`.

    Passes repeat (at most `MAX_PASSES`) until no chosen value changes: each setting is judged with the others at their chosen values
    (see the module docstring, FIXED POINT). `Chosen.passes` says how many ran."""
    res = Chosen()
    previous = previous or {}
    names = list(names or setting_names(snap))
    chosen = dict((n, p["value"]) for n, p in previous.items() if p["how"] == "chosen" and n in names)
    fixed = dict(chosen)
    derived = {}                                    # the derive answers, by the non-look settings they were made under

    def derived_for(non_look, refine=True):
        """(look, status, error): the derived look for the converted tree under `non_look`, asked once per distinct set. A look made
        to SCORE a candidate is read once (`refine` False); the look the plan keeps, and the one `look` is judged on, is read up to four times (`look.derive_look`)."""
        key = json.dumps([sorted(non_look.items()), refine], default=repr) if derive_under is not None else ""
        if key not in derived:
            try:
                look, status = (derive_under(dict(non_look), refine) if derive_under is not None else derive())
                derived[key] = (look, status or {}, None)
            except Exception as e:      # noqa: BLE001 -- derive refuses with its own words; a refusal is a finding, not a crash
                derived[key] = (None, {}, str(e)[:120])
        return derived[key]

    def under(name, cand, others):
        """The settings a candidate is built with: the others, the candidate, and, when a derived look is in play, the look derived
        for exactly these."""
        st = dict(others, **{name: cand})
        if name != "look" and derive_under is not None and isinstance(others.get("look"), dict):
            non_look = dict((k, v) for k, v in st.items() if k != "look")
            look = derived_for(non_look, name in HOME_OPTIONS)[0]
            if look is not None:
                st["look"] = look
        return st

    def best_score(name, cand, others):
        """`score` of one candidate; a candidate with a DEPENDENT setting is scored under that setting's best value."""
        dep = partner(name, cand, snap) or (look_partner(name, cand) if isinstance(others.get("look"), dict) else None)
        if dep is None:
            return score(local, evaluate(under(name, cand, others)), name)
        out = None
        for v in candidates_for(dep, snap, data, local):
            st = dict(others, **{dep: v})
            r = score(local, evaluate(under(name, cand, st)), name)
            if out is None or (r[0], -r[2]) > (out[0], -out[2]):
                out = r
        return out

    last = {}
    default_looks = {}                              # the default look's count of visible differences, for the final reason
    for npass in range(1, MAX_PASSES + 1):
        res.rows, res.lines, res.passes = {}, [], npass
        picks, judged, cur = {}, 0, dict(fixed)         # `cur`: what the next setting is judged under (earlier picks of THIS pass included)
        for name in names:
            prev = previous.get(name)
            if prev and prev["how"] == "chosen":
                res.rows[name] = Row(name, prev["value"], "chosen", prev["reason"])
                continue
            if local is None:
                if name in NEEDS_LOCAL or len(candidates_for(name, snap, data)) > 1:
                    res.rows[name] = Row(name, None, "not measured", "not measured (%s)" % (no_local_reason or "no local build"))
                continue
            # the home's own options and the lone reference's grid are judged under every other setting, but no other setting is judged
            # under them: a `partOrder` that names `featured` made `featuredFrom` unmeasurable in the second pass (the builder of the home
            # options, F1), and so did `blocks.loneReferenceGrid` (the page that holds the lone reference changes what the look derive reads
            # of the home, which no setting of the home can answer for)
            others = dict((k, v) for k, v in cur.items() if k != name and (name in JUDGED_LAST or k not in JUDGED_LAST))
            cands = candidates_for(name, snap, data, local, others)
            if len(cands) < 2 and name != "look":
                continue
            judged += 1
            tried, picked, partly = [], None, None                       # tried: [(candidate, first difference, count, pages, seen)]
            for cand in cands:
                ok, why, n, pset, seen = best_score(name, cand, others)
                if ok:
                    picked = cand
                    break
                tried.append((cand, why, n, pset, seen))
            if picked is None and cands and len(tried) < len(cands):     # the absent candidate (None) itself was EQUAL
                res.rows[name] = Row(name, None, "measured", _reason(name, None, True, snap, None))
                cur.pop(name, None)
                continue
            if name == "look" and tried:
                default_looks[name] = tried[0][2]
            if picked is None and name == "look" and (derive is not None or derive_under is not None):
                look, status, err = derived_for(dict((k, v) for k, v in others.items() if k != "look"))
                res.look_status = status or {}
                if look is None:
                    tried.append(("derived", "could not derive: %s" % (err or "nothing to derive"), 10 ** 9, None, ()))
                else:
                    ok, why, n, pset, seen = score(local, evaluate(dict(others, look=look)), name)
                    if ok:
                        picked = look
                    else:
                        tried.append(("derived", why, n, pset, seen))
            if picked is None and len(tried) > 1 and name != "look" and len(set(t[4] for t in tried)) == 1:
                picked, partly = cands[0], "none"                  # every candidate leaves exactly the same differences: no effect
            written = portfolio_facts(snap).get(name.split(".", 1)[1], {}).get("view") if setting_family(name) == "view" else None
            if picked is None and len(tried) > 1 and written not in BUILT_IN_VIEWS:
                # only a candidate that builds the SAME PAGES as the default can win by count: a candidate that drops a page
                # (a view that replaces an index) has fewer differences by having fewer pages, not by being closer
                same_pages = [t for t in tried[1:] if t[3] is not None and t[3] == tried[0][3]]
                best = min(same_pages, key=lambda t: t[2]) if same_pages else tried[0]
                if best[2] < tried[0][2]:                                  # strictly fewer visible differences than the default
                    picked = (derived_for(dict((k, v) for k, v in others.items() if k != "look"))[0] if best[0] == "derived" else best[0])
                    partly = (best[2], tried[0][2])
            if picked is None:
                res.rows[name] = Row(name, None, "not measured",
                                     "no candidate leaves the pages it touches the same: " + "; ".join(
                                         "%s -> %s" % (c if isinstance(c, str) else json.dumps(c), w) for c, w, _n, _p, _s in tried),   # noqa
                                     [(c, w) for c, w, _n, _p, _s in tried])
                res.lines.append("you decide: %s -- %s" % (name, res.rows[name].reason))
                cur.pop(name, None)
                continue
            is_default = picked == cands[0] and not isinstance(picked, dict)
            res.rows[name] = Row(name, picked, "measured", _reason(name, picked, is_default, snap, partly))
            if partly and partly != "none":
                res.lines.append("partly: %s -- %s" % (name, res.rows[name].reason))
            if not is_default:
                picks[name] = picked                   # a default is no key: it needs no fixing for the others to be judged under it
                cur[name] = picked
            else:
                cur.pop(name, None)
        new = dict(chosen, **picks)
        if new == fixed or judged < 2:                 # nothing moved, or only one setting was judged: no interaction to re-judge
            break
        fixed = new
    # the look the plan keeps is the one derived under the settings finally chosen
    row = res.rows.get("look")
    if derive_under is not None and row is not None and row.how == "measured" and isinstance(row.value, dict):
        final = dict((k, r.value) for k, r in res.rows.items()
                     if k != "look" and r.how in ("measured", "chosen") and r.value is not None and r.value != DEFAULTS.get(k))
        look, status, _err = derived_for(final)
        if look is not None and look != row.value:
            _ok0, _w0, kept_n, _p0, _s0 = score(local, evaluate(dict(final, look=row.value)), "look")
            ok, _why, n, _pset, _seen = score(local, evaluate(dict(final, look=look)), "look")
            if n <= kept_n:
                default_n = score(local, evaluate(dict(final)), "look")[2]
                res.rows["look"] = Row("look", look, "measured", _reason("look", look, False, snap, None if ok else (n, default_n)))
                res.look_status = status or {}
    drop_lossy_look(res, local, evaluate)
    return res
