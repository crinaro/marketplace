"""Migration 0.76.0: `m_0_76_0_source_adoption()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_adoption import _adoption_replace_lines
from migrations.support_uid import _uid_text_read

VERSION = "0.76.0"


# ---- 0.76.0 (dev #774; design-source-catalog.md section 5, with review B3 and B4): adopt the hand-made rows the plugin
# itself once told users to paste -----------------------------------------------------------------------------------
#
# WHY A MIGRATION NOW. Stamping an existing row changes what it MEANS: it starts receiving catalog updates. That is the
# shape CLAUDE.md says ships as a version, not as an instruction, and it is why the boards-only build (which stamped
# nothing on its own) needed none. KEYED "0.76.0": 0.75.0 is the newest PUBLISHED release (a profile that installed it is
# stamped exactly "0.75.0", and strict `<` would never fire a migration keyed to it). It runs LAST.
#
# WHAT IT DOES, in the order it does it:
#   1. READS STRICTLY. `channels.jsonl`, `companies.jsonl` and `asks.jsonl` are read with `_uid_text_read`: ONE line that
#      does not parse is PENDING (nothing written), because rewriting a store this could not fully read would drop that
#      line. The catalog is read with `channel_catalog.load_catalog`; one that cannot be read is PENDING too. An absent
#      store reads as no rows (an honest zero, after a successful strict read).
#   2. PRESERVES FIRST. Before the first write `channels.jsonl` is copied byte for byte to `channels.jsonl.pre-0.76.0`,
#      never over a copy already there (that is the true original of an earlier partial run).
#   3. MATCHES (`channel_catalog.adoption_plan`). Only UNSTAMPED rows of type job-board / aggregator / alert-email are
#      considered, and only against `curated` / `portfolio` entries. EXACT = the row's id equals the entry's channel_id
#      and its match projection equals the projection EMBEDDED in one of the entry's `shipped_templates` (B3: the
#      installed copy has no git history, so it never looks at git; `check_channel_catalog.py` G11 recomputes the
#      embedded value from the tagged text at release). An exact row is STAMPED with the template's sha and
#      `ADOPTED_REV`; no other field is touched, and a retired row stays retired. A NEAR row (same id, or overlapping
#      board_hosts, with a projection no template carries) gets ONE ask `source-adopt:<channel_id>` and is not written.
#      Anything else is untouched and unasked. Swept boards and alert senders never had a template, so a hand row for
#      Indeed, Dice or the LinkedIn job search is never adopted and never asked: it works without a stamp.
#   4. VERIFIES FROM DISK. Every stamped row passes the stamp and field validators and still equals the template it was
#      stamped against; every other row is byte-identical; every ask exists exactly once. ANY SHORTFALL restores the
#      stores and returns PENDING (B4).
#   5. B4 -- WHAT A ROLLBACK PUTS BACK. Only the bytes THIS RUN read just before its own write (an in-memory snapshot),
#      never `channels.jsonl.pre-0.76.0`: that copy is the original of the FIRST run, so restoring it after a user edit
#      between two shortfalls would erase the edit. (A shortfall, an edit, a shortfall again leaves the edit.)
#   6. NEVER TURNS A SOURCE ON OR OFF. No row changes `relationship_status`, no row is created, and
#      `sourcing.feeds.enabled` is not written (absent keeps 0.72.0's behaviour).
#
# IDEMPOTENT: a stamped row is no longer unstamped and an existing ask (open or resolved) is never rewritten, so a second
# run finds nothing to do. ROLLBACK RISK: an engine older than 0.76.0 does not know the stamp on a row it adopted (the
# stamp fields are declared since 0.75.x's data model, so the older validator accepts them); restoring
# channels.jsonl.pre-0.76.0 undoes the adoption only for rows not edited since.
ADOPTION_PRE_COPY = "pre-0.76.0"
_adoption_fault = None            # TEST SEAM (in the family of `_inject_fault`): "shortfall" forces the verify step to fail


def m_0_76_0_source_adoption(profile, apply_it):
    """0.76.0 -- stamp the hand-made rows that exactly match a template the plugin once shipped, and ask about the near
    matches (see the block above). Returns (done, message); PENDING (False) whenever it cannot know or cannot verify."""
    import datetime
    import channel_catalog as cc
    import _atomic
    import validate_data as _vd
    pending = "  ⏳ 0.76.0 PENDING -- %s. Nothing was written."
    channels, ch_raws, err = _uid_text_read(profile, "channels")
    companies, _craws, err2 = _uid_text_read(profile, "companies")
    asks, _araws, err3 = _uid_text_read(profile, "asks")
    err = err or err2 or err3
    if err:
        return False, pending % ("%s. Fix it and this runs again next session: rewriting a store this could not fully read "
                                 "would drop that line" % err)
    try:
        catalog = cc.load_catalog()
    except cc.CatalogError as e:
        return False, pending % ("the source catalog cannot be read (%s); it is tried again next session" % e)
    plan = cc.adoption_plan(channels, catalog)
    exact = [p for p in plan if p["status"] == "exact"]
    exact_ids = {p["channel_id"] for p in exact}
    near, seen_near = [], set()
    for p in plan:                                  # ONE question per row: a row near two entries is asked about the first
        if p["status"] == "near" and p["channel_id"] not in exact_ids and p["channel_id"] not in seen_near:
            seen_near.add(p["channel_id"])
            near.append(p)
    entries = cc.by_id(catalog)
    ask_ids = {a.get("id") for a in asks}
    new_asks = [p for p in near if cc.ADOPT_ASK_PREFIX + p["channel_id"] not in ask_ids]
    if not exact and not new_asks:
        return True, "  ✅ sources (0.76.0) -- adopted 0, asked 0 (no hand-made row exactly matches a shipped template; %d catalog question%s already on file)" % (
            len(near), "" if len(near) == 1 else "s")
    if not apply_it:
        return True, ("  would stamp %d hand-made row%s that exactly match%s a shipped template (%s) and ask about %d near match%s"
                      % (len(exact), "" if len(exact) == 1 else "s", "es" if len(exact) == 1 else "",
                         ", ".join(p["channel_id"] for p in exact) or "none", len(new_asks), "" if len(new_asks) == 1 else "es"))
    data_dir = os.path.join(profile, "data")
    chan_path = os.path.join(data_dir, "channels.jsonl")
    asks_path = os.path.join(data_dir, "asks.jsonl")
    today = datetime.date.today().isoformat()
    try:
        with open(chan_path, "rb") as fh:
            chan_bytes = fh.read()                                  # THIS RUN's snapshot: what a restore puts back (B4)
    except OSError as exc:
        return False, pending % ("channels.jsonl cannot be re-read (%s)" % exc)
    asks_bytes = None
    if os.path.exists(asks_path):
        try:
            with open(asks_path, "rb") as fh:
                asks_bytes = fh.read()
        except OSError as exc:
            return False, pending % ("asks.jsonl cannot be re-read (%s)" % exc)
    pre = chan_path + "." + ADOPTION_PRE_COPY
    if not os.path.exists(pre):
        try:
            shutil.copy2(chan_path, pre)
        except (OSError, shutil.Error) as exc:
            return False, "  ⚠️ 0.76.0 PENDING -- channels.jsonl could not be preserved to %s (%s), so NOTHING was changed." % (
                os.path.basename(pre), exc)
    replacements, stamped_rows = {}, {}
    for p in exact:
        row = channels[p["index"]]
        new = cc.adopted_row(row, entries[p["entry"]], p["template_sha"], today)
        replacements[p["index"]] = json.dumps(new, ensure_ascii=False)
        stamped_rows[p["index"]] = (row, new, p)
    try:
        text = chan_bytes.decode("utf-8")
        if replacements:
            _atomic.write_text(chan_path, _adoption_replace_lines(text, replacements))
        if new_asks:
            base = asks_bytes.decode("utf-8") if asks_bytes is not None else ""
            if base and not base.endswith("\n"):
                base += "\n"
            added = "".join(json.dumps(cc.adopt_ask_row(channels[p["index"]], entries[p["entry"]], p["differing"], today),
                                       ensure_ascii=False) + "\n" for p in new_asks)
            _atomic.write_text(asks_path, base + added)
    except (OSError, UnicodeDecodeError) as exc:
        _adoption_restore(chan_path, chan_bytes, asks_path, asks_bytes)
        return False, pending % ("the write failed (%s); the stores are restored" % exc)
    # ---- the success condition, re-read from disk
    bad = []
    after, _raws, e1 = _uid_text_read(profile, "channels")
    after_asks, _ar2, e2 = _uid_text_read(profile, "asks")
    if e1 or e2:
        bad.append(e1 or e2)
    else:
        if len(after) != len(channels):
            bad.append("the channel row count changed (%d -> %d)" % (len(channels), len(after)))
        else:
            for i, (was, now) in enumerate(zip(channels, after)):
                if i in stamped_rows:
                    _row, _new, p = stamped_rows[i]
                    if cc.stamp_problems(now) or _vd.check_channel_catalog_fields([now]):
                        bad.append("%s: the stamp does not validate" % now.get("id"))
                    base = {k: v for k, v in now.items() if k not in cc.STAMP_FIELDS}
                    if base != was or list(base) != list(was):
                        bad.append("%s: a field other than the stamp changed" % now.get("id"))
                    if cc.template_match_projection(now) != cc.template_match_projection(was) \
                            or now.get("channel_catalog_sha") != p["template_sha"]:
                        bad.append("%s: the row no longer equals the template it was stamped against" % now.get("id"))
                elif now != was:
                    bad.append("%s: a row that was not adopted changed" % was.get("id"))
        counts = {}
        for a in after_asks:
            counts[a.get("id")] = counts.get(a.get("id"), 0) + 1
        for p in new_asks:
            if counts.get(cc.ADOPT_ASK_PREFIX + p["channel_id"]) != 1:
                bad.append("the adoption question for %s does not exist exactly once" % p["channel_id"])
    if _adoption_fault == "shortfall":
        bad.append("TEST FAULT INJECTED: forced shortfall")
    if bad:
        _adoption_restore(chan_path, chan_bytes, asks_path, asks_bytes)
        return False, ("  ⏳ 0.76.0 PENDING -- the success condition did not hold after the write (%s); the stores are "
                       "restored to what this run read, so nothing you changed is lost. Offered again next session." % "; ".join(bad[:3]))
    lines = ["  ✅ sources (0.76.0) -- adopted %d hand-made row%s, asked %d (nothing else in any row was touched; the original "
             "channels.jsonl is kept at data/channels.jsonl.%s)" % (len(exact), "" if len(exact) == 1 else "s", len(new_asks),
                                                                  ADOPTION_PRE_COPY)]
    for p in exact:
        lines.append("      adopted  %s  (catalog entry %s)" % (p["channel_id"], p["entry"]))
    for p in new_asks:
        lines.append("      asked    %s  (differs from the shipped template on: %s)" % (p["channel_id"], ", ".join(p["differing"]) or "its address"))
    return True, "\n".join(lines)


def _adoption_restore(chan_path, chan_bytes, asks_path, asks_bytes):
    """B4: put back EXACTLY the bytes this run read before its own write. Never reads `*.pre-0.76.0`."""
    import _atomic
    try:
        _atomic.write_text(chan_path, chan_bytes.decode("utf-8"))
        if asks_bytes is not None:
            _atomic.write_text(asks_path, asks_bytes.decode("utf-8"))
        elif os.path.exists(asks_path):
            os.unlink(asks_path)
    except (OSError, UnicodeDecodeError):
        pass
