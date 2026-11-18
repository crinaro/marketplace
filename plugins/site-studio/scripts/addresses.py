#!/usr/bin/env python3
"""addresses.py -- the published-address guard's record and rules (design-template-fidelity section 8 A1; step 1.6).
Python 3.9, standard library only. A MODULE, not a command: `deploy.py drop` and `move.py` are its two writers, and
`deploy.py` its one reader at publish. Nothing here starts a process except `require_clean`'s one `git status`.

WHAT AN ADDRESS IS. Every path the public repo's `main` serves today is an address a visitor, a bookmark or a search
engine may hold. A build that no longer has one of them silently ends it. The guard says so BEFORE anything is
staged:

    dropped(public, build, record)   every public path the new build lacks and the record does not release
    released(public, build, record)  the paths the record DOES release in this publish, with their reasons: what the
                                     dry run prints and the person's approval must name

An HTML page can be kept by a `redirects` entry (a refresh page is HTML, and the build writes it at the old path, so a
redirected path is already IN the build and the guard needs no knowledge of redirects). A file that is not a page (a
PDF, an image) cannot: its address is kept only by a file at that path (the same name, or a kept copy at
`site/src/<path>`) or released on purpose with `deploy.py drop`. The comparison is of RAW path sets, never through the
parity normaliser: a case-different name is a different address on Pages.

THE RECORD, `.site-studio/addresses.json` (design 3.5), committed, never published, never written by hand:

    {"schema": 1, "dropped": [{"path": "<output path>", "reason": "<text>"}],
     "moved": [{"from": "<portfolio>/<slug>", "to": "<portfolio>/<slug>"}]}

each list sorted and without duplicates, no dates, so two writes of one fact are byte-identical. `parse` is the strict
reader: an unknown key, a wrong type, an unsorted list, a duplicate, an absolute path, a `..` segment or a path the
publish refuses on principle (`private_path`) raises `AddressError` naming the file and the line to fix. Its mere
presence is a schema-4 reason (`siteconfig.ADDRESSES_RECORD`; section 3.1 rule 8): every 0.3.x install refuses a tree
that carries it instead of publishing it with no guard, and `site_json_text` writes `site.json` at the schema the tree
then needs, in the same change as the record.

BOTH WRITERS RUN THE RAISE-SCHEMA PRE-WRITE CHECK (R2-3), `check_prewrite`: a tree below schema 3, or one holding a
custom `:::part` whose name schema 4 fixes, is REFUSED naming `build.py raise-schema`, and nothing is written. One
door into schema 4 is the invariant; skipping the check would leave the older-install hole the guard reason closes.
A cloud session is not refused here (R2-6): these are content edits like add-work, and the publish refusal is the
control; the person's approval of the released list, at the publish ask, is the human checkpoint for every release.

THE SEQUENCE a person follows (R2-8): drop (or move) and COMMIT; push or merge that commit to `origin/main`; run the
dry run, which prints the released list; confirm. `drop` publishes nothing.
"""
import json
import os
import posixpath
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import content as C  # noqa: E402
import siteconfig  # noqa: E402

RECORD_REL = siteconfig.ADDRESSES_RECORD
RECORD_SCHEMA = 1
LIST_CAP = 12                     # paths a refusal or a dry run names before "and N more"
HTML_EXTS = (".html", ".htm")
# A path nothing may release or move: the segments `deploy.forbidden` keeps out of a publish, so a record can never
# name a private file as a "published address".
PRIVATE_SEGMENTS = (".site-studio", "decisions", ".claude", ".git", "originals")
CLEAN_PATHS = ("site", "content", ".site-studio")     # what must hold no uncommitted change before a writer runs


class AddressError(ValueError):
    """A refusal of the record, a path or a tree. The message is the line the person reads, and names the fix."""


def empty():
    return {"schema": RECORD_SCHEMA, "dropped": [], "moved": []}


def private_path(path):
    segs = [s.lower() for s in path.split("/")]
    return any(s in PRIVATE_SEGMENTS for s in segs) or segs[-1] in ("site.json", "handoff.md", "claude.md")


def check_path(path, where="the path"):
    """`path` as an output path of the site: relative, `/`-separated, no `..`, no empty segment, no control
    character, never a private file, never a folder (no trailing `/`). Raises `AddressError`."""
    if not isinstance(path, str) or not path:
        raise AddressError("%s must be a non-empty text, such as work/old/index.html or cv.pdf" % where)
    bad = (path.startswith("/") or path.endswith("/") or "\\" in path or "//" in path
           or any(ord(c) < 32 or ord(c) == 127 for c in path)
           or any(seg in ("", ".", "..") for seg in path.split("/")))
    if bad:
        raise AddressError("%s %r is not an output path; write it the way the live site serves it, with no leading "
                           "or trailing slash, no .. and no backslash (work/old/index.html, cv.pdf)"
                           % (where, path[:80]))
    if private_path(path):
        raise AddressError("%s %r is a private file, which is never published, so it has no address to release; "
                           "the path must be one the live site serves" % (where, path[:80]))
    return path


def is_html(path):
    return path.lower().endswith(HTML_EXTS)


def _piece_key(value, where):
    parts = value.split("/") if isinstance(value, str) else []
    if len(parts) != 2 or not all(C.SLUG_RE.match(p) for p in parts):
        raise AddressError("%s must be <portfolio>/<piece> in lower-case letters, digits and hyphens, not %r"
                           % (where, value if not isinstance(value, str) else value[:60]))
    return value


def parse(text, where=RECORD_REL):
    """The strict reader of `.site-studio/addresses.json`: returns the record. Anything it cannot read raises
    `AddressError`: a fact a run knows goes into a store with a parser that refuses what it cannot read."""
    try:
        d = json.loads(text)
    except ValueError as e:
        raise AddressError("%s is not valid JSON (%s); restore it from git, or delete it and run deploy.py drop "
                           "again" % (where, e))
    fix = "restore it from git, or write it only through deploy.py drop and move.py"
    if not isinstance(d, dict) or set(d) != {"schema", "dropped", "moved"}:
        raise AddressError("%s must hold exactly schema, dropped and moved; %s" % (where, fix))
    if d["schema"] != RECORD_SCHEMA or isinstance(d["schema"], bool):
        raise AddressError("%s: schema %r is not understood (this site-studio reads %d); update site-studio, or %s"
                           % (where, d["schema"], RECORD_SCHEMA, fix))
    if not isinstance(d["dropped"], list) or not isinstance(d["moved"], list):
        raise AddressError("%s: dropped and moved must be lists; %s" % (where, fix))
    dropped = []
    for i, item in enumerate(d["dropped"]):
        at = "%s: dropped[%d]" % (where, i)
        if not isinstance(item, dict) or set(item) != {"path", "reason"}:
            raise AddressError("%s must hold exactly path and reason; %s" % (at, fix))
        check_path(item["path"], at + " path")
        if not isinstance(item["reason"], str) or not item["reason"].strip() or "\n" in item["reason"]:
            raise AddressError("%s: reason must be one line of text saying why the address is released; %s"
                               % (at, fix))
        dropped.append((item["path"], item["reason"]))
    moved = []
    for i, item in enumerate(d["moved"]):
        at = "%s: moved[%d]" % (where, i)
        if not isinstance(item, dict) or set(item) != {"from", "to"}:
            raise AddressError("%s must hold exactly from and to; %s" % (at, fix))
        moved.append((_piece_key(item["from"], at + " from"), _piece_key(item["to"], at + " to")))
    for label, rows in (("dropped", dropped), ("moved", moved)):
        keys = [r[0] if label == "dropped" else r for r in rows]
        if keys != sorted(keys):
            raise AddressError("%s: %s is not sorted (it must be written in order); %s" % (where, label, fix))
        if len(set(keys)) != len(keys):
            raise AddressError("%s: %s names one entry twice (each must appear once); %s" % (where, label, fix))
    return {"schema": RECORD_SCHEMA,
            "dropped": [{"path": p, "reason": r} for p, r in dropped],
            "moved": [{"from": a, "to": b} for a, b in moved]}


def dump(record):
    """The one writer form: sorted lists, sorted keys, indent 2, one trailing LF, no date. `parse(dump(r)) == r` for
    any record `merge` builds; a malformed record raises here rather than reaching disk."""
    rows = {"schema": RECORD_SCHEMA,
            "dropped": sorted(({"path": d["path"], "reason": d["reason"]} for d in record["dropped"]),
                              key=lambda d: d["path"]),
            "moved": sorted(({"from": m["from"], "to": m["to"]} for m in record["moved"]),
                            key=lambda m: (m["from"], m["to"]))}
    text = json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    parse(text)
    return text


def merge(record, dropped=(), moved=()):
    """A new record: `record` plus the `(path, reason)` drops and the `(from, to)` moves. A path already released
    keeps its first reason (the record states a fact once); a move already recorded is not repeated."""
    out = {"schema": RECORD_SCHEMA, "dropped": [dict(d) for d in record["dropped"]],
           "moved": [dict(m) for m in record["moved"]]}
    have = set(d["path"] for d in out["dropped"])
    for path, reason in dropped:
        check_path(path, "the dropped path")
        if path not in have:
            have.add(path)
            out["dropped"].append({"path": path, "reason": reason})
    seen = set((m["from"], m["to"]) for m in out["moved"])
    for a, b in moved:
        if (a, b) not in seen:
            seen.add((a, b))
            out["moved"].append({"from": _piece_key(a, "the moved piece"), "to": _piece_key(b, "the moved piece")})
    return out


# ---------------------------------------------------------------- the guard

def dropped(public_paths, build_paths, record):
    """Every public path the build no longer has and the record does not release, sorted. Raw sets: no
    normalisation, no `PARITY_IGNORED`."""
    have = set(build_paths)
    released = set(d["path"] for d in record["dropped"])
    return sorted(p for p in set(public_paths) if p not in have and p not in released)


def released(public_paths, build_paths, record):
    """`[[path, reason]]`, sorted by path: the addresses this publish ends ON PURPOSE, each public today, absent
    from the build, and in the record (a moved piece's non-page files included). A record entry for a path that is
    not public, or that the build still has, releases nothing and is not listed."""
    have, public = set(build_paths), set(public_paths)
    return sorted([d["path"], d["reason"]] for d in record["dropped"] if d["path"] in public and d["path"] not in have)


def _listed(paths, cap=LIST_CAP):
    shown = ", ".join(paths[:cap])
    return shown + (", and %d more" % (len(paths) - cap) if len(paths) > cap else "")


def refusal(paths, redirect_keys=()):
    """The guard's refusal, naming each path's own fix: an HTML page a redirect or a drop keeps, any other file a
    kept name, a kept copy or a drop. A `redirects` key that names a non-HTML path is said to be useless."""
    keys = set(k.strip("/") for k in redirect_keys)
    pages = [p for p in paths if is_html(p)]
    files = [p for p in paths if not is_html(p)]
    lines = ["the new build no longer has %d address%s the public site serves today (%s); a visitor, a bookmark or "
             "a search result may still use %s" % (len(paths), "" if len(paths) == 1 else "es", _listed(paths),
                                                    "it" if len(paths) == 1 else "them")]
    if pages:
        lines.append("for a page (%s): add a \"redirects\" entry to site/site.json, {\"<old>\": \"<new>\"}, or run "
                     "deploy.py drop <path> --reason TEXT" % _listed(pages, 4))
    if files:
        lines.append("for a file that is not a page (%s): a redirect cannot keep a file address, because a redirect "
                     "is an HTML page; keep the file's name, or commit a copy at site/src/<path>, or run deploy.py "
                     "drop <path> --reason TEXT" % _listed(files, 4))
        useless = [p for p in files if p in keys]
        if useless:
            lines.append("site.json redirects already names %s, which does not help: a redirect page is HTML and "
                         "cannot sit at a file address" % _listed(useless, 4))
    lines.append("then commit, push that commit to the main branch (a pull request merge), and run the dry run "
                 "again")
    return "; ".join(lines)


# ---------------------------------------------------------------- what both writers share

def _git_status(repo):
    try:
        p = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=all", "--"]
                           + list(CLEAN_PATHS), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AddressError("could not run git (%s); install git, or check that `git status` works in this folder, "
                           "then try again" % e.__class__.__name__)
    if p.returncode != 0:
        raise AddressError("git status failed here (%s); run this inside the dev repo"
                           % (p.stderr.decode("utf-8", "replace").strip().splitlines() or ["no reason given"])[-1])
    return [l for l in p.stdout.decode("utf-8", "replace").splitlines() if l.strip()]


def require_clean(repo):
    """Refuse while `site/`, `content/` or `.site-studio/` holds an uncommitted change. Narrower than "any dirty
    file" on purpose: a publish leaves HANDOFF.md uncommitted, and that must not block the next move. The writers
    read the working tree and commit only their own paths, so a change in these folders would be committed with
    them or be lost in the diff."""
    dirty = _git_status(repo)
    if dirty:
        raise AddressError("the tree has uncommitted changes in %s (%s); commit or discard them first, then try "
                           "again" % ("/, ".join(CLEAN_PATHS) + "/", dirty[0].strip()[:80]))


def check_prewrite(cfg, files):
    """The raise-schema pre-write check (R2-3): refuse a tree below schema 3, or one holding a `:::part` whose name
    schema 4 fixes. Both refusals name `build.py raise-schema`; nothing has been written when this raises. `files` is
    the tree as {path: bytes}."""
    if cfg.schema < 3:
        raise AddressError("this site is at schema %d, and recording an address needs schema 4, which is reached "
                           "through schema 3: run `build.py raise-schema` (it lists what changes before it writes), "
                           "commit, then try again" % cfg.schema)
    probs = siteconfig.part_collision_problems(files)
    if probs:
        raise AddressError("%s; a site with that part cannot be raised to schema 4, so rename it, then run `build.py "
                           "raise-schema` and try again" % probs[0].line())


def site_json_text(cfg, files, record_text):
    """The `site.json` text the tree needs once it carries `record_text` (at schema 4 or above, the guard reason).
    `files` is the tree without the record; this adds it, so `required_schema` sees the reason."""
    tree = dict(files)
    tree[RECORD_REL] = record_text.encode("utf-8")
    return siteconfig.canonical_text(cfg, tree, C.interpretation_reasons(tree), at_least=4)


def read_record_file(repo):
    """The working tree's record, or an empty one when the file is absent."""
    path = os.path.join(repo, *RECORD_REL.split("/"))
    if not os.path.isfile(path):
        return empty()
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return parse(fh.read())


def write_text(repo, rel, text):
    full = os.path.join(repo, *rel.split("/"))
    os.makedirs(posixpath.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_bytes(repo, rel, data):
    full = os.path.join(repo, *rel.split("/"))
    os.makedirs(posixpath.dirname(full) or ".", exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)
