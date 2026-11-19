"""One reading of the pages: the state that anchors each recorded part in a page and offers the readings of its template (`_Derivation`)."""

import collections
import looks
from lookfiles.anchors import (
    _Fail,
    _SHARE,
    _SUBST_SKIP,
    _above,
    _attr_only,
    _can_go,
    _fixed_beside,
    _full_needles,
    _has_nested,
    _has_url,
    _holds,
    _int_needles,
    _is_wild,
    _node_holds,
    _out_items,
    _own_needles,
    _sub_slot,
    _tops,
    _value_items,
    _widened,
    _word_pattern,
)
from lookfiles.pagedom import (
    El,
    Mk,
    Tx,
    _STOP_UP,
    _WS,
    _copy,
    _height,
    is_ws,
    ser,
    squash,
    text_of,
    walk,
)
from lookfiles.renderlog import _tree, kids_of
from lookfiles.templatemerge import _merge


class _Derivation(object):
    """The state of one `derive`: the templates found per (construct, part), and what each page's anchors explain."""

    def __init__(self, prefer_parent=False, prior=None):
        self.prefer_parent = prefer_parent                   # of readings that take one element, leave the wrappers to the parent
        self.prior = prior or {}                             # what the counting reading kept: {(construct, part): (markup, a call that holds it)}
        self.agreed = {}                                     # (id(call), markup) -> does it share the prior's markup of its part
        self.alts = collections.defaultdict(set)             # id(call) -> every markup any reading of it (at any wrapper) gives it
        self.vote = prior is not None                        # a reading with a prior (even an empty one) COUNTS INSTANCES (`_derive_look`)
        self.entries = collections.defaultdict(list)        # (construct, part) -> [(template, call)]
        self.explained = collections.defaultdict(set)       # id(page) -> {id(element inside an anchored extent)}
        self.runs = {}                                      # id(call) -> sibling nodes a multi-element part spans
        self.seen = {}                                      # (page, part, scope, bound) -> its readings, or the failure

    # ------------------------------------------------------------------------------------------ anchoring
    def anchors(self, page, scope, call, bound):
        """Candidate extents for `call` inside `scope`: the lowest elements holding every hard needle, moved out to
        the element that carries the call's own address, and, among several, those holding the most addresses."""
        hard, soft = _full_needles(call)
        _own_hard, own_soft = _own_needles(call)
        out = []
        if not hard and not soft:
            ints = _int_needles(call)
            if not ints:
                return []
            want = squash(ints[0])
            for el in walk(scope):
                if el.tag in _STOP_UP or page.stext(el) != want:
                    continue
                if any(isinstance(k, El) and page.stext(k) == want for k in el.kids):
                    continue
                out.append(el)
            return out
        if not hard or (soft and _attr_only(call)):
            # dev #941: a part the page can find only by an alt (a picture, or a figure or gallery item holding only one) is found by
            # its address: the `h1` whose text is the same words as the alt is the piece's title, and reading the picture there drops it
            hard = list(soft)
        # a value the page does not show at all (a host name, a count the template leaves out) cannot place the
        # instance: the template simply has no slot for it. A needle found nowhere in `scope` is left out; the anchor
        # still holds every needle the page does show.
        hard = [n for n in hard if _holds(page, scope, [n])] or hard
        # a value that is only a part of another value of the same instance is looked for at a place of its own first; where no
        # element holds them so, the instance anchors as every earlier release read it
        for apart in ((True, False) if _has_nested(hard) else (False,)):
            for el in walk(scope):
                if el.tag in _STOP_UP or not _holds(page, el, hard, apart):
                    continue
                if any(isinstance(k, El) and _holds(page, k, hard, apart) for k in el.kids):
                    continue
                out.append(el)
            if out:
                break
        out = [_widened(page, scope, el, hard, bound) for el in out]
        if own_soft:
            fixed = []
            for el in out:
                top, hops = el, 0
                while not _has_url(page, top, own_soft[0]) and hops < 3:
                    up = top.parent
                    if not _can_go(up, bound):
                        break
                    top, hops = up, hops + 1
                fixed.append(top if _has_url(page, top, own_soft[0]) else el)
            out = fixed
            if len(out) > 1:
                best = max(sum(1 for u in own_soft if _has_url(page, e, u)) for e in out)
                out = [e for e in out if sum(1 for u in own_soft if _has_url(page, e, u)) == best]
        seen, uniq = set(), []
        for e in out:
            if id(e) not in seen:
                seen.add(id(e))
                uniq.append(e)
        return uniq

    # ------------------------------------------------------------------------------------------ one instance
    def instance(self, page, call, scope, bound):
        """Every way `call` anchors in `scope`: [(template map, extent, place, depth)], best first within a place.
        The map is {id(call): (template, suffix flag)} for the call and its descendants; `place` numbers the anchors
        (two places on one page); `depth` numbers the wrappers the extent includes (0 is the lowest). Raises _Fail
        when it anchors nowhere."""
        key = (id(page), id(call), id(scope), id(bound))
        hit = self.seen.get(key)
        if hit is not None:                 # the same part asked for inside the same element again (every wrapper reading of its parent asks)
            if isinstance(hit, _Fail):
                raise hit
            return hit
        try:
            hit = self.seen[key] = self._instance(page, call, scope, bound)
        except _Fail as e:
            self.seen[key] = e
            raise
        for tm, _e, _pl, _d in hit:
            for c in _tree(call):
                if id(c) in tm:
                    self.alts[id(c)].add(tm[id(c)])
        return hit

    def _instance(self, page, call, scope, bound):
        cands = self.anchors(page, scope, call, bound)
        if not cands:
            raise _Fail("unmapped", "no element of the page holds this instance's values")
        results, last = [], None
        for place, r0 in enumerate(cands):
            try:
                options = self._one(page, call, r0, bound)
                # `depth` is how many wrappers the extent takes in above the lowest one (a reading is the same extent
                # under another wrapper choice of its parts, so it is the extent, not the list position, that says)
                ups = [_height(ext) for _tm, ext in options]
                plain = [u for (tm, _e), u in zip(options, ups) if ("fill", id(call)) not in tm]
                base = max(plain or ups)                  # a reading kept for a parent that needs it does not move the others' depth
                for (tmap, ext), up in zip(options, ups):
                    results.append((tmap, ext, place, base - up))
            except _Fail as e:
                last = e
        if not results:
            last.where = (page, cands)
            raise last
        return results

    def _agrees(self, c, markup):
        """May `c` (read as `markup`, a (template, suffix flag)) share the markup the counting reading kept for its part? True where it
        kept none."""
        got = self.prior.get(c.key)
        text = markup[0] + (" " if markup[1] else "")
        if got is None or text == got[0]:
            return True
        k = (id(c), text)
        if k not in self.agreed:
            self.agreed[k] = _merge([(text, c), got], c.construct, c.part) is not None
        return self.agreed[k]

    def _kids_in(self, page, kids, r, tight=False, runs=False):
        """The extent of each searchable child inside `r`: {id(child): (template map, extent)}. A child takes the
        highest of its own wrapper variants that stays below `r` (a list item is its `li`, not its `a`); with `tight`
        (a number of wrappers, 0 for none) it takes the variant that many wrappers up, or the highest it has when it has
        fewer (the wrappers above a block that is alone in them are then the parent's, such as the element a page's
        body slot sits in). With `runs`, a child that fills `r` with its parent, or an element with another child, is read as a run of
        that element's children (`_runs_for_sharers`) instead of being refused."""
        cands = []
        for k in kids:
            allopts = self.instance(page, k, r, r)

            def own(o, k=k):
                """How much markup the parts BELOW the kid hold in a reading: of readings that take the same element, the one that
                leaves a wrapper to the parent (the parts below it hold the least) is taken, because a wrapper the parent owns serves
                every place the part below is used and one that part owns serves only the places that carry it (a showcase's span
                around an image a card does not wrap). Of those, the one whose parts below hold the markup the counting reading kept
                (`prior`) comes first: a list of ONE cannot say whether the `ul` is the list's or its item's, and the lists of several
                (every other `cards`) have said."""
                if not self.prefer_parent:
                    return (0, 0)
                below = [c for c in _tree(k) if c is not k and id(c) in o[0]]
                return (sum(1 for c in below if not self._agrees(c, o[0][id(c)])), sum(len(o[0][id(c)][0]) for c in below))
            if tight is None or tight is False:
                opts = sorted(allopts, key=lambda o: (("fill", id(k)) in o[0], o[2], -o[3], own(o)))
            else:
                opts = sorted(allopts, key=lambda o: (("fill", id(k)) in o[0], o[2],
                                                      abs(o[3] - tight) if o[3] <= tight else -o[3] + 1000, own(o)))
            cands.append([(tm, ext) for tm, ext, _pl, _d in opts])
        picks = self._choose(cands, runs)
        if picks is None:
            raise _Fail("ambiguous", "two instances of one construct share one element")
        if runs:
            picks = self._runs_for_sharers(page, kids, picks, r)
        extents = {}
        for k, pick in zip(kids, picks):
            self.runs[id(k)] = pick[0].get(("run", id(k)), 1)
            extents[id(k)] = pick
        return extents

    @staticmethod
    def _choose(cands, shared_ok):
        """One reading per child, the first of each child's own order that fits: no two children take the same element (unless
        `shared_ok`) and none takes an element that holds another child's (the children of one part are side by side, never one
        inside another: a wrapper that reaches over a sibling is not that part's own). None when no choice fits."""
        picks, budget = [], [4000]

        def clash(ext):
            for _tm, e in picks:
                if e is ext:
                    if not shared_ok:
                        return True
                elif _above(e, ext) or _above(ext, e):
                    return True
            return False

        def go(i):
            if i == len(cands):
                return True
            for opt in cands[i]:
                budget[0] -= 1
                if budget[0] < 0:
                    return False
                if clash(opt[1]):
                    continue
                picks.append(opt)
                if go(i + 1):
                    return True
                picks.pop()
            return False
        return list(picks) if go(0) else None

    def _runs_for_sharers(self, page, kids, picks, r):
        """The children that fill one element with the parent (or with each other) read as RUNS of the children of that element:
        a part the plugin writes as one element (`previously-item`: a span around a link and a period) that a template writes
        as two siblings in the element the parent owns (`<span>..</span><i>..</i>` in a `p`). Each takes the children from where
        the one before it ended to the last that holds one of its values. Raises _Fail when a part holds no value to place it by."""
        by = collections.OrderedDict()
        for i, (_tm, ext) in enumerate(picks):
            by.setdefault(id(ext), []).append(i)
        out = list(picks)
        for idxs in by.values():
            ext = picks[idxs[0]][1]
            if len(idxs) < 2 and ext is not r:
                continue
            start = 0
            for i in idxs:
                tm, first, start = self._run_reading(page, kids[i], ext, start)
                out[i] = (tm, first)
        return out

    def _run_reading(self, page, call, p, start):
        """(template map, first node, next start) of `call` read as the run of `p`'s children, from the `start`th non-blank child,
        that holds every value the page shows of it and every part inside it."""
        searchable = [k for k in kids_of(call) if not _is_wild(k)]
        extents = self._kids_in(page, searchable, p)
        pos = [i for i, k in enumerate(p.kids) if not is_ws(k)]
        hard, _soft = _full_needles(call)
        lo, hi = len(pos), -1
        for n in hard:
            for j in range(start, len(pos)):
                if _node_holds(page, p.kids[pos[j]], n):
                    lo, hi = min(lo, j), max(hi, j)
                    break
        for _tm, ext in extents.values():
            top = ext
            while top is not None and top.parent is not p:
                top = top.parent
            if top is not None and top in [p.kids[i] for i in pos]:
                j = [p.kids[i] for i in pos].index(top)
                if j >= start:
                    lo, hi = min(lo, j), max(hi, j)
        if hi < 0:
            raise _Fail("unmapped", "no element of the page holds this part's values as a run of neighbouring nodes")
        tm, first = self._run_template(page, call, p, pos[lo], pos[hi], extents)[0]
        return tm, first, hi + 1

    def _one(self, page, call, r0, bound):
        """The options for `call` anchored at `r0`: [(template map, extent)], lowest first. The extent is moved up
        while a child covers it exactly; the options after it are the single-child wrappers above (an instance alone
        in its list cannot say whether `ul` or `li` is its own, so both are offered and the instances of the same part
        decide, in derive_look). A child alone in a wrapper is read both ways too: the wrapper is the child's (the
        reading first, as a list item takes its `li`) or the parent's (`tight`), and the instances of the part decide
        again."""
        kids = kids_of(call)
        searchable = [k for k in kids if not _is_wild(k)]
        if _tops(call) > 1:
            try:
                return self._one_multi(page, call, r0, searchable)
            except _Fail as multi:
                # the template does not write the part as the plugin does (a heading around the name and the count, where the plugin
                # writes two sibling spans): the part is the one element that holds what the page shows of it
                try:
                    return self._one_elements(page, call, r0, bound, searchable)
                except _Fail:
                    raise multi
        return self._one_elements(page, call, r0, bound, searchable)

    def _one_elements(self, page, call, r0, bound, searchable):
        out = self._one_read(page, call, r0, bound, searchable, None)
        if searchable:
            have = set(self._reading_sig(o, call) for o in out)
            for tight in (0, 1):
                try:
                    more = self._one_read(page, call, r0, bound, searchable, tight)
                except _Fail:
                    continue
                for o in more:
                    sig = self._reading_sig(o, call)
                    if sig not in have:
                        have.add(sig)
                        out.append(o)
        return out

    @staticmethod
    def _reading_sig(option, call):
        """What a reading says about the call and its parts: each part's template, in a stable order."""
        tmaps = option[0]
        return tuple(sorted((c.key, tmaps[id(c)]) for c in _tree(call) if id(c) in tmaps))

    def _one_read(self, page, call, r0, bound, searchable, tight):
        """The readings of `call` at `r0`: the extent moved up while a child fills it (the wrapper above is the parent's), then the
        single-child wrappers above; and, where a child filled an element with its parent or with another child, the reading in
        which the parent keeps that element and the children are runs of its children (after the others, so a part that derived as
        it always did derives so)."""
        r, fill, out, failure = r0, None, [], None
        try:
            while True:
                try:
                    extents = self._kids_in(page, searchable, r, tight)
                except _Fail as e:
                    if e.why == _SHARE and fill is None:
                        fill = r
                    raise
                if not any(ext is r for _t, ext in extents.values()):
                    break
                if fill is None:
                    fill = r
                up = r.parent
                if not _can_go(up, bound):
                    raise _Fail("unmapped", "the instance and one of its parts share one element")
                r = up
            out = self._read_variants(page, call, r, extents, bound, searchable, tight)
        except _Fail as e:
            failure = e
        if fill is not None and searchable:
            try:
                runs = self._options(call, [(fill, self._kids_in(page, searchable, fill, tight, True))])
                for tm, _ext in runs:
                    tm[("fill", id(call))] = True       # a reading kept for the parent that needs it (`_choose`), never a root's own
                out = out + runs
            except _Fail:
                pass
        if not out:
            raise failure
        return out

    def _read_variants(self, page, call, r, extents, bound, searchable, tight):
        variants = [(r, extents)]
        cur = r
        beside = _fixed_beside(call)
        while len(variants) < 3:
            up = cur.parent
            if (not _can_go(up, bound)
                    or any(isinstance(k, Tx) and k.data.strip() for k in up.kids)):
                break
            sibs = [k for k in up.kids if isinstance(k, El)]
            # a wrapper alone around the extent, or one that holds the extent and the fixed element(s) the plugin's own markup for
            # the part writes beside it: the section around a heading and a list of ONE, where nothing but the heading says that the
            # section is the part's and the list's wrapper is not (`_fixed_beside`)
            if sibs != [cur] and not (beside and sorted(k.tag for k in sibs if k is not cur) == beside and cur in sibs):
                break
            try:
                variants.append((up, self._kids_in(page, searchable, up, tight)))
            except _Fail:
                break
            cur = up
        return self._options(call, variants)

    def _options(self, call, variants):
        out = []
        for v, exts in variants:
            tmaps = {}
            for tm, _e in exts.values():
                tmaps.update(tm)
            template, flags, fixed = self._template(call, v, exts)
            tmaps[id(call)] = (template, False)
            for cid_, tpl in fixed.items():
                tmaps[cid_] = (tpl, False)
            for key, flag in flags.items():
                if flag and key in tmaps:
                    tmaps[key] = (tmaps[key][0], True)
            out.append((tmaps, v))
        return out

    # ------------------------------------------------------------------------------------------ the template
    def _one_multi(self, page, call, p, searchable):
        """A part that writes several sibling elements (the home page's intro and its endorsement): its extent is the
        run of `p`'s children that holds them, and its template is those nodes one after another."""
        extents = self._kids_in(page, searchable, p)
        items, kid_orig = [], dict((k, ext) for k, (_t, ext) in extents.items())
        for it in _out_items(call):
            if it[0] == "kid" and id(it[1]) not in kid_orig:
                items.append(("wild", max(1, _tops(it[1])), it[1]))
            else:
                items.append(it)
        kidset = set(id(e) for e in kid_orig.values())
        pos = [i for i, k in enumerate(p.kids) if not is_ws(k)]
        for st in range(len(pos)):
            m = self._match(p, pos, st, items, kid_orig, kidset)
            if m is not None:
                break
        else:
            raise _Fail("unmapped", "the page holds this part's elements in no run of neighbouring nodes")
        a, b, _wild = m
        return self._run_template(page, call, p, a, b, extents)

    def _run_template(self, page, call, p, a, b, extents):
        """[(template map, first node)] for `call` read as `p.kids[a..b]`: those nodes one after another are its template."""
        cmap, root = {}, El("#root")
        for node in p.kids[a:b + 1]:
            c = _copy(node, cmap)
            c.parent = root
            root.kids.append(c)
        n = len([k for k in p.kids[a:b + 1] if not is_ws(k)])
        self.runs[id(call)] = n
        first = next(k for k in p.kids[a:b + 1] if not is_ws(k))
        tmaps = {}
        for tm, _e in extents.values():
            tmaps.update(tm)
        template, flags, fixed = self._template_in(call, root, cmap, extents)
        tmaps[id(call)] = (template, False)
        tmaps[("run", id(call))] = n
        for cid_, tpl in fixed.items():
            tmaps[cid_] = (tpl, False)
        for key, flag in flags.items():
            if flag and key in tmaps:
                tmaps[key] = (tmaps[key][0], True)
        return [(tmaps, first)]

    def _template(self, call, r, extents):
        cmap = {}
        return self._template_in(call, _copy(r, cmap), cmap, extents)

    def _template_in(self, call, root, cmap, extents):
        flags, fixed, kid_copy = {}, {}, {}
        for k in kids_of(call):
            if id(k) in extents:
                kid_copy[id(k)] = cmap.get(id(extents[id(k)][1]))
        inside = set()
        for node in kid_copy.values():
            if node is not None:
                inside.update(id(e) for e in walk(node))
        for slot in call.slot_order():
            if call.table[slot] != looks.HTML or not call.values.get(slot):
                continue
            items = _value_items(call, slot)
            if items:
                self._replace_run(root, slot, items, kid_copy, inside, flags, fixed)
        for slot in call.all_slots():
            kind, v = call.table[slot], call.values.get(slot)
            if v is None or v == "":
                continue
            if kind == looks.TEXT:
                # a slot the page does not show can only be a markup hook (a class token, a data attribute)
                self._text_slot(root, slot, str(v), inside, attrs_only=slot not in call.used)
            elif kind in (looks.URL, looks.CONTACT, looks.SRCSET, looks.EMBED, looks.POSITION):
                self._url_slot(root, slot, kind, str(v))
        return ser(root), flags, fixed

    def _replace_run(self, root, slot, items, kid_copy, inside, flags, fixed):
        """Replace the sibling run that holds html slot `slot`'s items by one marker."""
        placed = []
        for it in items:
            if it[0] == "kid" and id(it[1]) not in kid_copy:
                placed.append(("wild", max(1, _tops(it[1])), it[1]))
            else:
                placed.append(it)
        if all(it[0] == "wild" for it in placed):
            raise _Fail("unmapped", "a slot holds only fixed markup, so nothing in the page says where it is")
        kidset = set(id(v) for v in kid_copy.values())
        for p in walk(root):
            if id(p) in inside:
                continue
            pos = [i for i, k in enumerate(p.kids) if not is_ws(k) and not isinstance(k, Mk)]
            for st in range(len(pos)):
                m = self._match(p, pos, st, placed, kid_copy, kidset)
                if m is None:
                    continue
                a, b, wild = m
                self._swap(p, a, b, slot, placed, flags)
                for key, nodes in wild.items():
                    fixed[key] = "".join(ser(n) for n in nodes)
                return
        if len(placed) == 1 and placed[0][0] == "tx" and self._text_slot(root, slot, placed[0][2], inside):
            return
        raise _Fail("unmapped", "the page holds this slot's content in no run of neighbouring nodes that matches it")

    def _span(self, it):
        """How many sibling nodes an item takes: a fixed part, or a part that writes several elements, takes more."""
        if it[0] == "wild":
            return it[1]
        return self.runs.get(id(it[1]), 1) if it[0] == "kid" else 1

    def _match(self, p, pos, st, items, kid_copy, kidset):
        need = sum(self._span(it) for it in items)
        if st + need > len(pos):
            return None
        cur, wild = st, {}
        for it in items:
            if it[0] == "wild":
                nodes = [p.kids[pos[cur + j]] for j in range(it[1])]
                if any(id(n) in kidset for n in nodes):
                    return None
                wild[id(it[2])] = nodes
                cur += it[1]
                continue
            node = p.kids[pos[cur]]
            if it[0] == "kid":
                if node is not kid_copy.get(id(it[1])):
                    return None
                cur += self._span(it)
                continue
            if it[0] == "el":
                if not isinstance(node, El) or node.tag != it[1] or squash(text_of(node)) != it[2]:
                    return None
            elif not isinstance(node, Tx) or squash(node.data) != it[1]:
                return None
            cur += 1
        return pos[st], pos[cur - 1], wild

    def _swap(self, p, a, b, slot, items, flags):
        """Replace p.kids[a..b] by a marker, settling the space between members (module docstring: whitespace)."""
        members = [i for i in range(a, b + 1) if not is_ws(p.kids[i])]
        gaps = [any(is_ws(p.kids[i]) for i in range(m1 + 1, m2)) for m1, m2 in zip(members, members[1:])]
        end = b
        if all(it[0] in ("kid", "wild") for it in items):
            trail = end + 1 < len(p.kids) and is_ws(p.kids[end + 1])
            if gaps and any(gaps) and not all(gaps):
                raise _Fail("unmapped", "the space between items differs from one to the next")
            if (all(gaps) if gaps else trail):
                if not trail:
                    raise _Fail("unmapped", "the items are spaced apart but nothing follows the last one")
                end += 1
                for it in items:
                    flags[id(it[1] if it[0] == "kid" else it[2])] = True
        mk = Mk(slot)
        mk.parent = p
        p.kids[a:end + 1] = [mk]

    def _text_slot(self, root, slot, value, inside=(), attrs_only=False):
        """Write `slot` where `value` stands as a whole word in a text node or a text attribute. True if it did. With `attrs_only` (a slot
        the plugin's own markup does not show) a text node is the slot only where the value is the WHOLE text of the node and is more than
        a couple of letters: a template may show the employer in a line of its own where the plugin does not, and that line is the slot,
        never the person's own words; a word that is merely one of several in a line stays literal (a coincidence is not a slot)."""
        pat = _word_pattern(value)
        if pat is None:
            return False
        done = False
        whole = squash(value) if attrs_only and len(squash(value)) >= 3 else None
        for el in list(walk(root)):
            if id(el) in inside:
                continue
            for i, (name, val) in enumerate(el.attrs):
                if val is None or name in _SUBST_SKIP or name == "style":
                    continue
                if name in ("class", "id") and len(squash(value)) < 3:
                    continue
                if pat.search(val):
                    el.attrs[i] = (name, _sub_slot(pat, slot, val))
                    done = True
            for i, k in enumerate(el.kids):
                if not attrs_only and isinstance(k, Tx) and pat.search(k.data):
                    t = Tx(_sub_slot(pat, slot, k.data))
                    t.parent = el
                    el.kids[i] = t
                    done = True
                elif whole is not None and isinstance(k, Tx) and squash(k.data) == whole:
                    lead, trail = k.data[:len(k.data) - len(k.data.lstrip())], k.data[len(k.data.rstrip()):]
                    t = Tx("%s{{%s}}%s" % (lead, slot, trail))
                    t.parent = el
                    el.kids[i] = t
                    done = True
        return done

    def _url_slot(self, root, slot, kind, value):
        for el in walk(root):
            for i, (name, val) in enumerate(el.attrs):
                if val is None:
                    continue
                same = val.strip() == value.strip()
                if kind in (looks.URL, looks.CONTACT) and name in ("href", "src", "cite") and same:
                    el.attrs[i] = (name, "{{%s}}" % slot)
                elif kind == looks.SRCSET and name == "srcset" and same:
                    el.attrs[i] = (name, "{{%s}}" % slot)
                elif kind == looks.EMBED and name in ("src", "data-embed") and same:
                    el.attrs[i] = (name, "{{%s}}" % slot)
                elif kind == looks.POSITION and name == "style" and \
                        _WS.sub("", val) == "object-position:" + _WS.sub("", value):
                    el.attrs[i] = (name, "object-position: {{%s}}" % slot)
