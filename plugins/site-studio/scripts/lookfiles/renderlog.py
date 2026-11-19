"""The recording: every `looks.render` call a build makes, linked into a tree of parts (a call is the child of the call whose html slot holds
its output), which is what derive looks for in the published pages."""

import collections
import contextlib
import looks
from building import running
from lookfiles.pagedom import _SLOT
from lookfiles.refusals import LookCommandError


# ================================================================================================== the recording
class Call(object):
    """One `looks.render` call: what was rendered, from which values, with what result."""

    def __init__(self, idx, construct, part, values, out, look=None):
        self.idx, self.construct, self.part, self.out = idx, construct, part, out
        self.values = dict(values)
        self.table = looks.CONSTRUCTS[construct]["parts"][part]
        self.parent = None
        self.segments = {}              # html slot -> [("text", html) | ("kid", Call)]
        self.cache = {}                 # memo of items and needles (a Call is read many times while anchoring)
        try:
            text = looks.part_markup(construct, part, look)
        except looks.LookError:
            text = ""
        self.template = text            # the recording look's markup for this part
        used, in_text = [], set()
        for m in _SLOT.finditer(text):
            if m.group(1) in self.table and m.group(1) not in used:
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


@contextlib.contextmanager
def recording():
    """Record every `looks.render` call made inside the block (build.py and content.py call it through the module,
    so the one wrapper sees them all). Restores the original on exit. Yields the list of `Call`."""
    calls = []
    original = looks.render

    def rec(construct, part, values, look=None):
        out = original(construct, part, values, look)
        calls.append(Call(len(calls), construct, part, values, out, look))
        return out
    looks.render = rec
    try:
        yield calls
    finally:
        looks.render = original


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


def kids_of(call):
    return [seg[1] for segs in call.segments.values() for seg in segs if seg[0] == "kid"]


def record(files):
    """Build `files` in memory with every render call recorded. Returns (calls, html_outputs). Raises
    LookCommandError when the tree does not build: nothing can be derived from content the build refuses."""
    with recording() as calls:
        acc = running.accept(files)
    if acc.problems:
        first = "; ".join(p.line() for p in acc.problems[:2])
        raise LookCommandError("this repository's content does not build today (%s), so a look cannot be derived from "
                               "it; fix that first, then run derive again" % first)
    link_calls(calls)
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
