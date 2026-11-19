"""cmap.py -- a ToUnicode CMap: bfchar and bfrange entries read from a font's map stream.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re


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
