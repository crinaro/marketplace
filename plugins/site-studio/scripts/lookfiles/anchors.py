"""Finding where a recorded part sits in a page: the items of a slot value, the needles a part's values give, and the tests that say whether
an element holds them (TEXT ANCHORING, design R5.4(f))."""

import looks
import re
from contentmodel import links
from lookfiles.pagedom import (
    El,
    Tx,
    _NOT_TEXT_ATTRS,
    _PH,
    _PH_CLOSE,
    _PH_OPEN,
    _SLOT,
    _STOP_UP,
    _URL_ATTRS,
    is_ws,
    parse_dom,
    ser,
    squash,
    text_of,
    walk,
)
from lookfiles.renderlog import LIST_SEP, kids_of


# ================================================================================================= the derivation
class _Fail(Exception):
    """One instance could not be anchored or templated; `status` is `unmapped` or `ambiguous`."""

    def __init__(self, status, why):
        Exception.__init__(self, why)
        self.status, self.why = status, why
        self.where = None               # (page, anchors) when the instance WAS anchored and then could not be read as a template


def _value_items(call, slot):
    """The top-level items of html slot `slot` of `call`: [("el", tag, squashed text) | ("tx", squashed text) |
    ("kid", Call) | ("wild", n)], or raises _Fail where a child sits inside Markdown markup (not at the top of its
    slot) or the markup cannot be read."""
    memo = call.cache.get(("items", slot))
    if memo is not None:
        if isinstance(memo, _Fail):
            raise memo
        return memo
    try:
        items = _value_items_uncached(call, slot)
    except _Fail as e:
        call.cache[("items", slot)] = e
        raise
    call.cache[("items", slot)] = items
    return items


def _value_items_uncached(call, slot):
    return _parse_items(call.segments.get(slot) or [("text", call.values.get(slot) or "")])


def _out_items(call):
    """The top-level items of the part's own output (a part that writes several sibling elements): its template is
    walked, a slot at the top of it (outside every element) contributes its own segments, so a child there is marked,
    and every other slot is its rendered value."""
    memo = call.cache.get("out-items")
    if memo is None:
        tmpl = call.template
        probe = parse_dom(_SLOT.sub(lambda m: "" + m.group(1) + "", tmpl))
        top = set(re.findall("([a-z0-9]+)", "".join(k.data for k in probe.kids if isinstance(k, Tx))))
        segs, pos = [], 0
        for m in _SLOT.finditer(tmpl):
            if m.start() > pos:
                segs.append(("text", tmpl[pos:m.start()]))
            pos = m.end()
            name, kind, v = m.group(1), call.table.get(m.group(1)), call.values.get(m.group(1))
            if v is None or v == "":
                continue
            if kind == looks.HTML and name in top:
                segs.extend(call.segments.get(name) or [("text", str(v))])
            elif kind == looks.HTML or kind == looks.INT:
                segs.append(("text", str(v)))
            else:
                segs.append(("text", links.esc(str(v))))
        if pos < len(tmpl):
            segs.append(("text", tmpl[pos:]))
        memo = call.cache["out-items"] = _parse_items(segs)
    return memo


def _parse_items(segs):
    kids, text = [], []
    for kind, payload in segs:
        if kind == "text":
            text.append(payload)
        else:
            kids.append(payload)
            text.append(_PH_OPEN + str(len(kids) - 1) + _PH_CLOSE)
    root = parse_dom("".join(text))
    items = []
    for n in root.kids:
        if isinstance(n, El):
            if n.tag in ("link", "script"):     # the plugin's own asset tag (blocks.css, video.js): a look names its own
                continue
            if _PH.search(text_of(n)):
                raise _Fail("unmapped", "a construct is used inside Markdown text, not at the top of its slot")
            items.append(("el", n.tag, squash(text_of(n))))
            continue
        data = n.data
        pos = 0
        for m in _PH.finditer(data):
            if data[pos:m.start()].strip():
                raise _Fail("unmapped", "a construct is used inside a line of Markdown text")
            items.append(("kid", kids[int(m.group(1))]))
            pos = m.end()
        rest = data[pos:]
        if rest.strip():
            items.append(("tx", squash(rest), rest))
    return items


def _own_needles(call):
    """(hard text needles, soft url needles) of `call`'s own values: text slots, the text of an html slot's own
    fragments (never its children's), and the url-kind values."""
    if "own" in call.cache:
        return call.cache["own"]
    hard, soft, opt = [], [], []
    for slot in call.slot_order():
        v = call.values.get(slot)
        kind = call.table[slot]
        if v is None or v == "":
            continue
        if kind == looks.TEXT:
            s = squash(str(v))
            if s:
                # a value the recording look writes into an attribute only (a label, an alt) may not be on the page at
                # all (the template has no such attribute), and a word of it found elsewhere must not pull the anchor out;
                # a list the page may join its own way (`LIST_SEP`) is looked for item by item
                items = [x for x in (squash(i) for i in s.split(LIST_SEP)) if x] if LIST_SEP in s else [s]
                (opt if slot in call.attr_only else hard).extend(items)
        elif kind == looks.HTML:
            for it in _items_or_empty(call, slot):
                if it[0] == "el" and it[2]:
                    hard.append(it[2])
                elif it[0] == "tx" and it[1]:
                    hard.append(it[1])
        elif kind in (looks.URL, looks.CONTACT, looks.SRCSET, looks.EMBED):
            soft.append(str(v).strip())
    call.cache["own"] = (hard, soft)
    call.cache["own-opt"] = opt
    return hard, soft


def _int_needles(call):
    return [str(call.values[s]) for s in call.slot_order()
            if call.table[s] == looks.INT and call.values.get(s) not in (None, "")]


def _items_or_empty(call, slot):
    try:
        return _value_items(call, slot)
    except _Fail:
        return []


def _full_needles(call):
    if "full" in call.cache:
        return call.cache["full"]
    hard, soft = _own_needles(call)
    hard, soft = list(hard), list(soft)
    attr_only = not hard
    for k in kids_of(call):
        h, s = _full_needles(k)
        hard += h
        soft += s
        attr_only = attr_only and (not h or k.cache["attr-only"])
    if not hard:
        hard = list(call.cache["own-opt"])      # nothing else at or under this part to anchor on: its attribute values
    call.cache["full"] = (hard, soft)
    call.cache["attr-only"] = bool(hard) and attr_only
    return hard, soft


def _attr_only(call):
    """Does `call` anchor only on values the recording look writes into attributes (a picture's alt, at or under it)? Such a part is the
    element that also carries its address: the same words as a heading's text are not the picture (dev #941)."""
    _full_needles(call)
    return call.cache["attr-only"]


def _tops(call):
    """How many sibling nodes the part's own output holds at the top (a list item is one; the home page's intro and
    its endorsement are two)."""
    n = call.cache.get("tops")
    if n is None:
        n = call.cache["tops"] = len([k for k in parse_dom(call.out).kids if not is_ws(k)])
    return n


def _fixed_beside(call):
    """The element names of the FIXED elements the plugin's own markup for `call` writes in one element beside a slot: `['h2']` for
    `<section class="featured"><h2>Featured</h2>{{cards}}</section>`, `[]` for a part with none. A list of one carries nothing but
    that heading to say its section is the part's, so a wrapper holding the extent and exactly these elements is a reading of the
    part (`_read_variants`); the element names must agree, so a card's sibling card is never taken for one."""
    got = call.cache.get("beside")
    if got is None:
        got = []
        for el in walk(parse_dom(call.template)):
            if any(isinstance(k, Tx) and _SLOT.search(k.data) for k in el.kids):
                names = sorted(k.tag for k in el.kids if isinstance(k, El) and not _SLOT.search(ser(k)))
                if len(names) > len(got):
                    got = names
        call.cache["beside"] = got
    return got


def _is_wild(call):
    """A part nothing can be searched for: no text, no url, no number (a fixed heading). It is placed by its
    neighbours."""
    h, s = _full_needles(call)
    return not (h or s or _int_needles(call))


_SHARE = "two instances of one construct share one element"


def _above(a, b):
    """Is `a` a proper ancestor of `b`?"""
    p = b.parent
    while p is not None:
        if p is a:
            return True
        p = p.parent
    return False


def _node_holds(page, node, needle):
    """Does this child (a text node, or an element and what is under it) hold `needle`?"""
    if isinstance(node, Tx):
        s = squash(node.data)
        return s == needle if len(needle) < 2 else needle in s
    return isinstance(node, El) and _holds(page, node, [needle])


def _has_nested(needles):
    """True when one needle is only a part of another (a label "Client" and a value "Invented Client")."""
    ns = set(n for n in needles if len(n) >= 2)
    return any(a != b and a in b for a in ns for b in ns)


def _holds_apart(page, el, hard):
    """Does `el` hold every needle at a place of its own? A needle that is only a part of a longer needle ("Client" inside "Invented
    Client") is not held by the longer value alone: the longer needles take their occurrence out of the text first (and out of each
    attribute value), and the shorter ones must still be found in what is left."""
    pool = [page.stext(el)] + [sq for _k, sq, _raw in page.attrs(el)]
    for n in sorted(set(hard), key=lambda s: (-len(s), s)):
        if len(n) < 2:
            if n not in page.words(el):
                return False
            continue
        for i, s in enumerate(pool):
            j = s.find(n)
            if j >= 0:
                pool[i] = s[:j] + "\x00" + s[j + len(n):]
                break
        else:
            return False
    return True


def _holds(page, el, hard, apart=False):
    if apart:
        return _holds_apart(page, el, hard)
    stext = page.stext(el)
    attrs = None
    for n in hard:
        if len(n) < 2:
            if n not in page.words(el):
                return False
            continue
        if n in stext:
            continue
        if attrs is None:
            attrs = page.attrs(el)
        if not any(n in sq for _k, sq, _raw in attrs):
            return False
    return True


def _has_url(page, el, url):
    return any(k in _URL_ATTRS and (raw == url or url in [c.split()[0] for c in raw.split(",") if c.split()])
               for k, _sq, raw in page.attrs(el))


def _can_go(up, bound):
    """May an extent grow to `up`? Not past the document, and, inside a parent, only to a proper descendant of the
    parent's own extent `bound`."""
    if up is None or up.tag in _STOP_UP:
        return False
    if bound is None:
        return True
    p = up.parent
    while p is not None:
        if p is bound:
            return True
        p = p.parent
    return False


def _widened(page, scope, el, hard, bound):
    """The extent a candidate `el` grows to where the page SHOWS a value as text beside it that `el` holds only in an attribute (a
    video's title is the `title` of its iframe and the words of the caption beside it; a play link's `aria-label` repeats the caption
    next to it): the lowest ancestor, within three levels and `bound`, whose text holds those values too. `el` itself when none is
    needed, or none reaches. A value the page shows nowhere as text is left to the attribute (the lowest element still holds it)."""
    lone = [n for n in hard if len(n) >= 2 and n not in page.stext(el) and n in page.stext(scope)]
    top, hops = el, 0
    while lone and not all(n in page.stext(top) for n in lone):
        up = top.parent
        if hops == 3 or not _can_go(up, bound):
            return el
        top, hops = up, hops + 1
    return top


_SUBST_SKIP = frozenset(n for n in _NOT_TEXT_ATTRS if n not in ("class", "id"))


def _word_pattern(value):
    """A pattern for `value` as a whole word (or words) in a page: whitespace between its words is any whitespace,
    and it is not part of a longer word. A one-character value is looked for as the whole of a text or an attribute
    value only, never as a letter inside other text. None for no value at all."""
    words = value.split()
    if not words or not squash(value):
        return None
    if len(squash(value)) < 2:
        return re.compile(r"^(\s*)" + re.escape(words[0]) + r"(\s*)$")
    return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in words) + r"(?![A-Za-z0-9])")


def _list_pattern(value):
    """A pattern for a `LIST_SEP` value in a page: its items as whole words, in order, with one separator between them that is
    the same every time (group `sep`: a short run of anything but letters, digits and tags, such as ", " or " / "). None when the
    value holds fewer than two items."""
    items = [i.split() for i in value.split(LIST_SEP)]
    if len(items) < 2 or not all(items):
        return None
    words = [r"\s+".join(re.escape(w) for w in ws) for ws in items]
    body =words[0] + r"(?P<sep>[^A-Za-z0-9<>]{1,8}?)" + words[1] + "".join(r"(?P=sep)" + w for w in words[2:])
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])")


def _sub_slot(pat, slot, text):
    """`text` with `slot` written where `pat` matched (keeping the space around a whole-value match)."""
    marker = "{{%s}}" % slot
    if pat.groups:
        return pat.sub(lambda m: m.group(1) + marker + m.group(2), text)
    return pat.sub(marker, text)
