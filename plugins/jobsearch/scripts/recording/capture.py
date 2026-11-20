"""capture: `capture-batch`, the card -> role step: link every open `capture-role` item that is a sighting of a known
role, create the roles a run's drain admitted from their oldest item and close their siblings, one write per store;
and `create --from-item`'s copy of the facts the sweep parsed onto the new role.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import re
from recording import profile_paths as _paths
from recording.row_checks import (
    _POSTING_FIELD,
    _diagnostic_lines,
    _row_checks,
    dry_run_validate,
    new_problems,
    validate,
)
from recording.common import _Refused, _engine_version, _now, _profile_mod, _slug, _validator_module
from recording.posting import _feed_posting_value
from recording.reads import (
    CAPTURE_DEADLINE_S_DEFAULT,
    EXIT_ITEM_REFUSED,
    _store_screen,
    type_from_setting,
)
from recording.sourcing import _new_opportunity_plan, _without_provenance
from recording.store_files import (
    LockError,
    _load_or_empty,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


def copy_capture_item_facts(new_row, item_id, rid=None, item=None, profile=None):
    """`(copied, error)` -- `create --from-item <deferred id>` (dev #715 / public #143, dev #716 /
    public #142; design §2). Copy what `deferred.py --add-roles` PARSED from the sweep's ROLE line,
    held on the `capture-role` item's `role` object, onto the opportunity being created:
    `role.listed_pay` -> `listed_pay`, `role.posted` -> `posted`, `role.location_declared` ->
    `location.declared`. The shapes are the ones `record.py listed-pay` / `posted` store, so the
    model never re-types a value a script already parsed, and a captured role does not screen
    NOT-CAPTURED for a pay its own sweep read.

    ⭐ jobsearch 0.70.0 (dev #727 / public #159; design-location-screen.md §4): `role.location_listed`
    (the ROLE line's `location=` text, verbatim) is copied to `location.primary`, and a posting whose
    setting the sweep read as `none stated` at a CONCRETE PLACE (`places.parse_place` reads it) is
    recorded as `location.type: onsite` with `location.setting_source: inferred`. This is the one
    place a captured row is born, so the inference is a recorded rule, not a type the model picked
    and nobody noted. It is OURS (the publisher convention reserves `TELECOMMUTE` for remote work
    and has no value for hybrid, so an unmarked posting may be hybrid; at a place proven outside every
    commute radius hybrid is as infeasible as onsite, which is why a removal on an inference is safe).
      * `none stated` + a place -> `type: onsite`, `setting_source: inferred`.
      * `none stated` + no place (or no text) -> `type` stays ABSENT; the screen asks (NEEDS-REVIEW).
      * `none stated` + a `location.type` in the JSON -> REFUSED: the sweep read no setting, so a type
        the model chose would be an unflagged guess. Omit it; or create the row, then replace the
        location with the JD's wording (`record.py set <id> location '<json>'`, which records the
        overturn).
      * `?` (not read) or a verbatim setting -> as before: the JSON states the type, nothing is
        inferred, and `unresolved` is never touched.
      * A `location.primary` in the JSON that differs from `location_listed` is refused (one value,
        stated once). An item queued before 0.70.0 has no `location_listed`; the JSON's is used.

    ⭐ jobsearch 0.82.0 (dev #820 / public #175; design-role-pipeline.md section 3.1): EVERYTHING copied here is a
    CARD fact. `listed_pay` and `location` are stamped `provenance: card`, a card place that equals a commute
    anchor's own place also gets `location.anchor_echo: true` (a board searched at your home town prints that
    town on every card), and **a card never infers `onsite`**: the 0.70.0 inference above is NOT made here any
    more, so a `none stated` card at a concrete place has no `type` until the JD is read (`record.py read-jd`
    keeps the inference, where the posting itself has been read). The screen of a card-input role is
    `provisional` (`profile.screen_rules`). `item` (a replayed `capture-role` item) and `profile` may be passed by
    a caller that copies many items, so each is loaded once per call, not once per item.

    A slot the sweep did not read (`?`) is `None` on the item and is NOT copied: the field stays
    ABSENT (NOT CAPTURED / age unknown), never `none-shown` and never an invented date. A field the
    payload already carries must agree with the item (one fact, stated once): a different value is
    an `error`, never a silent overwrite. An item with no `role` object (queued before 0.67.0)
    copies nothing and is not an error. `new_row` is mutated in place; `copied` names the fields."""
    import deferred as _deferred
    if item is None:
        try:
            items = {r.get("id"): r for r in _deferred.replay(_deferred.load())}
        except (OSError, ValueError) as e:
            return [], "the deferred queue cannot be read (%s)" % e
        item = items.get(item_id)
    if item is None:
        return [], ("no deferred item %r (`deferred.py --claimable` lists the pending ones)"
                    % item_id)
    if item.get("kind") != _deferred.KIND_CAPTURE:
        return [], ("deferred item %r is a %r item; --from-item takes a %r item"
                    % (item_id, item.get("kind"), _deferred.KIND_CAPTURE))
    copied = []
    # dev #751 (B7) -- a FEED item names the company-site channel it came from. It is copied into
    # sightings[0] when the JSON leaves it out, and a different channel the model supplies is
    # REFUSED: the channel is a recorded fact, so feed yield is measurable.
    feed_channel = item.get("channel_id")
    if feed_channel:
        sgs = new_row.get("sightings")
        first = sgs[0] if isinstance(sgs, list) and sgs and isinstance(sgs[0], dict) else None
        if first is not None:
            have_ch = first.get("channel_id")
            if have_ch and have_ch != feed_channel:
                return [], ("the JSON's sightings[0].channel_id is %s but deferred item %r came from "
                            "channel %s (the sweep or feed that queued it recorded it). One value, stated once: omit "
                            "sightings[0].channel_id and the script copies it."
                            % (json.dumps(have_ch), item_id, json.dumps(feed_channel)))
            if not have_ch:
                first["channel_id"] = feed_channel
                copied.append("sightings[0].channel_id")
    role = item.get("role")
    if not isinstance(role, dict):
        return copied, None
    wanted = []
    # dev #846 (0.88.0, design 3.1): a card's `none-shown` is never copied. `deferred.role_payload` stores none now; an item queued
    # by 0.87.0 and earlier still carries one, and a card showing no pay is not evidence the listing states none.
    card_pay = role.get("listed_pay")
    if card_pay is not None and not (isinstance(card_pay, dict) and card_pay.get("state") == "none-shown"):
        wanted.append(("listed_pay", role["listed_pay"]))
    if role.get("posted") is not None:
        wanted.append(("posted", role["posted"]))
    declared = role.get("location_declared")
    listed = role.get("location_listed")
    for field, value in wanted:
        if field == "listed_pay":
            value = dict(value, provenance="card")
        have_f = new_row.get(field)
        if field in new_row and _without_provenance(have_f) != _without_provenance(value):
            return [], ("the JSON carries %s=%s but deferred item %r says %s. One value, stated "
                        "once." % (field, json.dumps(new_row[field]), item_id, json.dumps(value)))
        if field not in new_row:
            new_row[field] = value
            copied.append(field)
        elif field == "listed_pay" and isinstance(have_f, dict) and "provenance" not in have_f:
            new_row[field] = dict(have_f, provenance="card")
    if declared is not None:
        loc = new_row.get("location")
        if loc is not None and not isinstance(loc, dict):
            return [], "the JSON's location is not an object; cannot add location.declared"
        have = (loc or {}).get("declared")
        if have is not None and have != declared:
            return [], ("the JSON carries location.declared=%s but deferred item %r says %s. One "
                        "value, stated once." % (json.dumps(have), item_id, json.dumps(declared)))
        if have is None:
            new_row["location"] = dict(loc or {}, declared=declared)
            copied.append("location.declared")
    if listed is not None:
        loc = new_row.get("location")
        if loc is not None and not isinstance(loc, dict):
            return [], "the JSON's location is not an object; cannot add location.primary"
        have = (loc or {}).get("primary")
        if have is not None and have != listed:
            return [], ("the JSON carries location.primary=%s but deferred item %r says %s. One "
                        "value, stated once: omit location.primary and the script copies it."
                        % (json.dumps(have), item_id, json.dumps(listed)))
        if have is None:
            new_row["location"] = dict(loc or {}, primary=listed)
            copied.append("location.primary")
    if declared == _deferred.SETTING_NONE_STATED:
        import places as _places
        loc = new_row.get("location")
        loc = loc if isinstance(loc, dict) else {}
        if "type" in loc:
            return [], ("the sweep read no setting on this posting (setting=\"none stated\"), so "
                        "location.type=%s would be a guess nobody can tell from a stated setting. "
                        "Omit location.type and the script infers it from the place (recorded as "
                        "location.setting_source: inferred); or create the row without it and then "
                        "replace the location with the JD's wording: `record.py set %s location "
                        "'<the whole location object, without setting_source>'` -- that write "
                        "records the overturn."
                        % (json.dumps(loc["type"]), rid or "<id>"))
        # dev #820 / public #175 (design section 3.1): a CARD never infers `onsite`. The place is recorded as the
        # card printed it, and `type` stays absent (legal beside `declared: none stated`) until the JD is read.
    loc = new_row.get("location")
    if isinstance(loc, dict) and (declared is not None or listed is not None):
        loc = dict(loc, provenance="card")
        if listed is not None and not loc.get("anchor_echo"):
            try:
                import profile as _pf_echo
                if _pf_echo.anchor_echo(listed, profile if profile is not None else _pf_echo.load()):
                    loc["anchor_echo"] = True
                    copied.append("location.anchor_echo")
            except (OSError, ValueError, KeyError):
                pass                    # an unreadable profile cannot say; the card is provisional all the same
        new_row["location"] = loc
        copied.append("location.provenance (card)")
    if "listed_pay" in copied:
        copied.append("listed_pay.provenance (card)")
    return copied, None


CAPTURE_USAGE = ("capture-batch --run <id> --link-only | --admitted [--deadline-s N] [--check] [--already-locked]")


class _ItemRefused(Exception):
    """One capture item (or the role it belongs to) is refused: the others still land."""


def _item_listings(item):
    """`[(url, location | None)]` the item is listed at: its address, then each sibling listing."""
    role = item.get("role") if isinstance(item.get("role"), dict) else {}
    out = []
    ref = item.get("ref")
    if isinstance(ref, str) and ref.strip():
        loc = role.get("location_listed")
        out.append((ref.strip(), loc if isinstance(loc, str) and loc.strip() else None))
    for s in item.get("siblings") or []:
        if isinstance(s, dict) and isinstance(s.get("url"), str) and s["url"].strip():
            loc = s.get("location")
            out.append((s["url"].strip(), loc if isinstance(loc, str) and loc.strip() else None))
    return out


def _item_seen_on(item):
    raw = str(item.get("queued_at") or "")[:10]
    try:
        return datetime.date.fromisoformat(raw).isoformat()
    except ValueError:
        return _now().date().isoformat()


def _sighting_catalog():
    """`(catalog or None, why-not or None)`: the shipped source catalog, for step 4 of `_item_channel_why`. An unreadable
    catalog is NOT an empty one: the reason is returned and the refusal says it (a missing thing must not read as "no board
    owns this host")."""
    import channel_catalog as _cc
    try:
        return _cc.load_catalog(), None
    except _cc.CatalogError as e:
        return None, str(e)


def _sighting_entries(host, catalog):
    """The `swept-board` catalog entries whose `sighting_hosts` domain-match `host`: a value matches itself and any
    subdomain of it (`board_hosts.host_matches`, RFC 6265 section 5.1.3), never another registrable domain.
    `check_channel_catalog.py` rule K7 keeps the answer to at most one; more than one here is a catalog defect and is
    treated as no answer."""
    import board_hosts as _bh
    out = []
    for e in (catalog or {}).get("entries") or []:
        if not (isinstance(e, dict) and e.get("kind") == "swept-board"):
            continue
        hosts = e.get("sighting_hosts")
        if isinstance(hosts, list) and any(_bh.host_matches(host, h) for h in hosts if isinstance(h, str)):
            out.append(e)
    return out


def _item_channel_why(item, channels, row=None, catalog=None):
    """dev #825 / public #176 -- `(channel_id, None)` or `(None, why)`: the channel a capture item's sighting is attributed
    to, or the reason none can be, with the FIX named. `catalog` is `_sighting_catalog()`'s pair (loaded here when None).
    In order:

      1. the channel the item itself names (a company-feed item, dev #751; every producer since dev #825), IF the profile
         holds a row with that id. An id the profile does not hold is REMEMBERED and resolution continues;
      2. the role's own channel (when the item is linked to a row);
      3. the one `board_hosts` names for the item's address (a `manual-candidate` board, dev #765);
      4. the `swept-board` catalog entry whose `sighting_hosts` domain-match the item's host, then the ONE live profile row
         linked to that entry (`channel_catalog_entry == entry.id`, or `id == entry.channel_id`). A `login`-access board
         such as LinkedIn can never carry `board_hosts` (that field means "the engine never opens this host"), so this is
         how its sightings are attributed;
      5. the ONE job-board or aggregator channel the profile holds, ONLY when step 1 named nothing and step 4 matched no
         entry. Evidence of a specific source is never overridden by guessing the only other board.

    Never a guess beyond that: an item that matches no channel is REFUSED (`capture-refused`), and the reason names the
    cause and what to do about it."""
    import board_hosts as _bh
    held = {c.get("id") for c in channels if isinstance(c, dict)}
    named = item.get("channel_id") or None
    if named and named in held:
        return named, None
    if row is not None:
        ch = row.get("channel_id") or next((s.get("channel_id") for s in (row.get("sightings") or [])
                                            if isinstance(s, dict) and s.get("channel_id")), None)
        if ch:
            return ch, None
    host = _bh.host_of(item.get("ref"))
    if host:
        for c in channels:
            hosts = c.get("board_hosts") if isinstance(c, dict) else None
            if isinstance(hosts, list) and any(_bh.host_matches(host, h) for h in hosts if isinstance(h, str)):
                return c.get("id"), None
    entries, cat_why, why = [], None, None
    if host:
        cat, cat_why = catalog if catalog is not None else _sighting_catalog()
        entries = _sighting_entries(host, cat) if cat is not None else []
    if len(entries) == 1:
        ent = entries[0]
        linked = [c for c in channels if isinstance(c, dict)
                  and (c.get("channel_catalog_entry") == ent.get("id") or c.get("id") == ent.get("channel_id"))]
        live = [c for c in linked if c.get("relationship_status") != "retired"]
        if len(live) == 1:
            return live[0].get("id"), None
        if len(live) > 1:
            why = ("the address is on %s and this profile links %d channel rows to it (%s): name the right one by hand "
                   "(`record.py create <id> '<json>' --from-item %s`), or close the item"
                   % (ent.get("label"), len(live), ", ".join(str(c.get("id")) for c in live), item.get("id")))
        elif linked:
            why = ("the address is on %s, whose channel row %s is turned off in this profile: turn it back on "
                   "(`record.py source on %s`) to capture it, or close the item"
                   % (ent.get("label"), linked[0].get("id"), linked[0].get("id")))
        else:
            why = ("the address is on %s, which this profile does not link: adopt that source to capture it "
                   "(`record.py source on %s`), or close the item" % (ent.get("label"), ent.get("id")))
    elif len(entries) > 1:
        why = ("the address host %s is claimed by %d catalog entries (%s): that is a catalog defect, report it, or close "
               "the item" % (host, len(entries), ", ".join(str(e.get("id")) for e in entries)))
    if why is None and named:
        why = ("the item was seen on channel %s, which this profile does not hold: adopt it (`record.py source on %s` for a "
               "catalog source, or `record.py channel-catalog add <entry> --attach <your channel id>` to tie a channel you "
               "already hold), or close the item" % (named, named))
    if why is not None:
        return None, why
    boards = [c.get("id") for c in channels if isinstance(c, dict)
              and c.get("type") in _validator_module().URL_BEARING_CHANNEL_TYPES
              and c.get("relationship_status") != "retired"]
    if len(boards) == 1:
        return boards[0], None
    if host:
        return None, ("the address host %s belongs to no known board: report the host if it is a board's (it may belong in "
                      "a catalog entry's sighting_hosts), or close the item; the profile holds %d board%s, so none is "
                      "assumed%s" % (host, len(boards), "" if len(boards) == 1 else "s",
                                     "" if cat_why is None else " (the source catalog could not be read: %s)" % cat_why))
    return None, ("the item names no channel, its address has no host to match, and the profile holds %d board%s: create "
                  "it by hand (`record.py create <id> '<json>' --from-item %s`) or close the item"
                  % (len(boards), "" if len(boards) == 1 else "s", item.get("id")))


def _from_item_resolved_channel(item_id):
    """dev #825 / public #176 -- `(item or None, error or None)` for `create --from-item <id>`: the capture item with its
    `channel_id` made to name a channel this profile HOLDS, or the reason it cannot be, with the fix named (the same
    wording `capture-batch` prints, `_item_channel_why`). `(None, None)` means "let `copy_capture_item_facts` look the
    item up itself" (no such item, a non-capture item, or an item that names no channel: its own refusals, unchanged), so
    this adds one refusal and no other behaviour. An item whose stamped channel the profile holds is returned as is."""
    import deferred as _deferred_mod
    item = _deferred_mod.load_capture_item(item_id)
    if item is None or not item.get("channel_id"):
        return None, None
    channels = _load_or_empty("channels")
    if item["channel_id"] in {c.get("id") for c in channels if isinstance(c, dict)}:
        return item, None
    channel, why = _item_channel_why(item, channels)
    if channel is None:
        return None, why
    return dict(item, channel_id=channel), None


def _item_channel(item, channels, row=None, catalog=None):
    """The channel `_item_channel_why` attributes the item to, or None (the reason is the other half of that pair)."""
    return _item_channel_why(item, channels, row, catalog)[0]


def _run_planned_items(recs, run):
    """The item ids the run's own `drain planned` event admitted, or None when the run has no plan."""
    planned = None
    for r in recs:
        if (r.get("event") == "drain" and r.get("phase") == "planned" and r.get("run_id") == run
                and not r.get("on_behalf_of")):
            planned = r
    if planned is None:
        return None
    adm = planned.get("admitted") or {}
    return set(adm.get("items") or [])


def _capture_code_list(item):
    """`capture.unverified` for an item: the distinct degraded codes it was quarantined for, else None."""
    q = item.get("quarantine")
    if not q:
        return None
    codes = []
    for c in (q.get("because") if isinstance(q, dict) else None) or []:
        if c in _validator_module().CAPTURE_UNVERIFIED_CODES and c not in codes:
            codes.append(c)
    if not codes:
        raise _ItemRefused("the item is quarantined but names no degraded code the capture record can carry")
    return codes


def _same_listing(url, row):
    import pipeline_index as _pidx
    have = [row.get("jd_url")] + [s.get("source_url") for s in (row.get("sightings") or [])
                                  if isinstance(s, dict) and not s.get("split_to")]
    return any(h and _pidx._urls_equal(url, h) for h in have)


def cmd_capture_batch(args):
    """`record.py capture-batch` -- see the section comment above. Exit 0 when every item was landed or is waiting (a
    deadline is not a fault: run it again), 4 when any item was refused (the others still landed), 1 when a store could
    not be read or the write was rolled back, 2 on usage."""
    import time
    if args.rid or args.rest:
        print("usage: " + CAPTURE_USAGE)
        return 2
    run = (args.run_id_arg or "").strip()
    if not run or re.search(r"\s", run):
        print("⛔ REFUSED — --run <run id> is required (no whitespace).\nusage: " + CAPTURE_USAGE)
        return 2
    if bool(args.link_only) == bool(args.admitted):
        print("⛔ REFUSED — exactly one of --link-only and --admitted.\nusage: " + CAPTURE_USAGE)
        return 2
    deadline_s = CAPTURE_DEADLINE_S_DEFAULT if args.deadline_s is None else args.deadline_s
    if deadline_s < 0:
        print("⛔ REFUSED — --deadline-s must be 0 or more.")
        return 2
    check = bool(args.check or args.dry_run)
    phase = "admitted" if args.admitted else "link-only"
    t0 = time.monotonic()

    if not check:
        if args.already_locked:
            if not lock_is_held():
                print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
                return 1
        else:
            try:
                take_lock("record.py capture-batch --run %s --%s" % (run, phase), wait=args.wait)
            except LockError as e:
                print("  REFUSED — %s" % e)
                return 1
    try:
        import deferred as _deferred
        import journal as _journal
        try:
            # the stores are read HERE, inside the lock (once each), and handed down: nothing below reads a store again
            stores = {"opps": load("opportunities"), "companies": load("companies"),
                      "apps": _load_or_empty("applications"), "channels": _load_or_empty("channels"),
                      "items": _deferred.replay(_deferred.load()), "recs": _journal.read(_paths.ROOT),
                      "profile": _profile_mod().load()}
        except (OSError, ValueError, _journal.JournalError) as e:
            print("⛔ REFUSED — a store cannot be read (%s); nothing written." % e)
            return 1
        return _capture_batch_locked(args, run, phase, deadline_s, check, t0, stores)
    finally:
        if not check and not args.already_locked:
            release_lock()


def _capture_batch_locked(args, run, phase, deadline_s, check, t0, stores):
    import time
    import deferred as _deferred
    import journal as _journal
    import lifecycle as _lc
    import pipeline_index as _pidx
    import profile as _pf
    opps, companies = stores["opps"], stores["companies"]
    applications, channels = stores["apps"], stores["channels"]
    items, recs, profile = stores["items"], stores["recs"], stores["profile"]
    open_items = sorted((i for i in items if i.get("kind") == _deferred.KIND_CAPTURE and i.get("status") == "pending"),
                        key=lambda i: (str(i.get("queued_at") or ""), str(i.get("id"))))
    admitted = None
    if phase == "admitted":
        admitted = _run_planned_items(recs, run)
        if admitted is None:
            print("⛔ REFUSED — run %r has no `drain planned` event: run `lifecycle.py --drain-plan --run %s "
                  "--render-route yes|no` first (it decides which roles this run admits); nothing written."
                  % (run, run))
            return 1
    idx = _lc.RoleIndex(opps, companies)
    opps_by_id = {o.get("id"): o for o in opps}
    created_by_item = {o["capture"]["item"]: o for o in opps
                       if isinstance(o.get("capture"), dict) and o["capture"].get("item")}
    keys = {i["id"]: idx.key(i) for i in open_items}
    considered = [i for i in open_items if phase == "link-only" or i["id"] in admitted]
    engine, now = _engine_version(), _now()
    on, at_iso = now.date(), now.isoformat()
    owner = _pf.owner_token()
    plan_cache = []
    catalog = _sighting_catalog()                  # dev #825: read once; an unreadable one is said in the refusal

    state = {"created": 0, "linked": 0, "folded": 0, "refused": 0, "nearer": 0, "unverified": 0}
    closes = []                                    # [(item id, closed_as)]
    refused_ids = []                               # item ids a gap is filed for
    reasons = {}
    changed_before = {}                            # opp id -> deepcopy before this call touched it
    new_companies, new_opps = [], []
    skipped = []

    def _not_a_target(item):
        """dev #834 (design-network-first.md 3.1): True when the item's company is NOT an `active-target` company, so the
        sighting is recorded before the plan and its read, screen and research wait. A company the store does not know yet is
        not a target (capture will make it, `watching`). A name that matches SEVERAL companies is left to the plan: `create`
        refuses it either way, and a refusal every run before anyone is admitted would only add noise."""
        name, _title = _lc.item_company_title(item)
        if not name:
            return False
        hits = _pidx.company_candidates(name, companies)
        if len(hits) > 1:
            return False
        if not hits:
            return True
        return next(c for c in companies if c.get("id") == hits[0]).get("status") != "active-target"

    def refuse(item_ids, why):
        state["refused"] += len(item_ids)
        for iid in item_ids:
            refused_ids.append(iid)
            reasons[iid] = why
        print("REFUSED %s: %s" % (", ".join(item_ids), why))

    def touch(row):
        changed_before.setdefault(row["id"], json.loads(json.dumps(row)))

    def link(item, row):
        """Join `item`'s listings onto `row`; close it. Returns 'linked' | 'folded' | 'nearer'."""
        kind = "excluded" if _pidx.is_excluded(row) else "active"
        listings = _item_listings(item)
        basis = "url" if any(_same_listing(u, row) for u, _l in listings) else "company + title"
        if kind == "excluded" and basis != "url":
            try:
                nearer, place, st = _pf.nearer_listing(_pidx.listing_places(row), [l for _u, l in listings if l],
                                                        profile)
            except (OSError, ValueError, KeyError):
                nearer, place, st = False, None, None
            if nearer:
                print("NEARER LISTING of passed %s: %s (%s) -- %s stays open, a fresh decision" %
                      (row["id"], place, st, item["id"]))
                return "nearer"
        todo = [(u, l) for u, l in listings if not _same_listing(u, row)]
        if todo:
            channel, why = _item_channel_why(item, channels, row, catalog)
            if not channel:
                raise _ItemRefused("no channel can be named for the sighting of %s: %s" % (item["id"], why))
            touch(row)
            seen_on = _item_seen_on(item)
            have = set()
            for u, l in todo:
                if u in have:
                    continue
                have.add(u)
                sg = {"channel_id": channel, "seen_on": seen_on, "source_url": u}
                if l:
                    sg["location"] = l
                row.setdefault("sightings", []).append(sg)
        owned = isinstance(row.get("capture"), dict) and row["capture"].get("item") == item["id"]
        closes.append((item["id"], ("created:%s" if owned else "linked:%s") % row["id"]))
        if owned:
            return "created"
        return "linked" if basis == "url" else "folded"

    def plan_id_for_new():
        if not plan_cache:
            plan_cache.append(_new_opportunity_plan(None))
        plan_id, err = plan_cache[0]
        if not plan_id:
            raise _ItemRefused(err or "no active search plan sources role/contract, so a new role has no plan_id")
        return plan_id

    def create(group):
        """Create the role of a group of sibling items (oldest first); returns the new row."""
        item = group[0]
        company_name, title = _lc.item_company_title(item)
        if not (company_name and title):
            raise _ItemRefused("the item's text names no company and title (%r)" % str(item.get("what"))[:80])
        listings = _item_listings(item)
        if not listings:
            raise _ItemRefused("the item carries no address")
        channel, why = _item_channel_why(item, channels, None, catalog)
        if not channel:
            raise _ItemRefused("no channel can be named for the sighting: %s" % why)
        unverified = _capture_code_list(item)
        plan_id = plan_id_for_new()
        hits = _pidx.company_candidates(company_name, companies)
        if len(hits) > 1:
            raise _ItemRefused("the company %r matches %d companies (%s); name the right one by hand"
                               % (company_name, len(hits), ", ".join(hits)))
        new_company = None
        if hits:
            company_id = hits[0]
        else:
            company_id = _slug(company_name)
            if not company_id:
                raise _ItemRefused("the company %r has no letters or digits to make an id from" % company_name)
            taken_c = {c.get("id") for c in companies}
            base_c, n = company_id, 1
            while company_id in taken_c:
                n += 1
                company_id = "%s-%d" % (base_c, n)
            new_company = {"id": company_id, "name": company_name.strip(), "vertical": "other",
                           "status": "watching", "research_log": []}
        taken = {o.get("id") for o in opps}
        base = _slug("%s-%s" % (company_id, title)) or _slug(company_id) or "role"
        opp_id, n = base, 1
        while opp_id in taken:
            n += 1
            opp_id = "%s-%d" % (base, n)
        seen_on = _item_seen_on(item)
        sightings = []
        for pos, (u, l) in enumerate(listings):
            sg = {"channel_id": channel, "seen_on": seen_on, "source_url": u}
            if pos and l:
                sg["location"] = l
            sightings.append(sg)
        for sib in group[1:]:                                   # the siblings' listings join the same role
            for u, l in _item_listings(sib):
                if not any(_pidx._urls_equal(u, s["source_url"]) for s in sightings):
                    sg = {"channel_id": channel, "seen_on": _item_seen_on(sib), "source_url": u}
                    if l:
                        sg["location"] = l
                    sightings.append(sg)
        new_row = {"id": opp_id, "company_id": company_id, "title": title, "status": "backlog", "stage": "sourced",
                   "verdict": "undecided", "jd_url": listings[0][0], "location": {}, "sightings": sightings,
                   "next_action_owner": owner, "plan_id": plan_id, "plan_assigned_on": on.isoformat()}
        _copied, err = copy_capture_item_facts(new_row, item["id"], rid=opp_id, item=item, profile=profile)
        if err:
            raise _ItemRefused(err)
        loc = new_row.get("location") if isinstance(new_row.get("location"), dict) else {}
        loc = dict(loc)
        loc.setdefault("declared", "none stated")             # a card that read no setting states none
        loc.setdefault("provenance", "card")
        if "type" not in loc and loc["declared"] != "none stated":
            loc["type"] = type_from_setting(loc["declared"], loc.get("primary"))[0] or "unresolved"
            loc["remote"] = loc["type"] == "remote"
        new_row["location"] = loc
        cap = {"run": run, "at": at_iso, "item": item["id"]}
        if unverified:
            cap["unverified"] = unverified
        new_row["capture"] = cap
        feed_written = False
        if str(item.get("source") or "").startswith("feed:"):
            try:
                value, ferr = _feed_posting_value(item, new_row, on, channels=channels)
            except _Refused as e:
                raise _ItemRefused(str(e))
            if ferr:
                raise _ItemRefused(ferr)
            if value is not None:
                new_row[_POSTING_FIELD] = value
                feed_written = True
        # the new row is in the lists before it is screened and checked, and OUT of them again if either refuses
        if new_company is not None:
            companies.append(new_company)
        opps.append(new_row)
        try:
            _store_screen(new_row, on, engine, profile=profile, all_opps=opps, applications=applications,
                          channels=channels)
            bad = _row_checks("capture-batch", None, new_row, posting_ok=feed_written)
            if bad:
                raise _ItemRefused("; ".join(bad))
        except BaseException:
            opps.remove(new_row)
            if new_company is not None:
                companies.remove(new_company)
            raise
        if new_company is not None:
            new_companies.append(new_company)
        new_opps.append(new_row)
        opps_by_id[opp_id] = new_row
        if unverified:
            state["unverified"] += 1
        return new_row

    # ---- walk the items: units are a role's items (new roles, grouped by key) or one item (a known role) ----
    groups = []
    seen_groups = {}
    for item in considered:
        iid = item["id"]
        if iid in created_by_item:                              # a rerun after a kill between the stores
            row = created_by_item[iid]
            closes.append((iid, "created:%s" % row["id"]))
            state["created"] += 1
            continue
        k = keys[iid]
        if k in opps_by_id and not k.startswith("item:"):
            groups.append(("known", opps_by_id[k], [item]))
        elif phase == "admitted" or (phase == "link-only" and _not_a_target(item)):
            # dev #834 (0.86.0): a sighting at a company that is not `active-target` is RECORDED here, before the plan, as an
            # ordinary role (`held-for-company` until the company is targeted); it consumes no intake
            if k not in seen_groups:
                members = [i for i in open_items if keys[i["id"]] == k and i["id"] not in created_by_item]
                seen_groups[k] = ("new", None, members)
                groups.append(seen_groups[k])
    for kind, row, members in groups:
        if time.monotonic() - t0 >= deadline_s:
            skipped += [i["id"] for i in members]            # between roles, never inside one
            continue
        ids = [i["id"] for i in members]
        before_opps, before_cos, n_changed = len(new_opps), len(new_companies), len(changed_before)
        mark = len(closes)
        try:
            if kind == "known":
                res = link(members[0], row)
                if res == "nearer":
                    state["nearer"] += 1
                else:
                    state[res] += 1
            else:
                new_row = create(members)
                closes.append((members[0]["id"], "created:%s" % new_row["id"]))
                for sib in members[1:]:
                    closes.append((sib["id"], "linked:%s" % new_row["id"]))
                state["created"] += 1
                print("CREATED %s from %s%s" % (new_row["id"], members[0]["id"],
                                                (" (+%d sibling item(s))" % (len(members) - 1)) if len(members) > 1
                                                else ""))
        except _ItemRefused as e:
            del closes[mark:]
            refuse(ids, str(e))
        except (KeyError, ValueError, OSError) as e:
            del closes[mark:]
            refuse(ids, "%s: %s" % (type(e).__name__, " ".join(str(e).split())[:200]))
    closed_ids = {iid for iid, _c in closes}
    remaining = [i for i in open_items if i["id"] not in closed_ids]
    waiting_roles = len({keys[i["id"]] for i in remaining})
    nconsidered = len(considered)
    deadline_left = len(skipped)
    unreached = [i for i in skipped if admitted is not None and i in admitted]

    # ---- nothing written under --check; otherwise: validate, write once per store, then the append-only records ----
    rc = 0
    if check:
        if new_opps or changed_before:
            rc_v, out_v, err_v, problems = dry_run_validate("opportunities", opps, extra={"companies": companies})
            pre = validate()[3]
            added = new_problems(pre, problems) if rc_v != 0 else []
            if rc_v != 0 and (added is None or added):
                print("  ⛔ a REAL (non-dry-run) write of this would be REFUSED and rolled back.")
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out_v, err_v)))
                return 1
        print("  --check: nothing written.")
    else:
        if new_opps or changed_before:
            for oid, before in changed_before.items():
                bad = _row_checks("capture-batch", before, opps_by_id[oid])
                if bad:
                    print("⛔ REFUSED — %s: %s (nothing written)" % (oid, "; ".join(bad)))
                    return 1
            snap_o, snap_c = snapshot("opportunities"), snapshot("companies")
            pre_problems = validate()[3]
            if new_companies:
                save_atomic("companies", companies)
            save_atomic("opportunities", opps)
            rc_v, out_v, err_v, post_problems = validate()
            added = new_problems(pre_problems, post_problems)
            if rc_v != 0 and (added is None or added):
                ok_o = restore("opportunities", snap_o)
                ok_c = restore("companies", snap_c) if new_companies else True
                print("⛔ the write left the stores invalid and was %s."
                      % ("ROLLED BACK (byte-identical)" if ok_o and ok_c
                         else "NOT VERIFIABLY ROLLED BACK -- restore companies.jsonl and opportunities.jsonl "
                              "from git"))
                print("  " + "\n  ".join(added if added else _diagnostic_lines(rc_v, out_v, err_v)))
                return 1
        for iid, closed_as in closes:
            _deferred.close_item(iid, closed_as)
        open_scopes = {g.get("scope") for g in _journal.open_gaps(recs, run)}
        for iid in refused_ids:
            scope = "jobsearch:capture-item:%s" % iid
            if scope in open_scopes:
                continue
            try:
                _journal.record_gap(_paths.ROOT, run, scope, "other", closes_when="captured")
            except _journal.JournalError as e:
                print("⚠️ could not journal the gap %s (%s)" % (scope, e))
                rc = 1
        if phase == "admitted":
            try:
                _journal.record_pass(_paths.ROOT, run, "capture", "done", unreached=sorted(unreached))
            except _journal.JournalError as e:
                print("⚠️ could not journal `pass capture done` (%s): drain-close cannot name a deadline-reached "
                      "role without it" % e)
                rc = 1
    import handback as _handback
    if state["refused"]:
        verdict = _handback.verdict_line("line-faults", state["refused"],
                                         len(unreached) if unreached else None)
    elif deadline_left:
        verdict = _handback.verdict_line("incomplete", detail=deadline_left)
    else:
        verdict = _handback.verdict_line("clean")
    print(verdict)
    print("capture-batch: %d items -> %d created · %d linked · %d folded · %d refused · %d waiting · "
          "%d unverified-source%s · %d deadline-left"
          % (nconsidered, state["created"], state["linked"], state["folded"], state["refused"], waiting_roles,
             state["unverified"], (" · %d nearer" % state["nearer"]) if state["nearer"] else "", deadline_left))
    print("deadline-left %d" % deadline_left)
    if rc:
        return rc
    return EXIT_ITEM_REFUSED if state["refused"] else 0
