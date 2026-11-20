# Posting fetch: reading a LinkedIn posting when no browser could

The setting is `search.posting_fetch`. **From jobsearch 0.90.0 the fetch is automatic**: unless you turn it off, the
plugin uses it for a LinkedIn role that no browser could read on a run. Everything below says what it does, so you
can decide whether to keep it.

## The problem it answers

To read a LinkedIn posting, the plugin opens it in the Browser pane. When the pane is hidden, or the page does not
draw, the posting is not read. Since 0.85.0 such a role is *held*: it is not counted as a failure, it is tried
again on a later run, and the run summary says so:

```
HELD: 5 (oldest 2d; 0 now your read; 4 by pane line, 1 by tab only): the Browser pane was hidden or the reader's tab was not in front, so these roles were not read. Show the pane during a run, or see docs/user/jobsearch/posting-fetch.md (search.posting_fetch).
```

The simplest fix is to show the Browser pane during a run. The posting fetch is the last step after the browsers,
for a run where that did not happen.

## The order for one posting

1. **The Browser pane.** The plugin reads the page, and when the read comes back empty it checks whether the page is
   actually drawing. A hidden pane on its own no longer stops the read; whether the page draws decides.
2. **Claude in Chrome**, if the pane cannot draw the page and you are at the computer for this run. It works in a tab
   of its own in your Chrome on this computer, and the run says so once when it starts. A scheduled run that nobody
   is watching skips this step, because Chrome may stop to ask you to allow the site and nobody would answer.
3. **The posting fetch**, described below, only when both browsers could not read the page for a reason that is
   about the browser, not the posting.
4. **Nothing.** The role is held and tried again on a later run. The run summary names it as `NOT CHECKED`.

The run summary counts each step:

```
BROWSER FALLBACK: extension read 2, could not 1 (not-connected 1), fetch read 3, withheld 1 (sandbox-unconfirmed 1), NOT CHECKED 1
```

## What it does

After the browsers have tried a role on this run and could not read it, the plugin makes one request for that role's
public, logged-out posting page and copies the description it finds, word for word. It never summarises. If the page
says the role is no longer accepting applications, the role is recorded as closed. Anything else (an unfamiliar page,
a refusal, a wrong page) records nothing about the role, and the role keeps the result the browser gave it.

It runs **only after a browser read could not happen** on this run. It never runs first, and it never runs on a role a
browser read. If the pane drew the page and the posting still could not be read, that is the posting's own result,
and the fetch does not run. If Chrome showed a sign-in wall or a CAPTCHA, or you declined Chrome's request to allow
the site, the fetch does not run either: a logged-out read must not get round a wall or your "no".

The first automatic request of each run prints the terms below once.

## What is sent

One `GET` to `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>` per role. The only header the plugin sets
is `User-Agent`, which names this plugin and its repository. Your computer's HTTP library adds `Host`,
`Accept-Encoding` and `Connection`. There is no cookie and no sign-in: LinkedIn sees a logged-out visitor.

## Before anything is sent: your sandbox settings

Each time the fetch step starts, before it sends anything, the plugin reads the Claude Code settings files the session actually loads, and sends nothing
unless they show that `www.linkedin.com` is allowed. It sends only when one of these is true:

- the command sandbox is off (no `HTTPS_PROXY`, `https_proxy`, `ALL_PROXY` or `all_proxy` is set); or
- `www.linkedin.com` is listed in `sandbox.network.allowedDomains`, or allowed by a `WebFetch(domain:www.linkedin.com)`
  rule, in your own `~/.claude/settings.json`, or in the profile folder's `.claude/settings.json` or
  `.claude/settings.local.json` when the run was started from the profile folder.

It sends nothing, whatever else is set, when your settings use `strictAllowlist`, when an administrator's managed
settings file sets any `sandbox` key (only that file's list then counts), when `www.linkedin.com` is denied anywhere it
reads, or when one of those files exists and cannot be read.

When the check cannot show the host is allowed, the role records `sandbox-unconfirmed` and the run prints how to
allow it:

```
allow it: list www.linkedin.com in ~/.claude/settings.json sandbox.network.allowedDomains, or run from the profile folder after `posting_fetch.py --set on`
```

The upgrade to 0.90.0 never changes a sandbox setting. If you never allowed the host, the fetch stays silent until you
do. Settings an administrator pushes from a server, or a device-management profile, cannot be read by a script; if
they block the host, the request may still be refused or prompt.

## The notice in your asks

The automatic fetch is announced by one entry in your asks (`data/asks.jsonl`, id `ask-posting-fetch-auto`). The
0.90.0 upgrade adds it, a new profile is created with it, and every `posting_fetch.py --set` rewrites its text for the
new setting. Resolving it changes nothing and does not stop the fetch. If the entry is missing and the setting is
not set, the fetch sends nothing, and the run says so (`notice-missing`) with the command that restores it.

## Limits

| limit | value |
|---|---|
| requests per run, per machine | **40** |
| pause between requests | **3 seconds plus up to 1 second of random extra** |
| when LinkedIn says "too many requests" | wait once (up to 30 seconds), then skip the role. Nothing is recorded against the role |
| when LinkedIn refuses or answers with anything unexpected | skip the role and record nothing. After three such answers the fetch stops for the rest of the run |

The limits are per machine and per run. Machines that share one internet address add up.

## What it never does

- **It never sends a GET to a LinkedIn job-view address on the first pass.** Every LinkedIn role first prints
  `RESIDUE <id> (render): browser-first` and waits for the browsers.
- It never sends anything when the setting is `off`, when the setting holds a value it cannot read, or when your
  sandbox settings do not show the host is allowed.
- It never summarises or rewrites a posting.
- It never signs in, sends a cookie, or acts on your account. LinkedIn actions are never automated.
- It never records a role as gone, blocked or failed because of what the endpoint answered.
- It never quits or relaunches your Chrome.

## The terms: your decision

LinkedIn's `robots.txt` disallows this path, and LinkedIn's User Agreement (section 8.2) restricts automated access
to its service. The plugin's maintainers decided to offer this fetch for personal use, as a method for when the
browser breaks on someone's machine, and read robots.txt as guidance for crawlers, not as access authorization. That
is the maintainers' reading, not LinkedIn's permission. From 0.90.0 the fetch runs without asking first, and the
notice above tells you so. If you are not comfortable with it, turn it off. Nothing else in the plugin depends on it.

## Turning it off, on, or back to automatic

```
~/.claude/jobsearch/run posting_fetch.py --set off
~/.claude/jobsearch/run posting_fetch.py --set auto
~/.claude/jobsearch/run posting_fetch.py --set on
```

| setting | what the fetch does |
|---|---|
| not set (the default) | automatic: runs after both browsers could not read the page, when your sandbox settings allow the host and the notice entry exists |
| `off` | **never runs**, automatic or not. An `off` you set before 0.90.0 stays `off` |
| `on` | runs after any failed browser read of the page on this run (the 0.85.0 rule), when your sandbox settings allow the host |
| any other value | never runs; the run prints why |

- `--set off` writes `off` and updates the notice. It leaves `www.linkedin.com` in the profile folder's sandbox list if
  it was there, and says so; remove it by hand if you no longer want it.
- `--set auto` prints the terms, removes the setting (back to automatic), and updates the notice.
- `--set on` prints the terms **before** it changes anything, then adds `www.linkedin.com` to the profile folder's
  `.claude/settings.json` (`sandbox.network.allowedDomains`) and writes `on`. If it cannot allow the host, it writes
  nothing and says why. If your administrator controls the sandbox, the profile folder's entry is ignored and the
  check above refuses to send.

## Where it keeps files

Under the plugin's state directory for your profile, never in your data files: `cache/posting_fetch.json` (the
run's request count and pacing) and `cache/bodies/` (the text it copied, which is public posting text). Both are
deleted after seven days. If the state directory is lost, the cap for that run resets once.
