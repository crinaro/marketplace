"""docx_match: which paragraphs of a person's Word file are header, and how the rest align with the md's blocks
(design-resume-docx.md §4.2, §4.3, §R2 S2-4 and S2-5, O28; B10).

**Identity** (`identity`, `identity_hits`). The md holds no header; the default render composes name, phone and
email from `user.json`. *Name and email* are compared after `fold`: NFKC, then U+2018, U+2019 and U+02BC become
`'`, U+201C and U+201D become `"`, U+2010 to U+2015 become `-`, then `casefold()` and whitespace collapse; the
paragraph must contain the folded value. *Phone*: every match of `PHONE_RE` in the paragraph is a candidate; the
candidate and the stored phone are reduced to digits with leading zeros dropped, and they match when the shorter is
a suffix of the longer and has at least 7 digits (the national significant number, with or without a country code
or a trunk zero). O28: a header holds the name and at least one of the email and the phone (`identity_ok`).

**A contact-only paragraph** is header wherever it sits: never aligned, so never edited or taken back. It is one
with no letter or digit left once its email-shaped tokens and phone candidates are removed. OURS, narrower than
§4.3's words: at least one removed token must be an email or a candidate matching the stored phone, so a line that
is only a date range (`2019 - 2023`, which the phone pattern also matches) stays resume text.

**The header zone** is every paragraph from the top through the last of the first ten non-empty paragraphs that
holds the name, the phone or the email, and it never reaches a paragraph whose comparison text equals an md block:
it ends before the first such paragraph.

**Alignment.** Below the zone, the non-empty, non-contact paragraphs (their `comparison_text`, the leading bullet
glyph dropped) are aligned to the md's blocks (`parse_variant_blocks` text) by
`difflib.SequenceMatcher(None, word, md, autojunk=False).get_opcodes()`. In a `replace` span, paragraphs and blocks
of one type (heading, bullet or paragraph; a Word paragraph typed as `resume_import._paragraph` types it, a style
`heading_styles` resolves as a heading counting too) are paired best-first by `ratio()` at `PAIR_RATIO` or above.
OURS: a pair that would cross one already taken is skipped, so a pairing never reorders the file. An unpaired
paragraph is to be deleted and an unpaired block inserted; what the edit does with each is `docx_update`'s (B11).
An md block that is contact-only is left out on the md side too, symmetric with the Word side.

Capability module; nothing here reads or writes a file. Python 3.9+, standard library only."""

import difflib
import re
import unicodedata

from presence.docx_scan import comparison_text
from presence.resume_import import GLYPH_RE, HEADING_RE

PAIR_RATIO = 0.6
ZONE_SCAN = 10                      # the first ten non-empty paragraphs hold the header
PHONE_MIN_DIGITS = 7                # the national significant number's shortest accepted length
PHONE_RE = re.compile(r"[+(]?\d[\d ().\-/]{5,}\d")
EMAIL_RE = re.compile(r"[\w.+%'-]+@[\w-]+(?:\.[\w-]+)+")
_FOLD = {0x2018: "'", 0x2019: "'", 0x02BC: "'", 0x201C: '"', 0x201D: '"',
         0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2015: "-"}
KINDS = ("heading", "bullet", "paragraph")


# ---------------------------------------------------------------- identity

def fold(s):
    """`s` as identity is compared (§R2 S2-5): NFKC, apostrophes, quotes and hyphens folded, casefolded, whitespace
    collapsed."""
    s = unicodedata.normalize("NFKC", s or "").translate(_FOLD).casefold()
    return " ".join(s.split())


def phone_digits(s):
    """The digits of `s`, leading zeros dropped (a trunk zero, or the `00` of an international prefix)."""
    return "".join(ch for ch in (s or "") if ch.isdigit()).lstrip("0")


def phone_matches(candidate, stored):
    """True when the shorter digit string is a suffix of the longer and holds at least `PHONE_MIN_DIGITS` digits."""
    a, b = phone_digits(candidate), phone_digits(stored)
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= PHONE_MIN_DIGITS and long_.endswith(short)


def phone_candidates(text):
    """Every run of `text` shaped like a phone number, in order."""
    return [m.group(0) for m in PHONE_RE.finditer(text or "")]


def identity(user):
    """{"name", "email", "phone"} from `user.json`'s dict (`identity.full_name`, `primary_email`, `phone`); a missing
    field is ""."""
    ident = (user or {}).get("identity", {}) or {}
    return {"name": (ident.get("full_name") or "").strip(),
            "email": (ident.get("primary_email") or "").strip(),
            "phone": (ident.get("phone") or "").strip()}


def identity_hits(text, ident):
    """{"name": bool, "email": bool, "phone": bool}: which identity fields the paragraph `text` holds."""
    folded = fold(text)
    name, email = fold(ident.get("name")), fold(ident.get("email"))
    phone = ident.get("phone") or ""
    return {"name": bool(name) and name in folded,
            "email": bool(email) and email in folded,
            "phone": bool(phone_digits(phone)) and any(phone_matches(c, phone) for c in phone_candidates(text))}


def identity_ok(hits):
    """O28: the name and at least one of the email and the phone."""
    return bool(hits.get("name")) and bool(hits.get("email") or hits.get("phone"))


def identity_in(texts, ident):
    """The union of `identity_hits` over `texts` (the first ten body paragraphs, a page-header part)."""
    out = {"name": False, "email": False, "phone": False}
    for t in texts:
        for k, v in identity_hits(t, ident).items():
            out[k] = out[k] or v
    return out


def contact_only(text, ident):
    """True when nothing but separators is left of `text` once its email-shaped tokens and phone candidates are
    removed, and at least one removed token was an email or the stored phone (see the module docstring)."""
    if not text:
        return False
    emails = EMAIL_RE.findall(text)
    rest = EMAIL_RE.sub(" ", text)
    phones = phone_candidates(rest)
    rest = PHONE_RE.sub(" ", rest)
    if any(ch.isalnum() for ch in rest):
        return False
    stored = ident.get("phone") or ""
    return bool(emails) or any(phone_matches(p, stored) for p in phones)


# ---------------------------------------------------------------- types

def word_kind(paragraph, heading_styles=None):
    """("heading", level) | ("bullet", depth) | ("paragraph", None) for a scanned paragraph, typed as
    `resume_import._paragraph` types it. `heading_styles` ({styleId: level}, from `docx_ats.heading_styles`) adds the
    styles `word/styles.xml` names as headings, so a localized styleId types as a heading too."""
    style = paragraph.style or ""
    if heading_styles and style in heading_styles:
        return "heading", heading_styles[style]
    m = HEADING_RE.match(style)
    if m or style == "Title":
        return "heading", int(m.group(1)) if m else 1
    if paragraph.listed or style.startswith("List") or GLYPH_RE.match(paragraph.text):
        return "bullet", paragraph.ilvl or 0
    return "paragraph", None


def md_kind(block):
    """("heading", level) | ("bullet", depth) | ("paragraph", None) of a `parse_variant_blocks` block; a bullet
    indented two or more spaces is depth 1, as the default render indents it."""
    t = block["type"]
    if t == "heading":
        return "heading", block["level"]
    if t == "bullet":
        return "bullet", 1 if block.get("indent", 0) >= 2 else 0
    return "paragraph", None


def word_text(paragraph):
    """The text a Word paragraph is compared by (§4.2): its text with a leading bullet glyph dropped."""
    return comparison_text(paragraph.text)


# ---------------------------------------------------------------- the header zone

def header_zone(paragraphs, ident, md_texts):
    """The number of paragraphs, from the top, in the header zone (§4.3)."""
    nonempty = [p for p in paragraphs if p.text][:ZONE_SCAN]
    holders = [p.index for p in nonempty if any(identity_hits(p.text, ident).values())]
    if not holders:
        return 0
    end = holders[-1] + 1
    md_set = set(md_texts)
    for p in paragraphs[:end]:
        if p.text and word_text(p) in md_set:
            return p.index
    return end


# ---------------------------------------------------------------- alignment

class Span:
    """One opcode of the alignment, in paragraph and block indices: `pairs` [(paragraph, block, ratio)] are the
    paragraphs whose text is (or is to be made) that block's; `deleted` paragraphs have no block, `inserted` blocks
    no paragraph."""

    __slots__ = ("tag", "word", "md", "pairs", "deleted", "inserted")

    def __init__(self, tag, word, md):
        self.tag = tag
        self.word = word
        self.md = md
        self.pairs = []
        self.deleted = []
        self.inserted = []

    def __repr__(self):
        return "<Span %s word=%r md=%r pairs=%r>" % (self.tag, self.word, self.md, self.pairs)


class Alignment:
    """The result of `align`: `zone` (paragraph indices of the header zone), `contact` (contact-only paragraphs below
    it), `md_contact` (contact-only blocks, left out), `empty` (empty paragraphs below the zone), `spans`."""

    def __init__(self, zone, contact, md_contact, empty, spans):
        self.zone = zone
        self.contact = contact
        self.md_contact = md_contact
        self.empty = empty
        self.spans = spans

    @property
    def header(self):
        """Every paragraph read as header: the zone and each contact-only paragraph, in order."""
        return sorted(self.zone + self.contact)

    @property
    def all_equal(self):
        """True when every aligned span is `equal`: the Word file's words are the md's."""
        return all(s.tag == "equal" for s in self.spans)

    def matched(self):
        """[(paragraph index, block index)] of every equal or paired span member, in order."""
        out = []
        for s in self.spans:
            out.extend((w, m) for w, m, _r in s.pairs)
        return out


def pair_replace(word_items, md_items, threshold=PAIR_RATIO):
    """Best-first pairing inside one `replace` span. `word_items` and `md_items` are [(index, kind, text)]; returns
    [(word index, md index, ratio)] in word order. Only one kind pairs with itself, at `threshold` or above; a pair
    crossing one already taken is skipped."""
    scored = []
    for wi, (wx, wk, wt) in enumerate(word_items):
        for mi, (mx, mk, mt) in enumerate(md_items):
            if wk != mk:
                continue
            r = difflib.SequenceMatcher(None, wt, mt, autojunk=False).ratio()
            if r >= threshold:
                scored.append((-r, wi, mi))
    scored.sort()
    taken = []
    used_w, used_m = set(), set()
    for neg, wi, mi in scored:
        if wi in used_w or mi in used_m:
            continue
        if any((wi - a) * (mi - b) < 0 for a, b, _r in taken):
            continue
        taken.append((wi, mi, -neg))
        used_w.add(wi)
        used_m.add(mi)
    taken.sort()
    return [(word_items[wi][0], md_items[mi][0], r) for wi, mi, r in taken]


def _span(tag, w_items, m_items):
    sp = Span(tag, [x[0] for x in w_items], [x[0] for x in m_items])
    if tag == "equal":
        sp.pairs = [(a[0], b[0], 1.0) for a, b in zip(w_items, m_items)]
    elif tag == "delete":
        sp.deleted = list(sp.word)
    elif tag == "insert":
        sp.inserted = list(sp.md)
    else:
        sp.pairs = pair_replace(w_items, m_items)
        paired_w = {p[0] for p in sp.pairs}
        paired_m = {p[1] for p in sp.pairs}
        sp.deleted = [i for i in sp.word if i not in paired_w]
        sp.inserted = [j for j in sp.md if j not in paired_m]
    return sp


def align(paragraphs, blocks, ident, heading_styles=None):
    """Align a scan's `paragraphs` with an md's `blocks` (§4.3). Returns an `Alignment`."""
    md_contact = [j for j, b in enumerate(blocks) if contact_only(b["text"], ident)]
    m_items = [(j, md_kind(b)[0], b["text"]) for j, b in enumerate(blocks) if j not in md_contact]
    n_zone = header_zone(paragraphs, ident, [t for _j, _k, t in m_items])
    zone = list(range(n_zone))
    contact, empty, w_items = [], [], []
    for p in paragraphs[n_zone:]:
        if not p.text:
            empty.append(p.index)
        elif contact_only(p.text, ident):
            contact.append(p.index)
        else:
            w_items.append((p.index, word_kind(p, heading_styles)[0], word_text(p)))
    sm = difflib.SequenceMatcher(None, [x[2] for x in w_items], [x[2] for x in m_items], autojunk=False)
    spans = [_span(tag, w_items[i1:i2], m_items[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes()]
    return Alignment(zone, contact, md_contact, empty, spans)
