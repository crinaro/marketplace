"""Migration 0.50.0: `m_0_50_0_variant_surface_field()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl

VERSION = "0.50.0"


def m_0_50_0_variant_surface_field(profile, apply_it):
    """0.50.0 — public #59/#64, ADR-027 (build step 3 of ADR-028's own `surface` field):
    `resume_variants.py --check` proved only that a printed claim traces to the union, which
    is the right check for a page sent to a named recipient and the wrong one, alone, for a
    page published to the open web. Every declared variant now carries `surface`
    (`scripts/surfaces.py` is the one lookup table); `visibility` is DERIVED from it and is
    never stored (ADR-027 rejected storing it a second time — the alternative an EARLIER,
    now-superseded version of this same fix tried; see docs/doc_impact.jsonl).

    ⚠️ ADR-027, quoted, governs what this migration may NOT do: "An undeclared `surface` is
    not a default — it is a state, and it fails" ... "Default-private ... hides the true state
    (nobody decided) behind a value that looks decided" ... "Neither default is acceptable;
    the gate must refuse to guess." That is a rule about resume_variants.py's own CHECK LOGIC
    going forward — it must never treat an absent `surface` as `print` on an ONGOING basis.

    What this migration DOES do, and why it is not the rejected alternative: at 0.50.0,
    `surfaces.SURFACES` carries exactly ONE entry (`print`) reachable by any PRE-EXISTING
    variant (the second, `public-profile`, is new in this same release and cannot be what an
    already-declared row meant). `surfaces.py`'s own prior comment on this exact fact: "Not a
    guess — with one row in the table there is exactly one possible value." Seeding `print`
    here is recording, once, in an audited migration, the single fact that was already true of
    every such row (the code's own `DEFAULT_SURFACE` fallback already rendered every one of
    them as `print` before this field existed) — never an ongoing default a reader would have
    to already suspect the gap to find, and never a guess among options that could disagree.
    Going forward the CHECK never guesses: a NEW row with no `surface`, or a profile that
    later gains a third surface, is `unplaced` — a state, never a default — exactly as
    ADR-027 requires.

    RETIRED rows are seeded too (a store that reads uniformly; the CHECK itself never asks a
    retired row for its surface, same as it never asks a retired row for anything else —
    terminal, no claim checks). PRESERVE, THEN TRANSFORM is vacuous in the usual sense
    (nothing is relocated — a missing key is filled, not a value replaced) but the
    ADDITIVE-ONLY half still matters: a row that already carries ANY value for `surface` —
    including a value this migration would not itself have chosen — is left exactly as it is.

    Idempotent: a second run finds no row missing the key and reports a no-op.
    """
    path = os.path.join(profile, "data", "resume_variants.jsonl")
    if not os.path.exists(path):
        return True, ""
    try:
        rows = _read_jsonl(path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ resume_variants.jsonl could not be read — nothing seeded: %s" % e
    missing = [r for r in rows if "surface" not in r]
    if not missing:
        return True, ""
    if not apply_it:
        return True, ("  would seed (0.50.0) resume_variants.jsonl: surface=print on "
                      "%d row(s) (the one surface any pre-existing row could mean)"
                      % len(missing))
    for r in rows:
        if "surface" not in r:
            r["surface"] = "print"
    import _atomic
    _atomic.write_jsonl(path, rows)
    return True, ("  ✅ resume_variants.jsonl (0.50.0) — seeded surface=print on %d row(s) "
                 "(the only surface a pre-existing row could mean); declare 'public-profile' "
                 "by hand on the one meant for the open web — the engine cannot make that "
                 "call for you, and any FUTURE row with no surface is 'unplaced', never "
                 "guessed" % len(missing))
