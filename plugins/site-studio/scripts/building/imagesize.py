"""Image dimensions read from the file header; nothing is decoded."""

import struct


# ---------------------------------------------------------------- image headers (no media work)

_SOF = (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)


def image_size(data):
    """(width, height) read from the file header, or None when it is not a readable PNG, JPEG,
    GIF or WebP. Nothing is decoded."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 4 <= len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                while i < len(data) and data[i] == 0xFF:
                    i += 1
                marker = data[i]
                i += 1
                if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
                    continue
                if marker == 0xD9:
                    return None
                seglen = struct.unpack(">H", data[i:i + 2])[0]
                if marker in _SOF:
                    h, w = struct.unpack(">HH", data[i + 3:i + 7])
                    return (w, h)
                i += seglen
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return (w & 0x3FFF, h & 0x3FFF)
            if chunk == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            if chunk == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1,
                        int.from_bytes(data[27:30], "little") + 1)
    except (struct.error, IndexError):
        return None
    return None
