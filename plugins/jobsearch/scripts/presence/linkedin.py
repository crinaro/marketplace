"""linkedin: the LinkedIn-coverage section (design-presence-report.md §5.6, D-LI) over the stated values the one replay
(`presence/changes.py`) derives.

- **Status first.** A stated status of `none` or `skip` prints `LinkedIn: not applicable (stated <date>)` or `LinkedIn:
  not tracked (stated <date>)`, raises no `li:` gap and asks nothing.
- **Headline:** each target title present or absent in the stated headline, by §5.1's matcher; none present raises
  `li:headline@<h>`, its pool the `[public]` union bullets.
- **Skills:** the top `TOP_TOPICS` recurring topics by the number of pursued roles whose verdict is aligned or partial,
  ties by slug. A skill matches a topic when `slug(skill) == topic`; a topic no stated skill matches raises
  `li:skill:<topic>`, its pool the `[public]` union bullets that pursued-role rows of that topic cite as `claim`.
- **Not stated:** no headline or skills row and no status prints `LinkedIn headline and skills: not stated` and the
  command that states them: a question, and the unchecked input `linkedin`.

Pure over rows already read and checked; nothing here reads a file or writes."""

from presence import changes, titles
from presence.skill_slugs import slug
from presence.union_text import is_public

TOP_TOPICS = 5
STATE_COMMAND = ("record.py presence-state linkedin headline --text-file <f> | linkedin skills --from-file <f> | "
                 "linkedin status none|skip|active")
QUESTION = "the LinkedIn headline and skills are not stated (%s)" % STATE_COMMAND
OFF = {"none": "not applicable", "skip": "not tracked"}


def stated(rows):
    """`{field: (value, row)}` for status, headline and skills."""
    return {f: changes.current(rows, "linkedin", f) for f in ("status", "headline", "skills")}


def section(rows, titles_list, top, cited, union):
    """`(lines, gaps, unchecked reason or None, question or None)`.

    `titles_list` is the usable target titles (empty when unchecked); `top` the top topics; `cited` `{topic: [union
    bullets]}`; `union` the union bullets, or None when the union is unchecked (every pool is then None)."""
    st = stated(rows)
    status, srow = st["status"]
    if status in OFF:
        return ["  LinkedIn: %s (stated %s)" % (OFF[status], srow.get("created"))], [], None, None
    (head, hrow), (skills, krow) = st["headline"], st["skills"]
    if hrow is None and krow is None and srow is None:
        return (["  LinkedIn headline and skills: not stated", "    state them: " + STATE_COMMAND], [], "not stated",
                QUESTION)
    public = None if union is None else [b for b in union if is_public(b)]
    lines, gaps = [], []
    if hrow is None:
        lines.append("  headline: not stated")
    elif titles_list:
        shown, present = titles.headline_lines(head, hrow.get("created"), titles_list)
        lines.extend(shown)
        if not present:
            gaps.append({"key": "li:headline@%s" % titles.title_hash(titles_list), "target": "linkedin",
                         "field": "headline", "variant_id": None, "before": head, "pool": public, "public": True})
    else:
        lines.append("  LinkedIn headline (stated %s): %s" % (hrow.get("created"), head))
    if krow is None:
        lines.append("  skills: not stated")
    else:
        have = {slug(s) for s in skills or ()}
        lines.append("  skills (stated %s): %s" % (krow.get("created"), ", ".join(skills or ())))
        lines.append("  top %d recurring topics: %s" % (TOP_TOPICS, ", ".join(top) if top else "none"))
        for t in top:
            if t in have:
                continue
            lines.append("    li:skill:%s  no stated skill matches" % t)
            pool = None if union is None else [b for b in cited.get(t, []) if is_public(b)]
            gaps.append({"key": "li:skill:%s" % t, "target": "linkedin", "field": "skills", "variant_id": None,
                         "before": list(skills or ()), "pool": pool, "public": True})
    question = QUESTION if (hrow is None or krow is None) else None
    return lines, gaps, None, question
