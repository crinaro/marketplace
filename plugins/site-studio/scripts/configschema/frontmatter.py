"""frontmatter: reading a page file's front matter for the schema checks: its keys, its key/value pairs, the
`labels:` line, and the text of a tree file the caller holds."""

import re


_LABELS_FM_RE = re.compile(r"(?m)^labels:[ \t]*(\S.*)?$")


def _text_of(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else v


def _expanded_file(path):
    """The files the builder token-expands: layouts, `site/src` HTML pages, Markdown bodies."""
    low = path.lower()
    if path.startswith("site/templates/"):
        return True
    if path.startswith("site/src/") and low.endswith((".html", ".htm")):
        return True
    return path.startswith("content/") and low.endswith(".md")


def _page_md_labels(path, text):
    """True when a content/<folder>/page.md front matter carries a non-empty `labels` entry."""
    if not text.startswith("---\n"):
        return False
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        return False
    block = "\n".join(lines[1:end])
    m = _LABELS_FM_RE.search(block)
    if not m:
        return False
    if m.group(1):
        return m.group(1).strip() not in ("{}", "[]", "''", '""')
    # `labels:` alone: non-empty when an indented line follows it
    after = block[m.end():].lstrip("\n").split("\n")
    return bool(after) and after[0][:1] in (" ", "\t") and bool(after[0].strip())


_FM_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):(?:\s|$)")


def front_matter_keys(text):
    """[(key, lineno)] for the top-level keys of a file's front matter (an unreadable block yields what
    was read). Lines are numbered from 1 over the whole file. No front matter yields []."""
    text = _text_of(text).replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return []
    out = []
    for i, line in enumerate(text.split("\n")[1:], 2):
        if line.rstrip() == "---":
            break
        m = _FM_KEY_RE.match(line)
        if m:
            out.append((m.group(1), i))
    return out


_FM_PAIR_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):(?:[ \t]+(.*))?$")


def front_matter_pairs(text):
    """[(key, value text, lineno)] for the top-level `key: value` lines of a file's front matter, the value
    unquoted and stripped (None for a key with nothing after the colon). Same line numbering and tolerance as
    `front_matter_keys`; a nested or list value yields its first line only."""
    text = _text_of(text).replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return []
    out = []
    for i, line in enumerate(text.split("\n")[1:], 2):
        if line.rstrip() == "---":
            break
        m = _FM_PAIR_RE.match(line)
        if m:
            val = (m.group(2) or "").strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            out.append((m.group(1), val or None, i))
    return out
