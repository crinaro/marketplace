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

ROOT = _profile_root()
DATA = os.environ.get("CLAUDESEARCH_DATA_DIR") or os.path.join(ROOT, "data")

_NAME_KEEP = re.compile(r"[^a-z0-9 ]")
_NAME_SPACE = re.compile(r"\s+")


def normalize_name(s):
    """NFKD, strip combining marks, casefold, keep letters/digits/spaces, collapse whitespace.

    "José  Álvarez" and "jose alvarez" must compare equal (an accent AND a doubled space, both
    at once — the exact P2/N-series fixture shape); "Taylor Fixture" at two different companies
    must ALSO compare equal to itself (this function says nothing about whether two equal-name
    people are the same human — that is §3's job, using this as one input, never the whole
    answer)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = _NAME_KEEP.sub("", s)
    return _NAME_SPACE.sub(" ", s).strip()


def normalize_email(s):
    """Casefold and strip. Nothing else — see the module docstring on why dot/plus-stripping
    is deliberately NOT done here (it would merge two different humans at some providers)."""
    if not s:
        return ""
    return str(s).strip().casefold()


def normalize_linkedin(url):
    """`/in/<slug>`, lowercased, scheme/host/`www.` dropped, trailing slash and query string
    stripped, percent-decoded. Returns None for anything that is not a `/in/...` LinkedIn
    profile URL — no URL at all, or a company/school page — since None must never compare
    equal to another None (the caller only compares two REAL normalized values, never treats
    "no linkedin" as a match)."""
    if not url:
        return None
    low = str(url).lower()
    i = low.find("/in/")
    if i == -1:
        return None
    tail = str(url)[i:].split("?", 1)[0].rstrip("/")
    return urllib.parse.unquote(tail).lower()


# ---------------------------------------------------------------------------------------------
# THE REVIEW QUEUE — A QUERY, NOT A LIST (design §3). Shared by the migration (which PRINTS
# what it finds and writes nothing for it) and `--duplicates` (which re-derives the same set on
# every run against the STORED people.jsonl, so a queue nobody drains cannot go stale — it is
# recomputed from data every time, per the design's own words).
# ---------------------------------------------------------------------------------------------

def _candidate(row):
    """Normalize one row (a migration candidate dict, OR a real people.jsonl row — both carry
    the same field names) into the tuple this module's comparisons need. Never raises."""
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "email": row.get("email"),
        "linkedin": row.get("linkedin"),
        "company_id": row.get("company_id"),
        "status": row.get("status"),
        "merged_into": row.get("merged_into"),
        "not_same_as": row.get("not_same_as") or [],
    }


def find_duplicates(rows):
    """Every pair among `rows` that shares a signal too WEAK to auto-merge (design §3's table):

        same normalized email, different normalized name   — a shared/team inbox, or a typo
        same normalized name, same company_id               — two people, one employer
        same normalized name, different (or absent) company — a raw id/slug collision, or
                                                                genuinely the same human at two
                                                                employers over time

    Excludes any pair where either side is `status: merged` (already answered — settled, not a
    question) and any pair already recorded in either row's `not_same_as`. Returns a list of
    `{"a": id, "b": id, "reason": str}`, sorted for a deterministic report — this is a QUERY,
    recomputed from data on every call, never a stored list that can go stale."""
    cands = [_candidate(r) for r in rows]
    out = []
    seen_pairs = set()
    n = len(cands)
    for i in range(n):
        a = cands[i]
        if a["status"] == "merged" or not a["id"]:
            continue
        na = normalize_name(a["name"])
        ea = normalize_email(a["email"])
        for j in range(i + 1, n):
            b = cands[j]
            if b["status"] == "merged" or not b["id"]:
                continue
            if a["id"] == b["id"]:
                continue
            if b["id"] in a["not_same_as"] or a["id"] in b["not_same_as"]:
                continue
            nb = normalize_name(b["name"])
            eb = normalize_email(b["email"])
            reason = None
            if ea and eb and ea == eb and na != nb:
                reason = "same email (%s), different name — a shared inbox or a typo" % ea
            elif na and nb and na == nb:
                if a["company_id"] and a["company_id"] == b["company_id"]:
                    reason = ("same name, same company (%s) — two different people, or one "
                              "mis-slugged" % a["company_id"])
                else:
                    reason = ("same name, different company — a slug collision, or the same "
                              "person across employers")
            if reason:
                pair = tuple(sorted((a["id"], b["id"])))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    out.append({"a": pair[0], "b": pair[1], "reason": reason})
    out.sort(key=lambda p: (p["a"], p["b"]))
    return out


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
    print("%d possible duplicate pair(s) — your call (record.py set <id> merged_into <survivor>, "
          "or set <id> not_same_as '[\"<other-id>\"]' to say they are different):" % len(pairs))
    for p in pairs:
        print("  %s <-> %s — %s" % (p["a"], p["b"], p["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
