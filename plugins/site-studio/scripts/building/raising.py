"""The raise-to-schema-3 report's record and the text it keeps when it rewrites `site.json`."""

import content as C

from building.outcomes import BuildError


# ---------------------------------------------------------------- the raise to schema 3 (design section 3.4)

class RaiseReport(object):
    """What `raise_report` found. `differences` is [(output path, source, detail)]: every output file whose
    bytes differ between the old reading and schema 3's (`source` is the page's source file, when it has one).
    `problems` is what schema 3 refuses that the old reading accepted (never confirmable). `base_problems` is
    what the site refuses TODAY, before any raise. `site_json` is the text a raise would write."""

    def __init__(self, differences, problems, base_problems, site_json):
        self.differences = differences
        self.problems = problems
        self.base_problems = base_problems
        self.site_json = site_json


def _first_difference(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "(end)"
        y = lb[i] if i < len(lb) else "(end)"
        if x != y:
            return "line %d: %r -> %r" % (i + 1, x[:70], y[:70])
    return "binary content differs"


def _keep_text(files, specs):
    """The tree with a `\\` put at the start of each PATH:LINE the person wants kept as text. Raises
    BuildError naming a line that is not one schema 3 reads differently."""
    out = dict(files)
    reasons = set((p, n) for p, n, _form in C.interpretation_reasons(files))
    for spec in specs:
        path, _, n = spec.rpartition(":")
        if not n.isdigit() or path not in files:
            raise BuildError("--keep-text %s: write it as PATH:LINE, naming a file under content/" % spec,
                             fix="use --keep-text content/<folder>/index.md:<line number>")
        if (path, int(n)) not in reasons:
            raise BuildError("%s is not a line schema 3 reads differently, so there is nothing to keep as text"
                             % spec, fix="run raise-schema without --keep-text to see the lines it lists")
        lines = C.decode_text(out[path], path).split("\n")
        lines[int(n) - 1] = "\\" + lines[int(n) - 1]
        out[path] = "\n".join(lines).encode("utf-8")
    return out
