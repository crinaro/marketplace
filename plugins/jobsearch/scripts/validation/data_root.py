"""Where the dataset is, for every `validation/` module: the one owner of `ROOT` and `DATA`.

Capability module of `validate_data.py`. `validate_data.py` resolved `ROOT = _profile_root()` and `DATA` (the
`CLAUDESEARCH_DATA_DIR` override, else `<ROOT>/data`) at import; a package module may not do that work at import
(design §3.2), so `validate_data.py` calls `bind(_profile_root(), os.environ.get("CLAUDESEARCH_DATA_DIR"))` at its
own import, at the same moment as before, and every reader reads `data_root.DATA` as an attribute of this module
(design §9.3: shared state stays in one module). A test points the validator at a scratch dataset by assigning
`data_root.DATA` (and restoring it) or calling `bind`. `SCRIPTS_DIR` is the scripts directory, one level above this
package: the directory `validate_data.py`'s own `os.path.dirname(os.path.abspath(__file__))` named."""

import os

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT = None
DATA = None


def bind(root, data_dir=None):
    """Point every `validation/` module at the profile `root`; `DATA` is `data_dir` when given, else `<root>/data`."""
    global ROOT, DATA
    ROOT = root
    DATA = data_dir or os.path.join(root, "data")
