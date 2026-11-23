"""document_verbs: `record.py presence-docx`, the one writer of a resume variant's managed Word file (jobsearch 0.93.0,
design-resume-docx.md §3, §4.1, §4.5, §5, §6.1, §8, §R2, §R3; B13).

    record.py presence-docx <variant-id> [--fresh] [--here] [--keep md|word] [--answer <ask-id>] [--attended] [--dry-run]
    record.py presence-docx --all [--dry-run]

**The state decides** (`presence/docx_state.derive`, §3.2 as §R3 amends it): `none` renders the default layout
(`variant_out.py --render`, run as its own program into a temp file beside the target); `in-sync` does nothing;
`md-ahead`, and `layout-edited` with the md changed, update the file in place (`presence/docx_update.update`);
`layout-edited` with the md the same, `unrecorded` and `both-edited` whose texts agree adopt the bytes as they are
(R3-2: a layout edit is never asked); `missing` refuses; `elsewhere` holds and refuses every write but `--here
--attended`. A Word file whose WORDS changed (`words-edited`, `both-edited`, `stale-save`, `unrecorded` whose texts
differ) is never taken back or overwritten by itself (R3-1): attended, the question is printed and nothing happens
until `--keep word|md`; unattended, ONE ask is filed (kind `system`, id `resume-word-edited:<variant>`, replaced by
id) and nothing is written to either file. `--keep word` takes the Word words into the md (`variant_patch`, written
through `presence_verbs._put_bytes`), two `stated` rows and an `adopt` row; `--keep md` takes the dated `before-keep`
backup and updates the Word file from the md. `--keep` with `--answer <ask-id>` needs no `--attended` and resolves
that ask under the same lock.

**Refused, nothing written** (§4.5): R13 (the resume directory outside the profile) first, before anything is read;
R1, R2, R7, R8 on every reconcile; R10 (the variant check), R11 (an editor's lock file), R12 (the target changed
since the scan, through `docx_package.replace_file`'s `rehash` seam) only when the Word file would be written; R3 to
R6 and R9 from the updater. `--fresh`, `--here` and `--keep` are refused without `--attended` (NOT ENFORCED beyond
the flag, §3.4). Under `mode: drive` every call prints `SKIPPED` and exits 0 (§R2 S2-1).

**Write order** (§4.1): the md, then the Word file (dated backup; temp file; R12; `os.replace`), then every row in
one locked append; a failed step puts back the bytes it replaced. Backups: `before-update` ten deep, `before-keep`
and `before-fresh` for ever (`docx_package`).

**Machines** (§R2 S2-2, §R3 R3-4): `machine_id(root, create=True)`; a None id in a git profile refuses. No remote:
the file is machine-local, and a tracked `.docx` in the resume directory prints `TRACKED`. A remote: when the
managed path is unmerged in the index, stage 2 is written to the path and stage 3 beside it as
`<stem>.remote-<short sha>.docx` (the stage-3 blob's), the index is touched no further, the `git add` the commit step
will run is printed, and R3-1's question names both files.

`--all` covers active variants on the `print` surface plus every variant an `approved` outbox row's `attachments`
name (read only). Every program this verb starts (`variant_out.py`, `resume_variants.py --check`, git) is reached
through `Deps`, so a test injects its own.

Capability module of record.py, reached from `mutation.preflight`; also `order_refusal`, §3.3's check there."""

import datetime
import json
import os
import re
import subprocess
import sys

import _atomic
import _tree
from journaling import journal_file as _jf
from presence import changes as _changes
from presence import docx_ats as _ats
from presence import docx_package as _pkg
from presence import docx_state as _state
from presence import docx_update as _upd
from presence import variant_patch as _vp
from presence.docx_match import identity as _identity
from presence.docx_match import word_text as _word_text
from presence.docx_scan import ScanRefusal
from presence.variant_compose import DEFAULT_MODE, DEFAULT_RENDER, _deep_merge, filename
from recording import presence_verbs as pv
from recording import profile_paths as _paths
from recording.common import _Usage
from recording.profile_paths import ENGINE_SCRIPTS
from recording.resolves import _asks_path, _load_asks

DOCUMENT_OPS = ("presence-docx",)
USAGE = ("presence-docx <variant-id> [--fresh] [--here] [--keep md|word] [--answer <ask-id>] [--attended] "
         "| presence-docx --all")
LOCK_WHY = "record.py presence-docx"
GIT_TIMEOUT = 15
_GATE_LINE = re.compile(r"^⛔ (\S+) \[([^\]]+)\]: (.*)$")
REMOTE_LINE = (" The other machine's copy is saved beside it as {remote}; to keep its words, copy it over {path} "
               "first, then answer.")
ELSEWHERE = ("ELSEWHERE {vid}: its Word file is kept on another machine (last written {date}). Attach it from there, "
             "or copy it to {path} and run record.py presence-docx {vid} --here --attended")
ANSWER_HOW = (" Answer: record.py presence-docx {vid} --keep word --answer {aid} (update it from the Word file), or "
              "record.py presence-docx {vid} --keep md --answer {aid} (keep ours; your file is backed up first).")


class _Rule(Exception):
    """A §4.5 refusal this verb raises itself (R10, R11, R13, missing): `rule`, `detail`, `route`."""

    def __init__(self, rule, detail, route=""):
        Exception.__init__(self, "%s: %s" % (rule, detail))
        self.rule, self.detail, self.route = rule, detail, route


def gate_state(root, vid):
    """None when `resume_variants.py --check` (its own program, the profile pinned) does not list `vid` as failing;
    else `<state>: <why>`. A check that cannot run is `unknown: ...`, never a pass (R10)."""
    cmd = [sys.executable, os.path.join(ENGINE_SCRIPTS, "resume_variants.py"), "--check"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, CLAUDESEARCH_ROOT=root))
    except (OSError, subprocess.SubprocessError) as e:
        return "unknown: resume_variants.py --check did not run (%s)" % type(e).__name__
    if r.returncode not in (0, 1):
        return "unknown: resume_variants.py --check exited %d" % r.returncode
    for line in (r.stderr or "").splitlines():
        m = _GATE_LINE.match(line.strip())
        if m and m.group(1) == vid:
            return "%s: %s" % (m.group(2), m.group(3))
    return None


def render_child(root, vid, out):
    """`variant_out.py --render <vid> --target docx --out <out>` as its own program: `(written, output lines)`. Exit 3
    (content loss) still wrote the file; its loud line is in the output."""
    cmd = [sys.executable, os.path.join(ENGINE_SCRIPTS, "variant_out.py"), "--render", vid, "--target", "docx",
           "--out", out]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, CLAUDESEARCH_ROOT=root))
    except (OSError, subprocess.SubprocessError) as e:
        return False, ["variant_out.py did not run (%s)" % type(e).__name__]
    lines = [l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip()]
    return r.returncode in (0, 3) and os.path.exists(out), lines


def _git(root, *argv, binary=False):
    r = subprocess.run(["git", "-C", root] + list(argv), capture_output=True, timeout=GIT_TIMEOUT)
    return r.returncode, r.stdout if binary else r.stdout.decode("utf-8", "replace")


class Deps:
    """Every program and clock the verb reaches, injectable: `gate(root, vid)`, `render(root, vid, out)`, `check()`,
    `has_remote(root)`, `machine_id(root, create)`, `git_dir(root)`, `rehash(path)` (R12's seam), `now()`."""

    def __init__(self, **kw):
        self.gate, self.render, self.check = gate_state, render_child, pv.variant_check
        self.has_remote, self.machine_id, self.git_dir = _state.has_remote, _jf.machine_id, _jf._git_common_dir
        self.rehash = _pkg.sha256_file
        self.now = lambda: datetime.datetime.now(datetime.timezone.utc)
        for k, v in kw.items():
            setattr(self, k, v)


# ---------------------------------------------------------------- settings and paths

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise pv._Refusal("%s cannot be read (%s); nothing written." % (os.path.basename(path), e))


def settings(root):
    """The resume-output block of `<root>/config.json`, the shipped defaults applied (as `variant_compose.
    output_settings`, which reads the remembered profile; this reads the bound one)."""
    cfg = _read_json(os.path.join(root, "config.json"))
    block = (cfg.get("writing") or {}).get("resume_output") or {}
    return {"mode": block.get("mode") or DEFAULT_MODE, "local_dir": block.get("local_dir") or _tree.rel("resumes"),
            "render": _deep_merge(DEFAULT_RENDER, block.get("render") or {})}


def resume_dir(root, local_dir):
    """`(absolute resume directory, inside the profile?)`: R13 compares real paths (absolute, `..`, a symlink out)."""
    path = _tree.resolve_rel(root, local_dir)
    real_root, real = os.path.realpath(root), os.path.realpath(path)
    return path, real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def _rel(root, path):
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")


def lock_files(rdir):
    """R11: `~$*` and `.~lock.*#` in the resume directory (a glob: one lock holds every variant there)."""
    try:
        names = os.listdir(rdir)
    except OSError:
        return []
    return sorted(n for n in names if n.startswith("~$") or (n.startswith(".~lock.") and n.endswith("#")))


def _headings(docx):
    try:
        styles = _pkg.read_part(docx, _ats.STYLES_PART)
    except _pkg.PackageRefusal as e:
        if "has no" not in e.detail:
            raise
        styles = None
    return _ats.heading_styles(_ats.style_table(styles))


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def all_ids(data):
    """`--all`: active variants on the `print` surface, then every variant an approved outbox row attaches."""
    variants = pv._rules.variant_rows(data) or {}
    ids = [v for v, r in variants.items() if r.get("status") != "retired" and (r.get("surface") or "print") == "print"]
    try:
        with open(os.path.join(data, "outbox.jsonl"), encoding="utf-8") as fh:
            outbox = [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        outbox = []
    except (OSError, ValueError) as e:
        raise pv._Refusal("outbox.jsonl cannot be read (%s), so --all cannot list the variants it attaches" % e)
    for row in outbox:
        if row.get("state") != "approved":
            continue
        for item in row.get("attachments") or []:
            ref = str((item or {}).get("ref") or "")
            if ref.startswith("resume:") and ref[7:] and ref[7:] not in ids:
                ids.append(ref[7:])
    return ids


# ---------------------------------------------------------------- git: TRACKED and the unmerged index (R3-4)

def tracked_lines(root, rdir):
    """§9 (no remote only): one `TRACKED` line per `.docx` git tracks in the resume directory."""
    try:
        rc, out = _git(root, "ls-files", "-z", "--", rdir)
    except (OSError, subprocess.SubprocessError):
        return []
    names = [n for n in out.split("\0") if n.lower().endswith(".docx")] if rc == 0 else []
    return ["TRACKED %s: this Word file is committed to the profile, so it travels and can conflict. To stop tracking "
            "it: git rm --cached -- %s, then commit. Your other machine's next pull then deletes its copy" % (n, n)
            for n in names]


def unmerged_stages(root, target):
    """`{stage: blob sha}` of `target` in the index when it is unmerged (`git ls-files -u`), else {}."""
    rc, out = _git(root, "ls-files", "-u", "-z", "--", target)
    stages = {}
    for entry in (out.split("\0") if rc == 0 else []):
        if "\t" in entry:
            _mode, sha, stage = entry.split("\t", 1)[0].split()
            stages[int(stage)] = sha
    return stages


def split_conflict(root, target, stages):
    """R3-4: stage 3 beside the target as `<stem>.remote-<short sha>.docx` (once), stage 2 at the target. Returns
    `(remote path, written now?)`; the index is not touched."""
    if 2 not in stages or 3 not in stages:
        raise _Rule("unmerged", "%s is unmerged with a side deleted (stages %s)" % (os.path.basename(target),
                    sorted(stages)), "resolve it by hand in git, then run it again")
    stem = os.path.basename(target)[:-5]
    remote = os.path.join(os.path.dirname(target), "%s.remote-%s.docx" % (stem, stages[3][:7]))
    if os.path.exists(remote):
        return remote, False
    rc3, theirs = _git(root, "cat-file", "blob", stages[3], binary=True)
    rc2, ours = _git(root, "cat-file", "blob", stages[2], binary=True)
    if rc2 or rc3:
        raise _Rule("unmerged", "git cat-file could not read the two sides", "run it again")
    for path, data in ((remote, theirs), (target, ours)):
        os.replace(_pkg.write_temp(path, data), path)
    return remote, True


# ---------------------------------------------------------------- the asks store (R3-1)

def _asks():
    try:
        return _load_asks() or []
    except ValueError as e:
        raise pv._Refusal("asks.jsonl cannot be read (%s); nothing written." % e)


def ask_row(vid, question, today):
    aid = _changes.word_edited_ask_id(vid)
    return {"id": aid, "kind": "system", "title": "Your Word resume for %s changed" % vid,
            "ask": question + ANSWER_HOW.format(vid=vid, aid=aid), "created": today, "act_by": None, "opp_id": None,
            "channel_id": None, "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None}


def file_ask(vid, question, today):
    """ONE open ask per variant, replaced by id (the `m_0_63_0` shape). False when the open one already says it."""
    new, out, found = ask_row(vid, question, today), [], False
    for a in _asks():
        if a.get("id") == new["id"] and not found:
            found = True
            if not a.get("resolved_on"):
                if a.get("ask") == new["ask"]:
                    return False
                new["created"] = a.get("created") or today
            a = new
        out.append(a)
    if not found:
        out.append(new)
    _atomic.write_jsonl(_asks_path(), out)
    return True


def open_ask(aid):
    return next((a for a in _asks() if a.get("id") == aid and not a.get("resolved_on")), None)


def resolve_ask(aid, keep, today):
    out = []
    for a in _asks():
        if a.get("id") == aid and not a.get("resolved_on"):
            a = dict(a, resolved_on=today, resolution="answered",
                     note="answered --keep %s by record.py presence-docx" % keep)
        out.append(a)
    _atomic.write_jsonl(_asks_path(), out)


# ---------------------------------------------------------------- one variant

class _Ctx:
    def __init__(self, args, deps, root):
        self.args, self.deps, self.root = args, deps, root
        self.dry_run = bool(getattr(args, "dry_run", False))
        self.attended = bool(getattr(args, "attended", False))
        self.keep, self.answer = getattr(args, "keep", None), getattr(args, "answer", None)
        self.fresh, self.here = bool(getattr(args, "fresh", False)), bool(getattr(args, "here", False))
        self.lines = []

    def say(self, line):
        self.lines.append(line)
        print(line)


def _derive(ctx, vid, docx, md, rows=()):
    return _state.derive(list(rows), vid, docx, md, ctx.machine, ctx.remote, ctx.ident, ctx.cfg,
                         _headings(docx) if docx is not None else None, here=ctx.here)


def _doc_row(ctx, vid, op, target, docx, md, removed=(), added=(), note=None):
    """The `document` row for the file `docx` and md `md` as they are after the event (fingerprints from `derive`,
    hashed exactly as the stale-save test reads them)."""
    st = _state.derive([], vid, docx, md, ctx.machine, False, ctx.ident, ctx.cfg, _headings(docx))
    ats = _ats.checks(st.scan, _headings(docx), st.alignment, st.blocks, ctx.ident)
    return _changes.document_row(vid, op, _rel(ctx.root, target), st.doc_sha256, st.doc_text_sha256,
                                 st.source_sha256, ats, ctx.machine, _changes.written_at_now(ctx.deps.now()),
                                 pv._today(), removed, added, note)


def _changed_texts(st):
    """`(removed, added)` of an update from `st`'s alignment: `text_hash` of each paragraph text replaced or deleted
    and of each text written (§3.2's stale-save test reads exactly these)."""
    paras, blocks, removed, added = st.scan.paragraphs, st.blocks, [], []
    for s in st.alignment.spans:
        for w, m, _r in s.pairs:
            old, new = _word_text(paras[w]), blocks[m]["text"]
            if old != new:
                removed.append(_state.text_hash(old))
                added.append(_state.text_hash(new))
        removed.extend(_state.text_hash(_word_text(paras[w])) for w in s.deleted)
        added.extend(_state.text_hash(blocks[m]["text"]) for m in s.inserted)
    return removed, added


def _write_word(ctx, target, data, expect, op):
    """R11, the dated backup (when a file is replaced), a temp file, R12, `os.replace`; prune on update."""
    locks = lock_files(os.path.dirname(target))
    if locks:
        raise _Rule("R11", "LOCKED: %s says an editor has a file here open" % locks[0],
                    "Close it. If no editor is open, delete that file")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    backup = _pkg.write_backup(target, op) if expect is not None else None
    tmp = _pkg.write_temp(target, data)
    try:
        _pkg.replace_file(tmp, target, expect, rehash=ctx.deps.rehash)
    except _pkg.PackageRefusal:
        if backup:
            os.remove(backup)
        raise
    if op == "update":
        _pkg.prune_update_backups(target)
    return backup


def _restore(target, old):
    msg = pv._restored(target, old)
    print("  %s: %s." % (os.path.basename(target), msg))


def _append(ctx, new_rows, undo):
    """The locked append of the variant's rows (the lock is already held); `undo()` puts the files back on failure."""
    rows, variants = pv.read_checked()
    pv._number(rows, new_rows)
    problems = pv._rules.check_rows(rows + new_rows, variants)
    if problems:
        undo()
        raise pv._Refusal("the rows would break the store's rules (nothing recorded): " + "; ".join(problems))
    try:
        pv._write_appended(new_rows)
    except pv._Rolled:
        undo()
        raise


def _render(ctx, vid, target, docx, md, op):
    """`none` and `--fresh`: the default layout, rendered by `variant_out.py` into a temp file, then written."""
    if ctx.dry_run:
        return ctx.say("WOULD RENDER %s to %s (default layout)" % (vid, _rel(ctx.root, target)))
    locks = lock_files(os.path.dirname(target))
    if locks:
        raise _Rule("R11", "LOCKED: %s says an editor has a file here open" % locks[0],
                    "Close it. If no editor is open, delete that file")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = os.path.join(os.path.dirname(target), ".%s.render-%d.tmp.docx" % (os.path.basename(target), os.getpid()))
    try:
        ok, lines = ctx.deps.render(ctx.root, vid, tmp)
        for line in lines:
            print("  " + line)
        if not ok:
            raise _Rule("render", "variant_out.py did not render it (above)", "fix what it names, then run it again")
        new = _read(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    backup = _write_word(ctx, target, new, _pkg.sha256_bytes(docx) if docx is not None else None, op)
    row = _doc_row(ctx, vid, "render", target, new, md, note="rendered by record.py presence-docx")
    _append(ctx, [row], lambda: _restore(target, docx))
    ctx.say("RENDERED %s to %s; RECORDED %s render%s" % (vid, row["file"], row["id"],
                                                          "; backup %s" % os.path.basename(backup) if backup else ""))


def _update(ctx, vid, target, docx, md, st, op="update"):
    """Write the md's words into the Word file in place (§4); `adopt` when nothing needs editing. R10 first."""
    bad = ctx.deps.gate(ctx.root, vid)
    if bad:
        raise _Rule("R10", "the variant fails its check (%s)" % bad, "resume_variants.py --check")
    up = _upd.update(docx, st.blocks, ctx.ident, _headings(docx))
    if not up.changed:
        return _adopt(ctx, vid, target, docx, md, "the Word file already holds the md's words")
    if ctx.dry_run:
        return ctx.say("WOULD UPDATE %s in place: %d edited, %d inserted, %d deleted"
                       % (vid, up.edited, up.inserted, up.deleted))
    removed, added = _changed_texts(st)
    backup = _write_word(ctx, target, up.docx, st.doc_sha256, op)
    row = _doc_row(ctx, vid, "update", target, up.docx, md, removed, added, note="updated in place by "
                   "record.py presence-docx%s" % (" --keep md" if op == "keep" else ""))
    _append(ctx, [row], lambda: _restore(target, docx))
    ctx.say("UPDATED %s in place (%d edited, %d inserted, %d deleted); RECORDED %s update; backup %s"
            % (vid, up.edited, up.inserted, up.deleted, row["id"], os.path.basename(backup)))


def _adopt(ctx, vid, target, docx, md, why):
    if ctx.dry_run:
        return ctx.say("WOULD ADOPT %s as it is (%s)" % (vid, why))
    row = _doc_row(ctx, vid, "adopt", target, docx, md, note="adopted by record.py presence-docx: " + why)
    _append(ctx, [row], lambda: None)
    for line in ["ATS %s: %s" % (c, _ats.REASONS[c]) for c in row["ats"]]:
        print("  " + line)
    ctx.say("ADOPTED %s (%s); RECORDED %s adopt" % (vid, why, row["id"]))


def _keep_word(ctx, vid, target, docx, md, md_path, st):
    """`--keep word` (§5.1): the Word words into the md, the candidate's; two `stated` rows and an `adopt` row."""
    ops = _vp.ops_from_alignment(st.scan, st.alignment, st.blocks, _headings(docx))
    new_md = _vp.patch(md, ops, ctx.cfg["page_break_marker"], ctx.cfg.get("preamble_marker"))
    if ctx.dry_run:
        return ctx.say("WOULD TAKE %d change(s) from the Word file into %s" % (len(ops), _rel(ctx.root, md_path)))
    rel_md = _rel(ctx.root, md_path)
    if not pv._put_bytes(md_path, new_md):
        raise pv._Refusal("%s could not be written; %s; nothing recorded." % (rel_md, pv._restored(md_path, md)))
    rows = [pv._row("stated", "session", target="variant", variant_id=vid, field="text", value=md.decode("utf-8"),
                    note="the text of %s before presence-docx --keep word, kept so it can be put back" % rel_md),
            pv._row("stated", "candidate", target="variant", variant_id=vid, field="text",
                    value=new_md.decode("utf-8"), note="taken from the Word file %s by record.py presence-docx "
                    "--keep word" % _rel(ctx.root, target)),
            _doc_row(ctx, vid, "adopt", target, docx, new_md, note="the Word file's words kept (--keep word)")]
    _append(ctx, rows, lambda: _restore(md_path, md))
    green, detail = ctx.deps.check()
    ctx.say("KEPT WORD %s: %d change(s) into %s; RECORDED %s" % (vid, len(ops), rel_md,
                                                                 " ".join("%s %s" % (r["id"], r["kind"]) for r in rows)))
    print("  resume_variants.py --check: %s" % ("green" if green else "not green (%s): reconcile %s against "
                                                "presence/claims.md, then resume_variants.py --stamp %s"
                                                % (detail, rel_md, vid)))


def _ask(ctx, vid, question):
    """R3-1 without `--keep`: attended, print the question; unattended, file ONE ask. Nothing written to the files."""
    aid = _changes.word_edited_ask_id(vid)
    if ctx.attended or ctx.dry_run:
        return ctx.say("ASK %s: %s%s" % (vid, question, ANSWER_HOW.format(vid=vid, aid=aid)))
    filed = file_ask(vid, question, pv._today())
    ctx.say("ASKED %s (%s%s): %s" % (vid, aid, "" if filed else ", already open", question))


def _question(st, vid, remote, target, root):
    q = st.question if st is not None and st.question else _state.question(vid)
    return q + (REMOTE_LINE.format(remote=_rel(root, remote), path=_rel(root, target)) if remote else "")


def _act(ctx, vid, target, docx, md, md_path, st, remote):
    """What the state's action, and the flags, say to do."""
    if st.action == "hold":
        if ctx.keep or ctx.fresh:
            raise _Rule("elsewhere", st.why, "only --here --attended is accepted here")
        return ctx.say(ELSEWHERE.format(vid=vid, date=st.since, path=_rel(ctx.root, target)))
    if ctx.fresh:
        return _render(ctx, vid, target, docx, md, "fresh")
    if st.action == "refuse":
        raise _Rule("missing", st.why, "restore it, or record.py presence-docx %s --fresh --attended" % vid)
    if ctx.keep and st.action != "ask":
        if not ctx.answer:
            raise _Rule("keep", "%s is %s: no Word edit is waiting for an answer" % (vid, st.state), "run it without --keep")
        return ctx.say("SETTLED %s: %s; nothing to keep" % (vid, st.state))
    if st.action == "render":
        return _render(ctx, vid, target, docx, md, "fresh")
    if st.action == "nothing":
        return ctx.say("IN-SYNC %s: nothing to do" % vid)
    if st.action == "adopt":
        return _adopt(ctx, vid, target, docx, md, st.why)
    if st.action == "update":
        return _update(ctx, vid, target, docx, md, st)
    if ctx.keep == "word":
        return _keep_word(ctx, vid, target, docx, md, md_path, st)
    if ctx.keep == "md":
        return _update(ctx, vid, target, docx, md, st, op="keep")
    return _ask(ctx, vid, _question(st, vid, remote, target, ctx.root))


def _locate(ctx, vid, rows, variants):
    """`(target, md path, md bytes)`: the newest row's `file` when there is one (the record), else the derived name."""
    _rec, md_path = pv._variant_file(variants, vid)
    md = _read(md_path)
    if md is None:
        raise pv._Refusal("%s's md file %s does not exist; nothing written." % (vid, _rel(ctx.root, md_path)))
    derived = os.path.join(ctx.rdir, filename(vid, ctx.user))
    newest = _changes.newest_document(rows, vid)
    if newest is None:
        return derived, md_path, md
    target = os.path.join(os.path.realpath(ctx.root), *newest["file"].split("/"))
    if os.path.realpath(target) != os.path.realpath(derived):
        print("  %s: the record names %s; the derived name would be %s, so the record's path is used"
              % (vid, newest["file"], _rel(ctx.root, derived)))
    return target, md_path, md


def reconcile(ctx, vid):
    """One variant, end to end. Raises `_Rule`, `pv._Refusal`, the scan's and updater's refusals."""
    rows, variants = pv.read_checked()
    if vid not in (variants or {}):
        raise pv._Refusal("no resume_variants row %r; nothing written." % vid)
    target, md_path, md = _locate(ctx, vid, rows, variants)
    remote_copy = None
    if ctx.remote:
        stages = unmerged_stages(ctx.root, target)
        if stages and ctx.dry_run:
            return ctx.say("WOULD SPLIT %s: %s is unmerged in the index" % (vid, _rel(ctx.root, target)))
        if stages:
            remote_copy, now = split_conflict(ctx.root, target, stages)
            if now:
                ctx.say("UNMERGED %s: this machine's file kept at %s, the other side saved as %s; the commit step "
                        "will run: git add -- %s" % (vid, _rel(ctx.root, target), _rel(ctx.root, remote_copy),
                                                     _rel(ctx.root, target)))
                return _ask(ctx, vid, _question(None, vid, remote_copy, target, ctx.root))
    docx = _read(target)
    st = _derive(ctx, vid, docx, md, rows)
    if docx is not None and st.scan is not None:
        _upd.check_reconcile(st.scan, ctx.ident, _upd.page_header_texts(docx))
    for line in st.header:
        print("  [header] %s" % line)
    _act(ctx, vid, target, docx, md, md_path, st, remote_copy)


# ---------------------------------------------------------------- the verb

def _usage_check(args):
    if bool(args.rid) == bool(getattr(args, "all_variants", False)) or args.rest:
        raise _Usage()


def _flag_refusal(ctx, args):
    """The flag rules after `SKIPPED`: --all takes no per-variant flag; --fresh, --here, --keep need --attended,
    except --keep with --answer (R3-1); --answer names this variant's ask and needs --keep."""
    if getattr(args, "all_variants", False) and (ctx.fresh or ctx.here or ctx.keep or ctx.answer):
        raise _Usage()
    if ctx.answer and not ctx.keep or (ctx.fresh and ctx.keep):
        raise _Usage()
    if ctx.answer:
        try:
            if _changes.ask_variant(ctx.answer) != args.rid:
                raise ValueError("%r is not %s's ask" % (ctx.answer, args.rid))
        except ValueError as e:
            raise pv._Refusal("--answer %s; nothing written." % e)
        if not ctx.dry_run and open_ask(ctx.answer) is None:
            raise pv._Refusal("no open ask %s to answer; nothing written." % ctx.answer)
    needs = [f for f, on in (("--fresh", ctx.fresh), ("--here", ctx.here), ("--keep", ctx.keep and not ctx.answer))
             if on]
    if needs and not ctx.attended:
        raise pv._Refusal("%s needs --attended (the candidate is present and chose it); nothing written."
                          % ", ".join(needs))


def _prepare(ctx):
    """Remote, machine, identity and settings, read once per call (R3-4, S2-2)."""
    try:
        ctx.remote = ctx.deps.has_remote(ctx.root)
    except _state.RemoteUnknown as e:
        raise pv._Refusal("whether the profile has a git remote is unknown (%s), so where its Word files live cannot "
                          "be decided; nothing written." % e)
    ctx.machine = ctx.deps.machine_id(ctx.root, create=not ctx.dry_run)
    if ctx.machine is None and not ctx.dry_run and ctx.deps.git_dir(ctx.root) is not None:
        raise pv._Refusal("the profile is a git repository and no machine id could be read or written, so the row "
                          "could not say which machine holds the file; nothing written.")
    ctx.user = _read_json(os.path.join(ctx.root, "user.json"))
    ctx.ident = _identity(ctx.user)


def _one(ctx, vid):
    """Exit 0 done, held or asked; 1 refused."""
    try:
        reconcile(ctx, vid)
        return 0
    except _Rule as e:
        ctx.say("REFUSED %s: %s: %s; nothing written" % (vid, e.rule, e.detail) + ("\n  " + e.route if e.route else ""))
    except (_upd.UpdateRefusal, ScanRefusal, _pkg.PackageRefusal, _vp.PatchRefusal) as e:
        ctx.say(_upd.refusal_line(vid, e))
    except pv._Refusal as e:
        ctx.say("REFUSED %s: %s" % (vid, e))
    except (OSError, subprocess.SubprocessError) as e:
        ctx.say("REFUSED %s: io: %s (%s); a step that wrote was put back where it could be" % (vid, e, type(e).__name__))
    except pv._Rolled:
        pass
    return 1


def cmd_document(args, deps=None):
    """`record.py presence-docx`: exit 0 done/held/asked/skipped, 1 refused, 2 usage."""
    deps = deps or Deps()
    root = _paths.ROOT
    ctx = _Ctx(args, deps, root)
    try:
        _usage_check(args)
        s = settings(root)
        every = getattr(args, "all_variants", False)
        if s["mode"] == "drive":
            for vid in (all_ids(_paths.DATA) if every else [args.rid]) or ["--all"]:
                ctx.say("SKIPPED %s: resume output mode is drive; no Word file is managed" % vid)
            return 0
        ctx.cfg = s["render"]
        ctx.rdir, inside = resume_dir(root, s["local_dir"])
        if not inside:                   # R13: before anything else is read
            ctx.say("REFUSED: local_dir is outside the profile. Set writing.resume_output.local_dir to a folder in the "
                    "profile, or write a copy with variant_out.py --render <id> --out <path>")
            return 1
        ids = all_ids(_paths.DATA) if every else [args.rid]
        _flag_refusal(ctx, args)
        _prepare(ctx)
    except _Usage:
        print("usage: " + USAGE)
        return 2
    except pv._Refusal as e:
        ctx.say("⛔ REFUSED — %s" % e)
        return 1
    if not ctx.remote:
        for line in tracked_lines(root, ctx.rdir):
            ctx.say(line)
    if ctx.dry_run:
        return max([_one(ctx, vid) for vid in ids] or [0])
    try:
        pv._lock(args, LOCK_WHY)
    except pv._Refusal as e:
        ctx.say("⛔ REFUSED — %s" % e)
        return 1
    try:
        rcs = [_one(ctx, vid) for vid in ids]
        aid = ctx.answer or (ctx.keep and _changes.word_edited_ask_id(args.rid))
        if aid and rcs == [0] and open_ask(aid):      # an attended --keep answers a filed ask too
            resolve_ask(aid, ctx.keep, pv._today())
            ctx.say("RESOLVED ask %s (--keep %s)" % (aid, ctx.keep))
    finally:
        if not args.already_locked:
            pv.release_lock()
    return max(rcs or [0])


def order_refusal(args):
    """§3.3, from `mutation.preflight`: 1, printed, when `presence-apply` or `presence-import` would write the md of a
    variant whose Word file's words changed (`docx_state.blocks_md_write`); else None. Never on `unrecorded` (§R1
    M-1); a state it cannot read is left to `presence-docx` itself."""
    if args.op not in ("presence-apply", "presence-import") or not args.rid:
        return None
    try:
        root = _paths.ROOT
        s = settings(root)
        rows, variants = pv.read_checked()
        vid = args.rid
        if args.op == "presence-apply":
            prop = next((r for r in rows if r.get("kind") == "proposal" and r.get("id") == args.rid), None)
            vid = (prop or {}).get("variant_id")
        if s["mode"] == "drive" or vid not in (variants or {}):
            return None
        ctx = _Ctx(args, Deps(), root)
        ctx.cfg, (ctx.rdir, inside) = s["render"], resume_dir(root, s["local_dir"])
        ctx.user = _read_json(os.path.join(root, "user.json"))
        ctx.ident, ctx.here = _identity(ctx.user), False
        target, _md_path, md = _locate(ctx, vid, rows, variants)
        docx = _read(target) if inside else None
        if docx is None:
            return None
        try:
            ctx.remote = ctx.deps.has_remote(root)
        except _state.RemoteUnknown:
            ctx.remote = True            # never `elsewhere`: the file is compared, the strict side
        ctx.machine = ctx.deps.machine_id(root, create=False)
        st = _derive(ctx, vid, docx, md, rows)
    except (pv._Refusal, ScanRefusal, _pkg.PackageRefusal, OSError, ValueError):
        return None
    if not _state.blocks_md_write(st.state):
        return None
    print("⛔ REFUSED — variant %s's Word file is %s (%s): its words changed and are not in the md yet, so %s would "
          "write over them. Run record.py presence-docx %s first; nothing written." % (vid, st.state, st.why, args.op,
                                                                                         vid))
    return 1
