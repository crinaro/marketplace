#!/usr/bin/env python3
"""The .docx writer this engine shares — a real Word document assembled from raw XML using
only the standard library (a .docx is a zip of XML parts).

⭐ WHY THIS IS ITS OWN MODULE (public #64, the resume-variant renderer). `letter_out.py` had
this code first, built for a one-shot letter: two header lines, a body of plain paragraphs, no
headings, no hanging indents, no widow/orphan control, no keep-with-next, no page breaks.
`variant_out.py` needs all of those — real Heading1/Heading2 styles, a hanging-indent bullet, a
paragraph that must not be orphaned from the next, an explicit authored page break — so the
paragraph model grew a real shape: `{text, bold, size_half_pt, space_after, align, style,
keep_next, widow, indent, page_break_before, color}`. `letter_out.write_docx` keeps its OLD
five-argument signature and calls straight into this module (a thin wrapper) so its output is
untouched by the move.

⭐⭐ THE PLANT THAT MATTERS HERE IS BYTE-IDENTITY, NOT CORRECTNESS. The exact same
`(header_lines, body_lines, font, margin_twips)` must produce the exact same bytes after this
extraction as before it — see test_checks.py's `TestDocxExtractionByteIdentity`, which keeps a
verbatim copy of the pre-extraction implementation and diffs its output against this module's
`write_docx` on identical input, in the same test run.

⚠️ NEVER NORMALIZE THE ZIP ENTRY TIMESTAMPS. `zipfile.ZipFile.writestr(name, data)` stamps each
entry with `time.localtime()` when given a bare string name — exactly what the pre-extraction
code did, unexamined. "Fixing" that to a constant epoch here would make this module's output
permanently UNABLE to match the pre-extraction code's own (time-stamped) bytes, which is the
opposite of what the byte-identity plant exists to prove. Two renders emitted back-to-back in
one process land in the same 2-second DOS-time bucket, which is what the plant actually relies
on — never a frozen clock.

ATS-SAFE BY CONSTRUCTION (public #64's own list, encoded rather than re-derived by hand):
no `<w:tbl>` (no tables), no `<w:txbxContent>` (no text boxes), no `<w:numPr>` (no automatic
numbering — a bullet is a literal glyph character on an ordinary paragraph). One column,
always: nothing here ever writes more than one `<w:sectPr>`.

Python 3.9+. Standard library only.
"""

import os
import zipfile

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.styles+xml"/></Types>')

PACKAGE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>')

DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/styles" Target="styles.xml"/></Relationships>')


def xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def paragraph_xml(text, bold=False, size_half_pt=22, space_after=160, align=None,
                  style=None, keep_next=False, widow=False, indent=None,
                  page_break_before=False, color=None, line=240, line_rule="auto"):
    """One paragraph of the shared model, rendered to its `<w:p>` XML.

    Every field beyond the original five (`text`, `bold`, `size_half_pt`, `space_after`,
    `align`) is OMITTED from the output when falsy/unset rather than written as an explicit
    empty value — this is what keeps the pre-extraction call shape byte-identical: a call
    naming none of `style`/`keep_next`/`widow`/`indent`/`page_break_before`/`color` reproduces
    exactly the `<w:pPr>{jc}<w:spacing .../></w:pPr>` the original code emitted, in the same
    order (`jc` before `spacing`) — see `write_docx` below.
    """
    runs = ""
    if text:
        color_xml = ('<w:color w:val="%s"/>' % color) if color else ""
        rpr = "<w:rPr>%s%s<w:sz w:val=\"%d\"/></w:rPr>" % (
            "<w:b/>" if bold else "", color_xml, size_half_pt)
        runs = ('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>'
                % (rpr, xml_escape(text)))
    pPr = []
    if style:
        pPr.append('<w:pStyle w:val="%s"/>' % style)
    if keep_next:
        pPr.append('<w:keepNext/>')
    if widow:
        pPr.append('<w:widowControl/>')
    if page_break_before:
        pPr.append('<w:pageBreakBefore/>')
    if align:
        pPr.append('<w:jc w:val="%s"/>' % align)
    pPr.append('<w:spacing w:after="%d" w:line="%d" w:lineRule="%s"/>' % (space_after, line, line_rule))
    if indent:
        left, hanging = indent
        attrs = []
        if left is not None:
            attrs.append('w:left="%d"' % left)
        if hanging is not None:
            attrs.append('w:hanging="%d"' % hanging)
        if attrs:
            pPr.append('<w:ind %s/>' % " ".join(attrs))
    return '<w:p><w:pPr>%s</w:pPr>%s</w:p>' % ("".join(pPr), runs)


def paragraph_xml_from_dict(d):
    """Same as `paragraph_xml`, reading its fields off a dict with `.get()` — the shape
    `variant_out.py` builds its composed paragraphs in. Robust to extra/missing keys, unlike
    `paragraph_xml(**d)`, which would raise on either."""
    return paragraph_xml(
        text=d.get("text", ""), bold=d.get("bold", False),
        size_half_pt=d.get("size_half_pt", 22), space_after=d.get("space_after", 160),
        align=d.get("align"), style=d.get("style"), keep_next=d.get("keep_next", False),
        widow=d.get("widow", False), indent=d.get("indent"),
        page_break_before=d.get("page_break_before", False), color=d.get("color"))


def document_xml(paragraphs_xml, margin_twips):
    sect = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
            'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
            % (margin_twips, margin_twips, margin_twips, margin_twips))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>%s%s</w:body></w:document>' % ("".join(paragraphs_xml), sect))


def heading_style_xml(style_id, name, size_half_pt, color=None, bold=True):
    """One NAMED paragraph style (`w:styleId="Heading1"` etc.) — a real style a structural/ATS
    parser can find by walking styles, not direct run formatting repeated on every heading."""
    color_xml = ('<w:color w:val="%s"/>' % color) if color else ""
    return ('<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/>'
            '<w:qFormat/><w:rPr>%s%s<w:sz w:val="%d"/></w:rPr></w:style>'
            % (style_id, name, "<w:b/>" if bold else "", color_xml, size_half_pt))


def styles_xml(font, extra_styles=None):
    """`extra_styles` is a list of already-built `<w:style>...</w:style>` fragments, appended
    after `docDefaults`. `None`/`[]` reproduces the pre-extraction, letter-only output exactly
    — no named styles beyond the default run properties."""
    extra = "".join(extra_styles or [])
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/><w:sz w:val="22"/>'
        '</w:rPr></w:rPrDefault></w:docDefaults>%s</w:styles>' % (font, font, font, extra))


def write_package(path, document, styles):
    """Zip the four parts into a real .docx at `path`. Never normalizes ZipInfo timestamps —
    see the module docstring."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", PACKAGE_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
    return path


def write_docx(path, header_lines, body_lines, font="Times New Roman", margin_twips=1080):
    """`letter_out.py`'s ORIGINAL signature and behaviour, moved here verbatim (public #64's
    extraction) so `letter_out.write_docx` can become a thin wrapper over this. See the module
    docstring's byte-identity note, and `TestDocxExtractionByteIdentity`."""
    paras = []
    for i, line in enumerate(header_lines):
        paras.append(paragraph_xml(line, bold=(i == 0), size_half_pt=24 if i == 0 else 20,
                                   space_after=40, align="center"))
    paras.append(paragraph_xml("", space_after=200))
    for line in body_lines:
        paras.append(paragraph_xml(line, space_after=160 if line.strip() else 80))
    document = document_xml(paras, margin_twips)
    styles = styles_xml(font)
    return write_package(path, document, styles)


def write_docx_paragraphs(path, paragraphs, font="Times New Roman", margin_twips=1080,
                          heading_styles=None):
    """The general form `variant_out.py` uses. `paragraphs` is a list of dicts in the shared
    model (`paragraph_xml_from_dict`'s shape); `heading_styles` is a list of
    `(style_id, name, size_half_pt, color)` tuples declared in styles.xml as real named
    styles."""
    paras_xml = [paragraph_xml_from_dict(p) for p in paragraphs]
    extra = [heading_style_xml(sid, name, size, color)
            for sid, name, size, color in (heading_styles or [])]
    document = document_xml(paras_xml, margin_twips)
    styles = styles_xml(font, extra_styles=extra)
    return write_package(path, document, styles)
