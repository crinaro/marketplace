"""adoption.joint -- rule J: settings tied on the same first difference are judged together (design-adopt-ownership-line section 8,
owner decision 4: tied families only, capped; dev 1006 section 1).

Part of the `adoption` package behind the entry point `adopt.py`. `adoption.choose` makes the one call (`judge_families`) after its
pass loop, with every setting at the value the passes chose:

  * WHICH SETTINGS (8.1). A setting is TIED when its last `choose.Decision` was `you decide` with two or more live candidates, or
    M3's "no effect"; `Decision.tie` is the default candidate's first difference, `(page, what)`. A FAMILY is the tied settings with
    the same `tie`; a family of one is left alone. `look`, `carried`, a chosen setting and one whose other candidates were all
    refused are never tied (`decide` sets no `tie` for them).
  * FACTORS AND COST, BEFORE ANY BUILD (8.2 steps 1 and 2). Each member brings its live candidates, at most `JOINT_VALUES_MAX` (the
    default and the first two others; the rest are named, "not combined"). `B_f` is the builds every combination asks for: one, times
    the values of a dependent setting a member's value is scored under (`cardNumber: true` under each `cardNumberFormat`), unless that
    dependent is itself a member.
  * FIT (step 3). While `B_f > min(JOINT_FAMILY_BUILDS, JOINT_BUILDS - spent)` the family's last member (in the order settings are
    chosen) is cut, with the line `not judged together: <name> (<n> combinations would need <B> builds; the cap is <cap>)`; a family
    cut below two is skipped. At most `JOINT_FAMILIES` families, in the order of their first member. The cap is checked against
    `B_f`, never against what a cache might save.
  * JUDGE (steps 4 and 5), on the union of the members' pages, fewest changes first: J1 a combination the build refuses where the
    all-default is not never wins; J2 the first whose pages are EQUAL or MARKUP-ONLY; J3 else the one with strictly fewer visible
    differences than the all-default and than every single change, building the same pages (equal counts: fewest changes; still
    equal: `you decide`, naming them). M4 is not applied to a combination.
  * MINIMAL (step 6). A member of the winner whose default leaves the same count and the same differences reverts to its default.
  * ROWS (step 7). A member that ends changed is `measured`, "judged together with ...: together they leave N visible difference(s)
    on <pages> (the defaults leave M); alone it changed nothing"; one at its default keeps its row with "; judged together with ...:
    no combination does better" (or "you decide between ...").

THE BOUND (8.3, with review round 2's M2: every phase listed). One `choose` makes at most `bound(C, refused)` builds, a build being one
`running.accept` (the cache misses of `adoption.measure`'s `evaluate`): `(MAX_PASSES + 1) x (C + 1)` for the passes and the settle
pass, `JOINT_BUILDS`, `FINAL_LOOK_BUILDS` (`choose._final_look`), `RULE_L_BUILDS` (`lookkeep.keep`: `L2_BUILDS_MAX` + 2, held here as
a literal so that a raised `L2_BUILDS_MAX` fails `CostBound` instead of moving the bound with it), `SETTLE_REFUSED_BUILDS` plus one
per candidate of each setting `settle_refused` judges again, and `PERSON_BUILDS_MAX` (section 4's rows, `adoption.lookperson`). `C` is the
candidates summed over the settings, a candidate scored under a dependent counted once per value of it (`Ledger`).
"""

import itertools
import json

import parity_classes
from adoption.scoring import not_seen, refusals

JOINT_FAMILY_BUILDS = 32
JOINT_BUILDS = 48
JOINT_FAMILIES = 3
JOINT_VALUES_MAX = 3

MAX_PASSES_BOUND = 3            # choose.MAX_PASSES, held here as the bound's own figure (test_joint.CostBound pins that they agree)
FINAL_LOOK_BUILDS = 3           # `choose._final_look`: the kept look, the look derived under the final settings, the default look
RULE_L_BUILDS = 12 + 2          # `lookkeep.keep`: L2_BUILDS_MAX (12) and the derived and default looks' builds
SETTLE_REFUSED_BUILDS = 2       # `choose.settle_refused`: the kept look and the default look under the final settings; then one a candidate
PERSON_BUILDS_MAX = 1 + 8       # section 4's rows (`lookperson.py`): B, then at most lookperson.PERSON_BUILDS_MAX (8) alone


def bound(candidates, refused=0):
    """The most builds one `choose` makes (section 8.3): `candidates` is `C`, `refused` the candidates `settle_refused` judged."""
    return ((MAX_PASSES_BOUND + 1) * (candidates + 1) + JOINT_BUILDS + FINAL_LOOK_BUILDS + RULE_L_BUILDS
            + SETTLE_REFUSED_BUILDS + refused + PERSON_BUILDS_MAX)


class Ledger(object):
    """What one `choose` spent: `candidates` {setting: the most builds one pass asks for it}, `phases` {phase: builds} (None when
    `evaluate` counts no builds: a fake with no `builds` attribute), `refused` (the candidates `settle_refused` judged), `joint`
    (the `B_f` of the families judged) and `calls` (the builds `judge` asked `evaluate` for, before any cache: at most `joint`)."""

    def __init__(self, evaluate):
        self.evaluate, self.candidates, self.phases, self.refused, self.joint, self.calls = evaluate, {}, {}, 0, 0, 0
        self._last = self._builds()

    def _builds(self):
        return getattr(self.evaluate, "builds", None)

    def ask(self, name, n):
        self.candidates[name] = max(n, self.candidates.get(name, 0))

    def mark(self, phase):
        now = self._builds()
        self.phases[phase] = None if now is None else self.phases.get(phase, 0) + now - self._last
        self._last = now

    def total(self):
        return self._builds()

    def bound(self):
        return bound(sum(self.candidates.values()), self.refused)


class Member(object):
    """One tied setting in a family: its `name`, the `values` combined (default first) and the live values `cut` past
    `JOINT_VALUES_MAX`."""

    def __init__(self, name, live):
        self.name, self.values, self.cut = name, list(live[:JOINT_VALUES_MAX]), list(live[JOINT_VALUES_MAX:])


def families(names, decisions):
    """[[Member]] of the tied settings with the same `tie`, each of two or more, in the order of their first member (`names` is the
    order settings are chosen in; `decisions` {name: the last `Decision`})."""
    by_tie, order = {}, []
    for n in names:
        d = decisions.get(n)
        if d is None or getattr(d, "tie", None) is None or len(d.live or ()) < 2:
            continue
        if d.tie not in by_tie:
            by_tie[d.tie] = []
            order.append(d.tie)
        by_tie[d.tie].append(Member(n, d.live))
    return [by_tie[t] for t in order if len(by_tie[t]) > 1]


def combinations(members):
    """Every combination [(name, value)], fewest changes first (a change is a member off its first value), else in product order."""
    combos = list(itertools.product(*[[(m.name, v) for v in m.values] for m in members]))
    return [list(c) for c in sorted(combos, key=lambda c: sum(1 for i, (_n, v) in enumerate(c) if v != members[i].values[0]))]


def cost(members, deps):
    """`B_f`: the builds every combination asks for. `deps(name, value)` is the number of values of the dependent setting that
    value is scored under (1 for none); a dependent that is itself a member adds nothing (the family varies it already)."""
    names = set(m.name for m in members)
    total = 0
    for combo in combinations(members):
        each = 1
        for name, value in combo:
            each *= deps(name, value, names)
        total += each
    return total


def fit(members, spent, deps, lines):
    """Step 3: cut the family's last members until `B_f` fits the cap; returns (members kept, `B_f`) or (None, 0) when fewer than
    two are left. Each cut is printed."""
    members = list(members)
    cap = min(JOINT_FAMILY_BUILDS, JOINT_BUILDS - spent)
    while len(members) > 1:
        need = cost(members, deps)
        if need <= cap:
            return members, need
        n = 1
        for m in members:
            n *= len(m.values)
        lines.append("not judged together: %s (%d combinations would need %d builds; the cap is %d)" % (members[-1].name, n, need, cap))
        members.pop()
    return None, 0


def _subset(files, paths):
    if "*" in paths:
        return dict(files)
    return dict((p, b) for p, b in files.items() if any(p == q or (q.endswith("/") and p.startswith(q)) for q in paths))


def _pages(paths, outs, local):
    """M1 over the union: the pages one build lacks and no combination adds or removes, left out of every combination alike."""
    old = set(p for p in _subset(local, paths) if p.lower().endswith((".html", ".htm")))
    built = [set(p for p in _subset(o, paths) if p.lower().endswith((".html", ".htm"))) for o in outs]
    if not built:
        return frozenset()
    return frozenset((old - set().union(*built)) | (set.intersection(*built) - old))


def score(local, plugin, paths, drop):
    """(ok, count, pages built, the differences) of one combination on the union `paths`, as `scoring.score` reads one setting's."""
    theirs = dict((p, b) for p, b in _subset(plugin, paths).items() if p not in drop)
    res = parity_classes.classify_differences(dict((p, b) for p, b in _subset(local, paths).items() if p not in drop), theirs)
    built = frozenset(p for p in theirs if not p.startswith("site-studio/"))
    shown = [d for d in res["visible"] or () if not not_seen(d)]
    if res["verdict"] in ("EQUAL", "MARKUP-ONLY") or (not shown and res["visible"]):
        return True, 0, built, ()
    return False, len(shown) or 1, built, tuple(sorted((d.path, d.kind, tuple(d.local), tuple(d.plugin)) for d in shown))


class Verdict(object):
    """What `judge` made of one family: `winner` {name: value} (None: no combination does better), `tied` (the combinations J3
    could not separate), `refused` (J1's combinations), the winner's and the defaults' counts, and `calls` (builds asked for)."""

    def __init__(self):
        self.winner, self.tied, self.refused, self.n, self.default_n, self.calls = None, [], [], 0, 0, 0


def judge(members, build, local, paths, deps_values):
    """Steps 4 to 6 for one family. `build(values {name: value}) -> output` builds one combination under the settings the passes
    chose; `deps_values(name, value, names) -> [(dependent, value)]` the dependent values a member's value is scored under ([] for
    none). Every combination is built once; the best dependent value is taken for each, as `choose.best_score` does."""
    v = Verdict()
    names = set(m.name for m in members)
    defaults = dict((m.name, m.values[0]) for m in members)
    combos = combinations(members)
    outs = []
    for combo in combos:
        deps = [deps_values(n, val, names) for n, val in combo]
        tries = [dict(combo)]
        for options in [d for d in deps if d]:
            tries = [dict(t, **{dep: dv}) for t in tries for dep, dv in options]
        built = []
        for t in tries:
            built.append(build(t))
            v.calls += 1
        outs.append(built)
    drop = _pages(paths, [o for each in outs for o in each], local)
    scored = []                                     # [(combo, changes, (ok, n, pages, seen), refused)]
    for combo, built in zip(combos, outs):
        best = None
        for o in built:
            s = score(local, o, paths, drop)
            if best is None or (s[0], -s[1]) > (best[0][0], -best[0][1]):
                best = (s, o)
        scored.append([dict(combo), sum(1 for n, val in combo if val != defaults[n]), best[0], best[1]])
    base = scored[0]
    for row in scored[1:]:
        row[3] = bool(refusals(row[3], base[3]))
        if row[3]:
            v.refused.append(row[0])
    base[3] = False
    v.default_n = base[2][1]
    live = [r for r in scored if not r[3]]
    win = next((r for r in live if r[2][0]), None)                                                  # J2
    if win is None:
        singles = [r for r in live if r[1] == 1]
        better = [r for r in live if r[1] > 1 and r[2][2] == base[2][2] and r[2][1] < base[2][1]
                  and all(r[2][1] < s[2][1] for s in singles)]
        if better:
            least = min(r[2][1] for r in better)
            best = [r for r in better if r[2][1] == least]
            fewest = min(r[1] for r in best)
            best = [r for r in best if r[1] == fewest]
            if len(best) > 1:
                v.tied = [r[0] for r in best]
                return v
            win = best[0]                                                                           # J3
    if win is None or win[1] == 0:
        return v
    table = dict((_key(r[0]), (r[2][1], r[2][3])) for r in live)
    winner = minimal(win[0], defaults, table)
    if winner == defaults:
        return v
    v.winner, v.n = winner, table[_key(winner)][0]
    return v


def _key(values):
    return tuple(sorted(values.items(), key=lambda kv: kv[0]))


def minimal(winner, defaults, table):
    """Step 6: `winner` {name: value} with every member reverted to its default whose default leaves the same count and the same
    differences (`table` {key: (count, differences)} of the combinations built; each revert is one of them, already built). Under
    steps 4 and 5's order (fewest changes first, and the fewest changes on an equal count) a winner reaches here minimal already, so
    this is the guard that keeps it so if that order changes (`test_joint.MinimalWinner` tests it at this function)."""
    winner = dict(winner)
    moved = True
    while moved:
        moved = False
        for name in sorted(winner):
            if winner[name] == defaults[name]:
                continue
            back = table.get(_key(dict(winner, **{name: defaults[name]})))
            if back is not None and back == table[_key(winner)]:
                winner[name], moved = defaults[name], True
    return winner


def _show(value):
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _combo_text(values):
    return ", ".join("%s = %s" % (n, _show(v)) for n, v in sorted(values.items()))


def judge_families(res, names, decisions, ctx):
    """Rule J over `res` (a `choose.Chosen`) after the passes: every family that fits is judged (`judge`) and its members' rows
    written (step 7). `ctx` gives `build(values)`, `paths(name)` (the pages a setting is judged on), `deps(name, value, members)`
    (how many builds a value asks for), `deps_values(name, value, members)`, `local`, `ledger` and `Row` (the row class). Returns
    the names of the members judged (the settle pass holds them) and of those whose value moved; `ctx.ledger.joint` gains each
    family's `B_f`."""
    judged, moved, spent = [], [], 0
    for members in families(names, decisions)[:JOINT_FAMILIES]:
        for m in members:
            if m.cut:
                res.lines.append("judged together: %s: %s not combined (at most %d values a setting)"
                                 % (m.name, ", ".join(_show(c) for c in m.cut), JOINT_VALUES_MAX))
        members, need = fit(members, spent, ctx.deps, res.lines)
        if members is None:
            continue
        spent += need
        ctx.ledger.joint += need
        paths = sorted(set(p for m in members for p in ctx.paths(m.name)))
        paths = ["*"] if "*" in paths else paths
        v = judge(members, ctx.build, ctx.local, paths, ctx.deps_values)
        ctx.ledger.calls += v.calls
        judged.extend(m.name for m in members)
        for combo in v.refused:
            res.lines.append("judged together: the plugin's build refuses %s" % _combo_text(combo))
        _rows(res, members, v, paths, ctx.Row, moved)
    return judged, moved


def _rows(res, members, v, paths, row_type, moved):
    """Step 7: each member's row, and the lines that go with it."""
    where = "every page" if paths == ["*"] else ", ".join(paths)
    for m in members:
        others = ", ".join("`%s`" % o.name for o in members if o is not m)
        row = res.rows[m.name]
        if v.winner is not None and v.winner[m.name] != m.values[0]:
            reason = ("judged together with %s: together they leave %d visible difference(s) on %s (the defaults leave %d); alone it "
                      "changed nothing" % (others, v.n, where, v.default_n))
            res.rows[m.name] = row_type(m.name, v.winner[m.name], "measured", reason)
            res.lines = [l for l in res.lines if not l.startswith(("you decide: %s -- " % m.name, "partly: %s -- " % m.name))]
            res.lines.append("judged together: %s -- %s" % (m.name, reason))
            moved.append(m.name)
        elif v.tied:
            row.reason += "; judged together with %s: you decide between %s" % (others, "; ".join(_combo_text(c) for c in v.tied))
        else:
            row.reason += "; judged together with %s: no combination does better" % others
