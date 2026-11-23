"""field_shapes: which fields hold an object or an array, and the one place a CLI string becomes a stored value.

`docs/data_model.json` declares the shape of every container field in `shapes` (a store's top-level fields, and the
fields of one of its arrays' rows); a field absent from `shapes` is scalar. `record.py set`, `set-in` and `confirm --set`
read a value through `typed`: a declared object or array is parsed as JSON and must be that container; anything else is
text, brackets included, so `[CLAUDE] x` is a note and not a JSON parse error (dev #1001 / public #260). A bad value for a
declared container is a refusal naming the field, never a traceback.

The data model is read through `recording.row_checks.model`. `row_checks._object_shaped_fields` reads `shapes` itself
rather than calling `declared` here: this module imports `row_checks`, and an import back would close a cycle.

Capability module of record.py (an entry point over `recording/`)."""

import json
from recording.common import _Refused
from recording.row_checks import model

_EXAMPLE = {"object": '{"k": 1}', "array": '["a"]'}
_JSON_TYPE = {dict: "an object", list: "an array", str: "a string", bool: "a boolean", int: "a number", float: "a number"}


def shape_of(store, field, array=None):
    """`"object"`, `"array"` or None (a scalar field, an unknown store or an unknown array) for `field` of `store`, or of
    one row of `store`'s `array`."""
    spec = (model()["stores"].get(store) or {})
    if array:
        spec = (spec.get("arrays") or {}).get(array) or {}
    return (spec.get("shapes") or {}).get(field)


def declared(store):
    """`{field: shape}` for the top-level fields of `store` that hold an object or an array."""
    return dict((model()["stores"].get(store) or {}).get("shapes") or {})


def coerce(raw, shape=None):
    """A CLI gives strings; the store is typed. With no `shape` the scalar guesses (`true`, `false`, `null`, a whole
    number) and ANY other text is text, brackets included. With a `shape`, `null` or an empty string is None and anything
    else is JSON that must parse to an object (`"object"`) or an array (`"array"`); a ValueError names why it did not."""
    if shape is None:
        if raw in ("true", "True"):
            return True
        if raw in ("false", "False"):
            return False
        if raw in ("null", "None", ""):
            return None
        if raw.lstrip("-").isdigit():
            return int(raw)
        return raw
    if raw in ("null", "None", ""):
        return None
    value = json.loads(raw)
    want = dict if shape == "object" else list
    if not isinstance(value, want):
        raise ValueError("got %s" % _JSON_TYPE.get(type(value), "null"))
    return value


def typed(store, field, raw, array=None, current=None):
    """The stored value for `raw` written to `field` of `store` (or of a row of `store`'s `array`). `current` is the value
    the row holds now, when the caller has it. Raises `_Refused`, nothing written, when the field is declared an object or
    an array and `raw` is not valid JSON for it, or when the field is NOT declared and the row holds an object or an array
    there (an undeclared container is never overwritten with text: that is an engine defect, so it is reported)."""
    shape = shape_of(store, field, array)
    if shape is None and isinstance(current, (dict, list)):
        raise _Refused("%s holds %s on this row but is not declared in data_model.json; nothing written. This is an "
                       "engine defect: report it." % (field, _JSON_TYPE[type(current)]))
    try:
        return coerce(raw, shape)
    except ValueError as e:
        raise _Refused("%s is declared %s in data_model.json; the value is not valid JSON for it (%s). Quote it as one "
                       "argument, e.g. '%s'." % (field, shape, e, _EXAMPLE[shape]))
