"""titles: the lead-title section (design-presence-report.md §5.1, D-TITLE) and the `<h>` of a title gap's key (§5.7).

**The opening block** of a variant is its non-blank lines above the first bullet line, at most `OPENING_MAX`. Bullets
are the one structure the variant format fixes, so a file that opens with a name, a contact line and a location still
has its title line inside the block.

**A title is present in a line when its words occur there as a run of whole words, in order**, both sides case-folded
and split on anything outside `a-z0-9+#.`. "Staff Engineer" is absent from "Staff Software Engineer" and from "Staff
Engineering Manager", and present in "Senior Staff Engineer, Platform". `LIMITS` is printed with the result.

`<h>` is the first six hex of sha-256 over `json.dumps(sorted(set(titles)), separators=(",", ":"))`, each title
case-folded with whitespace collapsed: it hashes the titles only, so reordering them, or editing a contact line or the
headline, keeps the key. Pure functions over text; nothing here reads a file."""

import hashlib
import json
import re

from presence.union_text import BULLET_RE

OPENING_MAX = 15
SHOWN_LINES = 3
WORD_SPLIT_RE = re.compile(r"[^a-z0-9+#.]+")
LIMITS = ("limits: whole words in order, no synonyms; a longer title containing the target's words counts; a title "
          "only below the first bullet is not seen; a past role's title above it counts")


def usable(titles):
    """The non-blank `targets.titles` entries, stripped, first spelling kept, in order."""
    out, seen = [], set()
    for t in titles if isinstance(titles, list) else ():
        if isinstance(t, str) and t.strip() and _fold(t) not in seen:
            seen.add(_fold(t))
            out.append(" ".join(t.split()))
    return out


def _fold(text):
    return " ".join(str(text).casefold().split())


def words(text):
    return [w for w in WORD_SPLIT_RE.split(str(text or "").casefold()) if w]


def present_in(title, line):
    """True when `title`'s words occur in `line` as a run of whole words, in order."""
    tw, lw = words(title), words(line)
    if not tw:
        return False
    return any(lw[i:i + len(tw)] == tw for i in range(len(lw) - len(tw) + 1))


def opening_block(text):
    """`[(line number, line), ...]`: the non-blank lines above the first bullet line, at most `OPENING_MAX`."""
    out = []
    for n, line in enumerate(str(text or "").splitlines(), 1):
        if BULLET_RE.match(line):
            break
        if line.strip():
            out.append((n, line.rstrip()))
            if len(out) == OPENING_MAX:
                break
    return out


def find(title, numbered_lines):
    """`(line number, line)` of the first line `title` is present in, or None."""
    for n, line in numbered_lines:
        if present_in(title, line):
            return n, line
    return None


def title_hash(titles):
    """§5.7's `<h>`: the titles only, folded, deduplicated and sorted, so order and other text do not move it."""
    blob = json.dumps(sorted({_fold(t) for t in titles}), separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:6]


def title_lines(titles, numbered_lines, indent="    "):
    """One line per target title: `present (line n): <line>` or `absent`; and whether any was present."""
    out, any_present = [], False
    for t in titles:
        hit = find(t, numbered_lines)
        any_present = any_present or hit is not None
        out.append("%s%s: %s" % (indent, t, "present (line %d): %s" % (hit[0], hit[1].strip()) if hit else "absent"))
    return out, any_present


def variant_section(variant, titles):
    """`(lines, gap or None)` for one readable variant `{id, surface, text}`. The gap is raised when no target title is
    in the opening block; its pool is the caller's (any union bullet, `[public]` only on a public surface)."""
    block = opening_block(variant["text"])
    lines = ["  %s (%s): opening block %d line(s)%s" % (variant["id"], variant["surface"], len(block),
                                                       "" if block else ", none above the first bullet")]
    lines.extend("    | %s" % line for _n, line in block[:SHOWN_LINES])
    shown, any_present = title_lines(titles, block)
    lines.extend(shown)
    if any_present:
        return lines, None
    gap = {"key": "title:%s@%s" % (variant["id"], title_hash(titles)), "target": "variant",
           "variant_id": variant["id"], "field": "opening", "before": "\n".join(l for _n, l in block)}
    return lines, gap


def headline_lines(headline, stated_on, titles):
    """The stated LinkedIn headline printed as a variant's block is, with its date; and whether a title was present."""
    lines = ["  LinkedIn headline (stated %s): %s" % (stated_on, headline)]
    shown, any_present = title_lines(titles, [(1, headline)])
    return lines + [l.replace(" (line 1)", "") for l in shown], any_present
