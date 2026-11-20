"""The schema stamp, the profile pin and the posting-fetch notice row a NEW profile is scaffolded with.

One module of `migrations/` (design-component-segmentation.md §5), called by `init_profile.py --scaffold` (moved out of its `main()`
by dev 858, so the entry point does not grow).

⭐⭐ B1 (ADR-031 §28.1 item 5 / gates-connected-entities.md §3, "the fresh-scaffold no-op migration gate"). Before this,
init_profile.py wrote NO stamp at all: `migrate.read_stamp` on an unstamped profile returns "0.0.0", so a brand-new profile replayed
EVERY migration this engine has ever shipped on its first hook-firing session. Stamping at the engine's OWN version here means a
fresh scaffold is current-shape from the first moment, so the chain is a no-op on it, exactly as the design intends.

⭐ ONLY WHEN NO STAMP EXISTS YET -- never overwrite one. `--scaffold` also runs against an OLDER, populated profile to fill in
newly-added stores; that profile is not fresh and may genuinely have pending migrations, so stamping it "current" would hide exactly
the backlog migrate.py exists to run.

dev #834 (design-network-first.md 12.2): a profile scaffolded by 0.86.0 or later carries the pin from its first moment, so it is never
"pin lost" and an older engine on the same profile stops at its first journal reader instead of writing as if the profile were its
own. dev 858 (design-browser-fallback.md 8.2, 6.4; criterion C9): the pin a NEW profile carries is now 0.90.0 (`pin_scan` takes the
highest, and 0.90.0 satisfies every check a 0.86.0 pin did), because a profile scaffolded by 0.90.0 is read by the 0.90.0 evidence
keys from its first run. It also carries the NOTICE ROW (`ask-posting-fetch-auto`): a migration message reaches neither a new
installer nor a scheduled first run, so the disclosure of the automatic posting fetch is a stored row, written here before the first
run can make its first automatic GET (by id, whatever its status). FAIL OPEN: a pin that cannot be written leaves the profile
pending (the next hook re-appends it); a row that cannot be written leaves the key reading `absent` with no row, which stores
`notice-missing` and SENDS NOTHING until `posting_fetch.py --set auto` writes it."""

import datetime
import os
import _atomic
from browser_fallback.fetch_key import key_value
from browser_fallback.fetch_notice import NOTICE_ID, notice_row
from journaling.row_kinds import record_profile_schema
from migrations import stamp
from migrations.support_pins import BROWSER_FALLBACK_PIN, _browser_fallback_asks


def write_notice_row(root):
    """Write the posting-fetch notice row for the config key's current value, unless a row has the id (whatever its status).
    Returns True when it wrote one. Raises ValueError when asks.jsonl or the key cannot be read."""
    asks, asks_err = _browser_fallback_asks(root)
    value, why = key_value(root)
    if asks_err or value not in ("absent", "on", "off"):
        raise ValueError(asks_err or "config.json's search.posting_fetch does not read (%s)" % (why or value))
    if any(a.get("id") == NOTICE_ID for a in asks):
        return False
    _atomic.write_jsonl(os.path.join(root, "data", "asks.jsonl"), asks + [notice_row(value, datetime.date.today().isoformat())])
    return True


def stamp_new_profile(root, created):
    """Stamp `root` at the engine's version, pin it at `BROWSER_FALLBACK_PIN` and write the notice row, when it has no stamp yet.
    Appends what it wrote to the list `created`; prints a warning (never raises) for what it could not write."""
    if os.path.exists(os.path.join(root, stamp.STAMP)):
        return
    ok, err = stamp.write_stamp(root, stamp.engine_version())
    if not ok:
        print("  ⚠️ could not write %s (%s) — migrate.py will treat this profile as "
              "unmigrated and replay its whole chain on the next hook-firing session." % (stamp.STAMP, err))
        return
    created.append(stamp.STAMP)
    try:
        record_profile_schema(root, BROWSER_FALLBACK_PIN, "init_profile")
        created.append("data/runs.jsonl (the jobsearch %s profile pin)" % BROWSER_FALLBACK_PIN)
    except Exception as e:              # noqa: BLE001
        print("  ⚠️ could not record the profile pin (%s) — migrate.py will record it on the next hook-firing "
              "session." % e)
    try:
        if write_notice_row(root):
            created.append("data/asks.jsonl (the %s notice: the automatic posting fetch)" % NOTICE_ID)
    except Exception as e:              # noqa: BLE001
        print("  ⚠️ could not write the posting-fetch notice row (%s) — the automatic fetch sends nothing until "
              "`python3 posting_fetch.py --set auto` writes it." % e)
