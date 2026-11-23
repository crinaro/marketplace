"""app_endings: why a pursuit stopped (`ended_because`), moved out of `your_move.py` unchanged
(design-presence-report.md §11 B0) so a capability module can read the ending vocabulary without
importing an entry point. `your_move` re-exports it."""


def ended_because(opp, apps):
    """§2b — why a pursuit STOPPED, or `None` if it is still live. `apps` is this
    opportunity's own slice of the top-level applications store (same contract as
    `has_submitted_application` — `applications.group_by_opp(...)[opp_id]`, or `[]`).

    Precedence, top to bottom (§2b's table, RE-ORDERED 2026-09-13 — public #94): `rejected`
    (the employer said no) > `closed-silence` (we closed it after ATS silence, §3c) >
    `withdrawn` (they did, after applying) > `expired` (the posting vanished) >
    `unrecorded` (a submitted application on a now-terminal opportunity, with nothing saying
    why it ended) > `passed` (a verdict of `pass`, or an opportunity `status: passed` — they,
    or we, walked away before applying) > `unrecorded` a second time (a `stage: closed` req
    with NO application and NO passed verdict either — genuinely nothing says why).

    ⭐ `passed` now runs BEFORE the second `unrecorded` check, not after. Before this fix a
    closed-and-never-applied-to opportunity that WAS in fact passed on (`verdict: pass`) hit
    the `stage == closed and not past_started` branch first and read as `unrecorded` — the
    exact shape public #94 traced the migration's over-count to (`m_0_47_0_application_
    endings` only ever printed what this function returned). A `passed` verdict is a fact
    already on hand; treating it as merely "closed" threw that fact away. Each fact stays
    where it already lives (application status vs. opportunity status/stage/verdict); this
    only composes them, and never invents a reason a value older than this vocabulary should
    have recorded (§3d)."""
    apps = sorted(apps or [], key=lambda a: str(a.get("date") or ""))
    newest = apps[-1] if apps else None
    app_status = newest.get("status") if newest else None
    opp_status = opp.get("status")
    stage = opp.get("stage")
    verdict = opp.get("verdict")

    if app_status == "rejected":
        return "rejected"
    if app_status == "closed":
        return "closed-silence"
    if app_status == "withdrawn":
        return "withdrawn"
    if opp_status == "expired":
        return "expired"

    terminal_opp = opp_status == "passed" or stage == "closed"
    submitted_like = app_status in ("submitted", "acknowledged", "advanced")
    past_started = any((a.get("status") or "not-started") not in ("not-started", "started")
                       for a in apps)
    if terminal_opp and submitted_like:
        return "unrecorded"

    # ⭐ public #94 — MOVED ABOVE the `stage == "closed"` catch-all below: a passed verdict is
    # a fact already on hand and must win over a bare "it's closed" guess.
    if (verdict == "pass" or opp_status == "passed") and not past_started:
        return "passed"

    if stage == "closed" and not past_started:
        # §15.4 finding 6 — a dead req with NO application at all is not "still pursuing".
        # Nothing says whether they passed or the posting vanished, so this is unrecorded too,
        # never guessed as `expired` (only the posting's OWN status says that) — and, since
        # the `passed` check above already ran, never guessed as `passed` either: this is
        # reached only when NEITHER a verdict nor a status says why.
        return "unrecorded"

    return None
