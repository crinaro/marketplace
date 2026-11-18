"""adoption.blocks -- the TEMPLATE class `blocks` (design 8 B1, #898): the template's body lines as the plugin's containers.

Part of the `adoption` package behind the entry point `adopt.py`.

THE FORMS. In a Markdown body, a run of lines (a paragraph: lines with no blank line between) that is

  * every line `tile: <figure> | <text>`          ->  `:::tiles` with one row `<figure> | <text>` per line
  * every line `video: <title> | <url>`           ->  `:::videos` with one row `<title> | <url>` per line
  * `> ` lines holding ONE quote ended by a `> — Who` line  ->  `:::quote`, the words, then `— Who`
  * `> ` lines holding SEVERAL quotes, each ended by its `> — Who` line  ->  `:::quotes` (schema 4)
  * image lines `![alt](path "caption")` (at least two)  ->  `:::gallery`; a LONE image line (no caption, no address)
    standing directly before such a run leads the same gallery
  * an image line with a trailing address `![alt](path "caption") <url>`  ->  a gallery video row (schema 4), in a
    `:::gallery` with the lines around it

is rewritten, and nothing else is touched: every other byte of the file, the front matter included, stays. `:::carousel`
is kept as written (the plugin has it), a titled image on its own line is the plugin's own figure, and `ref:` lines are the
plugin's reference cards in place. A paragraph that opens like one of the forms but cannot be converted (a quote with no
`— ` line among several, a `tile:` line beside a prose line) is left as text and named by `blocks_left`, with its path and
line: adopt's `check` prints each, so the person is told what stays a paragraph. Lines inside a `:::` container are
never read (a carousel slide, a part).

PURE FUNCTIONS over a `Tree`/`TreeFiles`; nothing here reads a file but through it.
"""

import re

_TILE = re.compile(r"^tile: (.+?) \| (.+)$")
_VIDEO = re.compile(r"^video: (.+?) \| (\S+)$")
_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?: \"([^\"]*)\")?\)(?: (\S+))?$")
_OPENER = re.compile(r"^:::[A-Za-z]")
_FENCE = re.compile(r"^```")


def body_files(tree):
    """The Markdown files whose bodies hold template blocks: every `.md` under `content/` that is not a reference
    (`reference.json` is JSON) and is not inside a `_`-named folder (kept source material, never built)."""
    out = []
    for p in sorted(tree.paths()):
        if (p.startswith("content/") and p.lower().endswith(".md")
                and not any(seg.startswith("_") for seg in p.split("/")[:-1])):
            out.append(p)
    return out


def _split(text):
    """(front matter lines incl. the closing `---`, body lines): a file with no front matter is all body."""
    lines = text.split("\n")
    if lines and lines[0].rstrip() == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                return lines[:i + 1], lines[i + 1:]
    return [], lines


def _paragraphs(body):
    """[(start index, [lines])]: the runs of non-blank lines of `body`, skipping every line inside a `:::` container
    or a code fence (their content is never read)."""
    out, cur, depth, fence = [], None, 0, False
    for i, line in enumerate(body):
        s = line.rstrip()
        skip = False
        if _FENCE.match(s):
            fence, skip = not fence, True
        elif fence:
            skip = True
        elif depth > 0 or _OPENER.match(s) or s == ":::":
            if _OPENER.match(s):
                depth += 1
            elif s == ":::" and depth > 0:
                depth -= 1
            skip = True
        elif not s.strip():
            skip = True
        if skip:
            if cur is not None:
                out.append(cur)
                cur = None
            continue
        if cur is None:
            cur = (i, [])
        cur[1].append(s)
    if cur is not None:
        out.append(cur)
    return out


def _quotes(lines):
    """[(words, who or None)] for a run of `> ` lines, or None when a line is not one."""
    qs = []
    for line in lines:
        if not line.startswith("> "):
            return None
        t = line[2:]
        if t.startswith("— ") and qs and qs[-1][1] is None:
            qs[-1] = (qs[-1][0], t[2:].strip())
        else:
            qs.append((t, None))
    return qs


def _gallery_lines(lines):
    return all(_IMAGE.match(l) for l in lines)


def _classify(lines, nxt):
    """(kind, replacement lines, lines consumed from `nxt` (the next paragraph or None)) for one paragraph, or
    (None, why, 0): `why` is "" when the paragraph is not a template form at all."""
    first = lines[0]
    if all(_TILE.match(l) for l in lines):
        return "tiles", [":::tiles"] + [_TILE.match(l).expand(r"\1 | \2") for l in lines] + [":::"], 0
    if all(_VIDEO.match(l) for l in lines):
        return "videos", [":::videos"] + [_VIDEO.match(l).expand(r"\1 | \2") for l in lines] + [":::"], 0
    if first.startswith("> ") and all(l.startswith("> ") for l in lines):
        qs = _quotes(lines)
        if qs is None or not qs:
            return None, "", 0
        if len(qs) == 1:
            if qs[0][1] is None:
                return None, "", 0          # an unattributed `>` is the Markdown blockquote: the plugin renders it as it is
            return "quote", [":::quote", qs[0][0], "— " + qs[0][1], ":::"], 0
        if any(who is None for _w, who in qs):
            return None, "a `>` block with several quotes, one with no `— ` line (every quote in `:::quotes` needs one)", 0
        body = []
        for words, who in qs:
            body += [words, "— " + who]
        return "quotes", [":::quotes"] + body + [":::"], 0
    if _gallery_lines(lines):
        lone = (len(lines) == 1 and _IMAGE.match(lines[0]).group(3) is None and _IMAGE.match(lines[0]).group(4) is None)
        if lone and nxt is not None and len(nxt) > 1 and _gallery_lines(nxt):
            return "gallery", [":::gallery"] + lines + nxt + [":::"], len(nxt)
        if len(lines) > 1:
            kind = "gallery video" if any(_IMAGE.match(l).group(4) for l in lines) else "gallery"
            return kind, [":::gallery"] + lines + [":::"], 0
        m = _IMAGE.match(lines[0])
        if m.group(4):
            return "gallery video", [":::gallery"] + lines + [":::"], 0
        return None, "", 0                  # one image line: the plugin's own image or titled figure
    if any(_TILE.match(l) or _VIDEO.match(l) for l in lines) and len(lines) > 1:
        return None, "a paragraph that mixes `tile:` or `video:` lines with other lines", 0
    return None, "", 0


def block_rewrites(tree, only=None):
    """{path: (new text, [(line, form)])} for each file whose body holds a template block; `line` is the 1-based line of
    the first line the rewrite replaced. `only` limits the files (a set of paths)."""
    out = {}
    for path in body_files(tree):
        if only is not None and path not in only:
            continue
        try:
            text = tree.text(path)
        except (KeyError, UnicodeDecodeError):
            continue
        crlf = "\r\n" in text
        flat = text.replace("\r\n", "\n")
        front, body = _split(flat)
        paras = _paragraphs(body)
        edits, skip = [], set()
        for k, (start, lines) in enumerate(paras):
            if k in skip:
                continue
            nxt = paras[k + 1][1] if k + 1 < len(paras) and paras[k + 1][0] == start + len(lines) + 1 else None
            kind, repl, used = _classify(lines, nxt)
            if kind is None:
                continue
            if used:
                skip.add(k + 1)
                span = (start, paras[k + 1][0] + used)
            else:
                span = (start, start + len(lines))
            edits.append((span, repl, kind, len(front) + start + 1))
        if not edits:
            continue
        new_body = list(body)
        for (a, b), repl, _kind, _ln in sorted(edits, key=lambda e: e[0][0], reverse=True):
            new_body[a:b] = repl
        new = "\n".join(front + new_body)
        out[path] = ((new.replace("\n", "\r\n") if crlf else new), [(ln, kind) for _s, _r, kind, ln in sorted(edits, key=lambda e: e[0][0])])
    return out


def blocks_left(tree):
    """[(path, line, why)] for every paragraph that opens like a template form but cannot be converted, so `check` can say
    what stays text. Never raises."""
    out = []
    for path in body_files(tree):
        try:
            text = tree.text(path)
        except (KeyError, UnicodeDecodeError):
            continue
        front, body = _split(text.replace("\r\n", "\n"))
        paras = _paragraphs(body)
        for k, (start, lines) in enumerate(paras):
            nxt = paras[k + 1][1] if k + 1 < len(paras) and paras[k + 1][0] == start + len(lines) + 1 else None
            kind, why, _used = _classify(lines, nxt)
            if kind is None and why:
                out.append((path, len(front) + start + 1, why))
    return out


def piece_pages(path):
    """The output page a body file builds, for the class's output paths: `content/<p>/<s>/index.md` is `<p>/<s>/`, a
    portfolio `page.md` is `<p>/index.html`, and any other content page is `*` (its address is the build's to say)."""
    parts = path.split("/")
    if len(parts) == 4 and parts[3] in ("work.md", "index.md") and parts[0] == "content":
        return "%s/%s/" % (parts[1], parts[2])
    if len(parts) == 3 and parts[2] == "page.md":
        return "%s/index.html" % parts[1]
    return "*"
