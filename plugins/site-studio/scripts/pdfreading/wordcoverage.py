"""wordcoverage.py -- text normalisation, words, and the word-coverage fraction the caller uses to compare a printed PDF with its source text.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
import unicodedata
from collections import Counter


def normalise_text(s):
    """NFC, casefolded, all whitespace runs collapsed to one space, stripped."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def words(s):
    return re.findall(r"\w+", normalise_text(s))


def word_coverage(source_text, decoded_text):
    """Fraction (0..1) of the source's word occurrences present in the decoded text, or None when
    the source has no words (rule 2 then cannot be satisfied)."""
    src = Counter(words(source_text))
    total = sum(src.values())
    if not total:
        return None
    got = Counter(words(decoded_text))
    hit = sum(min(n, got.get(w, 0)) for w, n in src.items())
    return hit / float(total)
