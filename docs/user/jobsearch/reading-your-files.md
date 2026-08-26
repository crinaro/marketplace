# Reading what the search produces

The search writes files that exist to be read by you — company knowledge, call preps, drafts
awaiting your review, and the dashboard. They are not all the same kind of file, and **they do
not all open in the same tool**: the dashboard is HTML and wants a browser, everything else is
markdown and wants a markdown viewer. Open one in the wrong tool and you get something readable
but ugly — raw HTML source, or a wall of `#` and `>` markers where formatting should be.

This page says which file opens where, and walks through every realistic way to get at them.

---

## What there is to read

All paths are inside **your profile directory** (the private folder you created at setup — see
[Your data](your-data.md)).

**Starting with 0.32.0, these files sit inside six phase directories** — `presence/`,
`configure/`, `pipeline/`, `applying/`, `conversations/`, `outreach/` — instead of loose at the
profile root. This happens automatically, the first time you open a session after upgrading; you
do nothing to trigger it. The table below gives the path you'll have once that has happened. If
you open your profile folder and still see the old flat names — `kb/`, `call_preps/`,
`drafts.md`, `cover_letters.md` — your next session hasn't run yet; open one and it moves them for
you before you notice.

| file | what it is | format |
|---|---|---|
| `dashboard.html` | a **tombstone stub** — a note saying the dashboard moved, nothing else. Kept only so double-clicking the old filename tells you where things went | HTML |
| `views/dashboard_artifact.html` | the state view: pipeline overview, what needs you, drafts and letters shown as title + status + location (not in full — see below) | HTML |
| `views/router_artifact.html` | one row per phase (configure, presence, pipeline, applying, conversations, outreach) naming the next action and a count — the page to open first, especially on a phone | HTML |
| `views/phase-<name>_artifact.html` | the detail for one phase, published only when that phase has enough open items to be worth its own page — e.g. `phase-outreach_artifact.html` is where a pending message's **full text** lives | HTML |
| `views/applying.md` | the working queue: roles to apply to, and the follow-up work a submission created. Generated and read-only — never published, regenerated fresh every time you open an application session | markdown |
| `*_url.txt` (`views/dashboard_artifact_url.txt`, `views/router_artifact_url.txt`, `views/phase-<name>_artifact_url.txt`) | the URL of that page's published Artifact — a link, not a page. Only pages that cleared the publish threshold get one | plain text |
| `pipeline/kb/<company>.md` | durable knowledge about one company, e.g. `pipeline/kb/acme-health.md` | markdown |
| `conversations/call_prep_<date>.md` | prep notes for a scheduled call, e.g. `conversations/call_prep_2026-01-15.md` | markdown |
| `outreach/drafts.md` | staged outreach messages awaiting your review | markdown |
| `applying/cover_letters.md` | letters, one per role — a letter carrying an unresolved send-hold shows a `**Blocked until:**` marker and is not ready to submit; see below | markdown |

**The published surface is a small set, not one page.** Earlier versions had one `dashboard.html`
that inlined every draft, letter and kb file in full — it grew to hundreds of KB and kept a local
copy that could silently drift from what was actually published. Now every draft, letter or
knowledge file renders as **title + status + location** on the state view, and its full body
lives once, on its own phase page. `dashboard.html` itself carries no state at all any more.

The datasets (`data/*.jsonl`) are deliberately not in this table — they are for querying, not
reading, and [Your data](your-data.md) covers them. Neither is `.jobsearch/`, a folder you will
also see in your profile: it holds engine diagnostics, not anything about your search, and
[Your data](your-data.md#jobsearch-engine-state-not-your-data) explains what it is.

---

## A marker you may see in `applying/cover_letters.md`

Upgrading to 0.27.0 may add a line under a letter's heading that was not there before:

```
**Blocked until:** unresolved (migrated 0.27.0 from prose)
```

That is not new information. It is a hold that already existed in the letter's own prose — a note
like "wait until they confirm the licensing question" — made structured, so the dashboard can act
on it instead of only a person reading the text. `unresolved` means the hold is real but not yet
machine-checkable: nothing has said **what** it is waiting on.

**What this means for you:** a letter carrying an unmet `**Blocked until:**` line — `unresolved` or
anything else not satisfied yet — renders on the dashboard under *"⏳ Cover letters held — do not
submit yet,"* not in the ready list, even if you consider the letter itself finished. To clear it:

- replace `unresolved` with the real condition once you know it —
  `**Blocked until:** contact:<id> outcome:<accepted|replied|...>` — and the letter moves to ready
  by itself the next time the dashboard is generated, or
- delete the `**Blocked until:**` line if the letter was never actually held.

The original prose that prompted the marker is left in place beneath it — nothing was deleted, only
made visible to the dashboard as well as to you.

---

## Which file opens in which tool

This is the part nothing else tells you, so here it is as a table:

| you want to read | open it in | in the wrong tool you get |
|---|---|---|
| the state view, the router, or a phase page | a **web browser** — double-click the local `.html` file, or open its published Artifact link | a text editor shows thousands of lines of raw HTML |
| the working queue (`views/applying.md`), a call prep, kb file, `outreach/drafts.md`, `applying/cover_letters.md` | a **markdown-rendering viewer** — the desktop app, or an editor with markdown preview | a browser or plain editor shows the unrendered source: readable, but the structure that makes it scannable is gone |
| an Artifact URL | it is just a link — open the file, copy the URL into any browser on any device | — |

Rule of thumb: **`.html` means browser, `.md` means markdown viewer.**

---

## The routes, cleanest first

### 1. The desktop app's `</>` Code side — recommended

Open the Claude Code side of the desktop app in your profile directory and ask for what you
want: *"show me the call prep for tomorrow"*, *"what is in the kb file for Acme Health?"*,
*"read me the pending drafts."* The session finds the file, renders the markdown properly, and
can answer questions about it — which no file manager can. This is the cleanest route because
it is the same place the search already runs, and it needs no extra tooling.

For the dashboard, ask the session to open `views/dashboard_artifact.html` (or `views/router_artifact.html`)
in your browser, or use route 2.

### 2. The published Artifacts — best on a phone

Every daily run republishes the state view and router as claude.ai Artifacts at **stable URLs**
(`views/dashboard_artifact_url.txt`, `views/router_artifact_url.txt`), plus a URL for each phase page
that has enough open items to earn its own publish. Open the router URL first — it names the
next action and a count per phase, and links on to whichever phase page you need. This is the one
route that needs neither the desktop app nor the local folder, which makes it the practical way to
check state from a phone. **A pending message's full text lives on the outreach phase page, not
the dashboard** — drafts and cover letters show as title + status + location everywhere else, and
since the fix for issue #20, kb files and call preps render as content on their own phase pages too.

Every one of these Artifacts is **default-private** to your claude.ai account. Each shows what the
last run published; for state newer than the last run, use routes 1 or 3. `views/applying.md` —
the working queue — is never published this way; see route 1 or 3 for it.

### 3. The local folder, with a markdown-capable editor

Everything is a plain file, so any editor opens it — but for the markdown to *render* you want
an editor with a markdown preview. VS Code is the common choice: open your profile folder,
select a `.md` file, and toggle preview with **Cmd+Shift+V** (macOS) or **Ctrl+Shift+V**
(Windows/Linux). Any dedicated markdown viewer works the same way. Without a preview you get
the raw source — every fact is there, the scannability is not.

### 4. The browser, for the HTML only

Double-click `views/dashboard_artifact.html`, `views/router_artifact.html`, or any
`views/phase-<name>_artifact.html` and it opens in your default browser, fully rendered, no server
needed — this is the freshest view after a run finishes locally, since these local files are
generated in the same step as the published copy. Do **not** double-click `dashboard.html` for
this — it is a tombstone stub, kept only to tell you the dashboard moved. Do **not** open the
`.md` files this way either — a browser does not render markdown, so a call prep (or
`views/applying.md`) becomes a single run-on wall of text.

### 5. Your profile's private git remote, if you have one

If you followed the backup recommendation and your profile syncs to a **private** git
repository, the hosting site's web view renders markdown files properly — which quietly gives
you a phone-friendly reader for kb files and call preps too, at whatever freshness your last
push was. This route is only as private as that repository; keep it private.

---

## The morning-of-an-interview case

A call prep exists precisely because something is scheduled soon, so the fast paths matter:

- **At a computer:** route 1 — ask the session for the prep by date or company.
- **On a phone:** route 2 — the relevant phase page renders call preps as content.
- **No Claude available at all:** route 3 or 5 — the file itself, in anything that shows
  markdown.

---

## What this page is not

It does not decide which of these routes is *supported* — they all are; the plugin's files are
plain HTML and markdown exactly so that no single tool owns them. It also does not cover
editing: for changing files by hand and validating afterwards, see
[Your data](your-data.md#editing-by-hand).
