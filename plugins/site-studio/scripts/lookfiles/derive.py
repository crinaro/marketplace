"""Deriving a look: the readings (`derive_look`), the choice among a part's readings (`_derive_look`) and the report (`Derivation`)."""

import collections
import json
import looks
import re
from lookfiles.anchors import _Fail
from lookfiles import literals
from lookfiles.derivation import _Derivation
from lookfiles.pagedom import Page, Tx, _STOP_UP, walk
from lookfiles.refusals import LookCommandError
from lookfiles.renderlog import LIST_SEP_PARTS, PLACE_PICTURES, _tree, kids_of, place_calls, record
from lookfiles.templatemerge import _majority, _merge, _merge_place_picture
from lookgrammar.constructs import PART_FIRST


STATUSES = ("mapped", "unmapped", "ambiguous", "not reached")
DEFAULT_LIST_SEP = " / "                    # what the build joins a list role with when the look names no separator
PLACE_PARTS = frozenset((c, "image") for c, _p in PLACE_PICTURES)


# ================================================================================================ derive, whole
class Derivation(object):
    def __init__(self):
        self.look = {"look": looks.LOOK_FORMAT, "constructs": {}}
        self.status = collections.OrderedDict()      # construct -> Counter of statuses (by distinct instance)
        self.reasons = {}                             # construct -> first reason it did not map
        self.unexplained = collections.Counter()
        self.pages_read = 0
        self.mapped_instances = 0
        self.consensus = {}                           # (construct, part) -> (the markup it kept, a call that holds it): the next reading's prior

    @property
    def text(self):
        return json.dumps(self.look, indent=2, ensure_ascii=False) + "\n"

    def lines(self):
        out = []
        for cid in looks.CONSTRUCTS:
            if cid not in self.status:
                continue
            c = self.status[cid]
            line = "%s: %s" % (cid, ", ".join("%s %d" % (s, c[s]) for s in STATUSES if c.get(s)))
            if cid in self.reasons and not c.get("mapped"):
                line += " (%s)" % self.reasons[cid]
            out.append(line)
        silent = [cid for cid in looks.CONSTRUCTS if cid not in self.status]
        out.append("%d construct(s) have no instance in this repository's content: the plugin's markup is used"
                   % len(silent))
        if self.unexplained:
            out.append("text no content explains, by element: " + ", ".join(
                "element/%s x%d" % (t, n) for t, n in sorted(self.unexplained.items())))
        return out


def _sanitise(message):
    return re.sub(r"'[^']*'|\"[^\"]*\"", "...", message)[:90]


def _opt_sig(root, tmap):
    """What an option says about each part: the key, the template and the suffix flag, in a stable order."""
    return tuple(sorted((c.key, tmap[id(c)]) for c in _tree(root) if id(c) in tmap))


def derive_look(files, pages, never=(), recorded=None, refine=True):
    """`_derive_look`, read again when the first reading leaves an instance `ambiguous` (`refine`; adopt's per-candidate scoring reads
    once, the look it keeps is read up to four times):

      1. the reading every earlier release gave;
      2. the one that prefers, among the readings that take one element, the one that leaves a wrapper to the PARENT (a wrapper that a
         part owns only serves the places that carry it, and two places that do not agree make the part `ambiguous`);
      3. the one that COUNTS INSTANCES (`_derive_look`, THE MARKUP MORE INSTANCES CAN SHARE WINS): a markup more instances cannot share
         than can is read last, so the page that wraps its one reference card in a grid is the page that differs, not the home page;
      4. the one that does both and is told what the third kept (a list of ONE cannot say whether the `ul` is the list's or its item's,
         and the lists of several have said; a wrapper only one place carries is the parent's).

    The reading that maps the most instances is the answer, then the one that names the fewest `ambiguous`; on a tie, the earlier (the
    first is what every earlier release gave, so a site that derived cleanly derives as it did)."""
    calls_pages = recorded if recorded is not None else record(files)
    best = _readings(files, pages, never, calls_pages, refine)
    # a home tile's picture is read as the site-wide `image` first (a look that keeps it so needs no newer release); only where that
    # leaves the tiles or the pictures not mapped is it read again as the tile's own `home-showcase.image` part (step G O3), and that
    # reading is kept only when it maps more. It is tried only for content that already prints a 0.5.0 construct: a tree 0.4.x
    # accepts derives as 0.4.x derived it (G3: the look of a schema-4 template site never comes to need 0.5.0 through its tiles)
    tiles = place_calls(calls_pages[0], (("home-showcase", "item"),))
    unsettled = lambda cid: any(best.status.get(cid, {}).get(s) for s in ("ambiguous", "unmapped"))      # noqa: E731
    newer = any(looks.CONSTRUCTS[c.construct]["first"] == PART_FIRST[("home-showcase", "image")] for c in calls_pages[0])
    if tiles and newer and (unsettled("home-showcase") or unsettled("image")):
        for c in tiles:
            c.as_place("home-showcase")
        try:
            more = _readings(files, pages, never, calls_pages, refine)
        except LookCommandError:
            more = None
        if more is not None and _quality(more) > _quality(best):
            return more
        for c in tiles:
            c.as_site()
    return best


def _readings(files, pages, never, calls_pages, refine):
    """The readings of `derive_look`, the best of them."""
    best = _derive_look(files, pages, never, calls_pages, False)
    if not refine or not any(c.get("ambiguous") for c in best.status.values()):
        return best
    counted = None
    for prefer, prior in ((True, None), (False, {}), (True, "counted")):
        if prior == "counted":
            if counted is None:
                continue
            prior = counted.consensus
        try:
            more = _derive_look(files, pages, never, calls_pages, prefer, prior)
        except LookCommandError:
            continue
        if prior == {} and not prefer:
            counted = more
        if _quality(more) > _quality(best):
            best = more
    return best


def _quality(d):
    """What a reading is worth: the instances it maps, then (of readings that map as many) the fewer it names `ambiguous`."""
    return (d.mapped_instances, -sum(c.get("ambiguous", 0) for c in d.status.values()))


class _Reading(object):
    """What one `_derive_look` reading holds while it places the instances of the recorded parts in the pages. Each method is one stage
    of it, run in this order: `anchor_roots`, `count_support`, `place_pending`, `place_salvaged`, `merge_templates`, `count_statuses`,
    `finish`."""

    def __init__(self, calls, built, parsed, never, state, values=()):
        self.calls, self.built, self.parsed = calls, built, parsed
        self.values = values                    # the pieces' own values (`literals.content_values`): none is a look's fixed text
        self.by_key = dict((p.key, p) for p in parsed)
        self.never = set(never)
        self.state = state
        self.seen_root, self.outcome, self.instances = set(), {}, {}
        self.pending = []                       # (root, page, [(sig, tmap, ext, place, depth)])
        self.salvaged = []                      # the same, for parts read on their own because their parent could not be mapped
        self.ordered_pending = []               # `pending`, the instances with one reading first (set by `count_support`)
        self.accepted = collections.defaultdict(list)
        self.support = collections.Counter()
        self.root_now = [None]
        self.readings, self.calls_of = {}, collections.defaultdict(dict)   # id(call) -> the markups any reading of its root gives it; part -> calls
        self.shares = {}

    def read(self, root, scope=None):
        """(page, options) of the first page that holds `root`, else (None, the failure, the pages it was built into). `scope` is
        (page, element): the part is looked for inside that element of that page only (as it is inside its parent), else page-wide."""
        want = [k for k, h in self.built.items() if root.out and root.out in h]
        if scope is not None:
            page, el = scope
            try:
                opts = self.state.instance(page, root, el, el)
            except _Fail as e:
                return None, e, want
            plain = [o for o in opts if ("fill", id(root)) not in o[0]]
            return (page, [(_opt_sig(root, tm), tm, ext, pl, d) for tm, ext, pl, d in (plain or opts)]), None, want
        ordered = [self.by_key[k] for k in want if k in self.by_key] + [p for p in self.parsed if p.key not in want]
        failure = None
        for page in ordered:
            try:
                opts = self.state.instance(page, root, page.root, None)
            except _Fail as e:
                if failure is None:
                    failure = e
                elif failure.where is None:
                    failure.where = e.where         # the first page that held the part's values at all
                continue
            plain = [o for o in opts if ("fill", id(root)) not in o[0]]
            return (page, [(_opt_sig(root, tm), tm, ext, pl, d) for tm, ext, pl, d in (plain or opts)]), None, want
        return None, failure or _Fail("unmapped", "no page was read"), want

    def settle(self, root, failure, want, where):
        """`root` could not be mapped: it is named, and the parts inside it that the page DOES hold are read on their own, inside the
        element that held the whole of it (a part that cannot be mapped does not take the parts inside it with it: the home page's body
        is a run the builder writes in one order, a template may set the same parts in another, and the showcase in it is still the
        showcase). Where nothing held the whole of it, its parts are not looked for."""
        status = failure.status
        if status == "unmapped" and not any(k in self.by_key for k in want) and any(k in self.never for k in want):
            status = "not reached"
        self.outcome[id(root)] = (status, failure.why)
        claimed = set()                     # the elements the parts read so far hold: two parts of one parent are never one element
        for kid in kids_of(root):
            got = None
            if where is not None:
                page, cands = where
                for el in cands:
                    first, _fail, _kwant = self.read(kid, (page, el))
                    if first is None:
                        continue
                    opts = [o for o in first[1] if id(o[2]) not in claimed]
                    if not opts:
                        continue
                    nearest = min(o[3] for o in opts)       # the first place that is still free (the same reference twice on a page)
                    opts = [o for o in opts if o[3] == nearest]
                    # only a part the page reads one way: where it can be read several ways (a list of one: is the `ul` or the `li` its
                    # own?) the parent's own extent decided that, and the parent is gone
                    if len(set(o[0] for o in opts)) == 1:
                        got = (first[0], opts)
                        break
            if got is not None:
                self.salvaged.append((kid, got[0], got[1]))
                for o in got[1]:
                    claimed.update(id(e) for e in walk(o[2]))
            else:
                self.settle(kid, failure, want, where)       # the reason is the part's whose parts these are: it is why they were not placed

    def anchor_roots(self):
        """Every root call is read in the pages: one that anchors is pending, one that does not is named and its parts settled."""
        for root in [c for c in self.calls if c.parent is None]:
            sig = (root.construct, root.part, root.out)
            if sig in self.seen_root:
                continue
            self.seen_root.add(sig)
            got, failure, want = self.read(root)
            if got is not None:
                self.pending.append((root, got[0], got[1]))
                continue
            self.settle(root, failure, want, failure.where)

    def conflicts(self, root, tmap, hold=()):
        """The calls of `root` whose markup, in the reading `tmap`, cannot be one markup with what the parts accepted so far hold
        (the `hold` calls are not asked: they are offered later)."""
        out = set()
        for c in _tree(root):
            if id(c) in tmap and id(c) not in hold:
                tpl, suf = tmap[id(c)]
                cur = self.accepted[c.key]
                if cur and _merge(cur + [(tpl + (" " if suf else ""), c)], c.construct, c.part) is None:
                    out.add(id(c))
        return out

    def consistent(self, root, tmap, hold=()):
        return not self.conflicts(root, tmap, hold)

    def commit(self, root, page, tmap, exts, skip=()):
        for c in _tree(root):
            if id(c) in self.state.absent and id(c) not in skip:
                self.instances[id(c)] = c       # a number the page does not print, and the look does not either (U-D1)
            if id(c) in tmap and id(c) not in skip:
                tpl, suf = tmap[id(c)]
                self.state.entries[c.key].append((tpl + (" " if suf else ""), c))
                self.accepted[c.key].append((tpl + (" " if suf else ""), c))
                self.instances[id(c)] = c
            sep = tmap.get(("sep", id(c)))
            if sep is not None and sep[0] != DEFAULT_LIST_SEP and id(c) not in skip:
                # the separator the page writes between a list's items is the look's own part (`steps-view.role-sep`)
                self.state.entries[(c.construct, LIST_SEP_PARTS[c.key])].append((sep[0], c))
        for ext in exts:
            for el in walk(ext):
                self.state.explained[id(page)].add(id(el))

    def count_support(self):
        """Counts, before anything is placed, what instances can share."""
        # an instance with one reading fixes the templates; an instance with several (a list of one: is the `ul` or the
        # `li` the part's own?) takes the reading the others agree with
        self.ordered_pending = [p for p in self.pending if len({o[0] for o in p[2]}) == 1] + \
                               [p for p in self.pending if len({o[0] for o in p[2]}) != 1]
        # how many instances can read a part with a given markup: of several readings that all fit what is fixed so far, the
        # one the most other instances can share is taken (the wrapper above a block belongs to the block when every other
        # instance of it carries that wrapper, and to its parent when they do not)
        for root, _page, opts in self.pending:
            seen_here = set()
            for o in opts:
                for c in _tree(root):
                    if id(c) in o[1]:
                        seen_here.add((c.key, o[1][id(c)]))
            self.support.update(seen_here)
        # THE MARKUP MORE INSTANCES CAN SHARE WINS (G3 derive link 2). A reading gives a part a markup; every OTHER instance of the part
        # either has a reading that can share it (`_merge`) or has none. A reading that leaves more instances without a shareable reading
        # than there are instances (itself included) that can share it is OUTVOTED, and an instance every reading of which is outvoted is
        # placed LAST: a reference card the home page's feed and samples write as a bare link, and one piece's page wraps in a grid of one,
        # is the bare link (the two cards outvote the one), and the piece's page is the one that differs.
        for root, _page, opts in self.pending:
            for c in _tree(root):
                ms = set(o[1][id(c)] for o in opts if id(c) in o[1]) | self.state.alts.get(id(c), set())
                if ms:
                    self.readings[id(c)] = ms
                    self.calls_of[c.key][id(c)] = c

    def score(self, reading):
        return sum(self.support[(c.key, reading[1][id(c)])] for c in _tree(self.root_now[0]) if id(c) in reading[1])

    def shares_markup(self, c1, m1, c2, m2):
        """Can the instance `c1` read as `m1` and the instance `c2` read as `m2` be one markup of the part (`_merge`)? A markup that is
        only the more general of two (`{{portfolio}}-item` for the `work-item` of one portfolio) shares."""
        if m1 == m2:
            return True
        k = (id(c1), m1, id(c2), m2)
        if k not in self.shares:
            self.shares[k] = _merge([(m1[0] + (" " if m1[1] else ""), c1), (m2[0] + (" " if m2[1] else ""), c2)],
                                    c1.construct, c1.part) is not None
        return self.shares[k]

    def outvoted(self, root, reading):
        """The calls of `root` whose markup, in `reading`, more instances cannot share than can (themselves included)."""
        own, out = set(id(c) for c in _tree(root)), set()
        for c in _tree(root):
            if not self.state.vote or id(c) not in reading[1]:          # only a counting reading votes (the first is what every release gave)
                continue
            mine, can, cannot = reading[1][id(c)], 1, 0
            for c2 in self.calls_of[c.key].values():
                if id(c2) in own:
                    continue
                if any(self.shares_markup(c, mine, c2, m2) for m2 in self.readings[id(c2)]):
                    can += 1
                else:
                    cannot += 1
            if cannot > can:
                out.add(id(c))
        return out

    def place(self, root, page, opts, hold=()):
        self.root_now[0] = root
        # of readings the instances support equally, the one that reads the root as the plugin's own markup comes first: nothing above a
        # root owns a wrapper, so a page that writes the part exactly as the plugin does (`<nav class="site-nav"><ul>`) keeps that wrapper
        keep = sorted((o for o in opts if self.consistent(root, o[1], hold)),
                      key=lambda o: (-self.score(o), o[1].get(id(root), ("",))[0] != root.template))
        if not keep:
            # no reading agrees with what is accepted: the reading with the fewest such parts is kept, and those parts alone are named
            # `ambiguous` (a home page does not lose its wrapper, its heading and every part inside it because one list of links is
            # marked up as the resume page marks it). Which markup stands is the one accepted first when the instances tie.
            best = min(opts, key=lambda o: (len(self.conflicts(root, o[1], hold)), -self.score(o)))
            skip = self.conflicts(root, best[1], hold)
            if len(skip) == sum(1 for c in _tree(root) if id(c) in best[1] and id(c) not in hold):
                for c in _tree(root):
                    self.outcome[id(c)] = ("ambiguous", "no reading of this instance agrees with the other instances of the part")
                return
            for c in _tree(root):
                if id(c) in skip:
                    self.outcome[id(c)] = ("ambiguous", "this instance's markup differs from the one most instances share")
            self.commit(root, page, best[1], [o[2] for o in opts if o[0] == best[0]], set(skip) | set(hold))
            return
        places = {}
        for o in keep:
            places.setdefault(o[3], []).append(o[0])
        if len(places) > 1 and len({ss[0] for ss in places.values()}) > 1:
            for c in _tree(root):
                self.outcome[id(c)] = ("ambiguous", "two places in the page hold this instance with different markup")
            return
        self.commit(root, page, keep[0][1], [o[2] for o in keep if o[0] == keep[0][0]], hold)

    def place_pending(self):
        """Places the anchored instances: the ones some reading of which the majority can share first, the others last."""
        last, held = [], []
        for root, page, opts in self.ordered_pending:
            self.root_now[0] = root
            sigs = []
            for o in opts:
                if o[0] not in sigs:
                    sigs.append(o[0])
            live = [o for o in opts if not self.outvoted(root, o)]
            if not live:
                last.append((root, page, opts))
            elif len(sigs) == 1:
                self.commit(root, page, live[0][1], [o[2] for o in live])
            else:
                self.place(root, page, live)
        # an instance every reading of which holds a part the majority cannot share: the reading with the fewest such parts is committed
        # WITHOUT them, and each of them is offered last, after every other instance has fixed its markup (the home page keeps its wrapper
        # and every part inside it where one part is another page's odd one out, and the page that differs is the one that says so)
        for root, page, opts in last:
            self.root_now[0] = root
            best = min(opts, key=lambda o: (len(self.outvoted(root, o)), -self.score(o)))
            out = self.outvoted(root, best)
            held.append((root, best, out))
            self.place(root, page, [best], out)
        for root, best, out in held:
            for c in _tree(root):
                if id(c) not in out:
                    continue
                tpl, suf = best[1][id(c)]
                cur = self.accepted[c.key]
                if cur and _merge(cur + [(tpl + (" " if suf else ""), c)], c.construct, c.part) is None:
                    self.outcome[id(c)] = ("ambiguous", "this instance's markup differs from the one most instances share")
                    continue
                self.state.entries[c.key].append((tpl + (" " if suf else ""), c))
                self.accepted[c.key].append((tpl + (" " if suf else ""), c))
                self.instances[id(c)] = c

    def place_salvaged(self):
        # parts read on their own come LAST and only add: where a reading agrees with everything the other readings fixed it is kept,
        # where it does not it is named `ambiguous` and the others stand (a part another page wrote differently never takes away what
        # an instance of its own parent gave)
        for root, page, opts in self.salvaged:
            self.root_now[0] = root
            keep = sorted((o for o in opts if self.consistent(root, o[1])), key=lambda o: -self.score(o))
            if not keep:
                for c in _tree(root):
                    self.outcome[id(c)] = ("ambiguous", "no reading of this instance agrees with the other instances of the part")
                continue
            places = {}
            for o in keep:
                places.setdefault(o[3], []).append(o[0])
            if len(places) > 1 and len({ss[0] for ss in places.values()}) > 1:
                for c in _tree(root):
                    self.outcome[id(c)] = ("ambiguous", "two places in the page hold this instance with different markup")
                continue
            self.commit(root, page, keep[0][1], [o[2] for o in keep if o[0] == keep[0][0]])

    def merge_templates(self, result):
        """Each part's instances are merged into one template and checked against the grammar; returns {construct: (status, why)} of the
        constructs that could not be mapped."""
        bad = {}
        for (cid, pn), entries in sorted(self.state.entries.items()):
            tpl = (_merge_place_picture if (cid, pn) in PLACE_PARTS else _merge)(entries, cid, pn)
            if tpl is None:
                tpl, odd = _majority(entries, cid, pn)
                if tpl is None:
                    bad.setdefault(cid, ("ambiguous", "instances of one part do not share one markup"))
                    continue
                for _t, c in odd:         # the markup most instances share is used; the others are named, never guessed
                    self.outcome[id(c)] = ("ambiguous", "this instance's markup differs from the one most instances share")
            problems = looks.check_part(cid, pn, tpl)
            if problems:
                bad.setdefault(cid, ("unmapped", _sanitise(problems[0][0])))
                continue
            if literals.literal_hits(tpl, self.values):
                # dev 941 (D1): one instance's own value written as the template's fixed text would print it on every instance's page;
                # in a part of one instance (the home page) it would print the value as it was when the look was made (step 5c-4)
                bad.setdefault(cid, ("unmapped", literals.why_fixed(cid)))
                continue
            result.look["constructs"].setdefault(cid, {})[pn] = tpl
            result.consensus[(cid, pn)] = (tpl, entries[0][1])
        # a home tile's picture that the site-wide `image` parts already write as the page does needs no part of its own: kept, it
        # would make the look need 0.5.0 for nothing (review F8a's rule, applied to the picture parts of step G O3)
        tiles = result.look["constructs"].get("home-showcase", {})
        shared = set(result.look["constructs"].get("image", {}).values())
        if "image" in tiles and all(t in shared for t, _c in self.state.entries[("home-showcase", "image")]):
            del tiles["image"]
        return bad

    def count_statuses(self, result, bad):
        """One status per construct instance, counted by distinct instance."""
        counted = set()
        for c in self.calls:
            sig = (c.construct, c.part, c.out)
            if sig in counted:
                continue
            counted.add(sig)
            cnt = result.status.setdefault(c.construct, collections.Counter())
            if id(c) in self.outcome:
                st, why = self.outcome[id(c)]
            elif c.construct in bad:
                st, why = bad[c.construct]
            elif id(c) in self.instances:
                cnt["mapped"] += 1
                result.mapped_instances += 1
                continue
            else:
                st, why = "unmapped", "an instance of the same markup was read through another page"
            cnt[st] += 1
            result.reasons.setdefault(c.construct, why)

    def finish(self, result, bad):
        """The look keeps the constructs that mapped; a tree that mapped none is refused, and the text no content explains is counted."""
        result.look["constructs"] = dict((cid, result.look["constructs"][cid]) for cid in looks.CONSTRUCTS
                                         if cid in result.look["constructs"] and cid not in bad
                                         and result.status.get(cid, collections.Counter()).get("mapped", 0))
        if not result.mapped_instances:
            raise LookCommandError("these pages were not built from this repository's content: no instance of any construct "
                                   "was found in them. Run derive in the repository whose content produced the pages, or "
                                   "check which pages were read")
        for p in self.parsed:
            for el in walk(p.root):
                if el.tag in _STOP_UP or el.tag in ("script", "style", "title") or id(el) in self.state.explained[id(p)]:
                    continue
                if any(isinstance(k, Tx) and re.search(r"[A-Za-z]", k.data) for k in el.kids):
                    result.unexplained[el.tag] += 1


def _derive_look(files, pages, never, recorded, prefer_parent, prior=None):
    """Derive a look from this tree's content and `pages` ({key: html text}; a key is an output path such as
    `work/x/index.html`, or a page's own path). `never` is the output paths of pages the content built that were not
    read (a cap, a refusal): an instance found nowhere on those is `not reached`. `recorded` is `record(files)`'s
    result when the caller already holds it. Returns a `Derivation`. Raises LookCommandError when the tree does not
    build, no page is given, or no instance anchors anywhere (R5.4(c))."""
    calls, built = recorded if recorded is not None else record(files)
    parsed = [Page(k, t) for k, t in pages.items()]
    if not parsed:
        raise LookCommandError("no page was read, so there is nothing to derive a look from; read the pages with "
                               "--build <folder of built pages>, or check the address")
    result = Derivation()
    result.pages_read = len(parsed)
    rd = _Reading(calls, built, parsed, never, _Derivation(prefer_parent, prior), literals.content_values(files))
    rd.anchor_roots()
    rd.count_support()
    rd.place_pending()
    rd.place_salvaged()
    bad = rd.merge_templates(result)
    rd.count_statuses(result, bad)
    rd.finish(result, bad)
    return result
