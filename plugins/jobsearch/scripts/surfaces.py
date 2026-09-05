#!/usr/bin/env python3
"""The publishing surfaces a declared resume variant can target — ONE lookup table.

⭐ WHY ONE TABLE (ADR-028 rule 6, ADR-027). Two decisions read the same fact about a
surface: the working-set artifact measures a field against the surface's character cap
(rule 6), and the variant containment gate derives a page's VISIBILITY from the surface it
targets (ADR-027: `public` when any reader can reach the page without being chosen,
`private` when the candidate picks every recipient). Kept in two places those would drift —
a surface's publication reach disagreeing with its own character budget — so both read here.

⭐ A CAP IS AN OBSERVATION WITH A DATE, NEVER A CONSTANT. The engine cannot query a platform
for its own limits; a cap is measured once, by a person, and restated with the date it was
measured (`as_of`). A surface with no cap says so (`cap: None`), which is a different fact from
"nobody looked".

⭐ AN UNKNOWN SURFACE FAILS. `get()` raises on a name this table does not carry — the same
posture ADR-027 takes toward an unmarked surface and precondition.py takes toward an unreadable
value: undecidable is loud, never a default that silently permits everything.

## Step 1 (ADR-028 build, 0.39.0): the `print` surface ONLY.

A printed resume — handed to a named recipient, no field cap. Every declared variant renders
under it until the variant row carries its own `surface` field (ADR-027 / ADR-028 step 3,
a schema change this step deliberately does not make). Adding a surface is adding a row here,
with its cap measured and dated, never inferred from its name.

Usage (library; the CLI prints the table):
    python3 scripts/surfaces.py

Python 3.9+. Standard library only.
"""

import sys

# name -> the surface's declared properties. `visibility` is by PROPERTY (who can reach the
# page), never by name. `cap` is characters per field, or None when the surface has no hard
# limit; `as_of` dates the measurement that produced `cap` (None when there is no cap to date).
SURFACES = {
    "print": {
        "label": "printed resume",
        "visibility": "private",       # the candidate chooses every recipient
        "cap": None,                   # a page has no per-field character limit
        "as_of": None,
        "why": "a resume handed to a named recipient: sent, never published",
    },
}

# The surface a variant renders under while no row carries a `surface` field (step 3). Not a
# guess — with one row in the table there is exactly one possible value, and the strip on
# the working set says which it is and why.
DEFAULT_SURFACE = "print"

VISIBILITIES = ("public", "private")


def names():
    """Every declared surface name, in declaration order."""
    return tuple(SURFACES)


def get(name):
    """The surface's row. KeyError, loudly, on a name the table does not carry — a variant
    targeting an undeclared surface must fail at the call site, never resolve to a guess."""
    if name not in SURFACES:
        raise KeyError("surface %r is not declared in surfaces.py (known: %s) — declare it, "
                       "with its cap measured and dated, before a variant can target it"
                       % (name, ", ".join(SURFACES)))
    return SURFACES[name]


def visibility(name):
    return get(name)["visibility"]


def cap(name):
    """(cap_chars_or_None, as_of_or_None)."""
    row = get(name)
    return row["cap"], row["as_of"]


def describe(name):
    """One line for a strip outside a pane: the surface, its reach, its cap and the date."""
    row = get(name)
    limit = ("no character cap" if row["cap"] is None
             else "cap %d chars per field, measured %s" % (row["cap"], row["as_of"] or "?"))
    return "%s (%s) — %s, %s" % (name, row["label"], row["visibility"], limit)


def main():
    print("SURFACES — the destinations a declared variant can target (surfaces.py)\n")
    for n in names():
        print("  %s" % describe(n))
        print("      %s" % SURFACES[n]["why"])
    print("\n  default while no variant row carries a `surface` field: %s" % DEFAULT_SURFACE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
