"""Migration 0.37.0: `m_0_37_0_medium_line()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import re

VERSION = "0.37.0"


# The ONE legacy shape this relocates: the value written INTO the Status line as a bold
# label, `**Medium: linkedin-message**`, instead of on the entry's own line. Exactly one
# such fragment, naming exactly one MEDIA value — anything else is left where it is and said
# out loud.
MEDIUM_IN_STATUS_RE = re.compile(r"\*\*Medium:\s*([A-Za-z0-9-]+)\s*\*\*")


def m_0_37_0_medium_line(profile, apply_it):
    """0.37.0 — a medium written into the `**Status:**` line is RELOCATED onto the entry's own
    `**Medium:**` line (dev #265, first instance; the owner declined a tolerant reader).

    precondition.medium_of reads one line-anchored `**Medium:**` line per entry; a value
    anywhere else is prose to it and the row renders `medium: unknown`. Measured 2026-09-03
    on one profile: three entries carried a correct, in-vocabulary value inside the Status
    field's prose — `**Status:** rewritten. **Medium: linkedin-message** (~N words, cap N)` —
    and no `**Medium:**` line at all. The reader was NOT taught that shape: a reader that
    learns malformed output loses the ability to detect drift, and the writer produced three
    different shapes in one day. The writer is fixed (outreach-drafter § the entry's meta
    lines) and this heals what is already written, once.

    PRESERVE, THEN TRANSFORM. Only an entry with NO `**Medium:**` line whose Status line
    carries EXACTLY ONE `**Medium: <value>**` fragment naming EXACTLY ONE validate_data.MEDIA
    value gets a `**Medium:** <value>` line inserted directly under its Status line. That is
    relocation of a token from a known position, never inference. The Status line itself is
    left byte-identical — the leftover fragment is inert to the line-anchored reader, and
    deleting prose is the one thing a migration cannot undo. Everything else is reported,
    never guessed over: a Status line naming a medium in any other shape (`MEDIUM changed to
    …`, two fragments, a non-vocabulary token) stays `unknown` and is printed; a `**Medium:**`
    line that names no value stays `unknown` and is printed; an entry with no line and no
    mention is counted. The dashboard flags every one of those rows on the page.

    Drafts only: cover letters carry no medium dimension (generate_dashboard.COVER_DIMS).
    Idempotent: a relocated entry has a line and is skipped on the next pass. Entries are
    split by precondition.ENTRY_RE — the reader's own definition — so this cannot file a
    line under a different entry than the one the reader will read it from.
    """
    import _tree
    import precondition as _pre
    path = _tree.resolve_rel(profile, _tree.rel("drafts"))
    if not os.path.exists(path):
        return True, ""
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError as e:
        return False, "  ⚠️ %s could not be read, so no medium line was relocated: %s" % (
            _tree.rel("drafts"), e)

    inserts, loud, bare = [], [], 0          # inserts: (absolute offset, value, title)
    for m in _pre.ENTRY_RE.finditer(md):
        title, body = m.group(1).strip(), m.group(2)
        if _pre.medium_of(body) != "unknown":
            continue
        if _pre.MEDIUM_RE.search(body):
            loud.append("%s: its `**Medium:**` line names no MEDIA value" % title[:60])
            continue
        sm = _pre.STATUS_RE.search(body)
        status_line = ""
        if sm:
            end = body.find("\n", sm.start())
            end = len(body) if end < 0 else end
            status_line = body[sm.start():end]
            values = [v.lower() for v in MEDIUM_IN_STATUS_RE.findall(status_line)]
            if len(values) == 1 and values[0] in _pre.MEDIA:
                inserts.append((m.start(2) + end, values[0], title))
                continue
        if re.search(r"medium", body, re.I):
            loud.append("%s: names a medium in a shape this migration does not read — write "
                        "its `**Medium:**` line by hand" % title[:60])
        else:
            bare += 1

    if not (inserts or loud or bare):
        return True, ""
    bits = []
    if inserts:
        bits.append("%d medium value(s) relocated from the Status line onto a `**Medium:**` "
                    "line: %s" % (len(inserts), "; ".join("%s→%s" % (t[:40], v)
                                                         for _o, v, t in inserts)[:300]))
    for l in loud:
        bits.append("⚠️ still `unknown` — " + l)
    if bare:
        bits.append("%d entr%s carr%s no `**Medium:**` line and name no medium — flagged on "
                    "the dashboard row; the writer owns the line from 0.37.0"
                    % (bare, "y" if bare == 1 else "ies", "ies" if bare == 1 else "y"))
    if not apply_it:
        return True, "  would relocate (0.37.0): " + " · ".join(bits)
    if inserts:
        new = md
        for off, value, _title in sorted(inserts, reverse=True):
            new = new[:off] + "\n**Medium:** " + value + new[off:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new)
        os.replace(tmp, path)               # atomic: never a half-written drafts file
    return True, "  ✅ %s (0.37.0): " % _tree.rel("drafts") + " · ".join(bits)
