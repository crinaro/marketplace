"""Migration 0.47.0: `m_0_47_0_drafts_working_set()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.47.0"


def m_0_47_0_drafts_working_set(profile, apply_it, today=None):
    """0.47.0 — States & Views V1b, design-states-and-views.md §4: `drafts.md` becomes the
    working set and nothing else. PRESERVE, THEN TRANSFORM (the standing rule): every
    TERMINAL (sent/moot) entry either DELETES (a matching `outreach[]`/`messages.jsonl` row
    already records the fact) or RELOCATES — its paragraph becomes a `research_log[]` row on
    the opportunity `**Triggered by:**` names, or a `channels[].log[]` row when the entry
    addresses only a channel-anchored person — never dropped, always counted
    (`precondition.plan_prune`, the SAME decision core `--prune` uses, so the migration and
    the CLI can never answer "what does this tombstone relocate to" two different ways).

    An entry with NEITHER anchor is left exactly where it is, reported, and counted —
    refusing to guess an anchor is the ONE thing this migration will not do automatically,
    and it says so loudly (the standing rule: a migration that refuses has not shipped
    either — this one refuses NOTHING, it just cannot invent a home).

    The header above the first `## ` entry is replaced with the GENERATED preamble
    (`precondition.format_header()`), so it stops being prose someone maintains by hand.

    ALL-OR-NOTHING for the JSONL half: every relocation is built in memory first and
    shadow-validated (`_shadow_validate`, the B1/B2 precedent) before a single real byte
    moves; a relocation that would introduce a new problem writes nothing at all, and
    drafts.md itself is untouched in that case either (never delete/relocate a paragraph out
    of the working set on the strength of a write that did not actually land).

    Idempotent: a second run finds no TERMINAL entries left to relocate/delete and a preamble
    that already matches `format_header()` byte for byte, and reports a no-op.

    `today` is test-only (never passed by the MIGRATIONS runner, which calls every migration
    with exactly `(profile, apply_it=...)`): a MOOT tombstone's relocated `research_log[]` row
    is dated `today` when its own Status line names no date (most don't), so the golden-output
    test (`TestV1bMigrationGoldenOutput`) pins it to the date the committed `post-v1b` fixture
    was generated on — real runs always take the actual date.
    """
    import precondition as _pre
    drafts_path = _pre._tree.resolve_rel(profile, _pre.FILES[0])
    if not os.path.exists(drafts_path):
        return True, ""
    plan = _pre.plan_prune(profile, today=today)
    if plan["new_text"] is None:
        return True, ""

    header_ok = (_pre._preamble_text(plan["new_text"]).rstrip("\n")
                == _pre.format_header().rstrip("\n"))
    n_relocated, n_deleted, n_unresolved = (len(plan["relocations"]), len(plan["deleted_only"]),
                                            len(plan["unresolved"]))
    if not n_relocated and not n_deleted and header_ok:
        return True, ""

    if not apply_it:
        parts = []
        if n_relocated:
            parts.append("%d relocated to research_log[]/channels[].log[]" % n_relocated)
        if n_deleted:
            parts.append("%d deleted (a row already exists)" % n_deleted)
        if n_unresolved:
            parts.append("%d left in place — no resolvable anchor" % n_unresolved)
        if not header_ok:
            parts.append("preamble regenerated")
        return True, "  would migrate (0.47.0) drafts.md working set: %s" % "; ".join(parts)

    opps_path = os.path.join(profile, "data", "opportunities.jsonl")
    chans_path = os.path.join(profile, "data", "channels.jsonl")
    try:
        opps = _read_jsonl(opps_path) if os.path.exists(opps_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e
    try:
        chans = _read_jsonl(chans_path) if os.path.exists(chans_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ channels.jsonl could not be read — nothing migrated: %s" % e
    opps_by_id = {o.get("id"): o for o in opps}
    chans_by_id = {c.get("id"): c for c in chans}
    for r in plan["relocations"]:
        rec = (opps_by_id if r["anchor_kind"] == "opp" else chans_by_id).get(r["anchor_id"])
        if rec is None:
            # plan_prune resolves an anchor against THIS SAME profile, so this is not
            # expected to happen — defensive rather than assumed (the m_0_45_0 precedent).
            return False, ("  ⚠️ %s:%s no longer resolves — nothing migrated (re-run after "
                          "investigating)" % (r["anchor_kind"], r["anchor_id"]))
        arr = "research_log" if r["anchor_kind"] == "opp" else "log"
        rec.setdefault(arr, []).append(r["row"])

    if plan["relocations"]:
        rc, _problems, new = _shadow_validate(profile, {"opportunities.jsonl": opps,
                                                         "channels.jsonl": chans})
        if rc != 0 and new:
            return False, ("  ⚠️ this migration would introduce %d new problem(s) — nothing "
                          "written: %s" % (len(new), "; ".join(new[:5])))
        import _atomic
        _atomic.write_jsonl(opps_path, opps)
        _atomic.write_jsonl(chans_path, chans)

    rest = plan["new_text"][len(_pre._preamble_text(plan["new_text"])):]
    final_text = _pre.format_header() + rest
    import _atomic
    _atomic.write_text(drafts_path, final_text)

    msg = ["  ✅ drafts.md working set (0.47.0) — %d relocated, %d deleted (a row already "
          "existed), preamble regenerated" % (n_relocated, n_deleted)]
    if n_unresolved:
        msg.append("  ℹ️ %d TERMINAL entr%s left in place — no resolvable anchor: %s"
                  % (n_unresolved, "y" if n_unresolved == 1 else "ies",
                     ", ".join(t for t, _r, _w in plan["unresolved"])[:200]))
    return True, "\n".join(msg)
