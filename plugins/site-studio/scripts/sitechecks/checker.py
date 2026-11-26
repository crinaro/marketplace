"""checker.py -- `Checker`, one check run over a built tree, and `check_tree`, its one-call form.

`Checker` inherits the thirteen families from the mixins (`structure`, `linking`, `domain`,
`contentchecks`, `budgets`, `pagemeta`, `privacy`), and holds the parsed pages, the reference
resolver and `run`, which calls the families in order and then fails any family that examined
nothing (a green run is never an empty one). `not_read_pdfs` is the seam review_record.py's
coverage packet reads. Since 0.6.0 it also holds the carried set (`carried`, `held_pages`:
`sitechecks/carriedpages.py`, design-adopt-parity-2 section 4.7.2), and `run` prints the `carried:`
note when the tree holds a carried page. Since 0.10.0 it also holds `pieces` (`_piece_pages`: the pages that are a piece's, read from
`content/<portfolio>/<slug>/index.md` in the repo it is given; design-publish-preflight section 4, dev 1068).
"""

import os
import posixpath
from configschema import frontmatter, model
from urllib.parse import unquote, urlsplit
from sitechecks import carriedpages
from sitechecks.budgets import BudgetChecks
from sitechecks.contentchecks import ContentChecks
from sitechecks.domain import DomainChecks
from sitechecks.linking import LinkChecks
from sitechecks.page import parse_page, search_out
from sitechecks.pagemeta import PageMetaChecks
from sitechecks.privacy import PrivacyChecks
from sitechecks.report import FAMILIES, Report
from sitechecks.structure import StructureChecks
from sitechecks.tree import Tree, site_base


class Checker(StructureChecks, LinkChecks, DomainChecks, ContentChecks, BudgetChecks, PageMetaChecks,
              PrivacyChecks):
    """One check run over a built tree: the thirteen families live in the mixins above; this class holds the
    parsed pages, the reference resolver and `run`."""

    def __init__(self, tree, cfg, repo=None):
        self.t = tree
        self.cfg = cfg
        self.repo = repo
        self.r = Report()
        self.base = site_base(cfg)
        self.pages = {}
        for rel in sorted(tree.files):
            if rel.lower().endswith((".html", ".htm")):
                self.pages[rel] = parse_page(rel, tree.text(rel))
        self.redirects = set(r for r, p in self.pages.items() if self._is_redirect(p))
        self.content_pages = [r for r in sorted(self.pages) if r not in self.redirects]
        # schema 6: the files `site.json` `carried` names, served as adopted. Each family module's dated note says what
        # it holds them to; `held_pages` are the content pages held to the plugin's own page form.
        self.carried = carriedpages.carried_in(cfg, tree.files)
        self.held_pages = [r for r in self.content_pages if r not in self.carried]
        # `site.json` `sitemap: "indexable"` (schema 10; design-publish-preflight section 7, dev 1068): the content pages the build leaves out of
        # the sitemap because a `robots` meta holds noindex or none (`page.search_out`, the build's own function). Empty without the key.
        self.left_out = set(r for r in self.content_pages if getattr(cfg, "sitemap", None) == "indexable"
                            and search_out(self.pages[r]) == "noindex")
        self.pieces = self._piece_pages()
        self.refs_by_page = {}
        self.referenced = set()
        self.flagged = set()      # files `structure` already refused: not reported again as orphans

    # -- helpers ----------------------------------------------------------------------------
    @staticmethod
    def _is_redirect(p):
        return any(m.get("http-equiv", "").lower() == "refresh" for m in p.metas)

    def _piece_pages(self):
        """{page: the piece's own title} for the pages that are a PIECE's (design-publish-preflight section 4, T1; dev 1068): the page is
        `<portfolio>/<slug>/index.html`, `content/<portfolio>/<slug>/index.md` exists in the repo the gate is given with a front matter
        `title`, and the page's `<title>` begins with that title (the parsed `<title>` is already unescaped, so the compare is of the
        text the build escaped). A title is the person's words, so two pieces may share one and a piece may be called "Untitled"
        (`contentchecks.unfinished`, `pagemeta.head`). Read from the SOURCE, never from the page's markup, because the gate cannot
        tell a generated page from a hand-written one: with no repo, on a `hub` or `custom` site (whose `site/src` is built as written,
        so no `content/` page is generated), or for a page whose source says nothing, NOTHING is exempt (a missing fact reads as a
        refusal, never as a pass)."""
        if not self.repo or getattr(self.cfg, "siteKind", "portfolio") != "portfolio":
            return {}
        out = {}
        for rel in self.held_pages:
            parts = rel.split("/")
            if len(parts) != 3 or parts[2] != "index.html":
                continue
            try:
                with open(os.path.join(self.repo, "content", parts[0], parts[1], "index.md"), "r", encoding="utf-8",
                          errors="replace") as fh:
                    pairs = frontmatter.front_matter_pairs(fh.read())
            except OSError:
                continue
            title = dict((k, v) for k, v, _n in pairs).get("title")
            if title and title.strip() and self.pages[rel].title.strip().startswith(title.strip()):
                out[rel] = title.strip()
        return out

    def site_path(self):
        if not self.base:
            return ""
        return urlsplit(self.base).path.rstrip("/")

    def resolve(self, from_rel, url):
        """(target_rel or None, fragment, problem). `url` is relative or site-internal."""
        sp = urlsplit(url)
        path = unquote(sp.path)
        frag = unquote(sp.fragment)
        if path == "":
            return (from_rel, frag, None)
        if url.startswith("/"):
            # only ever a site-internal absolute URL whose origin and base path were already removed
            joined = path.lstrip("/")
            cand = posixpath.normpath(joined) if joined else "."
            trailing = path.endswith("/") or joined == ""
        else:
            cand = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), path))
            trailing = path.endswith("/")
        if cand.startswith(".."):
            return (None, frag, "the link climbs out of the site root")
        if cand == ".":
            cand = ""
        if trailing or cand == "":
            idx = (cand + "/index.html").lstrip("/")
            if idx in self.t.files:
                return (idx, frag, None)
            miss = "no such page"
        else:
            if cand in self.t.files:
                return (cand, frag, None)
            if (cand + "/index.html") in self.t.files:
                return (cand + "/index.html", frag, None)
            idx = cand
            miss = "no such file"
        lower = dict((k.lower(), k) for k in self.t.files)
        if idx.lower() in lower:
            return (None, frag, "case differs from the file (%s); Pages is case-sensitive" % lower[idx.lower()])
        return (None, frag, miss)

    def collect_refs(self):
        """Every reference in every page and stylesheet: (from_rel, kind, url). The readers are
        `carriedpages.page_refs` and `css_refs`, which the build's reading of a carried page shares."""
        refs = []
        for rel, p in self.pages.items():
            refs.extend(carriedpages.page_refs(rel, p))
        for rel in sorted(self.t.files):
            if rel.lower().endswith(".css"):
                refs.extend(carriedpages.css_refs(rel, self.t.text(rel)))
        return refs

    # -- run ---------------------------------------------------------------------------------
    def run(self):
        self.structure()
        self.links()      # fills all_refs and the referenced set before reachable/basepath
        self.comments()
        self.reachable()
        self.domain()
        self.media()
        self.unfinished()
        self.performance()
        self.head()
        self.nav()
        self.basepath()
        self.size()
        self.privacy()
        carried_pages = sum(1 for rel in self.carried if carriedpages.is_page(rel))
        if carried_pages:           # the families that skip a carried page say so, never a quiet pass
            self.r.notes.append(carriedpages.carried_note(carried_pages))
        if self.pages:
            for fam in FAMILIES:
                if self.r.checked.get(fam, 0) == 0 and fam not in ("media",):
                    self.r.add("structure", ".", "the %s family examined nothing" % fam)
        seen = set()
        unique = []
        for f in sorted(self.r.findings, key=lambda f: f.sort_key()):
            key = (f.family, f.path, f.message)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        self.r.findings = unique
        self.r.not_read.sort(key=lambda f: f.path)
        return self.r


def check_tree(out_dir, cfg, repo=None):
    return Checker(Tree(out_dir), cfg, repo).run()


def not_read_pdfs(out_dir, repo):
    """The built PDFs the privacy family could NOT read (design 7.1), as sorted relative paths.
    The seam review_record.py's coverage packet reads (dev #835): every path listed here must be
    in the privacy agent's coverage, because no pattern looked inside it."""
    repo = os.path.abspath(repo)
    cfg = model.load(os.path.join(repo, "site", "site.json"))
    rep = check_tree(out_dir, cfg, repo)
    return sorted({f.path for f in rep.not_read})
