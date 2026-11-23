"""R-A (design-adopt-ownership-line section 7, dev 1006 section 2): the element that carries a part's own address is that part's.

A part with a `url` slot of its own (`card.wrap`) is the element that holds that address and everything inside it: a card whose class
is on its anchor (`<li><a class="t-card" href>`) holds a frame and a label span inside the anchor, and the label span holds every
word a list of ONE shows, so the list would anchor there and read its template inside its own card. Such a reading is never the
parent's: where the parent anchors inside a child's address element it is read from that element instead (`lifted`, from
`_Derivation._one_read`), as every earlier release read a list of one whose words the anchor itself holds; the child read inside that
element may be the element itself (`bound_for`, from `_Derivation._kids_in`), so the single-child wrapper above it (the `li`) is
still offered both ways and decided by count; and a parent reading whose root lies inside that element is refused (`refuse`, from
`_Derivation._kids_in`).

R-F (design-adopt-ownership-line section 7, the frame of design 2.4's `card.wrap`): a wrapper the page prints EMPTY is the parent's.
A part with nothing to show prints nothing (an html slot that holds nothing expands to nothing, `templatemerge._expand`), so where
the page holds an element with exactly the start tag of the single-child wrapper above a part, and nothing in it, inside an element
of the same tag and class as the wrapper's own parent (the frame of a card with no cover, beside the frames that hold a picture),
that wrapper is markup the parent prints whether the part is there or not: it is never offered as the part's own
(`printed_empty`, from `_Derivation._read_variants`). Where no such empty twin is on the page, the wrapper is offered both ways as
before, so a wrapper that really is the picture's own (absent with the picture) still reads as the picture's.
"""

import looks
from lookfiles.anchors import _Fail
from lookfiles.pagedom import El, is_ws, walk


def own_address(call):
    """The address a part carries of its own: its `url` slot's value, or None (a part with no such slot, or none set)."""
    if call.table.get("url") != looks.URL:
        return None
    value = call.values.get("url")
    return str(value).strip() if value not in (None, "") else None


def _carries(el, url):
    """Does the element ITSELF (not what is under it) carry `url` as its `href`?"""
    return isinstance(el, El) and any(k == "href" and (v or "").strip() == url for k, v in el.attrs)


def holder(kids, el):
    """The nearest element at or above `el` that carries the own address of one of `kids`, or None."""
    urls = set(u for u in (own_address(k) for k in kids) if u)
    while urls and el is not None:
        if any(_carries(el, u) for u in urls):
            return el
        el = el.parent
    return None


def lifted(kids, r0):
    """Where a parent whose children are `kids` is read from when it anchors at `r0`: the element that carries a child's own address
    when `r0` lies inside it, else `r0` itself."""
    got = holder(kids, r0)
    return got if got is not None and got is not r0 else r0


def bound_for(kid, r):
    """The bound a child is read inside `r` with: `r`'s parent where `r` itself carries the child's own address (so the child's
    extent can be that element, which is the child's), else `r`."""
    url = own_address(kid)
    return r.parent if url and _carries(r, url) and r.parent is not None else r


def refuse(kids, r):
    """Raise _Fail when `r`, a parent's root, lies INSIDE the element that carries one of `kids`' own address. The element itself is
    not refused: the child fills it and the parent moves up from it, and a reference card the page writes as a bare link is read
    as runs of that link where the place holds nothing else (measured: refusing it lost `DeriveTheHomeWrapAndAListOfOne`'s home)."""
    got = holder(kids, r)
    if got is not None and got is not r:
        raise _Fail("unmapped", "the page holds this part inside the element that carries a part's own address, which is that part's")


def _shape(el):
    """An element's tag and class: what two instances of one parent share where their addresses differ."""
    return (el.tag, dict(el.attrs).get("class")) if isinstance(el, El) else None


def empty_shapes(root):
    """{(start tag, the parent's shape)} of every element under `root` that holds nothing (no element, no text but white space)."""
    out = set()
    for el in walk(root):
        if el is not root and isinstance(el, El) and el.raw is None and all(is_ws(k) for k in el.kids):
            out.add(((el.tag, tuple(el.attrs)), _shape(el.parent)))
    return out


def printed_empty(shapes, wrapper):
    """R-F: is `wrapper` (a single-child wrapper above a part) printed EMPTY elsewhere on its page, inside an element shaped like its
    own parent? `shapes` is `empty_shapes` of that page. Then the wrapper is the parent's, never the part's."""
    return isinstance(wrapper, El) and ((wrapper.tag, tuple(wrapper.attrs)), _shape(wrapper.parent)) in shapes
