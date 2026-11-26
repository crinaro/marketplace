"""ready_content: the wait-for-content scripts of the two LinkedIn kinds that decide by CONTENT, not by a selector (jobsearch 0.94.0, dev 1064; docs/design-role-first.md 19.3 N11, N12).

Capability module of `page_ready.py`, which renders these into `READY_JS` beside its generic kinds and reads their answers in `verdict()`.

WHY. Measured twice in a scheduled session with the pane open in no window (TESTED, §19.2 and §19.3): a LinkedIn page drew NO frames, so the paint gate would have called
it `not-painting` and sent a complete page to the next rung, yet the page was complete. Frames were the wrong question. So for these two kinds content decides, and paint is only recorded:

  `posting-read-linkedin`   READY when an element whose whole text is "About the job" has, in its block, 400 or more characters, and two reads `GAP` apart agree.
                            The block is the heading's parent, and its parent or grandparent while what is above has the heading as its ONLY child (a pure wrapper: never further, never
                            `body`). It does NOT climb to find 400 characters: a heading with no description over a sidebar would pass. A shell (the page's chrome, a skeleton, a
                            heading with no description under it) never passes. Answers `{ready, chars}`: `chars` is the block's text length without the heading.
  `linkedin-results`        READY when the page holds 1 or more job cards, EVERY card has text, and two reads agree. Cards are found by `[componentkey^="job-card-component-ref-"]`
                            (the layout measured 2026-11-25: two elements per card, one id), then the older `[data-occludable-job-id]` and `[data-job-id]`, and, when none of
                            those is on the page, by their dismiss controls (`button[aria-label^="Dismiss"]`, the card being the nearest `li`). Cards are counted by id, so two
                            elements of one card are one card. Answers `{ready, chars, cards}`: `chars` is the cards' text length in all.

UNDETERMINED: whether the description's block is the heading's parent on every posting layout, and whether a layout change moves the heading or the card attributes. A page that does
not match is NOT-READY, never READY: the safe direction is that a read waits for the next rung rather than reading a shell.

Timers only, never `requestAnimationFrame` (a pane that does not paint never gives one). READ-ONLY: nothing is clicked, scrolled, typed, requested or navigated, and the only things
the script touches on the page are `document.readyState`, `document.querySelectorAll`, `document.body`, `getAttribute`, `closest`, `parentElement`, `children`, `textContent` and
`innerText`. The allowlist test of `page_ready` holds the constants to that list.

Pure. Python 3.9+, standard library only."""

ABOUT_HEADING = "about the job"
ABOUT_MIN = 400                     # characters in the heading's block (design 19.3, N11)
RESULTS_MIN = 20                    # characters of card text in all: each card must also have some (N11)
CARD_ID_SELECTOR = '[componentkey^="job-card-component-ref-"], [data-occludable-job-id], [data-job-id]'
DISMISS_SELECTOR = 'button[aria-label^="Dismiss"]'

# The page's own content check. `@@LOOK@@` is one of the two bodies below; `@@OK@@` the shape of an answer. Nothing else is a hole.
CONTENT_TEMPLATE = """(async () => {
  const MIN = @@MIN@@, GAP = @@GAP@@, POLLS = @@POLLS@@;
  const look = () => {
@@LOOK@@
  };
  let prev = '';
  for (let i = 0; i < POLLS; i++) {
    const r = look(), sig = r.n + ':' + r.k;
    if (document.readyState === 'complete' && r.n >= MIN && sig === prev) return {ready: true, chars: r.n@@K@@};
    prev = sig;
    await new Promise(res => setTimeout(res, GAP));
  }
  const r = look();
  return document.readyState === 'complete' && r.n >= MIN && r.n + ':' + r.k === prev
    ? {ready: true, chars: r.n@@K@@} : {ready: false, chars: r.n@@K@@, state: document.readyState};
})()"""

LOOK_POSTING = """    const HEAD = 'about the job';
    const len = e => (e.innerText || '').trim().length;
    let best = -1;
    for (const h of Array.from(document.querySelectorAll('*'))) {
      if (h.children.length !== 0 || (h.textContent || '').trim().toLowerCase() !== HEAD) continue;
      let b = h.parentElement;
      for (let i = 0; i < 2 && b && b !== document.body && b.children.length === 1; i++) b = b.parentElement;
      if (b && b !== document.body) best = Math.max(best, len(b) - len(h));
    }
    return {n: best, k: null};"""

LOOK_RESULTS = """    const len = e => (e.innerText || '').trim().length;
    const key = e => e.getAttribute('componentkey') || e.getAttribute('data-occludable-job-id') || e.getAttribute('data-job-id');
    const at = Object.create(null), texts = [];
    for (const e of Array.from(document.querySelectorAll(@@IDS@@))) {
      const id = key(e);
      if (!id) continue;
      if (at[id] === undefined) { at[id] = texts.length; texts.push(0); }
      texts[at[id]] = Math.max(texts[at[id]], len(e));
    }
    if (texts.length === 0) {
      const seen = [];
      for (const b of Array.from(document.querySelectorAll(@@DISMISS@@))) {
        const c = b.closest('li') || b.parentElement;
        if (c && !seen.includes(c)) { seen.push(c); texts.push(len(c)); }
      }
    }
    return {n: texts.length > 0 && texts.every(t => t > 0) ? texts.reduce((a, t) => a + t, 0) : -1, k: texts.length};"""

CHECKS = {
    "posting-about": {"look": LOOK_POSTING, "k": ""},
    "results-cards": {"look": LOOK_RESULTS, "k": ", cards: r.k"},
}


def _js_string(text):
    """`text` as a JS string literal in single quotes (the selectors hold double quotes)."""
    if "'" in text or "\\" in text or "\n" in text:
        raise ValueError("a selector with a quote, a backslash or a newline is not rendered: %r" % text)
    return "'" + text + "'"


def render_content(check, min_chars, gap_ms, polls):
    """The content check `check` rendered with its numbers. `ValueError` on an unknown check or a non-positive int: a typo is loud, never rendered."""
    if check not in CHECKS:
        raise ValueError("unknown content check %r; the checks are %s" % (check, ", ".join(sorted(CHECKS))))
    for name, val in (("MIN", min_chars), ("GAP", gap_ms), ("POLLS", polls)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 1:
            raise ValueError("%s must be a positive int, not %r" % (name, val))
    look = CHECKS[check]["look"].replace("@@IDS@@", _js_string(CARD_ID_SELECTOR)).replace("@@DISMISS@@", _js_string(DISMISS_SELECTOR))
    out = CONTENT_TEMPLATE.replace("@@LOOK@@", look).replace("@@K@@", CHECKS[check]["k"])
    for hole, text in (("@@MIN@@", str(min_chars)), ("@@GAP@@", str(gap_ms)), ("@@POLLS@@", str(polls))):
        out = out.replace(hole, text)
    return out
