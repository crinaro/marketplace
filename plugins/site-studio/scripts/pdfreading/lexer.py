"""lexer.py -- the PDF tokenizer and object parser: names, strings, numbers, arrays, dictionaries and `n g R` references.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
from pdfreading.values import Name, Op, Ref


_WS = b" \t\r\n\f\x00"
_DELIM = b"()<>[]{}/%"
_NUM_RE = re.compile(rb"^[+-]?(\d+\.?\d*|\.\d+)$")


class Lexer(object):
    def __init__(self, data, pos=0):
        self.d = data
        self.i = pos
        self.n = len(data)

    def _skip(self):
        d, n = self.d, self.n
        while self.i < n:
            c = d[self.i:self.i + 1]
            if c in (b" ", b"\t", b"\r", b"\n", b"\f", b"\x00"):
                self.i += 1
            elif c == b"%":
                while self.i < n and d[self.i:self.i + 1] not in (b"\r", b"\n"):
                    self.i += 1
            else:
                break

    def token(self):
        """(kind, value): kind in num name str op [ ] << >> eof."""
        self._skip()
        d, n = self.d, self.n
        if self.i >= n:
            return ("eof", None)
        c = d[self.i:self.i + 1]
        if c == b"/":
            j = self.i + 1
            while j < n and d[j:j + 1] not in _WS and d[j:j + 1] not in _DELIM:
                j += 1
            raw = d[self.i + 1:j]
            self.i = j
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
            return ("name", Name(raw.decode("latin-1")))
        if c == b"(":
            return ("str", self._lit_string())
        if c == b"<":
            if d[self.i + 1:self.i + 2] == b"<":
                self.i += 2
                return ("<<", None)
            j = d.find(b">", self.i)
            if j < 0:
                j = n
            hx = re.sub(rb"[^0-9A-Fa-f]", b"", d[self.i + 1:j])
            if len(hx) % 2:
                hx += b"0"
            self.i = j + 1
            return ("str", bytes.fromhex(hx.decode("ascii")))
        if c == b">":
            if d[self.i + 1:self.i + 2] == b">":
                self.i += 2
                return (">>", None)
            self.i += 1
            return self.token()
        if c in (b"[", b"]"):
            self.i += 1
            return (c.decode(), None)
        if c in (b"{", b"}", b")"):
            self.i += 1
            return self.token()
        j = self.i
        while j < n and d[j:j + 1] not in _WS and d[j:j + 1] not in _DELIM:
            j += 1
        word = d[self.i:j]
        self.i = j
        if _NUM_RE.match(word):
            s = word.decode("ascii")
            return ("num", float(s) if "." in s else int(s))
        return ("op", Op(word.decode("latin-1")))

    def _lit_string(self):
        d, n = self.d, self.n
        i = self.i + 1
        depth = 1
        out = bytearray()
        while i < n:
            c = d[i]
            if c == 0x5C:  # backslash
                i += 1
                if i >= n:
                    break
                e = d[i]
                simple = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 40, 0x29: 41,
                          0x5C: 92}
                if e in simple:
                    out.append(simple[e])
                elif 0x30 <= e <= 0x37:
                    j = i
                    v = 0
                    while j < n and j < i + 3 and 0x30 <= d[j] <= 0x37:
                        v = v * 8 + d[j] - 0x30
                        j += 1
                    out.append(v & 0xFF)
                    i = j - 1
                elif e == 13:
                    if d[i + 1:i + 2] == b"\n":
                        i += 1
                elif e == 10:
                    pass
                else:
                    out.append(e)
            elif c == 0x28:
                depth += 1
                out.append(c)
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
                out.append(c)
            else:
                out.append(c)
            i += 1
        self.i = i
        return bytes(out)


def parse_value(lx, first=None):
    """One object from the lexer, recognising `n g R` references."""
    kind, val = first if first is not None else lx.token()
    if kind in ("name", "str"):
        return val
    if kind == "num":
        if isinstance(val, int) and val >= 0:
            save = lx.i
            k2, v2 = lx.token()
            if k2 == "num" and isinstance(v2, int) and v2 >= 0:
                k3, v3 = lx.token()
                if k3 == "op" and v3 == "R":
                    return Ref(val, v2)
            lx.i = save
        return val
    if kind == "[":
        arr = []
        while True:
            t = lx.token()
            if t[0] in ("]", "eof"):
                return arr
            if t[0] in (">>",):
                continue
            arr.append(parse_value(lx, t))
    if kind == "<<":
        dic = {}
        while True:
            t = lx.token()
            if t[0] in (">>", "eof"):
                return dic
            if t[0] != "name":
                continue
            v = lx.token()
            if v[0] in (">>", "eof"):
                return dic
            dic[str(t[1])] = parse_value(lx, v)
    if kind == "op":
        if val == "true":
            return True
        if val == "false":
            return False
        if val == "null":
            return None
        return val
    return None
