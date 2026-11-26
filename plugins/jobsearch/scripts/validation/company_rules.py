"""Company-row field checks and the commute configuration check.

Capability module of `validate_data.py` (S4a, moved unedited)."""

import datetime
from validation.pay import COMPANY_KINDS, _is_number, _unknown_keys
from validation.vocab import DATE_RE, MOTIVATION_MAX, MOTIVATION_MIN


def check_company_fields(c, label, problems):
    """The four optional company fields `data_model.json` has declared since jobsearch 0.73.0
    (dev #757), typed as `schema.md` documents them. The data model carries no types for any store,
    so the types are enforced HERE:

      career_url      absent, null, or a non-empty string (`ats_slug.discover` reads it)
      domain          absent, null, or a non-empty string
      aliases         absent, or a list of non-empty strings. A bare STRING is refused: `ats_slug`
                      iterates it, and a string iterates character by character
      size_ownership  absent, or a non-empty string

    A refusal names the `record.py set` command that writes the field in the right shape."""
    cid = c.get("id", "?")
    for f in ("career_url", "domain"):
        if f in c and c[f] is not None and not (isinstance(c[f], str) and c[f].strip()):
            problems.append("%s: %s must be a non-empty string or null -- %r (fix: record.py set %s %s "
                            "<value> --file companies)" % (label, f, c[f], cid, f))
    if "aliases" in c:
        al = c["aliases"]
        if not (isinstance(al, list) and all(isinstance(a, str) and a.strip() for a in al)):
            problems.append("%s: aliases must be a list of non-empty strings, e.g. [\"Example "
                            "Holdings\"] -- %r (fix: record.py set %s aliases '[\"<name>\"]' "
                            "--file companies)" % (label, al, cid))
    if "size_ownership" in c:
        so = c["size_ownership"]
        if not (isinstance(so, str) and so.strip()):
            problems.append("%s: size_ownership must be a non-empty string -- %r (fix: record.py set "
                            "%s size_ownership \"<text>\" --file companies)" % (label, so, cid))
    # dev #834 (jobsearch 0.86.0, design-network-first.md 4.1, 13.1): `active-target` is LIST MEMBERSHIP, so the company carries
    # the date the candidate decided it (`status_on`) and, for a target, how much they want to work there (`motivation`, 1..5, LAMP's
    # M). Both are the candidate's own statements, written together with `status` by `record.py company-status`. `motivation` is an
    # int 1..5 or null; a bool is not an int here, and a string "3" is refused rather than read as 3.
    if "status_on" in c and not (isinstance(c["status_on"], str) and DATE_RE.match(c["status_on"])):
        problems.append("%s: status_on must be an ISO date (YYYY-MM-DD) -- %r (it is written only by `record.py company-status`)"
                        % (label, c["status_on"]))
    if "motivation" in c and c["motivation"] is not None:
        mv = c["motivation"]
        if not (isinstance(mv, int) and not isinstance(mv, bool) and MOTIVATION_MIN <= mv <= MOTIVATION_MAX):
            problems.append("%s: motivation must be an integer %d..%d or null -- %r (the candidate's own stated hunger to work "
                            "there; written by `record.py company-status %s active-target --motivation <%d-%d>`)"
                            % (label, MOTIVATION_MIN, MOTIVATION_MAX, mv, cid, MOTIVATION_MIN, MOTIVATION_MAX))
    # dev #834 (jobsearch 0.86.0, design-network-first.md 3.3, 13.1): `raised_on`, the date the company was first raised as a
    # "look into this company?" item. Absent means never raised. When present it is an ISO date NOT AFTER today: a future date
    # would hide the company from the raise for as long as it lasts. The one writer is `record.py raise-companies`.
    if "raised_on" in c:
        ro = c["raised_on"]
        if not (isinstance(ro, str) and DATE_RE.match(ro)):
            problems.append("%s: raised_on must be an ISO date (YYYY-MM-DD) -- %r (it is written only by "
                            "`record.py raise-companies`)" % (label, ro))
        elif ro > datetime.date.today().isoformat():
            problems.append("%s: raised_on %s is after today: a company is raised on the day a run raised it (it is "
                            "written only by `record.py raise-companies`)" % (label, ro))
    # dev #915 (jobsearch 0.88.0, design-jobsearch-0.88.0.md 6.3, 6.4): `kind`, what the candidate says a company IS, and
    # `later_on`, the day they asked to hear about it later (a derived snooze on the Targets-to-review list, never a status).
    # Both are optional and absent has a defined meaning; a PRESENT one must be well formed. Their writers are `record.py
    # company-kind` and `record.py company-later`.
    if "kind" in c and c["kind"] not in COMPANY_KINDS:
        problems.append("%s: kind must be one of %s -- %r (written by `record.py company-kind %s <kind>`)"
                        % (label, ", ".join(COMPANY_KINDS), c["kind"], cid))
    if "later_on" in c:
        lo = c["later_on"]
        if not (isinstance(lo, str) and DATE_RE.match(lo)):
            problems.append("%s: later_on must be an ISO date (YYYY-MM-DD) -- %r (it is written only by `record.py "
                            "company-later %s`)" % (label, lo, cid))
        elif lo > datetime.date.today().isoformat():
            problems.append("%s: later_on %s is after today: \"later\" is the day the candidate said it (written only by "
                            "`record.py company-later %s`)" % (label, lo, cid))
    # jobsearch 0.94.0 (dev 1062, design-role-first.md 4.4): `target_from`, `{opp, on}`, says an `active-target` came from the candidate's pursue
    # of the role `opp` on `on` (a target stated with `company-status` has none, and stating one deletes it). Optional; a PRESENT one is checked
    # for SHAPE only (the status it sits beside is `lifecycle`'s to read), `on` an ISO date not after today. Written only by `record.py decide ... pursue`.
    if "target_from" in c:
        tf = c["target_from"]
        if not (isinstance(tf, dict) and set(tf) == {"opp", "on"} and isinstance(tf["opp"], str) and tf["opp"].strip()
                and not any(ch.isspace() for ch in tf["opp"]) and isinstance(tf["on"], str) and DATE_RE.match(tf["on"])):
            problems.append("%s: target_from must be {opp: <an opportunity id>, on: <ISO date>} -- %r (written only by `record.py decide <opp> pursue`)"
                            % (label, tf))
        elif tf["on"] > datetime.date.today().isoformat():
            problems.append("%s: target_from.on %s is after today: a company is targeted on the day the role was pursued" % (label, tf["on"]))


def check_commute_config(geography, problems):
    """The commute tables of `config.json` `geography` (design §3.8, §9): each anchor's optional
    `bands` -- `[{max_minutes, floor}]`, strictly ascending, the last no greater than the anchor's
    own `max_commute_minutes` -- and any `includes[]` entry that is an object (`{place,
    minutes}`). Appends to `problems`; returns the number of bands checked."""
    n = 0
    anchors = (geography or {}).get("commute_anchors") if isinstance(geography, dict) else None
    if not isinstance(anchors, list):
        return 0
    for ai, anchor in enumerate(anchors):
        al = "config geography.commute_anchors[%d]" % ai
        if not isinstance(anchor, dict):
            continue
        for ii, inc in enumerate(anchor.get("includes") or []):
            if isinstance(inc, str):
                continue
            il = "%s.includes[%d]" % (al, ii)
            if not isinstance(inc, dict):
                problems.append("%s: an includes entry is a place string or {place, minutes}" % il)
                continue
            _unknown_keys(inc, ("place", "minutes"), il, problems)
            if not (isinstance(inc.get("place"), str) and inc["place"].strip()):
                problems.append("%s: place must be a non-empty string" % il)
            m = inc.get("minutes")
            if not (isinstance(m, int) and not isinstance(m, bool) and m >= 0):
                problems.append("%s: minutes must be a whole number >= 0 -- %r" % (il, m))
        if "bands" not in anchor:
            continue
        bands = anchor["bands"]
        if not isinstance(bands, list) or not bands:
            problems.append("%s.bands must be a non-empty list of {max_minutes, floor}" % al)
            continue
        prev, cap = None, anchor.get("max_commute_minutes")
        for bi, b in enumerate(bands):
            bl = "%s.bands[%d]" % (al, bi)
            if not isinstance(b, dict):
                problems.append("%s: must be an object {max_minutes, floor}" % bl)
                continue
            _unknown_keys(b, ("max_minutes", "floor"), bl, problems)
            mm, fl = b.get("max_minutes"), b.get("floor")
            n += 1
            if not (isinstance(mm, int) and not isinstance(mm, bool) and mm > 0):
                problems.append("%s: max_minutes must be a whole number > 0 -- %r" % (bl, mm))
                continue
            if not (_is_number(fl) and fl > 0):
                problems.append("%s: floor must be a positive number -- %r" % (bl, fl))
            if prev is not None and mm <= prev:
                problems.append("%s: max_minutes %d is not above the previous band's %d -- bands "
                                "run strictly ascending" % (bl, mm, prev))
            prev = mm
        if prev is not None and isinstance(cap, int) and not isinstance(cap, bool) and prev > cap:
            problems.append("%s.bands: the last band reaches %d minutes but the anchor's "
                            "max_commute_minutes is %d -- a band cannot price a commute the "
                            "anchor says is out of radius" % (al, prev, cap))
    return n
