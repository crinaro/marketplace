#!/usr/bin/env python3
"""Where a role is, in miles: place text -> coordinates -> great-circle distance.

jobsearch 0.70.0, dev #729 / public #157 (docs/design-location-screen.md §2, R1). Until now the
screen could only answer "is this place NAMED by a commute anchor", so a role in a city nobody had
ever named could never be called far: `within_commute` answered None, the comp rule asked a
question, and the geography rule kept the role when relocation was open. A profile that screened 75
captured roles removed none of them. This module is the distance half of the answer; the decision
lives in `profile.commute_outcome`.

THREE FUNCTIONS, ONE SOURCE
---------------------------
    parse_place(text)             -> [(city_norm, region)] or None
    coords(city_norm, region)     -> (lat, lon) or None
    haversine_miles(a, b)         -> float

`coords` is the only function that touches data, and it reads exactly one file:
`<engine_root>/places/us_places.csv.gz` (columns `name,state,lat,lon`; the US Census Bureau 2024
Gazetteer places file, public domain, built by `build_places_table.py`; see `places/SOURCE.md`).
There is NO environment variable, NO profile path and NO fixture fallback on an installed engine:
the table is part of the plugin or it is absent. A caller that wants a different table passes one
in (`table=`), which is how every test supplies a table of fictional places.

ABSENT IS NOT EMPTY. A table that is missing, unreadable or has zero rows is reported by
`resolve_table` as a REASON, never as "the place is not in the table": `profile.commute_outcome`
turns it into `hold="place-table"` and the screen prints `PLACE TABLE MISSING (<path>): distance not
checked`. Folding it into "unresolvable" would claim a role is in an unknown place when the truth is
that nobody looked (the marketplace's signature failure: a missing thing read as an empty thing).

`parse_place` IS STRICT (OURS). It accepts `City, ST`, `City, State name` and `City, ST, <country>`
(a US country name only), with a trailing ZIP and any parenthesised note tolerated; it splits several
places on `;` or `|` and on nothing else; it refuses (None) any text carrying a `remote` or `hybrid`
token, any text with no comma, any region it cannot map, and a list in which ANY part fails. A
refusal is None, which the caller reports as unresolvable: loud, never a guess.

Python 3.9+. Standard library only.
"""

import csv
import gzip
import math
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _root

EARTH_RADIUS_MILES = 3958.8

# (code, name): 50 states, DC and Puerto Rico -- exactly the Gazetteer's coverage.
_STATES = (
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("DC", "District of Columbia"), ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"),
    ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("PR", "Puerto Rico"), ("RI", "Rhode Island"),
    ("SC", "South Carolina"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"),
    ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"),
    ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
)
STATE_CODES = frozenset(code for code, _n in _STATES)
_STATE_BY_NAME = {name.lower(): code for code, name in _STATES}
_STATE_BY_NAME["washington dc"] = "DC"
_STATE_BY_NAME["washington d.c."] = "DC"

_US_NAMES = frozenset({"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"})
_TOKEN_RE = re.compile(r"\b(remote|hybrid)\b", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
_ZIP_RE = re.compile(r"^(.*?)\s+\d{5}(?:-\d{4})?$")

TABLE_RELATIVE = os.path.join("places", "us_places.csv.gz")


def norm_city(name):
    """The one normalisation a city name is compared in: accents stripped, lower-cased, periods
    dropped, `saint` -> `st`, whitespace collapsed. The table is keyed by it on load, so a posting's
    "St. Louis" and the Gazetteer's "St. Louis" meet, and so do "Saint Paul" and "St. Paul"."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace(".", "")
    text = " ".join(text.split())
    if text.startswith("saint "):
        text = "st " + text[len("saint "):]
    return text


def _region(raw):
    """The state code for `raw` (an abbreviation or a full name), or None."""
    text = " ".join(str(raw or "").split())
    if not text:
        return None
    m = _ZIP_RE.match(text)
    if m:
        text = m.group(1)
    if len(text) == 2 and text.upper() in STATE_CODES:
        return text.upper()
    return _STATE_BY_NAME.get(text.lower())


def parse_place(text):
    """`[(city_norm, region_code), ...]` for a location string, or None when it is not a concrete
    place this module can read. See the module docstring for the grammar. Never raises."""
    if not isinstance(text, str) or not text.strip():
        return None
    if _TOKEN_RE.search(text):
        return None
    out = []
    for part in re.split(r"[;|]", text):
        part = " ".join(_PAREN_RE.sub(" ", part).split())
        if not part:
            return None
        fields = [f.strip() for f in part.split(",")]
        if len(fields) < 2 or len(fields) > 3 or not all(fields):
            return None
        if len(fields) == 3 and fields[2].lower() not in _US_NAMES:
            return None
        city, region = norm_city(fields[0]), _region(fields[1])
        if not city or region is None:
            return None
        if (city, region) not in out:
            out.append((city, region))
    return out or None


def haversine_miles(a, b):
    """Great-circle distance in statute miles between two `(lat, lon)` pairs in degrees. It "cannot
    be guaranteed correct to better than 0.5%", which is small next to a city centroid's error; a
    straight line is also a LOWER BOUND on any road distance, which is what makes `outside` a proof
    (design §3.3)."""
    lat1, lon1, lat2, lon2 = (math.radians(float(v)) for v in (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


def table_path():
    """Where the shipped table lives: beside the scripts, under the ENGINE root. Never a profile."""
    return os.path.join(_root.engine_root(), TABLE_RELATIVE)


def make_table(rows):
    """A table from `(name, state, lat, lon)` rows, keyed the way `coords` looks places up. The one
    constructor: the loader and every test that supplies a table of fictional places use it."""
    table = {}
    for name, state, lat, lon in rows:
        key = (norm_city(name), str(state).upper())
        if key[0] and key not in table:
            table[key] = (float(lat), float(lon))
    return table


def load_table(path=None):
    """`(table, problem)`: the table read from `path` (default `table_path()`), or `(None, why)`.
    A file that is absent, unreadable, malformed or has zero usable rows is a PROBLEM in plain words,
    never an empty table."""
    path = path or table_path()
    if not os.path.isfile(path):
        return None, "the file does not exist"
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or [f.strip() for f in reader.fieldnames] != [
                    "name", "state", "lat", "lon"]:
                return None, "its header is not name,state,lat,lon"
            rows = [(r["name"], r["state"], r["lat"], r["lon"]) for r in reader]
    except (OSError, EOFError, ValueError, KeyError, csv.Error, UnicodeDecodeError) as e:
        return None, "it cannot be read (%s)" % e
    try:
        table = make_table(rows)
    except ValueError as e:
        return None, "a coordinate is not a number (%s)" % e
    if not table:
        return None, "it has no rows"
    return table, None


_DEFAULT = {}


def default_table():
    """`(table, problem)` for the shipped table, read once per process."""
    if "v" not in _DEFAULT:
        _DEFAULT["v"] = load_table()
    return _DEFAULT["v"]


def resolve_table(table=None):
    """`(table, problem)` for a caller's `table` argument: an injected dict is used as given (an
    EMPTY one is a problem, like an empty file); None means the shipped table."""
    if table is None:
        return default_table()
    if not table:
        return None, "the table is empty"
    return table, None


def coords(city_norm, region, table=None):
    """`(lat, lon)` for a normalised city and a state code, or None when the table does not know
    the place OR there is no table (a caller that must tell those apart reads `resolve_table`)."""
    tbl, _problem = resolve_table(table)
    if tbl is None:
        return None
    return tbl.get((city_norm, str(region).upper()))


def anchor_coords(anchor, table=None):
    """`(lat, lon)` of one `geography.commute_anchors[]` entry, or None when it cannot be located:
    the anchor's own `lat`/`lon` (OD-1 option 4) win; otherwise its `place` is read through
    `parse_place` and `coords`. Values that are not numbers in range are not used (the validator in
    `config_keys.validate_anchor_geo` reports them; this never raises)."""
    if not isinstance(anchor, dict):
        return None
    lat, lon = anchor.get("lat"), anchor.get("lon")
    if lat is not None or lon is not None:
        ok = (all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon))
              and -90 <= lat <= 90 and -180 <= lon <= 180)
        return (float(lat), float(lon)) if ok else None
    parsed = parse_place(anchor.get("place"))
    if not parsed:
        return None
    return coords(parsed[0][0], parsed[0][1], table)
