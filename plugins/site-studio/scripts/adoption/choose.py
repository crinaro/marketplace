"""adoption.choose -- choose each measured setting by building the plugin's side once per candidate (design 8, "Measured settings";
R5.3, R6; step 1.9).

Part of the `adoption` package behind the entry point `adopt.py`. The settings and what writes them are `adoption.settings`; what
each setting is offered is `adoption.candidates` and how one candidate is judged against the old build is `adoption.scoring` (both
moved out of this file unedited, design-adopt-parity-2 step 1); this module DECIDES them:

  * ORDER. `look` first, then `featuredFrom`, `sort`, `nav.home`, `resume.headings`, `cardLabels` and the `view` of each portfolio,
    each with the earlier choices fixed. Greedy; interactions beyond that are design UNDETERMINED U-4.
  * MEASURE (rule M, design-adopt-parity-2 section 5; `decide`). Per candidate the plugin side alone is built IN MEMORY
    (`build.accept` over the converted tree: no git, no node, no disk) and compared, on the pages the setting can touch
    (`settings.setting_paths`, less M1's pages one build lacks and no candidate adds or removes), with the ONE local build. The first
    candidate whose touched pages are EQUAL or MARKUP-ONLY is the conversion (`how: measured`). When none qualifies, the candidate
    with the FEWEST visible differences on those pages is the conversion if it has strictly fewer than the default (`how: measured`,
    the reason says "fewest visible differences" and how many); when none is strictly better, M4 judges the visitor facts in the
    setting's own scope (`scoring.judge_by_facts`, over `adoption.facts`); when that does not decide either, the setting is `you
    decide`, naming each candidate's first difference, and it keeps its default (`how: not measured`).
  * FIXED POINT (step 1.9f). A setting is judged with every OTHER setting at the value chosen for it, so a setting that only makes
    sense under the right look (the nav's Home item, a card number, a menu link) is judged under that look, and the look is
    judged with those settings applied. One pass in order cannot do that, so passes repeat until no value changes, at most
    `MAX_PASSES` (3); the cost bound below counts passes. Without the fixed point every setting was judged against the default
    look on every page, no candidate could qualify, and the plan kept the default look (G3 on template-variant-a: 14 of 14
    `not measured`).
  * NO LOCAL BUILD, NO CHOICE (R1, S6). With no local build (node missing, a template that needs a network install, any other
    reason P1 gives) no setting is chosen: every one is `you decide: not measured (<the reason>)`, the reason printed once, and `look`
    is NEVER defaulted to a candidate. A setting the person CHOSE (`how: chosen`) is kept and not measured.
  * LOOK. Candidates in order: the default look; then, only if it does not qualify, a look DERIVED from the local build's own pages
    against the converted content (`look.derive_look`, R5.4, R6): vendored as `site/looks/derived.json`. EQUAL under a derived look is
    evidence of page assembly on the person's current content, not of template fidelity (R5.3); a construct it could not map stays
    DIFFERENT and is a `look/unmapped/<construct>` cause (`Chosen.look_status`).
  * THE LOOK FOLLOWS THE CANDIDATE (step G3 flip). A derived look is made FROM the converted content, and a setting changes that content
    (a card number the plugin now prints is a slot the old card's number can be mapped to; a card label that is off makes the card's
    value the text the old page shows, so a year is no longer a literal). So while a derived look is the look in play, every
    candidate of every other setting is judged under the look derived FOR THAT CANDIDATE (`derive_under(settings)`), and the look
    the plan keeps is derived once more under the settings finally chosen. Without this a setting that only helps once the look
    can carry what it adds (cardNumber, cardLabels) is judged against a look made without it, ties, and stays `not measured`.
  * A SETTING THAT CHANGES NOTHING A VISITOR SEES. When every candidate, the default included, leaves exactly the same visible
    differences on the pages the setting touches, the setting has no effect there: the default is kept, `how: measured`, and the
    reason says so. (A tie with different differences is still `not measured`: the person decides.)
  * SORT IS JUDGED BY ORDER. `sort.<portfolio>` changes the ORDER of the pieces on the portfolio's index and nothing else, and a look
    that cannot map cards that stand in another order hides the right value (the cards of a portfolio sorted by `order` do not
    form the run the date order builds). So it is scored by the order of the piece links on the index page, old against
    candidate (`link_order`), never by the page's other differences.
  * A DEPENDENT VALUE. A card number prints in a format, and a number in the wrong format is worse than none, so the candidate
    `cardNumber: true` is scored under the best `cardNumberFormat` (`partner`); the format is then chosen on its own. The resume's
    headings and its layout are two halves of one page (role cards under headings written as the old page wrote them), and each
    alone leaves the page as different as the other does, so each is scored under the best value of the other.
  * A VIEW AS WRITTEN. A built-in `view` the old page.md names (`roles`, `showcase`) is what the person wrote: another view wins
    only by being EQUAL, never by having fewer differences (a grid has fewer differences from a page it does not look like).
  * WHAT A SETTING IS NOT JUDGED ON. A difference no visitor of the page meets (`not_seen`: the `<meta name="description">` text a search
    engine reads, and the plugin's own stylesheet and script files, which change nothing on a page that does not use them) is in every
    candidate's pages, so it can never decide between them, and it made every setting that touches a page with one a tie. The publish
    gate still counts them (parity says DIFFERENT); only the choice of a setting ignores them.
  * THE HOME'S AND THE INDEX'S OPTIONS (G3 adopt link). `titleForm`, `introScope` and `partOrder` (the home page's front matter) and
    `onePieceIndex.<portfolio>` (a one-piece portfolio's page.md) are schema-4 build options, measured like the rest, each on the
    one page it touches. The candidate for `partOrder` is READ from the old build (`adoption.homeparts`: the order the old home page
    prints the parts of the converted home in) and kept only when the plugin's build agrees: a reading is a guess where two parts
    share their only text, the measurement is not. `introScope` is offered for a home whose body has a second block outside its
    `:::part` blocks, and `rest` is a part of a `partOrder` only under `first-block`. The home's options are judged under every other
    setting but no other setting is judged under them (a `partOrder` naming `featured` made `featuredFrom` unmeasurable in the second
    pass), and each is judged under a refined look (`look.derive_look` reads again while an instance stays ambiguous, up to four
    times), because one reading leaves a wrapped part of the home ambiguous.
  * THE LONE REFERENCE (G3, the last link). `blocks.loneReferenceGrid` (site.json, schema 4) is offered only where a body of the
    converted tree holds a `ref:` line that stands alone (`has_lone_reference`: the build writes one reference as a bare card and two
    or more as a grid), and measured on every page like any other: the old builder's grid of one is what a candidate has to equal.
  * THE LIVE PLAYER (owner ruling 2026-11-18). `blocks.videoEmbed` (site.json, schema 4) is offered only where the converted tree
    holds a `:::videos` block or a gallery video row (`has_video`), and judged like `blocks.loneReferenceGrid`: last, on every page,
    under the look derived FOR the candidate. Only the live address lets the look derive map a player (the page's own address is the
    value a slot is found by), so the plugin's click-to-load address (`facade`, the default) is judged first and the live one wins
    when it leaves fewer visible differences. The key is the ADDRESS; the look's markup says whether a player loads with the page.
  * A LOOK IS KEPT PER CONSTRUCT (rule L, design-adopt-parity-2 section 6, step 11; it replaced D2's whole-look refusal, dev 941). A
    derived look is a look of FEWEST differences when no candidate is EQUAL, and fewest is not the same as nothing taken away. Once
    every other setting has its value, `adoption.lookkeep.keep` asks what the look the plan keeps loses (`lost_content`, read through
    this module) against what the default look loses under the same settings: a loss both have is a content gap, listed and never
    the look's; a construct that loses what the default look shows is dropped alone, found by bisection, and the rest is kept. It is
    judged LAST, never while the look is a candidate: a card number, a label or a featured piece's picture is another setting's to
    put back, and a look judged before them would lose what they supply.
  * THE CARD AND PIECE SETTINGS (design-movement-view 6.3, schema 5). `cardImage`, `cardAlt`, `cardKicker`, `pieceLink` and
    `pieceTeaser` of each portfolio are offered only when their "offered when" holds (`v5_candidates`): a piece has `photo` (or, under
    a roles view, `photo` or `cover`); a piece has `coverAlt` or `photoAlt`; a piece key nothing reads exists (`unread_keys`: not built
    in, not in `meta`, `cardMeta` or `groupBy`, not read by the view or another setting the portfolio is judged under, not renamed by a
    pending conversion), most-used first, name order on a tie, at most `KICKER_MAX`; a piece has `link`; a piece has `teaser`, or a key a
    pending conversion makes `teaser` (`summary`). Each is judged like every setting, under the look derived for the candidate.
  * THE SCHEMA-6 SETTINGS (design-adopt-parity-2 section 7.6; `candidates.v6_candidates`). Each is offered only where its "offered
    when" holds and judged like the rest. `backLink` is measured per portfolio (`backLink.<p>`); a site-wide `backLink` the person
    chose stays the one row. M4 reads each build's addresses under its own path and the old build's links through the recorded
    redirects (`facts.frame_for`, read once per `choose`: section 5.1's piece key, section 7.1's two paths; step 8b, F8).
  * COST. One `accept` per candidate per pass, and a second pass runs only when the first moved a value off its default: the cost case
    (`test_choose.Cost`) bounds the whole at `3 x (candidates + 1) x` one `accept`, which is the pass cap times one pass. The five card
    and piece settings add at most 3 + 2 + 5 + 2 + 2 = 14 candidates per portfolio per pass, and none where nothing is offered: the
    gate counts them (`test_choose.CostSchema5`).

`evaluate(settings) -> {path: bytes}` is the plugin output for a settings dict, supplied by the caller (so the greedy loop is tested
over fakes and the real one is `accept`-backed in `adoption.measure`).
"""

import json

from adoption import homeparts  # noqa: F401 -- read through this module by test_choose.py (`C.homeparts`)
from adoption.candidates import (BUILT_IN_VIEWS, DEFAULTS, VIDEO_EMBED, candidates_for, look_partner, partner, portfolio_facts,
                                 setting_names)
from adoption import facts, joint, lookkeep
from adoption.scoring import judge_by_facts, judged_paths, lost_content, one_build_pages, refusal_line, refusals, score
from adoption.settings import setting_family, unwritten_reason
# Moved to `adoption.candidates` and `adoption.scoring` by split_module.py (design-adopt-parity-2 step 1) and still read through this
# module by the test_choose.py classes, which the move left unedited: re-exports only, never patched here. (`lost_content`, which
# test_adoption_look_real_sites.py patches on this module, is imported above because `choose` hands it to `lookkeep.keep`.)
from adoption.candidates import TEASER_SOURCES, back_link_texts, showcased  # noqa: F401
from adoption.scoring import link_order, not_seen, score_order  # noqa: F401
from adoption.settings import V5_PORTFOLIO_SETTINGS  # noqa: F401 -- the same: test_choose.py reads `C.V5_PORTFOLIO_SETTINGS`


MAX_PASSES = 3


HOME_OPTIONS = ("titleForm", "introScope", "partOrder")    # the home page's own options: each is judged under a refined look (read up to four times; one reading
#                                                            leaves the home's wrapped parts ambiguous), and no other setting under them
LONE_REFERENCE = "blocks.loneReferenceGrid"    # judged under every other setting, and no other setting under it (see JUDGED_LAST)
BODY_HEADINGS = "blocks.headings"     # step 8b: judged under `blocks.headingLevel` (which wins inside a block), never it under this
JUDGED_LAST = HOME_OPTIONS + (LONE_REFERENCE, VIDEO_EMBED, BODY_HEADINGS)   # judged under every other setting; no setting that is not one of these is judged under them
NEEDS_LOCAL = ("look", "backLink")          # settings whose candidates come from the old builder's own output
NEVER_TIED = ("look", "carried")            # rule J (section 8.1): never judged together; a chosen or all-refused setting has no tie either


class Row(object):
    """One setting's result: `value`, `how` (`measured`, `chosen`, `not measured`), `reason`, and `tried` ([(candidate, first
    visible difference)] for a setting no candidate satisfied)."""

    def __init__(self, name, value, how, reason, tried=()):
        self.name, self.value, self.how, self.reason, self.tried = name, value, how, reason, list(tried)

    def plan_row(self):
        return {"value": self.value, "how": self.how, "reason": self.reason}


class Chosen(object):
    def __init__(self):
        self.rows, self.lines, self.look_status, self.passes = {}, [], {}, 0

    def values(self):
        return dict((n, r.value) for n, r in self.rows.items() if r.how in ("measured", "chosen") and r.value is not None
                    and r.value != DEFAULTS.get(n))

    def plan_rows(self):
        return dict((n, r.plan_row()) for n, r in self.rows.items())


def _reason(name, picked, is_default, snap, partly=None):
    reason = ("the default leaves the pages it touches the same" if is_default
              else "the first candidate whose pages are EQUAL or MARKUP-ONLY")
    if partly == "none":
        return "no candidate changes what a visitor sees on the pages it touches: the default stays"
    if partly == "refused":
        return "the plugin's build refuses every other candidate: the default stays"
    if partly:
        return "the fewest visible differences on the pages it touches (%d, the default has %d); the rest is not this setting's" % partly
    if name == "featuredFrom" and picked == "flags":
        n = sum(1 for f in portfolio_facts(snap).values() for fm in f["pieces"] if fm.get("featured", "").lower() in ("true", "yes"))
        reason = ("without `featuredFrom: flags` the home page loses its featured pieces (%d piece(s) flagged; `{{featured}}` "
                  "renders none)" % n)
    elif setting_family(name) == "sort" and picked == "order":
        reason = "every piece carries an integer `order`; without `sort: order` your pieces are sorted by date, then title"
    return reason


class Decision(object):
    """What `decide` makes of one setting: its `row`, the line to print (`line`, or None), and whether the value is to be fixed for
    the settings judged after it (`fix`: the value, or `CLEAR` when the setting is at its default or undecided); for `look`, the
    default look's count of visible differences (`default_n`) and derive's status (`look_status`, None when derive was not asked).
    Rule J (design-adopt-ownership-line section 8.1): `tie` is the default candidate's first difference `(page, what)` when the
    setting is `you decide` with two or more live candidates, or M3's "no effect", else None; `live` the candidates that were not
    refused, in order (`adoption.joint` combines them)."""

    def __init__(self, row, line=None, fix=None, default_n=None, look_status=None):
        self.row, self.line, self.fix, self.default_n, self.look_status = row, line, fix, default_n, look_status
        self.tie, self.live = None, []

    def tied(self, tried, live):
        """Mark this decision tied on the default's first difference (`tried[0]`), with the `live` candidates."""
        page, _sep, what = (tried[0][1] if tried else "").partition(": ")
        self.tie, self.live = (page, what), [t[0] for t in live]
        return self


class CLEAR(object):
    """`Decision.fix` for a setting at its default or undecided: no key is fixed for the settings judged after it."""


class Judge(object):
    """What every setting of one `choose` is judged with: the converted tree, the old build, `evaluate`, and the closures of `choose`
    (`under`, `best_score`, `derived_for`); the portfolios and the piece addresses rule M4 reads (`adoption.facts`), and one cache of
    page readings shared by every candidate."""

    def __init__(self, snap, local, evaluate, under, best_score, derived_for, can_derive, data=None, whose="the look's"):
        self.snap, self.local, self.evaluate, self.under, self.whose, self.data = snap, local, evaluate, under, whose, data
        self.best_score, self.derived_for, self.can_derive = best_score, derived_for, can_derive
        self.ports = sorted(portfolio_facts(snap))
        self.pieces = facts.piece_addresses(snap)
        self.frame = facts.frame_for(snap, data, local)          # each build's path and the redirects (sections 5.1, 7.1)
        self.cache = {}


def decide(j, name, cands, others):
    """One setting judged by rule M (design-adopt-parity-2 section 5.1), the first test that decides winning:

      M1  its pages are `setting_paths` less every page one build lacks and no candidate adds or removes (`one_build_pages`; asked
          only when the default's build lacks a page or adds one, so a site where both builds write the same pages is judged as
          0.5.0 judged it);
      M2  the first candidate, default first, whose pages are EQUAL or MARKUP-ONLY (for `look`, then a look derived from the old pages);
      M3  every candidate leaves the same differences: the default stays, and decides even when the default is None (step 8d: a
          None default no longer reads as undecided and falls through to M4); else one with strictly fewer hunks that builds the
          same pages (never against a built-in view the person wrote);
      M4  the visitor facts in the setting's own scope (`scoring.judge_by_facts`): the unique smallest distance, smaller than the
          default's; or, in a scope that is the setting's own region, the default when every candidate leaves the same facts there
          (its winner is then the default, which may be None: `m4.winner`, never the value, says M4 decided). Never for `look`,
          never against a written built-in view.

    Otherwise `you decide`. A candidate (not the default, not for `look`) whose build the publish build refuses where the default's is
    not (`scoring.refusals`; step 11c, F24) never wins any of them: it is tried as "the plugin's build refuses it: <what>", and the
    row's reason names it (a value the look in place cannot print, the slot named). Under a derived look the look is not judged
    against a setting's value: the value yields. Returns a `Decision`."""
    snap, local, evaluate = j.snap, j.local, j.evaluate
    drop, first = frozenset(), j.best_score(name, cands[0], others)
    if one_build_pages(local, [first[1]], name):
        drop = one_build_pages(local, [first[1]] + [evaluate(j.under(name, c, others)) for c in cands[1:]], name)
        first = j.best_score(name, cands[0], others, drop) if drop else first
    tried, picked, partly, outs = [], None, None, []          # tried: [(candidate, first difference, count, pages, seen)]
    refused = []                                             # [(candidate, what its build is refused for)] (step 11c)
    for i, cand in enumerate(cands):
        (ok, why, n, pset, seen), plugin = first if i == 0 else j.best_score(name, cand, others, drop)
        outs.append(plugin)
        bad = refusals(plugin, outs[0]) if i and name != "look" else ()
        if bad:              # never picked, never the fewest (no pages), never alike for M4 (scoring._same_pages)
            refused.append((cand, refusal_line(bad, j.whose)))
            tried.append((cand, "the plugin's build refuses it: " + refused[-1][1], 10 ** 9, None, None))
            continue
        if ok:
            picked = cand
            break
        tried.append((cand, why, n, pset, seen))
    if picked is None and cands and len(tried) < len(cands):     # the absent candidate (None) itself was EQUAL
        return Decision(Row(name, None, "measured", _reason(name, None, True, snap, None)), fix=CLEAR)
    out = Decision(None, default_n=tried[0][2] if name == "look" and tried else None)
    if picked is None and name == "look" and j.can_derive:
        look, status, err = j.derived_for(dict((k, v) for k, v in others.items() if k != "look"))
        out.look_status = status or {}
        if look is None:
            tried.append(("derived", "could not derive: %s" % (err or "nothing to derive"), 10 ** 9, None, ()))
        else:
            ok, why, n, pset, seen = score(local, evaluate(dict(others, look=look)), name, drop)
            if ok:
                picked = look
            else:
                tried.append(("derived", why, n, pset, seen))
    decided = picked is not None             # M2 picked; from here a rule may pick the default, which may be None (step 8d)
    live = [t for t in tried if t[4] is not None]           # a refused candidate is no evidence either way
    if not decided and refused and live == tried[:1]:
        picked, partly, decided = cands[0], "refused", True   # every other candidate is refused: the default stays
    if not decided and len(live) > 1 and name != "look" and len(set(t[4] for t in live)) == 1:
        picked, partly, decided = cands[0], "none", True   # every candidate leaves exactly the same differences: no effect
    written = portfolio_facts(snap).get(name.split(".", 1)[1], {}).get("view") if setting_family(name) == "view" else None
    if not decided and len(tried) > 1 and written not in BUILT_IN_VIEWS:
        # only a candidate that builds the SAME PAGES as the default can win by count: a candidate that drops a page
        # (a view that replaces an index) has fewer differences by having fewer pages, not by being closer
        same_pages = [t for t in tried[1:] if t[3] is not None and t[3] == tried[0][3]]
        best = min(same_pages, key=lambda t: t[2]) if same_pages else tried[0]
        if best[2] < tried[0][2]:                                  # strictly fewer visible differences than the default
            picked = (j.derived_for(dict((k, v) for k, v in others.items() if k != "look"))[0] if best[0] == "derived" else best[0])
            partly, decided = (best[2], tried[0][2]), True
    m4 = None
    if not decided and name != "look" and written not in BUILT_IN_VIEWS and len(outs) == len(cands) > 1:
        m4 = judge_by_facts(name, cands, local, outs, j.ports, j.pieces, j.cache, drop, j.frame)
        if m4 is not None and m4.winner is not None:
            picked, decided = cands[m4.winner], True
    if not decided:
        lines = ([(c, w) for c, w in m4.tried] if m4 is not None and m4.tried else [(c, w) for c, w, _n, _p, _s in tried])
        reason = ("no candidate leaves the pages it touches the same: " + "; ".join(
            "%s -> %s" % (c if isinstance(c, str) else json.dumps(c), w) for c, w, _n, _p, _s in tried))
        if m4 is not None:
            reason += "; by what a visitor meets there, " + m4.reason
        out.row = Row(name, None, "not measured", reason, lines)
        out.line, out.fix = "you decide: %s -- %s" % (name, reason), CLEAR
        return out.tied(tried, live) if name not in NEVER_TIED and len(live) > 1 else out
    is_default = picked == cands[0] and not isinstance(picked, dict)
    reason = m4.reason if m4 is not None and m4.winner is not None else _reason(name, picked, is_default, snap, partly)
    unwritten = [unwritten_reason(snap, name, c) for c in cands[1:] if c is not None] if partly == "none" else []
    if any(unwritten):        # dev #1041: a candidate adopt could not write measures as the default, which is not "measured"
        reason = "not written: %s; the default stays" % next(u for u in unwritten if u)
    reason += "".join("; %s loses: the plugin's build refuses it (%s)" % (c if isinstance(c, str) else json.dumps(c), w)
                      for c, w in refused)
    out.row = Row(name, picked, "measured", reason)
    if partly and partly not in ("none", "refused"):
        out.line = "partly: %s -- %s" % (name, reason)
    out.fix = CLEAR if is_default else picked              # a default is no key: it needs no fixing for the others to be judged under it
    return out.tied(tried, live) if partly == "none" and name not in NEVER_TIED else out


def choose(snap, data, evaluate, local, previous=None, no_local_reason=None, derive=None, names=None, derive_under=None):
    """Choose every setting. `snap` is the converted tree ({path: bytes}), `evaluate(settings)` the plugin output for a settings
    dict, `local` the old builder's output (or None), `previous` the plan's settings (a `chosen` row is kept as it is), `derive()`
    returns (look dict {"id","file"}, status {construct: status}) or raises when nothing can be derived. `derive_under(settings)` is
    the same for the converted tree under `settings` (the non-look settings): when it is given, a derived look is made again for
    every candidate (see the module docstring, THE LOOK FOLLOWS THE CANDIDATE) and `derive` is not used. Returns a `Chosen`.

    Passes repeat (at most `MAX_PASSES`) until no chosen value changes: each setting is judged with the others at their chosen values
    (see the module docstring, FIXED POINT), and each by `decide` (rule M). `Chosen.passes` says how many ran."""
    res = Chosen()
    previous = previous or {}
    names = list(names or setting_names(snap))
    if (previous.get("backLink") or {}).get("how") == "chosen" and any(n.startswith("backLink.") for n in names):
        # a site-wide `backLink` the person chose (0.5.x's one name) is kept as they chose it, in place of the per-portfolio ones
        at = min(i for i, n in enumerate(names) if n.startswith("backLink."))
        names = [n for n in names[:at] if n != "backLink"] + ["backLink"] + [
            n for n in names[at:] if not n.startswith("backLink.") and n != "backLink"]
    chosen = dict((n, p["value"]) for n, p in previous.items() if p["how"] == "chosen" and n in names)
    fixed = dict(chosen)
    derived = {}                                    # the derive answers, by the non-look settings they were made under

    def derived_for(non_look, refine=True):
        """(look, status, error): the derived look for the converted tree under `non_look`, asked once per distinct set. A look made
        to SCORE a candidate is read once (`refine` False); the look the plan keeps, and the one `look` is judged on, is read up to four times (`look.derive_look`)."""
        key = json.dumps([sorted(non_look.items()), refine], default=repr) if derive_under is not None else ""
        if key not in derived:
            try:
                look, status = (derive_under(dict(non_look), refine) if derive_under is not None else derive())
                derived[key] = (look, status or {}, None)
            except Exception as e:      # noqa: BLE001 -- derive refuses with its own words; a refusal is a finding, not a crash
                derived[key] = (None, {}, str(e)[:120])
        return derived[key]

    def under(name, cand, others):
        """The settings a candidate is built with: the others, the candidate, and, when a derived look is in play, the look derived
        for exactly these."""
        st = dict(others, **{name: cand})
        if name != "look" and derive_under is not None and isinstance(others.get("look"), dict):
            non_look = dict((k, v) for k, v in st.items() if k != "look")
            look = derived_for(non_look, name in HOME_OPTIONS)[0]
            if look is not None:
                st["look"] = look
        return st

    def best_score(name, cand, others, drop=frozenset()):
        """(`score`, the plugin output it was made from) of one candidate; a candidate with a DEPENDENT setting is scored under that
        setting's best value."""
        dep = partner(name, cand, snap) or (look_partner(name, cand) if isinstance(others.get("look"), dict) else None)
        if dep is None:
            plugin = evaluate(under(name, cand, others))
            return score(local, plugin, name, drop), plugin
        out = None
        for v in candidates_for(dep, snap, data, local):
            plugin = evaluate(under(name, cand, dict(others, **{dep: v})))
            r = score(local, plugin, name, drop)
            if out is None or (r[0], -r[2]) > (out[0][0], -out[0][2]):
                out = (r, plugin)
        return out

    judge = Judge(snap, local, evaluate, under, best_score, derived_for, derive is not None or derive_under is not None, data)
    ledger = res.ledger = joint.Ledger(evaluate)
    held = dict((n, Row(n, p["value"], "chosen", p["reason"])) for n, p in previous.items() if p["how"] == "chosen")
    for npass in range(1, MAX_PASSES + 1):
        res.rows, res.lines, res.passes = {}, [], npass
        picks, judged, decisions = _pass(judge, res, names, fixed, held, ledger, no_local_reason)
        new = dict(chosen, **picks)
        if new == fixed or judged < 2:                 # nothing moved, or only one setting was judged: no interaction to re-judge
            break
        fixed = new
    ledger.mark("passes")
    if local is not None:                          # rule J (section 8): the tied families, judged together, then one settle pass
        together, moved = joint.judge_families(res, names, decisions, _JointContext(res, judge, ledger))
        ledger.mark("joint")
        if moved:                                  # 8.2 step 8: one more ordinary pass with the members held, so the others can answer
            held.update((n, res.rows[n]) for n in together)
            rows, lines = res.rows, res.lines
            res.rows, res.lines, res.passes = {}, [], res.passes + 1
            _pass(judge, res, names, dict(res_values(rows)), held, ledger, no_local_reason)
            res.lines += [l for l in lines if l.startswith(("judged together", "not judged together")) or l.startswith(tuple(
                "%s: %s -- " % (k, n) for n in together for k in ("you decide", "partly")))]
            ledger.mark("settle pass")
    _final_look(res, local, evaluate, derive_under, derived_for, snap)
    ledger.mark("final look")
    lookkeep.keep(res, local, evaluate, lost_content, DEFAULTS)
    ledger.mark("rule L")
    ledger.refused = settle_refused(res, snap, data, local, evaluate)
    ledger.mark("settle refused")
    return res


def res_values(rows):
    """[(name, value)] of the rows a pass fixes the next one under: measured or chosen, not None, not the default."""
    return [(n, r.value) for n, r in rows.items() if r.how in ("measured", "chosen") and r.value is not None and r.value != DEFAULTS.get(n)]


def _pass(j, res, names, fixed, held, ledger, no_local_reason):
    """One pass of the greedy loop (FIXED POINT): each setting in order, judged by `decide` under `fixed` and this pass's earlier
    picks; a setting in `held` ({name: Row}: one the person chose, or in the settle pass a member rule J judged) keeps its row.
    Returns (picks {name: value}, how many were judged, {name: Decision})."""
    snap, data, local = j.snap, j.data, j.local
    picks, judged, cur, decisions = {}, 0, dict(fixed), {}     # `cur`: what the next setting is judged under (earlier picks of THIS pass included)
    for name in names:
        if name in held:
            res.rows[name] = held[name]
            continue
        if local is None:
            if setting_family(name) in NEEDS_LOCAL or len(candidates_for(name, snap, data)) > 1:
                res.rows[name] = Row(name, None, "not measured", "not measured (%s)" % (no_local_reason or "no local build"))
            continue
        # the home's own options and the lone reference's grid are judged under every other setting, but no other setting is judged
        # under them: a `partOrder` that names `featured` made `featuredFrom` unmeasurable in the second pass (the builder of the home
        # options, F1), and so did `blocks.loneReferenceGrid` (the page that holds the lone reference changes what the look derive reads
        # of the home, which no setting of the home can answer for)
        others = dict((k, v) for k, v in cur.items() if k != name and (name in JUDGED_LAST or k not in JUDGED_LAST))
        cands = candidates_for(name, snap, data, local, others)
        if len(cands) < 2 and name != "look":
            continue
        judged += 1
        ledger.ask(name, sum(len(_dependent(j, name, c, (), isinstance(others.get("look"), dict))) for c in cands))
        d = decisions[name] = decide(j, name, cands, others)
        res.rows[name] = d.row
        if d.look_status is not None:
            res.look_status = d.look_status
        if d.line:
            res.lines.append(d.line)
        if d.fix is CLEAR:
            cur.pop(name, None)
        else:
            picks[name] = cur[name] = d.fix
    return picks, judged, decisions


def _dependent(j, name, cand, members, derived):
    """[(dependent setting, value)] one candidate is scored under (`best_score`: a candidate with a DEPENDENT setting is built once
    per value of it), or [(None, None)] for one build; a dependent among `members` (rule J's family, which varies it already) adds
    none. `derived` says a derived look is in play (`look_partner`)."""
    dep = partner(name, cand, j.snap) or (look_partner(name, cand) if derived else None)
    if dep is None or dep in members:
        return [(None, None)]
    return [(dep, v) for v in candidates_for(dep, j.snap, j.data, j.local)]


class _JointContext(object):
    """What `joint.judge_families` builds and reads through (`adoption.joint`): every combination under the settings the passes
    chose for the others, with the look derived for it when a derived look is in play, as `under` does for one candidate."""

    def __init__(self, res, j, ledger):
        self.res, self.j, self.local, self.ledger, self.Row = res, j, j.local, ledger, Row

    def paths(self, name):
        return judged_paths(name, self.local)

    def _derived(self):
        return isinstance(getattr(self.res.rows.get("look"), "value", None), dict)

    def deps(self, name, value, members):
        return len(_dependent(self.j, name, value, members, self._derived()))

    def deps_values(self, name, value, members):
        pairs = _dependent(self.j, name, value, members, self._derived())
        return [] if pairs == [(None, None)] else pairs

    def build(self, values):
        last = any(n in JUDGED_LAST for n in values)
        base = dict((k, v) for k, v in self.res.values().items() if k not in values and (last or k not in JUDGED_LAST))
        first = sorted(values)[0]
        return self.j.evaluate(self.j.under(first, values[first], dict(base, **dict((k, v) for k, v in values.items() if k != first))))


def settle_refused(res, snap, data, local, evaluate):
    """Step 11c (F24): the settings against the look the plan KEEPS. A measured setting whose value that look cannot print (the
    publish build refuses the tree under it, where under the default look it does not: `scoring.refusals`) is judged again by rule M
    under the kept look, its refused candidates never winning, so it loses to the next candidate or the default; its reason names
    the slot ("the kept look's card.wrap has no {{kicker}}"). The look is never changed for a setting's value (rule L judges
    constructs by what a visitor sees, section 6, and a value that cannot print under the look shows nothing). Only a setting the
    refusal names (its key) is judged again, each once; a person's `chosen` value is kept. Its `Judge` keeps the look as it is (no
    look is derived again, and no dependent setting is searched again). Costs two builds when nothing is refused, and one
    a candidate of each setting judged again: returns how many candidates it judged (`joint.bound`'s `refused`)."""
    row = res.rows.get("look")
    if local is None or row is None or row.how != "measured" or not isinstance(row.value, dict):
        return 0
    final = lookkeep.chosen_settings(res, DEFAULTS)
    bad = refusals(evaluate(dict(final, look=row.value)), evaluate(dict(final)))
    if not bad:
        return 0

    def under(name, cand, others):
        return dict(others, **{name: cand})

    def best_score(name, cand, others, drop=frozenset()):
        plugin = evaluate(under(name, cand, others))
        return score(local, plugin, name, drop), plugin
    j = Judge(snap, local, evaluate, under, best_score, None, False, data, "the kept look's")
    keys, judged = set((p.found or "").split(" ", 1)[0] for p in bad), 0
    for name in [n for n in final if setting_family(n) in keys and res.rows[n].how == "measured"]:
        others = dict((k, v) for k, v in final.items() if k != name)
        cands = candidates_for(name, snap, data, local, others)
        if len(cands) < 2:
            continue
        judged += len(cands)
        d = decide(j, name, cands, dict(others, look=row.value))
        res.lines = [l for l in res.lines if not l.startswith(("partly: %s -- " % name, "you decide: %s -- " % name))]
        res.rows[name] = d.row
        if d.line:
            res.lines.append(d.line)
        final = lookkeep.chosen_settings(res, DEFAULTS)
    return judged


def _final_look(res, local, evaluate, derive_under, derived_for, snap):
    """The look the plan keeps is the one derived under the settings finally chosen (when it leaves no more differences)."""
    row = res.rows.get("look")
    if derive_under is not None and row is not None and row.how == "measured" and isinstance(row.value, dict):
        final = dict((k, r.value) for k, r in res.rows.items()
                     if k != "look" and r.how in ("measured", "chosen") and r.value is not None and r.value != DEFAULTS.get(k))
        look, status, _err = derived_for(final)
        if look is not None and look != row.value:
            _ok0, _w0, kept_n, _p0, _s0 = score(local, evaluate(dict(final, look=row.value)), "look")
            ok, _why, n, _pset, _seen = score(local, evaluate(dict(final, look=look)), "look")
            if n <= kept_n:
                default_n = score(local, evaluate(dict(final)), "look")[2]
                res.rows["look"] = Row("look", look, "measured", _reason("look", look, False, snap, None if ok else (n, default_n)))
                res.look_status = status or {}
