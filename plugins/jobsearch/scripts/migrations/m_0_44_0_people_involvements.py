"""Migration 0.44.0: `m_0_44_0_people_involvements()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import re
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.44.0"


def _slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").strip().lower()).strip("-")
    return s or "contact"


def m_0_44_0_people_involvements(profile, apply_it, _inject_fault=None):
    """0.44.0 — B1 of ADR-031's connected-entities design: `people` and `involvements` become
    real, top-level, globally-unique stores; `opportunities.contacts[]` and
    `channels.contacts[]` are promoted into them and removed; `contact_id` is renamed
    `person_id` on `outreach[]` (still nested — B3's job) and on `messages.jsonl`.

    ⭐⭐ KEYED "0.44.0", NOT "0.43.0" (ADR-009). 0.43.0 is the newest PUBLISHED jobsearch
    release (plugin.json at HEAD; `git log`/`origin/main` show the 0.43.0 bump and its
    changelog discharge already merged — no `jobsearch--v0.43.0` TAG exists yet on origin, but
    an untagged-yet-published release is a known lag this repo has hit before, CLAUDE.md rule
    9's own scar — it is not evidence 0.43.0 never shipped). `pending_for()` compares with
    strict `<`: a profile that installed 0.43.0 is stamped exactly "0.43.0", and a migration
    keyed to it would never fire for that profile on any later upgrade.

    PRESERVE, THEN TRANSFORM, ALL-OR-NOTHING (design §4 / gate review §2). Every new/changed
    row is built ENTIRELY IN MEMORY first; the result is validated against a throwaway shadow
    copy (`_shadow_validate`) BEFORE a single real byte moves; only a CLEAN shadow run is
    written, atomically (`_atomic.write_jsonl`), to the five real files this stage touches
    (`opportunities.jsonl`, `channels.jsonl`, `messages.jsonl`, and the two new stores). A dirty
    shadow leaves the real profile byte-for-byte untouched and this function returns
    `(False, ...)` naming what failed — a defect in THIS migration to fix before release, never
    a refusal on data grounds (every ambiguity below has a defined, non-destructive outcome).

    IDENTITY — ADR-031 §3, verbatim, via `people.py`'s three normalizers:
      * every nested contact becomes its own candidate person first, id = its own `contact_id`
        (channel contacts with none get `<name-slug>-<channel_id>` minted); a raw id colliding
        with one already minted (two different humans, one string) gets `-2`, `-3`, ... by
        record order (opportunities array order, then channels array order) — this is an
        ID-MINTING collision, not an identity signal, and by itself merges nothing.
      * candidates then MERGE (union-find over two signals) only on identical normalized
        LinkedIn `/in/<slug>`, or identical normalized email AND identical normalized name.
        Survivor = whichever candidate was minted EARLIEST in that same record order — never a
        guess, always reproducible from the input alone.
      * every OTHER apparent match (§3's table: same email/different name, same name/same
        company, same name/different company) is SURFACED — printed in this function's return
        message via `people.find_duplicates`, never merged, never lost: both rows survive as
        distinct, active `people` rows.
      * `path_type`/`role`/`status`/`note` — facts about the person IN THIS pursuit or channel
        — move to the `involvements` row, never to `people`. `people.title`/`cadence`/`note`/
        `created` are new B1 concepts nothing in the legacy shape maps to; left null rather
        than guessed (no legacy field is close enough to copy without inventing a fact).
      * `messages[].person_id` resolves the way the old model meant it (§3 "Messages"): within
        the message's own anchor (`opp_id` or `channel_id`) first, then globally only if the
        raw `contact_id` names exactly one survivor anywhere; anything else (resolves to zero,
        or more than one with no anchor to pick between them) mints its own
        `unresolved-<slug>` person — `status: active`, a note naming what could not be
        resolved — preserved and loud, never dropped (this branch does not occur on any VALID
        pre-migration profile; it exists for the profile that was already broken).

    Idempotent: a profile with no `contacts` key anywhere in `opportunities.jsonl` or
    `channels.jsonl` is treated as already migrated (or never populated) and this returns
    `(True, "")`.

    `_inject_fault` is a test-only hook (never reachable from the CLI): `"drop_required_field"`
    corrupts one freshly-built person row (drops its `name`) in the SHADOW copy right before
    validation, to prove the all-or-nothing property from outside this function rather than by
    reading its source and assuming.
    """
    import people as _people
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    chan_path = os.path.join(profile, "data", "channels.jsonl")
    msg_path = os.path.join(profile, "data", "messages.jsonl")
    if not os.path.exists(opp_path):
        return True, ""
    try:
        opps = _read_jsonl(opp_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e
    try:
        channels = _read_jsonl(chan_path) if os.path.exists(chan_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ channels.jsonl could not be read — nothing migrated: %s" % e
    try:
        messages = _read_jsonl(msg_path) if os.path.exists(msg_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ messages.jsonl could not be read — nothing migrated: %s" % e

    any_contacts = any("contacts" in r for r in opps) or any("contacts" in r for r in channels)
    if not any_contacts:
        return True, ""

    # ---- step 1: mint one candidate per nested contact row, in record order -----------------
    order = []                      # [candidate dict], in mint order (index = mint order)
    seen_raw = {}                   # raw id/base -> count so far (collision counter)
    anchor_index = {}               # (anchor_kind, anchor_id, raw_contact_id) -> mint index

    def _mint(anchor_kind, anchor_id, company_id, raw_id, rec):
        base = raw_id or ("%s-%s" % (_slugify(rec.get("name")), anchor_id))
        seen_raw[base] = seen_raw.get(base, 0) + 1
        cid = base if seen_raw[base] == 1 else "%s-%d" % (base, seen_raw[base])
        idx = len(order)
        order.append({"candidate_id": cid, "anchor_kind": anchor_kind, "anchor_id": anchor_id,
                      "company_id": company_id, "record": rec})
        if raw_id:
            anchor_index[(anchor_kind, anchor_id, raw_id)] = idx
        return cid

    for o in opps:
        for c in (o.get("contacts") or []):
            if isinstance(c, dict):
                _mint("opp", o.get("id"), o.get("company_id"), c.get("contact_id"), c)
    for ch in channels:
        for c in (ch.get("contacts") or []):
            if isinstance(c, dict):
                _mint("channel", ch.get("id"), None, c.get("contact_id"), c)

    # ---- step 2: union-find merge on the two strong signals only ---------------------------
    parent = list(range(len(order)))

    def _find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i, j):
        ri, rj = _find(i), _find(j)
        if ri == rj:
            return
        if ri < rj:                 # earlier MINT INDEX survives, always — reproducible
            parent[rj] = ri
        else:
            parent[ri] = rj

    # signal_of_index[i] records WHICH rule caused candidate i to merge with an earlier
    # candidate the moment that match is found — never inferred later from the union-find
    # structure, which loses the specific edge to path compression once a cluster has more
    # than two members. i is always the LATER (larger mint-index) side of the match here (the
    # earlier side only ever populates the by_* dict, never triggers a union itself), so this
    # is exactly the signal that pulled i into the cluster it ends up in — see finding #1.
    signal_of_index = {}
    by_linkedin, by_email_name = {}, {}
    for i, cand in enumerate(order):
        rec = cand["record"]
        li = _people.normalize_linkedin(rec.get("linkedin"))
        if li:
            if li in by_linkedin:
                _union(i, by_linkedin[li])
                signal_of_index[i] = "LinkedIn URL"
            else:
                by_linkedin[li] = i
        em, nm = _people.normalize_email(rec.get("email")), _people.normalize_name(rec.get("name"))
        if em and nm:
            key = (em, nm)
            if key in by_email_name:
                _union(i, by_email_name[key])
                signal_of_index.setdefault(i, "email+name")
            else:
                by_email_name[key] = i

    survivor_id = [order[_find(i)]["candidate_id"] for i in range(len(order))]

    # ---- step 3: build people rows --------------------------------------------------------
    merge_pairs = []               # (absorbed_id, survivor_id, signal) for the report
    people_rows = []
    for i, cand in enumerate(order):
        rec = cand["record"]
        root = _find(i)
        is_survivor = (root == i)
        row = {
            "id": cand["candidate_id"],
            "name": rec.get("name"),
            "email": rec.get("email"),
            "email_status": rec.get("email_status"),
            "linkedin": rec.get("linkedin"),
            "company_id": cand["company_id"] if cand["anchor_kind"] == "opp" else None,
            "title": None,
            "cadence": None,
            "status": "active" if is_survivor else "merged",
            "merged_into": None if is_survivor else order[root]["candidate_id"],
            "not_same_as": [],
            "created": None,
            "note": None,
        }
        people_rows.append(row)
        if not is_survivor:
            merge_pairs.append((cand["candidate_id"], order[root]["candidate_id"],
                                signal_of_index.get(i, "identity signal")))

    # ---- step 4: build involvements rows — ALWAYS the resolved survivor's person_id ---------
    involvements_rows = []
    for i, cand in enumerate(order):
        rec = cand["record"]
        pid = survivor_id[i]
        involvements_rows.append({
            "person_id": pid,
            "opp_id": cand["anchor_id"] if cand["anchor_kind"] == "opp" else None,
            "channel_id": cand["anchor_id"] if cand["anchor_kind"] == "channel" else None,
            "path_type": rec.get("path_type"),
            "role": rec.get("role"),
            "status": rec.get("status"),
            "note": rec.get("note"),
        })

    # ---- step 5: rename outreach[].contact_id -> person_id, anchor-scoped, and strip contacts
    new_opps = []
    for o in opps:
        o = dict(o)
        out_list = []
        for entry in (o.get("outreach") or []):
            entry = dict(entry)
            raw = entry.pop("contact_id", None)
            idx = anchor_index.get(("opp", o.get("id"), raw))
            entry["person_id"] = survivor_id[idx] if idx is not None else None
            out_list.append(entry)
        if "outreach" in o:
            o["outreach"] = out_list
        o.pop("contacts", None)
        new_opps.append(o)

    new_channels = []
    for ch in channels:
        ch = dict(ch)
        ch.pop("contacts", None)
        new_channels.append(ch)

    # ---- step 6: messages[].contact_id -> person_id — anchor first, then global-if-unique --
    raw_global = {}                 # raw contact_id -> set of survivor ids seen ANYWHERE
    for i, cand in enumerate(order):
        raw = cand["record"].get("contact_id")
        if raw:
            raw_global.setdefault(raw, set()).add(survivor_id[i])

    unresolved_notes = []
    new_messages = []
    for m in messages:
        m = dict(m)
        raw = m.pop("contact_id", None)
        pid = None
        if raw:
            opp_id, chan_id = m.get("opp_id"), m.get("channel_id")
            idx = anchor_index.get(("opp", opp_id, raw)) if opp_id else None
            if idx is None and chan_id:
                idx = anchor_index.get(("channel", chan_id, raw))
            if idx is not None:
                pid = survivor_id[idx]
            else:
                candidates = raw_global.get(raw) or set()
                if len(candidates) == 1:
                    pid = next(iter(candidates))
                else:
                    minted = "unresolved-%s" % _slugify(raw)
                    base_minted, n = minted, 1
                    existing_ids = {p["id"] for p in people_rows}
                    while minted in existing_ids:
                        n += 1
                        minted = "%s-%d" % (base_minted, n)
                    note = ("minted by the 0.44.0 migration: messages[%s].contact_id %r %s — "
                            "preserved as its own person rather than dropped"
                            % (m.get("id", "?"), raw,
                               "resolved nowhere" if not candidates else
                               "was ambiguous (%d candidates, no anchor to choose between "
                               "them)" % len(candidates)))
                    people_rows.append({
                        "id": minted, "name": raw, "email": None, "email_status": None,
                        "linkedin": None, "company_id": None, "title": None, "cadence": None,
                        "status": "active", "merged_into": None, "not_same_as": [],
                        "created": None, "note": note,
                    })
                    unresolved_notes.append(note)
                    pid = minted
        m["person_id"] = pid
        new_messages.append(m)

    # ---- step 7: surface, never merge, everything weaker (design §3's review queue) ---------
    dup_pairs = _people.find_duplicates(people_rows)

    overrides = {
        "opportunities.jsonl": new_opps,
        "channels.jsonl": new_channels,
        "messages.jsonl": new_messages,
        "people.jsonl": people_rows,
        "involvements.jsonl": involvements_rows,
    }

    merge_bit = "%d merge(s) by identity signal" % len(merge_pairs)
    if merge_pairs:
        merge_bit += ": " + "; ".join("%s -> %s (%s)" % (absorbed, survivor, signal)
                                      for absorbed, survivor, signal in merge_pairs)
    summary_bits = [
        "%d contact(s) promoted to people/involvements" % len(order),
        merge_bit,
    ]
    if dup_pairs:
        summary_bits.append("%d likely-duplicate pair(s) surfaced for review (not merged): %s"
                            % (len(dup_pairs),
                               "; ".join("%s<->%s (%s)" % (p["a"], p["b"], p["reason"])
                                        for p in dup_pairs)))
    if unresolved_notes:
        summary_bits.append("%d message contact_id(s) could not resolve — minted as their own "
                            "unresolved person: %s"
                            % (len(unresolved_notes), " | ".join(unresolved_notes)))
    summary = "; ".join(summary_bits)

    if not apply_it:
        return True, "  would migrate (0.44.0) to people/involvements: %s" % summary

    if _inject_fault == "drop_required_field" and people_rows:
        # TEST-ONLY — see docstring. Mutated on a COPY inside the override dict; the in-memory
        # `people_rows` list used for the real write below is untouched, so this only ever
        # corrupts what the SHADOW sees.
        faulted = [dict(r) for r in people_rows]
        del faulted[0]["name"]
        overrides = dict(overrides)
        overrides["people.jsonl"] = faulted

    rc, problems, new = _shadow_validate(profile, overrides)
    if new is None or new:
        # A genuinely NEW problem (or an unreadable pre/post comparison) — THIS migration's
        # own change is implicated; refuse and write nothing (see _shadow_validate's own
        # docstring for why the comparison is by problem SET, not by rc).
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list — it crashed" % rc)
        return False, ("  ⚠️ 0.44.0 REFUSED — the migrated shape introduces a new validation "
                       "problem, so NOTHING was written (the real profile is untouched): %s"
                       % detail)
    pre_existing_note = ""
    if rc != 0:
        pre_existing_note = ("  ⚠️ %d pre-existing problem(s) stand, unrelated to this "
                             "migration (a later stage's own migration may resolve them): %s"
                             % (len(problems or []), "; ".join((problems or [])[:4])))

    import _atomic
    for name in ("people.jsonl", "involvements.jsonl", "opportunities.jsonl",
                "channels.jsonl", "messages.jsonl"):
        _atomic.write_jsonl(os.path.join(profile, "data", name), overrides[name])
    msg = "  ✅ people/involvements (0.44.0) — %s" % summary
    return True, (msg + "\n" + pre_existing_note if pre_existing_note else msg)
