"""valuecheck: the small typed readers of one JSON value (`_str`, `_bool`, `_number`, `_str_list`, `_rel_path` ...).
Each RAISES one `SiteConfigError` carrying its own `Problem`; the collector turns that into an entry in the list
`problems()` returns and carries on, so a config with six faults reports six."""

from configschema.diagnostics import SiteConfigError
import github_url


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "number"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


# The two site.json values that may be a URL a person pasted with a credential in it
# (a clone URL with userinfo in front of the host); a problem line must never echo one (dev #851-#857 follow-up).
_URL_FIELDS = ("publicRepo", "previewUrl")


def _shown(value):
    """`value` with any userinfo removed, for a problem line or an error: `github_url.redact`, applied
    to the text between its surrounding whitespace (redact anchors at the start). Fails closed: if the
    redactor cannot be imported, nothing of the value is shown."""
    try:
        core = value.strip()
        return value.replace(core, github_url.redact(core), 1) if core else value
    except Exception:
        return "<not shown>"


def _bad(where, want, v):
    raise SiteConfigError("site.json: '%s' must be %s, got %s" % (where, want, _kind(v)),
                          path=where, found=_kind(v), expected=want,
                          fix="set '%s' to %s" % (where, want))


def _str(v, where, optional=False):
    if v is None and optional:
        return None
    if not isinstance(v, str):
        _bad(where, "a string", v)
    if not v.strip():
        raise SiteConfigError("site.json: '%s' must not be empty" % where, path=where, found="empty",
                              expected="a non-empty string", fix="give '%s' a value, or remove it" % where)
    if v != v.strip():
        raise SiteConfigError("site.json: '%s' has leading or trailing whitespace" % where, path=where,
                              found=repr(_shown(v) if where in _URL_FIELDS else v),
                              expected="no surrounding whitespace",
                              fix="remove the spaces around the value of '%s'" % where)
    return v


def _text(v, where):
    """A free-text string that may be empty."""
    if not isinstance(v, str):
        _bad(where, "a string", v)
    return v


def _one_line(v, where):
    """A non-empty single line of text (no line break)."""
    v = _str(v, where)
    if "\n" in v or "\r" in v:
        raise SiteConfigError("site.json: '%s' must be one line" % where, path=where, found="several lines",
                              expected="one line of text", fix="write '%s' on one line" % where)
    return v


def _bool(v, where):
    if not isinstance(v, bool):
        _bad(where, "true or false", v)
    return v


def _str_list(v, where, collect=None):
    """A list of non-empty strings. With `collect`, every bad item is recorded and the good ones are
    returned; without it, the first bad item raises."""
    if not isinstance(v, list):
        _bad(where, "a list of strings", v)
    out = []
    for i, item in enumerate(v):
        if collect is None:
            out.append(_str(item, "%s[%d]" % (where, i)))
        else:
            ok, val = collect.run(_str, item, "%s[%d]" % (where, i))
            if ok:
                out.append(val)
    return out


def _number(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(where, "a number", v)
    if v <= 0:
        raise SiteConfigError("site.json: '%s' must be greater than zero" % where, path=where,
                              found=v, expected="a number above zero", fix="set '%s' above zero" % where)
    return v


def _rel_path(v, where):
    v = _str(v, where)
    if v.startswith("/") or "\\" in v or ".." in v.split("/") or "//" in v or v.endswith("/"):
        raise SiteConfigError("site.json: '%s' must be a relative path inside the repo" % where,
                              path=where, found=v, expected="a relative path inside the repo",
                              fix="write '%s' as a path such as content/x, with no leading or trailing /"
                              % where)
    return v


def _needs_schema_2(where):
    return SiteConfigError("site.json: '%s' needs \"schema\": 2" % where, path=where,
                           found="schema 1", expected="schema 2",
                           fix="set \"schema\": 2 in site/site.json (a save by site-studio does this)")


def _needs_schema_4(where, have):
    """A schema-4 key under a lower declared schema: 0.3.x refuses it as an unknown key, and 0.4.0 refuses it
    naming the schema (a hand edit cannot quietly make a file an older install then misreads)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 4" % where, path=where,
                           found="schema %d" % have, expected="schema 4",
                           fix="set \"schema\": 4 in site/site.json (a save by site-studio does this)")
