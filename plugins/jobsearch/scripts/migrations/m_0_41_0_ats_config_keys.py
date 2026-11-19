"""Migration 0.41.0: `m_0_41_0_ats_config_keys()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_config import _load_config, _merge_lists, _rewrite_config

VERSION = "0.41.0"


def m_0_41_0_ats_config_keys(profile, apply_it):
    """0.41.0 — `config.json.ats` carries the names a receipt reader resolves (design pass A,
    step 1; the names live in scripts/_ats_keys.py).

    `init_profile.py` seeded `ats.sender_domains` and `ats.receipt_phrases`; every profile
    that actually ran carried `receipt_sender_domains` and `receipt_subject_phrases`. Two
    spellings of one meaning is ADR-011's banned-alias defect one level up, in config: a
    reader written against the live names would find NOTHING on a freshly scaffolded profile
    and read that nothing as "no receipts configured" — public #56's class. The scaffold now
    seeds the live names; this renames the profiles it already scaffolded.

    ⭐ MERGE, NEVER DROP. Where only the old name exists it is renamed. Where BOTH exist —
    someone added the live name by hand while the seed sat there — the two lists are unioned
    in order (the live list first, then anything only the old one had) and the old key
    removed: a profile carrying both loses nothing. A pair that is not two lists (and not
    identical) is REPORTED, not touched — merging shapes this migration cannot read would be
    a guess written as data. Idempotent: the second run finds no old name and returns.
    """
    import _ats_keys
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return True, ""
        return False, "  ⚠️ config.json is unreadable, so ats keys were left alone: %s" % err
    ats = cfg.get("ats")
    if not isinstance(ats, dict):
        return True, ""
    done, refused = [], []
    for old, new in _ats_keys.LEGACY_RENAMES:
        if old not in ats:
            continue
        if new not in ats:
            ats[new] = ats.pop(old)
            done.append("%s -> %s" % (old, new))
        elif isinstance(ats[old], list) and isinstance(ats[new], list):
            before = len(ats[new])
            ats[new] = _merge_lists(ats[new], ats[old])
            del ats[old]
            done.append("%s merged into %s (%d value(s) carried over, none dropped)"
                        % (old, new, len(ats[new]) - before))
        elif ats[old] == ats[new]:
            del ats[old]
            done.append("%s removed (identical to %s)" % (old, new))
        else:
            refused.append("%s and %s both exist and are not two lists — merge them by hand"
                           % (old, new))
    if refused:
        return False, "  ⚠️ config.json.ats (0.41.0): " + "; ".join(refused)
    if not done:
        return True, ""
    if not apply_it:
        return True, "  would rename (0.41.0) config.json.ats: %s" % "; ".join(done)
    _rewrite_config(path, cfg)
    return True, "  ✅ config.json.ats (0.41.0) — %s" % "; ".join(done)
