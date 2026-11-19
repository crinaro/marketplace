"""Migration 0.46.0: `m_0_46_0_brief_line()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl

VERSION = "0.46.0"


def _people_prerequisite_pending(profile):
    """True if `m_0_44_0_people_involvements` (0.44.0, B1) has not yet successfully landed —
    decided the SAME way THAT migration decides it has nothing left to do (a `contacts` key
    still present on any opportunity or channel row), never by `people.jsonl`'s mere
    existence: a profile that never had any legacy `contacts` at all also never gets a
    `people.jsonl` on disk (0.44.0's own `any_contacts` short-circuit returns `(True, "")`
    without writing one), and that is a genuinely FINISHED state, not a pending one — public
    #92's bug was treating 0.46.0 as safe to run the moment it was REACHED, not the moment its
    prerequisite had actually succeeded."""
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    chan_path = os.path.join(profile, "data", "channels.jsonl")
    try:
        opps = _read_jsonl(opp_path) if os.path.exists(opp_path) else []
        channels = _read_jsonl(chan_path) if os.path.exists(chan_path) else []
    except Exception:                                                  # noqa: BLE001
        return False           # unreadable is a DIFFERENT failure — the normal read below
                                # (inside m_0_46_0_brief_line itself) surfaces it properly
    return (any("contacts" in r for r in opps) or any("contacts" in r for r in channels))


def m_0_46_0_brief_line(profile, apply_it):
    """0.46.0 — Query or Citation C1's own migration (design-query-or-citation.md §7): stamps
    `**To:**`/`**Brief:**` onto every OPEN `outreach/drafts.md` entry (tombstones sent/moot
    skipped — public #29's TERMINAL check, read the same way `precondition.py` reads it), then
    runs a bulk, store-only rebrief (`brief.rebrief(profile, probe=False)`) so only genuinely
    unattributable and unverified rows are loud on day one (D7, owner decision 4).

    PRESERVE, THEN TRANSFORM. `**To:**` is derived ONLY from the entry's own `**Blocked
    until:** contact:<id>` token, resolved through `people.jsonl` (`merged_into` followed) —
    never inferred from headings or bodies, because a WRONG recipient is worse than a counted
    absence (§7 step 1). An entry with no such token, or one that does not resolve, gets the
    literal `**To:** unaddressed`. `**Brief:** none` is stamped under every open entry
    regardless of whether `**To:**` resolved (public #13's lesson: absence of a field must
    never read as "no brief needed").

    Idempotent: an entry that already carries BOTH lines is left untouched entirely; the bulk
    rebrief's own `only_all=False` default (this migration never passes `only_all=True`) skips
    any entry whose `**Brief:**` is already a real (non-`none`) citation, so a second run
    stamps nothing new and rebriefs nothing new.

    `briefs.jsonl` is created empty by THIS migration if it does not already exist yet — an
    absent store reads as an empty one and is reported as fact (trap 1's shape). `**To:**`/
    `**Brief:**` LINES are this migration's own write; `briefs.jsonl` ROWS are `brief.py`'s
    (via the bulk rebrief this migration calls, and every later `--for`/`--rebrief`).

    ⭐ PENDING ON ITS OWN PREREQUISITE (public #92, part 2). This migration's attribution reads
    `people.jsonl` through a `graph.Graph` — if 0.44.0 (B1, `m_0_44_0_people_involvements`) has
    not yet actually LANDED (refused, or not yet reached in this same batch), that store is
    either absent or still missing the rows this migration needs, and attributing against it
    silently stamps every entry `unaddressed` — wrong, not merely incomplete, because a later
    successful 0.44.0 run leaves those entries "already stamped" and this migration's own
    idempotency then skips them FOREVER (`brief.restamp_unaddressed` / the 0.48.0 migration is
    the recovery for a profile that already hit this). So this now checks the SAME condition
    0.44.0 itself uses to decide it has nothing to do (a `contacts` key still present on any
    opportunity or channel row) and returns PENDING — never silently "done" — rather than
    stamping anything at all: `_people_prerequisite_pending()` below.
    """
    import _tree
    import precondition as _pre
    import brief as _brief
    import graph as _graph

    if _people_prerequisite_pending(profile):
        return False, ("  ⏳ 0.46.0 PENDING — the people/involvements migration (0.44.0) has "
                       "not landed yet (opportunities/channels still carry a legacy `contacts` "
                       "key). Nothing stamped this run: attributing **To:** against a people "
                       "store that is not there yet is how public #92 happened.")

    # `brief.LEDGER` — never the literal "briefs.jsonl" here: check_ledger_reads.py's own
    # allowlist for that string constant is {brief.py, validate_data.py, make_fixture.py}
    # (§3.6), and this migration is not on it.
    briefs_path = os.path.join(profile, _brief.LEDGER)
    briefs_created = False

    path = _tree.resolve_rel(profile, _tree.rel("drafts"))
    if not os.path.exists(path):
        return True, ""
    try:
        with open(path, encoding="utf-8") as fh:
            md = fh.read()
    except OSError as e:
        return False, ("  ⚠️ %s could not be read, so nothing was stamped: %s"
                       % (_tree.rel("drafts"), e))

    try:
        g = _graph.Graph(os.path.join(profile, "data"))
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ could not load the graph, so nothing was stamped: %s" % e

    inserts = []           # (offset, text) — always right after the entry's title line
    attributed, unaddressed_ct, already = 0, 0, 0
    for m in _pre.ENTRY_RE.finditer(md):
        body = m.group(2)
        sm = _pre.STATUS_RE.search(body)
        if sm:
            st = sm.group(1)
            if _pre.SENT_RE.match(st) or _pre.MOOT_RE.search(st):
                continue    # tombstones — never stamped (§7)
        has_to = _brief.TO_RE.search(body) is not None
        has_brief = _brief.BRIEF_LINE_RE.search(body) is not None
        if has_to and has_brief:
            already += 1
            continue
        lines = []
        if not has_to:
            # ⭐ public #92 — `**Contact:**` FIRST (evidence already in the entry the
            # ORIGINAL version of this migration never consulted), `**Blocked until:**
            # contact:<id>` as the fallback. `precondition.resolve_entry_contact` owns both.
            pid = _pre.resolve_entry_contact(g, body)
            if pid:
                lines.append("**To:** contact:%s" % pid)
                attributed += 1
            else:
                lines.append("**To:** unaddressed")
                unaddressed_ct += 1
        if not has_brief:
            lines.append("**Brief:** none")
        # `m.start(2)` is the newline immediately after the `## title` line (ENTRY_RE's own
        # split, D3's precedent in precondition.py) — insert AFTER that newline, never before
        # it, or the stamped line would run onto the title itself.
        offset = m.start(2) + (1 if body.startswith("\n") else 0)
        inserts.append((offset, "\n".join(lines) + "\n"))

    if not apply_it:
        would = attributed + unaddressed_ct
        return True, ("  would stamp (0.46.0): %d entr%s (%d attributed, %d unaddressed), "
                      "%d already stamped"
                      % (would, "y" if would == 1 else "ies", attributed, unaddressed_ct,
                         already))

    if not os.path.exists(briefs_path):
        os.makedirs(os.path.dirname(briefs_path), exist_ok=True)
        open(briefs_path, "a").close()
        briefs_created = True

    if inserts:
        new_md = md
        for offset, text in sorted(inserts, key=lambda t: t[0], reverse=True):
            new_md = new_md[:offset] + text + new_md[offset:]
        import _atomic
        _atomic.write_text(path, new_md)

    result = _brief.rebrief(profile, probe=False)
    stamped = attributed + unaddressed_ct
    summary = ("%d entr%s stamped (%d attributed, %d unaddressed) · %d already stamped · "
              "%d rebriefed%s"
              % (stamped, "y" if stamped == 1 else "ies", attributed, unaddressed_ct, already,
                 result["rebriefed"], " · briefs.jsonl created" if briefs_created else ""))
    return True, ("  ✅ **To:**/**Brief:** (0.46.0) — %s\n"
                 "     next: ~/.claude/jobsearch/run brief.py --probe --held" % summary)
