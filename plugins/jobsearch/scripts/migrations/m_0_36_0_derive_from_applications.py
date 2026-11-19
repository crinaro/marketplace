"""Migration 0.36.0: `m_0_36_0_derive_from_applications()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl, _rewrite_jsonl

VERSION = "0.36.0"


def m_0_36_0_derive_from_applications(profile, apply_it):
    """0.36.0 — two fields the store could already prove, written from applications[]
    (dev/audit 2026-09-02, Class A: public #42 and #44).

    * `play_stage: unresolved` (m_0_25_0's marker, "a human must name the stage") is
      resolved by `your_move.derive_play_stage`: a submitted application → `applied` (the
      floor the evidence proves; a finer position stays human-authored, and the prose on
      the record still carries it), none → `needs-application`. Deterministic, so a run
      writes it — it was a printed `record.py set …` instruction to the user for 0.25.0
      through 0.35.0, and a change ships as a version, never as an instruction.
    * `verdict: undecided` on a row whose applications[] proves a submission becomes
      `pursue` — the human decided by applying; the field never followed, and Your Move
      went on asking pursue-or-pass about a role already applied to.

    PRESERVE, THEN TRANSFORM: nothing else on the row changes; both writes are reversible
    from git. Terminal rows (validate_data.TERMINAL_OPP_STATUSES) are never touched — the
    validator refuses a play position on one. Idempotent: a second run finds nothing.

    ⭐ ADR-031 B2 (2026-09-11): this function keeps its OWN small copy of the submitted/
    play-stage predicates (`_legacy_submitted`/`_legacy_play_stage` below) rather than calling
    `your_move.has_submitted_application`/`derive_play_stage`. Those two now read an explicit
    applications LIST (the caller's join against the promoted top-level store — B2 retired the
    nested-array reading they used to do internally), but THIS migration always runs against
    the PRE-B2 shape: it is keyed 0.36.0, B2's own promotion (m_0_45_0) always runs LATER in
    MIGRATIONS, and a profile reaching this function has not had `applications[]` promoted away
    yet. Depending on the promoted-store API here would be backwards — this migration is one of
    the two legitimate remaining readers of the nested key
    (`check_retired_reads.KNOWN_EXCEPTIONS` names this file for exactly this)."""
    import validate_data as _vd

    def _legacy_submitted(r):
        return any(a.get("status") in _vd.SUBMITTED_APP_STATUS
                   for a in (r.get("applications") or []))

    def _legacy_play_stage(r):
        return "applied" if _legacy_submitted(r) else "needs-application"

    path = os.path.join(profile, "data", "opportunities.jsonl")
    if not os.path.exists(path):
        return True, ""
    try:
        rows = _read_jsonl(path)
    except Exception as e:
        return False, ("  ⚠️ opportunities.jsonl could not be read, so nothing was derived "
                       "from applications[]: %s" % e)
    played, decided = [], []
    for r in rows:
        if r.get("status") in _vd.TERMINAL_OPP_STATUSES:
            continue
        if r.get("play_stage") == "unresolved":
            r["play_stage"] = _legacy_play_stage(r)
            played.append("%s→%s" % (r.get("id", "?"), r["play_stage"]))
        if r.get("verdict") == "undecided" and _legacy_submitted(r):
            r["verdict"] = "pursue"
            decided.append(r.get("id", "?"))
    if not (played or decided):
        return True, ""
    bits = []
    if played:
        bits.append("play_stage derived from applications[] on %d role(s): %s"
                    % (len(played), "; ".join(played)[:300]))
    if decided:
        bits.append("verdict undecided→pursue on %d role(s) with a submitted application: %s"
                    % (len(decided), "; ".join(decided)[:300]))
    if not apply_it:
        return True, "  would derive from applications[] (0.36.0): " + " · ".join(bits)
    _rewrite_jsonl(path, rows)
    return True, "  ✅ opportunities.jsonl (0.36.0): " + " · ".join(bits)
