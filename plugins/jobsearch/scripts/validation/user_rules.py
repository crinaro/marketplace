"""The profile's two root JSON files as `validate_data` reads them: `read_beside_data` (config.json or user.json, from the
directory that holds `data/`), and `check_user_file`, user.json's `affiliations` (jobsearch 0.91.0, design-build-reach.md 7.1).

`affiliations` absent is a state, never a gap: "not asked", which the next attended run raises once (owner O6). A present value
is run through `reach.affiliations.check`, the one strict parser, and every refusal is a problem: an unreadable value is loud,
never read as "no affiliations". A user.json that is present but not a readable JSON object is a problem too, because the field
cannot be read. Only a user.json that is not there at all (a test pointing `DATA` at a scratch directory, a dry-run copy of the
data directory) is `NOT CHECKED`, said on the summary line so it never reads as a pass.

Capability module of `validate_data.py`. Python 3.9+, standard library only."""

import json
import os
from reach import affiliations as _aff


def read_beside_data(data_dir, name):
    """`(obj, None)` for the JSON object `name` in the directory holding `data_dir`, or `({}, why)` when it cannot be used:
    absent, not readable JSON, or not an object. The `why` texts are the summary-line wording `validate_data` has printed for
    config.json since 0.67.0."""
    try:
        with open(os.path.join(os.path.dirname(data_dir), name), encoding="utf-8") as fh:
            obj = json.load(fh)
    except OSError:
        return {}, "no %s beside data/" % name
    except ValueError as e:
        return {}, "%s is not readable JSON (%s)" % (name, e)
    if not isinstance(obj, dict):
        return {}, "%s is not an object" % name
    return obj, None


def check_user_file(data_dir, problems):
    """Check user.json's `affiliations` (beside `data_dir`), appending each problem. Returns the summary line to print."""
    user, why = read_beside_data(data_dir, "user.json")
    if why is not None:
        if why.startswith("no "):
            return "Affiliations: NOT CHECKED -- %s" % why
        problems.append("user.json: %s, so its affiliations cannot be read" % why)
        return "Affiliations: NOT CHECKED -- %s (a problem above)" % why
    if "affiliations" not in user:
        return "Affiliations: not asked (absent from user.json; the next attended run asks once)"
    found = _aff.check(user["affiliations"])
    problems.extend("user.json: %s" % p for p in found)
    if found:
        return "Affiliations: %d problem(s) above" % len(found)
    n = len(user["affiliations"])
    return "Affiliations: asked, none ([] checked)" if n == 0 else "Affiliations: %d entr%s checked" % (n, "y" if n == 1 else "ies")
