"""protection.py -- the lines the Pages check reports about the protection on `main` and about who else can
write to the public repo (dev #835, design amendment 1 A3.4, A4.3; named changes AM6, AS4).

PROTECTION (AM6, AS4). `main` counts as protected when the rules in effect (from any ruleset at any
level) carry `deletion` and `non_fast_forward`, OR classic branch protection blocks force-push and
deletion (it is then reported as protecting main, C28). When rulesets are not available on the plan (a
plan-limit 403/422 on the rules read, recognised by rulesets.plan_unavailable) C26 is ONE line of kind
`info`, "not available on this plan; publish is unaffected": never a to-resolve line, because the person
cannot carry out its remedy.

WRITERS (guard c). Reported: any other collaborator with push, any team with push/maintain/admin, any
write deploy key. GitHub Apps installed with contents write are NOT CHECKED (U5), and the summary line
always says so.

"""

import rulesets
from pagesaudit.values import YOU


RULESETS_UNAVAILABLE_LINE = "Rulesets are not available on this plan; publish is unaffected."


def _protection_items(repo, base, is_admin, rd, add):
    rules, plan = None, False
    names = {}
    r4 = rd(base + "/rules/branches/main", True)
    if r4.status == 200 and isinstance(r4.data, (list, type(None))):
        rules = r4.data or []
    elif rulesets.plan_unavailable(r4.status, r4.message):
        plan, rules = True, []
    else:
        add("C31", "not_checked", "NOT CHECKED: the rules in effect on main (%s)."
            % (r4.message or "needs access"), YOU)

    r5 = rd(base + "/rulesets?includes_parents=false&targets=branch")
    listing, detail = None, None
    if r5.status == 200 and isinstance(r5.data, list):
        listing = [x for x in r5.data if isinstance(x, dict)]
        names = dict((x.get("id"), x.get("name")) for x in listing)
    elif rulesets.plan_unavailable(r5.status, r5.message):
        plan = True
    else:
        add("C31", "not_checked", "NOT CHECKED: the rulesets of %s (%s)." % (repo, r5.message or "needs access"), YOU)
    named = [x for x in (listing or []) if x.get("name") == rulesets.RULESET_NAME]
    if len(named) == 1:
        d = rd(base + "/rulesets/%s" % named[0].get("id"))
        if d.status == 200 and isinstance(d.data, dict):
            detail = d.data
        else:
            add("C31", "not_checked", "NOT CHECKED: the site-studio ruleset's settings (%s)."
                % (d.message or "needs access"), YOU)

    classic = None
    if is_admin:
        r6 = rd(base + "/branches/main/protection")
        if r6.status == 200 and isinstance(r6.data, dict):
            classic = r6.data
        elif r6.status == 404:
            classic = None
        elif not rulesets.plan_unavailable(r6.status, r6.message):
            add("C31", "not_checked", "NOT CHECKED: classic branch protection (%s)."
                % (r6.message or "needs access"), YOU)
    else:
        add("C31", "not_checked", "NOT CHECKED: classic branch protection (needs admin access).", YOU)

    if rules is not None:
        gaps = rulesets.protection_gaps(rules, classic)
        if gaps and plan and not rulesets.classic_blocks(classic):
            add("C26", "info", RULESETS_UNAVAILABLE_LINE, "")
        elif gaps:
            add("C26", "resolve", "main on %s is not protected against %s. Run setup's protect step "
                "(repos.py protect, which asks you first), or add a ruleset in Settings, then Rules."
                % (repo, " or ".join(gaps)), "site-studio, with your yes; or you")
        else:
            srcs = ["%s (%s)" % (n, s) if s else n for n, s in rulesets.sources(rules, names)]
            if rulesets.classic_blocks(classic) >= {"force-push", "deletion"} and not srcs:
                srcs = ["classic branch protection"]
            add("C28", "ok", "main is protected by %s." % ", ".join(srcs or ["rules in effect"]), "")
        for t, n in rulesets.refusing_rules(rules, names):
            add("C29", "resolve", "A rule on main can refuse publish's push: %s (%s). Publish pushes "
                "straight to main, so remove that rule in Settings, then Rules, or publishing will fail."
                % (t, n), YOU)
    if classic is not None:
        bad = rulesets.classic_refusing(classic)
        if bad:
            add("C30", "resolve", "Classic branch protection on main requires %s, which refuses publish's "
                "push. Remove it in Settings, then Branches." % ", ".join(bad), YOU)
    if len(named) > 1:
        add("C27", "resolve", "There are %d rulesets named '%s' (ids %s). Keep one and remove the others in "
            "Settings, then Rules." % (len(named), rulesets.RULESET_NAME,
                                       ", ".join(str(x.get("id")) for x in named)), YOU)
    elif detail is not None:
        diffs = rulesets.differences(detail)
        if diffs:
            add("C27", "resolve", "The site-studio ruleset on %s has been changed: %s. Run repos.py protect "
                "--fix to restore it (it asks you first)." % (repo, "; ".join(diffs)),
                "site-studio, with your yes")


def _writer_items(repo, base, owner_login, owner_is_org, rd, add):
    refused = []
    me = None
    if owner_is_org:
        u = rd("user")
        if u.status == 200 and isinstance(u.data, dict) and u.data.get("login"):
            me = u.data["login"]
        else:
            refused.append("which account is you")
    person = me if owner_is_org else owner_login
    seen = set()
    if not (owner_is_org and me is None):
        c = rd(base + "/collaborators?affiliation=all&per_page=100", True)
        if c.status == 200 and isinstance(c.data, list):
            for x in c.data:
                if not isinstance(x, dict) or not x.get("login"):
                    continue
                p = x.get("permissions") if isinstance(x.get("permissions"), dict) else {}
                if p.get("push") is True and x["login"].lower() != person.lower() and x["login"] not in seen:
                    seen.add(x["login"])
                    add("C32", "resolve", "%s can also push to %s (%s). If you did not mean that, remove "
                        "them in Settings, then Collaborators and teams."
                        % (x["login"], repo, x.get("role_name") or "write"), YOU)
        else:
            refused.append("collaborators")
    if owner_is_org:
        t = rd(base + "/teams", True)
        if t.status == 200 and isinstance(t.data, list):
            for x in t.data:
                if isinstance(x, dict) and x.get("permission") in ("push", "maintain", "admin"):
                    add("C33", "resolve", "The team %s can push to %s (%s). If you did not mean that, remove "
                        "it in Settings, then Collaborators and teams." % (x.get("slug"), repo, x["permission"]), YOU)
        else:
            refused.append("teams")
    k = rd(base + "/keys", True)
    if k.status == 200 and isinstance(k.data, list):
        for x in k.data:
            if isinstance(x, dict) and x.get("read_only") is False:
                add("C34", "resolve", "The deploy key '%s' can push to %s. If you did not mean that, remove "
                    "it in Settings, then Deploy keys." % (x.get("title") or "untitled", repo), YOU)
    else:
        refused.append("deploy keys")
    if refused:
        add("C35", "not_checked", "NOT CHECKED: who else can push (needs write access; could not read: %s)."
            % ", ".join(refused), YOU)
