"""The sandbox-settings step that allows company-feed hosts, shared by 0.72.0, 0.76.0 and `posting_fetch.py`.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import json
import os
import shutil


# ⭐⭐ KEYED "0.72.0" (dev #751, sourcing-feeds; the release/jobsearch-0.72.0 group). 0.71.0 is the
# newest release at the branch base, so a profile that installed it is stamped exactly "0.71.0" and
# pending_for()'s strict `<` fires a migration keyed to "0.72.0". It runs LAST: it touches only
# data/companies.jsonl, data/channels.jsonl (when it finds a feed) and <profile>/.claude/settings.json.
#
# TWO INDEPENDENT HALVES, each preserve-then-transform, each PENDING when it cannot know:
#
#   1. SLUGS. For each tracked company with NO `ats` key (a present `null` -- the candidate declined a
#      feed -- or an object is NEVER touched), parse the company's own URLs (`ats_slug.discover`: its
#      `career_url`, its opportunities' `jd_url` and sighting `source_url`s; a string parse, never a
#      fetch) and, for ONE unambiguous board, write `companies[].ats` and link or create the company's
#      career-page channel (`ats_slug.apply_discovery`, the SAME function `record.py ats --discover`
#      runs). Two distinct boards write nothing and print `ATS AMBIGUOUS`. A company the candidate
#      passed on (`status: passed`) is not tracked, so it is not fed. Before the first write
#      `companies.jsonl` and `channels.jsonl` are copied byte for byte to `*.pre-0.72.0` (never over a
#      copy already there: that is the true original of an earlier partial run). The success condition
#      is RE-READ from disk -- every written `ats` passes `ats_slug.check_ats` and
#      `validate_data.check_feed_links` holds -- and a shortfall RESTORES the originals and is PENDING.
#      A store that cannot be read strictly (one line that does not parse) is PENDING, never "0 done".
#
#   2. THE FOUR FEED HOSTS (owner decision R1, 2026-10-21). The poller makes outbound HTTPS GETs to
#      boards-api.greenhouse.io, api.lever.co, api.eu.lever.co and api.ashbyhq.com. A sandboxed Bash
#      command reaches a host outside `sandbox.network.allowedDomains` only by prompting, and a scheduled
#      run must never stop for a prompt, so this adds exactly those four to the PROFILE PROJECT's
#      `.claude/settings.json` -> `sandbox.network.allowedDomains` (a list of host strings; read from
#      https://code.claude.com/docs/en/sandboxing, which also says the sandbox ignores that key in a
#      repository file when an ADMIN requires the sandbox; the setting is then the admin's to make).
#      A timestamped copy of an existing settings file is made FIRST; every other key and entry is left
#      untouched; entries already there (compared case-insensitively) are not repeated; the file or the
#      key is created only if absent; and a file that EXISTS but cannot be parsed, or holds the key in a
#      shape this does not understand, is PENDING with nothing written. It NEVER writes
#      ~/.claude/settings.json, the user's global settings, or any other setting. The release note names
#      the four hosts and why. S2 (a scheduled run under the sandbox) stays UNVERIFIED until one run is
#      observed polling with the sandbox on.
#
# IDEMPOTENT: a second run finds every company keyed or without a source and every host present, and
# writes nothing. HONEST ZERO: an absent store has no companies to discover and is DONE.
#
# ⚠️ ROLLBACK RISK. Downgrading to 0.71.0 after this runs leaves `ats` and `company_id` on rows an older
# validator does not know (it reports an unknown field, it does not lose data); restoring
# companies.jsonl.pre-0.72.0 / channels.jsonl.pre-0.72.0 undoes the slugs only for rows not written since.
ATS_FEEDS_PRE_COPY = "pre-0.72.0"
ATS_FEED_HOSTS = ("boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com")


def _ats_feeds_settings_step(profile, apply_it, hosts=None, label="0.72.0", pre_copy=None):
    """`(ok, line)` for the allow-list half. `ok` is False ONLY when it could not know or could not
    write (PENDING); an already-complete list is ok with an empty line.

    `hosts`, `label` and `pre_copy` default to the 0.72.0 values (`ATS_FEED_HOSTS`, "0.72.0",
    `ATS_FEEDS_PRE_COPY`), so the 0.72.0 path is byte for byte what it was; dev #775 passes the Workday family and
    "0.76.0" to reuse every rule here (the timestamped copy first, only the profile project's file, neighbours
    untouched, casefold de-duplication, pending with nothing written on a file or key it cannot read, verified
    from disk) instead of writing a second step."""
    import datetime
    hosts = ATS_FEED_HOSTS if hosts is None else hosts
    pre_copy = ATS_FEEDS_PRE_COPY if pre_copy is None else pre_copy
    count_word = "the host" if len(hosts) == 1 else "%s hosts" % ({4: "four"}.get(len(hosts)) or len(hosts))
    path = os.path.join(profile, ".claude", "settings.json")
    pending = "  ⏳ " + label + " PENDING -- %s. Nothing was written to .claude/settings.json."
    data, existed = {}, os.path.exists(path)
    if existed:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            return False, pending % ("%s cannot be parsed (%s); fix it and this runs again next "
                                     "session" % (os.path.relpath(path, profile), exc))
        if not isinstance(data, dict):
            return False, pending % ".claude/settings.json is not a JSON object"
    sandbox = data.get("sandbox", {})
    network = sandbox.get("network", {}) if isinstance(sandbox, dict) else None
    allowed = network.get("allowedDomains", []) if isinstance(network, dict) else None
    if (not isinstance(sandbox, dict) or not isinstance(network, dict)
            or not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed)):
        return False, pending % ("sandbox.network.allowedDomains is present in a shape this does not "
                                 "understand (expected a list of host strings)")
    have = {x.strip().casefold() for x in allowed}
    missing = [h for h in hosts if h.casefold() not in have]
    if not missing:
        return True, ""
    if not apply_it:
        return True, ("  would allow the %d feed host(s) in .claude/settings.json "
                      "sandbox.network.allowedDomains: %s" % (len(missing), ", ".join(missing)))
    copy_rel = None
    if existed:
        copy_rel = os.path.join(".claude", "settings.json.%s.%s" % (
            pre_copy, datetime.datetime.now().strftime("%Y%m%dT%H%M%S")))
        try:
            shutil.copy2(path, os.path.join(profile, copy_rel))
        except (OSError, shutil.Error) as exc:
            return False, pending % ("the original could not be preserved to %s (%s)" % (copy_rel, exc))
    new = json.loads(json.dumps(data))
    new.setdefault("sandbox", {}).setdefault("network", {}).setdefault("allowedDomains", [])
    new["sandbox"]["network"]["allowedDomains"] = list(allowed) + missing
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(new, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
        with open(path, encoding="utf-8") as fh:
            after = json.load(fh)
    except (OSError, ValueError) as exc:
        if copy_rel:
            try:
                shutil.copy2(os.path.join(profile, copy_rel), path)
            except (OSError, shutil.Error):
                pass
        return False, pending % ("the write could not be verified (%s)%s" % (
            exc, "; the original is restored from " + copy_rel if copy_rel else ""))
    got = after.get("sandbox", {}).get("network", {}).get("allowedDomains", [])
    got_cf = {x.strip().casefold() for x in got if isinstance(x, str)}
    if after != new or not all(h.casefold() in got_cf for h in hosts):
        if copy_rel:
            try:
                shutil.copy2(os.path.join(profile, copy_rel), path)
            except (OSError, shutil.Error):
                pass
        return False, pending % ("the re-read did not show exactly %s added; original restored" % count_word)
    return True, ("  ✅ .claude/settings.json (" + label + ") -- allowed the %d company-feed host(s) %s in "
                  "sandbox.network.allowedDomains%s (nothing else in the file was changed)"
                  % (len(missing), ", ".join(missing),
                     (" (the original is kept at %s)" % copy_rel) if copy_rel else ""))
