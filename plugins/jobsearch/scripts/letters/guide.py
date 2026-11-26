"""The profile's declared letter guide: its verdict, and the pure half of `--set-guide` (jobsearch 0.95.0; dev 1071, 1073; design § 5).

`config.json` may declare `writing.letter_guide`, a file inside the profile the letter writer reads before it drafts:

    {"path": "presence/letter_guide.md", "required_headings": ["Structure", "Voice"]}      or a bare string path
                                                                                           (no required headings, § 5.1)

* `declaration(config)` returns `(decl, error)`. `decl` is `{"path", "required_headings"}`, or None when nothing is declared
  (`writing.letter_guide` absent or null); `error` is a one-line reason when the key is present but not a path or an object
  with a non-empty string `path` and a list of strings `required_headings` (reported as BROKEN, reason `malformed`).
* `check_guide(config, root)` returns a `Verdict`. It reads the file under `root`, the profile root, and judges, in this
  order: `outside the profile` (an absolute path, a `..` part, or a realpath that leaves the root, symlinks included),
  `missing`, `unreadable`, `empty` (no body words outside headings), `under the 20-word floor`, `lost heading "<name>"`
  (a required `##` heading no longer in the file; compared trimmed, case- and space-insensitive; every lost one is named),
  `empty section "<name>"` (a required `##` heading still in the file with nothing under it; both are named in one reason,
  `lost heading "A"; empty section "B"`, when both hold).
  Only REAL headings count (review of 0.95.0, item 11): a `##` line inside a fenced code block (``` or ~~~) or an HTML comment
  is not a heading, and fenced or commented words do not count toward the empty test or the 20-word floor. A section is empty
  when no non-blank, non-comment line (a code example counts; a bare subheading line does not, the text under it does)
  comes before the next heading of the same or a higher level.
* `Verdict.state` is `none` | `ok` | `broken`; `.path`; `.reason` (broken only); `.lost` (the lost heading names, as declared);
  `.empty` (the empty-section names, as declared);
  `.text` is the value after the label (`none declared (the default structure in cover-letter-writer applies)`,
  `presence/letter_guide.md OK`, `BROKEN — presence/letter_guide.md lost heading "Voice"`); `.short` is `.text` with the none
  state shortened to `none declared` (the `STAGED LETTERS` header); `.line` is `"letter guide: " + .text`, the line
  `profile.py --writing`, `letter_out.py --check` and `check_narrative.py` print; `.detail` is `"<path> <reason>"`, the stop
  reason of `letter_out.py --preflight` (§ 8.1).
* `plan_set_guide(config, root, arg)` is the pure half of `letter_out.py --set-guide <path> | none`: it writes nothing and
  returns a `GuideChange`: `action` `set` (with `value`, the new `writing.letter_guide` object holding the file's current `##`
  headings), `remove` (`arg` is `none`; `value` None), or `refuse` (with a `reason`: outside the profile, missing, unreadable,
  empty, or under the floor). `was` is the declaration in `config` before the change, for the caller to print.

Standard library only; imports nothing of the plugin; the only file it reads is the declared guide, under the root it is
handed. Python 3.9+.
"""

import os
import re

FLOOR_WORDS = 20
NONE_TEXT = "none declared (the default structure in cover-letter-writer applies)"
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")


class Verdict(object):
    """The guide's state against the profile root; see the module docstring."""

    def __init__(self, state, path=None, reason=None, lost=None, empty=None):
        self.state = state
        self.path = path
        self.reason = reason
        self.lost = lost or []
        self.empty = empty or []

    @property
    def text(self):
        if self.state == "none":
            return NONE_TEXT
        if self.state == "ok":
            return "%s OK" % self.path
        return "BROKEN — %s" % self.detail

    @property
    def short(self):
        """`text` without the explanatory tail of the none state: the form the `STAGED LETTERS` header prints."""
        return "none declared" if self.state == "none" else self.text

    @property
    def detail(self):
        return ("%s %s" % (self.path, self.reason)) if self.path else self.reason

    @property
    def line(self):
        return "letter guide: %s" % self.text


class GuideChange(object):
    """What `--set-guide` would do: `action` set | remove | refuse, with `value`, `reason`, `was`."""

    def __init__(self, action, value=None, reason=None, was=None):
        self.action = action
        self.value = value
        self.reason = reason
        self.was = was


def declaration(config):
    """(decl, error): the declared guide as `{"path", "required_headings"}`, None when absent, or a malformed-key reason."""
    writing = config.get("writing") if isinstance(config, dict) else None
    raw = writing.get("letter_guide") if isinstance(writing, dict) else None
    if raw is None:
        return None, None
    if isinstance(raw, str):
        raw = {"path": raw, "required_headings": []}
    if not isinstance(raw, dict):
        return None, "writing.letter_guide is neither a path nor an object"
    path, heads = raw.get("path"), raw.get("required_headings", [])
    if not isinstance(path, str) or not path.strip():
        return None, "writing.letter_guide has no path"
    if not isinstance(heads, list) or not all(isinstance(h, str) for h in heads):
        return None, "writing.letter_guide.required_headings is not a list of text"
    return {"path": path.strip(), "required_headings": list(heads)}, None


def resolve(root, path):
    """The real path of `path` under `root`, or None when it is absolute, climbs with `..`, or resolves outside the root."""
    if os.path.isabs(path) or path.startswith(("~", "/", "\\")) or re.match(r"^[A-Za-z]:", path):
        return None
    if ".." in re.split(r"[\\/]+", path):
        return None
    real_root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(root, path))
    if real != real_root and not real.startswith(real_root + os.sep):
        return None
    return real


def heading_key(name):
    """A heading name compared trimmed, case- and space-insensitive."""
    return re.sub(r"\s+", "", name).casefold()


def _strip_comments(line, in_comment):
    """(text outside any HTML comment, still inside one at the end of the line, a comment opened the line)."""
    out, i, lead = [], 0, in_comment
    while i < len(line):
        if in_comment:
            end = line.find("-->", i)
            if end < 0:
                return "".join(out), True, lead
            i, in_comment = end + 3, False
            continue
        start = line.find("<!--", i)
        if start < 0:
            out.append(line[i:])
            break
        out.append(line[i:start])
        if not "".join(out).strip():
            lead = True
        i, in_comment = start + 4, True
    return "".join(out), in_comment, lead


def parse_guide(text):
    """(body_word_count, headings) of a guide file's text, reading only what is really in the document.

    A line inside a fenced code block (``` or ~~~, closed by a fence of the same mark at least as long, or by the end of
    the file) or inside an HTML comment is not a heading and its words are not body words. `headings` is a list of
    `(level, name, has_body)`, one per real heading in file order; `has_body` is whether the section holds a
    non-blank line outside comments before the next heading of the same or a higher level. A code example counts as
    a section's body (it is not blank); a bare subheading line does not, though the text under it does. Words are
    counted outside heading lines, fences and comments."""
    words, heads = 0, []
    fence, in_comment = None, False
    for line in text.splitlines():
        if fence:
            if re.match(r"^\s{0,3}%s{%d,}\s*$" % (re.escape(fence[0]), fence[1]), line):
                fence = None
            elif line.strip() and heads:
                heads[-1][2].append(True)
            continue
        clean, in_comment, lead = _strip_comments(line, in_comment)
        fm = None if lead else re.match(r"^\s{0,3}(`{3,}|~{3,})", clean)
        if fm:
            fence = (fm.group(1)[0], len(fm.group(1)))
            if heads:
                heads[-1][2].append(True)
            continue
        m = None if lead else _HEADING_RE.match(clean)
        if m:
            heads.append([len(m.group(1)), m.group(2), []])
            continue
        if clean.strip():
            words += len(clean.split())
            if heads:
                heads[-1][2].append(True)
    return words, _with_bodies(heads)


def _with_bodies(heads):
    """Fold the raw collector into `(level, name, has_body)`: a section also owns the body of every deeper heading under it."""
    out = []
    for i, (level, name, body) in enumerate(heads):
        has = bool(body)
        for lvl, _n, b in heads[i + 1:]:
            if lvl <= level:
                break
            has = has or bool(b)
        out.append((level, name, has))
    return out


def split_guide_text(text):
    """(body_word_count, [`##` heading texts]) of a guide file's text; only real headings, never fenced or commented ones."""
    words, heads = parse_guide(text)
    return words, [name for level, name, _b in heads if level == 2 and name]


def _read(root, path):
    """(real, text, reason): `reason` is set when the file cannot be used (outside the profile, missing, unreadable)."""
    real = resolve(root, path)
    if real is None:
        return None, None, "outside the profile"
    if not os.path.isfile(real):
        return None, None, "missing"
    try:
        with open(real, encoding="utf-8") as fh:
            return real, fh.read(), None
    except (OSError, UnicodeDecodeError):
        return None, None, "unreadable"


def _body_reason(words):
    if words == 0:
        return "empty"
    if words < FLOOR_WORDS:
        return "under the %d-word floor" % FLOOR_WORDS
    return None


def check_guide(config, root):
    """The verdict on the declared guide against the profile root `root`."""
    decl, err = declaration(config)
    if err:
        return Verdict("broken", reason="malformed (%s)" % err)
    if decl is None:
        return Verdict("none")
    path = decl["path"]
    _real, text, reason = _read(root, path)
    if reason:
        return Verdict("broken", path, reason)
    words, heads = parse_guide(text)
    reason = _body_reason(words)
    if reason:
        return Verdict("broken", path, reason)
    filled = {}
    for level, name, has_body in heads:
        if level == 2 and name:
            filled[heading_key(name)] = filled.get(heading_key(name), False) or has_body
    lost = [h for h in decl["required_headings"] if heading_key(h) not in filled]
    empty = [h for h in decl["required_headings"] if heading_key(h) in filled and not filled[heading_key(h)]]
    if lost or empty:
        said = []
        if lost:
            said.append("lost heading %s" % ", ".join('"%s"' % h for h in lost))
        if empty:
            said.append("empty section %s" % ", ".join('"%s"' % h for h in empty))
        return Verdict("broken", path, "; ".join(said), lost, empty)
    return Verdict("ok", path)


def plan_set_guide(config, root, arg):
    """The pure half of `--set-guide`: what the new `writing.letter_guide` would be, or why not. Writes nothing."""
    decl, _err = declaration(config)
    if arg is None or not str(arg).strip():
        return GuideChange("refuse", reason="no path given", was=decl)
    arg = str(arg).strip()
    if arg.lower() == "none":
        return GuideChange("remove", was=decl)
    _real, text, reason = _read(root, arg)
    if reason:
        return GuideChange("refuse", reason="%s %s" % (arg, reason), was=decl)
    words, heads = split_guide_text(text)
    reason = _body_reason(words)
    if reason:
        return GuideChange("refuse", reason="%s %s" % (arg, reason), was=decl)
    seen, recorded = set(), []
    for h in heads:
        if heading_key(h) not in seen:
            seen.add(heading_key(h))
            recorded.append(h)
    rel = os.path.normpath(arg.replace("\\", "/")).replace(os.sep, "/")
    return GuideChange("set", value={"path": rel, "required_headings": recorded}, was=decl)
