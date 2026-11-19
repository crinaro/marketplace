"""The page's copy-as-prompt actions (dashboard-redesign A, moved from generate_dashboard.py): the tick boxes,
each group's one button, the shared fallback and the one script.

THE TICK-BOX MODEL (dashboard-redesign D3, design 6.1). Python writes every character of a prompt
(`dashboard_actions.head`, `record_line`, `tail`); this module only places those strings in attributes, and the
ONE script (`PICK_SCRIPT`) joins them. The HTML contract, which the section renderers wire:

  group      any element carrying `data-pick-group="<name>"` (`group_attr(name)` writes the attribute). A
             button and its tick boxes sit inside the same group element. Groups may nest: a box belongs to
             its NEAREST group ancestor, never to an outer one.
  tick box   `pick(pick_key, line, label, level=1, checked=False)`:
             `<input type="checkbox" class="pick" data-pick="<kind>:<id>" data-line="<record_line>"
             data-level="1|2" aria-label="<label>">`. The attribute is `data-pick`, NEVER `data-rec` or
             `data-ref`: the coverage gate's row patterns match any element, so a box carrying `data-rec` would
             count as a second primary row. `line` may hold several record lines joined by newlines (a Today
             group item stands for the rows of its group on the page).
  button     `group_button(label, head, tail, n_default)`: one `<button type="button" class="pick-go">` with
             `data-head`, `data-tail` (may be empty), `data-none` ("<label> for these N", shown while nothing
             is ticked), `data-some` ("<label> for the ticked ones") and `data-done` ("Copied").
  fallback   `SHARED_FALLBACK`, placed ONCE on the page: `<div class="pick-shared" hidden>` holding the hint and
             the one `<textarea>`.
  script     `PICK_SCRIPT`, placed once, under the marker the coverage gate allows. On a click of a
             `button.pick-go` it finds the button's nearest `[data-pick-group]` ancestor (the document when there
             is none), takes that group's own ticked `input.pick` boxes, or with none ticked its `data-level="1"`
             boxes, and joins `data-head`, each box's `data-line` (page order) and `data-tail` when not empty with
             "\\n" (exactly `dashboard_actions.compose`). It copies the text with `navigator.clipboard.writeText`;
             with no clipboard API (checked up front) or on a refusal it puts the text in the shared textarea,
             reveals it and selects it. On a box's change it swaps its group's button text between `data-none`
             and `data-some`. It knows no grammar and touches no network, storage or navigation. (The old
             per-row `button.cap-btn`, its text areas and `render_action_button` / `render_copy_as_prompt` are
             gone since the D2 merge.)
"""
import html

from dashboard.markup import esc


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ "COPY AS PROMPT" - OWNER REQUEST 2026-10-13 (design r3 "Owner request 2026-10-13: Copy as
# prompt"; the vendor pattern *Bring the result back to your session*). Since dashboard-redesign D2 the
# per-row button is gone: a group's ONE button copies the loader's head, the ticked rows' record lines and
# the tail (design 6.1).
#
# THE PAGE'S ONE SCRIPT is `PICK_SCRIPT` below since dashboard-redesign D2 (the per-row `COPY_SCRIPT` is gone); it
# keeps this marker, the one check_dashboard_coverage.py's SCRIPT gap allows.
# ─────────────────────────────────────────────────────────────────────────────
COPY_SCRIPT_MARKER = 'data-dashboard-script="copy-as-prompt"'


# ─────────────────────────────────────────────────────────────────────────────
# THE TICK-BOX MODEL (dashboard-redesign D3, design 6.1 and 12): the contract is in the module docstring.
# ─────────────────────────────────────────────────────────────────────────────
SHARED_HINT = "Copy the selected text, then paste it into your session."
# design 12's ship rule: shown under each button on a narrow screen ONLY when the clipboard probe (step V) finds
# a phone surface that gives neither a copy nor the selected text (`group_button(..., read_only=True)`).
READ_ONLY_NOTE = "On this screen the page is read-only: act from the session on your computer."

SHARED_FALLBACK = ('<div class="pick-shared" hidden><span class="cap-hint sub">Copy the selected text, then paste it '
                   'into your session.</span><textarea class="pick-text" readonly rows="8"></textarea></div>')


def _attr(value):
    """An attribute value: quotes escaped, and newlines as `&#10;` so no serializer can fold them."""
    return html.escape(value, quote=True).replace("\r", "").replace("\n", "&#10;")


def group_attr(name):
    """` data-pick-group="<name>"`, for the element that holds a group's button and its tick boxes."""
    return ' data-pick-group="%s"' % _attr(name)


def pick(pick_key, line, label, level=1, checked=False):
    """One row's tick box. `pick_key` is the action record id (`<kind>:<id>`, from the row's own
    `actions[...]["rec_id"]`, never the page key); `line` is `dashboard_actions.record_line(...)` (or several,
    joined by newlines); `label` names the row for a screen reader. `level` 1 is in the default set a button
    takes with nothing ticked; 2 is not."""
    if level not in (1, 2):
        raise ValueError("a tick box is level 1 or 2, not %r" % (level,))
    return ('<input type="checkbox" class="pick" data-pick="%s" data-line="%s" data-level="%d" aria-label="%s"%s>'
            % (_attr(pick_key), _attr(line), level, _attr(label), " checked" if checked else ""))


def group_button(label, head, tail, n_default, read_only=False):
    """A group's ONE button. `head` and `tail` are `dashboard_actions.head(action)` and `tail(more)`;
    `n_default` is the number of level-1 boxes the button takes with nothing ticked ("<label> for these N")."""
    none = "%s for these %d" % (label, n_default)
    note = '<span class="pick-ro sub">%s</span>' % esc(READ_ONLY_NOTE) if read_only else ""
    return ('<button type="button" class="pick-go" data-head="%s" data-tail="%s" data-none="%s" data-some="%s" '
            'data-done="Copied">%s</button>%s'
            % (_attr(head), _attr(tail), _attr(none), _attr("%s for the ticked ones" % label), esc(none), note))


PICK_SCRIPT = ("<script %s>\n" % COPY_SCRIPT_MARKER) + r"""(function () {
  var shared = document.querySelector('.pick-shared');
  function show(text) {
    if (!shared) { return; }
    var ta = shared.querySelector('textarea');
    ta.value = text; shared.hidden = false; ta.focus(); ta.select();
  }
  function copy(text, b, fallback) {
    function done() {
      var was = b.textContent; b.textContent = b.getAttribute('data-done') || was;
      setTimeout(function () { b.textContent = was; }, 1500);
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
        return;
      }
    } catch (err) { /* fall through to the manual copy */ }
    fallback();
  }
  function groupOf(el) {
    return (el.closest && el.closest('[data-pick-group]')) || document;
  }
  function boxes(g) {
    var all = g.querySelectorAll('input.pick'), out = [];
    for (var i = 0; i < all.length; i++) { if (groupOf(all[i]) === g) { out.push(all[i]); } }
    return out;
  }
  function sync(g) {
    var bs = boxes(g), any = false;
    for (var i = 0; i < bs.length; i++) { if (bs[i].checked) { any = true; } }
    var btns = g.querySelectorAll('button.pick-go');
    for (var j = 0; j < btns.length; j++) {
      if (groupOf(btns[j]) === g) {
        btns[j].textContent = btns[j].getAttribute(any ? 'data-some' : 'data-none');
      }
    }
  }
  var all = document.querySelectorAll('button.pick-go');
  for (var k = 0; k < all.length; k++) { sync(groupOf(all[k])); }
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t && t.classList && t.classList.contains('pick')) { sync(groupOf(t)); }
  });
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button.pick-go') : null;
    if (b) {
      var bs = boxes(groupOf(b)), use = [], i;
      for (i = 0; i < bs.length; i++) { if (bs[i].checked) { use.push(bs[i]); } }
      if (!use.length) {
        for (i = 0; i < bs.length; i++) { if (bs[i].getAttribute('data-level') === '1') { use.push(bs[i]); } }
      }
      if (!use.length) { return; }
      var parts = [b.getAttribute('data-head')];
      for (i = 0; i < use.length; i++) { parts.push(use[i].getAttribute('data-line')); }
      var tail = b.getAttribute('data-tail');
      if (tail) { parts.push(tail); }
      var text = parts.join('\n');
      copy(text, b, function () { show(text); });
    }
  });
})();
</script>"""
