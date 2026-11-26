"""Set or remove one key of a JSON document's TEXT, leaving every other byte as it was (jobsearch 0.95.0; dev 1071, review item 11).

`json.dump(cfg, ensure_ascii=False)` rewrites a whole `config.json` to say one thing: every `\\u2014` escape becomes a literal
dash, and a file laid out another way is re-laid out. `--set-guide` and `--set-mode` change one key of it, so they edit the text:

* `set_path(text, path, value)` replaces the member at `path` (a tuple of keys), or appends it (and any missing objects on the
  way) after the last member of its object. A replaced member keeps its position; the new value is laid out with two-space
  indent at the member's own depth, and nothing outside the member's own span changes.
* `remove_path(text, path)` removes the member and its separator; a path that is not there returns `text` unchanged.

Both return the new text and **prove it before returning**: the result must parse to the document the same operation gives on the
parsed original, key order included, else `ValueError` (the caller writes nothing). The text must be a JSON object; anything
the scan cannot follow is a `ValueError`, never a guess. Standard library only. Python 3.9+.
"""

import json
import json.decoder
import re

class REMOVE:
    """The `value` that means "remove the member" (the class itself is the sentinel; it is never instantiated)."""


_WS = " \t\r\n"


def _ws(t, i):
    while i < len(t) and t[i] in _WS:
        i += 1
    return i


def _indent(t, pos):
    """The leading whitespace of the line holding `pos`."""
    return re.match(r"[ \t]*", t[t.rfind("\n", 0, pos) + 1:]).group()


def _members(t, start):
    """([(key, key_start, value_start, value_end)], index of the closing brace) of the object at `t[start]`."""
    out, i = [], _ws(t, start + 1)
    while t[i] != "}":
        ks = i
        key, i = json.decoder.scanstring(t, i + 1)
        i = _ws(t, i)
        if t[i] != ":":
            raise ValueError("expected ':' at %d" % i)
        vs = _ws(t, i + 1)
        ve = json.JSONDecoder().raw_decode(t, vs)[1]
        out.append((key, ks, vs, ve))
        i = _ws(t, ve)
        if t[i] == ",":
            i = _ws(t, i + 1)
    return out, i


def _dump(value, indent):
    return json.dumps(value, indent=2, ensure_ascii=False).replace("\n", "\n" + indent)


def _edit(t, start, path, value):
    mem, close = _members(t, start)
    hit = next((m for m in mem if m[0] == path[0]), None)
    if hit and len(path) > 1:
        if t[hit[2]] != "{":
            raise ValueError("%r is not an object" % path[0])
        return _edit(t, hit[2], path[1:], value)
    if hit:
        _k, ks, vs, ve = hit
        if value is not REMOVE:
            return t[:vs] + _dump(value, _indent(t, ks)) + t[ve:]
        n = mem.index(hit)
        if n + 1 < len(mem):
            return t[:ks] + t[mem[n + 1][1]:]
        return t[:mem[n - 1][3]] + t[ve:] if n else t[:start + 1] + t[close:]
    if value is REMOVE:
        return t
    for key in reversed(path[1:]):          # the objects on the way that are not there yet
        value = {key: value}
    base = _indent(t, mem[0][1]) if mem else _indent(t, start) + "  "
    member = "%s: %s" % (json.dumps(path[0], ensure_ascii=False), _dump(value, base))
    if mem:
        end = mem[-1][3]
        return t[:end] + ",\n" + base + member + t[end:]
    return t[:start] + "{\n" + base + member + "\n" + _indent(t, start) + "}" + t[close + 1:]


def _apply(doc, path, value):
    for k in path[:-1]:
        if value is REMOVE and not isinstance(doc.get(k), dict):
            return
        doc = doc.setdefault(k, {})
    if value is REMOVE:
        doc.pop(path[-1], None)
    else:
        doc[path[-1]] = value


def _splice(text, path, value):
    path = tuple(path)
    try:
        start = _ws(text, 0)
        if not path or text[start] != "{":
            raise ValueError("a JSON object and a non-empty path are required")
        out = _edit(text, start, path, value)
        want = json.loads(text)
        _apply(want, path, value)
        if json.dumps(json.loads(out)) != json.dumps(want):
            raise ValueError("the edit did not give the document asked for")
    except (IndexError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as e:
        raise ValueError("cannot edit this JSON text in place: %s: %s" % (type(e).__name__, e))
    return out


def set_path(text, path, value):
    return _splice(text, path, value)


def remove_path(text, path):
    return _splice(text, path, REMOVE)
