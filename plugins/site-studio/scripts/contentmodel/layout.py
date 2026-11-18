"""What the folder layout of a tree must look like for a site kind, before anything is loaded."""

import re

from siteconfig import make_problem, schema_2_reasons

from contentmodel.errors import ContentError
from contentmodel.frontmatter import decode_text, parse_front_matter
from contentmodel.keytables import ABOUT_KEYS, HOME_KEYS, RESERVED_PORTFOLIO_NAMES


# What a `hub` or `custom` site does not build (design-site-adoption section 4.1), found by path.
_KIND_REFUSAL = ("only a portfolio site builds this; set siteKind to portfolio, or prefix the "
                 "folder with _ to keep it as source material")


def kind_layout_problems(files, kind):
    """Every path under `content/` that a `hub` or `custom` site refuses, each with its fix. Empty
    for a portfolio. A silently unbuilt portfolio would read as an empty one (CLAUDE.md, traps 1-4),
    so a stray `content/work/` is refused rather than ignored. Folders starting `_`, shared media
    and captured references stay allowed: nothing builds them on any kind."""
    if kind == "portfolio":
        return []
    out = []
    seen = set()
    for path in sorted(p for p in files if p.startswith("content/")):
        parts = path.split("/")
        if path in ("content/home.md", "content/about.md"):
            out.append("%s: %s" % (path, _KIND_REFUSAL.replace("prefix the folder with _",
                                                                "rename the file with a leading _")))
            continue
        if len(parts) >= 3 and not parts[1].startswith("_") and parts[1] not in ("media", "references"):
            folder = "content/%s/" % parts[1]
            if folder not in seen:
                seen.add(folder)
                what = "a resume source" if parts[1] == "resume" else "a portfolio folder"
                out.append("%s (%s): %s" % (folder, what, _KIND_REFUSAL))
    return out


def no_page_message(folder):
    return ("%s has no page.md: a folder under content/ is a portfolio only when it has one (put "
            "non-portfolio files outside content/, or start the folder name with _)" % folder)


def _home_featured_list(files):
    """True when content/home.md carries a `featured:` entry. An unreadable file is not reported
    here: the loader refuses it, naming the line."""
    where = "content/home.md" if "content/home.md" in files else "content/home/index.md"
    raw = files.get(where)
    if raw is None:
        return False
    try:
        meta, _body = parse_front_matter(decode_text(raw, where), where)
    except ContentError:
        return False
    return "featured" in meta


FOLDER_PAGES = (("home", HOME_KEYS), ("about", ABOUT_KEYS))


def folder_form_problems(files):
    """Schema 3's folder form of the home and about pages (design-site-fidelity section 5.1, F1):
    `content/home/index.md` and `content/about/index.md`, each with a `media/` folder, beside the
    `content/home.md` and `content/about.md` files. Every fault, each a `Problem`: both forms at once, a
    folder with no `index.md`, and any other file in the folder, which nothing would publish (a silently
    unpublished file is refused, never ignored). None is mechanical: adopt never moves a reserved folder."""
    out = []
    for name, _keys in FOLDER_PAGES:
        folder = "content/%s/" % name
        mine = sorted(p for p in files if p.startswith(folder))
        if not mine:
            continue
        index = folder + "index.md"
        if index not in files:
            out.append(make_problem("%s has no index.md: the folder form of the %s page needs one" % (folder, name),
                                    folder, "no index.md", "an index.md",
                                    "add content/%s/index.md (the page's copy and front matter)" % name))
        elif "content/%s.md" % name in files:
            out.append(make_problem("two %s pages: content/%s.md and content/%s/index.md; keep one"
                                    % (name, name, name), index, "two %s pages" % name, "one",
                                    "keep one: delete content/%s.md to use the folder, or the folder's "
                                    "index.md to use the file" % name))
        for p in mine:
            rel = p[len(folder):]
            if rel == "index.md" or rel.startswith("media/") or rel.startswith("_"):
                continue
            out.append(make_problem("%s: nothing publishes a file here; a file in content/%s/ must be index.md "
                                    "or be under media/" % (p, name), p, "a stray file", "index.md, or a file "
                                    "under media/", "move it into media/ or start its name with _"))
    return out


_HOME_TOKEN = re.compile(r"\{\{\s*home\s*:")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def hand_home_is_fed(files):
    """True when the hand-made home page (`site/src/index.html`) uses a `{{home:<part>}}` token outside an HTML
    comment, so `content/home.md` is not a second home page but the page's copy (site-fidelity section 6.1, C1).
    The pair is accepted only then; with no part token the 0.2.0 refusal of two home pages stands."""
    raw = files.get("site/src/index.html")
    if raw is None:
        return False
    try:
        text = decode_text(raw, "site/src/index.html") if isinstance(raw, bytes) else raw
    except ContentError:
        return False
    return bool(_HOME_TOKEN.search(_HTML_COMMENT.sub("", text)))


def layout_problems(files, site_kind, cfg=None):
    """Every problem in the content TREE, all at once, each a `siteconfig.Problem` (design-site-adoption
    sections 7.1, 4.1, 4.3, 6.2 and 3): a folder under content/ with no page.md, a hub or custom site
    holding portfolio content, two home pages, two featured sources, and (when `cfg` is given) a tree
    that needs schema 2 under a schema-1 config.

    `files` is {repo path: bytes} (this module reads no file; the design's `root` is this mapping, so
    adopt can pass a git tree and the build its commit). `cfg` is the parsed site.json, and may be None
    when only the layout is asked about. Empty means the tree has none of these faults."""
    out = []
    if site_kind != "portfolio":
        for text in kind_layout_problems(files, site_kind):
            path = text.split(":", 1)[0].split(" ", 1)[0]
            out.append(make_problem(text, path, "portfolio content", "none, on a %s site" % site_kind,
                                    "set siteKind to portfolio, or prefix the folder with _ to keep it as "
                                    "source material"))
    else:
        seen = set()
        for path in sorted(p for p in files if p.startswith("content/")):
            parts = path.split("/")
            if len(parts) < 3 or parts[1].startswith("_") or parts[1] in RESERVED_PORTFOLIO_NAMES:
                continue            # a reserved name is never a portfolio and is never offered the `_` rename (F1)
            name = parts[1]
            folder = "content/%s/" % name
            if folder in seen or name == "work" or folder + "page.md" in files:
                continue
            seen.add(folder)
            holds_md = any(p.startswith(folder) and p.lower().endswith(".md") for p in files)
            out.append(make_problem(
                no_page_message(folder), folder, "no page.md", "a page.md, or a folder name starting _",
                ("rename it to content/_%s (kept as source material, not built), or add a page.md so it "
                 "becomes a portfolio" % name) if not holds_md else
                ("decide: `adopt.py folder %s source` keeps it as source material (content/_%s, not built, "
                 "so the Markdown in it is not published), or add a page.md so it becomes a portfolio. A "
                 "folder holding Markdown is never moved without your say" % (name, name)), not holds_md))
        if cfg is not None and cfg.schema >= 3:
            out += folder_form_problems(files)
        if ("site/src/index.html" in files and ("content/home.md" in files or "content/home/index.md" in files)
                and not hand_home_is_fed(files)):
            out.append(make_problem(HOME_TWICE if "content/home.md" in files else
                                    HOME_TWICE.replace("content/home.md", "content/home/index.md"),
                                    "site/src/index.html", "two home pages",
                                    "one: site/src/index.html or content/home.md",
                                    "keep one: delete content/home.md to use the hand-made page, or "
                                    "delete site/src/index.html to use the generated home, or feed the "
                                    "hand-made page from content/home.md with {{home:intro}}"))
        if cfg is not None and cfg.featuredFrom == "flags" and _home_featured_list(files):
            out.append(make_problem(FEATURED_TWICE, "content/home.md", "a featured: list under flags",
                                    "no featured: list", "remove the featured: list from content/home.md, "
                                    "or drop featuredFrom"))
    if cfg is not None and cfg.schema < 2:
        for where, what, effect in schema_2_reasons(cfg, files):
            out.append(make_problem("%s %s, which needs \"schema\": 2 in site/site.json (%s)"
                                    % (where, what, effect), where, "schema 1", "schema 2",
                                    "set \"schema\": 2 in site/site.json (a save by site-studio does this)",
                                    True))
    return out


HOME_TWICE = "two home pages: site/src/index.html and content/home.md; keep one"

FEATURED_TWICE = ("featuredFrom is flags, so content/home.md's featured: list would be ignored; remove it, "
                  "or drop featuredFrom")
