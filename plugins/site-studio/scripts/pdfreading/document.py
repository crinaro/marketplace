"""document.py -- the object table of one PDF: objects found by scanning, object streams, cross-reference trailers, stream decoding (Flate, ASCIIHex, ASCII85).

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
import zlib
from pdfreading.lexer import Lexer, parse_value
from pdfreading.values import MAX_STREAM, PdfUnsupported, Ref


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
