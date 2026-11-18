"""reviews.rows -- the privacy-review record's rows: the strict reader of `.site-studio/reviews.jsonl`, and the one row kind that
is not an agent's review (owner ruling 2026-11-18, template-fidelity step F-1, site-studio 0.4.0).

Part of the `reviews` package behind the entry point `review_record.py`, which moved its row reader here (`validate_row`,
`parse_text`) and keeps thin wrappers that turn this module's `RowError` into its own `ReviewError`. The messages are unchanged.

TWO KINDS OF ROW, and no third.
  A REVIEW row has exactly the eight keys of `ROW_KEYS`: the verdict an agent reached after opening the coverage set.
  A STAND-IN row (`source: "parity-EQUAL+scans"`, plus `scans`) is what the one-process `adopt.py apply` records when no review
  covers the build it is about to publish, parity is EQUAL, and every automated privacy scan of `check_site` passed on that exact
  built tree (`adoption.review_cover`). It is never silent and never a review: the parser admits it ONLY as a `clear` row with
  nothing opened, no findings and nothing accepted, whose `scans` hold exactly `SCANS_KEYS`, parity `EQUAL` and zero findings. An
  ACCEPTED or MARKUP-ONLY parity, a blocked or accepted verdict, a scan that found anything: none of them can be written as one,
  because this reader refuses the row (`test_rows.StandIn`). Every reader (`deploy.py`, `publish_guard.py`) shows it with
  `describe`, so a stand-in is never mistaken for an agent's review.

`verdict_for` in `review_record.py` is unchanged: a stand-in is a `clear` row for its digest, so a BLOCKED review for the same
digest still wins over it, and the one way past a block is the later accepted row it always was.
"""

import json
import re

STORE_REL = ".site-studio/reviews.jsonl"
VERDICTS = ("clear", "accepted", "blocked")
ROW_KEYS = ("v", "digest", "baseline", "verdict", "opened", "findings", "accepted", "at")
SOURCE_STANDIN = "parity-EQUAL+scans"
STANDIN_KEYS = ("source", "scans")
SCANS_KEYS = ("parity", "files", "images", "pdfsRead", "findings")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class RowError(ValueError):
    """A refusal. The message is one line the person can act on."""


def _ints(scans, where):
    for k in ("files", "images", "pdfsRead", "findings"):
        if isinstance(scans[k], bool) or not isinstance(scans[k], int) or scans[k] < 0:
            raise RowError("%s: scans.%s must be a whole number, 0 or more" % (where, k))


def _check_standin(row, where):
    """The extra rules of a stand-in row (see the module docstring)."""
    if row["verdict"] != "clear" or row["opened"] or row["findings"] or row["accepted"]:
        raise RowError("%s: a %s row is a 'clear' row that opened nothing and carries no findings (an accepted or blocked "
                       "verdict needs the normal review)" % (where, SOURCE_STANDIN))
    scans = row["scans"]
    if not isinstance(scans, dict) or set(scans) != set(SCANS_KEYS):
        raise RowError("%s: 'scans' must hold exactly %s" % (where, ", ".join(SCANS_KEYS)))
    if scans["parity"] != "EQUAL":
        raise RowError("%s: only parity EQUAL stands in for a review (this row says %r); ACCEPTED and MARKUP-ONLY need the "
                       "normal review" % (where, scans["parity"]))
    _ints(scans, where)
    if scans["findings"] != 0 or scans["files"] < 1:
        raise RowError("%s: a stand-in records scans that found nothing in at least one file; this file is written by review_record.py, never edited by hand: restore it from git history" % where)


def validate_row(row, n):
    where = "%s line %d" % (STORE_REL, n)
    if not isinstance(row, dict):
        raise RowError("%s: a row must be an object" % where)
    if row.get("v") != 1 or isinstance(row.get("v"), bool):
        raise RowError("%s: unknown row version %r (this plugin reads v 1); update the site-studio plugin" % (where, row.get("v")))
    for k in ROW_KEYS:
        if k not in row:
            raise RowError("%s: missing field '%s'; this file is written by review_record.py, never edited by hand: restore it from git history" % (where, k))
    for k in row:
        if k not in ROW_KEYS + STANDIN_KEYS:
            raise RowError("%s: unknown field '%s'; this file is written by review_record.py, never edited by hand: restore it from git history" % (where, k))
    if not isinstance(row["digest"], str) or not _HEX64.match(row["digest"]):
        raise RowError("%s: 'digest' must be 64 lower-case hex characters" % where)
    if row["verdict"] not in VERDICTS:
        raise RowError("%s: 'verdict' must be clear, accepted or blocked" % where)
    if not isinstance(row["baseline"], dict) or "kind" not in row["baseline"]:
        raise RowError("%s: 'baseline' must be an object with a 'kind'" % where)
    for k in ("opened", "accepted"):
        if not isinstance(row[k], list) or not all(isinstance(x, str) for x in row[k]):
            raise RowError("%s: '%s' must be a list of strings" % (where, k))
    if not isinstance(row["findings"], list):
        raise RowError("%s: 'findings' must be a list" % where)
    for f in row["findings"]:
        if (not isinstance(f, dict) or set(f) != {"id", "path", "summary"}
                or not all(isinstance(f[k], str) for k in f)):
            raise RowError("%s: each finding needs exactly id, path and summary (strings)" % where)
    if not isinstance(row["at"], str):
        raise RowError("%s: 'at' must be a string" % where)
    if ("source" in row) != ("scans" in row):
        raise RowError("%s: 'source' and 'scans' go together (a stand-in row names both); this file is written by review_record.py, never edited by hand: restore it from git history" % where)
    if "source" in row:
        if row["source"] != SOURCE_STANDIN:
            raise RowError("%s: unknown source %r (a row is an agent's review, or %s); this file is written by review_record.py, never edited by hand: restore it from git history" % (where, row["source"], SOURCE_STANDIN))
        _check_standin(row, where)
    return row


def parse_text(text):
    """Every row of a store's text, strictly; a bad line raises `RowError` with its number and is never skipped."""
    rows = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise RowError("%s line %d is not valid JSON; fix or remove that line" % (STORE_REL, n))
        rows.append(validate_row(obj, n))
    return rows


def verdict_of(rows, digest):
    """(status, row) for `digest` over `rows` in order: status is "none", "clear", "accepted" or "blocked".

    A `blocked` row wins over any `clear`, before or after it. The only way past one is a LATER
    `accepted` row whose `accepted` list covers every finding id of every `blocked` row for the
    digest so far. A new `blocked` row after that re-blocks."""
    blocked = False
    blocked_ids = set()
    best = None
    for row in rows:
        if row["digest"] != digest:
            continue
        v = row["verdict"]
        if v == "blocked":
            blocked = True
            blocked_ids |= set(f["id"] for f in row["findings"])
            best = row
        elif v == "accepted":
            if blocked:
                if set(row["accepted"]) >= blocked_ids:
                    blocked = False
                    best = row
            else:
                best = row
        else:                                   # clear
            if not blocked:
                best = row
    if best is None:
        return "none", None
    return ("blocked" if blocked else best["verdict"]), best


def is_standin(row):
    return isinstance(row, dict) and row.get("source") == SOURCE_STANDIN


def describe(status, row):
    """What every reader prints about the row `verdict_for` chose, after its own `review:` label (`status` is that function's)."""
    if is_standin(row):
        s = row["scans"]
        return ("%s stand-in on %s, NOT an agent's review: parity EQUAL and every automated privacy scan passed (%d files "
                "scanned, %d images, %d PDFs read)" % (SOURCE_STANDIN, row["at"][:10], s["files"], s["images"], s["pdfsRead"]))
    ids = ", ".join(row["accepted"]) if row["accepted"] else "none"
    return "%s on %s, %d files opened, accepted %s" % (status, row["at"][:10], len(row["opened"]), ids)
