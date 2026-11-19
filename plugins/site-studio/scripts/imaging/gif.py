"""gif.py -- GIF block walking and the GIF stripper: comment, plain-text and application extensions go, the loop extension stays.

Moved out of images.py unchanged (S1b, dev 939); the interface and the design notes are in images.py."""

from imaging.errors import ImageError


def _gif_blocks(data):
    """Yield (kind, start, end, label, body) walking the block structure after the header."""
    if len(data) < 13:
        raise ImageError("GIF is truncated")
    flags = data[10]
    i = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0x3B:
            yield ("end", i, i + 1, None, b"")
            return
        if b == 0x21:
            label = data[i + 1]
            j = i + 2
            first = None
            while j < n:
                ln = data[j]
                if first is None:
                    first = data[j + 1:j + 1 + ln]
                j += 1 + ln
                if ln == 0:
                    break
            yield ("ext", i, j, label, first or b"")
            i = j
        elif b == 0x2C:
            if i + 10 > n:
                raise ImageError("GIF is truncated")
            f2 = data[i + 9]
            j = i + 10 + (3 * (2 << (f2 & 7)) if f2 & 0x80 else 0) + 1
            while j < n:
                ln = data[j]
                j += 1 + ln
                if ln == 0:
                    break
            yield ("image", i, j, None, b"")
            i = j
        else:
            raise ImageError("GIF is damaged")
    raise ImageError("GIF has no trailer")


def _gif_extensions(data):
    try:
        for kind, _s, _e, label, body in _gif_blocks(data):
            if kind == "ext":
                yield label, body
    except ImageError:
        return


def strip_gif(data):
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ImageError("not a GIF")
    flags = data[10] if len(data) > 10 else 0
    head_end = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    out = bytearray(data[:head_end])
    for kind, s, e, label, body in _gif_blocks(data):
        if kind == "ext":
            if label == 0xF9 or (label == 0xFF and body.startswith((b"NETSCAPE2.0", b"ANIMEXTS1.0"))):
                out += data[s:e]
        else:
            out += data[s:e]
    return bytes(out)
