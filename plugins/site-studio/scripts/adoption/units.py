"""adoption.units -- the units of a file: Markdown paragraphs, code statements, package.json keys; plumbing detection.

Part of the `adoption` package behind the entry point `adopt.py`.
"""

import posixpath
import re

_FM = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_HEAD = re.compile(r"^\s{0,3}#{1,6}\s")


def first_line(text, width=100):
    """The first non-blank line of a unit, cut at `width` with "..." when it is longer: how a unit is named to the person (the `--rest` print,
    the commit's "Covered by the plugin (dropped)" list), so a dropped unit is told by its own words and never only by its id (dev 1068)."""
    line = next((l.strip() for l in text.split("\n") if l.strip()), "")
    return line if len(line) <= width else line[:width - 3].rstrip() + "..."


def md_units(text):
    """Paragraphs and list items of a Markdown file; headings, comments, front matter, blanks excluded."""
    text = _FM.sub("", text.replace("\r\n", "\n"), count=1)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    units, cur, fence = [], [], False

    def flush():
        if cur:
            units.append("\n".join(cur).strip())
            del cur[:]
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if not fence:
                flush()
                fence = True
                cur.append(line)
            else:
                cur.append(line)
                fence = False
                flush()
            continue
        if fence:
            cur.append(line)
            continue
        if not line.strip():
            flush()
        elif _HEAD.match(line):
            flush()
        elif _LIST.match(line):
            flush()
            cur.append(line)
        else:
            cur.append(line)
    flush()
    return [u for u in units if u]


_CLOSERS = re.compile(r"^(?:[})\]]|fi\b|done\b|esac\b|else\b|elif\b|then\b|catch\b|finally\b|except\b|\.)")


def _code_line(line, ext):
    """The line with string contents and line comments blanked, for bracket counting."""
    out, i, n, q = [], 0, len(line), None
    while i < n:
        c = line[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c in "\"'`":
            q = c
        elif c == "#" and ext in (".py", ".sh", ".bash", ".zsh"):
            break
        elif c == "/" and line[i:i + 2] == "//" and ext in (".js", ".mjs", ".cjs"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def code_units(text, ext):
    """Top-level functions and statements; comments and blank lines are not units."""
    if ext == ".json":
        return _json_units(text)
    py = ext == ".py"
    sh = ext in (".sh", ".bash", ".zsh")
    units, cur, depth = [], [], 0
    in_block = False
    in_triple = None
    in_tpl = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw
        stripped = line.strip()
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        if in_triple:
            cur.append(raw)
            if in_triple in line:
                in_triple = None
            continue
        if in_tpl:
            cur.append(raw)
            if line.count("`") % 2 == 1:
                in_tpl = False
            continue
        if not stripped:
            continue
        if stripped.startswith("/*") and not py and not sh:
            if "*/" not in stripped:
                in_block = True
            continue
        if stripped.startswith("#") and (py or sh):
            continue
        if stripped.startswith("//") and not py and not sh:
            continue
        indent = len(line) - len(line.lstrip())
        starts_new = (indent == 0 and depth <= 0 and not _CLOSERS.match(stripped)
                      and not (py and re.match(r"(else|elif|except|finally)\b", stripped)))
        if starts_new:
            if cur:
                units.append("\n".join(cur))
            cur = [raw]
            depth = 0
        else:
            cur.append(raw)
        code = _code_line(line, ext)
        depth += sum(code.count(c) for c in "({[") - sum(code.count(c) for c in ")}]")
        if sh:
            if re.match(r"^\s*(if|for|while|case|until)\b", code) or re.search(r"\b(do|then)\s*$", code):
                pass
        for t in ('"""', "'''"):
            if py and line.count(t) % 2 == 1:
                in_triple = t
        if not py and line.count("`") % 2 == 1:
            in_tpl = True
    if cur:
        units.append("\n".join(cur))
    return [u.strip("\n") for u in units if u.strip()]


def _json_units(text):
    units, cur = [], []
    for line in text.replace("\r\n", "\n").split("\n"):
        if re.match(r'^ {2}"', line) or re.match(r"^\t\"", line):
            if cur:
                units.append("\n".join(cur))
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        units.append("\n".join(cur))
    return [u for u in units if u.strip()]


# Plumbing (dev #835 phase 4c): a line that only imports a module, declares strict mode, or lists the
# names a module exports carries no behaviour and no person data, so it is not a unit. Without this a
# clean copy of a plugin tool scored PARTIAL on its import lines alone (see the first run in
# tests/fixtures/adopt/AS-FOUND.md and EXPECTED.md's stated refinement).
_PLUMBING = tuple(re.compile(p, re.S) for p in (
    r"^import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*$",
    r"^from\s+[\w.]+\s+import\s+[\w\s,()*]+$",
    r"^(?:const|let|var)\s+[\w{},\s$:]+=\s*require\(\s*['\"][^'\"]+['\"]\s*\)\s*;?$",
    r"^import\s+(?:[\w{},\s*$]+\s+from\s+)?['\"][^'\"]+['\"]\s*;?$",
    r"^['\"]use strict['\"];?$",
    r"^set\s+-[A-Za-z]+(?:\s+\S+)*$",
    r"^module\.exports\s*=\s*\{[\w\s,:]*\}\s*;?$",
    r"^export\s*\{[\w\s,]*\}\s*;?$",
    r"^__all__\s*=\s*[\[(][^\])]*[\])]$",
))
_DOCSTRING = re.compile(r"^(?:\"{3}|'{3}).*(?:\"{3}|'{3})$", re.S)


def is_plumbing(unit):
    one = " ".join(unit.split())
    return any(r.match(one) for r in _PLUMBING)


def units_of(kind, path, text):
    if kind == "code":
        ext = posixpath.splitext(path)[1].lower()
        units = code_units(text, ext)
        if ext == ".py" and units and _DOCSTRING.match(units[0].strip()):
            units = units[1:]
        return [u for u in units if not is_plumbing(u)]
    return md_units(text)


# A driver statement (dev #835 phase 4c): a top-level statement that does nothing but call a function
# the same file defines is explained when that function's own unit is. A call to an unexplained
# function stays residual, so an extra renderer still counts.
_DEFS = (
    re.compile(r"^\s*(?:async\s+)?def\s+(\w+)"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"),
    re.compile(r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"),
    re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{"),
)


def defined_name(unit):
    first = unit.lstrip("\n").split("\n", 1)[0]
    for r in _DEFS:
        m = r.match(first)
        if m:
            return m.group(1)
    return None


def driver_explained(units, explained):
    """The indexes of unexplained units that only call explained functions defined in this file."""
    names = {}
    for i, u in enumerate(units):
        n = defined_name(u)
        if n:
            names[n] = i
    out = set()
    for i, u in enumerate(units):
        if explained[i] or defined_name(u):
            continue
        called = [n for n in names
                  if re.search(r"\b%s\s*\(|[(,]\s*%s\s*[,)]" % (re.escape(n), re.escape(n)), u)]
        if called and all(explained[names[n]] for n in called):
            out.add(i)
    return out
