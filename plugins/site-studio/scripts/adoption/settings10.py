"""adoption.settings10 -- the three settings site-studio 0.10.0 adds: `images.sizes`, `sitemap` and `blankMeta.<portfolio>` (design-publish-preflight sections 3.3, 6 and 7; group
`publish-preflight`; dev 1068). Part of the `adoption` package behind the entry point `adopt.py`; `settings.py` was 728 of 800 lines, so the writers live here. A LEAF: it imports
nothing of `settings`, `candidates`, `choose` or `measure` (those call it), and takes the choose `Row` class as an argument.

  images.sizes    `as-written` (default for a site whose old pages carry pictures with no width or height and whose converted build still does) or `held`. `as-written` changes no
                  byte of any page: the gate stops asking for sizes on the whole site. It is READ from the old pages, written by `for_parity` as a `how: measured` row whose reason
                  says it was read. `held` is ONLY ever chosen (`adopt.py setting images.sizes held`): `look_for` then completes the derived look's picture parts
                  (`lookfiles.heldsizes`) as the setting is written, BEFORE `lookwrite.carry`, so the stamp covers the completed text. A person's own look (`local.json`) is never edited, and no hand page gains an attribute (the visitor
                  invariant): the gate's `media` family relieves every picture without `data-ss-held` under `held` too and counts them in one note per page (review R4).
  sitemap         `indexable` (the build leaves a noindex or redirect page out of `sitemap.xml`; `sitechecks.page.search_out` is the one rule), written when the converted tree has such
                  a page and the OLD output's own `sitemap.xml` lists none of them, or there is none. Parity ignores `sitemap.xml`, so the reason says "read from your old sitemap",
                  never "measured". `adopt.py setting sitemap none` declines.
  blankMeta.<p>   `omit` (a front matter line with no value prints no row and no card separator): offered per portfolio where a piece holds a blank key the portfolio lists, and
                  judged like any setting by the one measurement. Written into the portfolio's page.md by the generic per-portfolio branch of `settings.apply_settings`.

What this does NOT measure, said so it is never read as sure: whether a picture's layout shifts while it loads, and whether a browser older than about 2022 meets the plain way
(`COST_LINE`); `img_attrs` stay ignored by parity (changing that would make every adopted site's record stale), so `blind_spot` says it when a person's own look adds sizes.
"""

import json
import re
from urllib.parse import urlsplit

from building.readsources import blank
from contentmodel.errors import ContentError
from contentmodel.frontmatter import parse_front_matter
from lookfiles import heldsizes
from sitechecks.page import parse_page, search_out

from adoption.base import Refused

IMAGES = "images.sizes"
SITEMAP = "sitemap"
BLANK = "blankMeta"
SITE_NAMES = (IMAGES, SITEMAP)
PORTFOLIO_FAMILIES = (BLANK,)
NAMES = SITE_NAMES + (BLANK + ".<portfolio>",)
IMAGE_VALUES = ("as-written", "held")
LOCAL_LOOK = "site/looks/local.json"
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)
_PIECE = re.compile(r"^content/([^/]+)/([^/]+)/index\.md$")

AS_WRITTEN_REASON = ("your pages' pictures carry no sizes; they stay as they are. `adopt.py setting images.sizes held` adds them: what that costs "
                     "is in the line below")
COST_LINE = ("images.sizes: as-written leaves pages shifting while their pictures load, as they did, and a picture added later without a size is counted in a note, not refused. "
             "`held` adds the sizes to generated pages with one more file (site-studio/held.css) that keeps the layout, while pictures in your hand-written pages stay as they are and are counted in a note; a visitor whose browser is older than about 2022 "
             "(an old iPhone is the likely case), or for whom that file does not load, gets the plain way; parity shows the added file and you accept it after seeing the pictures "
             "(`adopt.py parity --keep`); a privacy review will be needed, with the `apply` after it on the same UTC day")
BLIND_SPOT = "parity does not see image sizes: look at the pictures (`adopt.py parity --keep`)"


def is_v10(name):
    """True for a setting this module owns: `images.sizes`, `sitemap`, `blankMeta.<portfolio>`."""
    return name in SITE_NAMES or (isinstance(name, str) and name.startswith(BLANK + "."))


def parse_chosen(name, text):
    """The value for `adopt.py setting NAME TEXT` of one of these, or Refused naming what it takes. `sitemap none` and `blankMeta.<p> false` are the absent key (None)."""
    if name == IMAGES:
        if text not in IMAGE_VALUES:
            raise Refused("%s takes one of: %s (`held` adds the sizes the old pages did not have; `as-written` leaves the pictures as they were)" % (name, ", ".join(IMAGE_VALUES)))
        return text
    if name == SITEMAP:
        if text not in ("indexable", "none"):
            raise Refused("sitemap takes `indexable` (a noindex or redirect page is left out of sitemap.xml) or `none` (the sitemap lists them, as before)")
        return None if text == "none" else text
    if name.partition(".")[2] == "":
        raise Refused("%s names no portfolio: use `blankMeta.work`, with the portfolio's folder name after the dot" % name)
    if text not in ("omit", "false"):
        raise Refused("%s takes omit (a blank value prints no row) or false (it prints an empty row, as before)" % name)
    return None if text == "false" else "omit"


def chosen_lines(name, value):
    """What `adopt.py setting NAME VALUE` adds to its one line: for `images.sizes held`, what it costs, said at the moment it is chosen."""
    return [COST_LINE] if name == IMAGES and value == "held" else []


def look_for(settings):
    """The `look` setting's value as `lookwrite.carry` is to write it: under `images.sizes: held` the DERIVED look with its picture parts completed
    (`heldsizes.complete`), else the value as it is. Never a look the person wrote: `local.json` is not a setting's value and is never passed here."""
    look = settings.get("look")
    if settings.get(IMAGES) != "held" or not (isinstance(look, dict) and look.get("file")):
        return look
    text, changed = heldsizes.complete(look["file"])
    return dict(look, file=text) if changed else look


def apply_site(d, settings, name, value, notes):
    """Write one site-level setting into site.json's dict `d` and say so in `notes["settings"]`; True when `name` is one of `SITE_NAMES` (a None value writes nothing)."""
    if name == IMAGES:
        if value in IMAGE_VALUES:
            d["images"] = dict(d.get("images") or {}, sizes=value)
            if value == "held":
                look = settings.get("look")
                changed = heldsizes.complete(look.get("file") or "")[1] if isinstance(look, dict) else []
                notes["settings"].append("images.sizes: held (%s)" % (
                    "the derived look's %s gain width and height, and a page that prints one links site-studio/held.css" % ", ".join("%s.%s" % c for c in changed)
                    if changed else "no derived look part needed sizes: the plugin's own pictures carry them, and a look you wrote is never edited"))
            else:
                notes["settings"].append("images.sizes: as-written (%s)" % AS_WRITTEN_REASON)
            notes["settings"].append(COST_LINE)
        return True
    if name == SITEMAP:
        if value == "indexable":
            d["sitemap"] = "indexable"
            notes["settings"].append("sitemap: indexable (a noindex or redirect page is left out of sitemap.xml; read from your old sitemap, which parity cannot compare)")
        return True
    return False


# -- blankMeta.<p>: offered where a piece holds a blank key the portfolio lists ----------------------------------------------------------
def blank_candidates(port, snap, listed):
    """`[None, "omit"]` when a piece of portfolio `port` holds a blank value (`building.readsources.blank`: nothing, spaces, an empty list; `false` and `0` are values) for a key of `listed`, else `[None]`.
    `snap` is {path: bytes}; a piece the front matter parser refuses is skipped (the build refuses it and names it)."""
    listed = set(listed or ())
    for path in sorted(snap):
        m = _PIECE.match(path)
        if not (m and m.group(1) == port and not m.group(2).startswith("_")):
            continue
        try:
            meta = parse_front_matter(snap[path].decode("utf-8", "replace"), path)[0]
        except ContentError:
            continue
        if any(k in meta and blank(meta[k]) for k in listed):
            return [None, "omit"]
    return [None]


# -- images.sizes and sitemap: read from the old build, never measured ----------------------------------------------------------------
def _html(files):
    return sorted((p, b) for p, b in (files or {}).items() if p.lower().endswith((".html", ".htm")))


def unsized_pages(files, skip=(), local_only=False):
    """[path] of the HTML pages of `files` ({path: bytes}) with an `<img>` that has no `width` or no `height`; `skip` pages are left out (a carried page is the person's own bytes);
    `local_only` ignores a picture whose address is another site's (`http:`, `//`, `data:`)."""
    out = []
    for path, blob in _html(files):
        if path in skip:
            continue
        imgs = parse_page(path, blob.decode("utf-8", "replace")).imgs
        if any((im["width"] is None or im["height"] is None) and im["src"] and not (local_only and _EXTERNAL.match(im["src"])) for im in imgs):
            out.append(path)
    return out


def out_of_search(files):
    """{path: "noindex" or "refresh"}: the pages of `files` that tell search to leave them out (`sitechecks.page.search_out`, the build's and the gate's one rule)."""
    return dict((p, w) for p, b in _html(files) for w in [search_out(parse_page(p, b.decode("utf-8", "replace")))] if w)


def _forms(path):
    """The addresses a page may be listed under, without a leading slash: the file, and its folder with and without the trailing slash."""
    if path == "index.html":
        return {"", "index.html"}
    if path.endswith("/index.html"):
        folder = path[:-len("index.html")]
        return {path, folder, folder.rstrip("/")}
    return {path}


def listed_in(sitemap, pages):
    """The `pages` the sitemap text lists (`<loc>` addresses read with their path only; a prefix such as `/repo/` before the page is allowed)."""
    locs = [urlsplit(l.strip()).path.lstrip("/") for l in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", sitemap or "")]
    hit = []
    for p in pages:
        forms = _forms(p)
        if any(loc in forms or any(f and loc.endswith("/" + f) for f in forms) for loc in locs):
            hit.append(p)
    return hit


def blind_spot(files, old_unsized):
    """BLIND_SPOT when a look the person wrote (`site/looks/local.json` in `files`) has a picture part that carries sizes while `old_unsized` old pages had pictures with none, else None."""
    try:
        look = json.loads((files or {}).get(LOCAL_LOOK, b"").decode("utf-8")) if LOCAL_LOOK in (files or {}) else None
    except ValueError:
        return None
    constructs = look.get("constructs") if isinstance(look, dict) else None
    if not old_unsized or not isinstance(constructs, dict):
        return None
    for cid, part in heldsizes.picture_parts():
        markup = (constructs.get(cid) or {}).get(part)
        if isinstance(markup, str) and "<img" in markup.lower() and not heldsizes.wants_sizes(markup):
            return BLIND_SPOT
    return None


def for_parity(picked, row_type, local, snapshot, evaluate, previous):
    """Add the `images.sizes` and `sitemap` rows `parity` reads from the old build (`measure._choose_settings`, after the settings pass): rows are added to `picked.rows`, lines to `picked.lines`.
    A row the person CHOSE (`previous`, how `chosen`) is kept by the plan and never read over. With no old build nothing is read. The converted build is asked once, with the settings
    `picked` ended on."""
    if local is None:
        return
    mine = previous or {}
    final = picked.values()
    out = None
    old_bare = unsized_pages(local)
    if (mine.get(IMAGES) or {}).get("how") != "chosen" and old_bare:
        out = evaluate(final)
        new_bare = unsized_pages(out, skip=set(final.get("carried") or ()), local_only=True)
        if new_bare:
            picked.rows[IMAGES] = row_type(IMAGES, "as-written", "measured",
                                           "%s (read from your old pages: %d old page(s) have a picture with no width or height, and %d page(s) of the converted site still do)"
                                           % (AS_WRITTEN_REASON, len(old_bare), len(new_bare)))
            picked.lines.append(COST_LINE)
    if (mine.get(SITEMAP) or {}).get("how") != "chosen":
        out = out if out is not None else evaluate(final)
        away = out_of_search(out)
        if away:
            was = (local or {}).get("sitemap.xml")
            hit = listed_in(was.decode("utf-8", "replace"), sorted(away)) if was is not None else []
            first = sorted(away)[0]
            if hit:
                picked.lines.append("sitemap: left as it was: your old sitemap lists %d of the %d page(s) the converted site tells search to leave out (first: %s); "
                                    "`adopt.py setting sitemap indexable` leaves them out of the new one" % (len(hit), len(away), hit[0]))
            else:
                picked.rows[SITEMAP] = row_type(SITEMAP, "indexable", "measured",
                                                "read from your old sitemap, which parity cannot compare: %s; %d page(s) of the converted site tell search to leave them out "
                                                "(first: %s), so the new sitemap does not list them" % (
                                                    "it lists none of them" if was is not None else "your old build wrote no sitemap.xml", len(away), first))
    note = blind_spot(snapshot(final), len(old_bare)) if old_bare else None
    if note:
        picked.lines.append(note)
