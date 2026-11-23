"""bullets: the quantified-bullets section (design-presence-report.md §5.3, D-QUANT).

Per active variant: `7 of 12 bullets carry a number`. A bullet carries a number when a digit remains after removing
bare years (`YEAR_RE`). A count only: no target, no gap, no draft (O15). `LIMITS` is printed under the figures.
Pure functions over text; nothing here reads a file."""

import re

from presence.union_text import bullets_with_sections

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DIGIT_RE = re.compile(r"\d")
LIMITS = "limits: a spelled-out quantity (\"by half\") is not counted, and a year is not a result"


def carries_number(bullet):
    """True when a digit remains in `bullet` once bare years are removed."""
    return bool(DIGIT_RE.search(YEAR_RE.sub("", str(bullet or ""))))


def counts(text):
    """`(bullets carrying a number, bullets)` of a variant's text."""
    found = [b for b, _section in bullets_with_sections(text)]
    return sum(1 for b in found if carries_number(b)), len(found)


def variant_line(variant):
    """`  <id> (<surface>): 7 of 12 bullets carry a number` for one readable variant `{id, surface, text}`."""
    n, total = counts(variant["text"])
    return "  %s (%s): %d of %d bullets carry a number" % (variant["id"], variant["surface"], n, total)
