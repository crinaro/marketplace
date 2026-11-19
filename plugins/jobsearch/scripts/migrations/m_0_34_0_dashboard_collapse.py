"""Migration 0.34.0: `m_0_34_0_dashboard_collapse()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.34.0"


def m_0_34_0_dashboard_collapse(profile, apply_it):
    """0.34.0 — the published dashboard SET collapses to ONE artifact (owner-approved
    2026-08-26; ADR-019's threshold clause reversed). This migration handles the RETIRED
    per-page URLs, and it can only ever RECORD: it runs from a SessionStart hook as a
    deterministic script, and the Artifact tool is model-invoked only — no script can
    publish the "moved" stub the old URLs need. So the retirement is two-phase
    (scripts/pending_stubs.py owns the ledger and the drain protocol):

      1. HERE: every `views/*_url.txt` other than the surviving
         `dashboard_artifact_url.txt` becomes a pending-stub row (page, url_file, the URL
         itself, state=pending). **The url file is NOT deleted** — retiring it before its
         stub publish is confirmed would make that URL permanently unstubbable, which is
         exactly the dangling-live-URL outcome the collapse exists to remove.
      2. A tool-holding session drains the ledger: publish the constant moved-stub to
         each URL, and only then `pending_stubs.py --published <page>` retires the file.

    ⭐ AN ABSENT url file is BENIGN — "that page never published", never an error. Two
    phases on the reference profile are in exactly that state. A url file whose content
    does not parse as a URL is recorded LOUDLY as state `unresolved` (an unreadable value
    must never read as handled) and the file is kept.

    The retired GENERATED pages (views/router_artifact.html, views/phase-*_artifact.html)
    are deleted: they are re-derivable by construction (the 0.32.0 tree migration's own
    rule for generated files), and a generated file nothing regenerates is the
    linger-stale defect this collapse removes. Authored files are untouched.

    Idempotent: pending_stubs.record() is keyed by page, and a second run finds the
    generated pages already gone.

    ⚠️ RE-KEYED FROM 0.33.0 TO 0.34.0 (release-manager, preparing 0.34.0). This function was
    written and originally registered under "0.33.0" while 0.33.0 was still unpublished — but
    0.33.0 then shipped (tag jobsearch--v0.33.0, MIGRATIONS ending at 0.32.0, no entry for
    this migration at all) before this work was added. `pending_for()` compares with strict
    `<`: a profile that installed the real 0.33.0 has a stamp of exactly "0.33.0", and
    `ver("0.33.0") < ver("0.33.0")` is False — so a migration keyed "0.33.0" would silently
    never fire for that profile on any later upgrade. Verified empirically (not just reasoned
    about): `pending_for(stamp="0.33.0", engine="0.34.0")` returned `[]` before this rename.
    Keying it to 0.34.0 — the version it actually ships in — is what makes `stamp < "0.34.0"`
    true for that exact profile.
    """
    import pending_stubs as _stubs

    views = os.path.join(profile, "views")
    lines, recorded, unresolved = [], [], []

    candidates = []
    for d in (views, profile):          # profile root: pre-0.32.0 stragglers
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith("_url.txt") or name in _stubs.SURVIVING_URL_FILES:
                continue
            candidates.append((name, os.path.join(d, name)))

    for name, path in candidates:
        page = name[:-len("_url.txt")]
        try:
            content = open(path, encoding="utf-8").read().strip()
        except OSError as e:
            content = ""
            lines.append("url file %s unreadable (%s)" % (name, e))
        ok_url = content.startswith(("http://", "https://"))
        state = "pending" if ok_url else "unresolved"
        if apply_it:
            if _stubs.record(profile, page, os.path.relpath(path, profile),
                             content if ok_url else "", state=state):
                (recorded if ok_url else unresolved).append(page)
        else:
            (recorded if ok_url else unresolved).append(page)

    removed = []
    if os.path.isdir(views):
        for name in sorted(os.listdir(views)):
            if name == "router_artifact.html" or (name.startswith("phase-")
                                                  and name.endswith("_artifact.html")):
                if apply_it:
                    os.unlink(os.path.join(views, name))
                removed.append(name)

    if not (candidates or removed):
        return True, ("  dashboard collapse (0.34.0): nothing to record — no retired "
                      "url files or generated phase pages found (a phase that never "
                      "published has nothing to stub; that is the benign case)")
    if apply_it and not (recorded or unresolved or removed or lines):
        return True, ("  dashboard collapse (0.34.0): every retired url already "
                      "recorded — idempotent no-op (drain state lives in "
                      "data/pending_stubs.jsonl)")
    bits = []
    if recorded:
        bits.append("%d retired URL(s) recorded as pending stubs (%s) — a tool-holding "
                    "session drains them via scripts/pending_stubs.py; url files kept "
                    "until each stub publish is CONFIRMED" % (len(recorded),
                                                              ", ".join(recorded)))
    if unresolved:
        bits.append("%d url file(s) did not parse as a URL and were recorded LOUDLY as "
                    "unresolved (%s)" % (len(unresolved), ", ".join(unresolved)))
    if removed:
        bits.append("removed %d re-derivable generated page(s): %s"
                    % (len(removed), ", ".join(removed)))
    bits.extend(lines)
    prefix = "  ✅ dashboard collapse (0.34.0): " if apply_it \
        else "  would collapse the published set (0.34.0): "
    return True, prefix + "; ".join(bits)
