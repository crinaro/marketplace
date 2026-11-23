"""requirements: the `fit.requirements[]` rows the presence report reads, grouped by their stored `topic`
(design-presence-report.md §5.2, §8.1). Requirement text is free text and no rule groups it, so a row groups only by
its `topic`; a row with none groups only on identical wording.

B1 holds what `resume_report.py --topics` prints: every stored topic with the number of distinct roles whose rows
carry it, so the researcher reuses a listed topic rather than minting a near-duplicate (P-TOPIC-DRIFT). The counts
are derived on every call and never stored. Reads one store; writes nothing.

B4 adds the requirement-coverage section (§5.2). **Pursued roles** are opportunities with a `fit` that
`pursuits.ruled_out.is_excluded` does not rule out. **A topic is recurring when it appears in at least `RECUR_MIN`
distinct pursued roles**; two rows with one topic in one role count once. (a) recurring topics `not-aligned` in at
least two roles raise `req:<topic>`, never draftable (O12). (b) for recurring topics, an `aligned` or `partial` row's
`claim`: a union bullet a print-surface variant covers (one of its bullets, by `claim_key()`, equals the claim or is
contained in it) is covered; one no such variant covers raises `claim:<sha8>`; a claim no longer in the union is
`NOT CHECKED: claim no longer in the union`, counted; no claim is `not linkable`, counted, never matched by guess.
(b) is not `resume_variants.report()['orphans']`: print-surface variants only, only claims a recurring topic's row
cites, tag-insensitive with containment. A row with no topic is counted and grouped only on identical wording, so it
raises no keyed gap."""

import collections
import json
import os

from presence.union_text import claim_key, sha8
from pursuits.ruled_out import is_excluded

RECUR_MIN = 2
LINKED_VERDICTS = ("aligned", "partial")


def read_opportunities(root):
    """`(rows, None)`, or `(None, reason)` when `data/opportunities.jsonl` cannot be read. An absent store is not an
    empty one here: the report says NOT CHECKED rather than "no topics"."""
    path = os.path.join(root, "data", "opportunities.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()], None
    except (OSError, ValueError) as e:
        return None, "%s cannot be read (%s)" % (os.path.join("data", "opportunities.jsonl"), e)


def requirement_rows(opps):
    """`[(opp_id, row), ...]` for every requirement row of every role carrying a fit, in store order."""
    out = []
    for o in opps:
        fit = o.get("fit") if isinstance(o, dict) else None
        reqs = fit.get("requirements") if isinstance(fit, dict) else None
        for q in reqs or ():
            if isinstance(q, dict):
                out.append((o.get("id"), q))
    return out


def topic_counts(opps):
    """`([(topic, role count), ...] most roles first then by topic, rows with no topic)`."""
    roles = collections.defaultdict(set)
    untopiced = 0
    for oid, q in requirement_rows(opps):
        t = q.get("topic")
        if isinstance(t, str) and t:
            roles[t].add(oid)
        else:
            untopiced += 1
    ranked = sorted(((t, len(ids)) for t, ids in roles.items()), key=lambda p: (-p[1], p[0]))
    return ranked, untopiced


def topics_lines(opps):
    """The `--topics` text: a header, one `<roles>  <topic>` line per topic, and the count of rows with none."""
    ranked, untopiced = topic_counts(opps)
    total = len(requirement_rows(opps))
    lines = ["topics: %d topic(s) over %d requirement row(s); roles counted once per topic" % (len(ranked), total)]
    lines.extend("  %3d  %s" % (n, t) for t, n in ranked)
    lines.append("%d of %d requirement rows carry no topic; they are grouped only on identical wording"
                 % (untopiced, total))
    return lines


def pursued(opps):
    """The pursued roles: a `fit` object, and not ruled out."""
    return [o for o in opps if isinstance(o, dict) and isinstance(o.get("fit"), dict) and not is_excluded(o)]


def topic_roles(rows, verdicts=None):
    """`{topic: {opp id, ...}}` over `[(opp_id, row)]`, optionally only rows whose verdict is in `verdicts`."""
    out = collections.defaultdict(set)
    for oid, q in rows:
        t = q.get("topic")
        if isinstance(t, str) and t and (verdicts is None or q.get("verdict") in verdicts):
            out[t].add(oid)
    return out


def recurring(rows):
    """`{topic: roles}` for every topic in at least `RECUR_MIN` distinct roles."""
    return {t: ids for t, ids in topic_roles(rows).items() if len(ids) >= RECUR_MIN}


def top_topics(rows, n):
    """The first `n` recurring topics by the number of roles where the verdict is aligned or partial (a topic with
    none is not ranked), ties by slug."""
    rec, linked = recurring(rows), topic_roles(rows, LINKED_VERDICTS)
    ranked = sorted((t for t in rec if linked.get(t)), key=lambda t: (-len(linked[t]), t))
    return ranked[:n]


def union_index(bullets):
    """`{claim_key: union bullet as written}` (first spelling kept)."""
    out = {}
    for b in bullets:
        out.setdefault(claim_key(b), b)
    return out


def cited_claims(rows, topic, index):
    """The union bullets (as written) that `topic`'s aligned or partial rows cite as `claim`, in row order."""
    out = []
    for _oid, q in rows:
        c = q.get("claim")
        if q.get("topic") == topic and q.get("verdict") in LINKED_VERDICTS and isinstance(c, str):
            b = index.get(claim_key(c))
            if b and b not in out:
                out.append(b)
    return out


def covering(ck, print_variants):
    """`(variant id, bullet)` of the first print-variant bullet whose claim_key equals `ck` or is contained in it."""
    for v in print_variants:
        for b in v["bullets"]:
            vk = claim_key(b)
            if vk and (vk == ck or vk in ck):
                return v["id"], b
    return None


def not_aligned_lines(rows):
    """§5.2 (a): `(lines, gaps)`; each gap is `req:<topic>`, never draftable."""
    bad = {t: ids for t, ids in topic_roles(rows, ("not-aligned",)).items() if len(ids) >= RECUR_MIN}
    lines = ["  (a) recurring and not aligned: %s" % ("none" if not bad else "%d topic(s)" % len(bad))]
    gaps = []
    for t in sorted(bad):
        lines.append("    req:%s  not-aligned in %d roles: %s" % (t, len(bad[t]), ", ".join(sorted(map(str, bad[t])))))
        gaps.append({"key": "req:%s" % t, "pool": [], "why_not": "a recurring non-match is answered honestly, not with copy"})
    return lines, gaps


def claim_lines(rows, index, print_variants):
    """§5.2 (b): `(lines, gaps)` over recurring topics; `index` is `union_index` of the union bullets and each print
    variant is `{id, bullets}`."""
    rec = recurring(rows)
    claims, gone, unlinkable = collections.OrderedDict(), 0, 0
    for oid, q in rows:
        if q.get("topic") not in rec or q.get("verdict") not in LINKED_VERDICTS:
            continue
        c = q.get("claim")
        if not isinstance(c, str) or not c.strip():
            unlinkable += 1
            continue
        ck = claim_key(c)
        if ck not in index:
            gone += 1
            continue
        entry = claims.setdefault(ck, {"topics": set(), "roles": set()})
        entry["topics"].add(q["topic"])
        entry["roles"].add(str(oid))
    lines, gaps = ["  (b) in the union, on no printed variant: %d cited claim(s)" % len(claims)], []
    for ck, e in claims.items():
        hit = covering(ck, print_variants)
        about = "topics %s; roles %s" % (", ".join(sorted(e["topics"])), ", ".join(sorted(e["roles"])))
        if hit:
            lines.append("    covered by %s: %s (%s)" % (hit[0], hit[1], about))
            continue
        key = "claim:%s" % sha8(ck)
        lines.append("    %s  %s (%s)" % (key, index[ck], about))
        gaps.append({"key": key, "target": "variant", "field": "bullet", "variant_id": None, "before": None,
                     "variant_choices": [v["id"] for v in print_variants], "pool": [index[ck]]})
    lines.append("    %d row(s): NOT CHECKED: claim no longer in the union" % gone)
    lines.append("    %d row(s) not linkable (no claim)" % unlinkable)
    return lines, gaps
