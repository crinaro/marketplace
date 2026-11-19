"""reviews.addrow -- `review_record.py add`: append one verdict row and commit it (named change M12(a)).

`add` has NO `--digest` argument: it rebuilds, recomputes the digest and refuses unless it equals the packet's, so a verdict is
bound to a build this module computed. It recomputes the coverage set from the packet's stored baseline, requires every file of it
to be listed as opened for a clear or accepted verdict, and commits ONE path (`git add --` then `git commit --`). It never pushes.
"""
import json
import os
import re
import shutil
import tempfile
import time
from building import outcomes, running
from reviews.rows import VERDICTS, STORE_REL
from reviews.basics import ReviewError, git
from reviews.coverageset import coverage_set
from reviews.packet import _load_packet, _read_built
from reviews.store import load_rows


_FINDING_ID = re.compile(r"^F[0-9]+$")


def _clean_paths(items):
    out = []
    for it in items:
        it = it.strip()
        while it.startswith("./"):
            it = it[2:]
        if it:
            out.append(it)
    return sorted(set(out))


def _load_findings(path):
    if path is None:
        return []
    try:
        with open(path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        raise ReviewError("the findings file %s cannot be read as JSON" % path)
    if not isinstance(data, list):
        raise ReviewError("the findings file must hold a JSON list of {id, path, summary}")
    seen = set()
    for f in data:
        if (not isinstance(f, dict) or set(f) != {"id", "path", "summary"}
                or not all(isinstance(f[k], str) for k in f)):
            raise ReviewError("each finding needs exactly id, path and summary (strings)")
        if not _FINDING_ID.match(f["id"]) or f["id"] in seen:
            raise ReviewError("finding ids must be unique and look like F1, F2, ...")
        seen.add(f["id"])
    return data


def add(repo, packet_path, verdict, opened, accept=(), findings_path=None, now=None):
    """Append one verdict row and commit it. There is no digest argument. Returns the row."""
    repo = os.path.abspath(repo)
    if verdict not in VERDICTS:
        raise ReviewError("--verdict must be clear, accepted or blocked")
    packet = _load_packet(packet_path)
    findings = _load_findings(findings_path)
    ids = [f["id"] for f in findings]
    accept = sorted(set(a.strip() for a in accept if a.strip()))

    tmp = tempfile.mkdtemp(prefix="ss-review-")
    try:
        out_dir = os.path.join(tmp, "out")
        try:
            res = running.publish_build(repo, out_dir)
        except outcomes.BuildError as e:
            raise ReviewError("build refused: %s" % e)
        # 1. the digest, recomputed by this script
        if res.digest != packet["digest"]:
            raise ReviewError("the site changed since the review began; run the review again "
                              "(packet digest %s, build now %s)" % (packet["digest"][:12], res.digest[:12]))
        files = _read_built(out_dir, res.files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The coverage set is recomputed from the packet's stored baseline, never trusted as written.
    blobs = packet["baseline_blobs"] if packet["baseline"].get("kind") == "live" else None
    cov, _counts = coverage_set(files, blobs)
    if cov != packet["coverage"]:
        raise ReviewError("the packet's coverage set does not match the build; run begin again")
    required = set(cov)
    if packet["not_read_pdfs"]:
        required |= set(packet["not_read_pdfs"])
    opened_set = set(_clean_paths(opened))

    if verdict in ("clear", "accepted"):
        missing = sorted(required - opened_set)
        if missing:
            raise ReviewError("%d file(s) of the coverage set were not opened, so %s is refused: %s; open each of them in the review, then record it again"
                              % (len(missing), verdict, ", ".join(missing)))
    if verdict == "clear" and findings:
        raise ReviewError("'clear' carries no findings; use accepted (naming each) or blocked")
    if verdict in ("accepted", "blocked") and not findings:
        raise ReviewError("%s needs the review's findings (--findings FILE)" % verdict)
    if verdict == "accepted" and accept != sorted(ids):
        raise ReviewError("accepted needs --accept to name every finding id of this review (%s)"
                          % ", ".join(ids))
    if verdict != "accepted" and accept:
        raise ReviewError("--accept applies only to an accepted verdict")

    row = {
        "v": 1, "digest": packet["digest"],
        "baseline": {"kind": packet["baseline"].get("kind"), "tree": packet["baseline"].get("tree")},
        "verdict": verdict, "opened": sorted(opened_set), "findings": findings,
        "accepted": accept if verdict == "accepted" else [],
        "at": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_and_commit(repo, row)
    return row


def _append_and_commit(repo, row):
    """Append the row, `git add` the (possibly untracked) file, then `git commit -- <path>`."""
    load_rows(repo)                           # a corrupt store refuses before anything is written
    path = os.path.join(repo, STORE_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    before = None
    if os.path.exists(path):
        with open(path, "rb") as fh:
            before = fh.read()
    line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, "ab") as fh:
        if before and not before.endswith(b"\n"):
            fh.write(b"\n")
        fh.write(line.encode("utf-8"))
    try:
        git(repo, "add", "--", STORE_REL)
        git(repo, "commit", "-q", "-m", "site-studio: privacy review %s for %s"
            % (row["verdict"], row["digest"][:12]), "--", STORE_REL)
    except ReviewError as e:
        # Put the store back as it was, so a failed commit leaves no unrecorded row behind.
        if before is None:
            git(repo, "rm", "-q", "--cached", "--ignore-unmatch", "--", STORE_REL, check=False)
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            with open(path, "wb") as fh:
                fh.write(before)
            git(repo, "add", "--", STORE_REL, check=False)
        raise ReviewError("the review row was not recorded: %s" % e)
