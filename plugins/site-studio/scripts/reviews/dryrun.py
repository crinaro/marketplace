"""reviews.dryrun -- THE DRY-RUN RECORD, v2 (template-fidelity step 1.6r; design R2-1, R2-4): what `deploy.py --dry-run` writes and the
publish guard and `deploy.py --confirm` read, so what one side writes the other can read.

v2 adds `released`, the published addresses this publish ends on purpose; the person's yes at the publish ask is a yes to those
addresses, and `released_refusal` refuses a list that is not the one the dry run recorded. A v1 record is refused, loud.
"""
import json
import os
from reviews.basics import ReviewError, _HEX64


DRYRUN_REL = ".site-studio/review/dryrun.json"


# THE DRY-RUN RECORD, v2 (template-fidelity step 1.6r; design R2-1, R2-4; R4 row 21). `deploy.py --dry-run` writes it,
# the publish guard and `deploy.py --confirm` read it, all through the two functions below, so what one side writes
# the other can read. v2 adds `released`: `[[path, reason], ...]`, the published addresses this publish ends on
# purpose (a moved piece's files included), sorted by path, `[]` when none. The person's yes at the publish ask is
# then a yes to THOSE addresses (the guard's ask names them), and `deploy.py --confirm` refuses a list that is not
# the one the dry run recorded. A v1 record (0.3.x) is refused, loud: run the dry run again. The record may also
# carry `live` (the NOT APPLICABLE live comparison, a later step of the same group), which this reader passes through.
DRYRUN_VERSION = 2


def _released_pairs(value):
    """`value` as a list of `(path, reason)` tuples, or None when it is not the v2 shape: a list of two-text lists,
    each path non-empty and free of control characters, each reason one non-blank line (the rule
    `addresses.parse` holds the committed record to, so anything that record carries can be written here)."""
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        if (not isinstance(item, (list, tuple)) or len(item) != 2 or not all(isinstance(x, str) for x in item)
                or not item[0] or not item[1].strip() or "\n" in item[1]
                or any(ord(c) < 32 or ord(c) == 127 for c in item[0])):
            return None
        out.append((item[0], item[1]))
    return out


def check_dryrun(obj):
    """Raises ReviewError unless `obj` is a v2 dry-run record: an integer `files`, a 64-hex `digest`, and `released`
    in the shape above."""
    if (not isinstance(obj, dict) or obj.get("v") != DRYRUN_VERSION or isinstance(obj.get("files"), bool)
            or not isinstance(obj.get("files"), int) or not isinstance(obj.get("digest"), str)
            or not _HEX64.match(obj["digest"]) or _released_pairs(obj.get("released")) is None):
        raise ReviewError("%s is not a v%d dry-run record this plugin wrote; run the publish dry run again to write a "
                          "new one" % (DRYRUN_REL, DRYRUN_VERSION))
    return obj


def read_dryrun(repo):
    """The dry-run record `deploy.py --dry-run` writes. None when absent. Strict on shape (`check_dryrun`); a file that
    is not JSON is the same refusal."""
    path = os.path.join(repo, DRYRUN_REL)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        try:
            obj = json.loads(fh.read().decode("utf-8"))
        except ValueError:
            obj = None
    return check_dryrun(obj)


def write_dryrun(repo, record):
    """Writes `record` (checked first: nothing this module cannot read back reaches the disk) to the dry-run path."""
    check_dryrun(record)
    path = os.path.join(repo, DRYRUN_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")


def _some(pairs, cap=4):
    shown = ", ".join("%s (%s)" % (p, r if len(r) <= 60 else r[:57] + "...") for p, r in pairs[:cap])
    return shown + (", +%d more" % (len(pairs) - cap) if len(pairs) > cap else "")


def released_refusal(repo, digest, released):
    """The refusal `deploy.py --confirm` makes, or None: the addresses this publish releases (`released`, as
    `[[path, reason]]`) must be the ones the dry run for THIS digest recorded, which is what the person's yes named
    (R2-1, R2-4). A record that cannot be read refuses; a missing record, or one for another digest, refuses only when
    this publish releases something (nothing was then approved to release)."""
    try:
        rec = read_dryrun(repo)
    except ReviewError as e:
        return str(e)
    now = sorted(_released_pairs(released) or [])
    if rec is None or rec["digest"] != digest:
        if not now:
            return None
        return ("this publish releases %d published address%s (%s) and no dry run for this digest recorded %s; run "
                "`deploy.py --dry-run` and approve the list it prints" % (
                    len(now), "" if len(now) == 1 else "es", _some(now), "it" if len(now) == 1 else "them"))
    then = sorted(_released_pairs(rec["released"]))
    if now == then:
        return None
    new, gone = [x for x in now if x not in then], [x for x in then if x not in now]
    parts = []
    if new:
        parts.append("now released and not in the dry run: %s" % _some(new))
    if gone:
        parts.append("in the dry run and no longer released: %s" % _some(gone))
    return ("the addresses this publish releases changed since the dry run you approved (%s); run `deploy.py --dry-run` "
            "again and approve the list it prints" % "; ".join(parts))
