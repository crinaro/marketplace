"""attachments: a drafted email's resume file, from the drafts.md `**Attach:**` line to the `carried` verdict (jobsearch
0.93.0, design-resume-docx.md §6.2, §7.1, §R2 S2-1, M2-1, M2-3, S2-9, §R3 R3-1).

STAGE (§7.1 step 2). `stage_fields` reads an entry's one `**Attach:** resume:<variant-id>` line and gives the row
`attachments` (one item, `ref` set, the rest null) and `attach_sha256`. It refuses (`AttachError`, nothing written) two
Attach lines, a kind other than `resume`, and a variant that `resume_variants.jsonl` does not declare or has retired.

DRAFT (§7.1 step 4). When a draft call is about to be printed, `Probe.resolve` decides the attachment. The first row
that fits decides:

    1. `writing.resume_output.mode: drive` (S2-1), no Word file is managed: WITHOUT. Drafted without the file, the
       Drive by-hand line, `carried: false`; never left approved.
    2. The variant fails the gate (R10: `resume_variants.py --check` names it, or is not green): HOLD. The row stays
       approved and the file is never offered for attaching by hand.
    3. The resume directory is outside the profile (R13); a store, the md or `user.json` cannot be read; git cannot
       say whether the profile has a remote; reading the file is refused (R1, R2, R7, R8): WITHOUT, reason and route.
    4. The Word file is `in-sync`: ATTACH. gmail-multi's call carries it; a claude.ai connector gets the by-hand line.
    5. A state the next `presence-docx --all` settles alone (actions `render`, `update`, `adopt`: `none` with a
       complete identity, `md-ahead`, `layout-edited`, `unrecorded` or `both-edited` whose texts agree): HOLD, naming
       `record.py presence-docx <id>`.
    6. Every other state (`ask`: R3-1's word-changed states; `elsewhere`; `missing`; `none` with an incomplete
       identity): WITHOUT, the reason, and the path or, for `elsewhere`, the other machine.

The gate is checked before the file's state, one place where this differs from §7.1's row order: a variant that
fails the gate is never offered for attaching by hand, whatever its file's state (§7.1's last row), and the route it
names is the gate's, not a verb that would refuse it (R10).

The inputs come in from the entry point (`outbox.py`, the seam of §7.1 step 4): `gate` is a callable returning
`resume_variants.py --check`'s `(exit code, stderr)` (None for a check that did not run), run as its own program;
the document state is derived here from `presence/docx_state.derive`, and the mode from
`presence/variant_compose.output_settings`. Nothing here imports an entry point or starts a program.

CONFIRM (§7.1 step 5, NOT ENFORCED, §6.2). `settle` reads a saved draft-tool result with `attached_line.parse` and sets
`carried` true only when a line's hash AND size equal the stamp (the basename is not compared). No line, a different
hash or size, an empty or unreadable file: `carried: false`, `why` says which, and the by-hand line is printed. A
result saying gmail-multi refused the attachments means no draft exists: the row keeps the route a staged row whose
draft was never made already has (`outbox.py discard`, then stage again); no transition is added. `unconfirmed` is the
`UNCONFIRMED` line `outbox.py draft` and `list` print for a staged row still at `carried: null` (S2-9).

Capability module of `outbox.py` (through `sending/approval.py`). Python 3.9+, standard library only."""

import json
import os
import re

import _tree
import mail_connectors
from journaling import journal_file
from presence import changes, docx_ats, docx_state, store_rules
from presence import docx_match as dm
from presence import docx_update as du
from presence.docx_package import PackageRefusal, read_part
from presence.docx_scan import ScanRefusal
from presence.variant_compose import filename, identity_header, output_settings
from sending import attached_line
from sending import outbox_store as store
from validation.outbox_rules import ATTACH_KINDS, MAX_ATTACHMENTS, REF_RE, OutboxError, refs_sha256

ATTACH_RE = re.compile(r"^\*\*Attach:\*\*[ \t]*(.*?)[ \t]*$", re.M | re.I)
ATTACH, HOLD, WITHOUT = "attach", "hold", "without"
DRIVE_WHY = "resume output mode is drive"
GATE_ROUTE = "resume_variants.py --check"
GATE_LINE_RE = re.compile(r"^⛔ (?P<id>\S+) \[(?P<state>[a-z-]+)\]: (?P<why>.*)$")
NO_DRAFT_MARK = "no draft was created"           # gmail-multi drafting/attachments.py: a refusal makes no draft at all
OLDER_WHY = "gmail-multi did not confirm the attachment (older than 0.6.0?)"


class AttachError(ValueError):
    """An Attach line or a variant that cannot be staged; the text says why. Nothing was written."""


# ---------------------------------------------------------------- stage

def parse_attach(entry_body):
    """`(ref, variant id)` from an entry's one `**Attach:**` line, None when it has none. Strict: two lines, a value not
    `<kind>:<id>`, or a kind other than `resume` raise `AttachError`."""
    values = ATTACH_RE.findall(entry_body or "")
    if not values:
        return None
    if len(values) > MAX_ATTACHMENTS:
        raise AttachError("it has %d **Attach:** lines; a draft attaches at most %d file in this release"
                          % (len(values), MAX_ATTACHMENTS))
    m = REF_RE.match(values[0])
    if m is None:
        raise AttachError("its **Attach:** %r is not <kind>:<variant-id>, e.g. resume:<variant-id>" % values[0])
    if m.group("kind") not in ATTACH_KINDS:
        raise AttachError("its **Attach:** kind %r is unknown (known: %s)" % (m.group("kind"), ", ".join(ATTACH_KINDS)))
    return values[0], m.group("id")


def variant_row(root, variant_id):
    """The `resume_variants` row of `variant_id`, or None. A store that does not parse raises `AttachError`."""
    p = os.path.join(root, "data", "resume_variants.jsonl")
    try:
        with open(p, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise AttachError("resume_variants.jsonl cannot be read (%s: %s)" % (type(exc).__name__, exc))
    hits = [r for r in rows if isinstance(r, dict) and r.get("id") == variant_id]
    return hits[-1] if hits else None


def new_item(ref):
    return {"ref": ref, "file": None, "sha256": None, "bytes": None, "carried": None, "why": None}


def stage_fields(root, entry_body):
    """`{}` for an entry with no Attach line, else `{"attachments": [...], "attach_sha256": ...}` to merge into the
    new row. `AttachError` for an undeclared or retired variant, or a malformed line."""
    found = parse_attach(entry_body)
    if found is None:
        return {}
    ref, vid = found
    v = variant_row(root, vid)
    if v is None:
        raise AttachError("its **Attach:** names %s, which resume_variants.jsonl does not declare" % ref)
    if v.get("status") == "retired":
        raise AttachError("its **Attach:** names %s, which is retired" % ref)
    items = [new_item(ref)]
    return {"attachments": items, "attach_sha256": refs_sha256(items)}


# ---------------------------------------------------------------- draft

class Resolution(object):
    """What `Probe.resolve` decided for one ref: `outcome` (ATTACH, HOLD, WITHOUT), the variant, `why`, `route`, and
    for a file on this disk its absolute `path`, profile-relative `rel`, and the `sha256` and `nbytes` of the bytes the
    state was derived from (the stamp). `drive` marks the S2-1 outcome."""

    __slots__ = ("outcome", "variant_id", "why", "route", "path", "rel", "sha256", "nbytes", "drive")

    def __init__(self, outcome, variant_id, why=None, route=None, path=None, rel=None, sha256=None, nbytes=None,
                 drive=False):
        self.outcome, self.variant_id, self.why, self.route = outcome, variant_id, why, route
        self.path, self.rel, self.sha256, self.nbytes, self.drive = path, rel, sha256, nbytes, drive


def gate_verdict(returncode, stderr, variant_id):
    """None when `variant_id` passes the gate, else why it does not. `resume_variants.py --check` prints one
    `⛔ <id> [<state>]: <why>` line per variant in its FAIL_STATES and one `⛔ <problem>` line per store-wide
    problem; a store-wide problem, a check that did not run, or a failure naming nothing fails every variant."""
    if returncode is None:
        return stderr or "resume_variants.py --check did not run"
    if returncode == 0:
        return None
    lines = [line for line in (stderr or "").splitlines() if line.startswith("⛔")]
    if not lines:
        return "resume_variants.py --check exited %d and named no variant" % returncode
    for line in lines:
        m = GATE_LINE_RE.match(line)
        if m is None:
            return "resume_variants.py --check is not green: %s" % line[1:].strip()
        if m.group("id") == variant_id:
            return "%s is %s: %s" % (variant_id, m.group("state"), m.group("why"))
    return None


def _inside(root, path):
    r, p = os.path.realpath(root), os.path.realpath(path)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _heading_styles(docx):
    try:
        return docx_ats.heading_styles(docx_ats.style_table(read_part(docx, "word/styles.xml")))
    except PackageRefusal:
        return {}


def from_state(st, variant_id, path, rel, user):
    """The outcome a derived `DocState` gives (the table in the module docstring, after the gate)."""
    verb = "record.py presence-docx %s" % variant_id
    if st.action == "nothing":
        return Resolution(ATTACH, variant_id, path=path, rel=rel, sha256=st.doc_sha256, nbytes=None)
    if st.action == "render" and identity_header(user)[0] is None:
        return Resolution(WITHOUT, variant_id, path=path, rel=rel, route="fill identity in user.json, then " + verb,
                          why="it has no Word file yet, and user.json lacks %s for one"
                          % ", ".join(identity_header(user)[1]))
    if st.action in ("render", "update", "adopt"):
        return Resolution(HOLD, variant_id, route=verb, why="its Word file is %s (%s)" % (st.state, st.why))
    if st.state == "elsewhere":
        return Resolution(WITHOUT, variant_id, route="attach it from that machine",
                          why="its Word file is kept on another machine (%s)" % st.why)
    return Resolution(WITHOUT, variant_id, path=path, rel=rel, route=verb + " (attended: it asks you)",
                      why="its Word file is %s: %s" % (st.state, st.why))


def word_file_state(root, variant_id, settings, machine=None, remote=None):
    """Derive `variant_id`'s Word-file outcome from disk. `machine` and `remote` default to this machine's id
    (`machine_id(create=False)`: a reader never creates it) and `docx_state.has_remote(root)`."""
    rdir = _tree.resolve_rel(root, settings.get("local_dir") or "")
    if not _inside(root, rdir):
        return Resolution(WITHOUT, variant_id, why="R13: the resume directory %s is outside the profile" % rdir,
                          route="set writing.resume_output.local_dir to a folder in the profile")
    try:
        rows = store_rules.load_file(os.path.join(root, "data", store_rules.STORE_FILE))
        problems = store_rules.check_rows(rows)
        if problems:
            raise ValueError("presence_changes.jsonl does not hold: %s" % problems[0])
        v = variant_row(root, variant_id)
        if v is None or not v.get("file"):
            raise ValueError("resume_variants.jsonl declares no file for %s" % variant_id)
        user = _load_json(os.path.join(root, "user.json"))
        newest = changes.newest_document(rows, variant_id)
        rel = newest["file"] if newest else os.path.relpath(os.path.join(rdir, filename(variant_id, user)),
                                                             root).replace(os.sep, "/")
        path = os.path.join(root, *rel.split("/"))
        with open(os.path.join(root, v["file"]), "rb") as fh:
            md = fh.read()
        docx = None
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                docx = fh.read()
        if machine is None:
            machine = journal_file.machine_id(root)
        if remote is None:
            remote = docx_state.has_remote(root)
    except (OSError, ValueError, docx_state.RemoteUnknown) as exc:
        return Resolution(WITHOUT, variant_id, route="record.py presence-docx %s" % variant_id,
                          why="its Word file's state cannot be read (%s)" % exc)
    ident = dm.identity(user)
    try:
        st = docx_state.derive(rows, variant_id, docx, md, machine, remote, ident, cfg=settings.get("render"),
                               heading_styles=_heading_styles(docx) if docx else None)
        if st.scan is not None:
            du.check_reconcile(st.scan, ident, du.page_header_texts(docx))
    except (ScanRefusal, PackageRefusal, du.UpdateRefusal) as exc:
        return Resolution(WITHOUT, variant_id, path=path, rel=rel, route=du.ROUTES.get(exc.rule) or "named above",
                          why="its Word file is refused (%s: %s)" % (exc.rule, exc.detail))
    except ValueError as exc:
        return Resolution(WITHOUT, variant_id, path=path, rel=rel, route="record.py presence-docx %s" % variant_id,
                          why="its Word file's state cannot be read (%s)" % exc)
    res = from_state(st, variant_id, path, rel, user)
    if res.outcome == ATTACH:
        res.nbytes = len(docx)
    return res


class Probe(object):
    """The three inputs of §7.1 step 4 for one run: the mode (`settings`, default `output_settings()`), the gate
    (`gate()` -> `(exit code or None, stderr)`, run at most once) and the Word-file state (`state_of(root, variant id,
    settings)`, default `word_file_state`)."""

    def __init__(self, root, gate, settings=None, state_of=None):
        self.root, self._gate, self._gate_out = root, gate, None
        self._settings, self._state_of = settings, state_of or word_file_state

    def gate_why(self, variant_id):
        if self._gate_out is None:
            self._gate_out = self._gate()
        return gate_verdict(self._gate_out[0], self._gate_out[1], variant_id)

    def resolve(self, ref):
        m = REF_RE.match(ref or "")
        vid = m.group("id") if m else str(ref)
        try:
            settings = self._settings if self._settings is not None else output_settings()
        except (OSError, ValueError) as exc:
            return Resolution(WITHOUT, vid, why="the resume output settings cannot be read (%s)" % exc,
                              route="config.json")
        if settings.get("mode") == "drive":
            return Resolution(WITHOUT, vid, why=DRIVE_WHY, drive=True)
        why = self.gate_why(vid)
        if why:
            return Resolution(HOLD, vid, why="it fails the resume gate (%s)" % why, route=GATE_ROUTE)
        return self._state_of(self.root, vid, settings)


def without_line(outbox_id, res):
    """The ATTACH BY HAND line for a draft made without its file."""
    if res.drive:
        return ("ATTACH BY HAND %s: resume output is set to Drive, so there is no Word file of %s to attach. Add your "
                "resume to the draft before you press Send" % (outbox_id, res.variant_id))
    head = "ATTACH BY HAND %s: the Word file of %s is not attached: %s (%s)." % (outbox_id, res.variant_id, res.why,
                                                                                res.route)
    if res.path is None:
        return head + " Add your resume to the draft before you press Send."
    return "%s %s %s" % (head, mail_connectors.ADD_IT, mail_connectors.path_sentence(res.path))


def stamp(item, res, carried=None, why=None):
    """Stamp `item` with the file the printed call names: its relative path, hash and size, and the verdict so far."""
    item.update({"file": res.rel, "sha256": res.sha256, "bytes": res.nbytes, "carried": carried, "why": why})


def unstamped_without(item, res):
    item.update({"carried": False, "why": res.why if not res.drive else DRIVE_WHY})


def ready_note(res):
    """The approval line's attachment note (§7.1 step 3)."""
    if res.outcome == ATTACH:
        return "attaches %s (in sync)" % os.path.basename(res.path)
    if res.outcome == HOLD:
        return "attaches resume:%s once ready: %s; run %s" % (res.variant_id, res.why, res.route)
    return "drafted without its file: %s" % res.why


# ---------------------------------------------------------------- confirm

def judge(item, text):
    """`(carried, why)` for a saved result `text` (None for an unreadable file) against the item's stamp."""
    if text is None:
        return False, "the result file could not be read"
    if not text.strip():
        return False, "the result file is empty"
    try:
        lines = attached_line.parse(text)
    except ValueError as exc:
        return False, "the result's attached line could not be read (%s)" % exc
    if any(a.sha256 == item["sha256"] and a.nbytes == item["bytes"] for a in lines):
        return True, None
    if NO_DRAFT_MARK in text:
        return False, "gmail-multi refused the attachment, so no draft was created"
    if lines:
        return False, "gmail-multi attached a different file (%s), not the %d bytes printed" % (
            "; ".join("%s, %d bytes, %s" % (a.basename, a.nbytes, a.sha256[:12]) for a in lines), item["bytes"])
    return False, OLDER_WHY


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, ValueError):
        return None


def settle(root, outbox_id, result_file):
    """`outbox.py attached`: set each stamped item's `carried` from the saved result, under the outbox lock. Returns
    the printed lines. `OutboxError` for no such row, or a row that printed no file to attach."""
    text = _read(result_file)
    with store.lock(root, why="outbox.py attached"):
        rows = store.load(root)
        row = store.find(rows, outbox_id)
        if row is None:
            raise OutboxError("no outbox row %s; nothing recorded" % outbox_id)
        items = [i for i in (row.get("attachments") or []) if i.get("sha256")]
        if not items:
            raise OutboxError("%s printed no file to attach, so there is nothing to confirm; nothing recorded"
                              % outbox_id)
        out = []
        for item in items:
            item["carried"], item["why"] = judge(item, text)
            name = item["file"].rsplit("/", 1)[-1]
            if item["carried"]:
                out.append("%s: %s attached, size and hash match what was printed" % (outbox_id, name))
            elif item["why"].startswith("gmail-multi refused"):
                out.append("NO DRAFT %s: %s. The row stays %s: outbox.py discard %s, then stage the draft again"
                           % (outbox_id, item["why"], row.get("state"), outbox_id))
            else:
                out.append("MISMATCH %s: %s" % (outbox_id, item["why"]))
                out.append("ATTACH BY HAND %s: %s. %s %s" % (outbox_id, item["why"], mail_connectors.ADD_IT,
                                                             mail_connectors.path_sentence(
                                                                 os.path.join(root, *item["file"].split("/")))))
        problems = store.check_row(row)
        if problems:
            raise OutboxError("; ".join(problems))
        store.save(root, rows)
    return out


def unconfirmed(rows):
    """S2-9: one `UNCONFIRMED` line per staged row whose printed attachment has no recorded result yet."""
    return ["UNCONFIRMED %s: run outbox.py attached %s --result-file <f>" % (r["id"], r["id"]) for r in rows
            if r.get("state") == "staged"
            and any(i.get("sha256") and i.get("carried") is None for i in (r.get("attachments") or []))]
