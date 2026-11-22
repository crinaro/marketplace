"""The builder's core: state, the look, registering pages, navigation, `{{#page}}` sections, the featured
selection and the page shell."""

import re

from contentmodel import frontmatter
import looks
from lookgrammar import stylesheets
from contentmodel.errors import ContentError
from contentmodel.links import esc
from lookgrammar.errors import LookError

from building import mediapaths, navparts
from building.constants import HTML_EXTS
from building.outcomes import BuildError
from building.references import size_copies
from building.tokens import _SECTION, _page_dir, nfc, rel_link, strip_html_comments


class _PageBase(object):
    def __init__(self, repo, files, cfg, model, site_url, year, repo_for_dates, drafts, grammar=None):
        self.repo = repo
        self.grammar = cfg.schema if grammar is None else grammar     # the schema whose Markdown reading applies
        self.files = files
        self.cfg = cfg
        self.model = model
        self.site_url = site_url
        self.year = year
        self.date_repo = repo_for_dates
        self.drafts = drafts
        self.out = {}            # output path -> bytes
        self.owner = {}          # collision key -> (output path, source)
        self.pages = {}          # output path -> dict(kind, source, title, desc, image, lastmod_src, sitemap)
        self.used_refs = set()
        self.notes = []
        # where each media file is published: the model's addresses, home and about media placed by `mediaPaths` (schema 6)
        self.media_out = dict((p, nfc(o)) for p, o in mediapaths.media_map(model.media, cfg).items())
        # the size copies of a schema-4 reference `image`, published with the reference only when a card uses it (never in media_out)
        self.ref_copies = {}
        for ref in model.references.values():
            self.ref_copies.update((p, nfc(o)) for p, o in size_copies(ref, files, cfg).items())
        self._selection = None
        self._home_split = {}            # output page -> (intro, parts) of content/home.md for `{{home:<part>}}`
        self.assets_emitted = set()      # (page, kind) already linked, so a page links each plugin file once
        self.assets_used = set()         # kinds ("css", "js", "schema-4") some page links: those files are written
        self.look = None                 # the site's own look (`site.json` `look`), read by `load_look`; None: the default

    # ---- the look: every construct's markup is filled by looks.render (template-fidelity 1.4, design R5.8)
    def load_look(self):
        """The parsed look `site.json` names, read from the tree as it reads `layout.html` (a pure function of
        the committed tree and the plugin version). Absent key: None, and the default look renders everything.
        A look that is missing or refused refuses the build, naming the file."""
        ref = self.cfg.look
        if ref is None:
            return None
        raw = self.files.get(ref)
        if raw is None:
            raise BuildError("site.json: look '%s' is not a file in the build input" % ref, path="site/site.json",
                             fix="commit %s, or remove the look key from site/site.json for the plugin's own look" % ref)
        try:
            look = looks.parse(frontmatter.decode_text(raw, ref), ref)
            for rel in look.stylesheets:        # a regular file at HEAD (symlinks never reach the build input)
                sheet = self.files.get(rel)
                if sheet is None:
                    raise LookError("%s: stylesheets names %s, which is not a file in the build input" % (ref, rel),
                                    fix="commit the file, or remove it from the look's stylesheets")
                stylesheets.scan_stylesheet(frontmatter.decode_text(sheet, rel), rel)
            self.look = look
        except LookError as e:
            raise BuildError(str(e), path=ref, fix=e.fix or "fix the look file named above")
        except ContentError as e:
            raise BuildError(str(e), path=ref, fix=getattr(e, "fix", None) or "fix the look file named above")
        return look

    def r(self, construct, part, values, source=None):
        """Fill one part of the look (the site's, else the default). A refusal names the file when it is known
        (a value the build cannot put in a slot is the person's content; a look that cannot hold it is theirs)."""
        try:
            return looks.render(construct, part, values, self.look)
        except LookError as e:
            at = "%s: " % source if source else ""
            raise BuildError("%s%s" % (at, e), path=source, fix=e.fix or "fix the value named above, or the "
                             "look's %s.%s markup" % (construct, part))

    def assets(self, from_out, construct):
        """The tags that link the plugin files the look says `construct` needs on the page at `from_out`, each
        the first time the page uses it (`looks.assets_for`; the default look carries 0.3.1's links)."""
        return "".join(self.asset_html(from_out, kind) for kind in looks.assets_for(construct, self.look))

    # ---- output registry
    def add(self, out_path, data, source):
        out_path = nfc(out_path)
        key = out_path.casefold()
        if key in self.owner:
            prev_out, prev_src = self.owner[key]
            raise BuildError("two sources write the same output file: %s (from %s) and %s (from %s)"
                             % (prev_out, prev_src, out_path, source), fix="rename or remove one of the two files so each output path has one source")
        self.owner[key] = (out_path, source)
        self.out[out_path] = data

    # ---- links and tokens
    def preregister(self):
        """Every page's output path, known before any page renders, so {{link:...}} and the nav
        can point at a page that is built later."""
        known = {"index.html"}
        for pf in self.model.portfolios:
            known.add("%s/index.html" % pf.slug)
            for piece in pf.pieces:
                known.add("%s/%s/index.html" % (piece.portfolio, piece.slug))
        if self.model.about is not None:
            known.add("about/index.html")
        if self.model.resume is not None:
            known.add("resume/index.html")
        for path in self.files:
            if path.startswith("site/src/") and path.lower().endswith(HTML_EXTS):
                known.add(nfc(path[len("site/src/"):]))
        self.known = known
        # what a `{{#page:X}}` may NAME: a page that could exist for this site, built or not (a draft,
        # a resume not yet committed), so a misspelt X is refused instead of rendering nothing forever
        exist = {"home"}
        for path in self.files:
            if path.startswith("site/src/") and path.lower().endswith(HTML_EXTS):
                exist.add(_page_dir(nfc(path[len("site/src/"):])))
        if self.cfg.siteKind == "portfolio":
            exist |= {"about", "resume", "work"}
            slugs = set(pf.slug for pf in self.model.portfolios)
            exist |= slugs
            for path in self.files:
                parts = path.split("/")
                if (len(parts) == 4 and parts[0] == "content" and parts[1] in slugs
                        and parts[3] == "index.md"):
                    exist.add("%s/%s" % (parts[1], parts[2]))
        self.could_exist = exist

    def page_key_to_out(self):
        return dict((_page_dir(o), o) for o in self.known)

    @staticmethod
    def single_piece(pf):
        """True when `menuLinks: "single-piece"` applies: the portfolio builds exactly one piece and its index is
        the generated one. The nav then links the piece, and the index URL is served as a redirect page to it, so
        the old address keeps working and the published site has no page that nothing links (dev #864 C2: the
        build accepted a page `check_site.py` refuses as unreachable). Under `view: "page"` the index is the
        person's own page, which the build never replaces, so the nav keeps linking it."""
        st = pf.settings
        return st["menuLinks"] == "single-piece" and len(pf.pieces) == 1 and st["view"] != "page"

    def single_piece_redirect(self, pf):
        """True when the index of a `single_piece` portfolio is served as a redirect page: always at schema 3, and at
        schema 4 unless the page says `onePieceIndex: "listing"`, which builds the index as the listing it is for any
        other portfolio (the menu still links the piece)."""
        return self.single_piece(pf) and pf.settings.get("onePieceIndex", "redirect") != "listing"

    def nav_entries(self, current_out):
        """[(href from `current_out`, label, state)] of the site nav, in order: Home (unless `nav.home` is false, schema
        4; the site title under `nav.home: "title"`, schema 6), the menu portfolios, About, Resume, then schema 6's
        `nav.extra`. The state is `navparts.state`'s: "current", "section", "brand", "brand-current" or ""."""
        home = navparts.home_label(self.cfg)
        items = [("", home)] if home is not None else []
        for pf in self.model.menu_portfolios():
            if self.single_piece(pf):       # schema 3: the one piece
                items.append(("%s/%s" % (pf.slug, pf.pieces[0].slug), pf.settings["label"]))
            else:
                items.append((pf.slug, pf.settings["label"]))
        if self.model.about is not None:
            items.append(("about", "About"))
        if self.model.resume is not None:
            items.append(("resume", "Resume"))
        brand = self.cfg.nav.get("home") == navparts.NAV_HOME_TITLE
        out = []
        for key, label in items:
            to = "index.html" if key == "" else key + "/index.html"
            out.append((rel_link(current_out, to), label, navparts.state(key, to, current_out, brand and key == "")))
        return out + navparts.extra_entries(self)

    def nav_html(self, current_out):
        """`{{nav}}`: the nav element with its list, each item through the look's `nav` parts (`navparts.part`)."""
        lis = [self.r("nav", navparts.part(self, "item", st), {"url": href, "label": label})
               for href, label, st in self.nav_entries(current_out)]
        return self.r("nav", "wrap", {"items": "".join(lis)})

    def nav_links_html(self, current_out):
        """`{{navLinks}}` (schema 4): the same items as `{{nav}}` as links only, with no nav element and no
        list, for a layout that already wraps its links (design template-fidelity N1)."""
        return "".join(self.r("nav", navparts.part(self, "link", st), {"url": href, "label": label})
                       for href, label, st in self.nav_entries(current_out))

    def sections(self, text, source):
        """Resolve `{{#page:X}}...{{/page}}` before any token is read: a block whose page is built stays
        (its markers gone), any other block is dropped whole, so a `{{link:X}}` inside an absent section
        is never looked up. Refuses an unclosed, a stray and a nested section, and an X that could not
        exist for this site (design section 6.1)."""
        keys = self.page_key_to_out()
        keys.setdefault("home", keys.get(""))
        out, pos, name = [], 0, None
        for m in _SECTION.finditer(text):
            if m.group(1) is not None:
                if name is not None:
                    raise BuildError("%s: {{#page:%s}} opens inside the section {{#page:%s}}; sections do "
                                     "not nest" % (source, m.group(1), name), fix="close the first section with {{/page}} before opening the next")
                name = m.group(1).strip("/")
                if name not in self.could_exist and name not in keys:
                    raise BuildError("%s: {{#page:%s}} names a page this site cannot have (a misspelt "
                                     "name would render nothing for ever)" % (source, name), fix="fix the page name in {{#page:...}}, or remove the section")
                out.append(text[pos:m.start()])
                pos = m.end()
            else:
                if name is None:
                    raise BuildError("%s: {{/page}} closes a section that was never opened" % source, fix="remove the stray {{/page}}, or add the opening {{#page:name}}")
                if name in keys:
                    out.append(text[pos:m.start()])
                name, pos = None, m.end()
        if name is not None:
            raise BuildError("%s: {{#page:%s}} is never closed with {{/page}}" % (source, name), fix="add {{/page}} after the section's content, or remove the opening {{#page:...}}")
        out.append(text[pos:])
        return "".join(out)

    def selection(self):
        """The featured pieces, once per build: `content/home.md`'s `featured:` list in its order
        (featuredFrom home, as 0.1.0), or the pieces flagged `featured: true` (featuredFrom flags), in
        portfolio then piece order, a draft never (section 6.2)."""
        if self._selection is None:
            if self.cfg.featuredFrom == "flags":
                self._selection = [pc for pf in self.model.portfolios for pc in pf.pieces
                                   if pc.meta.get("featured") is True and not pc.draft]
            else:
                meta = self.model.home.meta if self.model.home else {}
                pieces = []
                for key in meta.get("featured", []):
                    pc = self.model.piece(key)
                    if pc is None:
                        raise BuildError("content/home.md: featured '%s' is not a built piece (a draft "
                                         "never builds)" % key, fix="fix the name in featured:, or publish the draft piece")
                    pieces.append(pc)
                self._selection = pieces
        return self._selection

    def link(self, from_out, to_out):
        """A relative link from one output file to another (`rel_link`), for the views module."""
        return rel_link(from_out, to_out)

    # ---- page assembly
    def layout(self):
        raw = self.files.get("site/templates/layout.html")
        if raw is None:
            raise BuildError("site/templates/layout.html is missing (the page shell for generated pages)", fix="add site/templates/layout.html, which holds {{content}}")
        text = strip_html_comments(frontmatter.decode_text(raw, "site/templates/layout.html"))
        if "{{content}}" not in text and not re.search(r"\{\{\s*content\s*\}\}", text):
            raise BuildError("site/templates/layout.html must contain {{content}}", fix="put {{content}} in site/templates/layout.html where the page body goes")
        return text

    def abs_url(self, out_path):
        d = _page_dir(out_path)
        return self.site_url + "/" + d + ("/" if d and (out_path.endswith("index.html")) else "")

    def emit_page(self, out_path, kind, source, title, page_title, desc, content_html, image_out=None,
                  og_type="website", lastmod_src=None, sitemap=True):
        layout = self.layout()
        extra = {"title": esc(title), "pageTitle": esc(page_title), "description": esc(desc),
                 "content": content_html}
        text = self.expand(layout, out_path, "site/templates/layout.html", extra=extra, featured=True)
        text = self.presence(text, out_path, title, desc, image_out, og_type)
        text = self.look_sheets(text, out_path)
        self.pages[out_path] = {"kind": kind, "source": source, "lastmod_src": lastmod_src,
                                "sitemap": sitemap}
        self.add(out_path, text.encode("utf-8"), source)

    def full_title(self, page_title, home=False):
        """A page's `<title>`: the site title alone for the home, else the page's title, `titleSeparator` (schema 6;
        default " | "), the site title. The separator is HTML-escaped where the layout prints it, as the title is."""
        return self.cfg.siteTitle if home else "%s%s%s" % (page_title, self.cfg.titleSeparator, self.cfg.siteTitle)
