"""Migration 0.47.0: `m_0_47_0_states_config_keys()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_config import _load_config, _rewrite_config

VERSION = "0.47.0"


def m_0_47_0_states_config_keys(profile, apply_it):
    """0.47.0 — States & Views V1 §15.7: seeds `config.json.ats.silence_days` and
    `config.json.ats.close` with the registry's own defaults (`config_keys.py`) where
    absent — the `m_0_41_0_ats_config_keys` precedent — so the two settings the owner asked
    to make configurable ("make sure the is a configurable setting") are visible in the owner's file
    literally, not only in the registry's defaults. Additive only; never overwrites a value
    already there, however it got there. `communications.chase_after_days` needs no seed
    here — every profile pre-dating C1 already carries it (config_keys.py's own docstring)."""
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
    if "silence_days" not in ats:
        ats["silence_days"] = _ck.ATS_SILENCE_DAYS_DEFAULT
        seeded.append("ats.silence_days=%s" % _ck.ATS_SILENCE_DAYS_DEFAULT)
    if "close" not in ats:
        ats["close"] = _ck.ATS_CLOSE_DEFAULT
        seeded.append("ats.close=%r" % _ck.ATS_CLOSE_DEFAULT)
    if not seeded:
        return True, ""
    if not apply_it:
        return True, "  would seed (0.47.0) config.json.ats: %s" % ", ".join(seeded)
    cfg["ats"] = ats
    _rewrite_config(path, cfg)
    return True, "  ✅ config.json.ats (0.47.0) — seeded %s" % ", ".join(seeded)
