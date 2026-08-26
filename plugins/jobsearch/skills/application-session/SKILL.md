---
name: application-session
description: 'Work through submitting applications: the applying view, resume variant decisions, form answers recorded as data, and the follow-up work each submission creates. Use when the candidate is applying to one or more roles this session. Not a sweep (that is daily-run) and not message drafting in isolation (that is outreach-drafter) — this is the session AROUND submissions, and it generates the outreach triggers those drafts hang from.'
---

# Application session

The working surface for phase 4 (applying) and the trigger half of phase 6 (outreach).
Public #27 is the evidence file for everything here: a worksheet written by hand because no
view existed, a resume-variant instruction leaked into free text and gone stale on the one
deadline role, form answers reasoned out at length and lost to prose, and a drafted ask
sitting unlinked to the application that generated it.

**The shape of this session: the view is where you look; records are where you write.**
`views/applying.md` is generated and read-only (D5 — no markdown round-trip). Every fact on
it lives on a record; when a fact changes, record it and regenerate. Never edit the view,
and never park a decision in a free-text field the view cannot read back.

## Binding — say which profile this session is acting on (dev #150)

```bash
~/.claude/jobsearch/run binding.py
```

**`NO PROFILE` (exit 3) means stop and say so.**

## 1. Open the working view

```bash
~/.claude/jobsearch/run applying.py && ~/.claude/jobsearch/run trigger.py --check
```

Regenerates `views/applying.md`: the queue to apply, follow-up work submissions have
created, and which sequences are unblocked now. A red `--check` is fixed FIRST — an
unreadable trigger or a dangling ref looks handled and is not.

## 2. Per role in the queue, in view order

1. **Verify the posting is live** at the view's link before anything else.
2. **The resume variant line.** `⛔ not decided` means decide NOW, with the candidate, and
   record it on the opportunity (`resume_variant`) before the form is opened. ⚠️ The
   printed-resume gap (dev #234) is open: the variant is a markdown file and the uploaded
   document is produced outside the engine. Confirm with the candidate what was actually
   attached; do not treat the gap as closed.
3. **Answer the form from precedent.** The view lists prior answers per `question_key` —
   same employer first, latest elsewhere second. A `⛔ conflicting precedent` line is
   resolved with the candidate before answering a third way.
4. **Record the application** with `record.py`: the applications[] row carries `date`,
   `method`, `status`, `req_id`, `resume_variant`, an `app_id` minted as `<opp_id>-aN`,
   and **`form_answers`** — one `{question_key, question, answer, answered_on}` per
   question actually answered. Shared slugs (`salary-expectations`, `reason-for-leaving`,
   `ai-usage`, …) make precedent a join; a per-form spelling makes it a search.
   An answer worth reasoning out is worth recording — the alternative measured in #27 was
   re-deriving it from the rule on every equivalent form.

## 3. After each submission — generate the work it created

Submitting CREATES work; nothing may stay linked only in memory (the measured defect:
the highest-value ask in outreach/drafts.md was the one not referencing its application).

- For each follow-up the play calls for (retained-firm relationship ask, insider check,
  chase after N days): create the ask or draft NOW, and stamp the join —
  - a record (`asks`, `outreach[]`): `trigger_kind: application`,
    `trigger_ref: <app_id>` (+ `opp_id` on an ask);
  - a staged draft in `outreach/drafts.md`: a `**Triggered by:** opp:<opp_id> app:<app_id>` meta
    line; a multi-step play also carries `**Sequence:** <sequence-id> step:<n>`, and any
    hold stays in `**Blocked until:**` (precondition.py's field — a sequence groups, it
    never re-spells a hold).
- A constraint on a triggered draft (e.g. "must not disclose the direct application") goes
  in the draft body as text, not in your memory.

## 4. Close the session

```bash
~/.claude/jobsearch/run trigger.py --check && ~/.claude/jobsearch/run precondition.py --check
~/.claude/jobsearch/run applying.py
```

Both checks green, view regenerated. Then report, in one line each: applications submitted,
follow-ups generated (with their triggers), sequences now waiting, and anything the
candidate still owes a decision on.
