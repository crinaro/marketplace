---
name: ideas
description: 'Call the advisors in on a topic and put two or three concrete options in front of the person. Use for open questions about the look, the content or the presence. Nothing here publishes. Not for checking a build before it is published (review).'
---

# Ideas

Two or three concrete options for the person to choose between, grounded in their own decisions
and in real references. Nothing here edits the site or publishes.

## 1. Frame the question

Say it back in one sentence and name which of the three it touches:

- **the look or the message** (identity, layout, how images are presented, what the site says
  first): `brand-advisor`;
- **the content** (which pieces, in what order, how each tells its story): `portfolio-advisor`;
- **the presence** (titles, social previews, profile text, how people find the site):
  `presence-advisor`.

## 2. Dispatch, in parallel when it touches more than one

Each brief names the dev repo's root, the scripts directory (`${CLAUDE_PLUGIN_ROOT}/scripts`,
expanded) and that advisor's own REQUIRES from its definition. Pass on any constraint the person
said in this session that is not yet in `decisions/`.

## 3. Put the options in front of the person

Read each advisor's file. Give two or three options in all, not three per advisor: what changes,
what it builds on, a real reference, and what it costs. Then one recommendation and the questions
the person must answer first.

## 4. Record what the person decides

Write the decision to `decisions/` (what was chosen, the date, the options that lost) and note it
in `HANDOFF.md`. If nothing was decided, record the open question instead. Building the change is
the next step (`add-work`, `resume`, or an edit to `site/src/` with the person), then `preview`.
