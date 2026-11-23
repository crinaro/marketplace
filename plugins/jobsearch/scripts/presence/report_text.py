"""report_text: the fixed wording of the presence report (design-presence-report.md §5, §5.5, §5.7): section headers,
the `NOT CHECKED` line, the readability line under each render mode, the `scanned:` line, and the question lines.

**An unchecked input is never an empty result.** `INPUTS` names the five inputs that can be unchecked, in the order
the `scanned:` line lists them: `titles`, `variants`, `union`, `roles`, `linkedin`.

**Readability (§5.5) is a property of the renderer**, not a score of the candidate's writing: under `local_docx` the
line says what this plugin's renderer produces (`tests/test_docx_structure.py` and `tests/test_misc.py` prove it);
under `drive` it is NOT CHECKED, because the documents connector makes that file. Pure text; nothing here reads."""

SECTIONS = (("title", "5.1 Lead title"), ("requirements", "5.2 Requirement coverage"),
            ("quantified", "5.3 Quantified bullets"), ("outcomes", "5.4 Outcomes by variant"),
            ("readability", "5.5 Readability"), ("linkedin", "5.6 LinkedIn coverage"))
INPUTS = ("titles", "variants", "union", "roles", "linkedin")
READABILITY = {
    "local_docx": ("Readability (local_docx): the .docx this plugin renders is one column with no tables or text "
                   "boxes. This is a property of the renderer, not a score of your resume, and says nothing about a "
                   "file made elsewhere."),
    "drive": ("Readability: NOT CHECKED (render mode is drive: the document is made by the documents connector, not "
              "by this plugin's renderer)."),
}
ATTENDED_FORM = "/jobsearch:weekly-review attended"


def header(name):
    return "== %s ==" % dict(SECTIONS)[name]


def not_checked(reason, indent="  "):
    return "%sNOT CHECKED (%s)" % (indent, reason)


def readability_line(mode):
    """§5.5's line for a render mode; a mode this table does not know is NOT CHECKED, never a guess."""
    if mode in READABILITY:
        return READABILITY[mode]
    return "Readability: NOT CHECKED (render mode %r is not one this report knows: %s)" % (mode, ", ".join(READABILITY))


def scanned_line(counts, unchecked):
    """`scanned: 3 variants, 11 pursued roles, 96 requirement rows, 2 target titles; NOT CHECKED: linkedin (not
    stated)`. `counts` holds `variants`, `roles`, `rows`, `titles`; `unchecked` is `{input: reason}`."""
    line = "scanned: %d variants, %d pursued roles, %d requirement rows, %d target titles" % (
        counts.get("variants", 0), counts.get("roles", 0), counts.get("rows", 0), counts.get("titles", 0))
    names = [n for n in INPUTS if n in unchecked]
    if names:
        line += "; NOT CHECKED: " + ", ".join("%s (%s)" % (n, unchecked[n]) for n in names)
    return line


def unchecked_names(unchecked):
    """The unchecked inputs' names in `INPUTS` order, for the `DISPATCH: no (NOT CHECKED: ...)` line."""
    return [n for n in INPUTS if n in unchecked]


def question_line(what, attended):
    """§5.7: `ASK: <what>` in the attended form; `LISTED: <what> (answered in <the attended form>)` otherwise."""
    return "ASK: %s" % what if attended else "LISTED: %s (answered in %s)" % (what, ATTENDED_FORM)


def refused_line(key):
    """§R3-4: a refused key is listed on every `--gaps`, so the state is never silent."""
    return "LISTED: refused %s (only an attended review redrafts it)" % key
