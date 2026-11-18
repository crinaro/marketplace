"""adoption.reports -- the blocker report step: `adopt.py report [--file | --decline]` and the reports record (design 8 RP).

Part of the `adoption` package behind the entry point `adopt.py`.

`apply` and `remeasure` write `.site-studio/adopt-reports.json` (one row per PLUGIN cause id, never per occurrence) whenever
the outcome is blocked, and print "blocked: N causes; run `adopt.py report` to read them". This module is the command that
reads them:

  report            prints every pending report (the closed body `report_issue.build_report` builds: a cause id, its
                    count and catalogue rows, the versions; nothing of the site). Files nothing.
  report --file     files them on the tracker after the dedup `report_issue.dedupe` does (an open or not-planned issue is
                    `existing`; a completed one in a newer version is `upgrade`; in an older or the same, `regressed`),
                    and commits ONLY the reports record. A person's yes is the person's own command: the publish guard
                    treats `report --file` and its abbreviations as a publish (step 1.6r), so an unattended run in a
                    deny mode prints the reports and leaves the rows pending.
  report --decline  records `declined` for every pending cause; a declined cause is offered again only on a newer version.

`--repo` is a TOP-LEVEL option, written before the verb (`adopt.py --repo X report --file`): the guard resolves the target
repository from it, from the working directory or from a `cd`, and the `report` subparser is built with `allow_abbrev=False`
so `--fil` can never mean something else (design Q1.10; the top-level parser's setting does not reach a subparser).

Everything the report says comes from `report_issue`; this module reads the record at HEAD, builds the leak-check terms from
the repository's own paths and content, and commits the record. It never reads a profile and never prints a site path.
"""

import os
import shutil
import sys

import report_issue  # noqa: E402

from adoption.base import Refused, git, gitt

REPORTS_REL = ".site-studio/adopt-reports.json"


def rows_at(repo, ref="HEAD"):
    """The parsed reports record at `ref`, or [] when the tree holds none."""
    shown = git(repo, "show", "%s:%s" % (ref, REPORTS_REL), check=False)
    if shown.returncode != 0:
        return []
    try:
        return report_issue.parse_reports(shown.stdout.decode("utf-8", "replace"))
    except report_issue.ReportsError as e:
        raise Refused("%s: %s; edit the file, or restore the committed copy from an earlier commit" % (REPORTS_REL, e))


def site_terms(repo):
    """The words a report body must never hold (RP check 2): every path segment of `git ls-files` and every word of four or
    more letters in the converted content. The two build outputs' class and id tokens are added by the caller that has
    built them."""
    paths = gitt(repo, "ls-files", check=False).split("\n")
    text = []
    for p in paths:
        if p.startswith("content/") and p.lower().endswith(".md"):
            try:
                with open(os.path.join(repo, *p.split("/")), "r", encoding="utf-8", errors="replace") as fh:
                    text.append(fh.read())
            except OSError:
                pass
    return report_issue.collect_terms(paths=[p for p in paths if p], text=text)


def write_rows(repo, rows):
    path = os.path.join(repo, *REPORTS_REL.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report_issue.dump_reports(rows))


def commit_record(repo, message):
    """Commit ONLY the reports record on the current branch (as `remeasure` commits its record)."""
    if git(repo, "var", "GIT_COMMITTER_IDENT", check=False).returncode != 0:
        raise Refused("git has no committer identity; set user.name and user.email and run it again")
    git(repo, "add", "-f", "--", REPORTS_REL)
    git(repo, "commit", "-q", "-m", message, "--", REPORTS_REL)


def cmd_report(repo, file=False, decline=False, runner=None, out=None, err=None, engine=None):
    """`adopt.py report`. Returns the exit code: 0 done, 1 could not file or check (the reports are printed), 2 a report
    was refused for carrying something of the site (nothing was filed, the record is unchanged)."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise Refused("adopt runs on your own computer, not in a cloud session; open the repo there")
    if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise Refused("%s is not a git checkout; run adopt from your site's repo folder, or pass it with --repo" % repo)
    rows = rows_at(repo)
    if not rows:
        out.write("report: there are no blockers recorded (no %s): nothing to report\n" % REPORTS_REL)
        return 0
    if decline:
        new = report_issue.decline(rows)
        n = sum(1 for a, b in zip(rows, new) if a["state"] != b["state"])
        if n:
            write_rows(repo, new)
            commit_record(repo, "adopt report: %d cause(s) declined" % n)
        out.write("report: %d pending cause(s) declined; each is offered again only by a newer site-studio\n" % n)
        return 0
    pending = [r for r in rows if r["state"] in ("pending", "regressed")]
    if not pending and not file:
        out.write("report: no pending blockers (%d recorded: %s)\n" % (
            len(rows), ", ".join(sorted(set(r["state"] for r in rows)))))
        return 0
    causes = [{"id": r["id"], "count": r["count"], "rows": list(r["rows"]), "class": None, "verdict": None, "kind": None}
              for r in pending]
    prov = report_issue.provenance(engine=engine, node=shutil.which("node") is not None)
    res = report_issue.report(causes, prov, terms=site_terms(repo), file=file, previous=rows, runner=runner, out=out,
                              err=err, engine=engine)
    if file and res["code"] != 2 and res["rows"] != rows:
        write_rows(repo, res["rows"])
        commit_record(repo, "adopt report: the reports record after filing")
    return res["code"]
