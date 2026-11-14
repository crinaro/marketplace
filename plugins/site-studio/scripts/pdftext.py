#!/usr/bin/env python3
"""pdftext.py -- read the TEXT of a PDF, and say honestly whether it was READ (dev #835, design
section 7.1). Python 3.9, stdlib only. Read-only: it never writes a file.

WHY THIS EXISTS. The privacy gate (check_site.py) must find a phone number or an address inside a
published PDF. Chrome's `printToPDF` writes its text as glyph ids -- `<0026...> Tj` -- inside
Flate streams. Successfully inflating the stream is therefore NOT reading: the text never
appears. A reader that inflates and greps would report a clean PDF that was never examined. So this
module decides, by OUTCOME, one of two things about a PDF: READ, or NOT READ. There is no third
answer and no "mostly".

WHAT "READ" MEANS (design 7.1, rule 1 -- the only rule implemented here)
  DECODED COMPLETELY. Every text-showing operator (Tj, TJ, ' and ") in every content stream --
  page content and Form XObjects reached by `Do` -- maps through its font's ToUnicode CMap
  (bfchar / bfrange), or is a literal string in a simple font whose encoding is a standard one
  (WinAnsi, MacRoman, Standard; a base-14 Type1 font with no /Encoding is Standard). No code is
  left unmapped (a destination of U+FFFD or nothing counts as unmapped), and the decoded text is
  non-empty on every page that has a text operator. A PDF with no text operator at all (an
  image-only scan) is NOT READ. Anything else is NOT READ, each with a stated reason: an encrypted
  file, an unmapped glyph, an unsupported stream filter, a font this module cannot decode, a parse
  failure. This module never raises on a hostile or damaged file; it returns NOT READ.

  Rule 2 of the design (a PDF the plugin printed itself must also be proven against its source
  text, at least 95% of the words) is a comparison the caller makes with `word_coverage()`, since
  it needs the resume page and the sidecar that only check_site.py has.

M8 -- WHAT HAS AND HAS NOT BEEN VALIDATED (named change M8, dev #835). Rule 1 has been validated
ONLY against generator PDFs: tests/test_pdftext.py writes PDFs that mimic Chrome's structure (a
Type0 font, Identity-H, a ToUnicode CMap) with plain Python, and they are not Chrome's output. Until
`tests/test_privacy_pdf.py` (phase 2) passes on real Chrome output, "decoded completely" is proven
against our own imitation of Chrome. Whether every Chrome version embeds ToUnicode is also not
established here; phase 2 records the Chrome version in the review packet so a version change
shows. Where Chrome did not embed a map, this module's answer is NOT READ, which is the safe
direction.

KNOWN LIMITS (all of them fail toward NOT READ or toward a wider scan, never toward "clean")
  * Word boundaries come from positioning operators and, where the font's glyph widths are
    known, from geometry (F10, below). A `Td`/`TD` move on the same baseline (ty == 0) that leaves
    a gap under JOIN_GAP_EM of an em after the previous run's own advance is NOT a word break, so
    a kerned pair that Chrome writes as two runs ("T" + "estfield") reads as one word. Every other
    move (a large gap, a baseline change, `Tm`, `T*`, `ET`, or a font whose widths are unknown) is
    still a break, so a word that is split anywhere else reads as two. `search_forms()` also
    offers the text with ALL whitespace removed, and the privateTerms scan uses both.
  * Annotation /Contents and form-field values are appended to the text; outline (bookmark)
    titles, embedded files and JavaScript are not read. Text drawn as vector outlines or as an
    image is invisible here by nature (design 7.1: images are covered by the judgement half).
  * Only Flate, ASCIIHex and ASCII85 stream filters, with no predictor, are decoded for content,
    ObjStm and CMap streams; any other filter there is NOT READ.

F10 (dev #835, measured 2026-11-12 on Chrome 157). Chrome writes each text run as `<glyphs> Tj`
and starts the next run with `tx 0 Td`. In the PDF content model `Td` is relative to the START of
the previous line, so `tx` is the previous run's ADVANCE, not the gap after it: a kerned "T" at 16 pt
is followed by `8 0 Td` (0.5 em), which a threshold on |tx| alone could never tell from a word
break. The reader therefore measures the gap, `tx - advance(previous run)`, from the font's own
widths (/W and /DW for a CID font, /Widths for a simple one); the advance is the sum of the glyph
widths x font size, less TJ adjustments. Chrome puts real space glyphs (code 3, mapped to U+0020)
inside its runs, so a gap of at most JOIN_GAP_EM is a kern or rounding. JOIN_GAP_EM = 0.15 em: a
Latin word space is 0.22 to 0.33 em (Helvetica 0.278, Times 0.25, Georgia 0.24), kerning only
tightens (gap <= 0) and tracking added by CSS is about 0.1 em at most. Where the widths are unknown
the old rule stands (a move is a break). Not modelled, and failing toward a break: Tc, Tw and Tz.

METADATA. `read_pdf()` also returns the document /Info strings and a few XMP fields (Author,
Creator, Producer, Title, Subject, Keywords, Company; dc:creator, dc:title, pdf:Producer,
xmp:CreatorTool), because the privacy family judges them (check_site.py).

CLI: python3 pdftext.py <file.pdf> [--json]   prints READ / NOT READ and the reason(s).
"""
import json
import re
import sys
import unicodedata
import zlib
from collections import Counter

MAX_STREAM = 64 * 1024 * 1024
MAX_DEPTH = 8
JOIN_GAP_EM = 0.15

# Ligature code points that normalise_text() folds by casefolding (U+FB00..U+FB06 -> ff fi fl ffi
# ffl st st). search_forms() folds exactly these and nothing else, so case is left as printed.
_LIGATURES = {c: chr(c).casefold() for c in range(0xFB00, 0xFB07)}


class PdfUnsupported(Exception):
    """A stream or construct this module declines to decode (becomes a NOT READ reason)."""


class Name(str):
    """A PDF name object (kept distinct from string objects, which are bytes)."""


class Ref(object):
    __slots__ = ("num", "gen")

    def __init__(self, num, gen):
        self.num, self.gen = num, gen


class Op(str):
    """A bare keyword / content-stream operator."""


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


_OBJ_RE = re.compile(rb"(?<![0-9])(\d{1,10})[ \t\r\n]+(\d{1,5})[ \t\r\n]+obj\b")


class Document(object):
    def __init__(self, data):
        self.data = data
        self.objs = {}       # num -> (value, raw stream bytes or None)
        self.trailers = []
        self.problems = []
        self._load()

    def _load(self):
        data = self.data
        for m in _OBJ_RE.finditer(data):
            num = int(m.group(1))
            lx = Lexer(data, m.end())
            try:
                val = parse_value(lx)
            except Exception:
                continue
            raw = None
            if isinstance(val, dict):
                save = lx.i
                k, v = lx.token()
                if k == "op" and v == "stream":
                    s = lx.i
                    if data[s:s + 2] == b"\r\n":
                        s += 2
                    elif data[s:s + 1] in (b"\n", b"\r"):
                        s += 1
                    length = val.get("Length")
                    end = None
                    if isinstance(length, int) and length >= 0 and \
                            re.match(rb"[ \t\r\n]*endstream", data[s + length:s + length + 12]):
                        end = s + length
                    if end is None:
                        end = data.find(b"endstream", s)
                        if end < 0:
                            end = len(data)
                        while end > s and data[end - 1:end] in (b"\r", b"\n"):
                            end -= 1
                            if data[end:end + 2] == b"\r\n":
                                break
                    raw = data[s:end]
                else:
                    lx.i = save
            self.objs[num] = (val, raw)
        for m in re.finditer(rb"\btrailer\b", data):
            try:
                v = parse_value(Lexer(data, m.end()))
            except Exception:
                continue
            if isinstance(v, dict):
                self.trailers.append(v)
        for num in list(self.objs):
            val, raw = self.objs[num]
            if isinstance(val, dict) and raw is not None and val.get("Type") == "XRef":
                self.trailers.append(val)
        for num in list(self.objs):
            val, raw = self.objs[num]
            if isinstance(val, dict) and raw is not None and val.get("Type") == "ObjStm":
                try:
                    self._expand_objstm(val, raw)
                except PdfUnsupported as e:
                    self.problems.append("object stream %d: %s" % (num, e))
                except Exception:
                    self.problems.append("object stream %d unreadable" % num)

    def _expand_objstm(self, dic, raw):
        body = self.decode_stream(dic, raw)
        n = int(self.res(dic.get("N")) or 0)
        first = int(self.res(dic.get("First")) or 0)
        lx = Lexer(body)
        pairs = []
        for _ in range(n):
            a, b = lx.token(), lx.token()
            if a[0] != "num" or b[0] != "num":
                break
            pairs.append((int(a[1]), int(b[1])))
        for num, off in pairs:
            if num in self.objs:
                continue
            try:
                self.objs[num] = (parse_value(Lexer(body, first + off)), None)
            except Exception:
                continue

    def res(self, o, depth=0):
        while isinstance(o, Ref) and depth < 32:
            ent = self.objs.get(o.num)
            o = ent[0] if ent else None
            depth += 1
        return o

    def stream_of(self, o):
        """(dict, raw) for a stream object reference or object, else (None, None)."""
        if isinstance(o, Ref):
            ent = self.objs.get(o.num)
            if ent and ent[1] is not None and isinstance(ent[0], dict):
                return ent[0], ent[1]
        return None, None

    def decode_stream(self, dic, raw):
        filt = self.res(dic.get("Filter"))
        parms = self.res(dic.get("DecodeParms", dic.get("DP")))
        filters = [self.res(f) for f in filt] if isinstance(filt, list) else \
            ([filt] if filt is not None else [])
        plist = [self.res(p) for p in parms] if isinstance(parms, list) else \
            ([parms] if parms is not None else [])
        out = raw
        for idx, f in enumerate(filters):
            p = self.res(plist[idx]) if idx < len(plist) else None
            if isinstance(p, dict) and (self.res(p.get("Predictor")) or 1) > 1:
                raise PdfUnsupported("a stream uses a predictor (unsupported)")
            f = str(f)
            if f in ("FlateDecode", "Fl"):
                dobj = zlib.decompressobj()
                try:
                    out = dobj.decompress(out, MAX_STREAM)
                except zlib.error:
                    raise PdfUnsupported("a Flate stream does not inflate")
            elif f in ("ASCIIHexDecode", "AHx"):
                hx = re.sub(rb"[^0-9A-Fa-f]", b"", out.split(b">")[0])
                if len(hx) % 2:
                    hx += b"0"
                out = bytes.fromhex(hx.decode("ascii"))
            elif f in ("ASCII85Decode", "A85"):
                import base64
                t = out.strip()
                if t.startswith(b"<~"):
                    t = t[2:]
                t = t.split(b"~>")[0]
                try:
                    out = base64.a85decode(t)
                except Exception:
                    raise PdfUnsupported("an ASCII85 stream is malformed")
            else:
                raise PdfUnsupported("stream filter %s is not decoded" % f)
        return out


# ---------------------------------------------------------------------------------------------
# ToUnicode CMaps
# ---------------------------------------------------------------------------------------------

_HEX = rb"<([0-9A-Fa-f\s]*)>"


def _u16(hexbytes):
    b = bytes.fromhex(re.sub(rb"\s", b"", hexbytes).decode("ascii") or "")
    if len(b) % 2:
        b += b"\x00"
    try:
        return b.decode("utf-16-be")
    except UnicodeDecodeError:
        return "\ufffd"


class CMap(object):
    def __init__(self, data):
        self.map = {}
        self.lens = set()
        for blk in re.findall(rb"begincodespacerange(.*?)endcodespacerange", data, re.S):
            for lo, _hi in re.findall(_HEX + rb"\s*" + _HEX, blk):
                lo = re.sub(rb"\s", b"", lo)
                if lo:
                    self.lens.add(len(lo) // 2)
        for blk in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
            for src, dst in re.findall(_HEX + rb"\s*" + _HEX, blk):
                s = re.sub(rb"\s", b"", src)
                if s:
                    self.map[int(s, 16)] = _u16(dst)
        for blk in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
            for m in re.finditer(_HEX + rb"\s*" + _HEX + rb"\s*(?:" + _HEX + rb"|\[(.*?)\])", blk, re.S):
                lo_s, hi_s = re.sub(rb"\s", b"", m.group(1)), re.sub(rb"\s", b"", m.group(2))
                if not lo_s or not hi_s:
                    continue
                lo, hi = int(lo_s, 16), int(hi_s, 16)
                if hi < lo or hi - lo > 0xFFFF:
                    continue
                if m.group(3) is not None:
                    base = _u16(m.group(3))
                    for k in range(hi - lo + 1):
                        if base:
                            self.map[lo + k] = base[:-1] + chr(ord(base[-1]) + k) \
                                if ord(base[-1]) + k < 0x110000 else "\ufffd"
                        else:
                            self.map[lo + k] = ""
                else:
                    arr = re.findall(_HEX, m.group(4) or b"")
                    for k, a in enumerate(arr[:hi - lo + 1]):
                        self.map[lo + k] = _u16(a)

    def split(self, s, default_len):
        """Split a string into code ints; a trailing partial unit comes back as None."""
        lens = sorted(self.lens) or [default_len]
        out = []
        i = 0
        while i < len(s):
            if len(lens) == 1:
                ln = lens[0]
                if i + ln <= len(s):
                    out.append(int.from_bytes(s[i:i + ln], "big"))
                    i += ln
                else:
                    out.append(None)
                    break
            else:
                # several code lengths: prefer the longest one whose code is mapped
                for ln in sorted(lens, reverse=True):
                    if i + ln <= len(s) and int.from_bytes(s[i:i + ln], "big") in self.map:
                        out.append(int.from_bytes(s[i:i + ln], "big"))
                        i += ln
                        break
                else:
                    out.append(None)
                    i += min(lens)
        return out


# ---------------------------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------------------------
# Content streams and pages
# ---------------------------------------------------------------------------------------------

class _Acc(object):
    def __init__(self):
        self.text = []
        self.text_ops = 0
        self.unmapped = 0
        self.reasons = []

    def note(self, why):
        if why not in self.reasons:
            self.reasons.append(why)


def _run_content(doc, data, resources, acc, depth, font_cache):
    if depth > MAX_DEPTH:
        acc.note("content nesting too deep")
        return
    res = doc.res(resources) if resources is not None else {}
    res = res if isinstance(res, dict) else {}
    fonts = doc.res(res.get("Font")) or {}
    xobjs = doc.res(res.get("XObject")) or {}
    lx = Lexer(data)
    stack = []
    font = None
    font_name = None
    size = None
    adv = None      # text-space advance of what was shown since the line start (None: unknown)
    while True:
        kind, val = lx.token()
        if kind == "eof":
            break
        if kind in ("num", "name", "str"):
            stack.append(val)
            continue
        if kind == "[":
            arr = []
            while True:
                t = lx.token()
                if t[0] in ("]", "eof"):
                    break
                if t[0] in ("num", "str", "name"):
                    arr.append(t[1])
            stack.append(arr)
            continue
        if kind == "<<":
            parse_value(lx, ("<<", None))
            stack.append(None)
            continue
        if kind != "op":
            continue
        op = str(val)
        if op == "BI":
            m = re.compile(rb"[ \t\r\n]ID[ \t\r\n]").search(data, lx.i)
            if not m:
                break
            e = re.compile(rb"[ \t\r\n]EI(?=[ \t\r\n]|$)").search(data, m.end())
            lx.i = e.end() if e else len(data)
            stack = []
            continue
        if op == "Tf":
            font_name = str(stack[-2]) if len(stack) >= 2 and isinstance(stack[-2], Name) else None
            size = float(stack[-1]) if stack and isinstance(stack[-1], (int, float)) else None
            fd = fonts.get(font_name) if font_name else None
            if fd is None:
                font = None
            else:
                key = fd.num if isinstance(fd, Ref) else id(fd)
                if key not in font_cache:
                    font_cache[key] = Font(doc, fd)
                font = font_cache[key]
        elif op in ("Tj", "'", '"', "TJ"):
            acc.text_ops += 1
            parts = []
            if op == "TJ" and stack and isinstance(stack[-1], list):
                for el in stack[-1]:
                    if isinstance(el, bytes):
                        parts.append(el)
                    elif isinstance(el, (int, float)):
                        if el < -250:
                            parts.append(None)  # a gap wide enough to be a word space
                        # a smaller number is a kern: it never breaks a word (F10)
                        if adv is not None and size:
                            adv -= el / 1000.0 * size
            elif stack and isinstance(stack[-1], bytes):
                parts.append(stack[-1])
            for p in parts:
                if p is not None:
                    w = font.advance(p) if font is not None and size else None
                    adv = None if (w is None or adv is None) else adv + w / 1000.0 * size
            if op in ("'", '"'):
                acc.text.append(" ")
                adv = None
            for p in parts:
                if p is None:
                    acc.text.append(" ")
                elif font is None:
                    acc.unmapped += max(1, len(p))
                    acc.note("text shown in a font resource that is missing (%s)" % font_name)
                    acc.text.append("\ufffd")
                else:
                    t, bad = font.decode(p)
                    acc.text.append(t)
                    if bad:
                        acc.unmapped += bad
                        acc.note("%d glyph code(s) unmapped in font %s%s" % (
                            bad, font_name, " (%s)" % font.problem if font.problem else ""))
        elif op in ("Td", "TD"):
            tx = stack[-2] if len(stack) >= 2 and isinstance(stack[-2], (int, float)) else None
            ty = stack[-1] if stack and isinstance(stack[-1], (int, float)) else None
            joined = (tx is not None and ty is not None and size and adv is not None
                      and abs(ty) < 0.001 * size and tx - adv <= JOIN_GAP_EM * size)
            if not joined:
                acc.text.append(" ")
            adv = 0.0       # the new line starts here, whatever the old one was
        elif op in ("Tm", "BT"):
            if op == "Tm":
                acc.text.append(" ")
            adv = 0.0
        elif op in ("T*", "ET"):
            acc.text.append(" ")
            adv = None
        elif op == "Do":
            nm = str(stack[-1]) if stack and isinstance(stack[-1], Name) else None
            xo = xobjs.get(nm) if nm else None
            sdic, raw = doc.stream_of(xo)
            if sdic is not None and doc.res(sdic.get("Subtype")) == "Form":
                try:
                    _run_content(doc, doc.decode_stream(sdic, raw), sdic.get("Resources", resources),
                                 acc, depth + 1, font_cache)
                except PdfUnsupported as e:
                    acc.note("form XObject: %s" % e)
        stack = []


def _walk_pages(doc, root):
    pages = []
    seen = set()

    def walk(node, inherited, depth):
        n = doc.res(node)
        if not isinstance(n, dict) or depth > 40:
            return
        key = node.num if isinstance(node, Ref) else id(n)
        if key in seen:
            return
        seen.add(key)
        inh = dict(inherited)
        if "Resources" in n:
            inh["Resources"] = n["Resources"]
        kids = doc.res(n.get("Kids"))
        if isinstance(kids, list) and n.get("Type") != "Page":
            for k in kids:
                walk(k, inh, depth + 1)
        else:
            pages.append((n, inh))
    walk(root.get("Pages"), {}, 0)
    return pages


def _pdf_text_string(b):
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace")
    if b.startswith(b"\xff\xfe"):
        return b[2:].decode("utf-16-le", "replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    return b.decode("latin-1")


class PdfReadResult(object):
    def __init__(self):
        self.status = "not_read"
        self.reasons = []
        self.text = ""
        self.pages = 0
        self.text_ops = 0
        self.info = {}
        self.xmp = {}

    @property
    def read(self):
        return self.status == "read"

    def search_forms(self):
        """The decoded text, and the same text with ALL whitespace removed (for term scans), both
        with ligature code points folded the way normalise_text() folds them (F10)."""
        folded = self.text.translate(_LIGATURES)   # a ligature glyph (U+FB01) searches as "fi"
        return [folded, re.sub(r"\s+", "", folded)]

    def to_dict(self):
        return {"status": self.status, "reasons": list(self.reasons), "pages": self.pages,
                "textOps": self.text_ops, "info": dict(self.info), "xmp": dict(self.xmp),
                "text": self.text}


_INFO_KEYS = ("Author", "Creator", "Producer", "Title", "Subject", "Keywords", "Company")
_XMP_FIELDS = (("dc:creator", "creator"), ("dc:title", "title"), ("pdf:Producer", "producer"),
               ("xmp:CreatorTool", "creatortool"), ("pdf:Author", "author"),
               ("pdf:Keywords", "keywords"), ("dc:description", "description"))


def read_pdf(data):
    """Decide whether the PDF in `data` (bytes) was READ, and return its text and metadata."""
    r = PdfReadResult()
    try:
        _read(data, r)
    except Exception as e:  # a hostile file must come back NOT READ, never crash the gate
        r.status = "not_read"
        r.reasons.append("parse failure: %s" % e.__class__.__name__)
    return r


def _read(data, r):
    if b"%PDF-" not in data[:1024]:
        r.reasons.append("not a PDF (no %PDF- header)")
        return
    doc = Document(data)
    for p in doc.problems:
        r.reasons.append(p)
    if not doc.objs:
        r.reasons.append("no PDF objects found")
        return
    enc = any(("Encrypt" in t) for t in doc.trailers)
    if enc:
        r.reasons.append("encrypted")
    # metadata first: it is judged even when the text is not read
    info = None
    for t in reversed(doc.trailers):
        if "Info" in t:
            info = doc.res(t["Info"])
            break
    if isinstance(info, dict):
        for k in _INFO_KEYS:
            v = doc.res(info.get(k))
            if isinstance(v, bytes):
                s = _pdf_text_string(v).strip()
                if s:
                    r.info[k] = s
    root = None
    for t in reversed(doc.trailers):
        if "Root" in t:
            root = doc.res(t["Root"])
            break
    if not isinstance(root, dict):
        for num in sorted(doc.objs):
            v = doc.objs[num][0]
            if isinstance(v, dict) and v.get("Type") == "Catalog":
                root = v
    if isinstance(root, dict) and "Metadata" in root:
        sdic, raw = doc.stream_of(root["Metadata"])
        if sdic is not None:
            try:
                x = doc.decode_stream(sdic, raw).decode("utf-8", "replace")
                for tag, key in _XMP_FIELDS:
                    vals = []
                    for m in re.finditer(r"<%s\b[^>]*>(.*?)</%s>" % (re.escape(tag), re.escape(tag)),
                                         x, re.S):
                        vals.extend(re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", m.group(1), re.S)
                                    or [m.group(1)])
                    vals = [re.sub(r"<[^>]+>", "", v).strip() for v in vals]
                    vals = [v for v in vals if v]
                    if vals:
                        r.xmp[key] = "; ".join(vals)
            except PdfUnsupported:
                r.reasons.append("XMP metadata stream not decoded")
    if enc:
        return
    if not isinstance(root, dict):
        r.reasons.append("no document catalog")
        return
    pages = _walk_pages(doc, root)
    if not pages:
        pages = [(v, {}) for _n, (v, _raw) in sorted(doc.objs.items())
                 if isinstance(v, dict) and v.get("Type") == "Page"]
    if not pages:
        r.reasons.append("no pages")
        return
    r.pages = len(pages)
    font_cache = {}
    all_text = []
    empty_pages = []
    for idx, (pg, inh) in enumerate(pages, 1):
        acc = _Acc()
        contents = doc.res(pg.get("Contents"))
        refs = pg.get("Contents")
        items = [x for x in contents] if isinstance(contents, list) else [refs]
        chunks = []
        for it in items:
            sdic, raw = doc.stream_of(it)
            if sdic is None:
                continue
            try:
                chunks.append(doc.decode_stream(sdic, raw))
            except PdfUnsupported as e:
                acc.note("page %d content: %s" % (idx, e))
        _run_content(doc, b"\n".join(chunks), pg.get("Resources", inh.get("Resources")), acc, 0,
                     font_cache)
        extra = []
        annots = doc.res(pg.get("Annots"))
        for a in (annots if isinstance(annots, list) else []):
            ad = doc.res(a)
            if isinstance(ad, dict):
                for k in ("Contents", "V", "T", "TU", "Subj"):
                    v = doc.res(ad.get(k))
                    if isinstance(v, bytes) and v.strip():
                        extra.append(_pdf_text_string(v))
        text = "".join(acc.text)
        if acc.text_ops and not text.replace("\ufffd", "").strip():
            empty_pages.append(idx)
        r.text_ops += acc.text_ops
        for why in acc.reasons:
            r.reasons.append("page %d: %s" % (idx, why))
        all_text.append(text + (" " + " ".join(extra) if extra else ""))
    r.text = "\n".join(all_text)
    if empty_pages:
        r.reasons.append("decoded text is empty on page(s) %s" % ", ".join(map(str, empty_pages)))
    if r.text_ops == 0:
        r.reasons.append("no text operators: image-only or empty")
    if not r.reasons:
        r.status = "read"


# ---------------------------------------------------------------------------------------------
# Rule 2 helpers (the comparison itself is made by check_site.py)
# ---------------------------------------------------------------------------------------------

def normalise_text(s):
    """NFC, casefolded, all whitespace runs collapsed to one space, stripped."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def words(s):
    return re.findall(r"\w+", normalise_text(s))


def word_coverage(source_text, decoded_text):
    """Fraction (0..1) of the source's word occurrences present in the decoded text, or None when
    the source has no words (rule 2 then cannot be satisfied)."""
    src = Counter(words(source_text))
    total = sum(src.values())
    if not total:
        return None
    got = Counter(words(decoded_text))
    hit = sum(min(n, got.get(w, 0)) for w, n in src.items())
    return hit / float(total)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    paths = [a for a in argv if a != "--json"]
    if len(paths) != 1:
        print("usage: pdftext.py <file.pdf> [--json]")
        return 2
    with open(paths[0], "rb") as fh:
        r = read_pdf(fh.read())
    if as_json:
        print(json.dumps(r.to_dict(), sort_keys=True))
    else:
        print("READ" if r.read else "NOT READ: " + "; ".join(r.reasons))
    return 0 if r.read else 1


if __name__ == "__main__":
    sys.exit(main())
