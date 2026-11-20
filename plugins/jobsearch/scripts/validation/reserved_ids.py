"""Reserved ids and the stores keyed by id (`check_reserved_ids`).

Capability module of `validate_data.py` (S4a, moved unedited)."""

from validation.basics import load


# dev #764 / public #162 (criterion 764-3) -- RESERVED IDS. `record.py create auto` is a create-time
# sentinel meaning "mint me an id"; on a store with no minting branch it used to be written LITERALLY,
# and a dependent row then pointed at the string "auto". The id of a stored row is never the sentinel
# and never empty. ONE rule over every id-keyed store, the store list DERIVED from the model's own
# `id_field` declarations (never hand-listed: a store added to docs/data_model.json is covered the day
# it is declared). A missing `id` key is the required-field rule's finding, not this one.
RESERVED_IDS = ("auto",)


def id_keyed_stores(model):
    """(store names, defects) -- every store `docs/data_model.json` declares with a non-null
    `id_field`, as `(name, id_field)` pairs sorted by name. `defects` is a list of sentences; the
    store list is empty when the model cannot be used, and an empty list is itself a defect (a
    rule whose declaration yields nothing must say so, never read as a rule with nothing to
    check)."""
    stores = (model or {}).get("stores") if isinstance(model, dict) else None
    if not isinstance(stores, dict):
        return [], ["docs/data_model.json has no `stores` object"]
    found = []
    for name, spec in sorted(stores.items()):
        if name.startswith("_") or not isinstance(spec, dict):
            continue
        fld = spec.get("id_field")
        if isinstance(fld, str) and fld:
            found.append((name, fld))
    if not found:
        return [], ["docs/data_model.json declares zero id-keyed stores"]
    return found, []


def check_reserved_ids(model, problems, loader=None):
    """dev #764 (764-3) -- refuse the reserved id `auto` and an empty id in every id-keyed store,
    naming the store and the row. Returns `(stores, rows)` actually checked, or None when the rule
    could not run (the reason is in `problems`, loudly). `loader(name)` returns `(rows, errors)`
    like this module's `load()`; a store file that is legitimately absent is skipped, not counted."""
    declared, defects = id_keyed_stores(model)
    if defects:
        for d in defects:
            problems.append("%s -- the reserved-id rule (764-3) is OFF, so it checks NOTHING; "
                            "declare each store's `id_field` in docs/data_model.json" % d)
        return None
    loader = loader or load
    n_stores = n_rows = 0
    for store, fld in declared:
        rows, _errs = loader("%s.jsonl" % store)
        if rows is None:
            continue
        n_stores += 1
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict) or fld not in row:
                continue
            n_rows += 1
            v = row[fld]
            if v is None or (isinstance(v, str) and not v.strip()):
                problems.append(
                    "%s[line %d]: %s is empty (%r) -- a stored row's id is never empty; supply "
                    "one with `record.py create %s <id>`" % (store, i, fld, v, store))
            elif isinstance(v, str) and v.strip() in RESERVED_IDS:
                problems.append(
                    "%s[%s]: %s %r is reserved -- it is `record.py create`'s placeholder for "
                    "\"mint me an id\", never a stored id; any row pointing at it points at "
                    "nothing. Repaired by migration m_0_76_1_legacy_placeholders, and a new "
                    "write of this id is refused" % (store, v, fld, v))
    return n_stores, n_rows
