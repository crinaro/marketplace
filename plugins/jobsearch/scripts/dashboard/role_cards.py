"""One role's card (dashboard-redesign A, moved from generate_dashboard.py): fit, touches, lean, warm path,
posting line, pursuit chip, stage rail, comp and location, and `render_opportunity_card`, the card cut from
the role list."""
import datetime
import re

from dashboard.markup import _rec_attrs, esc, md_inline, theirs


# The pursuit chip's words, one per `your_move.PURSUIT_STATES` value (moved from the retired filter chips' table,
# dashboard-redesign D2, D-6): the row's own chip still reads them. A state with no entry prints its token.
PURSUIT_LABELS = {
    "your-move": "Your move — today",
    "decide": "Decide — pursue/pass owed",
    "your-read": "Your read — only you can open the posting",
    "process-failure": "Process failure — a run did not finish these",
    "waiting-intake": "Waiting for intake — no run has taken these on",
    "in-progress": "In progress — a run has these open",
    "removed": "Screened out",
    "gone": "Posting gone",
    "held-for-company": "Held — the company comes first",    # dev #899
    "folded": "Folded — a duplicate of another role",        # dev #899
    "new": "New — pursue or pass?",
    "conversation": "In live conversation",
    "sent": "Sent — awaiting a reply",
    "not-sent": "Not sent yet — queued to apply",
    "interviews": "In interviews",
    "parked": "Parked",
    "ended": "Ended",
    "unclassifiable": "Unclassifiable — a field is missing",
}


def _dim_attrs(dims):
    """The row's `data-owner`, `data-pursuit` and `data-pursuit-also` attributes, in a fixed order: whose move it
    is, the role's pursuit partition token and its cross-cuts (no chip reads them since D-6; readers of the page and
    its tests do)."""
    return "".join(' data-%s="%s"' % (esc(d), esc(str(v))) for d, v in sorted(dims.items()) if v is not None)


# ⭐ `next_action` IS NOT A SHORT IMPERATIVE — measured, not assumed. On the live pipeline all 35
# live roles carrying one are over 120 chars: median 419, max 1052. They are recommendation
# memos ("YOUR CALL, recommend PASS - act by ... Three independent reasons ..."). Rendering
# them in full put a wall of text in the action colour on every row and destroyed the scan the
# row layout exists for. The FIRST clause is the valuable part — it carries the verdict and the
# act-by date — so the row shows that and the rest lives under Detail.
OPP_ACTION_CLAMP = 110


# ─────────────────────────────────────────────────────────────────────────────
# THE OPPORTUNITY ROW — one role, one place.
#
# ⭐⭐ WHY THIS REPLACED FIVE SECTIONS (2026-08-10).
#
# The Opportunities tab used to render the same roles five times: a JD-fit register, three
# application buckets (submitted / in play through a person / nothing sent), a focus-areas list
# and a sourced-pipeline table. Measured against the live pipeline: **every one of the 46 live
# roles appeared in at least two of those sections, 16 appeared in four, and not one appeared in
# exactly one.** Answering "where does this role stand" meant reading four tables and joining
# them by company name in your head.
#
# The cause was not too much content. It was that the tab was organised by ATTRIBUTE — fit,
# application state, focus, source — while the reader's unit of thought is the ROLE.
#
# ⭐ THE FIX IS STRUCTURAL, NOT COSMETIC. Bucket membership becomes a POSITION rather than a
# table you are listed in. `stage` already exists on every record, so the rail below shows where
# a role actually is; the three application buckets become a filter over one list instead of
# three copies of it. A status CHIP would not have done this — a chip shows state but not
# progression, and it would have left all four tables standing.
#
# Everything the old sections showed is still here. Each fact now appears once.
# ─────────────────────────────────────────────────────────────────────────────

STAGES = ("sourced", "contacted", "screening", "interviewing")


_STAGE_LABEL = {"sourced": "Sourced", "contacted": "Contacted",
                "screening": "Screening", "interviewing": "Interviewing"}


def stage_rail(o):
    """Four segments, one per real pipeline stage, with the CURRENT stage the only saturated one.

    ⚠️ An unrecognised stage renders every segment as pending rather than guessing a position.
    Inventing a position would put a role further along than it is, which is the one error that
    makes this rail worse than the tables it replaced.
    """
    cur = str(o.get("stage") or "").lower()
    idx = STAGES.index(cur) if cur in STAGES else -1
    segs = []
    for i, st in enumerate(STAGES):
        cls = "seg done" if (idx >= 0 and i < idx) else ("seg now" if i == idx else "seg todo")
        segs.append(f'<span class="{cls}" title="{esc(_STAGE_LABEL[st])}"></span>')
    label = _STAGE_LABEL.get(cur, "stage not set")
    return (f'<span class="rail" role="img" aria-label="Stage: {esc(label)}">'
            + "".join(segs) + f'</span><span class="rail-label">{esc(label)}</span>')


def _fit_detail(o, today):
    f = o.get("fit") or {}
    reqs = f.get("requirements") or []
    if not reqs and not f.get("summary"):
        return ""
    aligned = [r for r in reqs if r.get("verdict") == "aligned"]
    other = [r for r in reqs if r.get("verdict") != "aligned"]
    out = ['<div class="od-h">JD fit</div>']
    if f.get("summary"):
        out.append(f'<div class="od-p">{md_inline(str(f["summary"]))}</div>')
    if aligned:
        out.append('<div class="od-p"><strong>Evidence exists for:</strong> '
                   + esc(", ".join(str(r.get("requirement", "")) for r in aligned)) + "</div>")
    if other:
        # ⭐ The DO-NOT-CLAIM half is the half that keeps a letter honest, so it is never
        # collapsed away behind the aligned list.
        out.append('<div class="od-p od-warn"><strong>Do not claim:</strong> '
                   + esc(", ".join(str(r.get("requirement", "")) for r in other)) + "</div>")

    # ⭐⭐ THE OPEN QUESTIONS RENDER HERE — GitHub #5 (public).
    #
    # The coordinator truncates its own list and sends the reader to "the dashboard's JD fit
    # section" for the rest. That section existed and never held them: the renderer that did
    # was written and never called, so the feature looked present while every generated
    # dashboard omitted it. Grepping a real dashboard for the question text returned nothing,
    # for any role.
    #
    # A report that truncates itself must point at a surface that actually holds the
    # remainder, so they go where the pointer already says they are.
    #
    # ⚠️ DATED FIRST, AND SHOW THE DATE. `act_by` exists because the fact that made a question
    # urgent used to live as prose inside the question text, where nothing could sort it.
    # Rendering them undifferentiated here would rebuild exactly that.
    qs = [r for r in reqs
          if r.get("question_for_candidate") and r.get("question_status") == "open"]
    if qs:
        qs = sorted(qs, key=lambda r: (r.get("act_by") or "9999-99-99"))
        items = []
        for r in qs:
            ab = r.get("act_by")
            text = esc(str(r["question_for_candidate"]))
            if not ab:
                items.append("<li>%s</li>" % text)
            else:
                items.append('<li><strong>%s %s</strong> &middot; %s</li>'
                             % ("&#8252;&#65039; DUE" if str(ab) <= today else "&#9203; by",
                                esc(str(ab)), text))
        out.append('<div class="od-p"><strong>&#10067; Needs you:</strong></div>'
                   '<ul class="od-p" style="margin:0 0 6px 18px">%s</ul>' % "".join(items))
    return "".join(out)


def _touch_detail(o):
    out = []
    # ADR-031 B2 — o["_applications"] is the caller's join against the top-level applications
    # store (applications.enrich_opportunities, called once in load_jsonl above), never a
    # nested array on the record.
    apps = o.get("_applications") or []
    if apps:
        rows = []
        for a in apps:
            when = esc(str(a.get("applied_on") or a.get("date") or "date unrecorded"))
            how = esc(str(a.get("method") or "application"))
            # `cover_letter_id` is the FK to the cover_letters store (was the free-text
            # `cover_letter` field before B2) — "recorded" now means "linked", not "non-empty".
            cl = "cover letter recorded" if a.get("cover_letter_id") else "cover letter unrecorded"
            rows.append(f"<li>{when} — {how} · {cl}</li>")
        out.append('<div class="od-h">Applications</div><ul class="od-l">'
                   + "".join(rows) + "</ul>")
    # ADR-031 B3 — o["_touches"], the caller's join against the top-level touches store
    # (touches.enrich_opportunities, called once in load_jsonl above), never a nested array.
    tou = o.get("_touches") or []
    if tou:
        rows = []
        for t in tou:
            when = esc(str(t.get("sent_on") or t.get("date") or "date unrecorded"))
            who = esc(str(t.get("to") or t.get("person_id") or "recipient unrecorded"))
            med = esc(str(t.get("medium") or ""))
            res = t.get("outcome") or "no reply yet"
            rows.append(f"<li>{when} — {who}{' · ' + med if med else ''} · {esc(str(res))}</li>")
        out.append('<div class="od-h">Outreach</div><ul class="od-l">'
                   + "".join(rows) + "</ul>")
    return "".join(out)


def _days_since(iso, today):
    """Whole days from an ISO date to today, or None for anything unreadable or in the
    future - an unknown age is never invented as zero (`_age_days`' rule, as a number)."""
    try:
        d = datetime.date(*map(int, str(iso)[:10].split("-")))
        n = (today - d).days
        return n if n >= 0 else None
    except Exception:                                       # noqa: BLE001
        return None


def _pursuit_chip(p):
    """The row's own pursuit chip (`PURSUIT_LABELS`), with the finer cell or cause beside it. A row the engine
    could not classify is LOUD and names the field."""
    state = p.get("state")
    label = PURSUIT_LABELS.get(state, state)
    if state == "unclassifiable":
        return (' <span class="chip action" title="the pursuit state could not be derived">'
                'unclassifiable — %s missing</span>' % esc(str(p.get("missing") or "a field")))
    if state == "ended" and p.get("ended_because"):
        label = "Ended — %s" % p["ended_because"]
    return ' <span class="chip pursuit" title="%s">%s</span>' % (
        esc(str(p.get("cell") or "")), esc(label))


WARM_PATH_NOTES = {
    "ready": "after you decide",
    "draft-owed": "draft owed",
    "drafted": "draft ready for you to send",
    "touched": None,           # "asked <date>"
    "lookup-owed": None,       # a link / a search to open
    "looked-none": None,       # "looked <date>, none found"
}


def _warm_html(a):
    """dev #751 (W3) -- ONE line on a role card: the warm-path next action `warm_path.py` derived for it,
    never composed here. `data-warm` carries the state so `check_dashboard_coverage.py` can hold the page
    to it (a derived action whose card lacks the line, or shows a different state, is a gap). A lookup is a
    LINK the candidate opens, only when a LinkedIn company URL is already on record; nothing here sends,
    connects or messages anyone."""
    if not a:
        return ""
    who = esc(a.get("person_name") or a.get("person_id") or "")
    kind = {"referral-ask": "referral ask to", "hm-note": "note to the hiring manager",
            "backer-intro": "introduction ask to"}.get(a["kind"], "")
    st = a["state"]
    if st == "lookup-owed":
        if a.get("linkedin_url"):
            text = ('no one known: <a href="%s" target="_blank" rel="noopener">look up on LinkedIn '
                    '&#8599;</a>, then record who you found' % esc(a["linkedin_url"]))
        else:
            text = "no one known: search LinkedIn for people there, then record who you found"
    elif st == "looked-none":
        text = "looked %s, none found" % esc(a.get("on") or "?")
    elif st == "touched":
        text = "%s %s (asked %s)" % (kind, who, esc(a.get("on") or "?"))
    else:
        text = "%s %s (%s)" % (kind, who, WARM_PATH_NOTES[st])
    return '<div class="opp-warm" data-warm="%s">Warm path: %s</div>' % (esc(st), text)


def _lean_html(o, role_state, stage=None, lean=None):
    """The row-level line under a role (dev #713 / public #145, dev #820 / public #175): a `decide` row
    shows the LEAN and the likely-pass signals that matched; a `your-read` row shows WHY only you can
    read it and the command that records your read; a `process-failure`, `waiting-intake` or
    `in-progress` row names what the process did not do. Everything comes from your_move.py
    (`decide_lean`, `group_why`) - this only renders. A lean is a lean: it never removes a role, and
    the line says `LEAN`, not a verdict. `lean` holds those your_move values for this role, computed by the
    loader (`generate_dashboard._lean_values`, dashboard-redesign A): this module imports no flat script."""
    lean = lean or {}
    if role_state == "decide":
        ln = lean.get("decide")
        if not ln:
            return ""
        sigs = "".join(
            ' <span class="lean-sig" title="a likely-pass signal matched; it never removes a '
            'role">%s</span>' % esc("%s (in %s)" % (s.get("reason") or s.get("id") or "signal",
                                                    s.get("matched_in") or "?"))
            for s in ln["signals"])
        return ('<div class="opp-lean"><strong>LEAN %s</strong> · %s%s</div>'
                % (esc(ln["lean"]), esc(ln["line"]), sigs))
    if lean.get("kind") == "your-read" and stage is not None:
        return ('<div class="opp-lean opp-read" data-read="%s"><strong>YOUR READ</strong> &middot; %s'
                ' &middot; %s</div>'
                % (esc(str(stage.cause or "")), esc(lean["reason"]),
                   esc(lean["remedy"])))
    if lean.get("kind") == "process" and stage is not None:
        return ('<div class="opp-lean opp-process" data-process="%s">%s</div>'
                % (esc(role_state), esc(lean["why"])))
    return ""


def _posting_html(label):
    """The employer-posting line (dev #776 / public #166, design §8.2). `label` is one entry of
    `your_move.posting_labels` - {"code", "text", "flag", "headline"} - or None for a role the
    label does not belong on (no line at all, never a guessed one). It is RENDERED here and never
    derived: this file does not import `posting_check`, and the headline, the code and the text
    are your_move.py's. A flagged role (every code but `live`) gets the loud class, so an
    unconfirmed role is visibly different from a confirmed one; it is flagged, never hidden."""
    if not label:
        return ""
    flag = bool(label.get("flag"))
    return ('<div class="opp-posting%s" data-posting="%s"><strong>%s</strong> &middot; %s</div>'
            % (" opp-posting-flag" if flag else "", esc(str(label.get("code") or "")),
               esc(str(label.get("headline") or "")), esc(str(label.get("text") or ""))))


def _play_step_label(ns):
    """A short, row-scale label for one `plays.NextStep` — 'apply', 'research: find
    recruiter', 'touch (referral-ask) → insider' — or None when there is no runnable
    step to name (waiting/goal-reached/manual/stalled each render their own line)."""
    if ns.kind != "step":
        return None
    d = ns.detail or {}
    kind = d.get("kind")
    if kind == "apply":
        return "apply"
    if kind == "research":
        return "research: find %s" % d.get("find")
    if kind == "touch":
        return "touch (%s) → %s" % (d.get("touch_type"), d.get("to"))
    return ns.step


def _fmt_comp(c, currency):
    if not c:
        return "Not disclosed"
    def k(v): return ("%s%dK" % (currency, round(v/1000))) if v else "?"
    lo, hi = c.get("min"), c.get("max")
    rng = k(lo) if lo == hi else "%s–%s" % (k(lo), k(hi))
    return "%s %s" % (rng, c.get("basis", ""))


def _fmt_loc(loc):
    if not isinstance(loc, dict):
        return ""
    t = loc.get("type", "")
    p = loc.get("primary", "")
    return ("%s — %s" % (t, p)) if p and t not in p.lower() else (p or t)


def render_opportunity_card(o, comp, f, key, p, dims, waits, role_state, stage, posting_label, warm_action, pd,
                            pick_html=""):
    """One role's card in a role list (cut from `roles.render_opportunity_list`, dashboard-redesign A): the
    title, the company, the posting link, the pursuit chip, the stage rail, the meta line, the lean, the
    posting line, the next step, the warm path and the Detail block. `f` is the loader's values for the
    role (`link`, `play`, `lean`); `key`, `p` and `dims` are the list's (its record key, pursuit state and
    row attributes); `pd` the page's (`now`, `currency`); `pick_html` the row's tick box (`actions_ui.pick`),
    placed first in the title line."""
    # ADR-031 B4 (design §19) — the play position, DERIVED, on the row itself.
    _ns = f["play"]
    if _ns.kind == "stalled":
        play_html = '<span class="play-unres">play: stalled — %s</span>' % esc(_ns.why or "")
    elif _ns.kind == "step":
        play_html = esc("play: " + (_ns.step or "?"))
    elif _ns.kind not in ("no-plan", "no-play"):
        play_html = esc("play: " + _ns.kind)
    else:
        play_html = ""
    meta = " · ".join(x for x in (
        _fmt_loc(o.get("location")), _fmt_comp(o.get("comp"), pd.currency),
        esc(str(o.get("channel_id") or "").replace("firm:", "via ")) or "",
        play_html) if x)
    action_full = ""
    label = _play_step_label(_ns)
    if label:
        due = _ns.due
        who = "you" if waits else "the run"
        text = label
        flat = re.sub(r"[*`]+", "", text)
        if len(flat) > OPP_ACTION_CLAMP:
            teaser = flat[:OPP_ACTION_CLAMP].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"
            action_full = text
        else:
            teaser = flat
        nxt = (f'<div class="opp-next{" opp-next-you" if waits else ""}">'
               f'<span class="opp-arrow">→</span> {esc(teaser)} '
               f'<span class="opp-owner">{who}{" · due " + esc(str(due)) if due else ""}</span></div>')
    elif _ns.kind == "waiting":
        nxt = ('<div class="opp-next">waiting until %s — %s</div>'
              % (esc(str(_ns.until or "?")), esc(_ns.why or "")))
    elif _ns.kind == "goal-reached":
        nxt = '<div class="opp-next">goal reached</div>'
    elif _ns.kind == "manual":
        nxt = '<div class="opp-next">manual play — the owner decides each step</div>'
    else:
        # ⚠️ Named, not omitted. A role with no next step is a decision nobody has made,
        # and an empty space reads as "handled".
        nxt = ('<div class="opp-next opp-next-none">%s</div>'
              % esc(_ns.why or "No next step derived"))

    # ⭐⭐ THE POSTING LINK IS A ROW-LEVEL AFFORDANCE, NEVER BEHIND `Detail`.
    # The reported frustration was literally "I just wanted the JD link" — and the first
    # version of this layout still cost a click to reach it. Collapsing the duplication is
    # not the same as making the most-wanted thing reachable. It sits next to the title,
    # always in the same place, so it can be hit without reading the row.
    link, _employer_owned = f["link"]
    if link:
        # D817: a link that is not the employer's own says so, so nobody mistakes an aggregator's
        # copy of the posting for the employer's.
        jd = (f'<a class="opp-jd" href="{esc(link)}" target="_blank" rel="noopener" '
              f'title="Open the posting">JD ↗</a>'
              + ('' if _employer_owned else ' <span class="opp-copy">(aggregator copy)</span>'))
    else:
        # Named, not blank — "no link recorded" is a fact about the role, and an empty
        # space here reads as "look harder".
        jd = '<span class="opp-jd opp-jd-none" title="No posting URL recorded">no link</span>'

    detail = ""
    if action_full:
        # The full recommendation, first — it is the reason the reader opened the row.
        detail += ('<div class="od-h">The call in full</div>'
                   f'<div class="od-p">{md_inline(action_full)}</div>')
    detail += _fit_detail(o, pd.now.date().isoformat()) + _touch_detail(o)
    body = (f'<details class="opp-more"><summary>Detail</summary>'
            f'<div class="opp-detail">{detail}</div></details>') if detail else ""
    return (f'<div class="opp"{_rec_attrs(key)}{_dim_attrs(dims)}>'
            f'  <div class="opp-head">'
            f'    <div class="opp-title">{pick_html}{theirs(str(o.get("title") or "Untitled role"), "role-title")}'
            f'      <span class="opp-co">{theirs(str(comp.get("name", o.get("company_id", ""))), "company-name")}</span>'
            f'      {jd}{_pursuit_chip(p)}</div>'
            f'    <div class="opp-rail">{stage_rail(o)}</div>'
            f'  </div>'
            f'  <div class="opp-meta">{meta}</div>'
            f'  {_lean_html(o, role_state, stage, f["lean"])}{_posting_html(posting_label)}{nxt}{_warm_html(warm_action)}{body}'
            f'</div>')


def render_role_line(o, comp, key, p, dims, link, pick_html):
    """A LEVEL-2 row (design §4): one line for a role past its list's level 1, inside the list's closed fold. It is
    still the role's PRIMARY row (`data-rec` and its id), so a link lands on it and the coverage gate counts it
    rendered: the tick box, the title, the company, the pursuit chip and the posting link (`link`, the loader's). Its
    class is `role-line`, never `opp`: it is not a role CARD, and the coverage gate holds every `opp` card to its
    warm-path line (`check_warm_path`)."""
    jd = (' <a class="opp-jd" href="%s" target="_blank" rel="noopener">JD ↗</a>' % esc(link)) if link else ""
    return ('<div class="role-line"%s%s>%s%s <span class="opp-co">%s</span>%s%s</div>'
            % (_rec_attrs(key), _dim_attrs(dims), pick_html,
               theirs(str(o.get("title") or "Untitled role"), "role-title"),
               theirs(str(comp.get("name", o.get("company_id", ""))), "company-name"), _pursuit_chip(p), jd))
