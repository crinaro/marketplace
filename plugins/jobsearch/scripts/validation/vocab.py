"""The dataset's enum vocabularies and patterns: what every store's fields may hold. Its importers read these names
through `validate_data` today (the facade); new code imports them from here.

Capability module of `validate_data.py` (S4a, moved unedited)."""

import config_keys as _config_keys
import re


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


VERTICALS = {"healthcare-payer", "healthcare-provider", "healthtech", "saas",
             "fintech", "insurtech", "other"}
COMPANY_STATUS = {"active-target", "watching", "passed"}
CHANNEL_TYPES = {"job-board", "aggregator", "company-site", "recruiter",
                 "referral", "alert-email"}
# ⭐ public #83 rule 1 — channel TYPES that carry "a public URL was available at the moment of
# sighting". Recruiter/referral/company-site/alert-email sightings do not carry that guarantee
# (a recruiter can tell you about a role with no public posting at all), so a sighting from any
# other type is never in scope for either half of #83: doctor.py's run-start advisory (#360,
# `check_linkless_sightings`) and record.py's capture-time refusal (this rule's other half)
# both import THIS set rather than re-typing it — it is the one place it is spelled.
URL_BEARING_CHANNEL_TYPES = {"job-board", "aggregator"}
# public #83 rule 1's effective date — the day the capture-time refusal in record.py shipped.
# A sighting dated BEFORE this could not have been refused at write time (it predates the code
# that refuses it), so it stays doctor.py's advisory's business (WARN, non-fatal, and excluded
# there by the same recruiter-sourced/receipt-backed/grace-period rules). Only a sighting dated
# ON OR AFTER this date turns a missing source_url into a hard PROBLEM here — pinned to a
# constant, never "today", so a profile is never turned red retroactively for history it could
# not have prevented.
SOURCE_URL_REQUIRED_SINCE = "2026-09-14"
CADENCES = {"daily", "weekly", "biweekly", "monthly", "on-inbound"}
# `expired` added 2026-08-11 (issue #6): the posting vanished/closed before any decision was
# recorded. TERMINAL, and distinct from `passed` — "I declined this" and "it disappeared before
# I decided" are different signals wanting different remedies, and recording an expiry as a pass
# overstates the pass rate while hiding that the pipeline loses roles to expiry. Existing
# `parked` rows written as an expiry workaround are deliberately NOT reclassified: nothing can
# retroactively distinguish a genuine park from the workaround (adr-013).
OPP_STATUS = {"active-pursuit", "needs-resolution", "in-motion", "backlog", "passed", "expired"}
# ⭐⭐ THE ONE TERMINAL SET — owned HERE, imported by every renderer and check (dev/audit
# 2026-09-02, build item 1). A role is TERMINAL when it has left the funnel for good:
# declined (`passed`) or vanished (`expired`). Everything else — including `backlog`, which
# is a shelved-but-reopenable state that a newly sourced role STARTS in (your_move.py's
# `decide` group) — is live data the surfaces must still account for.
#
# The measured defect this closes: generate_dashboard.py carried its own per-file
# `_CLOSED_STATUSES = {passed, backlog, expired}` and dropped every backlog row as closed,
# while your_move.py treated backlog+undecided as the entry state and the same renderer's own
# sort key four lines below ranked backlog as live. Two files, two silent answers to one
# question. A per-file "closed" set is the inversion that let them disagree: each file named
# what IT wanted to hide. A shared TERMINAL set names what has actually ended, and anything
# a surface still wants to omit has to be a deliberate, visible choice on that surface.
TERMINAL_OPP_STATUSES = frozenset({"passed", "expired"})
STAGES = {"sourced", "contacted", "screening", "interviewing", "offer", "closed"}
# ⭐⭐ `play_stage`, `PLAY_SEQUENCE`, `PLAY_STAGES`, `POST_APPLICATION_PLAY` — RETIRED in
# ADR-031 B4 (design §19). `play_stage` was a HAND-SET cursor over a fixed sequence; a
# hand-set position not backed by a record is exactly "looks handled and is not". `plays.py`'s
# `next_step()` now DERIVES the position from the stores every time it is asked — the play is
# the authority for content, `plans.jsonl`/`plays.jsonl` the store. The field itself, and
# `next_action` (free text), join `banned_aliases` below (docs/data_model.json); a write of
# either is refused, not merely unknown. See RETIRED_KEYS/`active_retired_keys()` for the B4
# structural-marker gate and `check_retired_reads.py` for the source-code half of the same
# retirement. `record.py set <id> play_stage ...` disappears with it — the way to advance the
# play is to record the act.
# applications[].status values that prove a submission actually happened. States & Views V1
# (design-states-and-views.md §3c) adds `closed` here — a close PRESUPPOSES a submission (you
# cannot close what was never sent), which is exactly what SUBMITTED_APP_STATUS already means
# for every other status in this set. `_CLOSED_STATUSES` scar (§14): this is spelled by hand in
# TWO other places (check_sent_drafts.py, funnel_report.py) and mirrored behind an equality
# test in a third (applications.py) — see APPLICATION_ENDINGS below for the ending vocabulary,
# which is a DIFFERENT set (a subset of statuses that mean "the pursuit is over", not "a
# submission happened").
SUBMITTED_APP_STATUS = {"submitted", "acknowledged", "rejected", "advanced", "closed"}
# ⭐ States & Views V1 §2b/§3c — the ONE imported definition of "an application status that
# means the pursuit through this application is OVER" (the `TERMINAL_OPP_STATUSES` move, one
# layer down). `rejected` (the employer said no), `withdrawn` (they did, after applying) and
# `closed` (we gave up on ATS silence — §3c) are the three; `advanced`/`submitted`/`acknowledged`
# are live, and `not-started`/`started` never reached a submission to end. Read by
# `your_move.ended_because()` and `funnel_report.py`; never re-spelled.
APPLICATION_ENDINGS = frozenset({"rejected", "withdrawn", "closed"})
# States & Views V1 §3a — `opportunities.decision.reason_kind`, required whenever a written
# verdict diverges from `triage_suggestion()`'s own reading at decision time. Proposed by the
# design, not yet vetoed or extended by the owner (§3a's own note).
DECISION_REASON_KINDS = frozenset({"comp-acceptable", "setting-acceptable", "fit-misjudged",
                                   "company-priority", "not-interested", "timing", "other"})
VERDICTS = {"pursue", "pass", "parked", "undecided"}
# `unresolved` added 2026-08-11 (issue #4): a posting that declares two settings at once (e.g.
# tagged both hybrid and remote) previously forced a silent pick, and the pick selected which
# comp floor applied. `unresolved` makes "contested — ask the employer" a representable value
# instead of an absence; the verbatim declared text goes in `location.declared` (required for
# this type), and profile.screen_comp() DECLINES to pick a tier for it (adr-013).
LOC_TYPES = {"remote", "hybrid", "onsite", "relocation", "unresolved"}


CONTACT_EMAIL_STATUS = {"verified-published", "verified-received", "pattern-inferred", "unknown"}
OUTREACH_STATUS = {"drafted", "staged", "sent", "declined"}
# Added 2026-07-21, per the candidate: "We should be tracking who we connected with & when
# i applied to analyze what works and what doesnt." Applications were previously
# stuffed into outreach[] with a person-shaped `to` field reading e.g.
# "<a recognizable employer> careers (direct ATS application)" -- so counting them meant string-matching
# a free-text name, and an ATS submission was indistinguishable from a networking
# note. They are different funnels with different success measures; they get
# different arrays.
APPLICATION_METHODS = {"company-ats", "linkedin-easy-apply", "recruiter-submitted",
                       "email", "referral"}
APPLICATION_STATUS = {"not-started", "started", "submitted", "acknowledged",
                      "rejected", "advanced", "withdrawn", "closed"}
# ADR-031 B2 (design §1/§9, §16 item 3) — a fact about the OPPORTUNITY, not the plan: one
# vocabulary per fact is the rule, shared with the future plans.outcomes. `consulting` was the
# pre-Part-3 wording; amended to `contract`, one word, before anything shipped.
# jobsearch 0.73.0 (dev #740 / public #160) widens it: fractional, interim and advisory route the pay
# away from the annual tiers (profile.engagement). The ONE list is config_keys.ENGAGEMENT_TYPES.
ENGAGEMENT_TYPES = set(_config_keys.ENGAGEMENT_TYPES)
# ADR-031 B2 (design §1) — `cover_letters`, "resume_variants' twin": a status with a terminal
# value, same shape as VARIANT_STATUS. `retired` is TERMINAL, same contract as a resolved ask
# and a retired resume variant. Nullable: a row the 0.45.0 migration preserves verbatim from a
# legacy applications[] row may carry no status at all — the migration cannot know one and must
# not invent it (design §4/§28.2, the gate review's own B2 plant).
COVER_LETTER_STATUS = {"draft", "sent", "retired"}
# Whether outreach got a reply -- the other half of "what works".
OUTREACH_OUTCOME = {"awaiting", "replied", "no-response", "declined",
                    "meeting-booked", "accepted", "n/a"}


# ---- Communications: HOW a message was sent, and what kind it was (added 2026-08-02) ----
# WHY: `channel_id` was carrying three meanings at once — relationship (firm:halloway-partners),
# medium (linkedin-direct), and implicitly purpose. Worse, `linkedin-direct`'s own label read
# "exec-to-exec InMail" while the 12 rows stamped with it on 7/31 were CONNECTION-REQUEST NOTES.
# Every question the candidate asked about which comms work turns on distinctions that field erased.
MEDIA = {"linkedin-connection-note", "linkedin-inmail", "linkedin-message",
         "email-cold", "email-reply", "phone", "sms", "other", "unknown"}
# ⭐ Channel ids that still EXIST in channels.jsonl but must never be used again. They resolve,
# so a referential check cannot catch them; only naming them can. Kept as rows rather than
# deleted because historical outreach still points at them and a dangling pointer is worse.
RETIRED_CHANNEL_IDS = {"linkedin-direct", "email-direct"}


TOUCH_TYPES = {"first-touch", "chase", "reply", "referral-ask", "intro-request",
               "thank-you", "reconnect", "apply-path", "unknown"}
# jobsearch 0.92.0 (dev #951, design-decision-surface.md B.1): the two CONTROL touch types, written only by
# `record.py stop-following` (and its `--undo`). Kept OUT of TOUCH_TYPES on purpose: the outreach drafter's enum and the
# plays check are held to TOUCH_TYPES, and a control row is no outreach. The touches row check compares against the union.
FOLLOW_CONTROL_TYPES = frozenset({"stop-following", "resume-following"})
RECIPIENT_ROLES = {"hiring-manager", "hiring-line", "talent-acquisition", "recruiter-agency",
                   "warm-contact", "peer-network", "other", "unknown"}
ADDRESS_STATUS = {"verified-published", "verified-received", "pattern-inferred", "unknown"}
# A bounce that looks like a non-reply silently poisons the only comms metric there is.
DELIVERY = {"delivered", "bounced", "unknown"}
# ---- Triggers and sequences (public #27, 2026-08-25) -------------------------------------
# WHAT CAUSED THIS TOUCH OR ASK. The measured defect: a drafted ask generated by an application
# sat in drafts.md unlinked to the opportunity whose application generated it, and stayed
# correct only because a human remembered. `trigger_kind` names the cause class; `trigger_ref`
# names the instance. 'application' resolves against the OWN record's applications[] (app_id,
# or date for pre-migration rows) — the blocked_until own-record rule, because a join to
# another record's application would say this role moved when it did not. 'reply' resolves
# against data/messages.jsonl. 'elapsed' carries the ISO date the clock started. 'manual'
# means a human decided with no recorded cause — a manual trigger carrying a ref is a
# contradiction, refused rather than guessed over.
TRIGGER_KINDS = {"application", "reply", "elapsed", "manual", "introduction"}   # `introduction`: dev #834, design-network-first.md 5.4
# design-inbound-resolution.md §2 (ADR-029/030) — `messages[].resolved_by`: which of ADR-030's
# three deterministic tiers matched when a message resolves an application. Recorded so the
# EVIDENCE for a status change is auditable later, not just the fact of the change.
RESOLVED_BY = {"req-id", "url", "company-single"}
# A multi-step play ("part A sent, part B held until the connection is accepted") was a state
# machine living in a markdown heading — nothing could query "which sequences are unblocked
# today". sequence_id groups the steps; sequence_step orders them (int, 1-based). The HOLD on
# a staged step stays in **Blocked until:** (precondition.py) — a sequence adds grouping,
# never a second way to spell a hold. scripts/trigger.py owns the joins and the daily query.
# ---- Form answers (public #27, 2026-08-25) ------------------------------------------------
# What was actually answered on an application form's own questions — reasoned out once, at
# length, and previously lost to prose, so the next equivalent form re-derived it and
# consistency across two applications to the same employer was a matter of memory. Entry keys
# are REJECTED-unknown like OUTREACH_KEYS; question_key is a shared slug so precedent is a
# join, not a search.
FORM_ANSWER_KEYS = {"question_key", "question", "answer", "answered_on"}
# Unknown keys are REJECTED. Four alias keys (sent_on, replied_on, channel, notes) drifted
# into the data precisely because nothing rejected them.
# ⭐ ADR-031 B1: `contact_id` -> `person_id` (docs/data_model.json's banned_aliases carries the
# rename globally). A row still writing `contact_id` is caught by the SAME banned-alias branch
# every unknown-key guard already runs, not a special case here.
# ⭐ ADR-031 B3 — OUTREACH_KEYS retired along with the nested array it governed. `touches` is
# now a top-level store (docs/data_model.json's own field list, gaining `id` and the two §12
# object FKs no nested row ever had) checked by the GENERIC model-driven unknown-key guard
# every other top-level store added since B2 uses — never a second, dedicated set here.
# New required fields apply only from the cutover — backfilled history carries "unknown"
# where no contemporaneous record supports a value. Without this the validator would fail
# against 46 legacy rows on day one and get ignored.
COMMS_CUTOVER = "2026-08-02"
# dev #686 / public #139 — the touch rules that were typed inline in the validator and so
# invisible to `record.py fields --file touches`. Named once here; the validator and the
# `fields` listing both read these, never a typed copy.
COMMS_REQUIRED_FIELDS = ("medium", "touch_type", "recipient_role", "delivery")
SENT_REQUIRES_FIELD = "to"            # status='sent' requires a non-empty 'to'
SENT_REQUIRES_DATE_FIELD = "date"     # ... and an ISO 'date'
EMAIL_MEDIUM_PREFIX = "email"         # an email-* medium requires 'address_status'
EMAIL_REQUIRES_FIELD = "address_status"


# `side-contact` (jobsearch 0.91.0, design-build-reach.md 6.3): a recruiting, HR or talent person on the role who is NOT its lead
# (`recruiter`); the side-door play's first recipient. Never warm, never a referral: `warm_path` ranks it nowhere.
PATH_TYPES = {"warm-referral", "recruiter", "hiring-manager", "hiring-context", "internal", "cold", "side-contact"}
# jobsearch 0.91.0 (design-build-reach.md 6.2) -- `touches.build_kind`: which BUILD line a touch came from, set from the script-built
# brief row, never from drafter text. Absent means "not from a BUILD line". `advice-ask` is a `first-touch` with no `opp_id` and an
# `object_company_id`; `side-door` is an `intro-request` with an `opp_id` whose recipient holds a `side-contact` involvement on it.
BUILD_KINDS = ("advice-ask", "side-door")
BUILD_KIND_SHAPE = {"advice-ask": "first-touch", "side-door": "intro-request"}
TIE_VIA_PERSON = "person:"      # a tie's `via` that begins so names a people id, which must resolve to a living person
# ADR-031 B1 — `people.status`. `merged` is the ONLY non-active state a person can be in;
# `merged_into` is required iff status is `merged` (checked below, not restated as an enum).
PEOPLE_STATUS = {"active", "merged"}
# JD fit analysis (added 2026-08-02, per the candidate: "how is the candidate match to the JD?").
# DATA, not a document — requirement/verdict/evidence/question is a dataset, so it lives on
# the opportunity record and is validated like everything else.
FIT_VERDICTS = {"aligned", "partial", "not-aligned", "unknown"}
FIT_Q_STATUS = {"n/a", "open", "answered"}


# dev #751 (design D5, F3): `manual-candidate` was a hand-kept extra HERE while `route.py` did not know
# it, so a channel carrying it passed validation and then raised `RouteError` in `route.py --check`.
# `route.REQUIREMENTS` carries it now; the derivation above is the whole definition.
# ---- Asks and commitments (dev #93 / public #21) ----------------------------------------
# The hand-authored tail of Your Move and the This Week schedule were the last state living in
# focus.md prose, where a hand-written copy of a record went stale beside the generated row.
# They are stores now: an ask is OPEN until `resolved_on` is set (views filter, so expulsion is
# structural), and a commitment's `date` may be the literal `unresolved` — the migration marker
# for a date that could not be parsed, same precedent as blocked_until and play_stage.
ASK_KINDS = {"role", "system", "suggestion"}
# dev #834 (jobsearch 0.86.0, design-network-first.md 8.1, 8.2) -- `kind: suggestion` is a row the strategist PROPOSES and the owner
# CONFIRMS. `suggests` names the one write the ask stands for: `{store, op, id, fields, before}`. What may be suggested is closed and
# small: a company becomes an `active-target` (the owner supplies the motivation at confirm), a plan is created for a search, a company
# or a person, and a person's `cadence` is set. A PERSON row itself is never suggested (finding people is a manual LinkedIn step, and the
# engine never invents a person). `fields` of a plan are checked by the plan validator once the row exists; here only the key set.
SUGGEST_COMPANY_KEYS = frozenset({"status", "motivation"})
SUGGEST_PLAN_SUBJECT_KINDS = frozenset({"search", "company", "person"})
SUGGEST_PERSON_KEYS = frozenset({"cadence"})
SUGGEST_OPS = {("companies", "set"), ("plans", "create"), ("people", "set")}
SUGGEST_SHAPE_KEYS = frozenset({"store", "op", "id", "fields", "before"})
# dev #834 (design-network-first.md 6) -- the `proposals` store: one row per proposal to a prospective client of a non-employee
# engagement, several per engagement. `drafting` is the only status before the proposal went out; `date` is required for every
# status that presupposes it did (`withdrawn` may be a draft the candidate never sent, so it may carry none).
# ⚠️ THE FIELD IS `date`, NOT `sent_on` (design-network-first.md 6 spelled it `sent_on`): `sent_on` is a BANNED ALIAS for `date` in
# docs/data_model.json (`banned_aliases`, "the same meaning under two spellings silently splits a query"), and `applications` and
# `touches` already name the day an action went out `date`. The unknown-key guard refused the design's spelling on the first write.
PROPOSAL_STATUS = ("drafting", "sent", "accepted", "declined", "withdrawn", "expired")
PROPOSAL_NEEDS_SENT_ON = frozenset({"sent", "accepted", "declined", "expired"})
RATE_PER = ("hour", "day", "month", "year", "project")
CONCEPTUAL_AGREEMENT_LISTS = ("objectives", "measures", "value")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
# dev #133 / public #22 — the actions record.py can resolve an ask against atomically. An
# unparseable value must be LOUD (the precondition.py rule): a resolves_when nobody can act on
# means an ask that claims it will self-resolve and never does — it looks handled and is not.
ASK_RESOLVES_WHEN = {"application", "outreach"}
UNRESOLVED = "unresolved"
# public #50 — same shape as ADR-013's `expired` and the asks store's `resolved_on`: a fact
# the run knows (a meeting was called off) goes into the queryable store, never into prose.
# Additive; absent means `scheduled` until the 0.40.0 seed migration stamps every existing row
# explicitly (this store's siblings prefer an explicit value over a reader having to know that
# a missing key means the default).
COMMITMENT_STATUS = {"scheduled", "cancelled"}
# dev #834 (jobsearch 0.86.0, design-network-first.md 5.2, 13.1) -- a CHAT widens `commitments`. `kind` classifies a meeting
# (absent on a legacy row = unclassified, counted and never guessed); `attendance` records whether a past one HAPPENED (absent =
# unrecorded, never "held" and never "no-show"). `status` stays scheduled/cancelled: attendance is a second fact, not a third state.
# `event` (jobsearch 0.91.0, design-build-reach.md 6.5): a public event the candidate may attend, `{kind: event, date, title, source}`
# with `source` the event page's address and no `person_id`; `attendance` applies as it does to a chat.
COMMITMENT_KINDS = {"chat", "interview", "event"}
ATTENDANCE = {"held", "no-show"}
# dev #834 (design-network-first.md 4.3, accepted by the owner 2026-11-12) -- `people.ties`: how the candidate knows a person, one STATED
# field, `[{kind, via?}]`. `kind` is a closed set, `via` an optional non-empty string (which employer, school or community). Absent means
# unknown, never "no ties": LAMP's Alumni is derived by counting people with a non-empty `ties`, and nothing infers one (ADR-031 decision 5).
TIE_KINDS = ("former-colleague", "alumni", "community", "friend", "introduced", "other")
# jobsearch 0.91.0 (design-build-reach.md 5.2, owner O2/O3) -- where a person works NOW, a dated statement on the employer of record
# (`people.employment`), and where they used to (`people.formerly[]`). "Used to work there" has ONE spelling, an entry in `formerly`:
# a stored `status: former` is refused. Every date a derivation reads is the day the engine LEARNED the fact, set by the writer.
EMPLOYMENT_STATUS = ("current", "unknown")
EMPLOYMENT_SOURCES = ("stated", "observed-mail", "migration")
EMPLOYMENT_KEYS = frozenset({"status", "as_of", "confirmed_on", "source"})
FORMERLY_KEYS = frozenset({"company_id", "as_of", "until", "counted_from"})
# The people fields only the employment verbs write (`record.py employment|moved|merge-person`; `create` states the first one).
EMPLOYMENT_OWNED_FIELDS = ("company_id", "employment", "formerly")
# dev #834 (design-network-first.md 5.4) -- the cause of a touch or ask that came of an INTRODUCTION has two possible homes, so its
# `trigger_ref` is prefixed: `touch:<id>` (the intro-request touch that produced it) or `commitment:<id>` (an intro offered in a chat).
INTRODUCTION_REF_PREFIXES = ("touch", "commitment")
# `companies.motivation` (design 4.1): the candidate's own stated hunger to work at a company, 1..5 (LAMP's M).
MOTIVATION_MIN, MOTIVATION_MAX = 1, 5
# ---- Resume variants (public #26) --------------------------------------------------------
# The declared printed-resume set. The variant FILES and resume.md (the claim union) are
# authored prose; the RECORDS — which variants exist, which archetype each serves, which one
# an opportunity should receive, which one an application actually sent — live here and are
# validated like everything else. `retired` is TERMINAL: applications[] history may reference
# a retired variant forever, but an opportunity cannot PLAN to send one. Prose-level hygiene
# (claim containment against the union, staleness, orphan claims) is resume_variants.py's job;
# this validator is structure and referential integrity only.
VARIANT_STATUS = {"active", "retired"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA12_RE = re.compile(r"^[0-9a-f]{12}$")

# ---- briefs (Query or Citation C1, design-query-or-citation.md §3.3/§3.7/§4.1) ---------------
# Mirrored as LITERALS — never imported from `your_move.AXIS_FOLD` or `brief.py`'s own module
# constants, because `your_move` imports THIS module and `brief` imports `your_move`; importing
# either back here is the exact load-time cycle `precondition.py`'s lazy import of `brief`
# already exists to avoid. TestBriefVocabularyMirrorsTheReader holds this identical to the
# reader's own tuples, so the copy cannot drift silently. dev #680: the suffix is 4+ hex (old
# rows carry 4, new ids carry 16), as brief.py's own BRIEF_ID_RE.
BRIEF_ID_RE = re.compile(
    r"^brief:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}-[0-9a-f]{4,}$")
BRIEF_AXES = {"reply-owed", "accepted", "waiting", "silence-unverified", "silent",
             "nothing-sent"}
BRIEF_REGISTERS = {"reply-owed", "accepted", "premature", "chase", "reconnect",
                   "unverified-silent", "cold", "unverified-cold"}
BRIEF_EVIDENCE_RE = re.compile(
    r"^(?:none-recorded|not-configured|confirmed-empty(?:\(owner, \d{4}-\d{2}-\d{2}\))?|"
    r"confirmed \d+ thread\(s\), latest \d{4}-\d{2}-\d{2}.*|"
    r"candidate \d+ \(by name\)|"
    r"unreachable\([\w-]+\)|"
    r"not-permitted\([\w.-]+\))$")
