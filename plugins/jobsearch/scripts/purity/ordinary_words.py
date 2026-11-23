"""Is a single-token company name an ordinary English word? The engine itself answers (dev #1029, public #268).

A profile that tracks an employer whose name is one common English word flagged every engine file
that used the word: a capitalised sentence start, a heading, a quoted literal. The occurrence-shape rule
(`check_engine_purity._shape_exempt`, dev #342) already exempts the lowercase, unjoined prose use; the remaining
shapes cannot be told apart from a leak by shape alone, so the TERM has to be judged.

THE MECHANISM, AND WHY NOT A WORD LIST. Python's standard library has no dictionary, a shipped word list is a
dependency of its own (unauditable at dictionary size, and a list of real company names would be exactly the
personal-data shape this check exists to refuse), and `/usr/share/dict/words` is absent on some surfaces, so a
check that read it would answer differently per machine. The evidence used instead is the engine's own text, which
the scan already reads: a single-token term written as an ordinary lowercase word (the shape-exempt occurrences
`scan()` already collects) in at least `MIN_FILES` distinct engine files is a word of the engine's own vocabulary,
not a name the engine learned from one profile. Such a term is SET ASIDE: its hits do not count, and the company's
`domain` (added as its own term by `domain_qualifier`) is the qualifier that still does. A leak written as a
proper noun cannot manufacture this evidence: a name is capitalised, joined or quoted, never bare lowercase prose
in three files (the residual dev #342 already accepts, and counts on every run).

Scope: kinds `encountered` and `employer` only (the terms derived from company and contact names). The owner's own
`name` kind stays strict, as `_shape_exempt` keeps it; `geo` and `mailbox` are not company names. A multi-token
term is never set aside (two ordinary words making one specific phrase is not something prose does by accident),
and neither is a term carrying anything but letters (a domain, an address).
"""

MIN_FILES = 3
KINDS = ("encountered", "employer")


def candidate(kind, term):
    """True when `term` (of `kind`) may be judged an ordinary word at all: a company-derived kind, one token,
    letters only."""
    return kind in KINDS and isinstance(term, str) and term.isalpha()


def ordinary_word_terms(records, terms, min_files=MIN_FILES):
    """{(kind, term)} for every candidate term whose shape-exempt occurrences span `min_files` or more distinct
    files. `records` is an iterable of the scan's per-file records (`{"path", "text", "exempt": [[line, kind,
    term_index, sha], ...]}`); a record with no `exempt` list contributes nothing, so a caller that did not collect
    the exempt matches sets nothing aside. `term_index` points into the SORTED term list of its kind."""
    sorted_terms = {k: sorted(v) for k, v in (terms or {}).items()}
    files = {}
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("text"):
            continue
        for row in rec.get("exempt") or ():
            kind, idx = row[1], row[2]
            st = sorted_terms.get(kind) or []
            if not 0 <= idx < len(st) or not candidate(kind, st[idx]):
                continue
            files.setdefault((kind, st[idx]), set()).add(rec.get("path"))
    return {key for key, paths in files.items() if len(paths) >= min_files}


def domain_qualifier(row):
    """The lowercased `domain` of a `companies.jsonl` row whose name is a single token, or None. It is the
    qualifier a single-word name keeps when the word itself is set aside: a host is never ordinary prose."""
    if not isinstance(row, dict):
        return None
    name, domain = str(row.get("name") or "").strip(), str(row.get("domain") or "").strip().lower()
    if not name or " " in name or not domain:
        return None
    if domain.startswith("www."):
        domain = domain[4:]
    if "." not in domain or any(c in domain for c in " /@:"):
        return None
    return domain
