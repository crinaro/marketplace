"""Migration 0.54.0: `m_0_54_0_linkedin_quota()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_config import _load_config, _rewrite_config
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.54.0"


# ── linkedin quota (design-script-first.md §2/§12, public #75/#76/#87/#110) ────────────────────
def m_0_54_0_linkedin_quota(profile, apply_it):
    """0.54.0 — design-script-first.md §2/§12, build-list item 3, decision 1/4:
    `config.json.search.postures.<name>.linkedin_runs_per_day` is written EXPLICITLY on every
    posture whose `unattended` list contains "linkedin" — 1 for each
    (`config_keys.LINKEDIN_RUNS_PER_DAY_DEFAULT`), 2 for `full` (decision 4's own carve-out,
    `full` keeping five daily runs but only two LinkedIn passes). "Explicitly" matters: this key
    already has a default `describe()` would apply silently, but a profile upgrading loses real
    cadence (`standard` goes from 3 unbounded LinkedIn sweeps/day to a 1/day quota) and that
    belongs in config.json where the owner can see and edit it, never left implicit (the same
    reasoning `m_0_47_0_states_config_keys` and `m_0_50_0_ats_config_keys` already state for
    their own knobs). Additive only — the `m_0_50_0_ats_config_keys` precedent: a posture that
    already carries the key, however it got there, is left exactly as it is; a second run is a
    byte-identical no-op.

    A posture entry this cannot safely read — its own value not an object, or `unattended`
    present and not a list — is not silently skipped and does not block every OTHER posture's
    seed either: it is named in ONE queryable `asks.jsonl` row (`kind: system`, stable id), the
    `m_0_48_0_application_endings_restamp` precedent (CLAUDE.md: "never N printed commands").
    The row is replaced with the fresh set on a re-run and removed outright once nothing is left
    unreadable. `search.postures` missing entirely, or not an object, refuses the whole
    migration (`_load_config`'s own "reported, never guessed" shape) — a profile that has never
    had a postures table is `doctor.py --fix`'s job, not this one's.
    """
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return True, ""
        return False, ("  ⚠️ config.json is unreadable, so linkedin_runs_per_day was left "
                       "alone: %s" % err)

    import config_keys as _ck

    search = cfg.get("search")
    if search is not None and not isinstance(search, dict):
        return False, "  ⚠️ config.json.search is not an object — linkedin_runs_per_day left alone"
    search = search or {}
    postures = search.get("postures")
    if postures is None:
        return True, ""            # nothing to seed — search.postures is missing entirely
    if not isinstance(postures, dict):
        return False, ("  ⚠️ config.json.search.postures is not an object — "
                       "linkedin_runs_per_day left alone")

    ASK_ID = "system-linkedin-quota-unreadable"
    asks_path = os.path.join(profile, "data", "asks.jsonl")
    try:
        asks = _read_jsonl(asks_path) if os.path.exists(asks_path) else []
    except Exception as e:                                              # noqa: BLE001
        return False, "  ⚠️ asks.jsonl could not be read — nothing migrated: %s" % e

    unreadable = []
    seeded = []
    for name in sorted(postures):
        p = postures[name]
        if not isinstance(p, dict):
            unreadable.append(name)
            continue
        unattended = p.get("unattended")
        if unattended is None:
            continue                # this posture has never named an unattended list at all
        if not isinstance(unattended, list):
            unreadable.append(name)
            continue
        if "linkedin" not in unattended:
            continue
        if _ck.LINKEDIN_RUNS_PER_DAY in p:
            continue                # additive only — already set, however it got there
        value = 2 if name == "full" else _ck.LINKEDIN_RUNS_PER_DAY_DEFAULT
        seeded.append((name, value))

    existing_ask = [a for a in asks if a.get("id") != ASK_ID]
    if unreadable:
        import datetime
        ask_row = {
            "id": ASK_ID, "kind": "system",
            "title": "%d posture(s) cannot be read for linkedin_runs_per_day" % len(unreadable),
            "ask": ("search.postures.%s has no readable 'unattended' list, so "
                   "linkedin_runs_per_day could not be seeded there — fix the posture's shape "
                   "by hand (design-script-first.md §2)." % ", ".join(sorted(unreadable))),
            "created": datetime.date.today().isoformat(), "act_by": None, "opp_id": None,
            "channel_id": None, "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None,
        }
        new_asks = existing_ask + [ask_row]
    else:
        new_asks = existing_ask
    asks_changed = new_asks != asks

    if not seeded and not asks_changed:
        return True, ""

    if not apply_it:
        bits = []
        if seeded:
            bits.append("seed %s" % ", ".join("%s.linkedin_runs_per_day=%d" % (n, v)
                                              for n, v in seeded))
        if asks_changed:
            bits.append("%s asks.jsonl %r"
                       % ("write" if unreadable else "clear", ASK_ID))
        return True, "  would (0.54.0) " + "; ".join(bits)

    if asks_changed:
        rc, problems, new = _shadow_validate(profile, {"asks.jsonl": new_asks})
        if new is None or new:
            detail = "; ".join((new if new else (problems or []))[:8]) or (
                "validator exited %d with no problem list — it crashed" % rc)
            return False, ("  ⚠️ 0.54.0 linkedin quota REFUSED asks.jsonl write — a new "
                          "validation problem, so NOTHING was written: %s" % detail)

    for name, value in seeded:
        postures[name][_ck.LINKEDIN_RUNS_PER_DAY] = value
    if seeded:
        _rewrite_config(path, cfg)

    if asks_changed:
        import _atomic
        _atomic.write_jsonl(asks_path, new_asks)

    bits = []
    if seeded:
        bits.append("seeded %s" % ", ".join("%s.linkedin_runs_per_day=%d" % (n, v)
                                            for n, v in seeded))
    if asks_changed:
        bits.append("%s asks.jsonl %r" % ("wrote" if unreadable else "cleared", ASK_ID))
    return True, "  ✅ linkedin quota (0.54.0) — " + "; ".join(bits)
