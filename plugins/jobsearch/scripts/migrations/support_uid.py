"""The tolerant store reader the uid-text family of migrations shares (`_uid_text_read`).

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import json
import os


def _uid_text_read(profile, name):
    """`(rows, raw_lines, error)` for `data/<name>.jsonl` -- strict: ONE line that does not parse (or
    is not an object) is an error naming the store and line, because preserving and then rewriting
    a store this could not fully read would drop that line. An absent store reads as no rows."""
    path = os.path.join(profile, "data", "%s.jsonl" % name)
    if not os.path.exists(path):
        return [], [], None
    rows, raws = [], []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    return None, None, "%s.jsonl line %d is not valid JSON (%s)" % (name, n, exc)
                if not isinstance(row, dict):
                    return None, None, "%s.jsonl line %d is not an object" % (name, n)
                rows.append(row)
                raws.append(line.rstrip("\n"))
    except OSError as exc:
        return None, None, "%s.jsonl cannot be read (%s)" % (name, exc)
    return rows, raws, None
