"""Migration 0.50.0: `m_0_50_0_ats_config_keys()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_config import _load_config, _rewrite_config

VERSION = "0.50.0"


def m_0_50_0_ats_config_keys(profile, apply_it):
    """0.50.0 — design-inbound-resolution.md §5.2: seeds `config.json.ats.parsed_status`,
    `ats.sweep_days` and `ats.max_asks_per_run` with the registry's own defaults
    (`config_keys.py`) where absent — the `m_0_47_0_states_config_keys` precedent, verbatim
    shape, applied to the three new knobs `reconcile.py --ats` reads. Additive only; never
    overwrites a value already there, however it got there."""
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return True, ""
        return False, "  ⚠️ config.json is unreadable, so ats keys were left alone: %s" % err
    import config_keys as _ck
    ats = cfg.get("ats")
    if not isinstance(ats, dict):
        ats = {}
    seeded = []
    if "parsed_status" not in ats:
        ats["parsed_status"] = _ck.ATS_PARSED_STATUS_DEFAULT
        seeded.append("ats.parsed_status=%r" % _ck.ATS_PARSED_STATUS_DEFAULT)
    if "sweep_days" not in ats:
        ats["sweep_days"] = _ck.ATS_SWEEP_DAYS_DEFAULT
        seeded.append("ats.sweep_days=%s" % _ck.ATS_SWEEP_DAYS_DEFAULT)
    if "max_asks_per_run" not in ats:
        ats["max_asks_per_run"] = _ck.ATS_MAX_ASKS_PER_RUN_DEFAULT
        seeded.append("ats.max_asks_per_run=%s" % _ck.ATS_MAX_ASKS_PER_RUN_DEFAULT)
    if not seeded:
        return True, ""
    if not apply_it:
        return True, "  would seed (0.50.0) config.json.ats: %s" % ", ".join(seeded)
    cfg["ats"] = ats
    _rewrite_config(path, cfg)
    return True, "  ✅ config.json.ats (0.50.0) — seeded %s" % ", ".join(seeded)
