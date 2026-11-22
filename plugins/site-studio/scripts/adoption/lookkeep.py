"""adoption.lookkeep -- look rule L: a derived look is kept per construct, never refused whole (design-adopt-parity-2 section 6, L1
to L4; step 11). It replaces `choose.drop_lossy_look` (D2, dev 941), which refused the whole derived look for one text the plugin's
page did not hold, whether or not any look could print it (dev #980, public #250: the look refused for one paragraph).

Part of the `adoption` package behind the entry point `adopt.py`; `adoption.choose` makes the one call (`keep`), once, after its
last pass, with every other setting at its chosen value:

  * L1, DIFFERENTIAL. The derived look's losses (`scoring.lost_facts`) are compared with the default look's under the same settings.
    The derived look answers only for a loss the default look does not have (`SUBTRACT_DEFAULT_LOSSES`, below).
  * L3, CONTENT GAPS. A loss both looks have is no look's: it is listed once, "the plugin's build does not print: <page>, <what>",
    and never refuses the look. The page reads DIFFERENT, so it is an ACCEPT candidate (`parity.open`, a `page` row) already.
  * L2, PER CONSTRUCT, BY BISECTION. For the derived look's own losses: one build with every derived construct dropped (a construct a
    look omits renders with the default look's markup), RECORDED (`lookfiles.renderlog.recording`), which says which constructs
    render on each losing page (a construct whose recorded markup is in that page); by L1 each loss must come back there, and if one
    does not, `look` is `you decide` as before. Then, page by page, the constructs rendering there are halved: the half whose removal
    ALONE brings the page's losses back stays dropped, the other is restored; when neither half alone does, both stay dropped and
    the halving stops. At most `L2_BUILDS_MAX` builds over all pages, counting the recorded one and a last one that checks the kept
    look; at the cap the set still dropped stays dropped whole (it errs toward the plugin's markup, never toward a loss). Each
    dropped construct is listed, `look: <construct> dropped: loses content (<what>)`; the rest of the look is kept.
  * L4, COVERAGE. The kept look's reason ends with the constructs mapped of those that have an instance, and the share of the old
    pages' class names (in content, counted once each) that are on the plugin's pages, under the derived look and under the default
    one: "62% against 9%" (`scoring.class_share`).

COST (section 7.6): one build of the default look under the chosen settings (L1, L4), then at most `L2_BUILDS_MAX` (12), once.

THE BISECTION'S BOUND, stated (step 11, a reading of section 6): halving asks the first half first; when it does not bring the losses
back, the second half is a second build. So one construct that loses the fact is found in `1 + ceil(log2 n)` builds when it is in the
first half at every level, and in at most `1 + 2 * ceil(log2 n)` wherever it is; the cap holds either way.
"""

import json

from adoption.scoring import class_share, describe_loss, lost_facts, score
from lookfiles.renderlog import recording

L2_BUILDS_MAX = 12

# L1 (step 11, 2026-11-21): thrown by the switch the coordinator ruled on, after step 11 held it. Thrown, it keeps a look whose
# every loss the default look shares; held, it moved three files outside step 11's set:
# test_adoption_look_real_sites.py (its D2 case asserts the whole-look refusal rule L replaces), test_adoption_look_unmodelled.py
# (with the look kept, `apply` stops on a held conversion's `redirects` instead of blocking at step 2) and a held-out steps case (an
# unexpected success). Held (False), the default look's losses are read as none, so every loss is the derived look's and L2 drops
# what dropping can bring back.
SUBTRACT_DEFAULT_LOSSES = True


def chosen_settings(res, defaults):
    """Every setting but `look` at the value the plan keeps (measured or chosen, not the default): what the look is judged under."""
    return dict((k, r.value) for k, r in res.rows.items()
                if k != "look" and r.how in ("measured", "chosen") and r.value is not None and r.value != defaults.get(k))


def without(look, dropped):
    """The derived look `look` ({"id", "file"}) with the constructs `dropped` taken out of its file."""
    data = json.loads(look["file"])
    data["constructs"] = dict((c, p) for c, p in (data.get("constructs") or {}).items() if c not in dropped)
    return dict(look, file=json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def constructs_of(look):
    return sorted((json.loads(look["file"]).get("constructs") or {}))


def own_losses(derived_lost, default_lost):
    """L1 and L3: ({page: [loss]} the derived look has and the default look does not, {page: [loss]} both have)."""
    own, gaps = {}, {}
    for page, losses in derived_lost.items():
        theirs = set(default_lost.get(page, ()))
        mine = [x for x in losses if x not in theirs]
        both = [x for x in losses if x in theirs]
        if mine:
            own[page] = mine
        if both:
            gaps[page] = both
    return own, gaps


def gap_lines(gaps):
    """L3's lines: each loss no look prints, once."""
    out = []
    for page in sorted(gaps):
        media = sum(1 for k, _v in gaps[page] if k == "media")
        if media:
            out.append("the plugin's build does not print: %s, %d image(s) or video(s) of the old page" % (page, media))
        out.extend("the plugin's build does not print: %s, the text %r" % (page, v[:40]) for k, v in gaps[page] if k == "text")
    return out


class Bisection(object):
    """L2's result: `dropped` (the constructs taken out), `ok` (every own loss comes back under the look without them), `builds`
    (how many were made), `why` {construct: the loss it was dropped for} and `stopped` (True when the cap ended it)."""

    def __init__(self):
        self.dropped, self.ok, self.builds, self.why, self.stopped = set(), True, 0, {}, False


def bisect(own, on_page, everything, build, back, cap=L2_BUILDS_MAX):
    """L2 over `own` ({page: [loss]}): `on_page` {page: the derived constructs rendering there}, `everything` the output with every
    derived construct dropped (the first build, already made and counted by the caller), `build(dropped) -> output` one build with
    the constructs `dropped` taken out, `back(output, page) -> bool` whether that page's own losses are all back. Returns a
    `Bisection` whose `builds` counts this function's builds and the first. The last build of the cap is kept for the check of the
    look as kept, so that check is always made: the halving stops at `cap - 1`."""
    b = Bisection()
    b.builds = 1
    limit = cap - 1
    for page in sorted(own):
        if not back(everything, page):
            b.ok = False
            b.why = {"": page}
            return b
    cur = None                                   # the output of the look without `b.dropped`, when one was built for exactly that set
    for page in sorted(own):
        if cur is not None and back(cur, page):
            continue
        if cur is None and b.dropped:
            if b.builds >= limit:
                b.stopped = True
            else:
                cur, b.builds = build(frozenset(b.dropped)), b.builds + 1
                if back(cur, page):
                    continue
        left = sorted(set(on_page.get(page) or ()) - b.dropped)
        if not left:
            b.ok = False
            b.why = {"": page}
            return b
        cur = None                               # the look without b.dropped | left is known good on this page, not built whole
        while len(left) > 1 and not b.stopped:
            half = len(left) // 2
            found = None
            for part in (left[:half], left[half:]):
                if b.builds >= limit:
                    b.stopped = True
                    break
                out, b.builds = build(frozenset(b.dropped | set(part))), b.builds + 1
                if back(out, page):
                    found = (part, out)
                    break
            if found is None:
                break                            # neither half alone (or the cap): the whole of `left` stays dropped
            left, cur = found
        b.dropped |= set(left)
        b.why.update((c, page) for c in left)
    if b.dropped and cur is None:
        cur, b.builds = build(frozenset(b.dropped)), b.builds + 1      # within the cap: the halving stopped one short of it
    if cur is not None and not all(back(cur, p) for p in own):
        b.ok = False
        b.why = {"": next(p for p in sorted(own) if not back(cur, p))}
    return b


def rendering_on(pages, calls, cids):
    """{page: the constructs of `cids` that render on it}: a recorded call of the construct whose markup is in that page's text."""
    out = {}
    for page, text in pages.items():
        out[page] = set(c.construct for c in calls if c.construct in cids and c.out and c.out.strip() and c.out in text)
    return out


def _recorded(evaluate, settings):
    """`evaluate(settings)` with every `looks.render` call recorded: (output, calls). A build the caller fakes records none."""
    with recording() as calls:
        out = evaluate(settings)
    return out, list(calls)


def coverage(res, local, derived, default, dropped=()):
    """L4: the look row's last words."""
    status = res.look_status or {}
    have = [c for c, s in status.items() if s in ("mapped", "unmapped", "ambiguous")]
    mapped = [c for c in have if status[c] == "mapped" and c not in dropped]
    mine, total = class_share(local, derived)
    theirs, _t = class_share(local, default)
    pct = lambda n: int(round(100.0 * n / total)) if total else 0             # noqa: E731
    return ("coverage: %d of %d construct(s) with an instance mapped; %d%% against %d%% of the %d class name(s) the old pages show "
            "in their content are on the plugin's pages (the derived look against the default one)"
            % (len(mapped), len(have), pct(mine), pct(theirs), total))


def keep(res, local, evaluate, lost, defaults):
    """Rule L for the look `res` (a `choose.Chosen`) keeps, after the last pass. `lost(local, plugin, "look")` is the first loss as
    a sentence ("" for none: `scoring.lost_content`, read through `adoption.choose` so a test can take the check out); `defaults`
    the settings' defaults. Changes `res` in place: the look row's value, how and reason, and `res.lines`."""
    row = res.rows.get("look")
    if local is None or row is None or row.how != "measured" or not isinstance(row.value, dict):
        return
    final = chosen_settings(res, defaults)
    derived = evaluate(dict(final, look=row.value))
    default = evaluate(dict(final))
    if score(local, derived, "look")[0] or not lost(local, derived, "look"):
        row.reason += "; " + coverage(res, local, derived, default)
        return
    own, gaps = own_losses(lost_facts(local, derived, "look"), lost_facts(local, default, "look") if SUBTRACT_DEFAULT_LOSSES else {})
    res.lines.extend(gap_lines(gaps))
    if not own:                                  # L1: every loss is one the default look has too, so none is the look's
        row.reason += "; " + coverage(res, local, derived, default)
        return
    cids = constructs_of(row.value)
    everything, calls = _recorded(evaluate, dict(final, look=without(row.value, cids)))
    on_page = rendering_on(dict((p, everything[p].decode("utf-8", "replace")) for p in own if p in everything), calls, set(cids))
    on_page = dict((p, on_page.get(p) or set(cids)) for p in own)          # nothing recorded (a faked build): every construct

    def back(out, page):
        if page not in out:
            return False
        still = lost_facts(local, out, "look", pages=(page,)).get(page, ())
        return not (set(own[page]) & set(still))
    b = bisect(own, on_page, everything, lambda dropped: evaluate(dict(final, look=without(row.value, dropped))), back)
    if not b.ok:
        page = b.why[""]
        why = describe_loss(page, own[page])
        res.rows["look"] = type(row)("look", None, "not measured", "the derived look loses content: " + why, [("derived", "loses content: " + why)])
        res.lines.append("you decide: look -- %s" % res.rows["look"].reason)
        return
    look = without(row.value, b.dropped)
    for c in sorted(b.dropped):
        res.lines.append("look: %s dropped: loses content (%s)" % (c, describe_loss(b.why[c], own[b.why[c]])))
    kept = evaluate(dict(final, look=look))
    row.value = look
    row.reason += "; %d construct(s) dropped: loses content (%s)%s; %s" % (
        len(b.dropped), ", ".join(sorted(b.dropped)), ", the build cap reached" if b.stopped else "",
        coverage(res, local, kept, default, b.dropped))
