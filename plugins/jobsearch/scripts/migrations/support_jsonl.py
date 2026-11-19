"""JSONL helpers two or more migrations share: read, rewrite, and the tolerant asks reader.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import json
import os


def _rewrite_jsonl(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)               # atomic: never a half-written store


def _read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_asks_tolerant(path):
    """(rows, error) — `error` is a plain-words reason when the file exists and cannot be read."""
    if not os.path.exists(path):
        return [], None
    try:
        return _read_jsonl(path), None
    except (OSError, ValueError) as e:
        return None, "%s: %s" % (type(e).__name__, e)
