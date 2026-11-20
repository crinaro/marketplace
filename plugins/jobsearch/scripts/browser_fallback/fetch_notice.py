"""fetch_notice: the `asks.jsonl` notice row that discloses the automatic posting fetch (design-browser-fallback.md 6.4).

Capability module of `posting_fetch.py`, which re-exports these names (the cap and the interval the text states are `fetch_limits`). It is how the disclosure reaches a user who never ran the setter: a migration message reaches neither a new installer nor a
scheduled first run, so the disclosure is a stored row. Built here only; the setter, the migration and `init_profile.py` all write
it through `notice_row`."""

import json
import os
import _atomic
from browser_fallback.fetch_limits import MIN_INTERVAL_S, POSTING_FETCH_CAP

NOTICE_ID = "ask-posting-fetch-auto"
NOTICE_VALUES = ("absent", "on", "off")                  # the key's value the row's text is written for
NOTICE_REMEDY = ("the notice row %s is missing from data/asks.jsonl: run `posting_fetch.py --set auto` (it writes the row and keeps "
                 "the automatic fetch) or `posting_fetch.py --set on`, or `--set off` to stop it" % NOTICE_ID)


def notice_texts():
    """`{value: (title, ask)}` for the three key values, stating the cap per run and the seconds between requests."""
    terms = ("It sends one GET per role to LinkedIn's public guest posting address, with only a User-Agent naming this plugin "
             "(no cookie, no sign-in), at most %d per run and at least %d seconds apart. LinkedIn's robots.txt disallows "
             "that path and LinkedIn User Agreement section 8.2 restricts automated access, so using it is your decision "
             "(terms: docs/user/jobsearch/posting-fetch.md)." % (POSTING_FETCH_CAP, MIN_INTERVAL_S))
    return {
        "absent": ("A LinkedIn job posting is now read automatically when no browser could read it",
                   "When neither the Browser pane nor Claude in Chrome could read a LinkedIn posting during a run, this plugin reads "
                   "its public logged-out page instead, only from a host your sandbox settings allow. " + terms +
                   " `posting_fetch.py --set off` stops it. Resolving this ask changes nothing."),
        "off": ("The automatic LinkedIn posting fetch is off",
                "You turned the posting fetch off, and that also stops the automatic fetch: no browser-fallback GET is sent to "
                "LinkedIn. `posting_fetch.py --set auto` allows it again. " + terms + " Resolving this ask changes nothing."),
        "on": ("The LinkedIn posting fetch you turned on also runs automatically",
               "The posting fetch you turned on now also runs in the case neither the Browser pane nor Claude in Chrome could read a "
               "LinkedIn posting, only from a host your sandbox settings allow. " + terms +
               " `posting_fetch.py --set off` stops it. Resolving this ask changes nothing."),
    }


def notice_row(value, today, created=None):
    """The ONE `asks.jsonl` row, `kind: system`, stable id NOTICE_ID, for the key value `value` (`absent`, `on` or `off`). It has no
    `resolves_when`, so no automatic pass removes it, and it asks for no decision: the text says what runs and how to stop it."""
    if value not in NOTICE_VALUES:
        raise ValueError("a notice row is written for one of %s, not %r" % (", ".join(NOTICE_VALUES), value))
    title, ask = notice_texts()[value]
    return {"id": NOTICE_ID, "kind": "system", "title": title, "ask": ask, "created": created or today, "act_by": None,
            "opp_id": None, "channel_id": None, "resolves_when": None, "resolved_on": None, "resolution": None,
            "trigger_kind": None, "trigger_ref": None, "note": None}


def _asks_path(root):
    return os.path.join(root, "data", "asks.jsonl")


def read_asks(root):
    """`(rows, None)`, `([], None)` when the file does not exist, or `(None, why)` when it exists and cannot be read."""
    path = _asks_path(root)
    if not os.path.exists(path):
        return [], None
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        return None, "asks.jsonl line %d is not an object" % n
                    rows.append(row)
    except (OSError, ValueError) as e:
        return None, "asks.jsonl cannot be read (%s)" % e
    return rows, None


def notice_exists(root):
    """`(True, None)` when a row with NOTICE_ID exists, WHATEVER its status (open, resolved or closed: resolving the notice is the
    natural answer to it and never stops the fetch), else `(False, why)`. An `asks.jsonl` that cannot be read is `(False, why)`."""
    rows, why = read_asks(root)
    if why:
        return False, why
    return (True, None) if any(r.get("id") == NOTICE_ID for r in rows) else (False, "no row %s in data/asks.jsonl" % NOTICE_ID)


def write_notice_row(root, value, today):
    """Write the notice row for `value` BY ID, in place when one exists, else appended. An existing row keeps its `created`,
    `resolved_on` and `resolution`: this never reopens a row the owner resolved. Raises ValueError when asks.jsonl cannot be read."""
    rows, why = read_asks(root)
    if why:
        raise ValueError(why)
    have = next((r for r in rows if r.get("id") == NOTICE_ID), None)
    new = notice_row(value, today, created=(have or {}).get("created"))
    if have is not None:
        new["resolved_on"], new["resolution"] = have.get("resolved_on"), have.get("resolution")
    out = [new if r is have else r for r in rows] if have is not None else rows + [new]
    os.makedirs(os.path.dirname(_asks_path(root)), exist_ok=True)
    _atomic.write_jsonl(_asks_path(root), out)
