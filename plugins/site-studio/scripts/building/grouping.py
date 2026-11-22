"""grouping: a portfolio's pieces group by group, as its index shows them, and the featured shelf as a view of each
portfolio's index (design-adopt-parity-2 sections 4.1 and 4.2).

    group_sections(pf, pieces)            [(group value, its pieces)] in the order of `groups`, each group that holds one
    groups_html(builder, pf, pieces, out) those groups through `group.wrap`, as a grouped index prints them
    count_unit(settings, group, n)        the word after the number of a group heading (`labels.counts`)
    count_slot(builder, pf, group, n, out) the gated `group.wrap` `count` slot, filled only under `groupCount`
    number_alone(rendered, markup)        that count with an empty word: no whitespace written beside the missing word
    featured_html(builder, pieces, out)   `{{featured}}` and the generated home's featured part

Default path, stated: without `featuredView: grouped` the shelf is `cards_html` of the selection, byte for byte what
0.5.x printed; without `groupCount` the `count` slot is "" (rule L3a) and no `schema-6.css` is linked. The `group` open
slot of `cards.wrap` and `group.wrap` is always filled (the group's own value, "" outside a group), and no default part
holds it, so no default byte moves. Every key read here is a schema-6 key, so no tree 0.5.x accepted holds one."""

import re

from contentmodel import keytables

import looks

_SLOT = re.compile(r"\{\{[^{}]*\}\}")        # a slot of a look's part (looks.py's own form)


def group_sections(pf, pieces):
    """[(group value, its pieces in the order given)] of a portfolio with `groupBy`, in the order of its `groups`; a group
    with none of `pieces` is left out, as a grouped index leaves it out."""
    st = pf.settings
    out = []
    for g in st["groups"]:
        ps = [p for p in pieces if p.meta.get(st["groupBy"]) == g]
        if ps:
            out.append((g, ps))
    return out


def count_unit(settings, group, n):
    """The word after the number `n` of a group heading: from `labels.counts[<group value>]`, else `labels.counts["*"]`,
    else none; its `one` word when `n` is 1 and its `other` word for every other number (CLDR's two categories of a
    language with two forms; section 4.2 says what two forms cover). A missing member is "": the number prints alone."""
    counts = settings["labels"].get("counts", {})
    forms = counts[group] if group in counts else counts.get("*", {})
    return forms.get("one" if n == 1 else "other", "")


def count_slot(builder, pf, group, n, out):
    """The gated `group.wrap` `count` slot: `group-count.wrap` holding `n` (the number of cards this group prints HERE)
    and its word, with the link to `schema-6.css`, when the portfolio holds `groupCount`; else "" (no link either)."""
    triggers = keytables.active_triggers(pf.settings)
    if "groupCount" not in triggers:
        return ""
    unit = count_unit(pf.settings, group, n)
    assets = builder.assets(out, "group-count")
    count = builder.r("group-count", "wrap", {"n": n, "unit": unit}, pf.page_source)
    if not unit:
        count = number_alone(count, looks.part_markup("group-count", "wrap", builder.look))
    return looks.gate("group", "wrap", "count", triggers, assets + count)


def number_alone(rendered, markup):
    """`rendered`, the count filled with an empty word, without the whitespace the look's `markup` writes between the number
    and the missing `{{unit}}` (section 4.2: "a missing member prints the number alone", so `{{n}} {{unit}}` prints `2`, never
    `2 `). It goes only where the word stood at an edge of its text (the markup's end or a tag on its far side) and that side
    of the slot holds no other slot, so every other byte is the rendered one; a look that writes text beside the word, or
    another slot there, prints exactly what it rendered. Schema 6 only (`groupCount`)."""
    if markup.count("{{unit}}") != 1:
        return rendered
    before, after = markup.split("{{unit}}")
    if (not after or after.startswith("<")) and not _SLOT.search(after) and rendered.endswith(after):
        head = rendered[:len(rendered) - len(after)]
        return head.rstrip() + after
    if (not before or before.endswith(">")) and not _SLOT.search(before) and rendered.startswith(before):
        return before + rendered[len(before):].lstrip()
    return rendered


def groups_html(builder, pf, pieces, out):
    """The groups of `pieces` (a subset of `pf.pieces`, in its order) through `group.wrap`: the group's label, its cards
    in `cards.wrap`, the count under `groupCount`, and the group's own value in the open `group` slot."""
    st = pf.settings
    body = []
    for g, ps in group_sections(pf, pieces):
        body.append(builder.r("group", "wrap", {"title": st["labels"]["groups"].get(g, g),
                                                "cards": builder.cards_html(ps, out, group=g),
                                                "count": count_slot(builder, pf, g, len(ps), out),
                                                "group": g}))
    return "".join(body)


def featured_html(builder, pieces, out):
    """The featured selection `pieces` on the page at `out`. `featuredView: grouped` (schema 6): a filtered view of each
    portfolio's index, portfolios in menu order; a portfolio with `groupBy` prints its groups (each holding only its
    featured pieces, in the portfolio's own sort), one without prints one `cards.wrap`; a portfolio or group with no
    featured piece prints nothing. The selection itself is unchanged (`featuredFrom`), and each card is `card_html`, so
    the card settings of the piece's own portfolio apply. Otherwise (`flat`, the default): `cards_html(pieces)`."""
    if builder.cfg.featuredView != "grouped":
        return builder.cards_html(pieces, out)
    chosen = set((p.portfolio, p.slug) for p in pieces)
    body = []
    for pf in builder.model.menu_portfolios():
        mine = [p for p in pf.pieces if (p.portfolio, p.slug) in chosen]
        if not mine:
            continue
        body.append(groups_html(builder, pf, mine, out) if pf.settings["groupBy"] else builder.cards_html(mine, out))
    return "".join(body)
