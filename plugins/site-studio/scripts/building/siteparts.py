"""The files that are not generated pages: `site/src` pages, media and redirects."""

import posixpath
import re

import content as C

from building.constants import HTML_EXTS
from building.outcomes import BuildError
from building.references import size_copies
from building.tokens import _meta_description, _meta_title, nfc, rel_link, strip_css_comments, strip_html_comments


class _SiteParts(object):
    # ---- site/src
    def build_site_src(self):
        for path in sorted(self.files):
            if path.startswith("site/src/"):
                self.build_site_src_file(path)

    def build_site_src_file(self, path):
        rel = path[len("site/src/"):]
        raw = self.files[path]
        low = rel.lower()
        if low.endswith(HTML_EXTS):
            origin = C.decode_text(raw, path)
            text = strip_html_comments(origin)
            text = self.expand(text, nfc(rel), path, featured=True, origin=origin, home=True)
            title = _meta_title(text) or rel
            desc = _meta_description(text) or ""
            text = self.presence(text, nfc(rel), title, desc, None, "website")
            self.pages[nfc(rel)] = {"kind": "site", "source": path, "lastmod_src": path,
                                    "sitemap": posixpath.basename(rel) != "404.html"}
            self.add(rel, text.encode("utf-8"), path)
        elif low.endswith(".css"):
            self.add(rel, strip_css_comments(C.decode_text(raw, path)).encode("utf-8"), path)
        elif low.endswith(C.TEXT_EXTS):
            self.add(rel, C.decode_text(raw, path).encode("utf-8"), path)
        else:
            self.add(rel, raw, path)

    def build_media(self):
        for repo_path, out_path in sorted(self.media_out.items()):
            self.add(out_path, self.files[repo_path], repo_path)
        for name in sorted(self.used_refs):
            ref = self.model.references[name]
            if ref.card_path:
                self.add(self._card_out(ref), self.files[ref.card_path], ref.card_path)
                for repo_path, out_path in sorted(size_copies(ref, self.files).items()):
                    self.add(out_path, self.files[repo_path], repo_path)

    def build_redirects(self):
        for old in sorted(self.cfg.redirects):
            self.build_redirect(old)

    def build_redirect(self, old):
        targets = self.page_key_to_out()
        new = self.cfg.redirects[old]
        old_clean = old.strip("/")
        out = old_clean if old_clean.lower().endswith(HTML_EXTS) else old_clean + "/index.html"
        if nfc(out).casefold() in self.owner:
            raise BuildError("redirect '%s' would replace a real page (%s from %s)"
                             % (old, self.owner[nfc(out).casefold()][0],
                                self.owner[nfc(out).casefold()][1]), fix="remove the redirect, or rename the page it would replace")
        if re.match(r"^https?://", new):
            href, canonical = new, new
        else:
            to = targets.get(new.strip("/"))
            if to is None:
                raise BuildError("redirect '%s' points at '%s', which is not a built page" % (old, new), fix="point the redirect at a page that is built, or build that page")
            href, canonical = rel_link(out, to), self.abs_url(to)
        self.emit_redirect(out, href, canonical, "site.json redirects")

    def build_index_redirect(self, out, to):
        """A portfolio index served as a redirect page to its one piece (`menuLinks: "single-piece"`)."""
        self.emit_redirect(out, rel_link(out, to), self.abs_url(to), "content/ (menuLinks: single-piece)")
