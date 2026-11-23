"""variant_patch: the Word file's words written into a variant's md, every other byte of the md kept (design-resume-
docx.md §5.1, §5.3, §R2 M2-4, §R3 R3-1; B11). The `--keep word` path, and nothing else.

`patch(md_bytes, ops, page_break_marker, preamble_marker)` is a pure function from md bytes to md bytes: it reads
and writes no file (the verb writes its result through `_put_bytes`, §3.3). `ops_from_alignment(...)` derives the ops
from a scan of the Word file aligned with the md (`docx_match.align`):

    ("replace", block, text)              a pair whose texts differ: the block's own lines are replaced by one line
                                          holding the Word text, keeping the block's marker (`##`, `-`, `*`, `+`)
                                          and indent; its continuation lines go with it
    ("insert", after, text, like, kind)   a Word paragraph with no block: a new md line directly after the last line
                                          of block `after`, or, when `after` is None, before the first block and
                                          after any preamble marker. Its marker and indent are block `like`'s (a
                                          matched paragraph with the same `w:pPr` bytes, else of the same kind),
                                          else the default for `kind` ("heading" level n: `#`*n; "bullet": `- `)
    ("delete", block)                     a block whose paragraph the person deleted: its own lines are removed

The header zone and contact-only paragraphs are never in an alignment's spans, so they are never taken back.

**Lines that would merge.** The md grammar (`variant_blocks.parse_variant_blocks`) joins a plain line to the bullet or
paragraph line directly above it. So a new paragraph line after a bullet or paragraph gets a blank line before it; a
new bullet or paragraph line followed directly by a plain line gets a blank line after it; and a deleted block whose
neighbours would merge leaves one blank line. OURS, because the alternative is a take-back that changes words the
person did not change.

**Post-condition** (`PatchRefusal`, rule `patch`): the result is parsed again and must hold exactly the expected
blocks (type and text), or nothing is returned. It catches a Word text the md grammar would read differently (one
holding `**x**`, or starting with `# ` or `- `).

Capability module; nothing here reads or writes a file. Python 3.9+, standard library only."""

import re

from presence import docx_match as dm
from presence.variant_blocks import BULLET_INDENT_RE, HEADING_RE, parse_variant_blocks

_HEAD_PREFIX = re.compile(r"^(\s*#{1,6}\s+)")
_BULLET_PREFIX = re.compile(r"^(\s*[-*+]\s+)")
_LEAD_WS = re.compile(r"^(\s*)")


class PatchRefusal(Exception):
    """A patch refused with nothing returned; `rule` is `patch`, `detail` says why."""

    def __init__(self, detail, rule="patch"):
        Exception.__init__(self, "%s: %s" % (rule, detail))
        self.rule = rule
        self.detail = detail


# ---------------------------------------------------------------- where each block lives

def block_lines(text, page_break_marker, preamble_marker=None):
    """(lines with their endings, [[line index, ...] per block], first body line index): the md's own lines of each
    block `parse_variant_blocks` yields, by the same grammar. Refused when the two readings disagree."""
    lines = text.splitlines(True)
    first = 0
    if preamble_marker:
        for i, line in enumerate(lines):
            if line.strip() == preamble_marker:
                first = i + 1
                break
    owned = []
    run_type = None
    for i in range(first, len(lines)):
        bare = _bare(lines[i])
        if page_break_marker and bare.strip() == page_break_marker:
            continue
        if not bare.strip():
            run_type = None
            continue
        if HEADING_RE.match(bare):
            owned.append([i])
            run_type = None
        elif BULLET_INDENT_RE.match(bare):
            owned.append([i])
            run_type = "bullet"
        elif run_type in ("bullet", "paragraph") and owned:
            owned[-1].append(i)
        else:
            owned.append([i])
            run_type = "paragraph"
    if len(owned) != len(parse_variant_blocks(text, page_break_marker, preamble_marker)):
        raise PatchRefusal("the md's blocks could not be placed on its lines")
    return lines, owned, first


def _ending(line):
    body = line.splitlines()[0] if line.splitlines() else ""
    return line[len(body):]


def _bare(line):
    return line.splitlines()[0] if line.splitlines() else ""


def _newline(lines):
    for line in lines:
        e = _ending(line)
        if e:
            return e
    return "\n"


def _prefix(line, kind):
    """The marker and indent of an md line of `kind`: `## `, `  - `, or the leading whitespace of a paragraph."""
    pat = {"heading": _HEAD_PREFIX, "bullet": _BULLET_PREFIX}.get(kind, _LEAD_WS)
    m = pat.match(_bare(line))
    return m.group(1) if m else ""


def _default_prefix(kind):
    if kind[0] == "heading":
        return "#" * max(1, min(6, kind[1] or 1)) + " "
    if kind[0] == "bullet":
        return "  " * (kind[1] or 0) + "- "
    return ""


def _plain(line, page_break_marker):
    """True for a line the grammar would join to a bullet or paragraph line directly above it."""
    bare = _bare(line)
    if not bare.strip() or (page_break_marker and bare.strip() == page_break_marker):
        return False
    return not HEADING_RE.match(bare) and not BULLET_INDENT_RE.match(bare)


def _next_significant(lines, i, page_break_marker):
    """The first line at or after `i` that is neither removed ("") nor a page-break marker, or None."""
    while i < len(lines):
        if lines[i] and not (page_break_marker and _bare(lines[i]).strip() == page_break_marker):
            return lines[i]
        i += 1
    return None


# ---------------------------------------------------------------- the patch

def patch(md_bytes, ops, page_break_marker, preamble_marker=None):
    """The md `md_bytes` with `ops` applied (see the module docstring). Returns bytes; raises `PatchRefusal`."""
    try:
        text = md_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchRefusal("the md is not UTF-8")
    blocks = parse_variant_blocks(text, page_break_marker, preamble_marker)
    lines, owned, first = block_lines(text, page_break_marker, preamble_marker)
    nl = _newline(lines)
    out = list(lines)                       # out[i] stands for line i; "" removes it
    expected = [(b["type"], b["text"]) for b in blocks]
    head, placed, deleted = [], {}, set()
    for op in ops:
        if op[0] == "replace":
            _o, j, new_text = op
            new_text = " ".join(new_text.split())
            own = owned[j]
            out[own[0]] = _prefix(lines[own[0]], blocks[j]["type"]) + new_text + _ending(lines[own[-1]])
            for i in own[1:]:
                out[i] = ""
            expected[j] = (blocks[j]["type"], new_text)
        elif op[0] == "delete":
            deleted.add(op[1])
        elif op[0] == "insert":
            _o, at, new_text, like, kind = op
            new_text = " ".join(new_text.split())
            prefix = (_prefix(lines[owned[like][0]], blocks[like]["type"]) if like is not None
                      else _default_prefix(kind))
            (head if at is None else placed.setdefault(at, [])).append((kind[0], prefix + new_text, new_text))
        else:
            raise PatchRefusal("unknown op %r" % (op[0],))
    for j in deleted:
        for i in owned[j]:
            out[i] = ""
        expected[j] = None
    for j in sorted(deleted):
        _keep_apart(out, owned[j], first, page_break_marker, nl)
    anchor = owned[0][0] if owned else len(lines)
    result = []
    for i in range(len(lines)):
        if i == anchor and head:
            _terminate(result, nl)
            result.extend(_lines_block(head, None, out[i], page_break_marker, nl))
        result.append(out[i])
        for j in [j for j in placed if owned[j][-1] == i]:
            _terminate(result, nl)
            prev = next((x for x in reversed(result) if x), None)
            result.extend(_lines_block(placed[j], prev, _next_significant(out, i + 1, page_break_marker),
                                       page_break_marker, nl))
    if anchor >= len(lines) and head:
        _terminate(result, nl)
        result.extend(_lines_block(head, None, None, page_break_marker, nl))
    new_text = "".join(result)
    want = [(t, x) for t, _l, x in head]
    for j in range(len(blocks)):
        if expected[j] is not None:
            want.append(expected[j])
        want.extend((t, x) for t, _l, x in placed.get(j, []))
    got = [(b["type"], b["text"]) for b in parse_variant_blocks(new_text, page_break_marker, preamble_marker)]
    if got != want:
        bad = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        raise PatchRefusal("the patched md would read differently at block %d (%r, expected %r)"
                           % (bad + 1, got[bad] if bad < len(got) else None, want[bad] if bad < len(want) else None))
    return new_text.encode("utf-8")


def _terminate(result, nl):
    """Give the last written line a line ending before a new line follows it."""
    for k in range(len(result) - 1, -1, -1):
        if result[k]:
            if not _ending(result[k]):
                result[k] = result[k] + nl
            return


def _keep_apart(out, own, first, page_break_marker, nl):
    """A deleted block whose neighbours the grammar would join leaves one blank line."""
    above = own[0] - 1
    while above >= first and out[above] == "":
        above -= 1
    if above < first:
        return
    prev = _bare(out[above])
    nxt = _next_significant(out, own[-1] + 1, page_break_marker)
    if prev.strip() and not HEADING_RE.match(prev) and nxt is not None and _plain(nxt, page_break_marker):
        out[own[-1]] = nl


def _lines_block(items, prev, nxt, page_break_marker, nl):
    """The new lines for `items` [(type, line, text)] placed between line `prev` and line `nxt` (either None), with
    the blank lines that keep each one its own block."""
    out = []
    above = prev
    for typ, line, _text in items:
        if typ == "paragraph" and above is not None and _bare(above).strip() and \
                not HEADING_RE.match(_bare(above)):
            out.append(nl)
        out.append(line + nl)
        above = line
    if nxt is not None and _plain(nxt, page_break_marker) and items[-1][0] in ("bullet", "paragraph"):
        out.append(nl)
    return out


# ---------------------------------------------------------------- from an alignment

def ops_from_alignment(sc, alignment, blocks, heading_styles=None):
    """The ops that take the Word file's words back into the md (§5.1), from a scan `sc` of the Word file and its
    `docx_match.align(...)` with the md's `blocks`."""
    paras = sc.paragraphs
    matched = alignment.matched()
    ops = []
    for s in alignment.spans:
        if s.tag != "replace":
            continue
        for w, m, _r in s.pairs:
            text = dm.word_text(paras[w])
            if text != blocks[m]["text"]:
                ops.append(("replace", m, text))
    for s in alignment.spans:
        for m in s.inserted:
            ops.append(("delete", m))
        for w in s.deleted:
            above = [b for p, b in matched if p < w]
            ops.append(("insert", above[-1] if above else None, dm.word_text(paras[w]),
                        _like(sc, w, matched, blocks, heading_styles), dm.word_kind(paras[w], heading_styles)))
    return ops


def _like(sc, w, matched, blocks, heading_styles):
    """A matched block to copy the marker of: one whose paragraph has the same `w:pPr` bytes and kind, else the
    nearest one of the same kind (same level or depth), else None."""
    paras = sc.paragraphs
    kind = dm.word_kind(paras[w], heading_styles)
    ppr = sc.raw(paras[w].ppr) if paras[w].ppr is not None else b""
    near = sorted(matched, key=lambda pb: abs(pb[0] - w))
    for p, b in near:
        other = sc.raw(paras[p].ppr) if paras[p].ppr is not None else b""
        if other == ppr and dm.word_kind(paras[p], heading_styles)[0] == kind[0] == dm.md_kind(blocks[b])[0]:
            return b
    for p, b in near:
        if dm.word_kind(paras[p], heading_styles) == kind and dm.md_kind(blocks[b])[0] == kind[0]:
            return b
    return None
