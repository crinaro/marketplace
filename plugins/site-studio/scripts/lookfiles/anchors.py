"""Finding where a recorded part sits in a page: the items of a slot value, the needles a part's values give, and the tests that say whether
an element holds them (TEXT ANCHORING, design R5.4(f))."""

import looks
import posixpath
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


_SEP_TEXT = re.compile(r"^[^A-Za-z0-9<>]{1,8}$")


def _is_sep(text):
    """Is `text`, between two parts at the top of an html slot, a separator the build writes between them (` / ` between a card's
    two numbers, `portfolios.card_html`) rather than a line of words? A short run of anything but letters, digits and tags."""
    return bool(text.strip()) and bool(_SEP_TEXT.match(text.strip()))


def _parse_items(segs):
    """The top-level items of a slot's segments. Text between parts at the top is a line of Markdown text holding a construct, which
    no template can read, except a separator (`_is_sep`) the build writes between two parts: that is an item of its own (step 12,
    the card number `02 / 2024` of design-adopt-parity-2 section 9's `-a`)."""
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
            between = data[pos:m.start()]
            if between.strip():
                if not (pos and _is_sep(between)):
                    raise _Fail("unmapped", "a construct is used inside a line of Markdown text")
                items.append(("tx", squash(between), between))
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
                elif it[0] == "tx" and it[1] and not _is_sep(it[1]):
                    hard.append(it[1])
        elif kind in (looks.URL, looks.CONTACT, looks.SRCSET, looks.EMBED):
            soft.append(str(v).strip())
    call.cache["own"] = (hard, soft)
    call.cache["own-opt"] = opt
    return hard, soft


def _unit_after(call):
    """(slot, number) of the TEXT slot the recording look writes right after a number, `{{n}} {{unit}}`, when the build gave it no value (a group count
    whose word site.json cannot hold: design-adopt-parity-2 section 4.2, owner decision 4), else None. Where the page writes a word
    there, that word stands in the place of the slot: the part is still the page's number and its word (step 12)."""
    if "unit" not in call.cache:
        got = None
        for m in re.finditer(r"\{\{(\w+)\}\}\s+\{\{(\w+)\}\}", call.template):
            num, word = m.group(1), m.group(2)
            if call.table.get(num) == looks.INT and call.table.get(word) == looks.TEXT and call.values.get(word) == "" \
                    and call.values.get(num) not in (None, ""):
                got = (word, str(call.values[num]))
                break
        call.cache["unit"] = got
    return call.cache["unit"]


_NUMBER_WORDS = r"^%s\s+([^\W\d][^<>\d]*)$"


def _number_then_words(text, number):
    """Is `text` the number `number` followed by a word or words (`2 projects`), and nothing else?"""
    return re.match(_NUMBER_WORDS % re.escape(number), text) is not None


def _unit_slot(root, slot, number):
    """Write `slot` in place of the words after `number` in the text node that is the number and its words. True if it did."""
    for el in walk(root):
        for i, k in enumerate(el.kids):
            if isinstance(k, Tx) and _number_then_words(" ".join(k.data.split()), number):
                m = re.search(r"(%s\s+)(\S.*?)(\s*)$" % re.escape(number), k.data, re.S)
                t = Tx(k.data[:m.start(2)] + "{{%s}}" % slot + k.data[m.end(2):])
                t.parent = el
                el.kids[i] = t
                return True
    return False


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
        if not any(_attr_holds(k, sq, raw, n) for k, sq, raw in attrs):
            return False
    return True


def _attr_holds(name, sq, raw, needle):
    """Does one attribute (its name, squashed and stripped value) hold `needle`? A class token's tail after a joint is a hook the
    template writes, not a place the page shows a value (R-G: `<ul class="t-grid-Print">` does not hold a group whose title is
    `Print`; the group is the heading and the list)."""
    if needle not in sq:
        return False
    return name != "class" or any(needle in tok and not _is_tail(tok, needle) for tok in raw.split())


def _resolved(page_key, url):
    """The site path a relative address names from the page `page_key` (`work/index.html`), with `index.html` and a trailing `/`
    read as one; None for an address that is not relative (a scheme, `//`, `/`, `#`, `?`, or none at all)."""
    url = (url or "").strip()
    if not url or url.startswith(("/", "#", "?")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url):
        return None
    path = url.split("#")[0].split("?")[0]
    here = posixpath.dirname(page_key or "")
    out = posixpath.normpath(posixpath.join(here, path)) if path else posixpath.normpath(here or ".")
    if out.startswith(".."):
        return None
    if out.endswith("/index.html") or out == "index.html":
        out = posixpath.dirname(out)
    return "" if out == "." else out


def same_target(page_key, a, b):
    """Do the relative addresses `a` and `b`, written on the page `page_key`, name the same page (`./` and `../work/` on
    `work/index.html`)? Their query and fragment must agree too."""
    tail = lambda u: (u.split("#", 1)[1] if "#" in u else "", u.split("#")[0].split("?", 1)[1] if "?" in u.split("#")[0] else "")  # noqa: E731
    ra, rb = _resolved(page_key, a), _resolved(page_key, b)
    return ra is not None and ra == rb and tail(a.strip()) == tail(b.strip())


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


# R-G (design-adopt-ownership-line section 7): the open text slots a page may write as the TAIL of a class token, after a `-` or `_`
# (`t-grid-{{group}}`). Another slot's value there is a coincidence with a fixed class (a group whose title and key are both `Print`).
CLASS_TAIL_SLOTS = {("cards", "wrap"): ("group",), ("group", "wrap"): ("group",), ("piece", "wrap"): ("slug", "portfolio", "group"),
                    ("portfolio", "wrap"): ("slug",)}
JOINTS = ("-", "_")


def class_tail_slots(construct, part):
    """The slots of a part a class token's tail may hold (`CLASS_TAIL_SLOTS`), () for any other part."""
    return CLASS_TAIL_SLOTS.get((construct, part), ())


def _is_tail(token, value):
    """Is `value` the whole tail of the class token `token` after a joint (`Print` of `t-grid-Print`)?"""
    return any(token.endswith(j + value) and len(token) > len(value) + 1 for j in JOINTS)


def _other_forms(value):
    """The other forms a page may write a value in as a class token's tail: lower case, and lower case with its spaces as `-`."""
    low = value.lower()
    return set((low, re.sub(r"[^a-z0-9]+", "-", low).strip("-"))) - set(("", value))


def class_sub(val, slot, value, pat, tail_ok):
    """The class attribute value `val` with `slot` written where `value` stands, or `val` unchanged. A value that is the whole tail of
    a token after a joint (R-G) is the slot only for a part's open tail slot (`tail_ok`) and a value of two characters or more,
    exactly as written; it stays literal for any other slot. Elsewhere in a token a value of three characters or more is the slot, as
    every earlier release read it. Raises _Fail where an open tail slot's value is a token's tail only in another form
    (`t-grid-print` for `Print`): no template can write it so."""
    marker, out, exact = "{{%s}}" % slot, [], False
    if re.search(r"\s", value.strip()):             # words: never one token, so never a tail (as every earlier release read it)
        out.append(_sub_slot(pat, slot, val) if len(squash(value)) >= 3 and pat.search(val) else val)
    else:
        for tok in re.split(r"(\s+)", val):
            if tok and not tok.isspace() and _is_tail(tok, value):
                exact = True
                tok = tok[:len(tok) - len(value)] + marker if tail_ok and len(value) >= 2 else tok
            elif tok and not tok.isspace() and len(squash(value)) >= 3 and pat.search(tok):
                tok = _sub_slot(pat, slot, tok)
            out.append(tok)
    if tail_ok and not exact and any(_is_tail(t, f) for t in val.split() for f in _other_forms(value)):
        raise _Fail("unmapped", "the page holds this %s's value only in another form" % slot)
    return "".join(out)
