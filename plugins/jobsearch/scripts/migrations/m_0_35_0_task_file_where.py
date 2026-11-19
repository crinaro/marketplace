"""Migration 0.35.0: `m_0_35_0_task_file_where()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.35.0"


TASK_WHERE_OLD = (
    '$(cat ~/.claude/jobsearch/engine_root)',
    '$(cat "$HOME/.claude/jobsearch/engine_root")',
    '$(cat $HOME/.claude/jobsearch/engine_root)',
    '$(cat "${HOME}/.claude/jobsearch/engine_root")',
    '$(cat ${HOME}/.claude/jobsearch/engine_root)',
)
TASK_WHERE_NEW = "$(~/.claude/jobsearch/run --where)"


def m_0_35_0_task_file_where(profile, apply_it, home=None):
    """0.35.0 — scheduled-task files stop reading the demoted engine pointer (dev #167,
    closing #249).

    The task files under `~/.claude/scheduled-tasks/<name>/SKILL.md` carry a fallback line,
    `export CLAUDE_PLUGIN_ROOT="$(cat ~/.claude/jobsearch/engine_root)"`, written back when
    the pointer file was the resolution mechanism. Since the launcher's TEMPLATE_GENERATION 3
    nothing resolves through that file — it is repaired after resolution, informationally —
    so a task reading it gets an answer that is merely USUALLY right: between a poisoning
    write and the next `run` call, the file can name a dead session copy or a maintainer
    tool's temp directory. `run --where` returns the SAME resolution every run uses, so the
    task and the launcher can never disagree.

    ⭐ PRESERVE, THEN TRANSFORM. Only the known command-substitution forms are rewritten, in
    place, atomically; everything else in the task file is untouched. A task file that
    mentions `jobsearch/engine_root` in a shape this rewrite does not recognise is recorded
    LOUDLY — a `task-file-unrewritten` machine event plus a printed line — never silently
    left looking handled (the unparseable-value rule). That case still returns ok: the file
    belongs to the scheduler, not the engine, and blocking the schema stamp forever on a
    hand-authored variant would hold every later migration hostage to it.

    Machine state, not profile data — same precedent as m_0_26_0_state_home and
    m_0_29_0_gmail_connector_config, which also reach under `$HOME`. Idempotent: a second run
    finds no old pattern and no-ops. `home` is a test seam; real runs resolve `$HOME`.

    ⚠️ WHAT IS TESTED, AND WHAT REMAINS COMPOSITION-UNTESTED (dev #165 item 2). The rewrite
    itself, and the `sh`-level command substitution it produces — `export
    CLAUDE_PLUGIN_ROOT="$(~/.claude/jobsearch/run --where)"` yielding the bare resolved path
    with nothing else in the variable — are both exercised against a real `/bin/sh`
    (`TestTaskFileWhereMigration` and `TestLauncherShellNewestWins.
    test_where_composes_into_the_task_file_fallback_line` in test_checks.py). The DESKTOP
    SCHEDULER'S OWN HARNESS actually executing a rewritten `SKILL.md` — its own shell, its own
    environment, its own error handling around a failed `run --where` — is external to this
    repo and is NOT reproduced by any test here. Stated here plainly, as residue, rather than
    left to be assumed covered by the sh-level test above.
    """
    from _diag import log_machine as _diag_machine
    base = os.path.join(home or os.path.expanduser("~"), ".claude", "scheduled-tasks")
    if not os.path.isdir(base):
        return True, ""

    rewritten, loud = [], []
    for name in sorted(os.listdir(base)):
        f = os.path.join(base, name, "SKILL.md")
        if not os.path.isfile(f):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            if apply_it:
                _diag_machine("task-file-unrewritten", task=name, reason="unreadable")
            loud.append("%s: unreadable (%s) — left untouched" % (name, e))
            continue
        new = text
        for old in TASK_WHERE_OLD:
            new = new.replace(old, TASK_WHERE_NEW)
        if new != text:
            if apply_it:
                tmp = f + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(new)
                os.replace(tmp, f)          # atomic: never a half-written task file
            rewritten.append(name)
        elif "jobsearch/engine_root" in text and TASK_WHERE_NEW not in text:
            # Names the pointer in a form this migration does not know how to rewrite. An
            # unrewritten reader of a demoted pointer must be LOUD: it would go on looking
            # handled while reading a file nothing keeps authoritative any more.
            if apply_it:
                _diag_machine("task-file-unrewritten", task=name, reason="unrecognised-form")
            loud.append("%s: references jobsearch/engine_root in a form this migration does "
                        "not recognise — edit it to use %s" % (name, TASK_WHERE_NEW))

    if not (rewritten or loud):
        return True, ""
    bits = []
    if rewritten:
        bits.append("%s scheduled-task file(s) now resolve the engine via `run --where` "
                    "instead of the demoted engine_root pointer: %s"
                    % (len(rewritten), ", ".join(rewritten)))
    for l in loud:
        bits.append("⚠️ " + l)
    prefix = "  ✅ " if apply_it else "  would rewrite: "
    return True, prefix + "; ".join(bits)
