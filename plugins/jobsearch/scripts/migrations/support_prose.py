"""Marking prose holds in a markdown file, shared by 0.18.0 and 0.27.0.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import os


def _mark_prose_holds(profile, filename, apply_it, label):
    """Shared body of m_0_18_0 and m_0_27_0_cover_preconditions (dev #169): mark every '## '
    entry in `filename` whose text carries a hold phrase but no structured field with
    `**Blocked until:** unresolved (migrated <label> from prose)`. PRESERVE, THEN TRANSFORM —
    the prose stays as evidence; only the marker line is inserted. Additive and idempotent."""
    import precondition as _pre
    path = os.path.join(profile, filename)
    if not os.path.exists(path):
        return True, ""
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError as e:
        return False, ("  ⚠️ %s could not be read, so no preconditions were marked: %s"
                       % (filename, e))

    import re as _re
    marked, out, pos = 0, [], 0
    for m in _re.finditer(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", md, _re.M | _re.S):
        title, body = m.group(1).strip(), m.group(2)
        needs = (not _pre.FIELD_RE.search(body)
                 and (_pre.HOLD_RE.search(title) or _pre.HOLD_RE.search(body)))
        out.append(md[pos:m.end(1)])
        if needs:
            out.append("\n**Blocked until:** unresolved (migrated %s from prose)" % label)
            marked += 1
        out.append(md[m.end(1):m.end()])
        pos = m.end()
    out.append(md[pos:])

    if not marked:
        return True, ""
    if not apply_it:
        return True, ("  would mark %d entry(s) in %s whose send-precondition lives only in "
                      "prose as `**Blocked until:** unresolved`" % (marked, filename))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(out))
    os.replace(tmp, path)               # atomic: never a half-written file
    return True, ("  ✅ %s — %d prose precondition(s) marked as data (`**Blocked "
                  "until:** unresolved`); they now report as blocked, not sendable. Structure "
                  "each with contact:<id> outcome:<...> when the join is known."
                  % (filename, marked))
