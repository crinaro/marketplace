"""The page's structure as the coverage checks read it (dashboard-redesign E): ONE pass of the standard library's HTML
parser, never a regex over nested markup (a fold inside a row inside a fold is ordinary on this page).

    walk(page) -> Walk
      rows     [Row]   every ROW: an element carrying `data-rec`, `data-ref` or `data-subject` (a row the reader sees
                       even when it is no record, such as an excluded company). `Row.attrs` its attributes,
                       `Row.fold` the page-order index of its NEAREST closed `<details>` (None when no closed fold holds
                       it), `Row.in_today` whether it sits inside the Today section.
      folds    {index: (tag attributes, summary text)}   every closed `<details>` (no `open` attribute), by index.
      today    None when the page has no `<section class="today">`; else `Today(attrs, items)`, `items` one
               `(attrs, [href])` per `<li class="today-item">`: the item's attributes and every link inside it.
      boxes    [attrs]  every tick box, `<input class="pick">`.
      buttons  [attrs]  every `<button>`.

A closed `<details>` hides its body, never its `<summary>`; a row is never inside a summary, so the nearest closed
fold is the fold that hides it. Unclosed tags are closed by their parent's end tag, as a browser would."""
import collections
from html.parser import HTMLParser

VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
                  "wbr"))
ROW_ATTRS = ("data-rec", "data-ref", "data-subject")

Row = collections.namedtuple("Row", "attrs fold in_today")
Today = collections.namedtuple("Today", "attrs items")
Walk = collections.namedtuple("Walk", "rows folds today boxes buttons")


class _Walker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                 # (tag, closed-fold index or None, today?, today item index or None, summary?)
        self.rows, self.folds, self.boxes, self.buttons = [], {}, [], []
        self.today, self.items = None, []

    def _top(self, i, default=None):
        for e in reversed(self.stack):
            if e[i] is not None:
                return e[i]
        return default

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        in_today = any(e[2] for e in self.stack)
        if any(k in a for k in ROW_ATTRS):
            self.rows.append(Row(a, self._top(1), in_today))
        if tag == "input" and "pick" in classes:
            self.boxes.append(a)
        if tag == "button":
            self.buttons.append(a)
        item = self._top(3)
        if tag == "a" and item is not None and "href" in a:
            self.items[item][1].append(a["href"])
        if tag in VOID:
            return
        fold = None
        if tag == "details" and "open" not in a:
            fold = len(self.folds)
            self.folds[fold] = (a, "")
        today = tag == "section" and "today" in classes
        if today and self.today is None:
            self.today = a
        it = None
        if tag == "li" and "today-item" in classes and in_today:
            it = len(self.items)
            self.items.append((a, []))
        summary = tag == "summary" and bool(self.stack) and self.stack[-1][0] == "details" \
            and self.stack[-1][1] is not None
        self.stack.append((tag, fold, today, it, self.stack[-1][1] if summary else None))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        k = self._top(4)
        if k is not None:
            attrs, text = self.folds[k]
            self.folds[k] = (attrs, (text + data))


def walk(page):
    """The page's `Walk` (the module docstring). Raises whatever the parser raises: the caller says NOT CHECKED."""
    w = _Walker()
    w.feed(page)
    w.close()
    today = Today(w.today, w.items) if w.today is not None else None
    return Walk(w.rows, {k: (a, " ".join(t.split())) for k, (a, t) in w.folds.items()}, today, w.boxes, w.buttons)
