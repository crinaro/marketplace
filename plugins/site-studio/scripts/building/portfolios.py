"""A portfolio's index, its cards and its piece pages."""

import posixpath
import re
from urllib.parse import urlsplit

from contentmodel import frontmatter, grammar
from configschema import configkeys

import looks

from building import grouping, piecehead, pictures, readsources, stepsview
from building.outcomes import BuildError
from building.tokens import rel_link


def card_teaser_html(builder, piece):
    """A card's `teaser` slot: the `card.teaser` part through `card.teaser.text` (the look's `reads` entry, else the piece's
    `teaser`), "" for a piece with no text. Extracted from `card_html` unedited (0.8.0): the roles card's `{{teaser}}` (design-adopt-
    local-reach section 1.2, dev #1038) calls this same function, `views.py` by name, for the group's newest piece."""
    text = readsources.slot(builder.look, "card.teaser.text", piece.meta.get)       # 0.7.0 `reads`; else `teaser`
    return builder.r("card", "teaser", {"text": text}, piece.source) if text else ""


def card_meta_html(builder, piece, pf):
    """A card's `meta` slot: the `card.meta` part over the rows of the piece's own portfolio's `cardMeta` that print
    (`card.meta.text`'s `unless`), with the `labels.meta` names unless `cardLabels` is false; "" when no row prints. Extracted from
    `card_html` unedited (0.8.0), as `card_teaser_html` is: the roles card's `{{meta}}` calls it with the newest piece's portfolio."""
    names = pf.settings["labels"]["meta"]
    labelled = pf.settings.get("cardLabels", True)      # schema 4 `cardLabels: false`: values only on a card
    cm = [("%s: %s" % (names[k], frontmatter.meta_text(piece.meta[k])) if (k in names and labelled)
           else frontmatter.meta_text(piece.meta[k]))
          for k in readsources.rows(builder.look, "card.meta.text", piece.meta, pf.settings["cardMeta"])]
    return builder.r("card", "meta", {"text": " \u00b7 ".join(cm)}, piece.source) if cm else ""


class _Portfolios(object):
    # ---- cards
    @staticmethod
    def _whole(v):
        """A whole number from a front-matter value (an int, or digits), else None."""
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v if 0 <= v <= 999999 else None
        if isinstance(v, str) and re.match(r"^\d{1,6}$", v.strip()):
            return int(v.strip())
        return None

    def card_number(self, piece, pf, from_out, position=None):
        """`cardNumber` (schema 4): the card's `NN / YYYY`. NN is the piece's `order` zero-padded to two digits
        (`cardNumberFormat: "plain"`, schema 4: as it is, `2` for 2), YYYY its `year` (a whole number) or the year
        of its `date`; a part the piece does not have is left out (and so is the separator). `cardNumberFormat:
        "order"` (schema 4) prints the order as it is and never the year (`2`); a piece with no order prints no
        number. "" when the setting is off or the piece has nothing to print.

        0.7.0 (design-adopt-ownership-line section 5, owner decision 2): `position`, the card's running position on its
        page, stands where the `order` stands (`{{position}}` in `card.wrap`); and a `card.number` that places `{{text}}`
        renders ONCE with the whole joined string (`01 / 2022`), where one that places `{{n}}` renders once per part."""
        if not pf.settings.get("cardNumber"):
            return ""
        shown = []
        fmt = pf.settings.get("cardNumberFormat")
        order = position if position is not None else self._whole(piece.meta.get("order"))
        if order is not None:
            shown.append(str(order) if fmt in ("plain", "order") else "%02d" % order)
        year = self._whole(piece.meta.get("year"))
        if year is None and piece.date and re.match(r"^\d{4}-", piece.date):
            year = int(piece.date[:4])
        if year is not None and fmt != "order":
            shown.append(str(year))
        if not shown:
            return ""
        if looks.places("card", "number", "text", self.look):
            return self.assets(from_out, "card") + self.r("card", "number", {"text": " / ".join(shown)}, piece.source)
        return (self.assets(from_out, "card")                  # 0.6.0's values exactly: derive reads what a slot was given
                + " / ".join(self.r("card", "number", {"n": n}, piece.source) for n in shown))

    def card_position(self, piece, pf, from_out):
        """`{{position}}` (0.7.0): the card's number with its running position on the page `from_out` (1 for the first
        card printed there, counting across groups and lists) in place of the `order`. The counter moves only when the
        effective `card.wrap` places the slot, so a look without it builds as before; "" when `cardNumber` is off."""
        if not looks.places("card", "wrap", "position", self.look):
            return ""
        seen = self.__dict__.setdefault("_card_positions", {})
        seen[from_out] = seen.get(from_out, 0) + 1
        return self.card_number(piece, pf, from_out, position=seen[from_out])

    def card_html(self, piece, from_out):
        to = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        pf = self.model.portfolio(piece.portfolio)         # the piece's OWN portfolio: every trigger is read from it
        picture = pictures.card_picture(self, piece, pf.settings, pictures.CARD_IMAGE_TARGET)     # design-movement-view section 5: `cover` unless a trigger or (0.8.0) a `reads` entry says otherwise
        img = picture.html(self, from_out) if picture else ""
        teaser = card_teaser_html(self, piece)
        meta = card_meta_html(self, piece, pf)
        position = self.card_position(piece, pf, from_out)        # "" and no count when the effective card.wrap lacks it
        own = {"position": position} if looks.places("card", "wrap", "position", self.look) else {}
        return self.r("card", "wrap", dict(own, **{"url": rel_link(from_out, to), "image": img, "title": piece.card_title,
                                       "fullTitle": piece.title,             # step G, O4a: no default part holds it
                                       "teaser": teaser, "meta": meta,
                                       "number": self.card_number(piece, pf, from_out),
                                       "kicker": stepsview.kicker_slot(self, "card", "wrap", piece, from_out)}),
                      piece.source)

    def cover_of(self, piece, key="cover"):
        """(repo path, output path) of the image a piece's `key` names (`cover`, or the view key `tileImage`: the
        same two forms, a file in the piece's folder or `ref:<reference>`), or None when it has none. `cover` is
        checked when the content is read; a `tileImage` that names no file is refused here, naming the piece."""
        cv = piece.meta.get(key)
        if not cv:
            return None
        if cv.startswith("ref:"):
            name = cv[4:]
            ref = self.model.references.get(name)
            if ref is None or not ref.card_path:
                raise BuildError("%s: %s %s names no reference with a card image" % (piece.source, key, cv), path=piece.source,
                                 fix="capture the reference first, or point %s at an image in media/" % key)
            self.used_refs.add(name)
            return ref.card_path, self._card_out(ref)
        full = posixpath.normpath(posixpath.join(piece.folder, cv))
        if full not in self.media_out:
            raise BuildError("%s: %s '%s' is not a file in %s/media/" % (piece.source, key, cv, piece.folder),
                             path=piece.source, fix="put the image in %s/media/ and name it as media/<file>" % piece.folder)
        return full, self.media_out[full]

    def cards_html(self, pieces, from_out, group=""):
        """The cards of `pieces` in `cards.wrap`; `group` (schema 6's open slot) is the group's own value, "" outside a group."""
        return self.r("cards", "wrap", {"items": "".join(self.card_html(p, from_out) for p in pieces), "group": group})

    # ---- the pages
    def build_portfolios(self):
        for pf in self.model.portfolios:
            self.build_portfolio(pf)
            for piece in pf.pieces:
                self.build_piece(pf, piece)

    def build_portfolio(self, pf):
        out = "%s/index.html" % pf.slug
        st = pf.settings
        if st["view"] == "page":      # schema 3: the index is the person's own site/src page, served as written
            return
        if self.single_piece_redirect(pf):     # schema 3: the nav links the piece; the index URL redirects to it (no orphan page)
            self.build_index_redirect(out, "%s/%s/index.html" % (pf.slug, pf.pieces[0].slug))
            return
        if st["view"] in configkeys.V4_PAGE_VIEWS + configkeys.V5_PAGE_VIEWS:     # roles, map, showcase (4), steps (5)
            cards = self.views().index_html(self, pf, out)
        elif st["groupBy"]:            # each group through `group.wrap`; its count only under `groupCount` (schema 6)
            cards = grouping.groups_html(self, pf, pf.pieces, out)
        else:
            cards = self.cards_html(pf.pieces, out) if pf.pieces else ""
        intro = self.markdown(pf.intro, pf.page_source or "content/%s" % pf.slug, out,
                              "content/" + pf.slug, pf.intro_line) if pf.intro.strip() else ""
        desc = st["description"] or grammar.plain_excerpt(pf.intro, grammar=self.grammar) or \
            "%s: %s" % (self.cfg.siteTitle, st["label"])
        tagline = (self.assets(out, "tagline") + self.r("tagline", "wrap", {"text": st["tagline"]})
                   if st["tagline"] else "")
        self.emit_page(out, "portfolio", pf.page_source or "content/%s/" % pf.slug,
                       self.full_title(pf.title), pf.title, desc,
                       self.r("portfolio", "wrap", {"title": pf.title, "tagline": tagline, "intro": intro,
                                                    "cards": cards, "slug": pf.slug}))

    def back_link(self, pf, piece, out):
        """`backLink` (schema 4): a link to the portfolio's index above the piece title, with the person's
        words. "" when the setting is off."""
        text = pf.settings.get("backLink")
        if not text:
            return ""
        return (self.assets(out, "back-link")
                + self.r("back-link", "wrap", {"url": rel_link(out, "%s/index.html" % pf.slug), "label": text},
                         piece.source))

    def piece_link(self, piece, out):
        """`pieceLink: true` (schema 5, design-movement-view section 3.2): the piece page's one outbound link, address
        `link`, text `linkLabel`, else the address's host, in the gated `piece.wrap` `link` slot. "" without the trigger
        of the piece's own portfolio, or for a piece with no `link`."""
        triggers = stepsview.piece_triggers(self, piece)
        address = piece.meta.get("link")
        if "pieceLink" not in triggers or not address:
            return ""
        label = piece.meta.get("linkLabel") or urlsplit(address).hostname or address
        markup = self.assets(out, "piece-link") + self.r("piece-link", "wrap", {"url": address, "label": label},
                                                          piece.source)
        return looks.gate("piece", "wrap", "link", triggers, markup)

    def piece_teaser(self, piece, out):
        """`pieceTeaser: true` (schema 5): the piece's `teaser` as one paragraph under its title, in the gated
        `piece.wrap` `teaser` slot (the card and the meta description keep using it). "" without the trigger."""
        triggers = stepsview.piece_triggers(self, piece)
        text = readsources.slot(self.look, "piece-teaser.wrap.text", piece.meta.get)    # 0.7.0 `reads`; else `teaser`
        if "pieceTeaser" not in triggers or not text:
            return ""
        markup = self.assets(out, "piece-teaser") + self.r("piece-teaser", "wrap", {"text": text}, piece.source)
        return looks.gate("piece", "wrap", "teaser", triggers, markup)

    def build_piece(self, pf, piece):
        out = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        names = pf.settings["labels"]["meta"]
        meta_rows = "".join(self.r("meta-list", "item", {"name": names.get(k) or k[:1].upper() + k[1:],
                                                         "value": frontmatter.meta_text(piece.meta[k])}, piece.source)
                            for k in readsources.rows(self.look, "meta-list.item.value", piece.meta, pf.settings["meta"]))
        dl = self.r("meta-list", "wrap", {"items": meta_rows}) if meta_rows else ""
        body = self.markdown(piece.body, piece.source, out, piece.folder, piece.first_line)
        desc = readsources.slot(self.look, "head.description", piece.meta.get) or \
            grammar.plain_excerpt(piece.body, grammar=self.grammar) or "%s: %s" % (piece.title, self.cfg.siteTitle)
        cover = self.cover_of(piece)
        group = piece.meta.get(pf.settings["groupBy"]) if pf.settings["groupBy"] else None
        self.emit_page(out, "piece", piece.source, self.full_title(piece.title), piece.title, desc,
                       self.r("piece", "wrap", {"title": piece.title, "meta": dl, "body": body,
                                                "back": self.back_link(pf, piece, out), "slug": piece.slug,
                                                "portfolio": pf.slug,
                                                "group": group if isinstance(group, str) else "",
                                                "teaser": self.piece_teaser(piece, out),     # first: it prints first
                                                "link": self.piece_link(piece, out),
                                                "roles": piecehead.roles_slot(self, piece, out)}, piece.source),
                       image_out=cover[1] if cover else None, og_type="article",
                       lastmod_src=piece.folder)
