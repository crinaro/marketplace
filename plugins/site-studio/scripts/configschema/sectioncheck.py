"""sectioncheck: the checks of the small `site.json` sections: `nav`, `blocks`, `look`, `redirects` and
`budgets`. Each reads one raw value and reports into a collector."""

import re
from configschema.configkeys import (
    BLOCKS_KEYS,
    BLOCK_HEADING_LEVELS,
    BUDGET_DEFAULTS,
    NAV_KEYS,
    VIDEO_EMBED_FORMS,
    _LOOK_RE,
)
from configschema.diagnostics import SiteConfigError
from configschema.valuecheck import _bad, _bool, _number, _rel_path, _shown, _str


def _nav_check(raw, col):
    """`nav` (schema 4): an object whose only key is `home`, a boolean. `{}` and `{"home": true}` are the default
    and normalise to `{}`; `{"home": false}` is the one setting."""
    if not isinstance(raw, dict):
        col.run(_bad, "nav", "an object", raw)
        return {}
    out = {}
    for k in raw:
        if k not in NAV_KEYS:
            col.add("site.json: unknown key 'nav.%s'" % k, "nav.%s" % k, "unknown key",
                    "one of: " + ", ".join(NAV_KEYS), "remove 'nav.%s'" % k)
    if "home" in raw:
        ok, val = col.run(_bool, raw["home"], "nav.home")
        if ok and val is False:
            out["home"] = False
    return out


def _blocks_check(raw, col):
    """`blocks` (schema 4): an object whose keys are `headingLevel` and `loneReferenceGrid`. `headingLevel` is a whole number from 2 to 6: the h-level a
    heading INSIDE a plugin block prints at, the way the person's old page printed it (today only `:::carousel`
    slides hold headings: tiles, quote, quotes, gallery and videos hold none). The number is the level a `###`
    (the heading that opens a slide) prints at; a deeper heading keeps its distance from it. ABSENT is the
    default, and means a block's headings follow the page (one deeper than written, or the resume's own
    `headings`); every number, 4 included, is a setting, so a `4` is kept and a site that writes it gets h4.
    `loneReferenceGrid` is a boolean: true prints a LONE `ref:` line inside `<div class="ref-grid">`, the way two or more
    print, because a site built elsewhere wrapped one (a grid track bounds a card's width, which a visitor sees); false,
    the default, is today's bare card, so it is accepted at 4 and normalised away, like `nav.home: true`.
    `videoEmbed` is "facade" or "live" (template-fidelity 0.4.0, the owner's video ruling, 2026-11-18). "facade", the
    default, is the privacy form the plugin has always written: a Vimeo address carries `dnt=1`. "live" keeps the
    player's own address with nothing added, the form a site built elsewhere put in its pages (`player.vimeo.com/video/ID`),
    so a look that places the player in `videos.item` can match those pages. Only the ADDRESS changes: whether a player
    loads with the page or after a click is the look's markup (decision 34). "facade" is accepted at 4 and normalised
    away; any other value is refused, naming the two."""
    if not isinstance(raw, dict):
        col.run(_bad, "blocks", "an object", raw)
        return {}
    out = {}
    for k in raw:
        if k not in BLOCKS_KEYS:
            col.add("site.json: unknown key 'blocks.%s'" % k, "blocks.%s" % k, "unknown key",
                    "one of: " + ", ".join(BLOCKS_KEYS), "remove 'blocks.%s'" % k)
    if "headingLevel" in raw:
        v = raw["headingLevel"]
        if type(v) is not int or v not in BLOCK_HEADING_LEVELS:        # a bool is an int, and 3.0 equals 3: neither is one
            col.add("site.json: 'blocks.headingLevel' must be a whole number from 2 to 6", "blocks.headingLevel",
                    _shown(repr(v)), "a whole number from 2 to 6",
                    "set blocks.headingLevel to the h-level the old page's block headings had, 2 to 6")
        else:
            out["headingLevel"] = v
    if "loneReferenceGrid" in raw:
        ok, val = col.run(_bool, raw["loneReferenceGrid"], "blocks.loneReferenceGrid")
        if ok and val is True:
            out["loneReferenceGrid"] = True
    if "videoEmbed" in raw:
        v = raw["videoEmbed"]
        if type(v) is not str or v not in VIDEO_EMBED_FORMS:
            col.add("site.json: 'blocks.videoEmbed' must be \"facade\" or \"live\"", "blocks.videoEmbed",
                    _shown(repr(v)), "\"facade\" or \"live\"",
                    "set blocks.videoEmbed to \"live\" to keep the player's own address, or remove it for the click-to-load default")
        elif v == "live":
            out["videoEmbed"] = "live"
    return out


def _look(v):
    """`look` (schema 4): the vendored look file, `site/looks/<name>.json`, `<name>` a slug. That the file exists
    at HEAD is the build's check (design section R5.2); this is the shape."""
    v = _str(v, "look")
    if not _LOOK_RE.match(v):
        raise SiteConfigError("site.json: 'look' must be a path such as site/looks/<name>.json, <name> lower-case "
                              "letters, digits and hyphens", path="look", found=v,
                              expected="site/looks/<name>.json",
                              fix="point look at a file under site/looks/, or remove it for the default look")
    return v


def _redirect_entry(old, new):
    _rel_path(old, "redirects key '%s'" % old)
    new = _str(new, "redirects['%s']" % old)
    if not re.match(r"^https?://", new):
        _rel_path(new, "redirects['%s']" % old)
    if new.strip("/") == old.strip("/"):
        raise SiteConfigError("site.json: redirect '%s' points at itself" % old, path="redirects['%s']" % old,
                              found=new, expected="another page", fix="point the redirect somewhere else")
    return new


def _redirects_check(raw, col):
    if not isinstance(raw, dict):
        col.run(_bad, "redirects", "an object", raw)
        return {}
    out = {}
    for old, new in raw.items():
        ok, val = col.run(_redirect_entry, old, new)
        if ok:
            out[old] = val
    return out


def _budgets_check(raw, col):
    if not isinstance(raw, dict):
        col.run(_bad, "budgets", "an object", raw)
        return {}
    out = {}
    for k, v in raw.items():
        if k not in BUDGET_DEFAULTS:
            col.add("site.json: unknown key 'budgets.%s'" % k, "budgets.%s" % k, "unknown key",
                    "one of: " + ", ".join(sorted(BUDGET_DEFAULTS)), "remove 'budgets.%s'" % k)
            continue
        ok, val = col.run(_number, v, "budgets." + k)
        if ok:
            out[k] = val
    return out
