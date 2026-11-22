"""Migration 0.91.0: `m_0_91_0_employment()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, frozen once released (§5.5)."""

import datetime
import email.utils
import os
import shutil
import _atomic
from migrations.support_jsonl import _read_jsonl

VERSION = "0.91.0"


# ⭐⭐ KEYED "0.91.0" (design-build-reach.md 5.4; owner O2, O3) -- 0.90.3 is the newest jobsearch release at the branch base
# (`release/jobsearch-0.91.0` was cut after 0.90.3 merged). A profile stamped "0.90.3" (or lower) fires a migration keyed "0.91.0"
# through pending_for()'s strict `<`. The version appears in the migration's name, its registry key, its test file's name and the
# group file, so a re-key is one commit by release-manager before any tag. It reads data/companies.jsonl, data/messages.jsonl and
# data/touches.jsonl and writes ONLY data/people.jsonl (one `employment` object per row it reaches).
EMPLOYMENT_PRE_COPY = "people.jsonl.pre-0.91.0"
MAIL_EVIDENCE_DAYS = 180            # owner O3: an inbound message at the company's domain within this many days is evidence of `current`
UNKNOWN_LISTED_PER_COMPANY = 8      # the query step names at most this many unknown people per target company, then counts the rest


def _store(profile, name, required=False):
    """`(rows, error)` for `data/<name>.jsonl`, read STRICTLY: one line that does not parse is an error naming the store. An absent
    store is `[]` (nothing to read is not a failure), unless `required`, when it is `(None, None)`: the honest zero of no people."""
    path = os.path.join(profile, "data", "%s.jsonl" % name)
    if not os.path.exists(path):
        return (None, None) if required else ([], None)
    try:
        return _read_jsonl(path), None
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return None, "data/%s.jsonl does not read (%s: %s)" % (name, type(e).__name__, e)


def _host_at(host, domain):
    """True when `host` is the company's `domain` or a subdomain of it (case-folded; a bare suffix match is not enough)."""
    host, domain = (host or "").strip().lower().rstrip("."), (domain or "").strip().lower().rstrip(".")
    return bool(host and domain) and (host == domain or host.endswith("." + domain))


def mail_evidence(person_id, merged_into, domain, messages, today):
    """The ISO date of the LATEST inbound message from `person_id` (a message naming an absorbed id counts for its survivor) whose
    `from` address is at `domain`, dated no later than `today` and no more than MAIL_EVIDENCE_DAYS before it, or None."""
    floor = today - datetime.timedelta(days=MAIL_EVIDENCE_DAYS)
    best = None
    for m in messages:
        if not isinstance(m, dict) or m.get("direction") != "inbound":
            continue
        pid, seen = m.get("person_id"), set()
        while pid in merged_into and pid not in seen:
            seen.add(pid)
            pid = merged_into[pid]
        if pid != person_id:
            continue
        addr = email.utils.parseaddr(str(m.get("from") or ""))[1]
        if "@" not in addr or not _host_at(addr.rsplit("@", 1)[1], domain):
            continue
        try:
            sent = datetime.date.fromisoformat(str(m.get("sent_on") or "")[:10])
        except ValueError:
            continue
        if floor <= sent <= today and (best is None or sent > best):
            best = sent
    return best.isoformat() if best else None


def plan(people, companies, messages, today):
    """`{person_id: employment}` for every non-merged row with a `company_id` and no `employment`: `current` from mail evidence,
    else `unknown`. Never `former`: no stored fact shows a departure, so `formerly` is never written."""
    domain = {c.get("id"): c.get("domain") for c in companies if isinstance(c, dict)}
    merged_into = {p.get("id"): p.get("merged_into") for p in people if p.get("merged_into")}
    out = {}
    for p in people:
        if p.get("status") == "merged" or not p.get("company_id") or "employment" in p:
            continue
        seen = mail_evidence(p.get("id"), merged_into, domain.get(p["company_id"]), messages, today)
        out[p["id"]] = ({"status": "current", "as_of": seen, "confirmed_on": None, "source": "observed-mail"} if seen else
                        {"status": "unknown", "as_of": None, "confirmed_on": None, "source": "migration"})
    return out


def m_0_91_0_employment(profile, apply_it, today=None):
    """0.91.0 -- every person with an employer of record gets a dated standing (design-build-reach.md 5.4; owner O2, O3).

    Until 0.91.0 a people row's `company_id` was the only fact about where a person works, so every "at the company" reader counted a
    former employee as a way in. 0.91.0 adds `employment {status, as_of, confirmed_on, source}`, and the readers count `current` only.

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY.
      1. Read `data/people.jsonl`, `companies.jsonl` and `messages.jsonl` STRICTLY. One line of any of them that does not parse is
         PENDING naming the store, with NOTHING written (the copy included): a standing guessed from a store this could not fully
         read is a guess. An absent people store is an honest zero (done, silent); an absent companies or messages store reads empty.
      2. Copy `people.jsonl` byte for byte to `people.jsonl.pre-0.91.0`, never over a copy already there (the true original from
         an earlier partial run); a failed copy writes nothing.
      3. Per non-merged row with a `company_id` and no `employment`: `current`, `source: observed-mail`, `as_of` the date of the
         latest INBOUND message from this person whose `from` address is at the company's `domain` (exact host or a subdomain)
         within MAIL_EVIDENCE_DAYS of today (owner O3); otherwise `unknown`, `source: migration`, `as_of: null`. NEVER guessed
         current, and nothing is written to `formerly`: no stored fact shows a departure.
      4. Re-read: every row planned carries its `employment`, and no row's `formerly` changed. A shortfall is PENDING with the copy
         kept. Then the counts, and the unknown people at `active-target` companies by company, each with a hint when a touch to
         them `bounced` (a hint only: it moves nothing).

    Until this has run, the readers treat a row with a `company_id` and no `employment` as `unknown`, so an unmigrated profile
    under-counts and says so; it never over-counts. IDEMPOTENT: a row that already carries `employment` (the verbs', or an earlier
    run's) is never touched, so a second run finds nothing and writes nothing. `today` is a test seam (default: the real date).

    ⚠️ ROLLBACK RISK. Downgrading to 0.90.x leaves the `employment` objects in place; 0.90.x ignores them (its validator does not
    check unknown people keys). Restoring `people.jsonl.pre-0.91.0` undoes this only for rows not written since. Returns
    `(done, message)`."""
    today = today or datetime.date.today()
    pending = "  ⏳ 0.91.0 PENDING -- %s. Nothing was written. This runs again next session."
    people, err = _store(profile, "people", required=True)
    if err:
        return False, pending % err
    if people is None:
        return True, ""
    companies, err = _store(profile, "companies")
    if err:
        return False, pending % err
    messages, err = _store(profile, "messages")
    if err:
        return False, pending % err
    todo = plan(people, companies, messages, today)
    if not todo:
        return True, ""
    by_kind = _counts(todo)
    if not apply_it:
        return True, ("  would state the employment of %d people: current by mail evidence %d · unknown %d (never guessed current)"
                      % (len(todo), by_kind["current"], by_kind["unknown"]))
    data = os.path.join(profile, "data")
    copy_path = os.path.join(data, EMPLOYMENT_PRE_COPY)
    if not os.path.exists(copy_path):
        try:
            shutil.copy2(os.path.join(data, "people.jsonl"), copy_path)
        except (OSError, shutil.Error) as e:
            return False, ("  ⚠️ people.jsonl could not be preserved to %s (%s), so NOTHING was changed." % (EMPLOYMENT_PRE_COPY, e))
    formerly_before = {p.get("id"): p.get("formerly") for p in people}
    for p in people:
        if p.get("id") in todo:
            p["employment"] = todo[p["id"]]
    _atomic.write_jsonl(os.path.join(data, "people.jsonl"), people)
    after, err = _store(profile, "people", required=True)
    by_id = {p.get("id"): p for p in (after or [])}
    short = sorted(pid for pid in todo if by_id.get(pid, {}).get("employment") != todo[pid])
    moved = sorted(pid for pid, f in formerly_before.items() if by_id.get(pid, {}).get("formerly") != f)
    if err or after is None or short or moved:
        return False, ("  ⏳ 0.91.0 PENDING -- the success condition did not hold after the write (%s); the original is kept at "
                       "data/%s. Offered again next session." % (err or "rows short: %s; formerly changed: %s"
                                                                  % (", ".join(short) or "none", ", ".join(moved) or "none"),
                                                                  EMPLOYMENT_PRE_COPY))
    return True, "\n".join(["  ✅ people (0.91.0) -- stated the employment of %d people: current by mail evidence %d · unknown %d "
                            "(the original is kept at data/%s)" % (len(todo), by_kind["current"], by_kind["unknown"],
                                                                   EMPLOYMENT_PRE_COPY)]
                           + _unknown_at_targets(profile, people, companies, todo))


def _counts(todo):
    out = {"current": 0, "unknown": 0}
    for e in todo.values():
        out[e["status"]] += 1
    return out


def _unknown_at_targets(profile, people, companies, todo):
    """The query step's lines: the unknown people at `active-target` companies, by company, with a bounce hint where one exists.
    Touches that do not read give no hints, and say so (a hint is never a reason to stop)."""
    targets = {c.get("id"): c.get("name") or c.get("id") for c in companies
               if isinstance(c, dict) and c.get("status") == "active-target"}
    touches, err = _store(profile, "touches")
    bounced = {t.get("person_id") for t in (touches or []) if isinstance(t, dict) and t.get("delivery") == "bounced"}
    names = {p.get("id"): p.get("name") or p.get("id") for p in people}
    by_company = {}
    for p in people:
        if todo.get(p.get("id"), {}).get("status") == "unknown" and p.get("company_id") in targets:
            by_company.setdefault(p["company_id"], []).append(p["id"])
    lines = []
    for cid in sorted(by_company):
        ids = by_company[cid]
        shown = ["%s%s" % (names[i], " (a touch to them bounced: they may have left)" if i in bounced else "")
                 for i in ids[:UNKNOWN_LISTED_PER_COMPANY]]
        more = " and %d more" % (len(ids) - UNKNOWN_LISTED_PER_COMPANY) if len(ids) > UNKNOWN_LISTED_PER_COMPANY else ""
        lines.append("     still at %s? %s%s -- `record.py employment <person_id> current|former`" % (targets[cid], " · ".join(shown), more))
    if lines and err:
        lines.append("     (data/touches.jsonl does not read, so no bounce hints: %s)" % err)
    if lines:
        lines.insert(0, "     EMPLOYMENT UNCONFIRMED at your targets: not counted until you say whether they still work there")
    return lines
