"""Targets to review: the weekly capped list of raised companies (dashboard-redesign A moved it from
generate_dashboard.py; D2b gives it one-line rows, tick boxes and the staffing question's signals: design §8, §6.5).

THE LIST. `targets_review`'s rows, in its order and under its weekly cap (both unchanged), one line each:
`name · N open roles · raised on DATE`, each a primary row (`data-rec="net:look-into:<id>"`) with a tick box. The
rest (over the cap, snoozed) is ONE counted remainder (`data-more="targets-review:N"`). The heading says the count and
what a yes does, and how many more companies later runs will raise (case E1b).

THE STAFFING QUESTION (§8). A listed row gets it only when the classification is thin: `company_kind` said
`employer` by `default`, AND signal T1 or T2. The loader decides it (`pd.targets_ask`) with the two pure signals here:
  T1 `t1(types, owned)`: every sighting of every open role came through a channel of type `aggregator` or `recruiter`
     (`types` holds one channel type per sighting, None when unknown), and no role links an employer-owned posting;
  T2 `t2(titles)`: more than `T2_ROLES` open roles in `T2_FAMILIES` or more title families (`title_family`).
UNDETERMINED (§8): whether T1 and T2 catch real staffing firms; a wrong guess costs one "No". English titles only: a
title `title_family` cannot reduce gives NO signal (it is not counted), so no question is asked on its account.

THE ACTIONS (§6.5). One `data-pick-group` for the list with Yes (`target-yes`, a route: the skill asks the
motivation, dev #960), No and Later. "These are staffing firms" is a nested group, present only when a listed row has
the question, holding one box per such row. The excluded companies are one counted, closed fold
(`name — staffing (by its name)`) of at most `caps.LEVEL2` rows, the rest one count line inside it (design §4, every
fold; dashboard-redesign E: it grew with the data, 60 rows at busy scale 10); only a rule-3 (`how == "name"`)
exclusion carries a tick box, under one button, "These are employers", whose tail counts the boxed ones past the fold. Python writes every character of a prompt: the loader fills `pd.targets_text`
(`{"heads": {action: head}, "lines": {company id: record line}, "tail": tail}`); this module only places them."""
import re

from dashboard import caps
from dashboard.action_block import tail
from dashboard.actions_ui import group_attr, group_button, pick
from dashboard.markup import _rec_attrs, esc, plain, theirs


TARGETS_SECTION = "phase-targets"
TARGETS_ANCHOR = "today-src-targets"
STAFFING_CHANNELS = ("aggregator", "recruiter")
T2_ROLES, T2_FAMILIES = 8, 3            # constants with no measurement behind them (§8, stated)
SENIORITY = ("senior", "sr", "junior", "jr", "lead", "principal", "staff", "head", "chief", "associate", "assistant",
             "intern", "internship", "trainee", "apprentice", "entry", "level", "mid", "graduate", "grad", "vp", "vice",
             "president", "executive", "i", "ii", "iii", "iv", "v", "1", "2", "3", "4", "5")
HOW = {"stated": "you said so", "channel": "by its channel", "name": "by its name"}
LISTED_ACTIONS = (("target-yes", "Yes"), ("target-no", "No"), ("target-later", "Later"))


def title_family(title):
    """A title's family: the title with qualifiers (after a comma, a dash, a bracket or `-`) and seniority words
    removed, cut to its head noun (its last word; for `X of Y`, X's, or Y's when X is only seniority). None when
    nothing is left: such a title gives no signal. Pure; English only (§8, stated)."""
    t = re.split(r"[,(\[|/]| - | – | — ", str(title or "").casefold())[0]
    parts = [[w for w in re.findall(r"[^\W\d_]+|\d+", p) if w not in SENIORITY] for p in t.split(" of ", 1)]
    words = parts[0] or (parts[1] if len(parts) > 1 else [])
    return words[-1] if words and len(words[-1]) > 1 else None


def t1(types, owned):
    """T1: there is a sighting, every one came through an aggregator or recruiter channel, and no role links an
    employer-owned posting."""
    types = list(types)
    return bool(types) and all(t in STAFFING_CHANNELS for t in types) and not owned


def t2(titles):
    """T2: more than T2_ROLES open roles whose titles reduce to a family, in T2_FAMILIES or more families."""
    fams = [f for f in (title_family(t) for t in titles) if f]
    return len(fams) > T2_ROLES and len(set(fams)) >= T2_FAMILIES


def ask_ids(listed, facts):
    """The ids of the listed companies that get the staffing question, in list order. `facts` is
    `{company id: (kind, how, sighting types, employer-owned)}`, the loader's reading of `company_kind`, the open
    roles' sightings and `role_link`; the titles are the item's own. Kind `employer` by `default`, AND T1 or T2."""
    out = []
    for it in listed:
        kind, how, types, owned = facts.get(it["id"]) or (None, None, (), False)
        if (kind, how) == ("employer", "default") and (t1(types, owned) or t2(it.get("titles") or [])):
            out.append(it["id"])
    return tuple(out)


def _n(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def _heading_words(n_listed, pd):
    held = (pd.today_counts or {}).get("held_listed") or 0
    words = ("%s: %s wait on your yes or no." % (_n(n_listed, "company", "companies"),
                                                 _n(held, "unread role", "unread roles"))
             if held else "%s wait%s on your yes or no." % (_n(n_listed, "company", "companies"),
                                                             "s" if n_listed == 1 else ""))
    words += " Yes lets the next run read that company's roles."
    if pd.targets_not_raised:
        words += " %d more will be raised by later runs." % pd.targets_not_raised
    return words


def _row(it, r, line, ask):
    roles = it.get("roles") or 0
    bits = [_n(roles, "open role", "open roles")] + (["raised on %s" % it["raised_on"]] if it.get("raised_on") else [])
    return ('<div class="net-row net-line"%s data-subject="company:%s">%s<strong>%s</strong> <span class="sub">'
            '&middot; %s</span>%s</div>'
            % (_rec_attrs(r["key"]), esc(it["id"]), pick(r["actions"][0]["rec_id"], line, it["name"]) if line else "",
               theirs(it["name"], "company-name"), esc(" · ".join(bits)),
               ' <span class="sub">may be a staffing firm</span>' if ask else ""))


def _staffing(shown, ask, text):
    """The nested group for the rows with the question: one box each and the one button."""
    rows = [it for it in shown if it["id"] in ask and text["lines"].get(it["id"])]
    if not rows:
        return ""
    return ('<div class="net-staffing"%s><div class="sub">Could these be staffing firms?</div>%s<div class="net-actions">'
            '%s</div></div>' % (group_attr("targets-staffing"),
                                "".join('<div class="net-line">%s%s</div>' % (pick("company:%s" % it["id"],
                                                                                   text["lines"][it["id"]], it["name"]),
                                                                              theirs(it["name"], "company-name"))
                                        for it in rows),
                                group_button("These are staffing firms", text["heads"]["company-kind-staffing"], "",
                                             len(rows))))


def _excluded(excluded, text):
    """The excluded companies: ONE counted, closed fold; a box and the one button only for a rule-3 exclusion."""
    if not excluded:
        return ""
    shown, rest = excluded[:caps.LEVEL2], excluded[caps.LEVEL2:]
    lines, boxed = [], 0
    for e in shown:
        line = text["lines"].get(e["id"]) if e.get("how") == "name" else None
        boxed += bool(line)
        lines.append('<div class="net-line net-excluded" data-subject="company:%s">%s%s <span class="sub">&mdash; %s '
                     '(%s)</span></div>' % (esc(e["id"]), pick("company:%s" % e["id"], line, e["name"]) if line else "",
                                            theirs(e["name"], "company-name"), esc(e["kind"]),
                                            esc(HOW.get(e.get("how"), e.get("how") or ""))))
    if rest:
        lines.append('<div class="sub ws-more">+ %d more that %s not on this page. To see them, say to the coordinator: '
                     'Show me every excluded company.</div>' % (len(rest), "is" if len(rest) == 1 else "are"))
    more = sum(1 for e in rest if e.get("how") == "name" and text["lines"].get(e["id"]))
    button = ('<div class="net-actions">%s</div>' % group_button("These are employers",
                                                                 text["heads"]["company-kind-employer"], tail(more),
                                                                 boxed)
              if boxed else "")
    return ('<details class="net-fold"%s><summary>%s excluded as aggregator or staffing</summary>%s%s</details>'
            % (group_attr("targets-excluded"), len(excluded), "".join(lines), button))


def render_targets_list(tr, net_rows, ledger, pd):
    """The weekly "Targets to review" list (dev #915 C7; the module docstring). Returns `(html, n_listed)`;
    `("", None)` when there is nothing to review. `ledger` is the render's `Ledger`; `pd.targets_text`,
    `pd.targets_ask` and `pd.targets_not_raised` are the loader's."""
    if not tr or not (tr["rows"] or tr["waiting"] or tr["snoozed"] or tr["excluded"]):
        return "", None
    by_cid = {r["key"].split(":", 2)[2]: r for r in (net_rows or []) if r["group"] == "look-into"}
    shown = [it for it in tr["rows"] if it["id"] in by_cid]
    rest = [it for it in tr["waiting"] + tr["snoozed"] if it["id"] in by_cid]
    ledger.cover_set("targets-review", [by_cid[it["id"]]["key"] for it in shown], [by_cid[it["id"]]["key"] for it in rest])
    text = pd.targets_text or {"heads": {}, "lines": {}, "tail": ""}
    ask = set(pd.targets_ask or ())
    rows = "".join(_row(it, by_cid[it["id"]], text["lines"].get(it["id"]), it["id"] in ask) for it in shown)
    buttons = "".join(group_button(label, text["heads"][action], text.get("tail") or "", len(shown))
                      for action, label in LISTED_ACTIONS) if shown and text["lines"] else ""
    out = ['<div class="net-group"%s>%s%s%s</div>'
           % (group_attr("targets"), rows, ('<div class="net-actions">%s</div>' % buttons) if buttons else "",
              _staffing(shown, ask, text))]
    foot = []
    if tr["waiting"]:
        foot.append("%d more waiting" % len(tr["waiting"]))
    if tr["snoozed"]:
        foot.append("%d snoozed until next week" % len(tr["snoozed"]))
    if foot:
        out.append('<div class="sub ws-more"%s>%s &middot; the weekly list shows at most %d</div>'
                   % ((' data-more="targets-review:%d"' % len(rest)) if rest else "", esc(" · ".join(foot)),
                      tr["per_week"]))
    out.append(_excluded(tr["excluded"], text))
    return ('<h2 id="%s">&#127919; Targets to review <span class="tcount">%d</span></h2>'
            '<div class="sub" id="%s" style="margin:-6px 0 10px">%s Aggregators and staffing firms are never listed '
            'as targets.</div><div class="card">%s</div>'
            % (TARGETS_SECTION, len(shown), TARGETS_ANCHOR, esc(_heading_words(len(shown), pd)), "".join(out))), len(shown)


def render_targets_failed(failed, lost):
    """The Targets section when its list could not be computed (cut from `main`, dashboard-redesign A): the
    failure, said, and the raised companies counted in one remainder line, never lost. The loader places
    `lost` in the ledger's `targets-review` remainder."""
    return ('<h2 id="%s">&#127919; Targets to review</h2><div class="note">&#9940; <strong>The targets list '
            'could not be computed</strong> (%s): what is waiting here is UNKNOWN, not zero.</div>'
            '<div class="sub ws-more"%s>%d raised compan%s waiting.</div>'
            % (TARGETS_SECTION, esc(plain(failed)),
               (' data-more="targets-review:%d"' % len(lost)) if lost else "", len(lost),
               "y" if len(lost) == 1 else "ies"))
