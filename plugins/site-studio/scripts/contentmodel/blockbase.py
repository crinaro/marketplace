"""The block renderer's shared parts: its state, filling a look part, finding a fence's close, a part's name,
the rows of a block and the video embed."""

import looks
from looks import LookError
from siteconfig import V4_PART_FIXED

from contentmodel.errors import ContentError
from contentmodel.grammar import Fragment, PART_FIXED, _HEADING, _OPEN, _PART_NAME, _lead_kind, _starts_block, block_names, fixed_part_names
from contentmodel.links import video_embed


class _BlockBase(object):
    def __init__(self, env, where, grammar, plain, headings="shift"):
        self.env = env
        self.where = where
        self.grammar = grammar
        self.plain = plain
        self.headings = headings
        # `blocks.headingLevel` (schema 4): the env says it; None (absent) leaves a block's headings to the page's rule
        self.block_level = getattr(env, "block_heading_level", None)
        # `blocks.loneReferenceGrid` (schema 4): the env says it; False (absent) is a lone `ref:` line as a bare card
        self.lone_ref_grid = bool(getattr(env, "lone_reference_grid", False))
        # `blocks.videoEmbed` (schema 4): the env says it; False (absent) is the privacy form, Vimeo's address with `dnt=1`
        self.video_live = bool(getattr(env, "video_embed_live", False))
        self.in_block = False            # true while a block's own items are rendered (a carousel's slides)
        self.look = getattr(env, "look", None)
        self.asset = getattr(env, "asset", None) or (lambda kind: "")
        self.names = block_names(grammar)
        self.fixed_parts = fixed_part_names(grammar)

    def _at(self, n):
        return "%s:%d" % (self.where, n)

    def r(self, construct, part, values, n=None):
        """Fill one part of the look (the site's, else the default). A refusal names the file and line."""
        try:
            return looks.render(construct, part, values, self.look)
        except LookError as e:
            raise ContentError("%s: %s" % (self._at(n) if n else self.where, e), path=self.where, lineno=n,
                               fix=e.fix or "fix the value named above, or the look's %s.%s markup" % (construct, part))

    def assets(self, construct):
        """The plugin files the look links where a page holds `construct`, as the env's tags (first use only)."""
        return "".join(self.asset(kind) for kind in looks.assets_for(construct, self.look))

    def block_image(self, src, alt):
        """An image inside a plugin block. An env that renders the `block-image` construct itself says so with
        a `block_image` method; for any other the `image` tag it built is marked through the look."""
        own = getattr(self.env, "block_image", None)
        if own is not None:
            return own(src, alt)
        return looks.block_image_tag(self.env.image(src, alt), self.look)

    def starts(self, frag, i):
        return frag.nums[i] not in self.plain and _starts_block(frag.lines[i], self.grammar)

    def heading_level(self, hashes):
        """The h-level a Markdown heading prints at: one deeper than written (the page title owns h1), or as
        written when the page says so (`resume.headings: "as-written"`, schema 4). Inside a block that holds headings
        (a carousel's slides) the site's `blocks.headingLevel` wins when it is set: the level a `###` prints at,
        a deeper heading keeping its distance from it, never above h6 and never h1 (the page title owns that)."""
        if self.in_block and self.block_level is not None:
            return max(2, min(len(hashes) + self.block_level - 3, 6))
        return min(len(hashes) + 1, 6) if self.headings == "shift" else len(hashes)

    # ---- the resume's role cards (schema 4: `resume.layout: "cards"`)
    def card_blocks(self, frag):
        """The blocks of a resume body with every `###` heading made a card that runs to the next heading of
        level 3 or above (`#`, `##` or `###`); a `####` stays inside its card. A container block is never
        cut: a heading inside one is the block's own (the carousel's slide titles)."""
        lines, nums = frag.lines, frag.nums
        out, seg, i = [], 0, 0

        def flush(a, b):
            if b > a:
                out.extend(self.blocks(Fragment(lines[a:b], nums[a:b], self.plain)))

        def skip_container(j):
            """The index after the container block that opens at `j`, or j + 1 when line j opens none."""
            if nums[j] in self.plain or _lead_kind(lines[j]) != "container":
                return j + 1
            return self.find_close(frag, j, _OPEN.match(lines[j].rstrip()).group(1)) + 1

        while i < len(lines):
            m = _HEADING.match(lines[i]) if nums[i] not in self.plain and _lead_kind(lines[i]) is None else None
            if not (m and len(m.group(1)) == 3):
                i = skip_container(i)
                continue
            flush(seg, i)
            j = i + 1
            while j < len(lines):
                hm = _HEADING.match(lines[j]) if nums[j] not in self.plain and _lead_kind(lines[j]) is None else None
                if hm and len(hm.group(1)) <= 3:
                    break
                j = skip_container(j)
            out.append(self.card(m.group(2), Fragment(lines[i + 1:j], nums[i + 1:j], self.plain), nums[i]))
            seg = i = j
        flush(seg, len(lines))
        return out

    # ---- containers (grammar 3)
    def find_close(self, frag, i, name):
        """The index of the `:::` line that closes the container opened at `i`. A `part` may hold other blocks
        (never another part): ONE below grammar 4, any number from 4 (design R3 C, a schema-4 reason; 0.3.x
        refused a second one). Any other container holds none."""
        lines, nums = frag.lines, frag.nums
        open_at = nums[i]
        inner_open, inner_seen = False, 0
        for j in range(i + 1, len(lines)):
            if nums[j] in self.plain:
                continue
            kind = _lead_kind(lines[j])
            if kind == "close":
                if inner_open:
                    inner_open = False
                    continue
                return j
            if kind == "leaf":
                raise ContentError("%s: '%s' is a leaf directive and this Markdown has none"
                                   % (self._at(nums[j]), lines[j].strip()), path=self.where, lineno=nums[j],
                                   fix="show the line as text by putting a backslash in front of it, or "
                                       "write a container block (:::name ... :::)")
            if kind == "container":
                inner = _OPEN.match(lines[j].rstrip()).group(1)
                many = self.grammar >= 4
                if (name == "part" and inner in self.names and inner != "part" and not inner_open
                        and (many or not inner_seen)):
                    inner_open, inner_seen = True, inner_seen + 1
                    continue
                raise ContentError("%s: ':::%s' opens inside ':::%s' (line %d); blocks do not nest, except "
                                   "that a part may hold %s"
                                   % (self._at(nums[j]), inner, name, open_at,
                                      "other blocks, one after another" if many else "one other block"),
                                   path=self.where, lineno=nums[j],
                                   fix="close the first block with a ::: line before opening the next, or "
                                       "show the line as text with a backslash in front of it")
        raise ContentError("%s: ':::%s' is never closed" % (self._at(open_at), name), path=self.where,
                           lineno=open_at, fix="add a line holding only ::: after the block, or show the line "
                                               "as text with a backslash in front of it")

    def part_name(self, label, n):
        name = label.split()[0] if label.split() else ""
        if not name or not _PART_NAME.match(name):
            raise ContentError("%s: ':::part' needs a name: lower-case letters, digits and hyphens (got %r)"
                               % (self._at(n), label), path=self.where, lineno=n,
                               fix="write the block as :::part <name>, such as :::part stats")
        if name in self.fixed_parts:
            what = ("the home key '%s'" if name in V4_PART_FIXED and name not in PART_FIXED
                    else "the fixed home part '%s'") % name
            raise ContentError("%s: ':::part %s' collides with %s" % (self._at(n), name, what),
                               path=self.where, lineno=n,
                               fix="rename the part; the fixed names are %s" % ", ".join(self.fixed_parts))
        return name

    def fence(self, frag, i, kind, out):
        lines, nums = frag.lines, frag.nums
        n = nums[i]
        if kind == "leaf":
            raise ContentError("%s: '%s' is a leaf directive and this Markdown has none"
                               % (self._at(n), lines[i].strip()), path=self.where, lineno=n,
                               fix="show the line as text by putting a backslash in front of it, or write "
                                   "a container block (:::name ... :::)")
        if kind == "close":
            raise ContentError("%s: a ::: line closes a block that was never opened" % self._at(n),
                               path=self.where, lineno=n,
                               fix="remove the stray ::: line, or open the block above it with :::name")
        m = _OPEN.match(lines[i].rstrip())
        name, label = m.group(1), (m.group(2) or "").strip()
        if name not in self.names:
            raise ContentError("%s: unknown block ':::%s' (the blocks are %s)"
                               % (self._at(n), name, ", ".join(self.names)), path=self.where, lineno=n,
                               fix="use one of the block names listed, or show the line as text by putting a "
                                   "backslash in front of it")
        close = self.find_close(frag, i, name)
        inner = Fragment(lines[i + 1:close], nums[i + 1:close], self.plain)
        html = getattr(self, "block_" + name)(inner, label, n)
        if html:
            out.append(html)
        return close + 1

    def rows(self, inner, n, what):
        rows = [(inner.nums[k], l.strip()) for k, l in enumerate(inner.lines) if l.strip()]
        if not rows:
            raise ContentError("%s: the :::%s block is empty" % (self._at(n), what), path=self.where,
                               lineno=n, fix="add at least one row inside the block, or remove it")
        return rows

    def embed_for(self, url, ln):
        """The iframe address a video link names, or a refusal naming the line. Vimeo's carries `dnt=1`, unless the site
        says `blocks.videoEmbed: "live"`: then it is the player's own address, as `video_embed` builds it (https, one of
        the three hosts, nothing added), the form a site built elsewhere wrote. Both forms refuse the same links."""
        embed = video_embed(url)
        if embed is None:
            raise ContentError("%s: %r is not a YouTube, Vimeo or public Google Drive link"
                               % (self._at(ln), url), path=self.where, lineno=ln,
                               fix="use the video's https address from YouTube, Vimeo or a public Drive file")
        if embed.startswith("https://player.vimeo.com/") and not self.video_live:
            embed += ("&" if "?" in embed else "?") + "dnt=1"
        return embed

    def block_part(self, inner, label, n):
        self.part_name(label, n)
        return "\n".join(self.blocks(inner))
