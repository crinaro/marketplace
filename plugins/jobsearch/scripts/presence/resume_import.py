"""resume_import: the text of a resume brought in from outside the profile, for `record.py presence-import` (owner ruling
2026-11-23: "It will import from an external location and will have full authorization to update within the project").

What "an external location" can be, and what this module reads of it:

    .md .markdown .txt   UTF-8 text (a byte-order mark dropped, CRLF and CR made LF), as it is
    .docx                the paragraphs of `word/document.xml`, in order: a Heading1..6 or Title paragraph becomes a `#`
                         line, a numbered or List-style paragraph (or one opening with a bullet glyph) a `- ` line, any
                         other paragraph its text; deleted tracked-change text and field codes are left out
    anything else        refused with the route: a PDF, .doc, .rtf, .odt or .pages file is read by the session into a .md
                         file first, verbatim, and that file is imported; a Google Doc is fetched through the session's
                         Drive connector as a .docx or text file, and that file is imported

The bullets matter most: a variant's bullet lines are claims (`resume_variants.py`), so a Word list item must arrive as a
`- ` line, never as bare prose the containment check cannot see.

Refused, never guessed: a file that cannot be read, is larger than `MAX_BYTES`, is not UTF-8 (text), is not a zip holding
`word/document.xml` (docx), declares a DTD (no Word document does; refusing it keeps entity expansion out), or yields no
text. Capability module of `record.py` (through `recording/presence_verbs.py`). Python 3.9+, standard library only."""

import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile

MAX_BYTES = 5 * 1024 * 1024          # a resume is kilobytes; a larger file (or a larger unzipped document part) is refused
TEXT_EXTENSIONS = (".md", ".markdown", ".txt")
DOCX_EXTENSIONS = (".docx",)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_RE = re.compile(r"^(?:Heading|heading)\s?([1-6])$")
GLYPH_RE = re.compile(r"^[•●▪◦‣⁃·\-\*]\s+")
ROUTE = ("read it into a .md file first, verbatim (the session can read a PDF), or fetch a Google Doc through the Drive "
         "connector as a .docx or text file, then import that file")


class ImportRefusal(ValueError):
    """The file cannot be imported; the text says why and what to do instead."""


def _read_bytes(path):
    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            raise ImportRefusal("%s is %d bytes, larger than the %d a resume import reads" % (path, size, MAX_BYTES))
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as e:
        raise ImportRefusal("%s cannot be read (%s)" % (path, e))


def normalize(text):
    """LF line ends, no trailing spaces, at most one blank line in a row, one final newline."""
    lines = [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) + "\n" if out else ""


def _paragraph(p):
    """One `w:p` as a line of markdown, or "" for an empty paragraph."""
    ppr = p.find(W + "pPr")
    style = ""
    listed = False
    if ppr is not None:
        ps = ppr.find(W + "pStyle")
        style = (ps.get(W + "val") or "") if ps is not None else ""
        listed = ppr.find(W + "numPr") is not None
    parts = []
    for el in p.iter():
        if el.tag == W + "t":
            parts.append(el.text or "")
        elif el.tag == W + "tab":
            parts.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            parts.append(" ")
    text = " ".join("".join(parts).split())
    if not text:
        return ""
    m = HEADING_RE.match(style)
    if m or style == "Title":
        return "%s %s" % ("#" * (int(m.group(1)) if m else 1), text)
    if listed or style.startswith("List") or GLYPH_RE.match(text):
        return "- " + GLYPH_RE.sub("", text)
    return text


def docx_text(data):
    """The markdown text of a .docx file's bytes (see the module docstring), or raises `ImportRefusal`."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = zf.getinfo("word/document.xml")
            if info.file_size > MAX_BYTES:
                raise ImportRefusal("its document part unpacks to %d bytes, more than %d" % (info.file_size, MAX_BYTES))
            xml = zf.read(info)
    except KeyError:
        raise ImportRefusal("it is a zip with no word/document.xml, so not a Word document")
    except (zipfile.BadZipFile, OSError, RuntimeError) as e:
        raise ImportRefusal("it is not a readable .docx (%s)" % type(e).__name__)
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ImportRefusal("its document part declares a DTD, which no Word document does")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ImportRefusal("its document part is not well-formed XML (%s)" % e)
    body = root.find(W + "body")
    paragraphs = body.iter(W + "p") if body is not None else ()
    return normalize("\n".join(_paragraph(p) for p in paragraphs))


def read_external(path):
    """The text to import from `path` (a `.md`, `.markdown`, `.txt` or `.docx` file), or raises `ImportRefusal`."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXTENSIONS + DOCX_EXTENSIONS:
        raise ImportRefusal("%s is a %s file, which is not imported directly: %s"
                            % (path, ext or "extension-less", ROUTE))
    data = _read_bytes(path)
    if ext in DOCX_EXTENSIONS:
        try:
            text = docx_text(data)
        except ImportRefusal as e:
            raise ImportRefusal("%s: %s" % (path, e))
    else:
        try:
            text = normalize(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise ImportRefusal("%s is not UTF-8 text: %s" % (path, ROUTE))
    if not text.strip():
        raise ImportRefusal("%s holds no text to import" % path)
    return text
