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

Run `adopt.py check` first. It prints `adopt ok: origin/main <sha> can be converted`, or refuses
with the reason. Do not work around a refusal.

- On the person's own computer: the desktop app or a terminal. In a cloud session, stop and say
  adopt runs on their own computer.
- The dev repo has no uncommitted changes. Untracked `.claude/worktrees/` and adopt's own plan
  file do not count.
- **adopt fetches for itself.** `check`, `inventory`, `parity` and `apply` run
  `git fetch origin main` and refuse if the fetch fails. Do not fetch on its behalf. The steps that
  record a decision (`confirm`, `unit`, `fact`, `reviewed`, `paper`) make no network call. They
  work against the `origin/main` that the last `inventory` fetched, so run `inventory` first.
- **A `claude/*` worktree branch is fine.** The desktop app starts each session in a worktree on a
  `claude/<name>` branch. Adopt does not need the checkout to be on `main`: it **branches from
  `origin/main`**, so what it converts is what is on the remote's `main`, whatever branch this
  session sits on.
- **The repo must be one adopt can read:** `site/site.json` exists and carries `name`,
  `siteTitle` and `publicRepo`. Anything else (another site generator, no `site/site.json`, a
  `site.json` without those keys) is refused with a pointer to `/site-studio:setup`; say so and
  stop. A `site.json` that already has `schema` and `engine` is refused as already converted.

## 1. Inventory: match by what each file does

`adopt.py inventory` (add `--json` for the full record). It walks `.claude/agents`,
`.claude/commands`, `.claude/skills`, `scripts/`, `tools/`, `site/*.js`, `CLAUDE.md` and
`.claude/settings.json`, and classifies each file by what it does, not by its name. Show the
person one table: the local file, what it does in one line, the plugin counterpart, the evidence
(score, residual, signals), the proposed action. Read every flagged file yourself before you show
it. A **SHADOW** warning means a local file is named like a plugin agent but does a different job.
It is kept, and because a project agent outranks the plugin's agent of the same name, suggest
that the person rename it. Show any `tokens the plugin's build will refuse` line as well.

Record each decision as the person makes it:

- **DUPLICATE:** removed only after the person confirms: `adopt.py confirm <path>`. To keep it:
  `adopt.py confirm <path> --keep`. Any residual units are shown first.
- **PARTIAL:** kept by default. Go through every residual unit the inventory lists, by its id:
  `adopt.py unit <path> <unit-id> person-data --kind context|voice|rule [--name <slug>]` ("person
  data, move it") or `adopt.py unit <path> <unit-id> keep` ("behaviour the plugin lacks, keep
  it"). The file becomes removable only when every unit is decided and none is `keep`, or when
  parity (step 3) passes.
- **AMBIGUOUS:** show both scores; the person decides which capability it is:
  `adopt.py confirm <path> --as <capability>` (or `--keep`).
- **CUSTOM:** kept, listed as a customisation.
- **MIXED** (`CLAUDE.md`, settings): split, in step 4.
- **DATA:** never removed.

`apply` refuses while any file proposed for removal has no decision.

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
`origin/main`'s committed files with the adopt changes applied. Neither build touches the repo.

- Parity runs only when the working copy matches `origin/main`. Otherwise (for example, this
  worktree has commits not yet on `main`) it is **UNVERIFIED** and the local builder stays.
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
`adopt.py apply`. It creates `site-studio/adopt-<date>` **from `origin/main`** in the dev repo,
with git plumbing. **The branch is not checked out**: the person's working tree, index and current
branch do not move. It makes one commit, in this order: data files first, configuration second,
removals last. Its message lists what was removed and why, what data moved where, what
configuration changed, which hooks were removed or rewritten, what customisations were kept, and
the parity result.

Configuration it changes, for you to show as a diff:

- **`CLAUDE.md`:** every section about the person is kept. The engine sections are replaced by
  one pointer to the plugin, and this line, exactly:

  `If /site-studio commands are unknown, this session does not have the plugin (cloud sessions do not install repo-declared plugins); open the repo on your own computer.`

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
- **`site/site.json`:** gains `schema`, `engine` and `resume`; every other key is kept.
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
