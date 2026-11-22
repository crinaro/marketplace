"""The recording: every `looks.render` call a build makes, linked into a tree of parts (a call is the child of the call whose html slot holds
its output), which is what derive looks for in the published pages."""

import collections
import contextlib
import looks
from building import grouping, navparts, running, stepsview
from lookfiles import places as place_tables
from lookfiles.pagedom import _SLOT
from lookfiles.refusals import LookCommandError


# ================================================================================================== the recording
# A list value the build joins with a separator the site's look may name (`steps-view.role-sep`, step G O2) is recorded joined with
# this private-use character instead, so derive can tell the items apart and read the separator the page writes between them.
LIST_SEP = ""
LIST_SEP_PARTS = {("steps-view", "role"): "role-sep"}
# The places whose picture may render through a part of their own (step G O3): a site-wide `image` call made for one of these is read as
# that place's `image` part, so a template that writes the step's or the home tile's `<img>` its own way derives it there. Read from
# `lookgrammar.constructs.PLACE_PARTS` (`lookfiles.places.picture_places`, step 12): one table for the build, derive and `looks.needs`.


class Call(object):
    """One `looks.render` call: what was rendered, from which values, with what result."""

    def __init__(self, idx, construct, part, values, out, look=None):
        self.idx, self.construct, self.part, self.out = idx, construct, part, out
        self.values = dict(values)
        self.table = looks.CONSTRUCTS[construct]["parts"][part]
        self.parent = None
        self.own = None                 # the optional part a nav item's state renders through where the look writes it (`places`)
        self.segments = {}              # html slot -> [("text", html) | ("kid", Call)]
        self.cache = {}                 # memo of items and needles (a Call is read many times while anchoring)
        try:
            text = looks.part_markup(construct, part, look)
        except looks.LookError:
            text = ""
        self.template = text            # the recording look's markup for this part
        used, in_text = [], set()
        # a gated slot (rule L3a) filled with "" writes nothing into the page, so the page does not show it
        empty_gated = set(s for s in looks.gated_slots(construct, part) if not self.values.get(s))
        for m in _SLOT.finditer(text):
            if m.group(1) in self.table and m.group(1) not in used and m.group(1) not in empty_gated:
                used.append(m.group(1))
            if text.rfind("<", 0, m.start()) <= text.rfind(">", 0, m.start()):
                in_text.add(m.group(1))     # not inside a tag: the slot's value is page text
        self.used = used                # the slots the recording look wrote into the page, in its order
        self.attr_only = frozenset(s for s in used if s not in in_text)   # written into attributes only (aria-label, alt, ...)

    @property
    def key(self):
        return (self.construct, self.part)

    def slot_order(self):
        """The slots the page shows (the recording look's own): only these can be searched for in a page."""
        return list(self.used)

    def all_slots(self):
        """The slots the page shows, then the ones it may carry as markup (a class token, a data attribute)."""
        return list(self.used) + [s for s in self.table if s not in self.used]

    def as_part(self, construct, part):
        """Read this call as `construct.part`, a part of its own for its place or state (`lookfiles.places`): the same values and the
        same recorded markup (the recording look writes no such part), under that part's slot table."""
        if not hasattr(self, "recorded"):
            self.recorded = (self.construct, self.part, self.table)
        self.construct, self.part = construct, part
        self.table = looks.CONSTRUCTS[construct]["parts"][part]

    def as_recorded(self):
        """Undo `as_part`: the call is the part it was recorded as."""
        if hasattr(self, "recorded"):
            self.construct, self.part, self.table = self.recorded

    def as_place(self, construct):
        """Read this site-wide `image` call as `construct`'s own picture part (`places.picture_places`)."""
        self.as_part(construct, "image")

    def as_site(self):
        """Undo `as_place`."""
        self.as_recorded()


@contextlib.contextmanager
def recording():
    """Record every `looks.render` call made inside the block (build.py and content.py call it through the module,
    so the one wrapper sees them all). Restores the original on exit. Yields the list of `Call`."""
    calls = []
    original, original_part = looks.render, navparts.part
    own = [None]

    def part(builder, base, st):
        # the nav item's state names the optional part it would take (`places.nav_own`); the next nav call is that item's
        got = original_part(builder, base, st)
        mine = place_tables.nav_own(base, st)
        own[0] = mine if mine != got else None
        return got

    def rec(construct, part, values, look=None):
        out = original(construct, part, values, look)
        call = Call(len(calls), construct, part, values, out, look)
        if construct == "nav" and part != "wrap":
            call.own, own[0] = own[0], None
        calls.append(call)
        return out
    original_alone = grouping.number_alone

    def alone(rendered, markup):
        # a count with no word drops the space beside it after its render (`grouping.number_alone`, section 4.2): the recorded
        # output is what the page holds, so the parent's html slot still holds it (step 12b)
        got = original_alone(rendered, markup)
        if got != rendered:
            for c in reversed(calls):
                if c.key == ("group-count", "wrap") and c.out == rendered:
                    c.out = got
                    break
        return got
    looks.render, navparts.part, grouping.number_alone = rec, part, alone
    try:
        yield calls
    finally:
        looks.render, navparts.part, grouping.number_alone = original, original_part, original_alone


def link_calls(calls):
    """Set each call's `parent` and its html slots' `segments`. A call is a child of the LATEST later call whose html
    slot holds its `out`, taking longest spans first so a grandchild is the child of its own parent, and one earlier
    call per occurrence (the closest not yet taken)."""
    taken = set()
    by_out = collections.defaultdict(list)
    for c in calls:
        if c.out:
            by_out[c.out].append(c)
    for p in calls:
        for slot, kind in p.table.items():
            v = p.values.get(slot)
            if kind != looks.HTML or not isinstance(v, str) or not v:
                continue
            spans = []
            used = []
            for out in sorted((o for o in by_out if o in v), key=len, reverse=True):
                start = 0
                while True:
                    i = v.find(out, start)
                    if i < 0:
                        break
                    j = i + len(out)
                    start = i + 1
                    if any(i < b and a < j for a, b in used):
                        continue
                    cands = [c for c in by_out[out] if c.idx < p.idx and c.idx not in taken]
                    if not cands:
                        continue
                    kid = cands[-1]
                    taken.add(kid.idx)
                    kid.parent = p
                    used.append((i, j))
                    spans.append((i, j, kid))
            spans.sort(key=lambda t: t[0])
            segs, pos = [], 0
            for i, j, kid in spans:
                if i > pos:
                    segs.append(("text", v[pos:i]))
                segs.append(("kid", kid))
                pos = j
            if pos < len(v):
                segs.append(("text", v[pos:]))
            p.segments[slot] = segs


@contextlib.contextmanager
def _list_items():
    """While recording, a list role is joined with `LIST_SEP` (the build reads the site's own separator through this one function)."""
    original = stepsview.role_separator
    stepsview.role_separator = lambda builder: LIST_SEP
    try:
        yield
    finally:
        stepsview.role_separator = original


def place_calls(calls, places=None):
    """The site-wide `image` calls that are the picture of a `places` part (a step, a home tile; every picture place by default)."""
    places = place_tables.picture_places() if places is None else places
    return [c for c in calls if c.construct == "image" and c.parent is not None
            and (c.parent.construct, c.parent.part) in places
            and any(seg[0] == "kid" and seg[1] is c for seg in c.parent.segments.get("image", ()))]


def place_pictures(calls, places=(("steps-view", "item"),)):
    """Every `image` call that is the picture of a `places` part is read as that place's own `image` part. The recording reads a
    step's picture so (`steps-view` is 0.5.0's own construct, so its picture part costs no newer release); a home tile's is read so
    only by the derive reading that needs it (`derive.derive_look`: `home-showcase.image` makes a look need 0.5.0)."""
    for c in place_calls(calls, places):
        c.as_place(c.parent.construct)


def kids_of(call):
    return [seg[1] for segs in call.segments.values() for seg in segs if seg[0] == "kid"]


def record(files):
    """Build `files` in memory with every render call recorded. Returns (calls, html_outputs). Raises
    LookCommandError when the tree does not build: nothing can be derived from content the build refuses."""
    with recording() as calls, _list_items():
        acc = running.accept(files)
    if acc.problems:
        first = "; ".join(p.line() for p in acc.problems[:2])
        raise LookCommandError("this repository's content does not build today (%s), so a look cannot be derived from "
                               "it; fix that first, then run derive again" % first)
    link_calls(calls)
    place_pictures(calls)
    pages = {}
    for path, data in acc.output.items():
        if path.lower().endswith((".html", ".htm")):
            try:
                pages[path] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
    return calls, pages


def _tree(call):
    yield call
    for k in kids_of(call):
        for d in _tree(k):
            yield d
