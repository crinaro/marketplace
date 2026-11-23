"""The tick-box model's gaps (design-dashboard-redesign §6.1; dashboard-redesign E).

    check_picks(page, ledger, expected) -> (gaps, line)

TICK BOX IS A ROW. A tick box (`<input class="pick">`) carries `data-pick` and `data-line`, NEVER `data-rec` or
`data-ref`: the gate's row patterns (`_REC_RE`, `_REF_RE`) match any element, so a box carrying `data-rec` would count
as a second primary row of its record (and one carrying `data-ref` as a reference). A box with no `data-pick`, or no
`data-line`, is the same gap: the button could not put its record in the prompt.

BUTTON WITHOUT A HEAD. Every `<button>` on the page is a group's ONE button (`class="pick-go"`), and Python writes
every character of its prompt: `data-head` is `dashboard_actions.head(action)`. A button with no `data-head` (or an
empty one) either copies a prompt with no action line or is some other button the page is not allowed (§6.5).

BUTTON LABEL HIDES THE COPY (jobsearch 0.92.0, design-decision-surface D.1). A click on a `button.pick-go` records
nothing: it copies text to paste into the session. So the button's text, and the two labels the script swaps in
(`data-none`, `data-some`), must start with `Copy`, and its `data-done` must say to paste. A label like "Yes for these
10" reads as if the click decided something.

Pure: no I/O; `ledger` and `expected` are accepted for the uniform signature and not read."""
from html.parser import HTMLParser

from coverage_checks.walk import walk


class _Labels(HTMLParser):
    """The text of every `<button class="pick-go">`, with its attributes: `[(attrs, text)]` (the walk keeps no text)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self._open = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "button" and "pick-go" in (a.get("class") or "").split():
            self._open = [a, ""]

    def handle_data(self, data):
        if self._open is not None:
            self._open[1] += data

    def handle_endtag(self, tag):
        if tag == "button" and self._open is not None:
            self.found.append((self._open[0], " ".join(self._open[1].split())))
            self._open = None


def check_picks(page, ledger=None, expected=None):
    """(gaps, line): TICK BOX IS A ROW and BUTTON WITHOUT A HEAD over `page` (the module docstring)."""
    w = walk(page)
    gaps = []
    for a in w.boxes:
        name = a.get("data-pick") or a.get("aria-label") or "?"
        for attr in ("data-rec", "data-ref"):
            if attr in a:
                gaps.append("TICK BOX IS A ROW -- the tick box for %r carries %s=%r; a box carries data-pick, never "
                            "data-rec or data-ref, or the record counts as a second row (design §6.1)"
                            % (name, attr, a[attr]))
        for attr in ("data-pick", "data-line"):
            if not a.get(attr):
                gaps.append("TICK BOX IS A ROW -- the tick box for %r has no %s, so no button can put its record in "
                            "a prompt (design §6.1)" % (name, attr))
    for a in w.buttons:
        if not a.get("data-head"):
            gaps.append("BUTTON WITHOUT A HEAD -- a <button> (%s) carries no data-head: every button on the page is a "
                        "group's one button, and its prompt's head is written by Python (design §6.1, §6.5)"
                        % (a.get("data-none") or a.get("class") or "no class"))
    labels = _Labels()
    labels.feed(page)
    labels.close()
    for a, text in labels.found:
        shown = {"text": text, "data-none": a.get("data-none") or "", "data-some": a.get("data-some") or ""}
        bad = [k for k, v in shown.items() if not v.startswith("Copy")]
        if "paste" not in (a.get("data-done") or "").lower():
            bad.append("data-done")
        if bad:
            gaps.append("BUTTON LABEL HIDES THE COPY -- the button %r reads wrong in %s: a click copies text and records "
                        "nothing, so its label must start with Copy and its data-done must say to paste (design "
                        "decision-surface D.1)" % (text or a.get("data-none") or "?", ", ".join(bad)))
    return gaps, "picks: %d tick box(es), %d button(s)" % (len(w.boxes), len(w.buttons))
