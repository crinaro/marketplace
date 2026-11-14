#!/usr/bin/env python3
"""review_record.py -- the privacy-review record the publish script binds (dev #835, design 7.2,
named changes M2, M4, M12(a)). Python 3.9, standard library only.

    review_record.py begin   [--repo R]
    review_record.py add     --packet P --verdict clear|accepted|blocked --opened PATH [--opened ...]
                             [--findings FILE] [--accept F1,F3] [--repo R]
    review_record.py verdict DIGEST [--repo R]

WHAT IT GUARANTEES (and what it does not)
-----------------------------------------
`begin` runs `build.publish_build` into `.site-studio/review/build/` (an ignored folder), computes
the digest ITSELF, then the COVERAGE SET, and writes `.site-studio/review/packet.json`. `add` has
NO `--digest` argument: it rebuilds, recomputes the digest, and refuses unless it equals the
packet's. So a verdict is bound to a build this script computed, and any later byte change voids
it. A `blocked` row for a digest wins over any `clear`. Whether the reviewing agent REALLY looked
at each file it lists as opened, whether its judgement is right, and which PAGES it actually read
are model judgement and are NOT measured; the control is the person at the publish prompt
(design 7.4). The packet and the store sit in the person's own repo with no signature: this
record protects against drift and accident, not against a model set on forging it.

THE COVERAGE SET (named change M4) is the COMPLEMENT of an allow-list, not a list of kinds
-----------------------------------------------------------------------------------------
Every built file that is NEW or CHANGED against the baseline AND is not on the short list of
pure-text types the pattern families already scan completely (`.css`, `.txt`, `.xml`, plus the
files named `CNAME` and `.nojekyll`). HTML pages ARE in the set (page text is the main judgement
surface), and so is every type this file has never heard of: `.svg` (carries text), video, audio,
fonts, `.zip`, `.docx`, `.js`, `.json`. The count per type is printed. The first version of this
rule named only images, PDFs and capture cards; an SVG or a changed page then needed no listing.
PDFs the pattern gate could not read (NOT READ, design 7.1) are added to the set explicitly.

THE BASELINE is the live site: `gh api repos/<publicRepo>/git/trees/main?recursive=1`, git blob
ids, compared with each built file's blob id (SHA-1 of `blob <n>\\0<bytes>`, the same value
`git hash-object` prints, computed here without a process). A tree the API marks
`truncated: true`, a failed read, no `gh`, no public repo, or a repo with no `main` yet is "no
baseline": then EVERY file not on the allow-list is in the set, and the output says which baseline
was used. A truncated baseline is never treated as complete.

THE STORE (`.site-studio/reviews.jsonl`) is read strictly (CLAUDE.md principle 4): an unparseable
line, an unknown `v`, a missing or unknown field refuses LOUDLY with the line number. Never
skipped. A row is stale by digest, never by age.

`add` appends then commits ONE path, in this order (named change M12(a)): `git add --
.site-studio/reviews.jsonl`, then `git commit -- .site-studio/reviews.jsonl`. For the first review
the file is untracked, and `git commit -- <untracked path>` alone fails; the explicit add comes
first. The commit takes only that path, so anything else the person has staged stays staged. It
never pushes. `.site-studio/review/` is kept out of the tree with an ignore line.

Shared with `deploy.py` and `publish_guard.py`: `verdict_for`, `load_rows`, `git`, the path
constants below, and `read_dryrun`.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STORE_REL = ".site-studio/reviews.jsonl"
REVIEW_DIR_REL = ".site-studio/review"
BUILD_REL = ".site-studio/review/build"
PACKET_REL = ".site-studio/review/packet.json"
DRYRUN_REL = ".site-studio/review/dryrun.json"
IGNORE_LINE = ".site-studio/review/"

VERDICTS = ("clear", "accepted", "blocked")
ROW_KEYS = ("v", "digest", "baseline", "verdict", "opened", "findings", "accepted", "at")
PACKET_KEYS = ("v", "digest", "baseline", "baseline_blobs", "coverage", "types", "files",
               "not_read_pdfs", "not_read_note")

# Pure-text types the pattern families scan completely: the ONLY kinds that may be left out of
# the coverage set. Everything else, including every unknown type, is in it.
TEXT_EXTS = (".css", ".txt", ".xml")
TEXT_NAMES = ("CNAME", ".nojekyll")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FINDING_ID = re.compile(r"^F[0-9]+$")


_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import platform_check  # noqa: E402


class ReviewError(ValueError):
    """A refusal. The message is one line the person can act on."""


# ---------------------------------------------------------------- git

_REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE")


def git(repo, *args, **kw):
    """Run git in `repo`; return stdout text. Raises ReviewError (one line) on failure."""
    inp = kw.pop("input", None)
    timeout = kw.pop("timeout", 120)
    check = kw.pop("check", True)
    env = {k: v for k, v in os.environ.items() if k not in _REDIRECTING}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = subprocess.run(("git", "-C", repo) + tuple(args), input=inp, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise ReviewError("git %s timed out after %ds" % (args[0], timeout))
    except OSError as e:
        raise ReviewError("could not run git (%s)" % e)
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ReviewError("git %s failed: %s" % (args[0], msg[-1] if msg else "exit %d" % p.returncode))
    out = p.stdout
    return out if kw.get("raw") else out.decode("utf-8", "replace")


def blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ---------------------------------------------------------------- the coverage set

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


# ---------------------------------------------------------------- the store, read strictly

def _validate_row(row, n):
    where = "%s line %d" % (STORE_REL, n)
    if not isinstance(row, dict):
        raise ReviewError("%s: a row must be an object" % where)
    if row.get("v") != 1 or isinstance(row.get("v"), bool):
        raise ReviewError("%s: unknown row version %r (this plugin reads v 1)" % (where, row.get("v")))
    for k in ROW_KEYS:
        if k not in row:
            raise ReviewError("%s: missing field '%s'" % (where, k))
    for k in row:
        if k not in ROW_KEYS:
            raise ReviewError("%s: unknown field '%s'" % (where, k))
    if not isinstance(row["digest"], str) or not _HEX64.match(row["digest"]):
        raise ReviewError("%s: 'digest' must be 64 lower-case hex characters" % where)
    if row["verdict"] not in VERDICTS:
        raise ReviewError("%s: 'verdict' must be clear, accepted or blocked" % where)
    if not isinstance(row["baseline"], dict) or "kind" not in row["baseline"]:
        raise ReviewError("%s: 'baseline' must be an object with a 'kind'" % where)
    for k in ("opened", "accepted"):
        if not isinstance(row[k], list) or not all(isinstance(x, str) for x in row[k]):
            raise ReviewError("%s: '%s' must be a list of strings" % (where, k))
    if not isinstance(row["findings"], list):
        raise ReviewError("%s: 'findings' must be a list" % where)
    for f in row["findings"]:
        if (not isinstance(f, dict) or set(f) != {"id", "path", "summary"}
                or not all(isinstance(f[k], str) for k in f)):
            raise ReviewError("%s: each finding needs exactly id, path and summary (strings)" % where)
    if not isinstance(row["at"], str):
        raise ReviewError("%s: 'at' must be a string" % where)
    return row


def load_rows(repo):
    """Every row of the store, strictly. No store file is no rows. Raises ReviewError with the
    line number on anything it cannot read; a bad line is never skipped."""
    path = os.path.join(repo, STORE_REL)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise ReviewError("%s cannot be read (%s)" % (STORE_REL, e.strerror))
    rows = []
    for n, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise ReviewError("%s line %d is not valid JSON; fix or remove that line" % (STORE_REL, n))
        rows.append(_validate_row(obj, n))
    return rows


def verdict_for(digest, repo="."):
    """(status, row) for `digest`: status is "none", "clear", "accepted" or "blocked".

    A `blocked` row wins over any `clear`, before or after it. The only way past one is a LATER
    `accepted` row whose `accepted` list covers every finding id of every `blocked` row for the
    digest so far. A new `blocked` row after that re-blocks."""
    blocked = False
    blocked_ids = set()
    best = None
    for row in load_rows(repo):
        if row["digest"] != digest:
            continue
        v = row["verdict"]
        if v == "blocked":
            blocked = True
            blocked_ids |= set(f["id"] for f in row["findings"])
            best = row
        elif v == "accepted":
            if blocked:
                if set(row["accepted"]) >= blocked_ids:
                    blocked = False
                    best = row
            else:
                best = row
        else:                                   # clear
            if not blocked:
                best = row
    if best is None:
        return "none", None
    return ("blocked" if blocked else best["verdict"]), best


def read_dryrun(repo):
    """The dry-run record `deploy.py --dry-run` writes. None when absent. Strict on shape."""
    path = os.path.join(repo, DRYRUN_REL)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        obj = json.loads(fh.read().decode("utf-8"))
    if (not isinstance(obj, dict) or obj.get("v") != 1 or not isinstance(obj.get("files"), int)
            or not isinstance(obj.get("digest"), str) or not _HEX64.match(obj["digest"])):
        raise ReviewError("%s is not a dry-run record this plugin wrote" % DRYRUN_REL)
    return obj


# ---------------------------------------------------------------- begin

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


def _read_built(out_dir, rels):
    out = {}
    for rel in rels:
        with open(os.path.join(out_dir, rel), "rb") as fh:
            out[rel] = fh.read()
    return out


def default_not_read(out_dir, repo=None):
    """PDFs the pattern gate could not read (design 7.1), or None when the gate is not present
    in this tree. `check_site.not_read_pdfs(out_dir)` is the seam phase 1b fills; until it
    exists the packet records NOT CHECKED rather than an empty list that reads as 'none'."""
    try:
        import check_site
        fn = getattr(check_site, "not_read_pdfs", None)
    except ImportError:
        fn = None
    if fn is None:
        return None
    return sorted(fn(out_dir, repo))


def begin(repo, baseline_fn=None, not_read_fn=None):
    """Build, compute the digest, the baseline and the coverage set; write the packet.
    Returns the packet dict."""
    import build
    import siteconfig
    repo = os.path.abspath(repo)
    try:
        cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    except (siteconfig.SiteConfigError, OSError) as e:
        raise ReviewError(str(e))
    out_dir = os.path.join(repo, BUILD_REL)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    _ensure_ignored(repo)
    try:
        res = build.publish_build(repo, out_dir)
    except build.BuildError as e:
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
        "v": 1, "digest": res.digest,
        "baseline": {"kind": base["kind"], "tree": base.get("tree"), "reason": base.get("reason", "")},
        "baseline_blobs": ({p: blobs[p] for p in sorted(files) if p in blobs} if blobs is not None else {}),
        "coverage": cov, "types": counts, "files": len(files),
        "not_read_pdfs": nr_list, "not_read_note": note,
    }
    ppath = os.path.join(repo, PACKET_REL)
    with open(ppath, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    return packet


def format_begin(packet, repo):
    lines = []
    b = packet["baseline"]
    if b["kind"] == "live":
        lines.append("baseline: the live site (public tree %s)" % (b["tree"] or "?")[:12])
    else:
        lines.append("baseline: NONE (%s); every file that is not plain text is in the set" % b["reason"])
    lines.append("built %d files; digest %s" % (packet["files"], packet["digest"]))
    lines.append("coverage set: %d file(s) to open" % len(packet["coverage"]))
    for t in sorted(packet["types"]):
        lines.append("  %s: %d" % (t, packet["types"][t]))
    nr = packet["not_read_pdfs"]
    if nr is None:
        lines.append(packet["not_read_note"])
    else:
        lines.append("PDFs NOT READ by the pattern gate: %d" % len(nr))
        for p in nr:
            lines.append("  " + p)
    lines.append("packet: %s" % os.path.join(repo, PACKET_REL))
    return "\n".join(lines)


# ---------------------------------------------------------------- add

def _load_packet(path):
    try:
        with open(path, "rb") as fh:
            p = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        raise ReviewError("the packet %s cannot be read; run begin again" % path)
    if not isinstance(p, dict) or p.get("v") != 1 or any(k not in p for k in PACKET_KEYS):
        raise ReviewError("the packet %s is not one this plugin wrote; run begin again" % path)
    if not isinstance(p["digest"], str) or not _HEX64.match(p["digest"]):
        raise ReviewError("the packet's digest is malformed; run begin again")
    return p


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
    import build
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
            res = build.publish_build(repo, out_dir)
        except build.BuildError as e:
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
            raise ReviewError("%d file(s) of the coverage set were not opened, so %s is refused: %s"
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


# ---------------------------------------------------------------- CLI

def main(argv=None):
    rc = platform_check.windows_refusal_rc("review_record.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="review_record.py", allow_abbrev=False,
                                 description="The privacy-review record (dev #835).")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    b = sub.add_parser("begin", allow_abbrev=False)
    b.add_argument("--repo", default=".")
    a = sub.add_parser("add", allow_abbrev=False)
    a.add_argument("--repo", default=".")
    a.add_argument("--packet", required=True)
    a.add_argument("--verdict", required=True, choices=VERDICTS)
    a.add_argument("--opened", action="append", default=[], metavar="PATH")
    a.add_argument("--findings", help="JSON list of {id, path, summary} the reviewer returned")
    a.add_argument("--accept", default="", help="comma-separated finding ids")
    v = sub.add_parser("verdict", allow_abbrev=False)
    v.add_argument("digest")
    v.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "begin":
            print(format_begin(begin(args.repo), os.path.abspath(args.repo)))
        elif args.cmd == "add":
            row = add(args.repo, args.packet, args.verdict, args.opened,
                      args.accept.split(","), args.findings)
            print("recorded %s for %s (%d files opened) and committed %s; nothing was pushed"
                  % (row["verdict"], row["digest"][:12], len(row["opened"]), STORE_REL))
        else:
            status, row = verdict_for(args.digest, args.repo)
            print("%s%s" % (status, "" if row is None else " (recorded %s)" % row["at"]))
            if status == "none":
                print("no review for this digest: run the review step")
        return 0
    except ReviewError as e:
        print("review refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
