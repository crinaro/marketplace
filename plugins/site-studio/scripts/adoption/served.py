"""adoption.served -- rule S: a file is accounted for by what is served from it (design-adopt-parity-2 section 8).

Part of the `adoption` package behind the entry point `adopt.py`. `adoption.usage` runs the counterfactual and
`adoption.fileacct` gathers the evidence; this module holds the readings rule S adds, each pure over plain data:

  S1  the plugin's side is what its build USED (`Acceptance.used`, step 5a). A file the build used whose old use attribution
      does not show is judged WITHOUT a run where it can be (`run_free_use`): its folder is served (a content unit of which
      another file's bytes are published), or a line of its text is in the old output. Only a file with neither still goes
      to the counterfactual (dated note 2026-11-21, step 10: design section 8 says such a file is never sent; a file whose
      use nothing else can show, a reference's `reference.json` whose JSON lines no page prints, would otherwise read
      "nothing builds or reads it" while the plugin's build reads it).
  S2  the old side is what the old site served: the counterfactual's groups are UNITS (`unit_of`: `content/<a>/<b>/` whole,
      else a directory), removed together, so an unused reference is one run that changes nothing. Its files are
      `archived` with the note `UNUSED_WHY` (rule `unused`), never a blocker; `unused_lines` names them by unit. A unit whose
      removal changes only its own published files, at addresses no old page links, is the same (`unlinked_removal`, step 10b),
      and P2 lists those addresses as `unlinked` ACCEPT rows.
  S3  a crash is not use (`crash_reading`): a file whose removal alone makes the old builder exit non-zero is asked one
      question, is anything of it published? "No" only on evidence: it decodes as UTF-8, holds at least one line of
      `MIN_LINE` characters or more, and none of those lines is in the old output. Then it is source material inside a
      content unit (`archived`, `unused`) or builder state anywhere else (`engine`). A file with no such line (binary,
      empty, short lines) gives no evidence: it stays used, and its row says so. A line that IS published is use.
      The template's stamp (`<resume pdf>.sha256` beside a PDF the plugin writes its own sidecar for) is builder state
      without a run, but only where `parity.template_fingerprint` holds (`template_stamp`).
  S4  every reason says what was served from the file: the output path that holds its bytes or its text.
"""

import posixpath

from adoption.accepts import linking_pages
from adoption.parity import template_fingerprint

MIN_LINE = 8                     # S3: a line this long or longer is evidence; a shorter one could be in any page by chance
YES, NO, UNKNOWN = "yes", "no", "unknown"
UNUSED_WHY = "unused: source material no page shows"
STATE_WHY = "builder state: your builder needs it to run and publishes nothing from it"
UNKNOWN_WHY = "your builder stops without it and site-studio cannot tell what it publishes from it"


def unit_of(path):
    """The unit `path` belongs to (S2): `content/<a>/<b>/` for a file inside a piece's or a reference's folder (at any depth),
    else its directory with a trailing `/` (`""` at the root)."""
    parts = path.split("/")
    if len(parts) >= 4 and parts[0] == "content":
        return "/".join(parts[:3]) + "/"
    folder = posixpath.dirname(path)
    return folder + "/" if folder else ""


def is_content_unit(unit):
    """True for a piece's or a reference's folder, `content/<a>/<b>/`."""
    return unit.startswith("content/") and unit.count("/") == 3


def units_of(paths):
    """The counterfactual's first groups (S2): the paths of one unit together, sorted, so a run is repeatable."""
    by = {}
    for p in sorted(paths):
        by.setdefault(unit_of(p), []).append(p)
    return [by[u] for u in sorted(by)]


def lines_of(blob):
    """The lines of `blob` that are evidence (S3), stripped; None when it does not decode as UTF-8."""
    try:
        text = blob.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    return [l.strip() for l in text.splitlines() if len(l.strip()) >= MIN_LINE]


def old_texts(old_out):
    """{output path: text} of every old output file that decodes as UTF-8: where S3 looks for a line."""
    out = {}
    for path, data in old_out.items():
        try:
            out[path] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return out


def published_in(blob, texts):
    """(YES, the first output path holding one of its lines) | (NO, None) | (UNKNOWN, None): is anything of `blob` published
    in the old output `texts` (`old_texts`)? UNKNOWN when the file has no line that is evidence (S3)."""
    lines = lines_of(blob)
    if not lines:
        return UNKNOWN, None
    for path in sorted(texts):
        if any(l in texts[path] for l in lines):
            return YES, path
    return NO, None


def crash_reading(path, blob, texts):
    """S3 for `path`, whose removal alone makes the old builder exit non-zero: ("old", why) when it is used (its text is
    published, or nothing can be told), ("unused", why) for source material inside a content unit that publishes nothing,
    ("state", why) for builder state anywhere else."""
    verdict, where = published_in(blob, texts)
    if verdict == YES:
        return "old", "your builder exits non-zero when it is missing, and its text is published in %s" % where
    if verdict == UNKNOWN:
        return "old", UNKNOWN_WHY
    unit = unit_of(path)
    if is_content_unit(unit):
        return "unused", "%s (%s); your builder stops without it" % (UNUSED_WHY, unit)
    return "state", STATE_WHY


def run_free_use(candidates, old_why, read, texts):
    """{path: why} for the files of `candidates` (used by the plugin's build, not shown used by the old one) that the old
    side serves, judged without a run (S1): a content unit another file of which `old_why` ({basis path: why}) shows
    published, or a line of the file in the old output (`texts`). `read(path)` gives a basis file's bytes."""
    served = {}
    for q in sorted(old_why):
        unit = unit_of(q)
        if is_content_unit(unit):
            served.setdefault(unit, q)
    out = {}
    for p in sorted(candidates):
        unit = unit_of(p)
        if unit in served:
            out[p] = "its folder %s is served (%s: %s)" % (unit, served[unit], old_why[served[unit]])
            continue
        verdict, where = published_in(read(p), texts)
        if verdict == YES:
            out[p] = "its text is published in %s" % where
    return out


def unlinked_removal(base, variant, unit, same):
    """S2's last sub-rule (step 10b, step 10's F6): the old output paths that removing the content unit `unit` takes away, when
    that is ALL the removal changes and no old page links what it takes, else None. `base` is the old output on the unchanged
    tree, `variant` the output with the unit removed, `same(a, b)` P2's comparison. It holds when (1) the variant adds nothing
    and every output it keeps reads `same`, (2) each path it loses is the unit's own (the unit's folder name is a segment of the
    path, or the stem of its last one), and (3) no remaining old page holds an address of one of them (`accepts.linking_pages`).
    Such a unit is source material no page shows (`archived`, rule `unused`); P2 lists its addresses as `unlinked` rows."""
    if not is_content_unit(unit):
        return None
    gone = sorted(p for p in base if p not in variant)
    if not gone or any(p not in base for p in variant):
        return None
    rest = dict((p, b) for p, b in base.items() if p not in gone)
    if not same(rest, variant):
        return None
    name = unit.rstrip("/").split("/")[-1]
    if any(name not in p.split("/")[:-1] and posixpath.splitext(posixpath.basename(p))[0] != name for p in gone):
        return None
    if any(linking_pages(rest, p) for p in gone):
        return None
    return gone


def template_stamp(tree, resume_pdf, sidecar):
    """The template's stamp beside the resume PDF (S3, without a run): `<resume pdf>.sha256`, when the plugin writes its own
    sidecar (`sidecar`: the PDF is a named input) and the repo has the template's shape (`template_fingerprint`); else
    None. On any other repo a file of that name gets the general rule, which needs the run."""
    if not resume_pdf or not sidecar:
        return None
    stamp = resume_pdf + ".sha256"
    if stamp not in tree.paths() or not template_fingerprint(tree):
        return None
    return stamp


def stamp_why(resume_pdf):
    return "%s (the template's stamp of %s; site-studio writes its own sidecar, %s.json)" % (STATE_WHY, resume_pdf, resume_pdf)


def unused_lines(dispositions):
    """The note (never a blocker) naming the units whose files are archived as source material no page shows (S2)."""
    by = {}
    for p, (disp, why) in sorted((dispositions or {}).items()):
        if disp == "archived" and why.startswith(UNUSED_WHY):
            by.setdefault(unit_of(p), []).append(p)
    if not by:
        return []
    return ["unused source: %d file(s) in %d folder(s) no page shows, archived and never a blocker: %s"
            % (sum(len(v) for v in by.values()), len(by), ", ".join("%s (%d)" % (u or "/", len(v)) for u, v in sorted(by.items())))]
