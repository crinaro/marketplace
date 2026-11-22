"""adoption.template -- the TEMPLATE and GENERAL classes that map what the template site-studio replaces wrote onto the
keys, files and tokens the plugin's build reads (design 8 R1, H1, P1, N1, RS1, A1; step 1.9).

Part of the `adoption` package behind the entry point `adopt.py`. Every function here is PURE over a tree-like object
(`paths()`, `exists()`, `text()`, `read()`): it returns what it would write and what it would remove, and never reads a
file but through that object, so `converted_site_files` can lay one class's result over the tree before the next reads it.

THE CLASSES.
  references   (TEMPLATE)  a `reference.json` with the template's `myRole` / `captured_from`: `myRole` is `role`,
                           `captured_from` is `fetched`, `alt` is `imageAlt` (dev 944); `image`, `author` and
                           `imagePosition` are the plugin's own keys and stay. A `null` in any optional key is "absent":
                           the key is dropped (dev 944, 964); a `null` `url` or `title` stays, for the build to refuse.
                           NO FILE MOVES, so no image address changes (R1).
  pageFiles    (TEMPLATE)  `content/home/home.md` -> `content/home/index.md`, `content/about/about.md` -> `content/about/
                           index.md`; the bytes are unchanged (the reserved folders' form of 0.3.0's `work.md` rule, H1).
  homeKeys     (TEMPLATE)  the home page's keys (H1): `headline` is `title`; the front-matter `intro` is the body's first
                           paragraph; `stats` is a `:::part stats` holding `:::tiles`; `quote` and `quoteBy` are
                           `endorsement`; a template `feed: a; b` is a list; the template's reference `featured` is
                           `samples`; `contact` text is a `:::part reach`; `linkedin` is `links`; the showcase is a list
                           of `portfolio/piece | image`; every key of `keytables.HOME_LIST_KEYS` the template wrote as
                           text, comma-separated (dev 943) or as ONE value (dev 964), is a list. `eyebrow`, `role` and
                           `photo` stay (keys at schema 4).
  resumeHeader (TEMPLATE)  the resume's `name` is `title`, `headline` is `tagline`, `linkedin` and `website` are ONE `links`
                           map (the website's label is its host, as the template prints it), `email` and `location` are
                           `contact` (RS1, dev 947).
  navTokens    (GENERAL)   `<nav ...>{{nav}}</nav>` is `<nav ...>{{navLinks}}</nav>`: the person's wrapper is kept and
                           the plugin's own `{{nav}}` wrapper is not added inside it (N1).
  personName   (GENERAL)   when site.json `name` has the shape of a domain or a repository name and the resume holds a
                           person's name, `name` is that name (RS1; measured).
  resumePdfName(GENERAL)   the committed resume PDF, and its sidecar, take the basename the old builder published it
                           under, and `resume.pdf` names it: `build_resume` publishes `resume/<basename>` (A1, #888).

A class whose reading is a guess without the template's fingerprint is `you decide` under 0.3.0 5.0.3, which
`decide_conversions` enforces; the functions here make the change either way, so `check` can name what it would do.
"""

import json
import posixpath
import re
from urllib.parse import urlsplit

from configschema import configkeys
from contentmodel import keytables, pagefiles

_KEY_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):(?:[ \t]+(.*?))?[ \t]*$")
_WORD_NAME = re.compile(r"^[A-Za-z][A-Za-z.'-]*(?: [A-Za-z][A-Za-z.'-]*)+$")
_DOMAIN_OR_REPO = re.compile(r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}$|^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$|^[a-z0-9]+(?:[-_][a-z0-9]+)+$")


# ---------------------------------------------------------------- front matter, kept byte for byte where untouched

def split_front(text):
    """(front lines without the fences, body lines, had front matter): a file with no front matter is all body."""
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].rstrip() == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                return lines[1:i], lines[i + 1:], True
    return [], lines, False


def entries(front):
    """[[key or None, [raw lines]]]: each top-level `key: value` line with the indented lines after it."""
    out = []
    for line in front:
        m = _KEY_LINE.match(line.rstrip("\r"))
        if m and not line.startswith((" ", "\t")):
            out.append([m.group(1), [line]])
        elif out:
            out[-1][1].append(line)
        else:
            out.append([None, [line]])
    return out


def scalar(entry):
    """The one-line value of an entry, unquoted; None for a list or a map (an entry with following lines)."""
    if len(entry[1]) != 1:
        return None
    m = _KEY_LINE.match(entry[1][0].rstrip("\r"))
    if not m or m.group(2) is None:
        return ""
    v = m.group(2).strip()
    if len(v) > 1 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    return v


def _yaml(value):
    """One value as the plugin's front-matter reader reads it back: plain text, quoted only when it must be."""
    if value == "" or value[0] in "\"'[{&*!|>%@`#-" or ": " in value or value.endswith(":") or " #" in value:
        return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')
    return value


def _emit(front_entries, body, had=True):
    """The file: its fenced front matter, then the body. No entry left means NO fence, never an empty `---` / `---`
    block (dev 946): a file with nothing to say in its front matter has none."""
    lines = ["---"]
    for _k, raw in front_entries:
        lines.extend(raw)
    if len(lines) == 1:
        return "\n".join(body)
    lines.append("---")
    return "\n".join(lines + body)


def _list_entry(key, items):
    return [key, ["%s:" % key] + ["  - %s" % _yaml(i) for i in items]]


def _map_entry(key, pairs):
    return [key, ["%s:" % key] + ["  %s: %s" % (k, _yaml(v)) for k, v in pairs]]


# ---------------------------------------------------------------- references (R1)

REFERENCE_RENAMES = (("myRole", "role"), ("captured_from", "fetched"), ("alt", "imageAlt"))
# The keys a reference may leave out: every key the newest schema reads but the two it requires (design-movement-view 6.2,
# dev #964). A `null` in one of them is "absent" (YAML and JSON) and is dropped; a `null` `url` or `title` stays, refused.
REFERENCE_REQUIRED = ("url", "title")
_JSON_KEY = r'((?:^|[{,])\s*)"%s"(\s*:)'          # a member at a line's start, or after `{` or `,` (a one-line reference)


def _renamed_only(text, data, old, new):
    """True when `text` parses as `data` with the member `old` named `new` and nothing else changed (a match inside a string
    value is not a member, and is never renamed)."""
    try:
        got = json.loads(text)
    except ValueError:
        return False
    want = dict((new if k == old else k, v) for k, v in data.items())
    return got == want and list(got) == list(want)


def optional_reference_keys():
    """The `reference.json` keys a `null` may be dropped from: `reference_keys(SCHEMA_MAX)` less `REFERENCE_REQUIRED`."""
    return tuple(k for k in keytables.reference_keys(configkeys.SCHEMA_MAX) if k not in REFERENCE_REQUIRED)


def reference_rewrites(tree):
    """{content/references/<r>/reference.json: (new text, [(old key, new key)])} for each reference holding a template
    key. Only the key's name changes: the order, the values and every other byte stay. A reference that already holds the
    plugin's key too is left (and `check` names the duplicate through the build's own refusal). Then every optional key
    holding `null` is dropped (`published: null` since 0.4.2, any optional key since 0.5.0)."""
    out = {}
    for p in sorted(tree.paths()):
        parts = p.split("/")
        if not (len(parts) == 4 and parts[:2] == ["content", "references"] and parts[3] == "reference.json"):
            continue
        try:
            text = tree.text(p)
            data = json.loads(text)
        except (KeyError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        done = []
        for old, new in REFERENCE_RENAMES:
            if old in data and new not in data:
                new_text, n = re.subn(_JSON_KEY % re.escape(old), r'\1"%s"\2' % new, text, count=1, flags=re.M)
                if n == 1 and _renamed_only(new_text, json.loads(text), old, new):
                    text = new_text
                    done.append((old, new))
        renamed = dict(done)
        for key in sorted(data, key=lambda k: (k != "published", k)):       # null is absent (dev 944 R1, dev 964)
            name = renamed.get(key, key)
            if data[key] is None and name in optional_reference_keys():
                dropped = _drop_null_member(text, name)
                if dropped is not None:
                    text = dropped
                    done.append(("%s: null" % name, "(no key: null means no date)" if name == "published"
                                 else "(no key: null means absent)"))
        if done:
            out[p] = (text, done)
    return out


def _drop_null_member(text, key):
    """`text` (a JSON object) without the member `"key": null`, with its comma, every other byte kept; None when the
    result would not parse as the same object less that key (then nothing is changed)."""
    member = r'"%s"\s*:\s*null' % re.escape(key)
    want = json.loads(text)
    want.pop(key, None)
    for pattern in (r",\s*" + member, member + r"\s*,\s*", member):       # after another member, before one, or alone
        new, n = re.subn(pattern, "", text, count=1)
        if n == 1:
            try:
                if json.loads(new) == want:
                    return new
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------- pageFiles (H1)

def page_file_renames(tree):
    """[(old, new)]: `content/home/home.md` and `content/about/about.md` where the folder has no `index.md`."""
    out = []
    for name in ("home", "about"):
        old, new = "content/%s/%s.md" % (name, name), "content/%s/index.md" % name
        if tree.exists(old) and not tree.exists(new):
            out.append((old, new))
    return out


# ---------------------------------------------------------------- homeKeys (H1)

TEMPLATE_HOME_KEYS = ("headline", "intro", "stats", "quote", "quoteBy", "linkedin")


def _split_items(value):
    return [x.strip() for x in value.split(";") if x.strip()]


def _split_list(value):
    """The items of a list the template wrote on one line: `a; b` (semicolons), or `a, b` (commas, the template's own
    documented "lists are comma-separated", dev 943). A value holding a semicolon splits on semicolons only, so an item
    that holds a comma stays whole."""
    return _split_items(value) if ";" in value else [x.strip() for x in value.split(",") if x.strip()]


def _piece_key(tree, slug):
    """`portfolio/slug` for the one piece folder named `slug` under content/, else None (zero or several)."""
    found = set()
    for p in tree.paths():
        parts = p.split("/")
        if (len(parts) == 4 and parts[0] == "content" and parts[2] == slug and parts[3] in ("work.md", "index.md")
                and not parts[1].startswith("_") and parts[1] not in ("references", "home", "about", "resume", "media")):
            found.add("%s/%s" % (parts[1], slug))
    return found.pop() if len(found) == 1 else None


def _piece_images(tree, piece):
    """The picture values a piece's own front matter names (`cover`, `tilePhoto`, `tileImage`), as a set of paths."""
    portfolio, slug = piece.split("/")
    for name in ("index.md", "work.md"):
        path = "content/%s/%s/%s" % (portfolio, slug, name)
        if tree.exists(path):
            front, _b, _h = split_front(tree.text(path))
            return set(scalar(e) for e in entries(front) if e[0] in ("cover", "tilePhoto", "tileImage") and scalar(e))
    return set()


def _reference_names(tree):
    return set(p.split("/")[2] for p in tree.paths() if p.startswith("content/references/") and p.endswith("/reference.json"))


def home_path(tree):
    for p in ("content/home/index.md", "content/home/home.md", "content/home.md"):
        if tree.exists(p):
            return p
    return None


def _template_shaped(vals, refs):
    """True when the home's front matter holds a key in the template's form (a scalar where the plugin reads a list or a
    map, or one of the template's own names): a plugin-shaped home is left exactly as it is."""
    if any(vals.get(k) not in (None, "") for k in ("headline", "intro", "stats", "quote", "quoteBy", "linkedin", "contact")):
        return True
    # a list key written as text, comma-separated or ONE value (dev #964: a lone `featured` naming one piece)
    return any(vals.get(k) not in (None, "") and not vals[k].startswith("[") for k in keytables.HOME_LIST_KEYS)


def home_key_rewrite(tree, path):
    """(new text, [what changed]) for the home page at `path`, or (None, []) when it holds no template key. The result is
    the plugin's home: the template's scalar lists become lists, `stats` and `contact` become named parts in the body, and
    what has no plugin form is left (the build refuses it by name and `check` lists it)."""
    text = tree.text(path)
    front, body, had = split_front(text)
    if not had:
        return None, []
    ents = entries(front)
    vals = dict((e[0], scalar(e)) for e in ents if e[0])
    refs = _reference_names(tree)
    if not _template_shaped(vals, refs):
        return None, []
    out, parts, notes, intro, quote_done = [], [], [], None, False
    for ent in ents:
        key = ent[0]
        v = scalar(ent) if key else None
        if key == "title" and vals.get("headline"):
            continue                                              # the template's h1 text, `headline`, is the plugin's `title`
        if key == "headline" and v:
            out.append(["title", ["title: %s" % _yaml(v)]])
            notes.append("headline -> title")
        elif key == "intro" and v:
            intro = v
            notes.append("intro -> the body's first paragraph")
        elif key == "stats" and v:
            parts.append([":::part stats", ":::tiles"] + _split_items(v) + [":::", ":::"])
            notes.append("stats -> :::part stats holding :::tiles")
        elif key in ("quote", "quoteBy") and v is not None:
            if not quote_done and vals.get("quote"):
                quote_done = True
                pairs = [("quote", vals["quote"])] + ([("by", vals["quoteBy"])] if vals.get("quoteBy") else [])
                out.append(_map_entry("endorsement", pairs))
                notes.append("quote, quoteBy -> endorsement")
            elif not vals.get("quote"):
                out.append(ent)
        elif key in keytables.HOME_LIST_KEYS and key != "showcase" and v and not v.startswith("["):
            if key == "featured" and all(n in refs for n in _split_list(v)):      # the reference test first (0.4.2's order)
                out.append(_list_entry("samples", _split_list(v)))
                notes.append("featured (references) -> samples")
            else:                                                                  # one value is a one-item list (dev #964)
                out.append(_list_entry(key, _split_list(v)))
                notes.append("%s -> a list" % key)
        elif key == "showcase" and v and not v.startswith("["):
            items = []
            for item in _split_list(v):
                name, _bar, image = [x.strip() for x in item.partition("|")]
                piece = name if "/" in name else _piece_key(tree, name)
                if piece is None:
                    items = None
                    break
                # the template's `| media/<file>` names the piece's own picture; the plugin reads the image from the HOME
                # page's media folder, so a picture the piece already carries is not repeated (the tile takes it from the
                # piece), and one it does not is kept for the build to refuse by name
                keep = image and image not in _piece_images(tree, piece)
                items.append(piece + ((" | " + image) if keep else ""))
            if items is None:
                out.append(ent)                # a name that is no single piece: left, and the build refuses it by name
            else:
                out.append(_list_entry("showcase", items))
                notes.append("showcase -> a list of portfolio/piece")
        elif key == "contact" and v:
            parts.append([":::part reach", v, ":::"])
            notes.append("contact -> :::part reach")
        elif key == "linkedin" and v:
            out.append(_map_entry("links", [("LinkedIn", v)]))
            notes.append("linkedin -> links")
        else:
            out.append(ent)
    core = list(body)
    while core and core[-1] == "":
        core.pop()
    while core and core[0] == "" and intro:
        core.pop(0)
    chunks = ([[intro]] if intro else []) + ([core] if core else []) + parts
    new_body = []
    for i, chunk in enumerate(chunks):
        new_body += ([""] if i else []) + chunk
    new = _emit(out, new_body + [""])
    return (None, []) if new == text.replace("\r\n", "\n") else (new, notes)


# ---------------------------------------------------------------- pieceKeys under pieceRoles (design-adopt-parity-2 7.4)

def role_list_lines(value):
    """(the front-matter lines of `role` as a YAML list, None) for the template's one-line `role: A (x); B (y)` with two or more
    entries, each one the build reads under `pieceRoles` (`pagefiles.role_entry`, section 4.4): the same words in the same
    order, `currentRole` never written (probe P-R is `default`: the first entry is the current one). (None, why) for a line an
    entry of which section 4.4 would refuse (an unclosed parenthesis, an empty title): the line is left as written, never
    half-converted, and `why` names the entry. (None, None) for a line that is not the one-line form (one entry, no `;`)."""
    if not isinstance(value, str) or ";" not in value:
        return None, None
    items = [x.strip() for x in value.split(";")]
    if len(items) < 2:
        return None, None
    for item in items:
        try:
            pagefiles.role_entry(item)
        except ValueError as e:
            return None, "the entry %s: %s" % (json.dumps(item, ensure_ascii=False), e)
    return ["role:"] + ["  - %s" % _yaml(x) for x in items], None


# ---------------------------------------------------------------- resumeHeader (RS1)

RESUME_OWNED_KEYS = ("name", "headline", "linkedin", "website", "email", "location")   # the keys `resumeHeader` converts


def _https_host(url):
    """The host of an `https://` address as the template prints it (no port, no credentials), else None: the plugin's
    `links` map holds https addresses only, so another form is left for the build to refuse by name."""
    parts = urlsplit(url)
    return parts.hostname if parts.scheme == "https" and parts.hostname and not parts.username else None


def resume_header_rewrite(text):
    """(new text, [(old key, new key)]): `name` is `title`, `headline` is `tagline`, `linkedin` and `website` are ONE `links`
    map (LinkedIn, and the website under its host as the label the template prints), `email` and `location` are one
    `contact` map (labels Email and Location; dev 947). A key whose plugin form is already there is left, and so is a
    `website` that is not an https address."""
    front, body, had = split_front(text)
    if not had:
        return text, []
    ents = entries(front)
    have = set(e[0] for e in ents if e[0])
    pairs = {"links": [], "contact": []}                  # the maps, each in the source's own order
    for ent in ents:
        key, v = ent[0], (scalar(ent) if ent[0] else None)
        if key == "linkedin" and v and "links" not in have:
            pairs["links"].append((key, "LinkedIn", v))
        elif key == "website" and v and "links" not in have and _https_host(v):
            pairs["links"].append((key, _https_host(v), v))
        elif key in ("email", "location") and v and "contact" not in have:
            pairs["contact"].append((key, key.capitalize(), v))
    out, done, placed = [], [], set()
    for ent in ents:
        key, v = ent[0], (scalar(ent) if ent[0] else None)
        if key == "name" and v and "title" not in have:
            out.append(["title", ["title: %s" % _yaml(v)]])
            done.append(("name", "title"))
        elif key == "headline" and v and "tagline" not in have:
            out.append(["tagline", ["tagline: %s" % _yaml(v)]])
            done.append(("headline", "tagline"))
        elif key in ("linkedin", "website", "email", "location") and any(key == k for k, _l, _v in pairs["links"] + pairs["contact"]):
            target = "links" if key in ("linkedin", "website") else "contact"
            if target not in placed:                          # the one map stands where its first source key stood
                placed.add(target)
                out.append(_map_entry(target, [(label, val) for _k, label, val in pairs[target]]))
            done.append((key, target))
        else:
            out.append(ent)
    if not done:
        return text, []
    return _emit(out, body), done


def resume_name(text):
    """The person's name the resume holds (`name:` front matter), or None."""
    front, _body, had = split_front(text)
    for e in entries(front):
        if e[0] == "name":
            return scalar(e) or None
    return None


# ---------------------------------------------------------------- personName (RS1)

def person_name_change(data, resume_text):
    """(old, new) when site.json `name` is a domain or repository-name shape and the resume holds a person's name made of
    two or more words, else None. Pure: the caller decides whether to measure it."""
    old = (data or {}).get("name")
    if not isinstance(old, str) or not _DOMAIN_OR_REPO.match(old):
        return None
    new = resume_name(resume_text) if resume_text else None
    if not new or not _WORD_NAME.match(re.sub(r"\s+\S*\d\S*$", "", new)) and not _WORD_NAME.match(new):
        return None
    return old, new


# ---------------------------------------------------------------- navTokens (N1)

_NAV_WRAP = re.compile(r"(<nav\b[^<>]*>)(\s*)\{\{\s*nav\s*\}\}(\s*)(</nav\s*>)", re.I)


def nav_token_rewrites(tree):
    """{path: (new text, [(line, old, new)])}: `<nav ...>{{nav}}</nav>` in the layout or a `site/src` page."""
    out = {}
    for p in sorted(tree.paths()):
        if not (p == "site/templates/layout.html" or (p.startswith("site/src/") and p.lower().endswith((".html", ".htm")))):
            continue
        try:
            text = tree.text(p)
        except KeyError:
            continue
        changes = []

        def sub(m):
            changes.append((text.count("\n", 0, m.start()) + 1, m.group(0), "%s%s{{navLinks}}%s%s" % (
                m.group(1), m.group(2), m.group(3), m.group(4))))
            return "%s%s{{navLinks}}%s%s" % (m.group(1), m.group(2), m.group(3), m.group(4))
        new = _NAV_WRAP.sub(sub, text)
        if changes:
            out[p] = (new, changes)
    return out


# ---------------------------------------------------------------- resumePdfName (A1)

def resume_pdf_rename(tree, resume_pdf, live_name):
    """([(old, new)] renamed, new `resume.pdf`) when the committed source PDF `resume_pdf` is named other than the file
    the old builder published (`live_name`, a basename), else ([], None). The sidecar `<pdf>.json` moves with it. Refuses
    nothing: a name already taken by another file returns no rename (the caller says so)."""
    if not resume_pdf or not live_name or posixpath.basename(resume_pdf) == live_name or "/" in live_name:
        return [], None
    new = posixpath.join(posixpath.dirname(resume_pdf), live_name)
    if tree.exists(new):
        return [], None
    moves = [(resume_pdf, new)]
    if tree.exists(resume_pdf + ".json") and not tree.exists(new + ".json"):
        moves.append((resume_pdf + ".json", new + ".json"))
    return moves, new


def live_pdf_name(tree, resume_pdf, local_files):
    """The basename the old builder published the resume PDF under: the one `.pdf` in its output whose bytes equal the
    committed source PDF's, or None when none or several do (then nothing is renamed and parity says what differs)."""
    if not resume_pdf or not tree.exists(resume_pdf):
        return None
    data = tree.read(resume_pdf)
    names = sorted(posixpath.basename(p) for p, b in local_files.items() if p.lower().endswith(".pdf") and b == data)
    return names[0] if len(names) == 1 else None
