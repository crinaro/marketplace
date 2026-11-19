"""Migration 0.29.0: `m_0_29_0_gmail_connector_config()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.29.0"


def m_0_29_0_gmail_connector_config(profile, apply_it, home=None):
    """0.29.0 — the Gmail MCP server moved to the standalone `gmail-multi` connector plugin
    (marketplace ADR-004). It used to point the connector's `include` list at this profile's  # retired-terms: ok
    `user.json`, so a mailbox added to the profile reached the connector with no second copy.

    ⭐⭐ RETIRED AS A WRITER by 0.63.0 (dev #469, F7; dated 2026-10-12) — it now writes NOTHING, in
    every registry state, and returns a one-line note. gmail-multi owns the ONE account registry
    and its one writer is gmail-multi's own `accounts.py` (A1); `include` is gone from gmail-multi  # retired-terms: ok
    0.5.0 (A4), so an include written here would be a dead key at best, and at worst a second
    writer re-adding a profile reference to a file this plugin no longer owns. A profile older than
    0.29.0 that upgrades straight to the current release therefore never touches the registry:

      * registry schema 2, schema 1 or ABSENT -> unchanged, byte for byte (absent stays absent)
      * the profile's addresses reach gmail-multi through `m_0_63_0_mailbox_references`, which
        READS the registry and raises a queryable ask per address it lacks — a decision for the
        user (`/gmail-multi:accounts`), never a hidden write.

    The function stays REGISTERED: `check_migration_keys.py` requires a published migration to stay
    in the table, and a profile stamped below 0.29.0 still has it pending. `apply_it` and `home` are
    accepted and ignored for the same signature's sake. Pinned by `TestM0290IsNoLongerAWriter`.
    """
    if not os.path.exists(os.path.join(profile, "user.json")):
        return True, ""
    return True, ("  gmail-multi's registry is gmail-multi's alone to write (0.63.0): this "
                  "profile's mailboxes are checked against it by the 0.63.0 step, not copied in.")
