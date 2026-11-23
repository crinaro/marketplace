"""union_text: reading the claim union (`presence/claims.md`) as text, moved out of
`resume_variants.py` unchanged (design-presence-report.md §11 B0): the bullet and heading
patterns, `_norm`, `read_union` and `bullets_with_sections`. `claim_key` (§5.2) is the one
comparison form of a claim; the report's `claim:<sha8>` key hashes it. `resume_variants`
re-exports the moved names."""

import _tree
import hashlib
import re


BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# public #59, ADR-027 — the per-claim marking, at the HEAD of a union bullet's own text. No
# section default, no cross-reference table, no id: the tag IS the claim's review stamp.
CLAIM_TAG_RE = re.compile(r"^\[(public|private)\]\s*(.+)$", re.I)


def _norm(s):
    """Whitespace-collapsed, case preserved — verbatim discipline minus formatting."""
    return " ".join((s or "").split())


def read_union(root):
    path = _tree.path(root, "claims")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def bullets_with_sections(text):
    """[(normalized_bullet, heading_path_of_its_section)] in file order.

    public #67 — heading_path is the full ancestor chain ("Outer > Inner"), not just the
    nearest heading. A single flat `heading` variable overwritten on every heading line loses
    the addenda association the moment a sub-heading nests under it: an "## Additional Detail"
    section containing "### <topic>" sub-headings reported every bullet under the sub-heading
    as having heading "<topic>" alone, so ADDENDA_HEADING_RE.search(heading) in report() no
    longer matched "additional detail" and those claims were counted as claims outside the
    addenda — overstated, not actually orphaned. Joining the ancestor chain keeps the match
    working via the same substring search, however deep the nesting goes.
    """
    out, stack = [], []   # stack: [(level, text), ...], outermost first
    for line in (text or "").splitlines():
        hm = HEADING_RE.match(line)
        if hm:
            level, htext = len(hm.group(1)), hm.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, htext))
            continue
        bm = BULLET_RE.match(line)
        if bm:
            out.append((_norm(bm.group(1)), " > ".join(t for _, t in stack)))
    return out


def claim_key(bullet):
    """A claim's comparison form (design-presence-report.md §5.2): the bullet as
    `bullets_with_sections` returns it, a head `[public]` or `[private]` tag removed, whitespace
    collapsed. The report's `<sha8>` is the first eight hex of sha-256 over this, UTF-8."""
    text = _norm(bullet)
    m = CLAIM_TAG_RE.match(text)
    return _norm(m.group(2)) if m else text


def sha8(bullet):
    """The report's `<sha8>` (design-presence-report.md §5.7): the first eight hex of sha-256 over
    `claim_key(bullet)`, UTF-8. `record.py presence-propose` resolves a cited key through this one function."""
    return hashlib.sha256(claim_key(bullet).encode("utf-8")).hexdigest()[:8]


def is_public(bullet):
    """True when a union bullet carries the head `[public]` tag (ADR-027's per-claim review stamp)."""
    m = CLAIM_TAG_RE.match(_norm(bullet))
    return bool(m and m.group(1).lower() == "public")
