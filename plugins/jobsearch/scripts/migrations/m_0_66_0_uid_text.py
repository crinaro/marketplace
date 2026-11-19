"""Migration 0.66.0: `m_0_66_0_uid_text()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import re
import shutil
from migrations.paths import HERE
from migrations.support_uid import _uid_text_read
from migrations.support_validate import _shadow_validate

VERSION = "0.66.0"


# ⭐⭐ KEYED "0.66.0" -- 0.65.0 is the newest jobsearch release at the branch base (plugin.json read
# 0.65.0 on base 8ab4ae8; the release_log's last row is jobsearch 0.65.0). A profile that installed
# 0.65.0 is stamped exactly "0.65.0", and pending_for()'s strict `<` fires a migration keyed to
# "0.66.0". Re-verify when 0.66.0 is actually cut (dev #704 / public #154).
UID_TEXT_SUFFIX = ".pre-0.66.0"
# the stores the migration reads and may rewrite through plain files; briefs go ONLY through brief.py
_UID_TEXT_STORES = ("messages", "asks", "touches", "commitments", "applications")
# a wrapped uid INSIDE a mail tag: `gmail:acct:b'101'` -> `gmail:acct:101` (the same grammar the
# validator's `source_tag.wrapped` declares)
_UID_WRAPPED_TAG_RE = re.compile(r"((?:gmail|mail|ats):[^:\s|]+:)b'(\d+)'")
# the completion marks `reconcile.py --ats` reads back as KEYS: `reconcile-ats <message id>; was ...`
# and `reconcile-ats-conflict <message id>` (dev #704 R1: keys, not prose)
_UID_MARK_RE = re.compile(r"(reconcile-ats(?:-conflict)?[ \t]+)([^\s;|]+)")
# (store, field, required trigger_kind) -- the fields that hold a message id and are rewritten through
# the old-to-new id map (design 4.3). A `trigger_ref` is a message id only when its kind is `reply`.
_UID_REF_FIELDS = (("messages", "answers", None), ("touches", "message_ref", None),
                   ("touches", "trigger_ref", "reply"), ("asks", "trigger_ref", "reply"))
# the three relation fields move as one group (`answers` and `resolves`/`resolved_by` are exclusive)
_UID_RELATION_FIELDS = ("answers", "resolves", "resolved_by")


def _uid_text_fix(s):
    return _UID_WRAPPED_TAG_RE.sub(r"\1\2", s)


def _uid_text_fix_value(value):
    """`value` with every wrapped mail tag in every string repaired (dicts and lists recursed)."""
    if isinstance(value, str):
        return _uid_text_fix(value)
    if isinstance(value, dict):
        return {k: _uid_text_fix_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_uid_text_fix_value(v) for v in value]
    return value


def _uid_text_merge(group, key, report):
    """One surviving row from `group` (rows sharing the normalized source `key`, in file order),
    and the ids of the rows merged away. The rule is OURS (design 4.4, no external source read):

      * the survivor is the row whose stored `source` was already clean (its id is the one a future
        re-sweep mints); if more than one was, or none was, the first in file order;
      * every non-null survivor value is kept; a null or absent one takes the dropped row's value;
        a field non-null on both that differs keeps the survivor's, and the conflict is REPORTED
        (nothing is lost: the dropped row is in `messages.jsonl.pre-0.66.0`);
      * `answers`, `resolves`, `resolved_by` move as a GROUP, only when the survivor has none of
        the three (`answers` and `resolves` can never both be set)."""
    clean = [m for m in group if m.get("source") == key]
    survivor = clean[0] if clean else group[0]
    merged = dict(survivor)
    dropped = [m for m in group if m is not survivor]
    for d in dropped:
        for k, v in d.items():
            if k in ("id", "source") or k in _UID_RELATION_FIELDS:
                continue
            sv = merged.get(k)
            if sv in (None, ""):
                if v not in (None, ""):
                    merged[k] = v
            elif v not in (None, "") and v != sv:
                report.append("    conflict on %s in %s (kept %r; %s had %r)"
                              % (k, survivor.get("id"), sv, d.get("id"), v))
        if (all(merged.get(k) in (None, "") for k in _UID_RELATION_FIELDS)
                and any(d.get(k) not in (None, "") for k in _UID_RELATION_FIELDS)):
            for k in _UID_RELATION_FIELDS:
                if k in d:
                    merged[k] = d[k]
    return merged, [d.get("id") for d in dropped], survivor


def _uid_text_plan(spec, data, _vd):
    """The whole change, computed in memory from `data` ({store: rows}) and written nowhere:
    `(new, id_map, report)` where `new` is `{store: [(row, raw_or_None)]}` (`raw` is the original
    line for a row that did not change, so an unchanged row is rewritten byte for byte),
    `id_map` is `{merged-away message id: survivor id}`, and `report` is the lines to print."""
    report, id_map = [], {}
    declared = {}
    for store, field, mode in spec["declared"]:
        declared.setdefault(store, {})[field] = mode

    # 1. merge messages that share a normalized mail source key
    msgs = data["messages"]
    groups, order = {}, []
    for m in msgs:
        src = m.get("source")
        if _vd.is_mail_tag(src):
            k = _vd.normalize_source_tag(src)
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(m)
    replaced = {}                       # id(original row) -> merged row
    gone = set()                        # id(original row) merged away
    for k in order:
        g = groups[k]
        if len(g) < 2:
            continue
        before = len(report)
        merged, dropped_ids, survivor = _uid_text_merge(g, k, report)
        replaced[id(survivor)] = merged
        for m in g:
            if m is not survivor:
                gone.add(id(m))
        for did in dropped_ids:
            id_map[did] = merged.get("id")
        report.insert(before, "  merged %d message rows sharing source %s into %s (dropped %s)"
                      % (len(g), k, merged.get("id"), ", ".join(map(str, dropped_ids))))

    def fix_row(store, row):
        """The declared-field repairs for one row: `whole` -> normalized tag, `embedded` -> wrapped
        tags repaired in every nested string."""
        out = dict(row)
        for field, mode in declared.get(store, {}).items():
            if field not in out:
                continue
            if mode == "whole":
                out[field] = _vd.normalize_source_tag(out[field])
            else:
                out[field] = _uid_text_fix_value(out[field])
        return out

    def ref_fix(store, row):
        out = dict(row)
        for s, field, kind in _UID_REF_FIELDS:
            if s != store or field not in out:
                continue
            if kind is not None and out.get("trigger_kind") != kind:
                continue
            if isinstance(out[field], str) and out[field] in id_map:
                out[field] = id_map[out[field]]
        return out

    def mark_fix(store, row):
        if store not in ("applications", "asks") or not isinstance(row.get("note"), str):
            return row
        new = _UID_MARK_RE.sub(lambda m: m.group(1) + id_map.get(m.group(2), m.group(2)),
                               row["note"])
        if new == row["note"]:
            return row
        out = dict(row)
        out["note"] = new
        return out

    new = {}
    for store in _UID_TEXT_STORES:
        rows, raws = data[store], data[store + "#raw"]
        out = []
        for orig, raw in zip(rows, raws):
            if store == "messages" and id(orig) in gone:
                continue
            merged = replaced.get(id(orig)) if store == "messages" else None
            cand = mark_fix(store, ref_fix(store, fix_row(
                store, merged if merged is not None else orig)))
            if store == "messages" and cand.get("answers") is not None \
                    and cand.get("answers") == cand.get("id"):
                report.append("  %s: answers named itself after the merge -- cleared"
                              % cand.get("id"))
                cand = dict(cand)
                cand["answers"] = None
            out.append((orig, raw) if merged is None and cand == orig else (cand, None))
        new[store] = out
    return new, id_map, report


def _uid_text_state(profile, model, spec, id_map, _vd, _brief):
    """The 0.66.0 SUCCESS CONDITION, queried from DISK (never assumed from what was just written):
    `(failures, stats, resolved)` -- `failures` is a list of the clauses that do not hold, `stats` is
    the validator's `(stores, fields, rows)` coverage, `resolved` the set of (store, key, field) refs
    that resolve to a stored message right now."""
    failures, data = [], {}
    for store in _UID_TEXT_STORES:
        rows, _raws, err = _uid_text_read(profile, store)
        if err:
            return ["%s cannot be re-read: %s" % (store, err)], None, set()
        data[store] = rows

    def loader(name):
        store = name[:-len(".jsonl")]
        if store == "briefs":
            try:
                return _brief.read_ledger_strict(profile), []
            except _brief.BriefError as exc:
                return None, [str(exc)]
        path = os.path.join(profile, "data", name)
        if not os.path.exists(path):
            return None, []
        if store not in data:
            rows, _r, err = _uid_text_read(profile, store)
            return rows, ([err] if err else [])
        return data[store], []

    problems = []
    stats = _vd.check_source_tags(model, problems, loader=loader)
    if stats is None or problems:
        failures.append("(a) a declared field still fails its source-tag mode: %s"
                        % ("; ".join(problems[:3]) or "the rule could not run"))
    seen, dup = {}, []
    for m in data["messages"]:
        if _vd.is_mail_tag(m.get("source")):
            k = _vd.normalize_source_tag(m["source"])
            if k in seen:
                dup.append(k)
            seen[k] = m.get("id")
    if dup:
        failures.append("(b) %d message source key(s) are still shared by two rows: %s"
                        % (len(dup), ", ".join(sorted(set(dup))[:3])))
    message_ids = {m.get("id") for m in data["messages"]}
    dangling = []
    resolved = _uid_text_resolved(data)
    for s, field, kind in _UID_REF_FIELDS:
        for i, row in enumerate(data[s]):
            v = row.get(field)
            if isinstance(v, str) and v in id_map \
                    and (kind is None or row.get("trigger_kind") == kind):
                dangling.append("%s[%s].%s -> %s" % (s, row.get("id", i), field, v))
    for s in ("applications", "asks"):
        for i, row in enumerate(data[s]):
            for m in _UID_MARK_RE.finditer(row.get("note") or ""):
                if m.group(2) in id_map:
                    dangling.append("%s[%s].note mark -> %s" % (s, row.get("id", i), m.group(2)))
    try:
        n_left, _p = _brief.remap_message_refs(profile, id_map, _uid_text_fix, apply_it=False)
        for rid, f, mid in _brief.ledger_message_ids(profile):
            if mid in message_ids:
                resolved.add(("briefs", rid, f))
    except _brief.BriefError as exc:
        return ["briefs cannot be re-read: %s" % exc], stats, set()
    if n_left:
        dangling.append("%d brief row(s) still cite a merged-away message or carry a wrapped tag"
                        % n_left)
    if dangling:
        failures.append("(c) a reference still names a merged-away message id: %s"
                        % "; ".join(dangling[:3]))
    return failures, stats, resolved


def m_0_66_0_uid_text(profile, apply_it, _inject_fault=None):
    """0.66.0 -- an IMAP uid is TEXT, and a mail tag has one shape (dev #704 / public #154).

    Before 0.66.0 `mail_client.Mailbox.search()` handed callers `bytes`, and every `"%s:%s:%s"` that
    built a source tag wrote the repr: `gmail:acct:b'101'` beside the clean `gmail:acct:101` the same
    message gets on a later sweep. The two keys named one message, so a "do I already hold it?"
    check that compared them raw said no and wrote the message twice. S1 fixes the writer, D1 makes
    every reader compare one normalized key, V1 refuses the wrapped shape in a store; this repairs
    the stores already written.

    WHAT IT DOES, in this order:

      1. read every store strictly (a line that does not parse is PENDING, naming the store and line,
         before anything is written);
      2. plan the change in memory: every `whole` field normalized, every wrapped tag inside an
         `embedded` field repaired, messages that share a normalized mail source MERGED into one row
         (the rule is `_uid_text_merge`'s), and every reference to a merged-away row rewritten;
      3. an empty plan is DONE and writes nothing -- not even a preserved copy -- which is what makes a
         second run change nothing;
      4. validate the migrated shape against a throwaway shadow (a genuinely NEW validation problem
         refuses the whole migration; nothing is written);
      5. PRESERVE: copy each store the plan changes to `data/<store>.jsonl.pre-0.66.0`, never
         overwriting a copy already there (it is the true original from an earlier partial run);
      6. TRANSFORM: briefs (through `brief.remap_message_refs` ONLY -- `check_ledger_reads.py` lets no
         other script open the ledger), then touches, asks, applications, commitments, and the
         messages store LAST, so a run that dies midway leaves every reference resolving;
      7. re-read the success condition from disk (`_uid_text_state`): (a) no declared field fails its
         source-tag mode, (b) no two message rows share a normalized mail source, (c) no reference
         or completion mark still names a merged-away id, (d) every reference that resolved before
         still resolves. Any shortfall returns PENDING with the failing clause; the preserved copies
         stay.

    ⭐ IDS ARE OPAQUE (owner decision R1, 2026-10-13). A message row that is not merged away keeps its
    id, even when the id embeds a wrapped uid or hashes the old source; nothing is re-minted, and the
    source check in `record.append_message` already stops a clean write from duplicating it. Only a
    merged-away row's id is mapped (to the survivor's), and the map rewrites `messages.answers`,
    `touches.message_ref`, `touches.trigger_ref` and `asks.trigger_ref` (kind `reply`), the briefs
    ledger, and the `reconcile-ats <id>` / `reconcile-ats-conflict <id>` completion marks in
    `applications.note` and `asks.note` -- marks are KEYS that `reconcile.py --ats` reads back, so
    an unmapped one would apply the same message a second time. Other prose mentions of an id stay.

    ⭐ PENDING WHEN IT CANNOT KNOW (R3). The shipped `docs/data_model.json` must carry a usable
    `source_tag` block; absent, malformed or declaring zero fields it returns PENDING, never a quiet
    done. The report always prints `N stores, M fields, K rows checked`.

    ⚠️ ROLLBACK RISK. Downgrading to 0.65.x after this runs brings the wrapped writer back WITHOUT the
    normalizing readers: the 0.65 harvest compares a fresh `gmail:a:b'101'` with a stored clean
    `gmail:a:101`, misses, and re-harvests every message it can still find -- duplicates of the very
    kind this removes. Restoring the `.pre-0.66.0` copies undoes the migration only when ALL of them
    are restored together (`briefs.jsonl.pre-0.66.0` included): one store alone leaves references to
    ids that no longer exist, and every row written since is lost on restore. No down-migration is
    built and none is asked for; the copies, the printed id map and an idempotent re-run are the
    mitigation."""
    import validate_data as _vd
    import brief as _brief

    try:
        with open(os.path.join(os.path.dirname(HERE), "docs", "data_model.json"),
                  encoding="utf-8") as fh:
            model = json.load(fh)
    except (OSError, ValueError) as exc:
        return False, ("  ⏳ 0.66.0 PENDING -- docs/data_model.json cannot be read (%s), so the "
                       "source-tag rule cannot run. Nothing was changed." % exc)
    spec, defects = _vd.source_tag_spec(model)
    if spec is None:
        return False, ("  ⏳ 0.66.0 PENDING -- the shipped docs/data_model.json `source_tag` block "
                       "is unusable (%s), so this migration cannot know what to repair or check. "
                       "Nothing was changed." % "; ".join(defects))

    data = {}
    for store in _UID_TEXT_STORES:
        rows, raws, err = _uid_text_read(profile, store)
        if err:
            return False, ("  ⏳ 0.66.0 PENDING -- %s. Nothing was written: preserving and then "
                           "rewriting a store this could not fully read would drop that line. Fix "
                           "it and this runs again next session." % err)
        data[store], data[store + "#raw"] = rows, raws
    try:
        _brief.read_ledger_strict(profile)
    except _brief.BriefError as exc:
        return False, ("  ⏳ 0.66.0 PENDING -- %s. Nothing was written." % exc)

    before_resolved = _uid_text_resolved(data)
    message_ids_before = {m.get("id") for m in data["messages"]}
    before_resolved |= {("briefs", rid, f) for rid, f, mid in _brief.ledger_message_ids(profile)
                        if mid in message_ids_before}
    new, id_map, report = _uid_text_plan(spec, data, _vd)
    # a merged-away row's OWN references leave with it; they are not 'no longer resolving'
    before_resolved = {r for r in before_resolved if not (r[0] == "messages" and r[1] in id_map)}
    changed = [s for s in _UID_TEXT_STORES
               if [r for r, _raw in new[s]] != data[s]]
    try:
        briefs_to_change, _p = _brief.remap_message_refs(profile, id_map, _uid_text_fix,
                                                          apply_it=False)
    except _brief.BriefError as exc:
        return False, "  ⏳ 0.66.0 PENDING -- %s. Nothing was written." % exc
    if briefs_to_change:
        changed.append("briefs")
    if not changed:
        return True, ""

    summary = ("%d store(s) to repair (%s); %d message row(s) merged away"
               % (len(changed), ", ".join(changed), len(id_map)))
    if not apply_it:
        return True, "  would repair (0.66.0) wrapped mail tags: %s" % summary

    overrides = {"%s.jsonl" % s: [r for r, _raw in new[s]] for s in changed if s != "briefs"}
    rc, problems, fresh = _shadow_validate(profile, overrides)
    if fresh is None or fresh:
        detail = "; ".join((fresh if fresh else (problems or []))[:8]) or (
            "validator exited %d with no problem list -- it crashed" % rc)
        return False, ("  ⚠️ 0.66.0 REFUSED -- the repaired shape introduces a new validation "
                       "problem, so NOTHING was written (the real profile is untouched): %s"
                       % detail)

    # PRESERVE every store this will change, before the first write
    lines, kept = [], []
    for s in changed:
        if s == "briefs":
            continue
        path = os.path.join(profile, "data", "%s.jsonl" % s)
        copy = path + UID_TEXT_SUFFIX
        if os.path.exists(copy):
            kept.append(s)
            continue
        try:
            shutil.copy2(path, copy)
        except (OSError, shutil.Error) as exc:
            return False, ("  ⚠️ 0.66.0 PENDING -- %s.jsonl could not be preserved to %s%s (%s), so "
                           "nothing was changed." % (s, s + ".jsonl", UID_TEXT_SUFFIX, exc))
    if kept:
        lines.append("  kept the existing %s copy of %s (it is the true original from an earlier "
                     "partial run)" % (UID_TEXT_SUFFIX, ", ".join(kept)))

    # TRANSFORM -- briefs first, messages LAST (a run that dies midway leaves every reference
    # resolving: the merged-away row still exists until the final write)
    import _atomic
    if "briefs" in changed:
        try:
            n, _copy = _brief.remap_message_refs(profile, id_map, _uid_text_fix,
                                                 preserve_suffix=UID_TEXT_SUFFIX)
        except Exception as exc:                                  # noqa: BLE001
            return False, ("  ⚠️ 0.66.0 PENDING -- the briefs ledger could not be rewritten (%s: %s); "
                           "offered again next session." % (type(exc).__name__, exc))
        lines.append("  rewrote %d brief row(s) citing a merged-away message" % n)
    order = [s for s in ("touches", "asks", "applications", "commitments", "messages")
             if s in changed]
    for s in order:
        if _inject_fault == "skip_%s" % s:
            continue                 # TEST-ONLY: this store's write never happens
        text = "".join((raw if raw is not None else json.dumps(r, ensure_ascii=False)) + "\n"
                       for r, raw in new[s])
        _atomic.write_text(os.path.join(profile, "data", "%s.jsonl" % s), text)

    failures, stats, _resolved = _uid_text_state(profile, model, spec, id_map, _vd, _brief)
    after_missing = [r for r in before_resolved if r not in _resolved]
    if not failures and after_missing:
        failures.append("(d) %d reference(s) that resolved before no longer do: %s"
                        % (len(after_missing), ", ".join("%s[%s].%s" % r for r in after_missing[:3])))
    lines.insert(0, "  repaired wrapped mail tags (0.66.0) -- %s" % summary)
    lines.extend(report)
    if id_map:
        lines.append("  id map (merged-away -> survivor): %s"
                     % ", ".join("%s -> %s" % kv for kv in sorted(id_map.items())))
    if stats is not None:
        lines.append("  source tags: %d stores, %d fields, %d rows checked" % stats)
    if failures:
        return False, "\n".join(
            lines + ["  ⏳ 0.66.0 PENDING -- the success condition does not hold:"]
            + ["    " + f for f in failures]
            + ["  The preserved %s copies stay; this is offered again next session." % UID_TEXT_SUFFIX])
    return True, "\n".join(lines)


def _uid_text_resolved(data):
    """The `(store, row id, field)` references that resolve to a stored message in `data`
    ({store: rows}). ONE function for the before and the after side, so the keys cannot disagree;
    a row is keyed by its id (a merged-away message row is not an index that survives)."""
    message_ids = {m.get("id") for m in data["messages"]}
    out = set()
    for s, field, kind in _UID_REF_FIELDS:
        for i, row in enumerate(data[s]):
            v = row.get(field)
            if isinstance(v, str) and v in message_ids and \
                    (kind is None or row.get("trigger_kind") == kind):
                out.add((s, row.get("id", i), field))
    return out
