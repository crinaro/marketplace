"""webp.py -- WebP (RIFF) chunk walking and the WebP stripper: the EXIF and XMP chunks go, the VP8X flags and RIFF size are rewritten.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import struct
from imaging.errors import ImageError


def _riff_chunks(data):
    i = 12
    n = len(data)
    while i + 8 <= n:
        typ = data[i:i + 4]
        ln = struct.unpack("<I", data[i + 4:i + 8])[0]
        if i + 8 + ln > n:
            return
        yield typ, data[i + 8:i + 8 + ln]
        i += 8 + ln + (ln & 1)


_WEBP_KEEP = frozenset([b"VP8 ", b"VP8L", b"VP8X", b"ICCP", b"ALPH", b"ANIM", b"ANMF"])


def strip_webp(data):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ImageError("not a WebP")
    body = bytearray(b"WEBP")
    for typ, chunk in _riff_chunks(data):
        if typ not in _WEBP_KEEP:
            continue
        if typ == b"VP8X" and len(chunk) >= 1:
            chunk = bytes([chunk[0] & ~0x0C & 0xFF]) + chunk[1:]
        body += typ + struct.pack("<I", len(chunk)) + chunk + (b"\x00" if len(chunk) & 1 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)
