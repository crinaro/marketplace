# Posting fetch: reading a LinkedIn posting when the browser could not

The setting is `search.posting_fetch`. It is **off unless you turn it on**, and turning it on is your decision.
Everything below says what it does, so you can make that decision.

## The problem it answers

To read a LinkedIn posting, the plugin opens it in the Browser pane. When the pane is hidden, or the page does not
draw, the posting is not read. Since 0.85.0 such a role is *held*: it is not counted as a failure, it is tried
again on a later run, and the run summary says so:

```
HELD: 5 (oldest 2d; 0 now your read; 4 by pane line, 1 by tab only): the Browser pane was hidden or the reader's tab was not in front, so these roles were not read. Show the pane during a run, or see docs/user/jobsearch/posting-fetch.md (search.posting_fetch).
```

The simplest fix is to show the Browser pane during a run. The posting fetch is a second way, for a machine where
that does not work.

## What it does

With `search.posting_fetch` on, after the browser has tried a role on this run and could not read it, the plugin
makes one request for that role's public, logged-out posting page and copies the description it finds, word for word.
It never summarises. If the page says the role is no longer accepting applications, the role is recorded as closed.
Anything else (an unfamiliar page, a refusal, a wrong page) records nothing, and the role keeps the result the browser
gave it.

It runs **only after a browser read could not happen**: the pane was hidden (`pane-hidden`) or the page did not
render (`render-failed`). It never runs first, and it never runs on a role the browser read.

## What is sent

One `GET` to `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>` per role. The only header the plugin sets
is `User-Agent`, which names this plugin and its repository. Your computer's HTTP library adds `Host`,
`Accept-Encoding` and `Connection`. There is no cookie and no sign-in: LinkedIn sees a logged-out visitor.

## Limits

| limit | value |
|---|---|
| requests per run, per machine | **40** |
| pause between requests | **3 seconds plus up to 1 second of random extra** |
| when LinkedIn says "too many requests" | wait once (up to 30 seconds), then skip the role. Nothing is recorded against the role |
| when LinkedIn refuses or answers with anything unexpected | skip the role and record nothing. After three such answers the fetch stops for the rest of the run |

The limits are per machine and per run. Machines that share one internet address add up.

## What it never does

- **It never sends a GET to a LinkedIn job-view address by default.** With the setting off, the plugin makes no
  request to LinkedIn for a posting at all; it prints `RESIDUE <id> (render): browser-first` and waits for the
  browser.
- It never summarises or rewrites a posting.
- It never signs in, sends a cookie, or acts on your account. LinkedIn actions are never automated.
- It never records a role as gone, blocked or failed because of what the endpoint answered.

## The terms: your decision

LinkedIn's `robots.txt` disallows this path, and LinkedIn's User Agreement (section 8.2) restricts automated access
to its service. The plugin's maintainers decided to offer this fetch for personal use, as a method for when the
browser breaks on someone's machine, and read robots.txt as guidance for crawlers, not as access authorization. That
is the maintainers' reading, not LinkedIn's permission. The plugin ships with the fetch off so that the choice is
yours, and the person who turns it on carries it. If you are not comfortable with it, leave it off. Nothing else in
the plugin depends on it.

## Turning it on and off

```
~/.claude/jobsearch/run posting_fetch.py --set on
~/.claude/jobsearch/run posting_fetch.py --set off
```

`--set on` prints the terms above **before** it changes anything, then allows `www.linkedin.com` in this project's
`.claude/settings.json` (`sandbox.network.allowedDomains`) and writes the setting. If it cannot allow the host, it
writes nothing and says why. `--set off` writes the setting and leaves the host allowed, and says so. If your
administrator controls the sandbox, the project entry is ignored and the first request fails; the run summary then
prints `POSTING FETCH: host unreachable ... check sandbox.network.allowedDomains`.

The 0.85.0 upgrade never turns this on. It prints one line about it, once.

## Where it keeps files

Under the plugin's state directory for your profile, never in your data files: `cache/posting_fetch.json` (the
run's request count and pacing) and `cache/bodies/` (the text it copied, which is public posting text). Both are
deleted after seven days. If the state directory is lost, the cap for that run resets once.
