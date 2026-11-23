"""Roles waiting on a company decision: the held count, its change since last week, and the held roles that match the
candidate's titles, role first (jobsearch 0.92.0, dev #1005, #950, #1002; docs/design-decision-surface.md §C, § Rendering,
review round 2 G3 and G6).

THE SECTION (`phase-held-roles`, after Targets). A role is held (`lifecycle` stage `held-for-company`) while its company waits
on the candidate: `undecided`, `watching` or `passed` (`reach.held_roles`).

    Roles waiting on a company decision  N
    {total} held · {u} at companies not yet decided · {w} at companies you are watching · {p} at companies you passed on · {change}
    [ ] {title} {company} {chip} · first seen {date} · {why} · JD

- The count line carries `data-held="{total}"`, the OPPORTUNITIES held (G3), and `data-held-items="{n}"`, the capture items
  the lifecycle also holds that are not roles yet, named as their own remainder (`N feed items not yet roles`), so
  `process_report().held_for_company` = total + items (the coverage gate's HELD COUNT UNEXPLAINED). A zero term is not printed.
- `{change}` is `+K | -K | no change since {date}` against `held_roles.baseline`, else one of the four states of
  `held_roles.count_state` (G6, H5): counting since {date} · the last run did not record a held count · no count recorded: an
  update step is pending · no count from a week ago yet.
- The rows are `held_roles.listing`'s (`undecided` and `watching` companies, a matching title; `passed` is counted, never
  listed), each a `role_cards.render_role_line` primary row (`data-rec="opp:<id>"`), in three levels (`caps.HELD_L1` open, one
  closed fold of `caps.LEVEL2`, then `data-more="held-roles:N"`), ledgered in set `held-roles`. The first row of each company
  carries the company's tick box (`company:<id>`, action `target-yes`) under one button, `Copy the "Target these companies"
  request for N`. With no target titles configured nothing is listed and the line says so (`data-held-list="unmatched"`).
- The caps, in order, are one line in a closed fold (the page word budget): a run raises at most {a} new companies · Targets lists at most {b} a week · a run reads at
  most {c} companies (`search.companies_raised_per_run` raises, dev #1021; `search.company_intake_per_run` admits;
  `network.targets_per_week` lists).

`listed_count` is the Targets heading's "N unread roles" (moved from `generate_dashboard._load_today`, unedited in meaning).
`load` reads the journal and the pin (the profile's own files); `render` is pure. Python 3.9+, standard library only."""
import config_keys as _ck
from dashboard import caps
from dashboard.action_block import head, record_line, tail
from dashboard.actions_ui import group_attr, group_button, pick
from dashboard.levels import fold, more_line
from dashboard.markup import esc
from dashboard.role_cards import render_role_line
from journaling.journal_file import pin_scan, read
from reach import held_roles

HELD_SECTION = "phase-held-roles"
HELD_SET = "held-roles"
PIN = (0, 92, 0)
ACTION = "target-yes"
BUTTON = 'the "Target these companies" request'
WHY_TEXT = {"undecided": "you have not decided about this company", "watching": "you are watching this company"}
COUNT_TEXT = {"undecided": "at companies not yet decided", "watching": "at companies you are watching",
              "passed": "at companies you passed on"}
STATE_TEXT = {"counting": "counting since %s", "unrecorded": "the last run did not record a held count",
              "pending": "no count recorded: an update step is pending", "none": "no count from a week ago yet",
              "unread": "no count: the run journal could not be read"}
UNMATCHED = "They cannot be matched to your titles: no target titles are configured."
NONE_MATCH = "None of them matches your titles."


def listed_count(live, listed, stages):
    """How many live roles at the companies Targets lists are held `undecided` (the Targets heading's "N unread roles")."""
    return sum(1 for o in live if o.get("company_id") in listed
               and getattr(stages.get(o.get("id")), "name", None) == held_roles.HELD
               and getattr(stages.get(o.get("id")), "detail", None) == "undecided")


def _pinned(root):
    pin = pin_scan(root)
    try:
        return pin is not None and tuple(int(x) for x in pin.split(".")) >= PIN
    except ValueError:
        return False


def load(root, opps, stages, companies, rep, matcher, first_seen, today, per_week):
    """The section's facts, or None when the lifecycle report is absent (the page says PIPELINE NOT CHECKED elsewhere).
    `stages` is `{opp id: Stage}`, `companies` `{id: row}`, `rep` `process_report`'s, `matcher` `(profile.title_matches, config)`,
    `first_seen(opp)` a date, `today` a date, `per_week` the Targets cap. The other two caps are `rep.intake`."""
    if rep is None:
        return None
    counts = held_roles.held_counts(stages.values())
    total = sum(counts.values())
    try:
        state = held_roles.count_state(read(root), today, _pinned(root))
    except Exception:                                            # noqa: BLE001 - said on the page, never a crash
        state = ("unread", None, None)
    if state[0] == "since":
        diff = total - state[2]
        state = ("since", "%s since %s" % ("%+d" % diff if diff else "no change", state[1]), None)
    return {"counts": counts, "total": total, "items": max(rep.held_for_company - total, 0), "state": state,
            "listing": held_roles.listing(opps, stages, companies, held_roles.title_matcher(*matcher), first_seen),
            "caps": (_raises(matcher[1], rep.intake), per_week, rep.intake)}


def _raises(cfg, intake):
    """`search.companies_raised_per_run` (dev #1021): absent, it reads the intake key. A bad value is refused loudly by
    `record.py raise-companies`; the page then shows the intake figure, which is what the key reads when absent."""
    try:
        return _ck.resolve_int(cfg or {}, _ck.SEARCH_COMPANIES_RAISED_PER_RUN)
    except ValueError:
        return intake


def _count_line(h):
    bits = ["%d held" % h["total"]] + ["%d %s" % (h["counts"][k], COUNT_TEXT[k]) for k in held_roles.WHY if h["counts"][k]]
    name, date, _ = h["state"]
    bits.append(date if name == "since" else (STATE_TEXT[name] % date if name == "counting" else STATE_TEXT[name]))
    if h["items"]:
        bits.append("%d feed item%s not yet roles" % (h["items"], "" if h["items"] == 1 else "s"))
    return ('<div class="sub" id="held-count" data-held="%d" data-held-items="%d">%s</div>'
            % (h["total"], h["items"], esc(" · ".join(bits))))


def _rows(rows, ledger):
    """The three levels, each company's first row boxed: `(html, n level-1 boxes, companies only past the page)`."""
    shown, folded, rest = caps.levels(rows, caps.HELD_L1, caps.LEVEL2, key=lambda r: r["id"])
    ledger.cover_set(HELD_SET, ["opp:%s" % r["id"] for r in shown + folded], ["opp:%s" % r["id"] for r in rest])
    boxed, n_open, out = set(), 0, {1: [], 2: []}
    for level, part in ((1, shown), (2, folded)):
        for r in part:
            cid, box = r["company_id"], ""
            if cid and cid not in boxed:
                boxed.add(cid)
                n_open += level == 1
                box = pick("company:%s" % cid, record_line("company:%s" % cid, r["company"]), r["company"], level=level)
            line = render_role_line(r["opp"], {"name": r["company"]}, "opp:%s" % r["id"],
                                    {"state": held_roles.HELD, "cell": r["why"]}, {}, r.get("link"), box)
            extra = " · ".join(b for b in ("first seen %s" % r["first_seen"] if r["first_seen"] else "",
                                           WHY_TEXT[r["why"]]) if b)
            out[level].append('%s <span class="sub">&middot; %s</span></div>' % (line[:-len("</div>")], esc(extra)))
    more = len({r["company_id"] for r in rest if r["company_id"]} - boxed)
    html = "".join(out[1]) + fold("%d more held roles" % len(folded), "".join(out[2]))
    return html + more_line(HELD_SET, len(rest), "held roles", "Show me every held role."), n_open, more


def render(h, ledger, link_of):
    """The section's html ("" when nothing is held or `h` is None). `link_of(opp)` is the posting link (`role_link(o)[0]`)."""
    if not h or not (h["total"] or h["items"]):
        return ""
    lst = h["listing"]
    a, b, c = h["caps"]
    body = [_count_line(h), '<details class="sub held-caps"><summary>The caps</summary>Caps, in order: a run raises at most %d '
                            'new companies · Targets lists at most %d a week · a run reads at most %d companies.</details>'
            % (a, b, c)]
    n_rows = 0
    if lst["unmatched"]:
        body.append('<div class="sub" data-held-list="unmatched">%s</div>' % esc(UNMATCHED))
    elif not lst["rows"]:
        body.append('<div class="sub">%s</div>' % esc(NONE_MATCH))
    else:
        rows = [dict(r, link=link_of(r["opp"])) for r in lst["rows"]]
        n_rows = len(rows)
        html, n_open, more = _rows(rows, ledger)
        button = ('<div class="net-actions">%s</div>' % group_button(BUTTON, head(ACTION), tail(more), n_open)
                  if n_open else "")
        body.append('<div class="card"%s>%s%s</div>' % (group_attr(HELD_SET), html, button))
    return ('<h2 id="%s">&#9208;&#65039; Roles waiting on a company decision <span class="tcount">%d</span></h2>%s'
            % (HELD_SECTION, n_rows, "".join(body)))
