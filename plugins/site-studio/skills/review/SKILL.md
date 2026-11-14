---
name: review
description: 'Check the built site before publishing: run the gates, then content-editor and privacy-guard in parallel, then the link report, then visual-qa, and report one ordered list. Use before every publish or after a large change. Not for proposing new directions (ideas); it never publishes (publish).'
---

# Review

One ordered list of what is wrong with the build that would be published, and a privacy record
bound to exactly that build. This skill never publishes; the person types `/site-studio:publish`
when the list is clear.

Every script runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"`. Agent briefs name the
dev repo's root and the scripts directory (`${CLAUDE_PLUGIN_ROOT}/scripts`, expanded).

## 1. Gates

`check_site.py --json` on the build. Every family runs (structure, comments, links, reachable,
privacy, domain, media, unfinished, performance, head, nav, basepath, size); none can be waived. A
gate failure goes first in the list. Read the privacy family's PDF line (`PDFs: N read, M NOT
READ`) and carry it into the list as printed.

## 2. Begin the privacy record

Commit any pending change first: the review is of the committed tree, never the working files.

`review_record.py begin`. It builds the publish build into `.site-studio/review/`, computes its
digest, works out the coverage set (every public image, PDF and capture card that is new or changed
against the live site, or all of them when there is no baseline), and writes
`.site-studio/review/packet.json`. It prints the packet's path and which baseline it used.

## 3. content-editor and privacy-guard, in parallel

- **`privacy-guard`**: hand it the packet path **and nothing else**. No summary of the change and
  no reassurance: a fresh view is the point. It writes `.site-studio/review/opened.txt` (every
  file it opened) and a findings file with stable ids `F1`, `F2`, …, and proposes `clear` or
  `blocked`.
- **`content-editor`**: hand it the changed pages and the build to read them in.

## 4. The link report

`check_site.py --report` prints the external links for a person to judge (an old site, a draft, a
link that moved). Show the list; the person says which to change.

## 5. visual-qa

`render.py` on the changed pages (390 and 1440 wide, light and dark, full height). Then hand
`visual-qa` the screenshot folder and the change in one sentence. With no Chrome, `render.py`
refuses: put that in the list as "visual check not run", never as passed.

## 6. One ordered list

Read each agent's file. Give the person one list: gate failures, then privacy findings, then
untraced facts, then other content findings, then visual defects, then links. Each row says where
it is and what would fix it. Then say what was **not** checked: files privacy-guard did not open,
PDFs not read, widths not rendered.

## 7. Record the verdict

The verdict is the person's call on privacy-guard's proposal:

- **clear:** no privacy findings, and every coverage-set file opened;
- **accepted:** findings exist and the person accepts each one by id, knowing it goes public;
- **blocked:** anything else. Fix the source and review again.

`review_record.py add --packet .site-studio/review/packet.json --verdict <verdict> --opened .site-studio/review/opened.txt`
with `--accept F1,F3` for an accepted verdict. There is no digest argument: the script rebuilds,
refuses if the build changed since `begin`, refuses `clear` or `accepted` when a coverage-set file
is missing from the opened list, and refuses `accepted` unless every finding id is named. It
appends the row and commits `.site-studio/reviews.jsonl` locally; publish pushes it.

Record in `HANDOFF.md`: the verdict, the digest's first 12 characters, and what is still open.
