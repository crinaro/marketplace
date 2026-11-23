"""store_rules: the `presence_changes` store's rules (design-presence-report.md §8.2, §R3), the one definition
`validate_data.py` and `recording/presence_verbs.py` both apply, so a row the verb would refuse is a row the validator
refuses.

`data/presence_changes.jsonl` is append-only dated event rows, kinds `stated`, `observed`, `proposal`, `decision`,
`refused`, and `document` (jobsearch 0.93.0, design-resume-docx.md §6.1). File order is event order: ids are
`pc-<n>` and strictly increase in file order, so a file a hand-resolved merge reordered is refused with the row named
and never replayed (`presence/changes.py` reads it through `check_rows`).
An absent file is an empty store (no migration); a present file that does not parse is a problem, never zero rows.

Checked here (the stored text only): every key set per kind; the enums; `variant_id` resolves to a `resume_variants`
row and is present exactly on a variant target; `value` is a string, or for `skills` a list of unique non-empty
strings (at most `SKILLS_MAX`); `status` is stated only; a decision names an EARLIER proposal, at most one decision
per proposal; `applied_on` and `applied_by` exactly with `applied`, `applied_on` not after `created`; `applied_by:
engine` on a LinkedIn proposal is refused ("the engine never edits"); at most one undecided proposal per gap; every
cited claim of a LinkedIn or public-surface proposal carries the `[public]` tag; a `refused` row is `by: session` and
carries exactly `gap` and `note`; every `gap` matches §5.7's key grammar (`gap_key_refusal`). A `document` row
(design-resume-docx.md §6.1, §R2 S2-2, S2-8) is `by: session` on a variant target and carries all ten of its fields
and none of the value fields: `doc_op` in DOC_OPS; `file` a "/"-separated profile-relative `.docx` path with no
backslash, no `..` and no absolute root (`doc_file_refusal`); the three fingerprints 64 lowercase hex; `ats` a list of
unique ids from ATS_CHECKS; `machine` null or a 32-hex machine id; `written_at` a parseable `YYYY-MM-DDTHH:MM:SSZ`
(a row without one is refused, since it decides "newest"); `removed` and `added` lists of 64-hex hashes, `[]` unless
`doc_op` is `update`.

NOT checked here, and why: that a cited claim still resolves to one union bullet (a union edited later is a report
state, as for `fit.requirements[].claim`; the verb checks it at the write), and that an `observed` row was confirmed
attended (a verb rule: `presence-state --observed` refuses without `--attended`); that a `document` row's `machine`
is non-null in a git profile (the verb refuses a None id before it writes, design-resume-docx.md §R2 S2-2: the store
cannot see whether the profile had a git common dir, so null is a legal SHAPE here); that `file` still exists.

It lives in `presence/`, not `validation/` (where B2 put it, now a facade): `resume_report.py` reads the
store through it, and a second top-level importer of `validation/` makes that package a node of its own and
grows the jobsearch G6 cycle 39 -> 40. Imported by `validate_data.py`, `recording/presence_verbs.py` (through
the facade) and `resume_report.py`. Python 3.9+, standard library only."""

import datetime
import json
import os
import re


STORE_FILE = "presence_changes.jsonl"
KINDS = ("stated", "observed", "proposal", "decision", "refused", "document")
BY = ("candidate", "profile-optimizer", "linkedin-runner", "session")
TARGETS = ("linkedin", "variant")
FIELDS_BY_TARGET = {"linkedin": ("status", "headline", "about", "skills", "experience", "featured"),
                    "variant": ("opening", "bullet", "text")}
STATUS_VALUES = ("none", "skip", "active")
DECISIONS = ("applied", "declined", "superseded")
APPLIED_BY = ("candidate", "engine")
DOC_OPS = ("render", "update", "adopt")   # design-resume-docx.md §6.1
# §4.6's check ids, the only values a `document` row's `ats` list may hold (presence/docx_ats.py runs them)
ATS_CHECKS = ("table", "textbox", "columns", "identity-top", "heading-style", "image")
DOC_FIELDS = ("doc_op", "file", "doc_sha256", "doc_text_sha256", "source_sha256", "ats", "machine", "written_at",
              "removed", "added")
SKILLS_MAX = 100          # LinkedIn's documented cap on listed skills (design prior art 2.2, as of 2026-11-22)
# the `public` visibility of surfaces.SURFACES (an entry point, so not imported): a variant on it is public
PUBLIC_SURFACES = ("public-profile",)

COMMON = ("id", "kind", "created", "by", "note")
KEYS = {"stated": COMMON + ("target", "variant_id", "field", "value"),
        "observed": COMMON + ("target", "variant_id", "field", "value"),
        # `handback`: the hand-back file a proposal was read from (§R3-5: a consumed path is refused on a retry)
        "proposal": COMMON + ("target", "variant_id", "field", "value", "gap", "before", "claims", "handback"),
        "decision": COMMON + ("proposal", "decision", "applied_on", "applied_value", "applied_by"),
        "refused": COMMON + ("gap",),
        "document": COMMON + ("target", "variant_id") + DOC_FIELDS}
REQUIRED = {"stated": ("target", "field", "value"), "observed": ("target", "field", "value"),
            "proposal": ("target", "field", "value", "gap", "before", "claims"), "decision": ("proposal", "decision"),
            "refused": ("gap", "note"), "document": ("target", "variant_id") + DOC_FIELDS}

ID_RE = re.compile(r"^pc-([1-9][0-9]*)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOPIC_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){0,5}$")         # == presence.skill_slugs.TOPIC_RE, pinned by its test
VARIANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# §5.7's five gap keys: title:<variant_id>@<h>, li:headline@<h>, li:skill:<topic>, claim:<sha8>, req:<topic>
GAP_RES = (("title", re.compile(r"^title:([A-Za-z0-9][A-Za-z0-9._-]*)@[0-9a-f]{6}$")),
           ("li:headline", re.compile(r"^li:headline@[0-9a-f]{6}$")),
           ("li:skill", re.compile(r"^li:skill:([a-z0-9]+(-[a-z0-9]+){0,5})$")),
           ("claim", re.compile(r"^claim:[0-9a-f]{8}$")),
           ("req", re.compile(r"^req:([a-z0-9]+(-[a-z0-9]+){0,5})$")))
PUBLIC_TAG_RE = re.compile(r"^\[public\]\s*\S", re.I)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MACHINE_RE = re.compile(r"^[0-9a-f]{32}$")                    # == journaling.row_shapes._MACHINE_RE, pinned by its test
WRITTEN_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
WRITTEN_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class PresenceStoreError(ValueError):
    """The store cannot be read. Loud by design: an unreadable store is never an empty one."""


def gap_key_refusal(key):
    """None when `key` is one of §5.7's gap keys, else the reason. The grammar only: whether the key is in the current
    dispatchable set is `presence/gaps.py`'s question (B4)."""
    if not isinstance(key, str):
        return "a gap key is a string (got %r)" % (key,)
    if any(rx.match(key) for _name, rx in GAP_RES):
        return None
    return ("%r is not a gap key (one of title:<variant_id>@<6 hex>, li:headline@<6 hex>, li:skill:<topic>, "
            "claim:<8 hex>, req:<topic>)" % key)


def doc_file_refusal(path):
    """None when `path` is a `document` row's `file`: relative to the profile root, "/"-separated, ending `.docx`, no
    backslash, no empty, `.` or `..` segment, no leading "/" and no drive letter. Else the reason
    (design-resume-docx.md §6.1)."""
    if not isinstance(path, str) or not path:
        return "file must be a non-empty string (got %r)" % (path,)
    if "\\" in path:
        return "file %r holds a backslash: the path is stored \"/\"-separated" % path
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return "file %r is absolute: it is stored relative to the profile root" % path
    segments = path.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return "file %r has an empty, \".\" or \"..\" segment" % path
    if not segments[-1].lower().endswith(".docx") or segments[-1].lower() == ".docx":
        return "file %r does not name a .docx file" % path
    return None


def parse_written_at(value):
    """The UTC `datetime` of a `written_at` stamp; raises `ValueError` on anything but `YYYY-MM-DDTHH:MM:SSZ` naming a
    real instant. The one parser: the store rule and the reader that orders rows by it both call it."""
    if not (isinstance(value, str) and WRITTEN_AT_RE.match(value)):
        raise ValueError("written_at %r is not YYYY-MM-DDTHH:MM:SSZ" % (value,))
    return datetime.datetime.strptime(value, WRITTEN_AT_FORMAT).replace(tzinfo=datetime.timezone.utc)


def load_file(path):
    """The rows of the store at `path`, in file order; `[]` when the file is absent; raises `PresenceStoreError` on a
    file that cannot be read or a line that is not one JSON object."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise PresenceStoreError("%s cannot be read (%s: %s)" % (path, type(exc).__name__, exc))
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise PresenceStoreError("%s line %d is not JSON (%s)" % (path, n, exc))
        if not isinstance(row, dict):
            raise PresenceStoreError("%s line %d is not a JSON object" % (path, n))
        rows.append(row)
    return rows


def id_number(row):
    m = ID_RE.match(str(row.get("id")))
    return int(m.group(1)) if m else None


def _is_date(v):
    if not (isinstance(v, str) and DATE_RE.match(v)):
        return False
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _value_problem(field, value):
    if field == "skills":
        if not isinstance(value, list) or not value:
            return "skills value must be a non-empty list of strings"
        if any(not (isinstance(s, str) and s.strip()) for s in value):
            return "every skill must be a non-empty string"
        if len(set(value)) != len(value):
            return "skills must be unique"
        if len(value) > SKILLS_MAX:
            return "at most %d skills (got %d)" % (SKILLS_MAX, len(value))
        return None
    if field == "status":
        return None if value in STATUS_VALUES else "status value %r not in {%s}" % (value, ", ".join(STATUS_VALUES))
    if not isinstance(value, str):
        return "value must be a string for field %r" % field
    return None


def _target_problems(row, variants, out, label):
    target, field = row.get("target"), row.get("field")
    if target not in TARGETS:
        out.append("%s: target %r not in {%s}" % (label, target, ", ".join(TARGETS)))
        return
    if field not in FIELDS_BY_TARGET[target]:
        out.append("%s: field %r not in {%s} for target %s"
                   % (label, field, ", ".join(FIELDS_BY_TARGET[target]), target))
        return
    vid = row.get("variant_id")
    if target == "variant":
        if not (isinstance(vid, str) and VARIANT_ID_RE.match(vid)):
            out.append("%s: variant_id is required on a variant target (got %r)" % (label, vid))
        elif variants is not None and vid not in variants:
            out.append("%s: variant_id %r resolves to no resume_variants row" % (label, vid))
    elif vid is not None:
        out.append("%s: variant_id must be null on a linkedin target" % label)
    if field == "status" and row.get("kind") != "stated":
        out.append("%s: a status row is stated only (kind %r)" % (label, row.get("kind")))
    why = _value_problem(field, row.get("value"))
    if why:
        out.append("%s: %s" % (label, why))


def public_required(row, variants):
    """True when a proposal's claims must all carry `[public]`: a LinkedIn target, or a variant on a public surface."""
    if row.get("target") == "linkedin":
        return True
    surface = (variants or {}).get(row.get("variant_id"), {}).get("surface")
    return surface in PUBLIC_SURFACES


def _proposal_problems(row, variants, out, label):
    why = gap_key_refusal(row.get("gap"))
    if why:
        out.append("%s: %s" % (label, why))
    before = row.get("before")
    if before is not None and not isinstance(before, (str, list)):
        out.append("%s: before must be a string, a list for skills, or null" % label)
    claims = row.get("claims")
    if not (isinstance(claims, list) and claims and all(isinstance(c, str) and c.strip() for c in claims)):
        out.append("%s: claims must be a non-empty list of the verbatim union bullets it rests on" % label)
    elif public_required(row, variants):
        for c in claims:
            if not PUBLIC_TAG_RE.match(c):
                out.append("%s: claim %r is not tagged [public] (ADR-027: a %s target cites [public] claims only)"
                           % (label, c, "linkedin" if row.get("target") == "linkedin" else "public-surface"))
    hb = row.get("handback")
    if hb is not None and not (isinstance(hb, str) and hb.strip()):
        out.append("%s: handback must be the hand-back file's path or absent" % label)


def _decision_problems(row, proposals, decided, out, label):
    pid, decision = row.get("proposal"), row.get("decision")
    prop = proposals.get(pid)
    if prop is None:
        out.append("%s: proposal %r names no EARLIER proposal row" % (label, pid))
    elif pid in decided:
        out.append("%s: proposal %s already has a decision (%s): a proposal has at most one" % (label, pid, decided[pid]))
    if decision not in DECISIONS:
        out.append("%s: decision %r not in {%s}" % (label, decision, ", ".join(DECISIONS)))
    applied = decision == "applied"
    on, by = row.get("applied_on"), row.get("applied_by")
    if applied != (on is not None) or applied != (by is not None):
        out.append("%s: applied_on and applied_by are required exactly with decision applied" % label)
    if on is not None and not _is_date(on):
        out.append("%s: applied_on %r is not an ISO date" % (label, on))
    elif on is not None and _is_date(row.get("created")) and on > row["created"]:
        out.append("%s: applied_on %s is after the row's created %s" % (label, on, row["created"]))
    if by is not None and by not in APPLIED_BY:
        out.append("%s: applied_by %r not in {%s}" % (label, by, ", ".join(APPLIED_BY)))
    if by == "engine" and prop is not None and prop.get("target") == "linkedin":
        out.append("%s: applied_by engine on a linkedin proposal (%s): the engine never edits a LinkedIn profile"
                   % (label, pid))
    av = row.get("applied_value")
    if av is not None and not isinstance(av, (str, list)):
        out.append("%s: applied_value must be null, a string, or a list for skills" % label)


def _hash_list_problem(name, value):
    if not isinstance(value, list):
        return "%s must be a list of 64-hex hashes (got %r)" % (name, value)
    bad = [v for v in value if not (isinstance(v, str) and SHA256_RE.match(v))]
    return "%s holds %r, not a 64-hex hash" % (name, bad[0]) if bad else None


def _document_problems(row, variants, out, label):
    """A `document` row's own shape (§6.1). The keys present/absent are check_rows' generic per-kind check."""
    if row.get("by") != "session":
        out.append("%s: a document row is by session (got %r)" % (label, row.get("by")))
    if row.get("target") != "variant":
        out.append("%s: a document row's target is variant (got %r)" % (label, row.get("target")))
    vid = row.get("variant_id")
    if not (isinstance(vid, str) and VARIANT_ID_RE.match(vid)):
        out.append("%s: variant_id is required on a document row (got %r)" % (label, vid))
    elif variants is not None and vid not in variants:
        out.append("%s: variant_id %r resolves to no resume_variants row" % (label, vid))
    op = row.get("doc_op")
    if op not in DOC_OPS:
        out.append("%s: doc_op %r not in {%s}" % (label, op, ", ".join(DOC_OPS)))
    if "file" in row:
        why = doc_file_refusal(row.get("file"))
        if why:
            out.append("%s: %s" % (label, why))
    for name in ("doc_sha256", "doc_text_sha256", "source_sha256"):
        if name in row and not (isinstance(row[name], str) and SHA256_RE.match(row[name])):
            out.append("%s: %s %r is not 64 lowercase hex" % (label, name, row[name]))
    ats = row.get("ats")
    if "ats" in row:
        if not isinstance(ats, list) or any(a not in ATS_CHECKS for a in ats):
            out.append("%s: ats must be a list of check ids from {%s} (got %r)" % (label, ", ".join(ATS_CHECKS), ats))
        elif len(set(ats)) != len(ats):
            out.append("%s: ats lists a check id twice (%r)" % (label, ats))
    machine = row.get("machine")
    if machine is not None and not (isinstance(machine, str) and MACHINE_RE.match(machine)):
        out.append("%s: machine %r is neither null nor a 32-hex machine id" % (label, machine))
    try:
        parse_written_at(row.get("written_at"))
    except ValueError as exc:
        out.append("%s: %s; a document row without a readable written_at cannot be ordered and is refused"
                   % (label, exc))
    for name in ("removed", "added"):
        if name not in row:
            continue
        why = _hash_list_problem(name, row[name])
        if why:
            out.append("%s: %s" % (label, why))
        elif op != "update" and row[name]:
            out.append("%s: %s must be [] on doc_op %r (only an update replaces text)" % (label, name, op))


def check_rows(rows, variants=None):
    """Every problem of `rows` (the store in file order). `variants` is `{variant id: resume_variants row}`, or None
    when that store is not at hand (variant ids are then checked for shape only)."""
    out, last, proposals, decided, undecided = [], 0, {}, {}, {}
    for i, row in enumerate(rows):
        label = "presence_changes[%d] %s" % (i, row.get("id"))
        n = id_number(row)
        if n is None:
            out.append("%s: id must be pc-<n>" % label)
        elif n <= last:
            out.append("%s: ids must strictly increase in file order (after pc-%d); a reordered file is never replayed"
                       % (label, last))
        else:
            last = n
        kind = row.get("kind")
        if kind not in KINDS:
            out.append("%s: kind %r not in {%s}" % (label, kind, ", ".join(KINDS)))
            continue
        extra = sorted(k for k in row if k not in KEYS[kind])
        if extra:
            out.append("%s: unknown key %r for kind %s (allowed: %s)" % (label, extra[0], kind, ", ".join(KEYS[kind])))
        missing = [k for k in REQUIRED[kind] if k not in row]
        if missing:
            out.append("%s: missing key %r for kind %s" % (label, missing[0], kind))
        if not _is_date(row.get("created")):
            out.append("%s: created %r is not an ISO date" % (label, row.get("created")))
        if row.get("by") not in BY:
            out.append("%s: by %r not in {%s}" % (label, row.get("by"), ", ".join(BY)))
        note = row.get("note")
        if note is not None and not isinstance(note, str):
            out.append("%s: note must be a string or null" % label)
        if kind in ("stated", "observed", "proposal"):
            _target_problems(row, variants, out, label)
        if kind == "proposal":
            _proposal_problems(row, variants, out, label)
            gap = row.get("gap")
            if gap in undecided:
                out.append("%s: %s already has an undecided proposal (%s): a new one supersedes it in the same write"
                           % (label, gap, undecided[gap]))
            undecided[gap] = row.get("id")
            proposals[row.get("id")] = row
        elif kind == "decision":
            _decision_problems(row, proposals, decided, out, label)
            prop = proposals.get(row.get("proposal"))
            if prop is not None and undecided.get(prop.get("gap")) == prop.get("id"):
                del undecided[prop.get("gap")]
            decided.setdefault(row.get("proposal"), row.get("id"))
        elif kind == "refused":
            if row.get("by") != "session":
                out.append("%s: a refused row is by session (got %r)" % (label, row.get("by")))
            why = gap_key_refusal(row.get("gap"))
            if why:
                out.append("%s: %s" % (label, why))
            if not (isinstance(note, str) and note.strip()):
                out.append("%s: a refused row's note carries the reason" % label)
        elif kind == "document":
            _document_problems(row, variants, out, label)
    return out


def variant_rows(data_dir):
    """`{id: row}` of `resume_variants.jsonl` beside the store, or None when it cannot be read (absent is empty)."""
    p = os.path.join(data_dir, "resume_variants.jsonl")
    try:
        with open(p, encoding="utf-8") as fh:
            return {r.get("id"): r for r in (json.loads(l) for l in fh if l.strip()) if isinstance(r, dict)}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None


def check_presence_changes(data_dir, problems):
    """validate_data's hook: append every problem of `<data_dir>/presence_changes.jsonl` and return the summary line."""
    try:
        rows = load_file(os.path.join(data_dir, STORE_FILE))
    except PresenceStoreError as exc:
        problems.append("presence_changes: %s" % exc)
        return "Presence changes: NOT CHECKED -- %s" % exc
    found = check_rows(rows, variant_rows(data_dir))
    problems.extend(found)
    if not rows:
        return "Presence changes: 0 rows (absent or empty is an empty store)"
    return "Presence changes: %d row(s) checked, %d problem(s)" % (len(rows), len(found))
