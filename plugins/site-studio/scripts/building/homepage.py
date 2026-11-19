"""The home page, the about page and the resume page, and the parts they share."""

import posixpath
import re

import content as C
from contentmodel import grammar, links as links_mod, pagefiles
import views
from contentmodel.errors import ContentError
from contentmodel.links import esc

from building import homeorder
from building.outcomes import BuildError
from building.tokens import rel_link


class _HomePage(object):
    # ---- `{{home:<part>}}`: a hand-made home page fed by content/home.md (schema 3, design section 6.1)
    def home_split(self, out):
        """(intro Fragment, {part name: Fragment}) of content/home.md's body, its tokens expanded for the page at
        `out`. Cached per page: a part's links are relative to it."""
        cache = self._home_split
        if out not in cache:
            page = self.model.home
            text = self.expand(page.body, out, page.source, escape=False)
            try:
                cache[out] = C.parse_parts(text, page.source, page.first_line, max(self.grammar, 3))
            except ContentError as e:
                raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None),
                                 fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
        return cache[out]

    def home_part(self, part, out, source, lineno, allowed):
        """The HTML of one named part of the home page, for a `{{home:<part>}}` token in `source` (line `lineno`
        when the check knows it). Every part but `title` and `description` is rendered by the generated home's
        own code, so the fed page and the generated one print it the same way. A part the page does not hold is
        refused, naming the token's file:line and the part."""
        at = "%s:%d" % (source, lineno) if lineno else source
        if not allowed:
            raise BuildError("%s: {{home:...}} is read in site/src pages only; this is %s" % (at, source),
                             path=source, lineno=lineno,
                             fix="move the token to a page under site/src, or remove it")
        if part is None:
            raise BuildError("%s: {{home}} needs the part it names, such as {{home:intro}}" % at, path=source, lineno=lineno,
                             fix="write {{home:<part>}} with one of: %s" % ", ".join(grammar.PART_FIXED))
        page = self.model.home
        if self.cfg.siteKind != "portfolio" or page is None:
            raise BuildError("%s: {{home:%s}} is fed by content/home.md, and this site has none" % (at, part),
                             path=source, lineno=lineno,
                             fix="add content/home.md (a hub or custom site has none), or remove the token")
        meta = page.meta
        intro, parts = self.home_split(out)
        env = self.md_env(page.source, out, posixpath.dirname(page.source))

        def render(frag):
            try:
                return C.render_fragment(frag, env, page.source, max(self.grammar, 3))
            except ContentError as e:
                raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None),
                                 fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
        html = None
        if part in ("title", "description"):
            html = esc(meta[part]) if meta.get(part) else None
        elif part == "intro":
            html = render(intro) or None
        elif part in ("photo", "endorsement", "contact"):
            html = self.page_extras(page, out)[part] or None
        elif part == "feed":
            html = self.feed_html([self.ref_card(n, out) for n in meta.get("feed", [])]) or None
        elif part in ("eyebrow", "role") and self.grammar >= 4:       # the schema-4 home keys are parts of their own
            html = self.home_line(part, meta, out) or None
        elif part == "samples" and self.grammar >= 4:
            html = self.samples_html(meta.get("samples", []), out) or None
        elif part == "links" and self.grammar >= 4:
            html = self.links_html(meta.get("links", {}), out) or None
        elif part == "showcase" and self.grammar >= 4:
            html = self.showcase_html(meta, page.source, out) or None
        elif part in parts:
            html = render(parts[part]) or None
        else:
            raise BuildError("%s: {{home:%s}} names no part of %s (its parts are %s)"
                             % (at, part, page.source, ", ".join(list(grammar.PART_FIXED) + sorted(parts))),
                             path=source, lineno=lineno,
                             fix="write :::part %s ... ::: in %s, or use one of the parts listed" % (part, page.source))
        if html is None:
            raise BuildError("%s: {{home:%s}} is a part %s does not have, or holds nothing" % (at, part, page.source),
                             path=source, lineno=lineno,
                             fix="add what the part shows to %s (a '%s' key, the intro text, or the :::part block), "
                                 "or remove the token" % (page.source, part))
        return html

    # ---- the home page's own parts (schema 4): each through the look, each linking the schema-4 stylesheet
    def home_line(self, part, meta, out):
        """The home page's eyebrow or role line, or "" when the page has none."""
        if not meta.get(part):
            return ""
        return self.assets(out, "home") + self.r("home", part, {"text": meta[part]}, self.model.home.source)

    def samples_html(self, names, out):
        """samples: the named references as reference cards (each with its role line), in the look's grid."""
        cards = [self.ref_card(n, out) for n in names]
        if not cards:
            return ""
        return self.assets(out, "home-samples") + self.r("home-samples", "wrap", {"items": "".join(cards)})

    def links_html(self, links, out, source=None):
        """links: a map of label to https address, as a list of links in the look's home-links parts (the home
        page's links part, and the resume's header links)."""
        if not links:
            return ""
        items = "".join(self.r("home-links", "item", {"url": url, "label": label}, source)
                        for label, url in links.items())
        return self.assets(out, "home-links") + self.r("home-links", "wrap", {"items": items}, source)

    def feed_html(self, cards):
        """The feed section: reference cards in the look's grid, or "" when there are none."""
        if not cards:
            return ""
        return self.r("feed", "wrap", {"grid": self.r("reference-grid", "wrap", {"items": "".join(cards)})})

    def views(self):
        """The module that renders the schema-4 views (the views module, template-fidelity 1.5): index_html(builder,
        portfolio, out) for a portfolio index under view roles, map or showcase, and showcase_html(builder,
        entries, out) for the home page's showcase. It ships with this file (the shipped set follows the imports),
        so a missing views module is a broken install that fails at import, never a build that refuses."""
        return views

    def showcase_html(self, meta, source, out):
        """showcase: one tile per piece the home page names, in the look's home-showcase parts (the tile function
        is the views module). A piece that is not built is refused naming the home page."""
        if not meta.get("showcase"):
            return ""
        entries = []
        for entry in meta["showcase"]:
            key, image = pagefiles.parse_showcase_entry(entry)
            pc = self.model.piece(key)
            if pc is None:
                raise BuildError("%s: showcase '%s' is not a built piece (a draft never builds)" % (source, key),
                                 path=source, fix="fix the name in showcase:, or publish the draft piece")
            entries.append((pc, image))
        return self.views().showcase_html(self, entries, out)

    def contact_html(self, contact):
        rows = []
        for label, value in contact.items():
            if re.match(r"^[^@\s]+@[^@\s]+$", value):
                rows.append(self.r("contact", "item-mail", {"label": label, "href": "mailto:" + value,
                                                            "text": value}))
            elif re.match(r"^https?://", value):
                links_mod.check_href(value, "contact '%s'" % label)   # dev #912: the one href check
                rows.append(self.r("contact", "item-link", {"label": label, "url": value, "text": value}))
            else:
                rows.append(self.r("contact", "item-text", {"label": label, "text": value}))
        return self.r("contact", "wrap", {"items": "".join(rows)})

    def contact_block(self, contact):
        """A page's contact section: its heading, then the contact list."""
        return self.r("contact", "heading", {}) + self.contact_html(contact)

    def page_extras(self, page, out):
        """photo, endorsement, contact blocks shared by home and about."""
        parts = {"photo": "", "endorsement": "", "contact": ""}
        meta = page.meta
        if "photo" in meta:
            base = posixpath.dirname(page.source)       # `content` for home.md; the page's own folder for index.md
            full = posixpath.normpath(base + "/" + meta["photo"])
            if full not in self.media_out:
                raise BuildError("%s: photo '%s' is not a file in %s/media/" % (page.source, meta["photo"], base), fix="put the photo in %s/media/ and name it as media/<file>" % base)
            parts["photo"] = self.r("photo", "wrap", {"image": self.img_tag(full, meta["photoAlt"], out)}, page.source)
        if "endorsement" in meta:
            e = meta["endorsement"]
            by = self.r("endorsement", "by", {"who": e["by"]}, page.source) if e.get("by") else ""
            parts["endorsement"] = self.r("endorsement", "wrap", {"quote": e["quote"], "by": by}, page.source)
        if "contact" in meta:
            parts["contact"] = self.contact_block(meta["contact"])
        return parts

    def build_home(self):
        out = "index.html"
        page = self.model.home
        meta = page.meta if page else {}
        title = meta.get("title") or self.cfg.siteTitle
        pieces = self.selection()
        feed = []
        for name in meta.get("feed", []):
            feed.append(self.ref_card(name, out))
        extras = self.page_extras(page, out) if page else {"photo": "", "endorsement": "", "contact": ""}
        if page and homeorder.wanted(meta, self.grammar):      # schema 4 `partOrder` / `introScope` (homeorder.py)
            body = homeorder.arranged_body(self, page, out, extras, pieces, feed)
        else:
            intro = self.markdown(page.body, page.source, out, posixpath.dirname(page.source),
                                  page.first_line) if page else ""
            body = self.r("home", "intro", {"photo": extras["photo"], "intro": intro,
                                            "endorsement": extras["endorsement"]})
            if pieces:
                body += self.r("home", "featured", {"cards": self.cards_html(pieces, out)})
            if page and self.grammar >= 4:             # the schema-4 home keys; a part the page does not hold is ""
                body += self.showcase_html(meta, page.source, out)
            body += self.feed_html(feed)
            if page and self.grammar >= 4:
                body += self.samples_html(meta.get("samples", []), out)
                body += self.links_html(meta.get("links", {}), out, page.source)
            body += extras["contact"]
        desc = meta.get("description") or (grammar.plain_excerpt(page.body, grammar=self.grammar) if page else "") \
            or self.cfg.siteTitle
        image = (self.media_out.get(posixpath.normpath(posixpath.dirname(page.source) + "/" + meta["photo"]))
                 if (page and "photo" in meta) else None)
        eyebrow = self.home_line("eyebrow", meta, out) if (page and self.grammar >= 4) else ""
        role = self.home_line("role", meta, out) if (page and self.grammar >= 4) else ""
        self.emit_page(out, "home", page.source if page else "(generated)",
                       self.full_title(title, home=meta.get("titleForm") != "page"), title, desc,
                       self.r("home", "wrap", {"title": title, "body": body, "eyebrow": eyebrow, "role": role}),
                       image_out=image, lastmod_src=None)

    def build_about(self):
        page = self.model.about
        out = "about/index.html"
        meta = page.meta
        title = meta.get("title") or "About"
        extras = self.page_extras(page, out)
        intro = self.markdown(page.body, page.source, out, posixpath.dirname(page.source), page.first_line)
        desc = meta.get("description") or grammar.plain_excerpt(page.body, grammar=self.grammar) or \
            "About %s" % self.cfg.name
        image = (self.media_out.get(posixpath.normpath(posixpath.dirname(page.source) + "/" + meta["photo"]))
                 if "photo" in meta else None)
        self.emit_page(out, "about", page.source, self.full_title(title), title, desc,
                       self.r("about", "wrap", {"title": title, "photo": extras["photo"], "intro": intro,
                                                "endorsement": extras["endorsement"],
                                                "contact": extras["contact"]}),
                       image_out=image, lastmod_src=page.source)

    def build_resume(self):
        page = self.model.resume
        out = "resume/index.html"
        title = page.meta.get("title") or "Resume"
        rs = self.cfg.resume or {}
        body = self.markdown(page.body, page.source, out, posixpath.dirname(page.source), page.first_line,
                             headings=rs.get("headings", "shift"), cards=rs.get("layout", "plain") == "cards")
        link = ""
        if self.model.resume_pdf:
            pdf_path, pdf = self.model.resume_pdf
            pdf_out = "resume/" + posixpath.basename(pdf_path)
            self.add(pdf_out, pdf, pdf_path)
            link = self.r("resume", "download", {"url": rel_link(out, pdf_out)})
        desc = page.meta.get("description") or "Resume of %s" % self.cfg.name
        contact = self.contact_block(page.meta["contact"]) if "contact" in page.meta else ""
        if page.meta.get("tagline"):         # schema 4: the subtitle opens the body (the `tagline` construct)
            body = (self.assets(out, "tagline") + self.r("tagline", "wrap", {"text": page.meta["tagline"]},
                                                          page.source) + body)
        links = self.links_html(page.meta.get("links", {}), out, page.source)
        self.emit_page(out, "resume", page.source, self.full_title(title), title, desc,
                       self.r("resume", "wrap", {"title": title, "links": links, "download": link, "body": body,
                                                 "contact": contact}),
                       lastmod_src=page.source)
