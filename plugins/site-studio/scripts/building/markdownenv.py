"""The builder's images, reference cards and the Markdown environment a body is rendered with."""

import itertools
import posixpath
import re

import content as C
from contentmodel import links
from contentmodel.errors import ContentError

from building import pictures
from building.constants import IMAGE_EXTS, SIZES_ATTR
from building.imagesize import image_size
from building.outcomes import BuildError
from building.references import card_out
from building.tokens import SIZE_COPY_SHAPES, rel_link


class _MarkdownEnv(object):
    # ---- images
    def _img_data(self, repo_path):
        data = self.files.get(repo_path)
        if data is None:
            raise BuildError("%s is not in the build input" % repo_path, fix="commit the file, or fix the path that names it")
        return data

    def img_tag(self, repo_path, alt, from_out, out_path=None, focus=None, construct="image"):
        """An <img> for a published file: width and height from the header, a srcset from the
        `<stem>-<w>w.<ext>` copies beside it, through the look's `image` construct (`block-image` for an image
        inside a plugin block). `focus` is a validated CSS position (a card's `coverPosition`): the look's
        `-pos` part prints it as the image's object-position."""
        out_path = out_path or self.media_out[repo_path]
        data = self._img_data(repo_path)
        values = {"src": rel_link(from_out, out_path), "alt": alt}
        part = "plain"
        if repo_path.lower().endswith(IMAGE_EXTS):
            size = image_size(data)
            if size is None:
                raise BuildError("%s: cannot read the image dimensions from its header; it is not "
                                 "a valid image" % repo_path, fix="replace the file with a valid PNG, JPEG, GIF or WebP image")
            values["width"], values["height"] = size
            part = "sized"
            stem, ext = posixpath.splitext(posixpath.basename(repo_path))
            copies = []
            rx = re.compile(r"^%s-(\d+)w%s$" % (re.escape(stem), re.escape(ext)))
            folder = posixpath.dirname(repo_path)
            shapes = [rx] if self.grammar < 3 else [rx] + [      # I-3: schema 3 reads these namings too (F4)
                re.compile(pat % (re.escape(stem), re.escape(ext))) for pat, _name in SIZE_COPY_SHAPES]
            for p in sorted(itertools.chain(self.media_out, self.ref_copies)):
                if posixpath.dirname(p) == folder and any(r.match(posixpath.basename(p)) for r in shapes):
                    s2 = image_size(self.files[p])
                    if s2 is not None:
                        copies.append((s2[0], rel_link(from_out, self.media_out.get(p) or self.ref_copies[p])))
            if copies:
                copies.append((size[0], rel_link(from_out, out_path)))
                seen, parts = set(), []
                for w, url in sorted(copies):
                    if w not in seen:
                        seen.add(w)
                        parts.append("%s %dw" % (url, w))
                values["srcset"], values["sizes"] = ", ".join(parts), SIZES_ATTR
                part = "sized-set"
        if focus and construct == "image":
            part += "-pos"
            values["focus"] = focus
        return self.r(construct, part, values)

    def ref_card(self, name, from_out):
        ref = self.model.references.get(name)
        if ref is None:
            raise BuildError("ref: %s names no reference under content/references/" % name, fix="capture the reference with /site-studio:capture, or fix its name")
        self.used_refs.add(name)
        d = ref.data
        img = ""
        if ref.card_path:       # design-movement-view section 5: `imageAlt` (else "") and `imagePosition`, schema-5 keys
            alt, position = pictures.reference_companions(ref)
            img = self.img_tag(ref.card_path, alt or "", from_out, out_path=self._card_out(ref), focus=position)
        site = self.r("reference-card", "site", {"text": d["site"]}) if d.get("site") else ""
        desc = self.r("reference-card", "description", {"text": d["description"]}) if d.get("description") else ""
        role = self.r("reference-card", "role", {"text": d["role"]}) if d.get("role") else ""
        card = self.r("reference-card", "wrap", {"url": d["url"], "image": img, "title": d["title"], "site": site,
                                                 "description": desc, "role": role})
        # a role line is a schema-4 part: the page that prints one links the schema-4 stylesheet the look names
        return (self.assets(from_out, "reference-card") if role else "") + card

    def _card_out(self, ref):
        return card_out(ref)

    # ---- markdown
    def markdown(self, body, source, from_out, base_dir, first_line=1, headings="shift", cards=False):
        """The body as HTML. `headings` and `cards` are the resume's schema-4 settings (`resume.headings`,
        `resume.layout`); every other page reads the defaults."""
        env = self.md_env(source, from_out, base_dir)
        text = self.expand(body, from_out, source, escape=False)
        try:
            return C.render_markdown(text, env, source, grammar=self.grammar, first_line=first_line,
                                     headings=headings, cards=cards)
        except ContentError as e:
            raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None), fix=getattr(e, "fix", None) or "fix the problem named above, then try again")

    def md_env(self, source, from_out, base_dir):
        """The environment a Markdown render reads images, references and plugin assets through."""
        builder = self

        class Env(object):
            look = builder.look           # the markup every plugin block is filled from (content.py asks for it)
            # `blocks.headingLevel` (schema 4): the h-level of a heading inside a block; None leaves it to the page
            block_heading_level = builder.cfg.blocks.get("headingLevel")
            # `blocks.loneReferenceGrid` (schema 4): a lone `ref:` line prints inside the reference grid, as two or more do
            lone_reference_grid = bool(builder.cfg.blocks.get("loneReferenceGrid"))
            # `blocks.videoEmbed` (schema 4): "live" keeps a video's own address (no `dnt=1`); absent is the click-to-load form
            video_embed_live = builder.cfg.blocks.get("videoEmbed") == "live"

            def asset(self, kind):
                return builder.asset_html(from_out, kind)

            def _img(self, src, alt, construct):
                if re.match(r"^https?://", src):
                    try:
                        return builder.r(construct, "plain", {"src": src, "alt": alt}, source)
                    except BuildError as e:
                        raise ContentError(str(e), path=source, fix=getattr(e, "fix", None) or "fix the address")
                seen = links.url_as_browser_reads(src)   # dev #912: decide as a browser reads it
                if seen.startswith("/") or links.url_scheme(src):
                    raise ContentError("%s: image '%s' must be a relative path or an https URL"
                                       % (source, src), fix="use a relative path to a file in media/, or an https URL")
                full = posixpath.normpath(posixpath.join(base_dir, src))
                if full not in builder.media_out:
                    raise ContentError("%s: image '%s' is not a file in a media/ folder" % (source, src), fix="put the image in a media/ folder and link it by its relative path")
                try:
                    return builder.img_tag(full, alt, from_out, construct=construct)
                except BuildError as e:
                    raise ContentError(str(e), path=source, fix=getattr(e, "fix", None) or "fix the image")

            def image(self, src, alt):
                return self._img(src, alt, "image")

            def block_image(self, src, alt):
                """An image inside a plugin block: the look's block-image construct (content.py asks for it)."""
                return self._img(src, alt, "block-image")

            def ref_card(self, name):
                try:
                    return builder.ref_card(name, from_out)
                except BuildError as e:
                    raise ContentError("%s: %s" % (source, e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None), fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
        return Env()
