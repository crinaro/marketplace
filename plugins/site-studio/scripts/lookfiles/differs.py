"""lookfiles.differs -- the candidates file never writes one instance's value as fixed text (dev 980, public #250).

`.site-studio/look-candidates.json` is the file parity tells the person to copy entries from, so a value in it that is ONE instance's
(a numbered tile's `t-shot-1`, one account appended to a card's site line) is copied and printed on every instance. The rule, applied
to what the file holds (never to the look the build uses, which keeps its own refusals):

  - where the instances of a part do not share one markup, each place they differ in the fixed text is written as the slot every
    instance's own value there equals (`flag`, rule a), else as a FLAG, `{{?differs: first | second}}` (rule b);
  - where a part is read from fewer instances than the build renders, a class token ending in the instance's own position
    (`t-shot-4` read from the fourth of four) is flagged the same way (`flag_positions`), and a picture's `width` and `height` are the
    picture's own slots (`size_slots`), never a literal.

THE FLAG'S FORM is `{{?differs: a | b}}` and nothing else, because the grammar refuses it where it is copied: the `{{`..`}}` of a
look part is a slot, and no part has a slot called `?differs: a | b`, so `looks.check_part` (and the build) refuse the part by name:
`home-showcase.item: the slot {{?differs: t-shot-1 | t-shot-2}} is not one of this part's slots`. A plain-text marker would pass the
build and print itself on the page; this one cannot be copied unchanged. The candidates file's own `checks` field says it.
"""

import difflib
import re

from lookfiles.templatemerge import _PROTECT, _expand

FLAG = "{{?differs: %s}}"
SHOWN = 4                                             # values a flag lists before "..."
_TOKEN = re.compile(r"\{\{[a-z][A-Za-z0-9]*\}\}|[^\W]+(?:[-_.][^\W]+)*|\s+|.", re.S)
_SLOT_TOKEN = re.compile(r"\{\{[a-z][A-Za-z0-9]*\}\}$")
_CLASS = re.compile(r'(class=")([^"]*)"')


def _plain(text):
    return text.translate(dict((ord(v), chr(k)) for k, v in _PROTECT.items()))


def _tokens(text):
    return _TOKEN.findall(text)


def _expanded(tokens, call):
    """[(token, index of the template token it came from)] of `tokens` written back with `call`'s own values."""
    out = []
    for i, t in enumerate(tokens):
        out.extend((x, i) for x in (_tokens(_expand(t, call)) if _SLOT_TOKEN.match(t) else [t]))
    return out


def _ops(base, tokens, entry):
    """The places `entry` (template, call) differs from `base` (`tokens`) in the template's fixed text: [(lo, hi, text)], the
    half-open range of the template's tokens and what the instance holds there (hi == lo for text the template lacks)."""
    tpl, call = entry
    mine, theirs = _expanded(tokens, call), _tokens(_expand(tpl, call))
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [t for t, _o in mine], theirs, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        fixed = [o for _t, o in mine[i1:i2] if not _SLOT_TOKEN.match(tokens[o])]
        if i1 == i2:
            lo = hi = mine[i1][1] if i1 < len(mine) else len(tokens)
        elif fixed:
            lo, hi = min(fixed), max(fixed) + 1
        else:
            continue                                  # a slot's own value differing is the slot's, not fixed text
        out.append((lo, hi, "".join(theirs[j1:j2])))
    return out


def _regions(spans):
    """The ranges of `spans` [(lo, hi)] merged where they overlap or touch."""
    out = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def _value(tokens, region, ops):
    """What an instance holds in `region`: the template's tokens, its own text where `ops` (its differences) replace them."""
    lo, hi = region
    text, i = "", lo
    for a, b, t in sorted(o for o in ops if lo <= o[0] and o[1] <= hi):
        text += "".join(tokens[i:a]) + t
        i = max(i, b)
    return _plain(text + "".join(tokens[i:hi]))


def _slot_for(values, calls):
    """The slot (text or int, never html) whose own value is, in every instance, exactly what that instance holds there."""
    first = calls[0]
    for slot, kind in sorted(first.table.items()):
        if kind == "html":
            continue
        if all(v != "" and _plain(_expand("{{%s}}" % slot, c)) == v for v, c in zip(values, calls)):
            return "{{%s}}" % slot
    return None


def flag(template, entries):
    """`template` (the markup one of `entries` [(markup, call)] holds) written for the candidates file: each place the instances
    differ in its fixed text is the slot that fits, else `{{?differs: ...}}`. Returns `template` when they do not differ."""
    tokens = _tokens(template)
    per = [(_ops(template, tokens, e) if e[0] != template else [], e[1]) for e in entries]
    regions = _regions([(lo, hi) for ops, _c in per for lo, hi, _t in ops])
    for lo, hi in reversed(regions):
        values = [_value(tokens, (lo, hi), ops) for ops, _c in per]
        shown = list(dict.fromkeys(v for v in values if v is not None))
        text = _slot_for(values, [c for _o, c in per]) or FLAG % " | ".join(
            (s if s != "" else "(nothing)") for s in shown[:SHOWN] + (["..."] if len(shown) > SHOWN else []))
        tokens[lo:hi] = [text]
    return "".join(tokens)


def flag_positions(template, ordinal, rendered):
    """`template` with each class token ending in the number `ordinal` (this instance's place of `rendered` instances, counted from
    one) flagged: a part read from fewer instances than the build renders cannot say which of its numbers are fixed."""
    def token(m):
        t = m.group(0)
        tail = re.search(r"[-_](\d+)$", t)
        return FLAG % ("%s: read from %d of %d instances" % (t, 1, rendered)) if tail and int(tail.group(1)) == ordinal else t

    def attr(m):
        return m.group(1) + re.sub(r"[^\s]+", token, m.group(2)) + '"'
    return _CLASS.sub(attr, template)


def size_slots(template, call):
    """`template` with a picture's own `width` and `height` written as those slots, where `call` has them."""
    for slot in ("width", "height"):
        if call.table.get(slot) and re.search(r' %s="\d+"' % slot, template):
            template = re.sub(r' %s="\d+"' % slot, ' %s="{{%s}}"' % (slot, slot), template, count=1)
    return template
