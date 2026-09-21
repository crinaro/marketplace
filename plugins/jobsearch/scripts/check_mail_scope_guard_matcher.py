#!/usr/bin/env python3
"""Does `hooks.json`'s PreToolUse matcher still agree with `guard_mail_scope.py`'s
GUARDED_MAIL_SCOPE_TOOLS?

⭐ WHY THIS EXISTS (design-manifest-heal.md § The boundary, item 1 — same shape as
check_mail_guard_matcher.py / check_click_guard_matcher.py, dev #78)
-------------------------------------------------------------------------------------------
`guard_mail_scope.py` names its `GUARDED_MAIL_SCOPE_TOOLS` tuple as the single source of
truth for which connector tools get scoped to this profile's own mailboxes. `hooks.json`'s
matcher string is a SEPARATE, hand-maintained copy of the same alternation, because the hook
registration format has no way to import a Python constant. The stakes are the same as the
send guard's: the matcher IS the classifier, so a matcher that covers less than the tuple
silently ships a scope policy that does not hold for the tool it dropped.

⚠️ This must run against the SHIPPED package, not just the dev tree —
`check_shipped_package.py` runs this exact script inside its materialized copy.

Resolves both files relative to ITS OWN location (sibling `scripts/` and `hooks/` under the
same `plugins/jobsearch/`), so the same script works unmodified whether it is run from this
repo or from inside a throwaway materialized package.

Usage:
    python3 scripts/check_mail_scope_guard_matcher.py

Python 3.9+. Standard library only.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
HOOKS_JSON = os.path.join(PLUGIN_ROOT, "hooks", "hooks.json")

sys.path.insert(0, HERE)


def guarded_tools():
    import guard_mail_scope as g
    return g.GUARDED_MAIL_SCOPE_TOOLS


def find_matcher(hooks_config):
    """The matcher string of the PreToolUse entry that runs guard_mail_scope.py, or None if no
    such entry exists at all — itself a failure, not a silent pass."""
    for entry in (hooks_config.get("hooks") or {}).get("PreToolUse") or []:
        for h in entry.get("hooks") or []:
            if "guard_mail_scope.py" in (h.get("command") or ""):
                return entry.get("matcher")
    return None


def main():
    print("MAIL SCOPE GUARD MATCHER — does hooks.json agree with GUARDED_MAIL_SCOPE_TOOLS?")
    print("  hooks.json: %s" % HOOKS_JSON)

    try:
        tools = guarded_tools()
    except Exception as e:
        print("\n  !! could not import guard_mail_scope.py — %s. This gate cannot run "
              "without the tuple it checks against." % e)
        return 1

    if not tools:
        print("\n  !! GUARDED_MAIL_SCOPE_TOOLS is empty — that would make the alternation "
              "empty too, which is itself a defect, not a clean state.")
        return 1

    expected = "|".join(tools)

    if not os.path.exists(HOOKS_JSON):
        print("\n  !! hooks.json is missing entirely at %s — and this guard without its "
              "registration is a scope policy that does not hold." % HOOKS_JSON)
        return 1

    try:
        with open(HOOKS_JSON, encoding="utf-8") as fh:
            hooks_config = json.load(fh)
    except Exception as e:
        print("\n  !! hooks.json did not parse as JSON — %s" % e)
        return 1

    actual = find_matcher(hooks_config)
    if actual is None:
        print("\n  !! no PreToolUse entry in hooks.json runs guard_mail_scope.py at all — "
              "the guard is built but never wired in, and the scope policy is unenforced.")
        return 1

    print("  GUARDED_MAIL_SCOPE_TOOLS: %s" % ", ".join(tools))
    print("  expected matcher:         %s" % expected)
    print("  hooks.json matcher:       %s" % actual)

    if actual != expected:
        print("\n  !! DRIFT: hooks.json's matcher does not equal "
              "\"|\".join(GUARDED_MAIL_SCOPE_TOOLS).")
        print("     Either the tuple changed without updating hooks.json, or the reverse.")
        print("     Whichever moved, bring the other back to matching this print.")
        return 1

    print("\n  CLEAN. hooks.json's matcher equals \"|\".join(GUARDED_MAIL_SCOPE_TOOLS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
