"""sectioncheck: the checks of the small `site.json` sections: `nav`, `blocks`, `look`, `redirects` and
`budgets`, the schema-6 top-level keys (`featuredView`, `titleSeparator`, `mediaPaths`, `sizeCopies`, `carried`;
design-adopt-parity-2 section 3.2) and the schema-7 key `lookLocal` (design-adopt-ownership-line section 2.1). Each
reads one raw value and reports into a collector."""

import math
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
    IMAGES_KEYS,
    IMAGES_SIZES,
    LOOK_LOCAL_PATH,
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
    NAV_LABEL_KEYS,
    REFERENCES_KEYS,
    REFERENCE_UNPRINTED_KEYS,
    REFERENCE_WORD_MAX,
    REFERENCE_WORDS_MAX,
    RESUME_HEADINGS,
    SCHEMA_MAX,
    SITEMAP_VALUES,
    SIZE_COPIES,
    TITLE_SEPARATOR_DEFAULT,
    TITLE_SEPARATOR_MAX,
    V10_BUDGET_KEYS,
    V6_NAV_KEYS,
    V8_NAV_KEYS,
    V9_BLOCKS_KEYS,
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


def needs_schema_7(where, have):
    """A schema-7 key under a lower declared schema: 0.6.0 refuses it as an unknown key, and 0.7.0 refuses it naming the
    schema (design-adopt-ownership-line section 2.1)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 7" % where, path=where,
                           found="schema %d" % have, expected="schema 7",
                           fix="run `python3 build.py raise-schema --to 7`, which lists what the page changes before "
                               "it writes schema 7")


def needs_schema_8(where, have):
    """A schema-8 key under a lower declared schema: 0.7.0 refuses it as an unknown key, and 0.8.0 refuses it naming the
    schema (design-adopt-local-reach section 2.1). `workcheck` imports it from here (the reverse import would cycle)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 8" % where, path=where,
                           found="schema %d" % have, expected="schema 8",
                           fix="run `python3 build.py raise-schema --to 8`, which lists what the page changes before "
                               "it writes schema 8")


def needs_schema_9(where, have):
    """A schema-9 key under a lower declared schema: 0.8.0 refuses it as an unknown key, and 0.9.0 refuses it naming the
    schema (design-reference-layout section 5)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 9" % where, path=where,
                           found="schema %d" % have, expected="schema 9",
                           fix="run `python3 build.py raise-schema --to 9`, which lists what the page changes before "
                               "it writes schema 9")


def needs_schema_10(where, have):
    """A schema-10 key under a lower declared schema: 0.9.0 refuses it as an unknown key, and 0.10.0 refuses it naming the
    schema (design-publish-preflight section 8; dev 1068)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 10" % where, path=where,
                           found="schema %d" % have, expected="schema 10",
                           fix="run `python3 build.py raise-schema --to 10`, which lists what the page changes before "
                               "it writes schema 10")


def _look_local(v, look=None):
    """`lookLocal` (schema 7, design-adopt-ownership-line section 2.1): exactly `site/looks/local.json`, the person's own
    look laid over the look `look` names; `look` naming the same file is refused (one file in both places). That the file
    exists at HEAD is the build's check, as it is for `look`."""
    v = _str(v, "lookLocal")
    if v != LOOK_LOCAL_PATH:
        raise SiteConfigError("site.json: 'lookLocal' must be exactly %s" % LOOK_LOCAL_PATH, path="lookLocal", found=v,
                              expected=LOOK_LOCAL_PATH,
                              fix="write \"lookLocal\": \"%s\" and keep your own look in that file" % LOOK_LOCAL_PATH)
    if look == LOOK_LOCAL_PATH:
        raise SiteConfigError("site.json: 'look' and 'lookLocal' both name %s; one file cannot be laid over itself"
                              % LOOK_LOCAL_PATH, path="look", found=look, expected="another file under site/looks/, or none",
                              fix="point look at the derived look (site/looks/derived.json) or remove it, and keep "
                                  "lookLocal")
    return v


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
        elif k in V8_NAV_KEYS and schema < 8:
            col.problems.append(needs_schema_8("nav.%s" % k, schema).problem)
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
    if "labels" in raw and schema >= 8:
        labels = _nav_labels(raw["labels"], col)
        if labels:
            out["labels"] = labels
    return out


def _nav_labels(raw, col):
    """`nav.labels` (schema 8, O-3): an object whose keys come from `NAV_LABEL_KEYS` (`about`, `resume`), each a non-empty
    one-line label the menu prints for that built-in page. `{}` is the default and writes away. Returns the good items;
    every fault is recorded in `col`."""
    if not isinstance(raw, dict):
        col.run(_bad, "nav.labels", "an object", raw)
        return {}
    out = {}
    for k in raw:
        at = "nav.labels.%s" % k
        if k not in NAV_LABEL_KEYS:
            col.add("site.json: unknown key '%s'" % at, at, "unknown key", "one of: " + ", ".join(NAV_LABEL_KEYS),
                    "remove '%s'" % at)
            continue
        ok, label = col.run(_one_line, raw[k], at)
        if ok:
            out[k] = label
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
    away; any other value is refused, naming the two.
    `unlistedVideos` (schema 9, design-reference-layout section 2, owner answer O-1 b) is `true` only: an unlisted Vimeo
    link's private code is sent to the player. Absent is the default; below 9 it is refused naming the schema."""
    if not isinstance(raw, dict):
        col.run(_bad, "blocks", "an object", raw)
        return {}
    out = {}
    for k in raw:
        if k not in BLOCKS_KEYS:
            col.add("site.json: unknown key 'blocks.%s'" % k, "blocks.%s" % k, "unknown key",
                    "one of: " + ", ".join(BLOCKS_KEYS), "remove 'blocks.%s'" % k)
        elif k in V9_BLOCKS_KEYS and schema < 9:
            col.problems.append(needs_schema_9("blocks.%s" % k, schema).problem)
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
    if "unlistedVideos" in raw and schema >= 9:
        v = raw["unlistedVideos"]
        if v is not True:
            col.add("site.json: 'blocks.unlistedVideos' must be true", "blocks.unlistedVideos", _shown(repr(v)), "true",
                    "set blocks.unlistedVideos to true to send an unlisted Vimeo link's code to the player, or remove it")
        else:
            out["unlistedVideos"] = True
    return out


def _reference_word(v, where):
    """One word of a `references` list: a non-empty one-line string with no surrounding whitespace, at most
    `REFERENCE_WORD_MAX` characters (the limit of a `type` or `channel` value, so a longer word could never be used)."""
    v = _one_line(v, where)
    if len(v) > REFERENCE_WORD_MAX:
        raise SiteConfigError("site.json: '%s' is %d characters; a word is at most %d" % (where, len(v), REFERENCE_WORD_MAX),
                              path=where, found="%d characters" % len(v),
                              expected="at most %d characters" % REFERENCE_WORD_MAX,
                              fix="shorten the word, or remove it")
    return v


def _reference_words(raw, where, col):
    """One list of `references`: 1 to `REFERENCE_WORDS_MAX` distinct words (compared in NFC, case-sensitively). Returns the
    good words in order, or None when the list itself is refused; every fault is recorded in `col`. An empty list is refused,
    never stored: `references` holds no list when the site sets none."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= REFERENCE_WORDS_MAX:
        col.add("site.json: '%s' must be a list of one to %d words" % (where, REFERENCE_WORDS_MAX), where,
                "%d item(s)" % len(raw) if isinstance(raw, list) else "not a list",
                "one to %d words" % REFERENCE_WORDS_MAX,
                "write %s as a list such as [\"Blog\", \"Film\"], or remove it to allow any word" % where)
        return None
    out, seen = [], {}
    for i, item in enumerate(raw):
        at = "%s[%d]" % (where, i)
        ok, word = col.run(_reference_word, item, at)
        if not ok:
            continue
        key = unicodedata.normalize("NFC", word)
        if key in seen:
            col.add("site.json: '%s' repeats %s" % (at, _shown(repr(word))), at, word, "each word once",
                    "remove the repeated word (it is the same as %s[%d])" % (where, seen[key]))
            continue
        seen[key] = i
        out.append(word)
    return out


def _references_check(raw, col):
    """`references` (schema 9, design-reference-layout section 1.3): an object with any of `types`, `channels` (each a list of
    words, `_reference_words`) and `unprinted` (an object whose keys are `type` and `channel`, each a list of words that are
    stored but never printed; with the matching list set, each must be in it). `{}` is the default and normalises away, as does an
    empty `unprinted`. Returns the good members; every fault is recorded in `col`."""
    if not isinstance(raw, dict):
        col.run(_bad, "references", "an object", raw)
        return {}
    out = {}
    for k in raw:
        if k not in REFERENCES_KEYS:
            col.add("site.json: unknown key 'references.%s'" % k, "references.%s" % k, "unknown key",
                    "one of: " + ", ".join(REFERENCES_KEYS), "remove 'references.%s'" % k)
    lists = {}
    for member, key in (("types", "type"), ("channels", "channel")):
        if member in raw:
            words = _reference_words(raw[member], "references.%s" % member, col)
            if words is not None:
                lists[key] = out[member] = words
    if "unprinted" in raw:
        un = raw["unprinted"]
        if not isinstance(un, dict):
            col.run(_bad, "references.unprinted", "an object", un)
            un = {}
        kept = {}
        for key in un:
            if key not in REFERENCE_UNPRINTED_KEYS:
                at = "references.unprinted.%s" % key
                col.add("site.json: unknown key '%s'" % at, at, "unknown key",
                        "one of: " + ", ".join(REFERENCE_UNPRINTED_KEYS), "remove '%s'" % at)
        for key in (k for k in REFERENCE_UNPRINTED_KEYS if k in un):      # the writer's order, whatever the file's
            at = "references.unprinted.%s" % key
            words = _reference_words(un[key], at, col)
            if words is None:
                continue
            member = key + "s"
            names = set(unicodedata.normalize("NFC", w) for w in lists.get(key, ()))
            outside = [(i, w) for i, w in enumerate(words) if key in lists and unicodedata.normalize("NFC", w) not in names]
            for i, w in outside:
                col.add("site.json: '%s[%d]' is %s, which references.%s does not list" % (at, i, _shown(repr(w)), member),
                        "%s[%d]" % (at, i), w, "a word of references.%s" % member,
                        "add %s to references.%s, or remove it from %s" % (_shown(repr(w)), member, at))
            if not outside:
                kept[key] = words
        if kept:
            out["unprinted"] = kept
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


def _finite_number(v, where):
    """`_number`, and a finite one: JSON as Python reads it holds `NaN` and `Infinity`, which compare above zero or never
    below it and would make a limit that never refuses (schema 10's `budgets.lazyImagesMaxMB`; dev 1068)."""
    v = _number(v, where)
    if not math.isfinite(v):
        raise SiteConfigError("site.json: '%s' must be a finite number" % where, path=where, found=_shown(repr(v)),
                              expected="a finite number above zero", fix="set '%s' to a number such as 20" % where)
    return v


def _budgets_check(raw, col, schema=SCHEMA_MAX):
    """`budgets`: the four limits of `BUDGET_DEFAULTS`, each a number above zero, and from schema 10 `lazyImagesMaxMB`
    (`V10_BUDGET_KEYS`, a finite number above zero; below 10 it is refused naming the schema)."""
    if not isinstance(raw, dict):
        col.run(_bad, "budgets", "an object", raw)
        return {}
    out = {}
    for k, v in raw.items():
        if k in V10_BUDGET_KEYS:
            if schema < 10:
                col.problems.append(needs_schema_10("budgets.%s" % k, schema).problem)
            else:
                ok, val = col.run(_finite_number, v, "budgets." + k)
                if ok:
                    out[k] = val
            continue
        if k not in BUDGET_DEFAULTS:
            known = sorted(BUDGET_DEFAULTS) + (sorted(V10_BUDGET_KEYS) if schema >= 10 else [])
            col.add("site.json: unknown key 'budgets.%s'" % k, "budgets.%s" % k, "unknown key",
                    "one of: " + ", ".join(known), "remove 'budgets.%s'" % k)
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


def _images_check(raw, col):
    """`images` (schema 10, design-publish-preflight section 3.2, owner decision O-3 a; dev 1068): an object whose one key is
    `sizes`, "as-written" or "held". `{}` is the default and normalises away. Returns the good members; every fault is recorded in
    `col`."""
    if not isinstance(raw, dict):
        col.run(_bad, "images", "an object", raw)
        return {}
    out = {}
    for k in raw:
        if k not in IMAGES_KEYS:
            col.add("site.json: unknown key 'images.%s'" % k, "images.%s" % k, "unknown key",
                    "one of: " + ", ".join(IMAGES_KEYS), "remove 'images.%s'" % k)
    if "sizes" in raw:
        ok, v = col.run(_one_of, raw["sizes"], "images.sizes", IMAGES_SIZES)
        if ok:
            out["sizes"] = v
    return out


def v10_top_check(data, col):
    """The schema-10 top-level keys of a decoded `site.json` (the caller has refused them below 10), as {key: value} of those
    that are set: `images` (`_images_check`; `{}` is written away) and `sitemap` ("indexable", the one value). Every fault is
    recorded in `col`."""
    out = {}
    if "images" in data:
        v = _images_check(data["images"], col)
        if v:
            out["images"] = v
    if "sitemap" in data:
        ok, v = col.run(_one_of, data["sitemap"], "sitemap", SITEMAP_VALUES)
        if ok:
            out["sitemap"] = v
    return out
