"""presence_verbs: the writers and the reader of `data/presence_changes.jsonl` (design-presence-report.md §8.2, §R3).

    record.py presence                                                  current status, headline and skills; open proposals
    record.py presence-state linkedin status none|skip|active           kind stated, by candidate
    record.py presence-state linkedin headline --text-file <f>
    record.py presence-state linkedin skills --from-file <f>            one skill per line
    record.py presence-state --observed --from-file <f> --attended      linkedin-runner's hand-back, confirmed
    record.py presence-propose --from-file <f> --dispatched <key> ...   one JSON object per line, strict keys
    record.py presence-decide <id> applied [--applied-on D] [--as-edited --text-file <f>] | declined [--why "..."]
    record.py presence-apply <id> [--attended]                          a variant proposal, applied directly (owner 2026-11-23)
    record.py presence-import <variant-id> --from-file <f>              a resume from outside the profile into a variant file

**presence-apply** (§7; owner ruling 2026-11-23: "Claude should edit your resume, it's in the local project so no
authorization is needed"): a variant file is the candidate's own profile, so no action mode and no `--attended` gate holds
it; the flag, when given, is only recorded in the note. A LinkedIn target is refused with `reach/keys.me_refusal`'s
`linkedin-profile-edit` reason (the engine never edits a LinkedIn profile). Under the run lock it replaces the proposal's
`before` text, found EXACTLY once (overlapping finds counted; zero or two writes nothing), with its `value` in the variant's
file, runs the variant check (`variant_check`: `resume_variants.py --check` as its own program, exit 0 green; a test
injects its own callable), restores the file's exact bytes when the check is not green and records nothing, and otherwise
appends one `decision` row: `applied`, `applied_on` today, `applied_value` null, `applied_by: engine`, `by: session`. A
rolled-back append restores the file's bytes too.

**presence-import** (the same ruling): `presence/resume_import.read_external` reads a `.md`, `.markdown`, `.txt` or
`.docx` file from anywhere; any other kind is refused with its route. The variant must be declared in `resume_variants`.
Under the run lock it writes the text into the variant's file and appends `stated` rows, target `variant`, field `text`:
first the file's earlier text (`by: session`) when it had any, so the import can be seen and put back; then the imported
text (`by: candidate`, the source's name in the note). Text identical to the file's writes nothing. The variant check runs
after and is printed, never restoring: an imported resume is the candidate's own document, and its check states
(unstamped, drifted) name the reconcile the import starts. A rolled-back append restores the file's bytes.

**Append-only in fact.** No verb rewrites a row: every write appends whole lines under the run lock, re-reads the file
inside the lock, checks the whole would-be store against `validation/presence_rules.py` BEFORE writing, runs the
whole-store validator before and after, and on a new problem truncates the file back to its exact earlier bytes. After
every verb the file's earlier bytes are a prefix of it. Ids are minted here (`pc-<n>`, one above the highest stored).

**presence-propose** (§R3): every `--dispatched` key must match §5.7's grammar AND be in the current dispatchable set
for the given `--attended` value (§R3-2), which `resume_report.py --gaps --json` computes; that program is started
here the way `row_checks.validate` starts the store validator (variant state reaches the report only as a
subprocess, §11), and a set it cannot compute refuses the call, never waves the keys through. With the flag, a proposal whose `gap` was not dispatched is refused; leaving the flag out is valid only with
`--attended`. The hand-back is parsed line by line: an unparseable line prints `REFUSED <line n>: <reason>` and spoils
no other. A proposal cites claims by `<sha8>`; each must resolve to exactly one union bullet, `[public]` for a
LinkedIn or public-surface target, and the verbatim bullet is stored. A missing or empty `--from-file` is zero
proposals. Each dispatched key judged only on whether a row was RECORDED for it: one with none gets a `refused` row
(`by: session`, exactly `gap` and `note`), which stops an unattended run redrafting it. A hand-back path a stored
row was already judged on is refused on a retry, so a rerun appends nothing: a proposal carries it as `handback`, a
`refused` row as its note's ` [hand-back <path>]` suffix (so an all-refused or missing hand-back is consumed too). At most one undecided proposal per
gap: a new one appends a `superseded` decision for the older, BEFORE itself, in the same write.

Capability module of record.py (an entry point over `recording/`). Reached from the store-verb path's first step
(`mutation.preflight`), as the affiliations verb is."""

import datetime
import json
import os
import subprocess
import sys

from presence import changes as _changes
from presence import resume_import as _import
from presence.union_text import CLAIM_TAG_RE, bullets_with_sections, read_union, sha8
from reach import keys as _rk
from recording import profile_paths as _paths
from recording.profile_paths import ENGINE_SCRIPTS
from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.store_files import LockError, lock_is_held, release_lock, take_lock
from validation import presence_rules as _rules

PRESENCE_OPS = ("presence", "presence-state", "presence-propose", "presence-decide", "presence-apply", "presence-import")
PROPOSAL_LINE_KEYS = ("gap", "target", "variant_id", "field", "value", "before", "claims", "note")
PROPOSAL_REQUIRED = ("gap", "target", "field", "value", "claims")
USAGE = {
    "presence-state": ("presence-state linkedin status none|skip|active | presence-state linkedin headline --text-file <f> "
                       "| presence-state linkedin skills --from-file <f> | presence-state --observed --from-file <f> "
                       "--attended"),
    "presence-propose": "presence-propose --from-file <f> --dispatched <key> ... [--attended]",
    "presence-decide": ("presence-decide <id> applied [--applied-on D] [--as-edited --text-file <f>] | "
                        "presence-decide <id> declined [--why \"...\"]"),
    "presence-apply": "presence-apply <id> [--attended]",
    "presence-import": "presence-import <variant-id> --from-file <f.md|f.markdown|f.txt|f.docx>",
}


class _Refusal(Exception):
    """A refusal printed as `⛔ REFUSED — <text>`, exit 1, nothing written."""


def store_path():
    return os.path.join(_paths.DATA, _rules.STORE_FILE)


def _today():
    return datetime.date.today().isoformat()


def read_checked():
    """`(rows, variants)` of the store as it is, refused when it cannot be read or does not hold."""
    variants = _rules.variant_rows(_paths.DATA)
    try:
        rows = _rules.load_file(store_path())
    except _rules.PresenceStoreError as e:
        raise _Refusal(str(e))
    problems = _rules.check_rows(rows, variants)
    if problems:
        raise _Refusal("%s does not hold, so it is not replayed or appended to (%d problem(s)); first: %s"
                       % (_rules.STORE_FILE, len(problems), problems[0]))
    return rows, variants


def _read_lines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    return [(n, (raw[:-1] if raw.endswith("\r") else raw).strip(" \t"))
            for n, raw in enumerate(text.split("\n"), 1) if raw.strip(" \t\r")]


def _number(rows, new_rows):
    """Give each of `new_rows` its id, in order, one above the highest stored."""
    n = int(_changes.next_id(rows)[3:])
    for r in new_rows:
        r["id"] = "pc-%d" % n
        n += 1
    return new_rows


def _row(kind, by, **fields):
    row = {"id": None, "kind": kind, "created": _today(), "by": by, "note": None}
    row.update(fields)
    return row


def _render(out):
    """Result lines: a string as it is, a `(template, row)` pair with the row's minted id in `{id}`."""
    return "\n".join(o if isinstance(o, str) else o[0].format(id=o[1]["id"]) for o in out)


def _append(args, why, plan):
    """The append-only write. `plan(rows, variants)` returns `(new rows, result lines, partial)` or raises `_Refusal`;
    it runs once to report, and again inside the lock on the file as it is then. Exit 0 written, 1 when `partial`
    (some line refused; the rest still written) or refused or rolled back."""
    rows, variants = read_checked()
    new_rows, out, partial = plan(rows, variants)
    if not new_rows or args.dry_run:
        _number(rows, new_rows)
        print(_render(out))
        if args.dry_run:
            print("  --dry-run: nothing written.")
        return 1 if partial else 0
    if args.already_locked:
        if not lock_is_held():
            raise _Refusal("--already-locked, but NOBODY holds the run lock.")
    else:
        try:
            take_lock(why, wait=args.wait)
        except LockError as e:
            raise _Refusal(str(e))
    try:
        rows, variants = read_checked()
        new_rows, out, partial = plan(rows, variants)
        _number(rows, new_rows)
        if new_rows:
            problems = _rules.check_rows(rows + new_rows, variants)
            if problems:
                raise _Refusal("the rows would break the store's rules (nothing written): " + "; ".join(problems))
            _write_appended(new_rows)
    finally:
        if not args.already_locked:
            release_lock()
    print(_render(out))
    return 1 if partial else 0


def _write_appended(new_rows):
    path = store_path()
    try:
        with open(path, "rb") as fh:
            before = fh.read()
    except FileNotFoundError:
        before = None
    pre = validate()[3]
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new_rows)
    lead = "\n" if before and not before.endswith(b"\n") else ""
    with open(path, "ab") as fh:
        fh.write((lead + text).encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
    rc, out, err, post = validate()
    added = new_problems(pre, post)
    if rc != 0 and (added is None or added):
        ok = _truncate_back(path, before)
        print("⛔ the write left the store invalid and was %s."
              % ("ROLLED BACK (byte-identical)" if ok else
                 "NOT VERIFIABLY ROLLED BACK — restore presence_changes.jsonl from git"))
        print("  " + "\n  ".join(added if added else _diagnostic_lines(rc, out, err)))
        raise _Rolled()


class _Rolled(Exception):
    """The append was rolled back; its lines are printed."""


def _truncate_back(path, before):
    try:
        if before is None:
            os.remove(path)
            return not os.path.exists(path)
        with open(path, "r+b") as fh:
            fh.truncate(len(before))
        with open(path, "rb") as fh:
            return fh.read() == before
    except OSError:
        return False


# ---- presence (the read form) ---------------------------------------------------------------------------------------

def cmd_show(rows):
    status, srow = _changes.current(rows, "linkedin", "status")
    print("PRESENCE linkedin status: %s" % ("%s (stated %s, %s)" % (status, srow["created"], srow["id"]) if srow
                                             else "not stated"))
    for field in ("headline", "skills"):
        value, row = _changes.current(rows, "linkedin", field)
        if row is None:
            print("  %s: not stated" % field)
        else:
            shown = ", ".join(value) if isinstance(value, list) else value
            print("  %s (%s %s, %s): %s" % (field, row.get("kind"), row.get("created"), row.get("id"), shown))
    open_rows = _changes.open_proposals(rows)
    print("  open proposals: %d" % len(open_rows))
    for p in open_rows:
        print("    %s %s since %s (%s %s)" % (p["id"], p.get("gap"), p.get("created"), p.get("target"), p.get("field")))
    edits = _variant_edits(rows)
    print("  resume variant edits: %d%s" % (len(edits), " (newest last)" if edits else ""))
    for line in edits[-10:]:
        print("    " + line)
    return 0


def _variant_edits(rows):
    """One line per row that changed a variant file: an import's `stated` text rows and each applied variant proposal."""
    props = {r.get("id"): r for r in rows if r.get("kind") == "proposal"}
    out = []
    for r in rows:
        if r.get("kind") == "stated" and r.get("target") == "variant":
            out.append("%s %s %s %s (%s)" % (r["id"], r.get("created"), r.get("variant_id"), r.get("field"),
                                              r.get("note") or "stated"))
        elif r.get("kind") == "decision" and r.get("decision") == "applied" \
                and props.get(r.get("proposal"), {}).get("target") == "variant":
            p = props[r["proposal"]]
            out.append("%s %s %s %s (%s applied by %s)" % (r["id"], r.get("created"), p.get("variant_id"), p.get("field"),
                                                         p["id"], r.get("applied_by")))
    return out


# ---- presence-state ---------------------------------------------------------------------------------------------------

def _text_file(path, flag):
    if not path:
        raise _Usage()
    try:
        with open(path, encoding="utf-8") as fh:
            text = " ".join(fh.read().split())
    except (OSError, UnicodeDecodeError) as e:
        raise _Refusal("%s %s cannot be read (%s); nothing written." % (flag, path, e))
    if not text:
        raise _Refusal("%s %s is empty; nothing written." % (flag, path))
    return text


def _skills_file(path):
    if not path:
        raise _Usage()
    try:
        lines = [l.strip() for _n, l in _read_lines(path)]
    except (OSError, UnicodeDecodeError) as e:
        raise _Refusal("--from-file %s cannot be read (%s); nothing written." % (path, e))
    skills = [l for l in lines if l]
    why = _rules._value_problem("skills", skills)
    if why:
        raise _Refusal("%s (%s); nothing written." % (why, path))
    return skills


class _Usage(Exception):
    """A usage error: the verb's usage line, exit 2."""


def _with_status(rows, new_rows):
    """Stating a headline or skills after `none` or `skip` writes `status: active` in the same locked write."""
    status, _r = _changes.current(rows, "linkedin", "status")
    if status in ("none", "skip"):
        new_rows.insert(0, _row("stated", "candidate", target="linkedin", variant_id=None, field="status",
                                value="active", note="stated with the %s" % new_rows[0]["field"]))
    return new_rows


def _observed_rows(path):
    """linkedin-runner's hand-back: one JSON object per line, `{"field": "headline"|"skills", "value": ...}`."""
    out = []
    try:
        lines = _read_lines(path)
    except (OSError, UnicodeDecodeError) as e:
        raise _Refusal("--from-file %s cannot be read (%s); nothing written." % (path, e))
    for n, line in lines:
        try:
            obj = json.loads(line)
        except ValueError as e:
            raise _Refusal("line %d of %s is not JSON (%s); nothing written." % (n, path, e))
        if not isinstance(obj, dict) or sorted(obj) != ["field", "value"] or obj["field"] not in ("headline", "skills"):
            raise _Refusal("line %d of %s must be exactly {\"field\": \"headline\"|\"skills\", \"value\": ...}; "
                           "nothing written." % (n, path))
        out.append(_row("observed", "linkedin-runner", target="linkedin", variant_id=None, field=obj["field"],
                        value=obj["value"]))
    if not out:
        raise _Refusal("--from-file %s holds no observed field; nothing written." % path)
    return out


def cmd_state(args):
    if getattr(args, "observed", False):
        if not getattr(args, "attended", False):
            raise _Refusal("presence-state --observed writes only with --attended, after the candidate confirms what "
                           "was read; nothing written.")
        new = _observed_rows(args.from_file) if args.from_file else None
        if new is None:
            raise _Usage()
    else:
        if args.rid != "linkedin" or not args.rest:
            raise _Usage()
        field = args.rest[0]
        if field == "status":
            if len(args.rest) != 2 or args.rest[1] not in _rules.STATUS_VALUES:
                raise _Usage()
            value = args.rest[1]
        elif field == "headline" and len(args.rest) == 1:
            value = _text_file(getattr(args, "text_file", None), "--text-file")
        elif field == "skills" and len(args.rest) == 1:
            value = _skills_file(args.from_file)
        else:
            raise _Usage()
        new = [_row("stated", "candidate", target="linkedin", variant_id=None, field=field, value=value)]

    def plan(rows, _variants):
        rows_new = [dict(r) for r in new]
        if rows_new[0]["field"] in ("headline", "skills"):
            rows_new = _with_status(rows, rows_new)
        return rows_new, [("RECORDED {id} %s %s %s" % (r["kind"], r["target"], r["field"]), r) for r in rows_new], False
    return _append(args, "record.py presence-state", plan)


# ---- presence-propose -------------------------------------------------------------------------------------------------

def _union_by_sha():
    text = read_union(_paths.ROOT)
    if text is None:
        return None
    out = {}
    for bullet, _section in bullets_with_sections(text):
        out.setdefault(sha8(bullet), []).append(bullet)
    return out


def _parse_proposal(line):
    """`(object, None)` or `(None, reason)`: the strict shape of one hand-back line."""
    try:
        obj = json.loads(line)
    except ValueError as e:
        return None, "not JSON (%s)" % e
    if not isinstance(obj, dict):
        return None, "not one JSON object"
    extra = sorted(str(k) for k in obj if k not in PROPOSAL_LINE_KEYS)
    if extra:
        return None, "unknown key %r (allowed: %s)" % (extra[0], ", ".join(PROPOSAL_LINE_KEYS))
    missing = [k for k in PROPOSAL_REQUIRED if k not in obj]
    if missing:
        return None, "missing key %r" % missing[0]
    if not (isinstance(obj["claims"], list) and obj["claims"] and all(isinstance(c, str) for c in obj["claims"])):
        return None, "claims must be a non-empty list of <sha8> keys"
    return obj, None


def _proposal_row(obj, union, variants, handback):
    """The stored proposal for a parsed line, or raises `_Refusal` with the reason."""
    why = _rules.gap_key_refusal(obj["gap"])
    if why:
        raise _Refusal(why)
    if union is None:
        raise _Refusal("presence/claims.md cannot be read, so no cited claim can be resolved")
    row = _row("proposal", "profile-optimizer", target=obj["target"], variant_id=obj.get("variant_id"),
               field=obj["field"], value=obj["value"], gap=obj["gap"], before=obj.get("before"), claims=[],
               handback=handback, note=obj.get("note"))
    public = _rules.public_required(row, variants)
    for key in obj["claims"]:
        hits = union.get(key, [])
        if len(hits) != 1:
            raise _Refusal("claim %s resolves to %d union bullets, not exactly one" % (key, len(hits)))
        m = CLAIM_TAG_RE.match(hits[0])
        if public and not (m and m.group(1).lower() == "public"):
            raise _Refusal("claim %s is not tagged [public] (a %s target cites [public] claims only)"
                           % (key, row["target"]))
        row["claims"].append(hits[0])
    problems = _rules.check_rows([dict(row, id="pc-1")], variants)
    if problems:
        raise _Refusal(problems[0].split(": ", 1)[-1])
    return row


def _supersede(rows, gap, pending):
    """A `superseded` decision for the undecided proposal on `gap`, if any (stored or written earlier in this call)."""
    decided = _changes.decisions(rows)
    for p in reversed(rows):
        if p.get("kind") == "proposal" and p.get("gap") == gap and p.get("id") not in decided:
            return _row("decision", "session", proposal=p["id"], decision="superseded", applied_on=None,
                        applied_value=None, applied_by=None, note="superseded by a newer proposal for %s" % gap)
    for p in reversed(pending):
        if p.get("kind") == "proposal" and p.get("gap") == gap:
            return "pending"
    return None


def dispatchable_keys(attended):
    """`(set of keys, None)`, or `(None, reason)`: the dispatchable set of `resume_report.py --gaps --json` (with
    `--attended` when given), run as its own program with the profile root pinned (§R3-2)."""
    cmd = [sys.executable, os.path.join(ENGINE_SCRIPTS, "resume_report.py"), "--gaps", "--json"]
    env = dict(os.environ, CLAUDESEARCH_ROOT=_paths.ROOT)
    try:
        r = subprocess.run(cmd + (["--attended"] if attended else []), capture_output=True, text=True, env=env,
                           timeout=300)
        rep = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return None, "resume_report.py --gaps --json failed (%s)" % type(e).__name__
    keys = rep.get("dispatchable") if isinstance(rep, dict) else None
    if not isinstance(keys, list):
        return None, "resume_report.py --gaps --json gave no dispatchable list (exit %d)" % r.returncode
    return set(keys), None


def cmd_propose(args):
    dispatched = getattr(args, "dispatched", None)
    attended = getattr(args, "attended", False)
    if dispatched is None and not attended:
        print("⛔ REFUSED — --dispatched <key> ... is required unless the run is --attended; nothing written.")
        print("  usage: " + USAGE["presence-propose"])
        return 2
    if dispatched is None and not args.from_file:
        raise _Usage()
    for key in dispatched or ():
        why = _rules.gap_key_refusal(key)
        if why:
            raise _Refusal("--dispatched %s; nothing written." % why)
    if dispatched:
        allowed, why = dispatchable_keys(attended)
        if allowed is None:
            raise _Refusal("the dispatchable set cannot be computed (%s); nothing written." % why)
        for key in dispatched:
            if key not in allowed:
                raise _Refusal("--dispatched %s is not in the current dispatchable set%s (resume_report.py --gaps%s); "
                               "nothing written." % (key, "" if attended else " for an unattended run",
                                                     " --attended" if attended else ""))
    path = os.path.abspath(args.from_file) if args.from_file else None
    try:
        lines = _read_lines(path) if path else []
        note = "no hand-back" if not lines else None
    except FileNotFoundError:
        lines, note = [], "no hand-back"
    except (OSError, UnicodeDecodeError) as e:
        lines, note = [], "no hand-back (%s cannot be read: %s)" % (path, e)

    def plan(rows, variants):
        if path:
            used = _changes.consumed_by(rows, path)
            if used:
                raise _Refusal("%s was already consumed (%s): a hand-back is read once; nothing written." % (path, used))
        union = _union_by_sha() if lines else None
        new, out, recorded, why_by_gap = [], [], set(), {}
        for n, line in lines:
            obj, why = _parse_proposal(line)
            if obj is None:
                out.append("REFUSED %d: %s" % (n, why))
                continue
            gap = obj["gap"]
            if dispatched is not None and gap not in dispatched:
                out.append("REFUSED %s: not dispatched (dispatched: %s)" % (gap, " ".join(dispatched)))
                continue
            try:
                row = _proposal_row(obj, union, variants, path)
                sup = _supersede(rows, gap, new)
                if sup == "pending":
                    raise _Refusal("a second proposal for %s in one hand-back" % gap)
            except _Refusal as e:
                out.append("REFUSED %s: %s" % (gap, e))
                why_by_gap.setdefault(gap, str(e))
                continue
            if sup:
                new.append(sup)
                out.append("SUPERSEDED %s %s" % (sup["proposal"], gap))
            new.append(row)
            recorded.add(gap)
            out.append(("RECORDED {id} %s" % gap, row))
        for key in dispatched or ():
            if key not in recorded:
                reason = note or ("nothing recorded: %s" % why_by_gap[key] if key in why_by_gap
                                  else "nothing recorded: the hand-back holds no proposal for it")
                new.append(_row("refused", "session", gap=key, note=_changes.handback_note(reason, path)))
                out.append(("REFUSED %s: %s (refused row {id})" % (key, reason), new[-1]))
        if not lines and not dispatched:
            out.append("presence-propose: %s; nothing recorded" % (note or "no hand-back"))
        partial = any(isinstance(o, str) and o.startswith("REFUSED") for o in out)
        return new, out, partial or any(k not in recorded for k in dispatched or ())
    return _append(args, "record.py presence-propose", plan)


# ---- presence-decide --------------------------------------------------------------------------------------------------

def cmd_decide(args):
    if not args.rid or len(args.rest) != 1 or args.rest[0] not in ("applied", "declined"):
        raise _Usage()
    pid, decision = args.rid, args.rest[0]
    as_edited, text_file = getattr(args, "as_edited", False), getattr(args, "text_file", None)
    if decision == "declined" and (as_edited or getattr(args, "applied_on", None)):
        raise _Usage()
    if as_edited != bool(text_file):
        raise _Usage()

    def plan(rows, _variants):
        prop = next((r for r in rows if r.get("kind") == "proposal" and r.get("id") == pid), None)
        if prop is None:
            raise _Refusal("no proposal with id %r; nothing written." % pid)
        if pid in _changes.decisions(rows):
            raise _Refusal("%s already has a decision (%s); nothing written."
                           % (pid, _changes.decisions(rows)[pid]["id"]))
        if decision == "declined":
            row = _row("decision", "candidate", proposal=pid, decision="declined", applied_on=None,
                       applied_value=None, applied_by=None, note=getattr(args, "why", None))
        else:
            value = None
            if as_edited:
                value = (_skills_file(text_file) if prop.get("field") == "skills"
                         else _text_file(text_file, "--text-file"))
            row = _row("decision", "candidate", proposal=pid, decision="applied",
                       applied_on=getattr(args, "applied_on", None) or _today(), applied_value=value,
                       applied_by="candidate")
        return [row], [("RECORDED {id} %s for %s" % (decision, pid), row)], False
    return _append(args, "record.py presence-decide", plan)


# ---- presence-apply and presence-import (owner ruling 2026-11-23: a variant file is edited directly) ---------------------

def variant_check():
    """`(green, detail)` of `resume_variants.py --check`, run as its own program with the profile root pinned (§7's
    subprocess contract: exit 0 green, anything else, a failure to start included, not green)."""
    cmd = [sys.executable, os.path.join(ENGINE_SCRIPTS, "resume_variants.py"), "--check"]
    env = dict(os.environ, CLAUDESEARCH_ROOT=_paths.ROOT)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, "resume_variants.py --check did not run (%s)" % type(e).__name__
    tail = [l for l in (r.stderr or r.stdout or "").splitlines() if l.strip()][-3:]
    return r.returncode == 0, "exit %d%s" % (r.returncode, (": " + " | ".join(tail)) if tail else "")


def _occurrences(text, needle):
    """Every start of `needle` in `text`, overlapping ones included (so "aa" is found twice in "aaa")."""
    out, i = [], text.find(needle)
    while i != -1:
        out.append(i)
        i = text.find(needle, i + 1)
    return out


def _variant_file(variants, vid):
    """`(resume_variants row, absolute path of its file)`, the path inside the profile, or `_Refusal`."""
    rec = (variants or {}).get(vid)
    if not (isinstance(rec, dict) and isinstance(rec.get("file"), str) and rec["file"]):
        raise _Refusal("variant %r has no readable resume_variants row with a file; nothing written." % vid)
    root = os.path.realpath(_paths.ROOT)
    path = os.path.realpath(os.path.join(root, rec["file"]))
    if os.path.commonpath([root, path]) != root:
        raise _Refusal("variant %s's file %r is outside the profile; nothing written." % (rec.get("id"), rec["file"]))
    return rec, path


def _apply_plan(rows, variants, pid, attended):
    """`(decision row, variant file path, its bytes now, its bytes after)` for applying proposal `pid`, or `_Refusal`."""
    prop = next((r for r in rows if r.get("kind") == "proposal" and r.get("id") == pid), None)
    if prop is None:
        raise _Refusal("no proposal with id %r; nothing written." % pid)
    if prop.get("target") != "variant":         # the engine never edits a LinkedIn profile
        why = _rk.me_refusal({}, "linkedin-profile-edit")
        raise _Refusal("%s targets %s, and linkedin-profile-edit offers no `me` (%s): the candidate pastes it, then runs "
                       "`record.py presence-decide %s applied`; nothing written." % (pid, prop.get("target"), why, pid))
    if pid in _changes.decisions(rows):
        raise _Refusal("%s already has a decision (%s); nothing written." % (pid, _changes.decisions(rows)[pid]["id"]))
    before = prop.get("before")
    if not (isinstance(before, str) and before) or not isinstance(prop.get("value"), str):
        raise _Refusal("%s has no `before` text to replace (a variant edit replaces exact text); nothing written." % pid)
    rec, path = _variant_file(variants, prop.get("variant_id"))
    try:
        with open(path, "rb") as fh:
            old = fh.read()
        text = old.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise _Refusal("%s cannot be read (%s); nothing written." % (rec["file"], e))
    found = _occurrences(text, before)
    if len(found) != 1:
        raise _Refusal("%s's `before` text is found %d times in %s, not exactly once; nothing written."
                       % (pid, len(found), rec["file"]))
    new = (text[:found[0]] + prop["value"] + text[found[0] + len(before):]).encode("utf-8")
    row = _row("decision", "session", proposal=pid, decision="applied", applied_on=_today(), applied_value=None,
               applied_by="engine", note="applied by record.py presence-apply (%s run) to %s; resume_variants.py --check "
                                         "green" % ("attended" if attended else "unattended", rec["file"]))
    return row, path, old, new


APPLY_LOCK_WHY = "record.py presence-apply"     # the lock's reason; the store is re-read inside it (read_checked)


def _put_bytes(path, data):
    """Replace `path`'s bytes with `data` (a sibling temp file, then `os.replace`); True when a read-back equals it."""
    tmp = "%s.presence-apply.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        with open(path, "rb") as fh:
            return fh.read() == data
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _restored(path, old):
    if old is None:                              # the file did not exist before: putting it back is removing it
        try:
            os.remove(path)
        except OSError:
            pass
        return "it is removed again" if not os.path.exists(path) else "it was NOT verifiably removed: delete it by hand"
    ok = _put_bytes(path, old)
    return "its bytes are restored" if ok else "its bytes were NOT verifiably restored: restore it from git"


def _lock(args, why):
    if args.already_locked:
        if not lock_is_held():
            raise _Refusal("--already-locked, but NOBODY holds the run lock.")
    else:
        try:
            take_lock(why, wait=args.wait)
        except LockError as e:
            raise _Refusal(str(e))


def cmd_apply(args, check=None):
    """`presence-apply <id> [--attended]`: replace the proposal's exact `before` with its `value` in the variant file, under
    the run lock; run the variant check; restore the file's bytes unless it is green; then append the `applied` decision
    (`applied_by: engine`, `by: session`). Attended or not (owner ruling 2026-11-23). `check` is `variant_check` unless a
    test injects one."""
    if not args.rid or args.rest:
        raise _Usage()
    attended = bool(getattr(args, "attended", False))
    check = check or variant_check
    if args.dry_run:
        rows, variants = read_checked()
        row, path, _old, _new = _apply_plan(rows, variants, args.rid, attended)
        print("WOULD APPLY %s to %s and record an applied decision" % (args.rid, os.path.relpath(path, os.path.realpath(_paths.ROOT))))
        print("  --dry-run: nothing written.")
        return 0
    _lock(args, APPLY_LOCK_WHY)
    try:
        rows, variants = read_checked()
        row, path, old, new = _apply_plan(rows, variants, args.rid, attended)
        _number(rows, [row])
        problems = _rules.check_rows(rows + [row], variants)
        if problems:
            raise _Refusal("the decision would break the store's rules (nothing written): " + "; ".join(problems))
        rel = os.path.relpath(path, os.path.realpath(_paths.ROOT))
        if not _put_bytes(path, new):
            raise _Refusal("%s could not be written; %s; nothing recorded." % (rel, _restored(path, old)))
        green, detail = check()
        if not green:
            raise _Refusal("resume_variants.py --check is not green after the edit (%s); %s %s; nothing recorded."
                           % (detail, rel, _restored(path, old)))
        try:
            _write_appended([row])
        except _Rolled:
            print("  %s: %s." % (rel, _restored(path, old)))
            raise
    finally:
        if not args.already_locked:
            release_lock()
    print("APPLIED %s to %s; RECORDED %s applied (applied_by engine)" % (args.rid, rel, row["id"]))
    return 0


def _import_plan(rows, variants, vid, text, source):
    """`(new stated rows, variant file path, its bytes now or None, its bytes after)`, or None when the file already holds
    exactly `text`; `_Refusal` for an undeclared variant or an earlier text that cannot be kept."""
    if vid not in (variants or {}):
        raise _Refusal("no resume_variants row %r: declare the variant in data/resume_variants.jsonl first (id, archetype, "
                       "file, surface, status, created); nothing written." % vid)
    rec, path = _variant_file(variants, vid)
    try:
        with open(path, "rb") as fh:
            old = fh.read()
    except FileNotFoundError:
        old = None
    except OSError as e:
        raise _Refusal("%s cannot be read (%s); nothing written." % (rec["file"], e))
    new = text.encode("utf-8")
    if old == new:
        return None
    out = []
    if old is not None and old.strip():
        try:
            earlier = old.decode("utf-8")
        except UnicodeDecodeError:
            raise _Refusal("%s is not UTF-8, so its earlier text cannot be kept for putting back; nothing written."
                           % rec["file"])
        out.append(_row("stated", "session", target="variant", variant_id=vid, field="text", value=earlier,
                        note="the text of %s before presence-import, kept so it can be put back" % rec["file"]))
    out.append(_row("stated", "candidate", target="variant", variant_id=vid, field="text", value=text,
                    note="imported by record.py presence-import from %s" % os.path.basename(source)))
    return out, path, old, new


def cmd_import(args, check=None):
    """`presence-import <variant-id> --from-file <f>`: the resume at `f` (anywhere) becomes the variant's file, under the
    run lock, with its `stated` rows appended; the variant check is run and printed. `check` as for `cmd_apply`."""
    if not args.rid or args.rest or not args.from_file:
        raise _Usage()
    try:
        text = _import.read_external(args.from_file)
    except _import.ImportRefusal as e:
        raise _Refusal("%s; nothing written." % e)
    check = check or variant_check
    if args.dry_run:
        rows, variants = read_checked()
        plan = _import_plan(rows, variants, args.rid, text, args.from_file)
        print("WOULD IMPORT %d line(s) into variant %s%s" % (text.count("\n"), args.rid, "" if plan else " (unchanged)"))
        print("  --dry-run: nothing written.")
        return 0
    _lock(args, "record.py presence-import")
    try:
        rows, variants = read_checked()
        plan = _import_plan(rows, variants, args.rid, text, args.from_file)
        if plan is None:
            print("UNCHANGED %s already holds exactly this text; nothing written." % args.rid)
            return 0
        new_rows, path, old, new = plan
        _number(rows, new_rows)
        problems = _rules.check_rows(rows + new_rows, variants)
        if problems:
            raise _Refusal("the rows would break the store's rules (nothing written): " + "; ".join(problems))
        rel = os.path.relpath(path, os.path.realpath(_paths.ROOT))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not _put_bytes(path, new):
            raise _Refusal("%s could not be written; %s; nothing recorded." % (rel, _restored(path, old)))
        try:
            _write_appended(new_rows)
        except _Rolled:
            print("  %s: %s." % (rel, _restored(path, old)))
            raise
    finally:
        if not args.already_locked:
            release_lock()
    green, detail = check()
    print("IMPORTED %s into %s; RECORDED %s" % (os.path.basename(args.from_file), rel,
                                               " ".join("%s stated %s" % (r["id"], r["by"]) for r in new_rows)))
    print("  resume_variants.py --check: %s" % ("green" if green else "not green (%s): reconcile %s against "
                                                "presence/claims.md, then resume_variants.py --stamp %s"
                                                % (detail, rel, args.rid)))
    return 0


def cmd_presence(args):
    """The one entry from `mutation.preflight` for every presence verb: exit 0, 1 refused, 2 usage."""
    try:
        if args.op == "presence":
            if args.rid or args.rest:
                raise _Usage()
            return cmd_show(read_checked()[0])
        fn = {"presence-state": cmd_state, "presence-propose": cmd_propose, "presence-decide": cmd_decide,
              "presence-apply": cmd_apply, "presence-import": cmd_import}[args.op]
        return fn(args)
    except _Usage:
        print("usage: " + USAGE.get(args.op, "presence"))
        return 2
    except _Refusal as e:
        print("⛔ REFUSED — %s" % e)
        return 1
    except _Rolled:
        return 1
