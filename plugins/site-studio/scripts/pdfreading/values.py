"""values.py -- the PDF reader's limits (stream size, nesting depth, the word-join gap), the ligature fold table, and the small object types the lexer produces.

Moved out of pdftext.py unchanged (S1b, dev 939) except `_LIGATURES`, which was a comprehension with a call (G3: no work at
import) and is now the same table written out (`test_values.py` asserts it equals the casefold of U+FB00..U+FB06); the
interface and the design notes are in pdftext.py."""


MAX_STREAM = 64 * 1024 * 1024
MAX_DEPTH = 8
JOIN_GAP_EM = 0.15

# Ligature code points that normalise_text() folds by casefolding (U+FB00..U+FB06 -> ff fi fl ffi
# ffl st st). search_forms() folds exactly these and nothing else, so case is left as printed.
_LIGATURES = {0xFB00: "ff", 0xFB01: "fi", 0xFB02: "fl", 0xFB03: "ffi", 0xFB04: "ffl", 0xFB05: "st", 0xFB06: "st"}


class PdfUnsupported(Exception):
    """A stream or construct this module declines to decode (becomes a NOT READ reason)."""


class Name(str):
    """A PDF name object (kept distinct from string objects, which are bytes)."""


class Ref(object):
    __slots__ = ("num", "gen")

    def __init__(self, num, gen):
        self.num, self.gen = num, gen


class Op(str):
    """A bare keyword / content-stream operator."""
