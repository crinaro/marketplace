"""rewrite.py -- the text edits a move makes: `{{link:<old>/<slug>...}}` tokens and the home page's `featured` and
`showcase` names are rewritten to the new place (design-template-fidelity section 8 A1, issue #877).
"""

import re
import unicodedata


_FRONT_KEYS = ("featured", "showcase")


def nfc(s):
    return unicodedata.normalize("NFC", s)


def link_pattern(old_key):
    """`{{link:<old_key>}}`, `{{link:<old_key>/...}}`, `#` and `?` forms: never a longer name that merely starts
    the same (`harbor-lights-2`)."""
    return re.compile(r"(\{\{\s*link:)" + re.escape(old_key) + r"(?=[/#?]|\s*\}\})")


def rewrite_links(text, old_key, new_key):
    """(new text, count) with every `{{link:<old_key>...}}` pointing at `new_key`."""
    return link_pattern(old_key).subn(lambda m: m.group(1) + new_key, text)


def rewrite_front_names(text, old_key, new_key):
    """(new text, count): the piece name in the `featured` and `showcase` lists of a home page's front matter,
    where `old_key` stands alone (a showcase entry's image path, `media/<old_key>.jpg`, is not a name)."""
    if not text.startswith("---\n"):
        return text, 0
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return text, 0
    name = re.compile(r"(?<![A-Za-z0-9/_.-])" + re.escape(old_key) + r"(?![A-Za-z0-9/_.-])")
    key, total = None, 0
    for i in range(1, end):
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*):", lines[i])
        if m:
            key = m.group(1)
        if key in _FRONT_KEYS:
            lines[i], n = name.subn(new_key, lines[i])
            total += n
    return "\n".join(lines), total


def _decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
