"""lookgrammar/reads.py -- a look's `reads`: the slot-to-key map (design-adopt-ownership-line section 6, rule K; site-studio
0.7.0; design-adopt-local-reach adds five targets at 0.8.0). Python 3.9, standard library only. Imports only
`lookgrammar.constructs`.

    "reads": { "<target>": <spec>, ... }
    <spec>   := [<source>, ...]                                  1 to 4 sources, no repeats
              | {"from": [<source>, ...], "unless": "<key>"}     either member may be absent, not both
    <source> := a front-matter key (^[A-Za-z][A-Za-z0-9_]*$) | a built-in "@name" the target's row lists

    READS           the closed table of targets (section 6.2): what each reads, where 0.6.0 reads it (`site`), the release that
                    added it (`first`: "0.7.0" for the nine of 0.7.0, "0.8.0" for the five of 0.8.0; `needs.release_needs` reads
                    it) and what the target takes. A target's `kind` is `slot`, `rows`, `choice` or (0.8.0) `picture`: an ordered
                    list of `PICTURE_KEYS`, no built-ins. Its `scope` is `piece`, `page` or (0.8.0) `reference`: a source is a key
                    of `REFERENCE_SOURCE_KEYS`. GRAMMAR ONLY: the build resolves a spec in `building/readsources.py` (step 6).
    parse_reads(where, value)       ({target: Spec}, [problem line]): every refusal of section 6.1, each naming the file,
                                    the target and the fix
    pair_problems(where, constructs, reads, default_has)   the look-wide pairs (section 6.3, 6.4, rule P4): a choice
                                    with no variant part to print through, a variant part with no choice, `{{usedBy}}`
                                    with no `used-by` part. Run on the look the build reads (with layering, the merged one)

A `reads` key of any content is a 0.7.0 look key (`constructs.TOP_KEY_FIRST`): 0.6.0 refuses the key itself, `{}` included.
"""
import re

from lookgrammar.constructs import CONSTRUCTS

SLOT, ROWS, CHOICE, PICTURE = "slot", "rows", "choice", "picture"
REFERENCE = "reference"      # a scope (0.8.0): the keys of a `reference.json`
MAX_SOURCES = 4
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# Section 6.2, one row per target: `kind`; `scope`, what a source is read from; `default`, the chain 0.6.0 reads (a rows
# target reads the keys of its `setting` instead); `then`, what 0.6.0 prints when the chain gives nothing; `builtins`;
# `unless`, whether the target takes it; `site`, the default-path function 0.6.0 reads the value in (READ at step 0, U-R1;
# `test_building_identity_070.py` keys a row per target on it). A choice target names a variant part (`variant_part`).
READS = {
    "video-embed.wrap.title": {"kind": SLOT, "scope": "page", "default": ("@caption",), "then": "the word Video",
                               "builtins": ("@caption",), "unless": False, "setting": None,
                               "site": ("content.py", "video_values"), "first": "0.7.0"},
    "piece-teaser.wrap.text": {"kind": SLOT, "scope": "piece", "default": ("teaser",), "then": None, "builtins": (),
                               "unless": False, "setting": None, "site": ("building/portfolios.py", "piece_teaser"),
                               "first": "0.7.0"},
    "card.teaser.text": {"kind": SLOT, "scope": "piece", "default": ("teaser",), "then": None, "builtins": (),
                         "unless": False, "setting": None, "site": ("building/portfolios.py", "card_html"),
                         "first": "0.7.0"},
    "head.description": {"kind": SLOT, "scope": "piece", "default": ("description", "teaser"), "then": "the excerpt",
                         "builtins": (), "unless": False, "setting": None,
                         "site": ("building/portfolios.py", "build_piece"), "first": "0.7.0"},
    "roles-view.item.employer": {"kind": SLOT, "scope": "piece", "default": ("employer",), "then": None, "builtins": (),
                                 "unless": False, "setting": None, "site": ("views.py", "_employer"),
                                 "first": "0.7.0"},
    "meta-list.item.value": {"kind": ROWS, "scope": "piece", "default": (), "then": None, "builtins": (), "unless": True,
                             "setting": "meta", "site": ("building/portfolios.py", "build_piece"), "first": "0.7.0"},
    "card.meta.text": {"kind": ROWS, "scope": "piece", "default": (), "then": None, "builtins": (), "unless": True,
                       "setting": "cardMeta", "site": ("building/portfolios.py", "card_html"), "first": "0.7.0"},
    "piece-roles.item-current": {"kind": CHOICE, "scope": "piece", "default": ("currentRole", "@first"), "then": None,
                                 "builtins": ("@first", "@last"), "unless": False, "setting": None,
                                 "site": ("building/piecehead.py", "current_entries"), "first": "0.7.0"},
    "tiles.item-accent": {"kind": CHOICE, "scope": "page", "default": (), "then": "the part is never used",
                          "builtins": ("@first", "@last"), "unless": False, "setting": None,
                          "site": ("contentmodel/blockkinds.py", "block_tiles"), "first": "0.7.0"},
    # ---- 0.8.0 (design-adopt-local-reach): five targets, each a K reason for schema 8 (0.7.0: "reads names the unknown target")
    # G4: the kicker line's text. The row carries `setting: "cardKicker"`: its default chain is the key that setting names,
    # which only the caller knows, so `readsources.slot` takes it as `default=` for a row with a setting.
    "kicker.wrap.text": {"kind": SLOT, "scope": "piece", "default": (), "then": None, "builtins": ("@portfolio", "@group"),
                         "unless": False, "setting": "cardKicker", "site": ("building/stepsview.py", "kicker"),
                         "first": "0.8.0"},
    # G3: what a reference card's `site` part prints. Scope `reference`: a source is a key of `reference.json`.
    "reference-card.site.text": {"kind": SLOT, "scope": REFERENCE, "default": ("site",), "then": None,
                                 "builtins": ("@kind",), "unless": False, "setting": None,
                                 "site": ("building/markdownenv.py", "ref_card"), "first": "0.8.0"},
    # G5: which picture each place shows, an ordered list of picture keys (`PICTURE_KEYS`); with no entry each place picks
    # what `cardImage` gives it today.
    "card.wrap.image": {"kind": PICTURE, "scope": "piece", "default": (), "then": None, "builtins": (), "unless": False,
                        "setting": None, "site": ("building/portfolios.py", "card_html"), "first": "0.8.0"},
    "home-showcase.item.image": {"kind": PICTURE, "scope": "piece", "default": (), "then": None, "builtins": (),
                                 "unless": False, "setting": None, "site": ("views.py", "_tile"), "first": "0.8.0"},
    "roles-view.item.image": {"kind": PICTURE, "scope": "piece", "default": (), "then": None, "builtins": (),
                              "unless": False, "setting": None, "site": ("building/pictures.py", "roles_image_slot"),
                              "first": "0.8.0"},
}
# The picture keys a `picture` target may name, in the order `pictures.COMPANIONS` holds them (pinned equal by a test, as
# `REFERENCE_SOURCE_KEYS` is pinned to the content model's reference keys: this module imports nothing of the build).
PICTURE_KEYS = ("cover", "photo", "tileImage")
REFERENCE_SOURCE_KEYS = ("url", "title", "description", "site", "published", "kind", "captured", "image", "role", "fetched",
                         "author", "imageAlt", "imagePosition")
# The parts a site places `{{usedBy}}` in (section 6.4: they share `REFERENCE_CARD_SLOTS`), and the part that fills it.
USED_BY_PARTS = (("reference-card", "wrap"), ("feed", "item"), ("home-samples", "item"))
USED_BY_PART = ("reference-card", "used-by")
# 0.8.0 (section 1.3): the part that fills `{{author}}` (placed in the same three parts), and the words `@kind` prints.
AUTHOR_PART = ("reference-card", "author")
KIND_TARGET, KIND_BUILTIN = "reference-card.site.text", "@kind"
KIND_PARTS = ("reference-card", ("kind-page", "kind-article", "kind-video"))


class Spec(object):
    """One parsed `reads` entry: `sources` (a tuple, or None when the entry names none) and `unless` (a key, or None)."""

    def __init__(self, sources, unless):
        self.sources = sources
        self.unless = unless

    def __eq__(self, other):
        return isinstance(other, Spec) and (self.sources, self.unless) == (other.sources, other.unless)

    def __repr__(self):
        return "Spec(%r, %r)" % (self.sources, self.unless)


def variant_part(target):
    """(construct, part) a choice target picks entries for: the target's own name (`tiles.item-accent`)."""
    construct, part = target.split(".", 1)
    return construct, part


def _sources(where, target, row, value):
    """(tuple of sources, [problem line]) of one `from` list."""
    if not isinstance(value, list) or not value:
        return None, ["%s: reads %s must list 1 to %d sources -- fix: write [\"<key>\"]%s"
                      % (where, target, MAX_SOURCES, "" if not row["builtins"] else ", or one of " + ", ".join(row["builtins"]))]
    out = []
    if len(value) > MAX_SOURCES:
        out.append("%s: reads %s lists %d sources; at most %d -- fix: keep the first %d you need"
                   % (where, target, len(value), MAX_SOURCES, MAX_SOURCES))
    seen = set()
    for src in value:
        if not isinstance(src, str):
            out.append("%s: reads %s: a source is a front-matter key or a built-in, not %r -- fix: write it as a string"
                       % (where, target, src))
            continue
        if src in seen:
            out.append("%s: reads %s names %r twice -- fix: name each source once" % (where, target, src))
        seen.add(src)
        if src.startswith("@"):
            if src not in row["builtins"]:
                out.append("%s: reads %s: %r is not a built-in of this target (%s) -- fix: use a front-matter key%s"
                           % (where, target, src, ", ".join(row["builtins"]) or "it has none",
                              "" if not row["builtins"] else " or " + ", ".join(row["builtins"])))
        elif not _KEY.match(src):
            out.append("%s: reads %s: %r is not a front-matter key (a letter, then letters, digits or _) -- fix: write "
                       "the key as the piece's front matter spells it" % (where, target, src))
        elif row["kind"] == PICTURE and src not in PICTURE_KEYS:
            out.append("%s: reads %s: %r is not a picture key (%s) -- fix: name the key a piece's picture is stored under"
                       % (where, target, src, ", ".join(PICTURE_KEYS)))
        elif row["scope"] == REFERENCE and src not in REFERENCE_SOURCE_KEYS:
            out.append("%s: reads %s: %r is not a key of a reference.json (%s) -- fix: name one of them%s"
                       % (where, target, src, ", ".join(REFERENCE_SOURCE_KEYS),
                          "" if not row["builtins"] else ", or " + ", ".join(row["builtins"])))
    return tuple(value), out


def parse_spec(where, target, value):
    """(Spec or None, [problem line]) of one entry of a `reads` map."""
    row = READS.get(target)
    if row is None:
        return None, ["%s: reads names the unknown target %r -- fix: use one of %s" % (where, target, ", ".join(sorted(READS)))]
    if isinstance(value, list):
        if row["kind"] == ROWS:
            return None, ["%s: reads %s takes no list of sources: its rows are the keys of the %s setting -- fix: write "
                          "{\"unless\": \"<key>\"}" % (where, target, row["setting"])]
        sources, out = _sources(where, target, row, value)
        return (Spec(sources, None) if not out else None), out
    if not isinstance(value, dict):
        return None, ["%s: reads %s is a list of sources or an object with from and unless -- fix: write [\"<key>\"]"
                      % (where, target)]
    out = ["%s: reads %s has the unknown member %r (from, unless) -- fix: remove it" % (where, target, k)
           for k in sorted(value) if k not in ("from", "unless")]
    if "from" not in value and "unless" not in value:
        out.append("%s: reads %s names neither from nor unless -- fix: give one, or remove the entry" % (where, target))
    sources = unless = None
    if "from" in value:
        if row["kind"] == ROWS:
            out.append("%s: reads %s takes no from: its rows are the keys of the %s setting -- fix: remove from"
                       % (where, target, row["setting"]))
        else:
            sources, more = _sources(where, target, row, value["from"])
            out.extend(more)
    if "unless" in value:
        unless = value["unless"]
        if not row["unless"]:
            out.append("%s: reads %s takes no unless (only %s do) -- fix: remove unless"
                       % (where, target, ", ".join(sorted(t for t, r in READS.items() if r["unless"]))))
        elif not isinstance(unless, str) or not _KEY.match(unless):
            out.append("%s: reads %s: unless names a front-matter key, not %r -- fix: write the key, such as \"title\""
                       % (where, target, unless))
    return (Spec(sources, unless) if not out else None), out


def parse_reads(where, value):
    """({target: Spec}, [problem line]) of a look's `reads` value. `{}` is a valid, empty map."""
    if not isinstance(value, dict):
        return {}, ["%s: `reads` is an object of target -> sources -- fix: write {\"<target>\": [\"<key>\"]}" % where]
    clean, out = {}, []
    for target in sorted(value):
        spec, problems = parse_spec(where, target, value[target])
        out.extend(problems)
        if spec is not None:
            clean[target] = spec
    return clean, out


def pair_problems(where, constructs, reads, default_has):
    """[problem line] of the pairs a look must hold together (sections 6.3 and 6.4; rule P4 runs it on the merged look).
    `constructs` {id: {part: markup}} and `reads` {target: Spec} are the look's own; `default_has(construct, part)` says
    whether the default look renders a part this look omits."""
    out = []
    for target, row in sorted(READS.items()):
        if row["kind"] != CHOICE:
            continue
        construct, part = variant_part(target)
        own = part in constructs.get(construct, {})
        if target in reads and not (own or default_has(construct, part)):
            out.append("%s: reads %s picks entries for the part %s.%s, which the look does not write -- fix: write the "
                       "part, or remove the reads entry" % (where, target, construct, part))
        if own and target not in reads and not default_has(construct, part):
            out.append("%s: the part %s.%s is printed only for the entries reads %s picks, and the look has no such entry "
                       "-- fix: add \"%s\": [\"@first\"] (or @last, or a key) to reads, or remove the part"
                       % (where, construct, part, target, target))
    placed = [c + "." + p for c, p in USED_BY_PARTS if "{{usedBy}}" in constructs.get(c, {}).get(p, "")]
    if placed and USED_BY_PART[1] not in constructs.get(USED_BY_PART[0], {}):
        out.append("%s: %s place {{usedBy}}, and the look writes no %s.%s part to fill it -- fix: write the part (its "
                   "slots are {{title}} and {{url}}), or remove the slot" % (where, " and ".join(placed), *USED_BY_PART))
    # 0.8.0 (design-adopt-local-reach section 1.3): `{{author}}` is printed through the optional part `reference-card.author`,
    # and `@kind` through the text of a `reference-card.kind-*` part; each without its part would print nothing, silently.
    placed = [c + "." + p for c, p in USED_BY_PARTS if "{{author}}" in constructs.get(c, {}).get(p, "")]
    if placed and AUTHOR_PART[1] not in constructs.get(AUTHOR_PART[0], {}):
        out.append("%s: %s place {{author}}, and the look writes no %s.%s part to fill it -- fix: write the part (its "
                   "slot is {{text}}), or remove the slot" % (where, " and ".join(placed), *AUTHOR_PART))
    spec = reads.get(KIND_TARGET)
    if spec is not None and KIND_BUILTIN in (spec.sources or ()) and not any(
            p in constructs.get(KIND_PARTS[0], {}) for p in KIND_PARTS[1]):
        out.append("%s: reads %s names @kind, and the look writes none of the parts %s.%s -- fix: write the words (such as "
                   "\"kind-page\": \"Website\"), or remove @kind from the entry"
                   % (where, KIND_TARGET, KIND_PARTS[0], ", ".join(KIND_PARTS[1])))
    return out


def table_problems():
    """The table's own consistency ([] is sound): each target names a construct part, each choice a part of the table."""
    out = []
    for target, row in READS.items():
        if not re.match(r"^\d+\.\d+\.\d+$", row.get("first", "")):
            out.append("%s: names no release it first needs (first)" % target)
        bits = target.split(".")
        if bits[0] == "head":
            continue                # the page head's description: no construct, `building/portfolios.py` writes it
        if len(bits) != 3 and row["kind"] != CHOICE:
            out.append("%s: a slot or rows target is <construct>.<part>.<slot>" % target)
            continue
        construct, part = bits[0], bits[1]
        if construct not in CONSTRUCTS or part not in CONSTRUCTS[construct]["parts"]:
            out.append("%s: names no construct part" % target)
        elif len(bits) == 3 and bits[2] not in CONSTRUCTS[construct]["parts"][part]:
            out.append("%s: names no slot of %s.%s" % (target, construct, part))
    return out
