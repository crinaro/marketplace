"""docx_ats: the six ATS checks on a person's Word file (design-resume-docx.md §4.6, §R2 S2-5, O23, O28; B10).

Checked on every reconcile, printed, stored as the `document` row's `ats` list, and never repaired. The ids are
`presence.store_rules.ATS_CHECKS`, imported, never restated: `checks` walks that tuple and looks each id up in
`_RULES`, so an id with no rule fails loudly and the mirrored test pins the two sets equal.

| id              | fails when                                                                                     |
|-----------------|------------------------------------------------------------------------------------------------|
| `table`         | the body holds a `w:tbl`                                                                       |
| `textbox`       | the body holds `w:txbxContent` or a VML text box                                               |
| `columns`       | any `w:sectPr` sets more than one column (`w:cols w:num` above 1, or more than one `w:col`)     |
| `identity-top`  | the name, or both the email and the phone, is missing from the first ten non-empty body        |
|                 | paragraphs; a page-header part does not count (O28; `docx_match.identity_hits`)                |
| `heading-style` | a paragraph aligned to an md heading block has no style whose `w:name` in `word/styles.xml`,   |
|                 | followed through `w:basedOn`, casefolds to `heading 1` ... `heading 9` or `title`. The styleId |
|                 | is never compared (a localized Word writes localized ids); an id that does not resolve fails   |
| `image`         | the body holds a `w:drawing` or `w:pict` that is not a text box                                |

A Word list (`w:numPr`) on a paragraph aligned to an md bullet, where the default render writes a glyph, is a
`NOTE` line (P-ATS), printed and never stored. OURS: "the first ten body paragraphs" counts non-empty ones, as the
header zone of §4.3 does, so a spacer paragraph is not held against the person.

Capability module; nothing here reads or writes a file. Python 3.9+, standard library only."""

import re

from presence import docx_match as dm
from presence.docx_package import PackageRefusal, read_part
from presence.docx_scan import W, scan
from presence.store_rules import ATS_CHECKS

STYLES_PART = "word/styles.xml"
VML = "{urn:schemas-microsoft-com:vml}"
_HEADING_NAME = re.compile(r"^heading ([1-9])$")
REASONS = {
    "table": "a table: many applicant-tracking parsers read a table's cells out of order or not at all",
    "textbox": "a text box: its text is outside the page's paragraphs, and parsers often skip it",
    "columns": "more than one column: parsers read across the columns, mixing their lines",
    "identity-top": "the name, and an email or phone, are not in the first ten paragraphs of the page body",
    "heading-style": "a section heading without a Word heading style: parsers find sections by those styles",
    "image": "a picture: a parser reads no text from it",
}


# ---------------------------------------------------------------- styles

def style_table(styles_bytes):
    """{styleId: (w:name value, w:basedOn value)} of `word/styles.xml`'s bytes; {} for None or empty."""
    if not styles_bytes:
        return {}
    out = {}
    for n in scan(styles_bytes).nodes:
        if n.tag != W + "style":
            continue
        sid = n.attrs.get(W + "styleId")
        if not sid:
            continue
        name = n.child(W + "name")
        based = n.child(W + "basedOn")
        out[sid] = ((name.attrs.get(W + "val") or "") if name is not None else "",
                    (based.attrs.get(W + "val") or "") if based is not None else "")
    return out


def _name_level(name):
    """The heading level a style name means (`title` is 1), or None."""
    folded = " ".join((name or "").casefold().split())
    if folded == "title":
        return 1
    m = _HEADING_NAME.match(folded)
    return int(m.group(1)) if m else None


def heading_styles(table):
    """{styleId: level} of every style whose `w:name`, or an ancestor's through `w:basedOn`, is a heading (§4.6)."""
    out = {}
    for sid in table:
        seen = set()
        cur = sid
        while cur in table and cur not in seen:
            seen.add(cur)
            level = _name_level(table[cur][0])
            if level is not None:
                out[sid] = level
                break
            cur = table[cur][1]
    return out


# ---------------------------------------------------------------- the six rules

def _body_tags(sc):
    return {n.tag for n in sc.body.iter()} if sc.body is not None else set()


def _table(ctx):
    return W + "tbl" in ctx["tags"]


def _textbox(ctx):
    return W + "txbxContent" in ctx["tags"] or VML + "textbox" in ctx["tags"]


def _columns(ctx):
    for sp in ctx["scan"].sectprs:
        cols = sp.child(W + "cols")
        if cols is None:
            continue
        num = cols.attrs.get(W + "num") or ""
        if (num.isdigit() and int(num) > 1) or sum(1 for c in cols.children if c.tag == W + "col") > 1:
            return True
    return False


def _identity_top(ctx):
    texts = [p.text for p in ctx["scan"].paragraphs if p.text][:dm.ZONE_SCAN]
    return not dm.identity_ok(dm.identity_in(texts, ctx["ident"]))


def _heading_style(ctx):
    paragraphs = ctx["scan"].paragraphs
    for p, b in ctx["alignment"].matched():
        if ctx["blocks"][b]["type"] == "heading" and paragraphs[p].style not in ctx["headings"]:
            return True
    return False


def _image(ctx):
    if ctx["scan"].body is None:
        return False
    for n in ctx["scan"].body.iter():
        if n.tag in (W + "drawing", W + "pict"):
            inner = {c.tag for c in n.iter()}
            if W + "txbxContent" not in inner and VML + "textbox" not in inner:
                return True
    return False


_RULES = {"table": _table, "textbox": _textbox, "columns": _columns, "identity-top": _identity_top,
          "heading-style": _heading_style, "image": _image}


# ---------------------------------------------------------------- entry points of the module

def checks(sc, headings, alignment, blocks, ident):
    """The ids of `ATS_CHECKS` that fail, in that order. `sc` is the document part's scan, `headings` is
    `heading_styles(...)`, `alignment` is `docx_match.align(...)` of the same scan and `blocks`."""
    ctx = {"scan": sc, "tags": _body_tags(sc), "headings": headings, "alignment": alignment, "blocks": blocks,
           "ident": ident}
    return [cid for cid in ATS_CHECKS if _RULES[cid](ctx)]


def notes(sc, alignment, blocks):
    """`NOTE` lines: a Word list (`w:numPr`) where the default render writes a glyph (P-ATS); never stored."""
    out = []
    for p, b in alignment.matched():
        para = sc.paragraphs[p]
        if blocks[b]["type"] == "bullet" and para.listed:
            out.append("NOTE: paragraph %d is a Word list item where the default render writes a bullet glyph; "
                       "whether an applicant-tracking parser reads it as well is not known (P-ATS)" % (p + 1))
    return out


class Report:
    """`failed` (ids, in `ATS_CHECKS` order), `notes`, and the `alignment` and `headings` they were read from."""

    def __init__(self, failed, note_lines, alignment, headings):
        self.failed = failed
        self.notes = note_lines
        self.alignment = alignment
        self.headings = headings

    def lines(self):
        """What a run prints: one `ATS <id>: <reason>` line per failed check, then the notes."""
        return ["ATS %s: %s" % (cid, REASONS[cid]) for cid in self.failed] + list(self.notes)


def check_file(docx_bytes, blocks, ident):
    """Scan a Word file's bytes, align it with `blocks` and run every check. Returns a `Report`; raises
    `PackageRefusal` or `ScanRefusal` (R8) for a file that is not a readable Word document."""
    sc = scan(read_part(docx_bytes))
    try:
        styles = read_part(docx_bytes, STYLES_PART)
    except PackageRefusal as e:
        if "has no" not in e.detail:
            raise
        styles = None
    headings = heading_styles(style_table(styles))
    alignment = dm.align(sc.paragraphs, blocks, ident, headings)
    return Report(checks(sc, headings, alignment, blocks, ident), notes(sc, alignment, blocks), alignment, headings)

