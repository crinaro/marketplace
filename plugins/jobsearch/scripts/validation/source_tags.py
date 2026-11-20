"""Source tags: the tag grammar, uid normalisation, the per-store source-tag spec and its check.

Capability module of `validate_data.py` (S4a, moved unedited)."""

import re
from validation.basics import load


# ── dev #704 / public #154 -- the mail source tag: ONE grammar, ONE normalizer ───────────────
# `mail_client.Mailbox.search()` used to hand callers `bytes` uids, and every `"%s:%s:%s"` that
# built a source tag wrote the bytes' REPR -- `gmail:acct:b'101'` -- beside the clean
# `gmail:acct:101` the same message gets on a later run. The two keys name one message, so a
# "do I already hold this?" check that compared them raw said no and wrote a duplicate.
#
# The grammar below is also DECLARED in docs/data_model.json (`source_tag`), which the validator's
# V1 rule reads; a test pins the two to each other so they cannot drift.
SOURCE_TAG_PATTERN = r"^(gmail|mail|ats):[^:]+:\d+$"          # the clean shape (anchored)
SOURCE_TAG_PREFIX = r"^(gmail|mail|ats):"                      # "this value IS a mail tag"
# The repr of a bytes uid INSIDE a mail tag. Deliberately the TAG, not the bare `b'123'`: a message
# id minted before 0.66.0 may end in the repr (`<opp>-<person>-b'101'`), and the owner's id policy
# (dev #704 R1) is that ids are OPAQUE -- they keep their value, nothing is re-minted -- so a bare
# match would hold every such profile red after the migration that repaired it.
SOURCE_TAG_WRAPPED = r"(?:gmail|mail|ats):[^:\s|]+:b'\d+'"
SOURCE_TAG_PREFIXES = ("gmail", "mail", "ats")
# A tag inside FREE TEXT (an ask's `note`): the account is any run of non-space, non-`:`, non-`|`.
TAG_TOKEN_RE = re.compile(r"(?<!\w)(?:gmail|mail|ats):[^:\s|]+:(?:b'\d+'|\d+)")
_WRAPPED_UID_RE = re.compile(r"^b'(\d+)'$")
_TAG_RES = {}


def normalize_uid(uid):
    """A bare uid, with a `b'123'` wrapper stripped. Anything else is returned unchanged."""
    if isinstance(uid, str):
        m = _WRAPPED_UID_RE.match(uid)
        if m:
            return m.group(1)
    return uid


def normalize_source_tag(s, prefixes=SOURCE_TAG_PREFIXES):
    """The ONE key every "do I already hold this message" check compares (D1): a value of the
    shape `<tag>:<account>:<uid>` where `<uid>` is digits or the wrapped `b'<digits>'` is returned
    as `<tag>:<account>:<digits>`; ANY other value is returned unchanged (a LinkedIn thread URL,
    `record.py touched`, a path), so the function is safe to call on every `source`.

    `prefixes` widens the tag word for a caller whose keys carry another (`watch.py` queues
    `alert:`/`meet:`/`reply:` keys in `data/inbox.jsonl`); the default is the three mail tags."""
    if not isinstance(s, str):
        return s
    rx = _TAG_RES.get(prefixes)
    if rx is None:
        rx = _TAG_RES[prefixes] = re.compile(
            r"^(%s):([^:]+):(?:b'(\d+)'|(\d+))$" % "|".join(re.escape(p) for p in prefixes))
    m = rx.match(s)
    if not m:
        return s
    return "%s:%s:%s" % (m.group(1), m.group(2), m.group(3) or m.group(4))


def is_mail_tag(s):
    """True when `s` claims to be a mail source tag (clean OR wrapped) -- the gate that keeps a
    LinkedIn thread URL or `record.py touched` out of any source comparison."""
    return isinstance(s, str) and re.match(SOURCE_TAG_PREFIX, s) is not None


def tags_in_text(text):
    """The set of NORMALIZED mail tags found in free text (an ask's `note`)."""
    if not isinstance(text, str):
        return set()
    return {normalize_source_tag(t) for t in TAG_TOKEN_RE.findall(text)}


SOURCE_TAG_MODES = ("whole", "embedded")
SOURCE_TAG_MIGRATION = "m_0_66_0_uid_text"


def _strings_in(value):
    """Every string in `value`, descending into dicts (values) and lists."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            for x in _strings_in(v):
                yield x
    elif isinstance(value, (list, tuple)):
        for v in value:
            for x in _strings_in(v):
                yield x


def source_tag_spec(model):
    """(spec, defects) -- `docs/data_model.json`'s `source_tag` block, compiled, or the reasons it
    cannot be used. dev #704 / public #154 (V1) + R3: a rule whose declaration is missing, malformed
    or empty must say so LOUDLY, never read as a rule with nothing to check (a missing thing reads
    as an empty thing and gets reported as fact). `defects` is a list of sentences; `spec` is None
    unless it is empty.

    The block declares, per store, the fields that can carry a mail tag and HOW each is checked:
      whole     the value IS a tag (or legitimately something else: `messages.source` may be a
                path or a LinkedIn thread URL). If it starts with the mail prefix it must
                fullmatch `pattern`.
      embedded  the value, or any string nested in it, must contain no wrapped uid (`b'123'`):
                message ids that embed a uid, references to them, and free text (`asks.note`)
                into which a sweep writes a dedup tag."""
    block = (model or {}).get("source_tag") if isinstance(model, dict) else None
    if block is None:
        return None, ["docs/data_model.json has no `source_tag` block"]
    if not isinstance(block, dict):
        return None, ["docs/data_model.json `source_tag` is not an object"]
    defects, rx = [], {}
    for key in ("pattern", "prefix", "wrapped"):
        v = block.get(key)
        if not isinstance(v, str) or not v:
            defects.append("`source_tag.%s` is missing or not a non-empty string" % key)
            continue
        try:
            rx[key] = re.compile(v)
        except re.error as exc:
            defects.append("`source_tag.%s` is not a valid regex (%s)" % (key, exc))
    fields = block.get("fields")
    stores = (model.get("stores") or {}) if isinstance(model, dict) else {}
    declared = []
    if not isinstance(fields, dict):
        defects.append("`source_tag.fields` is missing or not an object")
    else:
        for store, flds in sorted(fields.items()):
            if store.startswith("_"):
                continue
            if store not in stores:
                defects.append("`source_tag.fields` names store %r, which docs/data_model.json "
                               "does not declare" % store)
                continue
            if not isinstance(flds, dict):
                defects.append("`source_tag.fields.%s` is not an object" % store)
                continue
            for fld, mode in sorted(flds.items()):
                if fld.startswith("_"):
                    continue
                if mode not in SOURCE_TAG_MODES:
                    defects.append("`source_tag.fields.%s.%s` has mode %r, not one of %s"
                                   % (store, fld, mode, "/".join(SOURCE_TAG_MODES)))
                elif fld not in (stores[store].get("fields") or []):
                    defects.append("`source_tag.fields.%s.%s` names a field the store does not "
                                   "declare" % (store, fld))
                else:
                    declared.append((store, fld, mode))
        if not declared and not defects:
            defects.append("`source_tag.fields` declares zero fields")
    if defects:
        return None, defects
    return {"declared": declared, "pattern": rx["pattern"], "prefix": rx["prefix"],
            "wrapped": rx["wrapped"]}, []


def check_source_tags(model, problems, loader=None):
    """dev #704 / public #154 (V1) -- refuse a wrapped uid (`b'123'`) in every declared field,
    naming the store, the row and the field. Returns `(stores, fields, rows)` actually checked, or
    None when the rule could not run (the reason is in `problems`, loudly -- R3).

    `loader(name)` returns `(rows, errors)` like this module's `load()`; the default reads the
    profile's own data directory. A store file that is legitimately absent (`briefs.jsonl`) is
    skipped and not counted."""
    spec, defects = source_tag_spec(model)
    if spec is None:
        for d in defects:
            problems.append("%s -- the wrapped-uid rule (V1) is OFF, so it checks NOTHING; declare "
                            "it in docs/data_model.json" % d)
        return None
    loader = loader or load
    loaded, fields_checked = {}, 0
    for store, fld, mode in spec["declared"]:
        if store not in loaded:
            loaded[store], _errs = loader("%s.jsonl" % store)
        rows = loaded[store]
        if rows is None:
            continue
        fields_checked += 1
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict) or fld not in row:
                continue
            label = "%s[%s]" % (store, row.get("id") if row.get("id") else "line %d" % i)
            value = row[fld]
            if mode == "whole":
                if isinstance(value, str) and spec["prefix"].match(value) \
                        and not spec["pattern"].fullmatch(value):
                    problems.append(
                        "%s: %s %r is a mail source tag that does not match %s -- a uid is "
                        "digits, never the repr of a bytes object; repaired by migration %s, "
                        "and a new write of this shape is refused"
                        % (label, fld, value, spec["pattern"].pattern, SOURCE_TAG_MIGRATION))
            else:
                bad = next((s for s in _strings_in(value) if spec["wrapped"].search(s)), None)
                if bad is not None:
                    problems.append(
                        "%s: %s carries a wrapped uid in %r -- a uid is digits, never the repr "
                        "of a bytes object; repaired by migration %s, and a new write of this "
                        "shape is refused" % (label, fld, bad, SOURCE_TAG_MIGRATION))
    n_stores = len([s for s in loaded if loaded[s] is not None])
    rows_checked = sum(len(loaded[s]) for s in loaded if loaded[s] is not None)
    return n_stores, fields_checked, rows_checked
