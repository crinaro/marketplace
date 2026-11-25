"""referencelayout.py -- the layout keys of a reference: `project`, `type` and `channel` (schema 9; design-reference-layout sections
1.1 to 1.4; dev 1061). Pure: it reads no file and runs no command. `content.load_content` calls `check` once the pieces and the
references are loaded, and the builder prints through `printed`.

The three keys are each optional and one line of text; `""` or blank reads as absent everywhere (`clean`). `type` and `channel` are at
most `VALUE_MAX` characters after trimming. `project` names a piece (`harbor-lights`, or `<portfolio>/<slug>` when two portfolios hold the
slug) and is checked against the piece folders found in the PATHS of the tree, not against what loaded: a piece the build refuses for
its own reason still counts, so a reference naming it is not refused in consequence, and a draft is a piece. The site's own lists
(`site.json` `references.types` / `channels`) close a value set; `references.unprinted` words are stored and never printed.

Every fault is one `ContentError` with the file and the line of the member, and NONE of them drops the reference: the reference stays
loaded, so no `ref:` line that names it is refused after it (on 0.8.0 an unknown key drops it, and each `ref:` line of it is refused).
A value that is faulted reads as absent to every later reader.

What other steps reuse (each of them states a value rule once, here): `VALUE_MAX`, `ONE_LINE_RE`, `problem` (why a value is not
readable), `clean`, `printed`, `piece_keys` and `resolve` (which piece a `project` names), `member_line` and `near`.
"""
import difflib
import json
import re
import unicodedata

from configschema.configkeys import REFERENCE_UNPRINTED_KEYS, REFERENCE_WORD_MAX, V9_REFERENCE_KEYS
from contentmodel.errors import ContentError
from contentmodel.frontmatter import decode_text, parse_front_matter
from contentmodel.keytables import RESERVED_PORTFOLIO_NAMES

VALUE_MAX = REFERENCE_WORD_MAX                     # the longest `type` or `channel` after trimming (a `project` has no limit)
TEXT_KEYS = REFERENCE_UNPRINTED_KEYS               # ("type", "channel"): the two that print
ONE_LINE_RE = re.compile(r"^[^\r\n]*$")            # the one-line rule, for a reader that matches text (the JSON Schema)
_LISTS = {"type": "types", "channel": "channels"}  # the `site.json` `references` list that closes each


def _nfc(text):
    return unicodedata.normalize("NFC", text)


def problem(key, value):
    """Why `value` cannot be a `key` of a reference, as the words that follow "'<key>' ", or None when it can: it is text, one line
    after trimming, and (for `type` and `channel`) at most `VALUE_MAX` characters. A blank text is readable (it reads as absent)."""
    if not isinstance(value, str):
        return "must be text"
    text = value.strip()
    if not ONE_LINE_RE.match(text):
        return "must be one line of text"
    if key in TEXT_KEYS and len(text) > VALUE_MAX:
        return "is %d characters; at most %d" % (len(text), VALUE_MAX)
    return None


def clean(data, key):
    """The trimmed text of `key` in a reference's data, or None when it is absent, blank or not readable (`problem`)."""
    value = data.get(key)
    if not isinstance(value, str) or problem(key, value) is not None:
        return None
    return value.strip() or None


def printed(data, key, cfg):
    """What a card prints for `type` or `channel`: the trimmed value, or None when it is absent, blank, not readable, or one of the
    site's `references.unprinted` words for the key (compared in NFC). The one place a card decides: the three places that print a
    reference all fill their slots through it."""
    text = clean(data, key)
    if text is None:
        return None
    hidden = ((getattr(cfg, "references", None) or {}).get("unprinted") or {}).get(key, ())
    return None if _nfc(text) in set(_nfc(w) for w in hidden) else text


def piece_keys(paths):
    """The sorted `<portfolio>/<slug>` of every piece folder in `paths`: `content/<portfolio>/<slug>/index.md`, neither folder starting
    `_`, the portfolio not one of the folders that are pages and not pieces (`RESERVED_PORTFOLIO_NAMES`). Read from paths alone."""
    out = set()
    for p in paths:
        parts = p.split("/")
        if (len(parts) == 4 and parts[0] == "content" and parts[3] == "index.md" and parts[1] not in RESERVED_PORTFOLIO_NAMES
                and not parts[1].startswith("_") and not parts[2].startswith("_")):
            out.add("%s/%s" % (parts[1], parts[2]))
    return sorted(out)


def _squash(text):
    return text.lower().replace("-", "")


def near(value, words, cutoff=0.75):
    """The word of `words` a `value` is nearest to: the one that differs only by case or hyphens, else the closest by spelling, else None."""
    same = [w for w in words if _squash(w) == _squash(value)]
    if same:
        return same[0]
    close = difflib.get_close_matches(value, list(words), n=1, cutoff=cutoff)
    return close[0] if close else None


def resolve(value, keys):
    """(piece key, None) when `value` names exactly one piece of `keys` (the output of `piece_keys`); else (None, what), `what` the words
    that follow "'project' " in the refusal. A `<portfolio>/<slug>` names a piece or none; a bare slug names the piece of that slug in
    the one portfolio that has it, and two portfolios holding it is a refusal naming both."""
    if "/" in value:
        if value in keys:
            return value, None
        where, close = "content/%s/index.md" % value, near(value, keys)
    else:
        held = [k for k in keys if k.partition("/")[2] == value]
        if len(held) == 1:
            return held[0], None
        if held:
            return None, "names pieces in %d portfolios (%s)" % (len(held), " and ".join(held))
        where, close = "content/*/%s/index.md" % value, near(value, sorted(set(k.partition("/")[2] for k in keys)))
    return None, "names no piece (there is no %s%s)" % (where, "; the closest is '%s'" % close if close else "")


def member_line(text, key):
    """The 1-based line where the top-level member `key` of the JSON object in `text` is written, or None. A scan of the text
    (strings and nesting are skipped, so the word inside a value is not a member)."""
    depth, i, n, line = 0, 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        elif c == '"':
            start, start_line = i, line
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                if i < n and text[i] == "\n":
                    line += 1
                i += 1
            if depth == 1:
                after = text[i + 1:].lstrip()
                if after.startswith(":"):
                    try:
                        name = json.loads(text[start:i + 1])
                    except ValueError:
                        name = None
                    if name == key:
                        return start_line
        i += 1
    return None


def _fault(rj, text, key, what, fix):
    line = member_line(text, key)
    return ContentError("%s%s: %s" % (rj, ":%d" % line if line else "", what), path=rj, lineno=line, fix=fix)


def _is_draft(content, files, key):
    """Does the piece `key` say `draft: true`? Read from the loaded piece, else from its own front matter (a draft is not loaded
    unless the build asks for drafts); a piece whose front matter cannot be read is not a draft, it is refused for its own reason."""
    piece = content.piece(key)
    if piece is not None:
        return bool(piece.draft)
    path = "content/%s/index.md" % key
    try:
        meta, _body = parse_front_matter(decode_text(files[path], path), path)
    except (ContentError, KeyError):
        return False
    return meta.get("draft") is True


def check(files, paths, content, cfg):
    """The faults of the layout keys of every loaded reference, as a list of `ContentError` (empty below schema 9, where the keys are
    refused as unknown before this runs), in the order of the references' names then the keys'. Sets `ref.project` (the piece key a
    valid `project` names) and `ref.project_draft` on each reference that has one. A faulted value reads as absent from then on."""
    if cfg.schema < 9:
        return []
    faults, keys = [], piece_keys(paths)
    lists = getattr(cfg, "references", None) or {}
    for name in sorted(content.references):
        ref = content.references[name]
        rj = "content/references/%s/reference.json" % name
        text = decode_text(files[rj], rj)
        for key in V9_REFERENCE_KEYS:
            if key not in ref.data:
                continue
            bad = problem(key, ref.data[key])
            if bad:
                faults.append(_fault(rj, text, key, "'%s' %s" % (key, bad),
                                     "write %s as one line of text, or remove it" % key))
                continue
            value = clean(ref.data, key)
            if value is None:
                continue
            if key == "project":
                found, why = resolve(value, keys)
                if found is None:
                    faults.append(_fault(rj, text, key, "'project' %s" % why,
                                         "write project as a piece's folder name, or as <portfolio>/<slug> when two portfolios hold "
                                         "the name, or remove it"))
                else:
                    ref.project, ref.project_draft = found, _is_draft(content, files, found)
                continue
            words = lists.get(_LISTS[key])
            if words and _nfc(value) not in set(_nfc(w) for w in words):
                close = near(value, words)
                faults.append(_fault(rj, text, key, "'%s' %r is not one of the site's references.%s (%s)%s"
                                     % (key, value, _LISTS[key], ", ".join(words), "; did you mean '%s'?" % close if close else ""),
                                     "use one of the listed words, or add %r to references.%s in site/site.json"
                                     % (value, _LISTS[key])))
    return faults
