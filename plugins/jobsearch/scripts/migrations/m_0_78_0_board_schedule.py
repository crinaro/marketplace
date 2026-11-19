"""Migration 0.78.0: `m_0_78_0_board_schedule()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_config import _load_config, _rewrite_config
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.78.0"


# ---- 0.78.0 (dev #770-4; design-employer-discovery.md §5.1, §6, owner rulings O4 and O5): the board-sweep schedule ---------
#
# WHY A MIGRATION. `board` becomes a real unattended token gated by two per-posture keys (O4): `company_days` (employer
# career pages, `company-site` channels) and `board_days` (job boards and aggregators). Every profile carries
# `search.postures` explicitly (seeded), so a read-time default would leave the gate refusing (`board` absent, the days keys
# missing) on every existing profile and today's UNGATED weekly board sweep would STOP: a silent regression. (O5 had
# this migration add `research` to economy; owner ruling O6 made research not posture-gated at all, so it no longer
# does, and no token is removed: a 0.77.0 engine sharing the profile keeps holding research on economy.) KEYED "0.78.0": 0.77.0 is the newest
# PUBLISHED jobsearch release (plugin.json read 0.77.0 and `jobsearch--v0.77.0` was the newest tag on base d8e2871; a
# profile that installed it is stamped exactly "0.77.0", and strict `<` would never fire a migration keyed to it).
#
# WHAT IT DOES (O4: EXISTING PROFILES MOVE TO THE NEW DAYS; it supersedes O3's keep-weekly). For each posture entry, in name
# order:
#   * `board` absent from `unattended`: added when the name is not `minimal` and `max_agents_per_run` is an integer >= 1,
#     the postures on which today's ungated weekly dispatch could already run. Otherwise left alone.
#   * `research` is never added (O6 supersedes O5: research is not posture-gated). A token is never removed.
#   * `company_days` / `board_days` absent: the 0.78.0 new-install values for a SHIPPED name (economy [mon] / [tue],
#     standard [mon, wed] / [tue, thu], full [mon, wed, fri] / [tue, thu, sat], read from
#     `config_keys.SEARCH_POSTURES_DEFAULT`), and economy's ([mon] / [tue]) for any other name -- on a posture that has
#     `board` after the first step; `[]` on every other (minimal, and a posture that cannot dispatch an agent).
#   * a key already present, however it got there, is left exactly as it is; a second run is a byte-identical no-op.
#   * a posture whose value is not an object, or whose `unattended` is present and not a list, is named in ONE `kind: system`
#     ask with a stable id (the `m_0_54_0_linkedin_quota` shape) and written nowhere. `search.postures` not an object
#     refuses the migration; missing entirely there is nothing to migrate (`doctor.py --fix` seeds the 0.78.0 defaults).
#
# PRESERVE, THEN TRANSFORM, THEN QUERY. Before the first write `config.json` is copied byte for byte to
# `config.json.pre-0.78.0` (never over a copy already there: that is the original of the FIRST run); a failed copy writes
# nothing. After the write the success condition is RE-READ from disk, and on any shortfall the bytes THIS run read just
# before its own write are put back (never `.pre-0.78.0`, which a user edit between two attempts would have outlived) and the
# result is PENDING (False), never a false "0 done".
#
# One printed line per posture says what was written and how to change it: `posture.py --set-company-days` /
# `--set-board-days`, the validated setters (never a hand edit). A second machine still on 0.77.0 reads the migrated config
# with one report line, `posture token 'board' ignored`, until it updates (ADR-012).
# ROLLBACK RISK: restoring `config.json.pre-0.78.0` undoes the migration for a file not edited since.
BOARD_SCHEDULE_PRE_COPY = "config.json.pre-0.78.0"
BOARD_SCHEDULE_ASK_ID = "system-board-schedule-unreadable"
BOARD_SCHEDULE_SHIPPED = ("economy", "standard", "full")       # the shipped names that sweep; minimal never does
BOARD_SCHEDULE_CUSTOM_AS = "economy"                           # the rule for a posture name the engine did not ship


def _board_schedule_days(ck, name, key):
    """The days a posture that sweeps gets for `key` (`company_days` / `board_days`): its own shipped defaults, or economy's
    for a name the engine did not ship."""
    shipped = name if name in BOARD_SCHEDULE_SHIPPED else BOARD_SCHEDULE_CUSTOM_AS
    return list(ck.SEARCH_POSTURES_DEFAULT[shipped][key])


def m_0_78_0_board_schedule(profile, apply_it, _inject_fault=None):
    """0.78.0 -- write `board`, `company_days` and `board_days` (O4) on existing postures (see the block
    above). `_inject_fault="shortfall"` is a TEST SEAM that makes the re-read check fail. Returns `(done, message)`."""
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return True, ""                  # no config.json at all: nothing to migrate
        return False, ("  ⏳ 0.78.0 PENDING -- config.json is unreadable, so the board schedule was not "
                       "written: %s" % err)
    if not isinstance(cfg, dict):
        return False, "  ⏳ 0.78.0 PENDING -- config.json is not a JSON object; nothing written."
    import config_keys as _ck

    search = cfg.get("search")
    if search is not None and not isinstance(search, dict):
        return False, "  ⏳ 0.78.0 PENDING -- config.json.search is not an object; the board schedule left alone."
    postures = (search or {}).get("postures")
    if postures is None:
        return True, ("  ⚠️ 0.78.0: config.json has no search.postures, so the board schedule was not written; "
                      "`doctor.py --fix` seeds the 0.78.0 defaults.")
    if not isinstance(postures, dict):
        return False, "  ⏳ 0.78.0 PENDING -- config.json.search.postures is not an object; the board schedule left alone."

    asks_path = os.path.join(profile, "data", "asks.jsonl")
    try:
        asks = _read_jsonl(asks_path) if os.path.exists(asks_path) else []
    except Exception as e:                                              # noqa: BLE001
        return False, "  ⏳ 0.78.0 PENDING -- asks.jsonl could not be read, nothing migrated: %s" % e

    keys = (_ck.COMPANY_DAYS, _ck.BOARD_DAYS)
    unreadable, plan = [], []            # plan: (name, add_tokens, {days_key: days})
    for name in sorted(postures):
        p = postures[name]
        if not isinstance(p, dict):
            unreadable.append(name)
            continue
        unattended = p.get("unattended")
        if unattended is not None and not isinstance(unattended, list):
            unreadable.append(name)
            continue
        unattended = unattended or []
        mx = p.get("max_agents_per_run")
        can_sweep = (name != "minimal" and isinstance(mx, int) and not isinstance(mx, bool) and mx >= 1)
        add = []
        if _ck.BOARD_TOKEN not in unattended and can_sweep:
            add.append(_ck.BOARD_TOKEN)
        has_board = _ck.BOARD_TOKEN in unattended or bool(add)
        days = {k: (_board_schedule_days(_ck, name, k) if has_board else [])
                for k in keys if k not in p}
        if add or days:
            plan.append((name, add, days))

    other_asks = [a for a in asks if a.get("id") != BOARD_SCHEDULE_ASK_ID]
    if unreadable:
        import datetime
        ask_row = {
            "id": BOARD_SCHEDULE_ASK_ID, "kind": "system",
            "title": "%d posture(s) cannot be read for the board-sweep schedule" % len(unreadable),
            "ask": ("search.postures.%s has no readable 'unattended' list, so board, company_days and board_days "
                    "could not be written there -- fix the posture's shape by hand "
                    "(design-employer-discovery.md §6)." % ", ".join(sorted(unreadable))),
            "created": datetime.date.today().isoformat(), "act_by": None, "opp_id": None,
            "channel_id": None, "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None,
        }
        new_asks = other_asks + [ask_row]
    else:
        new_asks = other_asks
    asks_changed = new_asks != asks

    if not plan and not asks_changed:
        return True, ""

    def _describe(entry):
        name, add, days = entry
        parts = []
        if add:
            parts.append("unattended += %s" % ", ".join(add))
        for k in keys:
            if k in days:
                parts.append("%s %s" % (k, json.dumps(days[k])))
        line = "  %s: %s" % (name, "; ".join(parts))
        if any(days.values()):
            line += ("; change with `~/.claude/jobsearch/run posture.py --set-company-days DAYS --posture %s` or "
                     "`--set-board-days DAYS --posture %s`" % (name, name))
        return line

    if not apply_it:
        lines = ["  would (0.78.0) " + _describe(e).strip() for e in plan]
        if asks_changed:
            lines.append("  would %s asks.jsonl %r" % ("write" if unreadable else "clear",
                                                      BOARD_SCHEDULE_ASK_ID))
        return True, "\n".join(lines)

    if asks_changed:
        rc, problems, new = _shadow_validate(profile, {"asks.jsonl": new_asks})
        if new is None or new:
            detail = "; ".join((new if new else (problems or []))[:8]) or (
                "validator exited %d with no problem list -- it crashed" % rc)
            return False, ("  ⏳ 0.78.0 PENDING -- the asks.jsonl write was REFUSED (a new validation problem), "
                           "so NOTHING was written: %s" % detail)

    if plan:
        try:
            with open(path, "rb") as fh:
                snapshot = fh.read()                 # the bytes THIS run read; what a shortfall puts back
        except OSError as e:
            return False, "  ⏳ 0.78.0 PENDING -- config.json could not be re-read (%s); nothing written." % e
        copy_path = os.path.join(profile, BOARD_SCHEDULE_PRE_COPY)
        if not os.path.exists(copy_path):
            try:
                shutil.copy2(path, copy_path)
            except (OSError, shutil.Error) as e:
                return False, ("  ⏳ 0.78.0 PENDING -- config.json could not be preserved to %s (%s), so "
                               "NOTHING was written." % (BOARD_SCHEDULE_PRE_COPY, e))
        for name, add, days in plan:
            if add:
                if not isinstance(postures[name].get("unattended"), list):
                    postures[name]["unattended"] = []
                postures[name]["unattended"].extend(add)
            for k, v in days.items():
                postures[name][k] = v
        _rewrite_config(path, cfg)
        # QUERY: the success condition is what the disk says now, not what was just written.
        _p, after, _e = _load_config(profile)
        after_postures = ((after or {}).get("search") or {}).get("postures") if isinstance(after, dict) else None
        short = []
        for name, add, days in plan:
            q = after_postures.get(name) if isinstance(after_postures, dict) else None
            if not isinstance(q, dict):
                short.append(name)
            elif any(t not in (q.get("unattended") or []) for t in add):
                short.append(name)
            elif any(q.get(k) != v for k, v in days.items()):
                short.append(name)
        if _inject_fault == "shortfall":
            short = short or [plan[0][0]]
        if short:
            with open(path, "wb") as fh:             # put back exactly what this run read
                fh.write(snapshot)
            return False, ("  ⏳ 0.78.0 PENDING -- %s still unwritten after the write; config.json was restored "
                           "(the original is also at %s); offered again next session."
                           % (", ".join(short), BOARD_SCHEDULE_PRE_COPY))

    if asks_changed:
        import _atomic
        _atomic.write_jsonl(asks_path, new_asks)

    lines = [_describe(e) for e in plan]
    if asks_changed:
        lines.append("  %s asks.jsonl %r" % ("wrote" if unreadable else "cleared", BOARD_SCHEDULE_ASK_ID))
    head = "  ✅ board schedule (0.78.0)" + (
        " -- config.json (the original is kept at %s)" % BOARD_SCHEDULE_PRE_COPY if plan else "")
    return True, "\n".join([head] + lines)
