#!/usr/bin/env python3
"""platform_check.py -- the one Windows refusal every site-studio entry point shares (dev #835, design
5.4, gate-keeper D8). Python 3.9, standard library only.

0.1.0 supports macOS and Linux. Windows is refused in ONE sentence, first, at every command-line entry
point (build, deploy, preview, adopt, check_site, review_record, repos; browser.py and doctor.py say the
same sentence in their own words), so a person on Windows is told what is true instead of meeting a
POSIX-only failure halfway through a build. The deployment audit found that only browser.py and
doctor.py checked `os.name` at all; the others ran unrefused on Windows.

Each entry point's `main` begins:

    rc = platform_check.windows_refusal_rc("build.py")
    if rc is not None:
        return rc

`windows_refusal_rc` reads `os.name` at CALL time (a test patches it to "nt"), prints the sentence to
stderr and returns 1; on any other platform it returns None and does nothing. The text is pinned equal
to browser.WINDOWS_REFUSAL by tests/test_windows_refusal.py.
"""
import os
import sys

WINDOWS_REFUSAL = "site-studio 0.1.0 runs on macOS and Linux; Windows is not supported yet."


def is_windows():
    return os.name == "nt"


def windows_refusal_rc(prog=None):
    """The exit code (1) after printing the one-sentence refusal on Windows, else None."""
    if not is_windows():
        return None
    print(WINDOWS_REFUSAL, file=sys.stderr)
    return 1
