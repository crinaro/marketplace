#!/usr/bin/env python3
"""Which company-feed board does this URL name? A string parse of the candidate's OWN URLs,
never a fetch (dev #751; design-sourcing-feeds.md §3.2).

⭐ WHAT THIS IS FOR. `companies[].ats = {vendor, slug, region, source, since}` says "poll this
company's public job-board feed" (`feed_poll.py`). The slug is read OFF a URL the candidate or the
research step already attached to that company -- `career_url`, an opportunity's `jd_url`, a
sighting's `source_url` -- so the company is never inferred. A receipt email's sender domain never
identifies the employer (ADR-030), so no mail path exists here; the design names it as a follow-on
(§9) only if this misses companies in practice.

⭐ A CLOSED SET. Only the forms below parse. Everything else -- an unknown host, a path that is not a
slug, a Workday host or site of a shape not listed -- is `None`, so every unslugged company stays on
the browser route (criterion A5). A slug is `SLUG_RE`: letters, digits, `.`, `_`, `-`, so it can never
carry a path separator, a query or a percent escape into the URL `feed_poll.py` builds from it.

⭐ WORKDAY (dev #775, jobsearch 0.76.0; design-workday-feed.md section 3). A Workday career site is named
by THREE parts the candidate's own URL carries -- tenant, `wd<N>` and site -- and none is ever guessed:

    <tenant>.wd<N>.myworkdayjobs.com[/<ll-CC>]/<site>[/...]   workday, <tenant>.wd<N>/<site>   (key below)

The host must be exactly two labels plus `.myworkdayjobs.com` (an apex, a one-label host and a host with
three or more labels are `None`; so is `myworkdaysite.com`, whose path form is unverified). A first
path segment shaped `ll-CC` that is FOLLOWED by another segment is a locale and is stripped (it is not
stored; `workday_locale` reads it for the poller's locale rule). The site keeps its CASE (robots.txt path
matching is case-sensitive), is never `wday` (the `/wday/cxs/` JSON endpoint is banned by ADR-037), and a
URL with no site segment is `None`. `parse` returns the display key `<tenant>.<wd>/<site>` where the
other vendors return a slug; it is never stored as a slug: a Workday `ats` object carries
`tenant`, `wd` and `site` (`ats_object` builds every vendor's stored object, `check_ats` refuses a
malformed one). Nothing here fetches.

    jobs.lever.co/{site}[/...]                  lever, {site}, global      DOCUMENTED (lever/postings-api)
    jobs.eu.lever.co/{site}[/...]               lever, {site}, eu          DOCUMENTED
    jobs.ashbyhq.com/{name}[/...]               ashby, {name}              DOCUMENTED (Ashby posting API)
    boards.greenhouse.io/{token}[/...]          greenhouse, {token}        UNDETERMINED (design U2)
    job-boards.greenhouse.io/{token}[/...]      greenhouse, {token}        UNDETERMINED (design U2)
    boards.greenhouse.io/embed/job_board?for=T  greenhouse, T -- PARSED, NEVER FETCHED (its robots
                                                 file disallows /embed/; the slug is all we take)

Host and first path segment compare case-insensitively; the slug keeps the spelling it had.

Python 3.9+. Standard library only.
"""

import collections
import datetime
import re
import urllib.parse

VENDORS = ("greenhouse", "lever", "ashby", "workday")
REGIONS = ("global", "eu")
SOURCES = ("career-url", "posting-url", "candidate")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
# dev #775 -- the three Workday parts (design section 3.1). The site keeps its case.
WD_TENANT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
WD_RE = re.compile(r"^wd[1-9][0-9]{0,2}$")
WD_SITE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
WD_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
WD_SUFFIX = ".myworkdayjobs.com"

# host -> (vendor, region)
_HOSTS = {
    "jobs.lever.co": ("lever", "global"),
    "jobs.eu.lever.co": ("lever", "eu"),
    "jobs.ashbyhq.com": ("ashby", None),
    "boards.greenhouse.io": ("greenhouse", None),
    "job-boards.greenhouse.io": ("greenhouse", None),
}
_GREENHOUSE_EMBED = ("job_board", "job_app")


def _workday_parts(url):
    """`(tenant, wd, site, locale)` for a URL on the Workday family's closed forms (module docstring),
    else None. `locale` is the stripped `ll-CC` segment or None. A string parse; never a fetch."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host.endswith(WD_SUFFIX):
        return None
    if port not in (None, 443):
        return None
    labels = host[:-len(WD_SUFFIX)].split(".")
    if len(labels) != 2:                      # exactly <tenant>.<wdN>: no apex, one-label or deeper host
        return None
    tenant, wd = labels
    if not (WD_TENANT_RE.match(tenant) and WD_RE.match(wd)):
        return None
    segs = [s for s in parts.path.split("/") if s]
    locale = None
    if len(segs) >= 2 and WD_LOCALE_RE.match(segs[0]):
        locale, segs = segs[0], segs[1:]
    if not segs:
        return None
    site = segs[0]
    if not WD_SITE_RE.match(site) or site.casefold() == "wday" or WD_LOCALE_RE.match(site):
        return None
    return tenant, wd, site, locale


def workday_locale(url):
    """The `ll-CC` locale segment a Workday URL carries (`en-US`), or None (no locale, or not a Workday
    form). The poller's locale rule (R2) compares its language with the pages' `inLanguage`."""
    p = _workday_parts(url)
    return p[3] if p else None


def workday_locale_for(company, opportunities, ats):
    """The `ll-CC` locale the candidate's own URLs carry for THIS stored Workday board (the company's `career_url`
    first, then its postings' URLs), or None. Only a URL that parses to the same tenant, wdN and site (site
    compared case-insensitively) counts, so another tenant's URL never decides it. A string parse; no fetch."""
    want = str(board_key(ats) or "").lower()
    for url, _origin in candidate_urls(company, opportunities):
        p = _workday_parts(url)
        if p and p[3] and ("%s.%s/%s" % p[:3]).lower() == want:
            return p[3]
    return None


def split_workday_key(key):
    """`(tenant, wd, site)` from a display key `<tenant>.<wd>/<site>`, else None."""
    if not isinstance(key, str) or "/" not in key:
        return None
    host, _slash, site = key.partition("/")
    tw = host.split(".")
    if len(tw) != 2 or not (WD_TENANT_RE.match(tw[0]) and WD_RE.match(tw[1]) and WD_SITE_RE.match(site)):
        return None
    return tw[0], tw[1], site


def board_key(ats):
    """The display key of a stored `ats` object: the slug for the other vendors, `<tenant>.<wd>/<site>` for
    Workday. Printed in `FEED NOT COVERED` lines and used to key the feed cache; never an address."""
    if not isinstance(ats, dict):
        return None
    if ats.get("vendor") == "workday":
        return "%s.%s/%s" % (ats.get("tenant"), ats.get("wd"), ats.get("site"))
    return ats.get("slug")


def parse(url):
    """`(vendor, slug, region)` for a URL naming one of the closed set's boards, else None.
    `region` is `global`/`eu` for Lever and None for the other vendors. For Workday the second member
    is the display key `<tenant>.<wd>/<site>` (module docstring). Never raises on a
    non-string or a malformed URL: those are None, because "not a board URL" is the answer."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    try:
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if host.endswith(WD_SUFFIX):
        w = _workday_parts(url)
        return ("workday", "%s.%s/%s" % w[:3], None) if w else None
    hit = _HOSTS.get(host)
    if hit is None:
        return None
    vendor, region = hit
    segs = [s for s in parts.path.split("/") if s]
    if not segs:
        return None
    first = segs[0]
    if vendor == "greenhouse" and first.lower() == "embed":
        # the embedded board: the token is the `for=` query value, and only a documented embed
        # path counts. PARSED, never fetched (A9).
        if len(segs) < 2 or segs[1].lower() not in _GREENHOUSE_EMBED:
            return None
        qs = urllib.parse.parse_qs(parts.query)
        vals = qs.get("for") or []
        token = vals[0] if len(vals) == 1 else None
        return (vendor, token, None) if token and SLUG_RE.match(token) else None
    return (vendor, first, region) if SLUG_RE.match(first) else None


Discovery = collections.namedtuple("Discovery", "found source ambiguous")


def candidate_urls(company, opportunities):
    """`[(url, origin)]` -- the company's own `career_url`, then the `jd_url` and every sighting
    `source_url` of each opportunity whose `company_id` is this company. `origin` is `career-url`
    or `posting-url`."""
    out = []
    cu = (company or {}).get("career_url")
    if isinstance(cu, str) and cu.strip():
        out.append((cu, "career-url"))
    cid = (company or {}).get("id")
    for o in opportunities or []:
        if not cid or o.get("company_id") != cid:
            continue
        if isinstance(o.get("jd_url"), str):
            out.append((o["jd_url"], "posting-url"))
        for s in o.get("sightings") or []:
            if isinstance(s, dict) and isinstance(s.get("source_url"), str):
                out.append((s["source_url"], "posting-url"))
    return out


def discover(company, opportunities):
    """`Discovery(found, source, ambiguous)` for one company.

      found      the single distinct `(vendor, slug, region)` its URLs name, else None
      source     `career-url` when `career_url` produced it, else `posting-url`; None if not found
      ambiguous  the list of distinct triples when there are TWO OR MORE (found is then None and
                 NOTHING may be written -- an acquisition, or a recruiter's own board attached to
                 the wrong company; the candidate settles it with `record.py ats`), else []

    Distinct is judged case-insensitively on the slug (a host is case-insensitive and the same
    board must not read as two). Pure: it reads what it is handed and fetches nothing."""
    seen = collections.OrderedDict()
    for url, origin in candidate_urls(company, opportunities):
        p = parse(url)
        if p is None:
            continue
        key = (p[0], p[1].lower(), p[2])
        entry = seen.setdefault(key, {"triple": p, "origins": set()})
        entry["origins"].add(origin)
    if not seen:
        return Discovery(None, None, [])
    if len(seen) > 1:
        return Discovery(None, None, [e["triple"] for e in seen.values()])
    e = next(iter(seen.values()))
    return Discovery(e["triple"], "career-url" if "career-url" in e["origins"] else "posting-url",
                     [])


def ats_object(triple, source, since=None):
    """The ONE builder of a stored `companies[].ats` object, for every vendor (dev #775: `record.py`,
    discovery and the migrations hold no per-vendor shape of their own). `region` is stored for Lever
    only; Workday stores `tenant`, `wd` and `site` (parsed back out of the display key) and no `slug`."""
    vendor, slug, region = triple
    if vendor == "workday":
        parts = split_workday_key(slug)
        if parts is None:
            raise ValueError("%r is not a Workday display key <tenant>.<wd>/<site>" % (slug,))
        ats = {"vendor": "workday", "tenant": parts[0], "wd": parts[1], "site": parts[2]}
    else:
        ats = {"vendor": vendor, "slug": slug}
        if vendor == "lever":
            ats["region"] = region or "global"
    ats["source"] = source
    ats["since"] = since or datetime.date.today().isoformat()
    return ats


make_ats = ats_object            # the name 0.72.0 callers used; one function, two names


def career_channel_id(company_id):
    """ADR-002's naming for a company's career-page channel."""
    return "company:%s" % company_id


def link_channel(company, channels):
    """Make sure `company` has exactly one linked `company-site` channel in `channels` (a list of
    dicts, MUTATED in place), and say how. Returns `(channel_id, how)`, `how` one of

      exists    a company-site channel with `company_id` == this company is already there
      linked    set `company_id` on the channel whose `id` is `company:<company_id>`, else on
                EXACTLY ONE `company-site` channel whose `label` equals the company's `name` or an
                alias, case-insensitively (more than one such is ambiguous: none is guessed at)
      created   a new channel `{id: company:<id>, label: <name>, type: company-site, access: public,
                review_cadence: monthly, company_id, last_reviewed: null, scope_notes}`

    `monthly` matches the anchor-employer career-page cadence; it governs only the browser fallback,
    because the feed runs every day. A KNOWN RISK, named (design §3.2): an unlinked career-page
    channel with a different label survives beside a created one, so both are reviewed -- duplicate
    work, never a loss; the resolver still de-duplicates the roles, and `feed_poll.py --status` lists
    the unlinked company-site channels."""
    cid = company.get("id")
    for ch in channels:
        if ch.get("type") == "company-site" and ch.get("company_id") == cid:
            return ch.get("id"), "exists"
    want_id = career_channel_id(cid)
    for ch in channels:
        if ch.get("id") == want_id and ch.get("type") == "company-site" \
                and ch.get("company_id") in (None, cid):
            ch["company_id"] = cid
            return ch.get("id"), "linked"
    names = {str(company.get("name") or "").strip().casefold()}
    names |= {str(a).strip().casefold() for a in (company.get("aliases") or [])}
    names.discard("")
    labelled = [ch for ch in channels if ch.get("type") == "company-site"
                and not ch.get("company_id")
                and str(ch.get("label") or "").strip().casefold() in names]
    if len(labelled) == 1:
        labelled[0]["company_id"] = cid
        return labelled[0].get("id"), "linked"
    used = {ch.get("id") for ch in channels}
    new_id = want_id
    n = 2
    while new_id in used:                     # an id taken by something that is not this company's
        new_id = "%s-%d" % (want_id, n)
        n += 1
    channels.append({"id": new_id, "label": company.get("name") or cid, "type": "company-site",
                     "access": "public", "review_cadence": "monthly", "company_id": cid,
                     "last_reviewed": None,
                     "scope_notes": "career page; reached by its ATS feed"})
    return new_id, "created"


def apply_discovery(company, channels, triple, source, since=None):
    """Write `ats` on `company` (mutated) and link or create its channel (`channels` mutated).
    Returns `(channel_id, how)` from `link_channel`. The caller owns persistence, the lock and the
    rollback; this is the ONE definition of what a discovery changes, shared by `record.py ats`
    and migration `m_0_72_0_ats_feeds`."""
    company["ats"] = ats_object(triple, source, since)
    return link_channel(company, channels)


def check_ats(ats, label="ats"):
    """The problems with a stored `ats` value (a list of strings; empty when sound). `None` is
    legal (the candidate declined a feed) and is NOT this function's question -- callers test it
    first. Shared by `validate_data.py` and `record.py ats`, so the two cannot disagree."""
    if not isinstance(ats, dict):
        return ["%s: must be an object (or null to decline a feed), got %r" % (label, ats)]
    problems = []
    vendor = ats.get("vendor")
    allowed = ({"vendor", "tenant", "wd", "site", "source", "since"} if vendor == "workday"
               else {"vendor", "slug", "region", "source", "since"})
    for k in sorted(set(ats) - allowed):
        problems.append("%s: unknown key %r" % (label, k))
    if vendor not in VENDORS:
        problems.append("%s.vendor %r is not one of %s" % (label, vendor, ", ".join(VENDORS)))
    if vendor == "workday":
        # dev #775 -- all three parts required; no slug or region; the site is never `wday` or a path
        tenant, wd, site = ats.get("tenant"), ats.get("wd"), ats.get("site")
        if not (isinstance(tenant, str) and WD_TENANT_RE.match(tenant)):
            problems.append("%s.tenant %r is not a tenant (%s)" % (label, tenant, WD_TENANT_RE.pattern))
        if not (isinstance(wd, str) and WD_RE.match(wd)):
            problems.append("%s.wd %r is not wd<digits> (%s)" % (label, wd, WD_RE.pattern))
        if not (isinstance(site, str) and WD_SITE_RE.match(site)) or \
                (isinstance(site, str) and site.casefold() == "wday"):
            problems.append("%s.site %r is not a Workday site name (%s, never `wday`, never a path)"
                            % (label, site, WD_SITE_RE.pattern))
    else:
        slug = ats.get("slug")
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            problems.append("%s.slug %r is not a slug (%s)" % (label, slug, SLUG_RE.pattern))
        if vendor == "lever":
            if ats.get("region") not in REGIONS:
                problems.append("%s.region must be one of %s for lever, got %r"
                                % (label, ", ".join(REGIONS), ats.get("region")))
        elif "region" in ats:
            problems.append("%s.region is legal only for lever (got it on %r)" % (label, vendor))
    if ats.get("source") not in SOURCES:
        problems.append("%s.source %r is not one of %s" % (label, ats.get("source"),
                                                          ", ".join(SOURCES)))
    since = ats.get("since")
    try:
        if not (isinstance(since, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", since)):
            raise ValueError
        datetime.date.fromisoformat(since)
    except ValueError:
        problems.append("%s.since %r is not an ISO date" % (label, since))
    return problems
