"""adoption.homeparts -- the order the OLD home page shows its parts in, read from the old build (design 8, `partOrder` and `introScope`).

Part of the `adoption` package behind the entry point `adopt.py`. Pure over the converted tree ({path: bytes}) and the old builder's
output ({path: bytes}); it names no setting's value, it only OFFERS a candidate, and `adoption.choose` keeps it only when the plugin's
build agrees (the candidate is built and compared like every other setting's).

The generated home page (schema 4) prints its parts in a fixed order unless `partOrder` names another: `intro` (the photo, the
intro, the endorsement), `rest` (what follows the body's first block, under `introScope: first-block`), `featured`, `showcase`,
`feed`, `samples`, `links`, `contact`, and each `:::part` block of the body. The old page printed them in its own order, so each part
is given the TEXT it prints (`parts`: a piece's title for a showcase, a reference's title for a feed, a block's own words), the text
nodes of the old home page's body are read in order (`text_nodes`), and a part sits where its text is found (`placement`).

A text can occur twice (a piece is both in the showcase and featured). Parts claim text nodes longest-first, a node claimed once is
not claimed again, so a part with two titles takes the two places that hold both and the part with one title takes the other.
That is a reading, not a proof: what two parts that share their only text do is a guess, which is why the order is MEASURED.
"""

import html.parser
import json
import re

import siteconfig

from adoption.template import entries, scalar, split_front

HOME_PATHS = ("content/home/index.md", "content/home/home.md", "content/home.md")
MIN_ANCHOR = 3                    # a text shorter than this ("40") says nothing about where a part is


def home_in(snap):
    """The converted home page's path in `snap`, or None."""
    return next((p for p in HOME_PATHS if p in snap), None)


def _text(snap, path):
    return snap[path].decode("utf-8", "replace")


def front_values(front):
    """{key: value}: a one-line value is a string, `[a, b]` or `- a` lines a list, indented `k: v` lines a dict. Quotes are removed."""
    out = {}
    for ent in entries(front):
        key = ent[0]
        if not key:
            continue
        one = scalar(ent)
        if one is not None:
            out[key] = [x.strip().strip("\"'") for x in one[1:-1].split(",") if x.strip()] if one.startswith("[") else one
            continue
        items, pairs = [], {}
        for line in ent[1][1:]:
            s = line.strip()
            if s.startswith("- "):
                items.append(s[2:].strip().strip("\"'"))
            elif ":" in s:
                k, _c, v = s.partition(":")
                pairs[k.strip()] = v.strip().strip("\"'")
        out[key] = items if items else pairs
    return out


def plain(line):
    """A line of the page's markdown as the words it prints: the block syntax and the inline marks are gone."""
    s = line.strip()
    s = re.sub(r"^(#+\s+|[-*+]\s+|>\s*)", "", s)
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"[*_`]+", "", s).strip()


def anchors_of(lines):
    """The texts a run of body lines prints: each line's words, a `a | b` line as two texts; block fences and short texts left out."""
    out = []
    for line in lines:
        if line.strip().startswith(":::"):
            continue
        for piece in plain(line).split("|"):
            piece = " ".join(piece.split())
            if len(piece) >= MIN_ANCHOR and not piece.isdigit():
                out.append(piece)
    return out


def body_blocks(body):
    """(blocks, parts): the top-level blocks of the home body outside a `:::part` as lists of lines, and {part name: its lines} in file
    order. A `:::kind` block nests; a bare `:::` closes the innermost."""
    blocks, parts, cur, depth, name, held = [], {}, [], 0, None, []
    for line in body:
        s = line.strip()
        if name is not None:                                     # inside a part
            if s == ":::":
                depth -= 1
                if depth == 0:
                    parts[name], name = held, None
                    continue
            elif s.startswith(":::"):
                depth += 1
            held.append(line)
        elif s.startswith(":::part") and depth == 0:
            words = s[len(":::part"):].split()
            name, held, depth = (words[0] if words else ""), [], 1
            if cur:
                blocks.append(cur)
                cur = []
        elif s.startswith(":::"):                                # a block of the body outside a part
            depth = max(depth - 1, 0) if s == ":::" else depth + 1
            cur.append(line)
        elif not s and depth == 0:
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)
    return blocks, parts


def _title(snap, portfolio, slug):
    for name in ("index.md", "work.md"):
        path = "content/%s/%s/%s" % (portfolio, slug, name)
        if path in snap:
            front, _b, _h = split_front(_text(snap, path))
            return str(front_values(front).get("title") or "")
    return ""


def _reference_title(snap, name):
    path = "content/references/%s/reference.json" % name
    try:
        return str(json.loads(_text(snap, path)).get("title") or "")
    except (KeyError, ValueError, AttributeError):
        return ""


def _pieces(snap):
    for path in sorted(snap):
        parts = path.split("/")
        if len(parts) == 4 and parts[0] == "content" and parts[3] in ("index.md", "work.md") and not parts[1].startswith("_"):
            yield parts[1], parts[2]


def _flagged_titles(snap):
    """The titles of the pieces that carry `featured: true`."""
    out = []
    for portfolio, slug in _pieces(snap):
        for name in ("index.md", "work.md"):
            path = "content/%s/%s/%s" % (portfolio, slug, name)
            if path in snap:
                if re.search(r"(?mi)^featured:\s*(true|yes)\s*$", _text(snap, path)):
                    out.append(_title(snap, portfolio, slug))
                break
    return [t for t in out if t]


def parts(snap, scope="body"):
    """{part: [the texts it prints, in order]} for the parts the converted home page holds, in the build's default order
    (`siteconfig.HOME_SECTIONS` with the body's own parts after `rest`). A part with no text to look for is absent: it cannot be placed.
    `scope` is the `introScope` the page is built under: under `body` the intro holds every block outside a `:::part` and there is no
    `rest` (a `partOrder` naming it is refused); under `first-block` the intro holds the first block and `rest` the others."""
    path = home_in(snap)
    if path is None:
        return {}
    front, body, _had = split_front(_text(snap, path))
    fm = front_values(front)
    blocks, named = body_blocks(body)
    out = {}
    if blocks:
        quote = fm.get("endorsement")
        shown = blocks[:1] if scope == "first-block" else blocks
        out["intro"] = [a for b in shown for a in anchors_of(b)] + ([quote["quote"]] if isinstance(quote, dict) and quote.get("quote") else [])
    if len(blocks) > 1 and scope == "first-block":
        out["rest"] = [a for b in blocks[1:] for a in anchors_of(b)]
    out["featured"] = _flagged_titles(snap)
    show = fm.get("showcase")
    out["showcase"] = [_title(snap, *i.split("|")[0].strip().split("/")[:2]) for i in show if "/" in i] if isinstance(show, list) else []
    for key in ("feed", "samples"):
        names = fm.get(key)
        out[key] = [_reference_title(snap, n) for n in names] if isinstance(names, list) else []
    links = fm.get("links")
    out["links"] = list(links) if isinstance(links, dict) else []
    contact = fm.get("contact")
    out["contact"] = [str(v) for v in (contact.values() if isinstance(contact, dict) else contact or [])]
    for name, lines in named.items():
        out[name] = anchors_of(lines)
    order = ["intro", "rest"] + list(named) + [n for n in siteconfig.HOME_SECTIONS if n not in ("intro", "rest")]
    shown = dict((n, [a for a in out.get(n, ()) if len(a) >= MIN_ANCHOR]) for n in order)
    return dict((n, a) for n, a in shown.items() if a)


class _Text(html.parser.HTMLParser):
    """The text nodes of an HTML page's body, in order, whitespace collapsed; script and style text left out."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self._in_body, self._skip = [], False, 0

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
        elif tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and self._in_body and not self._skip:
            self.nodes.append(text.lower())


def text_nodes(blob):
    """The text nodes of the page `blob` (bytes), lower-cased, in the order a visitor reads them."""
    reader = _Text()
    reader.feed(blob.decode("utf-8", "replace"))
    return reader.nodes


def _match(nodes, anchors, used):
    """[node index] for the best run that finds every anchor in order (the shortest span, the earliest), or None."""
    best = None
    for start in range(len(nodes)):
        if start in used or anchors[0].lower() not in nodes[start]:
            continue
        run, at = [start], start
        for a in anchors[1:]:
            nxt = next((i for i in range(at + 1, len(nodes)) if i not in used and a.lower() in nodes[i]), None)
            if nxt is None:
                break
            run.append(nxt)
            at = nxt
        if len(run) == len(anchors) and (best is None or run[-1] - run[0] < best[-1] - best[0]):
            best = run
    return best


def placement(held, nodes):
    """{part: the node index it starts at}: parts claim text nodes longest-first, and a node is claimed once. A part none of whose
    text is found is not placed."""
    used, placed = set(), {}
    for name in sorted(held, key=lambda n: -len(held[n])):          # a stable sort: a tie keeps the build's default order
        run = _match(nodes, held[name], used)
        if run is None:                                             # not all of it, in order: the first text that is found at all
            for a in held[name]:
                run = _match(nodes, [a], used)
                if run:
                    break
        if run:
            used.update(run)
            placed[name] = run[0]
    return placed


def old_order(snap, local, scope="body"):
    """The parts of the converted home in the order the old home page prints them, or None when there is nothing to offer: no home
    page, no old home page, fewer than two parts placed, or the old page prints them in the order the build does anyway."""
    held = parts(snap, scope)
    page = (local or {}).get("index.html")
    if not held or page is None:
        return None
    placed = placement(held, text_nodes(page))
    order = sorted(placed, key=lambda n: (placed[n], list(held).index(n)))
    if len(order) < 2 or order == [n for n in held if n in placed]:
        return None
    return order + [n for n in held if n not in placed]


def block_count(snap):
    """How many top-level blocks the converted home body holds outside its `:::part` blocks."""
    path = home_in(snap)
    if path is None:
        return 0
    return len(body_blocks(split_front(_text(snap, path))[1])[0])
