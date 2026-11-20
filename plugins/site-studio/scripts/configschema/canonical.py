"""canonical: the one writer of `site/site.json`, and the engine-marker check `doctor.py` asks.

`canonical_text` and `write` emit the one canonical form (every known key, schema order, two-space indent, UTF-8,
one trailing LF) at the lowest schema that holds the site. `marker_state`, `marker_status` and
`is_canonical_marker` say whether the `"engine": "site-studio"` line is there and in canonical form."""

import json
import os
import tempfile
from configschema.configkeys import (
    CANONICAL_MARKER_LINE,
    CANON_ORDER,
    ENGINE_MARKER,
    RESUME_KEYS,
    WORK_KEYS,
)
from configschema.diagnostics import SiteConfigError
from configschema.model import SiteConfig, _no_dupes, parse_data
from configschema.treeschema import required_schema
from configschema.workcheck import validate_portfolio_settings


def canonical_text(cfg, files=None, interpretations=None, at_least=None, look_needs=None):
    """The one canonical form of a config: schema order, indent 2, one trailing LF. It writes the
    LOWEST schema that holds the site (`required_schema(cfg, files)`) and only that schema's keys:
    `siteKind` only when it is not `portfolio`, `labels` only when non-empty, `featuredFrom` only
    when `flags`. A `hub` or `custom` config leaves out `work` and `resume` when they hold
    nothing. `files` is the tree the caller holds (None: no tree feature is known); when it is given,
    so must `interpretations` be, and `look_needs` (`building.lookneeds.look_needs(files)`; see `required_schema`)."""
    if not isinstance(cfg, SiteConfig):
        cfg = parse_data(cfg)
    d = cfg.to_dict()
    d["schema"] = max(required_schema(cfg, files, interpretations, look_needs), at_least or 1)
    d["work"] = dict((k, d["work"][k]) for k in WORK_KEYS if k in d["work"])
    if d["resume"] is not None:
        d["resume"] = dict((k, d["resume"][k]) for k in RESUME_KEYS
                           if k in d["resume"] and not (k == "paper" and d["resume"][k] is None))
    if cfg.siteKind != "portfolio":
        if cfg.work == validate_portfolio_settings({}, "work"):
            del d["work"]
        if cfg.resume is None:
            del d["resume"]
    ordered = dict((k, d[k]) for k in CANON_ORDER if k in d)
    return json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"


def write(path, cfg, files=None, interpretations=None, at_least=None, look_needs=None):
    """Validate, then write `site.json` in canonical form, atomically. The only writer. `files` is
    the tree the caller holds, so the schema written is the one the whole site needs (with `files`,
    pass `interpretations` too: `content.interpretation_reasons(files)`)."""
    if not isinstance(cfg, SiteConfig):
        cfg = parse_data(cfg)
    text = canonical_text(cfg, files, interpretations, at_least, look_needs)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".site.json.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


MARKER_OK, MARKER_INVALID, MARKER_ABSENT, MARKER_NONCANONICAL = "ok", "invalid", "absent", "non-canonical"


def marker_state(text):
    """Return (state, reason): WHICH way a site.json's marker is wrong, so the one caller that must give
    different advice for each (doctor.py) never has to read the reason's wording. `state` is one of
    MARKER_OK (the file parses with engine "site-studio" AND the marker is written in canonical form,
    the form the SessionStart prefilter greps for), MARKER_INVALID (not JSON), MARKER_ABSENT (no
    `"engine": "site-studio"` at all: a site.json site-studio did not make and does not manage yet, the
    one to ADOPT, dev #855) or MARKER_NONCANONICAL (the marker is there but respelled, the one a re-save
    fixes)."""
    try:
        data = json.loads(text, object_pairs_hook=_no_dupes)
    except (ValueError, SiteConfigError):
        return MARKER_INVALID, "site.json is not valid JSON"
    if not isinstance(data, dict) or data.get("engine") != ENGINE_MARKER:
        return MARKER_ABSENT, "site.json has no \"engine\": \"site-studio\" marker"
    if CANONICAL_MARKER_LINE not in text.split("\n"):
        return MARKER_NONCANONICAL, ("the engine marker is not in canonical form; re-save site.json with "
                                     "site-studio so the session-start check can find it")
    return MARKER_OK, "canonical"


def marker_status(text):
    """Return (ok, reason). ok is True only when `marker_state` is MARKER_OK. A legal-JSON respelling
    (`"engine" : "site-studio"`) parses fine and returns False, so doctor can ask for a re-save
    instead of the hook silently not starting; a site.json with no marker at all returns False too, and
    doctor tells that one to adopt (see `marker_state`)."""
    state, reason = marker_state(text)
    return state == MARKER_OK, reason


def is_canonical_marker(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return marker_status(fh.read())[0]
    except (OSError, UnicodeDecodeError):
        return False
