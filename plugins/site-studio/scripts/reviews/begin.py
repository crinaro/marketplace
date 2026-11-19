"""reviews.begin -- `review_record.py begin`: run the publish build into `.site-studio/review/build/`, compute the digest ITSELF, the
baseline and the coverage set, and write the packet. The privacy pattern gate's list of PDFs it could not read comes from
`sitechecks.checker.not_read_pdfs`; when that gate is not present the packet says NOT CHECKED rather than an empty list.
"""
import json
import os
import shutil
from building import outcomes, running
from configschema import diagnostics, model
from reviews.basics import ReviewError, git
from reviews.coverageset import coverage_set, fetch_baseline
from reviews.packet import BUILD_REL, IGNORE_LINE, PACKET_REL, PACKET_VERSION, _read_built
from sitechecks import checker


def _ensure_ignored(repo):
    """Keep `.site-studio/review/` out of `git status` through the repo-local exclude file, so
    a repo whose `.gitignore` predates this plugin still stays clean."""
    try:
        rel = git(repo, "rev-parse", "--git-path", "info/exclude").strip()
        path = rel if os.path.isabs(rel) else os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cur = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                cur = fh.read()
        if IGNORE_LINE not in cur.split("\n"):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(("" if cur.endswith("\n") or not cur else "\n") + IGNORE_LINE + "\n")
    except (ReviewError, OSError):
        pass                      # an ignore line is a convenience; the build never reads this dir


def default_not_read(out_dir, repo=None):
    """PDFs the pattern gate could not read (design 7.1), or None when the gate is not present
    in this tree. `sitechecks.checker.not_read_pdfs(out_dir, repo)` is the seam phase 1b fills; until it
    exists the packet records NOT CHECKED rather than an empty list that reads as 'none'. (S1b: it was
    looked up on `check_site`, which after the split is only the entry point, so the list was silently lost.)"""
    fn = getattr(checker, "not_read_pdfs", None)
    if fn is None:
        return None
    return sorted(fn(out_dir, repo))


def begin(repo, baseline_fn=None, not_read_fn=None):
    """Build, compute the digest, the baseline and the coverage set; write the packet.
    Returns the packet dict."""
    repo = os.path.abspath(repo)
    try:
        cfg = model.load(os.path.join(repo, "site", "site.json"))
    except (diagnostics.SiteConfigError, OSError) as e:
        raise ReviewError(str(e))
    out_dir = os.path.join(repo, BUILD_REL)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    _ensure_ignored(repo)
    try:
        res = running.publish_build(repo, out_dir)
    except outcomes.BuildError as e:
        raise ReviewError("build refused: %s" % e)
    files = _read_built(out_dir, res.files)
    base = (baseline_fn or fetch_baseline)(cfg.publicRepo)
    blobs = base["blobs"] if base["kind"] == "live" else None
    cov, counts = coverage_set(files, blobs)
    nr = not_read_fn(out_dir) if not_read_fn is not None else default_not_read(out_dir, repo)
    if nr is None:
        note = "NOT CHECKED: the privacy pattern gate (check_site.py) is not present, so PDFs it cannot read are unknown"
        nr_list = None
    else:
        note = ""
        nr_list = sorted(nr)
    packet = {
        "v": PACKET_VERSION, "digest": res.digest, "siteKind": res.site_kind,
        "baseline": {"kind": base["kind"], "tree": base.get("tree"), "reason": base.get("reason", "")},
        "baseline_blobs": ({p: blobs[p] for p in sorted(files) if p in blobs} if blobs is not None else {}),
        "coverage": cov, "types": counts, "files": len(files),
        "not_read_pdfs": nr_list, "not_read_note": note,
    }
    ppath = os.path.join(repo, PACKET_REL)
    with open(ppath, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    return packet
