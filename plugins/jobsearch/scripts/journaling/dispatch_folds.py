"""Folding a dispatch transcript into the journal, pass durations, and the `--dispatches` / `--passes` /
`--calibrate` reports.

Capability module of `journal.py` (S4a, moved unedited)."""

import json
import re
import sys
from _root import transcript_stash_path
from journaling.instants import _parse_iso
from journaling.journal_file import now_iso, read
from journaling.linkedin_passes import crashed_passes, pass_rows
from journaling.passes import dispatch_rows, record_dispatch
from journaling.tables import JournalError, OUTCOME_MAP


def pass_durations(recs):
    """design-linkedin-runner-resilience.md §1 (public #47/#96) — the MEASUREMENT tool behind
    `linkedin.pane_stale_minutes`'s UNVERIFIED default. For every run that both started and
    ended AND carries evidence of LinkedIn work, its wall-clock duration in minutes — longest
    first, so the owner reads the worst case off the top rather than guessing.

    "Carries LinkedIn work" is two different correlations, because a `gap` carries `run_id`
    directly but a `probe` never has (it is pointwise, not run-scoped — see `record_probe`):
    a `gap` whose scope starts with `linkedin:` counts its own `run_id` directly; a `probe` on
    medium `linkedin` counts every run whose [start, end] window contains the probe's `at` —
    the same interval-containment idea `covered_through()` uses, applied to run duration
    instead of mailbox coverage."""
    starts, ends = {}, {}
    for r in recs:
        if r.get("event") == "start":
            starts[r.get("run_id")] = r.get("at")
        elif r.get("event") == "end":
            ends[r.get("run_id")] = r.get("at")
    linkedin_run_ids = {r.get("run_id") for r in recs
                        if r.get("event") == "gap"
                        and str(r.get("scope") or "").startswith("linkedin:")}
    # design-script-first.md §2 — a `pass … phase returned` row carries its own `run_id`
    # directly (unlike a `probe`, which is pointwise): a second, free correlation once the
    # `pass` event exists, no new query needed.
    linkedin_run_ids |= {r.get("run_id") for r in recs
                        if r.get("event") == "pass" and r.get("kind") == "linkedin"
                        and r.get("phase") == "returned"}
    probe_ats = [d for d in (_parse_iso(r.get("at")) for r in recs
                            if r.get("event") == "probe" and r.get("medium") == "linkedin")
                if d is not None]
    out = []
    for rid, s in starts.items():
        e = ends.get(rid)
        if not e:
            continue
        sd, ed = _parse_iso(s), _parse_iso(e)
        if sd is None or ed is None:
            continue
        carries = rid in linkedin_run_ids or any(sd <= p <= ed for p in probe_ats)
        if not carries:
            continue
        out.append({"run_id": rid, "minutes": round((ed - sd).total_seconds() / 60.0, 1),
                    "start": s, "end": e})
    return sorted(out, key=lambda d: -d["minutes"])


def _parse_transcript_ts(raw):
    """A transcript record's own `timestamp`, which — unlike every `at` this journal writes
    itself (always `now_iso()`, naive local time) — may carry a trailing 'Z' (UTC) that
    `datetime.fromisoformat` only accepts from Python 3.11 (this file targets 3.9+). Stripped to
    a naive datetime for comparison against a run's `start.at`: an approximation when the two
    clocks disagree (local vs UTC), stated rather than silently assumed exact — the fold's own
    idempotence (keyed on `agent_id`, not on this filter) is what keeps a borderline miss from
    ever duplicating a row, so an imprecise boundary here costs at most one late fold, never a
    wrong one."""
    if not raw:
        return None
    s = str(raw)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = _parse_iso(s)
    if dt is not None and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _is_agent_result(rec):
    """Duck-typed on the §8.1 measurement (`deployment-auditor`, #82): a transcript record whose
    `toolUseResult` carries `agentId` is an `Agent`/`Task` dispatch's return — no other tool's
    `toolUseResult` shape carries that key. Never assumes a chain-walk to the originating
    `tool_use`'s `name`; the key itself is the signal that was actually measured."""
    tur = rec.get("toolUseResult")
    return isinstance(tur, dict) and bool(tur.get("agentId"))


def _hand_back_text(tur):
    """(text, source) — the hand-back to read `outcome`'s first word from. `content` first (§8.1:
    populated in 53 of 349 measured results); else the first line of `outputFile`, opened only
    when `canReadOutputFile` (#82: `content` is `None` in 296 of 349 — the common case). `(None,
    "none")` when neither is available — never a guess."""
    content = tur.get("content")
    if content:
        if isinstance(content, str):
            return content, "content"
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("text")]
            if texts:
                return " ".join(texts), "content"
        return str(content), "content"
    output_file = tur.get("outputFile")
    if output_file and tur.get("canReadOutputFile"):
        try:
            with open(output_file, encoding="utf-8") as fh:
                return fh.read(), "outputFile"
        except OSError:
            return None, "outputFile-unreadable"
    return None, "none"


def _outcome_from_text(text):
    word = (text or "").strip().split()[0] if text and text.strip() else ""
    key = re.sub(r"[^A-Za-z]", "", word).lower()
    if not key:
        return "unknown"
    return OUTCOME_MAP.get(key, key)


def _fields_from_agent_result(rec):
    """(fields, refusal_reason) — `fields` is the writer-ready dict (minus `event`/`run_id`/
    `at`) for ONE `Agent` toolUseResult, or `None` with a reason when a required §8.1 field is
    missing: 'refused loudly' rather than silently defaulted, so a malformed result never reads
    as a free, zero-cost dispatch."""
    tur = rec.get("toolUseResult") or {}
    agent_id = tur.get("agentId")
    agent = tur.get("agentType")
    tokens = tur.get("totalTokens")
    tool_uses = tur.get("totalToolUseCount")
    duration_ms = tur.get("totalDurationMs")
    missing = [k for k, v in (("agentId", agent_id), ("agentType", agent),
                              ("totalTokens", tokens), ("totalToolUseCount", tool_uses),
                              ("totalDurationMs", duration_ms)) if v is None]
    if missing:
        return None, "missing %s" % ", ".join(missing)
    text, _source = _hand_back_text(tur)
    prompt = tur.get("prompt") or ""
    for_ = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
    return {"agent": agent, "agent_id": agent_id, "model": tur.get("resolvedModel") or "",
           "tokens": int(tokens), "tool_uses": int(tool_uses),
           "duration_s": int(round(duration_ms / 1000.0)), "outcome": _outcome_from_text(text),
           "for": for_}, None


def fold_dispatches(root, run_id, transcript_path=None, at=None):
    """design-script-first.md §8.2 (public #82/#90/#91) — the PROVEN path (the `PostToolUse`
    hook is the unverified primary and is not built by this function). Resolves the transcript
    from `transcript_path` when given (tests), else this session's stash
    (`_root.transcript_stash_path()`); a surface with neither prints `no transcript on this
    surface` and writes nothing — never a false zero read as fact. Every `Agent` result strictly
    newer than the run's own `--start` is a candidate; idempotent on `agent_id`, so a second fold
    over the same transcript adds nothing. Returns (written, skipped, refused) — `refused`
    entries are printed loudly to stderr, one per malformed result, and never silently dropped."""
    recs = read(root)
    start_rec = next((r for r in recs if r.get("event") == "start" and r.get("run_id") == run_id),
                     None)
    if start_rec is None:
        raise JournalError("--fold-dispatches --run %r: no matching --start run — get one from "
                           "--start" % run_id)
    start_dt = _parse_iso(start_rec.get("at"))

    if transcript_path is None:
        try:
            with open(transcript_stash_path(), encoding="utf-8") as fh:
                transcript_path = fh.read().strip() or None
        except OSError:
            transcript_path = None
    if not transcript_path:
        print("no transcript on this surface")
        return 0, 0, []
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        print("no transcript on this surface (%s)" % e)
        return 0, 0, []

    already = {r.get("agent_id") for r in recs if r.get("event") == "dispatch"}
    written, skipped, refused = 0, 0, []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or not _is_agent_result(rec):
            continue
        ts = _parse_transcript_ts(rec.get("timestamp"))
        if ts is None or (start_dt is not None and ts < start_dt):
            continue
        fields, reason = _fields_from_agent_result(rec)
        if fields is None:
            hint = (rec.get("toolUseResult") or {}).get("agentId") or "?"
            print("⛔ dispatch fold: result %s refused — %s" % (hint, reason), file=sys.stderr)
            refused.append(hint)
            continue
        if fields["agent_id"] in already:
            skipped += 1
            continue
        record_dispatch(root, run_id=run_id, agent=fields["agent"],
                        agent_id=fields["agent_id"], model=fields["model"],
                        tokens=fields["tokens"], tool_uses=fields["tool_uses"],
                        duration_s=fields["duration_s"], outcome=fields["outcome"],
                        for_=fields["for"], at=at or now_iso())
        already.add(fields["agent_id"])
        written += 1
    print("folded %d dispatch row(s) for %s (%d already recorded, %d refused)"
         % (written, run_id, skipped, len(refused)))
    return written, skipped, refused


def _percentile(sorted_vals, p):
    """Linear-interpolation percentile over an already-sorted, non-empty list — copied from
    `scripts/dispatch_ledger.py` (the MAINTENANCE ledger, at the marketplace repo root): that
    module is never importable from a SHIPPED file, so the shape is duplicated, not shared, the
    same reasoning `TRIAGE_TTL_DAYS`'s own docstring already states for `mail_client.py`."""
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    k = (p / 100.0) * (n - 1)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return float(sorted_vals[f])
    d = k - f
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * d


def cmd_calibrate_dispatches(root):
    rows = dispatch_rows(read(root))
    print("DISPATCH --calibrate (per agent — token/tool_use quantiles, no recommendation)")
    if not rows:
        print("  no dispatch rows yet.")
        return 0
    by_agent = {}
    for r in rows:
        by_agent.setdefault(r.get("agent"), {"tokens": [], "tool_uses": []})
        by_agent[r.get("agent")]["tokens"].append(r.get("tokens", 0))
        by_agent[r.get("agent")]["tool_uses"].append(r.get("tool_uses", 0))
    for agent in sorted(by_agent):
        toks = sorted(by_agent[agent]["tokens"])
        tus = sorted(by_agent[agent]["tool_uses"])
        print("  %-24s n=%-4d tool_uses min=%-5d p50=%-7.1f p90=%-7.1f max=%-5d  "
             "tokens min=%-8d p50=%-9.1f p90=%-9.1f max=%-8d"
             % (agent, len(toks), tus[0], _percentile(tus, 50), _percentile(tus, 90), tus[-1],
                toks[0], _percentile(toks, 50), _percentile(toks, 90), toks[-1]))
    return 0


def cmd_dispatches(root, today_only=False, calibrate=False):
    rows = dispatch_rows(read(root), today_only=today_only)
    print("DISPATCHES%s" % (" (today)" if today_only else ""))
    if not rows:
        print("  none.")
    else:
        for r in sorted(rows, key=lambda r: r.get("at", "")):
            print("  %-19s %-22s run=%-26s tokens=%-7d tool_uses=%-4d %-8s for=%s"
                 % (str(r.get("at", ""))[:19], r.get("agent"), r.get("run_id"),
                    r.get("tokens", 0), r.get("tool_uses", 0), r.get("outcome"),
                    r.get("for") or "-"))
        by_agent, by_run = {}, {}
        for r in rows:
            a = by_agent.setdefault(r.get("agent"), [0, 0])
            a[0] += r.get("tokens", 0)
            a[1] += r.get("tool_uses", 0)
            rn = by_run.setdefault(r.get("run_id"), [0, 0])
            rn[0] += r.get("tokens", 0)
            rn[1] += r.get("tool_uses", 0)
        print("  by agent:")
        for a in sorted(by_agent):
            print("    %-24s tokens=%-8d tool_uses=%-5d" % (a, by_agent[a][0], by_agent[a][1]))
        print("  by run:")
        for rn in sorted(by_run):
            print("    %-24s tokens=%-8d tool_uses=%-5d" % (rn, by_run[rn][0], by_run[rn][1]))
    if calibrate:
        print()
        cmd_calibrate_dispatches(root)
    return 0


def cmd_passes(root, today_only=False):
    """design-script-first.md §2 — every `pass` row, oldest first, plus the crashed-pass line
    (a `dispatched` row in an ended run with no matching `returned`). `0 passes` on an empty
    journal, exit 0 either way — this is a report, never a gate."""
    recs = read(root)
    rows = pass_rows(recs, today_only=today_only)
    label = "%d passes%s" % (len(rows), " today" if today_only else "")
    print(label if rows else "0 passes")
    for r in sorted(rows, key=lambda r: r.get("at", "")):
        bits = "%-19s %-8s %-10s run=%s" % (str(r.get("at", ""))[:19], r.get("kind"),
                                            r.get("phase"), r.get("run_id"))
        if r.get("phase") == "returned":
            bits += (" reached=%s unreachable=%s not_attempted=%s"
                    % (",".join(r.get("reached") or []) or "-",
                       ",".join(r.get("unreachable") or []) or "-",
                       ",".join(r.get("not_attempted") or []) or "-"))
            if r.get("jobsearch"):
                bits += " jobsearch=%s" % r["jobsearch"]
        elif r.get("phase") == "refused":
            bits += " reason=%s" % (r.get("reason") or "-")
        elif r.get("phase") == "recorded":
            # dev #812 / public #169 -- how `linkedin_sweep.py record` judged the hand-back
            bits += (" verdict=%s faults=%s concluded=%s not_concluded=%s kept=%s"
                    % (r.get("verdict"), r.get("faults"), r.get("concluded"),
                       r.get("not_concluded"), r.get("kept") or "-"))
            # dev #826 / public #177 -- the pane account (0.83.0). A row written before it carries none of the three
            # fields and prints exactly as it did; one that carries them says the pane, the mode and any partial surfaces.
            if r.get("pane") is not None:
                part = r.get("partial") if isinstance(r.get("partial"), list) else []
                bits += " pane=%s mode=%s partial=%s" % (r.get("pane"), r.get("mode"),
                                                         ",".join(str(t) for t in part) or "-")
                if part:
                    bits += " PARTIAL"
        elif r.get("phase") == "dispatched" and r.get("channels"):
            bits += " channels=%s" % ",".join(r["channels"])
        elif r.get("phase") == "done":
            bits += " unreached=%s" % (",".join(r.get("unreached") or []) or "-")
        if r.get("ids"):
            bits += " ids=%s" % ",".join(r["ids"])
        print("  %s" % bits)
    crashed = crashed_passes(recs)
    if crashed:
        print("  pass dispatched, never returned (%s)" % ", ".join(crashed))
    return 0
