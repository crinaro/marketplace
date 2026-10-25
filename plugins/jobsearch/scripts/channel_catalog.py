#!/usr/bin/env python3
"""channel_catalog.py -- the shipped catalog of job SOURCES, and how a profile opts in to it
(dev #769 / public #164 and dev #774, jobsearch 0.76.0; docs/design-source-catalog.md as amended by its
review, which supersedes the boards-only scope of docs/design-channel-catalog.md and reuses every mechanism
below).

WHAT IT IS
----------
`channel_catalog/channel_catalog.json` (next to `scripts/`, shipped read-only engine data) lists the sources a
job search can use, verified once, centrally, so every install does not research them alone. Every entry has a
`kind`, and the kind decides what opting in writes and what is managed afterwards:

    portfolio     an investment firm's portfolio board; a channel row plus the firm's company row
    curated       a startup board with no firm behind it; a channel row
    swept-board   a board a browser reads (LinkedIn job search, Indeed): a channel row; allowed only where
                  its `terms.ruling` is `permits`, `owner-carve-out` or `owner-ruled` (ADR-037)
    alert-sender  a job-alert email swept from the user's OWN mailbox; a channel row of type alert-email
    feed-policy   the company-feed poller as one switch; NO row, a config key (`sourcing.feeds.enabled`)

`portfolio` and `curated` entries are `access: manual-candidate` (ADR-037): the candidate opens them, the
engine never does.

A source reaches a profile only when it is turned ON: `record.py source on <entry>` (or `channel-catalog add`),
which COPIES the entry into `data/channels.jsonl` and stamps the row (the `plays.py --adopt` copy-and-stamp
mechanism, reused). A NEW install gets the owner's defaults once, from init_profile.py (the only reader of an
entry's `default_on`); an existing install is never given a source (the plugin manifest's `defaultEnabled` rule).

    channel_catalog_entry   the catalog entry id the row came from
    channel_catalog_sha     12 hex: the sha of the entry's MANAGED projection as last applied/acknowledged
    channel_catalog_on      the ISO date of that apply or acknowledgement
    channel_catalog_rev     the catalog `revision` that wrote the stamp (R1: an ORDERING, not only a hash)

The managed projection is per kind (`PROJECTION_FIELDS`), plus the retired bit:

    curated, portfolio   {label, type, access, board_url, board_hosts (sorted, lower-case), retired}
    swept-board          {label, type, access, query_template, retired}
    alert-sender         {label, type, access, alert_sender, retired}

Everything else on the row (cadence, last_reviewed, scope_notes, log, next_touch, portfolio_of, and the
`alert_sender` FACET of a board) belongs to the user from the moment it is written, so reviewing a board never
makes it "edited". "Edited" is DERIVED (row projection vs stamp), never stored.

THE RECONCILE (`reconcile()`, run by migrate.py --hook; the catalog update reaches an install as a VERSION)
-----------------------------------------------------------------------------------------------------
Each stamped row is classified three ways (dpkg's conffile rules): r = row, s = its stamped sha,
e = the entry in THIS engine's catalog, rev = this catalog's `revision`.

    unstamped  no stamp                                 never read further: a user's own row
    unreadable a partial or malformed stamp             never touched (the validator names it)
    ahead      stamp rev > this catalog's revision      another, newer engine wrote it: do NOTHING
    orphaned   the entry is not in this catalog         ask, change nothing
    off        relationship_status == retired           never touched (turned off, or already retired)
    ok         sha(r) == s == sha(e)                    nothing
    converged  sha(r) == sha(e) != s                    the user made exactly the new values: restamp
    stale      sha(r) == s != sha(e)                    APPLY: log the old values in the row's log, write
                                                        the entry's, restamp, report
    edited     sha(r) != s == sha(e)                    nothing (the user's change stays)
    conflict   all three differ                         ask naming each differing field; change nothing

R1, THE ORDERING (settles review B1): two engines on different versions share one profile (remote mode,
a second machine, a synced copy) and a content hash alone has no direction, so each would undo the
other every session. Every WRITE here (apply, restamp, ask) happens only when this catalog's revision is
STRICTLY GREATER than the row's stamped one; a stamp from a newer revision is `ahead` and is left
byte-identical. `take` and `keep` refuse an `ahead` row. A catalog change that does not raise the
revision is `unrevised`: nothing is written (the shape gate refuses that change at release).

A new catalog entry is NEVER added to a profile by the reconcile: it is OFFERED (`offer()`, which
`sources.py` prints under "You could turn on").

ADOPTION (dev #774, jobsearch 0.76.0; `adoption_plan()`, run by migrate.py's `m_0_76_0_source_adoption`)
-------------------------------------------------------------------------------------------------------
A hand-made row is stamped ONLY when it matches EXACTLY a template the plugin itself once told users to paste
(Debian ucf: an unmodified file is adopted, nobody is asked). Each `curated` / `portfolio` entry carries
`shipped_templates`, each item EMBEDDING the template's match projection and its sha (review B3: the migration
runs from an installed copy with no git history, so it compares against the embedded value, never against a tag;
`check_channel_catalog.py` G11 recomputes the embedded value from the tagged text). Exact: the stamp is written
with the TEMPLATE's sha and `ADOPTED_REV`, so the next reconcile sees the row as `stale` when the template is
older than the entry and applies the change through the normal logged and reported path. Near: one ask, no
write. No match: untouched.

Usage:
    python3 channel_catalog.py --check        # read-only: the state of every stamped row

Python 3.9+. Standard library only. No network. The maintainers' shape gate is a separate script that
never ships to an install; the procedure for changing the catalog is in that gate's docstring.
"""

import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _root                                                         # noqa: E402
import board_hosts as _bh                                            # noqa: E402
import portfolio_boards as _pb                                       # noqa: E402

SCHEMA = 1
CATALOG_REL = os.path.join("channel_catalog", "channel_catalog.json")
# TEST SEAM, in the family of CLAUDESEARCH_LOCK_PATH / CLAUDESEARCH_DIAG_LOG: the regression suite points this
# at a catalog it DERIVED in a scratch directory (a later revision, a retired entry), because the shipped file
# is read-only to every test and a state like `stale` cannot be reached from the shipped revision alone. Unset in a
# real install; the shape gate and the CLI honour it identically.
CATALOG_PATH = (os.environ.get("CLAUDESEARCH_CHANNEL_CATALOG")
                or os.path.join(_root.engine_root(), CATALOG_REL))

KINDS = ("swept-board", "alert-sender", "feed-policy", "curated", "portfolio")
ROW_KINDS = ("swept-board", "alert-sender", "curated", "portfolio")     # kinds that write a channels row
BOARD_KINDS = ("curated", "portfolio")                                  # manual-candidate boards
# what `load_catalog` needs of an entry to use it at all; the maintainers' gate (check_channel_catalog.py) owns
# the full shape, so a rule about a key this module never reads lives there
RUNTIME_REQUIRED = {
    "portfolio": ("channel_id", "access", "board_url", "board_hosts", "firm", "review_cadence", "scope_notes"),
    "curated": ("channel_id", "access", "board_url", "board_hosts", "review_cadence", "scope_notes"),
    "swept-board": ("channel_id", "type", "access", "query_template", "review_cadence", "scope_notes"),
    "alert-sender": ("channel_id", "type", "access", "alert_sender", "review_cadence", "scope_notes"),
    "feed-policy": ("config_key", "vendors"),
}
FIRM_KEYS = ("id", "name", "domain")
STAMP_FIELDS = ("channel_catalog_entry", "channel_catalog_sha", "channel_catalog_on", "channel_catalog_rev")
# the managed projection per kind (the retired bit is added to every one). `curated` and `portfolio` are
# BYTE-IDENTICAL to the boards-only build, so no sha an earlier build computed moves.
PROJECTION_FIELDS = {
    "curated": ("label", "type", "access", "board_url", "board_hosts"),
    "portfolio": ("label", "type", "access", "board_url", "board_hosts"),
    "swept-board": ("label", "type", "access", "query_template"),
    "alert-sender": ("label", "type", "access", "alert_sender"),
}
CALENDAR_CADENCES = ("daily", "weekly", "biweekly", "monthly")
ENTRY_TYPE = "job-board"
ALERT_TYPE = "alert-email"
SOURCE_TYPES = ("job-board", "aggregator", "alert-email")               # the channel types that are sources
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CHANNEL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?::[a-z0-9]+(?:-[a-z0-9]+)*)?$")
SHA_RE = re.compile(r"^[0-9a-f]{12}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ASK_PREFIX = "channel-catalog:"
ADOPT_ASK_PREFIX = "source-adopt:"
# states for which the reconcile WRITES something, and so needs a strictly newer revision (R1)
WRITING_STATES = ("orphaned", "converged", "stale", "conflict")
# The revision an ADOPTED hand row is stamped with. A row adopted from a template the plugin shipped before any
# catalog existed is, by definition, older than every catalog; stamping it with the catalog's own revision would
# make the strictly-newer rule (R1) leave a `stale` row inert until the NEXT revision. The catalog ships at
# revision 2 (revision 1 was the unreleased boards-only build) so the baseline is a real, lower revision.
ADOPTED_REV = 1
FEEDS_ENTRY_ID = "company-feeds"

_LEGACY_ACCESS = {"login-chrome": "login", "public-bot-limited": "bot-limited"}   # route.py's own LEGACY mapping


class CatalogError(ValueError):
    """The catalog cannot be read. Loud by design: an unreadable catalog is never an empty one."""


class Refused(Exception):
    """A planned change that must not be made; nothing is written. `.args[0]` is the reason."""


class PriorUnreadable(ValueError):
    """`prior_relationship_status` is present and not one of its two legal shapes (R2)."""


def _real_date(value):
    if not (isinstance(value, str) and ISO_RE.match(value)):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_rev(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def norm_access(raw):
    """`access` with the two legacy spellings read as their modern requirement (route.py's own mapping)."""
    return _LEGACY_ACCESS.get(raw, raw) if isinstance(raw, str) else raw


def stamp_problems(row):
    """Why a row's `channel_catalog_*` stamp is unreadable, as a list of reasons (empty when the row carries no
    stamp at all, or a well-formed one). `validate_data.check_channel_catalog_fields` is the caller; the
    definition of "well formed" lives here, once."""
    present = [k for k in STAMP_FIELDS if k in row]
    if not present:
        return []
    out = []
    missing = [k for k in STAMP_FIELDS if k not in row]
    if missing:
        out.append("the four channel_catalog_* fields are all present or all absent; missing %s"
                   % ", ".join(missing))
    if "channel_catalog_entry" in row and not (isinstance(row["channel_catalog_entry"], str)
                                               and SLUG_RE.match(row["channel_catalog_entry"])):
        out.append("channel_catalog_entry must be a catalog entry id (a lower-case slug) -- %r"
                   % (row["channel_catalog_entry"],))
    if "channel_catalog_sha" in row and not (isinstance(row["channel_catalog_sha"], str)
                                             and SHA_RE.match(row["channel_catalog_sha"])):
        out.append("channel_catalog_sha must be 12 lower-case hex characters -- %r" % (row["channel_catalog_sha"],))
    if "channel_catalog_on" in row and not _real_date(row["channel_catalog_on"]):
        out.append("channel_catalog_on must be an ISO date -- %r" % (row["channel_catalog_on"],))
    if "channel_catalog_rev" in row and not _is_rev(row["channel_catalog_rev"]):
        out.append("channel_catalog_rev must be a positive integer -- %r" % (row["channel_catalog_rev"],))
    return out


# ---- the prior status of a turned-off row (R2) -------------------------------------------------------

def encode_prior(row):
    """The value `prior_relationship_status` takes when `row` is turned off, from the row as it is NOW.

    The key-absent versus null rule (R2): a row can lack `relationship_status` altogether, or carry it as null
    (the fixture's shape), or carry a string. Those are three different bytes, and `source on` must put back
    exactly what `source off` found. So the field is an object, never the bare value:

        {"had": false}                       the row had no `relationship_status` key
        {"had": true, "value": null | str}   it had one, with this value

    It is NEVER read from the free-text `log`."""
    if "relationship_status" not in row:
        return {"had": False}
    return {"had": True, "value": row["relationship_status"]}


def read_prior(row):
    """`None` when the row records no prior status; else the stored dict. Raises `PriorUnreadable` for any other
    shape: the strict reader (R2). `source on` refuses (exit 2) on it, and `validate_data` reports it."""
    if "prior_relationship_status" not in row:
        return None
    v = row["prior_relationship_status"]
    if not isinstance(v, dict) or set(v) not in ({"had"}, {"had", "value"}) or not isinstance(v.get("had"), bool):
        raise PriorUnreadable("prior_relationship_status must be {\"had\": false} or {\"had\": true, \"value\": "
                              "<string|null>} -- %r" % (v,))
    if v["had"] is False and "value" in v:
        raise PriorUnreadable("prior_relationship_status says the row had no status but carries a value -- %r" % (v,))
    if v["had"] is True and ("value" not in v or not (v["value"] is None or isinstance(v["value"], str))):
        raise PriorUnreadable("prior_relationship_status says the row had a status but its value is not a "
                              "string or null -- %r" % (v,))
    return dict(v)


def prior_problems(row):
    """validate_data's one question about the field: [] when absent or readable, else the reason."""
    try:
        read_prior(row)
    except PriorUnreadable as e:
        return [str(e)]
    return []


# ---- reading the catalog --------------------------------------------------------------------------

def load_catalog(path=None):
    """The parsed catalog, or `CatalogError`. Checks only what THIS module reads; the maintainers' gate
    (`check_channel_catalog.py`) is the full shape check."""
    path = path or CATALOG_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as e:
        raise CatalogError("cannot read the channel catalog (%s)" % type(e).__name__)
    except ValueError as e:
        raise CatalogError("the channel catalog is not valid JSON (%s)" % e)
    if not isinstance(doc, dict) or doc.get("channel_catalog") != SCHEMA:
        raise CatalogError("the channel catalog is not schema %d" % SCHEMA)
    if not _is_rev(doc.get("revision")):
        raise CatalogError("the channel catalog has no positive integer `revision`")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise CatalogError("the channel catalog has no `entries` list")
    seen = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise CatalogError("entries[%d] is not an object" % i)
        missing = [k for k in ("id", "kind", "label") if k not in e]
        if missing:
            raise CatalogError("entries[%d] lacks %s" % (i, ", ".join(missing)))
        if e["kind"] not in KINDS:
            raise CatalogError("entries[%d] (%s) has kind %r; the kinds are %s" % (i, e["id"], e["kind"], ", ".join(KINDS)))
        missing = [k for k in RUNTIME_REQUIRED[e["kind"]] if k not in e]
        if missing:
            raise CatalogError("entries[%d] (%s, %s) lacks %s" % (i, e["id"], e["kind"], ", ".join(missing)))
        if e["id"] in seen:
            raise CatalogError("entry id %r appears twice" % e["id"])
        seen.add(e["id"])
    return doc


def by_id(catalog):
    return {e["id"]: e for e in catalog["entries"]}


def is_retired(entry):
    return entry.get("retired") is not None


def entry_type(entry):
    """The channel `type` an entry writes."""
    if entry.get("kind") == "alert-sender":
        return ALERT_TYPE
    if entry.get("kind") == "swept-board":
        return entry.get("type") or ENTRY_TYPE
    return ENTRY_TYPE


# ---- the managed projection and its sha -----------------------------------------------------------

def _norm_hosts(hosts):
    if isinstance(hosts, list):
        return sorted(h.lower() for h in hosts if isinstance(h, str))
    return hosts


def managed_fields(kind):
    """The fields the catalog manages on a row of `kind`, retired bit included."""
    return PROJECTION_FIELDS[kind] + ("retired",)


def _value(source, field, kind, is_entry):
    if field == "type" and is_entry:
        return entry_type(source)
    if field == "board_hosts":
        return _norm_hosts(source.get(field))
    if field == "access":
        return norm_access(source.get(field)) if is_entry else source.get(field)
    return source.get(field)


def entry_kind(entry):
    """An entry's kind. An entry of the unreleased boards-only layout names it `category`; reading both lets the
    revision rule (G10) compare against a previous catalog written either way."""
    return entry.get("kind") or entry.get("category")


def entry_projection(entry):
    kind = entry_kind(entry)
    if kind == "feed-policy":                        # writes no row: what the poller's switch means is the projection
        return {"vendors": sorted(entry.get("vendors") or []), "config_key": entry.get("config_key"),
                "retired": is_retired(entry)}
    out = {f: _value(entry, f, kind, True) for f in PROJECTION_FIELDS[kind]}
    out["retired"] = is_retired(entry)
    return out


def row_projection(row, kind="curated"):
    out = {f: _value(row, f, kind, False) for f in PROJECTION_FIELDS[kind]}
    out["retired"] = row.get("relationship_status") == "retired"
    return out


def projection_sha(projection):
    blob = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def entry_sha(entry):
    return projection_sha(entry_projection(entry))


def row_sha(row, kind="curated"):
    return projection_sha(row_projection(row, kind))


# ---- the state of a stamped row (the three-way table) ---------------------------------------------

def has_stamp(row):
    return any(k in row for k in STAMP_FIELDS)


def stamp_well_formed(row):
    return has_stamp(row) and not stamp_problems(row)


def row_state(row, entries, cat_rev):
    """One of: unstamped unreadable ahead orphaned off ok converged stale edited conflict."""
    if not has_stamp(row):
        return "unstamped"
    if not stamp_well_formed(row):
        return "unreadable"
    if row["channel_catalog_rev"] > cat_rev:
        return "ahead"
    entry = entries.get(row["channel_catalog_entry"])
    if entry is None:
        return "orphaned"
    if row.get("relationship_status") == "retired":
        return "off"
    if entry["kind"] not in PROJECTION_FIELDS:
        return "orphaned"                    # a feed-policy entry writes no row: a stamp naming one is not ours
    s, sr, se = row["channel_catalog_sha"], row_sha(row, entry["kind"]), entry_sha(entry)
    if sr == s == se:
        return "ok"
    if sr == se:
        return "converged"
    if sr == s:
        return "stale"
    if s == se:
        return "edited"
    return "conflict"


def _differences(row, entry):
    """[(field, row value, entry value)] for each managed field on which the row and the entry differ."""
    kind = entry["kind"]
    rp, ep = row_projection(row, kind), entry_projection(entry)
    return [(k, rp[k], ep[k]) for k in managed_fields(kind) if rp[k] != ep[k]]


def _stamp(row, entry, catalog, today):
    row["channel_catalog_entry"] = entry["id"]
    row["channel_catalog_sha"] = entry_sha(entry)
    row["channel_catalog_on"] = today
    row["channel_catalog_rev"] = catalog["revision"]


def _write_managed(row, entry):
    for f in PROJECTION_FIELDS[entry["kind"]]:
        v = _value(entry, f, entry["kind"], True)
        if f == "board_hosts":
            v = list(entry["board_hosts"])
        if v is None:
            row.pop(f, None)                 # an optional field the entry does not carry (query_template: null) is ABSENT
        else:
            row[f] = v
    if is_retired(entry):
        row["relationship_status"] = "retired"


def _show(value):
    return json.dumps(value, ensure_ascii=False)


# ---- asks -------------------------------------------------------------------------------------------

def _ask_row(channel_id, title, text, token, today, ask_id=None):
    return {"id": ask_id or (ASK_PREFIX + channel_id), "kind": "system", "title": title, "ask": text,
            "created": today, "act_by": None, "opp_id": None, "channel_id": channel_id, "resolves_when": None,
            "resolved_on": None, "resolution": None, "trigger_kind": None, "trigger_ref": None,
            "note": token}


def _merge_asks(asks, new_rows):
    """Replace-by-id. An existing row (open OR resolved) that carries the same token is left exactly as it
    is: the same change never reopens an ask the candidate has answered, and a re-run is a no-op.
    Returns (merged list, changed?)."""
    merged = list(asks)
    changed = False
    for row in new_rows:
        existing = next((a for a in merged if a.get("id") == row["id"]), None)
        if existing is not None and existing.get("note") == row["note"]:
            continue
        merged = [a for a in merged if a.get("id") != row["id"]] + [row]
        changed = True
    return merged, changed


def _conflict_text(row, entry, diffs, catalog):
    lines = ["The channel catalog changed the source %r and you have changed it too, so it was left alone "
             "(catalog revision %d)." % (row.get("id"), catalog["revision"])]
    for field, mine, theirs in diffs:
        lines.append("    %s: yours %s, the catalog's %s" % (field, _show(mine), _show(theirs)))
    lines.append("Decide, then run ONE of these (either resolves this ask):")
    lines.append("    record.py channel-catalog take %s    use the catalog's values; yours are kept in the "
                 "row's log" % row.get("id"))
    lines.append("    record.py channel-catalog keep %s    keep yours; the next catalog change asks again"
                 % row.get("id"))
    return "\n".join(lines)


def _orphan_text(row, catalog):
    return ("The source %r came from the channel catalog entry %r, which this version of the catalog no "
            "longer lists (revision %d). Nothing was changed. The row stays as it is; remove its "
            "channel_catalog_* fields with record.py set if you want it to be only yours."
            % (row.get("id"), row.get("channel_catalog_entry"), catalog["revision"]))


# ---- the reconcile plan (pure) ----------------------------------------------------------------------

def plan_reconcile(channels, asks, catalog, today):
    """Decide what the catalog does to `channels`, mutating nothing handed in. Returns

        {"rows": new channels list, "asks": new asks list, "applied": [{channel_id, entry, changes}],
         "restamped": [channel_id], "asked": [{channel_id, kind}], "states": {state: n},
         "ahead": n, "changed_rows": bool, "changed_asks": bool}
    """
    entries = by_id(catalog)
    cat_rev = catalog["revision"]
    rows = copy.deepcopy(channels)
    out = {"applied": [], "restamped": [], "asked": [], "states": {}, "ahead": 0}
    new_asks = []
    for row in rows:
        state = row_state(row, entries, cat_rev)
        if state == "unstamped":
            continue
        out["states"][state] = out["states"].get(state, 0) + 1
        if state == "ahead":
            out["ahead"] += 1
            continue
        if state in WRITING_STATES and not cat_rev > row["channel_catalog_rev"]:
            out["states"]["unrevised"] = out["states"].get("unrevised", 0) + 1
            continue
        cid = row.get("id")
        entry = entries.get(row.get("channel_catalog_entry"))
        if state == "stale":
            diffs = _differences(row, entry)
            sha_now = entry_sha(entry)
            was = ", ".join("%s was %s" % (f, _show(old)) for f, old, _new in diffs)
            note = "replaced by channel catalog %s@%s (revision %d): %s" % (entry["id"], sha_now, cat_rev, was)
            if is_retired(entry):
                note += "; retired by the catalog: %s" % entry["retired"].get("reason")
            _write_managed(row, entry)
            row["log"] = list(row.get("log") or []) + [{"date": today, "note": note}]
            _stamp(row, entry, catalog, today)
            out["applied"].append({"channel_id": cid, "entry": entry["id"], "changes": diffs})
        elif state == "converged":
            _stamp(row, entry, catalog, today)
            out["restamped"].append(cid)
        elif state == "conflict":
            diffs = _differences(row, entry)
            names = ", ".join(f for f, _a, _b in diffs)
            token = "entry-sha=%s rev=%d" % (entry_sha(entry), cat_rev)
            new_asks.append(_ask_row(
                cid, "channel catalog and your edit of %s disagree on: %s" % (cid, names),
                _conflict_text(row, entry, diffs, catalog), token, today))
            out["asked"].append({"channel_id": cid, "kind": "conflict", "fields": [f for f, _a, _b in diffs]})
        elif state == "orphaned":
            token = "orphaned rev=%d" % cat_rev
            new_asks.append(_ask_row(
                cid, "the channel catalog no longer lists the entry behind %s" % cid,
                _orphan_text(row, catalog), token, today))
            out["asked"].append({"channel_id": cid, "kind": "orphaned", "fields": []})
    merged, asks_changed = _merge_asks(asks, new_asks)
    out["rows"] = rows
    out["asks"] = merged
    out["changed_rows"] = bool(out["applied"] or out["restamped"])
    out["changed_asks"] = asks_changed
    return out


def report_lines(plan):
    """The block the SessionStart hook prints (empty when nothing was applied or asked)."""
    n_up, n_ask = len(plan["applied"]), len(plan["asked"])
    if not (n_up or n_ask):
        return []
    head = []
    if n_up:
        head.append("%d source%s updated" % (n_up, "" if n_up == 1 else "s"))
    if n_ask:
        head.append("%d need%s your call" % (n_ask, "s" if n_ask == 1 else ""))
    lines = ["jobsearch: channel catalog - " + ", ".join(head)]
    for a in plan["applied"]:
        for field, old, new in a["changes"]:
            lines.append("  updated  %s  %s  %s -> %s" % (a["channel_id"], field, _show(old), _show(new)))
    for a in plan["asked"]:
        what = ("%s differs from the catalog" % ", ".join(a["fields"])) if a["kind"] == "conflict" \
            else "the catalog no longer lists this entry"
        lines.append("  ask      %s  %s (see your asks)" % (a["channel_id"], what))
    return lines


# ---- reading and writing the profile's stores -------------------------------------------------------

def _read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _read_store(profile, name):
    """(rows, present). An absent store is reported as absent, never as empty."""
    path = os.path.join(profile, "data", name + ".jsonl")
    if not os.path.exists(path):
        return [], False
    return _read_jsonl(path), True


def _problems(companies, channels):
    import validate_data as _vd
    return (list(_vd.check_portfolio_links(companies, channels))
            + list(_vd.check_channel_catalog_fields(channels)))


def _take_run_lock(why):
    """True when the run lock is ours, False when someone holds it (retry next session)."""
    lock = os.path.join(HERE, "runlock.py")
    r = subprocess.run([sys.executable, lock, "--take", why, "--wait", "0"], capture_output=True, text=True)
    return r.returncode == 0


def _release_run_lock():
    subprocess.run([sys.executable, os.path.join(HERE, "runlock.py"), "--release"], capture_output=True)


def reconcile(profile, today=None, catalog=None):
    """Reconcile every stamped channel row of `profile` with the catalog (migrate.py --hook's envelope
    calls this). Idempotent: it writes only on a change. Returns

        {"verdict": nothing | no-channels | applied | asked | ahead | unrevised | store-busy | refused |
                    catalog-unreadable,
         "lines": [...printable...], "written": [paths relative to the profile], "stamped": n,
         "states": {...}, "applied": n, "asked": n, "ahead": n}

    It never adds a row, never touches an unstamped row, and writes nothing when the lock is held. Any
    exception is the CALLER's to catch (migrate.py does, and writes a diag row)."""
    today = today or datetime.date.today().isoformat()
    res = {"verdict": "nothing", "lines": [], "written": [], "stamped": 0, "states": {}, "applied": 0,
           "asked": 0, "ahead": 0}
    chan_path = os.path.join(profile, "data", "channels.jsonl")
    if not os.path.exists(chan_path):
        res["verdict"] = "no-channels"
        return res
    channels = _read_jsonl(chan_path)
    res["stamped"] = sum(1 for r in channels if has_stamp(r))
    if not res["stamped"]:
        return res                                   # the common case: a profile that opted in to nothing
    try:
        catalog = catalog or load_catalog()
    except CatalogError as e:
        res["verdict"] = "catalog-unreadable"
        res["lines"] = ["jobsearch: channel catalog NOT CHECKED - %s; %d source%s you turned on %s not "
                        "reconciled this session" % (e, res["stamped"], "" if res["stamped"] == 1 else "s",
                                                     "was" if res["stamped"] == 1 else "were")]
        return res
    asks_rows, _present = _read_store(profile, "asks")
    plan = plan_reconcile(channels, asks_rows, catalog, today)
    res["states"], res["ahead"] = plan["states"], plan["ahead"]
    if not (plan["changed_rows"] or plan["changed_asks"]):
        res["verdict"] = "ahead" if plan["ahead"] else ("unrevised" if plan["states"].get("unrevised") else "nothing")
        return res
    if not _take_run_lock("migrate.py channel catalog reconcile"):
        res["verdict"] = "store-busy"
        return res
    try:
        # re-read INSIDE the lock and re-plan on what is really there
        channels = _read_jsonl(chan_path)
        asks_rows, _present = _read_store(profile, "asks")
        plan = plan_reconcile(channels, asks_rows, catalog, today)
        res["states"], res["ahead"] = plan["states"], plan["ahead"]
        if not (plan["changed_rows"] or plan["changed_asks"]):
            return res
        companies, _p = _read_store(profile, "companies")
        before = set(_problems(companies, channels))
        added = [p for p in _problems(companies, plan["rows"]) if p not in before]
        if added:
            res["verdict"] = "refused"
            res["lines"] = ["jobsearch: channel catalog update REFUSED (it would leave %d invalid row%s); "
                            "nothing was changed" % (len(added), "" if len(added) == 1 else "s")]
            return res
        import _atomic
        if plan["changed_rows"]:
            _atomic.write_jsonl(chan_path, plan["rows"])
            res["written"].append(os.path.join("data", "channels.jsonl"))
        if plan["changed_asks"]:
            _atomic.write_jsonl(os.path.join(profile, "data", "asks.jsonl"), plan["asks"])
            res["written"].append(os.path.join("data", "asks.jsonl"))
    finally:
        _release_run_lock()
    res["applied"], res["asked"] = len(plan["applied"]), len(plan["asked"])
    res["verdict"] = "applied" if plan["applied"] or plan["restamped"] else "asked"
    res["lines"] = report_lines(plan)
    return res


# ---- opting in: planning `add` (pure; record.py does the locked write) ------------------------------

def _hosts_overlap(a, b):
    for x in a or []:
        for y in b or []:
            if isinstance(x, str) and isinstance(y, str) and (_bh.host_matches(x, y) or _bh.host_matches(y, x)):
                return True
    return False


def _find(rows, rid):
    return next((r for r in rows if r.get("id") == rid), None)


def channel_row_from_entry(entry, catalog, today, portfolio_of=None):
    """The channel row `add` writes for `entry` (a row-writing kind). A board's `alert_sender` FACET is copied
    only when the entry carries one (the catalog cannot know a board's From address otherwise); it stays the
    user's afterwards. On an `alert-sender` entry the sender IS the source and is managed. `scope_notes` carries
    no URL, so a URL change never leaves stale prose."""
    kind = entry["kind"]
    if kind not in ROW_KINDS:
        raise Refused("a %s entry writes no channels row" % kind)
    row = {"id": entry["channel_id"], "label": entry["label"], "type": entry_type(entry),
           "access": entry["access"]}
    if kind in BOARD_KINDS:
        row["board_url"] = entry["board_url"]
        row["board_hosts"] = list(entry["board_hosts"])
    row["review_cadence"] = entry["review_cadence"]
    row["last_reviewed"] = None
    row["scope_notes"] = entry["scope_notes"]
    if kind == "swept-board" and entry.get("query_template") is not None:
        row["query_template"] = entry["query_template"]
    if entry.get("alert_sender"):
        row["alert_sender"] = entry["alert_sender"]
    if portfolio_of:
        row[_pb.FIRM_LINK_FIELD] = portfolio_of
    _stamp(row, entry, catalog, today)
    return row


def firm_row_from_entry(entry, today):
    firm = entry["firm"]
    return {"id": firm["id"], "name": firm["name"], "vertical": "other", "status": "watching",
            "size_ownership": "investment firm", "domain": firm["domain"],
            "research_log": [{"date": today, "note": "added with channel catalog entry %s" % entry["id"]}]}


def _resolve_firm(entry, companies, pending_firms, firm_arg, today):
    """(company_id, how, new_row_or_None) or raises Refused."""
    firm = entry["firm"]
    if firm_arg:
        if _find(companies, firm_arg) is None:
            raise Refused("--firm %r resolves to no companies record." % firm_arg)
        return firm_arg, "reused %s (--firm)" % firm_arg, None
    if _find(companies, firm["id"]) is not None:
        return firm["id"], "reused %s" % firm["id"], None
    if firm["id"] in pending_firms:
        return firm["id"], "created %s" % firm["id"], None
    import pipeline_index as _pidx
    hits = _pidx.company_candidates(firm["name"], companies)
    if len(hits) > 1:
        raise Refused("the firm %r matches %d companies you track (%s); pass --firm <company_id> to say which."
                      % (firm["name"], len(hits), ", ".join(hits)))
    if hits:
        return hits[0], "reused %s" % hits[0], None
    return firm["id"], "created %s" % firm["id"], firm_row_from_entry(entry, today)


def plan_add(catalog, entry_ids, channels, companies, today, attach=None, firm_arg=None):
    """Plan opting in to `entry_ids` (catalog entry ids, in order). Mutates nothing. Returns a list of per-entry
    dicts: {entry, channel_id, status: write | attach | already | skipped, why, row, fill, new_firm, firm_how}.

    The coexistence invariant (CC8): an UNSTAMPED row is read here only to detect a collision, and is never
    written, except by `--attach`, which is the user's own command naming that row."""
    entries = by_id(catalog)
    results, pending_firms = [], set()
    for eid in entry_ids:
        e = entries[eid]
        res = {"entry": eid, "channel_id": e.get("channel_id"), "status": "skipped", "why": None, "row": None,
               "fill": None, "new_firm": None, "firm_how": None}
        results.append(res)
        if e["kind"] not in ROW_KINDS:
            res["why"] = ("%s is a setting, not a row: turn it on with record.py source on %s" % (eid, eid))
            continue
        if is_retired(e):
            res["why"] = "retired %s: %s" % (e["retired"].get("on"), e["retired"].get("reason"))
            continue
        on = next((r for r in channels if r.get("channel_catalog_entry") == eid), None)
        if on is not None:
            res.update(status="already", channel_id=on.get("id"), why="already on as %s" % on.get("id"))
            continue
        try:
            firm_id, firm_how, new_firm = None, None, None
            if e["kind"] == "portfolio":
                firm_id, firm_how, new_firm = _resolve_firm(e, companies, pending_firms, firm_arg, today)
            if attach:
                target = _find(channels, attach)
                if target is None:
                    raise Refused("--attach %r resolves to no channels record." % attach)
                if has_stamp(target):
                    raise Refused("%s is already tied to a catalog entry (%s)."
                                  % (attach, target.get("channel_catalog_entry")))
                want_type = entry_type(e)
                if target.get("type") != want_type or norm_access(target.get("access")) not in (None, norm_access(e["access"])):
                    raise Refused("%s is a %r channel with access %r; only a %r channel with access %r (or "
                                  "none) can be tied to this entry." % (attach, target.get("type"),
                                                                        target.get("access"), want_type, e["access"]))
                fill = {}
                for field in PROJECTION_FIELDS[e["kind"]]:
                    if field == "type":
                        continue
                    if target.get(field) is None and e.get(field) is not None:
                        fill[field] = list(e[field]) if field == "board_hosts" else e[field]
                if firm_id and _pb.FIRM_LINK_FIELD not in target:
                    if target.get("review_cadence") not in CALENDAR_CADENCES:
                        raise Refused("%s has review_cadence %r; a portfolio board needs a calendar cadence "
                                      "(%s). Set it first (record.py set %s review_cadence weekly --file "
                                      "channels)." % (attach, target.get("review_cadence"),
                                                      ", ".join(CALENDAR_CADENCES), attach))
                    fill[_pb.FIRM_LINK_FIELD] = firm_id
                new_row = dict(target)
                new_row.update(fill)
                new_row.setdefault("type", want_type)
                _stamp(new_row, e, catalog, today)
                differs = [f for f, _a, _b in _differences(new_row, e)]
                res.update(status="attach", channel_id=attach, row=new_row, fill=fill, new_firm=new_firm,
                           firm_how=firm_how,
                           why=("tied to the catalog; filled %s%s" % (
                               ", ".join(sorted(fill)) or "nothing",
                               ("; your own %s kept, so catalog changes to it will ask first" % ", ".join(differs))
                               if differs else "")))
            else:
                colliders = [r.get("id") for r in channels
                             if r.get("id") == e["channel_id"]
                             or (e["kind"] in BOARD_KINDS and _hosts_overlap(r.get("board_hosts"), e["board_hosts"]))]
                if colliders:
                    raise Refused("you already have this source as %s; a second row for one source is never "
                                  "created. To let catalog updates reach it: record.py channel-catalog add %s "
                                  "--attach %s" % (", ".join(colliders), eid, colliders[0]))
                row = channel_row_from_entry(e, catalog, today, portfolio_of=firm_id)
                res.update(status="write", row=row, new_firm=new_firm, firm_how=firm_how,
                           why="turned on" + (" (firm %s)" % firm_how if firm_how else ""))
            if new_firm is not None:
                pending_firms.add(new_firm["id"])
        except Refused as r:
            res.update(status="skipped", why=str(r.args[0]), row=None, new_firm=None)
    return results


def apply_add(results, channels, companies):
    """Apply `plan_add`'s results to the two lists, in place."""
    for res in results:
        if res["status"] not in ("write", "attach"):
            continue
        if res["new_firm"] is not None and _find(companies, res["new_firm"]["id"]) is None:
            companies.append(res["new_firm"])
        if res["status"] == "write":
            channels.append(res["row"])
        else:
            idx = next(i for i, r in enumerate(channels) if r.get("id") == res["channel_id"])
            channels[idx] = res["row"]


# ---- take / keep (resolve a disagreement) -----------------------------------------------------------

def plan_resolve(catalog, channels, asks, channel_id, how, today):
    """`take` (the catalog's values win) or `keep` (the user's stay). Returns (new_row, new_asks, summary) or raises
    Refused. Both refuse a row stamped by a NEWER revision (R1: this engine's catalog cannot judge it)."""
    row = _find(channels, channel_id)
    if row is None:
        raise Refused("%r resolves to no channels record." % channel_id)
    entries = by_id(catalog)
    state = row_state(row, entries, catalog["revision"])
    if state == "unstamped":
        raise Refused("%s is not tied to a catalog entry; this verb never touches a row you made." % channel_id)
    if state == "unreadable":
        raise Refused("%s carries a partial channel_catalog_* stamp; fix it with record.py set first." % channel_id)
    if state == "ahead":
        raise Refused("%s was stamped by catalog revision %d, newer than this engine's catalog (revision %d). Update "
                      "the plugin (or run this from the newer machine); nothing was changed."
                      % (channel_id, row["channel_catalog_rev"], catalog["revision"]))
    if state == "orphaned":
        raise Refused("this catalog no longer lists the entry behind %s; there is nothing to %s." % (channel_id, how))
    if state in ("off", "ok", "converged"):
        raise Refused("%s is %s: nothing differs, or it is turned off, so there is nothing to %s."
                      % (channel_id, state, how))
    entry = entries[row["channel_catalog_entry"]]
    new = copy.deepcopy(row)
    if how == "take":
        diffs = _differences(row, entry)
        was = ", ".join("%s was %s" % (f, _show(old)) for f, old, _n in diffs)
        new["log"] = list(new.get("log") or []) + [{"date": today, "note": "replaced by channel catalog %s@%s "
                                                    "(revision %d): %s" % (entry["id"], entry_sha(entry),
                                                                           catalog["revision"], was)}]
        _write_managed(new, entry)
    _stamp(new, entry, catalog, today)
    new_asks = copy.deepcopy(asks)
    for a in new_asks:
        if a.get("id") == ASK_PREFIX + channel_id and not a.get("resolved_on"):
            a["resolved_on"], a["resolution"] = today, how
    verb = "took the catalog's values for" if how == "take" else "kept your values for"
    return new, new_asks, "%s %s" % (verb, channel_id)


# ---- adoption of hand-made rows (dev #774; the 0.76.0 migration's brain, pure) ---------------------------

def template_match_projection(row):
    """The projection a hand row is compared to a shipped template on: the managed fields of the `curated` /
    `portfolio` kinds WITHOUT the retired bit (a row the user turned off is still the same template), `access`
    normalised (`login-chrome` -> `login`, `public-bot-limited` -> `bot-limited`), hosts sorted and lower-cased."""
    return {"label": row.get("label"), "type": row.get("type"), "access": norm_access(row.get("access")),
            "board_url": row.get("board_url"), "board_hosts": _norm_hosts(row.get("board_hosts"))}


def template_sha(match_projection):
    """The sha a template is stamped with: the full managed projection, retired bit False, so a row that
    still equals its template reads `ok` or `stale` exactly as `row_sha` computes it."""
    full = dict(match_projection)
    full["retired"] = False
    return projection_sha(full)


def adoption_plan(channels, catalog):
    """Decide what the 0.76.0 adoption does, mutating nothing. Returns a list of
    {channel_id, entry, status: exact | near | none, template_sha, differing, rows_index}.

    Only UNSTAMPED rows of type job-board / aggregator / alert-email are considered, and only against `curated`
    and `portfolio` entries (a swept board or an alert sender never had a shipped template, so no hand row can
    match one exactly). EXACT: the row's id equals the entry's `channel_id` and its match projection equals the
    EMBEDDED projection of one of the entry's `shipped_templates` (review B3: never a git lookup). NEAR: the same
    id, or overlapping `board_hosts`, with a projection no template carries."""
    out = []
    for e in catalog["entries"]:
        if e["kind"] not in BOARD_KINDS or is_retired(e):
            continue
        templates = [t for t in e.get("shipped_templates") or [] if isinstance(t, dict)]
        for i, row in enumerate(channels):
            if has_stamp(row) or row.get("type") not in SOURCE_TYPES:
                continue
            same_id = row.get("id") == e["channel_id"]
            if not (same_id or _hosts_overlap(row.get("board_hosts"), e["board_hosts"])):
                continue
            mp = template_match_projection(row)
            hit = next((t for t in templates if same_id and t.get("projection") == mp), None)
            if hit is not None:
                out.append({"channel_id": row.get("id"), "entry": e["id"], "status": "exact",
                            "template_sha": hit["sha"], "differing": [], "index": i})
            else:
                ref = templates[0]["projection"] if templates else entry_projection(e)
                differing = sorted(k for k in mp if mp[k] != ref.get(k))
                out.append({"channel_id": row.get("id"), "entry": e["id"], "status": "near",
                            "template_sha": None, "differing": differing, "index": i})
    return out


def adopted_row(row, entry, template_sha_value, today):
    """`row` stamped as adopted from `entry`'s template: the four stamp fields added, nothing else touched."""
    new = dict(row)
    new["channel_catalog_entry"] = entry["id"]
    new["channel_catalog_sha"] = template_sha_value
    new["channel_catalog_on"] = today
    new["channel_catalog_rev"] = ADOPTED_REV
    return new


def adopt_ask_text(row, entry, differing):
    lines = ["Your source %r looks like the catalog's %r but differs from what this plugin once told you to "
             "paste, so it was left exactly as it is." % (row.get("id"), entry["id"])]
    for f in differing:
        lines.append("    %s: yours %s" % (f, _show(row.get(f))))
    lines.append("Decide, then run ONE of these:")
    lines.append("    record.py channel-catalog add %s --attach %s    let catalog updates reach this row "
                 "(fills only what is absent)" % (entry["id"], row.get("id")))
    lines.append("    record.py source keep-mine %s    leave it yours; this is not asked again" % row.get("id"))
    return "\n".join(lines)


def adopt_ask_row(row, entry, differing, today):
    cid = row.get("id")
    return _ask_row(cid, "the catalog has an entry for your source %s; adopt it or keep it yours" % cid,
                    adopt_ask_text(row, entry, differing), "adopt entry=%s" % entry["id"], today,
                    ask_id=ADOPT_ASK_PREFIX + cid)


# ---- turning a source on or off (dev #774; record.py source does the locked write) -------------------------
#
# ONE OFF BIT PER KIND, each honoured by every reader (design section 4.1): a channel row is OFF when
# `relationship_status` is `retired` (the bit alert_sweep.py, channels_due.py, portfolio_boards.py, the reconcile and
# linkedin_sweep.job_search_is_off all read); the feed policy is OFF when `sourcing.feeds.enabled` is false. Turning a
# row off stores what it found in the declared `prior_relationship_status` (R2) so turning it on puts back exactly
# that. Everything below is PURE: it mutates nothing it is handed and returns the stores it would write.
#
# CC8's invariant holds: the catalog code does not read an unstamped row on its own initiative. Here the row is read
# because the USER named it ("record.py source off <id>"), the same standing `--attach` has.

def _source_row_or_refuse(row, ident):
    if row.get("type") not in SOURCE_TYPES:
        verb = "record.py ats" if row.get("type") == "company-site" else "record.py set"
        raise Refused("%s is a %s channel, not a source: a recruiter or referral is a relationship, a company-site is "
                      "a company's own career page. Use %s, not record.py source." % (ident, row.get("type"), verb))
    return row


def resolve_source(catalog, channels, ident):
    """What `ident` names, as ("row", row) | ("entry", entry) | ("feeds", entry or None). The order is: the feed
    policy; a channel row by id (stamped or yours); a catalog entry that has a row (by entry id or by its channel id);
    a catalog entry with no row. Anything else raises `Refused`, naming what is known."""
    entries = by_id(catalog) if catalog else {}
    feed_entry = next((e for e in entries.values() if e["kind"] == "feed-policy"), None)
    if ident == FEEDS_ENTRY_ID or (feed_entry is not None and ident == feed_entry["id"]):
        return "feeds", feed_entry
    row = _find(channels, ident)
    if row is not None:
        return "row", _source_row_or_refuse(row, ident)
    entry = entries.get(ident) or next((e for e in entries.values() if e.get("channel_id") == ident), None)
    if entry is not None and entry["kind"] in ROW_KINDS:
        held = next((r for r in channels if r.get("channel_catalog_entry") == entry["id"]), None)
        if held is not None:
            return "row", held
        by_channel = _find(channels, entry["channel_id"])
        if by_channel is not None:
            return "row", _source_row_or_refuse(by_channel, ident)
        return "entry", entry
    known = sorted({r.get("id") for r in channels if r.get("type") in SOURCE_TYPES and r.get("id")}
                   | {e["id"] for e in entries.values()} | {FEEDS_ENTRY_ID})
    raise Refused("%r is not a source this profile holds or the catalog lists. Known: %s." % (ident, ", ".join(known)))


def _logged(row, today, note):
    row["log"] = list(row.get("log") or []) + [{"date": today, "note": note}]


def retire_row(row, today):
    """`row` turned off: `relationship_status: retired`, with what it found stored in `prior_relationship_status`. A
    row that is already retired is returned unchanged (a double off must not overwrite the first prior)."""
    if row.get("relationship_status") == "retired":
        return row, False
    new = copy.deepcopy(row)
    new["prior_relationship_status"] = encode_prior(row)
    new["relationship_status"] = "retired"
    _logged(new, today, "turned off with record.py source off")
    return new, True


def unretire_row(row, today):
    """`row` turned back on: the status `source off` found is put back EXACTLY (key absent, null, or the string), and
    the prior field is removed, so off -> on is byte-identical but for `log`. A row retired by hand (no prior
    recorded) gets `relationship_status: null`. Raises `PriorUnreadable` for a prior this cannot read."""
    if row.get("relationship_status") != "retired":
        return row, False
    prior = read_prior(row)
    new = copy.deepcopy(row)
    if prior is None:
        new["relationship_status"] = None
    elif prior["had"]:
        new["relationship_status"] = prior["value"]
    else:
        new.pop("relationship_status", None)
    new.pop("prior_relationship_status", None)
    _logged(new, today, "turned on with record.py source on")
    return new, True


def plan_source_toggle(catalog, channels, companies, config, ident, want_on, today, anyway=False):
    """Plan `record.py source on|off <ident>`. Mutates nothing. Returns

        {"changed": [store names among channels|companies|config], "channels": rows, "companies": rows,
         "config": dict, "lines": [...], "noop": bool, "row": the written/target channels row or None,
         "entry": the catalog entry or None}

    `Refused` (exit 2) for an id that is not a source, a prior this cannot read, a row the catalog retired (`on`
    without `anyway`), or an `off` of a source that is not on. Already in the requested state is a no-op (exit 0)."""
    channels, companies, config = copy.deepcopy(channels), copy.deepcopy(companies), copy.deepcopy(config)
    entries = by_id(catalog) if catalog else {}
    what, target = resolve_source(catalog, channels, ident)
    out = {"changed": [], "channels": channels, "companies": companies, "config": config, "lines": [],
           "noop": False, "row": None, "entry": target if what != "row" else entries.get((target or {}).get("channel_catalog_entry"))}
    verb = "on" if want_on else "off"
    if what == "feeds":
        import config_keys as _ck
        now, _problem = _ck.feeds_enabled(config)
        if now == want_on and _problem is None:
            out["noop"] = True
            stored = _ck._get_dotted(config, _ck.SOURCING_FEEDS_ENABLED) is not None
            out["lines"].append("  company-feeds is already %s%s" % (verb, "" if stored else " (the default: nothing is stored)"))
            return out
        node = config
        parts = _ck.SOURCING_FEEDS_ENABLED.split(".")
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = bool(want_on)
        out["changed"].append("config")
        out["lines"].append("  company-feeds: turned %s (%s = %s)" % (verb, _ck.SOURCING_FEEDS_ENABLED, str(bool(want_on)).lower()))
        return out
    if what == "row":
        row = target
        out["row"] = row
        entry = entries.get(row.get("channel_catalog_entry")) if has_stamp(row) else None
        if not want_on:
            new, changed = retire_row(row, today)
            if not changed:
                out["noop"] = True
                out["lines"].append("  %s is already off" % ident)
                return out
        else:
            if row.get("relationship_status") != "retired":
                out["noop"] = True
                out["lines"].append("  %s is already on" % ident)
                return out
            if entry is not None and is_retired(entry) and not anyway:
                raise Refused("the catalog retired %s (%s: %s), so it is not turned back on. Pass --anyway to turn it on "
                              "regardless; the row then counts as edited." % (ident, entry["retired"].get("on"),
                                                                              entry["retired"].get("reason")))
            try:
                new, _changed = unretire_row(row, today)
            except PriorUnreadable as e:
                raise Refused("%s; it was not turned on. Fix or remove the field with record.py set --file channels, "
                              "then run this again." % e)
            if entry is not None and is_retired(entry):
                # --anyway: the user acknowledges the catalog's retirement and keeps the source. Re-stamping with the
                # catalog's own sha makes the row `edited` (its retired bit differs from the entry's), so the next
                # reconcile leaves it on instead of applying the retirement again.
                _stamp(new, entry, catalog, today)
        idx = next(i for i, r in enumerate(channels) if r.get("id") == row.get("id"))
        channels[idx] = new
        out["row"] = new
        out["changed"].append("channels")
        out["lines"].append("  %s: turned %s" % (row.get("id"), verb))
        return out
    # an entry the profile holds no row for
    entry = target
    if not want_on:
        if entry.get("absence_reads_as") == "on" and not is_retired(entry):
            # the LinkedIn job search: its reader treats an ABSENT row as ON, so the only way to turn it off is a row
            row = channel_row_from_entry(entry, catalog, today)
            new, _changed = retire_row(row, today)
            channels.append(new)
            out["row"] = new
            out["changed"].append("channels")
            out["lines"].append("  %s: turned off (a row was written so the off switch exists; nothing else changed)"
                                % entry["channel_id"])
            return out
        raise Refused("%s is not on, so there is nothing to turn off." % ident)
    if entry.get("absence_reads_as") == "on" and not is_retired(entry):
        out["noop"] = True                       # no row means ON for this reader (the LinkedIn job search): already on
        out["lines"].append("  %s is already on (it has no row; its reader treats that as on)" % entry["channel_id"])
        return out
    results = plan_add(catalog, [entry["id"]], channels, companies, today)
    res = results[0]
    if res["status"] not in ("write", "attach"):
        raise Refused(res["why"] or "%s could not be turned on" % ident)
    apply_add(results, channels, companies)
    out["row"] = res["row"]
    out["changed"].append("channels")
    if res["new_firm"] is not None:
        out["changed"].append("companies")
    out["lines"].append("  %s: %s" % (res["channel_id"], res["why"]))
    return out


def plan_keep_mine(asks, channel_id, today):
    """`record.py source keep-mine <id>`: resolve the adoption ask for `channel_id`, changing nothing else. Returns the
    new asks list, or raises `Refused` when there is no open adoption ask for it."""
    ask_id = ADOPT_ASK_PREFIX + channel_id
    new = copy.deepcopy(asks)
    hit = [a for a in new if a.get("id") == ask_id and not a.get("resolved_on")]
    if not hit:
        raise Refused("there is no open adoption question for %r; nothing to resolve." % channel_id)
    hit[0]["resolved_on"], hit[0]["resolution"] = today, "keep-mine"
    return new


# ---- listing and offering (read-only) ---------------------------------------------------------------

def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0, 0, 0)


def entry_status(entry, channels):
    on = next((r for r in channels if r.get("channel_catalog_entry") == entry["id"]), None)
    if on is not None:
        return "on as %s" % on.get("id")
    if is_retired(entry):
        return "retired (%s)" % entry["retired"].get("reason")
    return "available"


def _url_hosts(opp):
    hosts = set()
    for u in _bh.read_urls(opp):
        h = _bh.host_of(u)
        if h:
            hosts.add(h)
    return hosts


def offer(catalog, channels, companies, opps):
    """(offers, attach_tips): offers = [(entry, [reasons])] for entries the profile does not hold; attach_tips =
    [(entry, channel_id)] for entries the user already holds as an unstamped row. Pure.

    A `portfolio` / `curated` entry is offered only with a profile signal (S1 a firm you state backs a company
    you track; S2 a role you track has an address on its `board_hosts`): no signal, no offer. A `swept-board`,
    `alert-sender` or `feed-policy` entry has no signal to read, so every one the profile does not hold is
    offered with an empty reason list."""
    import pipeline_index as _pidx
    company_ids = {c.get("id") for c in companies}
    offers, tips = [], []
    for e in catalog["entries"]:
        if is_retired(e) or any(r.get("channel_catalog_entry") == e["id"] for r in channels):
            continue
        if e["kind"] == "feed-policy":
            continue                                 # a setting: the view lists it as a source, never as an offer
        colliders = [r.get("id") for r in channels
                     if r.get("id") == e["channel_id"]
                     or (e["kind"] in BOARD_KINDS and _hosts_overlap(r.get("board_hosts"), e["board_hosts"]))]
        if colliders:
            tips.append((e, colliders[0]))
            continue
        reasons = []
        if e["kind"] == "portfolio":
            firm = e["firm"]
            firm_ids = {firm["id"]} | set(_pidx.company_candidates(firm["name"], companies))
            firm_ids &= company_ids
            # the ONE resolver of "who backs this company" (`portfolio_boards.backers_of`); with no channels and no
            # opportunities handed in, what it returns is exactly the backing the user STATED
            n = sum(1 for c in companies
                    if any(b["firm_id"] in firm_ids for b in _pb.backers_of(c.get("id"), companies, [], [])))
            if n:
                reasons.append("you state %s backs %d compan%s you track" % (firm["name"], n, "y" if n == 1 else "ies"))
        if e["kind"] in BOARD_KINDS:
            n_roles = sum(1 for o in opps if any(_bh.host_matches(h, bh) for h in _url_hosts(o) for bh in e["board_hosts"]))
            if n_roles:
                reasons.append("%d role%s you track ha%s an address on this board"
                               % (n_roles, "" if n_roles == 1 else "s", "s" if n_roles == 1 else "ve"))
            if reasons:
                offers.append((e, reasons))
        else:
            offers.append((e, reasons))
    return offers, tips


def check_lines(catalog, channels):
    entries = by_id(catalog)
    stamped = [r for r in channels if has_stamp(r)]
    lines = ["channel catalog revision %d: %d stamped row%s" % (catalog["revision"], len(stamped),
                                                               "" if len(stamped) == 1 else "s")]
    for r in stamped:
        lines.append("  %-30s %s" % (r.get("id"), row_state(r, entries, catalog["revision"])))
    return lines


def main():
    ap = argparse.ArgumentParser(description="The shipped channel catalog (read-only). `sources.py` is the view "
                                             "of every source; this prints the state of each stamped row.")
    ap.add_argument("--check", action="store_true", help="the state of every stamped row")
    args = ap.parse_args()
    if not args.check:
        ap.print_usage()
        return 2
    try:
        catalog = load_catalog()
    except CatalogError as e:
        print("NOT CHECKED: %s" % e)
        return 1
    profile = _root.profile_root()
    if not _root.looks_like_profile(profile):
        print("NOT CHECKED: %r does not look like a job-search profile (no config.json, no data/ directory)."
              % str(profile))
        return 3
    channels, _present = _read_store(profile, "channels")
    print("\n".join(check_lines(catalog, channels)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
