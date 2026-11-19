"""Migration 0.76.1: `m_0_76_1_legacy_placeholders()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
import shutil
from migrations.support_adoption import _adoption_replace_lines
from migrations.support_uid import _uid_text_read

VERSION = "0.76.1"


# ---- 0.76.1 (dev #768-1 + #764-4; public #165, #162): bring legacy placeholder values into the shape the validator now
# requires -------------------------------------------------------------------------------------------------------------
#
# WHY A MIGRATION. 0.73.0 tightened `check_company_fields` (an empty `career_url` / `domain` / `size_ownership`, or an empty
# entry in `aliases`, became a PROBLEM) and shipped no step for data written earlier; a create-time `auto` on a store with
# no minting branch left the literal id "auto" on a `cover_letters` row (#764). The contract step shipped without the
# migrate step, so a profile that was clean before the upgrade validated red after it. The validator is NOT loosened: this
# is the missing migrate step. KEYED "0.76.1" (0.76.0 is the newest PUBLISHED release; a profile that installed it is
# stamped exactly "0.76.0", and strict `<` would never fire a migration keyed to it). It runs LAST.
#
# WHAT IT DOES, in the order it does it:
#   1. READS STRICTLY (`_uid_text_read`): ONE line of companies / cover_letters / applications / asks that does not parse
#      is PENDING with nothing written, because rewriting a store this could not fully read would drop that line.
#   2. PRESERVES FIRST: each store about to change is copied byte for byte to `<store>.jsonl.pre-0.76.1`, never over a copy
#      already there (that is the true original of an earlier partial run).
#   3. companies: `career_url` / `domain` that are empty (or whitespace) strings become null; an empty `size_ownership`
#      (or a null one, which carries nothing either) is dropped; empty entries of `aliases` are dropped (a null `aliases`
#      is dropped like a null size_ownership). Nothing else in a row is touched, and no row is removed.
#   4. cover_letters: exactly ONE row with id "auto" whose `opp_id` is present is given `<opp_id>-clN` (N one past the
#      highest suffix already minted for that opp, never a freed number: `record.mint_app_id`'s rule), and every
#      `cover_letter_id` in applications that said "auto" is repointed to it.
#   5. ANYTHING IT CANNOT FIX LOSSLESSLY is left exactly as found and named, by store and id, in ONE `asks.jsonl` row
#      (`legacy-placeholders-unfixed`, kind system, replaced by id on a re-run, closed once nothing is left). That is a value
#      of the wrong TYPE (a list `career_url`, a bare-string `aliases`), several "auto" cover letters (which application
#      meant which cannot be known), an "auto" letter with no `opp_id` to mint from, and an application pointing at an
#      "auto" letter that does not exist. The result is PENDING (False), never a false "done".
#   6. VERIFIES FROM DISK: every store re-read must equal exactly what was planned and every untouched line must be
#      byte-identical; ANY SHORTFALL restores the bytes this run read just before its own write and returns PENDING.
#
# IDEMPOTENT: a second run finds nothing to fix and writes nothing. ROLLBACK RISK: restoring `<store>.jsonl.pre-0.76.1`
# undoes it for rows not edited since; an older engine's validator reads the fixed shape as valid.
LEGACY_PLACEHOLDERS_PRE_COPY = "pre-0.76.1"
LEGACY_PLACEHOLDERS_ASK_ID = "legacy-placeholders-unfixed"
_legacy_placeholders_fault = None   # TEST SEAM (family of `_adoption_fault`): "shortfall" forces the verify step to fail


def _blank_str(v):
    return isinstance(v, str) and not v.strip()


def _legacy_fix_company(row):
    """`(new_row, unfixable_fields)` for one companies row. Key order is kept; only the listed placeholders change."""
    new, bad = dict(row), []
    for f in ("career_url", "domain"):
        if f in new and new[f] is not None:
            if _blank_str(new[f]):
                new[f] = None
            elif not isinstance(new[f], str):
                bad.append(f)
    if "size_ownership" in new:
        if new["size_ownership"] is None or _blank_str(new["size_ownership"]):
            del new["size_ownership"]
        elif not isinstance(new["size_ownership"], str):
            bad.append("size_ownership")
    if "aliases" in new:
        al = new["aliases"]
        if al is None:
            del new["aliases"]
        elif isinstance(al, list):
            kept = [a for a in al if not _blank_str(a)]
            if len(kept) != len(al):
                new["aliases"] = kept
            if any(not isinstance(a, str) for a in kept):
                bad.append("aliases")
        else:
            bad.append("aliases")
    return new, bad


def _legacy_mint_cover_letter_id(opp_id, rows):
    """`<opp_id>-clN`, N one past the highest suffix already minted for this opp (record.mint_app_id's rule)."""
    prefix = "%s-cl" % opp_id
    n = 0
    for r in rows:
        rid = r.get("id")
        if isinstance(rid, str) and rid.startswith(prefix) and rid[len(prefix):].isdigit():
            n = max(n, int(rid[len(prefix):]))
    return "%s%d" % (prefix, n + 1)


def _legacy_plan(companies, letters, apps):
    """The whole plan as data: the rows each store should hold afterwards (`companies`, `cover_letters`,
    `applications`), `changed` ({store: [row index, ...]}), `unfixable` (sorted `store:id (why)` labels), `minted`."""
    new_companies, c_changed, unfixable = [], [], set()
    for i, row in enumerate(companies):
        new, bad = _legacy_fix_company(row)
        if new != row:
            c_changed.append(i)
        for f in bad:
            unfixable.add("companies:%s (%s has a value of the wrong type)" % (row.get("id", "line %d" % (i + 1)), f))
        new_companies.append(new)
    new_letters, l_changed = [dict(r) for r in letters], []
    new_apps, a_changed = [dict(r) for r in apps], []
    autos = [i for i, r in enumerate(letters) if r.get("id") == "auto"]
    minted = None
    if len(autos) > 1:
        unfixable.add("cover_letters:auto (%d rows share the id, so which application meant which cannot be known)"
                      % len(autos))
    elif len(autos) == 1:
        i = autos[0]
        opp = letters[i].get("opp_id")
        if isinstance(opp, str) and opp.strip():
            minted = _legacy_mint_cover_letter_id(opp, letters)
            new_letters[i]["id"] = minted
            l_changed.append(i)
        else:
            unfixable.add("cover_letters:auto (no opp_id to mint an id from)")
    for j, r in enumerate(apps):
        if r.get("cover_letter_id") == "auto":
            if minted:
                new_apps[j]["cover_letter_id"] = minted
                a_changed.append(j)
            else:
                unfixable.add("applications:%s (cover_letter_id points at 'auto', which cannot be resolved)"
                              % r.get("id", "line %d" % (j + 1)))
    return {"companies": new_companies, "cover_letters": new_letters, "applications": new_apps,
            "changed": {"companies": c_changed, "cover_letters": l_changed, "applications": a_changed},
            "unfixable": sorted(unfixable), "minted": minted}


def _legacy_ask_row(unfixable, today, created=None):
    """The ONE `asks.jsonl` row naming every row the migration could not fix. A DECISION, never mechanical work."""
    shown = unfixable[:20]
    more = len(unfixable) - len(shown)
    return {"id": LEGACY_PLACEHOLDERS_ASK_ID, "kind": "system",
            "title": "%d row%s still carry a legacy placeholder the migration could not fix"
                     % (len(unfixable), "" if len(unfixable) == 1 else "s"),
            "ask": ("jobsearch 0.76.1 repaired the legacy placeholder values it could repair without losing anything, and "
                    "left these exactly as they were: %s%s. Decide what each should hold and fix it with `record.py set` "
                    "(the validator names the command for each), then run validate_data.py. This migration tries again "
                    "next session and closes this ask once nothing is left. The original files are kept beside the data "
                    "as <store>.jsonl.%s." % ("; ".join(shown), (" and %d more" % more) if more else "",
                                              LEGACY_PLACEHOLDERS_PRE_COPY)),
            "created": created or today, "act_by": None, "opp_id": None, "channel_id": None,
            "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None}


def _legacy_restore(snapshots):
    """B4's rule: put back EXACTLY the bytes this run read before its own write (`None` = the file did not exist).
    Never reads `*.pre-0.76.1`."""
    import _atomic
    for path, data in snapshots.items():
        try:
            if data is None:
                if os.path.exists(path):
                    os.unlink(path)
            else:
                _atomic.write_text(path, data.decode("utf-8"))
        except (OSError, UnicodeDecodeError):
            pass


def m_0_76_1_legacy_placeholders(profile, apply_it):
    """0.76.1 -- repair legacy placeholder values in companies / cover_letters / applications (see the block above).
    Returns (done, message); PENDING (False) whenever it cannot read, cannot verify, or has a row it cannot fix losslessly."""
    import datetime
    import _atomic
    pending = "  ⏳ 0.76.1 PENDING -- %s. Nothing was written."
    stores, err = {}, None
    for name in ("companies", "cover_letters", "applications", "asks"):
        rows, raws, e = _uid_text_read(profile, name)
        err = err or e
        stores[name] = (rows, raws)
    if err:
        return False, pending % ("%s. Fix it and this runs again next session: rewriting a store this could not fully read "
                                 "would drop that line" % err)
    asks = stores["asks"][0]
    plan = _legacy_plan(stores["companies"][0], stores["cover_letters"][0], stores["applications"][0])
    changed, unfixable = plan["changed"], plan["unfixable"]
    n_changed = sum(len(v) for v in changed.values())
    today = datetime.date.today().isoformat()
    have_ask = next((a for a in asks if a.get("id") == LEGACY_PLACEHOLDERS_ASK_ID), None)
    ask_open = have_ask is not None and not have_ask.get("resolved_on")
    if not n_changed and not unfixable and not ask_open:
        return True, "  ✅ legacy placeholders (0.76.1) -- nothing to fix"
    summary = "%d companies row%s, %d cover letter%s, %d application reference%s" % (
        len(changed["companies"]), "" if len(changed["companies"]) == 1 else "s",
        len(changed["cover_letters"]), "" if len(changed["cover_letters"]) == 1 else "s",
        len(changed["applications"]), "" if len(changed["applications"]) == 1 else "s")
    if not apply_it:
        msg = "  would repair (0.76.1): %s" % summary
        if unfixable:
            msg += "; %d row%s it cannot fix losslessly (%s)" % (len(unfixable), "" if len(unfixable) == 1 else "s",
                                                               "; ".join(unfixable[:5]))
        return not unfixable, msg
    data_dir = os.path.join(profile, "data")
    paths = {name: os.path.join(data_dir, name + ".jsonl") for name in stores}
    # ---- plan every new file text BEFORE touching disk, from the bytes this run reads now
    snapshots, texts = {}, {}
    for name in ("companies", "cover_letters", "applications", "asks"):
        if name != "asks" and not changed[name]:
            continue
        try:
            with open(paths[name], "rb") as fh:
                snapshots[paths[name]] = fh.read()
        except FileNotFoundError:
            snapshots[paths[name]] = None
        except OSError as exc:
            return False, pending % ("%s.jsonl cannot be re-read (%s)" % (name, exc))
    try:
        for name in ("companies", "cover_letters", "applications"):
            if changed[name]:
                repl = {i: json.dumps(plan[name][i], ensure_ascii=False) for i in changed[name]}
                texts[paths[name]] = _adoption_replace_lines(snapshots[paths[name]].decode("utf-8"), repl)
        ask_bytes = snapshots[paths["asks"]]
        ask_text = ask_bytes.decode("utf-8") if ask_bytes is not None else ""
        if unfixable:
            want = _legacy_ask_row(unfixable, today, have_ask.get("created") if have_ask and have_ask.get("created") else None)
            line = json.dumps(want, ensure_ascii=False)
            if have_ask is not None:
                new_ask_text = _adoption_replace_lines(ask_text, {asks.index(have_ask): line})
            else:
                new_ask_text = (ask_text if not ask_text or ask_text.endswith("\n") else ask_text + "\n") + line + "\n"
        elif ask_open:
            closed = json.dumps(dict(have_ask, resolved_on=today, resolution="fixed"), ensure_ascii=False)
            new_ask_text = _adoption_replace_lines(ask_text, {asks.index(have_ask): closed})
        else:
            new_ask_text = ask_text
        if new_ask_text != ask_text:
            texts[paths["asks"]] = new_ask_text
    except UnicodeDecodeError as exc:
        return False, pending % ("a store is not valid UTF-8 (%s)" % exc)
    # ---- PRESERVE FIRST: one byte-for-byte copy per store about to change, never over an earlier one
    for path in texts:
        if snapshots[path] is None:
            continue
        pre = path + "." + LEGACY_PLACEHOLDERS_PRE_COPY
        if not os.path.exists(pre):
            try:
                shutil.copy2(path, pre)
            except (OSError, shutil.Error) as exc:
                return False, ("  ⚠️ 0.76.1 PENDING -- %s could not be preserved to %s (%s), so NOTHING was changed."
                               % (os.path.basename(path), os.path.basename(pre), exc))
    try:
        for path, text in texts.items():
            _atomic.write_text(path, text)
    except OSError as exc:
        _legacy_restore({p: snapshots[p] for p in texts})
        return False, pending % ("the write failed (%s); the stores are restored" % exc)
    # ---- the success condition, re-read from disk
    bad = []
    for name in ("companies", "cover_letters", "applications"):
        rows, raws = stores[name]
        after, after_raws, e = _uid_text_read(profile, name)
        if e:
            bad.append(e)
        elif len(after) != len(rows):
            bad.append("%s: the row count changed (%d -> %d)" % (name, len(rows), len(after)))
        else:
            for i, (was_raw, now_raw, now) in enumerate(zip(raws, after_raws, after)):
                if i in changed[name]:
                    if now != plan[name][i]:
                        bad.append("%s line %d: does not equal the planned row" % (name, i + 1))
                elif now_raw != was_raw:
                    bad.append("%s line %d: a row that was not repaired changed" % (name, i + 1))
    after_asks, _r, e = _uid_text_read(profile, "asks")
    if e:
        bad.append(e)
    else:
        mine = [a for a in after_asks if a.get("id") == LEGACY_PLACEHOLDERS_ASK_ID]
        if unfixable and (len(mine) != 1 or mine[0].get("resolved_on")):
            bad.append("the question naming the unfixable rows does not exist exactly once and open")
        if len(after_asks) != len(asks) + (1 if unfixable and have_ask is None else 0):
            bad.append("asks.jsonl: the row count is not what was planned")
    if _legacy_placeholders_fault == "shortfall":
        bad.append("TEST FAULT INJECTED: forced shortfall")
    if bad:
        _legacy_restore({p: snapshots[p] for p in texts})
        return False, ("  ⏳ 0.76.1 PENDING -- the success condition did not hold after the write (%s); the stores are "
                       "restored to what this run read, so nothing you changed is lost. Offered again next session."
                       % "; ".join(bad[:3]))
    lines = ["  %s legacy placeholders (0.76.1) -- repaired %s (the original files are kept beside the data as "
             "<store>.jsonl.%s)" % ("⏳" if unfixable else "✅", summary, LEGACY_PLACEHOLDERS_PRE_COPY)]
    if plan["minted"]:
        lines.append("      cover letter 'auto' -> %s, and every application that named it repointed" % plan["minted"])
    if unfixable:
        lines.append("  ⏳ 0.76.1 PENDING -- %d row%s could not be fixed losslessly and %s left as found; one ask (%s) "
                     "names %s: %s" % (len(unfixable), "" if len(unfixable) == 1 else "s",
                                       "was" if len(unfixable) == 1 else "were", LEGACY_PLACEHOLDERS_ASK_ID,
                                       "it" if len(unfixable) == 1 else "them", "; ".join(unfixable[:5])))
    return not unfixable, "\n".join(lines)
