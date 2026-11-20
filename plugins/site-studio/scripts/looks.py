#!/usr/bin/env python3
"""looks.py -- a site's look is DATA the site carries (design-template-fidelity section R5, #909).
Python 3.9, standard library only.

A *look* is a JSON file (`site/looks/<name>.json`, or the plugin's own default at
`templates/looks/site-studio.json`) that says which markup each *construct* renders. A construct is a
named piece of generated markup (a quote, a card, the nav); it has fixed named *parts* the plugin chooses
between (a quote's `wrap` and its optional `by`; a nav `item` and `item-current`); a part is HTML holding
`{{slot}}` placeholders and nothing else. There is no logic in a look: no loop, no condition, no script.

    CONSTRUCTS     the closed table: construct id -> parts -> slot name -> slot kind. Written once, in full
                   (step 1.2L, named change R5N-2), in `lookgrammar/constructs.py` with the element and
                   attribute lists, and re-exported here: later steps add default entries and code, never rows.
    parse()        strict, DENY-BY-DEFAULT validation of a look file (R5.2 rules 1 to 9), each refusal naming
                   the file, the construct, the part and the fix.
    render()       fill one part: every slot is escaped or validated by its KIND, whatever the look says.
    safe_url()     the one URL rule for a `url` slot, built on `contentmodel.links.url_as_browser_reads` (dev #912), the
                   same normaliser the content links use (R5N-4): no second normaliser.

THREAT MODEL (R5.1 L5). Slot VALUES are untrusted data (a person's text, a captured page's title). A look
FILE is trusted as markup only inside the allowlist below: the owner of a site can already write its
`layout.html`, so the grammar does not protect a site from its owner. It exists because looks TRAVEL as
data (a shipped look, `look.py use <path>` from another repo, a derived look that copied an old page's
attributes) and because the plugin's own claims (no script; no third party on load, bar the one named
exception) must hold for every look it renders. So an element, an (element, attribute) pair, a URL form or a
slot placement that is not listed is REFUSED, never ignored.

SLOT KINDS (fixed per slot name in CONSTRUCTS, so no context inference is needed; OURS, diverged from Go
`html/template`'s contextual escaping on purpose):
    text      escaped with `contentmodel.links.esc`; element content or a plain attribute value
    int       a non-negative whole number; element content or a plain attribute value
    html      HTML the PLUGIN rendered (an inline-Markdown run, another part); element content only
    url       `safe_url`: relative, http(s); exactly the whole value of `href`, `src` or `cite`
    srcset    a list of relative candidates, each checked by `safe_url`; exactly the value of `srcset`
    embed     one of the three embed hosts, https; exactly `iframe src` or `data-embed`
    contact   `safe_url` that also allows `mailto:`; only `a href` in the `contact` construct
    position  a CSS position (the regex 0.3.1 validates `coverPosition` with); only `style` on `img`

The Markdown renderer's own inline and block markup (`<p>`, `<h2>`, `<a>`, `<strong>`, the map's `<svg>`) is
not a construct: it is the value of an `html` slot, produced by the plugin, never by a look.
"""
import functools
import html.parser
import json
import os
import re

from contentmodel.links import esc
from lookgrammar.errors import LookError
from lookgrammar.slotvalues import _INTLIT, safe_embed, safe_int, safe_position, safe_srcset, safe_url
from lookgrammar.stylesheets import check_stylesheet_path
from lookgrammar import decoration, optionalparts
# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from lookgrammar.constructs import (
    TEXT,
    HTML,
    URL,
    SRCSET,
    POSITION,
    INT,
    EMBED,
    CONTACT,
    SLOT_KINDS,
    ASSET_KINDS,
    _c,
    CONSTRUCTS,
    PART_FIRST,
    SLOT_FIRST,
    OPEN_SLOT_FIRST, OPTIONAL_PARTS, TEXT_ONLY_PARTS, SENT_OPEN, SENT_CLOSE,
    ALLOWED_ELEMENTS,
    VOID_ELEMENTS,
    IFRAME_PARTS,
    ELEMENT_REFUSALS,
    GLOBAL_ATTRS,
    ELEMENT_ATTRS,
    NAMED_REFUSED_ATTRS,
    STYLE_FORM,
    URL_ATTRS,
    SCRIPT_READ_ATTRS,
    _ROLES,
    CLOSED_VALUES,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
DEFAULT_LOOK_REL = "templates/looks/site-studio.json"
DEFAULT_LOOK_PATH = os.path.join(PLUGIN_ROOT, *DEFAULT_LOOK_REL.split("/"))
LOOK_FORMAT = 1

# ------------------------------------------------------------------- the construct table's own checks
# The table itself (CONSTRUCTS, PART_FIRST) and the element and attribute lists are in lookgrammar/constructs.py.

_PART_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_SLOT_NAME = re.compile(r"^[a-z][A-Za-z0-9]*$")     # lower camel case: `fullTitle` (step G, O4a) is the first capital
_SLOT = re.compile(r"\{\{([^{}]*)\}\}")


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def part_first(construct, part):
    return PART_FIRST.get((construct, part), CONSTRUCTS[construct]["first"])


def gated_slots(construct, part):
    """{slot: trigger} of one part's gated slots (rule L3a, `SLOT_FIRST`); {} for a part that has none."""
    return dict((s, trig) for (c, p, s), (_rel, trig) in SLOT_FIRST.items() if (c, p) == (construct, part))


def gate(construct, part, slot, triggers, markup):
    """The value a gated slot is filled with: `markup` when `triggers` (the schema-5 triggers of the piece's OWN
    portfolio, `keytables.active_triggers`) holds the slot's trigger, else "" (design-movement-view section 4.3). Every
    call site that fills a gated slot goes through here, and `render` fills a gated slot it is given no value for with
    "", so a part rendered by a call site that predates the slot prints exactly what it printed before."""
    if SLOT_FIRST[(construct, part, slot)][1] in triggers:
        return markup
    return ""


def slot_release(construct, part, slot):
    """The release a slot added to an older part needs (`SLOT_FIRST`, gated; `OPEN_SLOT_FIRST`, ungated), else None."""
    row = SLOT_FIRST.get((construct, part, slot))
    return row[0] if row else OPEN_SLOT_FIRST.get((construct, part, slot))


def optional_part(construct, part, look):
    """The site's own markup for an `OPTIONAL_PARTS` part, or None when its look writes none (the default look has none
    of them): the caller then renders the place exactly as it did before the part existed (step G, O2 and O3)."""
    return look.own_part(construct, part) if look is not None and (construct, part) in OPTIONAL_PARTS else None


# ------------------------------------------------------------- the release a look needs (design-movement-view 3.4)
# An asset kind first released after 0.3.1 (`css` and `js` are 0.3.1's), with its release.
ASSET_FIRST = {"schema-4": "0.4.0", "schema-5": "0.5.0"}


def _decoration_needs(constructs):
    """The release a decoration (a literal `<svg>` subtree that meets `lookgrammar/decoration.py`'s rules; design-movement-
    view 3.4, 9.2) in any part of `constructs` ({construct id: {part: markup}}) needs: "0.5.0", else None."""
    return decoration.RELEASE if decoration.holds(constructs, _PartParser) else None


def needs(look_text):
    """The newest release the look file `look_text` (its JSON text) needs to be read, as "0.5.0": the newest of the
    `first` of every construct it names, every part it writes (`part_first`, `PART_FIRST`), every slot it places that
    `SLOT_FIRST` gates or `OPEN_SLOT_FIRST` adds (`slot_release`), every asset kind it links (`ASSET_FIRST`) and every
    decoration it holds (`_decoration_needs`).
    None for a look that names nothing, or that is not a look at all (`parse` refuses that with its own line). A name
    this release does not know is left to `parse`, which refuses it as unknown. The schema check reads this through
    `building.lookneeds`, because `configschema` does not import the look grammar."""
    try:
        data = json.loads(look_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    found, clean = [], {}
    constructs = data.get("constructs")
    for cid, parts in (constructs.items() if isinstance(constructs, dict) else ()):
        if cid not in CONSTRUCTS or not isinstance(parts, dict):
            continue
        found.append(CONSTRUCTS[cid]["first"])
        clean[cid] = {}
        for pn, text in parts.items():
            if pn not in CONSTRUCTS[cid]["parts"] or not isinstance(text, str):
                continue
            clean[cid][pn] = text
            found.append(part_first(cid, pn))
            found.extend(r for r in (slot_release(cid, pn, m.group(1)) for m in _SLOT.finditer(text)) if r)
    assets = data.get("assets")
    for kinds in (assets.values() if isinstance(assets, dict) else ()):
        found.extend(ASSET_FIRST[k] for k in (kinds if isinstance(kinds, list) else ())
                     if isinstance(k, str) and k in ASSET_FIRST)
    decoration = _decoration_needs(clean)
    if decoration:
        found.append(decoration)
    return max(found, key=version_tuple) if found else None


def table_problems():
    """The table's own consistency: names, kinds. Used by the tests; an empty list is a sound table."""
    out = []
    for cid, c in CONSTRUCTS.items():
        if not _PART_NAME.match(cid):
            out.append("construct %r: not a lower-case slug" % cid)
        if not c["parts"]:
            out.append("construct %r has no parts" % cid)
        for pn, slots in c["parts"].items():
            if not _PART_NAME.match(pn):
                out.append("%s.%s: part name is not a lower-case slug" % (cid, pn))
            for sn, kind in slots.items():
                if not _SLOT_NAME.match(sn):
                    out.append("%s.%s: slot name %r is not lower camel case (letters and digits)" % (cid, pn, sn))
                if kind not in SLOT_KINDS:
                    out.append("%s.%s.%s: unknown slot kind %r" % (cid, pn, sn, kind))
    return out


_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
_DIGITS3 = re.compile(r"\d{3,}")

_SENT_OPEN, _SENT_CLOSE = SENT_OPEN, SENT_CLOSE      # U+E000, U+E001
_SENT = re.compile(_SENT_OPEN + r"(\d+)" + _SENT_CLOSE)


# ---------------------------------------------------------------------------------------------- parse
def attr_allowed(tag, name):
    """True when (tag, name) is on the allowlist: a global attribute, an `aria-*` or `data-*` one, or one the
    element's own list names. `style` is never here: it has the one exact form of rule 6 and nothing else."""
    if name in GLOBAL_ATTRS or re.match(r"^(aria|data)-[a-z][a-z0-9-]*$", name):
        return True
    return name in ELEMENT_ATTRS.get(tag, ())


def live_players(look):
    """[(construct, part)] of a look that carry an `iframe`: the places a live third-party player loads on
    page load. A template or derived look may hold one in `videos.item` (design decision 34); the
    plugin-authored looks hold none, bar the bare video line the default look has carried since 0.2.0."""
    return sorted((c, p) for c, parts in look.constructs.items() for p, t in parts.items()
                  if re.search(r"<iframe\b", t, re.I))


class _PartParser(html.parser.HTMLParser):
    """Walks one part's text (slots already replaced by sentinels) and records every problem."""

    def __init__(self, ctx, slots, shipped, template):
        html.parser.HTMLParser.__init__(self, convert_charrefs=False)
        self.ctx = ctx                      # "construct.part"
        self.construct, self.part = ctx.split(".", 1)
        self.slots = slots                  # slot name -> kind (the table's)
        self.shipped = shipped
        self.template = template
        self.slots_by_index = ()
        self.stack = []
        self.problems = []
        self.elements, self.seen_attrs = [], []     # seen_attrs: every (name, value), for optionalparts

    # -- helpers
    def bad(self, message, fix=None):
        self.problems.append((message, fix))

    # -- structure
    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def _start(self, tag, attrs, selfclose):
        if _SENT_OPEN in tag:
            self.bad("%s: a slot inside a tag name" % self.ctx, "a slot may stand in text or in an attribute value only")
            return
        self.elements.append(tag)
        if tag in ELEMENT_REFUSALS and not (tag == "iframe" and (self.construct, self.part) in IFRAME_PARTS):
            self.bad("%s: <%s> is not allowed: %s" % (self.ctx, tag, ELEMENT_REFUSALS[tag]),
                     "remove the <%s>; allowed elements are listed in the content model" % tag)
        elif tag not in ALLOWED_ELEMENTS and tag != "iframe":
            self.bad("%s: <%s> is not an allowed element" % (self.ctx, tag),
                     "use one of the elements the content model lists")
        self.seen_attrs.extend(attrs)
        self._attrs(tag, attrs)
        if tag not in VOID_ELEMENTS and not selfclose:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.bad("%s: </%s> closes nothing that is open here (unbalanced tags)" % (self.ctx, tag),
                     "close every element you open, in order")
            return
        self.stack.pop()

    def handle_data(self, data):
        for i in _SENT.findall(data):
            sname, kind = self.slot_by_index(i)
            if kind not in (TEXT, HTML, INT):
                self.bad("%s: the %s slot {{%s}} stands in element content; a %s slot belongs in its attribute"
                         % (self.ctx, kind, sname, kind), "use a text slot for visible words")
        if "<" in data:
            self.bad("%s: a '<' that does not open a tag (or a slot in a tag name)" % self.ctx,
                     "write a literal < as &lt;")
        if self.template and any(ch.isalpha() for ch in _SENT.sub("", data)):
            self.bad("%s: literal text %r in a template look; text comes from a slot" % (self.ctx, data.strip()[:30]),
                     "replace the words with a slot")

    def handle_entityref(self, name):
        self.handle_data("")

    def handle_charref(self, name):
        self.handle_data("")

    def handle_comment(self, data):
        self.bad("%s: an HTML comment" % self.ctx, "remove the comment")

    def handle_decl(self, decl):
        self.bad("%s: a declaration (<!...>)" % self.ctx, "remove it")

    def handle_pi(self, data):
        self.bad("%s: a processing instruction (<?...>)" % self.ctx, "remove it")

    def unknown_decl(self, data):
        self.bad("%s: a marked section (<![...]>)" % self.ctx, "remove it")

    # -- attributes
    def _attrs(self, tag, attrs):
        seen = set()
        names = dict(attrs)
        for name, value in attrs:
            if _SENT_OPEN in name:
                self.bad("%s: a slot inside an attribute name on <%s>" % (self.ctx, tag),
                         "a slot may stand in an attribute VALUE only")
                continue
            if name in seen:
                self.bad("%s: <%s> repeats the attribute %s" % (self.ctx, tag, name), "write it once")
            seen.add(name)
            self._one_attr(tag, name, value, names)

    def _allowed_pair(self, tag, name):
        return attr_allowed(tag, name)

    def _one_attr(self, tag, name, value, names):
        where = "%s: <%s %s>" % (self.ctx, tag, name)
        if name == "style":
            ok = (tag == "img" and value is not None and _SENT_OPEN in value
                  and self._style_is_focus(value))
            if not ok:
                self.bad(where + " is refused: " + NAMED_REFUSED_ATTRS["style"], "remove the style attribute")
            return
        if name.startswith("on"):
            self.bad(where + " is refused: an event handler is code", "remove it")
            return
        if name in NAMED_REFUSED_ATTRS:
            self.bad(where + " is refused: " + NAMED_REFUSED_ATTRS[name], "remove it")
            return
        if not self._allowed_pair(tag, name):
            self.bad(where + " is not an allowed attribute of <%s>" % tag, "remove it; allowed pairs are listed in the content model")
            return
        if tag == "iframe" and name not in ELEMENT_ATTRS["iframe"]:
            self.bad(where + " is not allowed on an iframe", "an iframe carries only src, title, loading, allow, allowfullscreen, referrerpolicy")
            return
        if name == "allowfullscreen":
            if value not in (None, "", "allowfullscreen"):
                self.bad(where + " takes no value", "write it bare")
            return
        if name == "hidden":
            if value not in (None, "", "hidden", "until-found"):
                self.bad(where + " has an unknown value %r" % value, "write it bare")
            return
        if value is None:
            value = ""
        slots = [self.slot_by_index(i) for i in _SENT.findall(value)]
        literal = _SENT.sub("", value)
        if name in URL_ATTRS:
            self._url_attr(tag, name, value, slots, literal)
            return
        # rule 7: literals or text and int slots; a url, embed, srcset, contact, position or html slot is refused here
        for (sname, kind) in slots:
            if kind not in (TEXT, INT):
                self.bad("%s holds the %s slot {{%s}}; only a text or int slot may stand in this attribute"
                         % (where, kind, sname), "use a text slot, or put the slot where its kind belongs")
        if name in CLOSED_VALUES:
            if slots:
                self.bad(where + " holds a slot; the plugin chooses its value from a closed list", "write one of: " + ", ".join(CLOSED_VALUES[name]))
                return
            toks = value.split() if name in ("rel", "allow") else [value]
            if name == "allow":
                toks = [t.strip() for t in value.replace(";", " ").split()]
            if not toks or any(t not in CLOSED_VALUES[name] for t in toks):
                self.bad("%s has the value %r, which is not in its closed list" % (where, value),
                         "write one of: " + ", ".join(CLOSED_VALUES[name]))
            if name == "target" and value == "_blank":
                rel = names.get("rel") or ""
                if "noopener" not in rel.split():
                    self.bad(where + " _blank needs a rel containing noopener", "add rel=\"noopener\"")
            return
        if name == "tabindex":
            if value not in ("0", "-1"):
                self.bad(where + " may be the literal 0 or -1 only", "write tabindex=\"0\"")
            return
        if name in ("lang", "hreflang"):
            if slots or not _LANG.match(value):
                self.bad(where + " must be a language code such as en", "write a language code")
            return
        if name in ("width", "height", "start", "value", "colspan", "rowspan"):
            if not (slots and not literal) and not _INTLIT.match(value):
                self.bad(where + " must be a whole number or one int slot", "write a number or {{n}}")
            return
        if self.template:
            self._template_value(tag, name, value, slots, literal)
        if name == "class":
            for tok in literal.split():
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", tok):
                    self.bad("%s has a class token %r that is not a name" % (where, tok), "use letters, digits, - and _")

    def _template_value(self, tag, name, value, slots, literal):
        where = "%s: <%s %s>" % (self.ctx, tag, name)
        tokenish = name in ("class", "id") or name.startswith(("data-", "aria-"))
        if tokenish:
            for tok in literal.split():
                if not _TOKEN.match(tok) or _DIGITS3.search(tok):
                    self.bad("%s has the token %r (template looks: a name, at most 40 characters, no run of three digits)"
                             % (where, tok), "write the token as the template names it, with a slot for a number")
        elif any(ch.isalpha() for ch in literal):
            self.bad("%s carries literal text %r in a template look" % (where, literal[:30]), "use a slot, or a closed-list value")

    def _style_is_focus(self, value):
        return _SENT.sub("{{focus}}", value) == STYLE_FORM and self.slot_by_index(
            _SENT.findall(value)[0]) == ("focus", POSITION)

    def _url_attr(self, tag, name, value, slots, literal):
        where = "%s: <%s %s>" % (self.ctx, tag, name)
        allowed = URL_ATTRS[name]
        if slots:
            if literal.strip() or len(slots) != 1:
                self.bad(where + " must be exactly one slot and nothing else", "write %s=\"{{url}}\"" % name)
                return
            sname, kind = slots[0]
            if kind not in allowed:
                self.bad("%s holds the %s slot {{%s}}; a %s attribute takes only a %s slot"
                         % (where, kind, sname, name, "/".join(allowed)),
                         "use a slot of kind %s, or a relative literal" % "/".join(allowed))
                return
            if kind == CONTACT and not (tag == "a" and self.construct == "contact"):
                self.bad(where + " takes a contact slot only on an <a> in the contact construct", "use a url slot")
            if kind == EMBED:
                if not ((tag == "iframe" and name == "src") or name == "data-embed"):
                    self.bad(where + " takes an embed slot only as `iframe src` or `data-embed`", "use a url slot")
            if tag == "iframe" and name == "src" and kind != EMBED:
                self.bad(where + " must be exactly {{embed}}", "write src=\"{{embed}}\"")
            return
        # a literal
        if name == "data-embed" or (tag == "iframe" and name == "src"):
            self.bad(where + " must be exactly the {{embed}} slot, never a literal", "write %s=\"{{embed}}\"" % name)
            return
        try:
            if name == "srcset":
                for cand in literal.split(","):
                    bits = cand.split()
                    if bits:
                        safe_url(bits[0], relative_only=True)
            else:
                safe_url(literal, relative_only=True)
        except LookError as e:
            self.bad("%s: the literal %r is refused: %s" % (where, literal[:60], e), "use a {{url}} slot or a relative path")

    def slot_by_index(self, i):
        return self.slots_by_index[int(i)]


def _replace_slots(text, slots_table, ctx, problems):
    """Replace each valid `{{name}}` by a sentinel; collect (name, kind). A `{{` left over is a problem."""
    found = []

    def sub(m):
        name = m.group(1)
        if name not in slots_table:
            problems.append(("%s: the slot {{%s}} is not one of this part's slots (%s)"
                             % (ctx, name, ", ".join(sorted(slots_table)) or "it has none"),
                             "use only the part's own slots; the content model lists them"))
            found.append((name, TEXT))
        else:
            found.append((name, slots_table[name]))
        return _SENT_OPEN + str(len(found) - 1) + _SENT_CLOSE
    out = _SLOT.sub(sub, text)
    if "{{" in out or "}}" in out:
        problems.append(("%s: a literal '{{' or '}}' that is not a slot" % ctx, "write a slot as {{name}}, its name in lower camel case such as {{fullTitle}}"))
    return out, found


def check_part(construct, part, text, shipped=False, template=False, parsed=None):
    """Every problem with one part's text, as [(message, fix)]. [] is a clean part. `parsed`: see `optionalparts.problems`."""
    problems = []
    ctx = "%s.%s" % (construct, part)
    if not isinstance(text, str):
        return [("%s: a part is a string of HTML" % ctx, "write the part as a JSON string")]
    if _SENT_OPEN in text or _SENT_CLOSE in text:
        return [("%s: a private-use character U+E000 or U+E001" % ctx, "remove it")]
    if (construct, part) in TEXT_ONLY_PARTS and "<" in text:
        return [("%s: this part is literal text only, with no element" % ctx, "write the text alone, such as \" / \"")]
    table = CONSTRUCTS[construct]["parts"][part]
    replaced, found = _replace_slots(text, table, ctx, problems)
    p = decoration.reader(_PartParser)(ctx, table, shipped, template)    # an `<svg>` subtree: lookgrammar/decoration.py
    p.slots_by_index = found
    try:
        p.feed(replaced)
        p.close()
    except Exception as e:                                        # noqa: BLE001 -- html.parser's own errors
        problems.append(("%s: the markup cannot be read (%s)" % (ctx, e), "fix the markup"))
    problems.extend(p.problems)
    if (construct, part) in OPTIONAL_PARTS:      # step G's own rules (review F1, F7): lookgrammar/optionalparts.py
        problems.extend(optionalparts.problems(ctx, construct, part, text, replaced, found, p.seen_attrs, parsed))
    if p.stack:
        problems.append(("%s: <%s> is never closed" % (ctx, p.stack[-1]), "close every element you open"))
    # an html slot only in element content: a sentinel for an html slot inside any attribute value is caught
    # in _one_attr (kind not text/int); here the same slot in a tag position was caught by the tag-name rule.
    return [(m, f) for m, f in problems]


class Look(object):
    """A parsed look: `constructs` {id: {part: text}}, `stylesheets` [path], `assets` {id: [kind]}."""

    def __init__(self, constructs, stylesheets, assets, where):
        self.constructs = constructs
        self.stylesheets = stylesheets
        self.assets = assets
        self.where = where

    def has(self, construct, part):
        return part in self.constructs.get(construct, {})

    def own_part(self, construct, part):
        return self.constructs.get(construct, {}).get(part)

    def omitted(self):
        """Construct ids this look has no entry for (rendered with the default look's)."""
        return sorted(c for c in CONSTRUCTS if c not in self.constructs)


def parse(text, where="look", shipped=False, template=None):
    """Parse and validate a look file's text. Returns a `Look`; raises LookError naming the first
    problem group (every problem is in the message, one per line). `shipped=True` is CI's reading of a
    file in `templates/looks/` (R5.2 rule 8): the same rules, plus, for a TEMPLATE look (`template`,
    default: the file's name starts `template-`), no literal word in text or attribute values and the
    token rules; a plugin-authored look keeps the token and URL rules and may hold literal words, because
    it is engine text written in this repository, not extracted from a site."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise LookError("%s: the look is not valid JSON (%s)" % (where, e), fix="fix the JSON")
    if not isinstance(data, dict):
        raise LookError("%s: a look is a JSON object" % where, fix="start from {\"look\": 1, \"constructs\": {}}")
    problems = []
    for k in data:
        if k not in ("look", "constructs", "stylesheets", "assets"):
            problems.append("%s: unknown top-level key %r" % (where, k))
    ver = data.get("look")
    if ver is None or isinstance(ver, bool) or not isinstance(ver, int):
        problems.append("%s: `look` must be the format version, %d" % (where, LOOK_FORMAT))
    elif ver > LOOK_FORMAT:
        raise LookError("%s: this look was made by a newer site-studio (format %d); update the plugin" % (where, ver),
                        fix="update site-studio")
    elif ver != LOOK_FORMAT:
        problems.append("%s: `look` is %r; this version reads format %d" % (where, ver, LOOK_FORMAT))
    if template is None:
        template = bool(shipped) and os.path.basename(where).startswith("template-")
    constructs = data.get("constructs", {})
    if not isinstance(constructs, dict):
        problems.append("%s: `constructs` is an object of construct id -> part -> markup" % where)
        constructs = {}
    clean = {}
    for cid, parts in constructs.items():
        if cid not in CONSTRUCTS:
            problems.append("%s: unknown construct %r (known: see the content model)" % (where, cid))
            continue
        if not isinstance(parts, dict):
            problems.append("%s: construct %s is an object of part -> markup" % (where, cid))
            continue
        clean[cid] = {}
        for pn, ptext in parts.items():
            if pn not in CONSTRUCTS[cid]["parts"]:
                problems.append("%s: construct %s has no part %r (its parts: %s)"
                                % (where, cid, pn, ", ".join(sorted(CONSTRUCTS[cid]["parts"]))))
                continue
            for msg, fix in check_part(cid, pn, ptext, shipped=shipped, template=template):
                problems.append("%s: %s%s" % (where, msg, " -- fix: " + fix if fix else ""))
            clean[cid][pn] = ptext
    problems.extend(decoration.look_problems(where, clean, _PartParser))     # an id a decoration writes, once a look
    sheets = data.get("stylesheets", [])
    if not isinstance(sheets, list):
        problems.append("%s: `stylesheets` is a list of paths" % where)
        sheets = []
    norm_sheets = []
    for sp in sheets:
        try:
            norm_sheets.append(check_stylesheet_path(sp, where))
        except LookError as e:
            problems.append(str(e))
    assets = data.get("assets", {})
    if not isinstance(assets, dict):
        problems.append("%s: `assets` is an object of construct id -> [%s]" % (where, ", ".join(ASSET_KINDS)))
        assets = {}
    for cid, kinds in assets.items():
        if cid not in CONSTRUCTS:
            problems.append("%s: `assets` names the unknown construct %r" % (where, cid))
        if not isinstance(kinds, list) or any(k not in ASSET_KINDS for k in kinds):
            problems.append("%s: `assets` for %s must be a list drawn from %s" % (where, cid, ", ".join(ASSET_KINDS)))
    if shipped and not template:
        problems.extend(_third_party_problems(where, clean))
    if problems:
        raise LookError("\n".join(problems), fix="fix each line above, then run the check again")
    return Look(clean, norm_sheets, dict(assets), where)


def _third_party_problems(where, constructs):
    """`ShippedLooksNoThirdParty`'s rule, applied to a plugin-authored look: no iframe except 0.3.1's bare
    video line (a live embed since 0.2.0, frozen), and no off-origin reference in any attribute."""
    out = []
    for cid, parts in constructs.items():
        for pn, text in parts.items():
            if re.search(r"<iframe\b", text, re.I) and (cid, pn) != ("video-embed", "wrap"):
                out.append("%s: %s.%s holds an iframe; a plugin-authored look carries no live player "
                           "(invariant item 5), bar the bare video line" % (where, cid, pn))
            for m in re.finditer(r"(?:href|src|srcset|cite|data-embed)=\"([^\"]*)\"", text):
                v = _SLOT.sub("", m.group(1)).strip()
                if v and re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)", v):
                    out.append("%s: %s.%s holds the off-origin address %r" % (where, cid, pn, v[:50]))
    return out


# -------------------------------------------------------------------------------------- the default look
@functools.lru_cache(maxsize=1)
def default_look():
    """The plugin's own look, `templates/looks/site-studio.json`, parsed once. A missing file is a refusal,
    never an empty look (a missing thing must not read as an empty thing)."""
    try:
        with open(DEFAULT_LOOK_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise LookError("the plugin's default look %s cannot be read: %s" % (DEFAULT_LOOK_REL, e),
                        fix="reinstall site-studio: the package is missing a file it needs")
    return parse(text, DEFAULT_LOOK_REL, shipped=True)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read(), path)


# ------------------------------------------------------------------------------------------------ render
def part_markup(construct, part, look=None):
    """The template text for one part: the look's own, else the default look's."""
    if construct not in CONSTRUCTS or part not in CONSTRUCTS[construct]["parts"]:
        raise LookError("no such construct part: %s.%s; correct the name in the look file (site/looks/<name>.json), then run `/site-studio:look check`" % (construct, part))
    if look is not None and look.has(construct, part):
        return look.own_part(construct, part)
    base = default_look()
    if not base.has(construct, part):
        raise LookError("the default look has no markup for %s.%s yet; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (construct, part))
    return base.own_part(construct, part)


def assets_for(construct, look=None):
    """The plugin output files (`ASSET_KINDS`) a page links where it holds `construct`, in the order
    the look names them. A look that carries its own entry for the construct decides, by its `assets` (none
    named means none linked: a template look brings its own stylesheet); a construct the look omits is linked
    as the default look says, the same rule as its markup (R5.2: the default look's entries carry 0.3.1's
    links, so `blocks.css` and `video.js` appear exactly where 0.3.1 puts them)."""
    if construct not in CONSTRUCTS:
        raise LookError("no such construct: %s; correct the name in the look file (site/looks/<name>.json), then run `/site-studio:look check`" % construct)
    if look is not None and construct in look.constructs:
        return tuple(look.assets.get(construct, ()))
    return tuple(default_look().assets.get(construct, ()))


_BLOCK_IMG_CLASS = re.compile(r"^<img\s+class=\"([^\"{}]*)\"")


def block_image_tag(tag, look=None):
    """An image tag a plugin block holds, marked the way the look's `block-image` entry marks it: the literal
    classes on its `plain` part's `<img>` (the default look: `ss-img`) are put on `tag`, an `<img ...>` the
    caller's environment already built. This is the ONE place the class is applied (it was a string replace
    in `content.py`); an environment that renders the `block-image` construct itself passes its own tag
    through `env.block_image` and never reaches here. A look whose `block-image` carries no class leaves the
    tag as it was."""
    m = _BLOCK_IMG_CLASS.match(part_markup("block-image", "plain", look))
    if not m:
        return tag
    return tag.replace("<img ", '<img class="%s" ' % m.group(1), 1)


def render(construct, part, values, look=None):
    """Fill one part with `values` ({slot name: python value}). Every slot is escaped or validated by its
    KIND in CONSTRUCTS, whatever the look says. A slot the template uses that `values` lacks, and a value
    for a slot the part does not have, are refused (a programming error, never a blank). The one exception is a
    GATED slot (rule L3a, `SLOT_FIRST`): given no value, it is filled with "", as it is when its trigger is off."""
    template = part_markup(construct, part, look)
    table = CONSTRUCTS[construct]["parts"][part]
    for k in values:
        if k not in table:
            raise LookError("%s.%s has no slot %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (construct, part, k))
    gated = gated_slots(construct, part)

    def fill(m):
        name = m.group(1)
        if name not in values and name in gated:
            return ""
        if name not in values:
            raise LookError("%s.%s: the slot {{%s}} was given no value; correct the slot name in the look file "
                            "(site/looks/<name>.json), then run `/site-studio:look check`" % (construct, part, name))
        v, kind = values[name], table[name]
        if kind == HTML:
            if not isinstance(v, str):
                raise LookError("%s.%s: the html slot {{%s}} needs a string" % (construct, part, name))
            return v
        if kind == INT:
            return safe_int(v)
        if not isinstance(v, str):
            raise LookError("%s.%s: the %s slot {{%s}} needs a string" % (construct, part, kind, name))
        if kind == TEXT:
            return esc(v)
        if kind == URL:
            return esc(safe_url(v))
        if kind == CONTACT:
            return esc(safe_url(v, allow_mailto=True))
        if kind == SRCSET:
            return esc(safe_srcset(v))
        if kind == EMBED:
            return esc(safe_embed(v))
        if kind == POSITION:
            return esc(safe_position(v))
        raise LookError("unknown slot kind %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % kind)
    return _SLOT.sub(fill, template)
