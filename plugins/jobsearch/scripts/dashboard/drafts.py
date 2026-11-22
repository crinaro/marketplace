"""The staged-message pair (dashboard-redesign A, moved from generate_dashboard.py): the drafts.md and
cover_letters.md parsers, the three groups of a message list (D2, design §5), and the Drafts to review section."""
import re
from urllib.parse import urlsplit

from dashboard import caps, levels
from dashboard.actions_ui import group_attr
from dashboard.markup import _rec_attrs, esc, md_inline, plain, theirs, theirs_html


# `parse_focus` is gone with focus.md (dev #93), and `render_focus` followed on 2026-08-29
# with the one-artifact collapse: it rendered ('h', heading) / ('i', title, why) entry
# tuples, which the JSONL-backed builders now feed straight into working-set TABLES
# (render_ws below) — the owner rejected sentence-shaped rows twice, and a numbered prose
# list was that shape one level down. Removed rather than left never-called (the
# render_fit()/GitHub #5 trap).


def parse_cover_letters(md: str):
    """Entries from cover_letters.md, minus the trailing '⚠️ Questions...' section.

    Same '## ' shape as drafts.md, so parse_drafts does the splitting; this only
    filters out the housekeeping section at the bottom, which is a note to me
    rather than a letter the candidate would review.
    """
    entries = [(ttl, blocks) for ttl, blocks in parse_drafts(md)
               if "questions that would sharpen" not in ttl.lower()]
    # A letter whose body isn't blockquoted parses to an EMPTY body and publishes
    # silently as a heading with no text -- which is exactly how the PCG letter
    # reached the dashboard invisible on 2026-07-27 (the candidate caught it, not the run).
    # The body MUST be '> '-prefixed; warn loudly rather than shipping a blank.
    for ttl, blocks in entries:
        if not any(k == "quote" and any(p.strip() for p in v) for k, v in blocks):
            print("  !! WARNING: cover letter '%s' has NO quoted body -- "
                  "the letter text must be blockquoted with '> ' or it renders EMPTY."
                  % ttl[:70])
    return entries


def parse_drafts(md: str):
    """Split drafts.md on '## ' entries -> list of (title, blocks).

    ⭐⭐ REWRITTEN 2026-08-03. The candidate: *"can you fix the formatting for the html output for the
    drafts in the Your Move section? when i look at the drafts.md, they are so much easier to
    read versus the html page."*

    **What was wrong, and it was worse than cosmetic.** The old parser kept only two things: the
    lines starting with `**`, and EVERY `>` line in the entry CONCATENATED INTO ONE BLOB. For a
    single-message draft that was survivable. For a multi-recipient campaign it destroyed the
    document: the <an employer> entry has two recipients, each with a connection note AND a follow-up
    message, and all four bodies merged into one undifferentiated wall with no way to tell which
    text goes to whom or which piece is which. `### Recipient 1 of 2` and `#### A. / B.` headings
    were dropped outright, so the only signposts vanished too.

    **And free prose was silently discarded** — drafts.md's own header warns about this
    ("Free-form prose paragraphs without a `**Label:**` prefix are silently dropped... verified
    this the hard way 2026-07-10"). A parser that eats content and warns you in prose is a trap.
    This one renders everything, so the trap is gone rather than documented.

    Returns ordered, TYPED blocks so the HTML can mirror the markdown:
      ('meta', [lines])  '**Label:** value' runs
      ('h3', text)       '### ' — a recipient
      ('h4', text)       '#### ' — a piece (A. the note, B. the message)
      ('quote', [paras]) a '> ' run — THE TEXT THE CANDIDATE ACTUALLY SENDS
      ('note', [lines])  anything else, previously dropped
      ('rule', None)     '---'
    """
    entries = []
    for m in re.finditer(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", md, re.M | re.S):
        title, body = m.group(1).strip(), m.group(2)
        blocks, buf, kind = [], [], None

        def flush():
            if not buf:
                return
            if kind == "quote":
                # A bare '>' is a paragraph break inside the message, not a blank line to drop.
                paras, cur = [], []
                for ln in buf:
                    if ln.strip():
                        cur.append(ln)
                    elif cur:
                        paras.append("\n".join(cur)); cur = []
                if cur:
                    paras.append("\n".join(cur))
                blocks.append(("quote", paras))
            else:
                blocks.append((kind, list(buf)))
            buf.clear()

        for raw in body.splitlines():
            s = raw.strip()
            if s.startswith(">"):
                if kind != "quote":
                    flush(); kind = "quote"
                buf.append(raw.lstrip()[1:].lstrip() if raw.lstrip().startswith(">") else raw)
            elif s.startswith("####"):
                flush(); kind = None; blocks.append(("h4", s.lstrip("#").strip()))
            elif s.startswith("###"):
                flush(); kind = None; blocks.append(("h3", s.lstrip("#").strip()))
            elif s in ("---", "***", "___"):
                flush(); kind = None; blocks.append(("rule", None))
            elif s.startswith("**"):
                if kind != "meta":
                    flush(); kind = "meta"
                buf.append(s)
            elif not s:
                flush(); kind = None
            else:
                if kind != "note":
                    flush(); kind = "note"
                buf.append(s)
        flush()
        entries.append((title, blocks))

    # ⭐ AN UNTITLED ENTRY IS AN INVISIBLE ENTRY — added 2026-08-05, and it had already shipped.
    # The candidate: *"I still don't see the message for <a contact>."* The draft was in drafts.md, was
    # correctly `> `-blockquoted, and its text WAS in the published HTML — so every existing guard
    # passed. But it had been written with a `**Label:**` line where every other entry uses a
    # `## ` heading, and entries are split on `## ` alone. So it never began a card: it was
    # absorbed into the TAIL of the previous, unrelated draft (MedImpact/Marjan), under that
    # draft's title. Nothing was missing; it was filed under someone else's name.
    #
    # Why the existing checks could not catch it: the no-quoted-body guard asks whether the text
    # EXISTS, and it did. This asks the different question — whether the text is FINDABLE. A
    # `---` rule followed by a `**Label:**` line is precisely the shape of an entry that forgot
    # its heading, and it does not occur in a well-formed one.
    for m in re.finditer(r"^##\s+(.+?)$(.*?)(?=^##\s|\Z)", md, re.M | re.S):
        _t, _b = m.group(1).strip(), m.group(2)
        if re.search(r"^---\s*$\s*^\*\*Label:\*\*", _b, re.M):
            print("  !! WARNING: draft '%s' contains a '---' followed by a '**Label:**' line. "
                  "That is an entry that forgot its '## ' heading, so it renders INSIDE this "
                  "one instead of as its own card -- findable only by whoever already knew it "
                  "was there. Give it a '## ' title." % _t[:70])

    # Same silent-empty guard as before: a draft body must be '> '-quoted or it renders BLANK,
    # which is indistinguishable from "not drafted yet". That shipped once and only the candidate noticed.
    for ttl, blocks in entries:
        if "questions that would sharpen" in ttl.lower():
            continue
        if not any(k == "quote" and any(p.strip() for p in v) for k, v in blocks):
            print("  !! WARNING: draft '%s' has NO quoted body -- "
                  "the message text must be blockquoted with '> ' or it renders EMPTY."
                  % ttl[:70])
    return entries


def render_draft_entries(entries, empty_msg):
    """Render typed blocks so the page reads like the markdown does."""
    if not entries:
        return '<div class="sub">%s</div>' % empty_msg
    out = []
    for title, blocks in entries:
        parts = ['<div class="draft"><div class="draft-title">%s</div>'
                 % theirs_html(md_inline(title), "message-snippet")]
        for kind, val in blocks:
            if kind == "meta":
                parts.append('<div class="draft-meta">%s</div>'
                             % "".join("<div>%s</div>" % md_inline(l) for l in val))
            elif kind == "h3":
                parts.append('<div class="draft-h3">%s</div>' % md_inline(val))
            elif kind == "h4":
                parts.append('<div class="draft-h4">%s</div>' % md_inline(val))
            elif kind == "rule":
                parts.append('<hr class="draft-rule">')
            elif kind == "note":
                parts.append('<div class="draft-note">%s</div>'
                             % "<br>".join(md_inline(l) for l in val))
            elif kind == "quote":
                # THE SENDABLE TEXT. Its own card, so it is obvious what to copy.
                paras = "".join(
                    "<p>%s</p>" % "<br>".join(md_inline(x) for x in p.split("\n"))
                    for p in val if p.strip())
                parts.append('<div class="draft-quote">%s</div>' % paras)
        parts.append("</div>")
        out.append("".join(parts))
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# INDEX RENDERERS — dev #233. The state view lists documents as title + status +
# location, NEVER in full. The full text has exactly one published home (the phase
# page named on each index row) and one authored home (the file in the tree).
# ─────────────────────────────────────────────────────────────────────────────

def _draft_meta_summary(blocks):
    """The '**Label:** value' lines of the entry's FIRST meta block, flattened to one
    ' · '-joined line — enough to recognise the message without carrying its body."""
    for kind, val in blocks:
        if kind == "meta":
            parts = [re.sub(r"\*\*(.+?):\*\*\s*", r"\1: ", l).strip() for l in val]
            return " · ".join(p for p in parts if p)[:220]
    return ""


# ⭐ Query or Citation C1 (design-query-or-citation.md §3.5, D8) — six states join these three
# dicts, in their own three-way class split: `unaddressed`/`unbriefed`/`brief-mismatch`/
# `stale-brief` are NEEDS_HUMAN (chip class "action", same as `unresolved`/`unreadable`
# already render); `unverified-cold`/`unverified-silent` are WAITS_ON_SURFACE — a THIRD chip
# class, "queued", neither "waiting" (on the other side) nor "action" (on the owner): the
# draft waits on a session with a keychain. The mirror gate in TestQueryOrCitationC1 below
# asserts every state in `precondition.OPEN_STATES` is present in all three dicts, so a
# seventh state added to one and not the others fails loudly instead of rendering muted.
_SEND_ORDER = {"sendable": 0, "unreadable": 1, "unresolved": 1, "blocked": 2,
              "unaddressed": 1, "unbriefed": 1, "brief-mismatch": 1, "stale-brief": 1,
              "unverified-cold": 3, "unverified-silent": 3}


_SEND_CHIP = {"sendable": ("scheduled", "ready"), "blocked": ("waiting", "held"),
              "unresolved": ("action", "unresolved"), "unreadable": ("action", "unreadable"),
              "unaddressed": ("action", "unaddressed"), "unbriefed": ("action", "unbriefed"),
              "brief-mismatch": ("action", "brief mismatch"),
              "stale-brief": ("action", "stale brief"),
              "unverified-cold": ("queued", "queued — cold unverified"),
              "unverified-silent": ("queued", "queued — silence unverified")}


_SEND_WHERE = {
    "sendable": "full text below — expand it and read it here, never off a transcript",
    "blocked": "held — waits on the other side; moves to ready by itself once the touch "
               "outcome flips",
    "unresolved": "needs YOU — rewrite the **Blocked until:** line as contact:<id> "
                  "outcome:<...>; nobody can say what this waits on",
    "unreadable": "needs YOU — rewrite the **Blocked until:** line as contact:<id> "
                  "outcome:<...>; the strict parser refuses it",
    "unaddressed": "needs YOU — no recipient identified; add a **To:** contact:<id> line",
    "unbriefed": "needs YOU — drafted without reading the thread; ask Claude to refresh "
                "the brief",
    "brief-mismatch": "needs YOU — the cited brief names someone else; rebrief this entry",
    "stale-brief": "needs YOU — they wrote since this was drafted; rebrief, or redraft if "
                  "the register moved",
    "unverified-cold": "queued for a keychain-holding session — the mailbox has not been "
                       "checked on this surface",
    "unverified-silent": "queued for a keychain-holding session — a sweep must cover this "
                         "thread first",
}


def _wait_kind(st):
    """`held` (their move: `blocked`) or `queued` (a mailbox check first: `unverified-*`)."""
    return "queued" if st in ("unverified-cold", "unverified-silent") else "held"


def _text_fold(title, blocks, st, label):
    """The entry's text, in ONE closed fold (public #139 rule 1b; design §5): never open by default, and on the page
    exactly once (no prompt quotes it, design §6.2). A not-sendable entry's summary names its state."""
    summary = "the text" if st == "sendable" else "the text — %s, not sendable" % label
    return ('<details class="kdoc"><summary>%s</summary><div class="kdoc-body" data-theirs="kdoc-body">%s</div>'
            '</details>' % (esc(summary), render_draft_entries([(title, blocks)], "")))


def _subject(meta, key):
    """dev #915: the row's SUBJECT (who the message is to, else the role it follows up, else itself), the attribute
    check_dashboard_coverage's SUBJECT TWICE reads. Several drafts to one person are one section."""
    m_to = re.search(r"To:\s*contact:(\S+)", meta)
    m_opp = re.search(r"Triggered by:\s*opp:(\S+)", meta)
    return ("person:%s" % m_to.group(1)) if m_to else (("opp:%s" % m_opp.group(1)) if m_opp else key)


def primary_subjects(entries, keys, ledger):
    """{subject: key}: the subject of every staged entry whose PRIMARY row is on the page (the ledger placed it
    `rendered`), first entry wins (several drafts to one person are one appearance). `entries` ([(title, blocks)]) and
    `keys` are aligned. What `network.ref_targets` reads so a plan row about the same subject is a reference (dev 973)."""
    out = {}
    for (_title, blocks), key in zip(entries, keys):
        if (ledger.records.get(key) or {}).get("disposition") == "rendered":
            out.setdefault(_subject(_draft_meta_summary(blocks), key), key)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# THE HAND-OFF (jobsearch 0.91.0 B7a; design-build-reach.md 10.2 "The LinkedIn hand-off, precisely", owner O8 and the
# 2026-11-21 amendment). A READY draft names how it leaves:
#   * a LinkedIn medium: the action is the candidate's (`actions.modes` refuses `me` for every LinkedIn type, User Agreement
#     8.2 item 13), so the row carries a link to the exact page (the person's recorded LinkedIn address, or says none is
#     recorded; never a guessed or searched address). The Copy control is the one the row already has: its tick box and the
#     list's ONE button (`actions_ui`, `navigator.clipboard.writeText`), whose prompt names the draft for the session (design
#     10.2, 11: "link and text in the terminal"); the text itself is in the row's fold. A second button
#     kind that copied the text alone is NOT built: the page contract (dashboard-redesign 6.1, 6.5; test_dashboard_budget's
#     every-button-is-an-action-block and button-budget cases) allows one. Nothing else: no engine process opens LinkedIn,
#     reads a page or writes the clipboard, and the link is a plain anchor. `linkedin-profile-edit` and `linkedin-post` have
#     no drafts.md medium (`precondition.MEDIA`), so no row reaches them.
#   * an email with an outbox row: that row's state, and for a `me` row the attended-only note (a queued send goes only
#     from an attended session, after the candidate approves it and answers the platform's send prompt).
# ─────────────────────────────────────────────────────────────────────────────
LINKEDIN_ACTIONS = {"linkedin-connection-note": "linkedin-connect", "linkedin-message": "linkedin-message",
                    "linkedin-inmail": "linkedin-message"}
EMAIL_ME_NOTE = ("email me is attended only: it is sent only from a session you are at, after you approve it there and "
                 "answer the send prompt; a scheduled run never sends it")
_OUTBOX_NOTES = {
    "staged": "in your mailbox's drafts: open it there, edit it if you like, and send it yourself",
    "queued": "queued for jobsearch to send after your approval",
    "approved": "approved in an attended session: it goes only when you answer the send prompt",
    "sending": "the send call was made; it is recorded as sent once it shows in your Sent mail",
    "failed": "the send failed; nothing was sent",
}


def _linkedin_page(url):
    """`url` when it is an https address on linkedin.com (or a subdomain of it), else None: the hand-off links only a
    recorded LinkedIn address."""
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        return None
    host = (parts.hostname or "") if parts else ""
    return url if parts and parts.scheme == "https" and (host == "linkedin.com" or host.endswith(".linkedin.com")) else None


def handoff_data(people, outbox_rows):
    """`PageData.handoff`: {"pages": {person id: recorded LinkedIn address}, "outbox": {draft_ref: its open outbox row}}.
    A discarded or sent row hands nothing off; with two rows for one draft the later wins."""
    pages = {p["id"]: _linkedin_page(p.get("linkedin")) for p in people if isinstance(p, dict) and p.get("id")}
    outbox = {r["draft_ref"]: r for r in outbox_rows
              if isinstance(r, dict) and r.get("draft_ref") and r.get("state") in _OUTBOX_NOTES}
    return {"pages": {k: v for k, v in pages.items() if v}, "outbox": outbox}


def _handoff(blocks, meta, medium, pd):
    """The row's hand-off line (the block comment above), or "" when it hands nothing off."""
    data = getattr(pd, "handoff", None) or {}
    action = LINKEDIN_ACTIONS.get(medium)
    if action:
        m_to = re.search(r"To:\s*contact:(\S+)", meta)
        url = (data.get("pages") or {}).get(m_to.group(1)) if m_to else None
        # terse on purpose: the open page's word budget (dashboard-redesign 9.1, test_dashboard_budget) counts every row
        link = (('<a class="handoff-link" href="%s" target="_blank" rel="noopener">send on LinkedIn &#8599;</a>' % esc(url))
                if url else "no LinkedIn address recorded")
        return '<div class="handoff sub" data-handoff="%s">%s</div>' % (esc(action), link)
    m_brief = re.search(r"Brief:\s*(\S+)", meta)
    row = (data.get("outbox") or {}).get(m_brief.group(1)) if m_brief else None
    if not row:
        return ""
    note = _OUTBOX_NOTES[row["state"]] + ((" (%s)" % EMAIL_ME_NOTE) if row.get("mode") == "me" else "")
    return ('<div class="handoff sub" data-handoff="email-send"><span class="chip queued">outbox: %s</span> %s</div>'
            % (esc(row["state"]), esc(note)))


def _row(title, blocks, key, st, pd, pick_html, full, medium=None):
    """One entry's PRIMARY row. `full` (level 1): the title, its state chip, its meta line, the reason in plain words
    when it needs the owner, its hand-off when it is ready (`_handoff`), then the text fold. Otherwise (level 2, or a
    waiting entry) ONE line: the title, the state in a few words, the hand-off of a ready level-2 row, the text fold."""
    cls, label = _SEND_CHIP.get(st, ("waiting", st))
    meta = _draft_meta_summary(blocks)
    attrs = '%s data-sendability="%s" data-subject="%s"' % (_rec_attrs(key), esc(st), esc(_subject(meta, key)))
    hand = _handoff(blocks, meta, medium, pd) if st == "sendable" else ""
    if not full:
        note = ""
        if st in ("unverified-cold", "unverified-silent"):
            m_to = re.search(r"To:\s*contact:(\S+)", meta)
            act_id = pd.queued_by_contact.get(m_to.group(1)) if m_to else None
            note = (" · queued: %s" % act_id) if act_id else ""
        return ('<div class="draft draft-line"%s>%s%s <span class="chip %s">%s</span><span class="sub">%s</span>%s%s'
                '</div>' % (attrs, pick_html, theirs_html(md_inline(title), "message-snippet"), cls, esc(label),
                            esc(note), hand, _text_fold(title, blocks, st, label)))
    medium_flag = ""
    if medium == "unknown":
        # Loud on the row: the **Medium:** line names no MEDIA value (or there is no line); never a guess.
        medium_flag = ' <span class="chip action" title="the Medium line names no known medium">medium: unknown</span>'
    loud = st in pd.needs_human
    why = ('<div class="sub">%s</div>' % md_inline(plain(_SEND_WHERE.get(st, st)))) if loud else ""
    return ('<div class="draft%s"%s><div class="draft-title">%s%s <span class="chip %s">%s</span>%s</div>%s%s%s%s</div>'
            % (" ws-loud" if loud else "", attrs, pick_html, theirs_html(md_inline(title), "message-snippet"), cls,
               esc(label), medium_flag,
               ('<div class="draft-meta">%s</div>' % theirs(meta, "message-snippet")) if meta else "", why, hand,
               _text_fold(title, blocks, st, label)))


# The groups' headings and anchors (design §5; `dashboard.rank` names the anchors Today links).
_GROUPS = (("ready", "Ready to send", "today-src-drafts-ready"),
           ("needs", "Needs you", "today-src-drafts-needs-you"))


def render_message_groups(set_name, kind, entries, keys, states, filename, ledger, pd, section=None, noun="draft",
                          head_tag="h3"):
    """`(html, n_open)`: the open entries of one file of the staged pair in THREE groups by who they wait on (design §5,
    criterion N2): READY (`sendable`), NEEDS YOU (`precondition.NEEDS_HUMAN`, the reason through `plain()`) and WAITING
    (`blocked`, their move; `unverified-*`, a mailbox check first), ONE closed fold whose summary counts both.

    Ready and needs-you share level 1 (`caps.DRAFTS_L1` rows, in `precondition` order: sendable, then needs-you; the rows
    Today took from `section` first), each group under its own heading (with Today's anchor when `section` is given),
    its level-2 rows in its own closed fold, and one level-3 count line (`data-more="<set_name>:N"`). The waiting fold
    holds one-line rows (at most `caps.LEVEL2`, the rest counted as `<set_name>-waiting`). Every row is a primary row
    (`data-rec`) and carries its text in a closed fold; ready and needs-you rows carry a tick box, and the list ONE
    `work-through` button (`levels.group_button`). A waiting row has nothing for the owner to do, so it has no box.

    `entries` and `keys` are aligned (`your_move.entry_keys`); `states` is keyed `(filename, key)`; terminal entries are
    never passed (the loader ledgers them)."""
    rows = []
    for (title, blocks), key in zip(entries, keys):
        st = (states.get((filename, key)) or {}).get("state") or "sendable"
        medium = (states.get((filename, key)) or {}).get("medium") or "unknown"
        rows.append((title, blocks, key, st, medium))
    rows.sort(key=lambda r: _SEND_ORDER.get(r[3], 9))
    needs_human = set(pd.needs_human or ())
    act = [r for r in rows if r[3] == "sendable" or r[3] in needs_human]
    waiting = [r for r in rows if not (r[3] == "sendable" or r[3] in needs_human)]
    open_, folded, rest = levels.split(act, caps.DRAFTS_L1, pd, section, key=lambda r: r[2])
    w_shown, w_rest = waiting[:caps.LEVEL2], waiting[caps.LEVEL2:]
    ledger.cover_set(set_name, [r[2] for r in open_ + folded], [r[2] for r in rest])
    ledger.cover_set(set_name + "-waiting", [r[2] for r in w_shown], [r[2] for r in w_rest])
    out = [levels.group_button(pd, "Work through", len(open_), len(rest))]
    for gname, heading, anchor in _GROUPS:
        def mine(r, gname=gname):
            return (r[3] == "sendable") == (gname == "ready")
        g_all = [r for r in act if mine(r)]
        if not g_all:
            continue
        g_open, g_fold = [r for r in open_ if mine(r)], [r for r in folded if mine(r)]
        out.append('<%s class="dgroup"%s>%s <span class="tcount">%d</span></%s>'
                   % (head_tag, (' id="%s"' % anchor) if section else "", esc(heading), len(g_all), head_tag))
        out.extend(_row(t, b, k, st, pd, levels.row_pick(pd, k, t, 1), True, md) for t, b, k, st, md in g_open)
        out.append(levels.fold("%d more %s, one line each" % (len(g_fold), heading.lower()),
                               "".join(_row(t, b, k, st, pd, levels.row_pick(pd, k, t, 2), False, md)
                                       for t, b, k, st, md in g_fold)))
    out.append(levels.more_line(set_name, len(rest), "%ss ready or needing you" % noun,
                                "Show me every %s that is ready or needs me." % noun))
    if waiting:
        n_held = sum(1 for r in waiting if _wait_kind(r[3]) == "held")
        n_queued = len(waiting) - n_held
        summary = " · ".join(x for x in (
            ("%d held, waiting on their reply" % n_held) if n_held else "",
            ("%d queued, waiting for a mailbox check" % n_queued) if n_queued else "") if x)
        out.append(levels.fold(summary, "".join(_row(t, b, k, st, pd, "", False) for t, b, k, st, _md in w_shown)))
        out.append(levels.more_line(set_name + "-waiting", len(w_rest), "waiting %ss" % noun,
                                    "Show me every %s that is waiting." % noun))
    return "".join(out), len(open_)


def render_drafts_section(entries, keys, states, filename, trigger, ledger, pd):
    """The `Drafts to review` section (design §5): `render_message_groups` over the open drafts, under a heading that
    says the whole count and how many rows are open. `trigger` is `None` when the trigger scan failed (the page then
    says the counts are UNKNOWN), else `(n_unblocked, n_waiting)` sequences. `""` when there is no draft and the scan
    did not fail. The group element (`data-pick-group="drafts"`) holds the button and every tick box."""
    _trig_note = ('<div class="note">⛔ <strong>Trigger scan failed</strong> — sequence and '
                  'follow-up counts on this page are UNKNOWN, not zero. '
                  'Ask Claude to check the trigger links.</div>') if trigger is None else ""
    if not (entries or _trig_note):
        return ""
    seq_bits = []
    if trigger is not None and trigger[0]:
        seq_bits.append("%d sequence%s unblocked — the next step is sendable"
                        % (trigger[0], "" if trigger[0] == 1 else "s"))
    if trigger is not None and trigger[1]:
        seq_bits.append("%d waiting on a trigger" % trigger[1])
    body, n_open = ('<div class="sub">No pending drafts.</div>', 0)
    if entries:
        body, n_open = render_message_groups("drafts", "draft", entries, keys, states, filename, ledger, pd,
                                             section="drafts")
    return _trig_note + (
        '<h2 id="phase-outreach-approvals">✉️ Drafts to review <span class="tcount">%d</span>%s</h2>'
        '<div class="sub" style="margin:-6px 0 10px">Nothing is sent without your approval. Each message\'s text is '
        'in its fold: read it here, never off a transcript.%s</div>'
        '<div class="card"%s>%s</div>'
        % (len(entries), levels.showing(n_open, len(entries)),
           (" " + esc("; ".join(seq_bits)) + ".") if seq_bits else "", group_attr("drafts"), body))
