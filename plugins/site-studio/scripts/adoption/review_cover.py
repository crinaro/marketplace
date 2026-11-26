"""adoption.review_cover -- what step 3 of the one-process `apply` does when no review covers the build it is about to publish
(owner ruling 2026-11-18, "Yes, all three"; template-fidelity step F-1; site-studio 0.4.0).

Part of the `adoption` package behind the entry point `adopt.py`. `adoption.publish` asks `cover` after `deploy.py --dry-run` printed a
digest and said "no review covers this digest". A review is an agent's act, bound to the build's digest; the one-process `apply` builds
on a branch no checkout holds, so without this every real apply stopped at step 3 and "run adopt again" started over without the review.
THE RULING, built exactly:

1. CARRY. A review carries across the restart when the build digest is unchanged. A row for the SAME digest is looked for, read with
   `git show` (never the working files) and the strict reader of `reviews.rows`, in: every earlier adopt branch of this repo
   (`site-studio/adopt-*`, newest name first: where `/site-studio:review` records it, because the stop at step 3 tells the person to
   review a checkout of that branch), then the dev repo's `HEAD`, then `origin/main`. CHOSEN, and said in the apply output: the branch is
   where the review is made, and `HEAD` and `origin/main` are where a review the person already merged lives. A row for any other digest
   never carries. The rows found for the digest are written, unchanged, into the scratch clone's store in ONE commit (`carry`), so the
   carried review is on the adopt branch afterwards; `deploy.py --confirm` then finds it as it finds any review. A store a source holds
   that cannot be read is named and skipped (loud), never guessed at; a BLOCKED review that carries stops the run.
2. CONDITIONAL STAND-IN. When nothing carries, parity EQUAL stands in for the FIRST review, and only if ALL of `check_site`'s automated
   privacy scans pass on the EXACT built tree: the shape scan (phones, street addresses, emails), image metadata (EXIF and GPS) and
   unreferenced files. `check_site.py --json` is `check_site`'s own: this module builds the clone's tree with `build.py --digest`, requires
   the digest to equal the one the dry run printed (so the scans read the very tree that will be published), runs `check_site.py --out`
   on it, and keeps the findings of the `privacy` family and the `reachable` family's "published but not referenced" finding. Neither
   script is imported (an entry point is run, not imported: segmentation G5.L2), and none of the scans is written again here. A PDF the
   gate cannot read, a scan that examined no file, and an unreadable answer are each NOT CHECKED, never a pass. The stand-in is recorded
   in `.site-studio/reviews.jsonl` as a row whose `source` is `parity-EQUAL+scans` with the scans' summary (`reviews.rows` refuses any
   other shape), committed in the clone, and said in the apply output and HANDOFF.md: it is NEVER silent. A row that cannot be read back
   is an error, so a stand-in that is not recorded does not publish.
3. ACCEPTED ALWAYS NEEDS THE NORMAL REVIEW. Only parity EQUAL qualifies: ACCEPTED, MARKUP-ONLY, NOT APPLICABLE, no record and an
   unreadable record each stop with the reason (`CoverRefused`). The parity verdict is read from the record the conversion commit holds
   (`.site-studio/adopt-parity.json`, `adoption.parity.parse_parity_record`).

A PDF THE PERSON VOUCHED FOR (`adopt.py proof --as-is`, dev 1068 design 2.3) is a PDF the gate lists NOT READ on purpose: the commit says "the person vouched for the
resume PDF", this module reads that back from the clone's history, and the stop says so in place of "fix the PDF or remove it": the privacy review must open it. The
EQUAL stand-in never applies to it. A review is bound to the digest, which holds the conversion commit's date (the UTC day), so a review made on one day covers an
`apply` on that day only: every stop that needs a review says when the day ends (`utc_day_note`).

`deploy.py --dry-run` already refuses a build any check_site family finds fault with, so the scans here hold a second time, in this
module's own call, and what they found is what the row records. THE SEAM (tests only; no flag reaches it): `tool(script, argv, cwd) ->
(exit code, text)`; the default starts the script as a process, a test calls the script's `main` in this process.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from adoption.base import PARITY_RECORD_REL, PLUGIN, PlanError, git, gitt
from adoption.parity import parse_parity_record
from adoption.resumeproof import VOUCHED_LINE
from reviews import rows as review_rows

SCRIPTS = os.path.join(PLUGIN, "scripts")
TOOL_TIMEOUT = 900
ADOPT_BRANCHES = "refs/heads/site-studio/adopt-*"
UNREFERENCED = "published but not referenced by any page or stylesheet"       # check_site's own words for an unreferenced file
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_DIGEST_LINE = re.compile(r"^digest: ([0-9a-f]{64})$", re.M)


class CoverRefused(Exception):
    """No review covers the digest and none can be carried or stood in: `reason` is one line, `lines` what to print under it."""

    def __init__(self, reason, lines=(), blocked=False):
        Exception.__init__(self, reason)
        self.reason, self.lines, self.blocked = reason, list(lines), blocked


def run_tool(script, argv, cwd):
    """Run one of the plugin's scripts as a process: (exit code, its output)."""
    try:
        p = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, script)] + list(argv), cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "%s did not finish in %d minutes" % (script, TOOL_TIMEOUT // 60)
    except OSError as e:
        return 127, "%s could not start (%s)" % (script, e.__class__.__name__)
    return p.returncode, p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- 1. carry

def sources(repo):
    """`[(label, ref)]` the carry reads, in order: earlier adopt branches (newest name first), `HEAD`, `origin/main`."""
    names = [n for n in gitt(repo, "for-each-ref", "--format=%(refname)", ADOPT_BRANCHES, check=False).split("\n") if n]
    found = [(n[len("refs/heads/"):], n) for n in sorted(names, reverse=True)]
    return found + [("HEAD", "HEAD"), ("origin/main", "refs/remotes/origin/main")]


def carried(repo, digest):
    """`([(label, row)], notes)`: every row for `digest` in the stores `sources` names, each store read strictly, once per distinct
    row. A source with no store holds no rows; one whose store cannot be read is named in `notes` and skipped."""
    found, seen, notes, looked = [], set(), [], []
    for label, ref in sources(repo):
        text = gitt(repo, "show", "%s:%s" % (ref, review_rows.STORE_REL), check=False)
        if not text:
            continue
        looked.append(label)
        try:
            rows = review_rows.parse_text(text)
        except review_rows.RowError as e:
            notes.append("step 3: NOT CARRIED from %s: %s" % (label, e))
            continue
        for row in rows:
            key = json.dumps(row, sort_keys=True)
            if row["digest"] == digest and key not in seen:
                seen.add(key)
                found.append((label, row))
    notes.append("step 3: looked for a review of this digest in %s; found %d row(s)" % (", ".join(looked) or "no review store anywhere", len(found)))
    return found, notes


def read_store(clone):
    """The clone's rows, strictly. A store that cannot be read raises `CoverRefused`."""
    path = os.path.join(clone, *review_rows.STORE_REL.split("/"))
    if not os.path.exists(path):
        return []
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return review_rows.parse_text(raw.decode("utf-8", "replace"))
    except review_rows.RowError as e:
        raise CoverRefused("the clone's review record cannot be read: %s; restore .site-studio/reviews.jsonl from git history, then run adopt again" % e)


def append_rows(clone, new, message):
    """Append `new` rows to the clone's store and commit them (one commit). Each row is checked by the reader first, and the commit
    is read back: nothing this module's reader cannot read is written, and a row that is not there afterwards is an error."""
    for row in new:
        review_rows.validate_row(row, 0)
    old = read_store(clone)
    path = os.path.join(clone, *review_rows.STORE_REL.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    before = b""
    if os.path.exists(path):
        with open(path, "rb") as fh:
            before = fh.read()
    with open(path, "ab") as fh:
        if before and not before.endswith(b"\n"):
            fh.write(b"\n")
        for row in new:
            fh.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    git(clone, "add", "--", review_rows.STORE_REL)
    git(clone, "commit", "-q", "-m", message, "--", review_rows.STORE_REL)
    try:                                         # read back what the COMMIT holds, not the working file the rows were just written to
        now = review_rows.parse_text(gitt(clone, "show", "HEAD:" + review_rows.STORE_REL, check=False))
    except review_rows.RowError:
        now = None
    if now is None or now[:len(old)] != old or now[len(old):] != list(new):
        raise CoverRefused("the review record was written but does not read back as written; nothing was published; this is a site-studio defect: run `adopt.py report`")


def carry(clone, repo, digest):
    """Step 1. Writes the carried rows into the clone. Returns (where the deciding row came from, the digest's status in the clone's
    store afterwards, notes); the label is None when no row exists for the digest."""
    found, notes = carried(repo, digest)
    have = set(json.dumps(r, sort_keys=True) for r in read_store(clone))
    fresh = [(lab, r) for lab, r in found if json.dumps(r, sort_keys=True) not in have]
    if fresh:
        append_rows(clone, [r for _l, r in fresh],
                    "site-studio: carry the privacy review for %s into this adopt run (from %s)"
                    % (digest[:12], ", ".join(sorted(set(lab for lab, _r in fresh)))))
    label_of = dict((json.dumps(r, sort_keys=True), lab) for lab, r in found)
    status, row = review_rows.verdict_of(read_store(clone), digest)
    if status == "none":
        return None, status, notes
    return label_of.get(json.dumps(row, sort_keys=True), "the clone"), status, notes


# ---------------------------------------------------------------- 2. the stand-in

def parity_verdict(clone):
    """The verdict of the parity record the conversion commit holds, or None when there is no record."""
    path = os.path.join(clone, *PARITY_RECORD_REL.split("/"))
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        return parse_parity_record(text)["verdict"]
    except PlanError as e:
        raise CoverRefused("the parity record cannot be read, so nothing stands in for the review: %s; run `adopt.py parity` again" % e)


def scan_records(text):
    """The JSON records of `check_site.py --json`. An answer that is not that is NOT CHECKED (`CoverRefused`)."""
    records = []
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise CoverRefused("NOT CHECKED: check_site.py's answer could not be read as its JSON records (%s); this is a site-studio defect: run `adopt.py report`" % line[:80])
        if not isinstance(obj, dict):
            raise CoverRefused("NOT CHECKED: check_site.py's answer holds a record that is not an object; this is a site-studio defect: run `adopt.py report`")
        records.append(obj)
    summary = [r for r in records if r.get("level") == "summary"]
    if len(summary) != 1 or not isinstance(summary[0].get("checked"), dict):
        raise CoverRefused("NOT CHECKED: check_site.py printed no summary of what it scanned; this is a site-studio defect: run `adopt.py report`")
    return records, summary[0]


def standin_findings(records):
    """The findings that are the stand-in's scans: the `privacy` family (shapes, hidden image metadata, private terms, PDF metadata)
    and the `reachable` family's unreferenced file. A finding of any other family is the publish gate's, not the stand-in's."""
    return [r for r in records if r.get("level") == "error" and (
        r.get("family") == "privacy" or (r.get("family") == "reachable" and r.get("message") == UNREFERENCED))]


def vouched_in(clone):
    """True when a commit of the clone's recent history says the person vouched for the resume PDF (what `apply` writes for `proof --as-is`)."""
    return VOUCHED_LINE in gitt(clone, "log", "--format=%B", "-n", "20", check=False)


def utc_day_note(epoch=None):
    """The sentence a stop that needs a review ends with: the review is bound to the UTC day of the conversion commit, so `apply` must run again before the day
    ends (the clock time is the person's own), or the review has to be made again."""
    now = time.time() if epoch is None else epoch
    midnight = (int(now) // 86400 + 1) * 86400
    return ("run `adopt.py apply` again before 00:00 UTC (%s here), or the review has to be made again"
            % time.strftime("%H:%M", time.localtime(midnight)))


def _image_count(out_dir):
    return sum(1 for _d, _n, names in os.walk(out_dir) for n in names if n.lower().endswith(IMAGE_EXTS))


def scan_built_tree(clone, digest, tool, work):
    """Build the clone's tree, prove it is the tree the dry run printed, and scan it. Returns the scans' summary dict (the `scans` of
    a stand-in row without its `parity`); raises `CoverRefused` naming each finding, or why it could not look."""
    out_dir = os.path.join(work, "built")
    rc, text = tool("build.py", ["--repo", clone, "--out", out_dir, "--digest"], clone)
    found = _DIGEST_LINE.search(text)
    if rc != 0 or not found:
        raise CoverRefused("NOT CHECKED: the build the scans read did not finish (%s); fix what the build names, then run adopt again" % ((text.strip().split("\n") or [""])[-1][:160]))
    if found.group(1) != digest:
        raise CoverRefused("NOT CHECKED: the tree the scans read (digest %s) is not the tree the dry run printed (%s), so they did not "
                           "look at what would be published; leave the repo alone while adopt runs, then run adopt again" % (found.group(1)[:12], digest[:12]))
    rc, text = tool("check_site.py", ["--repo", clone, "--out", out_dir, "--json"], clone)
    records, summary = scan_records(text)
    hits = standin_findings(records)
    if hits:
        shown = "; ".join("%s %s: %s" % (h.get("family"), h.get("path"), h.get("message")) for h in hits[:3])
        raise CoverRefused("%d automated privacy scan finding(s) on the exact built tree: %s%s" % (
            len(hits), shown, "" if len(hits) <= 3 else "; and %d more" % (len(hits) - 3)),
            ["  run /site-studio:review: an agent opens each file and decides what to do about each finding"])
    if summary.get("pdfsNotRead") and vouched_in(clone):
        raise CoverRefused("NOT CHECKED: %d PDF(s) in the built tree could not be read by the privacy scan: you vouched for this PDF; the privacy review must open it"
                           % summary["pdfsNotRead"], ["  run /site-studio:review: an agent opens the PDF and decides what to do about it"])
    if summary.get("pdfsNotRead"):
        raise CoverRefused("NOT CHECKED: %d PDF(s) in the built tree could not be read by the privacy scan; fix the PDF or remove it, then run adopt again" % summary["pdfsNotRead"])
    checked = summary["checked"]
    if not checked.get("privacy") or not checked.get("reachable"):
        raise CoverRefused("NOT CHECKED: the scans examined nothing (privacy %s, reachable %s); this is a site-studio defect: run `adopt.py report`" % (checked.get("privacy", 0), checked.get("reachable", 0)))
    return {"files": checked["privacy"], "images": _image_count(out_dir), "pdfsRead": int(summary.get("pdfsRead") or 0), "findings": 0}


def standin(clone, digest, tool, now=None):
    """Step 2. Records the stand-in row in the clone and returns it; raises `CoverRefused` when parity is not EQUAL or a scan stops it."""
    verdict = parity_verdict(clone)
    if verdict != "EQUAL":
        raise CoverRefused("%s: only parity EQUAL stands in for a privacy review (ACCEPTED and MARKUP-ONLY need the normal one)"
                           % ("parity is %s" % verdict if verdict else "this tree has no parity record"))
    work = tempfile.mkdtemp(prefix="adopt-scan-")
    try:
        scans = dict(scan_built_tree(clone, digest, tool, work), parity="EQUAL")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    row = {"v": 1, "digest": digest, "baseline": {"kind": "none", "tree": None}, "verdict": "clear", "opened": [], "findings": [],
           "accepted": [], "at": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": review_rows.SOURCE_STANDIN, "scans": scans}
    append_rows(clone, [row], "site-studio: privacy review stand-in (%s) for %s" % (review_rows.SOURCE_STANDIN, digest[:12]))
    return row


# ---------------------------------------------------------------- the one call `publish` makes

def cover(clone, repo, digest, tool=None, now=None):
    """What covers `digest` now. Returns {"kind": "carried" | "standin", "note": the sentence the run prints and HANDOFF.md keeps,
    "lines": [...]} or raises `CoverRefused`. A carried review that is BLOCKED refuses; nothing stands in over a block."""
    tool = tool or run_tool
    label, status, lines = carry(clone, repo, digest)
    if status == "blocked":
        raise CoverRefused("the privacy review recorded for this digest (%s) is BLOCKED, and a stand-in never replaces a block; fix what it blocked on, then "
                           "run /site-studio:review on this branch" % label,
                           lines, blocked=True)
    if label is not None:
        note = "the privacy review for digest %s was carried from %s (it was made for this exact build); nothing new was reviewed" % (digest[:12], label)
        return {"kind": "carried", "note": note, "lines": lines + ["step 3: " + note]}
    try:
        row = standin(clone, digest, tool, now)
    except CoverRefused as e:
        raise CoverRefused(e.reason, lines + e.lines + ["  " + utc_day_note()])
    s = row["scans"]
    note = ("NO AGENT REVIEW covers digest %s: a stand-in (%s) was recorded in %s. Parity is EQUAL and every automated privacy scan "
            "passed on the exact built tree (%d files scanned, %d images, %d PDFs read); an agent has not opened a file. Run "
            "/site-studio:review when you want one" % (digest[:12], review_rows.SOURCE_STANDIN, review_rows.STORE_REL,
                                                       s["files"], s["images"], s["pdfsRead"]))
    return {"kind": "standin", "note": note, "lines": lines + ["step 3: " + note]}
