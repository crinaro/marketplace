"""The level-2 cap (design-dashboard-redesign §4; dashboard-redesign E): FOLD OVER CAP.

    check_folds(page, ledger, expected) -> (gaps, line)

Level 2 of every list is one-line rows inside ONE closed `<details>`, at most `LEVEL2` of them, "every fold, the
Drafts waiting fold included"; past that a row is a COUNT (level 3, `data-more`), never another row. A closed fold
that directly holds more than `LEVEL2` rows is the gap: the page has started growing with the data again (public #54
was the opposite failure: a row trimmed where no reader could reach it; level 3's count line is what keeps both
honest). A row is any element `walk` calls one (`data-rec`, `data-ref` or `data-subject`), so a list of rows that are
not records, such as the excluded companies, is held too. A row belongs to its NEAREST closed fold: a draft's own
text fold inside a folded row holds no row and is not counted.

`LEVEL2` is this module's own constant, never `dashboard.caps.LEVEL2` (a gate that read the renderer's cap would
loosen with it). Pure: no I/O; `ledger` and `expected` are accepted for the uniform signature and not read."""
import collections

from coverage_checks.walk import walk

LEVEL2 = 20                             # design §4: 20 per fold, every fold


def check_folds(page, ledger=None, expected=None):
    """(gaps, line): FOLD OVER CAP over `page` (the module docstring)."""
    w = walk(page)
    per_fold = collections.Counter(r.fold for r in w.rows if r.fold is not None)
    gaps = []
    for fold, n in sorted(per_fold.items()):
        if n > LEVEL2:
            gaps.append("FOLD OVER CAP -- the fold %r holds %d rows; level 2 holds at most %d, and the rest of a list "
                        "is one counted line, `+ N more` (design §4)" % (w.folds[fold][1][:60], n, LEVEL2))
    biggest = max(per_fold.values()) if per_fold else 0
    return gaps, "folds: %d with rows, the largest holds %d of at most %d" % (len(per_fold), biggest, LEVEL2)
