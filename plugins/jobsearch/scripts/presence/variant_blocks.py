"""variant_blocks: a resume variant's markdown read into blocks (jobsearch 0.93.0, B8 of
docs/design-resume-docx.md).

`parse_variant_blocks` turns a variant file into headings, bullets and paragraphs, in file order,
after its preamble marker and with page-break markers recorded on the next block. Moved out of
`variant_out.py` (an entry point, which keeps every name importable as a facade) so the Word
round trip can read the md side the same way the renderer does. `BULLET_INDENT_RE` moved here
from `resume_variants.py` for the same reason; `HEADING_RE` comes from `presence.union_text`.

Python 3.9+. Standard library only.
"""

import re

from presence.union_text import HEADING_RE

# Same bullet grammar as BULLET_RE, with the leading indentation captured separately —
# union_claim_tags() needs it to pair a nested `[private]` twin with its `[public]` parent; the
# plain containment path (bullets_with_sections) never needed nesting, only section membership.
BULLET_INDENT_RE = re.compile(r"^(\s*)[-*+]\s+(.+?)\s*$")


def _norm(s):
    return " ".join((s or "").split())


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _strip_markdown_emphasis(s):
    """dev #480 / public #113 — a docx run has no inline markdown; `**text**` must not reach
    the page as four literal asterisk characters. Strips the marker and keeps the wrapped text
    (this renderer's paragraph model is one run per paragraph — see `_docx.py` — so a REAL bold
    SPAN inside an otherwise-plain paragraph is not representable without a bigger change to
    that shared model; stripping is the honest, immediately-correct fix: never print markdown
    syntax as if it were prose)."""
    return _BOLD_RE.sub(r"\1", s or "")


def _strip_preamble(text, preamble_marker):
    """dev #480 / public #113 — a variant file's own drafting notes/internal header sit above
    `preamble_marker`'s exact line (mirrors `page_break_marker`'s exact-line-match convention).
    Returns the text strictly AFTER the marker's first occurrence, or `text` unchanged when the
    marker is absent or falsy — so a file with no such line renders exactly as before."""
    if not preamble_marker:
        return text or ""
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == preamble_marker:
            return "\n".join(lines[i + 1:])
    return text or ""


def parse_variant_blocks(text, page_break_marker, preamble_marker=None):
    """[{'type': 'heading', 'level': int, 'text': str, 'page_break': bool} |
        {'type': 'bullet', 'indent': int, 'text': str, 'page_break': bool} |
        {'type': 'paragraph', 'text': str, 'page_break': bool}], in file order.

    dev #480 / public #113 — headings and bullets were the ONLY blocks composed here; every
    non-bullet paragraph under a heading (a role's summary line, an employer's title/date line)
    was silently dropped, and a bullet's wrapped continuation line (indented, no `-`/`*`/`+`
    marker of its own — the standard multi-line bullet form) matched neither regex and vanished
    the same way. ADR-018's "summary paragraphs... are per-variant positioning and are not
    gated" is a decision about the CONTAINMENT CHECK (`resume_variants.py --check` does not
    require paragraph text to already live in the union) — it was never a decision that the
    RENDERER should omit them from the printed page. A variant's own prose is exactly the text
    a reader is meant to see; this composes it as an ordinary body paragraph.

    A continuation line is any non-blank line that is neither a heading nor a bullet, appearing
    directly after a bullet or paragraph line with no blank line between — it is appended
    (normalized, single-spaced) onto that block's own text, never treated as new content of its
    own. A blank line ends the current bullet/paragraph run, same as markdown's own paragraph
    break; text encountered after a blank line (or as the first content of a section) starts a
    new paragraph block."""
    text = _strip_preamble(text, preamble_marker)
    blocks = []
    pending_break = False
    run_type = None   # None | "bullet" | "paragraph" -- which block a continuation extends
    for line in (text or "").splitlines():
        if page_break_marker and line.strip() == page_break_marker:
            pending_break = True
            continue
        if not line.strip():
            run_type = None
            continue
        hm = HEADING_RE.match(line)
        if hm:
            blocks.append({"type": "heading", "level": len(hm.group(1)),
                           "text": _strip_markdown_emphasis(hm.group(2).strip()),
                           "page_break": pending_break})
            pending_break = False
            run_type = None
            continue
        bm = BULLET_INDENT_RE.match(line)
        if bm:
            blocks.append({"type": "bullet", "indent": len(bm.group(1)),
                           "text": _strip_markdown_emphasis(_norm(bm.group(2))),
                           "page_break": pending_break})
            pending_break = False
            run_type = "bullet"
            continue
        piece = _strip_markdown_emphasis(_norm(line))
        if run_type in ("bullet", "paragraph") and blocks:
            blocks[-1]["text"] = _norm(blocks[-1]["text"] + " " + piece)
        else:
            blocks.append({"type": "paragraph", "text": piece, "page_break": pending_break})
            pending_break = False
            run_type = "paragraph"
    return blocks
