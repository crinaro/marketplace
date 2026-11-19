"""Migration 0.82.0: `m_0_82_0_role_lifecycle()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil
from migrations.support_config import _load_config, _rewrite_config
from migrations.support_uid import _uid_text_read
from migrations.support_validate import _shadow_validate

VERSION = "0.82.0"


# ⭐⭐ KEYED "0.82.0" (dev #820 / public #175; design-role-pipeline.md section 9) -- 0.81.0 is the newest
# jobsearch release at the branch base (plugin.json read 0.81.0 on 89ecfcf7; `jobsearch--v0.81.0` is
# tagged and no 0.82.0 tag exists on the public remote). A profile that installed 0.81.0 is stamped
# exactly "0.81.0", and pending_for()'s strict `<` fires a migration keyed to "0.82.0". Re-verify at the
# moment 0.82.0 is cut. It runs LAST; it touches data/opportunities.jsonl (the new `jd_read`) and
# config.json (the intake keys and the feed deadline), and nothing else.
ROLE_LIFECYCLE_OPPS_PRE_COPY = "opportunities.jsonl.pre-0.82.0"
ROLE_LIFECYCLE_CONFIG_PRE_COPY = "config.json.pre-0.82.0"
ROLE_LIFECYCLE_RETIRED_KEY = "_retired_0_82_0"
ROLE_LIFECYCLE_OLD_INTAKE_DEFAULT = 10          # search.triage_per_run's old default (reads per run)
ROLE_LIFECYCLE_NEW_INTAKE_DEFAULT = 40          # owner ruling 7: "Raise 10 to the new default"


def _role_lifecycle_config_plan(cfg):
    """`(writes, notes, problem)` for the config half of the 0.82.0 migration, a PURE function of the
    loaded config. `writes` is a list of `(description, apply_fn)`; `problem` is a string when the config
    has a shape this refuses to guess over (the migration is then PENDING, nothing written)."""
    import copy as _copy
    writes, notes = [], []
    search = cfg.get("search")
    if search is not None and not isinstance(search, dict):
        return [], [], "config.json.search is not an object"
    search = search or {}
    sourcing = cfg.get("sourcing")
    if sourcing is not None and not isinstance(sourcing, dict):
        return [], [], "config.json.sourcing is not an object"
    feeds = (sourcing or {}).get("feeds")
    if feeds is not None and not isinstance(feeds, dict):
        return [], [], "config.json.sourcing.feeds is not an object"
    retired = search.get(ROLE_LIFECYCLE_RETIRED_KEY)
    if retired is not None and not isinstance(retired, dict):
        return [], [], "config.json.search.%s is not an object" % ROLE_LIFECYCLE_RETIRED_KEY

    def move_aside(key):
        def apply(c):
            sr = c.setdefault("search", {})
            rt = sr.setdefault(ROLE_LIFECYCLE_RETIRED_KEY, {})
            rt.setdefault(key, _copy.deepcopy(sr[key]))      # a copy already there is the true original
            del sr[key]
        return apply

    if "triage_per_run" in search:
        old = search["triage_per_run"]
        has_new = "intake_per_run" in search
        valid = isinstance(old, int) and not isinstance(old, bool) and 1 <= old <= 300
        if has_new:
            desc = ("search.triage_per_run %r moved aside (search.intake_per_run is already set to %r and "
                    "stays)" % (old, search["intake_per_run"]))
            writes.append((desc, move_aside("triage_per_run")))
        elif old == ROLE_LIFECYCLE_OLD_INTAKE_DEFAULT:
            def apply_raise(c, _mv=move_aside("triage_per_run")):
                c["search"]["intake_per_run"] = ROLE_LIFECYCLE_NEW_INTAKE_DEFAULT
                _mv(c)
            writes.append(("search.triage_per_run 10 became search.intake_per_run %d (raised from the old "
                           "default: it now counts roles admitted per run, not reads; owner ruling 7)"
                           % ROLE_LIFECYCLE_NEW_INTAKE_DEFAULT, apply_raise))
        elif valid:
            def apply_copy(c, _mv=move_aside("triage_per_run"), _v=old):
                c["search"]["intake_per_run"] = _v
                _mv(c)
            writes.append(("search.triage_per_run %d copied to search.intake_per_run %d (your own choice, "
                           "kept)" % (old, old), apply_copy))
        else:
            writes.append(("search.triage_per_run %r is not a number 1-300, so it was moved aside and "
                           "search.intake_per_run takes the default (%d)"
                           % (old, ROLE_LIFECYCLE_NEW_INTAKE_DEFAULT), move_aside("triage_per_run")))
    if "triage_stuck_days" in search:
        writes.append(("search.triage_stuck_days %r moved aside (a role that is not read is now a visible "
                       "process failure, not a role waiting out a timer)" % (search["triage_stuck_days"],),
                       move_aside("triage_stuck_days")))
    if "deadline_s" not in (feeds or {}):               # whatever is there, even a bad value, is the owner's
        def seed(c):
            c.setdefault("sourcing", {}).setdefault("feeds", {})["deadline_s"] = 240
        writes.append(("sourcing.feeds.deadline_s 240 seeded (the feed poll's deadline was fixed at 240 "
                       "seconds; it is now yours to set, 60-1800)", seed))
    return writes, notes, None


def m_0_82_0_role_lifecycle(profile, apply_it, _inject_fault=None):
    """0.82.0 -- one stored read record, and the intake keys (dev #820 / public #175 and #813 / #168;
    design-role-pipeline.md section 9, owner rulings 6 and 7).

    WHAT IT DOES
      1. Every opportunity with NO `jd_read`, a `fit.analyzed_on` and a non-empty string `fit.jd_source`
         gets `jd_read.attempts = [{at: <analyzed_on>T00:00:00, run: "legacy", url: <jd_url or null>,
         via: "legacy", outcome, evidence: {legacy: "fit.jd_source=<value, at most 200 characters>"}}]`.
         `outcome` is `read` for a plain source, or the mapped reason for `unavailable: <reason>` when the
         reason is in the 0.67.0 closed set. A value that cannot be mapped (an `unavailable:` reason
         outside the set, an `analyzed_on` that is no date) writes NOTHING for that role and is COUNTED
         and NAMED: it stays an unread process failure (`legacy-backlog`) rather than becoming a read
         nobody made. `fit` is never modified. Without this, every role read before 0.82.0 would show
         as an unread process failure on the day of the upgrade.
      2. `search.triage_per_run` becomes `search.intake_per_run`: a stored exactly `10` is raised to
         `40` (ruling 7: "Raise 10 to the new default"), any other whole number 1-300 is the owner's
         choice and is copied as it is, and the old key is moved to `search._retired_0_82_0.triage_per_run`.
         `search.triage_stuck_days` moves to `search._retired_0_82_0.triage_stuck_days`. An absent old
         key writes nothing: the default (40) applies. If `search.intake_per_run` is already set it
         stays and the old key is still moved aside.
      3. `sourcing.feeds.deadline_s: 240` is seeded where absent (it was a fixed constant).
         `search.intake_new_percent` is NOT seeded: absent means 50.

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. Before the first write `data/opportunities.jsonl` is copied
    byte for byte to `data/opportunities.jsonl.pre-0.82.0` and `config.json` to `config.json.pre-0.82.0`
    (never over a copy already there: that is the true original of an earlier partial run); a failed copy
    writes nothing. The store and the config are read STRICTLY first -- one line that does not parse, a
    config that is not an object, is PENDING naming it, never a false "0 done". The opportunities write
    is checked by the validator on a SHADOW copy first (a new validation problem refuses the whole
    migration, PENDING, nothing written). After the write the success condition is RE-READ from disk, and
    a shortfall puts the config back exactly and is PENDING. IDEMPOTENT: a second run finds every legible
    role already carrying a `jd_read` and every key already moved, and writes nothing.
    HONEST ZERO: an absent store and an absent config are DONE with no output.

    ⚠️ ROLLBACK RISK, STATED. Downgrading to 0.81.0 leaves the new keys in place (0.81.0 ignores them) and
    0.81.0's validator refuses an opportunity carrying `jd_read` (an unknown key); a 0.81.0 engine also
    cannot read a journal holding a `drain` or `mail-status` event. Restoring
    `opportunities.jsonl.pre-0.82.0` and `config.json.pre-0.82.0` undoes the migration only for what was
    not written since. A profile is driven by ONE engine version at a time.

    `_inject_fault="shortfall"` is a TEST SEAM that makes the re-read check fail. Returns `(done, message)`."""
    import _atomic
    import jd_read as _jd
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    rows, _raws, err = _uid_text_read(profile, "opportunities")
    if err:
        return False, ("  ⏳ 0.82.0 PENDING -- %s. Nothing was written: rewriting a store this could not "
                       "fully read would drop that line. Fix it and this runs again next session." % err)
    cfg_path, cfg, cfg_err = _load_config(profile)
    if cfg_err is not None:
        return False, ("  ⏳ 0.82.0 PENDING -- config.json is unreadable, so the intake keys were not "
                       "moved and nothing was written: %s" % cfg_err)
    if cfg is not None and not isinstance(cfg, dict):
        return False, "  ⏳ 0.82.0 PENDING -- config.json is not a JSON object; nothing written."

    # ---- plan --------------------------------------------------------------------------------------
    plan, unreadable = [], []
    for i, r in enumerate(rows):
        att, status = _jd.legacy_attempt(r)
        if status == "ok":
            plan.append((i, att))
        elif status == "unreadable":
            unreadable.append(str(r.get("id")))
    cfg_writes, _notes, problem = (_role_lifecycle_config_plan(cfg) if cfg is not None else ([], [], None))
    if problem:
        return False, ("  ⏳ 0.82.0 PENDING -- %s, so the intake keys were not moved and nothing was "
                       "written." % problem)
    unreadable_note = (" %d role(s) have JD evidence this cannot map and stay UNREAD process failures "
                       "(legacy-backlog) until read: %s" % (len(unreadable), ", ".join(unreadable))
                       if unreadable else "")
    if not plan and not cfg_writes:
        return True, (("  ⚠️ 0.82.0:" + unreadable_note) if unreadable else "")
    if not apply_it:
        lines = []
        if plan:
            lines.append("  would write a read record for %d role(s) from their pre-0.82.0 JD evidence"
                         % len(plan))
        for desc, _fn in cfg_writes:
            lines.append("  would: " + desc)
        if unreadable:
            lines.append(" " + unreadable_note)
        return True, "\n".join(lines)

    # ---- preserve ----------------------------------------------------------------------------------
    if plan:
        copy_path = os.path.join(profile, "data", ROLE_LIFECYCLE_OPPS_PRE_COPY)
        if not os.path.exists(copy_path):
            try:
                shutil.copy2(opp_path, copy_path)
            except (OSError, shutil.Error) as e:
                return False, ("  ⏳ 0.82.0 PENDING -- opportunities.jsonl could not be preserved to %s (%s), "
                               "so NOTHING was written." % (ROLE_LIFECYCLE_OPPS_PRE_COPY, e))
    if cfg_writes:
        cfg_copy = os.path.join(profile, ROLE_LIFECYCLE_CONFIG_PRE_COPY)
        if not os.path.exists(cfg_copy):
            try:
                shutil.copy2(cfg_path, cfg_copy)
            except (OSError, shutil.Error) as e:
                return False, ("  ⏳ 0.82.0 PENDING -- config.json could not be preserved to %s (%s), so "
                               "NOTHING was written." % (ROLE_LIFECYCLE_CONFIG_PRE_COPY, e))

    # ---- transform ---------------------------------------------------------------------------------
    new_rows = [dict(r) for r in rows]
    for i, att in plan:
        new_rows[i]["jd_read"] = {"attempts": [att]}
    if plan:
        rc, problems, new = _shadow_validate(profile, {"opportunities.jsonl": new_rows})
        if new is None or new:
            detail = "; ".join((new if new else (problems or []))[:8]) or (
                "validator exited %d with no problem list -- it crashed" % rc)
            return False, ("  ⏳ 0.82.0 PENDING -- the opportunities write was REFUSED (a new validation "
                           "problem), so NOTHING was written: %s" % detail)
    snapshot = None
    if cfg_writes:
        with open(cfg_path, "rb") as fh:
            snapshot = fh.read()                       # the bytes THIS run read; what a shortfall puts back
        for _desc, fn in cfg_writes:
            fn(cfg)
        _rewrite_config(cfg_path, cfg)
    if plan:
        _atomic.write_jsonl(opp_path, new_rows)

    # ---- query: the success condition is what the disk says now ------------------------------------
    after, _r, a_err = _uid_text_read(profile, "opportunities")
    by_id = {r.get("id"): r for r in (after or [])}
    short = [str(rows[i].get("id")) for i, att in plan
             if a_err or (by_id.get(rows[i].get("id")) or {}).get("jd_read") != {"attempts": [att]}]
    if cfg_writes:
        _p, cfg_after, _e = _load_config(profile)
        s_after = (cfg_after or {}).get("search") if isinstance(cfg_after, dict) else None
        if not isinstance(s_after, dict) or "triage_per_run" in s_after or "triage_stuck_days" in s_after \
                or (isinstance(cfg_after, dict) and cfg_after != cfg):
            short.append("config.json")
    if _inject_fault == "shortfall":
        short = short or ["(injected)"]
    if short:
        if snapshot is not None:
            _atomic.write_text(cfg_path, snapshot.decode("utf-8"))   # put back exactly what this run read
        return False, ("  ⏳ 0.82.0 PENDING -- %s still unwritten after the write; config.json was restored "
                       "(the originals are also at data/%s and %s); offered again next session."
                       % (", ".join(short), ROLE_LIFECYCLE_OPPS_PRE_COPY, ROLE_LIFECYCLE_CONFIG_PRE_COPY))

    parts = []
    if plan:
        parts.append("wrote a read record for %d role(s) from their pre-0.82.0 JD evidence (fit unchanged)"
                     % len(plan))
    parts += [desc for desc, _fn in cfg_writes]
    head = "  ✅ role lifecycle (0.82.0) -- " + "; ".join(parts)
    keep = []
    if plan:
        keep.append("data/" + ROLE_LIFECYCLE_OPPS_PRE_COPY)
    if cfg_writes:
        keep.append(ROLE_LIFECYCLE_CONFIG_PRE_COPY)
    head += " (the original%s kept at %s)" % ("s" if len(keep) > 1 else "", " and ".join(keep))
    return True, head + ("\n" + unreadable_note if unreadable else "")
