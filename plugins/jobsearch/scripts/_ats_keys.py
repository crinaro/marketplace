"""The `config.json.ats` key names, spelled ONCE — the target every ATS receipt reader resolves.

WHY THIS EXISTS (0.41.0, design pass A step 1)
-----------------------------------------------
`init_profile.py` seeded `ats.sender_domains` / `ats.receipt_phrases` while the profiles that
actually run carried `receipt_sender_domains` / `receipt_subject_phrases`: two spellings of one
meaning, split across the scaffold and the data. A reader written against either name would
have been VACUOUS on every profile carrying the other — a missing thing reading as an empty
one, which is public #56's class and this marketplace's characteristic failure. Step 1 fixes
the names before any reader exists, so the reader's target is guaranteed rather than hoped.

This module is a leaf: no imports, no I/O. `migrate.py` renames toward these names,
`init_profile.py` seeds them, and the regression suite holds the seeder's literal keys equal
to `READER_KEYS` (the `resume_variants.SUBMITTED` mirror precedent) — the seeder stays a
readable literal on purpose, and the test is what keeps it honest.

Python 3.9+. Standard library only.
"""

# The domains an ATS sends application receipts from (`greenhouse-mail.io`-shaped, synthesized
# in every example here). A reader matches an inbound sender against this list.
RECEIPT_SENDER_DOMAINS = "receipt_sender_domains"

# Subject phrases keyed by the `applications[].status` they evidence. `acknowledged` is the
# pre-0.41.0 `receipt_subject_phrases` list relocated (m_0_41_0_ats_status_phrases: preserve,
# then transform); the other lists are seeded empty so a reader finds the SHAPE and can say
# "no phrases configured for X" instead of finding nothing at all.
STATUS_PHRASES = "status_phrases"
STATUS_PHRASE_KEYS = ("acknowledged", "rejected", "advanced")

# The pre-0.41.0 home of the acknowledged-receipt phrases. Read by the move migration only;
# a reader never looks here.
RECEIPT_SUBJECT_PHRASES = "receipt_subject_phrases"

# old spelling (what init_profile.py seeded before 0.41.0) -> the name a reader looks for.
# `receipt_phrases` renames to the pre-move name on purpose: the rename migration runs FIRST,
# and the move migration then carries that list into status_phrases.acknowledged — one
# relocation path for every profile, whichever spelling it started with.
LEGACY_RENAMES = (("sender_domains", RECEIPT_SENDER_DOMAINS),
                  ("receipt_phrases", RECEIPT_SUBJECT_PHRASES))

# What a reader resolves — and therefore exactly what the scaffold must seed.
READER_KEYS = frozenset({RECEIPT_SENDER_DOMAINS, STATUS_PHRASES})
