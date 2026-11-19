"""Migration 0.50.0: `m_0_50_0_geography_keys()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_config import _load_config, _merge_lists, _rewrite_config

VERSION = "0.50.0"


# ── geo_screen (public #89, dev #355) ──────────────────────────────────────────────────────────
def m_0_50_0_geography_keys(profile, apply_it):
    """0.50.0 — public #89 / dev #355: `config.json.geography` carries the shape every profile
    actually derived from a resume already has (`relocation.{open, affirmative_destinations}`,
    `commute_anchors[].max_commute_minutes`) — `init_profile.py` scaffolded a DIFFERENT shape
    (`relocation_open_to`, `radius_minutes`) that no shipped script has ever read. Same defect
    class as `m_0_41_0_ats_config_keys` — two spellings of one meaning, config.geography instead
    of config.ats — and the reason public #89's daily-run triage answered from memory: there was
    nothing for it to consult even if it had tried to read the live names.

    ⭐ MERGE, NEVER DROP. `relocation_open_to` (the destinations the candidate named as open to)
    becomes `relocation.affirmative_destinations` — renamed outright when only the old key
    exists, unioned in order (the existing list first, then anything only the old one had) when
    both already exist, the same precedent `m_0_41_0_ats_config_keys` set for `ats.*`.
    `radius_minutes` (one global commute radius) seeds `max_commute_minutes` on every
    `commute_anchors[]` entry that does not already carry its own — an anchor that already
    states its own minutes keeps it, never overwritten. `relocation.open` is then seeded True
    when the merged `affirmative_destinations` ends up non-empty, False otherwise — never
    guessed True from an empty list, the same caution `effective_setting()` already applies to
    an unrecognized commute location (never default to "relocation").

    A shape this cannot read — `relocation_open_to` not a list, `geography.relocation` present
    and not an object, `radius_minutes` not a number, `commute_anchors` not a list of objects —
    is REPORTED, not overwritten, exactly the `m_0_41_0_ats_config_keys` refusal shape. Runs
    only when at least one old key is present; idempotent, the second run finds neither and
    returns.
    """
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return True, ""
        return False, ("  ⚠️ config.json is unreadable, so geography keys were left alone: %s"
                       % err)
    geo = cfg.get("geography")
    if not isinstance(geo, dict):
        return True, ""

    has_old_dest = "relocation_open_to" in geo
    has_old_radius = "radius_minutes" in geo
    if not has_old_dest and not has_old_radius:
        return True, ""

    old_dest = geo.get("relocation_open_to")
    relocation = geo.get("relocation")
    old_radius = geo.get("radius_minutes")
    anchors = geo.get("commute_anchors")

    refused = []
    if has_old_dest and not isinstance(old_dest, list):
        refused.append("geography.relocation_open_to is not a list — merge it by hand")
    if relocation is not None and not isinstance(relocation, dict):
        refused.append("geography.relocation exists and is not an object — merge it by hand")
    if has_old_radius and not isinstance(old_radius, (int, float)):
        refused.append("geography.radius_minutes is not a number — merge it by hand")
    if has_old_radius:
        if anchors is not None and not isinstance(anchors, list):
            refused.append("geography.commute_anchors is not a list — merge it by hand")
        elif isinstance(anchors, list):
            for i, a in enumerate(anchors):
                if not isinstance(a, dict):
                    refused.append("geography.commute_anchors[%d] is not an object — merge it "
                                   "by hand" % i)
    if refused:
        return False, "  ⚠️ config.json.geography (0.50.0): " + "; ".join(refused)

    if not isinstance(relocation, dict):
        relocation = {}
    done = []

    if has_old_dest:
        existing = relocation.get("affirmative_destinations")
        if isinstance(existing, list):
            before = len(existing)
            relocation["affirmative_destinations"] = _merge_lists(existing, old_dest)
            done.append("relocation_open_to merged into relocation.affirmative_destinations "
                        "(%d value(s) carried over, none dropped)"
                        % (len(relocation["affirmative_destinations"]) - before))
        else:
            relocation["affirmative_destinations"] = list(old_dest)
            done.append("relocation_open_to -> relocation.affirmative_destinations")
        del geo["relocation_open_to"]

    if has_old_radius:
        seeded_anchors = 0
        if isinstance(anchors, list):
            for a in anchors:
                if "max_commute_minutes" not in a:
                    a["max_commute_minutes"] = old_radius
                    seeded_anchors += 1
        del geo["radius_minutes"]
        done.append("radius_minutes -> max_commute_minutes on %d anchor(s) lacking their own"
                    % seeded_anchors)

    if "open" not in relocation:
        relocation["open"] = bool(relocation.get("affirmative_destinations"))
        done.append("relocation.open seeded %r" % relocation["open"])

    geo["relocation"] = relocation

    if not apply_it:
        return True, "  would rename (0.50.0) config.json.geography: %s" % "; ".join(done)
    cfg["geography"] = geo
    _rewrite_config(path, cfg)
    return True, "  ✅ config.json.geography (0.50.0) — %s" % "; ".join(done)
