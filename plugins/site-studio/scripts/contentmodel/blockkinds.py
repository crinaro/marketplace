"""The plugin blocks the block renderer builds: tiles, quote, quotes, gallery, videos and carousel."""

import re

import looks

from contentmodel.errors import ContentError
from contentmodel.grammar import Fragment, _GALLERY_ROW_TRAIL, _HEADING, _IMGLINE3
from contentmodel.links import _URL_SCHEME_OR_PROTOREL


class _BlockKinds(object):
    def block_tiles(self, inner, label, n):
        """A grid of figures. 0.7.0 (design-adopt-ownership-line section 6.3): a tile whose position the environment's
        `tile_accent` names (the look's `reads` `tiles.item-accent`, read from the page's front matter) prints through the
        variant part `tiles.item-accent`; without an entry it names none, and every tile prints through `tiles.item`."""
        items = []
        rows = self.rows(inner, n, "tiles")
        accent = getattr(self.env, "tile_accent", None)
        picked = accent(len(rows)) if accent is not None else frozenset()
        for ln, row in rows:
            if "|" not in row:
                raise ContentError("%s: a tile row is 'figure | label' and this one has no '|'"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write the row as figure | label, such as 1,200+ | visits")
            figure, _, text = row.partition("|")
            figure, text = figure.strip(), text.strip()
            if not figure or not text:
                raise ContentError("%s: a tile row needs a figure and a label on both sides of '|'"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write the row as figure | label, such as 1,200+ | visits")
            part = "item-accent" if len(items) + 1 in picked else "item"
            items.append(self.r("tiles", part, {"figure": figure, "text": text, "n": len(items) + 1}, ln))
        return self.assets("tiles") + self.r("tiles", "wrap", {"items": "".join(items), "label": label,
                                                               "count": len(items)}, n)

    @staticmethod
    def attribution(text):
        """Who said it, from a line starting '— ' (or '-- '); None for any other line."""
        s = text.strip()
        if s.startswith("— "):
            return s[2:].strip()
        if s.startswith("-- "):
            return s[3:].strip()
        return None

    def quote_paragraphs(self, rows):
        """[[line, ...], ...]: the quoted words of `rows`, a blank line between paragraphs."""
        paras, cur = [], []
        for _ln, text in rows:
            if text.strip():
                cur.append(text.strip())
            elif cur:
                paras.append(cur)
                cur = []
        if cur:
            paras.append(cur)
        return paras

    def block_quote(self, inner, label, n):
        rows = [(inner.nums[k], l.rstrip()) for k, l in enumerate(inner.lines)]
        while rows and not rows[-1][1].strip():
            rows.pop()
        if not rows:
            raise ContentError("%s: the :::quote block is empty" % self._at(n), path=self.where, lineno=n,
                               fix="write the quoted words inside the block, then an optional line "
                                   "starting '— ' with who said it")
        by = self.attribution(rows[-1][1])
        if by is not None:
            rows.pop()
        paras = self.quote_paragraphs(rows)
        if not paras:
            raise ContentError("%s: the :::quote block holds only an attribution" % self._at(n),
                               path=self.where, lineno=n,
                               fix="write the quoted words above the '— ' line")
        body = self.quote_body(paras)
        cap = self.r("quote", "by", {"who": self.quote_by(by)}, n) if by else ""
        return self.assets("quote") + self.r("quote", "wrap", {"body": body, "by": cap}, n)

    def block_quotes(self, inner, label, n):
        """Several quotes in one block, each ended by its '— ' line (schema 4): a grid of quote cards."""
        rows = [(inner.nums[k], l.rstrip()) for k, l in enumerate(inner.lines)]
        if not any(text.strip() for _ln, text in rows):
            raise ContentError("%s: the :::quotes block is empty" % self._at(n), path=self.where, lineno=n,
                               fix="write each quote's words, then a line starting '— ' with who said it")
        quotes, cur = [], []
        for ln, text in rows:
            by = self.attribution(text)
            if by is None:
                cur.append((ln, text))
                continue
            paras = self.quote_paragraphs(cur)
            if not paras:
                raise ContentError("%s: this '— ' line has no quoted words above it" % self._at(ln),
                                   path=self.where, lineno=ln,
                                   fix="write the quote's words above the '— ' line, or remove the line")
            quotes.append((paras, by))
            cur = []
        left = [(ln, text) for ln, text in cur if text.strip()]
        if left:
            raise ContentError("%s: this quote has no '— ' line after it; every quote in :::quotes is ended "
                               "by one" % self._at(left[0][0]), path=self.where, lineno=left[0][0],
                               fix="end the quote with a line starting '— ' and who said it, or use a "
                                   ":::quote block for one quote with no attribution")
        items = "".join(
            self.r("quotes", "item", {"body": self.quote_body(paras),
                                      "by": self.r("quotes", "by", {"who": self.quote_by(by)}, n)}, n)
            for paras, by in quotes)
        return self.assets("quotes") + self.r("quotes", "wrap", {"items": items, "label": label or "Quotes",
                                                                 "count": len(quotes)}, n)

    def gallery_video(self, m, ln):
        """One gallery item that opens or plays a video (schema 4): `![alt](path "caption") <video link>`."""
        alt, src, cap, url = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        embed = self.embed_for(url, ln)
        host = re.sub(r"^www\.", "", re.sub(r"^https://", "", url).split("/")[0])
        title = cap or alt or host        # the caption first: a template's `aria-label` repeats the words the viewer reads under the photo
        caption = self.r("gallery-video", "caption", {"text": cap, "url": url, "embed": embed, "title": title}, ln) if cap else ""
        return self.r("gallery-video", "item", {"url": url, "embed": embed, "image": self.block_image(src, alt),
                                                "title": title, "caption": caption}, ln)

    def block_gallery(self, inner, label, n):
        items, has_video = [], False
        for ln, row in self.rows(inner, n, "gallery"):
            m = _IMGLINE3.match(row)
            if m:
                cap = self.r("gallery", "caption", {"text": m.group(3)}, ln) if m.group(3) else ""
                items.append(self.r("gallery", "item", {"image": self.block_image(m.group(2), m.group(1)),
                                                        "caption": cap}, ln))
                continue
            v = _GALLERY_ROW_TRAIL.match(row) if self.grammar >= 4 else None
            if v:
                items.append(self.gallery_video(v, ln))
                has_video = True
                continue
            raise ContentError("%s: a gallery holds image lines only, and this is not one"
                               % self._at(ln) if self.grammar < 4 else
                               "%s: a gallery holds image lines, or an image line followed by a video link, and "
                               "this is neither" % self._at(ln), path=self.where, lineno=ln,
                               fix="write each line as ![alt](media/file.jpg), one per line" if self.grammar < 4 else
                                   "write each line as ![alt](media/file.jpg), and add a YouTube, Vimeo or public "
                                   "Drive link after it for a photo that plays a video")
        kinds = list(looks.assets_for("gallery", self.look))
        if has_video:
            kinds += [k for k in looks.assets_for("gallery-video", self.look) if k not in kinds]
        tags = "".join(self.asset(k) for k in kinds)
        values = {"items": "".join(items), "count": len(items)}
        if label:
            values["label"] = label
        return tags + self.r("gallery", "wrap-labelled" if label else "wrap", values, n)

    def block_videos(self, inner, label, n):
        items = []
        for ln, row in self.rows(inner, n, "videos"):
            cols = [c.strip() for c in row.split("|")]
            if len(cols) not in (2, 3) or not cols[0] or not cols[1]:
                raise ContentError("%s: a video row is 'title | url' or 'title | url | media/poster.jpg'"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write the row as title | url, and add | media/poster.jpg for a photo "
                                       "that plays the video")
            title, url = cols[0], cols[1]
            embed = self.embed_for(url, ln)
            if len(cols) == 3 and cols[2]:
                poster = cols[2]
                if _URL_SCHEME_OR_PROTOREL.match(poster):
                    raise ContentError("%s: the poster %r is a remote address; a facade loads nothing from "
                                       "a third party before a click" % (self._at(ln), poster),
                                       path=self.where, lineno=ln,
                                       fix="commit the image under media/ and name it as media/poster.jpg")
                items.append(self.r("videos", "item-poster", {"url": url, "embed": embed, "title": title,
                                                              "image": self.block_image(poster, ""),
                                                              "kind": "embed"}, ln))
            else:
                host = re.sub(r"^www\.", "", re.sub(r"^https://", "", url).split("/")[0])
                items.append(self.r("videos", "item", {"url": url, "embed": embed, "title": title, "host": host,
                                                       "kind": "embed"}, ln))
        values = {"items": "".join(items)}
        if label:
            values["label"] = label
        return self.assets("videos") + self.r("videos", "wrap-labelled" if label else "wrap", values, n)

    def block_carousel(self, inner, label, n):
        self.rows(inner, n, "carousel")
        heads = []
        for k, l in enumerate(inner.lines):
            m = _HEADING.match(l)
            if m and len(m.group(1)) == 3 and inner.nums[k] not in self.plain:
                heads.append(k)
        outer, self.in_block = self.in_block, True       # a slide's headings follow `blocks.headingLevel`
        try:
            if heads:
                cuts = ([0] if heads[0] > 0 and any(l.strip() for l in inner.lines[:heads[0]]) else []) + heads
                cuts.append(len(inner.lines))
                slides = []
                for a, b in zip(cuts, cuts[1:]):
                    part = Fragment(inner.lines[a:b], inner.nums[a:b], self.plain)
                    slides.append("\n".join(self.blocks(part)))
            else:
                slides = self.blocks(inner)
        finally:
            self.in_block = outer
        lis = "".join(self.r("carousel", "item", {"body": s}, n) for s in slides if s)
        return self.assets("carousel") + self.r("carousel", "wrap", {"items": lis, "label": label or "Carousel"}, n)
