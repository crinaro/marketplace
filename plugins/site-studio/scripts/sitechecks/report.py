"""report.py -- what the site gate reports: the thirteen families, a finding, the report, and its two printed forms
(dev #835, design 4.3).

THE FAMILIES (design 4.3). A finding names its family. There is NO command-line way to skip, waive or ignore a
family or a finding: a false positive is fixed in the module that holds the family, with a dated note in that
module's docstring (`linking.py` carries the two so far).

COVERAGE (CLAUDE.md: a green run is never an empty one). The gate prints what it scanned (`checked: ...`). A tree
with no HTML page is a failure in `structure`, not a pass.

--json prints one JSON object per line: each finding ({"level":"error","family","path","message"}), each NOT READ
PDF ({"level":"not-read",...}), with --report each external link ({"level":"report","kind":"external-link","url",
"pages"}), then one {"level":"summary",...}. A NOT READ PDF is listed and is never counted clean (privacy.py).
"""

import json


FAMILIES = ("structure", "comments", "links", "reachable", "privacy", "domain", "media",
            "unfinished", "performance", "head", "nav", "basepath", "size")


class Finding(object):
    def __init__(self, family, path, message, level="error"):
        self.family, self.path, self.message, self.level = family, path, message, level

    def to_dict(self):
        return {"level": self.level, "family": self.family, "path": self.path,
                "message": self.message}

    def sort_key(self):
        return (FAMILIES.index(self.family) if self.family in FAMILIES else 99, self.path,
                self.message)


class Report(object):
    def __init__(self):
        self.findings = []
        self.not_read = []          # Finding objects, level "not-read"
        self.pdfs_read = 0
        self.externals = {}         # url -> set(pages)
        self.checked = {}
        self.notes = []
        self.skipped = []

    def add(self, family, path, message):
        self.findings.append(Finding(family, path, message))

    def count(self, family, n=1):
        self.checked[family] = self.checked.get(family, 0) + n

    @property
    def ok(self):
        return not self.findings


def render_text(rep, report_links, header):
    lines = []
    for f in rep.findings:
        lines.append("%-11s %s: %s" % (f.family, f.path, f.message))
    lines.append("PDFs: %d read, %d NOT READ (listed below)" % (rep.pdfs_read, len(rep.not_read)))
    for f in rep.not_read:
        lines.append("NOT READ   %s: %s" % (f.path, f.message[len("NOT READ: "):]))
    if rep.not_read:
        lines.append("NOT CHECKED: %d PDF(s) could not be read and are listed for privacy-guard" % len(rep.not_read))
    for note in rep.notes:
        lines.append(note)
    if rep.checked:
        lines.append("checked: " + " · ".join("%s %d" % (k, rep.checked[k]) for k in FAMILIES if k in rep.checked))
    if report_links:
        lines.append("external links (%d):" % len(rep.externals))
        for url in sorted(rep.externals):
            lines.append("  %s  <- %s" % (url, ", ".join(sorted(rep.externals[url]))))
    fams = sorted(set(f.family for f in rep.findings), key=lambda x: FAMILIES.index(x) if x in FAMILIES else 99)
    lines.append("%s: %s (%d finding(s)%s)" % (header, "FAIL" if rep.findings else "PASS", len(rep.findings),
                                                " in " + ", ".join(fams) if fams else ""))
    return "\n".join(lines)


def render_json(rep, report_links):
    out = [json.dumps(f.to_dict(), sort_keys=True) for f in rep.findings]
    out += [json.dumps(f.to_dict(), sort_keys=True) for f in rep.not_read]
    if report_links:
        for url in sorted(rep.externals):
            out.append(json.dumps({"level": "report", "kind": "external-link", "url": url,
                                   "pages": sorted(rep.externals[url])}, sort_keys=True))
    out.append(json.dumps({"level": "summary", "findings": len(rep.findings),
                           "pdfsRead": rep.pdfs_read, "pdfsNotRead": len(rep.not_read),
                           "checked": rep.checked, "notes": rep.notes}, sort_keys=True))
    return "\n".join(out)
