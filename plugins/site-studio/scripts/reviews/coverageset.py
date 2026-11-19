"""reviews.coverageset -- THE COVERAGE SET (named change M4) and THE BASELINE (the live site's git blob ids, read through `gh`).

The set is the COMPLEMENT of an allow-list: every built file that is new or changed against the baseline and is not a pure-text
type the pattern families scan completely (`.css`, `.txt`, `.xml`, `CNAME`, `.nojekyll`). `fetch_baseline` never raises: any
failure is `"none"` with the reason, and a truncated tree is never treated as complete.
"""
import hashlib
import json
import os
import shutil
import subprocess


# Pure-text types the pattern families scan completely: the ONLY kinds that may be left out of
# the coverage set. Everything else, including every unknown type, is in it.
TEXT_EXTS = (".css", ".txt", ".xml")
TEXT_NAMES = ("CNAME", ".nojekyll")


def blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_type(path):
    base = path.rsplit("/", 1)[-1]
    if base in TEXT_NAMES:
        return base
    ext = os.path.splitext(base)[1].lower()
    return ext or "(no extension)"


def on_text_allowlist(path):
    base = path.rsplit("/", 1)[-1]
    return base in TEXT_NAMES or os.path.splitext(base)[1].lower() in TEXT_EXTS


def coverage_set(files, baseline_blobs):
    """`files`: {built path: bytes}. `baseline_blobs`: {path: git blob id} of the live site, or
    None for "no baseline". Returns (sorted list of paths in the set, {type: count})."""
    cov = []
    for path in sorted(files):
        if on_text_allowlist(path):
            continue
        if baseline_blobs is not None and baseline_blobs.get(path) == blob_id(files[path]):
            continue                      # unchanged against the live site
        cov.append(path)
    counts = {}
    for p in cov:
        t = file_type(p)
        counts[t] = counts.get(t, 0) + 1
    return cov, counts


def fetch_baseline(public_repo, gh="gh", timeout=60):
    """The live site's tree. Returns {"kind": "live"|"none", "tree": sha|None, "blobs":
    {path: blob id}, "reason": str}. NEVER raises: any failure is "none" with the reason."""
    none = {"kind": "none", "tree": None, "blobs": {}}
    if not public_repo:
        return dict(none, reason="site.json has no publicRepo")
    exe = shutil.which(gh) if os.sep not in gh else gh
    if not exe:
        return dict(none, reason="gh is not installed")
    try:
        p = subprocess.run([exe, "api", "repos/%s/git/trees/main?recursive=1" % public_repo],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                           env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(none, reason="the public repo could not be read (%s)" % type(e).__name__)
    if p.returncode != 0:
        return dict(none, reason="the public repo could not be read (gh exit %d)" % p.returncode)
    try:
        data = json.loads(p.stdout.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
            raise ValueError("no tree")
        if data.get("truncated") is not False:
            return dict(none, reason="the public tree is too large to list in one call "
                                     "(truncated), so it cannot serve as a baseline")
        blobs = {}
        for e in data["tree"]:
            if e.get("type") == "blob":
                blobs[str(e["path"])] = str(e["sha"])
    except (ValueError, KeyError, TypeError):
        return dict(none, reason="the public tree answer could not be read")
    return {"kind": "live", "tree": data.get("sha"), "blobs": blobs, "reason": ""}
