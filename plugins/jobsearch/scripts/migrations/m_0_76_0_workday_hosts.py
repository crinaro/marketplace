"""Migration 0.76.0: `m_0_76_0_workday_hosts()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_ats_feeds import _ats_feeds_settings_step

VERSION = "0.76.0"


# ---- 0.76.0 (dev #775; design-workday-feed.md section 7.3, ruling R1): allow the Workday host family ---------------
#
# KEYED "0.76.0", a SECOND entry beside `m_0_76_0_source_adoption` (the registry supports entries that share a version:
# `main()` runs every entry whose version is due, and `pending_for` returns each version once). It runs BEFORE the
# source adoption, which keeps its "runs LAST" note: this one touches only <profile>/.claude/settings.json.
#
# WHAT IT DOES. The Workday feed (`feed_poll.py`, vendor `workday`) makes outbound HTTPS GETs to
# `<tenant>.wd<N>.myworkdayjobs.com`: a host per tenant, so no list of exact hosts can be written. A sandboxed Bash command
# reaches a host outside `sandbox.network.allowedDomains` only by prompting, and a scheduled run must never stop for a
# prompt, so this adds the ONE family entry `*.myworkdayjobs.com` to the PROFILE PROJECT's `.claude/settings.json`,
# by the very step `m_0_72_0_ats_feeds` uses for its four exact hosts (`_ats_feeds_settings_step`): a timestamped copy
# first (`settings.json.pre-0.76.0.<timestamp>`), every other key and entry untouched, entries compared
# case-insensitively and not repeated, the file or key created only if absent, PENDING with nothing written on a file
# that exists but cannot be parsed or holds the key in a shape this does not understand, and the result RE-READ from
# disk. It NEVER writes ~/.claude/settings.json. `ATS_FEED_HOSTS` and `m_0_72_0_ats_feeds` are history and are NOT edited.
#
# ⚠️ WHAT THE ENTRY WIDENS (finding F-e, DOCUMENTED): `allowedDomains` is HOST-level, so the entry lets any sandboxed
# command in the profile project reach any path on any Workday tenant without a prompt, `/wday/cxs/` included. The
# `/wday/cxs/` ban (ADR-037's condition 5) is held by `feed_poll.py` and its test, not by the sandbox.
# ⚠️ UNVERIFIED (ruling R1): whether the sandbox honours `*.myworkdayjobs.com` for a TWO-level host
# (`<tenant>.wd<N>.myworkdayjobs.com`). The vendor's settings reference says wildcards match subdomains and is silent on
# two levels; no sandboxed session was run by the build. Named for the owner's first sandboxed session.
#
# IDEMPOTENT: a second run finds the entry present and writes nothing. ROLLBACK RISK: none beyond the setting itself;
# restoring settings.json.pre-0.76.0.<timestamp> undoes it for a file not edited since.
WORKDAY_FEED_HOSTS = ("*.myworkdayjobs.com",)
WORKDAY_HOSTS_PRE_COPY = "pre-0.76.0"


def m_0_76_0_workday_hosts(profile, apply_it):
    """0.76.0 -- allow the Workday host family for the sandbox (see the block above). Returns (done, message)."""
    return _ats_feeds_settings_step(profile, apply_it, hosts=WORKDAY_FEED_HOSTS, label="0.76.0",
                                    pre_copy=WORKDAY_HOSTS_PRE_COPY)
