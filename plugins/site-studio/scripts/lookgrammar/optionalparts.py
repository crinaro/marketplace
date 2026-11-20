"""lookgrammar/optionalparts.py -- the rules of step G's optional parts beyond the shared part grammar
(design-movement-view step G, O2 and O3; independent review findings F1 and F7). Python 3.9, standard library only.
Imports only `lookgrammar.constructs`.

`looks.check_part` calls `problems` for every `OPTIONAL_PARTS` part, after its own part parser has read it:

    steps-view.role-sep   literal text (`check_part` refuses an element). Read as the build reads it, its character
                          references as the characters they name (`stepsview.role_separator`), it must be one line:
                          no line break, no U+E000 or U+E001 (F7). An empty separator is still read (joined with
                          nothing): `test_stepsview.py` holds that case, outside review step G2's files, so refusing
                          it is the coordinator's call.
    <place>.image         a per-place picture part (`PLACE_IMAGE_SLOTS`). The build leaves a may-be-empty slot
                          (`PLACE_IMAGE_MAY_BE_EMPTY`) unfilled when the picture has no such value, and takes the
                          attribute holding it out of the markup (`strip`). So each such slot has ONE placement: the
                          whole value of its own double-quoted attribute, `name="{{slot}}"` after whitespace (for
                          `focus`, the one form the grammar allows it at all, `style="object-position: {{focus}}"`).
                          Any other placement is refused with a line naming the slot (F1a).

Why (F1): the 0.5.0 draft removed such attributes with a pattern on the raw markup AFTER validation. A pattern cannot
tell an attribute from text inside another attribute's value, so a part that passed `check_part` came out of the strip
as markup nobody had checked, with an event handler in it. Here where an attribute is comes from `looks`' own part parser
(the attributes it recorded, each slot replaced by its sentinel), never from a pattern on the raw markup (F1b), and the
build checks the stripped markup again before rendering it (F1c, `building.pictures.place_html`). A character reference
naming a sentinel character is refused in these parts first, so every sentinel the parser reports is the one real slot
of its index, standing once in the sentinel text. Review F8(c) (the slot placements a removal rule must cover) is settled
by F1(a): a may-be-empty slot has one placement, so no other quoting or position needs a removal rule.
"""
import html
import re

from lookgrammar.constructs import (CONSTRUCTS, PLACE_IMAGE_MAY_BE_EMPTY, PLACE_IMAGE_SLOTS, SENT_CLOSE, SENT_OPEN,
                                    STYLE_FORM, TEXT_ONLY_PARTS)

_SENT = re.compile(SENT_OPEN + r"(\d+)" + SENT_CLOSE)


def own_value(slot, i):
    """The whole attribute value slot occurrence `i` must be: its sentinel, or for `focus` the style form holding it."""
    sent = "%s%d%s" % (SENT_OPEN, i, SENT_CLOSE)
    return STYLE_FORM.replace("{{focus}}", sent) if slot == "focus" else sent


def own_form(slot):
    """The one placement of a may-be-empty slot, as a look writes it."""
    return '%s="%s"' % ("style", STYLE_FORM) if slot == "focus" else '%s="{{%s}}"' % (slot, slot)


def own_attributes(replaced, found, attrs):
    """({index: (start, end)}, [slot]). `replaced` is the part with each slot replaced by its sentinel, `found` the
    [(slot, kind)] by sentinel index, `attrs` the [(name, value)] the part parser read. For each may-be-empty slot
    occurrence: the span in `replaced` of its own double-quoted attribute and the whitespace before it, when exactly one
    attribute's whole value is `own_value` and `replaced` holds exactly `name="value"` after whitespace; else the slot,
    in the refused list."""
    spans, refused = {}, []
    for i, (slot, _kind) in enumerate(found):
        if slot not in PLACE_IMAGE_MAY_BE_EMPTY:
            continue
        names = [n for n, v in attrs if v == own_value(slot, i)]
        form = '%s="%s"' % (names[0], own_value(slot, i)) if len(names) == 1 else None
        at = replaced.find(form) if form else -1
        if at <= 0 or not replaced[at - 1].isspace():
            refused.append(slot)
            continue
        start = at
        while start > 0 and replaced[start - 1].isspace():
            start -= 1
        spans[i] = (start, at + len(form))
    return spans, refused


def problems(ctx, construct, part, text, replaced, found, attrs, parsed=None):
    """[(message, fix)] of an `OPTIONAL_PARTS` part beyond the shared grammar ([] is clean). `parsed`, a list, gets
    (replaced, found, spans) appended for a per-place picture part, for `strip`."""
    plain = html.unescape(text)
    if SENT_OPEN in plain or SENT_CLOSE in plain:
        return [("%s: a character reference to the private-use character U+E000 or U+E001" % ctx, "remove it")]
    if (construct, part) in TEXT_ONLY_PARTS:
        if "\n" in plain or "\r" in plain:
            return [("%s: the separator must be one line of text, with no line break" % ctx,
                     "write the text alone on one line, such as \" / \"")]
        return []
    if CONSTRUCTS[construct]["parts"][part] is not PLACE_IMAGE_SLOTS:
        return []
    spans, refused = own_attributes(replaced, found, attrs)
    if parsed is not None:
        parsed.append((replaced, found, spans))
    return [("%s: the slot {{%s}} may be left empty, so it must be the whole value of its own double-quoted attribute, "
             "%s; it stands anywhere else here" % (ctx, slot, own_form(slot)),
             "write it as %s, or leave the slot out" % own_form(slot)) for slot in refused]


def strip(replaced, found, spans, keep):
    """The part's markup with the own attribute of each may-be-empty slot NOT in `keep` taken out (the spans
    `own_attributes` found, with the whitespace before each), and every other sentinel written back as its `{{slot}}`."""
    out = replaced
    for i in sorted((i for i in spans if found[i][0] not in keep), reverse=True):
        out = out[:spans[i][0]] + out[spans[i][1]:]
    return _SENT.sub(lambda m: "{{%s}}" % found[int(m.group(1))][0], out)
