#!/usr/bin/env python3
"""RETIRED (ADR-031 B1, 2026-09-10) — `contacts[]` no longer exists.

WHAT THIS WAS
-------------
Made `contacts[]` the real contact record for an opportunity, and joined `outreach[]` to it —
built 2026-08-02 after the candidate asked whether the structure was managing all the contact
data for an opportunity. It measurably wasn't: 20 of 46 outreach rows had no contact record at
all, `outreach[].to` was free text that could not join to `contacts[].name`, and 0 of 60
contacts had a structured email field (six addresses existed, buried in prose).

WHY IT IS RETIRED, NOT DELETED
-------------------------------
ADR-031's connected-entities design promoted `opportunities.contacts[]` and
`channels.contacts[]` into two GLOBAL, top-level stores — `people` and `involvements` — because
a contact scoped to one opportunity could not represent "the same recruiter across three
different roles," which is exactly the shape a real search produces. The B1 migration
(`migrate.py::m_0_44_0_people_involvements`) is this script's successor: same problem
(join outreach to the people it actually went to), same "preserve, never guess" discipline,
now against a store with an identity rule (ADR-031 §3) this script never had.

The file stays, retired rather than deleted, for the same reason `RETIRED_CHANNEL_IDS` keeps a
channel id around after it stops being used: a doc, an old commit message, or a script still
tracked in git history may reference `scripts/migrate_contacts.py` by name, and a dangling
reference is worse than a file that explains itself.

`check_retired_reads.py` — the AST scanner that fails a shipped script reading `contacts` by
literal key — does not need a `KNOWN_EXCEPTIONS` entry for this file: it reads nothing anymore.

Python 3.9+. Standard library only. No profile is opened; this script does not run.
"""
import sys


def main():
    print("migrate_contacts.py is RETIRED (ADR-031 B1, 2026-09-10) — `contacts[]` no longer "
          "exists. `people`/`involvements` are real, top-level, globally-unique stores now; "
          "opportunities.contacts[] and channels.contacts[] were promoted into them by "
          "migrate.py's m_0_44_0_people_involvements, which every existing profile already ran "
          "the moment it upgraded past that version. There is nothing left for this script to "
          "do.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
