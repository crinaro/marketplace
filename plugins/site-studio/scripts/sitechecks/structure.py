"""structure.py -- the `structure` and `comments` families of the site gate (design 4.3), and the unexpanded-token
rule. A mixin of `checker.Checker`.

  structure    required files (index.html, 404.html, .nojekyll, and robots.txt + sitemap.xml once a
               site URL is known); files that must never be published (markdown sources, site.json,
               layout.html, *.pdf.json, .site-studio, decisions, originals, OS junk, editor leftovers,
               symlinks); URL-unsafe file names; every page has a doctype, <html lang>, balanced
               structural tags, and exactly one <h1> (the 404 page and redirect stubs excepted); and,
               from 0.2.0 (dev #852, design-site-adoption section 6.3), no unexpanded site-studio token
               or section in ANY built .html file: a `{{` followed by optional spaces and `#`, `/` or a
               letter is refused with its file:line. The builder expands or refuses every token it
               knows, so this catches a builder defect that leaves a section marker behind, and text
               such as `{{ two words }}` that no token regex matched (write &#123;&#123; to show braces
               as text). `{{1}}` and `{{ }}` are not matched.
  comments     no HTML comment in a page, no CSS or SVG comment (the build strips the first two; this
               proves it). JavaScript comments are NOT in scope: the build does not strip them, and
               a private term inside one is caught by the privacy family anyway. A sourceMappingURL
               reference in JS or CSS is a finding (it names a local path).

  Dated note, 2026-11-20 (design-adopt-parity-2 section 4.7.2, owner decision 2 (i)): a CARRIED file (`site.json`
  `carried`, schema 6; `sitechecks/carriedpages.py`) is served byte for byte as the person's old site served it, so the
  build neither expands nor strips it. `structure`'s per-file rules (a required file, a forbidden name or folder, junk,
  a URL-unsafe name, a symlink) hold it like any file; its per-page rules (doctype, `lang`, malformed markup, one
  `<h1>`, an unexpanded token) and the whole `comments` family (bar a `sourceMappingURL`, which names a local path) are
  NOT applied to it: they hold the plugin's output to the plugin's form, and refusing the page now would change nothing
  for a visitor and block the person. `checker.run` prints the `carried:` note, so the skip is never a quiet pass. A
  tree without the key has no carried file and is judged as before.
"""

import posixpath
import re
from sitechecks.kinds import FORBIDDEN_DIRS, FORBIDDEN_NAMES, JUNK_NAMES, JUNK_SUFFIXES
from sitechecks.page import _CSS_COMMENT


# an unexpanded token or section marker in a built page (section 6.3): `{{`, optional spaces, then `#`, `/`
# or a letter
_UNEXPANDED = re.compile(r"\{\{\s*[#/]?[A-Za-z]")
UNEXPANDED_MESSAGE = ("an unexpanded site-studio token or section; to show braces as text, "
                      "write &#123;&#123;")


class StructureChecks(object):
    """The `structure` and `comments` families (a mixin of `Checker`: it reads `self.t`, `self.pages`, `self.r`)."""

    # -- structure --------------------------------------------------------------------------
    def structure(self):
        fam = "structure"
        t = self.t
        self.r.count(fam, len(t.files))
        if not self.pages:
            self.r.add(fam, ".", "the tree holds no HTML page: nothing was checked")
            return
        required = ["index.html", "404.html", ".nojekyll"]
        if self.base:
            required += ["robots.txt", "sitemap.xml"]
        else:
            self.r.notes.append("NOT CHECKED: robots.txt and sitemap.xml (no previewUrl or domain "
                                "gives a site URL)")
        for f in required:
            if f not in t.files:
                self.r.add(fam, f, "required file is missing")
        for rel in sorted(t.files):
            name = posixpath.basename(rel)
            parts = rel.split("/")
            for d in parts[:-1]:
                if d in FORBIDDEN_DIRS:
                    self.r.add(fam, rel, "a %s folder must never be published" % d)
                    self.flagged.add(rel)
                    break
            if name in FORBIDDEN_NAMES:
                self.r.add(fam, rel, "this file is a source or maintenance file and must never be published")
                self.flagged.add(rel)
            elif name in JUNK_NAMES or name.endswith(JUNK_SUFFIXES) or name.startswith("._"):
                self.r.add(fam, rel, "source, editor or OS leftover must never be published")
                self.flagged.add(rel)
            if re.search(r"[\s#?%\\<>\"|*:]", rel):
                self.r.add(fam, rel, "file name is not URL-safe (space or reserved character)")
        for s in t.symlinks:
            self.r.add(fam, s, "a symbolic link must never be published")
        for rel in self.held_pages:             # a carried page keeps its own form (the dated note)
            p = self.pages[rel]
            if not p.doctype:
                self.r.add(fam, rel, "no <!doctype>")
            if not p.html_lang:
                self.r.add(fam, rel, "<html> has no lang attribute")
            for e in p.errors:
                self.r.add(fam, rel, "malformed markup: " + e)
            if rel != "404.html" and p.h1 != 1:
                self.r.add(fam, rel, "expected exactly one <h1>, found %d" % p.h1)
        for rel in sorted(self.pages):          # every built page, redirect stubs and the 404 page too
            if rel in self.carried:             # never token-expanded by the build: its braces are the person's
                continue
            for lineno, line in enumerate(t.text(rel).split("\n"), 1):
                if _UNEXPANDED.search(line):
                    self.r.add(fam, "%s:%d" % (rel, lineno), UNEXPANDED_MESSAGE)

    # -- comments ---------------------------------------------------------------------------
    def comments(self):
        fam = "comments"
        n = 0
        for rel, p in self.pages.items():
            if rel in self.carried:             # never comment-stripped by the build (the dated note)
                continue
            n += 1
            for c in p.comments:
                self.r.add(fam, rel, "HTML comment left in the published page (%d characters)" % len(c))
            for st in p.style_text:
                if _CSS_COMMENT.search(st):
                    self.r.add(fam, rel, "CSS comment left in an inline <style>")
        for rel in sorted(self.t.files):
            low = rel.lower()
            if rel in self.carried:
                pass
            elif low.endswith(".css"):
                n += 1
                css = self.t.text(rel)
                if _CSS_COMMENT.search(css.replace("/*# sourceMappingURL", "/*#sourceMappingURL")):
                    self.r.add(fam, rel, "CSS comment left in the published stylesheet")
            elif low.endswith(".svg"):
                n += 1
                if "<!--" in self.t.text(rel):
                    self.r.add(fam, rel, "comment left in the SVG")
            if low.endswith((".js", ".mjs", ".css")):
                if re.search(r"sourceMappingURL=", self.t.text(rel)):
                    self.r.add(fam, rel, "sourceMappingURL names a local file")
        self.r.count(fam, n)
