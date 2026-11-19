"""reviews.packet -- THE PACKET (`.site-studio/review/packet.json`, `v` 2, dev #857): the paths, the shape `begin` writes and `add` reads
back, and the text `begin` prints.

`siteKind` tells the reviewer whether it is looking at a portfolio, a links `hub` or a hand-made `custom` site. A `v` 1 packet, left
by 0.1.0, is refused with "run begin again".
"""
import json
import os
from reviews.basics import ReviewError, _HEX64


REVIEW_DIR_REL = ".site-studio/review"
BUILD_REL = ".site-studio/review/build"
PACKET_REL = ".site-studio/review/packet.json"


IGNORE_LINE = ".site-studio/review/"

# PACKET v2 (dev #857, design-site-adoption section 9): the packet gains `siteKind`, so a reviewer is told
# the kind of site it is looking at instead of inferring it. A v1 packet (0.1.0) is refused by
# `_load_packet` with its existing "run begin again" text. The packet is a per-review scratch file that
# `begin` rebuilds, so no stored record changes shape.
PACKET_VERSION = 2
PACKET_KEYS = ("v", "digest", "baseline", "baseline_blobs", "coverage", "types", "files",
               "not_read_pdfs", "not_read_note", "siteKind")


def _read_built(out_dir, rels):
    out = {}
    for rel in rels:
        with open(os.path.join(out_dir, rel), "rb") as fh:
            out[rel] = fh.read()
    return out


def format_begin(packet, repo):
    lines = []
    b = packet["baseline"]
    if b["kind"] == "live":
        lines.append("baseline: the live site (public tree %s)" % (b["tree"] or "?")[:12])
    else:
        lines.append("baseline: NONE (%s); every file that is not plain text is in the set" % b["reason"])
    if packet.get("siteKind", "portfolio") != "portfolio":
        lines.append("site kind: %s (a links or hand-made site: no pieces, no resume)" % packet["siteKind"])
    lines.append("built %d files; digest %s" % (packet["files"], packet["digest"]))
    lines.append("coverage set: %d file(s) to open" % len(packet["coverage"]))
    for t in sorted(packet["types"]):
        lines.append("  %s: %d" % (t, packet["types"][t]))
    nr = packet["not_read_pdfs"]
    if nr is None:
        lines.append(packet["not_read_note"])
    else:
        lines.append("PDFs NOT READ by the pattern gate: %d" % len(nr))
        for p in nr:
            lines.append("  " + p)
    lines.append("packet: %s" % os.path.join(repo, PACKET_REL))
    return "\n".join(lines)


def _load_packet(path):
    try:
        with open(path, "rb") as fh:
            p = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        raise ReviewError("the packet %s cannot be read; run begin again" % path)
    if not isinstance(p, dict) or p.get("v") != PACKET_VERSION or any(k not in p for k in PACKET_KEYS):
        raise ReviewError("the packet %s is not one this plugin wrote; run begin again" % path)
    if p["siteKind"] not in ("portfolio", "hub", "custom"):
        raise ReviewError("the packet's site kind is not one this plugin knows; run begin again")
    if not isinstance(p["digest"], str) or not _HEX64.match(p["digest"]):
        raise ReviewError("the packet's digest is malformed; run begin again")
    return p
