"""The role lists (dashboard-redesign A, moved from generate_dashboard.py): Opportunities to pursue, Needs
your read, Applications to finish, Roles to reconsider. Each has three levels since D2 (design §4): full rows open,
one-line rows in one closed fold, then a counted line."""
import html

from dashboard import caps, levels
from dashboard.actions_ui import group_attr
from dashboard.markup import esc, plain
from dashboard.role_cards import STAGES, _days_since, render_opportunity_card, render_role_line


# The fixed shape of render_opportunity_list's counts dict — see dev #80 in that function's
# docstring for why this has to be a single shared constant rather than two literals. `open` is the level-1 count.
_EMPTY_OPP_COUNTS = {"all": 0, "you": 0, "applied": 0, "person": 0, "nothing": 0, "open": 0}


# Each role list: (its level-1 cap, the section Today names it by (`dashboard.rank`), its anchor, the noun of its
# count line). The set name is the list's ledger set and its tick-box group.
LISTS = {
    "opportunities": (caps.OPPS_L1, "opps", "today-src-opportunities", "roles to decide"),
    "needs-read": (caps.NEEDS_READ_L1, "read", "today-src-needs-read", "roles only you can read"),
    "applying-finish": (caps.APPS_L1, "apply", "today-src-applications", "applications to finish"),
}


def render_opportunity_list(opps, companies, facts, ledger, pd, attention=None, owner=None, pursuit=None,
                            roles=None, set_name="opportunities", warm=None, posting=None, stages=None):
    """One row per LIVE role — needs-you first, then yours, then the run's — in THREE LEVELS (design §4, D2): the
    list's level-1 cap of full cards (`LISTS`; the roles Today took from this list first, `levels.split`), then up to
    `caps.LEVEL2` one-line rows in ONE closed fold, then a counted line naming the sentence that shows the rest. Closed
    roles are not here — they are not opportunities. The card's tick box and the list's ONE `work-through` button sit
    inside the list's group element (`data-pick-group="<set_name>"`).

    ⭐ public #54 — a trimmed row is first a REAL row one click away. 0.37.0 trimmed this list into a "+K more" no
    reader could reach; the filtered list that replaced it rendered every row. With the chips retired (D-6), a row past
    level 1 is a level-2 primary row (`data-rec`, its id, links land), and only past 20 is it a count, in the ledger's
    remainder (`data-more="<set_name>:N"`), with the way to it on the line.

    The reading order is whose move it is (ATTENTION's needs-you, then OWNER's you, then the run's), then DAYS SINCE
    ANYTHING LAST HAPPENED (stalest first; an unknown age after every known one, never invented as zero), dev #494 /
    #540. `attention`, `owner`, `pursuit` ({opp id: pursuit_state dict}), `roles`, `stages`, `posting` and `warm` are
    the loader's maps; `facts` (keyed by `id(role)`) each live role's link, bucket, play step and lean. Each row carries
    `data-pursuit` (its partition token), `data-pursuit-also` (the cross-cuts it is in: `your-move`, `decide`) and
    `data-owner`.

    ⭐ dev #80 — the counts dict has a FIXED shape (`_EMPTY_OPP_COUNTS`), shared by the empty and populated returns.
    `all` counts every live role (the jump bar's and the heading's whole count), `open` the level-1 rows.

    Returns (html, counts)."""
    attention = attention or {}
    live = [o for o in opps if o.get("status") not in pd.terminal_statuses]
    for o in opps:
        if o.get("status") in pd.terminal_statuses and o.get("id"):
            ledger.cover("opp:%s" % o["id"], "terminal", set_name)
    if not live:
        return '<div class="sub">No live opportunities.</div>', dict(_EMPTY_OPP_COUNTS)
    order = {"active-pursuit": 0, "needs-resolution": 1, "in-motion": 2, "backlog": 3}
    today = pd.now.date()

    def key(o):
        oid = o.get("id")
        tier = (0 if attention.get(oid) == "needs-you"
                else 1 if owner.get(oid) == "you" else 2)
        days = _days_since((pursuit.get(oid) or {}).get("last_activity_on"), today)
        return (tier, 0 if days is not None else 1, -(days or 0),
                order.get(o.get("status"), 9),
                -(STAGES.index(o["stage"]) if o.get("stage") in STAGES else -1),
                str(oid or ""))

    l1, section, anchor, noun = LISTS.get(set_name, (caps.OPPS_L1, None, None, "roles"))
    counts = dict(_EMPTY_OPP_COUNTS)
    ranked = sorted(live, key=key)
    open_, folded, rest = levels.split(ranked, l1, pd, section, key=lambda o: "opp:%s" % (o.get("id") or ""))
    cards, lines = [], []
    for o in ranked:
        f = facts[id(o)]
        waits = owner.get(o.get("id")) == "you"
        counts["all"] += 1
        counts[f["bucket"]] += 1
        if waits:
            counts["you"] += 1
    for level, group in ((1, open_), (2, folded)):
        for o in group:
            f = facts[id(o)]
            comp = companies.get(o.get("company_id"), {})
            _key = "opp:%s" % (o.get("id") or "")
            _p = pursuit.get(o.get("id")) or {"state": "unclassifiable", "missing": "pursuit"}
            dims = {"pursuit": _p["state"], "owner": owner.get(o.get("id"))}
            also = [cc for cc, on in (("your-move", attention.get(o.get("id")) == "needs-you"),
                                      ("decide", roles.get(o.get("id")) == "decide")) if on]
            if also:
                dims["pursuit-also"] = " ".join(also)
            box = levels.row_pick(pd, _key, str(o.get("title") or o.get("id")), level)
            if level == 1:
                cards.append(render_opportunity_card(
                    o, comp, f, _key, _p, dims, owner.get(o.get("id")) == "you", roles.get(o.get("id")),
                    stages.get(o.get("id")), posting.get(o.get("id")), (warm or {}).get(o.get("id")), pd,
                    pick_html=box))
            else:
                lines.append(render_role_line(o, comp, _key, _p, dims, f["link"][0], box))
    counts["open"] = len(open_)
    ledger.cover_set(set_name, ["opp:%s" % o["id"] for o in open_ + folded if o.get("id")],
                     ["opp:%s" % o["id"] for o in rest if o.get("id")])
    body = (levels.group_button(pd, "Work through", len(open_), len(rest))
            + '<div class="card opp-list">%s%s</div>' % ("".join(cards),
                                                         levels.fold("%d more, one line each" % len(lines),
                                                                     "".join(lines)))
            + levels.more_line(set_name, len(rest), noun, "Show me every one of my %s." % noun))
    return '<div%s%s>%s</div>' % (group_attr(set_name), (' id="%s"' % anchor) if anchor else "", body), counts


READ_SECTION = "phase-needs-read"


RESCREEN_SECTION = "phase-rescreen-flags"


def _flag_html(f, companies, full):
    co = (companies.get(f.get("company_id")) or {}).get("name") or f.get("company_id") or "?"
    attr = html.escape("rescreen:%s" % f["id"], quote=True)
    if not full:
        return ('<div class="rsflag" data-flag="%s"><span class="rs-title">%s: %s</span> <span class="sub">%s, '
                'was %s</span></div>' % (attr, esc(co), esc(f.get("title") or ""), esc(f.get("new_verdict") or ""),
                                         esc(f.get("old_verdict") or "")))
    return ('<div class="rsflag" data-flag="%s">'
            '<div class="rs-title">%s: %s <span class="sub">(%s)</span></div>'
            '<div class="rs-line">Stored verdict <code>%s</code>; jobsearch 0.73.0 would give '
            '<code>%s</code> (%s).</div>'
            '<div class="rs-line sub">Why: %s</div>'
            '<div class="rs-act">To reopen: %s</div></div>'
            % (attr, esc(co), esc(f.get("title") or ""),
               esc(f.get("status") or ""), esc(f.get("old_verdict") or ""), esc(f.get("new_verdict") or ""),
               esc(f.get("new_comp") or ""), esc(plain(f.get("why") or "")),
               esc(plain(f.get("action_plain") or "nothing to reopen"))))


def render_rescreen_flags(flags, unreadable, failed, companies, ledger=None):
    """The fourth, CONDITIONAL section of the review-now page (jobsearch 0.74.0, dev #761; owner decision
    2026-10-23: FLAG, NEVER REOPEN): the roles whose stored comp removal 0.73.0 would not repeat, each ONCE,
    with the old verdict, the new one and why, and the one-step action the candidate takes. Returns
    `(html, n)`; `("", 0)` when there is nothing to say. Three levels (design §4): `caps.RECONSIDER_L1` full flags,
    one-line flags in one closed fold, then a counted line (`data-more="rescreen-flags:N"`, its count placed in
    `ledger.remainders`). READ-ONLY by design (dev #761): no tick box and no button.

    ⭐ A flag entry is NOT an opportunity row. A removed role is `passed`, a TERMINAL status, and
    `check_dashboard_coverage.py`'s SCOPE refuses a terminal opportunity rendered as a row (`data-rec`),
    so a flag carries `data-flag="rescreen:<id>"` -- which that check's row, reference and ledger scans do
    not read -- and the role stays ledgered `terminal`. The page never silently exempts a terminal row.
    ⛔ Nothing here writes: the page draws what `profile.comp_rescreen_flags` decided; only the candidate's
    own `record.py decide` / `record.py screened` ends a flag.

    `failed` (an exception text) and `unreadable` (ids whose re-run raised) are SAID on the page: a
    flag that could not be computed must never read as no flag."""
    if not flags and not unreadable and not failed:
        return "", 0
    open_, folded, rest = caps.levels(flags, caps.RECONSIDER_L1, key=lambda f: f.get("id"))
    if rest and ledger is not None:
        ledger.remainders["rescreen-flags"] = len(rest)
    parts = [_flag_html(f, companies, True) for f in open_]
    parts.append(levels.fold("%d more, one line each" % len(folded),
                             "".join(_flag_html(f, companies, False) for f in folded)))
    parts.append(levels.more_line("rescreen-flags", len(rest), "roles to reconsider",
                                  "Show me every role flagged to reconsider."))
    notes = []
    if failed:
        notes.append('<div class="note">&#9940; <strong>The re-screen check failed</strong> (%s): whether '
                     'any removed role would now be screened differently is UNKNOWN, not zero.</div>'
                     % esc(failed))
    if unreadable:
        notes.append('<div class="note">&#9940; <strong>Not checked:</strong> %d role%s could not be '
                     're-screened (%s).</div>'
                     % (len(unreadable), "" if len(unreadable) == 1 else "s",
                        esc(", ".join(str(u) for u in unreadable))))
    n = len(flags)
    return (
        '<h2 id="%s">&#8617;&#65039; Roles to reconsider <span class="tcount">%d</span>%s</h2>'
        '<div class="sub" style="margin:-6px 0 10px">Stored <strong>comp removals</strong> that '
        'jobsearch 0.73.0 would not repeat. <strong>Nothing was changed</strong>: tell Claude to reopen or '
        'dismiss a role, which ends its flag.</div>%s%s'
        % (RESCREEN_SECTION, n, levels.showing(len(open_), n) if n else "", "".join(notes),
           '<div class="card">%s</div>' % "".join(parts) if flags else "")), n


def render_opportunities_section(list_html, n, n_open=None):
    """The `Opportunities to pursue` section around its role list (cut from `main`, dashboard-redesign A). `n` is the
    whole count (the coverage gate's PURSUE COUNT reads it from the `tcount` right after the heading text), `n_open`
    the level-1 rows."""
    return ('<h2 id="phase-pipeline-roles">🎯 Opportunities to pursue '
            '<span class="tcount">%d</span>%s</h2>'
            '<div class="sub" style="margin:-6px 0 10px">Roles where a <strong>decision is '
            'owed</strong>: pursue or pass, on a role that is read and screened. A role you are pursuing is under '
            'Applications to finish.</div>'
            % (n, levels.showing(n if n_open is None else n_open, n)) + list_html)


def render_read_section(list_html, n, n_open=None):
    """The `Needs your read` section (dev #820 / public #175, N9) around its role list (cut from `main`)."""
    return ('<h2 id="%s">&#128065; Needs your read <span class="tcount">%d</span>%s</h2>'
            '<div class="sub" style="margin:-6px 0 10px">Postings only <strong>you</strong> can '
            'open: a board that needs your login, a role with no posting address, a page behind a '
            'wall. Read it, then record what it says; the next run screens it.</div>'
            % (READ_SECTION, n, levels.showing(n if n_open is None else n_open, n)) + list_html)


def render_applications_section(todo, covers, n_letters_used, n_letters_moot):
    """`(html, n)`: the `Applications to finish` section (cut from `main`, dashboard-redesign A): the roles
    pursued with nothing sent (`todo` = `(list_html, counts)`, or None) and their cover letters (`covers` =
    `(list_html, n_listed, n_open)`, or None: the three groups of `drafts.render_message_groups`), with the
    cover-letter store's cascade note (public #95). `("", 0)` when there is neither. `n` is the whole count."""
    n_apply, n_open = 0, 0
    _apply_parts = []
    if todo is not None:
        todo_html, todo_counts = todo
        n_apply += todo_counts["all"]
        n_open += todo_counts["open"]
        _apply_parts.append(todo_html)
    if covers is not None:
        covers_html, n_listed, n_covers_open = covers
        # public #95 — the data-store side of the cascade, reported once, plainly.
        _cascade_note = ""
        if n_letters_moot or n_letters_used:
            _bits = []
            if n_letters_used:
                _bits.append("%d used (an application already carries it)" % n_letters_used)
            if n_letters_moot:
                _bits.append("%d moot (its pursuit has ended)" % n_letters_moot)
            _cascade_note = ('<div class="sub" style="margin:6px 0 0">data/cover_letters.'
                             'jsonl: %s — public #95</div>' % "; ".join(_bits))
        n_apply += n_listed
        n_open += n_covers_open
        _apply_parts.append(
            '<h3 id="phase-outreach-covers">📄 Cover letters — for applications you submit '
            'yourself <span class="tcount">%d</span>%s</h3>'
            '<div class="sub" style="margin:-6px 0 10px">Every claim traces to the claim '
            'union (presence/claims.md). A held letter waits on a precondition; do not submit it yet.</div>'
            '<div class="card"%s>%s</div>%s'
            % (n_listed, levels.showing(n_covers_open, n_listed), group_attr("covers"), covers_html, _cascade_note))
    if not _apply_parts:
        return "", n_apply
    return ('<h2 id="phase-applying-finish">📝 Applications to finish '
            '<span class="tcount">%d</span>%s</h2>'
            '<div class="sub" style="margin:-6px 0 10px">Roles you are pursuing that have no '
            'application out yet, and the cover letters you will paste into them.</div>'
            % (n_apply, levels.showing(n_open, n_apply)) + "".join(_apply_parts)), n_apply
