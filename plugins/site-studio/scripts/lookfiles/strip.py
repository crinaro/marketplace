"""lookfiles.strip -- one look entry made into a fragment that holds look grammar only (design-adopt-ownership-line section 13.2,
rules X1 to X8; round 2, M3).

A FRAGMENT is a look file holding one construct (or one named construct) and the `reads` entries that name it, after the strip,
written as canonical text (`json.dumps(sort_keys=True, indent=1, ensure_ascii=False)`). What it must pass is the reading CI gives a
`template-*.json` file in `templates/looks/`: `looks.parse(text, shipped=True, template=True)`. The strip is idempotent, and the
shipped looks are stripped by it before any comparison, so two sites with the same structure get the same fragment.

    X1  a class or id token            `c<n>` / `i<n>`, numbered by first appearance over the parts in the grammar's part order;
                                       the same token keeps one placeholder; a slot joined to a token stays (`c3-{{group}}`); a
                                       token the default look's own entry for that construct holds is kept
    X2  literal text in a text node    every word (letters or digits) removed; punctuation, spaces and entities stay
    X3  a text attribute               `alt`, `title`, `placeholder` and the `aria-*` text ones: removed unless its value is a slot
    X4  a `data-*` attribute           its name becomes `data-d<n>` and a literal value is removed (`data-embed` is grammar: kept)
    X5  a reference to an id           `aria-labelledby`, `aria-controls`, `for`, `href="#..."` and the like: X1's placeholder
    X6  a `reads` source               neither a built-in (`@first`) nor a plugin key (`contentmodel/keytables.py`, `READS`): `k<n>`
    X7  a named construct's name       `n1`; its `like` is kept
    X8  never carried                  `stylesheets`, an `assets` entry, a decoration (`<svg>`), a literal address
    kept                               element names, nesting, slots, closed-list values, whole numbers, `role`, `tabindex`

Every other `aria-*` value is kept only when it is in its closed list (`ARIA_CLOSED`) or a whole number (M3: no `aria-*` or `data-*`
value carries a word of the site). Python 3.9, standard library only; nothing here reads a file but the plugin's own tables.

    strip(construct, parts, reads=None, named=None, default=None)   a `Stripped`: fragment, text, digest, literals
    tokens_of(parts)                                                the class and id tokens a part set holds (G3 counts them)
    plugin_keys()                                                   the keys X6 keeps
"""

import hashlib
import html.parser
import json
import re

from contentmodel import keytables
from lookgrammar.constructs import CLOSED_VALUES, CONSTRUCTS, SENT_CLOSE, SENT_OPEN, URL_ATTRS
from lookgrammar.reads import READS

_SLOT = re.compile(r"\{\{([a-z][A-Za-z0-9]*)\}\}")
_SENT = re.compile(SENT_OPEN + r"(\d+)" + SENT_CLOSE)
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_EDGE = re.compile(r"^([-_]*)(.*?)([-_]*)$", re.S)
_WHOLE = re.compile(r"^\d+$")
TEXT_ATTRS = ("alt", "title", "placeholder", "aria-label", "aria-description", "aria-roledescription", "aria-placeholder",
              "aria-valuetext", "aria-keyshortcuts")
ID_REFS = ("for", "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-details", "aria-errormessage",
           "aria-flowto", "aria-activedescendant")
ARIA_CLOSED = {"aria-hidden": ("true", "false"), "aria-current": ("page", "step", "location", "date", "time", "true", "false"),
               "aria-expanded": ("true", "false"), "aria-pressed": ("true", "false", "mixed"), "aria-selected": ("true", "false"),
               "aria-live": ("polite", "assertive", "off"), "aria-haspopup": ("true", "false", "menu", "listbox", "dialog"),
               "aria-orientation": ("horizontal", "vertical"), "aria-sort": ("ascending", "descending", "none", "other")}
KEPT_LITERAL = ("lang", "hreflang", "style", "tabindex", "hidden", "allowfullscreen", "reversed")
_KEYS = []


class Stripped(object):
    """`fragment` (the look dict), `text` (its canonical text), `digest` (8 hex of its sha256), `literals` (how many literal values
    the strip removed: text runs and attribute values)."""

    def __init__(self, fragment, literals):
        self.fragment = fragment
        self.text = json.dumps(fragment, sort_keys=True, indent=1, ensure_ascii=False)
        self.digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:8]
        self.literals = literals


def plugin_keys():
    """Every key name the plugin's key tables and the `READS` defaults hold: a `reads` source that is one is plugin vocabulary."""
    if _KEYS:
        return _KEYS[0]
    found = set()

    def walk(v):
        if isinstance(v, str):
            if keytables.KEY_RE.match(v):
                found.add(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(k)
                walk(x)
        elif isinstance(v, (list, tuple, set, frozenset)):
            for x in v:
                walk(x)
    for name in dir(keytables):
        if name.isupper():
            walk(getattr(keytables, name))
    for row in READS.values():
        walk(row["default"])
        walk(row["setting"])
    _KEYS.append(frozenset(found))
    return _KEYS[0]


def _cores(value):
    """The literal cores of a class or id value's tokens (a slot and the separators beside it left out)."""
    out = []
    for tok in _SLOT.sub(SENT_OPEN + "0" + SENT_CLOSE, value or "").split():
        for seg in _SENT.split(tok)[::2]:
            core = _EDGE.match(seg).group(2)
            if core:
                out.append(core)
    return out


def tokens_of(parts):
    """{(kind, core)} of every class and id token in `parts` ({part: markup}): the tokens G3 counts and X1 keeps from the default."""
    found = set()
    for text in (parts or {}).values():
        for m in re.finditer(r'\b(class|id)="([^"]*)"', text if isinstance(text, str) else ""):
            found.update((m.group(1), c) for c in _cores(m.group(2)))
    return found


class _Part(html.parser.HTMLParser):
    """One part, slots replaced by sentinels, re-serialised with X1 to X5 and X8 applied."""

    def __init__(self, state):
        html.parser.HTMLParser.__init__(self, convert_charrefs=False)
        self.state, self.out, self.text, self.svg = state, [], [], False

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs, True)

    def _tag(self, tag, attrs, selfclose):
        self.flush()
        if self.svg:
            return
        if tag == "svg":                                   # X8: a decoration is never carried (to its own </svg>)
            self.svg = not selfclose
            self.state.literals += 1
            return
        kept = []
        for name, value in attrs:
            got = self.state.attr(name, value)
            if got is not None:
                kept.append(got)
        self.out.append("<%s%s%s>" % (tag, "".join(" " + a for a in kept), " /" if selfclose else ""))

    def handle_endtag(self, tag):
        self.flush()
        if self.svg:
            self.svg = tag != "svg"
            return
        self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if not self.svg:
            self.text.append(data)

    def handle_entityref(self, name):
        self.handle_data("&%s;" % name)

    def handle_charref(self, name):
        self.handle_data("&#%s;" % name)

    def flush(self):
        """X2 over the text node gathered so far: every word (a run of letters or digits) goes; punctuation, spaces, entities and
        slots stay, so a separator such as ` / ` keeps its place."""
        if not self.text:
            return
        pieces = _SENT.split("".join(self.text))
        self.text = []
        for i, piece in enumerate(pieces):
            if i % 2:
                self.out.append(SENT_OPEN + piece + SENT_CLOSE)
                continue
            kept = []
            for j, bit in enumerate(re.split(r"(&#?[A-Za-z0-9]+;)", piece)):
                words = _WORDS.findall(bit) if j % 2 == 0 else ()
                self.state.literals += len(words)
                kept.append(_WORDS.sub("", bit) if words else bit)
            self.out.append("".join(kept))


class _State(object):
    """The numbering one fragment shares across its parts (X1, X4, X5) and the count of literals removed."""

    def __init__(self, default_tokens):
        self.default, self.names, self.literals = default_tokens, {"class": {}, "id": {}, "data": {}}, 0

    def placeholder(self, kind, core):
        if (kind, core) in self.default:
            return core
        table = self.names[kind]
        if core not in table:
            table[core] = "%s%d" % ({"class": "c", "id": "i", "data": "data-d"}[kind], len(table) + 1)
        return table[core]

    def tokens(self, kind, value):
        """X1 over one class or id value, a slot joined to a token kept with its separator."""
        out = []
        for tok in value.split():
            segs = _SENT.split(tok)
            word = ""
            for i, seg in enumerate(segs):
                if i % 2:
                    word += SENT_OPEN + seg + SENT_CLOSE
                    continue
                lead, core, trail = _EDGE.match(seg).groups()
                word += lead + (self.placeholder(kind, core) if core else "") + trail
            out.append(word)
        return " ".join(out)

    def attr(self, name, value):
        """The attribute as the fragment writes it, or None when the strip removes it."""
        if name in ("class", "id"):                                                 # X1
            return '%s="%s"' % (name, _esc(self.tokens(name, value or "")))
        if name in ID_REFS or (name == "href" and (value or "").startswith("#")):  # X5
            pre = "#" if name == "href" else ""
            refs = " ".join(self.placeholder("id", t) for t in (value or "").lstrip("#").split())
            return '%s="%s%s"' % (name, pre, _esc(refs))
        if name.startswith("data-") and name not in URL_ATTRS:                     # X4
            value = value or ""
            if _SENT.sub("", value).strip():
                self.literals += 1
            return '%s="%s"' % (self.placeholder("data", name[len("data-"):]),
                                "".join(SENT_OPEN + i + SENT_CLOSE for i in _SENT.findall(value)))
        if value is None:
            return name                                     # a bare attribute (hidden, allowfullscreen, reversed)
        if not _SENT.sub("", value).strip():                # empty, or slots only (X3: a text attribute that is a slot stays)
            return '%s="%s"' % (name, _esc(value))
        closed = CLOSED_VALUES.get(name, ()) or ARIA_CLOSED.get(name, ())
        if (name in KEPT_LITERAL or (closed and all(t in closed for t in value.replace(";", " ").split()))
                or (_WHOLE.match(value) and name not in TEXT_ATTRS)):
            return '%s="%s"' % (name, _esc(value))
        self.literals += 1                          # X3, X8 (a literal address) and every other literal value: removed
        return None


def _esc(value):
    return value.replace("&", "&amp;").replace('"', "&quot;")


def _part(state, text):
    slots = []

    def sub(m):
        slots.append(m.group(0))
        return SENT_OPEN + str(len(slots) - 1) + SENT_CLOSE
    p = _Part(state)
    p.feed(_SLOT.sub(sub, text))
    p.close()
    p.flush()
    return _SENT.sub(lambda m: slots[int(m.group(1))], "".join(p.out))


def _spec(value, keys, table):
    """X6 over one `reads` value (a list of sources, or {"from", "unless"})."""
    def key(k):
        if not isinstance(k, str) or k.startswith("@") or k in keys:
            return k
        table.setdefault(k, "k%d" % (len(table) + 1))
        return table[k]
    if isinstance(value, list):
        return [key(k) for k in value]
    if isinstance(value, dict):
        return dict((m, [key(k) for k in v] if isinstance(v, list) else key(v)) for m, v in value.items())
    return value


def strip(construct, parts, reads=None, named=None, default=None):
    """The fragment of one unit: `construct` (a member of `CONSTRUCTS`; a named construct's `like`), `parts` ({part: markup}),
    `reads` ({target: value} of the entries that name it), `named` (the named construct's name, or None) and `default` (the default
    look's parts for that construct, whose tokens X1 keeps). Returns a `Stripped`."""
    state = _State(tokens_of(default))
    order = list(CONSTRUCTS.get(construct, {}).get("parts", {})) + sorted(parts or {})
    out = {}
    for pn in order:
        if pn in (parts or {}) and pn not in out:
            out[pn] = _part(state, parts[pn])
    frag = {"look": 1}
    if named is not None:
        frag["named"] = {"n1": {"like": construct, "parts": out}}             # X7
    else:
        frag["constructs"] = {construct: out}
    if reads:
        table, keys = {}, plugin_keys()
        frag["reads"] = dict((t, _spec(reads[t], keys, table)) for t in sorted(reads))
    return Stripped(frag, state.literals)


def restrip(fragment, default=None):
    """`strip` over a fragment it made (the idempotence check, and a shipped look's entry read back)."""
    reads = fragment.get("reads")
    if "named" in fragment:
        entry = fragment["named"]["n1"]
        return strip(entry["like"], entry["parts"], reads, "n1", default)
    (construct, parts), = fragment["constructs"].items()
    return strip(construct, parts, reads, None, default)
