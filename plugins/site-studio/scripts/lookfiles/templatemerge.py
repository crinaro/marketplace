"""Turning the anchored markup of several instances of one part into one template: slot substitution, number and word alignment, merging
and the majority reading."""

import looks
import re
from contentmodel import links
from lookfiles.pagedom import _SLOT, _collapse
from lookgrammar import optionalparts


# --------------------------------------------------------------------------------------------- merge and agree
_PROTECT = {48: "\ue100", 49: "\ue101", 50: "\ue102", 51: "\ue103", 52: "\ue104", 53: "\ue105", 54: "\ue106", 55: "\ue107",
            56: "\ue108", 57: "\ue109"}


def _expand(template, call):
    """`template` with each slot of `call`'s values written back as a page would hold it: a text, url, srcset, embed,
    contact or position slot as its escaped value, with its digits PROTECTED (so only a digit the template itself
    holds is ever read as a number); an int slot as its digits; an html slot as its marker when it holds anything,
    and as nothing when it holds nothing."""
    def sub(m):
        slot = m.group(1)
        kind = call.table.get(slot)
        v = call.values.get(slot)
        if kind is None:
            return m.group(0)
        if kind == looks.HTML:
            return m.group(0) if v else ""
        if v is None:
            return ""
        if kind == looks.INT:
            return str(v)
        return links.esc(_collapse(str(v))).translate(_PROTECT)
    return _SLOT.sub(sub, template)


def _align_ints(cand, entries, expanded):
    """`cand` with each of its literal digit runs written as the int slot whose value it is in EVERY instance, where
    the instances differ there; None when the instances are not shaped alike or a varying digit run is no int slot's
    value. `expanded` is [(its own expansion of `cand`, the instance's own expansion)] per instance."""
    int_slots = [s for s, k in looks.CONSTRUCTS[entries[0][1].construct]["parts"][entries[0][1].part].items()
                 if k == looks.INT]
    h_parts = [re.split(r"(\d+)", h) for h, _g in expanded]
    g_parts = [re.split(r"(\d+)", g) for _h, g in expanded]
    if any(len(h) != len(g) for h, g in zip(h_parts, g_parts)):
        return None
    if any(h[i] != g[i] for h, g in zip(h_parts, g_parts) for i in range(0, len(h), 2)):
        return None
    toks = re.split(r"(\d+)", cand)
    if len(toks) != len(h_parts[0]):
        return None
    for i in range(1, len(toks), 2):
        gs = [g[i] for g in g_parts]
        if all(g == h[i] for g, h in zip(gs, h_parts)):
            continue
        for slot in int_slots:
            vals = [str(c.values.get(slot)) for _t, c in entries]
            if len(set(vals)) >= 2 and gs == vals:
                toks[i] = "{{%s}}" % slot
                break
        else:
            return None
    return "".join(toks)


def _merge(entries, construct, part):
    """One template for every instance of a part, or None when they do not share one. A candidate is accepted when,
    written back with each instance's own values, it gives that instance's own page text; a number that differs
    between instances is written as the int slot whose value it is, and only there."""
    templates = []
    for t, _c in entries:
        if t not in templates:
            templates.append(t)
    if len(templates) == 1:
        return templates[0]
    got = [_expand(t, c) for t, c in entries]
    for cand in sorted(templates, key=lambda t: -t.count("{{")):
        for refined in (cand, _align_words(cand, entries, got)):
            if refined is None:
                continue
            mine = [_expand(refined, c) for _t, c in entries]
            if got == mine:
                return refined
            aligned = _align_ints(refined, entries, list(zip(mine, got)))
            if aligned is not None and all(_expand(aligned, c) == g for (_t, c), g in zip(entries, got)):
                return aligned
    return None


def _merge_place_picture(entries, construct, part):
    """`_merge` for a place's own picture part (`steps-view.image`, `home-showcase.image`; step G O3). The build takes the attribute
    of a slot the picture has no value for out of that part (`optionalparts.strip`: a picture with no position writes no `style`),
    so the instances holding the most values say the markup, and every other instance must be exactly that markup with those
    attributes taken out. A picture's pixel size is a may-be-empty slot there too, so where the instances do not share one markup
    their `width` and `height` are read as those slots first. None when they do not."""
    tpl = _merge(entries, construct, part)
    if tpl is not None:
        return tpl
    have = lambda c: set(s for s in c.table if c.values.get(s) not in (None, ""))        # noqa: E731
    sized = [(_size_slots(t, c), c) for t, c in entries]
    most = max(len(have(c)) for _t, c in entries)
    tpl = _merge([e for e in sized if len(have(e[1])) == most], construct, part)
    parsed = []
    if tpl is None or looks.check_part(construct, part, tpl, parsed=parsed) or not parsed:
        return None
    for t, c in entries:
        if _expand(optionalparts.strip(*parsed[0], keep=have(c)), c) != _expand(t, c):
            return None
    return tpl


def _size_slots(template, call):
    """`template` with the instance's own `width` and `height` attribute values written as those slots."""
    for slot in ("width", "height"):
        v = call.values.get(slot)
        if v not in (None, ""):
            template = template.replace(' %s="%s"' % (slot, v), ' %s="{{%s}}"' % (slot, slot), 1)
    return template


def _majority(entries, construct, part):
    """(template, [entries that do not share it]) for the markup MORE THAN HALF of the instances share, or (None, [])
    when no markup has that many. An instance whose own markup differs from the rest (a link the template points
    elsewhere for one page, a wrapper one page lacks) is left out and named, so one odd instance does not take the
    whole construct away; the page it is on stays DIFFERENT in parity, which is what says so."""
    best = (None, [])
    for lead in {t for t, _c in entries}:
        group = [e for e in entries if e[0] == lead]
        rest = [e for e in entries if e[0] != lead]
        for e in list(rest):
            if _merge(group + [e], construct, part) is not None:
                group.append(e)
                rest.remove(e)
        tpl = _merge(group, construct, part)
        if tpl is not None and len(group) * 2 > len(entries) and (
                best[0] is None or len(group) > len(entries) - len(best[1])):
            best = (tpl, rest)
    return best


def _align_words(cand, entries, got):
    """`cand` with each slot marker that does not stand for the slot's value in EVERY instance written as the text it
    stands for: a word that is a slot's value in some instances only is a coincidence (the `work` in `tn-work` is the
    portfolio's name in one portfolio and a fixed class in the next), so it stays literal. None when an instance does
    not fit `cand`'s shape, or a marker is neither its slot's value everywhere nor one text everywhere."""
    parts = re.split(r"(\{\{[a-z][A-Za-z0-9]*\}\})", cand)
    marks = [(i, p[2:-2]) for i, p in enumerate(parts) if i % 2 == 1]
    caps = []
    for (_t, c), g in zip(entries, got):
        rx = []
        for i, p in enumerate(parts):
            if i % 2 == 0:
                rx.append(re.escape(p))
            else:
                slot = p[2:-2]
                kind = c.table.get(slot)
                if kind is None:
                    return None
                if kind == looks.HTML:
                    rx.append(re.escape(p) if c.values.get(slot) else "")
                else:
                    rx.append("(.*?)")
        m = re.fullmatch("".join(rx), g, re.S)
        if m is None:
            return None
        it = iter(m.groups())
        caps.append([None if entries[0][1].table.get(s) == looks.HTML else next(it) for _i, s in marks])
    out = list(parts)
    for k, (i, slot) in enumerate(marks):
        if entries[0][1].table.get(slot) == looks.HTML:
            continue
        vals = [_expand("{{%s}}" % slot, c) for _t, c in entries]
        seen = [cap[k] for cap in caps]
        if seen == vals:
            continue
        if len(set(seen)) == 1 and entries[0][1].table.get(slot) != looks.INT:
            out[i] = seen[0].translate(dict((v, k2) for k2, v in _PROTECT.items()))
            continue
        return None
    return "".join(out)
