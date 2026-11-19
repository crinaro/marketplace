"""The tick-box model's gaps (design-dashboard-redesign §6.1; dashboard-redesign E).

    check_picks(page, ledger, expected) -> (gaps, line)

TICK BOX IS A ROW. A tick box (`<input class="pick">`) carries `data-pick` and `data-line`, NEVER `data-rec` or
`data-ref`: the gate's row patterns (`_REC_RE`, `_REF_RE`) match any element, so a box carrying `data-rec` would count
as a second primary row of its record (and one carrying `data-ref` as a reference). A box with no `data-pick`, or no
`data-line`, is the same gap: the button could not put its record in the prompt.

BUTTON WITHOUT A HEAD. Every `<button>` on the page is a group's ONE button (`class="pick-go"`), and Python writes
every character of its prompt: `data-head` is `dashboard_actions.head(action)`. A button with no `data-head` (or an
empty one) either copies a prompt with no action line or is some other button the page is not allowed (§6.5).

Pure: no I/O; `ledger` and `expected` are accepted for the uniform signature and not read."""
from coverage_checks.walk import walk


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
    return gaps, "picks: %d tick box(es), %d button(s)" % (len(w.boxes), len(w.buttons))
