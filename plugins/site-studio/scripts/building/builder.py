"""builder: `_Builder`, the class that combines the builder's parts (page base, Markdown environment, home page,
portfolios, site parts) and writes the plugin's own output files. The whole build is a method call on it."""

from contentmodel import frontmatter
import os
import re
from building.constants import CONTENT_MODEL, OUTPUT_TEMPLATES, PLUGIN_ASSETS
from building.homepage import _HomePage
from building.markdownenv import _MarkdownEnv
from building.outcomes import BuildError
from building.pagebase import _PageBase
from building.portfolios import _Portfolios
from building.siteparts import _SiteParts
from building import carried, grouping
from building.tokens import (
    ASSET_EXTS,
    TOKEN_SCOPES,
    TOKEN_SINCE,
    _TOKEN,
    _line_of,
    asset_version,
    nfc,
    rel_link,
    strip_css_comments,
)
from contentmodel.links import esc

# design-publish-preflight section 3.2 (dev 1068): the tag the look's own picture part writes under `images: {"sizes": "held"}`, and how the
# build finds it. Attributes are read with every quoted value taken out, so a word inside an `alt` is never the attribute.
_TAG = re.compile(r"<(?:img|link)\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_HELD_ATTR = re.compile(r"\sdata-ss-held(?![\w:.-])", re.I)
_REL = re.compile(r"""\brel\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_STYLE = re.compile(r"<style[\s>]", re.I)
_HEAD_END = re.compile(r"</head\s*>", re.I)
HELD_SHEET = "site-studio/held.css"


def held_mode(cfg):
    """True under `images: {"sizes": "held"}` (schema 10); an absent key, `as-written` and every older tree are False."""
    return (getattr(cfg, "images", None) or {}).get("sizes") == "held"


def held_images(text):
    """[start of each `<img>` tag of `text` that carries `data-ss-held`], in order."""
    return [m.start() for m in _TAG.finditer(text)
            if m.group(0)[:4].lower() == "<img" and _HELD_ATTR.search(_QUOTED.sub('""', m.group(0)))]


def _first_sheet(text, end):
    """Where the first stylesheet link or `<style>` begins in `text[:end]`, else None."""
    found = []
    for m in _TAG.finditer(text, 0, end):
        if m.group(0)[:5].lower() == "<link":
            rel = _REL.search(m.group(0))
            if rel and "stylesheet" in (rel.group(1) or rel.group(2) or rel.group(3) or "").lower().split():
                found.append(m.start())
                break
    style = _STYLE.search(text, 0, end)
    if style:
        found.append(style.start())
    return min(found) if found else None


def held_position(text):
    """Where `held.css` is linked into the page `text`: before the first stylesheet or `<style>` of its head, else before `</head>`; a page
    with no `</head>` takes the first stylesheet or `<style>` anywhere, else the place of its first held picture. It is first so that the
    layer it declares is the weakest of the page (design section 3.1: linked after the site's styles, 16 of 272 layouts change)."""
    head = _HEAD_END.search(text)
    sheet = _first_sheet(text, head.start() if head else len(text))
    if sheet is not None:
        return sheet
    return head.start() if head else held_images(text)[0]


class _Builder(_PageBase, _MarkdownEnv, _HomePage, _Portfolios, _SiteParts):
    def asset_html(self, from_out, kind):
        """The tag that links a plugin output file from `from_out`, the FIRST time a page uses a block that
        needs it; "" after that (design-site-fidelity section 7.7). A stylesheet is linked from the body (a
        link a body may hold), so the person's layout is never edited, and a page with no plugin block links
        nothing."""
        key = (from_out, kind)
        if key in self.assets_emitted:
            return ""
        self.assets_emitted.add(key)
        self.assets_used.add(kind)
        href = esc(rel_link(from_out, PLUGIN_ASSETS[kind]))
        if PLUGIN_ASSETS[kind].endswith(".css"):
            return '<link rel="stylesheet" href="%s">' % href
        return '<script src="%s" defer></script>' % href

    def build_plugin_assets(self):
        """Write each plugin output file some page linked, from the plugin's templates/output/. A missing
        template is a refusal, never a page that links a file the build did not write."""
        for kind in sorted(self.assets_used):
            rel = PLUGIN_ASSETS[kind]
            path = os.path.join(OUTPUT_TEMPLATES, *rel.split("/"))
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                raise BuildError("the site-studio install is missing templates/output/%s; reinstall the plugin"
                                 % rel, fix="reinstall the site-studio plugin, which ships that file")
            if rel.endswith(".css"):      # the build publishes no CSS comment (check_site's `comments` family proves it)
                data = strip_css_comments(frontmatter.decode_text(data, rel)).lstrip("\n").encode("utf-8")
            self.add(rel, data, "templates/output/" + rel)

    def expand(self, text, current_out, source, extra=None, escape=True, featured=False, origin=None, home=False):
        """`origin` is the file's own text, when the caller has changed `text` (comments stripped): an
        unknown token's line number is then read from the file as the person wrote it. `home` is true only for
        a site/src page, the one place `{{home:<part>}}` is read."""
        text = self.sections(text, source)
        keys = self.page_key_to_out()
        keys.setdefault("home", keys.get(""))
        root = rel_link(current_out, "index.html")
        fix = esc if escape else (lambda s: s)
        values = {"siteUrl": self.site_url, "siteTitle": fix(self.cfg.siteTitle),
                  "name": fix(self.cfg.name), "year": str(self.year), "root": root}

        def sub(m):
            name, arg = m.group(1), m.group(2)
            scope = TOKEN_SCOPES.get(name)
            if (scope is None or TOKEN_SINCE.get(name, 0) > self.cfg.schema
                    or (scope == "layout" and not (extra and name in extra))):
                at = (origin or "").find(m.group(0))
                raise BuildError("%s: unknown token {{%s}}" % (source, name),
                                 lineno=(origin.count("\n", 0, at) + 1) if origin and at >= 0 else None,
                                 fix="check the spelling of the token, or remove it (the tokens are listed in "
                                     "%s)" % CONTENT_MODEL)
            if name == "home":
                nth = text.count(m.group(0), 0, m.start())
                return self.home_part(arg, current_out, source, _line_of(origin, m.group(0), nth) if origin else None, home)
            if name == "link":
                if arg is None:
                    raise BuildError("%s: {{link}} needs a page, such as {{link:work/slug}}" % source, fix="write {{link:work}} or {{link:work/slug}}")
                to = keys.get(arg.strip("/"))
                if to is None:
                    raise BuildError("%s: {{link:%s}} names no built page (a draft never builds)"
                                     % (source, arg), fix="check the page name, or build that page (a draft never builds)")
                return rel_link(current_out, to)
            if name == "nav":
                return self.nav_html(current_out)
            if name == "navLinks":
                return self.nav_links_html(current_out)
            if name == "featured" and arg is None:
                if self.cfg.siteKind != "portfolio":
                    raise BuildError("%s: {{featured}} is only for a portfolio site; a %s site has no pieces"
                                     % (source, self.cfg.siteKind), fix="remove {{featured}} from this page, or set siteKind to portfolio")
                if not featured:
                    raise BuildError("%s: {{featured}} is for site/src pages and the layout; a Markdown "
                                     "body is escaped, so it would print as text" % source, fix="move {{featured}} to a site/src page or the layout")
                sel = self.selection()
                return grouping.featured_html(self, sel, current_out) if sel else ""
            if name == "assetVersion":      # schema 6 (TOKEN_SINCE): computed once, only where a page uses it
                return self.asset_version()
            if name in values:
                return values[name]
            if extra and name in extra:
                return extra[name]
            raise BuildError("%s: unknown token {{%s}}" % (source, name), fix="check the spelling of the token, or remove it (the tokens are listed in %s)" % CONTENT_MODEL)
        printed = _TOKEN.sub(sub, text)
        if featured and held_mode(self.cfg):       # a whole page (the layout, or a hand page): `featured` is true for exactly those
            printed = self.link_held(printed, text, current_out)
        return printed

    def link_held(self, printed, written, out_path):
        """Under `images.sizes: held` (section 3.2): the page `printed` links `site-studio/held.css` once, first among its stylesheets, when
        the BUILD printed an `<img data-ss-held>` into it, that is, when it holds more of them than `written` (the layout's or the hand
        page's own text) does. A page whose only such tags are the person's own is never touched, and neither is a block image (no look
        part of a block holds the attribute). The file is published with the page that links it (`asset_html` registers it)."""
        if len(held_images(printed)) <= len(held_images(written)):
            return printed
        tag = self.asset_html(out_path, "held")
        if not tag or HELD_SHEET in printed:
            return printed
        at = held_position(printed)
        lead = printed[printed.rfind("\n", 0, at) + 1:at]       # the indent of the line it goes in front of, kept for the line it pushes down
        return printed[:at] + tag + "\n" + (lead if not lead.strip() else "") + printed[at:]

    def asset_version(self):
        """`{{assetVersion}}` (schema 6, design-adopt-parity-2 section 3.2): `tokens.asset_version` of the bytes this build
        serves for every `site/src` stylesheet and script, by the transform `build_site_src_file` publishes them with (a
        stylesheet's comments stripped; a script decoded and written as UTF-8), so the value moves with the served bytes
        and never with a page. Computed once per build, the first time a page uses the token."""
        if getattr(self, "_asset_version", None) is None:
            served = {}
            for path in sorted(self.files):
                if path.startswith("site/src/") and path.lower().endswith(ASSET_EXTS):
                    text = frontmatter.decode_text(self.files[path], path)
                    served[path] = (strip_css_comments(text) if path.lower().endswith(".css") else text).encode("utf-8")
            self._asset_version = asset_version(served)
        return self._asset_version

    def presence(self, html_text, out_path, title, desc, image_out, og_type):
        """Inject canonical and og/twitter tags before </head>, only those not already present."""
        if "</head>" not in html_text:
            self.notes.append("%s: no </head>, so no canonical or og tags were added" % out_path)
            return html_text
        tags = []
        if not re.search(r"rel=[\"']canonical[\"']", html_text, re.I):
            tags.append('<link rel="canonical" href="%s">' % esc(self.abs_url(out_path)))
        metas = [("og:title", title), ("og:description", desc), ("og:url", self.abs_url(out_path)),
                 ("og:type", og_type), ("og:site_name", self.cfg.siteTitle)]
        if image_out:
            metas.append(("og:image", self.site_url + "/" + image_out))
        for prop, val in metas:
            if val and not re.search(r"property=[\"']%s[\"']" % re.escape(prop), html_text, re.I):
                tags.append('<meta property="%s" content="%s">' % (prop, esc(val)))
        if not re.search(r"name=[\"']twitter:card[\"']", html_text, re.I):
            tags.append('<meta name="twitter:card" content="%s">'
                        % ("summary_large_image" if image_out else "summary"))
        if not tags:
            return html_text
        return html_text.replace("</head>", "".join("  %s\n" % t for t in tags) + "</head>", 1)

    def look_sheets(self, html_text, out_path):
        """The look's stylesheets (`stylesheets` in the look file, paths under site/src/), each linked once before
        </head> on a generated page, except where the layout already links that address. The files are the
        person's own site/src files, which the build publishes as it publishes any of them."""
        if self.look is None or not self.look.stylesheets or "</head>" not in html_text:
            return html_text
        tags = []
        for rel in self.look.stylesheets:
            href = rel_link(out_path, rel[len("site/src/"):])
            if re.search(r"href=[\"']%s[\"']" % re.escape(esc(href)), html_text) or \
                    re.search(r"href=[\"']%s[\"']" % re.escape(href), html_text):
                continue
            tags.append('<link rel="stylesheet" href="%s">' % esc(href))
        if not tags:
            return html_text
        return html_text.replace("</head>", "".join("  %s\n" % t for t in tags) + "</head>", 1)

    def emit_redirect(self, out, href, canonical, source):
        text = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<title>Redirecting</title>\n<meta name="robots" content="noindex">\n'
                '<link rel="canonical" href="%s">\n<meta http-equiv="refresh" content="0; url=%s">\n'
                '</head>\n<body>\n<p>This page has moved: <a href="%s">continue</a>.</p>\n'
                '</body>\n</html>\n' % (esc(canonical), esc(href), esc(href)))
        self.pages[nfc(out)] = {"kind": "redirect", "source": source,
                                "lastmod_src": None, "sitemap": False}
        self.add(out, text.encode("utf-8"), source)

    # ---- sitemap, robots, markers
    def build_sitemap(self, lastmod):
        self.build_carried()        # schema 6: before the sitemap lists the pages; nothing without the `carried` key
        entries = []
        indexable = getattr(self.cfg, "sitemap", None) == "indexable"      # schema 10, dev 1068: a page that says it is out of search is not listed
        for out_path in sorted(self.pages):
            info = self.pages[out_path]
            if not info["sitemap"] or (indexable and carried.left_out(self.out[out_path])):
                continue
            loc = self.abs_url(out_path)
            lm = lastmod(info["lastmod_src"]) if info["lastmod_src"] else None
            entries.append((loc, lm))
        entries.sort()
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for loc, lm in entries:
            lines.append("  <url><loc>%s</loc>%s</url>" % (esc(loc), "<lastmod>%s</lastmod>" % lm if lm else ""))
        lines.append("</urlset>")
        self.add("sitemap.xml", ("\n".join(lines) + "\n").encode("utf-8"), "generated")
        self.add("robots.txt", ("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n"
                                % self.site_url).encode("utf-8"), "generated")
        self.add(".nojekyll", b"", "generated")
        if self.cfg.cutover:
            self.add("CNAME", (self.cfg.domain + "\n").encode("utf-8"), "site.json cutover")
