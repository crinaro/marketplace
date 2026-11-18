"""A portfolio's index, its cards and its piece pages."""

import posixpath
import re

import content as C
import siteconfig

from building.outcomes import BuildError
from building.tokens import rel_link


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

    def card_number(self, piece, pf, from_out):
        """`cardNumber` (schema 4): the card's `NN / YYYY`. NN is the piece's `order` zero-padded to two digits
        (`cardNumberFormat: "plain"`, schema 4: as it is, `2` for 2), YYYY its `year` (a whole number) or the year
        of its `date`; a part the piece does not have is left out (and so is the separator). `cardNumberFormat:
        "order"` (schema 4) prints the order as it is and never the year (`2`); a piece with no order prints no
        number. "" when the setting is off or the piece has nothing to print."""
        if not pf.settings.get("cardNumber"):
            return ""
        shown = []
        fmt = pf.settings.get("cardNumberFormat")
        order = self._whole(piece.meta.get("order"))
        if order is not None:
            shown.append(str(order) if fmt in ("plain", "order") else "%02d" % order)
        year = self._whole(piece.meta.get("year"))
        if year is None and piece.date and re.match(r"^\d{4}-", piece.date):
            year = int(piece.date[:4])
        if year is not None and fmt != "order":
            shown.append(str(year))
        if not shown:
            return ""
        return (self.assets(from_out, "card")
                + " / ".join(self.r("card", "number", {"n": n}, piece.source) for n in shown))

    def card_html(self, piece, from_out):
        to = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        pf = self.model.portfolio(piece.portfolio)
        img = ""
        cover = self.cover_of(piece)
        if cover:
            repo_path, out_path = cover
            img = self.img_tag(repo_path, "", from_out, out_path=out_path, focus=piece.meta.get("coverPosition"))
        teaser = (self.r("card", "teaser", {"text": piece.meta["teaser"]}, piece.source)
                  if piece.meta.get("teaser") else "")
        names = pf.settings["labels"]["meta"]
        labelled = pf.settings.get("cardLabels", True)      # schema 4 `cardLabels: false`: values only on a card
        cm = [("%s: %s" % (names[k], C.meta_text(piece.meta[k])) if (k in names and labelled)
               else C.meta_text(piece.meta[k])) for k in pf.settings["cardMeta"] if k in piece.meta]
        meta = self.r("card", "meta", {"text": " \u00b7 ".join(cm)}, piece.source) if cm else ""
        return self.r("card", "wrap", {"url": rel_link(from_out, to), "image": img, "title": piece.card_title,
                                       "teaser": teaser, "meta": meta,
                                       "number": self.card_number(piece, pf, from_out)}, piece.source)

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

    def cards_html(self, pieces, from_out):
        return self.r("cards", "wrap", {"items": "".join(self.card_html(p, from_out) for p in pieces)})

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
        if st["view"] in siteconfig.V4_PAGE_VIEWS:        # schema 4: roles, map or showcase, built by the views module
            cards = self.views().index_html(self, pf, out)
        elif st["groupBy"]:
            body = []
            for g in st["groups"]:
                ps = [p for p in pf.pieces if p.meta.get(st["groupBy"]) == g]
                if ps:
                    body.append(self.r("group", "wrap", {"title": st["labels"]["groups"].get(g, g),
                                                         "cards": self.cards_html(ps, out)}))
            cards = "".join(body)
        else:
            cards = self.cards_html(pf.pieces, out) if pf.pieces else ""
        intro = self.markdown(pf.intro, pf.page_source or "content/%s" % pf.slug, out,
                              "content/" + pf.slug, pf.intro_line) if pf.intro.strip() else ""
        desc = st["description"] or C.plain_excerpt(pf.intro, grammar=self.grammar) or \
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

    def build_piece(self, pf, piece):
        out = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        names = pf.settings["labels"]["meta"]
        meta_rows = "".join(self.r("meta-list", "item", {"name": names.get(k) or k[:1].upper() + k[1:],
                                                         "value": C.meta_text(piece.meta[k])}, piece.source)
                            for k in pf.settings["meta"] if k in piece.meta)
        dl = self.r("meta-list", "wrap", {"items": meta_rows}) if meta_rows else ""
        body = self.markdown(piece.body, piece.source, out, piece.folder, piece.first_line)
        desc = piece.meta.get("description") or piece.meta.get("teaser") or \
            C.plain_excerpt(piece.body, grammar=self.grammar) or "%s: %s" % (piece.title, self.cfg.siteTitle)
        cover = self.cover_of(piece)
        group = piece.meta.get(pf.settings["groupBy"]) if pf.settings["groupBy"] else None
        self.emit_page(out, "piece", piece.source, self.full_title(piece.title), piece.title, desc,
                       self.r("piece", "wrap", {"title": piece.title, "meta": dl, "body": body,
                                                "back": self.back_link(pf, piece, out), "slug": piece.slug,
                                                "portfolio": pf.slug,
                                                "group": group if isinstance(group, str) else ""}, piece.source),
                       image_out=cover[1] if cover else None, og_type="article",
                       lastmod_src=piece.folder)
