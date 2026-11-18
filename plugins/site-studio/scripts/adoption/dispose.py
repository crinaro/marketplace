"""adoption.dispose -- carry out the dispositions in the converted tree: archive the unused, mark the work in progress as draft
(design 8 FA rules 7 and 8; design 3.5 `archive/ARCHIVE.json`; step 1.9r).

Part of the `adoption` package behind the entry point `adopt.py`. The accounting (`adoption.accounting`, `adoption.fileacct`)
decides; this module writes, into the same overlay the other conversion classes write into, so P2 judges the tree apply WILL
commit: "the `archive` and `draft` classes are then applied and measured like every class" (FA step 5).

  archived   the file moves to `archive/<path>` (a leading `.claude/` segment as `_claude/`), nothing is deleted; one row in
             `archive/ARCHIVE.json` (`from`, `disposition: archived`, `rule`: `person` when the person chose it, else `unused`)
  draft      a piece's `index.md` gains `draft: true` (the one draft key); the piece FOLDER is the unit, so every other file in
             it stays where it is; no file is renamed (the `_` rename is withdrawn, Q1.3)
  published, kept, engine, no-landing, undisposed   nothing happens here (engine files move only after the publish)

A basis path that a conversion renamed (`work.md` to `index.md`, `home.md` to `index.md`, the resume PDF) is read under its
converted name, so what is archived or drafted is the file the build would have used. Existing `ARCHIVE.json` rows are kept.
"""

from adoption.accounting import ARCHIVE_REL, archive_path, dump_archive, is_piece_index, parse_archive


def conv_name(path, notes):
    """The name a basis path has in the converted tree (a renamed piece, page file or resume PDF)."""
    for old, new in list(notes.get("pieces") or []) + list(notes.get("pageFiles") or []) + list(notes.get("resumePdfName") or []):
        if old == path:
            return new
    return path


def set_draft(blob):
    """The piece text with `draft: true` as the first front-matter key (a file with no front matter gets one)."""
    text = blob.decode("utf-8", "replace")
    if text.startswith("---\n"):
        head, _sep, rest = text[4:].partition("\n---")
        lines = [l for l in head.split("\n") if not l.startswith("draft:")]
        return ("---\ndraft: true\n" + "\n".join(lines) + ("\n" if lines and lines[-1] else "") + "---" + rest).encode("utf-8")
    return ("---\ndraft: true\n---\n" + text).encode("utf-8")


def apply_dispositions(view, files, gone, notes, dispositions, persons=None, rename=None):
    """Write the archive moves and draft keys into `files` (the overlay dict), hide the moved names in `gone`, and say what was
    done in `notes["archived"]` ([(from, to)]), `notes["drafted"]` ([piece index.md]) and `notes["archiveRows"]` (rows).
    `dispositions` is {basis path: [disposition, why]}; `persons` {path: choice} marks `rule: person`; `rename(path)` is the
    converted name of a basis path."""
    rename = rename or (lambda p: p)
    persons = persons or {}
    rows = []
    if view.exists(ARCHIVE_REL):
        rows = list(parse_archive(view.text(ARCHIVE_REL)))
    have = set(r["from"] for r in rows)
    notes["archived"], notes["drafted"] = [], []
    for path in sorted(dispositions):
        disp = dispositions[path][0]
        conv = rename(path)
        if disp == "archived" and not path.startswith("archive/") and path not in have:
            if not view.exists(conv):
                continue
            dest = archive_path(path)
            files[dest] = view.read(conv)
            gone.add(conv)
            files.pop(conv, None)
            rows.append({"from": path, "disposition": "archived", "rule": "person" if persons.get(path) == "archive" else "unused"})
            notes["archived"].append((path, dest))
        elif disp == "draft" and is_piece_index(conv) and view.exists(conv):
            files[conv] = set_draft(view.read(conv))
            notes["drafted"].append(conv)
    notes["archiveRows"] = rows
    if notes["archived"]:
        files[ARCHIVE_REL] = dump_archive(rows).encode("utf-8")
