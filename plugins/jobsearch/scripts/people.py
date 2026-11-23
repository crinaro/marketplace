#!/usr/bin/env python3
"""people.py — identity resolution for the `people` store (ADR-031 §3 / §28.2 row 3).

WHY THIS EXISTS
---------------
ADR-031 promotes `opportunities.contacts[]` and `channels.contacts[]` into one global `people`
store (B1). The design's own §3 sets one rule and calls it the thing that must not go wrong:

    auto-merge ONLY on identical normalized LinkedIn URL, or identical normalized email AND
    identical normalized name. Everything weaker is SURFACED, never merged.

"Normalized" is undecidable prose until it names an algorithm (gate review §28.2, row 3) — this
module is that algorithm, in ONE place, so the migration, `--duplicates`, and (later)
`validate_data.py` can never each grow their own slightly-different idea of "the same email."

⭐⭐ THE THREE NORMALIZERS, EXACTLY AS ADR-031's AMENDMENT (2026-09-09) SPECIFIES — and nothing
more clever than that:

    name      NFKD, strip combining marks, casefold, keep letters/digits/spaces, collapse
              whitespace. An accent and a doubled space must compare equal; two DIFFERENT
              names must never accidentally collapse to the same string.
    email     casefold and strip. NOTHING ELSE — dot/plus-stripping merges two humans at
              some providers (gate review §28.2 row 3's own warning), so this is
              deliberately less aggressive than a "smart" email-dedup would be.
    linkedin  drop scheme, host, `www.`, query string, percent-decode, lowercase, trailing
              slash stripped. Two URLs that resolve to the same `/in/<slug>` are the same
              per-human identifier regardless of how either was pasted in.

None of the three ever raises on bad input — a normalizer that crashes on a malformed profile
value would turn "surface for review" into "the migration crashes," which is a worse failure
than either merging wrong or not merging at all. Unreadable input normalizes to "" (name/email)
or None (linkedin, since "no linkedin at all" and "unparseable linkedin" must both mean "this
signal contributes nothing," never "this signal is a match against every other blank").

`test_checks.py`'s `TestPreB1CoverageFixture` carries a byte-for-byte independent mirror of
these three functions, written BEFORE this file existed, to prove the fixture's own coverage
pairs have the normalized-equal / normalized-different property the migration needs — it is
deliberately NOT rewritten to import from here, so the fixture's claim about itself and this
module's own claim about itself stay two independent measurements of the same rule (this
module's own `TestPeopleNormalizers` below is the second, direct one).

Usage:
    python3 scripts/people.py --duplicates     # print candidate merge pairs the migration
                                                # and every future run would still surface

    from people import normalize_name, normalize_email, normalize_linkedin, find_duplicates

Python 3.9+. Standard library only.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _root import profile_root as _profile_root  # noqa: E402
# Moved out of this file by split_module.py; every moved name stays importable from here until the tests move.
from reach.person_match import (
    _NAME_KEEP,
    _NAME_SPACE,
    normalize_name,
    normalize_email,
    normalize_linkedin,
    _candidate,
    find_duplicates,
    _TITLE_SEP_RE,
    _ROLE_WORDS,
    _strip_role_suffix,
)

ROOT = _profile_root()
DATA = os.environ.get("CLAUDESEARCH_DATA_DIR") or os.path.join(ROOT, "data")

# ---------------------------------------------------------------------------------------------
# THE REVIEW QUEUE — A QUERY, NOT A LIST (design §3). Shared by the migration (which PRINTS
# what it finds and writes nothing for it) and `--duplicates` (which re-derives the same set on
# every run against the STORED people.jsonl, so a queue nobody drains cannot go stale — it is
# recomputed from data every time, per the design's own words).
# ---------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------
# GET-OR-CREATE LOOKUP (dev #686 / public #139, P1) — `record.py create --file people --reuse`.
# ONE matcher: this module's own three normalizers and ADR-031 §3's strength rule, never a
# second. A hit is reusable ONLY on an identical normalized LinkedIn, or an identical
# normalized email AND an identical normalized name. An email-only hit (same inbox, different
# name) is the shared-inbox / typo case `find_duplicates` already lists: it is returned as a
# CANDIDATE in the exact `{"a", "b", "reason"}` shape and is never reused silently.
# ---------------------------------------------------------------------------------------------

def _follow_merge(rows_by_id, row):
    """The survivor row a (possibly merged) row points at; the row itself when it is not
    merged. A cycle or a dangling `merged_into` stops at the last row reachable — never loops,
    never raises."""
    seen = set()
    cur = row
    while cur is not None and cur.get("status") == "merged" and cur.get("merged_into"):
        if cur.get("id") in seen:
            break
        seen.add(cur.get("id"))
        nxt = rows_by_id.get(cur["merged_into"])
        if nxt is None:
            break
        cur = nxt
    return cur


def find_reusable(rows, new):
    """Look `new` (a candidate people dict: `id`, `name`, `email`, `linkedin`) up among `rows`.

    Returns `{"hits": [(survivor_row, matched_on)], "candidates": [{"a","b","reason"}],
    "contradictions": [str]}`:

      hits            every existing person reusable by the strength rule, each resolved
                      through any merge to its survivor, `matched_on` one of
                      `id` · `linkedin` · `email+name`. Two hits on DIFFERENT survivors are
                      the caller's refusal (a guess would merge two people).
      candidates      weak pairs involving `new` in `find_duplicates`' own `{"a","b","reason"}`
                      shape (same email with a different name, above all). Never a reason to
                      reuse.
      contradictions  an id that exists but whose stored email or LinkedIn disagrees with the
                      candidate's: two people under one id.

    Never raises on malformed rows (the normalizers' own contract)."""
    by_id = {r.get("id"): r for r in rows if r.get("id")}
    hits, seen = [], set()

    def _hit(row, how):
        surv = _follow_merge(by_id, row)
        if surv is not None and (surv.get("id"), how) not in seen:
            seen.add((surv.get("id"), how))
            hits.append((surv, how))

    contradictions = []
    nid = new.get("id")
    n_li = normalize_linkedin(new.get("linkedin"))
    n_em = normalize_email(new.get("email"))
    n_nm = normalize_name(new.get("name"))
    if nid and nid in by_id:
        old = by_id[nid]
        o_li = normalize_linkedin(old.get("linkedin"))
        o_em = normalize_email(old.get("email"))
        if n_li and o_li and n_li != o_li:
            contradictions.append("id %r exists with LinkedIn %s, not %s" % (nid, o_li, n_li))
        if n_em and o_em and n_em != o_em:
            contradictions.append("id %r exists with email %s, not %s" % (nid, o_em, n_em))
        if not contradictions:
            _hit(old, "id")
    for r in rows:
        if r.get("id") == nid:
            continue
        r_li = normalize_linkedin(r.get("linkedin"))
        if n_li and r_li and n_li == r_li:
            _hit(r, "linkedin")
            continue
        r_em = normalize_email(r.get("email"))
        if n_em and r_em and n_em == r_em and n_nm and n_nm == normalize_name(r.get("name")):
            _hit(r, "email+name")

    candidates = []
    if nid:
        others = [r for r in rows if r.get("id") != nid]
        candidates = [p for p in find_duplicates(others + [dict(new)])
                      if nid in (p["a"], p["b"])]
    return {"hits": hits, "candidates": candidates, "contradictions": contradictions}


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duplicates", action="store_true",
                    help="print likely-same-person pairs `people.jsonl` still carries, "
                         "un-answered (no merged_into, not in either row's not_same_as)")
    args = ap.parse_args()
    if not args.duplicates:
        ap.print_help()
        return 0
    rows = _load_jsonl(os.path.join(DATA, "people.jsonl"))
    pairs = find_duplicates(rows)
    if not pairs:
        print("No un-answered likely-duplicate people. (%d people row(s) checked.)" % len(rows))
        return 0
    print("%d possible duplicate pair(s) — your call (record.py merge-person <id> --into "
          "<survivor>, or set <id> not_same_as '[\"<other-id>\"]' --file people to say they "
          "are different):" % len(pairs))
    for p in pairs:
        print("  %s <-> %s — %s" % (p["a"], p["b"], p["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
