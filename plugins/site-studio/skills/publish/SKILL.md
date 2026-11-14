---
name: publish
description: 'Publish the built site to its public repo after a dry run you approve. Not for checking the site first (review).'
disable-model-invocation: true
---

# Publish

The person typed this. What goes public stays public, so every step is checked by a script, and
the last word is the person's at a prompt the plugin raises. Never reproduce these steps another
way, and never push the public repo by hand.

Every script runs as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"`.

## Where publishing runs

- **The person's own computer** (the desktop app or a terminal, macOS or Linux): yes.
- **A cloud session** (`CLAUDE_CODE_REMOTE` is `true`): no. `deploy.py` and the guard refuse with:
  "site-studio 0.1.0 publishes only from a session on your own computer. Open this repo there and
  type /site-studio:publish." That is policy; say it and stop.
- **A scheduled run or `claude -p`:** no one can answer the prompt, so it never publishes.

## 1. The reviewed commit must be on `origin/main`

The public site is published from a reviewed commit that is on the dev repo's `origin/main`.
**`deploy.py` refuses otherwise**: it checks `git merge-base --is-ancestor HEAD origin/main` after
a fetch, and refuses when HEAD is not on `origin/main`.

- The tree must be clean. The review's own commit (`.site-studio/reviews.jsonl`) is committed by
  `review_record.py`; it still has to be pushed.
- **On a `claude/*` worktree branch** (the desktop app's default): push that branch, then merge it
  into `main` (a pull request in the private dev repo, or a fast-forward the person approves),
  then `git fetch origin`. Pushing asks the person each time.
- On `main`: push it.

Then confirm `git merge-base --is-ancestor HEAD origin/main` exits 0 before going on.

## 2. Dry run

`deploy.py --dry-run`. It builds the publish build, runs every gate, clones the public repo into a
temporary folder, makes a local commit of exactly the build's files, refuses if any private path
is in it, recomputes the digest from that commit's own tree, runs every gate again on it, and
prints the file list, the privacy review row and `confirm: <digest>`. It needs no Chrome.

## 3. The privacy record

The dry run reads the review row for this exact digest. Anything other than `clear` or `accepted`
refuses, and names `/site-studio:review` as the step to run. A review is for one build: any byte
changed since means a new digest and a new review.

## 4. The person's yes

Show the file count, the review row (verdict, date, how many files were opened, accepted findings)
and the commit message you propose, and let the person change the message.

## 5. Confirm

`deploy.py --confirm <digest> "<message>"`, with the digest the dry run printed.

**The plugin's guard asks the person before this runs.** A `PreToolUse` hook matches
`deploy.py --confirm` and decides from the session's permission mode:

| permission mode | the guard |
|---|---|
| `default`, `acceptEdits`, `plan` | **asks** the person, showing the file count, the review row and the digest |
| `auto` | **asks**, conditional on probe P-7: in auto mode a hook's ask *normally* goes to the permission prompt. Until P-7 passes, "publish asks you first" is UNVERIFIED in auto mode |
| `bypassPermissions`, `dontAsk`, **any other value, or no mode at all** | **denies**, naming the reason: publishing asks every time, and this session is set not to ask, or its mode is unknown. Switch the permission mode and type /site-studio:publish again |
| a cloud session | **denies**, with the policy sentence above |

The ask is the person's act. Never try to get past a denial.

`--confirm` then repeats the dry run's checks and refuses if the digest differs from the one
confirmed, pushes, checks the remote head is the pushed commit, and re-reads the public repo from a
fresh clone. A mismatch is red: "pushed, but the public tree differs from what you approved".

**If `deploy.py` refuses before pushing, it is one of four checks on the target; nothing was
pushed.** Say which, in its own words:

- **V1, the dev repo's own address:** `publicRepo` in `site.json` is the private dev repo, so
  publishing would overwrite it. Or the dev repo's `origin` is an SSH host alias (such as
  `github-work:o/r`) or not on github.com, so it cannot be compared. Fix: set `origin` to
  `https://github.com/<o>/<r>.git`, or to its SSH form on the host `github.com`; to keep a per-repo
  SSH key, use `git config core.sshCommand`. The refusal names the alias.
- **V2, the public repo:** `gh` cannot read it, it was renamed, it is not public, it is archived,
  or this login cannot push to it. Fix what the line names, or run `/site-studio:setup`'s step 1.
- **V3, where git would really push:** a git setting rewrites the public repo's address to a
  different repo, host or alias. A rewrite to the same repo over SSH is fine. An SSH push goes as
  the account that owns the SSH key, which can differ from the `gh` login V2 read.
- **V4, `main` moved:** the public repo's `main` changed after the dry run. Run the dry run again.
  The script never forces its way past this.

## 6. Pages

`deploy.py` polls the Pages build every 10 seconds for up to 10 minutes, through `gh`, never by
fetching the domain (caches lag):

- **published:** the build is `built` for the pushed commit;
- **failed (red):** the build `errored`;
- **at the time limit (amber):** "pushed and verified; Pages has not finished building after 10
  minutes". Never call that live.

## 7. The Pages check

After `deploy.py` reports, whether it published, is still waiting or is red, run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pages_check.py"`. It only reads. Read out every line it
prints, each with the "Who" it names ("you", "GitHub", "you, at your DNS provider"), and its
summary line. It is interactive and can take a few seconds to a minute. **The check never blocks or
undoes a publish:** exit 3 is amber (something to resolve or waiting), exit 1 means it could not
run (say why); neither changes what was published.

- **A line that says `main` is not protected** (against force-push or deletion): offer, with an
  ask, `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" protect`.
- **A line that says the site-studio ruleset has been changed:** offer, with an ask,
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" protect --fix`. If that line says there are
  several rulesets with that name, `protect` refuses; read it out and leave it to the person.
- **A line that says rulesets are not available on this plan** is an `[info]` line, not a
  to-resolve one. **Never offer plain `protect` for it**: a ruleset cannot be added on that plan.
  Say that publishing is unaffected. Once per session, you may offer, with an ask, the fallback
  that works without rulesets: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" protect --classic`
  (classic branch protection that blocks only force-push and deletion of `main`). If `protect`
  itself exits 5 after an offer, the same one `--classic` offer applies. Nothing more.
- A "no" to the offer is respected for the rest of the session.
- Lines about other people who can push, a rule that can refuse a push, or a check that could not
  run are the person's to resolve. Read them out; do not act on them.

## 8. Record

In `HANDOFF.md`: what was published, the public commit, the digest, the Pages status, what the Pages
check still reported, the date.
Commit it with its explicit path.
