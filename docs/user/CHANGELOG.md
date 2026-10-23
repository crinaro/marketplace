# Changelog

Generated from fixes confirmed shipped — public reports and internal fixes alike, each verified against its release tag on the published remote; older releases after their push, the newest one by the publish that pushed it, so the section for the version you installed is in the file that came with it. Sections are grouped by plugin, then by version. Newest first.

## jobsearch 0.74.0
Roles that an older version of the plugin screened wrongly are now brought back to your attention. If a role was removed for pay, or one you'd already decided on would now be screened differently under the fixes in 0.73.0, it shows once in your status panel under "Roles to reconsider" and on your review page. Each entry shows what the old screen said, what it would say now and why, and gives you a one-step command to reopen or re-screen it. Nothing is reopened or changed for you, and once you act on a role or re-screen it, the flag goes away. The plugin also now checks that its own lists of what it stores match what the guides describe.

## jobsearch 0.73.0
Pay screening now respects what you've decided and the kind of work a role is. If you record that a below-floor role's pay is acceptable (record.py decide <role> pursue --why-kind comp-acceptable), the role shows as accepted, keeps the original pay and your floor for reference, and is never removed. Change your mind and the screen goes back to removing it. Fractional, interim, advisory and contract roles are no longer measured against your annual salary floor. If you've set a separate pay floor for that kind of work, they're checked against it; otherwise they're flagged for you to review instead of being removed. Hourly, daily and monthly rates are never compared directly with an annual floor. A role counts as fractional or interim when you've said so on the role or when its title says so, and a role you've marked full-time always stays full-time. Roles waiting for your decision are re-checked automatically. You can now also record a company's careers page, domain, other names and size, which helps the plugin find its job feed.
- [#160](https://github.com/crinaro/marketplace/issues/160) — The comp screen has no engagement-type routing, so non-employee engagements (fractional, interim, advisory) are measured against annual base floors and removed
- [#161](https://github.com/crinaro/marketplace/issues/161) — A recorded comp-acceptable decision does not change the comp screen verdict, so an explicit candidate opt-in is ignored

## jobsearch 0.72.0
Your job search now looks beyond the job boards. For the companies you track that post jobs through Greenhouse, Lever or Ashby, the plugin reads their job listings directly each day, with no browser and no login, so new roles show up sooner. A feed that's broken or unreachable is reported as such, never mistaken for "no roles". Every role that passes your screen now shows a warm-path next step: the people you already know at the company, with a referral ask or a note to the hiring manager drafted for you to send yourself. Nothing is ever sent for you. Wellfound, Welcome to the Jungle and Y Combinator's job board can be added as channels you open yourself, and niche newsletters as alert senders. To read those feeds, the upgrade adds four job-board addresses to your search project's allowed network list; it keeps a copy of your settings first and changes nothing else. The plugin also states plainly what it will never do: auto-apply, automate LinkedIn, use contact databases, or game resume screeners.

## jobsearch 0.71.0
Your job search now has its own panel inside Claude. In the Desktop Code tab and in a terminal, a status band and panel show what needs you, act-by dates, your inbox, and when the daily and weekly runs last ran and run next, without spending any of your Claude usage. Buttons start the daily or weekly run on the spot, and you're told when a background run has queued something for you. The published dashboard now shows only what needs your review: current drafts, roles worth pursuing, and applications to finish. The separate presence page is gone; /jobsearch:review-resume and /jobsearch:review-linkedin bring those reviews up when you want them, and your old page is cleaned up for you with nothing lost. The plugin also says plainly where it runs: Claude Desktop and Claude Code in a terminal on your own machine. Headless and cloud sessions aren't supported.

## jobsearch 0.70.0
Where a role is now decides whether you see it. The plugin ships a public US Census list of places, so a role whose office is far beyond every place you said you'd commute from is removed as too far, instead of sitting in your list undecided — unless it is somewhere you've said you would move to, or you turn on geography.relocation.keep_outside_radius to keep far roles for review (existing setups gain that setting switched off, with a copy of your settings kept). A posting that names a city but never says remote, hybrid or onsite is now screened as onsite and marked as a guess, which you can correct when the job description says otherwise. One job advertised in several cities is now one decision: the listings are linked to a single role, judged by the place that suits you best, and a nearer listing of a role you already passed on is pointed out rather than quietly closed.
- [#157](https://github.com/crinaro/marketplace/issues/157) — The minimal screen keeps an onsite role whose location is unrecognized, so a role far outside the commute radius stays undecided indefinitely
- [#158](https://github.com/crinaro/marketplace/issues/158) — Capture creates one opportunity per job URL, so one posting listed in several cities becomes several new rows with no company-plus-title collapse
- [#159](https://github.com/crinaro/marketplace/issues/159) — A captured role with a location but no remote, hybrid or onsite label is kept as undecided instead of being treated as presumptively onsite

## jobsearch 0.69.1
The check that looks for your personal details accidentally left in the plugin's own files now finishes. It used to run out of time partway through, so it never gave a full answer; it is now fast enough to scan everything in well under a second, skips files that haven't changed since its last complete scan, and if it is ever cut short it picks up where it stopped next time instead of starting over.
- [#149](https://github.com/crinaro/marketplace/issues/149) — check_engine_purity.py default time budgets cannot complete the scan they are wired to run, so routine runs return an incomplete verdict

## jobsearch 0.69.0
A run's own report can no longer contradict what it actually did. If a run's notes say it was quiet but it changed your files, the summary still posts with the real count and the misleading note is shown as withheld, rather than telling you nothing happened; files a run commits partway through now count too. The standing instructions installed in your profile no longer state your current settings, so they can't go stale, and the check that compares your notes against your data now reads those instructions as well. And when a gap in coverage is marked as handled by an issue, it now needs a reason, and if that issue is later found closed the gap counts as open again instead of staying quietly hidden.
Fewer roles you'd never want land in your list, and none are thrown away on a guess. When a job board quietly drops a filter you asked for, adds one you didn't, or cuts the results short, and the search reports it, those roles are held back instead of being added; a clean search that sees them later releases them, and each run's summary now counts how many searches came back clean, unclear or degraded. You can set a title floor, such as director: a lower title never removes a role, because pay is the real test — if the pay is within your range the role is marked worth pursuing, and if pay isn't known yet it asks you to check pay first; roles already waiting are re-checked once against the new setting. A role you decide to pass on is now properly closed instead of lingering in your backlog (existing ones are fixed once, with a copy kept), and a job description that needs a signed-in browser is handed to the next run that has one.
- [#147](https://github.com/crinaro/marketplace/issues/147) — journal.py accepts a covered_by citation that is not topically related to the gap, and a closed citation is only surfaced by an on-demand network check
- [#152](https://github.com/crinaro/marketplace/issues/152) — The shipped rulebook asserts the current value of a profile config key, and no drift gate scans the rulebook
- [#155](https://github.com/crinaro/marketplace/issues/155) — A run-summary's generated headline is correct but the model-authored notes beside it can still assert a quiet run, and the contradiction is only detected after the summary is posted
- [#156](https://github.com/crinaro/marketplace/issues/156) — Daily-run role capture ingests degraded sweeps and the minimal screen's title rule is advisory-only, so sub-criteria roles flood the pipeline as undecided

## jobsearch 0.67.0
Roles reach you better vetted. The pay shown on a listing is now captured, and the screen tells 'no pay shown' apart from 'pay not recorded yet', so a role whose stated range tops out below your floor is removed instead of reaching your list; set your currency once (you'll be asked) and listed pay is compared. Pay floors can now be set by commute time, and a hybrid role near home is held to your local floor rather than the higher out-of-area one. Each role shows how long ago it was posted, and a recruiter's search older than five weeks comes with a first step: ask what stage the search is in before doing research or letters. And a role only becomes yours to decide once the job description has been read and it carries a pursue, pass or ask lean; until then it waits under Triaging, a few are read each day, and any still waiting after three days comes to you anyway. Roles already on your list that nobody has read move to Triaging when you upgrade and come back as they're read.
Two things that made every daily run lose work are fixed. Checking your held drafts against your mailbox can no longer hang: each mailbox call now gives up after a set time, the check stops itself before the run's limit, keeps every result it already has, and tells you who it didn't reach so the next run picks them up. And a job-search pass no longer throws away every role it found because of one malformed line: the good roles are kept, each bad line is noted on its own, the pass's report is saved so the problem can be seen, and the report can be checked before it is handed back.
Your mail records are cleaned up and harder to fool. A fault in how message numbers were read could store them in a garbled form, so the same email could be saved twice and later lookups came back empty; numbers are now read correctly, the garbled form is refused, and the first session on this version repairs your files once by itself (each file it changes is copied first) and merges the duplicates. The weekly check no longer counts an automatic application acknowledgement or a no-reply email as someone answering you, and a reply that came by a different route than your message (an email answering a LinkedIn note) is listed separately for you to look at. And the check for drafts you may already have sent only matches something sent for the same opportunity, and asks you to confirm rather than telling you to remove the draft.
- [#142](https://github.com/crinaro/marketplace/issues/142) — Roles carry no posting/search-open date, so effort is not gated on posting age (retained searches especially)
- [#143](https://github.com/crinaro/marketplace/issues/143) — Board capture does not record listed pay, so the comp screen keeps roles whose band top is below the floor
- [#144](https://github.com/crinaro/marketplace/issues/144) — Comp floors cannot be banded by commute time, and a hybrid role inside the commute radius is screened against the out-of-area hybrid floor
- [#145](https://github.com/crinaro/marketplace/issues/145) — No triage gate or configurable likely-pass signals before a sourced role is surfaced as a pursue/pass decision
- [#146](https://github.com/crinaro/marketplace/issues/146) — brief.py --probe --held has no time bound and hangs on every run, so held drafts are never verified
- [#150](https://github.com/crinaro/marketplace/issues/150) — reconcile.py --all counts an automated ATS acknowledgement as a reply to an outreach touch of a different medium, re-raising the same false positive every week
- [#151](https://github.com/crinaro/marketplace/issues/151) — A job-pass ROLES block is refused whole when any single provenance line fails the grammar, so every role the pass saw is lost
- [#153](https://github.com/crinaro/marketplace/issues/153) — check_sent_drafts.py matches a pending draft or letter to a sent touch or application without requiring the same opportunity or company, and its output says to retire the match
- [#154](https://github.com/crinaro/marketplace/issues/154) — An IMAP message uid is stored as a Python bytes repr in source tags, which breaks the source re-verification key AND defeats de-duplication so the same mailbox message is stored twice

## jobsearch 0.64.0
Your dashboard is reorganised around what you do every day. Drafts and Opportunities now sit at the top, with a bar that stays pinned as you scroll so either list is one tap away. Opportunities are grouped by where each role stands, in plain words, and the follow-up view shows what's due in the next few days. Each draft has a Copy as prompt button: paste it into your job-search session with your correction and it's applied for you, showing the before and after. Channel bookkeeping moves off the daily page to a one-line summary.
- [#48](https://github.com/crinaro/marketplace/issues/48) — The generated dashboard is a complete unfiltered inventory, not a today-oriented, navigable decision surface
- [#58](https://github.com/crinaro/marketplace/issues/58) — the opportunities surface presents three overlapping filter dimensions in engine vocabulary, one of them degenerate, and none of them expresses the question the user actually opens the page to ask
- [#87](https://github.com/crinaro/marketplace/issues/87) — Artifact comments are readable, but nothing writes a reviewer's correction back into the draft store — the in-chat revise loop has no equivalent on a published surface
- [#131](https://github.com/crinaro/marketplace/issues/131) — Dashboard's Sourcing/channel sections duplicate markdown data with little added value; the dashboard should stay activity-focused
- [#132](https://github.com/crinaro/marketplace/issues/132) — The top router's phases each build separate sections instead of filtering the existing lists they duplicate
- [#133](https://github.com/crinaro/marketplace/issues/133) — Consolidate outreach follow-up sections into the Drafts drill-down, defaulted to a 2-5 day sendable view

## jobsearch 0.63.0
Your job search's mailboxes now point at the accounts gmail-multi already knows, instead of keeping a separate list; this is moved over by itself. If a mailbox in your search isn't one of gmail-multi's accounts, you're told plainly and asked to fix it, rather than it being skipped without a word. A job-search session can also no longer list every email account on your computer.
- [#125](https://github.com/crinaro/marketplace/issues/125) — Mail access is hard-wired to one connector, and the connector's own config has to reach into a profile to find its mailboxes
- [#141](https://github.com/crinaro/marketplace/issues/141) — gmail-multi: reply drafts show literal ">" quote markers inside the HTML blockquote (quote string reused across plain + HTML parts)

## jobsearch 0.62.0
People you know outside any job opening are now first-class. You can record a touch or a message with someone who isn't tied to a role, a sent personal reply clears from your pending list, and a person can be linked to a role later without losing their history. Drafts that aren't ready to send still show their text on the dashboard, labelled with why. A LinkedIn reply to someone who messaged you first is judged by that conversation, not by your mailbox. The dashboard also lists the people you're due to follow up with.
- [#139](https://github.com/crinaro/marketplace/issues/139) — Person-only network outreach (no opportunity, no channel) is a second-class draft: body hidden, touch needs a role, prune refuses it

## jobsearch 0.61.1
Maintenance only: nothing changes for you. The plugin's own test runner can now re-run just the tests that failed.

## jobsearch 0.61.0
A run no longer quietly does less than it reports. Your posture now limits how often the search runs, not how much of what a run finds gets handled: every role a run sees is screened (pay floor, already seen or passed, title rules) or kept as its own follow-up, and research held back by a cheaper posture runs on the next run that allows it. Once a week a wider search catches older or reposted roles the daily search missed. Saving your conversation history during a locked run works again. A run you start yourself as /jobsearch:daily-run attended may do research under any posture. After one run on this version, an older version can no longer read your run journal, so don't roll back.
LinkedIn checks waste less and claim less. A LinkedIn pass that can't finish is queued once, not again on every run. Any profile or message the LinkedIn agent already looked at is recorded, so it isn't looked at again, and the reply check works from an exact list of who to check. A sweep that could only see part of a list no longer reports a connection request as still pending; it says the check was incomplete. Accepted connections are read from your Connections list, and routine sweeps no longer visit people's profiles.
Nothing for you to run. A brief now refuses an opportunity that doesn't exist, instead of saving a record your data check rejects later. New brief ids are long enough that two briefs written in the same second can no longer be mixed up, which could put a false hold on a valid draft.
- [#102](https://github.com/crinaro/marketplace/issues/102) — No periodic wide-window re-scan of the primary job board; only a since-last-run recency window
- [#105](https://github.com/crinaro/marketplace/issues/105) — LinkedIn connection acceptance is inferred from absence on a truncated Sent Invitations list, so accepted invites stay reported as pending indefinitely
- [#109](https://github.com/crinaro/marketplace/issues/109) — LinkedIn cold-hold requires a full browser-agent dispatch even when a script can already prove the hold's condition
- [#112](https://github.com/crinaro/marketplace/issues/112) — Background/scheduled runs cannot composite the Browser pane for interaction tools, and deferred.py re-queues the resulting item forever
- [#138](https://github.com/crinaro/marketplace/issues/138) — reconcile.py --harvest refuses every row when run inside runlock.py --run, because it takes its own lock and ignores the outer one
- [#140](https://github.com/crinaro/marketplace/issues/140) — Posture caps run DEPTH, not just frequency: a run silently drops most of the roles it finds

## jobsearch 0.60.1
Nothing for you to run. Scheduled runs that stopped starting after an update work again. The run helper is repaired automatically the next time Claude starts.
Also fixed, with nothing for you to run. Drafts can no longer name a channel that does not exist. Mail checks now record the real date of a contact's latest message, not the day the check ran. A role you already passed on is no longer shown again as new under a slightly different title.
- [#134](https://github.com/crinaro/marketplace/issues/134) — Generation-3 launcher resolves engine cache to the plugin-slug dir, not the install dir; 'run --where' finds no usable engine and every scheduled run dies
- [#135](https://github.com/crinaro/marketplace/issues/135) — brief.py --probe records the probe's own date as the thread's latest-message date
- [#136](https://github.com/crinaro/marketplace/issues/136) — Re-sourced roles evade the exclusion list when the new row gets a different id
- [#137](https://github.com/crinaro/marketplace/issues/137) — brief.py accepts a channel_id that does not resolve, and the invalid value later fails validate_data.py

## jobsearch 0.60.0
Nothing for you to run. Helper agents now report back briefly, with long detail saved to a file instead of flooding the conversation. When the desktop app's scheduling tools are missing, the coordinator and setup commands now skip those steps and say so, instead of guessing.
Also new: a weekly check that flags when your notes or pending decisions state a figure, search scope or open question that disagrees with your saved settings. It only reports; it never edits your documents. The handoff letter now shows decisions and opportunity stages straight from your records, so it cannot repeat an out-of-date status.
- [#56](https://github.com/crinaro/marketplace/issues/56) — nothing periodically checks whether a value restated in profile prose still agrees with its authoritative home, so a narrative document can contradict the configuration indefinitely and be read as fact
- [#78](https://github.com/crinaro/marketplace/issues/78) — A premise that changes a recommendation can be carried as bare prose with no source or date, and propagate into open decisions and a drafted decline
- [#81](https://github.com/crinaro/marketplace/issues/81) — Generated handoff prose can re-assert pipeline state that the structured records already corrected the same day
- [#106](https://github.com/crinaro/marketplace/issues/106) — coordinator skill assumes the desktop-app surface and has no fallback when its tools are absent (CLI)
- [#111](https://github.com/crinaro/marketplace/issues/111) — Dispatch context is rebuilt by the model on every agent call, and hand-backs are unbounded

## jobsearch 0.59.0
Nothing for you to run. You can now choose which Gmail connector jobsearch uses: gmail-multi or the Gmail connector managed by claude.ai. It uses only the one you pick and says which one in its reports. If you choose nothing, it keeps using gmail-multi, as before.
Also fixed: starting Claude in a folder that is not your job-search profile no longer leaves data/ or .jobsearch/ files behind in that folder. Before this, opening a session in any other project, including a checkout of this plugin's own source, could drop those files into it. Sessions in your profile behave exactly as before.
Two more fixes, and still nothing for you to run. The inbox now shows every waiting item it counts: an item of a kind it has no section for appears under Other instead of being counted but hidden. The daily run's file-hygiene check now stops on time and says so, instead of running on with no output.
- [#123](https://github.com/crinaro/marketplace/issues/123) — Advisory hygiene check can hang indefinitely with no time bound
- [#124](https://github.com/crinaro/marketplace/issues/124) — Inbox default view's pending count disagrees with what it renders

## jobsearch 0.58.0
jobsearch 0.58.0 has nothing for you to run. A new or edited record whose email is a placeholder (example.com, example.org and similar reserved addresses) is now refused, so a made-up address can no longer reach a draft or a send. Existing records are flagged, not refused. Six internal check scripts that nothing called were removed; this changes nothing you use. Several checks that could pass for the wrong reason were fixed, with no change to how the plugin behaves.
- ADR-035 §2.10 residual: 8 real-profile-only skips still unfalsifiable in CI (build the deferred infra) *(tracked internally as crinaro/marketplace-dev#427)*
- 6 more shipped check_*.py gates have no caller anywhere (found building dev #502's gate) *(tracked internally as crinaro/marketplace-dev#503)*
- Checks and tests that pass for the wrong reason, found building gates-that-do-not-gate (5 items) *(tracked internally as crinaro/marketplace-dev#644)*

## jobsearch 0.57.0
One thing changes in how a run reads your mailbox, and there is nothing for you to run. The store-behind-mailbox probe used to search for your name or address anywhere in a message, so an automated sender's own copy of it, a job board receipt or a LinkedIn notification, could register as a live human thread; on one profile it matched on the order of the whole mailbox. It now counts only a message where you were genuinely the sender or the recipient, and only when it came from what looks like a real person. And once you acknowledge one of those findings for a contact, it stays acknowledged instead of returning on the next run and asking you to check the mailbox again. Upgrading carries forward every acknowledgment you already gave, so nothing you already cleared re-queues itself. One limit worth knowing: a newsletter sent from an ordinary-looking address can still be counted, because nothing in your profile records which senders are newsletters.
- [#108](https://github.com/crinaro/marketplace/issues/108) — Cold-register mailbox probe matches on bare name terms and counts automated mail as a live thread

## jobsearch 0.56.0
Two things move in your profile on the first run, and there is nothing for you to run. The rendered-resume default moves out of the profile root into presence/resumes, and the retired root dashboard.html is archived to archive/retired-trackers/ rather than deleted - it used to be regenerated on every run even though it had been retired. Your old file is kept, not thrown away.

The change worth knowing about: a stale watermark could tell you 'UNCHANGED - safe to write' when it was blind to files added to the watched set after the mark was written, so a background run could have moved something underneath you and the check would still have said it was safe. It now reports four distinct answers instead of one, and names which of them means it cannot see part of your data.

Also fixed: a closed role at an organisation where you also have a live role no longer flags the live one; the ATS sweep stops recommending mail domains you have already configured; the dashboard freshness check now looks at all of your stores rather than half of them, so editing a channel touch no longer reads as no change; and a hygiene check that failed on every run is green again.
- [#120](https://github.com/crinaro/marketplace/issues/120) — reconcile.py --ats's 'add domain' hint does not subtract already-configured domains, repeatedly suggesting domains already present
- [#121](https://github.com/crinaro/marketplace/issues/121) — check_action_claims.py's closed-role name matcher flags on a bare company-name substring, so a live and a closed role at the same organization both trigger on every run
- [#122](https://github.com/crinaro/marketplace/issues/122) — changed.py never validates a reader's own watermark, so a stale or schema-mismatched mark compares silently forever
- [#126](https://github.com/crinaro/marketplace/issues/126) — Retired root dashboard.html tombstone is regenerated every run instead of being removed
- [#127](https://github.com/crinaro/marketplace/issues/127) — Rendered-resume default output directory fails the engine's own root-tree audit
- [#128](https://github.com/crinaro/marketplace/issues/128) — Dashboard freshness check's SOURCES list omits touches.jsonl, so a channel-touch edit reads as no-op
- [#129](https://github.com/crinaro/marketplace/issues/129) — check_rule_homes.py fails every run: the mailbox-coverage archive entry's own back-pointer target has no genuine narrative home

## jobsearch 0.55.0
A status you recorded by hand can no longer be overwritten backwards. The mail sweep used to re-read a resolved message on every run and could rewrite a rejection you had recorded back to an earlier status; it now refuses any write that would move an application backwards through its lifecycle, and hands you the disagreement as an ask instead of silently overwriting the record. If one of your ats.status_phrases classes is filled in while another is left empty, the sweep now says so loudly and writes an ask - an empty class beside a populated one does not mean 'unrecognised', it means mail belonging to it is misclassified as the populated one. Records already rewritten repair themselves: the next sweep notices a status sitting below what its own note records and restores it, so there is nothing for you to run. Also corrected: issue #111 was listed as fixed in 0.54.0 and only half of it shipped - the changelog now shows that retraction, and the issue is open again.
- [#130](https://github.com/crinaro/marketplace/issues/130) — The ATS status classifier can overwrite a correct terminal rejection back to an earlier status on every reconcile run

## jobsearch 0.54.0
This release backfills your own data on first run: the 0.54.0 migration rewrites involvements.jsonl and clears next_action_owner/next_action_date on touches recorded before record.py touched/answered propagated automatically, so history opened on 0.54.0 reads as if propagation had always run. Nothing to run yourself; the summary line names anything it could not resolve.
- [#107](https://github.com/crinaro/marketplace/issues/107) — Publish step re-sends byte-identical pages and forces a full-page context read every round
- [#110](https://github.com/crinaro/marketplace/issues/110) — LinkedIn cadence is coupled to run cadence, not separately configurable
- ~~[#111](https://github.com/crinaro/marketplace/issues/111) — Dispatch context is rebuilt by the model on every agent call, and hand-backs are unbounded~~
  ⚠️ **RETRACTED 2026-09-25** — Only half of this shipped in 0.54.0: the dispatch-packet half landed, the hand-back bound did not — every jobsearch agent is still on PLUGIN-AGENT-CONTRACT v2 with no cap. The issue is reopened and the remaining half is not yet released.
- [#113](https://github.com/crinaro/marketplace/issues/113) — variant_out.py --render (local_docx mode) drops paragraphs, truncates bullets to their first line, leaks the preamble heading, and prints literal markdown emphasis — while its own page-count estimate hides the loss
- [#114](https://github.com/crinaro/marketplace/issues/114) — record.py touched/answered writes the touch but never propagates it to the opportunity: involvement status, next_action_owner and next_action_date all stay stale, so completed outbound work keeps rendering as owed
- [#115](https://github.com/crinaro/marketplace/issues/115) — reconcile.py --ats --verify misclassifies pre-first-sweep mail as UNRECORDED once a mailbox has one completed sweep
- [#116](https://github.com/crinaro/marketplace/issues/116) — funnel_report.py crashes with TypeError on a channel-scoped touch, aborting all output after the outreach list
- [#117](https://github.com/crinaro/marketplace/issues/117) — check_engine_purity.py's standalone scan has no time budget and can run 10+ minutes, indistinguishable from a hang under a run's time budget
- [#118](https://github.com/crinaro/marketplace/issues/118) — brief.py's is_stale() flags a brief as stale on ANY resolved ask in open_asks, not just one concerning that brief's contact
- [#119](https://github.com/crinaro/marketplace/issues/119) — journal.py --check has no carve-out for the currently-executing run, and reports it to itself as died holding unwritten findings

## jobsearch 0.53.0
- Flaky: TestPurityHookDecisionResolution.test_not_my_data_dismisses_and_the_stamp_records_it fails 2 of 3 CI-shaped runs, passes alone *(tracked internally as crinaro/marketplace-dev#429)*
- land.py cannot pass on this repo: the suite (250-370s since 0.52.0) exceeds check_ci_parity.py's 300s step default, which CI does not have *(tracked internally as crinaro/marketplace-dev#431)*
- test_checks.py: 2 classes / 19 tests defined below the __main__ guard have never been discovered or run *(tracked internally as crinaro/marketplace-dev#405)*
- ledger --check --since + --calibrate; AGENT CONTRACT v10 (never a background wait) *(tracked internally as crinaro/marketplace-dev PR#433)*
- Ladder reset (builder 60/150/400, reader 20/90/150) + dev #405 citing test *(tracked internally as crinaro/marketplace-dev PR#435)*
- gmail-multi: manifest-heal design + 9 findings incl. the cross-profile account leak shape *(tracked internally as crinaro/marketplace-dev PR#436)*
- gmail-multi: manifest-heal + boundary design r3 — buildable, 12 findings dispositioned *(tracked internally as crinaro/marketplace-dev PR#437)*
- Release: jobsearch 0.53.0 + gmail-multi 0.4.0 — the connector heals itself; per-profile mailbox scoping *(tracked internally as crinaro/marketplace-dev PR#438)*
  gmail-multi now repairs its own install record at session start; jobsearch now reads only the mailboxes listed in the profile you are in — if two of your profiles list different mailboxes, each sees only its own. After upgrading, the second session start shows two check lines: whether the new hook fired, and whether mailbox scoping is enforced on this build. You read those; there is nothing to run.
- dev #411 piece 3: the 40 real-profile-only suite skips, dispositioned (40 → 9) *(tracked internally as crinaro/marketplace-dev PR#418)*
- Team review 2026-09-20: dev #419-#426 built and recorded, plus the #429 flake fix *(tracked internally as crinaro/marketplace-dev PR#430)*
- dev #431: land.py --timeout passthrough, parity wall times and 900s default, hook_step tests share one scan *(tracked internally as crinaro/marketplace-dev PR#432)*
- release-manager: 0.52.0 release record (step 8a) + changelog-row gate fix *(tracked internally as crinaro/marketplace-dev PR#417)*

## jobsearch 0.52.0
- Purity must resolve at plugin startup on the user's machine — the engine team never points a script at a real profile (publish.py --real-profile contradicts dev #167) *(tracked internally as crinaro/marketplace-dev#411)*
  The plugin now checks itself for your data at session start, so nothing about your profile is ever read by the maintainers. The first session after upgrading skips the check; the second one runs it. If it finds something, it shows up as a single item on your own decision list.
- gate-keeper: the dispatch ledger (dev #399 §5) — docs/dispatches.jsonl, dispatch_ledger.py --check, seeded with today's five rows (two over budget) *(tracked internally as crinaro/marketplace-dev PR#407)*
- public #107 §4.1: check_dashboard_fresh --publish-state prints 'unchanged — skip' per page; daily-run never reads a page it is not publishing *(tracked internally as crinaro/marketplace-dev PR#408)*
  the presence page now publishes only when it changed
- docs-steward: drain doc-impact 172 (design-script-first sec 1 / 4.1 shipped) *(tracked internally as crinaro/marketplace-dev PR#409)*
- Release: jobsearch 0.51.0 *(tracked internally as crinaro/marketplace-dev PR#410)*
- design: purity resolves at plugin startup on the user's machine (dev #411) *(tracked internally as crinaro/marketplace-dev PR#412)*
- review: 13 findings against the dev #411 design (deployment-auditor + gate-keeper) *(tracked internally as crinaro/marketplace-dev PR#413)*
- design: purity-at-startup rev 2 — all 13 findings dispositioned (dev #411) *(tracked internally as crinaro/marketplace-dev PR#414)*
- Release: jobsearch 0.52.0 — purity resolves at plugin startup (dev #411, ADR-035) *(tracked internally as crinaro/marketplace-dev PR#415)*
- docs: 2026-09-17 owner decisions (B5 22–28, script-first §9), doc-impact #168–#171 drained, HANDOFF pruned 105→~20 KB, token discipline *(tracked internally as crinaro/marketplace-dev PR#403)*
- gate-keeper: check_install ignores OS litter; public #55/#57 cited by the classes that cover them; #265 confirmed fixed, #259 not *(tracked internally as crinaro/marketplace-dev PR#404)*
- gate-keeper: dev #405 (19 never-run tests now run, main-guard gate) and dev #399 §1 — test_checks.py split into scripts/tests/ (1835 before and after) *(tracked internally as crinaro/marketplace-dev PR#406)*
- Inbound resolution: the unidentified-sender finding, noise suppression, --backfill-asks (dev #376) *(tracked internally as crinaro/marketplace-dev PR#388)*
- ADR-031 B5 items A+B: plans.assessments[] + validator, funnel_report --by step *(tracked internally as crinaro/marketplace-dev PR#389)*
- release_log.py: a per-row note for installer-facing prose; the 0.48.0 titles restored (dev #370) *(tracked internally as crinaro/marketplace-dev PR#390)*
- check_shipped_package.py runs the SessionStart hook chain inside the published set (dev #314) *(tracked internally as crinaro/marketplace-dev PR#391)*
- journal.py refuses to write into the tracked fixture; check_fixture_generated allowlists stores (dev #313) *(tracked internally as crinaro/marketplace-dev PR#392)*
- STORE_INTRODUCED: a store's absence is decidable against the stamp; the fresh-scaffold gate (dev #365) *(tracked internally as crinaro/marketplace-dev PR#393)*
- A maintainer checkout never writes the real profile pointer or diagnostics log (dev #394, trap 10 wave one) *(tracked internally as crinaro/marketplace-dev PR#395)*
- alert_sweep.py: per-uid triage ledger through journal.py — the digest half of public #99 *(tracked internally as crinaro/marketplace-dev PR#396)*
- Rule 3 as a mechanism: a PreToolUse guard denies git stash/checkout/switch/reset/restore (dev #307) *(tracked internally as crinaro/marketplace-dev PR#397)*
- doctor.py --fix seeds search.* from the config_keys registry; a missing default is loud (dev #323) *(tracked internally as crinaro/marketplace-dev PR#398)*
- The script-first design: public #105–#111 as one class, the dispatch packet, the cost ledger *(tracked internally as crinaro/marketplace-dev PR#401)*

## jobsearch 0.50.0
- First run on 0.49.0: the midnight-UTC golden, a waiting-state TypeError, and #98/#100/#101/#103 *(tracked internally as crinaro/marketplace-dev PR#372)*
- linkedin-runner resilience: the pane lock, the frame probe, and withholding across runs (#47, #96) *(tracked internally as crinaro/marketplace-dev PR#373)*
- geo_screen.py: a geography verdict cites the config key, never memory (#89, dev #355) *(tracked internally as crinaro/marketplace-dev PR#374)*
- run_summary.py: the run summary is a query over the run's own footprint (#85) *(tracked internally as crinaro/marketplace-dev PR#375)*
- Inbound resolution: ADR-029/030 implemented, the ATS sweep, and the resolution invariant (#55, #57, #103) *(tracked internally as crinaro/marketplace-dev PR#377)*
- Resume-variant visibility to ADR-027: surface on the row, per-claim marking, private-on-public fails closed (#59) *(tracked internally as crinaro/marketplace-dev PR#378)*
- The terminal cascade as a derivation: letter_state, touch_state, and the ended checkup line (#95) *(tracked internally as crinaro/marketplace-dev PR#379)*
- variant_out.py: a declared resume variant renders to .docx or a Google Doc, gated by visibility (#64) *(tracked internally as crinaro/marketplace-dev PR#380)*
- A linkless sighting from a URL-bearing channel is never written (#83, rule 1) *(tracked internally as crinaro/marketplace-dev PR#381)*
- Drain the 0.50.0 stack's nineteen doc-impact rows; ADR-034 (the pane is a resource); ADR-027/029/030 implemented *(tracked internally as crinaro/marketplace-dev PR#382)*
- heal_install.py repairs a truncated or stale-recorded engine file from the local clone; migrate.py never claims current over an unchecked tree (#104) *(tracked internally as crinaro/marketplace-dev PR#383)*
- ADR-014 amended: same-version drift is three classes, not one (#104) *(tracked internally as crinaro/marketplace-dev PR#384)*
- Release jobsearch 0.50.0: inbound resolution, runner resilience, the renderer, and the first-run repairs *(tracked internally as crinaro/marketplace-dev PR#385)*

## jobsearch 0.49.0
- Release jobsearch 0.49.0: the strategy as data — with plays.py --confirm actually wired *(tracked internally as crinaro/marketplace-dev PR#369)*
- Two designs, tracked: inbound resolution (ADR-029/030, #55/#57) and runner resilience (#47/#96) *(tracked internally as crinaro/marketplace-dev PR#364)*
- ADR-031 B4: plans and plays — the strategy as data, play_stage retired *(tracked internally as crinaro/marketplace-dev PR#366)*
- Drain B4's five doc-impact rows; ADR-031 → B4 IMPLEMENTED; ADR-016 superseded *(tracked internally as crinaro/marketplace-dev PR#367)*

## jobsearch 0.48.0
- Three releases (0.44.0, 0.46.0, 0.47.0) never reached the owner's machine: marketplace autoUpdate is OFF, and deployment.md asserts it is TESTED true *(tracked internally as crinaro/marketplace-dev#351)*
- journal.REASONS refuses 'surface-unreachable', the very reason linkedin-runner.md and journal.py's own D14 error text instruct the runner to file *(tracked internally as crinaro/marketplace-dev#354)*
- The five migration defects from the first real run (#90–#94), as repair migrations plus the migration contract *(tracked internally as crinaro/marketplace-dev PR#359)*
  0.48.0 repairs damage three 0.46.0/0.47.0 migration bugs already left on real profiles (public #90, #92, #94), on top of fixing all three at the source: a draft wrongly stamped `**To:** unaddressed` gets one re-check, and wherever a `**Contact:**` line was there all along or the people/involvements upgrade has since landed, it gets its real recipient; eight held contacts whose single-token first name made a mailbox search scan the whole inbox instead of one address, and so raised a false 'store-behind-mailbox' finding, are automatically acknowledged; and the leftover 'application endings' hand-off — previously N printed `record.py` commands, several naming ids with no application to act on — becomes one correct, queryable ask in `asks.jsonl` instead.
- Small-fix batch for 0.48.0: --screen-all coverage (#84), linkless-sighting advisory (#83), messages channel FK (#63) *(tracked internally as crinaro/marketplace-dev PR#360)*
  Small-fix batch: `doctor.py` now warns at the start of every run about a job-board or aggregator sighting with no link to its posting, before it disappears for good — unless the role is recruiter-sourced, already has a submitted application on record, or every sighting is too fresh (configurable via the new `config.json.sourcing.linkless_grace_days`, default 3 days) (#83); `--screen-all` now covers roles it previously skipped (#84); and a message's channel reference is now validated the same way every other foreign key is (#63).
- Drain 0.48.0's six doc-impact rows; fix the page-retirement flow (#35) *(tracked internally as crinaro/marketplace-dev PR#361)*
- Release jobsearch 0.48.0: touches store, first-real-run repairs, the queue drain *(tracked internally as crinaro/marketplace-dev PR#362)*
- A loud line at SessionStart when the marketplace is behind or autoUpdate is off (#351) *(tracked internally as crinaro/marketplace-dev PR#353)*
  A loud line now prints at the start of every session when your registered marketplace clone is behind, or when `autoUpdate` is off for it and releases have shipped since — silent before this, which is how three releases (0.44.0, 0.46.0, 0.47.0) shipped and were verified but never actually reached one owner's machine (#351).
- Subagent click guard derived the wrong transcript path (#88); CSS-unsafe variant tab ids (#97) *(tracked internally as crinaro/marketplace-dev PR#356)*
  Two fixes: the outbound-click guard now resolves a subagent's own transcript path correctly instead of falling back to the wrong one (#88), and a variant tab whose id contains a colon (e.g. `variant:engineering`) no longer breaks the CSS-only tab switcher on your generated presence page — regenerate `views/presence_set.html` to pick up the fix (#97).
- ADR-031 B3: touches become their own store; outreach[] retired (#53) *(tracked internally as crinaro/marketplace-dev PR#357)*
  0.48.0 moves your outreach history into its own file, `data/touches.jsonl` — before this, each role's own record carried its outreach as a small array on itself (`outreach[]`). Nothing about what a touch means or how you work with it changes; one new thing it can now say: a touch no longer has to be about a role at all — a periodic reconnect or an introduction ask can stand on its own with no opportunity attached.
- Drain B3's six doc-impact rows; ADR-031 → B3 IMPLEMENTED; correct the autoUpdate TESTED claim *(tracked internally as crinaro/marketplace-dev PR#358)*

## jobsearch 0.47.0
- Purity gate: an ordinary-word profile term re-fires on every new engine site, forever *(tracked internally as crinaro/marketplace-dev#342)*
- States & Views V1: the eight-state derivation, application endings, and registered ATS keys *(tracked internally as crinaro/marketplace-dev PR#347)*
- States & Views V1b: the drafts working set (#86), touched/answered *(tracked internally as crinaro/marketplace-dev PR#348)*
- Drain 0.47.0's seven doc-impact rows; record ADR-033 (States and Views) *(tracked internally as crinaro/marketplace-dev PR#349)*
- Release jobsearch 0.47.0: States & Views, the working set, purity by shape *(tracked internally as crinaro/marketplace-dev PR#350)*
- A linked worktree's .git is a file: fix the two checkout guards (#333) *(tracked internally as crinaro/marketplace-dev PR#345)*
- Purity gate exempts by occurrence shape, never by term: 28 exceptions become 2 (#342) *(tracked internally as crinaro/marketplace-dev PR#346)*

## jobsearch 0.46.0
- V0's sweep ledger has no production writer — the four sweep callers do not call sweep_accounts() yet *(tracked internally as crinaro/marketplace-dev#334)*
- Drain the four doc-impact rows from B2 *(tracked internally as crinaro/marketplace-dev PR#336)*
- Query or Citation design, revised after the C1 audit (D1–D14) *(tracked internally as crinaro/marketplace-dev PR#337)*
- Wire the four sweeps to sweep_accounts() so the coverage ledger has a writer (#334) *(tracked internally as crinaro/marketplace-dev PR#338)*
- Query or Citation C1: brief.py, the probe row, **To:**, and five draft states *(tracked internally as crinaro/marketplace-dev PR#339)*
- Drain C1's doc rows, record ADR-032 and the build deviations *(tracked internally as crinaro/marketplace-dev PR#340)*
- Every agent declares effort: with a reason; Haiku left bare on purpose *(tracked internally as crinaro/marketplace-dev PR#341)*
- Release jobsearch 0.46.0: B2, sweep ledger, Query or Citation C1, effort levels *(tracked internally as crinaro/marketplace-dev PR#343)*
- States V0: sweep-coverage ledger fixes check_followups' wall-clock silence (dev #321) *(tracked internally as crinaro/marketplace-dev PR#332)*
- B2: applications and cover_letters ship — store, migration, golden fixture, #70 *(tracked internally as crinaro/marketplace-dev PR#335)*

## jobsearch 0.44.0
- Release tags exist only on the publish target: dev remote is missing jobsearch--v0.30.0/v0.31.0/v0.32.0 *(tracked internally as crinaro/marketplace-dev#247)*
- the review-findings check had no CI wiring, and both it and the doc-impact check were invisible until publish time — CI now runs the real refusals *(tracked internally as crinaro/marketplace-dev#318)*
- check_sections.py and check_profile_leakage.py answer confidently from the wrong vantage (no fixture disclosure, dev #299's shape) *(tracked internally as crinaro/marketplace-dev#319)*
- 0.44.0 runs a one-time migration on your contacts the next time a session starts: opportunity- and channel-level contacts become real people and involvement records, so a person you know through one channel can now carry a LinkedIn URL and be recognized wherever else they appear. Two contacts merge into one person only when they share an identical LinkedIn URL, or an identical email and name — everything weaker (same email with a different name, same name at a different company, and the like) is left as separate people and surfaced for you to review, never merged automatically. A merge is a pointer (merged_into), never a rewrite, so it can be undone. The migration prints a report naming every merge it made and which rule fired (LinkedIn URL or email+name), plus every near-duplicate it surfaced instead of merging — at the start of that first session, in the SessionStart output that runs it. *(tracked internally as crinaro/marketplace-dev PR#325)*

## jobsearch 0.43.0
- [#65](https://github.com/crinaro/marketplace/issues/65) — A run the scheduler marks as fired can leave zero engine trace, including no SessionStart hook entry, indistinguishable from the scheduler never invoking a session at all
- [#66](https://github.com/crinaro/marketplace/issues/66) — Two views over the same fit data disagree about whether a question on a decided role is still live
- [#67](https://github.com/crinaro/marketplace/issues/67) — resume_variants.py --check overstates "claims outside the addenda" because heading-tracking loses the addenda association across sub-headings
- [#68](https://github.com/crinaro/marketplace/issues/68) — weekly-review skill takes the shared write lock at run start instead of immediately before its write phase, holding it across every read-only step and the strategy dispatch
- [#69](https://github.com/crinaro/marketplace/issues/69) — a coverage gap has no field to reference the issue that already explains it, so a known and already-filed limitation reopens a fresh gap on every run that hits it
- [#71](https://github.com/crinaro/marketplace/issues/71) — funnel_report.py --recommend compares media across different touch types, producing a false CONTRADICTED verdict against a first-touch sequence default
- [#72](https://github.com/crinaro/marketplace/issues/72) — a run that dies mid-flight has no journal event for "these stranded notes were reviewed and needed no write", so it is reported as an unresolved failure indefinitely
- [#73](https://github.com/crinaro/marketplace/issues/73) — Rulebook names docs/schema.md as the data-model reference, but no such file ships into a profile
- [#77](https://github.com/crinaro/marketplace/issues/77) — presence_set.py counts RENDERED variant panes, not DECLARED ones — a profile with active variants can be told it has none
- [#82](https://github.com/crinaro/marketplace/issues/82) — Printed skill commands and strict-schema rejections are not checked against what the shipped script actually accepts, so both can drift silently
- check_engine_purity's collision rate grows with the profile: ordinary English words become tripwires as encountered terms accumulate *(tracked internally as crinaro/marketplace-dev#225)*
- The reconcile step could not represent a public issue closed out-of-band with no dev mirror *(tracked internally as crinaro/marketplace-dev#248)*
- record-dev's issue-citation requirement forced fabricated issues for non-defect work, which the regression-links gate then flagged red *(tracked internally as crinaro/marketplace-dev#258)*
- The HOME-mutation tripwire does not watch the profile directory, which is where a shipped generator actually writes *(tracked internally as crinaro/marketplace-dev#278)*
- check_engine_purity --require-profile accepts the synthetic fixture, so it reports confident false staleness instead of refusing *(tracked internally as crinaro/marketplace-dev#299)*
- guard_outbound_click fails open for every subagent click, because a subagent's page reads are not in the transcript the guard is given *(tracked internally as crinaro/marketplace-dev#309)*
- browser_batch bypasses the outbound-click guard entirely, on the surface the LinkedIn agent prefers *(tracked internally as crinaro/marketplace-dev#310)*
- Gmail special folders are hardcoded English literals and select_all_mail silently falls back to INBOX *(tracked internally as crinaro/marketplace-dev#311)*
- The fixture generator produced only the config half, so the rulebook's never-hand-edit rule did not cover the data fixtures it was aimed at *(tracked internally as crinaro/marketplace-dev#291)*

## jobsearch 0.42.0
- [#74](https://github.com/crinaro/marketplace/issues/74) — Generated dashboard keeps listing resume variants as needing reconcile after the variant gate reports them current

## jobsearch 0.41.0
- The changelog sorts by version across plugins, so a new plugin's first release reads as the oldest entry *(tracked internally as crinaro/marketplace-dev#214)*
- Applications now carry a stable app_id (<opp_id>-aN, minted automatically), and the ATS settings — receipt_sender_domains and status_phrases — are documented for the first time and unified under one set of key names. An existing profile migrates to both automatically on upgrade; no new automated behavior ships yet, since nothing reads these keys until a later release adds the reader. *(tracked internally as crinaro/marketplace-dev#286)*

## jobsearch 0.40.0
- [#32](https://github.com/crinaro/marketplace/issues/32) — Generated rulebook text and several scripts' own printed usage strings still name a bare scripts/<file> path, after the launcher migration removed that directory from installed profiles
- [#33](https://github.com/crinaro/marketplace/issues/33) — The rulebook-refresh warning printed at SessionStart cannot observe whether its own file write landed before or after the session loaded its context, and unconditionally asserts the stale branch
- [#38](https://github.com/crinaro/marketplace/issues/38) — heal_install: tree walk does not exclude the macOS Finder metadata file, so a benign file raises an unexplained-drift alarm every session
- [#39](https://github.com/crinaro/marketplace/issues/39) — report_issue.py: the personal-data screen false-positives on ordinary technical prose, blocking reports on the only channel that files them
- [#40](https://github.com/crinaro/marketplace/issues/40) — check_stale_claims: no exemption for a leading quote marker, so a quoted message body is flagged permanently and can never be cleared
- [#49](https://github.com/crinaro/marketplace/issues/49) — drift_guard cannot re-announce to a resumed session, which is the exact session it just told to restart
- [#50](https://github.com/crinaro/marketplace/issues/50) — commitments store has no lifecycle field, so a canceled meeting can only be canceled in prose and keeps rendering as a live row
- [#52](https://github.com/crinaro/marketplace/issues/52) — migrate.py rewrites the rulebook and schema stamp but nothing ever commits them, so a profile stays dirty indefinitely and its recorded schema can regress

## jobsearch 0.39.0
- [#60](https://github.com/crinaro/marketplace/issues/60) — The claim union's filename does not read as "my resume" to anyone who did not follow the rename, and for a profile with no variants declared it IS the printed resume
- [#62](https://github.com/crinaro/marketplace/issues/62) — Stage 1 of #62's presence working set: a second page that always publishes alongside the dashboard — one tab per active resume variant, the claim union, an open-items tab, and the presence rules — with paragraph merges rendered the way they actually print instead of collapsed behind a line-break joiner that hid them. A round-trip check compares the page against its source before every publish. This is stage 1 of four — #62 stays open; the check confirms the page renders faithfully, not that any given variant is safe to send. *(stage 1 of 4 — the issue stays open)*

## jobsearch 0.38.0
- [#54](https://github.com/crinaro/marketplace/issues/54) — generate_dashboard.py's row-count truncation on the opportunities list no longer prioritizes owner-is-the-candidate state, so every record whose status marks it as awaiting the candidate can fall entirely outside the rendered window
- [#61](https://github.com/crinaro/marketplace/issues/61) — record.py --dry-run reports a false negative on every opportunities write once any resume variant is declared, because the shadow directory it validates against omits the variant files

## jobsearch 0.37.0
- [#48](https://github.com/crinaro/marketplace/issues/48) — Stage 1 of #48's dashboard redesign: six sections (opportunities, submitted, interviewing, offers, drafts, prep) gain per-section CSS-only filters, the four separate in-flight-summary sections users called noise are deleted, and a Submitted-state bug that dropped any role whose only application was rejected or advanced is fixed, so those roles stop vanishing from the Submitted count. This is stage 1 of four — #48 stays open; navigating between sections, staleness, and composing one sendable outreach unit are still ahead. *(stage 1 of 4 — the issue stays open)*
- A medium recorded as **Medium: value** inline on a draft's Status line, rather than on its own **Medium:** line, always read as medium: unknown to the dashboard and precondition checks. A one-time migration relocates that one legacy shape onto its own line; every other unrecognized shape is left alone and flagged instead of guessed at, and a new drift meter reports how many open drafts still resolve to an unknown medium. First instance of a broader class that stays open (dev #265): a model-authored field's format drifting against a strict reader over time. *(tracked internally as crinaro/marketplace-dev#265)* *(partial shipment — the issue stays open)*

## jobsearch 0.36.0
- [#30](https://github.com/crinaro/marketplace/issues/30) — A browser-executing agent re-dispatches its own agent type instead of performing its assigned task, producing a confident no-op
- [#31](https://github.com/crinaro/marketplace/issues/31) — The decision surface renders only an ask's title and opening sentence, so every ask body — the reasoning the decision needs — never reaches the page the user is told to read
- [#34](https://github.com/crinaro/marketplace/issues/34) — The outreach-row schema accepts a reply timestamp earlier than the row's own send date
- [#36](https://github.com/crinaro/marketplace/issues/36) — reconcile.py's reply-artifact attribution compares dates at day granularity, so a same-day artifact can be bound to an outreach row that was sent later that day
- [#37](https://github.com/crinaro/marketplace/issues/37) — precondition.py: unparseable precondition is treated as not-sendable, so ready items silently leave the ready count
- [#41](https://github.com/crinaro/marketplace/issues/41) — Nothing verifies that an inbound reply was written back to the row it answers, so funnel metrics silently undercount and strategy rules are derived from them
- [#42](https://github.com/crinaro/marketplace/issues/42) — A generated view asks the end user to run a maintenance script, for state the view's own data can derive, on rows it renders without a link
- [#43](https://github.com/crinaro/marketplace/issues/43) — The reads-as-an-ask invariant is enforced on one record type but not on the other that renders into the same panel
- [#44](https://github.com/crinaro/marketplace/issues/44) — Root cause: decision-bearing state lives in an unvalidated prose field, while the structured record that contradicts it is never consulted
- [#45](https://github.com/crinaro/marketplace/issues/45) — Dashboard generator drops an entire pipeline stage, and jd_url often has no rendered link
- [#46](https://github.com/crinaro/marketplace/issues/46) — Decisions panel's per-role action clause is truncated at an artificial separator the renderer itself inserts, dropping next_action text entirely whenever location or comp context precedes it

## jobsearch 0.35.0
- Fixed the engine pointer's resolution role, not its drift: a hook that bypassed the launcher could still drag ~/.claude/jobsearch/engine_root backward with nothing to catch it; the launcher now resolves the newest complete installed version itself on every call (an explicit override is the only way to point it at a checkout) and keeps the pointer file only as a repaired, informational trace. Does not repair a pointer that has already drifted on an existing install — the cause of that earlier drift remains an open unknown *(tracked internally as crinaro/marketplace-dev#249)*

## jobsearch 0.34.0
- Dashboard collapsed to one artifact with an anchor per phase, replacing separate pages that only republished once a phase's share of the data crossed a threshold — a page under that line used to stop updating while its link kept serving a stale snapshot; retired page links now retire in two steps so a bookmarked URL is never left orphaned *(tracked internally as crinaro/marketplace-dev#254)*
- Conversations gained a real prep-tracking capability: the dashboard now shows which upcoming calls still owe prep, and the daily run drafts it before the day ends — previously nothing tracked whether a call had prep, and prep only happened if you remembered to ask for it *(tracked internally as crinaro/marketplace-dev#255)*
- Fixed a launcher self-heal regression that could regenerate the launcher backward: a session running an older installed copy of jobsearch could overwrite a newer copy's correct launcher with older behavior; the launcher now carries a version marker and refuses to regenerate over a newer one going forward *(tracked internally as crinaro/marketplace-dev#256)*

## jobsearch 0.33.0
- heal_if_stale() certified a launcher naming a stale engine version as healthy (name-substring predicate, not full-body compare) *(tracked internally as crinaro/marketplace-dev#251)*

## jobsearch 0.32.0
- [#27](https://github.com/crinaro/marketplace/issues/27) — The dashboard is a state view, but applying is a process: there is no working surface for an application session, and follow-up work is not linked to what triggers it
- [#28](https://github.com/crinaro/marketplace/issues/28) — The profile directory tree is a primary interface and is not designed as one: 23 files at root, no home for application work, retired files still present, and engine directories vestigially mixed into a profile repo
- [#29](https://github.com/crinaro/marketplace/issues/29) — Ready-to-send panel does not exclude drafts already marked SENT or MOOT/DO-NOT-SEND
- [#26](https://github.com/crinaro/marketplace/issues/26) — Resume variants are not a first-class concept: one canonical file cannot serve two buyer archetypes, and nothing detects when it falls behind what is actually sent
- The dashboard inlines whole documents into a state view: 613KB in one page, a duplicate local copy, and artifacts reportedly not rendering on mobile *(tracked internally as crinaro/marketplace-dev#233)*

## jobsearch 0.31.0
- gmail-multi should support send/reply/forward; jobsearch must enforce draft-only as policy rather than rely on the capability being absent *(tracked internally as crinaro/marketplace-dev#213)*
- jobsearch vendors an entire MCP server to use five library functions from it *(tracked internally as crinaro/marketplace-dev#211)*

## jobsearch 0.30.0
- Marketplace identifier: careers-plugins -> crinaro-marketplace, with a launcher self-heal *(tracked internally as crinaro/marketplace-dev#216)*

## jobsearch 0.29.0
- _root.py hardcodes the marketplace name while install_launcher.py derives it — the two disagree for any non-default catalog *(tracked internally as crinaro/marketplace-dev#199)*
- Release: jobsearch 0.29.0 and gmail-multi 0.1.0 — connector self-install replaces the declared dependency *(tracked internally as crinaro/marketplace-dev#210)*

## jobsearch 0.28.0
- [#25](https://github.com/crinaro/careers-plugins/issues/25) — Dispatched subagents lack the engine-root pointer/launcher the main run uses to resolve engine files

## jobsearch 0.27.0
- Alert-sweep's aggregator sender list is hardcoded, independent of channel store retirement status *(tracked internally as crinaro/careers-plugins-dev#147)*
- Generated dashboard has no sourcing/strategy tab; channel status, route, cadence and yield are visible only via scripts *(tracked internally as crinaro/careers-plugins-dev#148)*
- Prep-note existing-work guard only scans call_preps/, so prep written into kb/ gets re-promised as owed *(tracked internally as crinaro/careers-plugins-dev#153)*
- A staged draft with no matching ask has no guaranteed home in the generated Your Move, so a ready-to-send draft can stay invisible *(tracked internally as crinaro/careers-plugins-dev#154)*
- A cover letter carrying a send-hold renders as READY — precondition machinery covers drafts.md only *(tracked internally as crinaro/careers-plugins-dev#169)*

## jobsearch 0.26.0
- [#22](https://github.com/crinaro/careers-plugins/issues/22) — The generated-dashboard publish model has a staleness window: the published view can lag committed state via two distinct mechanisms
- [#23](https://github.com/crinaro/careers-plugins/issues/23) — record.py's create path leaves the caller to guess a valid record at every stage: --dry-run passes input the real write then refuses, rejection messages name no field, and the fields listing omits enum and type constraints
- [#24](https://github.com/crinaro/careers-plugins/issues/24) — A user-owned role recorded with a future action date and a sourced/backlog status is invisible on the 'decisions waiting on you' surface until its action date arrives

## jobsearch 0.25.0
- [#12](https://github.com/crinaro/careers-plugins/issues/12) — The outbound-click guard's startup selftest fails to open its own transcript path, so every click is classified unresolvable and allowed through instead of blocked
- [#13](https://github.com/crinaro/careers-plugins/issues/13) — The weekly reconcile audit again mis-attributes replies and platform events to the wrong sibling outreach row for the same recipient
- [#14](https://github.com/crinaro/careers-plugins/issues/14) — A validation gate can never pass on a clean install: shipped design docs point at scripts present in no released version
- [#15](https://github.com/crinaro/careers-plugins/issues/15) — The browser automation cannot reach a social platform's secondary/message-requests inbox surface, reproducible across multiple runs
- [#17](https://github.com/crinaro/careers-plugins/issues/17) — The write API cannot CREATE a new record, and separately deadlocks when called while the run lock is held, together forcing direct hand-editing of the data store
- [#18](https://github.com/crinaro/careers-plugins/issues/18) — A skill mandates an unconditional per-turn re-claim of a session-scoped notification subscription whose delivery cannot be observed by the session
- [#19](https://github.com/crinaro/careers-plugins/issues/19) — No schema field represents a pursued opportunity's post-application play-sequence stage
- [#20](https://github.com/crinaro/careers-plugins/issues/20) — Generated dashboard renders knowledge-base and call-preparation artifacts as filename strings, not their content
- [#21](https://github.com/crinaro/careers-plugins/issues/21) — OPEN DESIGN QUESTION: two dashboard views present the same records through two different taxonomies instead of one lifecycle-state view

## gmail-multi 0.5.0
Reply drafts look right again. The quoted original no longer shows stray '>' marks inside the quote box, and anything in the original message that looks like code or a link is shown as plain text rather than becoming live in your draft.
gmail-multi now keeps one list of your accounts, and it moves your existing setup over by itself the next time Claude starts (your old file is kept beside it). Every search or read must name which account to use, so nothing reaches across all your mailboxes by accident. Sending, replying and forwarding now always ask you first, so a scheduled or unattended run can draft but never send. gmail-multi is also safe to use on its own, without the job search plugin.

## gmail-multi 0.4.1
gmail-multi 0.4.1 changes what a failed send tells you, and there is nothing for you to run. If the connection to the mail server was lost or timed out after the message body had begun to go out, a send, reply or forward used to fail with a bare connection error that did not say whether the message had been delivered, so retrying could deliver it twice from your own address. It now reports that delivery is UNKNOWN, asks you to look in [Gmail]/Sent Mail before trying again, and says not to retry blindly. A failure before that point (the server cannot be reached, its name cannot be looked up, the login is refused, or every recipient is refused) now says plainly that nothing was sent, so a retry is safe. The message for a send that reached only some recipients is unchanged.

## gmail-multi 0.4.0
- Release: jobsearch 0.53.0 + gmail-multi 0.4.0 — the connector heals itself; per-profile mailbox scoping *(tracked internally as crinaro/marketplace-dev PR#438)*

## gmail-multi 0.3.0
- [#76](https://github.com/crinaro/marketplace/issues/76) — gmail-multi: a non-ASCII character in a search query aborts the whole multi-account search
- Gmail special folders are hardcoded English literals and select_all_mail silently falls back to INBOX *(tracked internally as crinaro/marketplace-dev#311)*

## gmail-multi 0.2.0
- gmail-multi should support send/reply/forward; jobsearch must enforce draft-only as policy rather than rely on the capability being absent *(tracked internally as crinaro/marketplace-dev#213)*

## gmail-multi 0.1.1
- Marketplace identifier: careers-plugins -> crinaro-marketplace, with a launcher self-heal *(tracked internally as crinaro/marketplace-dev#216)*

## gmail-multi 0.1.0
- Release: jobsearch 0.29.0 and gmail-multi 0.1.0 — connector self-install replaces the declared dependency *(tracked internally as crinaro/marketplace-dev#210)*
