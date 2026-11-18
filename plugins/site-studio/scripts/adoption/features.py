"""adoption.features -- the signals found in a tree and the site kind they infer.

Part of the `adoption` package behind the entry point `adopt.py`.
"""

import posixpath
import re
from collections import namedtuple

import build as site_build  # noqa: E402

from adoption.tokens import (
    detect_resume, home_feed, portfolio_folders, rewrite_tokens,
    site_json_labels, token_files,
)
from adoption.redirects import redirect_pages
from adoption.convert import label_conversions

Feature = namedtuple("Feature", "key signal sentence answer")
# ONE table: what the person's site does -> what that is called -> what the plugin does about it. A signal
# the inventory finds that has no row here prints the fallback line, so the table is what the inventory says.
FEATURES = (
    Feature("token:resumeLink", "{{resumeLink}}",
            "a resume link that disappears when there is no resume",
            "a page section, {{#page:resume}}...{{/page}}: adopt rewrites an anchor whose whole href is the "
            "token, and lists any other placement for you to wrap by hand"),
    Feature("featured-flag", "featured: true in a piece's front matter",
            "the home page shows pieces marked featured: true",
            "set \"featuredFrom\": \"flags\" in site/site.json (schema 2); adopt does not set it for you, "
            "because it changes which pieces the home page shows"),
    Feature("token:featured", "{{featured}}", "the featured pieces on a page",
            "covered: `{{featured}}` renders the featured selection (schema 2)"),
    Feature("token:home", "{{home:<part>}}", "a hand-made page that takes its copy from a home page",
            "covered: `{{home:<part>}}` feeds a hand-made site/src page from content/home.md (schema 3). adopt "
            "never rewrites the token: it stays as you wrote it, the build refuses a part the home page does not "
            "have (with the file and line), and `parity` measures what the plugin prints for it"),
    Feature("hand-home", "site/src/index.html with no content/home.md",
            "a hand-made home page",
            "kept as written: a site/src/index.html with no content/home.md is the home page (schema 2)"),
    Feature("meta-refresh", "a meta-refresh page under site/src",
            "an old address that forwards to a new one",
            "a site.json redirects entry: adopt converts the simple ones and lists the rest"),
    Feature("labels", "a [key, label] pair in work.meta, cardMeta or groups",
            "custom field names on piece pages",
            "the work.labels map (schema 2): adopt converts each pair and lists it"),
)
_TOKEN_NAME = {"resumeLink": "token:resumeLink"}
_FEATURED_FLAG = re.compile(r"^featured:\s*(?:true|yes)\s*(?:#.*)?$", re.I | re.M)


def detect_signals(tree, data, redirect_found=None):
    """[(key, where)] for every feature signal the person's tree carries (design 7.7). `key` is a FEATURES key,
    or `token:<the refused token>` for a local token the plugin's build would refuse; each appears once, with
    the first place it was seen."""
    seen, out = set(), []

    def add(key, where):
        if key not in seen:
            seen.add(key)
            out.append((key, where))
    folders = portfolio_folders(tree)
    for p in token_files(tree):
        text = tree.text(p)
        for m in site_build.TOKEN_RE.finditer(text):
            if m.group(1) in _TOKEN_NAME:
                add(_TOKEN_NAME[m.group(1)], p)
        for m in site_build.TOKEN_RE.finditer(text):
            if m.group(1) == "featured" and site_build.token_known("featured", p == "site/templates/layout.html"):
                add("token:featured", p)
            if m.group(1) == "home" and m.group(2) and site_build.token_known("home", p == "site/templates/layout.html"):
                add("token:home", p)
        for tok in rewrite_tokens(text, folders, layout=(p == "site/templates/layout.html"), home=home_feed(tree),
                                  labels=site_json_labels(data))[2]:
            add("token:" + re.sub(r"\s", "", tok), p)
    for p in tree.paths():
        if p.startswith("content/") and p.lower().endswith(".md") and not posixpath.basename(p).startswith("_"):
            m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", tree.text(p), re.S)
            if m and _FEATURED_FLAG.search(m.group(1)):
                add("featured-flag", p)
                break
    if tree.exists("site/src/index.html") and not tree.exists("content/home.md"):
        add("hand-home", "site/src/index.html")
    convert, left = redirect_found if redirect_found is not None else redirect_pages(tree, (data or {}).get("redirects"))
    if convert or left:
        add("meta-refresh", (convert[0].path if convert else left[0][0]))
    work = (data or {}).get("work")
    if isinstance(work, dict) and label_conversions(work)[1]:
        add("labels", "site/site.json")
    return out


def feature_lines(signals):
    """The inventory's feature list, one line per signal: the feature's sentence and the plugin's answer from
    FEATURES, or the fallback for a signal with no row."""
    table = dict((f.key, f) for f in FEATURES)
    out = []
    for key, where in signals:
        f = table.get(key)
        if f:
            out.append("  - %s (%s): %s" % (f.sentence, where, f.answer))
        elif key.startswith("token:"):
            out.append("  - a local token %s (%s): the plugin's build refuses it; replace it with text or with one of "
                       "the build's own tokens ({{siteTitle}}, {{name}}, {{year}}, {{link:<page>}}, {{nav}}, "
                       "{{featured}}), by hand" % (key[len("token:"):], where))
        else:
            out.append("  - a local signal %s (%s); site-studio has no equivalent" % (key, where))
    return out


def infer_kind(tree):
    """(kind, why): the site kind adopt PROPOSES for the person to confirm (design 7.7). `portfolio` when
    `content/` has portfolio folders, a resume source or a `home.md` (only the portfolio build reads it), else
    `hub` when the links on `site/src/index.html` are mostly outbound, else `custom`."""
    folders = portfolio_folders(tree)
    resume = detect_resume(tree)["md"]
    if folders or resume or tree.exists("content/home.md"):
        what = ("portfolio folder%s %s" % ("s" if len(folders) > 1 else "", ", ".join(folders)) if folders else
                "a resume source (%s)" % resume if resume else "content/home.md")
        return "portfolio", "content/ holds %s" % what
    idx = "site/src/index.html"
    if tree.exists(idx):
        hrefs = [h.strip() for h in re.findall(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']*)["']""", tree.text(idx), re.I)]
        hrefs = [h for h in hrefs if h and not h.startswith(("#", "mailto:", "tel:", "{{"))]
        out = [h for h in hrefs if re.match(r"^(?:https?:)?//", h)]
        if hrefs and len(out) * 2 > len(hrefs):
            return "hub", "%d of the %d links on %s go to other sites" % (len(out), len(hrefs), idx)
        return "custom", "%s has %s" % (idx, "%d of %d links to other sites" % (len(out), len(hrefs)) if hrefs
                                         else "no links to read")
    return "custom", "there is no content/ portfolio and no site/src/index.html to read"
