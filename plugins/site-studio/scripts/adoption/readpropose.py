"""adoption.readpropose -- the `reads` entries adopt PROPOSES for the 0.8.0 targets (design-adopt-local-reach section 4a, named change N1,
part 2; dev #1035 to #1037). Part of the `adoption` package behind the entry point `adopt.py`.

THE LINE THIS HOLDS (design-adopt-ownership-line, 0.7.0's ownership line, unchanged): adopt PROPOSES, only the person writes
`site/looks/local.json`. Every proposal goes through `.site-studio/look-candidates.json` (`lookwrite.candidates_text`, key `reads`), the
scratch file parity already tells the person to copy from. Nothing here writes a file; `for_parity` returns a `Proposals`.

WHAT IS PROPOSED. For each target of `TARGETS`, a CLOSED set of candidates read from the old pages, never guessed:

  * the three picture targets (`card.wrap.image`, `home-showcase.item.image`, `roles-view.item.image`): an ordered list of
    `cover`, `photo`, `tileImage` that explains EVERY piece, i.e. for each piece whose picture an old page shows, the first listed key
    the piece holds is a key whose file the old page shows (`picture_orders`). No single list explains the pieces: no candidate;
  * `kicker.wrap.text`: the key the portfolios' `cardKicker` names (as chosen), then one built-in (`@portfolio`, `@group`) whose word
    the old pages print where the plugin's pages do not; at most two sources;
  * `reference-card.site.text`: `["@kind"]` and the `reference-card.kind-<kind>` words, for each kind whose every old card prints one
    constant word. A word read from FEWER instances than the plugin renders, or one that DIFFERS between instances, is never a literal
    (dev #980, `lookfiles.differs`): the proposal for that kind is not made, and the line says why with the flag `differs` writes.

Each candidate is built with the person's `lookLocal` laid (`snapshot(final)` carries it) and the candidate entry laid over it, and
measured on the pages the entry changes: it is proposed only when it leaves STRICTLY FEWER visible differences than the build without
it. Bounds: at most `PER_TARGET_BUILDS` builds for a target and `RUN_BUILDS` for a run, counted in `evaluate.builds` (parity's own
builds line); a target with candidates left once the run is spent says `not proposed: build budget`, naming itself.
"""

import html
import itertools
import json
import posixpath
import re

from adoption import lookperson
from adoption.lookwrite import LOOK_LOCAL_PATH
from building.pictures import CARD_IMAGE_TARGET, ROLES_IMAGE_TARGET, TILE_IMAGE_TARGET
from building.stepsview import KICKER
from lookfiles import differs, stamp
from lookfiles.pagedom import _STOP_UP, El, Tx, parse_dom, walk
from lookfiles.renderlog import Call
from lookgrammar.reads import KIND_BUILTIN, KIND_TARGET, PICTURE_KEYS

PER_TARGET_BUILDS = 3
RUN_BUILDS = 9
SCHEMA = 8                                  # the schema a 0.8.0 `reads` target needs
TARGETS = (CARD_IMAGE_TARGET, TILE_IMAGE_TARGET, ROLES_IMAGE_TARGET, KICKER, KIND_TARGET)
BUILTINS = ("@portfolio", "@group")
PROPOSED = "reads.%s: proposed -- %d fewer visible difference(s) on %d page(s); copy it into site/looks/local.json"
NOT_PROPOSED = "reads.%s: not proposed: build budget (%d builds this run)"
PARTLY = "reads.%s: not proposed: build budget (%d of %d candidates tried; %d builds this run)"
SETTLES = "; the picture entr%s %s in .site-studio/look-candidates.json settle%s it"
_FRONT = re.compile(r"\A---\n(.*?)\n---", re.S)
_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9]*):[ \t]*(.*?)[ \t]*$", re.M)
_ADDRESS = re.compile(r"(?:src|srcset|poster|data-src)\s*=\s*\"([^\"]*)\"|url\(([^)]*)\)")
_TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)


class Proposals(object):
    """What `for_parity` found: `entries` ({target: {"sources", "parts", "line"}} of the entries to copy), `lines` (what parity prints for
    a target it did not propose, with the reason) and `builds` (the builds made)."""

    def __init__(self):
        self.entries, self.lines, self.builds = {}, [], 0

    def reads(self):
        """The candidates file's `reads` value: each proposed entry with its sources, any parts it needs, and its line."""
        return dict((t, dict(e)) for t, e in sorted(self.entries.items()))

    def all_lines(self):
        return [e["line"] for _t, e in sorted(self.entries.items())] + list(self.lines)


# ----------------------------------------------------------------------------------------------------------- reading the old pages
def _front(blob):
    m = _FRONT.match(blob.decode("utf-8", "replace"))
    return dict(_KEY.findall(m.group(1))) if m else {}


def _stem(value):
    return posixpath.splitext(posixpath.basename(value.strip().strip("\"'")))[0]


def _text(markup):
    """The visible text of a page's markup, tags out, entities read, whitespace squashed."""
    return " ".join(html.unescape(_TAG.sub(" ", markup)).split())


def _old_html(local):
    return dict((p, b.decode("utf-8", "replace")) for p, b in local.items() if p.lower().endswith((".html", ".htm")))


def _picture_stems(pages):
    """The stems of every picture file the old pages name (an address, a `srcset` candidate, a `poster`, a CSS `url()`)."""
    out = set()
    for text in pages.values():
        for a, b in _ADDRESS.findall(text):
            for part in (a or b).split(","):
                token = part.split()[0] if part.split() else ""
                if token and not token.startswith("data:"):
                    out.add(_stem(token))
    return out


def _shown(stem, stems):
    """Does an old page name the file `stem`, or a file made from it (`c-640.webp`, `c_2x.png`)?"""
    return bool(stem) and any(s == stem or (s.startswith(stem) and s[len(stem)] in "-_." ) for s in stems if len(s) >= len(stem))


def pieces_of(files, stems):
    """{piece folder: (keys, shown)}: `keys` ({picture key: file stem}) of each piece that holds one, and `shown` the keys whose file an
    old page names. Read from the converted tree's own front matter (`files`) and the old pages' picture names (`stems`)."""
    out = {}
    for path, blob in files.items():
        m = re.match(r"^(content/[^/]+/[^/]+)/index\.md$", path)
        if not m or m.group(1).split("/")[1].startswith("_"):
            continue
        front = _front(blob)
        keys = dict((k, _stem(front[k])) for k in PICTURE_KEYS if front.get(k))
        if keys:
            out[m.group(1)] = (keys, set(k for k, s in keys.items() if _shown(s, stems)))
    return out


def _explains(order, pieces):
    """Does the ordered list `order` pick, for every piece whose picture an old page shows, a key whose file is the one shown?"""
    seen = False
    for keys, shown in pieces.values():
        if not shown:
            continue
        seen = True
        first = next((k for k in order if k in keys), None)
        if first not in shown:
            return False
    return seen


def picture_orders(pieces):
    """The ordered lists of picture keys (one or two) that explain every piece, most evidence first: the closed set a picture
    target's candidates are drawn from. Empty when no single list explains every piece (a site whose pieces disagree)."""
    count = dict((k, sum(1 for _ks, shown in pieces.values() if k in shown)) for k in PICTURE_KEYS)
    used = sorted((k for k in PICTURE_KEYS if count[k]), key=lambda k: (-count[k], PICTURE_KEYS.index(k)))
    return [o for n in (1, 2) for o in itertools.permutations(used, n) if _explains(o, pieces)]


def _applies(target, files):
    """Is there a place for `target` in this tree at all? The tile target needs a showcase, the roles target a roles view."""
    home = files.get("content/home.md", b"").decode("utf-8", "replace")
    if target == TILE_IMAGE_TARGET:
        return bool(re.search(r"^showcase:", home, re.M) or re.search(r"^featuredFrom:\s*showcase\s*$", home, re.M))
    if target == ROLES_IMAGE_TARGET:
        return any(re.match(r"^content/[^/]+/page\.md$", p) and _front(b).get("view") == "roles" for p, b in files.items())
    return True


def picture_candidates(target, files, local):
    """[(sources,)]: the candidates of picture `target`, from the old pages' pictures (`picture_orders`), none where the target has no
    place in the tree or no key's file is shown."""
    if not _applies(target, files):
        return []
    return [(list(o),) for o in picture_orders(pieces_of(files, _picture_stems(_old_html(local))))]


def _count(text, word):
    return len(re.findall(r"(?<![\w])%s(?![\w])" % re.escape(word), text))


def _labels(files):
    """{built-in: [the words it prints]}: `@portfolio` the portfolios' `label`s, `@group` the `labels.groups` values and group names."""
    portfolio, group = set(), set()
    cfg = {}
    try:
        cfg = json.loads(files["site/site.json"].decode("utf-8"))
    except (KeyError, ValueError):
        pass
    for p, blob in files.items():
        if re.match(r"^content/[^/]+/page\.md$", p):
            front = _front(blob)
            if front.get("label"):
                portfolio.add(front["label"].strip("\"'"))
    for conf in [v for v in cfg.values() if isinstance(v, dict) and ("label" in v or "groups" in v)]:
        if isinstance(conf.get("label"), str):
            portfolio.add(conf["label"])
        g = conf.get("groups")
        group.update(x for x in (g if isinstance(g, list) else []) if isinstance(x, str))
        names = (conf.get("labels") or {}).get("groups")
        group.update(v for v in (names.values() if isinstance(names, dict) else ()) if isinstance(v, str))
    return {"@portfolio": sorted(portfolio), "@group": sorted(group)}


def kicker_candidates(files, final, local, w_out):
    """[(sources,)]: the key each portfolio's chosen `cardKicker` names, then a built-in whose word an old page prints more often than
    the plugin's page does (the missing fallback of dev #1036), at most two sources. None without such a word."""
    keys = sorted(set(v for k, v in final.items() if k.startswith("cardKicker.") and isinstance(v, str) and v))
    words, have = _labels(files), []
    old = _old_html(local)
    for built in BUILTINS:
        for page, text in old.items():
            mine = w_out.get(page)
            if mine is None:
                continue
            plain, theirs = _text(text), _text(mine.decode("utf-8", "replace"))
            if any(_count(plain, w) > _count(theirs, w) for w in words[built]):
                have.append(built)
                break
    return [([k, b] if k else [b],) for b in have for k in (keys or [None])]


# -------------------------------------------------------------------------------------------------------------- the reference kinds
def _references(files):
    """[(name, reference dict)] of `content/references/<name>/reference.json`, in name order; one that does not parse is left out."""
    out = []
    for path, blob in sorted(files.items()):
        m = re.match(r"^content/references/([^/]+)/reference\.json$", path)
        if m:
            try:
                data = json.loads(blob.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("kind"), str) and isinstance(data.get("url"), str):
                out.append((m.group(1), data))
    return out


def _nodes(el):
    """The text nodes under `el`, each squashed to single spaces, those with no text left out."""
    for k in el.kids:
        if isinstance(k, Tx):
            t = " ".join(k.data.split())
            if t:
                yield t
        elif isinstance(k, El):
            for t in _nodes(k):
                yield t


def _under(el, ancestor):
    while el is not None:
        if el is ancestor:
            return True
        el = el.parent
    return False


def _cards(markup, urls):
    """{url: [the card's text nodes, one list per card of it on the page]}: a card is the largest element that holds one anchor to
    an address of `urls` and no other (the wrapper a look puts around a card is its own, the list around many is not)."""
    root = parse_dom(markup)
    anchors = [e for e in walk(root) if e.tag == "a" and dict(e.attrs).get("href") in urls]
    out = {}
    for a in anchors:
        region = a
        while region.parent is not None and region.parent.tag not in _STOP_UP and \
                sum(1 for e in anchors if _under(e, region.parent)) == 1:
            region = region.parent
        out.setdefault(dict(a.attrs)["href"], []).append(list(_nodes(region)))
    return out


def _on_pages(pages, urls):
    out = {}
    for markup in pages.values():
        for url, found in _cards(markup, urls).items():
            out.setdefault(url, []).extend(found)
    return out


def kind_words(files, local, w_out):
    """({kind: word}, [line]): the one word each kind's old cards print, for a kind whose every old card prints one constant word, and a
    line for each kind that does not. The word of a card is the text the old card holds that the plugin's own card of the same reference
    does not (the leftover, in the old card's order); it is a literal only when EVERY card of the kind the plugin renders was read and
    they leave one word. Read from fewer instances, or differing between instances, it is never a literal (dev #980): the line quotes
    the flag `lookfiles.differs` writes for it."""
    refs = dict((r["url"], r) for _n, r in _references(files))
    old, mine = _on_pages(_old_html(local), set(refs)), _on_pages(_old_html(w_out), set(refs))
    words, lines = {}, []
    for kind in sorted(set(r["kind"] for r in refs.values())):
        urls = sorted(u for u, r in refs.items() if r["kind"] == kind)
        rendered = sum(len(mine.get(u, ())) for u in urls)
        read = []
        for u in urls:
            own = set(n for nodes in mine.get(u, ()) for n in nodes)
            read.extend(" ".join(n for n in nodes if n not in own) for nodes in old.get(u, ()))
        if not rendered or not read:
            continue
        flagged = _kind_flag(kind, read, rendered)
        if flagged is None:
            if read[0]:
                words[kind] = read[0]
        else:
            lines.append("reads.%s: not proposed for kind %s -- %s" % (KIND_TARGET, kind, flagged))
    return words, lines


def _kind_flag(kind, read, rendered):
    """None when every instance of `kind` was read and they print one word, else the flag `lookfiles.differs` writes for it."""
    calls = [Call(i, "reference-card", "kind-page", {}, "") for i in range(len(read))]     # a text-only part: its table holds no slot
    template = max(sorted(set(read)), key=read.count)
    flag = differs.flag(template, list(zip(read, calls)))
    if flag != template:
        return flag
    if len(read) < rendered:
        return differs.FLAG % ("%s: read from %d of %d instances" % (template, len(read), rendered))
    return None


# --------------------------------------------------------------------------------------------------------------------- measuring
def lay(files, target, sources, parts=None):
    """`files` with the entry `target: sources` (and the text-only `parts` {construct: {part: text}}) laid in `site/looks/local.json`
    over what the tree holds there, as the next parity would see it were the person to copy it, and `lookLocal` and schema 8 in
    `site.json`. IN MEMORY: the copy of the files the build is made from, never a file on disk."""
    out = dict(files)
    try:
        look = json.loads(out[LOOK_LOCAL_PATH].decode("utf-8"))
    except (KeyError, ValueError):
        look = {"look": 1, "constructs": {}}
    look.setdefault("reads", {})[target] = list(sources)
    for construct, texts in (parts or {}).items():
        look.setdefault("constructs", {}).setdefault(construct, {}).update(texts)
    out[LOOK_LOCAL_PATH] = stamp.look_text(look).encode("utf-8")
    cfg = json.loads(out["site/site.json"].decode("utf-8"))
    cfg["lookLocal"] = LOOK_LOCAL_PATH
    cfg["schema"] = max(cfg["schema"] if isinstance(cfg.get("schema"), int) else 1, SCHEMA)
    out["site/site.json"] = (json.dumps(cfg, indent=2) + "\n").encode("utf-8")
    return out


class _Run(object):
    """One run's measurement: the final build W (`w_out`), the tree it was made from (`files`), the old build and the bounds."""

    def __init__(self, files, local, w_out, build, start):
        self.files, self.local, self.w, self.build, self.start = files, local, w_out, build, start
        self.tried = 0

    def spent(self, evaluate):
        return evaluate.builds - self.start

    def measure(self, target, sources, parts=None):
        """(fewer, pages) of the candidate entry, or None when the build refuses it or it changes no page."""
        got = self.build(lay(self.files, target, sources, parts))
        if getattr(got, "problems", None):
            return None
        pages = sorted(p for p, b in got.items() if p.lower().endswith((".html", ".htm")) and self.w.get(p) != b)
        if not pages:
            return None
        return lookperson.visible(self.local, self.w, pages)[0] - lookperson.visible(self.local, got, pages)[0], len(pages)


def for_parity(view, final, local, snapshot, evaluate, targets=TARGETS):
    """`parity`'s proposals, after the settings pass (called where `lookperson.for_parity` is): the person's tree `view` (a tree with
    `exists` and `read`), the `final` settings, the old build `local`, `snapshot(settings)` the converted tree as files, `evaluate` the
    memo of builds (its `builds` count is parity's). Returns `Proposals`. An entry the person already wrote is never proposed again."""
    out = Proposals()
    if local is None:
        return out
    files = snapshot(final)
    own = {}
    if view.exists(LOOK_LOCAL_PATH):
        try:
            own = json.loads(view.read(LOOK_LOCAL_PATH).decode("utf-8")).get("reads") or {}
        except (ValueError, AttributeError):
            own = {}
    w_out = evaluate(final)
    run = _Run(files, local, w_out, lookperson.counting(evaluate), evaluate.builds)
    for target in targets:
        if target in own:
            continue
        candidates, parts, notes = _candidates(target, files, final, local, w_out)
        out.lines.extend(notes)
        if not candidates:
            continue
        left = RUN_BUILDS - run.spent(evaluate)
        if left <= 0:
            out.lines.append(NOT_PROPOSED % (target, RUN_BUILDS))
            continue
        best = None
        for sources in candidates[:min(PER_TARGET_BUILDS, left)]:
            got = run.measure(target, sources, parts)
            if got is not None and got[0] > 0 and (best is None or got[0] > best[0]):
                best = (got[0], got[1], sources)
        if best is not None:
            out.entries[target] = {"sources": best[2], "line": PROPOSED % (target, best[0], best[1])}
            if parts:
                out.entries[target]["parts"] = parts
        elif len(candidates) > min(PER_TARGET_BUILDS, left) and left < PER_TARGET_BUILDS:
            out.lines.append(PARTLY % (target, min(PER_TARGET_BUILDS, left), len(candidates), RUN_BUILDS))
    out.builds = run.spent(evaluate)
    return out


def _candidates(target, files, final, local, w_out):
    """(the candidate source lists of `target` in the order they are tried, the text-only parts the entry needs, the lines to print)."""
    if target == KICKER:
        return [c[0] for c in kicker_candidates(files, final, local, w_out)], None, []
    if target == KIND_TARGET:
        words, notes = kind_words(files, local, w_out)
        parts = {"reference-card": dict(("kind-%s" % k, html.escape(w, quote=False)) for k, w in sorted(words.items()))}
        return ([[KIND_BUILTIN]] if words else []), (parts if words else None), notes
    return [c[0] for c in picture_candidates(target, files, local)], None, []


def name_in_rows(rows, proposals):
    """Where a `cardImage.<portfolio>` row is `you decide` (tied) and a picture entry was proposed, the row's reason names the entries
    that settle it (`rows`: {setting name: choose.Row}). Returns the names changed."""
    pictures = sorted(t for t in proposals.entries if t in (CARD_IMAGE_TARGET, TILE_IMAGE_TARGET, ROLES_IMAGE_TARGET))
    if not pictures:
        return []
    named = []
    for name, row in sorted(rows.items()):
        if name.startswith("cardImage.") and getattr(row, "how", None) == "not measured":
            row.reason += SETTLES % ("y" if len(pictures) == 1 else "ies", " and ".join("reads." + t for t in pictures),
                                     "s" if len(pictures) == 1 else "")
            named.append(name)
    return named
