"""png.py -- PNG chunk walking and the PNG metadata stripper: text, EXIF and time chunks and everything after IEND go.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import struct
from imaging.errors import ImageError


def _png_chunks(data):
    i = 8
    n = len(data)
    while i + 8 <= n:
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        if i + 12 + ln > n:
            return
        yield typ, data[i + 8:i + 8 + ln]
        i += 12 + ln
        if typ == b"IEND":
            return


_PNG_KEEP = frozenset([b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
                       b"sBIT", b"pHYs", b"bKGD", b"hIST", b"acTL", b"fcTL", b"fdAT"])


def strip_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageError("not a PNG")
    out = bytearray(data[:8])
    i = 8
    n = len(data)
    saw_end = False
    while i + 12 <= n:
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        if i + 12 + ln > n:
            raise ImageError("PNG is truncated")
        if typ in _PNG_KEEP:
            out += data[i:i + 12 + ln]
        i += 12 + ln
        if typ == b"IEND":
            saw_end = True
            break
    if not saw_end:
        raise ImageError("PNG has no IEND chunk")
    return bytes(out)
