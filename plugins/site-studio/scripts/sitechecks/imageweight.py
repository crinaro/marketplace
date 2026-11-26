"""imageweight.py -- what the images of one page weigh, for the `performance` family (design-publish-preflight section 5.1; dev 1068).

0.9.0 costed an image as its largest candidate up to 1440 px wide and added every image of a page into one sum, lazy images
included. This module costs an image by the SLOT it fills and keeps the lazy images apart:

  slot width   the `sizes` attribute read at two screens, a 1440 px wide one at a pixel ratio of 2 and a 390 px wide one at 3. The
               first entry whose media condition is true wins (https://html.spec.whatwg.org/multipage/images.html). A media condition
               is `(min-width: N)` or `(max-width: N)` in px, em or rem, joined by `and`; a length is px, em, rem, vw or a `calc()`
               of those. ANYTHING ELSE reads as 100vw, for the whole attribute (OURS: a slot that cannot be read is taken as wide
               as it can be, never as narrow). A missing `sizes` is 100vw too (UNDETERMINED in the HTML text, which is why the
               next line holds).
  candidate    the smallest one at least `slot width x ratio` wide, else the largest; the screen that fetches the heavier file
               sets the cost.
  THE COST IS THE LOWER of that and 0.9.0's (its largest candidate up to 1440 px). So no image costs more than it did.
  THE SUM IS KEYED BY 0.9.0's FILE. 0.9.0 counted a file once however many images used it. Keying by the file this image would
               have cost under 0.9.0 (its `legacy_pick`), each key at the heaviest cost any of its images has, keeps that: a page
               never weighs more than 0.9.0 weighed it, because every key's cost is at most that file's size and no key is new.
               Keyed by the file the slot picked instead, two images that shared one big file could each pick a smaller
               file of their own and weigh more together (found while writing the property test, not argued).
               This is what "never newly refused" rests on (`tests/sitechecks/test_imageweight.py`, a property over 400 seeded
               pages, and `tests/test_gate_only_looser.py` against 0.9.0's own gate).

A page is weighed three ways: `first` (an image that is not lazy, and the page's first image), `eager` (the images that are not lazy)
and `lazy` (the images marked `loading="lazy"`, the first one included). `budgets.py` holds each against its limit.

An `images` list is `[{"cands": [(width, file)], "sizes": str or None, "lazy": bool, "first": bool}]`, `size_of` maps a file to its
bytes. Pure: no tree, no config, no clock.
"""

import re

SCREENS = ((1440, 2), (390, 3))        # (viewport px, device pixel ratio): a desktop at 2x and a phone at 3x
LEGACY_CAP = 1440                      # 0.9.0's ceiling; the lower-of keeps it
_EM = 16.0                             # an em and a rem are 16 px here: a stylesheet that changes the root size is not read

_TOKEN = re.compile(r"\s*(\d*\.?\d+(?:px|rem|em|vw)?|[()+\-*/])", re.I)
_COND = re.compile(r"^\(\s*(min|max)-width\s*:\s*(\d*\.?\d+)(px|rem|em)\s*\)$", re.I)


class _Unread(ValueError):
    """The `sizes` text holds something this module does not read: the caller takes 100vw."""


def _split_top(text, sep=","):
    out, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _number(tok, viewport):
    """(value in px, dimension) of one token: dimension 1 for a length, 0 for a plain number."""
    m = re.match(r"^(\d*\.?\d+)(px|rem|em|vw)?$", tok, re.I)
    n = float(m.group(1))
    unit = m.group(2) and m.group(2).lower()
    if unit is None:
        return n, 0
    return n * {"px": 1.0, "rem": _EM, "em": _EM, "vw": viewport / 100.0}[unit], 1


class _Calc(object):
    """`calc()` over lengths and plain numbers: + - * / and parentheses; raises `_Unread` for anything it cannot read."""

    def __init__(self, text, viewport):
        self.toks = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m:
                raise _Unread()
            self.toks.append(m.group(1))
            pos = m.end()
        self.i = 0
        self.vp = viewport

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def expr(self):
        v, d = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            w, e = self.term()
            if e != d:
                raise _Unread()
            v = v + w if op == "+" else v - w
        return v, d

    def term(self):
        v, d = self.factor()
        while self.peek() in ("*", "/"):
            op = self.take()
            w, e = self.factor()
            if op == "*":
                if d and e:
                    raise _Unread()
                v, d = v * w, d + e
            else:
                if e > d or w == 0:
                    raise _Unread()
                v, d = v / w, d - e
        return v, d

    def factor(self):
        t = self.take()
        if t is None:
            raise _Unread()
        if t == "(":
            v, d = self.expr()
            if self.take() != ")":
                raise _Unread()
            return v, d
        if t == "-":
            v, d = self.factor()
            return -v, d
        if t in (")", "+", "*", "/"):
            raise _Unread()
        return _number(t, self.vp)

    def value(self):
        v, d = self.expr()
        if self.peek() is not None or d != 1:
            raise _Unread()
        return v


def _length(text, viewport):
    text = text.strip()
    m = re.match(r"^calc\((.*)\)$", text, re.I | re.S)
    if m:
        return _Calc(m.group(1), viewport).value()
    if not re.match(r"^\d*\.?\d+(px|rem|em|vw)$", text, re.I):
        raise _Unread()
    return _number(text, viewport)[0]


def _entry(text):
    """(conditions, length text) of one `sizes` entry; conditions is a list of ("min" or "max", px)."""
    text = text.strip()
    conds = []
    while text.startswith("("):
        depth = 0
        for i, ch in enumerate(text):
            depth += (ch == "(") - (ch == ")")
            if depth == 0:
                break
        else:
            raise _Unread()
        m = _COND.match(text[:i + 1])
        if not m:
            raise _Unread()
        conds.append((m.group(1).lower(), float(m.group(2)) * {"px": 1.0, "rem": _EM, "em": _EM}[m.group(3).lower()]))
        text = text[i + 1:].lstrip()
        if text[:4].lower() == "and ":
            text = text[4:].lstrip()
        elif text.startswith("("):
            raise _Unread()
    return conds, text


def slot_width(sizes, viewport):
    """The width in px that `sizes` gives an image on a screen `viewport` px wide; 100vw when `sizes` is missing, has no entry
    that applies, or holds anything this module does not read."""
    full = float(viewport)
    if not sizes or not sizes.strip():
        return full
    try:
        for part in _split_top(sizes):
            conds, length = _entry(part)
            if all((viewport >= px) if kind == "min" else (viewport <= px) for kind, px in conds):
                w = _length(length, viewport)
                return w if w > 0 else full
    except (_Unread, ValueError, ZeroDivisionError, TypeError):
        return full
    return full


def legacy_pick(cands):
    """0.9.0's candidate: the widest up to LEGACY_CAP, else the narrowest. `cands` is [(width, file)], not empty."""
    under = [c for c in cands if c[0] <= LEGACY_CAP] or [min(cands)]
    return max(under)


def slot_pick(cands, want):
    """The candidate for a wanted width: the narrowest at least that wide, else the widest."""
    wide = [c for c in cands if c[0] >= want]
    return min(wide) if wide else max(cands)


def image_cost(cands, sizes, size_of):
    """(key, bytes) of one image: `key` is the file 0.9.0 would have costed (the sum counts a key once), `bytes` the lower of 0.9.0's
    cost and the slot-width cost (the heavier of the two screens). (None, 0) when the image has no candidate."""
    if not cands:
        return None, 0
    old = legacy_pick(cands)[1]
    slot = max(size_of[slot_pick(cands, slot_width(sizes, vp) * dpr)[1]] for vp, dpr in SCREENS)
    return old, min(size_of[old], slot)


def weigh_page(images, size_of):
    """{"first", "eager", "lazy"}: bytes over the keys of the images each rule counts, each key at its heaviest image (the module
    docstring)."""
    parts = {"first": {}, "eager": {}, "lazy": {}}
    for im in images:
        key, cost = image_cost(im["cands"], im.get("sizes"), size_of)
        if key is None:
            continue
        wanted = (["first"] if im["first"] or not im["lazy"] else []) + (["lazy"] if im["lazy"] else ["eager"])
        for name in wanted:
            parts[name][key] = max(cost, parts[name].get(key, 0))
    return dict((k, sum(v.values())) for k, v in parts.items())
