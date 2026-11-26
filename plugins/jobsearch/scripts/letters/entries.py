"""Parse a cover-letters file into entries, and read an entry's two named lines (jobsearch 0.95.0; dev 1073, 1071; design § 7).

Pure functions over text. No file is read here, no profile is touched.

**The entry.** `parse_entries(text, full_name="")` splits on `## ` exactly as `dashboard/drafts.py::parse_drafts` does (the same
regex), drops the `⚠️ Questions that would sharpen` section, and returns `Entry` objects in file order:

* `heading`      the `## ` title, stripped.
* `raw`          the entry's text from the heading through the line before the next `## `; what `_entry_status.is_closed` reads.
* `meta`         `(label, value, continued)` for every non-quoted line shaped `**Label:** value`; `continued` is true when the
                 next line is stray prose that would fold the value onto a second line (the two named lines must be one line).
* `quote_paragraphs`  every `> `-quoted paragraph, in order, split as `parse_drafts` splits a quote run: a bare `>`, a blank
                 line, or any other non-quote line ends one. A paragraph is its lines joined by `\\n`.
* `header`, `signoff`, `paragraphs`  the counted body. A leading **header block** (the first paragraph, when it contains
                 `full_name`; the rule `letter_out.render()` uses) and a trailing **sign-off** (the last paragraph, when it has
                 six words or fewer) are set aside; `paragraphs` is what is left, and `P1` is its first item.
* `has_body`     any non-blank quoted paragraph. `body_text` is every quoted paragraph (header and sign-off included) joined by
                 blank lines: the text word counts and banned characters are measured on, as `letter_out.check_text` did.

**The two lines** (§ 7.1). `read_purpose(entry)` and `read_needs(entry)` return a `LineRead`:
`state` is `"missing"`, `"marker"` (the migration's marker, § 9.1), `"ok"` or `"error"`. `text` is the purpose sentence;
`items` is the needs as `[(need_text, n)]`; `error` is a `LineError` with a stable `code`, the offending `token`, and a message.
Codes: `empty` (a purpose with no value), `duplicate` (the label twice), `continued` (the value runs onto a
second line), `no-items` (a needs line with no value, or no need after splitting on `;`), `empty-item`, `bad-item` (not `<text> -> P<n>`), `p0` (paragraphs
count from P1). Labels are matched case-insensitively; `->` and `→` are both accepted.

**The marker pair** is recognised exactly as § 7.1 spells it: `**Purpose:** unrecorded (drafted before 0.95.0)` and
`**Needs:** unrecorded`, each judged on its own line (the migration inserts only the line an entry lacks). Whether a marker is
legitimate depends on the migration's record, which `letters/check.py` holds.

**Defaults are notes, never parse errors** (§ 5.3, § 7.1): `purpose_note(text)` (8 to 45 words) and `needs_note(items)` (2 to 5
items) return a message or None; `missing_paragraphs(items, count)` lists the needs whose `P<n>` the body lacks.

Standard library only; imports nothing of the plugin. Python 3.9+.
"""

import re

QUESTIONS_MARK = "questions that would sharpen"
SIGNOFF_MAX_WORDS = 6
PURPOSE_WORDS = (8, 45)
NEEDS_COUNT = (2, 5)
PURPOSE_MARKER = "unrecorded (drafted before 0.95.0)"
NEEDS_MARKER = "unrecorded"

_ENTRY_RE = re.compile(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", re.M | re.S)
_META_RE = re.compile(r"^\*\*([^*:]+):\*\*\s*(.*)$")
_ITEM_RE = re.compile(r"^(.+?)\s*(?:->|→)\s*P(0|[1-9][0-9]*)$")
_RULES = ("---", "***", "___")


class Entry(object):
    """One cover-letters entry; see the module docstring for the fields."""

    def __init__(self, heading, raw, meta, quote_paragraphs, header, signoff, paragraphs):
        self.heading = heading
        self.raw = raw
        self.meta = meta
        self.quote_paragraphs = quote_paragraphs
        self.header = header
        self.signoff = signoff
        self.paragraphs = paragraphs

    @property
    def has_body(self):
        return any(p.strip() for p in self.quote_paragraphs)

    @property
    def body_text(self):
        return "\n\n".join(self.quote_paragraphs)

    def values(self, label):
        """[(value, continued)] for every meta line carrying `label` (case-insensitive), in order."""
        want = label.strip().lower()
        return [(v, c) for (lb, v, c) in self.meta if lb.strip().lower() == want]


class LineError(object):
    """A named refusal: a stable `code`, the `token` that could not be read, and a one-line `message`."""

    def __init__(self, code, token, message):
        self.code = code
        self.token = token
        self.message = message

    def __str__(self):
        return self.message


class LineRead(object):
    """The reading of one named line: `state` missing | marker | ok | error, with `text`, `items` or `error` set."""

    def __init__(self, state, text=None, items=None, error=None):
        self.state = state
        self.text = text
        self.items = items if items is not None else []
        self.error = error


def _quote_paragraphs(lines):
    """`parse_drafts`' quote-run split, over a whole entry: the paragraphs of every `>` run, in order."""
    paras, cur = [], []
    for raw in lines:
        if raw.strip().startswith(">"):
            text = raw.lstrip()[1:].lstrip()
            if text.strip():
                cur.append(text)
                continue
        if cur:
            paras.append("\n".join(cur))
            cur = []
    if cur:
        paras.append("\n".join(cur))
    return paras


def _is_prose(line):
    """True for a line that `parse_drafts` would file as stray prose after a meta line."""
    s = line.strip()
    return bool(s) and not s.startswith((">", "**", "###")) and s not in _RULES


def _meta_lines(lines):
    out = []
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith(">"):
            continue
        m = _META_RE.match(s)
        if not m:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        out.append((m.group(1).strip(), m.group(2).strip(), _is_prose(nxt)))
    return out


def counted_paragraphs(paragraphs, full_name):
    """(header, signoff, counted): set aside a leading header block and a trailing sign-off of six words or fewer."""
    paras = list(paragraphs)
    name = (full_name or "").strip()
    header = signoff = None
    if paras and name and name in paras[0]:
        header = paras.pop(0)
    if paras and len(paras[-1].split()) <= SIGNOFF_MAX_WORDS:
        signoff = paras.pop()
    return header, signoff, paras


def parse_entries(text, full_name=""):
    """Entries of a cover-letters file, minus the Questions section, in file order. `text` None or empty gives []."""
    out = []
    for m in _ENTRY_RE.finditer(text or ""):
        heading, body = m.group(1).strip(), m.group(2)
        if QUESTIONS_MARK in heading.lower():
            continue
        lines = body.splitlines()
        quote = _quote_paragraphs(lines)
        header, signoff, counted = counted_paragraphs(quote, full_name)
        out.append(Entry(heading, m.group(0), _meta_lines(lines), quote, header, signoff, counted))
    return out


def _single(entry, label):
    """(value, continued, error) for a label that must appear once; (None, False, None) when absent."""
    found = entry.values(label)
    if not found:
        return None, False, None
    if len(found) > 1:
        return None, False, LineError("duplicate", "**%s:**" % label,
                                      "**%s:** appears %d times; keep one line" % (label, len(found)))
    return found[0][0], found[0][1], None


def read_purpose(entry):
    """The `**Purpose:**` line: missing, the marker, one non-empty sentence, or a named error."""
    value, continued, err = _single(entry, "Purpose")
    if err:
        return LineRead("error", error=err)
    if value is None:
        return LineRead("missing")
    if continued:
        return LineRead("error", error=LineError("continued", value[:40],
                        "**Purpose:** runs onto a second line; it is one sentence on one line"))
    if value == PURPOSE_MARKER:
        return LineRead("marker", text=value)
    if not value:
        return LineRead("error", error=LineError("empty", "", "**Purpose:** is empty"))
    return LineRead("ok", text=value)


def parse_need_items(value):
    """([(need_text, n)], None) or (None, LineError) for the value of a `**Needs:**` line (not the marker)."""
    parts = [p.strip() for p in value.split(";")]
    if not value.strip():
        return None, LineError("no-items", "", "**Needs:** has no items")
    items = []
    for i, part in enumerate(parts, 1):
        if not part:
            return None, LineError("empty-item", "item %d" % i, "**Needs:** item %d is empty" % i)
        m = _ITEM_RE.match(part)
        if not m:
            return None, LineError("bad-item", part, "**Needs:** cannot read \"%s\" (want \"<need> -> P<n>\")" % part)
        if int(m.group(2)) == 0:
            return None, LineError("p0", part, "**Needs:** \"%s\" cites P0 (paragraphs count from P1)" % part)
        items.append((m.group(1).strip(), int(m.group(2))))
    return items, None


def read_needs(entry):
    """The `**Needs:**` line: missing, the marker, `[(need, n)]`, or a named error."""
    value, continued, err = _single(entry, "Needs")
    if err:
        return LineRead("error", error=err)
    if value is None:
        return LineRead("missing")
    if continued:
        return LineRead("error", error=LineError("continued", value[:40],
                        "**Needs:** runs onto a second line; the items go on one line, separated by `;`"))
    if value == NEEDS_MARKER:
        return LineRead("marker", text=value)
    items, perr = parse_need_items(value)
    if perr:
        return LineRead("error", error=perr)
    return LineRead("ok", items=items)


def purpose_note(text):
    """A note when the purpose is outside the default 8 to 45 words, else None. Never an error."""
    n = len(text.split())
    lo, hi = PURPOSE_WORDS
    if n < lo or n > hi:
        return "**Purpose:** %d words (the default is %d to %d)" % (n, lo, hi)
    return None


def needs_note(items):
    """A note when the needs number fewer than 2 or more than 5, else None. Never an error."""
    lo, hi = NEEDS_COUNT
    if len(items) < lo or len(items) > hi:
        return "**Needs:** %d item%s (the default is %d to %d)" % (len(items), "" if len(items) == 1 else "s", lo, hi)
    return None


def missing_paragraphs(items, count):
    """The `(need_text, n)` items citing a paragraph the body does not have (`count` counted paragraphs)."""
    return [(t, n) for (t, n) in items if n > count]
