"""Migration 0.67.0: `m_0_67_0_sourcing_screen_config_keys()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil
from migrations.support_config import _load_config, _rewrite_config
from migrations.support_jsonl import _read_asks_tolerant

VERSION = "0.67.0"


# ⭐⭐ KEYED "0.67.0" -- 0.66.0 is the newest jobsearch release at the branch base (plugin.json read
# 0.66.0 on base 209767d; the release_log's last row is jobsearch 0.66.0). A profile that installed
# 0.66.0 is stamped exactly "0.66.0", and pending_for()'s strict `<` fires a migration keyed to
# "0.67.0". Re-verify when 0.67.0 is actually cut (dev #713-#716 / public #142-#145). It runs LAST:
# it reads only config.json and asks.jsonl, which no earlier migration depends on it for.
SOURCING_SCREEN_PRE_COPY = "config.json.pre-0.67.0"
CURRENCY_ASK_ID = "set-compensation-currency"


def _currency_ask_row(today):
    """R1 -- the ONE `asks.jsonl` row asking the candidate to set `compensation.currency`.
    kind=system, a STABLE id so a re-run replaces it by id. It asks for a DECISION (which currency
    your floors are in), never for mechanical work, and it says what the absence costs."""
    return {"id": CURRENCY_ASK_ID, "kind": "system",
            "title": "Set the currency your pay floors are in",
            "ask": ("A listed pay range can only be compared with your floors when this profile "
                    "says which currency the floors are in, and '$' alone is ambiguous, so none "
                    "was assumed. Until you set compensation.currency in config.json to an ISO "
                    "4217 code (for example USD), every listed pay range screens "
                    "PAY-UNCOMPARABLE: kept for review, never cleared and never removed. Set the "
                    "key, then resolve this ask."),
            "created": today, "act_by": None, "opp_id": None, "channel_id": None,
            "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None}


def _reconcile_currency_ask(profile, key_present, apply_it, today):
    """File, refresh or close the `set-compensation-currency` ask. Returns `(error, what)`:
    `error` a plain-words reason asks.jsonl could not be handled, `what` one of "filed",
    "closed" or None (already as it should be). The key absent -> the ask is OPEN (a present row is
    replaced by id, `created` kept); the key present -> an open row is closed `resolution: set`."""
    path = os.path.join(profile, "data", "asks.jsonl")
    rows, err = _read_asks_tolerant(path)
    if err:
        return err, None
    have = next((r for r in rows if r.get("id") == CURRENCY_ASK_ID), None)
    if key_present:
        if have is None or have.get("resolved_on"):
            return None, None
        new = [dict(r, resolved_on=today, resolution="set") if r is have else r for r in rows]
        what = "closed"
    else:
        want = _currency_ask_row(have.get("created") if have and have.get("created") else today)
        if have == want:
            return None, None
        new = [want if r is have else r for r in rows] if have is not None else rows + [want]
        what = "filed"
    if apply_it:
        import _atomic
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic.write_jsonl(path, new)
    return None, what


def m_0_67_0_sourcing_screen_config_keys(profile, apply_it):
    """0.67.0 -- the sourcing screen's config keys (design-sourcing-screen.md §8, R1, R3, R8;
    dev #713-#716 / public #142-#145).

    Seeds, WHERE ABSENT and never over a value already there, the four scalar keys the
    sourcing screen reads (`config_keys.SOURCING_SCREEN_SEEDED`): `compensation.hybrid_inside_radius`
    = "band", `search.retained_search_age_days` = 35, `search.triage_per_run` = 10 and
    `search.triage_stuck_days` = 3 -- the `m_0_47_0_states_config_keys` precedent, because a
    registered key is seeded so the owner's file shows it. Bands and likely-pass signals are
    nested tables whose absence has a defined meaning, so they are not seeded.

    `compensation.currency` is NOT seeded (R1): "$" is ambiguous, so a seeded value would be a
    guess. Instead, whenever the key is absent, ONE `asks.jsonl` row (`kind=system`, id
    `set-compensation-currency`, replaced by id) asks the candidate to set it; an open row is
    closed when the key is present.

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. Before the first write `config.json` is copied
    byte-for-byte to `config.json.pre-0.67.0` (unless that copy exists); a failed copy writes
    nothing. Then the keys are seeded, and the success condition -- every seeded key now readable
    from disk -- is RE-READ rather than assumed. A MISSING `config.json` returns PENDING
    (False), never a false "0 done": the migration is offered again next session, when it exists.
    A section that is present but is not an object is left alone and reported, never replaced."""
    import datetime as _dt
    import config_keys as _ck
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return False, ("  ⏳ 0.67.0 PENDING -- %s does not exist yet, so the sourcing-screen "
                           "keys cannot be seeded; offered again next session." % path)
        return False, ("  ⏳ 0.67.0 PENDING -- config.json is unreadable, so nothing was "
                       "seeded: %s" % err)
    if not isinstance(cfg, dict):
        return False, "  ⏳ 0.67.0 PENDING -- config.json is not a JSON object; nothing seeded."
    lines, to_seed, blocked = [], [], []
    for section, key, default in _ck.SOURCING_SCREEN_SEEDED:
        node = cfg.get(section)
        if node is None:
            to_seed.append((section, key, default))
        elif not isinstance(node, dict):
            blocked.append("%s (is %s, not an object)" % (section, type(node).__name__))
        elif key not in node:
            to_seed.append((section, key, default))
    if blocked:
        lines.append("  ⚠️ left alone, not an object: %s" % "; ".join(blocked))
    if to_seed:
        label = ", ".join("%s.%s=%r" % t for t in to_seed)
        if not apply_it:
            lines.append("  would seed (0.67.0) config.json: %s" % label)
        else:
            copy_path = os.path.join(profile, SOURCING_SCREEN_PRE_COPY)
            if not os.path.exists(copy_path):
                try:
                    shutil.copy2(path, copy_path)
                except (OSError, shutil.Error) as e:
                    return False, ("  ⚠️ config.json could not be preserved to %s (%s), so "
                                   "NOTHING was seeded." % (SOURCING_SCREEN_PRE_COPY, e))
            for section, key, default in to_seed:
                cfg.setdefault(section, {})[key] = default
            _rewrite_config(path, cfg)
            lines.append("  ✅ config.json (0.67.0) -- seeded %s (the original is kept at %s)"
                         % (label, SOURCING_SCREEN_PRE_COPY))
            # QUERY: the success condition is what the disk says now, not what was just written.
            _p, after, _e = _load_config(profile)
            missing = [t for t in to_seed
                       if not isinstance(after, dict)
                       or not isinstance(after.get(t[0]), dict) or t[1] not in after[t[0]]]
            if missing:
                return False, "\n".join(lines + [
                    "  ⏳ 0.67.0 PENDING -- %s still absent after the write; offered again next "
                    "session." % ", ".join("%s.%s" % (t[0], t[1]) for t in missing)])
            cfg = after
    comp = cfg.get("compensation")
    key_present = isinstance(comp, dict) and comp.get("currency") is not None
    ask_err, what = _reconcile_currency_ask(profile, key_present, apply_it,
                                            _dt.date.today().isoformat())
    if ask_err:
        return False, "\n".join(lines + [
            "  ⏳ 0.67.0 PENDING -- data/asks.jsonl cannot be read (%s), so the "
            "compensation.currency ask was not handled; offered again next session." % ask_err])
    if what == "filed":
        lines.append("  %s ask %r: set compensation.currency (it is deliberately not seeded)"
                     % ("filed" if apply_it else "would file", CURRENCY_ASK_ID))
    elif what == "closed":
        lines.append("  %s ask %r: compensation.currency is set"
                     % ("closed" if apply_it else "would close", CURRENCY_ASK_ID))
    return True, "\n".join(lines)
