"""THE ordered list of migrations, and `pending_for()`, the one answer to what a profile still needs.

Order is the tuple's order. Explicit, never discovered (design decision D4): a migration file missing from an install
is an ImportError here, never a migration skipped in silence. `assert_store_versions_known()` is the check that
`STORE_INTRODUCED` names only versions this registry knows; `migrate.py` calls it on every run, after the trampoline.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

from migrations import (
    m_0_13_0,
    m_0_14_0,
    m_0_17_0,
    m_0_18_0,
    m_0_19_0,
    m_0_20_0,
    m_0_24_0_blocked_until,
    m_0_24_0_last_touch,
    m_0_25_0_focus_retirement,
    m_0_25_0_play_stage,
    m_0_26_0_state_home,
    m_0_27_0_alert_sender_backfill,
    m_0_27_0_cover_preconditions,
    m_0_29_0_gmail_connector_config,
    m_0_31_0_mail_client_rename,
    m_0_32_0_tree,
    m_0_34_0_dashboard_collapse,
    m_0_35_0_task_file_where,
    m_0_36_0_archive_past_preps,
    m_0_36_0_derive_from_applications,
    m_0_36_0_message_answers,
    m_0_37_0_medium_line,
    m_0_39_0_presence_rules,
    m_0_40_0_commitment_status,
    m_0_41_0_app_ids,
    m_0_41_0_ats_config_keys,
    m_0_41_0_ats_status_phrases,
    m_0_44_0_people_involvements,
    m_0_45_0_applications_cover_letters,
    m_0_46_0_brief_line,
    m_0_47_0_application_endings,
    m_0_47_0_drafts_working_set,
    m_0_47_0_states_config_keys,
    m_0_48_0_application_endings_restamp,
    m_0_48_0_brief_line_restamp,
    m_0_48_0_probe_single_token_ack,
    m_0_48_0_touches,
    m_0_49_0_plans_plays,
    m_0_4_0,
    m_0_50_0_ats_config_keys,
    m_0_50_0_geography_keys,
    m_0_50_0_variant_surface_field,
    m_0_54_0_linkedin_quota,
    m_0_54_0_touch_propagation,
    m_0_56_0_resumes_to_presence,
    m_0_56_0_retire_dashboard_tombstone,
    m_0_57_0_probe_dedup_key,
    m_0_63_0_mailbox_references,
    m_0_66_0_uid_text,
    m_0_67_0_sourcing_screen_config_keys,
    m_0_69_0_passed_backlog_terminal,
    m_0_70_0_location_screen_config_keys,
    m_0_71_0_retire_presence_artifact,
    m_0_72_0_ats_feeds,
    m_0_76_0_source_adoption,
    m_0_76_0_workday_hosts,
    m_0_76_1_legacy_placeholders,
    m_0_78_0_board_schedule,
    m_0_82_0_role_lifecycle,
    m_0_83_0_capture_channel,
    m_0_85_0_readmit_render_failed,
    m_0_86_0_network_first,
    m_0_86_0_proposals,
    m_0_88_0_pay_evidence,
    m_0_90_0_browser_fallback,
)
from migrations.stamp import engine_version, read_stamp, ver
from migrations.stores import STORE_INTRODUCED
from migrations.support_pins import NETWORK_FIRST_PIN, _network_first_pin_needed


MIGRATIONS = (("0.4.0", m_0_4_0.m_0_4_0), ("0.13.0", m_0_13_0.m_0_13_0), ("0.14.0", m_0_14_0.m_0_14_0),
              ("0.17.0", m_0_17_0.m_0_17_0), ("0.18.0", m_0_18_0.m_0_18_0), ("0.19.0", m_0_19_0.m_0_19_0),
              ("0.20.0", m_0_20_0.m_0_20_0), ("0.24.0", m_0_24_0_blocked_until.m_0_24_0_blocked_until),
              ("0.24.0", m_0_24_0_last_touch.m_0_24_0_last_touch), ("0.25.0", m_0_25_0_play_stage.m_0_25_0_play_stage),
              ("0.25.0", m_0_25_0_focus_retirement.m_0_25_0_focus_retirement), ("0.26.0", m_0_26_0_state_home.m_0_26_0_state_home),
              ("0.27.0", m_0_27_0_cover_preconditions.m_0_27_0_cover_preconditions),
              ("0.27.0", m_0_27_0_alert_sender_backfill.m_0_27_0_alert_sender_backfill),
              ("0.29.0", m_0_29_0_gmail_connector_config.m_0_29_0_gmail_connector_config),
              ("0.31.0", m_0_31_0_mail_client_rename.m_0_31_0_mail_client_rename),
              # ⭐ the tree migration stays LAST among pre-0.33 migrations: earlier
              # migrations in the same pending batch (a stamp several minors behind) write
              # the OLD paths and are correct at the moment they run, because this one has
              # not moved them yet. The dashboard-collapse migration comes AFTER it for the
              # same ordering reason in reverse — it reads the post-move views/ layout.
              #
              # ⚠️ KEYED "0.34.0", NOT "0.33.0" — see m_0_34_0_dashboard_collapse's docstring.
              # It was written while 0.33.0 was unpublished, but 0.33.0 shipped without it
              # (jobsearch--v0.33.0's MIGRATIONS ends at 0.32.0), so a profile that installed
              # that real release has a stamp of exactly "0.33.0". pending_for()'s strict "<"
              # means a migration keyed "0.33.0" would never fire for that profile on any
              # later upgrade. It must be keyed to the version it actually ships in.
              ("0.32.0", m_0_32_0_tree.m_0_32_0_tree),
              ("0.34.0", m_0_34_0_dashboard_collapse.m_0_34_0_dashboard_collapse),
              # ⚠️ KEYED "0.35.0" — the version that will SHIP it, while 0.34.0 is the newest
              # PUBLISHED release (ADR-009: migration keys are versions too; a migration keyed
              # to an already-published version is silently unreachable for everyone who
              # installed that exact release, because pending_for() compares with strict `<`).
              ("0.35.0", m_0_35_0_task_file_where.m_0_35_0_task_file_where),
              # ⚠️ KEYED "0.36.0" — 0.35.0 is the newest PUBLISHED release (ADR-009): a
              # profile that installed it is stamped exactly "0.35.0", and strict `<` would
              # never fire a migration keyed to it. Re-verified when 0.36.0 is cut.
              ("0.36.0", m_0_36_0_derive_from_applications.m_0_36_0_derive_from_applications),
              ("0.36.0", m_0_36_0_message_answers.m_0_36_0_message_answers),
              ("0.36.0", m_0_36_0_archive_past_preps.m_0_36_0_archive_past_preps),
              # ⚠️ KEYED "0.37.0" — the version that ships it; 0.36.0-stamped profiles reach
              # it through strict `<`. Re-keyed if 0.37.0 is cut without it (ADR-009).
              ("0.37.0", m_0_37_0_medium_line.m_0_37_0_medium_line),
              # ⚠️ KEYED "0.39.0" — 0.38.0 is the newest PUBLISHED release (ADR-009): a
              # profile that installed it is stamped exactly "0.38.0", and strict `<` would
              # never fire a migration keyed to it. Re-verified when 0.39.0 is cut.
              ("0.39.0", m_0_39_0_presence_rules.m_0_39_0_presence_rules),
              # ⚠️ KEYED "0.40.0" — 0.39.0 is the newest PUBLISHED release (ADR-009): a
              # profile that installed it is stamped exactly "0.39.0", and strict `<` would
              # never fire a migration keyed to it. Re-verified when 0.40.0 is cut.
              ("0.40.0", m_0_40_0_commitment_status.m_0_40_0_commitment_status),
              # ⚠️ KEYED "0.41.0" — 0.40.0 is the newest PUBLISHED release (ADR-009; verified
              # 2026-09-06 against origin's jobsearch--v0.40.0 tag, not local tags): a profile
              # that installed it is stamped exactly "0.40.0", and strict `<` would never fire
              # a migration keyed to it. Re-verified when 0.41.0 is cut. ORDER IS LOAD-BEARING
              # within the release: the rename produces `receipt_subject_phrases`, which the
              # status_phrases move then carries into `status_phrases.acknowledged`.
              ("0.41.0", m_0_41_0_app_ids.m_0_41_0_app_ids),
              ("0.41.0", m_0_41_0_ats_config_keys.m_0_41_0_ats_config_keys),
              ("0.41.0", m_0_41_0_ats_status_phrases.m_0_41_0_ats_status_phrases),
              # ⚠️ KEYED "0.44.0" — 0.43.0 is the newest PUBLISHED release (ADR-009; verified
              # 2026-09-10 against plugin.json at HEAD and origin/main, which already carries
              # the 0.43.0 bump and its changelog discharge merged — no origin tag exists yet
              # for 0.43.0, a lag CLAUDE.md rule 9 already names as not itself evidence of
              # non-publication). A profile that installed 0.43.0 is stamped exactly "0.43.0",
              # and pending_for()'s strict `<` would never fire a migration keyed to it.
              # Re-verified when 0.44.0 is actually cut.
              ("0.44.0", m_0_44_0_people_involvements.m_0_44_0_people_involvements),
              # ⚠️ KEYED "0.45.0" — 0.44.0 is the newest PUBLISHED release (ADR-009; verified
              # 2026-09-11: `jobsearch--v0.44.0` exists in the local tag list and plugin.json
              # at HEAD reads 0.44.0). A profile that installed 0.44.0 is stamped exactly
              # "0.44.0", and pending_for()'s strict `<` would never fire a migration keyed to
              # it. Re-verified when 0.45.0 is actually cut.
              ("0.45.0", m_0_45_0_applications_cover_letters.m_0_45_0_applications_cover_letters),
              # ⚠️ KEYED "0.46.0" — 0.44.0 is the newest PUBLISHED release at the time this
              # was written (plugin.json at HEAD reads 0.44.0; 0.45.0 is merged but not yet
              # cut). Query or Citation C1's own migration keys to whatever minor actually
              # ships it (design-query-or-citation.md, front matter: "C1 keys >= 0.46.0",
              # ADR-009) — re-verified when 0.46.0 is actually cut.
              ("0.46.0", m_0_46_0_brief_line.m_0_46_0_brief_line),
              # ⚠️ KEYED "0.47.0" — 0.46.0 is the newest PUBLISHED release (ADR-009; verified
              # 2026-09-12: `jobsearch--v0.46.0` exists in the local tag list and plugin.json
              # at HEAD reads 0.46.0). A profile that installed 0.46.0 is stamped exactly
              # "0.46.0", and pending_for()'s strict `<` would never fire a migration keyed
              # to it. Re-verified when 0.47.0 is actually cut. ORDER IS LOAD-BEARING: the
              # config-key seed runs after the endings seed only because neither reads the
              # other's output — independent facts, same as 0.44.0's own two.
              ("0.47.0", m_0_47_0_application_endings.m_0_47_0_application_endings),
              ("0.47.0", m_0_47_0_states_config_keys.m_0_47_0_states_config_keys),
              # States & Views V1b (design §4) — ORDER: after the endings/config-keys seeds,
              # same reasoning 0.44.0's own two carry (independent facts, neither reads the
              # other's output) — this one additionally reads `data/opportunities.jsonl` and
              # `data/channels.jsonl`, which the endings migration may have just seeded
              # `status_on` on; drafts_working_set never touches `status`/`status_on` itself,
              # so the two cannot conflict, but running after keeps every 0.47.0 opportunities
              # write in one declared order rather than an accidental one.
              ("0.47.0", m_0_47_0_drafts_working_set.m_0_47_0_drafts_working_set),
              # ⚠️ KEYED "0.48.0" — 0.47.0 is the newest PUBLISHED release (ADR-009; verified
              # 2026-09-13: the gitStatus at this dispatch's own start shows the 0.47.0
              # release record discharged and its changelog PR already merged to
              # origin/main). A profile that installed 0.47.0 is stamped exactly "0.47.0",
              # and pending_for()'s strict `<` would never fire a migration keyed to it.
              # Re-verified when 0.48.0 is actually cut. ADR-031 B3 — the third store
              # promoted off the opportunity record, same pattern as 0.44.0/0.45.0.
              ("0.48.0", m_0_48_0_touches.m_0_48_0_touches),
              # The first real run of 0.44.0->0.47.0: public #90-#94 (design-first-real-run-
              # 2026-09-13.md §1). Repairs for damage the ALREADY-RUN 0.44.0-0.47.0 migrations
              # left on disk under their own pre-fix bugs — the code-level fixes protect every
              # future run regardless of these three; these three are for the run that already
              # happened. Order does not matter between them (three independent facts: drafts,
              # asks, inbox) but all three run after m_0_48_0_touches so ADR-031 B3's own
              # writes land first, same reasoning 0.44.0/0.45.0's ordering note gives.
              ("0.48.0", m_0_48_0_brief_line_restamp.m_0_48_0_brief_line_restamp),
              ("0.48.0", m_0_48_0_application_endings_restamp.m_0_48_0_application_endings_restamp),
              ("0.48.0", m_0_48_0_probe_single_token_ack.m_0_48_0_probe_single_token_ack),
              # ⚠️ KEYED "0.49.0" — 0.48.0 is the newest PUBLISHED jobsearch release
              # (plugin.json at HEAD; ADR-009's rule, same note every prior stage's own
              # migration carries). Re-verified when 0.49.0 is actually cut.
              ("0.49.0", m_0_49_0_plans_plays.m_0_49_0_plans_plays),
              # ⚠️ KEYED "0.50.0" — 0.49.0 is the newest PUBLISHED jobsearch release
              # (plugin.json at HEAD reads 0.49.0; gitStatus at this dispatch's own start
              # shows the 0.49.0 release record discharged). A profile that installed 0.49.0
              # is stamped exactly "0.49.0", and pending_for()'s strict `<` would never fire a
              # migration keyed to it. Re-verified when 0.50.0 is actually cut.
              # design-inbound-resolution.md (ADR-029/030 build).
              ("0.50.0", m_0_50_0_ats_config_keys.m_0_50_0_ats_config_keys),
              # ⚠️ KEYED "0.50.0" — 0.49.0 is the newest PUBLISHED jobsearch release (gitStatus
              # at this dispatch's own start shows the 0.49.0 release record discharged, commit
              # d9d3b3a). A profile that installed 0.49.0 is stamped exactly "0.49.0", and
              # pending_for()'s strict `<` would never fire a migration keyed to it.
              # Re-verified when 0.50.0 is actually cut. Public #89 / dev #355.
              ("0.50.0", m_0_50_0_geography_keys.m_0_50_0_geography_keys),
              ("0.50.0", m_0_50_0_variant_surface_field.m_0_50_0_variant_surface_field),
              # ⚠️ KEYED "0.54.0" — 0.53.0 is the newest PUBLISHED jobsearch release
              # (plugin.json at HEAD reads 0.53.0; `jobsearch--v0.53.0` exists in the local tag
              # list). A profile that installed 0.53.0 is stamped exactly "0.53.0", and
              # pending_for()'s strict `<` would never fire a migration keyed to it.
              # Re-verified when 0.54.0 is actually cut. design-script-first.md §2/§12,
              # build-list item 3 (public #75/#76/#87/#110).
              ("0.54.0", m_0_54_0_linkedin_quota.m_0_54_0_linkedin_quota),
              # ⚠️ KEYED "0.54.0" — same ADR-009 verification as m_0_54_0_linkedin_quota
              # immediately above (0.53.0 is the newest published release). dev #479 /
              # public #114.
              ("0.54.0", m_0_54_0_touch_propagation.m_0_54_0_touch_propagation),
              # ⚠️⚠️ KEYED "0.56.0", AND IT WAS KEYED "0.55.0" FIRST — the ADR-009 trap caught
              # live, mid-dispatch, which is worth recording because it is the third time this
              # exact shape has bitten (see m_0_34_0_dashboard_collapse's own note).
              #
              # These two were written and verified against a tree where 0.54.0 was the newest
              # PUBLISHED release: `jobsearch--v0.54.0` tagged, plugin.json reading 0.54.0, and
              # all four reporters of dev #543-#546 running 0.54.0. "0.55.0" was correct then.
              # While the work was still on this branch, PR #557 released jobsearch 0.55.0 — and
              # 0.55.0 shipped carrying NO migration at all. So a profile that installs it is
              # stamped exactly "0.55.0", and pending_for()'s `ver(stamp) < ver(v)` is STRICT:
              # a migration keyed "0.55.0" would never fire for any of them. Both were re-keyed
              # to 0.56.0 after re-measuring (plugin.json 0.55.0, `jobsearch--v0.55.0` tagged).
              #
              # ⭐ THE LESSON, for whoever keys the next one: a migration key verified at the
              # START of a dispatch is a claim with a shelf life. Re-measure the newest
              # published release just before handing back, not only when you write the entry.
              # Re-verify these when 0.56.0 is actually cut.
              #
              # Ordered after the tree migration for the same reason every later move is: it
              # reads the post-#28 `presence/` layout m_0_32_0_tree established.
              ("0.56.0", m_0_56_0_resumes_to_presence.m_0_56_0_resumes_to_presence),
              # Same 0.56.0 keying and the same re-key history as the migration above. ORDER is
              # not load-bearing between these two — they touch disjoint paths (a root
              # resumes/ directory and a root dashboard.html file) and neither reads the
              # other's output — but the retirement runs second so every 0.56.0 root move is
              # in one declared order rather than an accidental one.
              ("0.56.0", m_0_56_0_retire_dashboard_tombstone.m_0_56_0_retire_dashboard_tombstone),
              # ⚠️ KEYED "0.57.0" — 0.56.0 is the newest PUBLISHED jobsearch release
              # (jobsearch--v0.56.0 tagged; plugin.json at HEAD reads 0.56.0, one file changed
              # after that tag per check_marketplace.py, release-manager's own known drift, not
              # a re-publish). A profile that installed 0.56.0 is stamped exactly "0.56.0", and
              # `pending_for()`'s strict `<` would never fire a migration keyed to it.
              # Re-verify when 0.57.0 is actually cut. dev #485/public #108 ask 3 — runs after
              # every 0.48.0-and-earlier migration so `m_0_48_0_probe_single_token_ack`'s own
              # dated-id acks (a disjoint bug shape, single-token names) have already landed
              # before this one reads the log; the two never touch the same id (that migration
              # matches only 3+-part dated ids, this one's own dateless ids are 2 parts).
              ("0.57.0", m_0_57_0_probe_dedup_key.m_0_57_0_probe_dedup_key),
              # ⚠️ KEYED "0.63.0" — see the note above m_0_63_0_mailbox_references. It runs LAST:
              # m_0_29_0 (an older profile's pass) is a no-op now, so no earlier migration writes
              # gmail-multi's registry, and this one only READS it.
              ("0.63.0", m_0_63_0_mailbox_references.m_0_63_0_mailbox_references),
              # ⭐ KEYED "0.66.0" -- see the note above `UID_TEXT_SUFFIX`. It runs LAST: it reads
              # messages, touches, asks, applications and briefs as the earlier migrations left them.
              ("0.66.0", m_0_66_0_uid_text.m_0_66_0_uid_text),
              # ⭐ KEYED "0.67.0" -- see the note above `SOURCING_SCREEN_PRE_COPY`. It runs LAST;
              # it touches only config.json and the one ask row.
              ("0.67.0", m_0_67_0_sourcing_screen_config_keys.m_0_67_0_sourcing_screen_config_keys),
              # ⭐ KEYED "0.69.0" -- see the note above `PASSED_BACKLOG_PRE_COPY`. It runs LAST; it
              # touches only data/opportunities.jsonl.
              ("0.69.0", m_0_69_0_passed_backlog_terminal.m_0_69_0_passed_backlog_terminal),
              # ⭐ KEYED "0.70.0" -- see the note above `LOCATION_SCREEN_PRE_COPY`. It runs LAST; it
              # touches only config.json.
              ("0.70.0", m_0_70_0_location_screen_config_keys.m_0_70_0_location_screen_config_keys),
              # KEYED "0.71.0" -- see the note above `m_0_71_0_retire_presence_artifact`. It runs LAST;
              # it touches only data/pending_stubs.jsonl and the two generated presence files.
              ("0.71.0", m_0_71_0_retire_presence_artifact.m_0_71_0_retire_presence_artifact),
              # KEYED "0.72.0" -- see the note above `ATS_FEEDS_PRE_COPY`. It runs LAST; it touches only
              # data/companies.jsonl, data/channels.jsonl and <profile>/.claude/settings.json.
              ("0.72.0", m_0_72_0_ats_feeds.m_0_72_0_ats_feeds),
              # KEYED "0.76.0" (dev #775) -- see the note above `WORKDAY_FEED_HOSTS`. It shares the version with the source
              # adoption below and runs BEFORE it; it touches only <profile>/.claude/settings.json.
              ("0.76.0", m_0_76_0_workday_hosts.m_0_76_0_workday_hosts),
              # KEYED "0.76.0" -- see the note above `ADOPTION_PRE_COPY`. It runs LAST; it stamps the hand-made rows that
              # exactly match a template the plugin once shipped, and asks about the near matches. It never turns a
              # source on or off.
              ("0.76.0", m_0_76_0_source_adoption.m_0_76_0_source_adoption),
              # KEYED "0.76.1" (dev #768-1, #764-4) -- see the note above `LEGACY_PLACEHOLDERS_PRE_COPY`. It runs LAST;
              # it touches only data/companies.jsonl, cover_letters.jsonl, applications.jsonl and (one row) asks.jsonl.
              ("0.76.1", m_0_76_1_legacy_placeholders.m_0_76_1_legacy_placeholders),
              # KEYED "0.78.0" (dev #770-4) -- see the note above `BOARD_SCHEDULE_PRE_COPY`. It runs LAST; it touches
              # only config.json (`search.postures.<name>.unattended` / `.board_days`) and one asks.jsonl row.
              ("0.78.0", m_0_78_0_board_schedule.m_0_78_0_board_schedule),
              # KEYED "0.82.0" (dev #820 / public #175) -- see the note above `ROLE_LIFECYCLE_OPPS_PRE_COPY`. It runs
              # LAST; it touches only data/opportunities.jsonl (`jd_read`) and config.json (the intake keys).
              ("0.82.0", m_0_82_0_role_lifecycle.m_0_82_0_role_lifecycle),
              # KEYED "0.83.0" (dev #825 / public #176) -- see the note above `CAPTURE_CHANNEL_PRE_COPY`. It runs LAST;
              # it touches only data/pending_actions.jsonl (an appended full row per unstamped capture item).
              ("0.83.0", m_0_83_0_capture_channel.m_0_83_0_capture_channel),
              # KEYED "0.85.0" (dev #840 / public #181) -- see the note above `READMIT_RENDER_FAILED_BY`. It runs LAST; it
              # touches only data/runs.jsonl (one appended `readmit` event) and never writes search.posting_fetch.
              ("0.85.0", m_0_85_0_readmit_render_failed.m_0_85_0_readmit_render_failed),
              # KEYED "0.86.0" (dev #834) -- see the note above `NETWORK_FIRST_BY`. It runs LAST; its first write is the pin.
              ("0.86.0", m_0_86_0_network_first.m_0_86_0_network_first),
              # KEYED "0.86.0" (dev #834) -- see `m_0_86_0_proposals`. Registered AFTER the pin: it waits for it (PENDING without it)
              # and writes one empty store file, nothing else.
              ("0.86.0", m_0_86_0_proposals.m_0_86_0_proposals),
              # KEYED "0.88.0" (dev #846, #915, #836) -- see the note above `PAY_EVIDENCE_BY`. ONE migration covers every stored-record
              # change of the release. It runs LAST; its first write is the 0.88.0 pin.
              ("0.88.0", m_0_88_0_pay_evidence.m_0_88_0_pay_evidence),
              # KEYED "0.90.0" (dev 858) -- see the note above `BROWSER_FALLBACK_BY`. It runs LAST; its first write is the pin, its
              # second the one asks.jsonl notice row (by id, only when absent). No sandbox setting is touched.
              ("0.90.0", m_0_90_0_browser_fallback.m_0_90_0_browser_fallback))


# Every value above must be a version key the MIGRATIONS registry actually knows, so a typo here
# can never claim a version this chain never shipped. Checked once at import time (loud, not a
# silent assertion buried in a test) — the same "wrong at the moment it is written" failure mode
# every KEYED "0.NN.0" comment beside MIGRATIONS itself already guards against by hand.
# The tuple as shipped, kept by reference: `assert_store_versions_known()` checks the shipped registry even when a test
# has replaced `MIGRATIONS` with a stub (the check used to run once, at import, before any test could).
_SHIPPED_MIGRATIONS = MIGRATIONS


def assert_store_versions_known():
    """Raise AssertionError when `STORE_INTRODUCED` names a version the shipped registry does not know."""
    known = frozenset(v for v, _fn in _SHIPPED_MIGRATIONS)
    unknown = {s: v for s, v in STORE_INTRODUCED.items() if v not in known}
    if unknown:
        raise AssertionError(
            "migrate.STORE_INTRODUCED names a version the MIGRATIONS registry does not know: %r "
            "— every value must be a real migration key" % (unknown,))


def pending_for(profile, engine=None):
    """The migrations this profile still needs — THE one definition, exported.

    ⭐⭐ THE GUARD MUST ASK THE REMEDY (GitHub #6). drift_guard.py used to decide there was
    drift by comparing the schema stamp against the ENGINE VERSION, which is a different
    question and has a different answer: the stamp only advances when a migration exists,
    while the version advances on every release. After 0.21.0 and 0.22.0 — neither carrying
    a migration — a correct, fully-migrated profile sat legitimately at 0.20.0, and the
    guard warned on every prompt of every session about a condition no action could clear.
    Running the remedy it named printed "profile is current" and changed nothing.

    That is the exact failure the guard exists to prevent: a warning that always fires is
    one its reader learns to dismiss, so the release that DOES carry a migration produces a
    signal indistinguishable from the noise. Worse, it sent the reader to a script whose own
    output contradicted it, with nothing saying which was wrong.

    Both now read this. They cannot disagree, because there is only one answer.
    """
    engine = engine or engine_version()
    stamp = read_stamp(profile)
    # ⭐ dev #834 -- THE PIN IS A SECOND FACT ABOUT THE SAME QUESTION, and "pin lost" is a named state (design 12.1): a
    # profile stamped at or above 0.86.0 whose journal no longer carries the 0.86.0 pin (a hand-reset or a restored
    # `runs.jsonl`) has `m_0_86_0_network_first` pending whatever the stamp says, so the next hook re-appends the pin (its
    # other steps are idempotent no-ops). A profile pinned ABOVE the engine is "pinned ahead" and never pending here.
    try:
        pin_lost = (ver(engine) >= ver(NETWORK_FIRST_PIN) and ver(stamp) >= ver(NETWORK_FIRST_PIN)
                    and _network_first_pin_needed(profile))
    except ImportError:
        pin_lost = False        # a stripped engine copy with no journal.py cannot be asked; the shipped tree always has it
    return [v for v, _fn in MIGRATIONS
            if ver(stamp) < ver(v) <= ver(engine) or (pin_lost and v == NETWORK_FIRST_PIN)]
