"""reportcause.suggestion -- a look suggestion's id, its closed body and the grammar check of that body (design-adopt-ownership-line
sections 13.4 and 13.5; round 2, M3, M4 and M6; the owner's answer to O-5).

Imported by `adoption/suggestions.py` only, never by `report_issue.py`, so `doctor.py --hook` (which imports `report_issue`) still
imports no look code.

THE ID. `ss-look/<kind>/<construct>/h<8 hex>`: `kind` is derive, pattern or markup; `construct` a member of `looks.CONSTRUCTS`
(a named construct files under its `like`); the digest the first 8 hex of the sha256 of the fragment, after an `h` so an
all-digit digest never reads as "a bare 6+ digit number" to the shapes scan. Two sites with the same fragment get the same id.

THE BODY. One fixed line per field (`BODY`), the fragment in one fenced block, then the footer blocker reports carry. No line is
free text: every value is an enumeration member, a whole number, a version, a short commit or a grammar name, and the block is the
canonical text of a template look. `format_body` fills it with NO check (the tests plant through it); `line_problems` is grammar
layer 1 of `report_issue.leak_problems(lines=...)`; `vocabulary` is what the site-terms layer exempts.

    parse_id(sid)                         (kind, construct, digest) or raises SuggestionError
    format_body(fields)                   the body text, unchecked
    line_problems(title, body)            [(layer, why, found)]: layer 1, the grammar
    vocabulary()                          the words this body may print that are no site's
    digest_of(title, body)                the 12 hex `--digest` takes
"""

import hashlib
import json
import re

import looks
from lookfiles import strip
from lookgrammar.constructs import ALLOWED_ELEMENTS, CLOSED_VALUES, CONSTRUCTS, ELEMENT_ATTRS, GLOBAL_ATTRS
from lookgrammar.errors import LookError
from lookgrammar.reads import READS
from reportcause.grammar import VERDICTS

TITLE_PREFIX = "site-studio look: "
KINDS = ("derive", "pattern", "markup")
STATUSES = ("mapped", "ambiguous", "unmapped", "none")
ID_RE = re.compile(r"\Ass-look/(derive|pattern|markup)/([a-z][a-z0-9-]*)/h([0-9a-f]{8})\Z")
SENTENCES = {
    "derive": "The plugin's derive does not yet read this construct of a site's own markup; with this entry, the plugin's pages "
              "equal the old builder's.",
    "pattern": "A site's own look uses the plugin's look grammar in a way no look the plugin ships does.",
    "markup": "A site's own look places the same slots as a shipped look in other markup, which the site's owner thinks may "
              "help other sites.",
}
FOOTER = ("_Filed by `site-studio` from an installed plugin. It carries the shape of one look construct and version numbers "
          "only: no class name, id, path, address or text from the site._")
# (field, template line); `{x}` is a value. The fragment block follows the line `fence`.
BODY = (
    ("id", "**Suggestion:** `{id}`"),
    ("sentence", "{sentence}"),
    ("", ""),
    ("construct", "**Construct:** `{construct}`"),
    ("compared", "**Compared with:** {compared}"),
    ("uses", "**Uses no shipped look has:** {uses}"),
    ("evidence", "**Evidence:** {evidence}"),
    ("builds", "**Builds:** yes"),
    ("verdict", "**Parity verdict:** {verdict}"),
    ("pages", "**Pages it renders on:** {pages}"),
    ("yours", "**Visible differences with it:** {yours}"),
    ("derived", "**Visible differences with the derived reading:** {derived}"),
    ("status", "**Derive status:** {status}"),
    ("literals", "**Literals removed:** {literals}"),
    ("version", "**Plugin version:** `{version}`"),
    ("site_schema", "**site.json schema:** {site_schema}"),
    ("record_schema", "**Record schema:** `{record_schema}`"),
    ("", ""),
    ("fence", "```json"),
)
TAIL = ("```", "", "---", FOOTER)
EVIDENCE_BUILD = "build only, no parity measured"
_EVIDENCE_PARITY = re.compile(r"\Aparity, measured at `([0-9a-f]{7,40})`\Z")
_INT = re.compile(r"\A\d+\Z")
_VERSION = re.compile(r"\A\d+\.\d+\.\d+\Z")
_TICKED = re.compile(r"\A`([^`]+)`\Z")
_PLACEHOLDER = re.compile(r"\A(?:c\d+|i\d+|k\d+|n\d+|d\d+|data-d\d+)\Z")
_USE = re.compile(r"\A(?:named:([a-z][a-z0-9-]*)|reads ([a-z][a-z.-]*)(?: \[(@first|@last|@caption|unless)(?:, (@first|@last|@caption|"
                  r"unless))*\])?|([a-z][a-z0-9-]*)\.([a-z][a-z0-9-]*)(?:\.([a-z][A-Za-z0-9]*))?)\Z")
_SLOT_RE = re.compile(r"\{\{[a-z][A-Za-z0-9]*\}\}")
_ATTR_RE = re.compile(r'\s([a-zA-Z][a-zA-Z0-9-]*)(?:="([^"]*)")?')
_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>")
_VOCAB = []


class SuggestionError(ValueError):
    """A suggestion id is not one this plugin makes."""


def parse_id(sid):
    """(kind, construct, digest) of a suggestion id, or raises SuggestionError naming the fix."""
    m = ID_RE.match(sid if isinstance(sid, str) else "")
    if not m or m.group(2) not in CONSTRUCTS:
        raise SuggestionError("%r is not a suggestion id (ss-look/<derive|pattern|markup>/<construct>/h<8 hex>); copy one from what "
                              "adopt.py suggest prints" % (str(sid)[:80],))
    return m.group(1), m.group(2), m.group(3)


def make_id(kind, construct, digest):
    return "ss-look/%s/%s/h%s" % (kind, construct, digest)


def _ticks(items):
    return ", ".join("`%s`" % i for i in items) if items else "none"


def _num(v):
    return "%d" % v if isinstance(v, int) and not isinstance(v, bool) else "none"


def format_body(f):
    """The body for the fields `f` (id, kind, construct, compared, uses, evidence ("parity" or "build"), measured_at, verdict, pages,
    yours, derived, status, literals, version, site_schema, record_schema, fragment text), with NO validation."""
    measured = f.get("measured_at") or ""
    vals = {
        "id": f["id"], "sentence": SENTENCES.get(f.get("kind"), f.get("sentence", "")), "construct": f["construct"],
        "compared": _ticks(f.get("compared")), "uses": _ticks(f.get("uses")),
        "evidence": ("parity, measured at `%s`" % measured) if f.get("evidence") == "parity" else EVIDENCE_BUILD,
        "verdict": "`%s`" % f["verdict"] if f.get("verdict") else "none", "pages": _num(f.get("pages")),
        "yours": _num(f.get("yours")), "derived": _num(f.get("derived")),
        "status": "`%s`" % f["status"] if f.get("status") else "none", "literals": _num(f.get("literals")),
        "version": f.get("version") or "unknown",
        "site_schema": "`%s`" % f["site_schema"] if f.get("site_schema") is not None else "unknown",
        "record_schema": "%s" % f.get("record_schema"),
    }
    lines = [re.sub(r"\{(\w+)\}", lambda m: vals[m.group(1)], t) for _f, t in BODY]
    return "\n".join(lines + [f["fragment"]] + list(TAIL)) + "\n"


def short_sha(sha):
    """The commit as the body names it: 7 hex, longer only when 7 would be all digits (the shapes scan refuses a bare run of 6)."""
    n = 7
    while n < len(sha) and sha[:n].isdigit():
        n += 1
    return sha[:n]


def digest_of(title, body):
    """The first 12 hex of the sha256 of the title, a newline and the body: what `--digest` must be."""
    return hashlib.sha256(("%s\n%s" % (title, body)).encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------------------------------------- layer 1: the grammar
def _use_ok(item):
    m = _USE.match(item)
    if not m:
        return False
    if m.group(1):
        return m.group(1) in CONSTRUCTS
    if m.group(2):
        return m.group(2) in READS
    construct, part, slot = m.group(5), m.group(6), m.group(7)
    parts = CONSTRUCTS.get(construct, {}).get("parts", {})
    return part in parts and (slot is None or slot in parts[part])


def _list_ok(value, ok):
    if value == "none":
        return True
    items = value.split(", ")
    return all(_TICKED.match(i) and ok(_TICKED.match(i).group(1)) for i in items)


def _field_problem(field, v, shipped_ids):
    """Why one field's value is outside its grammar, or None."""
    ticked = _TICKED.match(v)
    checks = {
        "construct": lambda: v in CONSTRUCTS,
        "compared": lambda: _list_ok(v, lambda x: x in shipped_ids if shipped_ids else bool(re.match(r"\A[a-z][a-z0-9-]*\Z", x))),
        "uses": lambda: _list_ok(v, _use_ok),
        "evidence": lambda: v == EVIDENCE_BUILD or _EVIDENCE_PARITY.match(v) and not _EVIDENCE_PARITY.match(v).group(1).isdigit(),
        "verdict": lambda: v == "none" or (ticked and ticked.group(1) in VERDICTS),
        "pages": lambda: bool(_INT.match(v)) and int(v) >= 1,
        "yours": lambda: v == "none" or v == "0",
        "derived": lambda: v == "none" or bool(_INT.match(v)),
        "status": lambda: v == "none" or (ticked and ticked.group(1) in STATUSES),
        "literals": lambda: bool(_INT.match(v)),
        "version": lambda: bool(_VERSION.match(v)) or v == "unknown",
        "site_schema": lambda: v == "unknown" or (ticked and _INT.match(ticked.group(1))),
        "record_schema": lambda: bool(_INT.match(v)),
    }
    ok = checks.get(field)
    return None if ok is None or ok() else "the %s is outside its grammar" % field


def _markup_problems(construct, parts, default_tokens):
    """M3 and section 13.5 layer 1 over the fragment's markup: every class, id and `data-*` token is a placeholder or the default
    look's; every `aria-*` and `data-*` value is a slot, a placeholder, a closed-list value or a whole number."""
    out = []
    for pn, text in sorted(parts.items()):
        for tag, attrs in _TAG_RE.findall(text if isinstance(text, str) else ""):
            if tag.lower() not in ALLOWED_ELEMENTS and tag.lower() != "iframe":
                out.append(("grammar", "the fragment holds the element <%s>" % tag, tag[:40]))
            for name, value in _ATTR_RE.findall(attrs):
                name, value, bare = name.lower(), value or "", _SLOT_RE.sub("", value or "").strip()
                if name in ("class", "id"):
                    for core in strip._cores(value):
                        if not _PLACEHOLDER.match(core) and (name, core) not in default_tokens:
                            out.append(("grammar", "a %s token is neither a placeholder nor the default look's" % name, core[:40]))
                elif name.startswith("data-") and name != "data-embed":
                    if not _PLACEHOLDER.match(name) or bare:
                        out.append(("grammar", "a data- attribute is not a placeholder holding only slots", (name + "=" + value)[:60]))
                elif name.startswith("aria-"):
                    closed = strip.ARIA_CLOSED.get(name, ())
                    refs = name in strip.ID_REFS and all(_PLACEHOLDER.match(t) for t in bare.split())
                    if bare and not (bare in closed or refs or (_INT.match(bare) and name not in strip.TEXT_ATTRS)):
                        out.append(("grammar", "an aria- value is not a slot, a placeholder or a closed-list value", (name + "=" + value)[:60]))
                elif bare and name in strip.TEXT_ATTRS:
                    out.append(("grammar", "a text attribute holds a literal", (name + "=" + value)[:60]))
                elif bare and name not in GLOBAL_ATTRS and not any(name in a for a in ELEMENT_ATTRS.values()) \
                        and name not in CLOSED_VALUES:
                    out.append(("grammar", "an attribute outside the allowlist", name[:40]))
    return out


def _fragment_problems(block, construct, digest):
    try:
        frag = json.loads(block)
    except ValueError:
        return [("grammar", "the fenced block is not JSON", block[:60])]
    if not isinstance(frag, dict) or json.dumps(frag, sort_keys=True, indent=1, ensure_ascii=False) != block:
        return [("grammar", "the fenced block does not re-serialise to itself", block[:60])]
    out = []
    if hashlib.sha256(block.encode("utf-8")).hexdigest()[:8] != digest:
        out.append(("grammar", "the id's digest is not the fragment's", digest))
    try:
        looks.parse(block, "fragment", shipped=True, template=True, cross=False)
    except LookError as e:
        out.append(("grammar", "the fragment is not a template look", str(e).split("\n")[0][:80]))
    entries = [(c, p) for c, p in (frag.get("constructs") or {}).items()]
    entries += [(e.get("like"), e.get("parts") or {}) for n, e in (frag.get("named") or {}).items() if n == "n1"]
    if sorted(set(frag) - {"look", "constructs", "named", "reads"}) or len(entries) != 1 or len(frag.get("named") or {}) > 1 \
            or (frag.get("named") and list(frag["named"]) != ["n1"]):
        out.append(("grammar", "the fragment is not one construct", block[:60]))
        return out
    got, parts = entries[0]
    if got != construct:
        out.append(("grammar", "the fragment's construct is not the id's", str(got)[:40]))
    default = (looks.default_look().constructs or {}).get(construct)
    out.extend(_markup_problems(construct, parts if isinstance(parts, dict) else {}, strip.tokens_of(default)))
    keys = strip.plugin_keys()
    for target, value in sorted((frag.get("reads") or {}).items()):
        srcs = value if isinstance(value, list) else [x for v in (value or {}).values() for x in (v if isinstance(v, list) else [v])]
        for k in srcs:
            if not (isinstance(k, str) and (k.startswith("@") or k in keys or re.match(r"\Ak\d+\Z", k))):
                out.append(("grammar", "a reads key is neither k<n> nor a plugin key", str(k)[:40]))
    return out


def line_problems(title, body, shipped_ids=()):
    """Layer 1 (section 13.5): each line is its template with a value inside its enumeration; the block is a template look of one
    construct whose tokens are placeholders; the title is the id's. [(layer, why, found)]."""
    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    head, rest = lines[:len(BODY)], lines[len(BODY):]
    if len(head) != len(BODY) or len(rest) < len(TAIL) + 1 or tuple(rest[-len(TAIL):]) != TAIL:
        return [("grammar", "the body is not the suggestion template (%d lines)" % len(lines), "")]
    probs, sid, construct, digest = [], None, None, None
    for (field, template), line in zip(BODY, head):
        pattern = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.*)", re.escape(template))
        m = re.match(r"\A%s\Z" % pattern, line)
        if not m:
            probs.append(("grammar", "line `%s` is not its template" % (field or "blank"), line[:60]))
            continue
        v = m.groupdict().get(field)
        if field == "id":
            try:
                kind, construct, digest = parse_id(v)
                sid = v
            except SuggestionError as e:
                probs.append(("grammar", "the id: %s" % e, v[:60]))
        elif field == "sentence":
            if sid is None or v != SENTENCES[parse_id(sid)[0]]:
                probs.append(("grammar", "the sentence is not the kind's fixed sentence", v[:60]))
        elif field == "construct" and construct is not None and v != construct:
            probs.append(("grammar", "the construct is not the id's", v[:60]))
        elif v is not None:
            why = _field_problem(field, v, set(shipped_ids))
            if why:
                probs.append(("grammar", why, v[:60]))
    if sid is None:
        return probs
    if title != TITLE_PREFIX + sid:
        probs.append(("grammar", "the title is not the id's", title[:60]))
    probs.extend(_fragment_problems("\n".join(rest[:-len(TAIL)]), construct, digest))
    return probs


def vocabulary(shipped_ids=()):
    """Every word this body may print that is plugin vocabulary: the template and the sentences, the construct, part, slot and
    target names, the allowed element and attribute names and closed values, the default look's tokens and the shipped ids."""
    if _VOCAB and not shipped_ids:
        return _VOCAB[0]
    words = set()
    texts = [t for _f, t in BODY] + list(SENTENCES.values()) + list(TAIL) + [TITLE_PREFIX, EVIDENCE_BUILD, "parity, measured at"]
    texts += list(KINDS) + list(STATUSES) + list(VERDICTS) + list(READS) + list(ALLOWED_ELEMENTS) + list(GLOBAL_ATTRS)
    texts += ["look", "constructs", "named", "like", "parts", "reads", "from", "unless", "none", "yes", "json", "unknown", "iframe"]
    for c, row in CONSTRUCTS.items():
        texts.append(c)
        for p, slots in row["parts"].items():
            texts.extend([p] + list(slots))
    for v in list(ELEMENT_ATTRS.values()) + list(CLOSED_VALUES.values()) + list(strip.ARIA_CLOSED.values()):
        texts.extend(v)
    texts += list(CLOSED_VALUES) + list(strip.ARIA_CLOSED) + list(strip.TEXT_ATTRS) + list(strip.ID_REFS) + list(shipped_ids)
    texts += [core for parts in looks.default_look().constructs.values() for _k, core in strip.tokens_of(parts)]
    for t in texts:
        words.update(w.lower() for w in re.findall(r"[^\W_]+", t))
        words.update(w.lower() for w in re.findall(r"[^\W_]+(?:[-_.][^\W_]+)*", t))
    got = frozenset(words)
    if not shipped_ids:
        _VOCAB.append(got)
    return got


def is_placeholder(word):
    """True for the strip's own forms (`c3`, `i1`, `k2`, `n1`, `data-d1`): never a site term."""
    return bool(_PLACEHOLDER.match(word))
