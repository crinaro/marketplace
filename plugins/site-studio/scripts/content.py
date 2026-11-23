#!/usr/bin/env python3
"""content.py -- the content model and the Markdown subset (dev #835, design 2.4). Pure: it
reads no file and runs no command. `build.py` hands it a {repo path: bytes} map and gets back a
validated model; every refusal is a `ContentError` naming the file.

THE MODEL (every row of design 2.4 has a loader rule here and a case in tests/building and tests/contentmodel)
---------------------------------------------------------------------------------------
content/home.md, content/about.md   pages: front matter (title, description, featured, feed,
                                    endorsement, photo, photoAlt, contact) + an intro body
content/<portfolio>/page.md         one portfolio per folder; the FOLDER decides the page. The
                                    folder `work` is the default portfolio: its settings come from
                                    site.json `work`, overridden by its page.md. Folders starting
                                    `_` (`_template`) are skipped. Any other folder without a
                                    page.md is refused (it would be silently unpublished).
content/<portfolio>/<slug>/index.md a piece. Front matter: title (required), shortTitle, teaser,
                                    description, date, draft, group key, cover (`media/x.jpg` or
                                    `ref:<name>`), coverPosition, and any key `meta`/`cardMeta`
                                    lists. `draft: true` never builds (unless drafts=True).
content/<portfolio>/<slug>/media/*  the piece's published files (nothing else in a piece folder
                                    is published)
content/media/*                     shared published files (a home or about photo)
content/references/<name>/          reference.json + text.md + card.<ext>: a captured reference.
                                    `text.md` is raw material and is never published; only the
                                    card of a reference that is actually used is.
content/resume/resume.md (+ .pdf)   the resume page; the PDF and its `.pdf.json` sidecar are
                                    checked for staleness by a publish build

Size copies of an image sit beside it as `<stem>-<width>w.<ext>` (`images.py`, phase 1b, writes
them; the build only discovers them and builds a `srcset`).

MARKDOWN SUBSET: headings (a `#` is rendered as h2: the page title owns h1), paragraphs, one
level of `-`/`*` and `1.` lists, `>` quotes, `---`, `**bold**`, `*em*`, `` `code` ``, links,
images, a line holding only a YouTube, Vimeo or public-Drive URL (an embed), and `ref: <name>`
lines (consecutive lines make a grid). Raw HTML is escaped, never passed through. A link must be
http(s), mailto, an in-page `#anchor` or RELATIVE: a root-absolute href is refused because the
same output serves at `/<repo>/` and at `/`.

SCHEMA 3 ADDS SIX CONTAINER BLOCKS (site-fidelity, dev #865), each opt-in and recognised only at schema 3
(below it every such line is text, byte for byte as 0.2.0 renders it): `:::tiles`, `:::quote`, `:::gallery`,
`:::videos`, `:::carousel` and `:::part <name>`, each closed by a line holding only `:::`, with a titled
image line `![alt](path "title")`. A top-level line starting with a backslash and then one of those forms is
text. `LEAD_INS` is the one table of what changes meaning; `render_markdown(..., grammar=3)` reads it, and
so does `interpretation_reasons`, which `siteconfig` uses to decide a site needs schema 3.

SCHEMA 4 (template-fidelity 0.4.0, step 1.3; design-template-fidelity section 3.2). Every addition is a K reason:
a key, block or form 0.3.x refused, so no tree 0.3.x accepted changes. `:::quotes` (a grid of quotes, each ended
by its `-- ` line); a gallery row `![alt](path "caption") <video link>` (an item that opens or plays the video);
a `:::part` holding any number of blocks; the resume's role cards (`render_markdown(..., cards=True)`) and its
`headings` setting; the home keys `eyebrow`, `role`, `showcase`, `samples` and `links`, the resume keys `tagline`
and `links`, the `reference.json` keys `image`, `role`, `fetched` and `author` (`home_keys`, `resume_page_keys`,
`reference_keys`: the 0.3.x tuples are not extended); the five home keys as fixed part names (`fixed_part_names`);
and `VIEW_PIECE_KEYS`, the piece keys a setting reads, so `stray_warnings` does not call them unpublished.

EVERY MARKUP SITE GOES THROUGH `looks.render` (R5.8): the block renderer builds no HTML for a plugin construct
itself. `env.look` (absent: the plugin's default look) says which markup a construct renders, and
`looks.assets_for` which plugin files the page links. What this module still writes is the Markdown renderer's own
inline and block markup (a paragraph, a heading, a list, a `>` quote, a quote's `<cite>`): the value of an `html` slot.
"""
import hashlib
import html
import json
import posixpath
import re

import looks
from lookgrammar import named as looknamed
from lookgrammar.errors import LookError
from configschema.configkeys import WORK_KEYS, V3_PAGE_KEYS, V4_PAGE_KEYS
from configschema.diagnostics import SiteConfigError
from configschema.pagesettings import page_settings_problems
from configschema.workcheck import validate_portfolio_settings, labels_nonempty

from contentmodel.errors import ContentError
from contentmodel.keytables import SLUG_RE, RESERVED_PORTFOLIO_NAMES, CARD_EXTS, ABOUT_KEYS, PORTFOLIO_PAGE_KEYS, POSITION_RE, home_keys, reference_keys
from contentmodel.frontmatter import decode_text, parse_front_matter, _check_keys, _need_str
from contentmodel.models import Portfolio, Reference, Content
from contentmodel.pagefiles import _page, _validate_piece
from contentmodel.layout import no_page_message, FOLDER_PAGES
from contentmodel.loading import _unit, _key_line, _reference_image, _load_resume
from contentmodel.links import video_embed, esc, check_href
from contentmodel.grammar import _INLINE, _HEADING, _ULI, _OLI, _REFLINE, _IMGLINE, _HR, body_start_line, _IMGLINE3, _OPEN, _lead_kind, Fragment, _fragment, CARD_SEPARATOR
from contentmodel.blockbase import _BlockBase
from contentmodel.blockkinds import _BlockKinds

# The value of `video-embed.wrap`'s open slot `title` (design-adopt-parity-2 section 4.8): a bare video line's caption
# when it has one, else this word. Probe P-V (where a video's caption is written) was answered `default`, so 0.6.0 reads
# no caption and the value is the word the default look's own `title="Video"` literal has printed since 0.3.1.
VIDEO_TITLE = "Video"


def _load_portfolio_head(name, files, cfg, folder, page_path):
    """The folder checks, the page.md and the settings of one portfolio, as a `Portfolio` with no pieces."""
    if name in RESERVED_PORTFOLIO_NAMES:
        raise ContentError("%s: a portfolio folder name must be lower-case letters, digits "
                           "and hyphens (and not %s)" % (folder, ", ".join(RESERVED_PORTFOLIO_NAMES)),
                           path=folder, fix="%s is a reserved name: at schema 3 content/%s/index.md is the %s "
                           "page (run `build.py raise-schema`); any other folder needs another name"
                           % (name, name, name))
    if page_path not in files and name != "work":
        raise ContentError(no_page_message(folder), path=folder,
                           fix="add a page.md to the folder, or start its name with _ to keep it out of the build")
    if not SLUG_RE.match(name):
        raise ContentError("%s: a portfolio folder name must be lower-case letters, digits "
                           "and hyphens (and not %s)" % (folder, ", ".join(RESERVED_PORTFOLIO_NAMES)),
                           path=folder, fix="rename the folder to lower-case letters, digits and hyphens")
    base = dict(cfg.work) if name == "work" else {}
    if not labels_nonempty(base.get("labels")):
        base.pop("labels", None)     # the defaulted, empty map is not an entry in a schema-1 file
    title = None
    intro = ""
    meta = {}
    intro_line = 1
    page_text = ""
    v3 = {}
    if page_path in files:
        page_text = decode_text(files[page_path], page_path)
        meta, intro = parse_front_matter(page_text, page_path)
        intro_line = body_start_line(page_text)
        # The page keys this schema reads: schema 3's, and at schema 4 `mapMask`. Below 4 a `mapMask` is an unknown key (refused
        # by `_check_keys`), so a tree an earlier release accepted reads exactly as it did (design-template-fidelity 3.2).
        page_keys = V3_PAGE_KEYS + (V4_PAGE_KEYS if cfg.schema >= 4 else ())
        _check_keys(meta, PORTFOLIO_PAGE_KEYS + WORK_KEYS + (page_keys if cfg.schema >= 3 else ()), page_path)
        if "title" in meta:
            title = _need_str(meta, "title", page_path)
        overrides = dict((k, v) for k, v in meta.items() if k != "title" and k not in page_keys)
        v3 = dict((k, meta[k]) for k in page_keys if k in meta)
        try:
            if name == "work":
                merged = dict(base)
                merged.update(overrides)
                settings = validate_portfolio_settings(merged, "work", cfg.schema, cfg.featuredFrom)
            else:
                settings = validate_portfolio_settings(overrides, page_path, cfg.schema, cfg.featuredFrom)
        except SiteConfigError as e:
            raise ContentError("; ".join(p.message.replace("site.json: ", "%s: " % page_path, 1)
                                         for p in e.problems), path=page_path,
                               fix="fix the setting named above in this page.md front matter")
    else:
        settings = validate_portfolio_settings(base, "work", cfg.schema, cfg.featuredFrom)
        v3 = {}
    if name != "work" and "label" not in meta:
        settings["label"] = name.replace("-", " ").title()
    views = looknamed.tree_views(files, cfg.look, getattr(cfg, "lookLocal", None)) if cfg.schema >= 7 else None
    probs, page_settings = page_settings_problems(v3, page_path, cfg.schema, views)   # schema 3's keys (6.2), 4's views, mapMask; 7's named views
    if probs:
        raise ContentError("; ".join(p.message for p in probs), path=page_path, lineno=_key_line(page_text, v3, probs),
                           fix="fix the key named above: %s" % probs[0].fix)
    settings.update(page_settings)
    if settings["view"] == "page" and "site/src/%s/index.html" % name not in files:
        raise ContentError("%s: view is \"page\", so the portfolio's index is your own page, and "
                           "site/src/%s/index.html is not there" % (page_path, name), path=page_path,
                           lineno=_key_line(page_text, v3, None, "view"),
                           fix="add site/src/%s/index.html, or set view to \"grid\" (the generated index)" % name)
    return Portfolio(name, settings, title or settings["label"], intro,
                     page_path if page_path in files else None, intro_line, meta.keys())


def _load_piece(pf, name, slug, files, drafts, media_paths, featured_from):
    idx = "content/%s/%s/index.md" % (name, slug)
    if idx not in files:
        raise ContentError("content/%s/%s/ has no index.md: a piece folder needs one "
                           "(start the folder name with _ to keep it out of the build)"
                           % (name, slug), path="content/%s/%s/" % (name, slug),
                           fix="rename the piece file to index.md, or start the folder name with _ to "
                               "leave it out of the build")
    if not SLUG_RE.match(slug):
        raise ContentError("content/%s/%s: a piece folder name must be lower-case letters, "
                           "digits and hyphens" % (name, slug), path="content/%s/%s/" % (name, slug),
                           fix="rename the folder to lower-case letters, digits and hyphens")
    return _validate_piece(pf, slug, idx, files, drafts, media_paths, featured_from)


def _load_reference(name, files, paths, schema=3):
    rj = "content/references/%s/reference.json" % name
    if rj not in files:
        raise ContentError("content/references/%s/ has no reference.json" % name,
                           path="content/references/%s/" % name,
                           fix="add reference.json to the folder, or remove the folder")
    try:
        data = json.loads(decode_text(files[rj], rj))
    except ValueError as e:
        raise ContentError("%s is not valid JSON: %s" % (rj, e), path=rj,
                           fix="fix the JSON syntax in reference.json")
    if not isinstance(data, dict):
        raise ContentError("%s must be an object" % rj, path=rj, fix="make reference.json one JSON object")
    allowed = reference_keys(schema)
    for k in data:
        if k not in allowed:
            raise ContentError("%s: unknown key '%s'" % (rj, k), path=rj,
                               fix="remove the key (allowed: %s)" % ", ".join(allowed))
    for k in ("url", "title"):
        if not isinstance(data.get(k), str) or not data[k].strip():
            raise ContentError("%s: '%s' is required" % (rj, k), path=rj,
                               fix="add the key to reference.json as non-empty text")
    if not re.match(r"^https?://", data["url"]):
        raise ContentError("%s: 'url' must start with http:// or https://" % rj, path=rj,
                           fix="start the url with https://")
    check_href(data["url"], "%s: 'url'" % rj)   # dev #912: the one href check, as every link takes
    for k in allowed:
        if k in data and not isinstance(data[k], str):
            raise ContentError("%s: '%s' must be a string" % (rj, k), path=rj,
                               fix="write the value as text")
    if "role" in data and ("\n" in data["role"] or not data["role"].strip()):
        raise ContentError("%s: 'role' must be one line of text" % rj, path=rj,
                           fix="write role as one line, such as what you did on the project")
    # schema 5 (design-movement-view sections 3.2 and 5; `reference_keys` refuses both keys below it)
    if "imageAlt" in data and "\n" in data["imageAlt"]:
        raise ContentError("%s: 'imageAlt' must be one line of text" % rj, path=rj,
                           fix="write imageAlt as one line that says what the card's picture shows")
    if "imagePosition" in data and not POSITION_RE.match(data["imagePosition"]):
        raise ContentError("%s: 'imagePosition' must be a CSS position such as 'center 30%%'" % rj, path=rj,
                           fix="write a CSS position such as center 30%")
    cards =[p for p in paths if p.startswith("content/references/%s/card." % name)
             and p.lower().endswith(CARD_EXTS)]
    if len(cards) > 1:
        raise ContentError("content/references/%s/ has more than one card image" % name,
                           path="content/references/%s/" % name,
                           fix="keep one card image in the reference folder")
    if "image" in data:
        full = _reference_image(rj, name, data["image"], files)
        if cards:
            raise ContentError("%s: 'image' and the card file %s both name this reference's card" % (rj, cards[0]),
                               path=rj, fix="keep one: remove 'image' from reference.json, or remove %s"
                                            % cards[0])
        return Reference(name, data, full)
    return Reference(name, data, cards[0] if cards else None)


def load_content(files, cfg, drafts=False, check_resume_pdf=False, collect=None):
    """Build the validated model from {repo path: bytes} (only site/ and content/ paths are
    looked at). `drafts` includes `draft: true` pieces. `check_resume_pdf` is the publish-time
    stale-PDF refusal. `collect`: None raises the first `ContentError`, as the build always did; a list
    receives one `ContentError` per refused unit (a portfolio, a piece, a page, a reference, the resume)
    and the load carries on with the units that are fine, so `build.accept` reports every problem."""
    c = Content()
    paths = sorted(p for p in files if p.startswith("content/"))
    # the media each folder publishes, by repo path
    media_paths = set()
    top_dirs = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 3:
            top_dirs.setdefault(parts[1], []).append(p)
        if "media" in parts[1:-1] or (parts[1] == "media" and len(parts) > 2):
            media_paths.add(p)

    # ---- portfolios and pieces
    folder_form = cfg.schema >= 3      # schema 3 reads home and about as folders (F1); below it they are refused
    for name in sorted(top_dirs):
        if name.startswith("_") or name in ("media", "resume", "references"):
            continue
        if folder_form and name in ("home", "about"):
            continue
        folder = "content/" + name + "/"
        page_path = folder + "page.md"
        pf = _unit(collect, _load_portfolio_head, name, files, cfg, folder, page_path)
        if pf is None:
            continue
        slugs = {}
        for p in top_dirs[name]:
            parts = p.split("/")
            if len(parts) >= 4 and not parts[2].startswith("_"):
                slugs.setdefault(parts[2], []).append(p)
        for slug in sorted(slugs):
            piece = _unit(collect, _load_piece, pf, name, slug, files, drafts, media_paths, cfg.featuredFrom)
            if piece is None:
                continue
            pf.pieces.append(piece)
            for mp in slugs[slug]:
                if mp in media_paths and mp.startswith(piece.folder + "/media/"):
                    c.media[mp] = mp[len("content/"):]
        pf.pieces = sorted(sorted(pf.pieces, key=lambda x: x.slug), key=lambda x: x.date or "",
                           reverse=True)
        if pf.settings.get("sort") == "order":      # a piece with an `order` first, ascending; the rest stay by date
            pf.pieces = sorted(pf.pieces, key=lambda x: (0, x.meta["order"]) if "order" in x.meta else (1, 0))
        c.portfolios.append(pf)

    # ---- shared media
    for p in paths:
        if p.startswith("content/media/"):
            c.media[p] = p[len("content/"):]

    # ---- home, about
    if "content/home.md" in files:
        c.home = _unit(collect, _page, files, "content/home.md", home_keys(cfg.schema), "home", cfg.schema)
    elif folder_form and "content/home/index.md" in files:
        c.home = _unit(collect, _page, files, "content/home/index.md", home_keys(cfg.schema), "home", cfg.schema)
    if "content/about.md" in files:
        c.about = _unit(collect, _page, files, "content/about.md", ABOUT_KEYS, "about")
    elif folder_form and "content/about/index.md" in files:
        c.about = _unit(collect, _page, files, "content/about/index.md", ABOUT_KEYS, "about")
    if folder_form:           # a folder page's media/ is published beside it, as a piece's is
        for name, _keys in FOLDER_PAGES:
            if "content/%s/index.md" % name in files:
                for p in paths:
                    if p.startswith("content/%s/media/" % name):
                        c.media[p] = p[len("content/"):]

    # ---- references
    names = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 4 and parts[1] == "references" and not parts[2].startswith("_"):
            names.add(parts[2])
    for name in sorted(names):
        ref = _unit(collect, _load_reference, name, files, paths, cfg.schema)
        if ref is not None:
            c.references[name] = ref

    # ---- resume
    if cfg.resume is not None:
        _unit(collect, _load_resume, files, cfg, check_resume_pdf, c)
    return c


def render_inline(text, env, where):
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        pos = m.end()
        if m.group(1) is not None:
            out.append("<code>%s</code>" % esc(m.group(1)))
        elif m.group(3) is not None:
            out.append(env.image(m.group(3), m.group(2)))
        elif m.group(5) is not None:
            check_href(m.group(5), where)
            rel = ' rel="noopener"' if re.match(r"^https?://", m.group(5)) else ""
            out.append('<a href="%s"%s>%s</a>' % (esc(m.group(5)), rel,
                                                  render_inline(m.group(4), env, where)))
        elif m.group(6) is not None:
            out.append("<strong>%s</strong>" % render_inline(m.group(6), env, where))
        else:
            out.append("<em>%s</em>" % render_inline(m.group(7), env, where))
    out.append(esc(text[pos:]))
    return "".join(out)


class _Renderer(_BlockBase, _BlockKinds):
    """The block renderer. Below grammar 3 it is 0.2.0's loop, line for line (the owner invariant); at 3 and
    above a top-level fence line opens a container block, and at 4 `:::quotes`, the gallery video row and the
    resume's role cards are read too. `env` supplies `image`, `ref_card` and, for plugin blocks, `asset(kind)`:
    the `<link>` or `<script>` to emit before the page's first plugin block (or ""), and may supply `look`, the
    site's parsed look (absent: the plugin's default look).

    Every plugin-made construct is filled by `looks.render` (R5.8, step 1.3): this module holds no markup for
    one. What it keeps as literals is the Markdown renderer's own inline and block markup (a paragraph, a
    heading, a list, a quote's `<cite>`): it is the value of an `html` slot, produced here, never by a look."""

    def blocks(self, frag):
        lines, nums = frag.lines, frag.nums
        g3 = self.grammar >= 3
        env, where = self.env, self.where
        out, i = [], 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            plain = nums[i] in self.plain
            if g3 and not plain:
                kind = _lead_kind(line)
                if kind:
                    i = self.fence(frag, i, kind, out)
                    continue
            m = _HEADING.match(line)
            if m:
                level = self.heading_level(m.group(1))
                out.append("<h%d>%s</h%d>" % (level, render_inline(m.group(2), env, where), level))
                i += 1
                continue
            if _HR.match(line.strip()):
                out.append("<hr>")
                i += 1
                continue
            src = video_embed(line.strip())
            if src:
                out.append(self.r("video-embed", "wrap", self.video_values(src), nums[i]))
                i += 1
                continue
            m = _REFLINE.match(line)
            if m:
                cards = []
                while i < len(lines) and _REFLINE.match(lines[i]):
                    cards.append(env.ref_card(_REFLINE.match(lines[i]).group(1)))
                    i += 1
                out.append(cards[0] if len(cards) == 1 and not self.lone_ref_grid else
                           self.r("reference-grid", "wrap", {"items": "".join(cards)}, nums[i - 1]))
                continue
            m = (_IMGLINE3 if g3 and not plain else _IMGLINE).match(line)
            if m:
                title = m.group(3) if m.re is _IMGLINE3 else None
                cap = self.r("figure", "caption", {"text": title}, nums[i]) if title else ""
                out.append(self.r("figure", "wrap", {"image": env.image(m.group(2), m.group(1)), "caption": cap},
                                  nums[i]))
                i += 1
                continue
            if line.startswith(">"):
                quote = []
                while i < len(lines) and lines[i].startswith(">"):
                    quote.append(lines[i][1:].strip())
                    i += 1
                out.append("<blockquote><p>%s</p></blockquote>"
                           % render_inline(" ".join(quote), env, where))
                continue
            for rx, tag in ((_ULI, "ul"), (_OLI, "ol")):
                if rx.match(line):
                    items = []
                    while i < len(lines) and rx.match(lines[i]):
                        items.append("<li>%s</li>" % render_inline(rx.match(lines[i]).group(1), env, where))
                        i += 1
                    out.append("<%s>%s</%s>" % (tag, "".join(items), tag))
                    break
            else:
                para = [line.strip()]
                i += 1
                while i < len(lines) and lines[i].strip() and not self.starts(frag, i):
                    para.append(lines[i].strip())
                    i += 1
                out.append("<p>%s</p>" % render_inline(" ".join(para), env, where))
        return out

    def video_values(self, src):
        """The values of a bare video line's `video-embed.wrap`: the embed address, and the open slot `title` (0.6.0,
        `VIDEO_TITLE`) where the look in force places it. The bare line has no caption to read (probe P-V: `default`),
        so the title is a constant, the word the default look writes as a literal; it is given only where a look's
        part holds `{{title}}`, so a look derived from a page whose iframe says `title="Video"` keeps the literal and
        needs no newer release (a constant value has nothing for derive to read)."""
        values = {"embed": src}
        if "{{title}}" in looks.part_markup("video-embed", "wrap", self.look):
            own = getattr(self.env, "video_title", None)        # 0.7.0: the look's `reads` entry, read by the build's env
            values["title"] = (own() if own is not None else None) or VIDEO_TITLE
        return values

    def card(self, heading, body, n):
        """One role card: `Role · Organisation` heading text, or just a role when it holds no separator."""
        role, sep, org = heading.partition(CARD_SEPARATOR)
        html_body = "\n".join(self.blocks(body))
        prefix = self.assets("resume-role")
        if sep and role.strip() and org.strip():
            return prefix + self.r("resume-role", "wrap", {
                "role": render_inline(role.strip(), self.env, self.where),
                "org": render_inline(org.strip(), self.env, self.where), "body": html_body}, n)
        return prefix + self.r("resume-role", "wrap-bare", {
            "role": render_inline(heading, self.env, self.where), "body": html_body}, n)

    def quote_body(self, paras):
        return "".join("<p>%s</p>" % render_inline(" ".join(p), self.env, self.where) for p in paras)

    def quote_by(self, by):
        """The `who` of a quote: the attribution as inline Markdown, a trailing `*Title*` as a `<cite>`."""
        cm = re.search(r"\*([^*]+)\*\s*$", by)
        if cm:
            head = by[:cm.start()].rstrip()
            return ((render_inline(head, self.env, self.where) + " ") if head else "") + \
                "<cite>%s</cite>" % esc(cm.group(1))
        return render_inline(by, self.env, self.where)


def render_fragment(frag, env, where, grammar=3, headings="shift", cards=False):
    """Render a `Fragment` (a body, or a part of one) to HTML. `headings` and `cards` are the resume's schema-4
    settings (`resume.headings`, `resume.layout`); `cards` needs grammar 4."""
    if cards and grammar < 4:
        raise ValueError("role cards are read from grammar 4 (resume.layout is a schema-4 key); set the site to schema 4 "
                         "to use them")
    r = _Renderer(env, where, grammar, frag.plain, headings)
    return "\n".join(r.card_blocks(frag) if cards else r.blocks(frag))


def render_fragment_blocks(frag, env, where, grammar=4):
    """The blocks of a `Fragment` as a list of HTML, one entry per top-level block, in order: what `render_fragment`
    joins. The home page's `introScope: "first-block"` (schema 4) takes the first entry for its intro."""
    return _Renderer(env, where, grammar, frag.plain).blocks(frag)


def render_markdown(body, env, where, grammar=2, first_line=1, headings="shift", cards=False):
    """Render a Markdown-subset body to HTML. `env.image(src, alt)` and `env.ref_card(name)`
    return HTML (or raise ContentError). `grammar` is the schema whose reading of a line applies: 3 and
    above read the new block grammar (site-fidelity section 7); below it every line is 0.2.0 text, byte for
    byte (the owner invariant, `Upgrade020Unchanged`); 4 adds `:::quotes`, the gallery video row and a part
    holding any number of blocks. `first_line` is the file line number of the body's first
    line, so a refusal at schema 3 names the line the person wrote. `headings` ("shift", the default, or
    "as-written") and `cards` are the resume's schema-4 settings."""
    return render_fragment(_fragment(body, first_line, grammar), env, where, grammar, headings, cards)


class _LookOnly(object):
    """An environment that carries only the look: `parse_parts` reads the look's named block names through it."""

    def __init__(self, look):
        self.look = look


def parse_parts(body, where, first_line=1, grammar=3, look=None):
    """Split a schema-3 body into (intro, {part name: Fragment}) for `{{home:<part>}}` (section 6.1): each
    top-level `:::part <name>` block is taken out of the intro and kept by name; every other line, block
    included, stays in the intro. A duplicate name, an unclosed block and the other grammar refusals raise
    `ContentError` with the file and line. `intro` is a Fragment. `grammar` is the site's schema (at 4 a part
    may hold any number of blocks, and the home keys are fixed part names). `look` (0.7.0): the effective look, whose named
    blocks are blocks here too."""
    frag = _fragment(body, first_line, grammar)
    r = _Renderer(None if look is None else _LookOnly(look), where, grammar, frag.plain)
    keep_l, keep_n, parts, opened = [], [], {}, {}
    i = 0
    while i < len(frag.lines):
        kind = _lead_kind(frag.lines[i]) if frag.nums[i] not in frag.plain else None
        if kind == "container":
            m = _OPEN.match(frag.lines[i].rstrip())
            if m.group(1) in r.names:
                close = r.find_close(frag, i, m.group(1))
                if m.group(1) == "part":
                    name = r.part_name((m.group(2) or "").strip(), frag.nums[i])
                    if name in parts:
                        raise ContentError("%s: ':::part %s' appears twice (first at line %d)"
                                           % (r._at(frag.nums[i]), name, opened[name]), path=where,
                                           lineno=frag.nums[i], fix="give each part its own name")
                    parts[name] = Fragment(frag.lines[i + 1:close], frag.nums[i + 1:close], frag.plain)
                    opened[name] = frag.nums[i]
                else:
                    keep_l.extend(frag.lines[i:close + 1])
                    keep_n.extend(frag.nums[i:close + 1])
                i = close + 1
                continue
        keep_l.append(frag.lines[i])
        keep_n.append(frag.nums[i])
        i += 1
    return Fragment(keep_l, keep_n, frag.plain), parts
