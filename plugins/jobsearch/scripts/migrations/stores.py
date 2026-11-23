"""When each governed store was introduced (`STORE_INTRODUCED`), and whether a store's absence is legal for a stamp.
`validate_data.py` imports this module alone, not the registry (design §5.3).

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

from migrations.stamp import ver


# ⭐⭐ dev #365 (design-connected-entities.md §26.7/§28.2) — "no record of which version added
# which store" made a governed store's ABSENCE undecidable: a profile older than the stage that
# introduced a store legitimately never had it, but a MIGRATED profile missing the same file has
# lost data, and nothing told the two apart. This table is that record, compared against the
# stamp by `ver()` above — the same semver compare `pending_for()` uses, so there is only one
# answer to "is this version at or past that one" anywhere in the engine.
#
# ⭐ THE NINE PRE-ADR-031 STORES ARE FLOORED, NOT DATED. `opportunities`/`companies`/`channels`/
# `messages`/`inbox`/`pending_actions` were born together in `dc876f5` (plugin.json 0.1.0);
# `asks`/`commitments` in `ced242b` (0.25.0); `resume_variants` in `a2ce142` (0.38.0) — all
# THREE of those real birth versions predate `migrate.py` itself, which did not exist, and so
# could not stamp anything, before 0.5.0 (`ef814a5`). The smallest version any REAL profile can
# ever be stamped with is therefore 0.5.0 (the first release that wrote one at all) — no profile
# has ever existed, or ever will, with a genuine non-zero stamp between "0.0.0" and "0.4.0". So
# rather than inventing a precision the chain never had (and that no real profile could ever
# actually test), every one of these nine is floored at MIGRATIONS' own earliest key, "0.4.0" —
# a value chosen because it IS the oldest version this table's own comparison mechanism (the
# MIGRATIONS registry) can represent, verified by `min(v for v, _ in MIGRATIONS, key=ver)`
# rather than assumed. Below it: only "0.0.0" (never stamped at all), which is its own
# unconditional exemption in `validate_data.py`'s check regardless of this table's values.
#
# `people.jsonl`/`involvements.jsonl` through `plans.jsonl`/`plays.jsonl` are dated at the exact
# MIGRATIONS key that ships each (verified against the registry above, not against this
# comment): B1 0.44.0, B2 0.45.0, B3 0.48.0, B4 0.49.0.
#
# ⚠️ `resume_variants.jsonl` IS HERE BUT NOT ENFORCED THE SAME WAY — see the exemption comment
# beside `validate_data.py`'s own `check_store_introduction()`: legal-absent FOREVER (ADR-028,
# public #62), not merely pre-introduction — a single-resume profile never gets one, at any
# version. It still needs an entry here for the completeness test
# (`TestStoreIntroducedCompleteness`) to say so, rather than this table silently having nothing
# to say about a store `docs/data_model.json` governs.
#
# ⭐⭐ THE LEDGER (`briefs.jsonl`) IS DELIBERATELY NOT IN THIS TABLE AT ALL — the one
# `docs/data_model.json` store this table cannot cover. `check_ledger_reads.py`'s rule (a)
# fails any shipped file outside `brief.LEDGER_READERS` ({brief.py, validate_data.py, make_fixture.py,
# ledger/brief_rows.py}) that names the ledger by a bare `"briefs.jsonl"` string literal — a dict
# key here is exactly that shape, confirmed the hard way while building this table (it failed
# the gate). Importing `brief` here to derive the name indirectly was tried and reverted: `brief`
# imports `graph`/`inbox`/`journal`/`mail_client`/`posture`/`precondition`/`your_move`/
# `config_keys`/`credentials` at ITS OWN module level, so a top-level (or eagerly-invoked)
# `import brief` here would make importing `migrate` — which `drift_guard.py` and every
# `SessionStart` hook do unconditionally — pull in that whole chain too; it broke ten
# unrelated tests (`TestDriftGuardAsksTheRemedy` et al.) that build a minimal, isolated copy of
# `scripts/` and exercise `migrate.py` inside it. `validate_data.py` (a sanctioned reader) still
# carries its own `"briefs.jsonl": "0.46.0"` fact in `check_store_introduction()`'s own
# exemption comment; `TestStoreIntroducedCompleteness` states this one, named exception rather
# than silently expecting universal coverage. `m_0_46_0_brief_line` above creates the ledger
# empty the first time it does not already exist — its introduction version (0.46.0) is
# recorded there and in validate_data.py, never duplicated as a table entry here.
#
# `inbox.jsonl`/`pending_actions.jsonl` are also deliberately ABSENT from this table: they are
# the two stores `docs/data_model.json` does not govern (CLAUDE.md's fixture section), so
# neither the completeness test nor `validate_data.py` (which never loads either file today)
# has a schema to check them against — adding entries here would invent enforcement for a shape
# nothing documents. `init_profile.STORES` keeps scaffolding them unconditionally, as it always
# has; the fresh-scaffold gate's own completeness assertion only walks THIS table.
STORE_INTRODUCED = {
    "opportunities.jsonl": "0.4.0",
    "companies.jsonl": "0.4.0",
    "channels.jsonl": "0.4.0",
    "messages.jsonl": "0.4.0",
    "asks.jsonl": "0.4.0",
    "commitments.jsonl": "0.4.0",
    "resume_variants.jsonl": "0.4.0",          # legal-absent forever — see comment above
    "people.jsonl": "0.44.0",                  # ADR-031 B1
    "involvements.jsonl": "0.44.0",            # ADR-031 B1
    "applications.jsonl": "0.45.0",            # ADR-031 B2
    "cover_letters.jsonl": "0.45.0",           # ADR-031 B2
    "touches.jsonl": "0.48.0",                 # ADR-031 B3
    "plans.jsonl": "0.49.0",                   # ADR-031 B4
    "plays.jsonl": "0.49.0",                   # ADR-031 B4
    "proposals.jsonl": "0.86.0",               # dev #834 (network-first): `m_0_86_0_proposals` scaffolds it
    "outbox.jsonl": "0.91.0",                  # design-build-reach 9.1: no migration, absent is an empty outbox (validate_data exempts it)
    "presence_changes.jsonl": "0.93.0",        # presence-report 8.2: ships in 0.93.0, a registered key since m_0_93_0_word_round_trip (design-resume-docx R3-3); absent is empty (exempt)
    # the ledger is NOT here — see the comment above
}


def store_absence_legal(stamp, store):
    """Is `store`'s absence legal for a profile stamped `stamp` (dev #365)?

    Legal when the profile has never been stamped at all (`"0.0.0"` — the old behaviour, so a
    pre-stamp profile stays green until its first hook-firing session) OR when its stamp
    predates the version `STORE_INTRODUCED` says introduced this store. At or past that
    version, absence is NOT legal — a migrated profile that should already have this file is
    missing one, which is a validator failure, never a silent "nothing to check".

    An unrecognised `store` (not in the table at all) returns True: this function has no
    opinion about a store it was never told the introduction version of, and defaulting to
    "problem" for an unknown name would be inventing a claim `STORE_INTRODUCED` does not make.
    """
    introduced = STORE_INTRODUCED.get(store)
    if introduced is None:
        return True
    return stamp == "0.0.0" or ver(stamp) < ver(introduced)
