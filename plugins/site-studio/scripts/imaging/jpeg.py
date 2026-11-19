"""jpeg.py -- JPEG segment walking and the JPEG metadata stripper: every APPn and COM segment goes except JFIF, ICC and Adobe.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

import struct
from imaging.errors import ImageError


_SOF = frozenset([0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF])


def _jpeg_segments(data):
    """Yield (marker, start, payload_including_length) for each marker segment up to SOS/EOI.
    Entropy data is not yielded. Raises ImageError on structural damage."""
    n = len(data)
    i = 2
    while i < n:
        if data[i] != 0xFF:
            raise ImageError("JPEG is damaged (expected a marker at byte %d)" % i)
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        m = data[i]
        i += 1
        if m == 0xD9:
            return
        if m == 0x01 or 0xD0 <= m <= 0xD8:
            continue
        if i + 2 > n:
            raise ImageError("JPEG is truncated")
        ln = struct.unpack(">H", data[i:i + 2])[0]
        if ln < 2 or i + ln > n:
            raise ImageError("JPEG is truncated")
        yield (m, i - 2, data[i:i + ln])
        i += ln
        if m == 0xDA:
            return


def strip_jpeg(data):
    if data[:2] != b"\xff\xd8":
        raise ImageError("not a JPEG")
    out = bytearray(b"\xff\xd8")
    n = len(data)
    i = 2
    saw_eoi = False
    while i < n:
        if data[i] != 0xFF:
            raise ImageError("JPEG is damaged (expected a marker at byte %d)" % i)
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        m = data[i]
        i += 1
        if m == 0xD9:
            out += b"\xff\xd9"
            saw_eoi = True
            break
        if m == 0x01 or 0xD0 <= m <= 0xD8:
            out += bytes([0xFF, m])
            continue
        if i + 2 > n:
            raise ImageError("JPEG is truncated")
        ln = struct.unpack(">H", data[i:i + 2])[0]
        if ln < 2 or i + ln > n:
            raise ImageError("JPEG is truncated")
        body = data[i + 2:i + ln]
        keep = True
        if m == 0xE0:
            if body[:5] == b"JFIF\x00" and len(body) >= 14:
                # keep the JFIF header, drop an embedded thumbnail
                body = body[:12] + b"\x00\x00"
            else:
                keep = False
        elif m == 0xE2:
            keep = body[:12] == b"ICC_PROFILE\x00"
        elif m == 0xEE:
            keep = body[:5] == b"Adobe"
        elif 0xE1 <= m <= 0xEF or m == 0xFE:
            keep = False
        if keep:
            out += bytes([0xFF, m]) + struct.pack(">H", len(body) + 2) + body
        i += ln
        if m == 0xDA:
            # entropy-coded data: copy up to the next real marker
            j = i
            while j + 1 < n:
                if data[j] == 0xFF and data[j + 1] != 0x00 and not (0xD0 <= data[j + 1] <= 0xD7) \
                        and data[j + 1] != 0xFF:
                    break
                j += 1
            else:
                j = n
            out += data[i:j]
            i = j
    if not saw_eoi:
        raise ImageError("JPEG has no end-of-image marker")
    return bytes(out)
