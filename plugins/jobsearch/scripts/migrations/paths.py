"""Where the engine's `scripts/` directory is, for the migrations that name a sibling file or the plugin's `docs/`.

Capability module of `migrate.py`'s `migrations/` package. `HERE` has the value `migrate.py`'s own `HERE` had before
the split: the scripts directory, one level above this package."""

import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
