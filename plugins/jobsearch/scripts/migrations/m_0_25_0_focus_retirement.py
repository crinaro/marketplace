"""Migration 0.25.0: `m_0_25_0_focus_retirement()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os
from migrations.stamp import engine_version

VERSION = "0.25.0"


FOCUS_RETIRED_MARKER = "RETIRED as a source of state (dev #93)"


def m_0_25_0_focus_retirement(profile, apply_it):
    """0.25.0 — focus.md is retired as a source of state (dev #93 / public #21).

    The owner's call: "Keep the tabs and remove the use of focus.md, use the data in the
    json files." The verified failure behind it: a record hand-copied into focus.md's
    action-needed list duplicated its auto-rendered row and went stale, still claiming
    action was needed after it was not. The dashboard keeps both tabs; their content moves
    to stores a view cannot disagree with:

        ## ⚡ Your Move (numbered items)      -> data/asks.jsonl        kind=role
        ## ⚙️ Process — ⚡ Needs … (items)    -> data/asks.jsonl        kind=system
        ## 📅 This Week (items/bullets)      -> data/commitments.jsonl (unparseable date ->
                                                the literal `unresolved`, LOUD downstream)
        ## 🔗 Session Handoff                -> handoff.md — narrative for the next session,
                                                deliberately NOT forced into JSONL: a letter
                                                is not a record, and the stores it points at
                                                are already queryable.
        anything else with real content      -> appended to process_archive.md, stamped

    ⭐⭐ PRESERVE, THEN TRANSFORM — in that order, mechanically. Every relocation is written
    and verified BEFORE focus.md is touched; a failure part-way leaves content in BOTH
    places (recoverable), never in neither. A migration that refused because content would
    be lost has not shipped (this repo's own Process-section lesson); nothing here refuses.
    Finally focus.md is replaced with a frozen stub naming the new homes, which is also the
    idempotency marker: a stubbed file migrates to nothing on every later run. Ask and
    commitment ids are content-derived (a short hash), so even a re-run against a restored
    focus.md cannot duplicate rows. The two stores are created (empty) even when focus.md is
    absent — doctor.py asserts their existence, and an absent store must mean "not migrated
    yet", never "migrated on a profile that happened to have no focus.md".
    """
    import datetime as _dt
    import hashlib as _hashlib
    import re as _re

    data_dir = os.path.join(profile, "data")
    focus_path = os.path.join(profile, "focus.md")

    def _ensure_stores():
        made = []
        if os.path.isdir(data_dir):
            for name in ("asks.jsonl", "commitments.jsonl"):
                p = os.path.join(data_dir, name)
                if not os.path.exists(p):
                    if apply_it:
                        open(p, "a").close()
                    made.append("data/%s" % name)
        return made

    if not os.path.exists(focus_path):
        made = _ensure_stores()
        if made:
            return True, ("  %s empty store(s): %s (no focus.md to carry content from)"
                          % ("✅ created" if apply_it else "would create", ", ".join(made)))
        return True, ""

    try:
        with open(focus_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        return False, "  ⚠️ focus.md could not be read, so nothing was migrated: %s" % e

    if FOCUS_RETIRED_MARKER in text:
        _ensure_stores()
        return True, ""                     # already migrated — the stub is the marker

    # ---- parse the sections ------------------------------------------------
    def _section(pat):
        m = _re.search(r"(^##\s*" + pat + r".*?$)(.*?)(?=^##\s|\Z)", text, _re.M | _re.S)
        return (m.group(1) + m.group(2)) if m else ""

    def _items(body):
        out = []
        for line in body.splitlines():
            im = _re.match(r"^\s*(?:\d+\.|[-*])\s+(?:\*\*(.+?)\*\*\s*[—:-]?\s*)?(.*)$", line)
            if im and (im.group(1) or im.group(2).strip()):
                title = (im.group(1) or im.group(2).strip()[:80]).strip()
                rest = im.group(2).strip()
                out.append((title, rest))
        return out

    today = _dt.date.today().isoformat()

    def _hid(prefix, *parts):
        h = _hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:8]
        return "%s-mig-%s" % (prefix, h)

    # An opp_id is only carried when it RESOLVES — validate_data.py enforces referential
    # integrity on asks, and a migration must never leave the profile failing its own gate.
    # A tag that does not resolve is folded back into the ask text, so nothing is lost.
    known_opp_ids = set()
    try:
        with open(os.path.join(data_dir, "opportunities.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    known_opp_ids.add(json.loads(line).get("id"))
    except (OSError, ValueError):
        pass

    ask_rows = []
    ym_body = _section(r"(?:⚡\s*)?Your Move")
    for title, rest in _items(ym_body):
        opp_id = None
        tagm = _re.search(r"\s*\{opp:\s*([a-z0-9-]+)\s*\}\s*$", rest)
        if tagm:
            opp_id = tagm.group(1)
            rest = rest[:tagm.start()].rstrip()
        row = {"id": _hid("ask", "role", title, rest), "kind": "role", "title": title,
               "ask": rest or title, "created": today,
               "note": "migrated 0.25.0 from focus.md ## Your Move"}
        if opp_id and opp_id in known_opp_ids:
            row["opp_id"] = opp_id
        elif opp_id:
            row["ask"] = ("%s (tagged {opp:%s}, which resolves to no record)"
                          % (row["ask"], opp_id))
        ask_rows.append(row)
    needs_body = _section(r"⚙️\s*Process\s*—\s*⚡\s*Needs\b")
    for title, rest in _items(needs_body):
        ask_rows.append({"id": _hid("ask", "system", title, rest), "kind": "system",
                         "title": title, "ask": rest or title, "created": today,
                         "note": "migrated 0.25.0 from focus.md ## Process — Needs"})

    cm_rows = []
    tw_body = _section(r"📅\s*This Week")
    for title, rest in _items(tw_body):
        m = _re.search(r"\b(20\d\d-\d\d-\d\d)\b", "%s %s" % (title, rest))
        # A date that cannot be read mechanically is written as the literal `unresolved` —
        # LOUD downstream (validator, dashboard, check_sections), never guessed and never
        # dropped. Same precedent as blocked_until and play_stage.
        cm_rows.append({"id": _hid("cm", title, rest), "date": m.group(1) if m else "unresolved",
                        "title": title, "note": (rest or None),
                        "source": "migrated 0.25.0 from focus.md ## This Week"})

    handoff_body = _section(r"🔗\s*Session Handoff")

    # Everything not carried above, with real content, goes to the archive — including the
    # section headers themselves, so the archived copy stays readable in place.
    carried = [ym_body, needs_body, tw_body, handoff_body]
    leftover = text
    for block in carried:
        if block:
            leftover = leftover.replace(block, "", 1)
    leftover_has_content = any(
        l.strip() and not l.strip().startswith("#") for l in leftover.splitlines())

    if not apply_it:
        return True, ("  would retire focus.md: %d ask(s) -> data/asks.jsonl, %d commitment(s) "
                      "-> data/commitments.jsonl%s%s, then replace focus.md with a frozen stub"
                      % (len(ask_rows), len(cm_rows),
                         ", Session Handoff -> handoff.md" if handoff_body.strip() else "",
                         ", remaining prose -> process_archive.md"
                         if leftover_has_content else ""))

    # ---- PRESERVE (verified) ... -------------------------------------------
    try:
        os.makedirs(data_dir, exist_ok=True)

        def _append_rows(name, rows_new):
            p = os.path.join(data_dir, name)
            have = set()
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                have.add(json.loads(line).get("id"))
                            except ValueError:
                                pass
            fresh = [r for r in rows_new if r.get("id") not in have]
            with open(p, "a", encoding="utf-8") as fh:
                for r in fresh:
                    fh.write(json.dumps({k: v for k, v in r.items() if v is not None},
                                        ensure_ascii=False) + "\n")
            # verify: every id must now be present
            with open(p, encoding="utf-8") as fh:
                now_have = {json.loads(l).get("id") for l in fh if l.strip()}
            missing = [r["id"] for r in rows_new if r["id"] not in now_have]
            if missing:
                raise IOError("store write did not verify: %s missing %s" % (name, missing))
            return len(fresh)

        n_asks = _append_rows("asks.jsonl", ask_rows)
        n_cms = _append_rows("commitments.jsonl", cm_rows)

        if handoff_body.strip():
            hp = os.path.join(profile, "handoff.md")
            existing = ""
            if os.path.exists(hp):
                with open(hp, encoding="utf-8") as fh:
                    existing = fh.read()
            payload = ("\n\n## Migrated from focus.md by jobsearch %s\n\n%s"
                       % (engine_version(), handoff_body))
            with open(hp + ".tmp", "w", encoding="utf-8") as fh:
                fh.write((existing or "# Session handoff — a letter to the next session\n")
                         + payload)
            os.replace(hp + ".tmp", hp)
            with open(hp, encoding="utf-8") as fh:
                if handoff_body.strip()[:120] not in fh.read():
                    raise IOError("handoff.md write did not verify")

        if leftover_has_content:
            ap_ = os.path.join(profile, "process_archive.md")
            existing = ""
            if os.path.exists(ap_):
                with open(ap_, encoding="utf-8") as fh:
                    existing = fh.read()
            stamp = "\n\n## Retired from focus.md by jobsearch %s\n\n" % engine_version()
            with open(ap_ + ".tmp", "w", encoding="utf-8") as fh:
                fh.write(existing + stamp + leftover.strip() + "\n")
            os.replace(ap_ + ".tmp", ap_)
    except Exception as e:                   # noqa: BLE001 — refuse to transform on ANY miss
        return False, ("  ⚠️ could not relocate focus.md content (%s) — focus.md was NOT "
                       "changed. Removing content whose relocation failed is the one outcome "
                       "this migration must never produce; it will retry next session." % e)

    # ---- ... THEN TRANSFORM ------------------------------------------------
    stub = (
        "# focus.md — %s\n\n"
        "This file is no longer read or written. Its content moved on %s:\n\n"
        "- Your Move asks        -> `data/asks.jsonl` (kind: role | system)\n"
        "- This Week commitments -> `data/commitments.jsonl`\n"
        "- Session handoff       -> `handoff.md`\n"
        "- everything else       -> `process_archive.md`\n\n"
        "Role and channel state was already generated from `data/*.jsonl`. Edit the "
        "records, never this file.\n" % (FOCUS_RETIRED_MARKER, today))
    with open(focus_path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(stub)
    os.replace(focus_path + ".tmp", focus_path)   # atomic — never a half-written stub

    bits = ["%d ask(s) -> data/asks.jsonl" % n_asks,
            "%d commitment(s) -> data/commitments.jsonl" % n_cms]
    if handoff_body.strip():
        bits.append("Session Handoff -> handoff.md")
    if leftover_has_content:
        bits.append("remaining prose -> process_archive.md")
    return True, ("  ✅ focus.md retired: %s; focus.md is now a frozen stub naming the new "
                  "homes." % "; ".join(bits))
