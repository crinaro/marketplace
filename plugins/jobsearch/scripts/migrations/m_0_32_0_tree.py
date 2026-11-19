"""Migration 0.32.0: `m_0_32_0_tree()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil

VERSION = "0.32.0"


def m_0_32_0_tree(profile, apply_it):
    """0.32.0 — the tree becomes the six-phase structure the router already renders
    (public #28; layout table in `_tree.py`, THE one definition this shares with the
    resolver and the `--audit` check).

    The directory tree is a PRIMARY interface — the candidate browses the markdown in the
    desktop app — and it accumulated instead of being designed: ~25 entries at root mixing
    six categories, an application worksheet misfiled into interview prep because applying
    had no home, retirement existing only as prose, and generated output sitting beside
    hand-edited sources. Every move here comes from `_tree.LAYOUT`; nothing is hardcoded
    twice.

    ⭐ PRESERVE, THEN TRANSFORM, mechanically:
      - A move happens only when the destination slot is free; a same-name conflict is
        MERGED for authored markdown (legacy content appended under a stamped heading —
        nothing lost, loudly visible), and resolved keep-canonical for GENERATED files
        (dashboard artifacts are re-derivable by construction).
      - `application_batch_*.md` files found in the prep directory move to `applying/` —
        #28's clearest symptom, the worksheet filed into the nearest adjacent category.
      - RETIREMENT BECOMES A MOVE: a root `focus.md` / `opportunities.md` (both frozen by
        the rulebook, both still live-looking in every listing) goes to
        `archive/retired-trackers/`.
      - A root `nonexistent/` holding only empty directories (the unresolved-placeholder
        signature, #28 item 7) is removed — deleting empty directories loses nothing; one
        holding anything real is moved to `archive/` instead, never deleted.
      - THE UNION IS RENAMED ON THE MOVE: `resume.md` -> `presence/claims.md` (ADR-018's
        deferred question, settled by the owner with public #28 — the old name asserted a
        printed artifact; this is the superset nobody sends, and `claims` is the word the
        variant gate and the docs already use).
      - Declared variant pages move with the union: `data/resume_variants.jsonl` rows whose
        `file` moved get the field rewritten to the new relative path, value-preserving —
        including a row that declared the union itself, which follows the rename.

    ⭐ Scripts resolve every one of these paths through `_tree.path()`, which falls back to
    the legacy location — so a profile this migration has not reached (a failed-open run, a
    cloud checkout mid-window) keeps WORKING, while `_tree.py --audit` keeps SAYING it is
    unmigrated. A missing thing must never read as an empty thing.

    Idempotent: a second run finds every legacy slot empty and no-ops. History is moved,
    never rewritten — log.md, process_archive.md and the archives keep their content
    byte-for-byte; only their location changes where the structure requires it.
    """
    import datetime as _dt
    import _tree

    lines, moved, failed = [], [], []

    def _merge_md(src, dest):
        """Append src's content to dest under a stamped heading, then remove src."""
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        with open(dest, encoding="utf-8") as fh:
            existing = fh.read()
        stamp = ("\n\n## Merged from %s by the 0.32.0 tree migration (%s)\n\n"
                 % (os.path.relpath(src, profile), _dt.date.today().isoformat()))
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(existing.rstrip("\n") + stamp + body.strip() + "\n")
        os.replace(tmp, dest)
        with open(dest, encoding="utf-8") as fh:
            if body.strip() and body.strip()[:80] not in fh.read():
                raise IOError("merge into %s did not verify" % dest)
        os.remove(src)

    def _move(src, dest, generated=False):
        """One verified move. Returns a note, or raises to abort (preserving everything)."""
        rel_s, rel_d = os.path.relpath(src, profile), os.path.relpath(dest, profile)
        if not os.path.exists(src):
            return None
        if not apply_it:
            return "%s -> %s" % (rel_s, rel_d)
        os.makedirs(os.path.dirname(dest) or profile, exist_ok=True)
        if not os.path.exists(dest):
            os.rename(src, dest)
            if not os.path.exists(dest) or os.path.exists(src):
                raise IOError("move %s -> %s did not verify" % (rel_s, rel_d))
            return "%s -> %s" % (rel_s, rel_d)
        # Destination occupied — the half-migrated-then-recreated case.
        if os.path.isfile(src) and os.path.isfile(dest):
            with open(src, "rb") as fa, open(dest, "rb") as fb:
                if fa.read() == fb.read():
                    os.remove(src)
                    return "%s == %s (identical; legacy removed)" % (rel_s, rel_d)
            if generated:
                os.remove(src)          # re-derivable by construction; canonical wins
                return "%s superseded by %s (generated; canonical kept)" % (rel_s, rel_d)
            if src.endswith(".md"):
                _merge_md(src, dest)
                return "%s merged into %s (stamped heading)" % (rel_s, rel_d)
            alt = dest + ".migrated-duplicate"
            os.rename(src, alt)
            return "%s -> %s (destination occupied; nothing merged)" % (
                rel_s, os.path.relpath(alt, profile))
        if os.path.isdir(src) and os.path.isdir(dest):
            for name in sorted(os.listdir(src)):
                note = _move(os.path.join(src, name), os.path.join(dest, name))
                if note:
                    lines.append("    %s" % note)
            if not os.listdir(src):
                os.rmdir(src)
            return "%s folded into %s" % (rel_s, rel_d)
        raise IOError("%s and %s are different kinds; refusing to guess" % (rel_s, rel_d))

    try:
        # 1) Misfiled application worksheets move FIRST, before the prep dir is renamed.
        for prep_rel in (_tree.rel("call_preps"),) + _tree.LAYOUT["call_preps"][1]:
            d = os.path.join(profile, prep_rel)
            if os.path.isdir(d):
                for name in sorted(os.listdir(d)):
                    if name.startswith(_tree.APPLYING_PATTERN) and name.endswith(".md"):
                        note = _move(os.path.join(d, name),
                                     os.path.join(profile, "applying", name))
                        if note:
                            moved.append(note)

        # 2) The layout table, verbatim.
        generated_keys = {"dashboard_artifact", "dashboard_artifact_url"}
        for key in sorted(_tree.LAYOUT):
            new, legacies = _tree.LAYOUT[key]
            for old in legacies:
                note = _move(os.path.join(profile, old), os.path.join(profile, new),
                             generated=key in generated_keys)
                if note:
                    moved.append(note)

        # 3) Retirement as a move.
        for old, new in sorted(_tree.RETIRED_TO.items()):
            note = _move(os.path.join(profile, old), os.path.join(profile, new))
            if note:
                moved.append(note)

        # 4) Undeclared root variant pages follow the union into presence/.
        for name in sorted(os.listdir(profile)):
            if (name.startswith("resume_") and name.endswith(".md")
                    and os.path.isfile(os.path.join(profile, name))):
                note = _move(os.path.join(profile, name),
                             os.path.join(profile, "presence", name))
                if note:
                    moved.append(note)

        # 5) The unresolved-placeholder directory (#28 item 7).
        junk = os.path.join(profile, "nonexistent")
        if os.path.isdir(junk):
            has_content = any(files for _r, _d, files in os.walk(junk))
            if not apply_it:
                moved.append("nonexistent/ -> %s" % (
                    "removed (only empty directories)" if not has_content
                    else "archive/nonexistent-%s/" % _dt.date.today().isoformat()))
            elif not has_content:
                shutil.rmtree(junk)
                moved.append("nonexistent/ removed (held only empty directories)")
            else:
                note = _move(junk, os.path.join(
                    profile, "archive", "nonexistent-%s" % _dt.date.today().isoformat()))
                if note:
                    moved.append(note)

        # 6) Declared variant pages: rewrite `file` on rows whose target moved.
        vpath = os.path.join(profile, "data", "resume_variants.jsonl")
        if os.path.exists(vpath):
            rows, rewrote = [], 0
            with open(vpath, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    f = row.get("file")
                    # A degenerate single-resume profile may declare the union itself as its
                    # printed page; the union is renamed on the move (resume.md -> claims.md,
                    # ADR-018 settled with public #28), so the row follows the rename too.
                    base = os.path.basename(f) if f else ""
                    base = "claims.md" if base == "resume.md" else base
                    if (f and not os.path.exists(os.path.join(profile, f))
                            and os.path.exists(os.path.join(profile, "presence", base))):
                        row["file"] = "presence/" + base
                        rewrote += 1
                    rows.append(row)
            if rewrote:
                if apply_it:
                    tmp = vpath + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        for row in rows:
                            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    os.replace(tmp, vpath)  # atomic: never a half-written store
                moved.append("data/resume_variants.jsonl: %d file field(s) %s presence/"
                             % (rewrote, "rewritten to" if apply_it else "would follow"))
    except Exception as e:                   # noqa: BLE001 — preserve on ANY miss
        return False, ("  ⚠️ tree migration stopped at: %s. Everything already moved stays "
                       "moved and NOTHING was deleted; scripts resolve both shapes "
                       "(_tree.path), and this retries next session." % e)

    if not moved and not lines:
        return True, ""
    prefix = "  ✅ tree (public #28): " if apply_it else "  would restructure the tree: "
    return True, prefix + "; ".join(moved + lines)
