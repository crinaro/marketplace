"""Migration 0.31.0: `m_0_31_0_mail_client_rename()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.31.0"


def m_0_31_0_mail_client_rename(profile, apply_it):
    """0.31.0 — the vendored `scripts/gmail_mcp_server.py` becomes `scripts/mail_client.py`
    (marketplace #211: 19 definitions shipped so five could be imported; the MCP surface
    lives in the gmail-multi connector since ADR-004, so jobsearch's copy shrinks to the
    library the sweeps actually import).

    The profile's `docs/incident_archive.md` carries `→` back-pointers that
    `check_rule_homes.py` REQUIRES to resolve — an archived lesson whose rule vanished is
    exactly what that gate exists to catch, and a rename is the benign case of it. This
    rewrites the literal engine path in those back-pointers so the anchor follows the file.

    ⭐ PRESERVE, THEN TRANSFORM — the entry text is untouched apart from the path; the
    lesson keeps its history (the old name survives in the profile's own git history).
    SAFE: idempotent (a second run finds nothing to rewrite) and losslessly reversible
    from git. A profile with no archive yet is a clean no-op.
    """
    path = os.path.join(profile, "docs", "incident_archive.md")
    if not os.path.exists(path):
        return True, ""
    old_ref, new_ref = "scripts/gmail_mcp_server.py", "scripts/mail_client.py"
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        return False, "  ⚠️ %s exists but cannot be read (%s). Left untouched." % (path, e)
    if old_ref not in text:
        return True, ""
    n = text.count(old_ref)
    if not apply_it:
        return True, ("  would repoint %d archive back-pointer reference(s) in %s: "
                      "%s -> %s" % (n, path, old_ref, new_ref))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old_ref, new_ref))
    os.replace(tmp, path)
    return True, ("  repointed %d archive back-pointer reference(s) in %s: %s -> %s"
                  % (n, path, old_ref, new_ref))
