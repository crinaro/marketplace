"""A per-piece value is never a look's literal: the check on the text a derived template writes itself (dev 941, criterion D1).

A template holds words it writes itself (a fixed heading, a class name) and slots that the page's own data fills. A construct whose
instances each carry their own data (a piece's page, a card, a reference card) has no business writing one instance's value as a fixed
word: the look would print it on EVERY instance's page (one piece's teaser under another piece's title). When only one instance of the
construct could be read, nothing in the pages says the word varies, so the data itself is asked: a word of the template that is a value
of the site's own pieces and not one every piece shares is a per-piece value, and the construct is not derived (a construct the look
does not carry is built by the plugin's own markup, and `adoption.choose` then judges what that loses).

The same holds in a construct of ONE instance (step 5c-4, measured on `template-movement-e`): a home page whose shelf of piece tiles is
written into `home.wrap` as fixed markup is EQUAL on the day the look is made and stale once a piece changes, so derive asks every
construct, not only `PER_ITEM`'s; `why_fixed` words the two reasons.

`content_values(files)` is the site's per-piece values; `literal_hits(template, values)` the words of one template that are among them.
All are pure; none reads a file.
"""

import re

from contentmodel import frontmatter
from contentmodel.errors import ContentError

PER_ITEM = ("piece", "card", "reference-card")      # the constructs each of whose instances carries its own data
_PIECE = re.compile(r"^content/[^/_][^/]*/[^/_][^/]*/(?:index|[a-z0-9-]+)\.md$")
_TAG = re.compile(r"<[^>]*>")
_ATTR = re.compile(r"\b(?:alt|title|aria-label)=\"([^\"]*)\"")
_SLOT = re.compile(r"\{\{[a-z][A-Za-z0-9]*\}\}")


def _squash(s):
    return " ".join(s.split())


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for v in value:
            for s in _strings(v):
                yield s
    elif isinstance(value, dict):
        for v in value.values():
            for s in _strings(v):
                yield s


def content_values(files):
    """The strings of the pieces' front matter that belong to SOME pieces and not to all: `{squashed value}`. A value every piece
    carries (a constant a template may write itself) is left out when there are two pieces or more. `files` is `{path: bytes or str}`
    (the converted tree); a front matter this module cannot read is skipped (the build says why it is refused, not this check)."""
    per_piece = []
    for path in sorted(files):
        if not _PIECE.match(path) or path.endswith("/page.md") or path.startswith("content/references/"):
            continue
        blob = files[path]
        text = blob.decode("utf-8", "replace") if isinstance(blob, bytes) else blob
        try:
            meta, _body = frontmatter.parse_front_matter(text.replace("\r\n", "\n"), path)
        except ContentError:
            continue
        per_piece.append(set(_squash(s) for s in _strings(meta) if re.search(r"[A-Za-z]", s)))
    out = set()
    for vals in per_piece:
        for v in vals:
            if len(per_piece) < 2 or sum(1 for p in per_piece if v in p) < len(per_piece):
                out.add(v)
    return out


def literal_texts(template):
    """The words a template writes itself: its text between tags with the slots taken out, and the alt, title and aria-label of its
    elements, each squashed and holding a letter."""
    out = []
    for m in _ATTR.finditer(template):
        out.append(m.group(1))
    text = _TAG.sub("\x00", template)
    for chunk in re.split(r"\x00", text):
        out.extend(_SLOT.split(chunk))
    return [t for t in (_squash(x) for x in out) if re.search(r"[A-Za-z]", t)]


def why_fixed(construct):
    """derive's reason for not mapping a `construct` whose template writes a piece's own value as fixed text: in a construct of many
    instances (`PER_ITEM`) the value would print on every instance's page; in any other (the home page's shelf, step 5c-4) it would
    stay as it was when the look was made, whatever the piece says later."""
    if construct in PER_ITEM:
        return "this template writes a value of one piece's own data as fixed text"
    return "this template writes a value of a piece's own data as fixed text, which would not follow the piece"


def literal_hits(template, values):
    """The words `template` writes itself that are per-piece values (among `values`), sorted, each once."""
    return sorted(set(t for t in literal_texts(template) if t in values))
