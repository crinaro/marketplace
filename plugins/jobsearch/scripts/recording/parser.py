"""parser: record.py's argument grammar, in one place so help, usage and errors stay one text: the verb list
(`OPS`), `build_parser` / `parse`, the help epilog, the store each verb owns (`bind_store`) and the refusal of any
writer of `messages` but its three verbs.

Capability module of record.py (an entry point over `recording/`)."""

import argparse
import sys
from recording.common import _validator_module
from recording.fit import FIT_USAGE
from recording.reads import BATCH_OPS, CAPTURE_DEADLINE_S_DEFAULT, FETCH_DEADLINE_S_DEFAULT, JD_READ_OPS
from recording.store_files import DEFAULT_WAIT, MESSAGES_WRITE_VERBS, STORES


# ⭐ public #103 — THE SINGLE SOURCE for every verb this CLI has. main()'s parser is built
# from this tuple (never a second hand-typed list), and so is
# TestPublic103RecordDryRunNeverWrites.test_every_verb_dry_run_leaves_every_store_byte_identical
# in test_checks.py: a verb added here without a --dry-run mapping in that test fails LOUDLY
# instead of silently shipping a write-capable verb nobody proved honours --dry-run — which
# is exactly how `answered`/`touched` went unnoticed (they were added as their own
# early-return branches in main(), before the shared dry-run gate near the bottom of main()
# ever runs for them). `received` (design-inbound-resolution.md §2) joins the tuple for the
# identical reason — it is its own early-return branch too, and must prove --dry-run the
# same way.
OPS = ("create", "set", "set-in", "append", "show", "fields",
       "decide", "application-status", "networking-closed",
       "answered", "touched", "received", "merge-person",
       # dev #686 / public #139 (E2) — link a person to an opportunity later, as an explicit
       # act. An early-return verb like touched/answered/received: --dry-run proven in
       # test_record_call_surface.py's VERB_ARGS.
       "involve",
       # jobsearch 0.67.0 (dev #713-#716 / public #142-#145) -- the four SOURCING-SCREEN verbs. Each
       # writes one top-level field of ONE opportunity through the ordinary lock / validate /
       # rollback path below (they are branches of the shared mutation chain, not early returns),
       # and each stores what a SCRIPT computed -- never a value a model typed in:
       # `screened` re-runs profile.screen_rules; `lean` runs the signal matcher; `listed-pay`
       # parses the pay-slot grammar; `posted` computes a board-relative date from a shown age.
       "screened", "lean", "listed-pay", "posted",
       # jobsearch 0.70.0 (dev #728 / public #158) -- fold a duplicate row into its canonical one,
       # and undo a false merge. Both are branches of the shared mutation chain (one locked write
       # touching two rows of ONE store), so --dry-run, the validator and the rollback all apply.
       "link-sibling", "unlink-sibling",
       # jobsearch 0.72.0 (dev #751, sourcing-feeds) -- the company-feed verbs. Early-return verbs
       # like `involve`: each writes the COMPANIES store (and `ats` also the CHANNELS store, in one
       # locked, validated, rollback-verified transaction), so --dry-run is proven in test_record_call_surface.py.
       "ats", "warm-lookup",
       # jobsearch 0.75.0 (dev #765) -- record ONE role seen on a job board. An early-return verb writing
       # COMPANIES (when it creates one) and OPPORTUNITIES in one locked, validated, rollback-verified
       # transaction, so --dry-run is proven in test_record_call_surface.py.
       "board-sighting",
       # jobsearch 0.76.0 (dev #769) -- turn shipped channel-catalog boards on (`add`) and settle a
       # disagreement with the catalog (`take` / `keep`). An early-return verb writing CHANNELS (and
       # COMPANIES / ASKS when they change) in one locked, validated, rollback-verified transaction, so
       # --dry-run is proven in test_record_call_surface.py.
       "channel-catalog",
       # jobsearch 0.76.0 (dev #774) -- turn any job source on or off (`source on|off`), list them (`list`) and
       # resolve an adoption question (`keep-mine`). An early-return verb writing CHANNELS (and COMPANIES / ASKS /
       # config.json when they change) in one locked, validated, rollback-verified transaction, so --dry-run is
       # proven in test_record_source.py.
       "source",
       # jobsearch 0.80.0 (dev #776 / public #166) -- record what research or the scheduled re-check saw on the employer's OWN
       # posting. An early-return verb: it reads EMPLOYER-POSTING lines from a FILE (never argv, so no quote in a
       # posting's visible text can break a shell line), and writes OPPORTUNITIES in one locked, validated,
       # rollback-verified transaction, so --dry-run is proven in test_record_posting.py.
       "posting",
       # jobsearch 0.87.0 (dev #861 / public #194) -- record the `fit` the researcher handed back by FILE: an early-return verb
       # writing OPPORTUNITIES in one locked, validated, rollback-verified transaction, so --dry-run is proven in test_record_call_surface.py.
       "fit",
       # jobsearch 0.82.0 (dev #820 / public #175) -- the role pipeline's verbs. `read-jd` and `read-failed` are branches of
       # the shared mutation chain (one role, one attempt: the lock, the validator, the rollback and --dry-run all apply);
       # `capture-batch` and `read-batch` are early-return verbs writing OPPORTUNITIES (and COMPANIES, and the append-only
       # queue and journal) in one locked, validated, rollback-verified transaction, `--dry-run` being `--check`.
       "read-jd", "read-failed", "capture-batch", "read-batch",
       # jobsearch 0.85.0 (dev #839 / public #182, dev #840 / public #181) -- record that a browser read could not HAPPEN (the
       # Browser pane was hidden, or the reader's tab stayed in the background): several ids in one call, ALL or none, an
       # early-return verb writing OPPORTUNITIES in one locked, validated, rollback-verified transaction.
       "not-attempted",
       # jobsearch 0.86.0 (dev #834) -- raise the companies to "look into": an early-return verb, the ONE writer of
       # `companies.raised_on` (at most `search.company_intake_per_run` newly raised per run), one locked, validated,
       # rollback-verified write of COMPANIES plus one `companies-raised` journal event. `--dry-run` is `--check`.
       "raise-companies",
       # jobsearch 0.86.0 (dev #834) -- the network-first verbs: the candidate's answers about a company, a chat, an introduction and
       # a source. Each writes ONE store in one locked, validated, rollback-verified transaction and is never run unattended; the
       # `--dry-run` of each is proven in test_record_company_status.py / test_record_chat.py.
       "company-status", "chat", "attended", "intro-offered", "via",
       # jobsearch 0.88.0 (dev #915) -- the two writers of the Targets-to-review list's stored fields (`later_on`, `kind`), each ONE
       # field of ONE company in one locked, validated, rollback-verified write, behind the 0.88.0 pin. `--dry-run` is proven in
       # test_record_call_surface.py's VERB_ARGS and test_record_pay_evidence.py.
       "company-later", "company-kind",
       # jobsearch 0.86.0 (dev #834) -- the proposals verbs (a proposal to a prospective client of a non-employee engagement) and the
       # suggestion verbs (the strategist's proposed row, the candidate's confirm or decline). Each is a locked, validated,
       # rollback-verified write; `suggest` writes the ASK only, `confirm` writes the suggested row AND resolves the ask in ONE write.
       "proposal", "proposal-status", "suggest", "confirm", "decline")
SOURCING_OPS = ("screened", "lean", "listed-pay", "posted")


def _touch_requirement_lines(_vd):
    """dev #686 / public #139 (rule 3) — the CONDITIONAL touch requirements, as printable lines,
    read from `validate_data.py`'s own NAMED constants (never a typed copy), so a caller can
    build a valid `create --file touches` row, or run `touched`, from `fields` or `--help`
    alone. The `required:` line above only lists the unconditional four; these are the rules
    that used to surface one failed write at a time."""
    return [
        "  CONDITIONALLY REQUIRED (enforced by validate_data.py; the names below are its own "
        "constants):",
        "    status=sent                    requires: %s (non-empty), %s (ISO date)"
        % (_vd.SENT_REQUIRES_FIELD, _vd.SENT_REQUIRES_DATE_FIELD),
        "    date >= %s and status=sent  requires: %s"
        % (_vd.COMMS_CUTOVER, ", ".join(_vd.COMMS_REQUIRED_FIELDS)),
        "    medium %s*                  requires: %s"
        % (_vd.EMAIL_MEDIUM_PREFIX, _vd.EMAIL_REQUIRES_FIELD),
        "    (`record.py touched` fills every one of these; touch_type is set with "
        "--touch-type, default 'unknown')",
    ]


def _help_epilog():
    """The `--help` footer: the person-anchored `touched` form and `involve`, with the touch
    requirements named. Fails open to a shorter footer — a broken validator import must never
    make `--help` itself crash."""
    lines = [
        "touched / involve (dev #686 / public #139):",
        "  touched <opp_id> --to contact:<person-id> --medium <MEDIA> [--on D] [--role R] "
        "[--touch-type T]",
        "  touched          --to contact:<person-id> --medium <MEDIA> [--on D] [--role R] "
        "[--touch-type T]",
        "      the second form (no opp_id) records a PERSON-ANCHORED touch: a relationship with",
        "      a person who has no opportunity and no channel. --to, --medium and --on are",
        "      checked before the lock and before any write.",
        "  involve <person-id> --opp <opp_id> [--role R]",
        "      link a person to an opportunity later; earlier person-anchored touches are "
        "left as they were.",
        "  create <id> '<json>' --file people --reuse",
        "      get-or-create: an identical LinkedIn, or an identical email AND name, reuses "
        "the existing person (nothing written);",
        "      an email-only match is refused and listed as a candidate.",
        "",
        "sourcing screen (dev #713-#716 / public #142-#145) -- each stores what a script computed:",
        "  create <id> '<json>' --from-item <capture-role item id>",
        "      copies the pay, posting date and setting the sweep's ROLE line carried "
        "(listed_pay, posted, location.declared)",
        "      onto the new role; a slot the sweep did not read stays absent.",
        "  screened <opp_id> [--on D]                 re-run the minimal screen and store it",
        "  lean <opp_id> --lean pursue|pass|ask --line \"<one line>\" [--jd-file P] [--on D]",
        "  listed-pay <opp_id> --none-shown --pay-source candidate | --stated R[;R] | --estimate R[;R] [--pay-source S]",
        "      R is <min>-<max>/<yr|mo|day|hr>/<CUR> or <min>+/<unit>/<CUR>",
        "  posted <opp_id> --document-date D | --ats-date D | --board-date D | --shown-age N | "
        "--unknown",
        "",
        "research fit (dev #861 / public #194) -- the researcher's `fit`, handed back by file, before a role is ready:",
        "  " + FIT_USAGE,
        "      one JSON object per line ({opp, jd_source, requirements[]}); analyzed_on is stamped here, never typed.",
        "",
        "employer posting (dev #776 / public #166) -- the ONE writer of an opportunity's employer_posting:",
        "  posting --from-file <file of EMPLOYER-POSTING lines> [--dry-run] [--already-locked]",
        "      reads every EMPLOYER-POSTING line in the file (never argv); set / set-in / append / create refuse the field.",
    ]
    try:
        lines.append("")
        lines.append("touches — what a row needs:")
        lines.extend(_touch_requirement_lines(_validator_module()))
    except Exception:                                            # noqa: BLE001
        pass
    return "\n".join(lines)


def build_parser(argv=None):
    """record.py's ONE argument grammar, help text included (moved out of `main`). `argv` (default:
    `sys.argv[1:]`) is read only to decide whether help was asked for: the long epilog is built then
    and only then. Each `_*_arguments` below adds one consecutive run of the flags, in the order
    `--help` prints them."""
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="Atomic writes to the record stores.",
                                 epilog=(_help_epilog() if any(a in ("-h", "--help") for a in argv) else None),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    _core_arguments(ap)
    _write_arguments(ap)
    _sourcing_arguments(ap)
    _pipeline_arguments(ap)
    _network_arguments(ap)
    return ap


def parse(argv=None):
    """Parse record.py's arguments (default: `sys.argv[1:]`). A bad one prints argparse's usage and exits 2."""
    return build_parser(argv).parse_args(argv)


def _core_arguments(ap):
    """The verb, its id and operands, `--file`, and the flags of the message, decision and person verbs."""
    # States & Views V1 (design-states-and-views.md §13/§15.3) — three new verbs, each a
    # transaction over ONE file: `decide` and `networking-closed` on opportunities,
    # `application-status` on applications. Presented as new operations (not `set`/`set-in`)
    # because each carries its own refusal logic `set` cannot express (§15.3's own reasoning).
    # States & Views V1b (design §13/§15.3) — `answered`/`touched` join the verb set: the
    # only two writers `messages` (append-only, MESSAGES_WRITE_VERBS above) ever gets.
    ap.add_argument("op", choices=OPS)
    ap.add_argument("rid", nargs="?", help="record id (e.g. an opportunity_id)")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--file", default="opportunities", choices=sorted(STORES))
    ap.add_argument("--why-kind", dest="why_kind", default=None,
                    help="decide: required when the verdict diverges from the engine's own "
                         "suggestion — one of validate_data.DECISION_REASON_KINDS.")
    ap.add_argument("--why", dest="why", default=None,
                    help="decide: the reason in the owner's own words, required alongside "
                         "--why-kind on a diverging decision.")
    ap.add_argument("--i-checked", dest="i_checked", default=None,
                    help="networking-closed: an ISO date asserting the owner looked personally — "
                         "the one way to close on UNVERIFIED silence (§15.1).")
    ap.add_argument("--on", dest="on_date", default=None,
                    help="application-status/touched/answered: the ISO date the write takes "
                         "(default: today for touched/answered; required for "
                         "application-status is optional too, same default).")
    ap.add_argument("--to", dest="to_token", default=None,
                    help="touched: `contact:<person-id>` — who the touch went to (required; "
                         "the person must exist and not be merged).")
    ap.add_argument("--medium", dest="medium", default=None,
                    help="touched: one of validate_data.MEDIA (required).")
    ap.add_argument("--touch-type", dest="touch_type", default=None,
                    help="touched: one of validate_data.TOUCH_TYPES (optional, default "
                         "'unknown'; the validator requires touch_type on a sent touch dated "
                         "on/after COMMS_CUTOVER, so the verb always fills it).")
    ap.add_argument("--reuse", action="store_true",
                    help="create --file people: get-or-create. An identical normalized "
                         "LinkedIn, or an identical email AND name, reuses the existing person "
                         "and writes nothing; an email-only match is refused and listed as a "
                         "candidate (people.py's own matcher, ADR-031 §3).")
    ap.add_argument("--via", dest="via_medium", default=None,
                    help="answered: the medium the reply went out on — one of "
                         "validate_data.MEDIA.")
    ap.add_argument("--role", dest="recipient_role", default=None,
                    help="touched/answered/involve: one of validate_data.RECIPIENT_ROLES (optional) — "
                         "feeds the involvement's path_type via plays.ROLE_TO_PATH when the "
                         "recipient's involvement does not already have one (dev #479).")
    ap.add_argument("--opp", dest="opp_id", default=None,
                    help="answered: the opportunity this reply belongs to — required when "
                         "the target is a `contact:<id>` touch ref rather than a message id "
                         "(a bare message id already carries its own opp_id/channel_id). "
                         "involve: the opportunity to link the person to (required).")
    ap.add_argument("--when", dest="when_token", default=None,
                    help="set play:<id> params.<name>: the arm's predicate token — creates or "
                         "edits that arm (design §24.1). A NEW arm requires --why.")
    ap.add_argument("--plan", dest="plan_id", default=None,
                    help="create --file opportunities: which search plan sourced this role, "
                         "when more than one active search plan sources role/contract "
                         "(design §26.5) — required only in that ambiguous case.")
    ap.add_argument("--url", dest="listing_url", default=None,
                    help="unlink-sibling: the listing's source_url on the canonical row to split "
                         "away (dev #728 / public #158).")
    ap.add_argument("--into", dest="into_id", default=None,
                    help="merge-person: the SURVIVOR person id. The record named by <rid> "
                         "(the duplicate) gets status=merged, merged_into=<--into>, in one "
                         "write. Refused if that would close a merge cycle (public #93).")
    ap.add_argument("--note", dest="note_text", default=None,
                    help="application-status: appended to the row's existing `note` (never "
                         "overwritten — an owner's hand note survives) in the SAME transaction "
                         "as status/status_on (design-inbound-resolution.md §2).")
    ap.add_argument("--channel", dest="channel_id", default=None,
                    help="received: `--channel <channel_id>` — the other half of the anchor "
                         "rule (--opp or --channel, at least one, never both).")
    ap.add_argument("--person", dest="person_id_arg", default=None,
                    help="received: the sender's people.jsonl id, when known. With neither "
                         "--opp nor --channel a resolving --person is itself the anchor (a "
                         "message to/from a person about no role and no channel).")
    ap.add_argument("--from", dest="from_addr", default=None,
                    help="received: the message's From address.")
    ap.add_argument("--subject", dest="subject", default=None,
                    help="received: the message's Subject line.")
    ap.add_argument("--body-file", dest="body_file", default=None,
                    help="received: path to a file holding the body — never argv (an ATS "
                         "body is thousands of characters); written under the profile's own "
                         "scratch, never /tmp.")
    ap.add_argument("--source", dest="source_token", default=None,
                    help="received: provenance, e.g. gmail:<account>:<uid> — the id is minted "
                         "from this deterministically, so re-sending the same source is a "
                         "no-op, never a duplicate.")
    ap.add_argument("--resolves", dest="resolves", default=None,
                    help="received: the applications.id this inbound message resolves "
                         "(ADR-029/030). Requires --resolved-by; the opp anchor is then "
                         "DERIVED from the application's own opp_id — a conflicting --opp is "
                         "refused.")
    ap.add_argument("--resolved-by", dest="resolved_by", default=None,
                    choices=("req-id", "url", "company-single"),
                    help="received: which of ADR-030's three tiers matched. Required iff "
                         "--resolves is given.")
    ap.add_argument("--source-url", dest="source_url_flag", default=None,
                    help="append <id> sightings '{...}': merges this URL into the sighting as "
                         "'source_url' — public #83 rule 1's own convenience, so a caller never "
                         "has to hand-embed it in the JSON blob. Conflicts with an already-set "
                         "'source_url' in the JSON are refused (one fact, stated once).")


def _write_arguments(ap):
    """The flags of the write itself (`--dry-run`, the lock, `--force`) and of `create`."""
    ap.add_argument("--_inject-fault", dest="inject_fault", default=None,
                    help=argparse.SUPPRESS)     # test-only — see cmd_touched's own docstring
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", type=int, default=DEFAULT_WAIT,
                    help="Seconds to wait for the run lock (default %d — holders release in "
                         "seconds; a longer wait usually means you are waiting on your own "
                         "run, which never ends: see --already-locked)." % DEFAULT_WAIT)
    ap.add_argument("--already-locked", action="store_true",
                    help="The CALLING RUN already holds the run lock (it took it for its write "
                         "phase). Write under that hold; take and release nothing. Verified: "
                         "refused if nobody actually holds the lock.")
    ap.add_argument("--force", action="store_true",
                    help="Write an unknown field anyway. Almost never right — an unknown field "
                         "is invisible to every query written against the real one.")
    ap.add_argument("--req-id", dest="req_id", default=None,
                    help="create (opportunities): the ATS requisition id the sourced posting "
                         "carries. Used ONLY to match an already-passed role (dev #670); "
                         "never stored.")
    ap.add_argument("--fields", action="store_true",
                    help="Print what this store accepts, so a caller never has to guess.")
    ap.add_argument("--from-item", dest="from_item", default=None,
                    help="create (opportunities): a `capture-role` deferred item id. Copies the "
                         "pay, posting date and work setting `deferred.py --add-roles` parsed from "
                         "the sweep's ROLE line (listed_pay, posted, location.declared, "
                         "location.primary) onto the new role. A slot the sweep did not read stays "
                         "absent; a value the JSON also carries must agree with the item. When the "
                         "sweep read setting=\"none stated\" at a concrete place, the script sets "
                         "location.type onsite and location.setting_source inferred (omit "
                         "location.type; giving one is refused).")


def _sourcing_arguments(ap):
    """The flags of the sourcing-screen, company-feed, board-sighting, channel-catalog and posting verbs."""
    # jobsearch 0.67.0 sourcing-screen verbs (SOURCING_OPS) -- each flag belongs to one verb.
    ap.add_argument("--lean", dest="lean_choice", default=None,
                    help="lean: pursue | pass | ask (required, except on a role whose stored screen "
                         "carries the age flag -- over-age or unknown-age recruiter role -- where "
                         "omitting it records `ask` with the age line's first move).")
    ap.add_argument("--line", dest="line_text", default=None,
                    help="lean: the one-line reason (required, one line, capped).")
    ap.add_argument("--jd-file", dest="jd_file", default=None,
                    help="lean: a file holding the JD text the run read; the likely-pass "
                         "signals are matched against it as well as the title and company.")
    ap.add_argument("--none-shown", dest="none_shown", action="store_true",
                    help="listed-pay: the CANDIDATE read the posting and it showed NO pay (recorded, so it is not "
                         "'never captured'); needs --pay-source candidate.")
    ap.add_argument("--stated", dest="stated", default=None,
                    help="listed-pay: the EMPLOYER's range(s), <min>-<max>/<yr|mo|day|hr>/<CUR> "
                         "or <min>+/<unit>/<CUR>, separated by ';'.")
    ap.add_argument("--estimate", dest="estimate", default=None,
                    help="listed-pay: a BOARD's own estimate (never the employer's figure; it "
                         "can never remove a role), same range grammar.")
    ap.add_argument("--pay-source", dest="pay_source", default=None,
                    help="listed-pay: where the figure was read (default listing-text).")
    ap.add_argument("--document-date", dest="document_date", default=None,
                    help="posted: the date a recruiter's spec document carries "
                         "(source profile-document-date -- this flag is its only writer).")
    ap.add_argument("--ats-date", dest="ats_date", default=None,
                    help="posted: a JSON-LD datePosted or ATS API date (source ats-posted).")
    ap.add_argument("--board-date", dest="board_date", default=None,
                    help="posted: a bare date a board shows (source board-relative).")
    ap.add_argument("--shown-age", dest="shown_age", default=None,
                    help="posted: the age a board shows, in days; the date is COMPUTED from "
                         "the run date by this script (source board-relative).")
    ap.add_argument("--unknown", dest="unknown", action="store_true",
                    help="posted: record that the age is unknown (source unknown).")
    # jobsearch 0.72.0 (dev #751) company-feed verbs.
    ap.add_argument("--none", dest="ats_none", action="store_true",
                    help="ats: DECLINE a feed for this company (`ats: null`); discovery never "
                         "rewrites it.")
    ap.add_argument("--clear", dest="ats_clear", action="store_true",
                    help="ats: remove the `ats` key so discovery may run again.")
    ap.add_argument("--discover", dest="ats_discover", action="store_true",
                    help="ats: parse the slug off the company's own career_url / jd_url / sighting "
                         "URLs (never a fetch). Writes only an unambiguous result, and never over "
                         "an existing `ats` key (a declined `null` included).")
    ap.add_argument("--none-found", dest="none_found", action="store_true",
                    help="warm-lookup: record that you looked for a person at this company and "
                         "found nobody (with --on, default today).")
    # jobsearch 0.75.0 (dev #765) board-sighting flags (`--url` and `--plan` are the existing ones).
    ap.add_argument("--company", dest="company_name", default=None,
                    help="board-sighting: the company's name as the board shows it (matched against "
                         "the companies store by pipeline_index.company_candidates).")
    ap.add_argument("--company-id", dest="company_id_arg", default=None,
                    help="board-sighting: an existing companies id, when --company is ambiguous.")
    ap.add_argument("--title", dest="title_text", default=None,
                    help="board-sighting: the role's title as the board shows it.")
    ap.add_argument("--vertical", dest="vertical_arg", default=None,
                    help="board-sighting: required only when the company is NOT yet tracked and so is "
                         "created (one of validate_data.VERTICALS).")
    ap.add_argument("--seen-on", dest="seen_on", default=None,
                    help="board-sighting: the ISO date you saw the role (default: today).")
    # jobsearch 0.76.0 (dev #769) channel-catalog flags (`--on` and `--dry-run` are the existing ones).
    ap.add_argument("--kind", dest="cc_kind", default=None,
                    choices=("portfolio", "curated", "swept-board", "alert-sender"),
                    help="channel-catalog add: turn on every non-retired entry of one kind in one write.")
    ap.add_argument("--attach", dest="cc_attach", default=None,
                    help="channel-catalog add <entry>: tie an EXISTING channel you already hold to the entry "
                         "(fills only its absent managed fields) instead of creating a second row for one board.")
    ap.add_argument("--anyway", dest="src_anyway", action="store_true",
                    help="source on <id>: turn on a source whose catalog entry the catalog retired (the row then counts "
                         "as edited).")
    ap.add_argument("--firm", dest="cc_firm", default=None,
                    help="channel-catalog add <portfolio entry>: the companies id to use as the firm when the "
                         "firm's name matches several companies you track.")
    # jobsearch 0.80.0 (dev #776) posting flags. NO `--from-line`: a line on argv is a line a shell has already
    # parsed, and a posting's quoted visible text holds quotes, a dollar sign and backticks (design section 15 N1).
    ap.add_argument("--from-file", dest="from_file", default=None,
                    help="posting: a file holding the EMPLOYER-POSTING lines to record (the researcher's hand-back, or "
                         "`posting_check.py --run`'s own file). Every such line in it is read; other lines are ignored.")
    ap.add_argument("--today", dest="today_arg", default=None,
                    help="posting / create --from-item: TEST-ONLY. The run date as YYYY-MM-DD, so a dated case runs end "
                         "to end; omitted, it is today. Never pass it in a real run.")


def _pipeline_arguments(ap):
    """The flags of the role pipeline's verbs: read-jd, read-failed, not-attempted, capture-batch, read-batch."""
    # jobsearch 0.82.0 (dev #820 / public #175) -- the role pipeline's flags. `--url` and `--via` are the existing ones
    # (read-jd / read-failed reuse them); `--json` belongs to `show`.
    ap.add_argument("--run", dest="run_id_arg", default=None,
                    help="read-jd / read-failed / capture-batch / read-batch: the id of the run making the write "
                         "(stored on the attempt and the capture record; the drain's `drain planned` event is found "
                         "by it).")
    ap.add_argument("--pay", dest="pay_slot", default=None,
                    help="read-jd: the pay the posting states, in the ROLE line's grammar: none | ? | "
                         "stated:<min>-<max>/<yr|mo|day|hr>/<CUR> | estimate:<range>. `none` means you read the WHOLE "
                         "description and it states no pay (refused with --via fetch when the saved body states one); `?` means "
                         "you did not find or could not parse pay, and records NOT captured (re-read before the role is "
                         "surfaced).")
    ap.add_argument("--setting", dest="setting_text", default=None,
                    help="read-jd: the posting's own work-setting text, verbatim, or the literal `none stated`.")
    ap.add_argument("--location", dest="location_text", default=None,
                    help="read-jd: the posting's place text, verbatim, or ? when it states none.")
    ap.add_argument("--evidence", dest="evidence_text", default=None,
                    help="read-jd / read-failed: 1-200 characters. Under render, a quote of the posting's own title or "
                         "Apply text (it must share a word with this role's title or company); under candidate, the "
                         "candidate's own one-line note; under read-failed, the status line, the error text or the "
                         "page's own words.")
    ap.add_argument("--status-text", dest="status_text", default=None,
                    help="read-jd --via render: the words on the page where the Apply control is, verbatim (or its "
                         "status line), 1-200 characters on one line, or the literal `none shown`. Checked against "
                         "the closed-status marker and never stored: a page that says it is no longer accepting "
                         "applications is `read-failed --outcome closed`, never a read (dev #871).")
    ap.add_argument("--outcome", dest="outcome_arg", default=None,
                    help="read-failed: closed | dead-link | manual-board | no-url | login-wall | challenge | "
                         "render-failed | surface-cannot-read | site-not-allowed.")
    ap.add_argument("--reason", dest="reason_text", default=None,
                    help="not-attempted: pane-hidden (the only reason: the Browser pane was hidden, or the reader's tab "
                         "stayed in the background after one re-front).")
    ap.add_argument("--pane", dest="pane_line", default=None,
                    help="not-attempted / read-failed (required for render-failed): the last line of "
                         "`mcp__Claude_Browser__tabs_context`, as the harness wrote it. The "
                         "pane state is PARSED from it (`pane_probe.pane_state`) and stored; the raw line never is.")
    ap.add_argument("--page-result", dest="page_result", default=None,
                    help="read-failed --via render: what THIS page's read gave -- `chars=<N>` (the length of its get_page_text "
                         "result) or `error=<the tool's own error text, 1-120 characters>`. Required for every outcome but "
                         "no-url, manual-board and site-not-allowed: no page outcome is recorded for a page that was not opened "
                         "and read (dev #838 / public #183).")
    ap.add_argument("--probe", dest="probe_json", default=None,
                    help="RETIRED (jobsearch 0.90.0, dev 858): `gate` replaces `probe` for new writes. Any value is refused "
                         "and the refusal says what to run (`pane_probe.py --gate`) and which flag to pass (--gate).")
    ap.add_argument("--browser", dest="browser_arg", default=None,
                    help="read-jd / read-failed / not-attempted, --via render (0.90.0, dev 858): which browser made the "
                         "attempt, pane | extension. Refused below the 0.90.0 profile pin.")
    ap.add_argument("--ready", dest="ready_arg", default=None,
                    help="read-failed / not-attempted (0.90.0): the word `page_ready.py --verdict` printed for this page, "
                         "READY | NOT-READY | READY-ERROR.")
    ap.add_argument("--gate", dest="gate_arg", default=None,
                    help="read-failed / not-attempted (0.90.0): the word `pane_probe.py --gate --result <json>` printed for "
                         "the frame probe run on this page, paints | not-painting | probe-error. render-failed requires it and "
                         "is refused on not-painting or probe-error (a page that does not paint was never read).")
    ap.add_argument("--fallback-extension", dest="fallback_ext_arg", default=None,
                    help="read-failed / not-attempted (0.90.0): why the Chrome extension rung did not read this page, one of "
                         "the jd_read.EXTENSION_CODES (tools-absent, not-connected, not-this-computer, browser-ambiguous, "
                         "unattended-unprobed, not-preferred, lock-held, navigate-timeout, not-painting, not-ready, "
                         "challenge, permission-denied, not-signed-in).")
    ap.add_argument("--body-sha1", dest="body_sha1", default=None,
                    help="read-jd --via fetch: the sha1 the `RESIDUE <id> (body)` line printed. The read is refused unless it "
                         "matches the saved body's index entry and file, and the evidence, location and every --pay figure are "
                         "found in that body.")
    ap.add_argument("--tab-active", dest="tab_active", default=None, choices=("yes", "no"),
                    help="not-attempted: yes | no, the reader's own word about whether its tab was in front (the engine "
                         "cannot check it, and the stored evidence names it `tab_active` for that reason).")
    ap.add_argument("--link-only", dest="link_only", action="store_true",
                    help="capture-batch: link every open capture-role item that is a sighting of a known role "
                         "(before intake; they never consume it).")
    ap.add_argument("--admitted", dest="admitted", action="store_true",
                    help="capture-batch: create the roles the run's `drain planned` event admitted, from their oldest "
                         "item, and close every sibling item.")
    ap.add_argument("--fetch", dest="fetch", action="store_true",
                    help="read-batch: read each admitted role's posting by script (JSON-LD), settle what it can and "
                         "list the rest as the render residue.")
    ap.add_argument("--fallback", dest="fallback", action="store_true",
                    help="read-batch: the automatic fallback (never when search.posting_fetch is off) -- read the public "
                         "logged-out posting of a LinkedIn role no browser could read on this run. Records only `read` or "
                         "`closed` as an outcome; any other answer is stored as why-not-read (fallback.fetch), never as one.")
    ap.add_argument("--ids", dest="ids_arg", nargs="+", default=None, metavar="OPP_ID",
                    help="read-batch --fallback: narrow the fallback to these opportunity ids (it never widens the set).")


def _network_arguments(ap):
    """The flags of the network-first, proposal and suggestion verbs, `--check`, `--deadline-s` and `--json`."""
    # jobsearch 0.86.0 (dev #834) -- the network-first verbs' flags (`--on`, `--person`, `--opp`, `--title` and `--company` are the
    # existing ones: `--company` is a company ID for `intro-offered`, the board's company NAME for `board-sighting`).
    ap.add_argument("--motivation", dest="motivation_arg", default=None,
                    help="company-status active-target: how much the candidate wants to work there, a whole number 1-5 "
                         "(required for a target; refused beside watching or passed).")
    ap.add_argument("--time", dest="time_arg", default=None,
                    help="chat: the time of the chat, HH:MM (24 hours).")
    ap.add_argument("--touch", dest="touch_arg", default=None,
                    help="chat: the `meeting-booked` touch this chat came from (it must be a touch to the same person).")
    ap.add_argument("--notes", dest="notes_arg", default=None,
                    help="attended: the candidate's notes for the chat, a path relative to the profile root (no `..`, never absolute).")
    ap.add_argument("--chat", dest="chat_arg", default=None,
                    help="via: the commitments id of the chat that surfaced the role or application (it must be with --person).")
    # jobsearch 0.86.0 (dev #834) -- the proposal and suggestion verbs' flags. The design (8.2) spells suggest's flags `--op` and
    # `--fields`; `op` is this CLI's positional verb and `--fields` already lists a store's fields, so they are `--action` and `--values`.
    ap.add_argument("--scope", dest="scope_text", default=None,
                    help="proposal: what the proposal covers, in the candidate's words.")
    ap.add_argument("--rate", dest="rate_arg", default=None,
                    help="proposal: the rate as <amount>/<hour|day|month|year|project>/<CURRENCY>, e.g. 1500/day/USD.")
    ap.add_argument("--store", dest="suggest_store", default=None,
                    help="suggest: the store the suggested row belongs to (companies, plans or people).")
    ap.add_argument("--action", dest="suggest_action", default=None,
                    help="suggest: `set` (change fields of an existing row) or `create` (a new row).")
    ap.add_argument("--target-id", dest="suggest_id", default=None,
                    help="suggest: the id of the row to set, or of the row a `create` would make.")
    ap.add_argument("--values", dest="values_json", default=None,
                    help="suggest: the fields to write, as one JSON object (e.g. '{\"status\": \"active-target\"}').")
    ap.add_argument("--ask", dest="ask_text", default=None,
                    help="suggest: the question and the reason, in the strategist's words (it is what the candidate reads).")
    ap.add_argument("--set", dest="set_pairs", action="append", default=None, metavar="FIELD=VALUE",
                    help="confirm: the candidate's own value for a field of the suggested row (repeatable), e.g. --set motivation=4.")
    ap.add_argument("--check", dest="check", action="store_true",
                    help="capture-batch / read-batch: compute and print, write nothing (--dry-run is the same).")
    ap.add_argument("--deadline-s", dest="deadline_s", type=int, default=None,
                    help="capture-batch (default %d) / read-batch (default %d): stop BETWEEN roles after this many "
                         "seconds, write what is done and print `deadline-left N`." %
                         (CAPTURE_DEADLINE_S_DEFAULT, FETCH_DEADLINE_S_DEFAULT))
    ap.add_argument("--json", dest="json_out", action="store_true",
                    help="show: print the whole record as ONE compact JSON line.")


def bind_store(args):
    """Set `args.file` for every verb that owns its store (moved out of `main`): `--file` is never the caller's
    to pick for those."""
    # These three verbs each own exactly one store — --file is never the caller's to pick for
    # them (a mistaken --file would silently target the wrong record and never be diagnosed).
    if args.op in ("decide", "networking-closed") + SOURCING_OPS + JD_READ_OPS + BATCH_OPS:
        args.file = "opportunities"
    elif args.op == "application-status":
        args.file = "applications"
    elif args.op == "touched":
        # ADR-031 B3 — `cmd_touched` writes `touches`/`messages` internally by name, never
        # through this generic `--file`-driven path (it returns before reaching it, below);
        # this assignment only keeps the messages-append-only refusal check harmless.
        args.file = "opportunities"
    elif args.op == "answered":
        args.file = "messages"
    elif args.op == "received":
        args.file = "messages"
    elif args.op == "merge-person":
        args.file = "people"
    elif args.op == "involve":
        args.file = "opportunities"      # cmd_involve names its own stores; keeps the generic checks harmless
    elif args.op in ("ats", "warm-lookup"):
        args.file = "companies"          # dev #751: cmd_ats / cmd_warm_lookup name their own stores
    elif args.op == "board-sighting":
        args.file = "opportunities"      # dev #765: cmd_board_sighting names its own stores
    elif args.op == "channel-catalog":
        args.file = "channels"           # dev #769: cmd_channel_catalog names its own stores
    elif args.op == "source":
        args.file = "channels"           # dev #774: cmd_source names its own stores
    elif args.op == "posting":
        args.file = "opportunities"      # dev #776: cmd_posting names its own stores
    elif args.op == "fit":
        args.file = "opportunities"      # dev #861: cmd_fit names its own store
    elif args.op in ("company-status", "company-later", "company-kind"):
        args.file = "companies"          # dev #834: the network-first verbs each name their own store
    elif args.op in ("chat", "attended", "intro-offered"):
        args.file = "commitments"
    elif args.op == "via":
        args.file = "opportunities"
    elif args.op in ("proposal", "proposal-status"):
        args.file = "proposals"          # dev #834: the proposal verbs name their own stores
    elif args.op in ("suggest", "confirm", "decline"):
        args.file = "asks"


def messages_refusal(args):
    """1, printed, when a verb other than answered/touched/received would write `messages`; else None."""
    # §15.3 point 1 — `messages` is append-only; `answered`/`touched`/`received` are its ONLY
    # writers. Refused here, before any generic single-store machinery runs, so the refusal is
    # the very first thing printed rather than a confusing failure two steps later.
    if args.file == "messages" and args.op not in MESSAGES_WRITE_VERBS:
        print("⛔ REFUSED — 'messages' is append-only (design §15.3): a message row is "
              "immutable once written. Use `record.py answered ...`, `record.py touched ...` "
              "or `record.py received ...` — never set/set-in/append/create/show --file "
              "messages.")
        return 1
