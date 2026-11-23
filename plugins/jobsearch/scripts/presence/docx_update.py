"""docx_update: the md's words written into a person's Word file in place, inside the runs that hold them, with every
other byte kept (design-resume-docx.md §4.3, §4.4, §4.5, §R1 M-7, §R3 R3-2; B11).

`update(docx_bytes, blocks, ident, heading_styles)` returns an `Update`: the new package bytes and what changed. It
reads nothing and writes nothing: the verb (B13) takes the backup, re-hashes and replaces the file.

**What an update does**, span by span of `docx_match.align`:

    equal      nothing
    replace    each pair (`Span.pairs`, best-first by similarity, never by order) whose texts differ is edited in
               place (below); an unpaired paragraph is deleted; an unpaired block is inserted
    insert     a new paragraph: a byte copy of a donor's start tag, `w:pPr` and first run's `w:rPr`, holding the text
    delete     the paragraph's bytes are removed

**Editing one paragraph** (§4.4). The common prefix and suffix of the old and new text are found by character, on the
text as §4.2 reads it, and mapped back to the characters of the paragraph's `w:t` elements. Runs wholly inside the
prefix or suffix keep their bytes. The changed middle goes into the first `w:t` it touches, so it takes that run's
properties; a run wholly inside the changed region is removed; a run partly inside is trimmed. A leading bullet glyph
is part of the old text, so it stays in the prefix with its run: a bold lead-in survives an edit to the rest of the
bullet. Every `w:t` the edit writes is rewritten whole, its text XML-escaped and carrying `xml:space="preserve"`
(M-7), so a space left at either end by a split at a word boundary is kept. Nothing else in the paragraph changes:
`w:pPr` (spacing, indents, keep rules), each kept run's `w:rPr` (`w:sz`, `w:szCs`, fonts, colour) and every other
part of the package are byte-identical (§R3 R3-2), as are `w:sectPr` (`w:pgMar`) and `word/styles.xml`.

**The donor** of an inserted block is the nearest earlier matched paragraph of the same block type, else the nearest
later one; a bullet takes the same depth first, then any bullet. OURS, because the Word side cannot be trusted to
carry the md's level: the type of a matched paragraph is read from the md block it is matched to, so a `###` block
the default render wrote with `Heading2` finds the paragraph that renders `###` in this file. The copy drops
`w14:paraId` and `w14:textId`; bookmarks and comment ranges are never copied (only the start tag, `w:pPr` and one
`w:rPr` are). If the donor's text starts with a bullet glyph, the new text starts with the same glyph and separator.
An inserted paragraph goes directly after the matched paragraph of the block above it, else directly before the
matched paragraph of the block below it.

**Refused, nothing returned** (`UpdateRefusal`, §4.5): R1 tracked changes; R2 text outside body-level paragraphs;
R3 a changed region covering anything but plain text runs (a hyperlink, a field, a tab, a break, a drawing, a
comment range); R4 a text that occurs twice on its side when it sits outside the equal spans; R5 a new block with no
donor of its type; R6 a paragraph to delete or copy that holds a section break; R7 the identity not found at the top
or in a page-header part; R8 (from `docx_scan` and `docx_package`); R9 the post-condition: the rebuilt part, scanned
again, must hold the md's text block for block below an unchanged header zone. R9 is a self-consistency check: the
same code reads both sides, so it is not evidence of what Word shows (P-WORD-OPENS).

Capability module; nothing here reads or writes a file. Python 3.9+, standard library only."""

import io
import re
import zipfile

from presence import docx_ats as da
from presence import docx_match as dm
from presence import docx_package as dp
from presence import docx_scan as ds
from presence.resume_import import GLYPH_RE

W = ds.W
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"
VML = "{urn:schemas-microsoft-com:vml}"

ROUTES = {
    "R1": "accept or reject the tracked changes in Word",
    "R2": "move the text into plain paragraphs, or --fresh",
    "R3": "apply the change by hand in Word: the old and new text are printed above",
    "R4": "make the two lines differ, in either file",
    "R5": "add one paragraph of that kind in Word, or --fresh",
    "R6": "restructure in Word",
    "R7": "fix the header in Word, or the identity in user.json",
    "R8": "open and save the file in Word as a .docx, or --fresh",
    "R9": "a defect in the updater; --fresh",
}

# Tracked-change elements (R1): any one in the body means the person's file is mid-review.
TRACKED = tuple(W + t for t in ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange",
                                "tblPrChange", "tcPrChange", "trPrChange", "numberingChange", "cellIns", "cellDel",
                                "cellMerge", "moveFromRangeStart", "moveToRangeStart"))
# Containers of text that is not a body-level paragraph's (R2).
OUTSIDE = (W + "tbl", W + "sdt", W + "customXml", W + "txbxContent", W + "altChunk", VML + "textbox")
# Inside a paragraph: elements that hold no text and are never touched by an edit.
_IGNORED = (W + "pPr", W + "bookmarkStart", W + "bookmarkEnd", W + "proofErr", W + "permStart", W + "permEnd")
# Inside a plain run: elements that are neither text nor a reason to refuse.
_RUN_IGNORED = (W + "rPr", W + "lastRenderedPageBreak")
_TABS = (W + "tab", W + "ptab")
_BREAKS = (W + "br", W + "cr")
_PARA_ID = re.compile(rb'\s+w14:(?:paraId|textId)="[^"]*"')


class UpdateRefusal(Exception):
    """An update refused with nothing returned; `rule` is §4.5's id, `detail` says why, `route` what to do."""

    def __init__(self, rule, detail):
        Exception.__init__(self, "%s: %s" % (rule, detail))
        self.rule = rule
        self.detail = detail
        self.route = ROUTES.get(rule, "")


def refusal_line(variant, refusal):
    """§4.5's printed line: `REFUSED <variant>: <rule>: <detail>; nothing written`, then the route."""
    line = "REFUSED %s: %s: %s; nothing written" % (variant, refusal.rule, refusal.detail)
    route = getattr(refusal, "route", "") or ROUTES.get(refusal.rule, "")
    return line + ("\n  " + route if route else "")


class Update:
    """The result of `update`: `docx` (the new package's bytes; the input's own bytes when nothing changed), `part`
    (the new `word/document.xml`), and the paragraph counts `edited`, `inserted`, `deleted`, plus `header` (the
    header zone's lines, printed on each run)."""

    def __init__(self, docx, part, edited, inserted, deleted, header):
        self.docx = docx
        self.part = part
        self.edited = edited
        self.inserted = inserted
        self.deleted = deleted
        self.header = header

    @property
    def changed(self):
        return bool(self.edited or self.inserted or self.deleted)


# ---------------------------------------------------------------- reconcile refusals (R1, R2, R7)

def page_header_texts(docx_bytes):
    """The paragraph texts of every page-header part (`word/header*.xml`), in name order; [] when there is none."""
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            names = sorted(n for n in zf.namelist() if re.match(r"^word/header\d*\.xml$", n))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise UpdateRefusal("R8", "not a readable zip")
    out = []
    for name in names:
        sc = _scan(dp.read_part(docx_bytes, name))
        out.extend(ds.paragraph_text(n) for n in sc.nodes if n.tag == W + "p")
    return [t for t in out if t]


def check_reconcile(sc, ident, header_texts=()):
    """R1, R2 and R7 on a scanned document part, checked on every reconcile (§4.5): raises `UpdateRefusal`."""
    body = sc.body
    if body is None:
        raise UpdateRefusal("R8", "the document part has no w:body")
    for n in body.iter():
        if n.tag in TRACKED:
            raise UpdateRefusal("R1", "the file holds tracked changes (%s at byte %d)" % (_local(n.tag), n.start))
    for n in body.iter():
        if n.tag in OUTSIDE:
            raise UpdateRefusal("R2", "text sits outside body-level paragraphs (%s at byte %d)"
                                % (_local(n.tag), n.start))
    for c in sc.body_other:
        if any(x.tag == W + "t" for x in c.iter()):
            raise UpdateRefusal("R2", "text sits outside body-level paragraphs (in %s at byte %d)"
                                % (_local(c.tag), c.start))
    top = [p.text for p in sc.paragraphs if p.text][:dm.ZONE_SCAN]
    if not dm.identity_ok(dm.identity_in(list(top) + list(header_texts), ident)):
        raise UpdateRefusal("R7", "the name and an email or a phone are not in the first %d paragraphs or a "
                                  "page header" % dm.ZONE_SCAN)


# ---------------------------------------------------------------- one paragraph's characters

class _Chars:
    """The characters of one paragraph as §4.2 reads them, each mapped to where it lives. `chars[i]` is
    (char, w:t node or None, offset in that node's text, run node or None); a `None` node marks a character the edit
    may not touch (a tab, a break, text inside a hyperlink or field). `marks` are positions (between characters) of
    elements the edit may not cross: a drawing, a field character, a comment range."""

    def __init__(self, para):
        self.chars = []
        self.marks = []
        self.field = 0                      # inside a complex field (fldChar begin .. end), text is the field's
        for c in para.node.children:
            if c.tag == W + "r":
                self._run(c)
            elif c.tag in _IGNORED:
                continue
            else:
                self._foreign(c)

    def _run(self, run):
        for c in run.children:
            if c.tag == W + "t":
                for k, ch in enumerate(c.text):
                    self.chars.append((ch, None, 0, None) if self.field else (ch, c, k, run))
            elif c.tag in _TABS:
                self.chars.append(("\t", None, 0, None))
            elif c.tag in _BREAKS:
                self.chars.append((" ", None, 0, None))
            elif c.tag in _RUN_IGNORED:
                continue
            else:
                if c.tag == W + "fldChar":
                    kind = c.attrs.get(W + "fldCharType")
                    self.field += 1 if kind == "begin" else -1 if kind == "end" and self.field else 0
                self._foreign(c)

    def _foreign(self, node):
        self.marks.append(len(self.chars))
        for el in node.iter():
            if el.tag == W + "t":
                self.chars.extend((ch, None, 0, None) for ch in el.text)
            elif el.tag in _TABS:
                self.chars.append(("\t", None, 0, None))
            elif el.tag in _BREAKS:
                self.chars.append((" ", None, 0, None))
        self.marks.append(len(self.chars))

    def raw(self):
        return "".join(c[0] for c in self.chars)


def _collapse_map(raw):
    """(collapsed text, pos) where `pos[k]` is the raw index of collapsed character k's source (a collapsed space's
    source is the first whitespace of its run) and `pos[len]` is just past the last source."""
    out, pos = [], []
    i, n = 0, len(raw)
    while i < n and raw[i].isspace():
        i += 1
    last = i
    while i < n:
        if raw[i].isspace():
            j = i
            while j < n and raw[j].isspace():
                j += 1
            if j < n:
                out.append(" ")
                pos.append(i)
            i = j
            continue
        out.append(raw[i])
        pos.append(i)
        last = i + 1
        i += 1
    pos.append(last)
    return "".join(out), pos


def _common(a, b):
    p = 0
    m = min(len(a), len(b))
    while p < m and a[p] == b[p]:
        p += 1
    s = 0
    while s < m - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
        s += 1
    return p, s


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _qname(data, node):
    """The element's name as written (`w:t`), read from its start tag."""
    m = re.match(rb"<([^\s/>]+)", data[node.start:node.open_end])
    return m.group(1).decode("utf-8")


def _t_bytes(name, text):
    return ('<%s xml:space="preserve">%s</%s>' % (name, _escape(text), name)).encode("utf-8")


def edit_paragraph(data, para, new_text):
    """The bytes of `para` (a scanned `Paragraph` of `data`) holding `new_text`, edited inside its runs (§4.4).
    Raises `UpdateRefusal` R3 when the changed region covers anything but plain text runs."""
    chars = _Chars(para)
    raw = chars.raw()
    old, pos = _collapse_map(raw)
    new = " ".join(new_text.split())
    if old == new:
        return data[para.start:para.end]
    p, s = _common(old, new)
    rs, re_ = pos[p], pos[len(old) - s]
    mid = new[p:len(new) - s]
    detail = "the change covers more than plain text; old %r, new %r" % (old, new)
    if any(chars.chars[i][1] is None for i in range(rs, re_)) or any(rs < m < re_ for m in chars.marks):
        raise UpdateRefusal("R3", detail)
    t_target, at = None, 0
    if mid:
        if rs < re_:
            t_target, at = chars.chars[rs][1], chars.chars[rs][2]
        elif rs > 0 and chars.chars[rs - 1][1] is not None:
            t_target, at = chars.chars[rs - 1][1], chars.chars[rs - 1][2] + 1
        elif rs < len(chars.chars) and chars.chars[rs][1] is not None:
            t_target, at = chars.chars[rs][1], chars.chars[rs][2]
        else:
            raise UpdateRefusal("R3", detail)
    cut = {}
    for i in range(rs, re_):
        cut.setdefault(chars.chars[i][1], set()).add(chars.chars[i][2])
    edits, removed = [], []
    for t in sorted(set(cut) | ({t_target} if t_target is not None else set()), key=lambda n: n.start):
        gone = cut.get(t, set())
        keep = [(k, ch) for k, ch in enumerate(t.text) if k not in gone]
        if t is t_target:
            new_t = "".join(ch for k, ch in keep if k < at) + mid + "".join(ch for k, ch in keep if k >= at)
        else:
            new_t = "".join(ch for _k, ch in keep)
            run = _run_of(chars, t)
            if new_t == "" and _run_is_only(run, chars, rs, re_):
                if run not in removed:
                    removed.append(run)
                continue
        edits.append((t.start, t.end, _t_bytes(_qname(data, t), new_t)))
    edits = [e for e in edits if not any(r.start <= e[0] and e[1] <= r.end for r in removed)]
    edits.extend((r.start, r.end, b"") for r in removed)
    local = [(a - para.start, b - para.start, x) for a, b, x in edits]
    return dp.splice(data[para.start:para.end], local)


def _run_of(chars, t):
    for _ch, node, _k, run in chars.chars:
        if node is t:
            return run
    return t.parent


def _run_is_only(run, chars, rs, re_):
    """True when every character of `run` lies in the changed region [rs, re_) and the run holds only text."""
    if run is None:
        return False
    idx = [i for i, c in enumerate(chars.chars) if c[3] is run]
    if not idx or idx[0] < rs or idx[-1] >= re_:
        return False
    return all(c.tag in (W + "t", W + "rPr") for c in run.children)


# ---------------------------------------------------------------- the whole part

def _styles(docx_bytes):
    """`word/styles.xml`'s bytes, or None when the package has none."""
    try:
        return dp.read_part(docx_bytes, da.STYLES_PART)
    except dp.PackageRefusal as e:
        if "has no" in e.detail:
            return None
        raise


def _scan(part):
    try:
        return ds.scan(part)
    except ds.ScanRefusal as e:
        raise UpdateRefusal(e.rule, e.detail)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _holds_sectpr(para):
    return para.ppr is not None and para.ppr.child(W + "sectPr") is not None


def _check_duplicates(sc, blocks, al):
    """R4: a text in a span that is not equal which occurs more than once on its own side."""
    word_texts = [dm.word_text(sc.paragraphs[i]) for s in al.spans for i in s.word]
    md_texts = [blocks[j]["text"] for s in al.spans for j in s.md]
    for s in al.spans:
        if s.tag == "equal":
            continue
        for i in s.word:
            t = dm.word_text(sc.paragraphs[i])
            if word_texts.count(t) > 1:
                raise UpdateRefusal("R4", "the Word file holds %r more than once" % t)
        for j in s.md:
            t = blocks[j]["text"]
            if md_texts.count(t) > 1:
                raise UpdateRefusal("R4", "the md holds %r more than once" % t)


def _same_type(want, have, exact):
    if want[0] != have[0]:
        return False
    if want[0] == "paragraph":
        return True
    return want[1] == have[1] if exact else want[0] == "bullet"


def find_donor(block_index, blocks, matched):
    """The paragraph index of the donor of block `block_index` (see the module docstring), or None. `matched` is
    [(paragraph index, block index)] in order."""
    want = dm.md_kind(blocks[block_index])
    earlier = [(p, b) for p, b in matched if b < block_index][::-1]
    later = [(p, b) for p, b in matched if b > block_index]
    for exact in (True, False):
        for pool in (earlier, later):
            for p, b in pool:
                if _same_type(want, dm.md_kind(blocks[b]), exact):
                    return p
        if want[0] != "bullet":
            break
    return None


def donor_paragraph(data, donor, text):
    """A new paragraph's bytes: the donor's start tag (without `w14:paraId`/`w14:textId`), its `w:pPr`, and one run
    with the donor's first `w:rPr` holding `text`, glyph-led as the donor is."""
    if _holds_sectpr(donor):
        raise UpdateRefusal("R6", "the donor paragraph %d holds a section break" % (donor.index + 1))
    node = donor.node
    name = _qname(data, node)
    prefix = name.split(":", 1)[0] + ":" if ":" in name else ""
    if node.self_closing:
        start = _PARA_ID.sub(b"", data[node.start:node.end - 2]) + b">"
    else:
        start = _PARA_ID.sub(b"", data[node.start:node.open_end])
    ppr = data[donor.ppr.start:donor.ppr.end] if donor.ppr is not None else b""
    rpr = b""
    for r in donor.runs:
        rp = r.child(W + "rPr")
        if rp is not None:
            rpr = data[rp.start:rp.end]
        if r.child(W + "t") is not None:
            break
    glyph = GLYPH_RE.match(donor.text)
    full = (glyph.group(0) if glyph else "") + text
    run = b"<" + (prefix + "r").encode() + b">" + rpr + _t_bytes(prefix + "t", full) + b"</" + \
        (prefix + "r").encode() + b">"
    return start + ppr + run + b"</" + name.encode("utf-8") + b">"


def _plan(sc, blocks, al):
    """The paragraph-level plan: {paragraph index: new text} for edits, [paragraph index] to delete, and
    [(block index, donor paragraph index, anchor paragraph index, "after"|"before")] to insert."""
    edits, deletes, inserts = {}, [], []
    matched = al.matched()
    for s in al.spans:
        if s.tag == "replace":
            for w, m, _r in s.pairs:
                para = sc.paragraphs[w]
                glyph = GLYPH_RE.match(para.text)
                new = (glyph.group(0) if glyph else "") + blocks[m]["text"]
                if dm.word_text(para) != blocks[m]["text"]:
                    edits[w] = new
        deletes.extend(s.deleted)
        for j in s.inserted:
            donor = find_donor(j, blocks, matched)
            if donor is None:
                k = dm.md_kind(blocks[j])
                raise UpdateRefusal("R5", "the new %s %r has no paragraph of its kind to copy"
                                    % ({"heading": "heading level %s" % k[1], "bullet": "bullet"}.get(k[0], k[0]),
                                       blocks[j]["text"]))
            above = [p for p, b in matched if b < j]
            below = [p for p, b in matched if b > j]
            if above:
                inserts.append((j, donor, above[-1], "after"))
            else:
                inserts.append((j, donor, below[0], "before"))
    for w in deletes:
        if _holds_sectpr(sc.paragraphs[w]):
            raise UpdateRefusal("R6", "paragraph %d, to be deleted, holds a section break" % (w + 1))
    return edits, deletes, inserts


def _post_condition(part, sc, n_zone, blocks, al, ident):
    """R9: the rebuilt part, scanned again, holds the md's text block for block below an unchanged header zone."""
    new = _scan(part)
    if [sc.raw(p) for p in sc.paragraphs[:n_zone]] != [new.raw(p) for p in new.paragraphs[:n_zone]]:
        raise UpdateRefusal("R9", "the header zone changed")
    got = [dm.word_text(p) for p in new.paragraphs[n_zone:] if p.text and not dm.contact_only(p.text, ident)]
    want = [b["text"] for j, b in enumerate(blocks) if j not in al.md_contact]
    if got != want:
        first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        raise UpdateRefusal("R9", "after the edit the body does not equal the md at block %d (%r against %r)"
                            % (first + 1, got[first] if first < len(got) else None,
                               want[first] if first < len(want) else None))


def update_part(part, blocks, ident, heading_styles=None, header_texts=()):
    """The edit on a `word/document.xml` part: returns (new part bytes, edited, inserted, deleted, header lines)."""
    sc = _scan(part)
    check_reconcile(sc, ident, header_texts)
    al = dm.align(sc.paragraphs, blocks, ident, heading_styles)
    header = [sc.paragraphs[i].text for i in al.zone]
    _check_duplicates(sc, blocks, al)
    edits, deletes, inserts = _plan(sc, blocks, al)
    if not (edits or deletes or inserts):
        return part, 0, 0, 0, header
    data = sc.data
    body = {}
    for w, text in edits.items():
        body[w] = edit_paragraph(data, sc.paragraphs[w], text)
    before, after = {}, {}
    for j, donor, anchor, side in inserts:
        new = donor_paragraph(data, sc.paragraphs[donor], blocks[j]["text"])
        (after if side == "after" else before).setdefault(anchor, []).append(new)
    splice = []
    for w in sorted(set(body) | set(before) | set(after)):
        para = sc.paragraphs[w]
        own = body.get(w, data[para.start:para.end])
        splice.append((para.start, para.end, b"".join(before.get(w, [])) + own + b"".join(after.get(w, []))))
    for w in deletes:
        para = sc.paragraphs[w]
        splice.append((para.start, para.end, b""))
    try:
        new_part = dp.splice(data, splice, sc.protected())
    except dp.PackageRefusal as e:
        raise UpdateRefusal("R9", e.detail)
    _post_condition(new_part, sc, len(al.zone), blocks, al, ident)
    return new_part, len(edits), len(inserts), len(deletes), header


def update(docx_bytes, blocks, ident, heading_styles=None):
    """Write the md's `blocks` into the Word file `docx_bytes` in place. Returns an `Update`, or raises
    `UpdateRefusal` with nothing returned. `heading_styles` is `docx_ats.heading_styles(...)` of the same file, read from it when None."""
    try:
        part = dp.read_part(docx_bytes)
        if heading_styles is None:
            heading_styles = da.heading_styles(da.style_table(_styles(docx_bytes)))
        header_texts = page_header_texts(docx_bytes)
        new_part, edited, inserted, deleted, header = update_part(part, blocks, ident, heading_styles,
                                                                  header_texts)
        if new_part == part:
            return Update(docx_bytes, part, 0, 0, 0, header)
        out = dp.rewrite_part(docx_bytes, new_part)
    except dp.PackageRefusal as e:
        raise UpdateRefusal(e.rule if e.rule.startswith("R") else "R9", e.detail)
    return Update(out, new_part, edited, inserted, deleted, header)
