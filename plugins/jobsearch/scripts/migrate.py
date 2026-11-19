#!/usr/bin/env python3
"""Apply profile migrations when the engine version moves. Idempotent; safe to run every session.

Since marketplace issue #11 this is also the startup home of the INSTALL self-heal
(`heal_install.py`, adr-014): the same `SessionStart` hook keeps both the user's data and their
install current with the running version, and neither ever asks the user to run a command.

⭐ WHY THIS EXISTS
------------------
0.4.0 retired two `focus.md` sections. Shipping that as "run this script" put the work on every
installer, who would have to know the migration existed at all — **that does not scale past the
one person who happened to read the release note.** A plugin that changes the shape of a user's
data has to carry the change with it.

## ⭐⭐ THE RULE THAT SHAPES EVERY MIGRATION HERE: SAFE APPLIES, DESTRUCTIVE REPORTS.

A migration runs unattended, at session start, on data this engine does not own. So:

    SAFE         idempotent, and losslessly reversible from git -> APPLIED automatically.
    DESTRUCTIVE  could discard something recorded nowhere else -> REPORTED, never applied.

The retired-sections migration is the exact case: removing two dead headings is safe, **but not
if `🔧 Open` still holds items nobody filed** — those exist in no other place, and deleting them
at session start would be silent data loss the user never asked for. So it refuses and says what
to do. `retire_process_sections.py` already encodes that judgement; this runner defers to it.

⚠️ **FAILS OPEN, ALWAYS.** A migration that errors must never block a session — the user would be
locked out of their own search by a housekeeping step. Every failure path exits 0 and says so.

⚠️ **RESOLVES THE PROFILE FROM THE CURRENT DIRECTORY ONLY — never the remembered pointer.** The
pointer exists so a process with no cwd can still find the profile, which is exactly wrong here:
a session running in the ENGINE repo would otherwise resolve the user's profile and migrate it
from a session that has no business touching it. No profile under cwd means nothing to do.

The stamp lives in the PROFILE (`.jobsearch-schema`), because it records what has been done to
THIS user's data, not what version of the engine happens to be installed.

Usage:
    python3 migrate.py --check     # what is pending; writes nothing
    python3 migrate.py             # apply the safe ones, report the rest
    python3 migrate.py --hook      # same, but silent when there is nothing to say
                                   # (a current profile whose data fails validate_data.py is the one thing it
                                   # always says: one `systemMessage`, dev #768-2)

Python 3.9+. Standard library only.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _diag import log as diag
from migrations.paths import HERE
# Moved out of this file by split_module.py; the names this file still uses.
from migrations.install_cache import prune_install_cache
from migrations.stamp import (
    STAMP,
    KNOWN_PROFILE_ARTIFACTS,
    engine_version,
    ver,
    read_stamp,
    write_stamp_record,
    commit_migrated_paths,
    attempt_record,
    record_noop,
    _SEMVER_RE_STR,
)

MARKERS = ("config.json", "data")


def _hook_session_id():
    """The `session_id` Claude Code passes on stdin to every hook invocation — the same field
    `drift_guard.py` reads the same way. Used ONLY to stamp which session a rulebook refresh
    happened in (public #33/#49), so `drift_guard.py` can tell its own session apart from an
    unrelated one whose next prompt happens to fire first. Never load-bearing for the migration
    itself: any failure here (no stdin, a tty, malformed JSON) falls back to "", never blocks."""
    try:
        if not sys.stdin.isatty():
            return str((json.loads(sys.stdin.read() or "{}") or {}).get("session_id") or "")
    except Exception:                                   # noqa: BLE001
        pass
    return ""


def profile_from_cwd():
    """Walk up from cwd. Deliberately NOT `profile_root()` — see the module docstring."""
    cur = os.path.abspath(os.getcwd())
    while True:
        if any(os.path.exists(os.path.join(cur, m)) for m in MARKERS):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


# ── 0.36.0 — the dev/audit 2026-09-02 build ───────────────────────────────────────────────
# ⚠️ KEYED "0.36.0": 0.35.0 is PUBLISHED (jobsearch--v0.35.0, MIGRATIONS ending at 0.35.0),
# so a profile that installed it carries a stamp of exactly "0.35.0" and pending_for()'s
# strict `<` would never fire a migration keyed "0.35.0" for it (ADR-009, the 0.33.0 trap).
# release-manager re-verifies the key at the moment 0.36.0 is actually cut.


# ── 0.37.0 — the `**Medium:**` line (dev #265, first instance; the owner's decision) ─────────
# ⚠️ KEYED "0.37.0" — the version that SHIPS it (ADR-009). 0.36.0 is the newest release a
# profile can be stamped with, so strict `<` reaches this from that stamp; a key of "0.36.0"
# would be unreachable for exactly those profiles (the 0.33.0 trap). release-manager
# re-verifies the key at the moment 0.37.0 is actually cut: if 0.37.0 ships WITHOUT this
# migration, it must be re-keyed to the version that does.

# ── 0.39.0 — the presence standing-rules file (ADR-028 rule 2, public #62) ────────────────────
# ⚠️ KEYED "0.39.0" — the version that SHIPS it (ADR-009). 0.38.0 is the newest PUBLISHED
# release, so a profile that installed it is stamped exactly "0.38.0" and strict `<` reaches
# this only from a key ABOVE that. Re-verified when 0.39.0 is cut: if 0.39.0 ships WITHOUT
# this migration, it must be re-keyed to the version that does (the 0.33.0 trap).

# ── 0.41.0 — design pass A, step 1: the reader's target must exist ─────────────────────────
# ⚠️ KEYED "0.41.0": 0.40.0 is PUBLISHED (origin carries jobsearch--v0.40.0, whose MIGRATIONS
# ends at 0.40.0), so a profile that installed it is stamped exactly "0.40.0" and strict `<`
# would never fire a migration keyed "0.40.0" for it (ADR-009). release-manager re-verifies
# the key at the moment 0.41.0 is actually cut. Nothing visible to the owner changes in this
# step: every later step resolves to a key these three guarantee.


# ── the first real run of 0.44.0→0.47.0: public #90–#94 ──────────────────────────────────────
# Five defects the OWNER's own profile surfaced on its first real upgrade (design-first-real-
# run-2026-09-13.md §1) — every one of them a bug in code the migrations ALREADY ran with, so
# fixing the code alone leaves the damage already on disk. These three migrations are the
# re-runnable/one-shot repair for what already happened; the code-level fixes (your_move.
# ended_because's precedence, reconcile.person_terms's quoting, people.find_duplicates'
# stuffed-title normalization, brief.py's --probe/--held argparse, record.py's merge-person
# verb) are separate and apply to every FUTURE run regardless of these three.


# ── B4 of ADR-031's connected-entities design: plans, plays and the network capability's
# strategy layer (design-connected-entities.md §22, §26.1) ──────────────────────────────────


_TRAMPOLINE_ENV = "CLAUDESEARCH_MIGRATE_TRAMPOLINED"


def _find_newest_complete_installed(marketplace, plugin):
    """(version, path) of the newest INSTALLED copy of this (marketplace, plugin) identity that
    is COMPLETE — has both `scripts/` and `.claude-plugin/plugin.json` — or None.

    Same "complete" test as the generated launcher's own newest-wins walk (install_launcher.py's
    TEMPLATE): a version directory can exist mid-sync, and a directory caught mid-install must
    never be preferred over an older but genuinely complete one just because its name sorts
    higher. Numeric comparison only (`ver()`), never lexicographic."""
    import re
    import _root
    base = os.path.join(_root.CACHE_ROOT, marketplace, plugin)
    if not os.path.isdir(base):
        return None
    best = None
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for name in names:
        if not re.match(_SEMVER_RE_STR, name):
            continue
        cand = os.path.join(base, name)
        if not os.path.isdir(os.path.join(cand, "scripts")):
            continue
        if not os.path.isfile(os.path.join(cand, ".claude-plugin", "plugin.json")):
            continue
        tup = ver(name)
        if best is None or tup > best[0]:
            best = (tup, name, cand)
    return (best[1], best[2]) if best else None


def _maybe_trampoline_to_newest(argv):
    """⭐⭐ THE GOVERNING INVARIANT FOR THIS WHOLE HOOK: no code shipped here may run inside a
    session that resolves an OLD installed copy, because everything this function's caller is
    about to do — `heal_install`, the launcher heal, the rulebook refresh, every profile
    migration — executes as code belonging to THAT copy. An older copy cannot apply a newer
    fix; it can only ever apply yesterday's version of itself, however faithfully.

    So: before any of that runs, check whether THIS copy of `migrate.py` is older than the
    newest COMPLETE installed copy of the same (marketplace, plugin) identity. If it is, re-exec
    that copy's `migrate.py` with the same argv and exit with its return code — nothing below
    this function ever runs from the stale copy at all.

    Loop-guarded via `CLAUDESEARCH_MIGRATE_TRAMPOLINED`: a second hop always proceeds locally
    rather than re-trampolining, so a resolution race (two copies each briefly believing the
    other is newest) cannot recurse. Silent no-op — never raises, never re-execs — when: this
    process is already a hop (the env flag is set); the running copy is a CHECKOUT rather than
    an installed one (`is_installed_engine`) — a deliberate dev tree is not something this ever
    second-guesses, the same rule the launcher's `engine_root.override` encodes on the
    resolution side; this copy's own version cannot be read or does not
    look like semver; or nothing newer and complete is installed. FAILS OPEN, ALWAYS, same rule
    as everything else in this module — a trampoline that cannot resolve cleanly must never block
    the session; it just lets this (possibly stale) copy continue, exactly as before this existed.
    """
    if os.environ.get(_TRAMPOLINE_ENV):
        return False
    try:
        import _root
        my_root = _root.engine_root()
        if not _root.is_installed_engine(my_root):
            return False                              # a checkout — never second-guessed
        import re
        import install_launcher
        marketplace, plugin = install_launcher._install_identity()
        my_version = engine_version()
        if not re.match(_SEMVER_RE_STR, my_version):
            return False
        newest = _find_newest_complete_installed(marketplace, plugin)
        if not newest:
            return False
        newest_version, newest_path = newest
        if ver(newest_version) <= ver(my_version):
            return False                              # this copy already IS the newest complete
        target = os.path.join(newest_path, "scripts", "migrate.py")
        if not os.path.isfile(target):
            return False
        diag("migrate", verdict="trampolined", frm=my_version, to=newest_version)
        env = dict(os.environ)
        env[_TRAMPOLINE_ENV] = "1"
        r = subprocess.run([sys.executable, target] + list(argv), env=env)
        sys.exit(r.returncode)
    except SystemExit:
        raise
    except Exception as e:                            # noqa: BLE001 — fails open, deliberately
        diag("migrate", verdict="trampoline-error", reason=type(e).__name__)
        return False


# dev #769 (jobsearch 0.76.0, design-channel-catalog.md §6) -- the channel-catalog reconcile envelope. A catalog
# update reaches an install as a VERSION: on every session with a settled verdict (applying only a strictly newer catalog revision), every channel row the user
# turned on from the shipped catalog (`record.py channel-catalog add`) is compared three ways with this version's
# catalog. An unedited row the catalog changed is APPLIED (the old values go to the row's own log, the change is
# committed, one line is printed); an edited row is left alone; a row both sides changed gets an asks.jsonl row;
# a row stamped by a NEWER catalog revision is never touched (R1). It runs BEFORE the purity envelope (it creates
# no company row, so no purity term changes), only when the migration verdict is settled (`current`/`migrated`,
# never `pending`), never under --check, and has its own try: housekeeping must never block a session. It writes a
# diag row on EVERY outcome, `nothing` included, so "ran and found nothing" and "never ran" differ.
def _run_channel_catalog_envelope(profile, migrations_verdict, args):
    try:
        if migrations_verdict not in ("current", "migrated"):
            diag("channel-catalog", verdict="migrations-not-settled")
            return
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import channel_catalog
        res = channel_catalog.reconcile(profile)
        diag("channel-catalog", verdict=res["verdict"], stamped=res["stamped"], applied=res["applied"],
             asked=res["asked"], ahead=res["ahead"])
        if res["written"]:
            commit_migrated_paths(profile, res["written"],
                                  "jobsearch: channel catalog reconciled (%d row%s)"
                                  % (res["applied"] + res["asked"], "" if res["applied"] + res["asked"] == 1 else "s"))
        if res["lines"]:
            print("\n".join(res["lines"]))
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("channel-catalog", verdict="error", reason=type(e).__name__)


# dev #411 §2.1 — the SEVENTH and LAST envelope: the engine-purity term scan, install-side.
# Its own try, exactly like every housekeeping envelope above it: a purity-check crash must
# never cost the session its migrations, which is why this runs LAST, after everything that
# actually writes profile data, and only when the migration envelope itself reported "current".
def _run_purity_envelope(profile, migrations_verdict, args):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import check_engine_purity
        engine_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        pv, p_lines = check_engine_purity.hook_step(
            profile=profile, engine=engine_dir, budget_s=8,
            migrations_verdict=migrations_verdict)
        if p_lines and not args.hook:
            print("\n".join(p_lines))
        elif p_lines:
            # §2.5(c) — the one line a session start should see, even in --hook mode.
            print("\n".join(p_lines))
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("migrate", verdict="purity-error", reason=type(e).__name__)


# ---- dev #768-2: "current" must not be said over data the validator rejects ---------------------------------------------
VALIDATE_TIMEOUT_S = 15       # the SessionStart hook has a 30 s budget in all; the fixture validates in well under 1 s


def _data_problem_count(profile):
    """`(count, why)`: the number of PROBLEMs `validate_data.py` reports on `profile`, read from the validator's own
    sidecar (never parsed out of printed text). `count` is 0 for clean and None when the validator could not be run or
    did not finish, with `why` in plain words: unknown is never read as clean. READ-ONLY, so it also runs under --check."""
    fd, sidecar = tempfile.mkstemp(prefix=".migrate-validate-", suffix=".json")
    os.close(fd)
    try:
        env = dict(os.environ, CLAUDESEARCH_ROOT=profile, CLAUDESEARCH_DATA_DIR=os.path.join(profile, "data"),
                   CLAUDESEARCH_PROBLEMS_OUT=sidecar)
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "validate_data.py")], capture_output=True, text=True,
                           env=env, cwd=profile, timeout=VALIDATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, "validate_data.py did not finish within %d s" % VALIDATE_TIMEOUT_S
        except OSError as exc:
            return None, "validate_data.py could not be run: %s" % type(exc).__name__
        try:
            with open(sidecar, encoding="utf-8") as fh:
                text = fh.read()
            got = json.loads(text) if text.strip() else None
        except (OSError, ValueError):
            got = None
        if not isinstance(got, list):
            return None, "validate_data.py did not finish"
        return len(got), ""
    finally:
        try:
            os.unlink(sidecar)
        except OSError:
            pass


_SYSTEM_MESSAGES = []


def _say_system_message(text):
    """Queue ONE user-facing SessionStart line (a `systemMessage`); the same text is never queued twice."""
    if text not in _SYSTEM_MESSAGES:
        _SYSTEM_MESSAGES.append(text)


def _flush_hook_stdout(text, out):
    """Write what a `--hook` run printed. With no queued system message the text passes through untouched. With one, stdout
    becomes ONE JSON object (the only shape Claude Code reads a `systemMessage` from): the message, and everything else
    the run printed carried as `additionalContext`, so nothing the model used to be told is lost."""
    if not _SYSTEM_MESSAGES:
        out.write(text)
        return
    payload = {"systemMessage": " ".join(_SYSTEM_MESSAGES)}
    if text.strip():
        payload["hookSpecificOutput"] = {"hookEventName": "SessionStart", "additionalContext": text.rstrip("\n")}
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _pinned_ahead_refusal():
    """dev #834 -- the pin refusal for the profile the rulebook would write (`profile_root()`) or the one under the cwd,
    whichever is pinned above this engine, else None."""
    import _root
    import journal as _journal
    seen = []
    for cand in (_root.profile_root(), profile_from_cwd()):
        if not cand or cand in seen:
            continue
        seen.append(cand)
        refusal = _journal.pin_refusal(cand)
        if refusal:
            return refusal
    return None


def main():
    """`--hook` buffers stdout so a queued `systemMessage` can be emitted as one JSON document (see `_flush_hook_stdout`);
    every other mode prints as it goes, exactly as before."""
    del _SYSTEM_MESSAGES[:]
    if "--hook" not in sys.argv[1:]:
        return _main()
    real, buf = sys.stdout, io.StringIO()
    sys.stdout = buf
    try:
        return _main()
    finally:
        sys.stdout = real
        _flush_hook_stdout(buf.getvalue(), real)


def _main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    ap.add_argument("--hook", action="store_true", help="silent when there is nothing to say")
    args = ap.parse_args()

    # ── trampoline to the newest COMPLETE installed copy, before anything else runs ──────────
    # Must be first: every import below belongs to THIS copy, so any of it running before the
    # trampoline check defeats the whole point (see _maybe_trampoline_to_newest's own docstring).
    _maybe_trampoline_to_newest(sys.argv[1:])

    # ── the registry, only now (design-component-segmentation.md §5.3) ──────────────────────
    # It imports every migration module, so it is imported after the trampoline has had its chance
    # to hand over, never at this file's top. The STORE_INTRODUCED check that ran when this file was
    # imported runs here, on every run, before anything below.
    from migrations import registry
    registry.assert_store_versions_known()

    # ── install self-heal, BEFORE the profile half (marketplace issue #11, adr-014) ─────────
    # One mechanism keeps both halves current with the running version: this hook migrates the
    # user's DATA below, and heals the INSTALL here. The heal does not depend on a profile —
    # the install belongs to the machine — so it runs even when the cwd has nothing to migrate.
    # Its own envelope, so a heal crash can never cost the profile its migrations.
    #
    # ⭐ public #104 — captured in its OWN variable (`heal_verdict`, never the generic `verdict`
    # the profile-migration branch below also uses) specifically so the "Profile is current"
    # line further down can say what the TREE check actually found, instead of speaking only
    # from the schema version string. Defaults to None: a heal that raised below could not
    # verify the tree at all, and None is read the same as "not verified" there, never as "fine".
    heal_verdict = None
    try:
        import heal_install
        heal_verdict, h_lines = heal_install.heal_default(apply_it=not args.check)
        if h_lines:
            print("jobsearch: install self-heal (%s)" % heal_verdict)
            print("\n".join(h_lines))
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("migrate", verdict="heal-error", reason=type(e).__name__)
        if not args.hook:
            print("Install self-heal skipped: %s" % e, file=sys.stderr)

    # ── update-availability line, dev #351 ───────────────────────────────────────────────────
    # Same envelope as the heal above: machine state, not profile state, so it runs whether or
    # not a profile exists. `check_update_available.py` is deliberately self-contained — it
    # duplicates the small LOCAL-file autoUpdate read `scripts/check_install.py`'s
    # `autoupdate_state()` already has, rather than importing that script, because
    # `scripts/check_install.py` and `scripts/check_delivery.py` live in the MARKETPLACE repo's
    # own `scripts/` and never ship with the plugin (dev #259/#278) — and it reads no network,
    # ever: the "newer" version it can name is only what THIS MACHINE's already-registered
    # marketplace clone happens to have on disk right now.
    #
    # ⚠️ UNLIKE THE SIBLINGS ABOVE, THIS STAYS LOUD EVEN IN --hook MODE ON FAILURE. dev #351's
    # own plant forces this to raise, to prove the session still gets SOME visible evidence
    # rather than the check silently vanishing — a courtesy notice that can disappear without a
    # trace is the same "and then nothing tells the owner" gap dev #351 exists to close, just on
    # its own failure path instead of the release path.
    try:
        import check_update_available
        verdict, cu_lines = check_update_available.check_default()
        if cu_lines:
            print("\n".join(cu_lines))
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("migrate", verdict="update-check-error", reason=type(e).__name__)
        print("jobsearch: update-availability check skipped (%s: %s)" % (type(e).__name__, e),
              file=sys.stderr)

    # ── launcher self-heal, same envelope and same reason (marketplace identifier rename) ────
    # `~/.claude/jobsearch/run` is a GENERATED file that bakes in the marketplace identity at
    # the time it was last written (install_launcher.py's CACHE fallback line). A marketplace
    # rename moves the cache path an installed copy actually sits at; regenerating the launcher
    # whenever it already exists and disagrees with the currently-derived identity keeps it
    # from freezing on a path that no longer resolves. Machine state, not profile state, so it
    # runs even when the cwd has nothing to migrate — same reasoning as the heal above.
    try:
        import install_launcher
        lv, l_lines = install_launcher.heal_if_stale(apply_it=not args.check)
        if l_lines:
            print("jobsearch: launcher (%s)" % lv)
            print("\n".join(l_lines))
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("migrate", verdict="launcher-heal-error", reason=type(e).__name__)
        if not args.hook:
            print("Launcher heal skipped: %s" % e, file=sys.stderr)

    # ── install-cache hygiene, same envelope discipline (dev #167) ──────────────────────────
    # Owned here and never by the launcher: a resolver that deletes is the wrong shape for a
    # constantly-running sh script. Machine state, so it runs whether or not a profile exists.
    try:
        pv, p_lines = prune_install_cache(apply_it=not args.check)
        if p_lines:
            print("jobsearch: install cache (%s)" % pv)
            print("\n".join(p_lines))
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("migrate", verdict="prune-error", reason=type(e).__name__)
        if not args.hook:
            print("Cache prune skipped: %s" % e, file=sys.stderr)

    # ⭐⭐ dev #834 -- THE PIN GATE, before anything below writes to a profile. The machine half above (install heal, update
    # line, launcher heal, cache prune) ran as it always does: it is what updates THIS install, and the update line is the
    # help this machine needs. But a profile PINNED ABOVE this engine was upgraded by a newer jobsearch and carries shapes
    # this one cannot read, so nothing below it runs: not the rulebook (it would be the downgrade the new marker exists to
    # prevent), not a profile migration, not the no-op stamp, not either envelope. One systemMessage, one diagnostics row,
    # exit 0 (a hook never blocks a session). Both profiles are asked: the one the rulebook would write (`profile_root()`)
    # and the one under the cwd.
    try:
        refusal = _pinned_ahead_refusal()
    except Exception as e:                     # noqa: BLE001 -- the gate must not become a way to fail
        diag("migrate", verdict="pin-gate-error", reason=type(e).__name__)
        refusal = None
    if refusal:
        diag("migrate", verdict="pinned-ahead", engine=engine_version(), reason=refusal[:200])
        _say_system_message("jobsearch: " + refusal)
        if not args.hook:
            print("jobsearch: " + refusal)
        return 0

    # ⭐⭐ AND THE RULEBOOK, for the same reason and in the same place. It installs into the
    # profile as CLAUDE.md and loads at session start, so a stale copy is read as
    # authoritative — this file's own rule. Nothing called install_rulebook.py from any hook,
    # so the only thing keeping it current was somebody remembering: a live profile was found
    # running 0.17.0 rules under a 0.21.0 engine. Its own envelope, so a failure here cannot
    # cost the profile its migrations.
    try:
        import install_rulebook
        rb_verdict, rb_lines = install_rulebook.refresh_if_stale(apply_it=not args.check)
        if rb_lines:
            print("jobsearch: rulebook (%s)" % rb_verdict)
            print("\n".join(rb_lines))
        if rb_verdict in ("refreshed", "installed"):
            # ⚠️ The FILE is current now; the SESSION is not. A rulebook is read into context
            # once and never reloaded, so the session that refreshed it is still running the
            # previous rules (#7). Leave a flag for drift_guard to say so on the next prompt.
            #
            # ⭐ public #33/#49: the flag used to be a bare version string, so ANY session's next
            # UserPromptSubmit — not necessarily the one whose SessionStart just did the refresh
            # — would consume and announce it. That is a false "this session's start" claim
            # aimed at whichever session's prompt happened to land first, and it also means the
            # session that actually needs the warning can lose it to a race. The flag now
            # records WHICH session this refresh happened in (from the hook's own stdin, the
            # same field drift_guard.py reads) plus a nonce unique to this write, so
            # drift_guard.py can (a) only consume a flag addressed to its own session and (b)
            # never let a stale de-dup stamp from a prior write suppress a genuinely new one.
            try:
                import _root
                st = os.path.join(_root.state_root(), "drift")
                os.makedirs(st, exist_ok=True)
                payload = {"to": engine_version(),
                           "session": _hook_session_id() if args.hook else "",
                           "nonce": "%016x" % int.from_bytes(os.urandom(8), "big")}
                with open(os.path.join(st, "rulebook-refreshed"), "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
            except OSError:
                pass
            if not args.check:
                # ⭐ public #52 — the rewrite above must not sit as an uncommitted diff until
                # some later, unrelated commit happens to pick it up (or never does).
                import _root
                # ⭐ dev #618 — never `git add`/`commit` in an UNBOUND cwd. A "refreshed" verdict
                # already implies a profile (`refresh_if_stale` refuses a directory with no
                # marker), so this is defence in depth against a future verdict that does not.
                _pr = _root.profile_root()
                if not _root.is_unbound(_pr):
                    commit_migrated_paths(
                        _pr, ["CLAUDE.md"],
                        "jobsearch: rulebook refreshed to %s" % engine_version())
    except Exception as e:                     # noqa: BLE001
        diag("migrate", verdict="rulebook-error", reason=type(e).__name__)
        if not args.hook:
            print("Rulebook refresh skipped: %s" % e, file=sys.stderr)

    try:
        profile = profile_from_cwd()
        if not profile:
            diag("migrate", verdict="no-profile", mode="hook" if args.hook else "cli")
            if not args.hook:
                print("No profile under the current directory — nothing to migrate.")
            else:
                # ⭐ dev #618 — a SessionStart hook with no profile above the cwd writes nothing
                # into it (the profile half below never ran, and `diag` above lands in the
                # machine log or the checkout scratch dir — `_diag.py` never resolves a state
                # path from an unbound cwd) and says so ONCE, on stderr, exit 0. Silence would
                # leave "refused" and "never ran" looking the same.
                import _root
                _root.say_unbound_once("migrate.py --hook", os.getcwd())
            return 0

        engine = engine_version()
        stamp = read_stamp(profile)
        _due = set(registry.pending_for(profile, engine))
        pending = [(v, fn) for v, fn in registry.MIGRATIONS if v in _due]

        if not pending:
            diag("migrate", verdict="current", engine=engine, stamp=stamp)
            # ⭐ RECORD THE NO-OP (#41). Without this, "ran and found nothing" and "never ran
            # at all" leave identical traces, which is exactly how a stamp sat eleven minors
            # behind while the hook shipped in every version across that range.
            if not args.check:
                record_noop(profile, engine)
            # ⭐⭐ dev #768-2 — CURRENT IS A CLAIM ABOUT THE VERSION STRING, NOT ABOUT THE DATA. 0.73.0 tightened
            # a validator rule with no migration for older data, so a profile stamped current validated RED
            # while this script said "Profile is current" and a session start said nothing at all. Ask the
            # validator (read-only, so it also runs under --check). `invalid_n` is the PROBLEM count, 0 for
            # clean, None when the validator could not be run (an honest "unknown", never read as clean).
            invalid_n, invalid_why = _data_problem_count(profile)
            if invalid_n:
                _say_system_message(
                    "jobsearch: this profile's data has %d validation PROBLEM%s although its schema is current "
                    "(stamp %s) -- run `~/.claude/jobsearch/run validate_data.py` to see %s."
                    % (invalid_n, "" if invalid_n == 1 else "S", stamp, "it" if invalid_n == 1 else "them"))
            if not args.hook:
                # ⭐⭐ public #104 — THE LINE THE OWNER'S OWN RUN CAUGHT: this used to read
                # "Profile is current" from the schema version string alone, over an install
                # tree the heal above had ALREADY reported as corrupt (1 drifted, unexplained)
                # — both true of the version, both false of the tree. The schema-currency claim
                # this line makes is still only ever about the version string; say so plainly,
                # and never let it stand in for "the tree was verified clean this session."
                # ⚠️ the exact sentence below is pinned by existing tests (assertIn "Profile is
                # current") — extend what follows it, never the sentence itself. dev #768-2: it
                # is NEVER printed over a profile the validator reports PROBLEMs on; that case
                # says so in one line instead, naming the count and the script that lists them.
                if invalid_n:
                    base = ("Profile schema is up to date (schema %s, engine %s), but its data has %d validation "
                            "PROBLEM%s -- run `~/.claude/jobsearch/run validate_data.py` to see %s."
                            % (stamp, engine, invalid_n, "" if invalid_n == 1 else "S",
                               "it" if invalid_n == 1 else "them"))
                else:
                    base = "Profile is current (schema %s, engine %s)." % (stamp, engine)
                if invalid_n is None:
                    base += " NOT CHECKED: the data was not validated (%s)." % invalid_why
                if heal_verdict == "repaired":
                    print(base + " Install tree repaired this session (public #104) — see the "
                                 "install self-heal line above.")
                elif heal_verdict in ("unexplained", "no-manifest", "error"):
                    print(base)
                    print("  ⚠️ but the install TREE was not verified clean this session — see "
                          "the install self-heal warning above. The schema version matching "
                          "does not mean the files on disk do.")
                else:
                    print(base)
            if not args.check:
                _run_channel_catalog_envelope(profile, "current", args)    # dev #769
                _run_purity_envelope(profile, "current", args)
            return 0

        lines, all_done = [], True
        for v, fn in pending:
            ok, msg = fn(profile, apply_it=not args.check)
            all_done = all_done and ok
            if msg:
                lines.append(msg)

        if lines:
            print("jobsearch: profile migration %s → %s" % (stamp, engine))
            print("\n".join(lines))
        diag("migrate", verdict=("applied" if all_done else "refused"),
             engine=engine, stamp=stamp, pending=len(pending),
             mode=("check" if args.check else ("hook" if args.hook else "cli")))
        if all_done and not args.check:
            stamped, err = write_stamp_record(
                profile, engine,
                attempt_record(engine, "applied", "%d migration(s)" % len(pending)))
            if not stamped:
                # ⚠️ LOUD, NEVER SILENT (GitHub #8) — same principle as an unparseable
                # precondition: a failure nobody can see is worse than none. But per this
                # module's FAILS OPEN, ALWAYS rule, being loud must not mean being fatal — this
                # still returns 0 below, because housekeeping must never lock the user out of
                # their own session. The migration DID apply; only the record of it failed, so
                # say exactly that, or the discrepancy between "applied" above and "still 0.x.x
                # next session" reads as a mystery instead of a known, named failure.
                diag("migrate", verdict="stamp-failed", engine=engine, stamp=stamp,
                     reason=type(err).__name__)
                print("  ⚠️ schema stamp could not be written (%s: %s) — the migration WAS "
                      "applied but NOT recorded, so it will be re-applied every session until "
                      "the stamp succeeds. Check that %s is writable."
                      % (type(err).__name__, err, os.path.join(profile, STAMP)),
                      file=sys.stderr)
            else:
                # ⭐ public #52 — COMMIT ONLY ON APPLIED, never on record_noop()'s rate-limited
                # no-op stamp (that call site never reaches here). Explicit paths, never `git
                # add -A`: the schema stamp plus the same conservative "known artifacts" list
                # m_0_17_0's own initial commit stages, so whatever a migration actually
                # rewrote (config, data/, kb/, ...) is committed together with the stamp that
                # now claims it happened — never a stamp claiming a change nothing recorded.
                commit_migrated_paths(
                    profile, [STAMP] + list(KNOWN_PROFILE_ARTIFACTS),
                    "jobsearch: profile migration %s → %s (%d migration(s))"
                    % (stamp, engine, len(pending)))
        elif not all_done:
            # Do NOT stamp: leaving it unstamped is what makes this retry next session rather
            # than silently deciding the migration is finished when it is not.
            print("  (Not stamped — this will be offered again next session.)")
        if not args.check:
            _run_channel_catalog_envelope(profile, "migrated" if all_done else "pending", args)    # dev #769
            _run_purity_envelope(profile, "migrated" if all_done else "pending", args)
        return 0
    except Exception as e:                     # noqa: BLE001 — housekeeping must never block
        diag("migrate", verdict="error", error=type(e).__name__)
        if not args.hook:
            print("Migration check skipped: %s" % e, file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
