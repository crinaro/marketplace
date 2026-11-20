"""sourcing: the sourcing verbs: `source` (turn any job source on or off), the sourcing-screen verbs `screened`, `lean`,
`listed-pay` and `posted` (each a script-computed value on the shared write), and the matching that links a role
the pipeline already holds instead of creating it twice.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import os
import subprocess
import sys
from recording import profile_paths as _paths
from recording.row_checks import _diagnostic_lines, dry_run_validate, new_problems, validate
from recording.common import (
    _Refused,
    _Usage,
    _engine_version,
    _plans_mod,
    _run_date,
    _run_date_value,
)
from recording.reads import _store_screen
from recording.store_files import (
    LockError,
    STORES,
    _load_or_empty,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


SOURCE_USAGE = ("source on <id> [--anyway] [--dry-run] | source off <id> [--dry-run]\n"
                "       source list | source keep-mine <id>   [--on YYYY-MM-DD] [--already-locked]")


def _config_path():
    return os.path.join(_paths.ROOT, "config.json")


def _read_config_strict():
    """config.json as a dict, or raises ValueError/OSError. An unreadable config is never an empty one."""
    with open(_config_path(), encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError("config.json is not a JSON object")
    return cfg


def _remote_mode():
    try:
        return ((_read_config_strict().get("sync") or {}).get("mode")) == "remote"
    except (OSError, ValueError):
        return False


def cmd_source(args):
    """`record.py source on|off <id>`, `source list`, `source keep-mine <id>` -- dev #774 (design-source-catalog.md
    section 7.2; jobsearch 0.76.0). THE ONLY WRITER of a source's on/off state: the text path, the
    /jobsearch:sourcing command and the mod's panel button all run exactly this.

    `<id>` is a channel row (stamped or yours), a catalog entry (turn it on: the copy-and-stamp `channel-catalog add`),
    or `company-feeds`. OFF sets `relationship_status: retired` -- the one bit every reader already honours -- and
    stores what it found in the declared `prior_relationship_status` (R2) so ON puts it back exactly; `company-feeds`
    writes `sourcing.feeds.enabled`. A recruiter, referral, company-site or unknown id is REFUSED, naming the right verb.

    ONE locked, validated, rollback-verified write across the stores it touches (channels, companies, asks, and
    config.json), or none. Exit 0: done, or already in that state (a no-op). 2: refused (nothing written). 1: the write
    failed validation and was rolled back. `--dry-run` prints and writes nothing. In a `remote` profile it says that a
    machine on an engine older than 0.76.0 cannot see the switch, and that the change reaches other machines only
    after the next end-of-run commit and push (review B1)."""
    label = "usage: " + SOURCE_USAGE
    verb = args.rid
    if verb not in ("on", "off", "list", "keep-mine"):
        print(label)
        return 2
    import channel_catalog as _cc
    try:
        today = _run_date_value(args.on_date, "--on")
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 2
    if verb == "list":
        if args.rest:
            print(label)
            return 2
        import sources as _sources
        try:
            sys.stdout.write(_sources.render_text(_sources.report(_paths.ROOT, datetime.date.fromisoformat(today))))
        except _sources.SourcesError as e:
            print("NOT CHECKED: %s" % e)
            return 1
        return 0
    if len(args.rest) != 1 or (verb != "on" and args.src_anyway):
        print(label)
        return 2
    ident = args.rest[0]
    catalog = None
    try:
        catalog = _cc.load_catalog()
    except _cc.CatalogError as e:
        print("  NOT CHECKED: %s -- a source you already hold can still be turned on or off; a catalog entry cannot "
              "be turned on until it is readable." % e)
    try:
        stores = {"channels": load("channels"), "companies": _load_or_empty("companies"), "asks": _load_or_empty("asks")}
        config = _read_config_strict()
    except (OSError, ValueError) as e:
        print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
        return 2

    def build(rows, cfg):
        """(changed store names, printable lines, plan or None, noop?) -- raises `_cc.Refused`."""
        if verb == "keep-mine":
            new_asks = _cc.plan_keep_mine(rows["asks"], ident, today)
            rows["asks"] = new_asks
            return ["asks"], ["  %s: the catalog question is resolved; the row is exactly as it was" % ident], None
        plan = _cc.plan_source_toggle(catalog, rows["channels"], rows["companies"], cfg, ident, verb == "on", today,
                                      anyway=args.src_anyway)
        rows["channels"], rows["companies"] = plan["channels"], plan["companies"]
        cfg.clear()
        cfg.update(plan["config"])
        # an adoption ask this turn-on answers is resolved in the same write (`--attach` does the same)
        return list(plan["changed"]), list(plan["lines"]), plan

    shadow, shadow_cfg = json.loads(json.dumps(stores)), json.loads(json.dumps(config))
    try:
        changed, lines, plan = build(shadow, shadow_cfg)
    except _cc.Refused as e:
        print("⛔ REFUSED — %s" % e.args[0])
        return 2

    def extras(plan_, cfg_):
        out = []
        row = plan_["row"] if plan_ else None
        if verb == "on" and row is not None:
            if row.get("board_url"):
                out.append("      open it at %s" % row["board_url"])
            if row.get("query_template"):
                try:
                    import profile as _profile
                    import sources as _sources
                    out.append("      this will search: %s" % _sources.fill_query(row["query_template"], _profile.load(), cfg_))
                except Exception as exc:                              # noqa: BLE001 -- loud, not fatal
                    out.append("      this will search: NOT CHECKED (%s)" % exc)
        if _remote_mode() and not (plan_ and plan_["noop"]):
            if verb == "off":
                out.append("  NOTE (remote profile): a machine still on a jobsearch engine older than 0.76.0 cannot see this "
                           "switch and keeps running this source until it upgrades.")
            if verb in ("on", "off"):
                out.append("  NOTE (remote profile): this change reaches your other machines only after the next end-of-run "
                           "commit and push; it takes effect elsewhere after the next run.")
        return out

    head = "source %s %s" % (verb, ident)
    if plan is not None and plan["noop"]:
        print(head)
        print("\n".join(lines))
        print("  nothing to change.")
        return 0
    if args.dry_run:
        print(head)
        print("\n".join(lines + extras(plan, shadow_cfg)))
        changed_stores = [s for s in changed if s in ("channels", "companies", "asks")]
        if changed_stores:
            pre_problems = validate()[3]
            rc_v, out, err, problems = dry_run_validate(
                "channels", shadow["channels"], extra={k: shadow[k] for k in ("companies", "asks") if k in changed})
            added = new_problems(pre_problems, problems) if rc_v != 0 else []
            if rc_v != 0 and (added is None or added):
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out, err)))
                return 1
        print("  --dry-run: nothing written.")
        return 0
    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 2
    else:
        try:
            take_lock("record.py source %s" % verb, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 2
    try:
        live = {"channels": load("channels"), "companies": _load_or_empty("companies"), "asks": _load_or_empty("asks")}
        try:
            live_cfg = _read_config_strict()
            changed, lines, plan = build(live, live_cfg)
        except _cc.Refused as e:
            print("⛔ REFUSED — %s" % e.args[0])
            return 2
        except (OSError, ValueError) as e:
            print("⛔ REFUSED — config.json cannot be read (%s); nothing written." % e)
            return 2
        if plan is not None and plan["noop"]:
            print(head)
            print("\n".join(lines))
            print("  nothing to change.")
            return 0
        snaps = {s: snapshot(s) for s in changed if s in STORES}
        cfg_before = None
        if "config" in changed:
            with open(_config_path(), "rb") as fh:
                cfg_before = fh.read()
        pre_problems = validate()[3]
        for s in ("companies", "channels", "asks"):          # the firm row first: portfolio_of must resolve
            if s in changed:
                save_atomic(s, live[s])
        if "config" in changed:
            import _atomic
            _atomic.write_json(_config_path(), live_cfg)
        rc_v, out, err, post_problems = validate()
        added = new_problems(pre_problems, post_problems)
        verified = True
        if "config" in changed:
            import config_keys as _ck
            try:
                now_on, _problem = _ck.feeds_enabled(_read_config_strict())
                verified = (now_on == (verb == "on"))
            except (OSError, ValueError):
                verified = False
        if (rc_v != 0 and (added is None or added)) or not verified:
            ok = all(restore(s, snaps[s]) for s in snaps)
            if cfg_before is not None:
                try:
                    with open(_config_path(), "wb") as fh:
                        fh.write(cfg_before)
                except OSError:
                    ok = False
            print("⛔ the write left the stores invalid and was %s."
                  % ("ROLLED BACK (byte-identical)" if ok else "NOT VERIFIABLY ROLLED BACK — restore from git"))
            print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out, err)))
            return 1
    finally:
        if not args.already_locked:
            release_lock()
    print(head)
    print("\n".join(lines + extras(plan, live_cfg)))
    return 0


LEAN_VALUES = ("pursue", "pass", "ask")
# `listed_pay.source` per state (design §3.1): a board's estimate can only come from the board's
# own widget; an ATS API / JSON-LD read can only be the employer's own figure.
PAY_SOURCES_STATED = ("listing-text", "ats-api", "json-ld", "candidate")
PAY_SOURCES_NONE_SHOWN = ("listing-text", "candidate")


def _known_match_for(rows, new_row, extra_urls=()):
    """The pipeline row a role being created duplicates, as `(row, basis, kind)`, or None
    (dev #728 / public #158): by URL first (the row's `jd_url`, its sightings, the item's own URL),
    then by company + title -- `pipeline_index.find_known_match`, the one matcher."""
    import pipeline_index as _pidx
    apps = _load_or_empty("applications")
    urls = [new_row.get("jd_url")] + [s.get("source_url") for s in (new_row.get("sightings") or [])
                                       if isinstance(s, dict)] + list(extra_urls)
    for u in urls:
        if u:
            hit = _pidx.find_known_match(rows, url=u, applications=apps)
            if hit:
                return hit
    return _pidx.find_known_match(rows, company_id=new_row.get("company_id"),
                                  title=new_row.get("title"), applications=apps)


def _append_sightings(row_id, sightings, already_locked=False, wait=None):
    """Append each sighting to `row_id` THROUGH `record.py append` (the one writer: the lock, the
    validator and the rollback all apply) -- a subprocess on this interpreter, `record.py` having no
    in-process dispatch. Returns None, or the reason one failed (the ones before it stay: each is
    its own validated write)."""
    for sg in sightings:
        cmd = [sys.executable, _paths.RECORD_PY, "append", row_id, "sightings",
               json.dumps(sg)]
        if already_locked:
            cmd.append("--already-locked")
        if wait is not None:
            cmd += ["--wait", str(wait)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return "record.py append to %s exited %d: %s" % (
                row_id, r.returncode, " ".join((r.stdout + r.stderr).split())[-300:])
    return None


def _new_opportunity_plan(explicit_id):
    """`(plan_id | None, error | None)` for a freshly created opportunity (ADR-031 B4, design §17,
    §26.5): the one active search plan sourcing role/contract, or the `--plan` the caller named. The error
    is set only when a plan is named that cannot serve, or more than one could (the refusal names every
    candidate); with no active sourcing plan at all both are None and the required-field check refuses
    the missing `plan_id` the way it refuses any other. Shared by `create` and `board-sighting`."""
    _plans_rows, _e, _present = _plans_mod().load(_paths.ROOT)
    _cfg_for_plan = {}
    try:
        import profile as _profile_for_plan
        _cfg_for_plan = _profile_for_plan.config()
    except Exception:                                           # noqa: BLE001 — advisory only
        pass
    resolved, err = _plans_mod().resolve_sourcing_plan(_plans_rows, _cfg_for_plan,
                                                       explicit_id=explicit_id)
    if resolved:
        return resolved, None
    if explicit_id or len(_plans_mod().sourcing_candidates(_plans_rows)) > 1:
        return None, err or "no search plan could be resolved for this role (pass --plan <plan_id>)"
    return None, None


def _link_from_item(args, new_row, rows, match, item):
    """The `create --from-item` branch that finds the role ALREADY in the pipeline (dev #728 /
    public #158; design §5.3, R8): link the item's listing and its siblings onto that row instead of
    creating a second one. Returns the exit code. Prints `LINKED <item> -> <row id> (<basis>)`, or
    `NEARER LISTING of passed <id>: <place> (<state>)` and links nothing."""
    import pipeline_index as _pidx
    row, basis, kind = match
    item = item or {}
    own_loc = (new_row.get("location") or {}).get("primary") if isinstance(
        new_row.get("location"), dict) else None
    listings = [(item.get("ref") or new_row.get("jd_url"), own_loc)]
    listings += [(s.get("url"), s.get("location")) for s in (item.get("siblings") or [])]
    if kind == "excluded":
        # R8: a nearer listing of a role you PASSED on surfaces; it is not auto-closed.
        try:
            import profile as _pf
            nearer, place, state = _pf.nearer_listing(
                _pidx.listing_places(row), [loc for _u, loc in listings], _pf.load())
        except (OSError, ValueError, KeyError):
            nearer, place, state = False, None, None
        if nearer:
            print("NEARER LISTING of passed %s: %s (%s)" % (row.get("id"), place, state))
            print("  %r was NOT created or linked, and %s stays claimable: this listing is closer than "
                  "anywhere %s was listed. To decide it fresh, create it again with --force (the "
                  "pair is recorded in distinct_from)." % (args.rid, args.from_item, row.get("id")))
            return 1
    sg0 = next((s for s in (new_row.get("sightings") or []) if isinstance(s, dict)), None)
    if sg0 is None or not sg0.get("channel_id") or not sg0.get("seen_on"):
        print("⛔ REFUSED — linking %s onto %s needs the JSON's sightings[0] (channel_id, seen_on) to "
              "attribute the listing; none was given." % (args.from_item, row.get("id")))
        return 1
    have = {s.get("source_url") for s in (row.get("sightings") or []) if isinstance(s, dict)}
    have.add(row.get("jd_url"))
    todo = []
    for url, loc in listings:
        if not url or url in have or any(_pidx._urls_equal(url, h) for h in have if h):
            continue
        todo.append(dict({"channel_id": sg0["channel_id"], "seen_on": sg0["seen_on"],
                          "source_url": url}, **({"location": loc} if loc else {})))
        have.add(url)
    print("%s: link listing(s) onto %s (%s)" % (args.rid, row.get("id"), basis))
    if args.dry_run:
        print("  --dry-run: nothing written. Would append %d sighting(s) to %s and close %s as "
              "linked:%s." % (len(todo), row.get("id"), args.from_item, row.get("id")))
        return 0
    err = _append_sightings(row.get("id"), todo, already_locked=args.already_locked, wait=args.wait)
    if err:
        print("⛔ REFUSED — %s. %s stays claimable." % (err, args.from_item))
        return 1
    import deferred as _deferred_mod
    _deferred_mod.close_item(args.from_item, "linked:%s" % row.get("id"))
    print("LINKED %s -> %s (%s)" % (args.from_item, row.get("id"), basis))
    return 0


def location_replace(old, new, rid):
    """`(location, error)` -- `record.py set <id> location '<json>'` on an opportunity (dev #727 /
    public #159, design-location-screen.md §4.3 as amended by R5). `set` replaces the WHOLE
    `location` object, so this compares the stored object with the replacement:

      * the stored location is `setting_source: inferred` (the script inferred onsite at capture):
          - the replacement OMITS `setting_source` and CHANGES the type -> the setting was
            overturned: the same write adds `location.inference_overturned =
            {was: <old type>, to: <new type>, on: <today>}`;
          - it OMITS `setting_source` and keeps the type (onsite) -> the setting is now STATED: the
            flag is simply gone, nothing is recorded;
          - it KEEPS `setting_source` and changes the type -> REFUSED: the flag cannot outlive the
            inference it describes;
          - it carries no `type` -> REFUSED: an overturn names the setting it lands on.
      * a stored location that is not inferred: a replacement carrying `setting_source` is REFUSED
        (provenance is written by the capture script, never typed), and so is an
        `inference_overturned` that is not the stored one. A stored `inference_overturned` the
        replacement omits is CARRIED FORWARD: a whole-object replace must not erase the record that
        a guess was once overturned.

    No dotted `location.type` path exists (R5). Returns `(new location, None)` or `(None, why)`;
    every refusal names this exact command."""
    cmd = "`record.py set %s location '<json>'`" % (rid or "<id>")
    if not isinstance(new, dict):
        return new, None
    old = old if isinstance(old, dict) else {}
    out = dict(new)
    if old.get("setting_source") == "inferred":
        if "type" not in new:
            return None, ("the stored location.type was INFERRED (onsite); the replacement names no "
                          "type. Replace the whole object with the setting the posting states, "
                          "without setting_source: %s." % cmd)
        if "setting_source" in new:
            if new.get("type") != old.get("type"):
                return None, ("location.setting_source is 'inferred' but the type changes from %s to "
                              "%s: the flag cannot outlive the inference. Overturn it by replacing "
                              "the whole object WITHOUT setting_source: %s."
                              % (old.get("type"), new.get("type"), cmd))
            return out, None
        if new.get("type") != old.get("type"):
            out["inference_overturned"] = {"was": old.get("type"), "to": new.get("type"),
                                           "on": datetime.date.today().isoformat()}
        return out, None
    if "setting_source" in new:
        return None, ("location.setting_source is written only by the capture script when it "
                      "infers a setting (`create --from-item`); this location was not inferred, so "
                      "it is not typed by hand. Replace the object without it: %s." % cmd)
    if new.get("inference_overturned") != old.get("inference_overturned"):
        if "inference_overturned" in new:
            return None, ("location.inference_overturned is written only by the overturn of an "
                          "inferred setting, never typed: %s without it." % cmd)
    if "inference_overturned" in old and "inference_overturned" not in new:
        out["inference_overturned"] = old["inference_overturned"]
    return out, None


def _without_provenance(blob):
    """`blob` without its `provenance` key (a `listed_pay` object compared as the sweep parsed it), else `blob`."""
    return {k: v for k, v in blob.items() if k != "provenance"} if isinstance(blob, dict) else blob


def _sourcing_mutation(args, rec):
    """`(desc, apply)` for one of `SOURCING_OPS` against the opportunity `rec` (dev #713-#716 /
    public #142-#145; design §3.1, §3.3, §3.6, §3.7). `apply(row)` sets ONE top-level field; the
    shared write path in `main()` does the lock, the introduced-only rules, the validator and the
    rollback. Raises `_Refused` / `_Usage` before anything is written.

    What each stores is COMPUTED here, from the stored row and the profile, never transcribed:

      screened     `{on, verdict, rules, engine}` from `profile.screen_rules`, evaluated INSIDE
                   `apply` against the row as re-read under the lock.
      lean         `{lean, line, on, signals}`. `line` is required, one line, at most
                   `deferred.ROLES_FIELD_CAP` characters (refused, never truncated). `signals` is
                   what `profile.match_signals` finds in the title, the company row and (when
                   `--jd-file` is given) the JD text. An unreadable `screen.likely_pass_signals`
                   list REFUSES the write: a lean stored with `signals: []` because the list could
                   not be read would claim nothing matched.
      listed-pay   `{state, [ranges], source, captured_on}` from `--none-shown`, `--stated` or
                   `--estimate`; ranges parse through `profile.parse_pay_ranges`, strictly.
      posted       `{date, source, recorded_on}`; `--shown-age N` computes `run date - N`
                   (`board-relative`), `--document-date` is the only writer of
                   `profile-document-date`.
    """
    import profile as _pf
    op = args.op
    if args.rest:
        raise _Usage("usage: %s <opp_id> %s" % (op, {
            "screened": "[--on D]",
            "lean": "--lean pursue|pass|ask --line \"<one line>\" [--jd-file PATH] [--on D]  "
                    "(--lean may be omitted on an age-flagged recruiter role: ask, and on a "
                    "role whose title is below screen.title_floor: pursue when pay clears, "
                    "otherwise ask)",
            "listed-pay": "--none-shown --pay-source candidate | --stated R[;R] | --estimate R[;R] [--pay-source S] "
                          "[--on D]",
            "posted": "--document-date D | --shown-age N | --ats-date D | --board-date D | "
                      "--unknown [--on D]"}[op]))
    on = _run_date(args)
    on_iso = on.isoformat()

    if op == "screened":
        engine = _engine_version()

        def apply(r):
            _store_screen(r, on, engine)
        return "screened (the minimal screen, re-run and stored; on %s)" % on_iso, apply

    if op == "lean":
        lean_choice, line = args.lean_choice, args.line_text
        # ⭐ dev #716 / public #142 (design §6.2): an over-age retained-search role (or a recruiter
        # role of unknown age) defaults to `ask` with the age line's first move as its line. A
        # DEFAULT is what `--lean` omitted means -- an explicit `--lean` is the run's own reading of
        # the JD and is stored as given. Read from the STORED screen (`screened` runs first).
        # ⭐ dev #722 / public #156 (owner decision R1): a BELOW-FLOOR title never removes; the lean
        # it implies is COMPUTED from the stored screen's comp verdict (`profile.title_floor_lean`),
        # stored as a hit beside the signal hits, and is the DEFAULT when `--lean` is omitted. An
        # explicit `--lean` still wins (the 0.67.0 rule). The age flag, when both apply, defaults first.
        try:
            title_lean = _pf.title_floor_lean(rec.get("screen"), _pf.load())
        except (OSError, ValueError) as e:
            raise _Refused("the profile cannot be read, so the title floor's lean cannot be "
                           "computed: %s" % e)
        if lean_choice is None:
            first_move = _pf.age_flag_first_move(rec.get("screen"))
            if first_move:
                lean_choice = "ask"
                if line is None or not line.strip():
                    line = "FIRST MOVE: %s" % first_move
            elif title_lean:
                lean_choice = title_lean[0]
                if line is None or not line.strip():
                    line = title_lean[1]
        if lean_choice not in LEAN_VALUES:
            raise _Refused("--lean must be one of %s" % ", ".join(LEAN_VALUES))
        args.lean_choice, args.line_text = lean_choice, line
        if line is None or not line.strip():
            raise _Refused("--line is required: one line saying why (the lean without a reason "
                           "is a verdict nobody can check)")
        import deferred as _deferred
        if "\n" in line or "\r" in line:
            raise _Refused("--line must be a single line")
        if len(line) > _deferred.ROLES_FIELD_CAP:
            raise _Refused("--line is %d characters; the cap is %d (shorten it -- it is never "
                           "truncated for you)" % (len(line), _deferred.ROLES_FIELD_CAP))
        jd_text = ""
        if args.jd_file:
            try:
                with open(args.jd_file, encoding="utf-8") as fh:
                    jd_text = fh.read()
            except OSError as e:
                raise _Refused("--jd-file %r cannot be read: %s" % (args.jd_file, e))
        try:
            signals = (_pf.config().get("screen") or {}).get("likely_pass_signals")
        except (OSError, ValueError) as e:
            raise _Refused("config.json cannot be read, so likely-pass signals cannot be "
                           "matched: %s" % e)
        company = next((c for c in _load_or_empty("companies")
                        if c.get("id") == rec.get("company_id")), None)
        try:
            hits = _pf.match_signals(rec, company, jd_text, signals or [])
        except ValueError as e:
            raise _Refused(str(e))
        if title_lean:
            hits = hits + [title_lean[2]]
        lean_obj = {"lean": args.lean_choice, "line": line.strip(), "on": on_iso, "signals": hits}

        def apply(r):
            r["lean"] = lean_obj
        return ("lean %s (%d likely-pass signal(s) matched)" % (args.lean_choice, len(hits)),
                apply)

    if op == "listed-pay":
        modes = [m for m, v in (("none-shown", args.none_shown), ("stated", args.stated),
                                ("estimate", args.estimate)) if v]
        if len(modes) != 1:
            raise _Usage("listed-pay takes exactly one of --none-shown, --stated, --estimate")
        mode = modes[0]
        if mode == "none-shown":
            sources, state = PAY_SOURCES_NONE_SHOWN, "none-shown"
        elif mode == "stated":
            sources, state = PAY_SOURCES_STATED, "employer-stated"
        else:
            sources, state = ("board-widget",), "board-estimate"
        source = args.pay_source or sources[0]
        if mode == "none-shown" and source != "candidate":
            # dev #846 (0.88.0, design 3.1): "none shown" is a statement about the whole description. The CANDIDATE can make it
            # (they read the posting themselves); a `listing-text` none-shown has to come from a read that checked the body
            # (`read-jd`, which stamps `none_basis`), never from this verb, which has nothing to check it against.
            raise _Refused("listed-pay --none-shown needs --pay-source candidate: only the candidate's own read of the posting "
                           "records \"none shown\" by hand. A reader that did not find pay records `read-jd --pay ?` (NOT "
                           "captured, re-read before the role is surfaced); one that read the whole description and found none "
                           "records `read-jd --pay none`. Nothing written.")
        if source not in sources:
            raise _Refused("--pay-source %r is not valid for %s (allowed: %s)"
                           % (source, state, ", ".join(sources)))
        obj = {"state": state, "source": source, "captured_on": on_iso}
        if mode != "none-shown":
            try:
                obj = {"state": state, "ranges": _pf.parse_pay_ranges(
                    args.stated if mode == "stated" else args.estimate),
                    "source": source, "captured_on": on_iso}
            except ValueError as e:
                raise _Refused(str(e))

        def apply(r):
            r["listed_pay"] = obj
        return "listed-pay %s (source %s)" % (state, source), apply

    # posted
    picks = [(k, v) for k, v in (("profile-document-date", args.document_date),
                                 ("ats-posted", args.ats_date),
                                 ("board-relative", args.board_date),
                                 ("board-relative:age", args.shown_age),
                                 ("unknown", True if args.unknown else None))
             if v is not None]
    if len(picks) != 1:
        raise _Usage("posted takes exactly one of --document-date, --ats-date, --board-date, "
                     "--shown-age, --unknown")
    source, value = picks[0]
    if source == "unknown":
        obj = {"date": None, "source": "unknown", "recorded_on": on_iso}
    elif source == "board-relative:age":
        if not (isinstance(value, str) and value.isdigit() and int(value) < 3650):
            raise _Refused("--shown-age must be a whole number of days, got %r" % value)
        obj = {"date": (on - datetime.timedelta(days=int(value))).isoformat(),
               "source": "board-relative", "recorded_on": on_iso}
    else:
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            raise _Refused("the posting date must be an ISO date (YYYY-MM-DD), got %r" % value)
        obj = {"date": value, "source": source, "recorded_on": on_iso}

    def apply(r):
        r["posted"] = obj
    return "posted %s (%s)" % (obj["date"], obj["source"]), apply
