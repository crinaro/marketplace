#!/usr/bin/env python3
"""rulesets.py -- the ruleset that protects the public repo's `main`, as data and pure functions
(dev #835, design amendment 1 section A3 and A5; named changes AM6, AS4). Python 3.9, standard library
only. PURE: no I/O, no subprocess, no network, no clock. repos.py (setup's `protect`) and pages_check.py
(the report-only Pages check) import it; nothing here talks to GitHub.

THE INVARIANT (owner ruling (a), 2026-11-13, the second ruling on #835). The ruleset blocks force-push
and deletion of `main` and NOTHING ELSE. `deploy.py`'s normal publish is a fast-forward push of an
unsigned commit straight to `main`, so the ruleset must never gain a rule that would refuse it: no
`pull_request`, no `required_status_checks`, no `update` ("Restrict updates": only users with bypass
permissions can push, PA6), no `required_signatures`, no `merge_queue`, and so on. That is why
`PROTECT_MAIN`'s rule types are pinned EQUAL to `ALLOWED_MAIN_RULES` by tests/test_rulesets.py.
CHANGING `ALLOWED_MAIN_RULES` IS A DESIGN CHANGE, NOT A CONSTANT EDIT: it needs the owner's ruling to
move first, and the amendment to be amended. If a build is red here, fix the payload, not the pin.

What is DOCUMENTED and what is OURS:
  - the payload's shape (keys, `target`, `enforcement`, `bypass_actors`, `conditions.ref_name`, rule
    `type`s) is DOCUMENTED: https://docs.github.com/en/rest/repos/rules (PA5);
  - that "Restrict deletions", "Block force pushes" and "Restrict updates" mean what the invariant
    says is DOCUMENTED: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets (PA6);
  - the CONTENTS of the payload (which two rules, an empty bypass list, `refs/heads/main` by name) are
    OURS. Whether an empty `bypass_actors` also binds repository admins is UNDETERMINED, settled by
    P-10 step 5 (named change S9); nothing here claims it.

`HARMLESS_RULE_TYPES` is the allowlist `refusing_rules` uses: a rule in effect on `main` that is not
on it is reported as one that can refuse publish's push, including a rule type this release has never
heard of. An allowlist, so a future GitHub rule is never silently read as harmless.

Classic branch protection (AM6, `GET branches/main/protection`) is the older mechanism. It is read
only: `classic_blocks()` says which of force-push / deletion it blocks (it then counts as protecting
`main`), and `classic_refusing()` says which of its settings would refuse publish's push.

`plan_unavailable()` (AS4) recognises GitHub's "this feature is not on your plan" answer, so a person on
a plan without rulesets is told "not available on this plan; publish is unaffected" and not handed a
remedy they cannot carry out. Its message patterns are INFERRED from GitHub's wording, not fetched
(UNDETERMINED until a run on such a plan; P-10 settles U1 only for the owner's plan). It must NOT match
a plain permissions refusal ("Must have admin rights"), which is NOT CHECKED, not "unavailable".
"""
import copy
import re

RULESET_NAME = "site-studio: protect main"

PROTECT_MAIN = {
    "name": RULESET_NAME,
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},  # retired-terms: ok (a GitHub ruleset key, not the gmail-multi registry)
    "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
}

# The fallback for a plan that refuses rulesets (design amendment 1 section A3.1; shape DOCUMENTED, PA10,
# contents OURS). It blocks force-push and deletion and requires nothing else: no reviews, no status
# checks, no restricted pushers, so publish's fast-forward push stays allowed and pages_check's C30 never
# flags it. `enforce_admins` is there so the protection also binds the admin login; whether it does is
# U7, settled by P-10 step 2b. repos.py sends it as the body of `PUT branches/main/protection` and
# test_rulesets.Classic pins the literal.
CLASSIC_MAIN = {
    "required_status_checks": None,
    "enforce_admins": True,
    "required_pull_request_reviews": None,
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
}

# The ONLY rule types the ruleset may carry. Changing this is a design change (see the docstring).
ALLOWED_MAIN_RULES = frozenset({"deletion", "non_fast_forward"})

# Rule types that cannot refuse a fast-forward push of an unsigned commit to main. Anything else that
# is in effect on `main` is reported by refusing_rules(). `update` is NOT here: it is exactly the rule
# that would break publish (PA6).
HARMLESS_RULE_TYPES = frozenset({"deletion", "non_fast_forward", "required_linear_history"})

# What each protection is called to the person, and the rule type that gives it.
PROTECTIONS = (("force-push", "non_fast_forward"), ("deletion", "deletion"))


# ---------------------------------------------------------------- the ruleset's own comparison

def _norm_actor(a):
    return (a.get("actor_type"), a.get("actor_id"), a.get("bypass_mode"))


def _norm_rule(r):
    params = r.get("parameters")
    return (r.get("type"), repr(sorted(params.items())) if isinstance(params, dict) and params else "")


def normalize(ruleset):
    """The comparable form of a ruleset as GitHub returns it (ids, links, timestamps and `source`
    dropped; absent lists read as empty; lists sorted). `None` or a non-dict normalises to an empty
    ruleset, which differs from the canonical one in every field."""
    r = ruleset if isinstance(ruleset, dict) else {}
    cond = r.get("conditions") if isinstance(r.get("conditions"), dict) else {}
    ref = cond.get("ref_name") if isinstance(cond.get("ref_name"), dict) else {}
    return {
        "name": r.get("name"),
        "target": r.get("target"),
        "enforcement": r.get("enforcement"),
        "bypass_actors": sorted(_norm_actor(a) for a in (r.get("bypass_actors") or [])
                                if isinstance(a, dict)),
        "include": sorted(ref.get("include") or []),  # retired-terms: ok (a GitHub / gh key, not the gmail-multi registry)
        "exclude": sorted(ref.get("exclude") or []),
        "rules": sorted(_norm_rule(x) for x in (r.get("rules") or []) if isinstance(x, dict)),
    }


def differences(found, canonical=None):
    """Each way `found` (a ruleset read from GitHub) differs from the canonical payload, as plain
    sentences; an empty list means equal. Covers enforcement, target, conditions, bypass actors, and
    the set of rule types with their parameters (a rule missing and a rule that should not be there)."""
    want = normalize(PROTECT_MAIN if canonical is None else canonical)
    have = normalize(found)
    out = []
    if have["target"] != want["target"]:
        out.append("target is %r, should be %r" % (have["target"], want["target"]))
    if have["enforcement"] != want["enforcement"]:
        out.append("enforcement is %s, should be %s" % (have["enforcement"], want["enforcement"]))
    if have["include"] != want["include"]:  # retired-terms: ok (a GitHub / gh key, not the gmail-multi registry)
        out.append("it applies to %s, should apply to %s"
                   % (", ".join(have["include"]) or "no branch", ", ".join(want["include"])))  # retired-terms: ok (a GitHub / gh key, not the gmail-multi registry)
    if have["exclude"] != want["exclude"]:
        out.append("it excludes %s, should exclude nothing" % (", ".join(have["exclude"]) or "nothing"))
    if have["bypass_actors"] != want["bypass_actors"]:
        out.append("it has %d bypass actor(s), should have %d"
                   % (len(have["bypass_actors"]), len(want["bypass_actors"])))
    have_types = sorted(t for t, _p in have["rules"])
    want_types = sorted(t for t, _p in want["rules"])
    for t in want_types:
        if t not in have_types:
            out.append("the %s rule is missing" % t)
    for t in have_types:
        if t not in want_types:
            out.append("it has an extra rule: %s" % t)
    for (t, p) in have["rules"]:
        if t in want_types and (t, p) not in want["rules"]:
            out.append("the %s rule has parameters it should not have" % t)
    return out


def canonical_payload():
    """A fresh deep copy of PROTECT_MAIN, safe to send and to mutate."""
    return copy.deepcopy(PROTECT_MAIN)


# ---------------------------------------------------------------- what is in effect on main

def _rule_types(rules):
    return set(r.get("type") for r in (rules or []) if isinstance(r, dict))


def protection_gaps(rules_in_effect, classic=None):
    """Which of 'force-push' and 'deletion' are NOT blocked on main: the rules in effect (from
    `GET rules/branches/main`, any ruleset at any level) minus whatever classic protection
    (`classic`: the parsed `GET branches/main/protection`, or None) blocks."""
    have = _rule_types(rules_in_effect)
    blocked_by_classic = classic_blocks(classic)
    return [name for name, rule in PROTECTIONS if rule not in have and name not in blocked_by_classic]


def refusing_rules(rules_in_effect, names=None):
    """[(rule type, ruleset name)] for every rule in effect on `main` that is NOT on the harmless
    allowlist, i.e. one that can refuse publish's direct push. `names` optionally maps a ruleset id to
    its name (the list read); without it the name falls back to 'ruleset <id>', then to 'an unnamed
    ruleset' (`ruleset_name` is not a documented key of the rules-in-effect response, so it is never read). An entry with no `type` is reported as '(unknown)'."""
    names = names or {}
    out = []
    for r in rules_in_effect or []:
        if not isinstance(r, dict):
            continue
        t = r.get("type") or "(unknown)"
        if t in HARMLESS_RULE_TYPES:
            continue
        rid = r.get("ruleset_id")
        name = names.get(rid) or ("ruleset %s" % rid if rid is not None else "an unnamed ruleset")
        out.append((t, name))
    return out


def sources(rules_in_effect, names=None):
    """The distinct rulesets (name, source) that supply a protection rule in effect on main, in order.
    `source` is the entry's `ruleset_source` ('owner/repo' or an organisation) and may be None."""
    names = names or {}
    seen, out = set(), []
    for r in rules_in_effect or []:
        if not isinstance(r, dict) or r.get("type") not in ALLOWED_MAIN_RULES:
            continue
        rid = r.get("ruleset_id")
        name = names.get(rid) or ("ruleset %s" % rid if rid is not None else "a ruleset")
        key = (name, r.get("ruleset_source"))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


# ---------------------------------------------------------------- classic branch protection (AM6)

def _enabled(v):
    # GitHub returns {"enabled": bool, "url": ...}; tolerate a bare bool.
    if isinstance(v, dict):
        return bool(v.get("enabled"))
    return bool(v)


def classic_blocks(protection):
    """Which of 'force-push' and 'deletion' classic branch protection blocks (a set of those names)."""
    if not isinstance(protection, dict):
        return set()
    out = set()
    if "allow_force_pushes" in protection and not _enabled(protection.get("allow_force_pushes")):
        out.add("force-push")
    if "allow_deletions" in protection and not _enabled(protection.get("allow_deletions")):
        out.add("deletion")
    return out


def classic_refusing(protection):
    """The classic-protection settings that would refuse publish's direct push, as plain phrases."""
    if not isinstance(protection, dict):
        return []
    out = []
    if protection.get("required_pull_request_reviews"):
        out.append("pull request reviews")
    if protection.get("required_status_checks"):
        out.append("status checks")
    if _enabled(protection.get("required_signatures")):
        out.append("signed commits")
    if protection.get("restrictions"):
        out.append("a restricted list of who can push")
    if _enabled(protection.get("lock_branch")):
        out.append("a locked branch")
    return out


# ---------------------------------------------------------------- "not on this plan" (AS4)

# INFERRED wording (see the docstring). Deliberately narrow: a plan or "make it public" sentence.
_PLAN_PATTERNS = (
    re.compile(r"upgrade to github", re.I),
    re.compile(r"make this repository public", re.I),
    re.compile(r"(?:available|enabled?) (?:for|on|in|with) .{0,60}(?:plan|public repositor)", re.I),
    re.compile(r"\bon (?:your|this|the) (?:current )?plan\b", re.I),
    re.compile(r"enable this feature", re.I),
)


def plan_unavailable(status, message):
    """True when a refused read or write is GitHub saying rulesets are not available on this plan:
    status 402, 403 or 422 AND a message that names the plan. A permissions refusal ("Must have admin
    rights to Repository.", "Not Found", "Resource not accessible") is False."""
    if status not in (402, 403, 422):
        return False
    text = message if isinstance(message, str) else ""
    return any(p.search(text) for p in _PLAN_PATTERNS)
