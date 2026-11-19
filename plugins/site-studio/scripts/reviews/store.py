"""reviews.store -- the store (`.site-studio/reviews.jsonl`) read strictly, and the verdict for a digest.

An unparseable line, an unknown `v` or a missing or unknown field refuses LOUDLY with the line number; a bad line is never skipped.
A row is stale by digest, never by age. The row rules themselves are `reviews.rows`.
"""
import os
from reviews import rows as review_rows
from reviews.rows import STORE_REL
from reviews.basics import ReviewError


def _validate_row(row, n):
    try:
        return review_rows.validate_row(row, n)
    except review_rows.RowError as e:
        raise ReviewError(str(e))


def load_rows(repo):
    """Every row of the store, strictly. No store file is no rows. Raises ReviewError with the
    line number on anything it cannot read; a bad line is never skipped."""
    path = os.path.join(repo, STORE_REL)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise ReviewError("%s cannot be read (%s)" % (STORE_REL, e.strerror))
    try:
        return review_rows.parse_text(raw.decode("utf-8", "replace"))
    except review_rows.RowError as e:
        raise ReviewError(str(e))


def verdict_for(digest, repo="."):
    """(status, row) for `digest`: status is "none", "clear", "accepted" or "blocked".

    A `blocked` row wins over any `clear`, before or after it. The only way past one is a LATER
    `accepted` row whose `accepted` list covers every finding id of every `blocked` row for the
    digest so far. A new `blocked` row after that re-blocks."""
    return review_rows.verdict_of(load_rows(repo), digest)          # the rule moved to reviews.rows, so the adopt carry reads it too
