---
name: adopt
description: 'Convert a site repo that carries its own copy of these tools: keep its content, retire the copies, all on one branch for you to review. Not for starting a new site (setup).'
disable-model-invocation: true
---

# Adopt an existing site repo

The person typed this. Adopt keeps everything that is the person's (content, decisions, brand,
media, their own customisations), retires the local copies of what this plugin now does, and puts
the whole change on **one branch** for the person to review. `main` is untouched until they merge
it. Adopt never touches the public repo, never publishes, and never pushes.

Every step runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/adopt.py" [--repo <dev repo>] <step>`
(the repo defaults to the current directory). Exit codes: `0` done, `1` refused (the line says
why; nothing changed), `3` adopt needs an answer from the person (ask it, record it, re-run).

The person's decisions are kept in `.site-studio/adopt-plan.json`, written only by the `adopt.py`
steps below. Never edit that file by hand.

## Preconditions

Run `adopt.py check` first. It prints `adopt ok: <origin/main or HEAD> <sha> can be converted`, or
refuses with the reason. **It exits `1` while any `you decide` problem exists**, after printing every problem with its fix, so a red `check` is a list to work through, not a failure to report. Do not work around a refusal. Before that line it may print, once, which
tree adopt will convert and whether parity can run (the **parity basis**, below), and every problem
it found in what it would write, all at once, each marked `apply fixes this` or `you decide`.

- On the person's own computer: the desktop app or a terminal. In a cloud session, stop and say
  adopt runs on their own computer.
- The dev repo has no uncommitted changes. Untracked `.claude/worktrees/` and adopt's own plan
  file do not count.
- **adopt fetches for itself.** `check`, `inventory`, `parity` and `apply` run
  `git fetch origin main` and refuse if the fetch fails. Do not fetch on its behalf. The steps that
  record a decision (`confirm`, `unit`, `fact`, `reviewed`, `paper`, `folder`, `kind`) make no network
  call. They work against the `origin/main` that the last `inventory` fetched, so run `inventory`
  first.
- **The parity basis: one commit, which every step uses.** It is the checkout's `HEAD` when `HEAD`
  is origin/main or is ahead of it (a fast-forward), and `origin/main` otherwise. The inventory, the
  converted tree, both sides of parity, the new branch's parent and the "has anything moved" check all
  use that one commit. So "fix it, commit it, run adopt again" works, on a `claude/<name>` session
  worktree (the desktop app starts each session on one) and on `main` alike: adopt does not need
  the checkout to be on `main`. **When `HEAD` is ahead, adopt says so first and lists the commits;
  the apply branch will include them. Show that list to the person before you go on.** If `HEAD`
  has diverged from `origin/main`, or fallen behind it, adopt converts `origin/main`, says up front
  that **parity will be UNVERIFIED**, and the local builder is kept; tell the person to bring the
  branch and `origin/main` together first if they want parity. A commit made after the inventory
  moves the basis, and `apply` refuses with "the parity basis moved since the inventory": run
  `inventory` again.
- **The repo must be one adopt can read:** `site/site.json` exists and carries `name`,
  `siteTitle` and `publicRepo`. Anything else (another site generator, no `site/site.json`, a
  `site.json` without those keys) is refused with a pointer to `/site-studio:setup`; say so and
  stop. A `site.json` that already has `schema` and `engine` is refused as already converted.

## 1. Inventory: match by what each file does

`adopt.py inventory` (add `--json` for the full record, which carries `problems`, each with its fix, and
`sections`, the `{{#page:...}}` sections adopt wrote from local tokens). It walks `.claude/agents`,
`.claude/commands`, `.claude/skills`, `scripts/`, `tools/`, `site/*.js`, `CLAUDE.md` and
`.claude/settings.json`, and classifies each file by what it does, not by its name. Show the
person one table: the local file, what it does in one line, the plugin counterpart, the evidence
(score, residual, signals), the proposed action. Read every flagged file yourself before you show
it. A **SHADOW** warning means a local agent has the name of one of the plugin's agents. That holds
whatever the file does: a project agent outranks the plugin's agent of the same name when it is
called by its bare name, so **while the file is kept** it replaces the plugin's agent, on this
computer and on any computer the repo is cloned to. The inventory says whether the file does the
same job (and what it scored) or only shares the name. Show every SHADOW line, and for a file that
stays, suggest renaming it to `<name>-local`. Adopt reads this repo's `.claude/agents/` only: a
same-named agent in the person's own `~/.claude/agents/` also replaces the plugin's, and adopt
cannot see it. The plugin's own review and ideas steps call its agents by their scoped names
(`site-studio:<name>`), which a same-named file does not replace. Show any `tokens the plugin's
build will refuse` line as well.

Record each decision as the person makes it:

- **DUPLICATE:** removed only after the person confirms: `adopt.py confirm <path>`. To keep it:
  `adopt.py confirm <path> --keep`. Any residual units are shown first.
- **PARTIAL:** kept by default. Go through every residual unit the inventory lists, by its id:
  `adopt.py unit <path> <unit-id> person-data --kind context|voice|rule [--name <slug>]` ("person
  data, move it"), `adopt.py unit <path> <unit-id> rule` ("a standing rule of mine, keep it for
  every agent": see **Standing rules** below) or `adopt.py unit <path> <unit-id> keep` ("behaviour
  the plugin lacks, keep it"). The file becomes removable only when every unit is decided and none
  is `keep`, or when parity (step 3) passes.
- **AMBIGUOUS:** show both scores; the person decides which capability it is:
  `adopt.py confirm <path> --as <capability>` (or `--keep`).
- **CUSTOM:** kept, listed as a customisation.
- **MIXED** (`CLAUDE.md`, settings): split, in step 4.
- **DATA:** never removed.

`apply` refuses while any file proposed for removal has no decision.

**Problems in what adopt would write.** The inventory (and `check`) lists every problem at once,
each with its fix. **`apply fixes this`** are the mechanical ones: adopt makes the change itself
and lists it in the commit (a clone-URL `publicRepo` becomes `owner/name`; a `previewUrl` loses its
trailing slash; `[key, label]` pairs become the `work.labels` map; a `content/<name>/` folder with
no `page.md` is renamed `content/_<name>/`, kept as source material and not built). **`you
decide`** problems are never rewritten, and `apply` refuses until the person settles them. For a
folder with no `page.md`, ask whether it should be source material (the default) or a portfolio;
for a portfolio run `adopt.py folder <name> portfolio`, and `adopt.py folder <name> source` undoes
it. When apply replaces a value, it also names each file the person keeps that still holds the old
text (`file:line`, under "Your own script may depend on the old form"): read that list to the
person, because adopt cannot tell whether their script needs updating.

**Old addresses (meta-refresh pages).** A hand-made page under `site/src/` that is nothing but a
redirect (a refresh with a delay of 0, a canonical link, a link or a script to the same place, and a
few words) is listed as a problem `apply fixes`: apply writes it into `site.json` `redirects`, keyed the
way the build serves it, deletes the page and lists it in the commit, with any text it drops. The build
then writes an equivalent page at the same address. A refresh page that is more than that (a delay above
0, a paragraph of its own, a target the build has no page for, or a key `site.json` already sends
elsewhere) stays a hand page. The inventory and the commit list each one with its reason: read those to
the person. If the site has a local builder, its parity will show the generated redirect page as a
difference from the hand-made one; that is expected: the local builder does not write that page, so parity reports DIFFERENT, and the person
decides whether to accept it with `adopt.py parity --accept` (step 3).

**What the site does, and its kind.** After the problems, the inventory lists the features it found
(a resume link that disappears when there is no resume, pieces marked `featured: true`, a hand-made
home page, an old address that forwards, custom field names) and what site-studio does about each; a
local token with no row says "site-studio has no equivalent". Read that list to the person. It then
says which **site kind** it infers (`portfolio`, `hub` or `custom`): that is only a proposal. Ask the
person which kind the site is, and record the answer with `adopt.py kind portfolio|hub|custom`.
**Apply writes only a kind the person confirmed**: with none, it writes none and says in the commit
how to set one; `portfolio` is the default and is never written. A hub or custom site is written as
schema 2.

**Standing rules.** A residual unit marked `rule` is carried, verbatim and with its source path,
into the site repo's `CLAUDE.md` under `## Standing rules carried by adopt`, after the file it came
from is removed, and the commit lists each. It is refused on a file that stays: a rule travels only
out of a file adopt removes. Every agent the plugin dispatches loads the project's `CLAUDE.md`, and
probe P-B (`tests/probes/PB-RESULT.md`, Claude Code 2.1.325, a terminal session) measured that a file
under `.claude/rules/` reaches a plugin agent as well. Tell the person they may move those rules
there if they prefer; adopt itself writes `CLAUDE.md` only.

## 2. Keep the person's data, before anything is removed

For every DUPLICATE agent or command, read its body and list the statements that are the person's
data: who they are, their field, their audience, their voice, their standards. The person confirms
each one. Record each confirmed statement:

`adopt.py fact <path> --kind context|voice|rule --text "<the statement>" [--name <slug>]`

`context` (who, field, audience) goes to `decisions/00-context.md`, `voice` (voice and visual
standards) to `BRAND.md`, and `rule` (a person-specific rule) to a new `decisions/NN-<slug>.md`.
Each lands under a heading naming the file it came from and the date. When every statement of a
file is recorded, or the person says it has none: `adopt.py reviewed <path>`.

`adopt.py apply` refuses while any removal's facts are unreviewed, so nothing is removed before
its facts are moved.

**Resume paper size.** Adopt reads it from the repo's existing resume PDF. When it cannot (no PDF,
or one it cannot read), inventory reports that it needs the answer and `apply` exits `3`. Ask the
person whether their resume is Letter or A4, then run `adopt.py paper Letter` or
`adopt.py paper A4`. Never pick one for them.

## 3. Parity: build it both ways

`adopt.py parity` builds the site twice and compares the two. The repo's own builder runs under
`node` on a **temporary copy of the working copy, ignored files included**. The plugin builds from
the parity basis's committed files with the adopt changes applied: **the same commit as the local
side**. Neither build touches the repo.

- Parity runs on the parity basis (see the preconditions): `HEAD` when it is origin/main or a
  fast-forward of it, so a commit the person just made is what is measured. When `HEAD` has
  diverged from or fallen behind `origin/main`, parity is **UNVERIFIED** and the local builder
  stays; adopt says so before it does any work.
- **EQUAL:** the local builder is a duplicate.
- **DIFFERENT:** it is kept, and each difference is listed as a path and its first differing
  line. An ignored file in the working copy is named when it is the likely cause. Show every
  difference. If the person accepts them, so the build becomes the plugin's, run
  `adopt.py parity --accept`, which accepts the listed differences together. Otherwise the local
  builder is kept and the agents and commands can still be retired.
- **UNVERIFIED** (no Node on this computer, the local builder failed, or the plugin build
  refused): never a pass, and the local builder stays.

## 4. Apply: one branch, one commit

Run `adopt.py apply --dry-run` first and show the person what it would do. Then run
`adopt.py apply`. It creates `site-studio/adopt-<date>` **from the parity basis** (`HEAD` when it is
a fast-forward of origin/main, else `origin/main`) in the dev repo, with git plumbing. **The branch
is not checked out**: the person's working tree, index and current branch do not move. It makes one commit, in this order: data files first, configuration second,
removals last. Its message lists what was removed and why, what data moved where, what
configuration changed (every value it normalised, and which kept files still hold the old form),
which hooks were removed or rewritten, what customisations were kept, which commits not yet on
`origin/main` it includes, and the parity result.

Configuration it changes, for you to show as a diff:

- **`CLAUDE.md`:** every section about the person is kept. The engine sections are replaced by
  one pointer to the plugin, and this line, exactly:

  `If /site-studio commands are unknown, this session does not have the plugin (cloud sessions do not install repo-declared plugins); open the repo on your own computer.`

  After that, any standing rules the person marked `rule` are appended under
  `## Standing rules carried by adopt`, each under a `### From <file>` line.

- **`.gitignore`:** gains `.claude/worktrees/` (the desktop app keeps session worktrees inside
  the repo), `site/dist/` and `.site-studio/review/` if they are missing.
- **`.claude/settings.json`:** gains this plugin's registration and ask rules, and keeps every
  rule the person added. For a hook that pointed at a file being removed:
  - it is **removed** when the plugin's own hook does the same job;
  - it is **rewritten** to `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<script>"` when the plugin has a
    counterpart script. Its old arguments are kept;
  - otherwise **the file it needs is kept**.

  Every change is listed. Tell the person plainly: whether `${CLAUDE_PLUGIN_ROOT}` is defined for
  a hook in a project's own settings file is not yet known, so a rewritten hook should be read and
  tried before they rely on it. Apply refuses to finish if any hook still names a file that no
  longer exists.
- **`site/site.json`:** gains `schema`, `engine` and `resume`; every other key is kept, except the
  mechanical fixes listed under "Problems in what adopt would write", each of which is a line of
  the commit. A meta-refresh page it converted becomes a `redirects` entry, and the kind the person
  confirmed (`hub` or `custom`) becomes `siteKind`. It is written as schema 1 unless the converted
  site needs 2 (a label map, a page section, a hand-made home page, a kind other than `portfolio`),
  and the inventory says when it does and why.
- **`HANDOFF.md`:** apply adds the entry itself, **inside the same commit**: the branch name, what
  moved, and what is kept. Do not edit `HANDOFF.md` afterwards, because that would be a second
  commit.

## 5. Review and merge

Show the commit without checking anything out:
`git show --stat site-studio/adopt-<date>`, then `git show site-studio/adopt-<date>` for the full
diff. Never `git checkout` or `git switch` to it.

Adopt has no push step. Offer to push the branch to the **private** dev repo. If the person says
yes, run `git push origin site-studio/adopt-<date>` yourself (the dev repo's own ask rule applies),
and offer a pull request there. Reverting is deleting the branch. Nothing is merged until the
person approves.
