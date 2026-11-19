"""Migration 0.86.0: `m_0_86_0_network_first()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_config import _load_config, _rewrite_config
from migrations.support_files import _sha1_file
from migrations.support_pins import NETWORK_FIRST_PIN, _network_first_pin_needed
from migrations.support_validate import _shadow_validate

VERSION = "0.86.0"


# ⭐⭐ KEYED "0.86.0" (dev #834; design-network-first.md sections 12.0, 12.1, 14.2) -- 0.85.0 is the newest jobsearch
# release at the branch base (`jobsearch--v0.85.0` is tagged; plugin.json read 0.85.0 on 3361aa1f and the group's R0 commit
# bumped it to 0.86.0). A profile that installed 0.85.0 is stamped exactly "0.85.0", and pending_for()'s strict `<` fires a
# migration keyed to "0.86.0". The version appears literally in EIGHT places (design 12.0), so a re-key is one commit, by
# release-manager, before any tag: the two migration names, their two test files, the fixture case names, the `.pre-0.86.0`
# preserve suffix, the pin's `min_engine`, the group file, the branch and plugin.json. It runs LAST among the 0.86.0
# migrations' prerequisites: it writes the pin that every other 0.86.0 shape waits for.
NETWORK_FIRST_BY = "m_0_86_0_network_first"


NETWORK_FIRST_CONFIG_PRE_COPY = "config.json.pre-0.86.0"
NETWORK_FIRST_PLANS_PRE_COPY = "plans.jsonl.pre-0.86.0"


def _network_first_plans(profile):
    """`(lines, rows, error)` for data/plans.jsonl: the raw text lines, each line's parsed row (None for a blank one), and a
    string when the file is present but unreadable or a line does not parse. Absent is `([], [], None)`."""
    path = os.path.join(profile, "data", "plans.jsonl")
    if not os.path.exists(path):
        return [], [], None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return [], [], "data/plans.jsonl cannot be read (%s)" % e
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            rows.append(None)
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            return [], [], "data/plans.jsonl line %d does not parse: %s" % (n, e)
        rows.append(row)
    return lines, rows, None


def m_0_86_0_network_first(profile, apply_it, _inject_fault=None):
    """0.86.0 -- the profile pin, `access` on every active search plan, and the network-first config keys (dev #834;
    design-network-first.md sections 12.1 and 14.2; owner ruling 1: every run works the network, whatever the plan's
    outcomes).

    WHAT IT DOES, IN THIS ORDER
      1. THE PIN, as the FIRST write: one `profile-schema` journal event, `min_engine: 0.86.0`, through
         `journal.record_profile_schema` -- unless the journal already carries a pin at or above 0.86.0. An engine older
         than 0.86.0 stops at its first journal READER (it raises on an event it does not know); 0.86.0 and later check
         the pin before they write (`journal.pin_refusal`). The success condition is a RE-READ: `journal.profile_pin(
         journal.read(profile)) >= 0.86.0`. If the append raises (the file is not writable) or the re-read does not show
         the pin, the result is PENDING and NOTHING else was written, because nothing else had been.
      2. PRESERVE: `config.json` -> `config.json.pre-0.86.0` and `data/plans.jsonl` -> `data/plans.jsonl.pre-0.86.0`, byte
         for byte, never over a copy already there (that is the true original of an earlier partial run). The journal is
         not copied: it is append-only and step 1 only appended.
      3. Every ACTIVE `search` plan whose `outcomes` lacks `access` gains it (first; the other values are kept). A profile
         with no active search plan is REPORTED and no plan is created (a removed plan was the owner's act): the network
         block runs regardless of outcomes, so this is DONE, not pending. The write is checked on a SHADOW copy first.
      4. The network-first config keys (`config_keys.NETWORK_FIRST_SEEDED`) are seeded where ABSENT, never over a value the
         owner set. `search.intake_per_run` is LEFT IN PLACE, byte for byte: no 0.86.0 reader reads it and an older engine
         still does. No arithmetic maps roles to companies.
      No opportunity, company or commitment row is written.

    PREREQUISITES, READ-ONLY, each PENDING (never a false "0 done") naming its cause: `config.json` parses and its
    `search`, `network` and `access` sections are objects; `data/runs.jsonl` is absent or reads cleanly through
    `journal.read` (an unparseable line is named by its number); `data/plans.jsonl` is absent or parses.

    BETWEEN THE PIN AND COMPLETION a fault leaves the profile pinned while steps 3 and 4 have not run. That is safe by
    construction: every absent key reads its registered default, which EQUALS the seeded value, and a search plan without
    `access` changes nothing the network block does. The migration is not stamped done, so the next session re-runs it, step
    1 is skipped (the pin exists), and the rest completes.

    IDEMPOTENT: the pin exists, every active search plan has `access` and every key exists => done, nothing written, nothing
    said. The pin is also re-checked by `pending_for` whatever the stamp says ("pin lost": a hand-reset or restored journal).

    ⚠️ ROLLBACK, STATED. An engine older than 0.86.0 raises on a journal holding a `profile-schema` event, so after this runs
    an older machine stops at its first journal reader (and writes only the set design 14.2 declares). A profile is driven
    by ONE engine version at a time; restoring `config.json.pre-0.86.0` and `plans.jsonl.pre-0.86.0` undoes only steps 3 and
    4, not the pin.

    `_inject_fault` is a TEST SEAM: "before-pin", "after-pin", "after-preserve" raise at that point (a crash the next run
    must complete from), and "shortfall" makes the post-write re-read fail. Returns `(done, message)`."""
    import _atomic
    import config_keys as _ck
    import journal as _journal
    pending = "  ⏳ 0.86.0 PENDING -- %s. Nothing was written. This runs again next session."

    # ---- prerequisites (read-only) ---------------------------------------------------------------------
    cfg_path, cfg, cfg_err = _load_config(profile)
    if cfg_err is not None:
        return False, pending % ("config.json is unreadable (%s: %s)" % (type(cfg_err).__name__, cfg_err))
    if cfg is not None and not isinstance(cfg, dict):
        return False, pending % "config.json is not a JSON object"
    for section in ("search", "network", "access"):
        if isinstance(cfg, dict) and section in cfg and not isinstance(cfg[section], dict):
            return False, pending % ("config.json.%s is not an object, so the network-first keys cannot be seeded" % section)
    try:
        recs = _journal.read(profile)
    except _journal.JournalError as e:
        return False, pending % ("data/runs.jsonl does not read cleanly (%s)" % e)
    except (OSError, UnicodeDecodeError) as e:
        return False, pending % ("data/runs.jsonl cannot be read (%s)" % e)
    plan_lines, plan_rows, plan_err = _network_first_plans(profile)
    if plan_err:
        return False, pending % plan_err

    # ---- plan --------------------------------------------------------------------------------------------
    need_pin = _network_first_pin_needed(profile, recs)
    active_search = [i for i, r in enumerate(plan_rows)
                     if isinstance(r, dict) and r.get("subject_kind") == "search" and r.get("status") == "active"]
    plan_edits, odd_plans = [], []
    for i in active_search:
        outs = plan_rows[i].get("outcomes")
        if not isinstance(outs, list):
            odd_plans.append(str(plan_rows[i].get("id")))
        elif "access" not in outs:
            plan_edits.append(i)
    seed = []
    if isinstance(cfg, dict):
        for section, key, default in _ck.NETWORK_FIRST_SEEDED:
            if key not in (cfg.get(section) or {}):
                seed.append((section, key, default))
    if not need_pin and not plan_edits and not seed:
        return True, ""
    if not apply_it:
        lines = []
        if need_pin:
            lines.append("  would pin the profile to jobsearch %s (one `profile-schema` journal event)" % NETWORK_FIRST_PIN)
        if plan_edits:
            lines.append("  would add `access` to %d active search plan(s)" % len(plan_edits))
        if seed:
            lines.append("  would seed %s" % ", ".join("%s.%s" % (a, b) for a, b, _c in seed))
        return True, "\n".join(lines)

    # ---- the pin, as the first write ---------------------------------------------------------------------
    if _inject_fault == "before-pin":
        raise RuntimeError("injected fault: before-pin")
    if need_pin:
        runs_path = os.path.join(profile, "data", "runs.jsonl")
        try:
            try:
                size = os.path.getsize(runs_path)
            except OSError:
                size = 0                        # no journal yet: `journal.append` creates it
            if size:
                with open(runs_path, "rb") as fh:
                    fh.seek(size - 1)
                    last = fh.read(1)
                if last != b"\n":
                    with open(runs_path, "ab") as fh:
                        fh.write(b"\n")          # `journal.append` writes a whole line: never glue one onto an unterminated one
            _journal.record_profile_schema(profile, NETWORK_FIRST_PIN, NETWORK_FIRST_BY)
            if _network_first_pin_needed(profile, _journal.read(profile)):
                raise _journal.JournalError("the pin is not in the journal after the append")
        except (_journal.JournalError, OSError) as e:
            return False, pending % ("the profile pin could not be recorded: %s" % e)
    if _inject_fault == "after-pin":
        raise RuntimeError("injected fault: after-pin")

    after_pin = "  ⏳ 0.86.0 PENDING -- %s. The profile pin IS recorded; nothing else was written. This runs again next session."

    # ---- preserve ----------------------------------------------------------------------------------------
    copies = []
    if cfg is not None:
        copies.append((cfg_path, os.path.join(profile, NETWORK_FIRST_CONFIG_PRE_COPY), NETWORK_FIRST_CONFIG_PRE_COPY))
    if os.path.exists(os.path.join(profile, "data", "plans.jsonl")):
        copies.append((os.path.join(profile, "data", "plans.jsonl"),
                       os.path.join(profile, "data", NETWORK_FIRST_PLANS_PRE_COPY), "data/" + NETWORK_FIRST_PLANS_PRE_COPY))
    for src, dst, label in copies:
        if os.path.exists(dst):
            continue
        try:
            shutil.copy2(src, dst)
            if _sha1_file(src) != _sha1_file(dst):
                raise OSError("the copy does not match the original")
        except (OSError, shutil.Error) as e:
            try:
                os.remove(dst)                  # a copy that failed its check must not pass for the true original later
            except OSError:
                pass
            return False, after_pin % ("%s could not be preserved to %s (%s)" % (os.path.basename(src), label, e))
    if _inject_fault == "after-preserve":
        raise RuntimeError("injected fault: after-preserve")

    # ---- transform: plans, checked on a shadow copy first ------------------------------------------------------
    if plan_edits:
        new_rows = [dict(r) if isinstance(r, dict) else r for r in plan_rows]
        new_lines = list(plan_lines)
        for i in plan_edits:
            outs = list(new_rows[i]["outcomes"])
            new_rows[i]["outcomes"] = ["access"] + [o for o in outs if o != "access"]
            new_lines[i] = json.dumps(new_rows[i], ensure_ascii=False)
        rc, problems, new = _shadow_validate(profile, {"plans.jsonl": [r for r in new_rows if r is not None]})
        if new is None or new:
            detail = "; ".join((new if new else (problems or []))[:8]) or (
                "validator exited %d with no problem list -- it crashed" % rc)
            return False, after_pin % ("the plans write was REFUSED (a new validation problem): %s" % detail)
        _atomic.write_text(os.path.join(profile, "data", "plans.jsonl"), "\n".join(new_lines) + "\n")

    # ---- transform: config -------------------------------------------------------------------------------------
    snapshot = None
    if seed:
        with open(cfg_path, "rb") as fh:
            snapshot = fh.read()                # the bytes THIS run read; what a shortfall puts back
        for section, key, default in seed:
            import copy as _copy
            cfg.setdefault(section, {})[key] = _copy.deepcopy(default)
        _rewrite_config(cfg_path, cfg)

    # ---- query: the success condition is what the disk says now ------------------------------------------------
    short = []
    if plan_edits:
        _l, rows_after, e_after = _network_first_plans(profile)
        ids_edited = {plan_rows[i].get("id") for i in plan_edits}
        got = {r.get("id"): r for r in rows_after if isinstance(r, dict)}
        if e_after or any("access" not in (got.get(pid) or {}).get("outcomes", []) for pid in ids_edited):
            short.append("data/plans.jsonl")
    if seed:
        _p, cfg_after, _e = _load_config(profile)
        if not isinstance(cfg_after, dict) or any(k not in (cfg_after.get(sec) or {}) for sec, k, _d in seed):
            short.append("config.json")
    if _inject_fault == "shortfall":
        short = short or ["(injected)"]
    if short:
        if snapshot is not None:
            _atomic.write_text(cfg_path, snapshot.decode("utf-8"))   # put back exactly what this run read
        return False, after_pin % ("%s still unwritten after the write; config.json was restored (the originals are also "
                                   "at %s and data/%s)" % (", ".join(short), NETWORK_FIRST_CONFIG_PRE_COPY,
                                                           NETWORK_FIRST_PLANS_PRE_COPY))

    parts = []
    if need_pin:
        parts.append("pinned the profile to jobsearch %s" % NETWORK_FIRST_PIN)
    if plan_edits:
        parts.append("%d search plan%s gained access" % (len(plan_edits), "" if len(plan_edits) == 1 else "s"))
    elif not active_search:
        parts.append("no active search plan; the network block runs regardless")
    if odd_plans:
        parts.append("search plan%s %s ha%s no outcomes list and %s left alone"
                     % ("" if len(odd_plans) == 1 else "s", ", ".join(odd_plans),
                        "s" if len(odd_plans) == 1 else "ve", "was" if len(odd_plans) == 1 else "were"))
    seeded = {(a, b) for a, b, _c in seed}
    if ("search", "company_intake_per_run") in seeded:
        n = dict(((a, b), c) for a, b, c in _ck.NETWORK_FIRST_SEEDED)[("search", "company_intake_per_run")]
        parts.append("intake now counted in companies (%d a run); up to %d companies a run will be raised for you to look "
                     "into" % (n, n))
    if any(a == "network" for a, _b in seeded):
        parts.append("network settings added (%d new reach-outs a week)" % _ck.NETWORK_NEW_REACHOUTS_PER_WEEK_DEFAULT
                     if ("network", "new_reachouts_per_week") in seeded else "network settings added")
    if isinstance(cfg, dict) and "intake_per_run" in (cfg.get("search") or {}):
        parts.append("your roles-per-run setting is left in place for older engines and no longer read")
    keep = [label for _s, _d, label in copies]
    head = "  ✅ network-first (0.86.0) -- " + "; ".join(parts)
    if keep and (plan_edits or seed):
        head += " (the original%s kept at %s)" % ("s" if len(keep) > 1 else "", " and ".join(keep))
    return True, head
