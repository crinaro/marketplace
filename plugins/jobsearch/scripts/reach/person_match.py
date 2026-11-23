"""person_match: the one answer to "are these two people records the same person".

The three normalizers (name, email, LinkedIn URL; ADR-031 §3 / §28.2 row 3) and `find_duplicates`,
the weak-signal pair query. Moved out of `people.py` unchanged by split_module.py (jobsearch 0.92.0,
P0) so the follow-list reader can use the same matching without importing an entry point;
`people.py` keeps every name importable through a facade. Takes plain row dicts, never a Graph.
Stdlib only."""

import re
import unicodedata
import urllib.parse


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
    `{"a": id, "b": id, "reason": str, "kind": "email" | "name-company" | "name"}` (`kind` names which row of the table above
    matched, for a reader that words it itself; jobsearch 0.92.0, design-decision-surface.md B.4 step 8), sorted for a deterministic report — this is a QUERY,
    recomputed from data on every call, never a stored list that can go stale."""
    cands = [_candidate(r) for r in rows]
    out = []
    seen_pairs = set()
    n = len(cands)
    for i in range(n):
        a = cands[i]
        if a["status"] == "merged" or not a["id"]:
            continue
        na = normalize_name(_strip_role_suffix(a["name"]))
        ea = normalize_email(a["email"])
        for j in range(i + 1, n):
            b = cands[j]
            if b["status"] == "merged" or not b["id"]:
                continue
            if a["id"] == b["id"]:
                continue
            if b["id"] in a["not_same_as"] or a["id"] in b["not_same_as"]:
                continue
            nb = normalize_name(_strip_role_suffix(b["name"]))
            eb = normalize_email(b["email"])
            reason = kind = None
            if ea and eb and ea == eb and na != nb:
                reason, kind = "same email (%s), different name — a shared inbox or a typo" % ea, "email"
            elif na and nb and na == nb:
                # public #93 — a name that only compares equal after `_strip_role_suffix`
                # (one side carried a title stuffed into the name field) gets its own reason,
                # never folded into the plain same-name case: it names the MECHANISM so the
                # human deciding does not have to re-derive it from two raw strings.
                stuffed = (normalize_name(a["name"]) != normalize_name(b["name"]))
                if a["company_id"] and a["company_id"] == b["company_id"]:
                    kind = "name-company"
                    reason = ("same name%s, same company (%s) — two different people, or one "
                              "mis-slugged"
                              % (" once a stuffed title is stripped" if stuffed else "",
                                 a["company_id"]))
                else:
                    kind = "name"
                    reason = ("same name%s, different company — a slug collision, or the same "
                              "person across employers"
                              % (" once a stuffed title is stripped" if stuffed else ""))
            if reason:
                pair = tuple(sorted((a["id"], b["id"])))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    out.append({"a": pair[0], "b": pair[1], "reason": reason, "kind": kind})
    out.sort(key=lambda p: (p["a"], p["b"]))
    return out


_TITLE_SEP_RE = re.compile(r"\s*[,\-–—|/]\s*")
# A small, closed, role-class vocabulary (public #93) — deliberately NOT "any word after a
# separator", because a hyphenated surname ("Mary Smith-Jones") or a genuine suffix ("Pat
# Rivera, Jr.") must NEVER be stripped: the tail there never matches one of these words, so
# both are left exactly as recorded. Lowercased, single tokens only (matched against the
# tail's own lowercased word set) — this never changes `normalize_name` itself, only what
# `find_duplicates` (below) compares, because the IDENTITY rule §3 states is unaffected: a
# stuffed-title pair is SURFACED here, never auto-merged, exactly as any other weak signal is.
_ROLE_WORDS = frozenset({
    "vp", "svp", "evp", "avp", "director", "manager", "lead", "head", "chief", "president",
    "officer", "founder", "ceo", "cto", "coo", "cfo", "cmo", "engineer", "engineering",
    "recruiter", "recruiting", "talent", "partner", "principal", "staff", "architect",
    "consultant", "specialist", "coordinator", "associate", "analyst",
})


def _strip_role_suffix(name):
    """`"Jordan Rivera, VP Engineering"` -> `"Jordan Rivera"` — strip a trailing role/title
    clause STUFFED into a name field, for DUPLICATE DETECTION ONLY (never `normalize_name`
    itself, and never what a migration mints an id or a survivor from). Splits on the first
    separator (comma, hyphen, en/em dash, pipe, slash) and drops the tail only when it
    contains at least one word from the closed `_ROLE_WORDS` list — a name that happens to
    contain a hyphen or comma for an unrelated reason is returned unchanged, because its tail
    never matches a role word. Never raises; unreadable input returns "" (matching
    `normalize_name`'s own contract for the same input)."""
    s = str(name or "")
    m = _TITLE_SEP_RE.search(s)
    if not m:
        return s
    head, tail = s[:m.start()], s[m.end():]
    tail_words = set(re.findall(r"[a-z]+", tail.lower()))
    return head if (tail_words & _ROLE_WORDS) else s
