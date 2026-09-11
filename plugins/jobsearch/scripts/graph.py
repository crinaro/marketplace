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
Every store this design's B1 stage actually has data for: `companies`, `channels`,
`opportunities`, `people`, `involvements`, `messages`, `asks`, `commitments`. Nothing is
persisted — a stored reverse index is a second copy of the same fact, which is the drift
ADR-001 exists to end (design §2). A `Graph` is built fresh, in memory, for the lifetime of one
call.

MERGE RESOLUTION — THE ONE PLACE A `person_id` BECOMES A LIVING PERSON
------------------------------------------------------------------------
A person's `merged_into` chain is resolved HERE, at read time, never by rewriting the FK that
named the absorbed id (design §3: "a merge is a pointer, never a rewrite... graph.py resolves
through merged_into at read time"). The chain must be acyclic; `resolve_person` is defensive
about it anyway (`MergeCycleError`) so a walker can never hang even if the validator's own
acyclic-chain check somehow missed one — belt and suspenders, not a substitute for that check.

Usage:
    python3 scripts/graph.py --person <id>          # print what this person touches
    python3 scripts/graph.py --opportunity <opp_id> # print who is involved in this pursuit

    from graph import Graph, MergeCycleError

Python 3.9+. Standard library only. No network.
"""
import argparse
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
STORES = ("companies", "channels", "opportunities", "people", "involvements", "messages",
          "asks", "commitments")
STORES_WITH_ID = tuple(s for s in STORES if s != "involvements")


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
                "company": self.by_id["companies"].get(p.get("company_id")),
            }
        if kind == "opportunity":
            opp = self.by_id["opportunities"].get(id_)
            if opp is None:
                return {}
            return {
                "opportunity": opp,
                "people": self.people_for_opportunity(id_),
                "company": self.by_id["companies"].get(opp.get("company_id")),
            }
        if kind == "channel":
            ch = self.by_id["channels"].get(id_)
            if ch is None:
                return {}
            return {"channel": ch, "people": self.people_for_channel(id_)}
        if kind == "company":
            c = self.by_id["companies"].get(id_)
            if c is None:
                return {}
            return {"company": c, "opportunities": self.opportunities_for_company(id_)}
        return {}


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
