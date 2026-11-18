"""adoption.settings -- the measured settings, and writing one into the converted tree (design 8, "Measured settings").

Part of the `adoption` package behind the entry point `adopt.py`.

A conversion that chooses a value from a finite set is a SETTING. The plan holds each as `settings[<name>] = {value, how,
reason}` (plan schema 2, design 3.5); `converted_site_files(..., settings={name: value})` writes it into the tree, and
`adoption.choose` decides it by measurement. The names, in the order they are chosen (`SETTING_ORDER`, greedy: each
choice fixes the one before it; interactions beyond that are design UNDETERMINED U-4):

  look                the site's look: `site-studio` (the default, no key) or `derived` (a look file vendored at
                      `site/looks/derived.json`, derived from the old builder's own pages, R6)
  featuredFrom        `home` (the default) or `flags` (a piece's `featured: true` feeds the home page)
  sort.<portfolio>    `date` (the default) or `order` (every piece carries an integer `order`), in that portfolio's page.md
  nav.home            true (the default) or false: the nav without a Home item (`nav: {"home": false}`)
  resume.headings     `shift` (the default) or `as-written`
  cardLabels          true (the default) or false: card values without their labels
  resume.layout       `plain` (the default) or `cards`: the resume's roles as one card each (`resume.layout`, schema 4), for an old resume
                      page that sets each role in its own section
  workKeys            `work` (the default) or `all`: site.json's `work` object configures the portfolio named `work` ONLY, so an old site whose
                      one configuration (`meta`, `cardMeta`) applies to every portfolio needs those keys in each other portfolio's page.md
  cardNumber          false (the default) or true: a number on each card (P03: the piece's `order` and `year`), written into EVERY
                      portfolio's page.md (a page.md configures its own portfolio, and site.json's `work` the portfolio named `work` only)
  cardNumberFormat    `padded` (the default, `02 / 2025`), `plain` (`2 / 2025`) or `order` (`2`): what the number prints (schema 4)
  backLink            absent (the default) or one line of text: a link to the portfolio index above the piece title (P06), with the
                      text the old builder's own piece pages carry (`work.backLink`); the candidate is read from the local build
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

from adoption.base import Refused
from adoption.plan import _current_base, _plan_for, save_plan
from adoption.template import _yaml, entries, home_path, scalar, split_front

SETTING_ORDER = ("look", "featuredFrom", "sort", "nav.home", "resume.headings", "resume.layout", "workKeys", "cardLabels", "cardNumber", "cardNumberFormat",
                 "backLink", "menuLinks", "onePieceIndex", "blocks.headingLevel", "blocks.loneReferenceGrid", "blocks.videoEmbed", "titleForm", "introScope",
                 "partOrder", "view")
HOME_KEYS = ("titleForm", "introScope", "partOrder")       # the settings written into the home page's own front matter
PORTFOLIO_KEYS = ("cardNumber", "cardNumberFormat", "cardLabels", "backLink")     # the portfolio keys written into every page.md
SHARED_WORK_KEYS = ("meta", "cardMeta")                                          # the `work` keys `workKeys: all` copies
BACK_LINK_MAX = 60
_PER_PORTFOLIO = ("sort", "view", "menuLinks", "onePieceIndex")
_FM = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):")


def setting_family(name):
    """`sort.work` is of the family `sort`; `look` of `look`."""
    return name.split(".", 1)[0] if name.split(".", 1)[0] in _PER_PORTFOLIO else name


def setting_paths(name):
    """The output paths the setting can change: exact paths, prefixes ending in `/`, or `*` for every page. Never empty."""
    fam = setting_family(name)
    if fam in ("look", "nav.home"):
        return ["*"]
    if fam == "featuredFrom":
        return ["index.html"]
    if fam in ("resume.headings", "resume.layout"):
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


def apply_settings(view, files, d, settings, hints, notes, portfolios):
    """Lay the settings over the converted tree: `d` (site.json's dict) and `files` ({path: bytes}) are changed in place;
    `notes["settings"]` gains one line per setting applied."""
    for name in sorted(settings, key=lambda n: (SETTING_ORDER.index(setting_family(n)) if setting_family(n) in SETTING_ORDER else 99, n)):
        value, fam = settings[name], setting_family(name)
        if fam == "look":
            if isinstance(value, dict) and value.get("file"):
                files["site/looks/%s.json" % value.get("id", "derived")] = value["file"].encode("utf-8")
                d["look"] = "site/looks/%s.json" % value.get("id", "derived")
                notes["settings"].append("look: a look derived from your own pages, vendored at %s" % d["look"])
            continue
        if fam == "featuredFrom":
            if value != "home":
                d["featuredFrom"] = value
                notes["settings"].append("featuredFrom: %s" % value)
        elif name == "nav.home":
            if value is False:
                d["nav"] = {"home": False}
                notes["settings"].append("nav.home: false (no Home item in the nav)")
        elif name == "resume.headings":
            if value != "shift" and isinstance(d.get("resume"), dict):
                d["resume"]["headings"] = value
                notes["settings"].append("resume.headings: %s" % value)
        elif name == "resume.layout":
            if value != "plain" and isinstance(d.get("resume"), dict):
                d["resume"]["layout"] = value
                notes["settings"].append("resume.layout: %s" % value)
        elif name == "workKeys":
            if value == "all":
                work = d.get("work") or {}
                for key in SHARED_WORK_KEYS:
                    if work.get(key):
                        set_in_portfolios(view, files, key, "[%s]" % ", ".join(work[key]), only=[p for p in portfolios if p != "work"],
                                          missing_only=True)
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
        elif fam in HOME_KEYS:
            hp = home_path(view)                       # the converted home: a renamed one is read where the rename put it
            default = {"titleForm": "site", "introScope": "body", "partOrder": None}[fam]
            if hp and value not in (None, "", [], default):
                text = "[%s]" % ", ".join(value) if fam == "partOrder" else _front_value(value)
                files[hp] = _set_front_key(_page_text(view, files, hp), fam, text).encode("utf-8")
                notes["settings"].append("%s: %s" % (fam, ", ".join(value) if fam == "partOrder" else value))
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
            if (fam == "menuLinks" and value == "index") or (fam == "onePieceIndex" and value == "redirect"):
                continue                     # the default writes no key
            port = name.split(".", 1)[1]
            path = "content/%s/page.md" % port
            if not view.exists(path):
                continue
            cur = _page_text(view, files, path)
            files[path] = _set_front_key(cur, fam, value).encode("utf-8")
            notes["settings"].append("%s of %s: %s" % (fam, port, value))


_BOOL = {"true": True, "false": False}
_CHOICES = {"featuredFrom": ("home", "flags"), "sort": ("date", "order"), "resume.headings": ("shift", "as-written"),
            "resume.layout": ("plain", "cards"),
            "view": ("grid", "page", "roles", "map", "showcase"), "look": ("site-studio",), "menuLinks": ("index", "single-piece"),
            "workKeys": ("work", "all"), "cardNumberFormat": ("padded", "plain", "order"), "onePieceIndex": ("redirect", "listing"),
            "titleForm": ("site", "page"), "introScope": ("body", "first-block"), "blocks.videoEmbed": ("facade", "live")}
_BOOLEAN = ("nav.home", "cardLabels", "cardNumber", "blocks.loneReferenceGrid")


def parse_chosen(name, text):
    """The value for `adopt.py setting NAME TEXT`, or Refused naming what the setting takes. `look` takes only the default
    (a derived look is measured, never chosen: it is a file adopt writes); `backLink` takes one line of text."""
    fam = setting_family(name)
    portfolio_form = "." in name and name.split(".", 1)[0] in _PER_PORTFOLIO
    if fam not in SETTING_ORDER or (fam in _PER_PORTFOLIO) != portfolio_form:
        raise Refused("%s is not a setting adopt measures; the settings are %s (sort and view take a portfolio: `sort.work`); "
                      "pass one of those names" % (name, ", ".join(SETTING_ORDER)))
    if name in _BOOLEAN:
        if text not in _BOOL:
            raise Refused("%s takes true or false; pass one of those" % name)
        return _BOOL[text]
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
    if text not in _CHOICES[fam]:
        raise Refused("%s takes one of: %s" % (name, ", ".join(_CHOICES[fam])))
    return text


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
        return "adopt: %s is measured again at the next `adopt.py parity`" % name
    value = parse_chosen(name, text)
    plan["settings"][name] = {"value": value, "how": "chosen", "reason": "chosen with `adopt.py setting`"}
    save_plan(repo, plan)
    return "adopt: %s = %s (chosen: `adopt.py parity` keeps it and does not measure it)" % (name, json.dumps(value))
