"""look_into: the leaf helpers of the "look into this company?" derivation, moved out of `your_move.py` unchanged by
`split_module.py move` (jobsearch 0.94.0, step P0; dev 1055, 1062; docs/design-role-first.md section 13). `your_move.py` keeps every
name importable.

  _parse_date, _load_jsonl, _root_cfg   a date, a store's rows and the profile's config, each read leniently (a missing store is empty).
  STAFFING_NAME_PATTERNS, COMPANY_KINDS the words that make a company name a staffing firm, and the three kinds a company can be.
  _host                                  the lower-cased host of a URL without its `www.`.

WHAT DID NOT MOVE, and why (measured 2026-11-25 with `scripts/check_segmentation.py`). The design names `company_candidates`,
`classify_companies` and `targets_review` for this module. Moved whole with the fourteen definitions they need
(`company_kind`, `role_link`, `_cfg_int`, ...), the module imports `lifecycle`, `pipeline_index`, `profile`, `graph` and
`portfolio_boards`, entry points, which a package may not (G5.L2 +3), runs `re.compile` at import (G3 +1), and grows the plugin's
largest import cycle from 39 to 44 (G6): `reach` joins it through any of `config_keys` (`_cfg_int`) or `posting_check`
(`role_link`). What is here is what moves without any of them: the cycle stays at 39.

Python 3.9+, standard library only."""

import datetime
import json
import os


def _parse_date(s):
    return datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _load_jsonl(root, name):
    path = os.path.join(root, "data", name)
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except OSError:
        pass
    return out


STAFFING_NAME_PATTERNS = ("staffing", "recruiting", "recruitment", "talent solutions", "headhunt")
COMPANY_KINDS = ("employer", "staffing", "aggregator")


def _host(url):
    import urllib.parse
    try:
        h = urllib.parse.urlparse(str(url or "")).netloc.lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _root_cfg(root):
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}
