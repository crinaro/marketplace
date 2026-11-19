"""fonts.py -- decoding one font resource: ToUnicode, standard encodings, glyph names, and the glyph widths the word-gap measure needs.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
from pdfreading.cmap import CMap
from pdfreading.values import Name, PdfUnsupported


_BASE14 = ("Helvetica", "Times", "Courier", "Arial", "TimesNewRoman", "CourierNew")
_GLYPH_ASCII = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quotesingle": "'", "parenleft": "(", "parenright": ")", "asterisk": "*",
    "plus": "+", "comma": ",", "hyphen": "-", "minus": "-", "period": ".", "slash": "/",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "colon": ":", "semicolon": ";", "less": "<",
    "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_", "grave": "`",
    "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~", "bullet": "\u2022",
    "endash": "\u2013", "emdash": "\u2014", "quoteright": "\u2019", "quoteleft": "\u2018",
    "quotedblleft": "\u201c", "quotedblright": "\u201d", "fi": "fi", "fl": "fl",
}


def glyph_to_unicode(name):
    if len(name) == 1 and name.isalpha() and name.isascii():
        return name
    if name in _GLYPH_ASCII:
        return _GLYPH_ASCII[name]
    m = re.match(r"^uni([0-9A-Fa-f]{4})$", name)
    if m:
        return chr(int(m.group(1), 16))
    return None


def _base_table(enc):
    t = {}
    if enc == "WinAnsiEncoding":
        for c in range(0x20, 0x100):
            try:
                t[c] = bytes([c]).decode("cp1252")
            except UnicodeDecodeError:
                pass
        t.pop(0x7F, None)
    elif enc == "MacRomanEncoding":
        for c in range(0x20, 0x100):
            try:
                t[c] = bytes([c]).decode("mac_roman")
            except UnicodeDecodeError:
                pass
        t.pop(0x7F, None)
    elif enc == "StandardEncoding":
        for c in range(0x20, 0x7F):
            t[c] = chr(c)
        t[0x27], t[0x60] = "\u2019", "\u2018"
    else:
        return None
    return t


class Font(object):
    """A decoder for one font resource: decode(bytes) -> (text, unmapped_count)."""

    def __init__(self, doc, fdict):
        self.problem = None
        self.cmap = None
        self.table = None
        self.composite = False
        self.widths = None      # code -> width in 1/1000 em, or None when unknown (F10)
        self.default_width = 0
        f = doc.res(fdict)
        if not isinstance(f, dict):
            self.problem = "a font resource is missing"
            return
        sub = str(doc.res(f.get("Subtype")) or "")
        self.composite = sub == "Type0"
        try:
            self._load_widths(doc, f, sub)
        except Exception:
            self.widths = None  # widths only refine word breaks; unknown is the safe answer
        tu = f.get("ToUnicode")
        if tu is not None:
            sdic, raw = doc.stream_of(tu)
            if sdic is not None:
                try:
                    self.cmap = CMap(doc.decode_stream(sdic, raw))
                except PdfUnsupported as e:
                    self.problem = "ToUnicode: %s" % e
                except Exception:
                    self.problem = "ToUnicode CMap unreadable"
        if self.cmap is not None and self.problem is None:
            return
        if self.composite:
            if self.problem is None:
                self.problem = "composite font has no ToUnicode CMap"
            return
        # simple font, standard encoding
        enc = doc.res(f.get("Encoding"))
        base = str(doc.res(f.get("BaseFont")) or "")
        base = base.split("+", 1)[-1]
        is14 = any(base.startswith(b) for b in _BASE14)
        diffs = None
        if isinstance(enc, dict):
            diffs = doc.res(enc.get("Differences"))
            enc = doc.res(enc.get("BaseEncoding"))
        enc = str(enc) if enc is not None else None
        if enc is None and is14 and sub in ("Type1", "TrueType", "MMType1"):
            enc = "StandardEncoding" if sub != "TrueType" else None
        table = _base_table(enc) if enc else None
        if table is None and diffs is not None and is14:
            table = _base_table("StandardEncoding")
        if table is None:
            if diffs is None:
                self.problem = (self.problem or "") or \
                    "simple font has no ToUnicode and no standard encoding"
                return
            table = {}
        if isinstance(diffs, list):
            code = 0
            for item in diffs:
                item = doc.res(item)
                if isinstance(item, int):
                    code = item
                elif isinstance(item, Name):
                    u = glyph_to_unicode(str(item))
                    if u is None:
                        table.pop(code, None)
                    else:
                        table[code] = u
                    code += 1
        self.table = table
        self.problem = None

    def _load_widths(self, doc, f, sub):
        if sub == "Type0":
            enc = doc.res(f.get("Encoding"))
            desc = doc.res(f.get("DescendantFonts"))
            if not (isinstance(enc, str) and enc.startswith("Identity") and isinstance(desc, list)
                    and desc):
                return
            d = doc.res(desc[0])
            if not isinstance(d, dict):
                return
            dw = doc.res(d.get("DW"))
            self.default_width = float(dw) if isinstance(dw, (int, float)) else 1000.0
            w = {}
            arr = doc.res(d.get("W")) or []
            i = 0
            while i < len(arr):
                first = doc.res(arr[i])
                nxt = doc.res(arr[i + 1]) if i + 1 < len(arr) else None
                if isinstance(nxt, list):
                    for k, v in enumerate(nxt):
                        v = doc.res(v)
                        if isinstance(v, (int, float)):
                            w[int(first) + k] = float(v)
                    i += 2
                elif isinstance(nxt, (int, float)) and i + 2 < len(arr):
                    v = doc.res(arr[i + 2])
                    if isinstance(v, (int, float)) and int(nxt) - int(first) <= 65535:
                        for c in range(int(first), int(nxt) + 1):
                            w[c] = float(v)
                    i += 3
                else:
                    break
            self.widths = w
            return
        ws = doc.res(f.get("Widths"))
        fc = doc.res(f.get("FirstChar"))
        if isinstance(ws, list) and isinstance(fc, int):
            fd = doc.res(f.get("FontDescriptor"))
            mw = doc.res(fd.get("MissingWidth")) if isinstance(fd, dict) else None
            self.default_width = float(mw) if isinstance(mw, (int, float)) else 0.0
            self.widths = {}
            for k, v in enumerate(ws):
                v = doc.res(v)
                if isinstance(v, (int, float)):
                    self.widths[fc + k] = float(v)

    def advance(self, s):
        """The summed glyph widths of the string `s`, in 1/1000 em, or None when unknown."""
        if self.widths is None or self.problem:
            return None
        if self.composite:
            if len(s) % 2:
                return None
            return sum(self.widths.get((s[i] << 8) | s[i + 1], self.default_width)
                       for i in range(0, len(s), 2))
        return sum(self.widths.get(b, self.default_width) for b in s)

    def decode(self, s):
        if self.problem:
            return "\ufffd" * max(1, len(s)), max(1, len(s))
        out, bad = [], 0
        if self.cmap is not None:
            for code in self.cmap.split(s, 2 if self.composite else 1):
                u = self.cmap.map.get(code) if code is not None else None
                if not u or "\ufffd" in u:
                    out.append("\ufffd")
                    bad += 1
                else:
                    out.append(u)
            return "".join(out), bad
        for b in s:
            u = self.table.get(b)
            if u is None:
                out.append("\ufffd")
                bad += 1
            else:
                out.append(u)
        return "".join(out), bad
