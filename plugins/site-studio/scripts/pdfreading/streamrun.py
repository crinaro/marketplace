"""streamrun.py -- running one content stream: the text operators, Form XObjects reached by Do, and the per-page accumulator of text, counts and reasons.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
from pdfreading.fonts import Font
from pdfreading.lexer import Lexer, parse_value
from pdfreading.values import JOIN_GAP_EM, MAX_DEPTH, Name, PdfUnsupported, Ref


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
