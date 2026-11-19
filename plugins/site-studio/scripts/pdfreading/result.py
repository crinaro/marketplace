"""result.py -- what a read returns (status, reasons, text, document /Info and XMP strings) and the search forms of the text.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
from pdfreading.values import _LIGATURES


def _pdf_text_string(b):
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace")
    if b.startswith(b"\xff\xfe"):
        return b[2:].decode("utf-16-le", "replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    return b.decode("latin-1")


class PdfReadResult(object):
    def __init__(self):
        self.status = "not_read"
        self.reasons = []
        self.text = ""
        self.pages = 0
        self.text_ops = 0
        self.info = {}
        self.xmp = {}

    @property
    def read(self):
        return self.status == "read"

    def search_forms(self):
        """The decoded text, and the same text with ALL whitespace removed (for term scans), both
        with ligature code points folded the way normalise_text() folds them (F10)."""
        folded = self.text.translate(_LIGATURES)   # a ligature glyph (U+FB01) searches as "fi"
        return [folded, re.sub(r"\s+", "", folded)]

    def to_dict(self):
        return {"status": self.status, "reasons": list(self.reasons), "pages": self.pages,
                "textOps": self.text_ops, "info": dict(self.info), "xmp": dict(self.xmp),
                "text": self.text}


_INFO_KEYS = ("Author", "Creator", "Producer", "Title", "Subject", "Keywords", "Company")
_XMP_FIELDS = (("dc:creator", "creator"), ("dc:title", "title"), ("pdf:Producer", "producer"),
               ("xmp:CreatorTool", "creatortool"), ("pdf:Author", "author"),
               ("pdf:Keywords", "keywords"), ("dc:description", "description"))
