#!/usr/bin/env python3
"""Is this profile healthy and CURRENT with the installed plugin?

WHY THIS EXISTS (2026-08-05)
----------------------------
The owner, after the plugin install: *"how can we rerun the onboarding or something to verify the
configuration is up to date with the latest updates from the plugin?"*

Onboarding runs ONCE. The plugin keeps changing. Nothing connected the two, so a profile could
silently fall behind: a config key the engine now reads but the profile never gained, a scheduled
task still pointing at pre-plugin paths (which happened the same day — every run would have failed
at step 0), a store the engine expects that was never created.

**Re-running onboarding is the wrong instrument** — it is a conversation for a NEW user and it does
not touch scheduled tasks. This is the right one: read-only by default, explicit about what only a
human can fix, and safe to run any time.

    python3 "$ENGINE/scripts/doctor.py"           # from your profile directory
    python3 "$ENGINE/scripts/doctor.py" --fix     # apply only the SAFE, additive repairs

Python 3.9+, stdlib only.
"""

import argparse, copy, json, os, subprocess, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root, engine_root, looks_like_profile
from _atomic import write_jsonl, write_json

ROOT, ENGINE = profile_root(), engine_root()
OK, WARN, BAD = "  ok  ", " warn ", " FAIL "


def _cfg():
    try:
        return json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(name):
    """Best-effort JSONL read off THIS profile's data/ dir — an absent store is EMPTY, never a
    crash. A profile that predates a store (or a fresh install with no opportunities yet) must
    still get a clean DOCTOR run, the same "missing thing is not a failure" contract every other
    section here honours."""
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def check_linkless_sightings():
    """public #83, disposed 2026-09-13 (half 1 of 2 — the capture-time rule in record.py, now
    shipped, is the other half).

    A sighting from a URL-bearing channel (job-board/aggregator) that never recorded the link
    becomes permanently unverifiable the moment the posting comes down — the link is free at the
    moment of sighting and effectively unrecoverable afterward. Non-fatal (WARN, never BAD):
    three shapes are LEGITIMATELY linkless, excluded BY RULE rather than by hand, so an
    exclusion is never a silent guess:

      1. recruiter-sourced — the record's own channel_id, or any of its sightings' channel_id,
         resolves to a channel of type 'recruiter'. There was never a public posting to link.
      2. receipt-backed — an applications.jsonl row for this opportunity carries a status in
         SUBMITTED_APP_STATUS (validate_data.py's own "proves a submission actually happened"
         set). The application itself stands as durable evidence the role existed.
      3. too fresh — every board/aggregator sighting is younger than
         `sourcing.linkless_grace_days` (config_keys.py, default 3) — a research/backfill pass
         has not had a chance to run yet.

    A record with NO sighting from a URL-bearing channel at all (recruiter-only,
    company-site-only, …) is out of scope entirely — it was never going to carry a public link,
    so its absence is the sourcing model working as intended, not this advisory's business.

    ⭐ NARROWED to PRE-RULE sightings, now that record.py's capture-time refusal has shipped
    (public #83 rule 1): a board/aggregator sighting dated ON OR AFTER
    `validate_data.SOURCE_URL_REQUIRED_SINCE` could only be missing its source_url by predating
    the refusal some other way (a migration, a hand-authored fixture, `--force`) — that is now
    `validate_data.py`'s hard PROBLEM (see its sightings loop), not this advisory's WARN.
    Counting it here too would double-report the identical fact at two severities. A record
    whose board/aggregator sightings are ALL post-rule is therefore excluded a fourth way,
    distinct from the three above: nothing dated before the rule existed for this advisory to
    hold responsibility for is left on the record, so it has nothing left to say. `_URL_BEARING`
    is imported from `validate_data.py` (`URL_BEARING_CHANNEL_TYPES`) rather than re-typed —
    same single source `record.py`'s own refusal reads.
    """
    import config_keys as _ck
    import validate_data as _vd

    opps = _load_jsonl("opportunities.jsonl")
    if not opps:
        return [(OK, "linkless sightings", "no opportunities recorded yet")]

    channel_type = {c.get("id"): c.get("type") for c in _load_jsonl("channels.jsonl")}
    receipted_opp_ids = {a.get("opp_id") for a in _load_jsonl("applications.jsonl")
                         if a.get("opp_id") and a.get("status") in _vd.SUBMITTED_APP_STATUS}

    cfg = _cfg() or {}
    grace_days, provenance = _ck.describe(cfg, _ck.LINKLESS_GRACE_DAYS)
    today = date.today()

    named = []
    for o in opps:
        if o.get("jd_url"):
            continue
        sightings = o.get("sightings") or []
        if any(sg.get("source_url") for sg in sightings):
            continue

        board_sightings = [sg for sg in sightings if channel_type.get(sg.get("channel_id"))
                           in _vd.URL_BEARING_CHANNEL_TYPES]
        if not board_sightings:
            continue    # never sighted through a URL-bearing channel — out of scope

        referenced = {o.get("channel_id")} | {sg.get("channel_id") for sg in sightings}
        if any(channel_type.get(cid) == "recruiter" for cid in referenced if cid):
            continue    # 1. recruiter-sourced

        if o.get("id") in receipted_opp_ids:
            continue    # 2. receipt-backed

        # 4. every board/aggregator sighting is POST-rule — validate_data.py's hard PROBLEM now
        pre_rule_sightings = [sg for sg in board_sightings
                              if (sg.get("seen_on") or "") < _vd.SOURCE_URL_REQUIRED_SINCE]
        if not pre_rule_sightings:
            continue

        ages = []
        for sg in pre_rule_sightings:
            seen_on = sg.get("seen_on") or ""
            try:
                ages.append((today - date.fromisoformat(seen_on[:10])).days)
            except ValueError:
                continue
        if ages and min(ages) < grace_days:
            continue    # 3. too fresh — still inside the grace period

        named.append(o.get("id", "?"))

    if not named:
        return [(OK, "linkless sightings",
                "none — every PRE-RULE board/aggregator sighting (before %s) carries a link, "
                "or is recruiter-sourced, receipt-backed, or within the %sd grace (%s); a "
                "post-rule sighting missing one is validate_data.py's problem now"
                % (_vd.SOURCE_URL_REQUIRED_SINCE, grace_days, provenance))]
    return [(WARN, "linkless sightings",
            "%d record(s) with no jd_url and no sightings[].source_url from a PRE-RULE "
            "(before %s) board/aggregator channel, past the %sd grace (%s): %s"
            % (len(named), _vd.SOURCE_URL_REQUIRED_SINCE, grace_days, provenance,
               ", ".join(sorted(named))))]


def check_profile():
    out = []
    for f in ("config.json", "user.json"):
        out.append((OK if os.path.exists(os.path.join(ROOT, f)) else BAD, f,
                    "" if os.path.exists(os.path.join(ROOT, f)) else "missing — run init_profile.py --scaffold"))
    for s in ("opportunities", "companies", "channels", "messages", "inbox",
              "pending_actions", "asks", "commitments"):
        p = os.path.join(ROOT, "data", s + ".jsonl")
        out.append((OK if os.path.exists(p) else BAD, "data/%s.jsonl" % s,
                    "" if os.path.exists(p) else "missing store"))
    return out


def check_sync(root=None):
    """adr-012: the declared sync mode, verified against the repository by the single owner of
    that question (`sync.py`). Under `local-only` the exposure is stated at every checkup —
    single copy, no off-machine backup — so the fact stays visible instead of being discovered
    by a dead disk."""
    import sync as _sync
    root = root or ROOT
    try:
        verdict, mode, state, notes = _sync.resolve(root)
    except Exception as e:
        return [(BAD, "sync mode", "resolver failed: %s" % e)]
    if verdict == "ok" and mode == "remote":
        return [(OK, "sync mode", "remote — end-of-run is commit, then push (origin present)")]
    if verdict == "ok":                                    # local-only, declared and honourable
        rows = [(OK, "sync mode", "local-only — end-of-run is commit only, by declaration"),
                (WARN, "exposure", "SINGLE COPY on this machine — no off-machine backup, and no "
                                   "second machine or cloud worker can ever attach (adr-012)")]
        if state["origin"]:
            rows.append((WARN, "origin", "exists but nothing pushes to it, so it will grow "
                                         "stale — `sync.py --set remote` if it should be current"))
        return rows
    detail = {
        "undeclared": "not declared — runs are COMMIT-ONLY until migrate.py seeds it "
                      "(never push on a guess); `sync.py --set` declares it by hand",
        "mismatch":   "declared remote but the repository has NO origin — the push step WILL "
                      "fail; `git remote add origin <url>` or `sync.py --set local-only`",
        "no-repo":    "plain folder — nothing can commit, the audit trail is DOWN; "
                      "migrate.py initialises the repository",
        "no-git":     "git is not on PATH — nothing can commit; this machine changed since "
                      "the plugin was installed",
        "error":      "config.sync.mode is unreadable — `sync.py --status` shows it; fix with "
                      "`sync.py --set`, which validates first",
    }
    sev = WARN if verdict == "undeclared" else BAD
    return [(sev, "sync mode", detail.get(verdict, verdict))]


# The dotted `need` paths --fix will attempt to seed (dev #323). Kept as doctor's OWN fact,
# separate from config_keys.SEEDABLE_DEFAULTS's current contents — so a default missing from
# the registry for a key named here is "the registry broke its promise" (loud, non-zero), never
# silently read as "this was never fixable" (a quiet, ordinary MISSING row).
_ADDITIVE_SAFE_KEYS = frozenset({"search.posture", "search.postures"})


def check_config_currency(fix=False):
    """Keys the CURRENT engine reads. A profile older than the engine is the whole point of this."""
    out, cfg = [], _cfg()
    if cfg is None:
        return [(BAD, "config.json", "unreadable")]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config_keys as _ck
    # (path, why the engine needs it)
    need = [(("search", "posture"), "which budget tier the scheduled runs use (ADR-008)"),
            (("search", "postures"), "the tier definitions themselves"),
            (("compensation", "tiers"), "the comp screen; without it nothing is filtered"),
            (("communications", "default_sequence"), "which channels outreach uses"),
            (("writing", "banned_characters"), "the AI-tell guard")]
    added = []
    for path, why in need:
        node, missing = cfg, False
        for k in path:
            if not isinstance(node, dict) or k not in node:
                missing = True
                break
            node = node[k]
        label = ".".join(path)
        if not missing:
            out.append((OK, label, ""))
            continue
        # additive only, and only for the two paths this doctor knows how to safely default
        # (dev #323 — this used to read `scripts/_config_skeleton.json`, which never existed;
        # the read was wrapped in an `os.path.exists` guard, so --fix silently repaired
        # nothing). `_ADDITIVE_SAFE_KEYS` is what makes "should this be fixable" a fact this
        # doctor states on its own, never a fact borrowed from whether config_keys.py *happens*
        # to still have the default right now — a key outside it (compensation.tiers, …) is out
        # of scope for additive repair on purpose and falls straight through to the ordinary
        # MISSING row below, with or without --fix, exactly as before.
        if fix and label in _ADDITIVE_SAFE_KEYS:
            try:
                default = _ck.seed_default(label)
            except KeyError:
                # this key IS supposed to be additively fixable, and the registry could not
                # produce a default for it — never silently fall through to a plain MISSING
                # row, that is exactly the "missing thing read as empty" bug this fix closes.
                out.append((BAD, label, "cannot seed %s: no default registered" % label))
                continue
            node = cfg
            for k in path[:-1]:
                node = node.setdefault(k, {})
            node[path[-1]] = copy.deepcopy(default)   # never mutate the registry's own default
            added.append(label)
            out.append((OK, label, "seeded config.%s = %r (registry)" % (label, default)))
            continue
        out.append((BAD, label, "MISSING — the engine reads this. %s" % why))
    if added:
        # ⚠️ This is the user's ENTIRE configuration. It used to be truncated by json.dump and
        # then RE-OPENED in append mode for the trailing newline -- two chances to leave a
        # half-written profile behind.
        write_json(os.path.join(ROOT, "config.json"), cfg)

    # States & Views V1 §15.7 — the SAME registry `profile.py --options` reads
    # (config_keys.READER_KEYS), never a second hand-typed list: an adjustable key always has
    # an engine default, so its absence is never BAD here (that is what "adjustable" means) —
    # it is reported OK, with provenance, so CONFIG CURRENCY answers "what does this engine
    # read" for the adjustable surface too, not only the five structural keys above.
    for key in sorted(_ck.READER_KEYS):
        value, provenance = _ck.describe(cfg, key)
        out.append((OK, key, "%r (%s)" % (value, provenance)))
    return out


def check_scheduled_tasks():
    """The failure that actually happened: prompts pointing at pre-plugin paths."""
    out, base = [], os.path.expanduser("~/.claude/scheduled-tasks")
    if not os.path.isdir(base):
        return [(WARN, "scheduled tasks", "none installed — the search will not run unattended")]
    for name in sorted(os.listdir(base)):
        f = os.path.join(base, name, "SKILL.md")
        if not os.path.exists(f):
            continue
        t = open(f, encoding="utf-8", errors="ignore").read()
        if "jobsearch:daily-run" in t or "jobsearch:weekly-review" in t:
            out.append((OK, name, "thin pointer -> plugin skill (updates with the plugin)"))
        elif ENGINE in t:
            out.append((WARN, name, "references the engine path but does not invoke the plugin "
                        "SKILL - run behaviour is pinned here and a plugin update will not reach it"))
        elif "python3 scripts/" in t or "the `jobsearch:daily-run` skill" in t.replace(ENGINE, ""):
            out.append((BAD, name, "STALE pre-plugin paths — this run fails at step 0"))
        else:
            out.append((WARN, name, "does not reference the engine path; verify by hand"))
    return out


def check_cost_matches_intent():
    """⭐ COST LIVES IN TWO PLACES AND NOTHING RECONCILED THEM (owner, 2026-08-05: "the number of
    times the daily runs is a direct correlation to cost and it should be able to be updated
    independently").

    `config.json` DECLARES the tier (runs/day + a cron). The SCHEDULER holds the cron that actually
    fires. Change one and the other silently disagrees — so you believe you are on `economy` while
    still paying for `full`. This is the only check here that costs real money when it drifts."""
    cfg = _cfg() or {}
    s = cfg.get("search", {})
    name, postures = s.get("posture"), s.get("postures", {})
    p = postures.get(name)
    if not p:
        return [(WARN, "posture", "unset or undefined — cost is whatever the scheduler says")]
    want = p.get("cron")
    out = [(OK, "posture", "%s (%s runs/day, max %s agent(s)/run)"
            % (name, p.get("runs_per_day"), p.get("max_agents_per_run")))]
    f = os.path.expanduser("~/.claude/scheduled-tasks/search-daily/SKILL.md")
    if not os.path.exists(f):
        return out + [(WARN, "daily schedule", "no search-daily task installed")]
    # the scheduler owns the real cron; we can only compare against what the tier asks for
    out.append((WARN, "declared cron", "%s — verify the search-daily task matches; "
                "if it does not, YOU are paying a different tier than you configured" % want))
    return out


def check_data():
    r = subprocess.run([sys.executable, os.path.join(ENGINE, "scripts", "validate_data.py")],
                       capture_output=True, text=True, cwd=ROOT)
    return [(OK if r.returncode == 0 else BAD, "data integrity",
             "" if r.returncode == 0 else "validate_data.py failed — see its output")]


def check_credentials():
    """Report only. The engine never prints, logs or stores a credential; on stores whose only
    probe is the read API (Windows PasswordVault, secret-service) the value is read and
    immediately discarded — see credentials.has_credential."""
    try:
        u = json.load(open(os.path.join(ROOT, "user.json"), encoding="utf-8"))
        boxes = [m.get("address") for m in u.get("mailboxes", []) if m.get("address")]
    except Exception:
        boxes = []
    if not boxes:
        return [(WARN, "mailboxes", "none in user.json — no mailbox sweeps, so YOU are the only sensor")]
    # Probe through credentials.py — the same cross-platform store mail_client.py reads.
    # An earlier version shelled straight to macOS `security`, so on Windows/Linux this section
    # died with an uncaught FileNotFoundError after six clean sections — the doctor itself
    # failing on exactly the class of host assumption it exists to report.
    import credentials as _credentials
    out = []
    for a in boxes:
        try:
            ok = _credentials.has_credential(a)
        except Exception as e:
            return [(BAD, "credential store",
                     "unreachable on this platform (backend: %s) — %s"
                     % (_credentials.backend(), e))]
        out.append((OK if ok else BAD, a,
                    "" if ok else "no stored credential (%s) — see CREDENTIALS.md "
                                  "(only you can fix this; mailboxes.py --status prints the command)"
                                  % _credentials.backend()))
    return out


def check_click_guard():
    """dev #111: the guard-status line docs/deployment.md promised from doctor/whoami during the
    #78 audit — built here. REPORT ONLY: a probe result must never gate whether the hook runs
    (deployment.md's own rule), and nothing here changes the guard's fail-open posture — whether
    a known-inert guard should refuse instead of warn stays the owner's open decision.

    The verdict comes from guard_status(): recorded observations (the coded guard_status events
    every SessionStart selftest and click-path diagnosis writes to the diagnostics log) plus the
    executable parser fixture — never from the guard file merely existing, because a line that
    says 'live' against an inert guard is worse than no line."""
    try:
        import guard_outbound_click as _guard
        st = _guard.guard_status()
    except Exception as e:
        return [(WARN, "outbound-click guard", "status unavailable — %s: %s"
                 % (type(e).__name__, e))]
    sev = {"ACTIVE": OK, "UNKNOWN": WARN, "INERT": BAD, "BROKEN": BAD}.get(st["verdict"], WARN)
    rows = [(sev, "outbound-click guard", st["line"])]
    if st["verdict"] in ("INERT", "BROKEN"):
        rows.append((WARN, "what this means",
                     "clicks are ALLOWED unclassified (fail-open, by design); route the reason "
                     "above to engine-reporter — only the engine can fix it"))
    return rows


# ⭐ dev #155 — the recurrence check. install_rulebook.py now REFUSES to write a stamped
# rulebook anywhere that doesn't positively carry a profile marker, but that only stops the
# NEXT stray write — it says nothing about whether one already happened. `install_rulebook.py
# --check` only ever looks at the ONE destination it would write to today, so it cannot see a
# copy sitting somewhere else, left behind by a resolution that predates the refusal (or arrived
# some other way). A stray copy is mechanically findable because it carries its own provenance
# stamp — this is that sweep, wired into `doctor` rather than left as a one-off shell command,
# so it runs the same way every other health check does instead of depending on someone
# remembering the incident.
_STRAY_SWEEP_MAXDEPTH = 4
_STRAY_SWEEP_SKIP_DIRS = (".git", "node_modules")


def check_stray_rulebooks():
    """Any STAMPED CLAUDE.md under $HOME that does NOT sit inside a profile-shaped directory
    (`config.json` or `data/`) is dev #155 recurring — a rulebook install landed somewhere no
    profile lives, and would be loaded as project context by every Claude Code session that
    starts beneath it.

    Deliberately narrow: $HOME, shallow (maxdepth 4, matching the issue's own reproduction
    command), skipping `.git`/`node_modules`. This is a targeted sweep for the one incident
    shape, not a filesystem-wide audit — and it must DEGRADE HONESTLY rather than report a false
    CLEAN: if $HOME cannot be read at all, that is a WARN naming the reason, never a silent OK.
    It must also never flag a profile's OWN legitimate copy, including the edge case where a
    profile's root happens to be $HOME itself — `looks_like_profile()` is checked on the
    CONTAINING directory of every hit before it is reported.
    """
    home = os.path.expanduser("~")
    try:
        if not os.path.isdir(home) or not os.access(home, os.R_OK):
            return [(WARN, "stray rulebooks", "cannot read %s — sweep skipped" % home)]
    except OSError as e:
        return [(WARN, "stray rulebooks", "could not stat %s (%s) — sweep skipped" % (home, e))]

    import install_rulebook as _ir

    hits, dirs_swept = [], 0
    try:
        for dirpath, dirnames, filenames in os.walk(home):
            dirs_swept += 1
            depth = dirpath[len(home):].count(os.sep)
            if depth >= _STRAY_SWEEP_MAXDEPTH:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in _STRAY_SWEEP_SKIP_DIRS]
            if "CLAUDE.md" not in filenames:
                continue
            candidate = os.path.join(dirpath, "CLAUDE.md")
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    head = fh.read(400)
            except OSError:
                continue                       # unreadable file — nothing this check can assert
            if _ir.MARKER not in head:
                continue                       # not one of ours — the unmanaged case, not this bug
            if looks_like_profile(dirpath):
                continue                       # a genuine profile's own copy, correctly placed
            hits.append(candidate)
    except OSError as e:
        return [(WARN, "stray rulebooks", "sweep incomplete (%s) — check manually" % e)]

    if not hits:
        return [(OK, "stray rulebooks",
                 "none found outside a profile (swept %d dirs under %s, maxdepth %d)"
                 % (dirs_swept, home, _STRAY_SWEEP_MAXDEPTH))]
    rows = [(BAD, "stray rulebooks",
             "%d stamped CLAUDE.md found outside any profile — dev #155" % len(hits))]
    for h in hits[:5]:
        rows.append((BAD, "  ->", h))
    if len(hits) > 5:
        rows.append((BAD, "  ->", "...and %d more" % (len(hits) - 5)))
    return rows


# ⭐⭐ dev #<pending> — FREQUENCY IS THE SIGNAL. One pointer-repair is housekeeping (a version
# just landed, or the machine's pointer was never written before). A repair on every single call
# means something keeps rewriting `~/.claude/jobsearch/engine_root` BETWEEN calls — a live
# writer (an ephemeral desktop-app session copy, maintainer tooling, a stray checkout import) —
# and nothing else surfaces that distinction. Since the launcher's TEMPLATE_GENERATION 3
# (dev #167) such a writer can no longer influence RESOLUTION — the file is informational — so
# repeated repairs are evidence to diagnose, not an active outage; each repair event's `from=`
# field classifies the stale value (cache:<version> = a stale session's pinned copy, temp =
# tooling run from a temp directory, session = a per-session plugin copy), which is what turns
# the count into a named writer.
_POINTER_REPAIR_ALARM = 3


def check_pointer_health():
    """Counts of engine-pointer events from the MACHINE-GLOBAL diagnostics log (never a
    profile's own — dev #151: these describe which INSTALLED COPY is running, not any one
    profile's data, so they are read from `_diag.MACHINE_LOG` directly rather than via
    `state_root()`, which would sometimes answer with a profile's log depending on cwd).

    Three event classes, all written by `install_launcher.py`/`_root.py`, none written here:
        pointer-repair          the launcher moved the pointer forward — see ALARM threshold above
        pointer-repair-failed   the launcher tried to move it and the write failed
        stale-copy-session      `heal_if_stale()` refused to regenerate the launcher backward
                                because an OLDER engine copy tried to overwrite a NEWER one
    """
    try:
        import _diag
        lines = _diag.tail(_diag.MAX_LINES, path=_diag.MACHINE_LOG)
    except Exception as e:
        return [(WARN, "engine pointer", "could not read the machine diagnostics log — %s: %s"
                % (type(e).__name__, e))]
    events = []
    for l in lines:
        try:
            events.append(json.loads(l))
        except ValueError:
            continue
    repairs = [e for e in events if e.get("event") == "pointer-repair"]
    failed = [e for e in events if e.get("event") == "pointer-repair-failed"]
    stale = [e for e in events if e.get("event") == "stale-copy-session"]
    out = []
    if failed:
        out.append((BAD, "pointer repair", "%d FAILED write(s) to engine_root recorded — the "
                    "launcher could not repair its own pointer; check that "
                    "~/.claude/jobsearch/ is writable" % len(failed)))
    if len(repairs) >= _POINTER_REPAIR_ALARM:
        froms = sorted({str(e.get("from")) for e in repairs if e.get("from")})
        out.append((BAD, "pointer repair", "%d repair(s) recorded in the recent log — "
                    "something keeps rewriting engine_root between calls (writer classes seen: "
                    "%s). Resolution is unaffected since launcher generation 3; this is a live "
                    "writer to identify, not an outage"
                    % (len(repairs), ", ".join(froms) or "unclassified")))
    elif repairs:
        out.append((WARN, "pointer repair", "%d repair(s) recorded — housekeeping, unless this "
                    "count keeps climbing on repeat checks" % len(repairs)))
    if stale:
        pairs = ["%s->%s" % (e.get("own_generation"), e.get("disk_generation"))
                for e in stale[-3:]]
        out.append((BAD, "stale-copy session", "%d refusal(s): a session ran an OLDER engine "
                    "copy than what is installed and refused to regenerate the launcher "
                    "backward (own->disk generation: %s)" % (len(stale), ", ".join(pairs))))
    if not out:
        out.append((OK, "engine pointer", "no repairs or refusals in the recent machine log"))
    return out


def main():
    ap = argparse.ArgumentParser(description="Is this profile healthy and current with the plugin?")
    ap.add_argument("--fix", action="store_true",
                    help="Apply only SAFE, additive repairs (missing config defaults). Never edits "
                         "your data, never touches credentials, never overwrites a value you set.")
    args = ap.parse_args()

    print("DOCTOR — profile %s" % ROOT)
    print("        engine  %s" % ENGINE)
    print("=" * 74)
    sections = [("PROFILE FILES", check_profile()),
                ("SYNC (adr-012 — does this profile push, and does it know it?)", check_sync()),
                ("CONFIG CURRENCY (does it have what this engine reads?)", check_config_currency(args.fix)),
                ("COST — does the schedule match the tier you chose?", check_cost_matches_intent()),
                ("SCHEDULED RUNS", check_scheduled_tasks()),
                ("DATA", check_data()),
                ("SOURCING (public #83 — board/aggregator sightings with no recoverable link)",
                 check_linkless_sightings()),
                ("OUTBOUND-CLICK GUARD (report only — a probe never gates the hook)",
                 check_click_guard()),
                ("STRAY RULEBOOKS (dev #155 — a stamped CLAUDE.md outside any profile)",
                 check_stray_rulebooks()),
                ("ENGINE POINTER (repair frequency — one is housekeeping, many is a poisoner)",
                 check_pointer_health()),
                ("CREDENTIALS (yours to place)", check_credentials())]
    bad = warn = 0
    fix_failed = False
    for title, rows in sections:
        print("\n%s" % title)
        for status, label, note in rows:
            bad += status == BAD
            warn += status == WARN
            # dev #323: --fix asked to seed a key config_keys.py's own registry says it should
            # cover, and the registry could not produce a default. Never a quiet exit 0 — a
            # repair tool that reports success without repairing trains its reader to trust it.
            if args.fix and status == BAD and note.startswith("cannot seed "):
                fix_failed = True
            print("  [%s] %-34s %s" % (status, label[:34], note))
    print("\n" + "=" * 74)
    if bad:
        print("  %d PROBLEM(S). Additive config gaps: re-run with --fix." % bad)
        print("  Anything else needs a decision — read the note, it says who can fix it.")
    elif warn:
        print("  %d warning(s), nothing broken." % warn)
    else:
        print("  Healthy and current with the installed engine.")
    if fix_failed:
        print("  --fix could not seed everything it should have — see 'cannot seed' above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
