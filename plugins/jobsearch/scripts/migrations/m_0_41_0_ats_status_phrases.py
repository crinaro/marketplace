"""Migration 0.41.0: `m_0_41_0_ats_status_phrases()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_config import _load_config, _merge_lists, _rewrite_config

VERSION = "0.41.0"


def m_0_41_0_ats_status_phrases(profile, apply_it):
    """0.41.0 — `config.json.ats.status_phrases` exists on every profile, keyed by the
    application status a receipt subject evidences, and the acknowledged-receipt phrases move
    into it (design pass A, step 1).

    `receipt_subject_phrases` was one flat list that could only ever mean "acknowledged". A
    reader that also recognises a rejection or an advance needs the phrases keyed by the
    status they evidence — one shape for every status, so none is a special case.

    ⭐ PRESERVE, THEN TRANSFORM. The existing list is carried into `status_phrases.acknowledged`
    (unioned in order if that list already exists — nothing dropped) and only THEN is the old
    key removed; the other status lists are seeded empty so a reader finds the SHAPE and can
    say "no phrases configured for rejected" instead of finding nothing at all. A profile with
    no `ats` object gets one carrying only `status_phrases` — `receipt_sender_domains` is
    deliberately NOT seeded here, because an empty domain list reads as "configured, empty"
    when the truth is "never configured"; the reader asserts that at start-up. A
    `status_phrases` that is not an object, or a phrase list that is not a list, is REPORTED,
    not overwritten. Runs AFTER m_0_41_0_ats_config_keys on purpose: the rename produces the
    key this moves. Idempotent: the second run finds the shape and no old key.
    """
    import _ats_keys
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return True, ""
        return False, ("  ⚠️ config.json is unreadable, so status_phrases was left "
                       "unseeded: %s" % err)
    ats = cfg.get("ats")
    if ats is None:
        ats = cfg["ats"] = {}
    if not isinstance(ats, dict):
        return False, "  ⚠️ config.json.ats is not an object — status_phrases could not be seeded"
    created = _ats_keys.STATUS_PHRASES not in ats
    sp = {} if created else ats[_ats_keys.STATUS_PHRASES]
    if not isinstance(sp, dict):
        return False, ("  ⚠️ config.json.ats.%s exists but is not an object — left alone; "
                       "make it {status: [phrases]}" % _ats_keys.STATUS_PHRASES)
    done = ["created status_phrases"] if created else []
    seeded = []
    for k in _ats_keys.STATUS_PHRASE_KEYS:
        if k not in sp:
            sp[k] = []
            seeded.append(k)
        elif not isinstance(sp[k], list):
            return False, ("  ⚠️ config.json.ats.%s.%s is not a list — left alone"
                           % (_ats_keys.STATUS_PHRASES, k))
    if seeded:
        done.append("seeded empty %s" % ", ".join(seeded))
    old = _ats_keys.RECEIPT_SUBJECT_PHRASES
    if old in ats:
        if not isinstance(ats[old], list):
            return False, ("  ⚠️ config.json.ats.%s is not a list — left alone; move it into "
                           "%s.acknowledged by hand" % (old, _ats_keys.STATUS_PHRASES))
        before = len(sp["acknowledged"])
        sp["acknowledged"] = _merge_lists(sp["acknowledged"], ats[old])
        done.append("moved %d phrase(s) from %s into %s.acknowledged (%d new, none dropped)"
                    % (len(ats[old]), old, _ats_keys.STATUS_PHRASES,
                       len(sp["acknowledged"]) - before))
        del ats[old]
    if not done:
        return True, ""
    if created:
        ats[_ats_keys.STATUS_PHRASES] = sp
    if not apply_it:
        return True, "  would seed (0.41.0) config.json.ats: %s" % "; ".join(done)
    _rewrite_config(path, cfg)
    return True, "  ✅ config.json.ats (0.41.0) — %s" % "; ".join(done)
