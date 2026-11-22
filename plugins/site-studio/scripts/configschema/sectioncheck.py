"""sectioncheck: the checks of the small `site.json` sections: `nav`, `blocks`, `look`, `redirects` and
`budgets`, and the schema-6 top-level keys (`featuredView`, `titleSeparator`, `mediaPaths`, `sizeCopies`, `carried`;
design-adopt-parity-2 section 3.2). Each reads one raw value and reports into a collector."""

import re
import unicodedata
from configschema.configkeys import (
    BLOCKS_KEYS,
    BLOCK_HEADING_LEVELS,
    BUDGET_DEFAULTS,
    CARRIED_MAX,
    CARRIED_RESERVED,
    CARRIED_RESERVED_DIRS,
    FEATURED_VIEWS,
    GATE_FORBIDDEN_DIRS,
    GATE_FORBIDDEN_NAMES,
    GATE_JUNK_NAMES,
    GATE_JUNK_SUFFIXES,
    MEDIA_PATH_FOLDERS,
    MEDIA_PATH_SEGMENTS,
    NAV_EXTRA_MAX,
    NAV_EXTRA_SCHEMES,
    NAV_HOME_TITLE,
    NAV_KEYS,
    RESUME_HEADINGS,
    SCHEMA_MAX,
    SIZE_COPIES,
    TITLE_SEPARATOR_DEFAULT,
    TITLE_SEPARATOR_MAX,
    V6_NAV_KEYS,
    VIDEO_EMBED_FORMS,
    _LOOK_RE,
)
from configschema.diagnostics import SiteConfigError
from configschema.valuecheck import _bad, _bool, _number, _one_line, _rel_path, _shown, _str


def needs_schema_6(where, have):
    """A schema-6 key or value under a lower declared schema: 0.5.x refuses it (an unknown key, or a value it does not
    take), and 0.6.0 refuses it naming the schema (design-adopt-parity-2 section 3.1 rule 1)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 6" % where, path=where,
                           found="schema %d" % have, expected="schema 6",
                           fix="run `python3 build.py raise-schema --to 6`, which lists what the page changes before "
                               "it writes schema 6")


def _nav_check(raw, col, schema=SCHEMA_MAX):
    """`nav` (schema 4): an object whose key is `home`, a boolean. `{}` and `{"home": true}` are the default and
    normalise to `{}`; `{"home": false}` is the one schema-4 setting. Schema 6 adds `home: "title"` (the first item's
    text is the site title) and `extra` (`_nav_extra`); below 6 each is refused naming the schema."""
    if not isinstance(raw, dict):
        col.run(_bad, "nav", "an object", raw)
        return {}
    out = {}
    for k in raw:
        if k not in NAV_KEYS:
            col.add("site.json: unknown key 'nav.%s'" % k, "nav.%s" % k, "unknown key",
                    "one of: " + ", ".join(NAV_KEYS), "remove 'nav.%s'" % k)
        elif k in V6_NAV_KEYS and schema < 6:
            col.problems.append(needs_schema_6("nav.%s" % k, schema).problem)
    if "home" in raw:
        if raw["home"] == NAV_HOME_TITLE:
            if schema < 6:
                col.problems.append(needs_schema_6("nav.home", schema).problem)
            else:
                out["home"] = NAV_HOME_TITLE
        else:
            ok, val = col.run(_bool, raw["home"], "nav.home")
            if ok and val is False:
                out["home"] = False
    if "extra" in raw and schema >= 6:
        items = _nav_extra(raw["extra"], col)
        if items:
            out["extra"] = items
    return out


def _nav_extra_url(url, where):
    """One `nav.extra` address: what `contentmodel.links.check_href` accepts, narrowed to an absolute `https:` or
    `mailto:` address. `http:` is refused because the site gate refuses an `http://` link on any page, and a relative or
    `#anchor` address because the menu prints on pages at every depth (a page of the site belongs in the menu by its own
    key). The narrowing is read on the raw text with no space or control character anywhere in it, so the scheme read
    is the one a browser reads (`links.url_as_browser_reads` strips and removes only those), and every address it accepts
    `check_href` accepts too; `configschema` may not import `contentmodel` (G6), so `test_sectioncheck` holds that."""
    url = _one_line(url, where)
    low = url.lower()
    if any(ord(c) <= 0x20 or ord(c) == 0x7f for c in url) or not any(
            low.startswith(s) and len(low) > len(s) for s in NAV_EXTRA_SCHEMES):
        raise SiteConfigError("site.json: '%s' must be an absolute https: or mailto: address" % where, path=where,
                              found=url, expected="an https: or mailto: address",
                              fix="write the address in full, such as https://www.example.test/, or mailto: and "
                                  "an address; a page of this site belongs in the menu by its own key")
    return url


def _nav_extra(raw, col):
    """`nav.extra` (schema 6): one to four `{"label", "url"}` objects, printed after the built-in items in order. Returns
    the good items; every fault is recorded in `col`."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= NAV_EXTRA_MAX:
        col.add("site.json: 'nav.extra' must be a list of one to %d items" % NAV_EXTRA_MAX, "nav.extra",
                _shown(repr(raw)) if isinstance(raw, list) else "not a list",
                "one to %d {\"label\", \"url\"} items" % NAV_EXTRA_MAX,
                "write nav.extra as a list such as [{\"label\": \"Shop\", \"url\": \"https://www.example.test/\"}]")
        return []
    out = []
    for i, item in enumerate(raw):
        at = "nav.extra[%d]" % i
        if not isinstance(item, dict) or set(item) != {"label", "url"}:
            col.add("site.json: '%s' must be an object with exactly \"label\" and \"url\"" % at, at,
                    _shown(repr(item)), "{\"label\": ..., \"url\": ...}", "give %s a label and a url, and nothing else" % at)
            continue
        ok_l, label = col.run(_one_line, item["label"], at + ".label")
        ok_u, url = col.run(_nav_extra_url, item["url"], at + ".url")
        if ok_l and ok_u:
            out.append({"label": label, "url": url})
    return out


def _blocks_check(raw, col, schema=SCHEMA_MAX):
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
    if "headings" in raw:
        # Schema 6 (design-adopt-parity-2 section 4.5): the resume's two values, for every Markdown body but the resume's.
        v = raw["headings"]
        if schema < 6:
            col.problems.append(needs_schema_6("blocks.headings", schema).problem)
        elif type(v) is not str or v not in RESUME_HEADINGS:
            names = " or ".join('"%s"' % a for a in RESUME_HEADINGS)
            col.add("site.json: 'blocks.headings' must be %s" % names, "blocks.headings", _shown(repr(v)), names,
                    "set blocks.headings to \"as-written\" to print a body's headings at the level written, or remove it")
        elif v != RESUME_HEADINGS[0]:
            out["headings"] = v
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


# ---------------------------------------------------------------- the schema-6 top-level keys (design-adopt-parity-2 3.2)

def _title_separator(v):
    """`titleSeparator`: one to three characters, each a punctuation mark or a symbol (Unicode general category `P*` or
    `S*`), with at most one space on each side. No closed list: the value is HTML-escaped where it is printed, as a
    page's title is. A letter, a digit or a control character is refused, because a separator made of one reads as part
    of a title."""
    if not isinstance(v, str):
        _bad("titleSeparator", "text", v)
    core = v[1:] if v.startswith(" ") else v
    core = core[:-1] if core.endswith(" ") else core
    if not (1 <= len(core) <= TITLE_SEPARATOR_MAX and all(unicodedata.category(c)[0] in "PS" for c in core)):
        raise SiteConfigError("site.json: 'titleSeparator' must be one to %d punctuation marks or symbols, with at most "
                              "one space on each side" % TITLE_SEPARATOR_MAX, path="titleSeparator",
                              found=_shown(repr(v)), expected="such as \" | \", \" · \" or \" » \"",
                              fix="write a separator of punctuation or symbols, such as \" · \", or remove "
                                  "titleSeparator for the default \" | \"")
    return v


_SLUG_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _media_pattern(v, where, folder):
    """One `mediaPaths` pattern (design-adopt-parity-2 section 4.6): two to four `/`-separated segments, each a slug
    (`[a-z0-9][a-z0-9-]*`) or `{name}`, the last `{file}`; `references` holds `{name}` once, `home` and `about` none."""
    v = _str(v, where)
    segs = v.split("/")
    lo, hi = MEDIA_PATH_SEGMENTS
    good = (lo <= len(segs) <= hi and segs[-1] == "{file}"
            and all(_SLUG_SEGMENT.match(x) or x == "{name}" for x in segs[:-1]))
    names = segs.count("{name}")
    if good and (names != 1 if folder == "references" else names != 0):
        good = False
    if not good:
        want = ("refs/{name}/{file}" if folder == "references" else "media/{file}")
        raise SiteConfigError("site.json: '%s' must be %d to %d segments, each a lower-case name%s, the last {file}"
                              % (where, lo, hi, " or {name} (once)" if folder == "references" else ""), path=where,
                              found=_shown(v), expected="a pattern such as %s" % want,
                              fix="write %s as a pattern such as %s" % (where, want))
    return v


def _media_paths_check(raw, col):
    """`mediaPaths` (schema 6): an object with any of `references`, `home`, `about`, each a pattern. `{}` normalises away."""
    if not isinstance(raw, dict):
        col.run(_bad, "mediaPaths", "an object", raw)
        return {}
    out = {}
    for k, v in raw.items():
        if k not in MEDIA_PATH_FOLDERS:
            col.add("site.json: unknown key 'mediaPaths.%s'" % k, "mediaPaths.%s" % k, "unknown key",
                    "one of: " + ", ".join(MEDIA_PATH_FOLDERS), "remove 'mediaPaths.%s'" % k)
            continue
        ok, val = col.run(_media_pattern, v, "mediaPaths.%s" % k, k)
        if ok:
            out[k] = val
    return out


def _carried_path(v, where):
    """One `carried` output path: a relative path inside the published tree that is not a file the build owns for
    deployment (`CNAME`, `.nojekyll`, `robots.txt`, `sitemap.xml`), not under `site-studio/`, and not a name the site
    gate never publishes (its tables, copied into `configkeys` as `GATE_*`: a forbidden name or folder, a junk name or
    suffix)."""
    v = _rel_path(v, where)
    parts = v.split("/")
    name = parts[-1]
    why = None
    if v in CARRIED_RESERVED:
        why = "the build writes %s for deployment" % v
    elif parts[0] in CARRIED_RESERVED_DIRS:
        why = "site-studio/ holds the plugin's own files"
    elif any(p in GATE_FORBIDDEN_DIRS for p in parts[:-1]) or name in GATE_FORBIDDEN_NAMES:
        why = "the site gate never publishes that name"
    elif name in GATE_JUNK_NAMES or name.endswith(GATE_JUNK_SUFFIXES) or name.startswith("._"):
        why = "the site gate refuses that name as junk"
    if why:
        raise SiteConfigError("site.json: '%s' names %s, which is never carried: %s" % (where, v, why), path=where,
                              found=v, expected="an output path the site may publish",
                              fix="remove %s from carried; site-studio writes or refuses that path itself" % v)
    return v


def _carried_check(raw, col):
    """`carried` (schema 6): one to `CARRIED_MAX` output paths, each once, each served from `site/carried/<path>`."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= CARRIED_MAX:
        col.add("site.json: 'carried' must be a list of one to %d output paths" % CARRIED_MAX, "carried",
                "%d item(s)" % len(raw) if isinstance(raw, list) else "not a list",
                "one to %d paths" % CARRIED_MAX, "write carried as a list such as [\"404.html\"], or remove it")
        return []
    out = []
    for i, item in enumerate(raw):
        ok, val = col.run(_carried_path, item, "carried[%d]" % i)
        if not ok:
            continue
        if val in out:
            col.add("site.json: 'carried' names %s twice" % val, "carried[%d]" % i, val, "each path once",
                    "remove the repeated %s" % val)
            continue
        out.append(val)
    return out


def _one_of(v, where, allowed):
    if type(v) is not str or v not in allowed:
        names = " or ".join('"%s"' % a for a in allowed)
        raise SiteConfigError("site.json: '%s' must be %s" % (where, names), path=where, found=_shown(repr(v)),
                              expected=names, fix="set %s to %s, or remove it" % (where, names))
    return v


def v6_top_check(data, col):
    """The schema-6 top-level keys of a decoded `site.json` (the caller has refused them below 6), as {key: value} of
    those that are not their default: `featuredView` ("flat" is written away), `titleSeparator` (" | " is written
    away), `mediaPaths`, `sizeCopies` and `carried`. Every fault is recorded in `col`."""
    out = {}
    if "featuredView" in data:
        ok, v = col.run(_one_of, data["featuredView"], "featuredView", FEATURED_VIEWS)
        if ok and v != FEATURED_VIEWS[0]:
            out["featuredView"] = v
    if "titleSeparator" in data:
        ok, v = col.run(_title_separator, data["titleSeparator"])
        if ok and v != TITLE_SEPARATOR_DEFAULT:
            out["titleSeparator"] = v
    if "mediaPaths" in data:
        v = _media_paths_check(data["mediaPaths"], col)
        if v:
            out["mediaPaths"] = v
    if "sizeCopies" in data:
        ok, v = col.run(_one_of, data["sizeCopies"], "sizeCopies", SIZE_COPIES)
        if ok:
            out["sizeCopies"] = v
    if "carried" in data:
        v = _carried_check(data["carried"], col)
        if v:
            out["carried"] = v
    return out
