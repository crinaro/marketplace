"""pagesitems.py -- the lines the Pages check reports about the Pages settings, the domain, the DNS health and
the certificate (dev #835, design amendment 1 A2, A3.4), and `pages_source`, the one classifier of the Pages
SOURCE (C4, C5) that deploy.py reads too (template-fidelity R2-5).

STATE PRECEDENCE (AM11; OURS). Each block below yields mutually exclusive lines; blocks are independent.
  1. Domain block, first match wins:
       cname set, domain null                  -> C11
       cname set, domain != cname              -> C10
       cname set == domain, cutover false      -> C8b  (Pages already serves it, and the next publish would
                                                  ship no CNAME file; this is NOT "planned" and NOT C8)
       cname set == domain, cutover true       -> no domain line; the checks below run
       cname null, domain null                 -> C7   (ok)
       cname null, domain set, cutover false   -> C8   (info: planned, nothing wrong yet)
       cname null, domain set, cutover true    -> C9
  2. When a cname is set (whatever block 1 said): C12 verification, then DNS health: 202 after the
     retries -> C13 only; else dns_resolves false -> C14 only (the other DNS flags mean nothing then);
     else C15 to C19 each independently. Then the certificate: exactly one of C20 / C21 / C22 / C23
     (an ABSENT certificate reads as C20 wait, never as ok; only `approved` is ok: an allowlist, S4).
  3. HTTPS: https_enforced true -> ok. False: certificate ok or no cname -> C24; certificate waiting or
     absent -> C25; certificate failed or unknown -> no HTTPS line (the certificate line dominates).
  4. Protection (C26 to C31) and writers (C32 to C35) as in their tables below.
  Pages source (C4, C5, C6) come first, in that order; C6 errored and "building" (a wait) are exclusive.

DNS / CNAME: `alt_domain` (the www alias on an apex site) is handled to one signal only: if its DNS does
not resolve, an info line says so (`C14w`). Every other alt_domain flag is NOT CHECKED; the summary says
"the www alias is checked only for DNS".

"""

from pagesaudit.values import Item, YOU, YOU_DNS, YOU_SETTINGS


HEALTH_RETRIES = 2          # after the first 202
HEALTH_RETRY_SECONDS = 5


APEX_A = ("185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153")
CERT_WAIT = frozenset({"new", "authorization_created", "authorization_pending", "authorized", "issued",
                       "uploaded"})
CERT_OK = frozenset({"approved"})
CERT_FAILED = frozenset({"errored", "bad_authz", "authorization_revoked", "destroy_pending",
                         "dns_changed"})


def _dns_records(cname, owner, apex):
    if apex:
        return ("A records for %s (and AAAA records 2606:50c0:8000::153 to 2606:50c0:8003::153 for IPv6)"
                % ", ".join(APEX_A))
    return "a CNAME record pointing to %s.github.io (without the repo name)" % owner


def _is_apex(dom, cname):
    v = dom.get("is_apex_domain")
    if isinstance(v, bool):
        return v
    return cname.count(".") == 1


def pages_source(pages):
    """The Pages SOURCE (C4, C5) of one `GET .../pages` answer, as an `Item`, or None when Pages serves the
    branch publish pushes to: `main` at the root. The ONE function that classifies it (template-fidelity R2-5):
    `_pages_items` below adds its item, and `deploy.py` reads the same answer itself (a 60 s call of its own)
    and refuses on it before the address guard, because the public repo's `main /` is the tree a visitor sees
    only when Pages says so. It does no I/O, starts no process, and imports nothing from `deploy` or `adopt`.
    `pages` must be the decoded object; anything else is the caller's `NOT CHECKED`."""
    build_type = pages.get("build_type")
    src = pages.get("source") if isinstance(pages.get("source"), dict) else {}
    if build_type == "workflow":
        return Item("C4", "resolve", "Pages builds from a GitHub Actions workflow, so the files publish pushes "
                    "are not what is served. Set the source to 'Deploy from a branch'.", YOU_SETTINGS)
    if src.get("branch") != "main" or src.get("path") != "/":
        got = "%s%s" % (src.get("branch") or "no branch", src.get("path") or "")
        return Item("C5", "resolve", "Pages serves %s, but publish pushes to main at the root. Set the source "
                    "to main, / (root)." % got, YOU_SETTINGS)
    return None


def _pages_items(pages, cfg, owner, where, base, rd, sleep, add):
    domain = getattr(cfg, "domain", None)
    cutover = bool(getattr(cfg, "cutover", False))
    preview = getattr(cfg, "previewUrl", None) or "its github.io address"
    cname = pages.get("cname") or None

    # -- source and build
    source = pages_source(pages)
    if source is not None:
        add(*source)
    status = pages.get("status")
    if status == "errored":
        add("C6", "resolve", "The last Pages build failed. Open the repo's Actions tab, run 'pages build "
            "and deployment', and read the error.", YOU)
    elif status == "building":
        add("C6w", "wait", "GitHub is still building the Pages site. Run this check again in a minute.",
            "GitHub (wait)")

    # -- the domain block: first match wins (see the docstring)
    same = bool(cname and domain and cname.lower() == domain.lower())
    if cname and not domain:
        add("C11", "resolve", "Pages has the custom domain %s, but site.json does not name it, so the next "
            "publish carries no CNAME file. Set domain in site.json, or remove the domain in Settings, "
            "then Pages." % cname, YOU)
    elif cname and not same:
        add("C10", "resolve", "Pages serves %s, but site.json says %s. Decide which one is right: change "
            "it in Settings, then Pages, or edit domain in site.json and publish." % (cname, domain), YOU)
    elif cname and same and not cutover:
        add("C8b", "resolve", "Pages already serves %s, but site.json has cutover false, so the next "
            "publish carries no CNAME file and Pages would stop serving the domain. Set cutover to true "
            "(setup step 5), or remove the domain in Settings, then Pages." % cname, YOU)
    elif not cname and not domain:
        add("C7", "ok", "No custom domain. The site is at %s." % preview, "")
    elif not cname and not cutover:
        add("C8", "info", "%s is planned and not switched over yet. Run setup step 5 when the DNS is ready."
            % domain, YOU)
    elif not cname:
        add("C9", "resolve", "The site's CNAME file names %s, but Pages has no custom domain set. In the "
            "repo's Settings, then Pages, then Custom domain, enter %s and save (saving writes a commit "
            "to main; the next publish replaces it with the build's own CNAME file). Whether the pushed "
            "CNAME file alone sets it is not yet known (U2)." % (domain, domain), YOU)

    cert_state_kind = None
    if cname:
        # -- verification
        pstate = pages.get("protected_domain_state")
        if pstate != "verified":
            since = pages.get("pending_domain_unverified_at")
            add("C12", "resolve", "%s is not verified for %s (GitHub says: %s%s). Add a DNS TXT record "
                "named _github-pages-challenge-%s on the domain you verify, with the value GitHub shows "
                "under %s Settings, then Pages, then Add a domain (it shows the exact name and value). "
                "Then press Verify there, not in the repo's settings. This stops anyone else publishing "
                "on the domain." % (cname, owner, pstate or "no state",
                                    ", unverified since %s" % since if since else "", owner, where),
                "you, at your DNS provider and in your account's Settings")
        # -- DNS health
        _health_items(cname, owner, base, rd, sleep, add)
        # -- certificate
        cert = pages.get("https_certificate") if isinstance(pages.get("https_certificate"), dict) else None
        cstate = cert.get("state") if cert else None
        if cstate in CERT_OK:
            cert_state_kind = "ok"
            add("C21", "ok", "Certificate ready.", "")
        elif cstate in CERT_WAIT or cert is None or cstate is None:
            cert_state_kind = "wait"
            add("C20", "wait", "GitHub is getting a certificate for %s (%s). This can take up to 24 hours."
                % (cname, cstate or "no state reported yet"), "GitHub (wait)")
        elif cstate in CERT_FAILED:
            cert_state_kind = "failed"
            add("C22", "resolve", "The certificate for %s failed (%s: %s). Fix the DNS lines above, then "
                "remove the custom domain in Settings, then Pages, and add it again."
                % (cname, cstate, cert.get("description") or "no description"), YOU)
        else:
            cert_state_kind = "unknown"
            add("C23", "resolve", "GitHub reports a certificate state this check does not know (%s). Look "
                "in Settings, then Pages." % cstate, YOU)

    # -- HTTPS
    if pages.get("https_enforced"):
        add("C24", "ok", "HTTPS is enforced.", "")
    elif not cname or cert_state_kind == "ok":
        add("C24", "resolve", "HTTPS is not enforced. Turn on 'Enforce HTTPS' in the repo's Settings, "
            "then Pages.", YOU)
    elif cert_state_kind == "wait":
        add("C25", "wait", "'Enforce HTTPS' becomes available when the certificate is ready.",
            "GitHub (wait)")


def _health_items(cname, owner, base, rd, sleep, add):
    r = None
    for attempt in range(HEALTH_RETRIES + 1):
        r = rd(base + "/pages/health")
        if r.status != 202:
            break
        if attempt < HEALTH_RETRIES:
            sleep(HEALTH_RETRY_SECONDS)
    if r.status == 202:
        add("C13", "wait", "GitHub is still checking the DNS for %s. Run this check again in a minute."
            % cname, "GitHub (wait)")
        return
    if r.status != 200 or not isinstance(r.data, dict):
        why = "needs admin access" if r.status in (403, 404) else (r.message or "no answer")
        add("C13n", "not_checked", "NOT CHECKED: the DNS health of %s (%s)." % (cname, why), YOU)
        return
    dom = r.data.get("domain")
    if not isinstance(dom, dict):
        add("C13n", "not_checked", "NOT CHECKED: GitHub's DNS health answer for %s was empty." % cname, YOU)
        return
    apex = _is_apex(dom, cname)
    resolves = dom.get("dns_resolves")
    if resolves is False:
        reason = dom.get("reason")
        add("C14", "resolve", "%s does not resolve yet%s. Add these DNS records at your DNS provider: %s."
            % (cname, " (GitHub says: %s)" % reason if isinstance(reason, str) and reason else "",
               _dns_records(cname, owner, apex)), YOU_DNS)
    elif resolves is True:
        if apex and dom.get("is_pointed_to_github_pages_ip") is False:
            add("C15", "resolve", "The apex %s must have A records for %s (and AAAA 2606:50c0:8000::153 to "
                "2606:50c0:8003::153 for IPv6)." % (cname, ", ".join(APEX_A)), YOU_DNS)
        if dom.get("is_non_github_pages_ip_present") is True:
            add("C16", "resolve", "%s also points at an address that is not GitHub's. Remove that extra "
                "record, or GitHub cannot issue the certificate." % cname, YOU_DNS)
        if (not apex and dom.get("is_cname_to_github_user_domain") is False
                and dom.get("is_pointed_to_github_pages_ip") is not True):
            add("C17", "resolve", "%s must be a CNAME record pointing to %s.github.io (without the repo "
                "name)." % (cname, owner), YOU_DNS)
        if dom.get("is_proxied") is True or dom.get("is_cloudflare_ip") is True:
            add("C18", "resolve", "%s is behind a proxy or CDN, which stops GitHub issuing the "
                "certificate. Turn the proxy off for this record." % cname, YOU_DNS)
        if dom.get("caa_error"):
            add("C19", "resolve", "A CAA record on %s blocks the certificate (%s). Allow letsencrypt.org, "
                "or remove the CAA record." % (cname, dom.get("caa_error")), YOU_DNS)
    else:
        add("C13n", "not_checked", "NOT CHECKED: GitHub's DNS health answer for %s did not say whether it "
            "resolves." % cname, YOU)
    alt = r.data.get("alt_domain")
    if isinstance(alt, dict) and alt.get("dns_resolves") is False:
        add("C14w", "info", "The www alias of %s does not resolve, so www visitors will not reach the "
            "site. Add a CNAME record for www pointing to %s.github.io, or ignore this if you do not use "
            "www." % (cname, owner), YOU_DNS)
