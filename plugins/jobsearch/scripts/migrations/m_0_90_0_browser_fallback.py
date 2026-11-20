"""Migration 0.90.0: `m_0_90_0_browser_fallback()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, frozen once released (§5.5)."""

import datetime
import os
import _atomic
from browser_fallback.fetch_key import key_value
from browser_fallback.fetch_notice import NOTICE_ID, notice_row
from journaling.journal_file import read
from journaling.row_kinds import record_profile_schema
from journaling.tables import JournalError
from migrations.support_pins import BROWSER_FALLBACK_PIN, _browser_fallback_asks, _browser_fallback_pin_needed
from migrations.support_validate import _shadow_validate

VERSION = "0.90.0"


# ⭐⭐ KEYED "0.90.0" (dev 858; design-browser-fallback.md sections 6.4, 8.2, 8.3) -- 0.89.2 is the newest jobsearch release at the
# branch base (`jobsearch--v0.89.2` is tagged). A profile stamped "0.89.2" (or any lower version) fires a migration keyed "0.90.0"
# through pending_for()'s strict `<`. The version appears literally in the migration's name, its registry key, its test files' names,
# the pin (`BROWSER_FALLBACK_PIN`) and the group file, so a re-key is one commit by release-manager before any tag -- the 0.86.0
# section 12.0 precedent. (The build was written as 0.90.0 and renumbered once 0.90.0 shipped as the dashboard release.) It runs LAST
# among the migrations: its first write is the profile pin that makes an older engine stop at its first journal reader.
BROWSER_FALLBACK_BY = "m_0_90_0_browser_fallback"
POSTING_FETCH_NOTICE_ID = NOTICE_ID                      # the one asks.jsonl row that discloses the automatic fetch (design 6.4)


def m_0_90_0_browser_fallback(profile, apply_it, _inject_fault=None):
    """0.90.0 -- the profile pin and the disclosure row for the automatic posting fetch (dev 858;
    design-browser-fallback.md sections 6.4, 8.2 and 8.3; criterion C9). No data is transformed.

    WHAT IT DOES, IN THIS ORDER
      1. THE PIN, as the FIRST write: one `profile-schema` journal event, `min_engine: 0.90.0`, through
         `journal.record_profile_schema`, unless the journal already carries a pin at or above 0.90.0. The 0.90.0 reader
         accepts the evidence keys `browser`, `ready`, `gate` and `fallback`, which an older `jd_read.py` refuses; the pin
         is what stops an older engine from writing into (or reading) a profile that carries them (0.86.0 to 0.89.x refuse
         at their first journal read or append through `pin_refusal`). The success condition is a RE-READ:
         `journal.profile_pin(journal.read(profile)) >= 0.90.0`. If the append raises or the re-read does not show the pin,
         the result is PENDING and NOTHING else was written.
      2. THE NOTICE ROW, only when no row of `data/asks.jsonl` has the id `ask-posting-fetch-auto`, WHATEVER ITS STATUS
         (open, resolved or closed: resolving the notice is the natural answer to it, and a migration never reopens a row).
         The row is built only by `fetch_notice.notice_row(value, today)` for the config key's current value, and is appended
         after a SHADOW validation (the asks precedent, `m_0_48_0_application_endings_restamp`): a row that would add a new
         validation problem is refused, with the pin already recorded.
      3. One printed message, only when something was written.

    PREREQUISITES, READ-ONLY, each PENDING (never a false "0 done") naming its cause: `config.json` reads through
    `fetch_key.key_value` (an `unreadable` value is pending, because the notice text depends on the value);
    `data/runs.jsonl` reads cleanly through `journal.read`; `data/asks.jsonl` is absent or reads. A prerequisite that fails
    writes NOTHING, the pin included.

    BETWEEN THE PIN AND THE ROW a fault leaves the profile pinned without the row. That is safe by construction: a key that
    reads `absent` then stores `notice-missing` and sends nothing (design 6.4), and the next session re-runs this migration,
    skips the pin (it exists) and completes the row. No sandbox setting is read or written by this migration (owner ruling a2).

    IDEMPOTENT: the pin is there and a row with the id exists => done, nothing written, nothing said.

    `_inject_fault` is a TEST SEAM: "before-pin" and "after-pin" raise at that point (a crash the next run must complete
    from), and "shortfall" makes the row's re-read fail. Returns `(done, message)`."""
    pending = "  ⏳ 0.90.0 PENDING -- %s. Nothing was written. This runs again next session."

    # ---- prerequisites (read-only) ---------------------------------------------------------------------
    value, why = key_value(profile)
    if value not in ("absent", "on", "off"):
        return False, pending % ("config.json's search.posting_fetch does not read (%s)" % (why or value))
    try:
        recs = read(profile)
    except JournalError as e:
        return False, pending % ("data/runs.jsonl does not read cleanly (%s)" % e)
    except (OSError, UnicodeDecodeError) as e:
        return False, pending % ("data/runs.jsonl cannot be read (%s)" % e)
    asks, asks_err = _browser_fallback_asks(profile)
    if asks_err:
        return False, pending % asks_err

    # ---- plan --------------------------------------------------------------------------------------------
    need_pin = _browser_fallback_pin_needed(recs)
    need_row = not any(a.get("id") == POSTING_FETCH_NOTICE_ID for a in asks)
    if not need_pin and not need_row:
        return True, ""
    if not apply_it:
        lines = []
        if need_pin:
            lines.append("  would pin the profile to jobsearch %s (one `profile-schema` journal event)" % BROWSER_FALLBACK_PIN)
        if need_row:
            lines.append("  would write the notice row %s to data/asks.jsonl (the automatic posting fetch; the key reads %s)"
                         % (POSTING_FETCH_NOTICE_ID, value))
        return True, "\n".join(lines)

    # ---- the pin, as the first write ---------------------------------------------------------------------
    if _inject_fault == "before-pin":
        raise RuntimeError("injected fault: before-pin")
    if need_pin:
        ok, message = _write_pin(profile, pending)
        if not ok:
            return False, message
    if _inject_fault == "after-pin":
        raise RuntimeError("injected fault: after-pin")

    after_pin = "  ⏳ 0.90.0 PENDING -- %s. The profile pin IS recorded; nothing else was written. This runs again next session."

    # ---- the notice row, checked on a shadow copy first --------------------------------------------------
    if need_row:
        problem = _write_notice(profile, value, asks, after_pin, _inject_fault)
        if problem:
            return False, problem

    parts = []
    if need_pin:
        parts.append("pinned the profile to jobsearch %s" % BROWSER_FALLBACK_PIN)
    if need_row:
        parts.append({
            "absent": "when the Browser pane cannot paint and the extension cannot read a LinkedIn posting, the logged-out "
                      "fetch now runs automatically; `python3 posting_fetch.py --set off` stops it",
            "off": "your `off` setting also stops the automatic posting fetch; `python3 posting_fetch.py --set auto` allows it",
            "on": "the posting fetch you turned on now also runs when the Browser pane cannot paint and the extension "
                  "cannot read; `python3 posting_fetch.py --set off` stops it",
        }[value] + " (notice %s)" % POSTING_FETCH_NOTICE_ID)
    return True, "  ✅ browser fallback (0.90.0) -- " + "; ".join(parts)


def _write_pin(profile, pending):
    """Append the pin and re-read it. `(True, None)`, or `(False, the PENDING line)`; `pending` is the plain PENDING template."""
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
        record_profile_schema(profile, BROWSER_FALLBACK_PIN, BROWSER_FALLBACK_BY)
    except (JournalError, OSError) as e:
        return False, pending % ("the profile pin could not be recorded: %s" % e)
    # the success condition is the RE-READ, and it is stated apart from the append: the append may have landed even when
    # the read-back does not show it (a journal this engine refuses to read), so "nothing was written" is not claimed here
    try:
        shows_pin = not _browser_fallback_pin_needed(read(profile))
        why_not = "the pin is not in the journal after the append"
    except (JournalError, OSError, UnicodeDecodeError) as e:
        shows_pin, why_not = False, "the journal does not read back after the append: %s" % e
    if not shows_pin:
        return False, ("  ⏳ 0.90.0 PENDING -- the profile pin could not be recorded: %s. Nothing else was written; check "
                       "data/runs.jsonl before this runs again next session." % why_not)
    return True, None


def _write_notice(profile, value, asks, after_pin, _inject_fault):
    """Build, shadow-validate and write the notice row, then re-read it. `None` when it landed, else the PENDING line."""
    try:
        row = notice_row(value, datetime.date.today().isoformat())
    except Exception as e:                  # noqa: BLE001 -- reported, never raised: the pin is already down
        return after_pin % ("the notice row could not be built (%s: %s)" % (type(e).__name__, e))
    if not isinstance(row, dict) or row.get("id") != POSTING_FETCH_NOTICE_ID:
        return after_pin % ("fetch_notice.notice_row(%r) did not return a row with the id %s" % (value, POSTING_FETCH_NOTICE_ID))
    new_asks = asks + [row]
    rc, problems, new = _shadow_validate(profile, {"asks.jsonl": new_asks})
    if new is None or new:
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list -- it crashed" % rc)
        return after_pin % ("the notice row was REFUSED (a new validation problem): %s" % detail)
    _atomic.write_jsonl(os.path.join(profile, "data", "asks.jsonl"), new_asks)
    # ---- query: the success condition is what the disk says now ----------------------------------------
    after, after_err = _browser_fallback_asks(profile)
    if _inject_fault == "shortfall" or after_err or not any(a.get("id") == POSTING_FETCH_NOTICE_ID for a in after):
        return after_pin % "data/asks.jsonl does not hold the notice row after the write"
    return None
