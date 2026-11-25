"""rewrite.py -- the text edits a move makes: `{{link:<old>/<slug>...}}` tokens and the home page's `featured` and
`showcase` names are rewritten to the new place (design-template-fidelity section 8 A1, issue #877).
"""

import json
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


_PROJECT_MEMBER = re.compile(r'("project"\s*:\s*)"(?:[^"\\]|\\.)*"')
_REFERENCE_JSON = re.compile(r"^content/references/[^/]+/reference\.json$")


def is_reference_json(path):
    return bool(_REFERENCE_JSON.match(path))


def rewrite_project(text, old_key, new_key):
    """(new text, count): a `reference.json` whose `project` is the piece `old_key` (`<portfolio>/<slug>`, trimmed) now says `new_key`
    (schema 9, design-reference-layout section 1.2). Only that value changes: the result is re-parsed and must equal the old data with
    the one member replaced, in the same order, or the text is returned as it was (`adoption/template._renamed_only`'s method). A bare
    slug is no `old_key` and needs no rewrite."""
    try:
        data = json.loads(text)
    except ValueError:
        return text, 0
    if not isinstance(data, dict) or not isinstance(data.get("project"), str) or data["project"].strip() != old_key:
        return text, 0
    new_text, n = _PROJECT_MEMBER.subn(lambda m: m.group(1) + json.dumps(new_key), text, count=1)
    try:
        got = json.loads(new_text)
    except ValueError:
        return text, 0
    want = dict(data, project=new_key)
    if n != 1 or got != want or list(got) != list(want):
        return text, 0
    return new_text, 1


def _decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
