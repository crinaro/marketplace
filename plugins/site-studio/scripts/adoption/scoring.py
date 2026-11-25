"""adoption.scoring -- how ONE candidate of a measured setting is judged: the two builds compared on the pages the setting touches
(design 8, "Measured settings"; R5.3; D2, dev 941).

Part of the `adoption` package behind the entry point `adopt.py`; moved out of `adoption.choose` unedited by split_module.py
(design-adopt-parity-2 step 1). `adoption.choose` decides; this module only judges, and holds no state:

  * `score(local, plugin, name)` is the verdict of `parity_classes.classify_differences` over `settings.setting_paths(name)`, with
    what no visitor meets (`not_seen`: the meta description, the plugin's own asset files) left out; `sort.<portfolio>` is judged by
    the order of the piece links on the portfolio's index (`score_order`, `link_order`) and nothing else.
  * `lost_content(local, plugin, name)` says what the plugin's pages LOSE that the old pages show (an image or video, a text of the
    content area, `_Reading`); `lost_facts` is the same, every loss of every page, so rule L can compare two looks' losses as sets
    (`adoption.lookkeep`, design-adopt-parity-2 section 6, step 11), and `class_share` is L4's coverage of class names.

Rule M (design-adopt-parity-2 section 5, step 8), the parts that judge; `choose.decide` applies them in order:

  * M1 `one_build_pages(local, outs, name)`: the pages one build lacks and no candidate adds or removes, left out of every
    candidate's `score(..., drop=)` alike. A page only the old build has is `carried`'s to answer for, never a card setting's.
  * M4 `judge_by_facts(...)`: each page read into visitor facts (`adoption.facts`; each build's addresses read under its own path,
    the old build's links through the recorded redirects: `facts.Frame`, step 8b), a setting judged by the facts in its own
    SCOPE (`scopes`, section 5.3: pages, fact kinds and marks; card settings piece by piece, judged only where both builds link the
    same pieces), the distance additive, so a difference no candidate changes cancels. The unique smallest distance, smaller than
    the default's, wins; the reason counts facts by kind (section 5.2). `featuredView` is judged by its headings first and by the
    order of the home's piece links only on a tie (section 5.4). A page left out says why (`NOT CHECKED: ...`).
    A scope that is the setting's OWN region (`Scope.own`: `backLink.<p>`'s, the facts above the titles of that portfolio's piece
    pages, step 8c) is judged by those facts alone: when every candidate leaves exactly the same facts there, no candidate changes
    what a visitor meets in it and the default stays (`how: measured`), however the rest of those pages differs.
"""

import collections
import html.parser
import json
import posixpath
import re

import parity_classes

from adoption import carry, facts
from adoption.settings import setting_family, setting_paths


def _subset(files, paths):
    if "*" in paths:
        return files
    return dict((p, b) for p, b in files.items()
                if any(p == q or (q.endswith("/") and p.startswith(q)) for q in paths))


def not_seen(d):
    """True for a hunk of `classify_differences` no visitor of the page meets: the meta description (read by search engines, shown
    on no page) and a file of the plugin's own `site-studio/` assets (a stylesheet or script a page uses only where it carries the
    markup that needs it, and THAT markup is a difference of its own). Used to choose a setting, never to say two builds agree."""
    if d.path.startswith("site-studio/") and d.kind.startswith("only-plugin/"):
        return True
    return d.kind == "attribute/content" and any('name="description"' in line for line in list(d.local) + list(d.plugin))


class Output(dict):
    """The plugin's build of one candidate ({path: bytes}) with the publish build's own `problems` (`running.accept`; empty when
    the build accepts the tree). `adoption.measure`'s `evaluate` returns one, so a candidate is judged on what the publish build
    would refuse as well as on what it prints (step 11c, F24: `evaluate` read the output and dropped the problems, so `choose` stored
    as measured a setting the kept look cannot print). A plain dict (a build a test fakes) has no problems."""

    def __init__(self, files=(), problems=()):
        dict.__init__(self, files)
        self.problems = tuple(problems)


def refusals(out, default=None):
    """The problems of `out`'s build that the default's build (`default`, built under the same other settings) does not have: what
    THIS candidate makes the publish build refuse. Rule 9a2 extended (step 11c): a candidate whose build is refused never wins, so
    `choose.decide` and M4 (`_same_pages`) leave out one with any. A problem the default shares is the tree's, not the candidate's."""
    base = set(getattr(default, "problems", ()) or ())
    return [p for p in getattr(out, "problems", ()) or () if p not in base]


def refusal_line(problems, whose="the look's"):
    """What the first refusal is, short: a slot the look lacks reads "<whose> card.wrap has no {{kicker}}" (the slot named, as the
    build's own `expected` names it); anything else, where and the problem's `found` ("content/shelf/: refused by the build")."""
    p = problems[0]
    m = re.match(r"a (\{\{\w+\}\}) in (.+)$", getattr(p, "expected", None) or "")
    if m:
        return "%s %s has no %s" % (whose, m.group(2), m.group(1))
    found = getattr(p, "found", None) or "refused by the build"
    line = "%s: %s" % (p.path, found) if getattr(p, "path", None) else found
    fix = getattr(p, "fix", None)
    return "%s -- %s; fix: %s" % (line, p.message, fix) if fix and getattr(p, "message", None) else line   # dev #1009: the cause


def _is_page(path):
    return path.lower().endswith((".html", ".htm"))


def judged_paths(name, local):
    """The output paths rule M judges setting `name` on: `settings.setting_paths(name)`, except `carried`, whose pages are its
    candidate's value and not a function of its name: the pages offered against the old build `local` (`carry.scope`; step 10b,
    sections 5 and 7.6). Under `*` no candidate of `carried` could win: M2 needs the whole site EQUAL, and M3 refuses a candidate
    that builds other pages than the default. No other setting's scope moves."""
    return carry.scope(local) if name == "carried" else setting_paths(name)


def one_build_pages(local, outs, name):
    """M1 (design-adopt-parity-2 section 5.1): the pages of the setting's `setting_paths` that one build lacks and NO candidate adds
    or removes: a page the old build has and no candidate's build (`outs`, one output per candidate) writes, or one every candidate
    writes and the old build does not. Such a page is `carried`'s to answer for, never this setting's, so it is left out of every
    candidate's score alike. A page some candidate writes and another does not stays: that candidate changes it."""
    paths = judged_paths(name, local)
    old = set(p for p in _subset(local, paths) if _is_page(p))
    built = [set(p for p in _subset(o, paths) if _is_page(p)) for o in outs]
    if not built:
        return frozenset()
    anywhere = set().union(*built)
    everywhere = set.intersection(*built)
    return frozenset((old - anywhere) | (everywhere - old))


def score(local, plugin, name, drop=frozenset()):
    """(ok, first visible difference line, how many visible differences, the pages built, the differences themselves) for one
    candidate: the setting's pages in the two builds, less `drop` (M1's one-build pages: `one_build_pages`). The last is what two
    candidates are compared by when they have the same count."""
    if setting_family(name) == "sort":
        by_order = score_order(local, plugin, name)
        if by_order is not None:
            return by_order
    paths = judged_paths(name, local)
    theirs = dict((p, b) for p, b in _subset(plugin, paths).items() if p not in drop)
    res = parity_classes.classify_differences(dict((p, b) for p, b in _subset(local, paths).items() if p not in drop), theirs)
    built = frozenset(p for p in theirs if not p.startswith("site-studio/"))      # the PAGES: the plugin's own assets are no page a candidate drops
    if res["verdict"] in ("EQUAL", "MARKUP-ONLY"):
        return True, "", 0, built, ()
    shown = [d for d in res["visible"] or () if not not_seen(d)]
    if not shown and res["visible"]:
        return True, "", 0, built, ()
    seen = tuple(sorted((d.path, d.kind, tuple(d.local), tuple(d.plugin)) for d in shown))
    d = (shown or [None])[0]
    return (False, (("%s: %s" % (d.path, d.kind)) if d is not None else "a difference"), len(shown) or 1,
            built, seen)


_MEDIA = ("img", "video")
_SKIP_TEXT = ("script", "style", "title", "head", "template", "noscript")
_CHROME = ("nav", "footer")             # the menu and footer are the nav's and the footer's settings; a look is not judged on them here


class _Reading(html.parser.HTMLParser):
    """What one page SHOWS in its content area: the text nodes, the number of images and videos, and the class names of its elements
    (`classes`, rule L4's coverage: an element counts when it is itself inside the area). The area is `<main>` where the page has one,
    else the body without its `header`, `nav` and `footer` elements (the page's chrome, never its content)."""

    def __init__(self, page):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.stack, self.texts, self.media, self.has_main = [], [], 0, "<main" in page.lower()
        self.classes = set()
        self.feed(page)
        self.close()

    def live(self, tags=None):
        tags = self.stack if tags is None else tags
        if any(t in _SKIP_TEXT or t in _CHROME for t in tags):
            return False
        if self.has_main:
            return "main" in tags
        return "header" not in tags or any(t in ("article", "section", "aside") for t in tags)

    def _classes(self, tag, attrs):
        cls = dict(attrs).get("class")
        if cls and self.live(self.stack + [tag]):
            self.classes.update(cls.split())

    def handle_starttag(self, tag, attrs):
        if tag in _MEDIA and self.live():
            self.media += 1
        self._classes(tag, attrs)
        if tag not in ("br", "hr", "img", "input", "meta", "link", "source", "wbr"):
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in _MEDIA and self.live():
            self.media += 1
        self._classes(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and re.search(r"[A-Za-z0-9]", text) and self.live():
            self.texts.append(text)


def lost_facts(local, plugin, name, pages=None):
    """{page: [loss]} of everything the plugin's pages LOSE that the old builder's pages show (D2, dev 941; rule L1 compares two
    of these, design-adopt-parity-2 section 6): on each page both builds write that the setting touches (or the `pages` named), each
    `<img>` or `<video>` the old page has and the plugin's page has no counterpart for, as `("media", k)` for each missing one past the
    plugin's count (so two readings of one page compare as sets: a page that shows one more picture loses one fewer), then each piece
    of text of the old page's content that the plugin's page does not hold, `("text", words)`, in the old page's order, once."""
    out = collections.OrderedDict()
    paths = judged_paths(name, local)
    for path in sorted(_subset(local, paths)):
        if not _is_page(path) or path not in plugin or (pages is not None and path not in pages):
            continue
        old, new = (_Reading(b[path].decode("utf-8", "replace")) for b in (local, plugin))
        lost = [("media", k) for k in range(new.media, old.media)]
        held = " ".join(new.texts)
        for words in old.texts:
            if words not in held and ("text", words) not in lost:
                lost.append(("text", words))
        if lost:
            out[path] = lost
    return out


def describe_loss(path, losses):
    """One page's losses as the sentence `lost_content` prints: its pictures first, else its first text."""
    media = sum(1 for kind, _v in losses if kind == "media")
    if media:
        return "%s: %d image(s) or video(s) of the old page are not on the plugin's page" % (path, media)
    return "%s: the old page's text %r is not on the plugin's page" % (path, losses[0][1][:40])


def lost_content(local, plugin, name):
    """The first thing the plugin's pages LOSE that the old builder's pages show, as a sentence, or "" when nothing is lost (D2, dev 941):
    on each page both builds write that the setting touches, an `<img>` or `<video>` the old page has and the plugin's page has no
    counterpart for (fewer of them), or a piece of text of the old page's content that the plugin's page does not hold (`lost_facts`,
    its first page). A candidate that loses content is never the one with 'fewest differences': a page that is missing what a visitor
    saw is not a page that differs a little. Asked last (`choose`, through `adoption.lookkeep`), with every other setting at its chosen
    value: a card number, a label or a featured piece's picture is another setting's to supply, so a look judged earlier would lose
    what a setting not yet chosen puts back."""
    for path, losses in lost_facts(local, plugin, name).items():
        return describe_loss(path, losses)
    return ""


def class_share(local, plugin):
    """Rule L4 (design-adopt-parity-2 section 6): (held, total) of the class names the old pages show in their content (counted once
    each, `_Reading.classes`) that are on the plugin's pages, in their content too."""
    def names(build):
        out = set()
        for path in build:
            if _is_page(path):
                out |= _Reading(build[path].decode("utf-8", "replace")).classes
        return out
    old = names(local)
    return len(old & names(plugin)), len(old)


_PIECE_HREF = re.compile(r"<a\b[^>]*\bhref=\"([^\"#?]+)\"", re.I)


def link_order(html, port, page):
    """The pieces `page` (an output path) links to, in order, as `<portfolio>/<slug>` (a piece appears once)."""
    seen = []
    for href in _PIECE_HREF.findall(html):
        if re.match(r"^[a-z][a-z0-9+.-]*:|^//", href, re.I):
            continue
        target = posixpath.normpath(href.lstrip("/") if href.startswith("/") else posixpath.join(posixpath.dirname(page), href))
        parts = re.sub(r"(?:^|/)index\.html$", "", target).strip("/").split("/")
        if len(parts) == 2 and parts[0] == port and "/".join(parts) not in seen:
            seen.append("/".join(parts))
    return seen


def score_order(local, plugin, name):
    """`score` for `sort.<portfolio>`: the order of the piece links on the portfolio's index page. ok when the two orders are the
    same; otherwise the count is the number of places where they differ. A page that links no piece in either build, or one that
    is not there, is no judgement (None): the caller keeps the default-first rule."""
    port = name.split(".", 1)[1]
    page = "%s/index.html" % port
    if page not in local or page not in plugin:
        return None
    want, got = (link_order(b[page].decode("utf-8", "replace"), port, page) for b in (local, plugin))
    if not want or sorted(want) != sorted(got):
        return None
    if want == got:
        return True, "", 0, frozenset((page,)), ()
    n = sum(1 for a, b in zip(want, got) if a != b)
    return False, "%s: the pieces are in another order" % page, n, frozenset((page,)), (tuple(got),)


def judge(local, plugin, name):
    """(ok, first visible difference line) for one candidate (`score` without the count)."""
    ok, why, _n, _paths, _seen = score(local, plugin, name)
    return ok, why


# ---- rule M4: visitor facts in scope (design-adopt-parity-2 sections 5.1 to 5.4) -------------------------------------------------
# A setting's SCOPE is a set of pages, fact kinds and marks (section 5.3). `look` has none (markup is its subject, section 6), and
# a setting without a row here is never judged by M4: it keeps 0.5.0's `you decide`.
_CARD_FAMS = ("cardLabels", "cardNumber", "cardNumberFormat", "cardImage", "cardAlt", "cardKicker")
_HEADING_FAMS = ("groupCount", "featuredView")
_PIECE_PAGE_FAMS = ("pieceLink", "pieceTeaser", "pieceRoles", "backLink")    # `backLink.<p>` has its own region (`scopes`)
_CHROME_FAMS = ("nav.home", "nav.extra", "menuLinks", "nav.labels.about", "nav.labels.resume")     # the two labels: schema 8
_CHROME_KINDS = ("link", "word", "current")


class Scope(object):
    """One scope of a setting: `pages(path)` says which output pages, `keep(fact)` which facts, `piecewise` whether the facts are
    those marked with a piece (judged only where both builds link the same pieces, section 5.1), and `files(path)`, when given, which
    published files are facts of their own (`file`, the path: section 5.3's "the set of published files of that folder"). `part` is
    the part of each page read (`facts`, the whole page; `above_title`, the facts before its title: `facts.Page`), and `own` says
    the scope is the setting's own region, so candidates that leave the same facts there change nothing in it (module docstring)."""

    def __init__(self, what, pages, keep, piecewise=False, files=None, part="facts", own=False):
        self.what, self.pages, self.keep, self.piecewise, self.files = what, pages, keep, piecewise, files
        self.part, self.own = part, own


PICTURE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg")


def _picture_file(path):
    """A published picture: where `mediaPaths` and `sizeCopies` move or add a file (every folder's media is a picture or a copy)."""
    return path.lower().endswith(PICTURE_EXTS)


def _piece_page(path, ports):
    parts = path.split("/")
    return len(parts) == 3 and parts[2] == "index.html" and parts[0] in ports


def _content(f):
    return f.area == "content"


def _in_a_heading(f):
    return f.area == "content" and (f.kind == "heading" or (f.kind == "word" and f.in_heading))


def scopes(name, ports, cands=()):
    """[Scope] of setting `name` on a site whose portfolios are `ports` (section 5.3); [] for a setting M4 does not judge.
    `workKeys` has two: its card half and its meta half. `carried`'s is the pages its candidates (`cands`) name, every fact of
    them and the files themselves (step 10b)."""
    fam = setting_family(name)
    if name == "carried":
        named = frozenset(p for c in cands or () for p in (c or ()))
        return [Scope("the carried pages", lambda p: p in named, lambda f: True, files=lambda p: p in named)] if named else []
    port = name.split(".", 1)[1] if fam != name and "." in name else None
    if port:
        home_and = lambda p: p in ("index.html", "%s/index.html" % port)               # noqa: E731
    else:
        home_and = lambda p: p == "index.html" or any(p == "%s/index.html" % q for q in ports)    # noqa: E731
    cards = Scope("the cards", home_and, lambda f: f.piece is not None, True)
    if fam in _CARD_FAMS:
        return [cards]
    if fam in _HEADING_FAMS:
        return [Scope("the headings", home_and, _in_a_heading)]
    if fam in _PIECE_PAGE_FAMS:
        pages = (lambda p: p.startswith(port + "/") and p != port + "/index.html") if port else (lambda p: _piece_page(p, ports))
        if fam == "backLink" and port:
            # its own region (step 8c): the back link is printed above the piece title, and nothing a visitor meets below the
            # title, or on another page, is this setting's to answer for
            return [Scope("above the piece titles", pages, _content, part="above_title", own=True)]
        return [Scope("the piece pages", pages, _content)]
    if fam == "workKeys":
        return [cards, Scope("the piece pages", lambda p: _piece_page(p, ports), _content)]
    if fam == "blocks.headings":
        return [Scope("the headings", _is_page, lambda f: f.kind == "heading")]
    if fam in _CHROME_FAMS:
        return [Scope("the menu", _is_page, lambda f: f.area == "chrome" and f.kind in _CHROME_KINDS)]
    if fam == "titleSeparator":
        return [Scope("the titles", _is_page, lambda f: f.kind == "title")]
    if fam == "titleForm":
        return [Scope("the titles", lambda p: p == "index.html", lambda f: f.kind == "title")]
    if fam == "resume.titleForm":                  # schema 8: the resume page's own `<title>`
        return [Scope("the titles", lambda p: p == "resume/index.html", lambda f: f.kind == "title")]
    if fam == "view" and port:
        return [Scope("the index", lambda p: p == port + "/index.html", _content)]
    if fam in ("blocks.videoEmbed", "blocks.unlistedVideos"):          # one address, two settings (dev 1060): the same players
        return [Scope("the players", _is_page, lambda f: f.kind in ("frame", "link"))]
    if fam in ("mediaPaths", "sizeCopies"):
        return [Scope("the pictures", _is_page, lambda f: f.kind == "imgfile", files=_picture_file)]
    return []


def _file_facts(build, keep):
    """The `file` facts of one build: a Counter of `Fact("file", path, ...)` for each published file `keep` names."""
    return collections.Counter(facts.Fact("file", p, "content", False, None) for p in build if keep(p))


def _kept(reading, keep, part="facts", facts_of=None):
    out = collections.Counter()
    for f, n in (facts_of if facts_of is not None else getattr(reading, part).items() if reading is not None else ()):
        if keep(f):
            out[f] = n
    return out


def _count_word(value):
    """The count's word of a heading fact's value ((level, words)): the last word, when the word before it is a number and it holds
    a letter (`Objects 1 object`: 'object'), else None."""
    ws = value[1]
    if len(ws) >= 2 and ws[-2].isdigit() and any(ch.isalpha() for ch in ws[-1]):
        return ws[-1]
    return None


def unwritten_count_words(old, new):
    """The old page's facts (a Counter) with each group count's word taken out where the plugin's page prints that heading with its
    count and without the word (owner decision 4; step 11): `Objects 1 object` read as `Objects 1`, and its word fact 'object' gone.
    That difference is `groupCount`'s to answer for, as the named ACCEPT row the conversion states ("the count prints alone",
    `adoption.accepts`), never a difference of another setting: with the word in every candidate's count, a setting whose default
    puts back everything else read `you decide` (template-portfolio-a: `view.work`, `cardNumberFormat`). `new` is the plugin's
    page's facts; a heading the plugin prints with the word, or without the count, is left as it is."""
    out = collections.Counter(old)
    for f in [f for f in old if f.kind == "heading"]:
        word = _count_word(f.value)
        if word is None:
            continue
        short = f._replace(value=(f.value[0], f.value[1][:-1]))
        n = min(old[f] - new.get(f, 0), new.get(short, 0) - old.get(short, 0))
        if n <= 0:
            continue
        out[f] -= n
        out[short] += n
        w = facts.Fact("word", word, f.area, True, f.piece)
        out[w] -= min(n, out[w])
    return +out


def _total(c):
    return sum(c.values())


def _first(c):
    return min(c, key=lambda f: (facts.KINDS.index(f.kind), repr(f))) if c else None


class FactsJudgement(object):
    """M4's answer for one setting: `winner` (the candidate's index, or None), `how` and `reason` (section 5.2), the candidates'
    distances (`distances`), and `tried` ([(candidate, the first fact in scope it leaves out or adds)]) when nobody won."""

    def __init__(self, winner, how, reason, distances, tried=()):
        self.winner, self.how, self.reason, self.distances, self.tried = winner, how, reason, distances, list(tried)


def _tally(scs, old_pages, cand_pages, drop, count_words=False):
    """Per candidate: the old pages' facts in scope it leaves out (`missing`), the ones it adds (`extra`), and how many differences
    of the same pages are outside the scope (`other`); the pages judged, and the NOT CHECKED lines of the pages left out. With
    `count_words`, each old page is read against each candidate's with the counts' unwritten words taken out (`unwritten_count_words`),
    and `worded` says, per candidate, whether that took a fact in scope out."""
    n = len(cand_pages)
    missing, extra, other = [collections.Counter() for _ in range(n)], [collections.Counter() for _ in range(n)], [0] * n
    worded = [False] * n
    judged, left_out = [], []
    every = set(old_pages).union(*[set(c) for c in cand_pages])
    for sc in scs:
        for path in sorted(p for p in every if sc.pages(p) and p not in drop):
            readings = [old_pages.get(path)] + [c.get(path) for c in cand_pages]
            bad = next((r for r in readings if isinstance(r, facts.Unreadable)), None)
            if bad is not None:
                left_out.append(bad.line())
                continue
            if sc.piecewise:
                linked = [r.linked if r is not None else set() for r in readings]
                odd = next((s for s in linked[1:] if s != linked[0]), None)
                if odd is not None:
                    diff = sorted(linked[0] ^ odd)
                    left_out.append("NOT CHECKED: %s links %d piece(s) the other build's page does not (first: %s)"
                                    % (path, len(diff), diff[0]))
                    continue
            judged.append(path)
            o0, o_all0 = _kept(readings[0], sc.keep, sc.part), _kept(readings[0], lambda f: True)
            for i, r in enumerate(readings[1:]):
                m, m_all = _kept(r, sc.keep, sc.part), _kept(r, lambda f: True)
                o, o_all = o0, o_all0
                if count_words and readings[0] is not None and r is not None:
                    o = _kept(None, sc.keep, facts_of=unwritten_count_words(getattr(readings[0], sc.part),
                                                                             getattr(r, sc.part)).items())
                    o_all = unwritten_count_words(readings[0].facts, r.facts)
                    worded[i] = worded[i] or o != o0
                missing[i] += o - m
                extra[i] += m - o
                other[i] += max(0, _total(o_all - m_all) + _total(m_all - o_all) - _total(o - m) - _total(m - o))
    return missing, extra, other, judged, sorted(set(left_out)), worded


def _same_pages(scs, outs, drop):
    """Per candidate: True when its build writes the same pages of the setting's scope as the default's (`outs[0]`). Only such a
    candidate can win by facts, as only such a one can win by count (`choose.decide`, M3): a build that leaves a page out (a view
    whose own page is not there, so the plugin's build refuses the tree and writes nothing) leaves out every fact on it, and wins
    whenever the default prints more that the old pages lack than they show. Found at step 9a2 on template-portfolio-a: `view.work`
    measured `page`, whose build refuses that tree. Step 11c extends it from a build that writes nothing to a build that writes and
    is refused (`refusals`: a problem the default's build does not have): such a candidate is never alike, so it never wins."""
    def pages(out):
        return frozenset(p for p in out if _is_page(p) and p not in drop and any(sc.pages(p) for sc in scs))
    first = pages(outs[0]) if outs else frozenset()
    return [pages(o) == first and not (i and refusals(o, outs[0])) for i, o in enumerate(outs)]


def judge_by_facts(name, cands, local, outs, ports, pieces, cache=None, drop=frozenset(), frame=None):
    """M4 for setting `name`: `cands` its candidates (default first), `outs` the plugin's output under each, `local` the old
    build, `ports` the portfolios, `pieces` the piece addresses (`facts.piece_addresses`), `drop` M1's one-build pages, `frame`
    how each build's addresses are read (`facts.Frame`: the old build under its own path with the recorded redirects, the plugin's
    under the site's path; None reads both at the root). The candidate with the UNIQUE smallest distance (the size of the symmetric
    difference of the old pages' facts and the plugin's, in scope, summed over the setting's pages, and for a scope with `files` the
    published files it names), smaller than the default's, wins (`how: measured`); else `you decide`. `featuredView` is judged on
    its headings first and by the order of the home's piece links only on a tie (section 5.4). None when the setting has no scope
    (section 5.3).

    Two readings of step 11 (owner decision 4, on template-portfolio-a): a group count's word the plugin's page leaves unwritten is
    `groupCount`'s (its ACCEPT row), so every OTHER setting reads the old pages without it (`unwritten_count_words`); and a DEFAULT
    that, so read, leaves out nothing the old pages show in scope, where what it left out before were those words, with the unique
    smallest distance, stays (`how: measured`): no candidate can put back more, and every other one prints more the old pages do not
    show. Before both, a setting whose default was already right read `you decide` because each candidate left out the same count
    word. Asked only where a count word was taken out: a default that leaves nothing out on another site keeps M4's rule as it was
    (a broader reading moved a held-out steps case at step 11, and is not made)."""
    scs = scopes(name, ports, cands)
    if not scs:
        return None
    frame = frame or facts.Frame()
    old_pages = facts.pages_of(local, pieces, frame.old_path, frame.moved, cache=cache)
    cand_pages = [facts.pages_of(o, pieces, frame.new_path, cache=cache) for o in outs]
    missing, extra, other, judged, left, worded = _tally(scs, old_pages, cand_pages, drop, setting_family(name) != "groupCount")
    for sc in scs:
        if sc.files is not None:
            o = _file_facts(local, sc.files)
            for i, out in enumerate(outs):
                m = _file_facts(out, sc.files)
                missing[i] += o - m
                extra[i] += m - o
    n = len(outs)
    if not judged:
        return FactsJudgement(None, "not measured", "not measured: " + ("; ".join(left) or "no page of its scope is in both builds"),
                              [None] * n)
    dist = [_total(missing[i]) + _total(extra[i]) for i in range(n)]
    alike = _same_pages(scs, outs, drop)
    best = min(dist[i] for i in range(n) if alike[i])
    wins = [i for i in range(n) if alike[i] and dist[i] == best]
    tail = ("; " + "; ".join(left)) if left else ""
    if all(sc.own for sc in scs) and all(missing[i] == missing[0] and extra[i] == extra[0] for i in range(n)):
        return FactsJudgement(0, "measured", "no candidate changes what a visitor meets %s: the default stays"
                              % " and ".join(sc.what for sc in scs) + tail, dist)
    heading_scope = any(sc.what == "the headings" for sc in scs)
    featured = setting_family(name) == "featuredView"
    if len(wins) == 1 and wins[0] != 0 and best < dist[0]:
        w = wins[0]
        line = _measured_line(missing[0], missing[w], extra[w], other[w], heading_scope)
        return FactsJudgement(w, "measured", line + (_order_note(local, outs[w], ports) if featured else "") + tail, dist)
    if wins == [0] and not missing[0] and worded[0] and n > 1:
        return FactsJudgement(0, "measured", "the default leaves out nothing the old pages show %s but the count's word that the "
                              "count prints without (groupCount's ACCEPT row), and every other candidate prints more they do not "
                              "(%d against %s)" % (" and ".join(sc.what for sc in scs), dist[0], ", ".join(
                                  str(dist[i]) if alike[i] else "other pages" for i in range(1, n))) + tail, dist)
    if featured and len(set(dist)) == 1:
        order = [_home_order(local, o, ports) for o in outs]
        if order.count(True) == 1 and alike[order.index(True)]:
            w = order.index(True)
            return FactsJudgement(w, "measured", "no heading differs between the candidates; the piece links on the home page are "
                                  "in the old page's order under %s and not under the others" % json.dumps(cands[w]) + tail, dist)
    tried = []
    for i, c in enumerate(cands):
        f, sign = (_first(missing[i]), "leaves out") if missing[i] else (_first(extra[i]), "adds")
        tried.append((c, ("%s %s" % (sign, facts.describe(f))) if f is not None else "leaves the same facts"))
    why = "; ".join("%s -> %s" % (c if isinstance(c, str) else json.dumps(c), w) for c, w in tried)
    if featured:
        why += "; " + "; ".join("%s: its order %s" % (json.dumps(c), {True: "matches", False: "differs", None: "is not judged"}[
            _home_order(local, o, ports)]) for c, o in zip(cands, outs))
    return FactsJudgement(None, "not measured", "no candidate puts back more of what the old pages show there than the others: "
                          + why + tail, dist, tried)


def _counts_by_kind(c, heading_scope):
    out = collections.OrderedDict()
    for f in sorted(c, key=lambda f: (facts.KINDS.index(f.kind), repr(f))):
        if heading_scope and f.kind == "word" and f.in_heading:
            continue                                       # a heading counts once, as a heading (section 5.2)
        out[f.kind] = out.get(f.kind, 0) + c[f]
    return out


def _measured_line(default_missing, winner_missing, winner_extra, other, heading_scope):
    """Section 5.2: "puts back 9 of 9 words and 4 of 4 picture names the old pages show there and prints nothing they do not
    (first: ...); 14 other differences on those pages are not this setting's"."""
    put_back = default_missing - winner_missing
    of = _counts_by_kind(default_missing, heading_scope)
    got = _counts_by_kind(put_back, heading_scope)
    parts = ["%d of %d %s" % (got.get(k, 0), m, facts.PLURAL[k]) for k, m in of.items()]
    head = ("puts back " + " and ".join(parts) + " the old pages show there") if parts else "puts back nothing the old pages show there"
    adds = "prints nothing they do not" if not winner_extra else "prints %d they do not" % _total(winner_extra)
    first = _first(put_back) or _first(winner_extra)
    return "%s and %s%s; %d other difference(s) on those pages are not this setting's" % (
        head, adds, (" (first: %s)" % facts.describe(first)) if first is not None else "", other)


def _home_order(local, plugin, ports):
    """True when the home page links the pieces in the old home's order (`link_order`, every portfolio), False when not, None when
    the old home links none."""
    want, got = [], []
    for port in sorted(ports):
        for side, acc in ((local, want), (plugin, got)):
            if "index.html" in side:
                acc.extend(link_order(side["index.html"].decode("utf-8", "replace"), port, "index.html"))
    if not want:
        return None
    return want == got


def _order_note(local, plugin, ports):
    ok = _home_order(local, plugin, ports)
    if ok is None:
        return ""
    return "; its piece links are in the old page's order" if ok else "; its piece links are not in the old page's order"
