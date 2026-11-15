#!/usr/bin/env python3
"""graph.py — the single walker over every connected-entity store (ADR-031 §2 / §28.1 item 6).

WHY THIS EXISTS
---------------
ADR-031's model is "every relationship is a foreign key that must resolve; one module reads
every key in both directions" (design §0). Before this file, every renderer that wanted "who is
involved with this opportunity" or "which roles has this person touched" joined the stores by
hand — the same defect ADR-030 already named for `resolves`: a reader that forgets to branch
produces a number instead of an error. This is that one module.

⭐⭐ ITS EXISTENCE IS ALSO A SWITCH. `validate_data.active_retired_keys()` treats this file's
presence on disk as proof that B1 has shipped — the moment this file lands, `contacts` flips
from legal to refused across the whole engine (see validate_data.py's own block comment on
`RETIRED_KEYS`). That coupling is deliberate (design §6 mitigation 4: "B1 and B2 land before
B3, so the walker and the gate exist before the widest array moves") and is why this file ships
in the SAME commit as the B1 migration, never before it and never after.

WHAT IT LOADS, ONCE
--------------------
Every store this design's B1/B3 stages actually have data for: `companies`, `channels`,
`opportunities`, `people`, `involvements`, `messages`, `asks`, `commitments`, `touches`.
Nothing is persisted — a stored reverse index is a second copy of the same fact, which is the
drift ADR-001 exists to end (design §2). A `Graph` is built fresh, in memory, for the lifetime
of one call.

MERGE RESOLUTION — THE ONE PLACE A `person_id` BECOMES A LIVING PERSON
------------------------------------------------------------------------
A person's `merged_into` chain is resolved HERE, at read time, never by rewriting the FK that
named the absorbed id (design §3: "a merge is a pointer, never a rewrite... graph.py resolves
through merged_into at read time"). The chain must be acyclic; `resolve_person` is defensive
about it anyway (`MergeCycleError`) so a walker can never hang even if the validator's own
acyclic-chain check somehow missed one — belt and suspenders, not a substitute for that check.

WARMTH — A PERSON'S REACH STATE, DERIVED, NEVER STORED (ADR-031 B5b, dev #834)
-------------------------------------------------------------------------------
`warmth(person_id, as_of)` is the twin of `pursuit_state(opp)`: a property of a person, computed from
dated rows every time it is asked. It returns one of three words, or None.

    warm       they answer: an INBOUND message from them dated within `warm_days` of `as_of`, OR a
               HELD chat (a `kind: chat` commitment whose `attendance` is `held`) dated within the
               same window. The held chat is design-network-first.md section 10.1 (b): a chat booked
               from a calendar may leave no inbound mail, and it is the strongest evidence a person
               answers. It counts from the day it is recorded held (`attendance_on`), never earlier,
               so a replay at an earlier date does not know what had not been recorded yet.
    contacted  something has passed between you and them, and they are not warm now: a sent touch
               (`status: sent`), an outbound message, or an exchange older than the window.
               OURS, filling a gap in the design's table: a stale inbound or an old held chat is
               `contacted`, never `known`, because `known` is defined as "nothing sent, nothing
               received" and an old reply is something received.
    known      a people row, nothing exchanged.
    None       no such person, or (replay) they were not yet in the profile at `as_of` (`created`).

Merges resolve first, as everywhere in this module (`resolve_person`), so an absorbed id answers for
its survivor. A touch, message or chat dated AFTER `as_of` does not exist as of `as_of`: that is how
`access.py --since` replays a table at an earlier date from the same rows, with no stored snapshot.
`warm_days` is the caller's (`access.warm_days`, 180); this file never reads config.

Usage:
    python3 scripts/graph.py --person <id>          # print what this person touches
    python3 scripts/graph.py --opportunity <opp_id> # print who is involved in this pursuit

    from graph import Graph, MergeCycleError, warmth

Python 3.9+. Standard library only. No network.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _root import profile_root as _profile_root  # noqa: E402

ROOT = _profile_root()
DATA = os.environ.get("CLAUDESEARCH_DATA_DIR") or os.path.join(ROOT, "data")

# Every store this walker knows about. `involvements` has no `id` field (design §1: "No id of
# its own... the pair is the identity") so it is deliberately absent from STORES_WITH_ID below.
# ⭐ ADR-031 B3 — `touches` joins here because it is genuinely multi-directional (person,
# opportunity, channel, and §12's object person/company), the shape this walker exists for —
# unlike B2's applications (an owned pointer, one opportunity each), which stayed out of this
# file and got its own flat join module (`applications.py`) instead. See `touches.py`'s own
# module docstring for why BOTH files exist and what each owns.
STORES = ("companies", "channels", "opportunities", "people", "involvements", "messages",
          "asks", "commitments", "touches")
STORES_WITH_ID = tuple(s for s in STORES if s != "involvements")

# ADR-031 section 11 / design-network-first.md section 10.2: how long an answer keeps a person warm. The
# registered config key is `access.warm_days` (default 180, 30..365); the CALLER resolves it and passes it in.
WARM_DAYS = 180
WARMTH_STATES = ("warm", "contacted", "known")


def to_date(value):
    """A `datetime.date` from a date, a datetime or an ISO string (a `YYYY-MM-DD HH:MM` stamp keeps its
    date). Raises `ValueError` for anything else: an `as_of` nobody can read must be loud, never read as
    today."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    raise ValueError("not a date: %r" % (value,))


def date_or_none(value):
    """`to_date`, or None for a missing or unreadable STORED value (a commitment's literal `unresolved`
    date, a null). A row whose date cannot be read is not evidence of anything on any day."""
    try:
        return to_date(value)
    except ValueError:
        return None


class MergeCycleError(ValueError):
    """A `people` merged_into chain loops back on itself. `validate_data.py` is where this is
    SUPPOSED to be caught before it ever reaches a walker; this is the walker's own refusal to
    hang if that check is ever bypassed or stale."""


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


class Graph:
    """Loads every store ONCE (from `data_dir`, defaulting to this process's resolved DATA) and
    answers joins in memory. Build a new `Graph` per call site, per run — it is not meant to be
    long-lived or shared across a mutating write; a script that writes and then needs to read
    its own write back builds a fresh `Graph`."""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir or DATA
        self.stores = {name: _load_jsonl(os.path.join(self.data_dir, "%s.jsonl" % name))
                       for name in STORES}
        self.by_id = {name: {r.get("id"): r for r in self.stores[name] if r.get("id")}
                     for name in STORES_WITH_ID}

    # ---- people, and the one merge-resolution point every other method routes through -------

    def resolve_person(self, person_id, _seen=None):
        """The living survivor for `person_id` — itself, if `status` is not `merged`; otherwise
        the row `merged_into` names, resolved recursively (a chain of two merges is legal: A
        merged into B, B later merged into C). Returns None for an id that names no row at all
        (an unresolved FK — the CALLER's problem to report; this function does not invent one).
        Raises `MergeCycleError` rather than looping forever on a chain that points back on
        itself."""
        row = self.by_id["people"].get(person_id)
        if row is None:
            return None
        if row.get("status") != "merged" or not row.get("merged_into"):
            return row
        seen = set(_seen or ())
        if person_id in seen:
            raise MergeCycleError("merge cycle reached again at %r" % person_id)
        seen.add(person_id)
        return self.resolve_person(row["merged_into"], seen)

    def involvements_for_person(self, person_id):
        """Every involvement whose `person_id` resolves (through merge, possibly through an
        absorbed alias) to the SURVIVOR named by `person_id`. `person_id` itself must already be
        a survivor id — pass a merged id and you get involvements recorded against ITS OWN
        (now-absorbed) alias, resolved forward to the same answer, by construction."""
        out = []
        for inv in self.stores["involvements"]:
            pid = inv.get("person_id")
            if not pid:
                continue
            try:
                resolved = self.resolve_person(pid)
            except MergeCycleError:
                continue
            if resolved is not None and resolved.get("id") == person_id:
                out.append(inv)
        return out

    def messages_for_person(self, person_id):
        """Every message whose `person_id` resolves to this survivor — same resolve-and-match
        shape as `involvements_for_person`."""
        out = []
        for m in self.stores["messages"]:
            pid = m.get("person_id")
            if not pid:
                continue
            try:
                resolved = self.resolve_person(pid)
            except MergeCycleError:
                continue
            if resolved is not None and resolved.get("id") == person_id:
                out.append(m)
        return out

    # ---- touches (ADR-031 B3) — person/opportunity/channel, all merge-resolved on the person
    # side exactly as messages_for_person is above; the FK is what "belongs to the person"
    # means (design §1) so the merge chain must be honoured here too. ------------------------

    def touches_for_person(self, person_id):
        """Every touch whose `person_id` resolves to this survivor — same resolve-and-match
        shape as `messages_for_person`."""
        out = []
        for t in self.stores["touches"]:
            pid = t.get("person_id")
            if not pid:
                continue
            try:
                resolved = self.resolve_person(pid)
            except MergeCycleError:
                continue
            if resolved is not None and resolved.get("id") == person_id:
                out.append(t)
        return out

    def touches_for_opportunity(self, opp_id):
        """Every touch anchored to this opportunity — a direct FK match, no merge resolution
        needed on the opp side (an opportunity is never merged)."""
        return [t for t in self.stores["touches"] if t.get("opp_id") == opp_id]

    def touches_for_channel(self, channel_id):
        """Every touch that travelled through this channel (design §1: 'unchanged meaning')."""
        return [t for t in self.stores["touches"] if t.get("channel_id") == channel_id]

    # ---- commitments, people at a company, and warmth (ADR-031 B5b, dev #834) ----------------

    def commitments_for_person(self, person_id):
        """Every commitment (a chat, an interview) whose `person_id` resolves to this survivor, the
        same resolve-and-match shape as `messages_for_person`. A commitment with no `person_id`
        (absent on legacy rows) belongs to nobody here."""
        out = []
        for c in self.stores["commitments"]:
            pid = c.get("person_id")
            if not pid:
                continue
            try:
                resolved = self.resolve_person(pid)
            except MergeCycleError:
                continue
            if resolved is not None and resolved.get("id") == person_id:
                out.append(c)
        return out

    def people_for_company(self, company_id):
        """The living (not merged) people whose `company_id` is this company. An absorbed row is
        skipped: its survivor is the one person, and counts once."""
        return [p for p in self.stores["people"]
                if p.get("company_id") == company_id and p.get("status") != "merged"]

    def warmth(self, person_id, as_of, warm_days=WARM_DAYS):
        """`warm` · `contacted` · `known` for this person as of `as_of`, or None (see the module
        docstring, WARMTH). Raises `ValueError` for an unreadable `as_of`, and `MergeCycleError` for
        a looped merge chain: a state nobody can trust is never defaulted to `known`."""
        today = to_date(as_of)
        p = self.resolve_person(person_id)
        if p is None:
            return None
        created = date_or_none(p.get("created"))
        if created is not None and created > today:
            return None
        pid = p["id"]
        floor = today - datetime.timedelta(days=int(warm_days))
        exchanged = False
        for m in self.messages_for_person(pid):
            d = date_or_none(m.get("sent_on"))
            if d is None or d > today:
                continue
            if m.get("direction") == "inbound" and d >= floor:
                return "warm"
            exchanged = True
        for c in self.commitments_for_person(pid):
            if c.get("kind") != "chat" or c.get("attendance") != "held" \
                    or c.get("status") == "cancelled":
                continue
            d = date_or_none(c.get("date"))
            if d is None:
                continue
            recorded = date_or_none(c.get("attendance_on")) or d
            if max(d, recorded) > today:
                continue
            if d >= floor:
                return "warm"
            exchanged = True
        for t in self.touches_for_person(pid):
            d = date_or_none(t.get("date"))
            if t.get("status") == "sent" and d is not None and d <= today:
                exchanged = True
        return "contacted" if exchanged else "known"

    # ---- opportunities / channels, the other side of an involvement --------------------------

    def involvements_for_opportunity(self, opp_id):
        return [i for i in self.stores["involvements"] if i.get("opp_id") == opp_id]

    def involvements_for_channel(self, channel_id):
        return [i for i in self.stores["involvements"] if i.get("channel_id") == channel_id]

    def people_for_opportunity(self, opp_id):
        """`[(person, involvement), ...]` — every person involved in this pursuit, resolved
        through any merge, paired with the involvement row that names them (the involvement is
        never resolved; only the person side is — `path_type`/`role`/`status` on the
        involvement are facts about the pursuit, not about the merge)."""
        out = []
        for inv in self.involvements_for_opportunity(opp_id):
            p = self.resolve_person(inv.get("person_id"))
            if p is not None:
                out.append((p, inv))
        return out

    def people_for_channel(self, channel_id):
        out = []
        for inv in self.involvements_for_channel(channel_id):
            p = self.resolve_person(inv.get("person_id"))
            if p is not None:
                out.append((p, inv))
        return out

    def opportunities_for_company(self, company_id):
        return [o for o in self.stores["opportunities"] if o.get("company_id") == company_id]

    # ---- the generic bidirectional entry point (design §2: "answers neighbors(kind, id) in
    # both directions") -------------------------------------------------------------------------

    def neighbors(self, kind, id_):
        """A dict naming every related record this walker can derive for `(kind, id_)`, in both
        directions. Deliberately a small, explicit dispatch — not a fully generic FK-reflection
        engine — because the FKs this design actually has are few and named (design §2: "an edge
        store" was rejected for exactly this reason). Returns `{}` for an unknown kind or an id
        that resolves to nothing, never raises — a caller asking about a dangling reference gets
        an empty neighborhood, which it can report as it sees fit."""
        if kind == "person":
            p = self.resolve_person(id_)
            if p is None:
                return {}
            invs = self.involvements_for_person(p["id"])
            return {
                "person": p,
                "involvements": invs,
                "opportunities": [i["opp_id"] for i in invs if i.get("opp_id")],
                "channels": [i["channel_id"] for i in invs if i.get("channel_id")],
                "messages": self.messages_for_person(p["id"]),
                "touches": self.touches_for_person(p["id"]),
                "company": self.by_id["companies"].get(p.get("company_id")),
            }
        if kind == "opportunity":
            opp = self.by_id["opportunities"].get(id_)
            if opp is None:
                return {}
            return {
                "opportunity": opp,
                "people": self.people_for_opportunity(id_),
                "touches": self.touches_for_opportunity(id_),
                "company": self.by_id["companies"].get(opp.get("company_id")),
            }
        if kind == "channel":
            ch = self.by_id["channels"].get(id_)
            if ch is None:
                return {}
            return {"channel": ch, "people": self.people_for_channel(id_),
                    "touches": self.touches_for_channel(id_)}
        if kind == "company":
            c = self.by_id["companies"].get(id_)
            if c is None:
                return {}
            return {"company": c, "opportunities": self.opportunities_for_company(id_)}
        return {}


def warmth(person_id, as_of, graph=None, warm_days=WARM_DAYS):
    """`graph.warmth(person_id, as_of)`: `warm` · `contacted` · `known` · None (see the module
    docstring). Builds a fresh `Graph` over this process's data unless one is passed; a caller that
    asks about many people passes its own, so the stores load once."""
    return (graph or Graph()).warmth(person_id, as_of, warm_days=warm_days)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--person", metavar="ID")
    ap.add_argument("--opportunity", metavar="ID")
    ap.add_argument("--channel", metavar="ID")
    ap.add_argument("--company", metavar="ID")
    args = ap.parse_args()
    g = Graph()
    for kind, id_ in (("person", args.person), ("opportunity", args.opportunity),
                      ("channel", args.channel), ("company", args.company)):
        if id_:
            neigh = g.neighbors(kind, id_)
            if not neigh:
                print("%s %r: nothing known (no such row, or nothing joins to it)" % (kind, id_))
            else:
                print(json.dumps(neigh, indent=2, default=str))
            return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
