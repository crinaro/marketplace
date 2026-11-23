"""The Markdown subset's line grammar: the patterns, the lead-ins that change meaning at schema 3, the block
names and the fragment the renderer walks."""

import re

from configschema.configkeys import V4_PART_FIXED

from contentmodel.errors import ContentError
from contentmodel.frontmatter import decode_text
from contentmodel.links import video_embed


_INLINE = re.compile(r"`([^`]+)`|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)"
                     r"|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

_ULI = re.compile(r"^[-*]\s+(.*)$")

_OLI = re.compile(r"^\d+\.\s+(.*)$")

_REFLINE = re.compile(r"^ref:\s*([A-Za-z0-9_-]+)\s*$")

_IMGLINE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)$")

_HR = re.compile(r"^(-{3,}|\*{3,})$")

# ---- the one grammar table of the schema-3 interpretations (design-site-fidelity section 3.3)
# Each row is a top-level Markdown body line that 0.2.0 renders as plain text and schema 3 reads as
# something else: (form name, pattern, how a reason names it). `siteconfig` cannot import this module,
# so `interpretation_reasons` hands its result to `siteconfig.required_schema(..., interpretations=)`.
# A row is added here BEFORE `render_markdown` gives a line new meaning at schema 3, and a corpus test
# (tests/test_contentmodel_blocks.py) asserts nothing the renderer special-cases is missing from this table.
LEAD_INS = (
    ("container", re.compile(r"^:::[A-Za-z][A-Za-z0-9_-]*(?:[ \t].*)?$"), "a ::: container line"),
    ("leaf", re.compile(r"^::[A-Za-z][A-Za-z0-9_-]*(?:[ \t].*)?$"), "a :: directive line"),
    ("close", re.compile(r"^:::[ \t]*$"), "a bare ::: line"),
    ("titled-image", re.compile(r"^!\[[^\]]*\]\([^)\s]+\s+\"[^\"]*\"\)$"), "a titled image line"),
)


def body_start_line(text):
    """The 1-based line number of the first body line of a Markdown file (after its front matter, or
    1 when it has none or the block never closes)."""
    if not text.startswith("---\n"):
        return 1
    for i, line in enumerate(text.split("\n")[1:], 2):
        if line.rstrip() == "---":
            return i + 1
    return 1


def interpretation_reasons(files):
    """[(path, lineno, form)] for every top-level Markdown body line in `files` ({path: bytes or str})
    that a `LEAD_INS` row matches: the I-1 and I-2 reasons of schema 3. Front matter is skipped; a
    line inside a `>` quote or a list item is not top level and is never matched (its first column is
    not the form's first character). A file that is not valid UTF-8 is skipped: the build refuses it
    on its own."""
    out = []
    for path in sorted(files):
        if not (path.startswith("content/") and path.lower().endswith(".md")):
            continue
        raw = files[path]
        try:
            text = decode_text(raw, path) if isinstance(raw, bytes) else raw.replace("\r\n", "\n")
        except ContentError:
            continue
        first = body_start_line(text)
        for n, line in enumerate(text.split("\n"), 1):
            if n < first:
                continue
            for _name, rx, form in LEAD_INS:
                if rx.match(line.rstrip()):
                    out.append((path, n, form))
                    break
    return out


_IMGLINE3 = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)$')

_OPEN = re.compile(r"^:::([A-Za-z][A-Za-z0-9_-]*)(?:[ \t]+(.*))?$")

_PART_NAME = re.compile(r"^[a-z][a-z0-9-]*$")

# The six container blocks (site-fidelity section 7), recognised at schema 3 only. A name is added here and as
# a `block_<name>` method of `_Renderer` together; the grammar corpus test (tests/test_contentmodel_blocks.py) walks `LEAD_INS`.
BLOCK_NAMES = ("tiles", "quote", "gallery", "videos", "carousel", "part")

# Schema 4 adds one block (design 1.3): a grid of quotes. The 0.3.x tuple is not extended, so `:::quotes` stays an
# unknown block at grammar 3 exactly as 0.3.x refuses it.
BLOCK_NAMES_V4 = ("quotes",)

# The parts of a home page that `{{home:<part>}}` names without a `:::part` container (section 6.1).
PART_FIXED = ("title", "description", "intro", "photo", "endorsement", "feed", "contact")


def block_names(grammar, named=()):
    """The container block names the grammar reads: the six of schema 3, from 4 `quotes`, and the names of the look's
    named blocks (`named`, 0.7.0, design-adopt-ownership-line section 6.6: the renderer has the look in hand and passes
    them; a look holding one needs schema 7, and a name may not be a plugin block's)."""
    return BLOCK_NAMES + (BLOCK_NAMES_V4 if grammar >= 4 else ()) + tuple(named)


def fixed_part_names(grammar):
    """The home part names fixed at `grammar`: `PART_FIXED`, and from 4 the five home keys (design 3.1 rule 7: below
    4 a custom `:::part showcase` is accepted and renders as in 0.3.x)."""
    return PART_FIXED + (V4_PART_FIXED if grammar >= 4 else ())


def _lead_kind(line):
    """The `LEAD_INS` form a line IS ("container", "leaf" or "close"), or None. The titled-image row is
    handled by `_IMGLINE3`. One table: this reads `LEAD_INS`, so the renderer cannot recognise a form the
    corpus test (and `interpretation_reasons`) does not know."""
    s = line.rstrip()
    for name, rx, _form in LEAD_INS:
        if name != "titled-image" and rx.match(s):
            return name
    return None


def _is_lead_in(line):
    """True for a line any `LEAD_INS` row matches: the lines a backslash escapes at schema 3."""
    s = line.rstrip()
    return any(rx.match(s) for _name, rx, _form in LEAD_INS)


def _starts_block(line, grammar=2):
    """True when `line` ends a paragraph. At grammar 3 and above a fence line and a titled image line end it
    too (a line escaped with a backslash is unescaped first and marked plain, so it never reaches here as a
    fence); below 3 the rule is exactly 0.2.0's."""
    if (_HEADING.match(line) or _ULI.match(line) or _OLI.match(line)
            or line.startswith(">") or _REFLINE.match(line) or _IMGLINE.match(line)
            or _HR.match(line.strip()) or video_embed(line.strip())):
        return True
    return grammar >= 3 and (_lead_kind(line) is not None or bool(_IMGLINE3.match(line)))


class Fragment(object):
    """A run of Markdown lines, each with its 1-based line number in its file (`nums`), and the set of those
    numbers whose backslash escape was removed (`plain`: they are text, whatever they now look like)."""

    def __init__(self, lines, nums, plain):
        self.lines = lines
        self.nums = nums
        self.plain = plain


def _fragment(body, first_line=1, grammar=2):
    lines = body.split("\n")
    nums = list(range(first_line, first_line + len(lines)))
    plain = set()
    if grammar >= 3:
        for k, ln in enumerate(lines):
            if ln.startswith("\\") and _is_lead_in(ln[1:]):
                lines[k] = ln[1:]
                plain.add(nums[k])
    return Fragment(lines, nums, plain)


_GALLERY_ROW_TRAIL = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)\s+(.+)$')

CARD_SEPARATOR = " · "        # `### Role · Organisation`: the text before it is the role, after it the organisation


def _drop_containers(frag):
    """The lines of a schema-3 fragment outside every container block, for the excerpt (a block's rows are
    never a page's description)."""
    out_l, depth = [], 0
    for ln, n in zip(frag.lines, frag.nums):
        kind = _lead_kind(ln) if n not in frag.plain else None
        if kind == "container":
            depth += 1
            continue
        if kind == "close":
            depth = max(0, depth - 1)
            continue
        if kind == "leaf" or depth:
            continue
        out_l.append(ln)
    return "\n".join(out_l)


def plain_excerpt(body, limit=160, grammar=2):
    """The first prose paragraph as plain text, cut on a word boundary: a deterministic
    description when a page gives none. At grammar 3 the text of a container block is never the excerpt, and
    a fence line ends a paragraph."""
    if grammar >= 3:
        body = _drop_containers(_fragment(body, 1, 3))
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if not block or _starts_block(block.split("\n")[0], grammar):
            continue
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", block)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"[*`]", "", text)
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.-")
        return cut + "..."
    return ""
