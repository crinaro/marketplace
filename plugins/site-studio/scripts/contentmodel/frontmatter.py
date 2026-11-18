"""Reading a content file: UTF-8 text, the front matter subset of YAML, and the checks on its values."""

import json
import re

from contentmodel.errors import ContentError


# ---------------------------------------------------------------- text and front matter

def decode_text(raw, where):
    """UTF-8, BOM dropped, CR LF and lone CR normalised to LF."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ContentError("%s is not valid UTF-8" % where, fix="save the file as UTF-8")
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_flow(s, where):
    items, cur, quote = [], "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if quote:
        raise ContentError("%s: an unterminated quote in a list" % where, fix="close the quote in the list")
    if cur.strip() or items:
        items.append(cur.strip())
    return items


def _scalar(s, where):
    s = s.strip()
    if s == "true":
        return True
    if s == "false":
        return False
    if re.match(r"^-?\d+$", s):
        return int(s)
    if s[:1] == '"':
        try:
            val = json.loads(s)
        except ValueError:
            val = None
        if not isinstance(val, str):
            raise ContentError("%s: a bad double-quoted string: %s" % (where, s), fix="close the quotes, or write the value without quotes")
        return val
    if s[:1] == "'":
        if len(s) < 2 or s[-1] != "'":
            raise ContentError("%s: a bad single-quoted string: %s" % (where, s), fix="close the quotes, or write the value without quotes")
        return s[1:-1].replace("''", "'")
    return s


def _block_map(block, where):
    """A block map of `k: v` lines; a `k:` line with nothing after it opens ONE more level of the same
    (dev #853: `labels:` holds `meta:` and `groups:`, each a map of key to display label). `block` is
    [(line number, indent, stripped line)]."""
    base = min(ind for _n, ind, _b in block)
    d = {}
    i = 0
    while i < len(block):
        n, ind, b = block[i]
        mm = re.match(r"^([^:]+):\s+(.*)$", b)
        head = re.match(r"^([^:]+):\s*$", b)
        if ind != base or b.startswith("- ") or not (mm or head):
            raise ContentError("%s:%d: cannot read this nested line: %s" % (where, n, b), fix="write nested values as indented key: value lines")
        k2 = (mm or head).group(1).strip()
        if k2 in d:
            raise ContentError("%s:%d: duplicate key '%s'" % (where, n, k2), fix="remove the repeated key")
        i += 1
        if mm:
            d[k2] = _scalar(mm.group(2), where)
            continue
        sub = []
        while i < len(block) and block[i][1] > base:
            sub.append(block[i])
            i += 1
        if not sub:
            raise ContentError("%s:%d: cannot read this nested line: %s" % (where, n, b), fix="write nested values as indented key: value lines")
        sbase = min(x[1] for x in sub)
        inner = {}
        for sn, sind, sb in sub:
            sm = re.match(r"^([^:]+):\s+(.*)$", sb)
            if sind != sbase or sb.startswith("- ") or not sm:
                raise ContentError("%s:%d: cannot read this nested line: %s" % (where, sn, sb), fix="write nested values as indented key: value lines")
            k3 = sm.group(1).strip()
            if k3 in inner:
                raise ContentError("%s:%d: duplicate key '%s'" % (where, sn, k3), fix="remove the repeated key")
            inner[k3] = _scalar(sm.group(2), where)
        d[k2] = inner
    return d


def parse_front_matter(text, where):
    """Return (meta dict, body text). A subset of YAML: `key: scalar`, `key: [a, b]`, a block
    list of `- item`, or a one-level block map of `k: v`. A duplicate key or a line it cannot
    read is refused with the file and line number. No front matter means ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        raise ContentError("%s: front matter opens with --- but never closes" % where, fix="add a closing --- line after the front matter")
    meta = {}
    i = 1
    while i < end:
        raw = lines[i]
        lineno = i + 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*):(?:\s+(.*)|\s*)$", raw)
        if not m:
            raise ContentError("%s:%d: cannot read this front matter line: %s" % (where, lineno, raw), fix="write each front matter line as key: value")
        key, val = m.group(1), m.group(2)
        if key in meta:
            raise ContentError("%s:%d: duplicate front matter key '%s'" % (where, lineno, key), fix="remove the repeated key")
        i += 1
        if val is None or not val.strip():
            block = []
            while i < end and (lines[i].startswith("  ") or lines[i].startswith("\t") or
                               not lines[i].strip()):
                if lines[i].strip():
                    block.append((i + 1, len(lines[i]) - len(lines[i].lstrip(" \t")), lines[i].strip()))
                i += 1
            if not block:
                meta[key] = ""
            elif all(b.startswith("- ") or b == "-" for _n, _ind, b in block):
                meta[key] = [_scalar(b[2:], where) for _n, _ind, b in block]
            else:
                meta[key] = _block_map(block, where)
        elif val.startswith("["):
            if not val.rstrip().endswith("]"):
                raise ContentError("%s:%d: a list opens with [ but does not close" % (where, lineno), fix="close the list with ]")
            inner = val.strip()[1:-1]
            meta[key] = [_scalar(p, where) for p in _split_flow(inner, where) if p != ""]
        else:
            meta[key] = _scalar(val, where)
    return meta, "\n".join(lines[end + 1:])


def _check_keys(meta, allowed, where):
    for k in meta:
        if k not in allowed:
            raise ContentError("%s: unknown front matter key '%s' (allowed: %s)"
                               % (where, k, ", ".join(allowed)), fix="remove the key, or use one of the allowed keys named here")


def _need_str(meta, key, where, required=False):
    if key not in meta:
        if required:
            raise ContentError("%s: front matter '%s' is required" % (where, key), fix="add the required key to the front matter")
        return None
    v = meta[key]
    if not isinstance(v, str) or not v.strip():
        raise ContentError("%s: front matter '%s' must be a non-empty string" % (where, key), fix="write a non-empty text value for that key")
    return v


def _str_list(meta, key, where):
    v = meta.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise ContentError("%s: front matter '%s' must be a list of strings" % (where, key), fix="write the value as a list of text items, such as [a, b]")
    return v


def meta_text(v):
    """A front matter value as display text."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)
