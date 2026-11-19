"""Migration 0.19.0: `m_0_19_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.19.0"


def m_0_19_0(profile, apply_it):
    """0.19.0 — the knowledge stores get their join to the pipeline (GitHub issue #12).

    `kb/` filenames were free-form and drifted; dated call-prep notes joined to nothing; the
    promote-before-archive rule lived only in prose. `knowledge.py` now resolves three fields
    (`**Company:**`, `**Companies:**`, `**Promoted:**`) against the data model, and this
    migration marks every pre-existing file so a gap reports as `unresolved` — never as absent,
    and never as fine. Same shape as m_0_18_0; fires when the engine version reaches 0.19.0.

    ⭐ PRESERVE, THEN TRANSFORM — nothing is renamed, moved, or deleted. Files gain one or two
    marker lines; existing content is untouched, so every drifted kb file stays exactly where
    its owner knows it, just LOUDLY unjoined until someone structures the join.

    The one join written confidently: a kb filename that equals a company id after separator
    normalization (`Bluewater_Grid.md` → `bluewater-grid`) gets its `**Company:**` field —
    deterministic, not a guess. A business-unit-vs-parent mismatch or a no-match filename gets
    `unresolved`: guessing that join would file one organization's intel under another,
    which is the same store-that-answers-wrongly this whole issue is about.

    Additive and idempotent: files already carrying a field are skipped. SAFE by this module's
    rule — inserts lines, deletes nothing, reversible from git.
    """
    import knowledge as _kn

    def _insert(path, lines):
        """Insert marker lines after a leading heading (or at the top), atomically."""
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
        body = md.splitlines(True)
        at = 1 if body and body[0].lstrip().startswith("#") else 0
        block = "".join(l + "\n" for l in lines)
        if at and body[0] and not body[0].endswith("\n"):
            block = "\n" + block
        new = "".join(body[:at]) + block + "".join(body[at:])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new)
        os.replace(tmp, path)

    def _norm(s):
        import re as _re
        return _re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

    cids = _kn.company_ids(profile)
    by_norm = {}
    for cid in cids:
        by_norm.setdefault(_norm(cid), []).append(cid)

    planned = []   # (path, lines, note)
    kb_dir = os.path.join(profile, "kb")
    for name in sorted(os.listdir(kb_dir)) if os.path.isdir(kb_dir) else []:
        if not name.endswith(".md") or name.lower() in _kn.KB_EXEMPT:
            continue
        path = os.path.join(kb_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                md = fh.read()
        except OSError:
            continue
        stem = name[:-3]
        if _kn.KB_FIELD_RE.search(md) or stem in cids:
            continue                          # already joined, by field or by name
        hits = by_norm.get(_norm(stem)) or []
        if len(hits) == 1:
            planned.append((path, ["**Company:** company:%s (migrated 0.19.0 from filename)"
                                   % hits[0]], "kb/%s → company:%s" % (name, hits[0])))
        else:
            planned.append((path, ["**Company:** unresolved (migrated 0.19.0 — filename "
                                   "resolves to no company id)"], "kb/%s → unresolved" % name))

    prep_dir = os.path.join(profile, "call_preps")
    for name in sorted(os.listdir(prep_dir)) if os.path.isdir(prep_dir) else []:
        if not name.endswith(".md"):
            continue
        path = os.path.join(prep_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                md = fh.read()
        except OSError:
            continue
        if not _kn.PREP_FIELD_RE.search(md):
            planned.append((path, ["**Companies:** unresolved (migrated 0.19.0 — organizations "
                                   "not yet recorded)"], "call_preps/%s → unresolved" % name))

    for sub in _kn.ARCHIVE_DIRS:
        d = os.path.join(profile, sub)
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not name.endswith(".md"):
                continue
            path = os.path.join(d, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    md = fh.read()
            except OSError:
                continue
            lines = []
            if not _kn.PREP_FIELD_RE.search(md):
                lines.append("**Companies:** unresolved (migrated 0.19.0 — organizations "
                             "not yet recorded)")
            if not _kn.PROMOTED_RE.search(md):
                lines.append("**Promoted:** unresolved (migrated 0.19.0 — promotion not "
                             "recorded)")
            if lines:
                planned.append((path, lines, "%s → unresolved" % os.path.join(sub, name)))

    if not planned:
        return True, ""
    if not apply_it:
        return True, ("  would mark %d knowledge-store file(s) whose join or promotion is "
                      "unrecorded (kb/, call_preps/, archived preps)" % len(planned))
    for path, lines, _note in planned:
        _insert(path, lines)
    return True, ("  ✅ knowledge stores — %d file(s) marked: joins written where the filename "
                  "resolves deterministically, `unresolved` where only a human can say. "
                  "`knowledge.py --check` is loud until each is structured; nothing was "
                  "renamed, moved, or deleted." % len(planned))
