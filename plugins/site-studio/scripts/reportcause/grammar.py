"""grammar: the blocker reporter's CAUSE ID and the closed enumerations behind it (moved out of report_issue.py unchanged,
S1b). A cause id is `ss-adopt/<group>/<key>[/<row>]`, every part from a plugin enumeration and never from the site; anything
outside an enumeration maps to that enumeration's `other` (or `unclassified`) member and is never echoed (Q1.8). `parse_cause` is
the strict reader, `cause_id` the one builder, `cause_kind` says plugin, person or environment (R3N-13: only a plugin cause is
ever filed). The enumerations replicate what an owning module holds where the SessionStart hook cannot import it cheaply; each
replica is asserted equal to its owner by tests/test_report_issue.py."""

import looks
import parity_classes
import re


PREFIX = "ss-adopt"


# ------------------------------------------------------------------------------------------- the enumerations
# Replicated where the owning module cannot be imported cheaply (the SessionStart hook imports this file); each
# replica is asserted EQUAL to its owner by tests/test_report_issue.py, so a drift is a red test, not a wrong id.
REFUSAL_CODE_IDS = ("unknown-reference-key", "unknown-page-key", "unknown-token", "unknown-piece-key",
                    "piece-both", "redirect-collision", "held-choice", "unclassified")
AREAS = ("content", "site", "root")
# adopt.CONVERSION_CLASSES' names (0.3.1) plus the classes 0.4.0 adds; asserted a superset of adopt's table.
CONVERSION_CLASS_IDS = ("normalise", "redirectKeys", "labels", "redirects", "redirectBoiler", "layout", "tokens",
                        "viewKeys", "pieces", "pieceKeys", "resumeFields", "archive", "draft", "references", "personName", "blocks",
                        "resumePdfName", "pageFiles", "homeKeys", "resumeHeader", "navTokens", "other")
LANGUAGES = ("python", "shell", "ruby", "go", "php", "typescript", "make", "workflow", "other")
UNITS = ("about", "home", "resume", "portfolio", "site-src")
GATE_FAMILIES = ("structure", "comments", "links", "reachable", "privacy", "domain", "media", "unfinished",
                 "performance", "head", "nav", "basepath", "size")
ENV_CAUSES = ("no-node", "builder-fails", "builder-nondeterministic", "pages-unread", "no-public-repo",
              "public-target", "public-unreachable", "pages-not-built", "pages-errored")
# Where `adopt.py apply` can end after its checks (steps 3 to 5): `adoption.publish.Stop` and `adoption.finish` name one of these.
APPLY_STOPS = ("run-in-progress", "publish-refused", "no-review", "not-publishable", "archive-refused", "push-refused")
PERSON_CAUSES = (("publish", "other-publisher"), ("publish", "pages-workflow"), ("publish", "serves-dev-repo"),
                 ("refusal", "unknown-piece-key"), ("apply", "run-in-progress"), ("apply", "no-review"),
                 ("apply", "push-refused"))
VERDICTS = ("EQUAL", "MARKUP-ONLY", "DIFFERENT", "ACCEPTED", "UNVERIFIED", "NOT APPLICABLE")
UNATTRIBUTED = "unattributed"
STATES = ("pending", "filed", "existing", "declined", "resolved", "regressed", "upgrade")

# `Unmapped is counted, never echoed` (Q1.8): the member an out-of-enumeration value becomes, per slot. None means
# the slot has no such member and a value outside it is refused (a construct id comes from the shipped table, so a
# value outside it is a defect in the caller).
FALLBACKS = {"refusal-code": "unclassified", "family": "other", "class": "other", "fails-class": "other",
             "language": "other", "unit": None, "gate": None, "area": None, "construct": None, "apply-stop": None}


def families():
    return tuple(parity_classes.FAMILIES)


def constructs():
    """The shipped construct ids (`looks.CONSTRUCTS`): the one source of a `<row>` and of a `look/` construct."""
    return tuple(sorted(looks.CONSTRUCTS))


def _enum(slot):
    if slot == "refusal-code":
        return REFUSAL_CODE_IDS
    if slot == "family":
        return families()
    if slot == "area":
        return AREAS
    if slot == "class":
        return CONVERSION_CLASS_IDS
    if slot == "fails-class":
        return tuple(c for c in CONVERSION_CLASS_IDS if c != "other") + ("combined", "other")
    if slot == "language":
        return LANGUAGES
    if slot == "unit":
        return UNITS
    if slot == "gate":
        return GATE_FAMILIES
    if slot == "construct":
        return constructs()
    if slot == "apply-stop":
        return APPLY_STOPS
    raise ValueError("unknown slot %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (slot,))


# The shapes: a tuple of literals and `<slot>` markers. `kind` and `row` are special slots (below).
SHAPES = (
    ("refusal", "<refusal-code>"),
    ("no-landing", "<family>", "<area>"),
    ("parity", "<kind>"),
    ("conversion", "<class>"),
    ("builder", "fails", "<fails-class>"),
    ("builder", "unmeasurable", "<language>"),
    ("builder", "invocation-differs"),
    ("unobservable", "<family>"),
    ("draft", "unsupported", "<unit>"),
    ("publish", "gate", "<gate>"),
    ("publish", "address"),
    ("publish", "pages-workflow"),
    ("publish", "other-publisher"),
    ("publish", "serves-dev-repo"),
    ("apply", "<apply-stop>"),
    ("look", "unmapped", "<construct>"),
    ("look", "ambiguous", "<construct>"),
)

# The shape of an id, nothing more; `parse_cause` is the check against the enumerations.
CAUSE_RE = re.compile(r"\Ass\-adopt(?:/[A-Za-z0-9][A-Za-z0-9-]*){2,5}\Z")      # PREFIX, escaped: an import runs no code (G3)


class CauseError(ValueError):
    """An id that is outside the closed grammar, or a value that cannot be mapped into it."""


def kind_labels_ok(kind):
    """True when `kind` is one of `parity_classes.kind()`'s closed labels."""
    pc = parity_classes
    parts = kind.split("/")
    if kind in ("head-only", "text"):
        return True
    if len(parts) != 2:
        return False
    head, tail = parts
    if head == "element":
        return tail == "other" or tail in pc.STANDARD_ELEMENTS
    if head == "attribute":
        return tail == "other" or tail in pc.STANDARD_ATTRIBUTES
    if head in ("file", "only-local", "only-plugin"):
        return tail in pc.FAMILIES
    return False


def _kind_prefix_len(segments):
    """How many segments (1 or 2) of `segments` form a parity kind, or 0."""
    if not segments:
        return 0
    if segments[0] in ("head-only", "text"):
        return 1
    if len(segments) >= 2 and kind_labels_ok("/".join(segments[:2])):
        return 2
    return 0


def parse_cause(cid):
    """`(shape, values, row)` for a valid id, else CauseError. `shape` is the matched SHAPES entry; `row` is the
    trailing construct id (parity only) or None."""
    if not isinstance(cid, str) or not CAUSE_RE.match(cid):
        raise CauseError("a cause id has the form %s/<group>/<key>, from the plugin's own names; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)" % PREFIX)
    segs = cid.split("/")[1:]
    if segs[0] == "env":
        if len(segs) == 2 and segs[1] in ENV_CAUSES:
            return ("env", "<env>"), (segs[1],), None
        raise CauseError("an unknown environment cause; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")
    for shape in SHAPES:
        if shape[0] != segs[0]:
            continue
        values, i, ok = [], 0, True
        for part in shape[1:]:
            if part == "<kind>":
                n = _kind_prefix_len(segs[1 + i:])
                if not n:
                    ok = False
                    break
                values.append("/".join(segs[1 + i:1 + i + n]))
                i += n
            elif part.startswith("<"):
                if 1 + i >= len(segs) or segs[1 + i] not in _enum(part[1:-1]):
                    ok = False
                    break
                values.append(segs[1 + i])
                i += 1
            else:
                if 1 + i >= len(segs) or segs[1 + i] != part:
                    ok = False
                    break
                i += 1
        if not ok:
            continue
        rest = segs[1 + i:]
        if not rest:
            return shape, tuple(values), None
        if shape[0] == "parity" and len(rest) == 1 and (rest[0] == UNATTRIBUTED or rest[0] in constructs()):
            return shape, tuple(values), rest[0]
        raise CauseError("a cause id has a part outside the plugin's own names; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")
    raise CauseError("a cause id has a part outside the plugin's own names; restore .site-studio/adopt-reports.json from an earlier commit (adopt writes it, so never edit it by hand)")


def cause_id(*segments, **kw):
    """Build a valid id from the plugin's own names. A value outside its enumeration becomes that enumeration's
    `other` or `unclassified` member where one exists (counted by the caller, never echoed) and is otherwise refused.
    `row=` is the construct id of a parity cause. `cause_id("parity", "element/div", row="card")`."""
    row = kw.pop("row", None)
    if kw:
        raise TypeError("unexpected keyword %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % sorted(kw))
    segs = [str(s) for s in segments]
    if not segs:
        raise CauseError("empty cause; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
    if segs[0] == "env":
        out = PREFIX + "/env/" + "/".join(segs[1:])
        parse_cause(out)
        return out
    for shape in SHAPES:
        if shape[0] != segs[0]:
            continue
        out = [PREFIX, shape[0]]
        args = segs[1:]
        ai = 0
        good = True
        for part in shape[1:]:
            if ai >= len(args):
                good = False
                break
            if part == "<kind>":
                kind = args[ai]
                if not kind_labels_ok(kind):
                    head = kind.split("/")[0]
                    if head == "element":
                        kind = "element/other"
                    elif head == "attribute":
                        kind = "attribute/other"
                    else:
                        raise CauseError("a parity kind outside the closed labels; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists")
                out.append(kind)
            elif part.startswith("<"):
                slot, value = part[1:-1], args[ai]
                if value not in _enum(slot):
                    fb = FALLBACKS.get(slot)
                    if fb is None:
                        raise CauseError("a value outside the %s enumeration; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % slot)
                    value = fb
                out.append(value)
            else:
                if args[ai] != part:
                    good = False
                    break
                out.append(part)
            ai += 1
        if not good or ai != len(args):
            continue
        if row is not None:
            if shape[0] != "parity":
                raise CauseError("only a parity cause carries a row")
            out.append(row if row == UNATTRIBUTED or row in constructs() else UNATTRIBUTED)
        cid = "/".join(out)
        parse_cause(cid)
        return cid
    raise CauseError("no cause shape matches %s; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % "/".join(segs[:1]))


def cause_kind(cid):
    """`plugin`, `person` or `environment`: what may be done with the cause (R3N-13)."""
    shape, values, _row = parse_cause(cid)
    if shape[0] == "env":
        return "environment"
    if tuple(cid.split("/")[1:3]) in PERSON_CAUSES:
        return "person"
    return "plugin"
