"""gaps: §5.7's gap statuses, the dispatchable set and the one `DISPATCH:` line (design-presence-report.md §5.7, §R3).

**A gap is draftable only when its pool is not empty**, the verb's own rule, so a draft the verb would refuse is never
asked for: `title:` any union bullet (`[public]` ones only on a public-surface variant), `li:headline` the `[public]`
union bullets, `li:skill:` and `claim:` the pool their section names, `req:` never.

**Status** is that of the newest `presence_changes` row carrying the key (`presence/changes.gap_status`). **Dispatchable**
gaps are the draftable ones that are `open`, plus `refused` ones under `--attended`, when the candidate is there to see
why (§R3-4: only an attended row clears `refused`). The order is the key table's (`KIND_ORDER`), then by key; the
dispatch carries the first `MAX_GAPS`.

**The posture** arrives as `(name, posture, err)` from `presence/posture_cfg.read(root)`, never from `posture.may()`,
which cannot tell "not granted" from "unreadable". "Grants" means `drafting` is in the posture's `unattended` list.

| dispatchable | posture | attended | last line |
|---|---|---|---|
| none, every input checked | any | any | `DISPATCH: no (no open draftable gap)` |
| none, an input unchecked | any | any | `DISPATCH: no (NOT CHECKED: <inputs>)` |
| one or more | grants | any | `DISPATCH: yes <key> ...` |
| one or more | does not grant | no | `DISPATCH: held (posture <name> does not grant drafting unattended; <n> open)` |
| one or more | unreadable | no | `DISPATCH: held (NOT CHECKED: posture unreadable: <err>)` |
| one or more | does not grant, or unreadable | yes | `DISPATCH: yes <key> ...` |

Pure: every function takes what the caller read. Nothing here reads a file or writes; a held dispatch is printed,
never queued."""

from presence import changes, report_text
from presence.union_text import is_public, sha8

MAX_GAPS = 5
KIND_ORDER = ("title", "li:headline", "li:skill", "claim", "req")
PUBLIC_SURFACES = ("public-profile",)


def kind(key):
    for k in ("li:headline", "li:skill"):
        if key.startswith(k):
            return k
    return key.split(":", 1)[0]


def with_pools(raw, union):
    """Give a `title:` gap its rule's pool (`union` the union bullets, or None when the union is unchecked)."""
    out = []
    for g in raw:
        g = dict(g)
        if kind(g["key"]) == "title":
            public = g.get("surface") in PUBLIC_SURFACES
            g["public"] = public
            g["pool"] = None if union is None else ([b for b in union if is_public(b)] if public else list(union))
        out.append(g)
    return out


def _why_not(g):
    if g.get("why_not"):
        return g["why_not"]
    if g.get("pool") is None:
        return "union NOT CHECKED"
    if not g["pool"]:
        return "no [public] claim supports it" if g.get("public") else "no union claim supports it"
    return None


def judge(raw, rows, rows_err, attended):
    """Each gap with `status`, `state`, `draftable`, `why_not` and `dispatchable`, in dispatch order. `rows` are the
    checked `presence_changes` rows; with `rows_err` set no status is known and nothing is dispatchable."""
    out = []
    for g in raw:
        g = dict(g)
        g["why_not"] = _why_not(g)
        g["draftable"] = g["why_not"] is None
        if rows_err:
            g["state"], g["status"] = "unknown", "NOT CHECKED (presence_changes: %s)" % rows_err
        else:
            g["state"] = changes.gap_state(rows, g["key"])[0]
            g["status"] = changes.gap_status(rows, g["key"])
        g["dispatchable"] = g["draftable"] and (g["state"] == "open" or (g["state"] == "refused" and attended))
        out.append(g)
    return sorted(out, key=lambda g: (KIND_ORDER.index(kind(g["key"])), g["key"]))


def gap_line(g):
    line = "GAP %s %s" % (g["key"], g["status"])
    return line if g["draftable"] else "%s (not draftable: %s)" % (line, g["why_not"])


def dispatch(judged, unchecked_names, posture_read, attended):
    """`(the DISPATCH: line, the keys it carries)`."""
    disp = [g["key"] for g in judged if g["dispatchable"]]
    if not disp:
        if unchecked_names:
            return "DISPATCH: no (NOT CHECKED: %s)" % ", ".join(unchecked_names), []
        return "DISPATCH: no (no open draftable gap)", []
    keys = disp[:MAX_GAPS]
    yes = "DISPATCH: yes " + " ".join(keys)
    if attended:
        return yes, keys
    name, posture, err = posture_read
    unattended = posture.get("unattended") if isinstance(posture, dict) else None
    if err or not isinstance(unattended, list):
        why = err or "posture %r has no unattended list" % (name,)
        return "DISPATCH: held (NOT CHECKED: posture unreadable: %s)" % why, []
    if "drafting" in unattended:
        return yes, keys
    return "DISPATCH: held (posture %s does not grant drafting unattended; %d open)" % (name, len(disp)), []


def block(judged, counts, unchecked, questions, posture_read, attended):
    """`--gaps`: the `scanned:` line, one `GAP` line per gap, the question lines, a `LISTED: refused` line per refused
    key (§R3-4), then exactly one `DISPATCH:` line. Returns `(lines, the keys the line carries)`."""
    lines = [report_text.scanned_line(counts, unchecked)]
    lines.extend(gap_line(g) for g in judged)
    lines.extend(report_text.question_line(q, attended) for q in questions)
    lines.extend(report_text.refused_line(g["key"]) for g in judged if g["state"] == "refused")
    line, keys = dispatch(judged, report_text.unchecked_names(unchecked), posture_read, attended)
    return lines + [line], keys


SHAPE = ('{"gap": "<key>", "target": "linkedin"|"variant", "variant_id": <id or null>, "field": "<field>", '
         '"value": <the proposed text, or for skills a list>, "before": <the before text below>, '
         '"claims": ["<sha8>", ...], "note": "<why>"}')


def _target(g):
    if g.get("target") == "linkedin":
        return "linkedin %s" % g["field"]
    if g.get("variant_id"):
        return "variant %s %s" % (g["variant_id"], g["field"])
    return "variant (one of: %s) %s" % (", ".join(g.get("variant_choices") or ()) or "none", g["field"])


def packet_lines(judged, keys, titles_list, union, handback):
    """`--packet`: the optimizer's brief for exactly `keys` (the `DISPATCH: yes` keys): per gap its target, the
    before text, the target titles and the pool, each claim as `<sha8> <verbatim text>` for a `claim:` or `li:skill:`
    gap and the pool's rule for a title or headline gap (with the union's `<sha8>` index once below). Claims are cited
    by `<sha8>`, never retyped. Writes nothing; `handback` is the path to write to."""
    by_key = {g["key"]: g for g in judged}
    lines = ["PACKET profile-optimizer: %d gap(s): %s" % (len(keys), " ".join(keys)), "hand-back: %s" % handback,
             "target titles: %s" % ("; ".join(titles_list) or "none"),
             "write one JSON object per line to the hand-back path: " + SHAPE]
    ruled = False
    for key in keys:
        g = by_key[key]
        lines.append("GAP %s  target: %s" % (key, _target(g)))
        before = g.get("before")
        lines.append("  before: %s" % (", ".join(before) if isinstance(before, list) else (before or "(none)")))
        if kind(key) in ("title", "li:headline"):
            ruled = True
            lines.append("  pool: %s (see the claim index below)"
                         % ("[public] union bullets only" if g.get("public") else "any union bullet"))
        else:
            lines.append("  pool:")
            lines.extend("    %s %s" % (sha8(b), b) for b in g["pool"])
    if ruled:
        lines.append("claim index (<sha8> <verbatim union bullet>):")
        lines.extend("  %s %s" % (sha8(b), b) for b in union or ())
    return lines
