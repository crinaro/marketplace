"""The model a content tree loads into: pages, pieces, portfolios, references and the whole `Content`."""

import posixpath


# ---------------------------------------------------------------- the model

class Page(object):
    def __init__(self, source, meta, body, first_line=1):
        self.source = source
        self.meta = meta
        self.body = body
        self.first_line = first_line      # the file line of the body's first line (a refusal names it)


class Piece(object):
    def __init__(self, portfolio, slug, source, meta, body, first_line=1):
        self.portfolio = portfolio
        self.slug = slug
        self.source = source
        self.folder = posixpath.dirname(source)
        self.meta = meta
        self.body = body
        self.first_line = first_line
        self.title = meta["title"]
        self.draft = meta.get("draft", False)
        self.date = meta.get("date")

    @property
    def key(self):
        return "%s/%s" % (self.portfolio, self.slug)

    @property
    def card_title(self):
        return self.meta.get("shortTitle") or self.title


class Portfolio(object):
    def __init__(self, slug, settings, title, intro, page_source, intro_line=1, page_keys=()):
        self.slug = slug
        self.settings = settings
        self.title = title
        self.intro = intro
        self.page_source = page_source
        self.intro_line = intro_line
        self.page_keys = frozenset(page_keys)     # the front matter keys its page.md sets (a refusal names the file)
        self.pieces = []


class Reference(object):
    def __init__(self, name, data, card_path):
        self.name = name
        self.data = data
        self.card_path = card_path


class Content(object):
    def __init__(self):
        self.portfolios = []      # sorted by slug
        self.home = None
        self.about = None
        self.resume = None        # Page or None
        self.resume_pdf = None    # (repo path, bytes) or None
        self.references = {}      # name -> Reference
        self.media = {}           # repo path -> output path, only for what is published
        self.notes = []

    def portfolio(self, slug):
        for p in self.portfolios:
            if p.slug == slug:
                return p
        return None

    def menu_portfolios(self):
        """The portfolios in menu order: those with a page.md `order` first, ascending, then the rest by folder
        name (a tie too). Without `order` anywhere this is the folder-name order the nav always had."""
        return sorted(self.portfolios, key=lambda p: ((0, p.settings["order"], p.slug)
                                                      if p.settings.get("order") is not None else (1, 0, p.slug)))

    def piece(self, key):
        p, _, s = key.partition("/")
        pf = self.portfolio(p)
        if pf is None:
            return None
        for pc in pf.pieces:
            if pc.slug == s:
                return pc
        return None
