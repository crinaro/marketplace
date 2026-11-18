#!/usr/bin/env python3
"""parity_whitespace.py -- when whitespace that exists in only one of two builds is whitespace a visitor cannot see
(template-fidelity group, G3: a newline between `</h3>` and `<p>` was counted as a visitor-visible `text` difference).
Python 3.9, standard library only. Pure functions; no I/O. `parity_classes.py` imports this module and nothing here
imports it back.

THE RULE. `parity_classes` reduces every run of whitespace between two tags to ONE whitespace token. A hunk made only
of such a token (present in one build, absent in the other at the same place) is invisible when a browser would
collapse it away, and visible otherwise. A browser collapses a whitespace run that touches the edge of a block box
(the start or end tag of a block-level element, on either side of the run) and is not preserved. So the token is
INVISIBLE only when ALL hold:

    1. the page is readable in full: nothing is loaded off-origin (an unreadable stylesheet could set `display` or
       `white-space`), and no script names `style`, `cssText`, `setProperty`, `hidden`, `display` or `white-space`;
    2. no open element around the token preserves whitespace: not `pre`, `textarea`, `listing`, `xmp`, `plaintext`,
       `script`, `style`, `svg`, `math`, `template`, a form control or an embedded object, and not an element a rule
       of either build's CSS (or its own `style` attribute) gives a `white-space` other than `normal`/`nowrap`;
    3. the tag on one side of the token is the start or end tag of a block-level element (BLOCK_ELEMENTS) that is
       still a block: no `hidden`
       attribute, no `style` attribute naming `display`, and no CSS rule of either build that could match it
       (by its last compound selector: element name, classes, id; every other part of a selector is ignored, which
       only makes a rule match MORE) sets `display` to anything but a block-level value.

Everything else is visible: between two inline elements, between text and an inline element, inside `pre`, inside an
element styled `white-space: pre*`, next to an element a stylesheet makes `display: inline`/`inline-block`/`none`.
A CSS rule whose subject names a class or id that a script also names matches any element (a script can add it).

A `rel` THAT NO VISITOR MEETS (G3 derive link 2). The other thing in this module that is not whitespace and is invisible for the same
kind of reason: a `rel` of `noopener` or `noreferrer` on an `a` or `area` that opens in the SAME window changes nothing a visitor
sees or does (`noopener` cuts the opened window's access to this one and `noreferrer` omits the Referer header; with no new window
there is nothing to cut). `rel_invisible` says so, and only so: the two tags differ in nothing but those tokens of `rel` (every other
token, `nofollow`, `me`, `author`, is read by a search engine or a browser), the target is absent or one of `_self`, `_parent`,
`_top` (a `_blank` link's opened window is reachable without `noopener`; a NAMED target is reused where it is open, and `noopener`
makes the browser open a new window instead: visible, and a conservative reading of an HTML Standard rule the author has not
tested in a browser), no `<base target>` is in either page (it would give a link with no target of its own one), no stylesheet of
either build selects on `[rel` and no script names `rel` or `relList`, and nothing is loaded off-origin. DOCUMENTED: the HTML Standard
on `rel=noopener` and `rel=noreferrer`. No token is recorded for the publish re-check, as for whitespace.

LIMITS, as for the rest of parity: the check is static and errs toward visible. A script that sets styles in a way the
regex above does not see, a selector the last-compound reading cannot match, and CSS that this module's rule parser
cannot balance (`blind`) all end in VISIBLE, never in invisible. No token is recorded for the publish re-check: the
whitespace exists only in one build's markup, and the re-check rebuilds only the plugin's.
"""
import re
from collections import namedtuple

BLOCK_ELEMENTS = frozenset("""
address article aside blockquote body caption dd details div dl dt fieldset figcaption figure footer form h1 h2 h3 h4
h5 h6 header hgroup hr html legend li main menu nav ol p pre search section summary table tbody td tfoot th thead tr
ul""".split())

PRESERVING = frozenset("""
pre textarea listing xmp plaintext script style svg math template select option datalist object canvas iframe audio
video""".split())

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())

# A `display` value that leaves the element block-level (its first word); anything else, and any `var(`, is risky.
SAFE_DISPLAY = frozenset("block flex grid list-item flow-root table table-row table-cell table-row-group "
                         "table-header-group table-footer-group table-caption".split())

_JS_STYLE = re.compile(r"\.style\b|cssText|setProperty|setAttribute\s*\(\s*[\"']style|\.hidden\b|[\"']hidden[\"']|"
                       r"display|white-?space", re.I)
_PROPERTY = re.compile(r"(?<![\w-])(display|white-space|white-space-collapse|all)\s*:\s*([^;]*)", re.I)
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_IDENT = r"(?:\\.|[\w-]|[^\x00-\x7f])+"
_CLASS = re.compile(r"\.(" + _IDENT + ")")
_ID = re.compile(r"#(" + _IDENT + ")")

WS = "<ws>"        # the line, and the `info` name, of a whitespace token (`parity_classes`)
Site = namedtuple("Site", "prev next stack")     # a whitespace token: its neighbours and the open elements around it


# ---------------------------------------------------------------- where the whitespace sits in a page

def sites(stream):
    """{index: Site} for every whitespace token of a token stream. `stream` is a list of `(line, element, attributes,
    role)` as `parity_classes._tokens` writes it: role is ("start",), ("end", element), ("text",), ("ws",) or
    ("decl",). A neighbour is ("start", element, attributes), ("end", element, the attributes of the element it
    closes or None), ("text",), ("decl",) or None at the edge. The open-element stack is read the way a browser
    reads end tags: an end tag closes the nearest open element of its name, and one that matches none closes nothing."""
    n = len(stream)
    bounds, snaps, stack = [None] * n, {}, []
    for i, (_line, name, attrs, role) in enumerate(stream):
        kind = role[0]
        if kind == "start":
            bounds[i] = ("start", name, attrs)
            if name not in VOID:
                stack.append((name, attrs))
        elif kind == "end":
            opened = None
            for j in range(len(stack) - 1, -1, -1):
                if stack[j][0] == role[1]:
                    opened = stack[j][1]
                    del stack[j:]
                    break
            bounds[i] = ("end", role[1], opened)
        elif kind == "ws":
            snaps[i] = tuple(stack)
            bounds[i] = ("ws",)
        else:
            bounds[i] = (kind,)
    return dict((i, Site(bounds[i - 1] if i > 0 else None, bounds[i + 1] if i + 1 < n else None, snap))
                for i, snap in snaps.items())


# ---------------------------------------------------------------- what the CSS can do to an element

def _rules(text):
    """[(selector text, declaration text)] for the style rules of one stylesheet, nested rules and rules inside an
    `@media`-like block included; None when its braces do not balance (the caller then reads nothing from it)."""
    text = _COMMENT.sub("", text)
    out, stack, seg, i, n = [], [], 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if c == "\\":
            i += 2
            continue
        if c == "{":
            chunk = text[seg:i]
            k = chunk.rfind(";")
            decl, head = (chunk[:k + 1], chunk[k + 1:]) if k >= 0 else ("", chunk)
            if stack and stack[-1][2]:
                stack[-1][1].append(decl)
            head = head.strip()
            stack.append([head, [], not head.startswith("@")])
            seg = i + 1
        elif c == "}":
            if not stack:
                return None
            top = stack.pop()
            top[1].append(text[seg:i])
            if top[2]:
                out.append((top[0], ";".join(top[1])))
            seg = i + 1
        i += 1
    return None if stack else out


def _split_top(text, seps):
    """`text` cut at every character of `seps` outside `()`, `[]` and quotes; the empty pieces dropped."""
    parts, depth, cur, quote, i = [], 0, [], None, 0
    while i < len(text):
        c = text[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c == "\\" and i + 1 < len(text):
            cur.append(c + text[i + 1])
            i += 1
        elif c in "\"'":
            quote = c
            cur.append(c)
        elif c in "([":
            depth += 1
            cur.append(c)
        elif c in ")]":
            depth -= 1
            cur.append(c)
        elif depth == 0 and c in seps:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _subject(selector, unescape):
    """(element name or None, {classes}, {ids}) of a selector's LAST compound: what a rule can possibly style. Anything
    the reading cannot place (nesting `&`, a namespace, an empty compound) is None, `set()`, `set()`: any element."""
    compounds = _split_top(selector, " \t\r\n\f>+~")
    last = compounds[-1] if compounds else ""
    if not last or "&" in last or "|" in last:
        return (None, frozenset(), frozenset())
    bare = last
    prev = None
    while prev != bare:                         # `:not(.x)`, `:is(a, b)`, `:nth-child(2n+1)`: they only narrow
        prev, bare = bare, re.sub(r"\([^()]*\)", "", bare)
    bare = re.sub(r"\[[^\]]*\]", "", bare)       # attribute selectors only narrow
    m = re.match(r"(\*|" + _IDENT + ")", bare)
    name = m.group(1).lower() if m and m.group(1) != "*" else None
    return (name, frozenset(unescape(c) for c in _CLASS.findall(bare)),
            frozenset(unescape(i) for i in _ID.findall(bare)))


def _matches(subject, name, attrs):
    """True when a rule with this subject could style the element: the name, every class and the id fit."""
    want_name, classes, ids = subject
    if want_name is not None and want_name != name:
        return False
    have = dict(attrs or ())
    if classes and not classes <= set((have.get("class") or "").split()):
        return False
    return not ids or (have.get("id") or "") in ids


def _risky_display(value):
    value = value.strip().lower()
    return "var(" in value or not value or value.split()[0] not in SAFE_DISPLAY


def _risky_space(prop, value):
    value = value.strip().lower().replace("!important", "").strip()
    if prop == "white-space-collapse":
        return value != "collapse"
    return value not in ("normal", "nowrap")


class Facts(object):
    """What both builds' CSS and scripts can do to whitespace. `css` is the stylesheets' RAW text (escapes intact),
    `js` the scripts' text, `external` the off-origin loads (any one makes everything unreadable), `unescape` the
    CSS escape decoder. Built once per comparison."""

    def __init__(self, css, js, external, unescape):
        self.blind = bool(external) or any(_JS_STYLE.search(t) for t in js)
        self.display, self.space = [], []
        naming = "\n".join(js)
        for text in css:
            rules = _rules(text)
            if rules is None:
                self.blind = True
                continue
            for selector, decls in rules:
                kinds = set()
                for prop, value in _PROPERTY.findall(decls):
                    prop = prop.lower()
                    if prop == "all":
                        kinds.update(("display", "space"))
                    elif prop == "display" and _risky_display(value):
                        kinds.add("display")
                    elif prop != "display" and _risky_space(prop, value):
                        kinds.add("space")
                for sel in _split_top(selector, ","):
                    subject = _subject(sel, unescape)
                    if (subject[1] or subject[2]) and any(t in naming for t in subject[1] | subject[2]):
                        subject = (None, frozenset(), frozenset())       # a script names it: it may be added anywhere
                    if "display" in kinds:
                        self.display.append(subject)
                    if "space" in kinds:
                        self.space.append(subject)

    def _styled(self, rules, name, attrs):
        return any(_matches(s, name, attrs) for s in rules)

    def _space_risky(self, name, attrs):
        style = dict(attrs or ()).get("style") or ""
        return "white-space" in style.lower() or "all:" in style.lower().replace(" ", "") or \
            self._styled(self.space, name, attrs)

    def _reliable_block(self, name, attrs):
        have = dict(attrs or ())
        style = (have.get("style") or "").lower().replace(" ", "")
        return ("hidden" not in have and "display" not in style and "all:" not in style
                and not self._styled(self.display, name, attrs))

    def invisible(self, site):
        """True when the whitespace token at `site` renders nothing (module docstring). Both tags beside it are lines
        the two builds share: a hunk of one whitespace token sits between two equal blocks of the diff, so a block
        boundary it relies on is never itself part of another difference."""
        if self.blind or site.prev is None or site.next is None:
            return False
        for name, attrs in site.stack:
            if name in PRESERVING or self._space_risky(name, attrs):
                return False
        return any(side[0] in ("start", "end") and side[1] in BLOCK_ELEMENTS and self._reliable_block(side[1], side[2])
                   for side in (site.prev, site.next))


# ---------------------------------------------------------------- a `rel` that changes nothing a visitor does

REL_NO_EFFECT = frozenset(("noopener", "noreferrer"))
SAME_WINDOW = frozenset(("_self", "_parent", "_top"))
_REL_SELECTOR = re.compile(r"\[\s*rel(?![\w-])", re.I)
_REL_SCRIPT = re.compile(r"(?<![\w-])rel(?:List)?(?![\w-])")
_LINKS = frozenset(("a", "area"))


def rel_invisible(element, local, plugin, base_target, css, js, external=False):
    """True when two tags of one link, `local` and `plugin` (their attributes as dicts), differ in nothing a visitor can see or do:
    only in the tokens `noopener` and `noreferrer` of `rel`, and the link opens in the same window (module docstring). `base_target`
    is True when either page holds a `<base target>`, `css` and `js` the text of both builds' stylesheets and scripts, `external` True
    when either build loads anything off-origin (an unreadable stylesheet could select on `rel`)."""
    if element not in _LINKS or external:
        return False
    others = [k for k in set(local) | set(plugin) if k != "rel" and local.get(k) != plugin.get(k)]
    if others or local.get("rel") == plugin.get("rel"):
        return False
    a = set((local.get("rel") or "").lower().split())
    b = set((plugin.get("rel") or "").lower().split())
    if (a ^ b) - REL_NO_EFFECT:
        return False
    target = (local.get("target") or "").strip().lower()
    if target:
        if target not in SAME_WINDOW:
            return False
    elif base_target:
        return False
    return not (any(_REL_SELECTOR.search(t) for t in css) or any(_REL_SCRIPT.search(t) for t in js))


def hunk_invisible(facts, ia, ib, i1, i2, j1, j2):
    """True when a hunk (lines `i1:i2` of the local build, `j1:j2` of the plugin build, `ia` and `ib` the pages' aligned
    `info` lists) is exactly one whitespace token, present in one build and absent in the other, and `facts` says a
    browser collapses it. Only the build that holds the token says where it sits."""
    if ia is None or ib is None or (i2 - i1) + (j2 - j1) != 1:
        return False
    entry = ia[i1] if i2 > i1 else ib[j1]
    return entry is not None and entry[0] == WS and facts.invisible(entry[1])
