"""Where the journal's code is: the scripts directory, for the two functions that locate this plugin's own manifest and
checkout (`_public_repo`, `_private_repo`).

Capability module of `journal.py` (S4a). They read `os.path.dirname(os.path.abspath(__file__))` inside `journal.py`, which
named the scripts directory; inside a package that expression would name the package, so they read `SCRIPTS_DIR`."""

import os

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
