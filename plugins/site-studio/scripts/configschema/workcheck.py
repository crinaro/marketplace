"""workcheck: the checks of the portfolio settings (`work`, and a `page.md`'s portfolio keys) and of the resume
section, and the helpers that read their label maps."""

import json
from configschema.configkeys import (
    BUILTIN_PIECE_KEYS,
    CARD_ALT_TITLE,
    CARD_IMAGES,
    CARD_NUMBER_FORMATS,
    COUNT_ANY,
    COUNT_FORMS,
    COUNT_FORMS_RESERVED,
    DEFAULT_RESUME_PATH,
    DEFAULT_RESUME_PDF,
    LABEL_PARTS,
    PAPERS,
    RESUME_HEADINGS,
    RESUME_KEYS,
    RESUME_LAYOUTS,
    SCHEMA_MAX,
    V4_WORK_KEYS,
    V5_WORK_KEYS,
    V6_LABEL_PARTS,
    V6_WORK_KEYS,
    WORK_KEYS,
    _KEY_RE,
)
from configschema.diagnostics import SiteConfigError, _Collector
from configschema.sectioncheck import needs_schema_6
from configschema.valuecheck import (
    _bad,
    _bool,
    _needs_schema_2,
    _needs_schema_4,
    _one_line,
    _rel_path,
    _shown,
    _str,
    _text,
)


def _pair_key(item):
    """The key of a `[key, label]` pair or a `{"key": ..., "label": ...}` object, else None. These are
    the shapes an older hand-made site.json used for a display label (section 5); adopt converts them."""
    if (isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) and x.strip() for x in item)):
        return item[0]
    if (isinstance(item, dict) and set(item) == {"key", "label"}
            and all(isinstance(x, str) and x.strip() for x in item.values())):
        return item["key"]
    return None


def pair_label(item):
    """(key, label) of a `[key, label]` pair or `{"key", "label"}` object, else None."""
    k = _pair_key(item)
    if k is None:
        return None
    return (k, item[1] if isinstance(item, list) else item["label"])


def _labels(raw, where, col, schema=SCHEMA_MAX):
    """The `labels` map of a portfolio-settings object: {meta: {key: label}, groups: {name: label}}, and at schema 6
    `counts` (`_counts`), present only when it holds a word.
    Both parts optional. Values are non-empty strings. Returns the fully-defaulted shape; every fault
    is recorded in `col`."""
    out = {"meta": {}, "groups": {}}
    if not isinstance(raw, dict):
        col.run(_bad, where, "an object", raw)
        return out
    for k in raw:
        if k in V6_LABEL_PARTS:
            if schema < 6:
                col.problems.append(needs_schema_6("%s.%s" % (where, k), schema).problem)
            else:
                counts = _counts(raw[k], "%s.%s" % (where, k), col)
                if counts:
                    out[k] = counts
        elif k not in LABEL_PARTS:
            col.add("site.json: unknown key '%s.%s'" % (where, k), "%s.%s" % (where, k), "unknown key",
                    "one of: " + ", ".join(LABEL_PARTS + V6_LABEL_PARTS), "remove '%s.%s'" % (where, k))
    for part in LABEL_PARTS:
        if part not in raw:
            continue
        m = raw[part]
        if not isinstance(m, dict):
            col.run(_bad, "%s.%s" % (where, part), "an object", m)
            continue
        for key, label in m.items():
            if part == "meta" and not _KEY_RE.match(key):
                col.add("site.json: '%s.meta' labels '%s', which is not a plain key name" % (where, key),
                        "%s.meta" % where, key, "a plain key name", "label a key that appears in meta")
                continue
            if not key.strip():
                col.add("site.json: '%s.%s' has an empty key" % (where, part), "%s.%s" % (where, part),
                        "empty key", "a key name", "remove the empty key")
                continue
            ok, val = col.run(_str, label, "%s.%s['%s']" % (where, part, key))
            if ok:
                out[part][key] = val
    return out


def _counts(raw, where, col):
    """`labels.counts` (schema 6, design-adopt-parity-2 sections 3.2 and 4.2): {group value or "*": {"one": word,
    "other": word}}, either member absent. The member names are CLDR's plural categories; 0.6.0 prints two forms, so
    `zero`, `two`, `few` and `many` are reserved: refused, naming the release, so a later release can read them as its
    own K reason. Whether a group value is one of `groups` is the caller's check. Returns the good entries."""
    if not isinstance(raw, dict):
        col.run(_bad, where, "an object", raw)
        return {}
    out = {}
    for group, forms in raw.items():
        at = "%s['%s']" % (where, group)
        if not isinstance(group, str) or not group.strip():
            col.add("site.json: '%s' has an empty key" % where, where, "empty key", "a group value or \"*\"",
                    "remove the empty key")
            continue
        if not isinstance(forms, dict):
            col.run(_bad, at, "an object such as {\"one\": \"piece\", \"other\": \"pieces\"}", forms)
            continue
        good = {}
        for form, word in forms.items():
            if form in COUNT_FORMS_RESERVED:
                col.add("site.json: '%s' names the plural form '%s': site-studio 0.6.0 prints two forms (`one`, `other`)"
                        % (at, form), "%s.%s" % (at, form), form, "one or other",
                        "write the word under \"other\" (every number but 1), or under \"one\"")
            elif form not in COUNT_FORMS:
                col.add("site.json: unknown key '%s.%s'" % (at, form), "%s.%s" % (at, form), "unknown key",
                        "one of: " + ", ".join(COUNT_FORMS), "remove '%s.%s'" % (at, form))
            else:
                ok, val = col.run(_one_line, word, "%s.%s" % (at, form))
                if ok:
                    good[form] = val
        if good:
            out[group] = good
    return out


def labels_nonempty(labels):
    return bool(labels) and any(labels.get(p) for p in LABEL_PARTS + V6_LABEL_PARTS)


def _list_of_keys(raw, k, where, col):
    """`meta`, `cardMeta`, `groups` or `required`: a list of strings. A `[key, label]` pair (or the
    object form) is a problem adopt can fix, and its key is kept so later checks do not cascade."""
    v = raw[k]
    here = "%s.%s" % (where, k)
    if not isinstance(v, list):
        col.run(_bad, here, "a list of strings", v)
        return []
    out = []
    for i, item in enumerate(v):
        at = "%s[%d]" % (here, i)
        if k in ("meta", "cardMeta", "groups") and not isinstance(item, str):
            key = _pair_key(item)
            if key is not None:
                col.add("site.json: '%s' is a [key, label] pair; %s holds plain keys, and a display label "
                        "goes in %s.labels (adopt converts this)" % (at, k, where), at,
                        json.dumps(item), "a plain key", "move the label into %s.labels.%s"
                        % (where, "groups" if k == "groups" else "meta"), True)
                out.append(key)
                continue
        ok, val = col.run(_str, item, at)
        if ok:
            out.append(val)
    return out


def _needs_schema_5(where, have):
    """A schema-5 setting under a lower declared schema: 0.4.x refuses it as an unknown key, and 0.5.0 refuses it naming
    the schema (design-movement-view section 3.1 rule 1)."""
    return SiteConfigError("site.json: '%s' needs \"schema\": 5" % where, path=where,
                           found="schema %d" % have, expected="schema 5",
                           fix="run `python3 build.py raise-schema --to 5`, which lists what the page changes before "
                               "it writes schema 5")


def _v5_settings(raw, where, schema, out, col):
    """The schema-5 portfolio settings (design-movement-view section 3.2), each stored only when set: `cardImage`
    ("cover" or "photo"), `cardKicker` (a piece key's name: not a built-in key, and not also in `cardMeta`, where it
    would print twice) and `cardAlt`, `pieceLink`, `pieceTeaser` (`true` only)."""
    for k in V5_WORK_KEYS:
        if k not in raw:
            continue
        here = "%s.%s" % (where, k)
        v = raw[k]
        if schema < 5:
            col.problems.append(_needs_schema_5(here, schema).problem)
        elif k == "cardImage":
            if v not in CARD_IMAGES:
                names = " or ".join('"%s"' % a for a in CARD_IMAGES)
                col.add("site.json: '%s' must be %s" % (here, names), here, _shown(repr(v)), names,
                        "set %s to %s" % (here, names))
            else:
                out[k] = v
        elif k == "cardKicker":
            if not isinstance(v, str) or not _KEY_RE.match(v):
                col.add("site.json: '%s' must be the name of a piece key" % here, here, _shown(repr(v)),
                        "a plain key name", "name the piece key the card prints, such as cardKicker: industry")
            elif v in BUILTIN_PIECE_KEYS:
                col.add("site.json: '%s' names '%s', a built-in key the build shows already" % (here, v), here, v,
                        "a piece key that is not built in", "name another piece key")
            elif v in out["cardMeta"]:
                col.add("site.json: '%s' names '%s', which cardMeta lists too, so the card would print it twice"
                        % (here, v), here, v, "a key not in cardMeta",
                        "remove '%s' from cardMeta, or name another key" % v)
            else:
                out[k] = v
        elif k == "cardAlt" and v == CARD_ALT_TITLE:
            # Schema 6 (design-adopt-parity-2 section 4.3): the alt of a card's picture is the piece's title.
            if schema < 6:
                col.problems.append(needs_schema_6(here, schema).problem)
            else:
                out[k] = CARD_ALT_TITLE
        elif v is not True:
            col.add("site.json: '%s' must be true" % here, here, _shown(repr(v)), "true",
                    "set %s to true, or remove it" % here)
        else:
            out[k] = True


def _v6_settings(raw, where, schema, out, col):
    """The schema-6 portfolio settings (design-adopt-parity-2 section 3.2), each `true` only and stored only when set:
    `groupCount` (each group heading prints how many pieces it shows; its `groupBy` is the caller's check) and
    `pieceRoles` (a piece's `role` is a list of dated roles). Below 6 each is refused naming the schema."""
    for k in V6_WORK_KEYS:
        if k not in raw:
            continue
        here = "%s.%s" % (where, k)
        if schema < 6:
            col.problems.append(needs_schema_6(here, schema).problem)
        elif raw[k] is not True:
            col.add("site.json: '%s' must be true" % here, here, _shown(repr(raw[k])), "true",
                    "set %s to true, or remove it" % here)
        else:
            out[k] = True


def _portfolio_check(raw, where, schema, featured_from, col):
    out = {"label": "Work", "description": "", "required": ["title"], "meta": [], "cardMeta": [],
           "groupBy": None, "groups": [], "labels": {"meta": {}, "groups": {}}}
    if not isinstance(raw, dict):
        col.run(_bad, where, "an object", raw)
        return out
    for k in raw:
        if k not in WORK_KEYS:
            col.add("site.json: unknown key '%s.%s'" % (where, k), "%s.%s" % (where, k), "unknown key",
                    "one of: " + ", ".join(WORK_KEYS), "remove '%s.%s'" % (where, k))
    labels_raw = None
    if "labels" in raw:
        if schema < 2:
            col.problems.append(_needs_schema_2(where + ".labels").problem)
        else:
            labels_raw = raw["labels"]
    if "label" in raw:
        ok, val = col.run(_str, raw["label"], where + ".label")
        if ok:
            out["label"] = val
    if "description" in raw:
        ok, val = col.run(_text, raw["description"], where + ".description")
        if ok:
            out["description"] = val
    for k in ("required", "meta", "cardMeta", "groups"):
        if k in raw:
            out[k] = _list_of_keys(raw, k, where, col)
    for k in V4_WORK_KEYS:
        if k not in raw:
            continue
        if schema < 4:
            col.problems.append(_needs_schema_4("%s.%s" % (where, k), schema).problem)
        elif k == "backLink":
            ok, val = col.run(_one_line, raw[k], "%s.%s" % (where, k))
            if ok:
                out[k] = val
        elif k == "cardNumberFormat":
            if raw[k] not in CARD_NUMBER_FORMATS:
                names = ", ".join('"%s"' % f for f in CARD_NUMBER_FORMATS[:-1]) + ' or "%s"' % CARD_NUMBER_FORMATS[-1]
                col.add("site.json: '%s.%s' must be %s" % (where, k, names), "%s.%s" % (where, k),
                        _shown(repr(raw[k])), names, "set %s.%s to %s" % (where, k, names))
            elif raw[k] != CARD_NUMBER_FORMATS[0]:
                out[k] = raw[k]
        else:
            ok, val = col.run(_bool, raw[k], "%s.%s" % (where, k))
            if ok and val != (k == "cardLabels"):          # the defaults are cardNumber false, cardLabels true
                out[k] = val
    _v5_settings(raw, where, schema, out, col)
    _v6_settings(raw, where, schema, out, col)
    if "groupBy" in raw:
        ok, val = col.run(_str, raw["groupBy"], where + ".groupBy", optional=True)
        if ok:
            out["groupBy"] = val
            if val is not None and not _KEY_RE.match(val):
                col.add("site.json: '%s.groupBy' must be a plain key name" % where, where + ".groupBy", val,
                        "a plain key name", "use a plain key name (letters, digits, underscore)")
    if bool(out["groups"]) != (out["groupBy"] is not None):
        col.add("site.json: '%s.groupBy' and '%s.groups' go together" % (where, where), where + ".groupBy",
                "one without the other", "both, or neither", "set groupBy and groups together, or remove both")
    if out.get("groupCount") and out["groupBy"] is None:
        col.add("site.json: '%s.groupCount' counts the pieces of each group, and this portfolio has no groupBy"
                % where, where + ".groupCount", "no groupBy", "groupBy and groups",
                "set groupBy and groups, or remove groupCount")
    for k in ("required", "meta", "cardMeta"):
        for item in out[k]:
            if not _KEY_RE.match(item):
                col.add("site.json: '%s.%s' holds '%s', which is not a plain key name" % (where, k, item),
                        "%s.%s" % (where, k), item, "a plain key name",
                        "use a plain key name (letters, digits, underscore)")
    if featured_from == "flags":
        for k in ("meta", "cardMeta"):
            if "featured" in out[k]:
                col.add("site.json: '%s.%s' lists 'featured', which is reserved while featuredFrom is flags"
                        % (where, k), "%s.%s" % (where, k), "featured", "no 'featured' in %s" % k,
                        "remove 'featured' from %s, or drop featuredFrom" % k)
    if labels_raw is not None:
        out["labels"] = _labels(labels_raw, where + ".labels", col, schema)
        shown = set(out["meta"]) | set(out["cardMeta"])
        for key in out["labels"]["meta"]:
            if key not in shown:
                col.add("site.json: '%s.labels.meta' labels '%s', which is not in meta or cardMeta"
                        % (where, key), "%s.labels.meta" % where, key, "a key listed in meta or cardMeta",
                        "remove the label, or add '%s' to meta or cardMeta" % key)
        for key in out["labels"]["groups"]:
            if key not in out["groups"]:
                col.add("site.json: '%s.labels.groups' labels '%s', which is not in groups" % (where, key),
                        "%s.labels.groups" % where, key, "a name listed in groups",
                        "remove the label, or add '%s' to groups" % key)
        for key in out["labels"].get("counts", {}):
            if key != COUNT_ANY and key not in out["groups"]:
                col.add("site.json: '%s.labels.counts' names '%s', which is not in groups" % (where, key),
                        "%s.labels.counts" % where, key, "a name listed in groups, or \"*\"",
                        "remove the entry, or add '%s' to groups" % key)
    return out


def portfolio_problems(raw, where, schema=SCHEMA_MAX, featured_from="home"):
    """Every problem in a portfolio-settings object (site.json `work`, or a page.md's overrides), as
    (problems, settings). `settings` is fully defaulted and only meaningful when `problems` is empty."""
    col = _Collector()
    out = _portfolio_check(raw, where, schema, featured_from, col)
    return col.problems, out


def validate_portfolio_settings(raw, where, schema=SCHEMA_MAX, featured_from="home"):
    """The `work` object of site.json, and the front matter of a portfolio's page.md, share this
    shape. `where` prefixes error messages. `schema` is the declared schema of the site.json the
    settings belong to: `labels` is refused under schema 1. `featured_from` is the site's
    `featuredFrom`: under `flags` the name `featured` is reserved. Returns a fully-defaulted dict;
    raises ONE SiteConfigError carrying every problem."""
    probs, out = portfolio_problems(raw, where, schema, featured_from)
    if probs:
        raise SiteConfigError.of(probs)
    return out


def _resume_check(raw, col, schema=SCHEMA_MAX):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        col.run(_bad, "resume", "an object", raw)
        return None
    n = len(col.problems)
    for k in raw:
        if k not in RESUME_KEYS:
            col.add("site.json: unknown key 'resume.%s'" % k, "resume.%s" % k, "unknown key",
                    "one of: " + ", ".join(RESUME_KEYS), "remove 'resume.%s'" % k)
    extra = {}
    for k, allowed, default in (("headings", RESUME_HEADINGS, "shift"), ("layout", RESUME_LAYOUTS, "plain")):
        if k not in raw:
            continue
        if schema < 4:
            col.problems.append(_needs_schema_4("resume." + k, schema).problem)
        elif raw[k] not in allowed:
            names = " or ".join('"%s"' % a for a in allowed)
            col.add("site.json: 'resume.%s' must be %s" % (k, names), "resume." + k, _shown(repr(raw[k])),
                    names, "set resume.%s to %s" % (k, names))
        elif raw[k] != default:
            extra[k] = raw[k]
    paper = None
    # K-1 (schema 3): a resume with no PDF has no paper size to ask about. Below schema 3 the answer is
    # always required, exactly as 0.2.0 reads it.
    no_pdf = "pdf" in raw and raw["pdf"] is None
    if "paper" not in raw and no_pdf and schema >= 3:
        pass
    elif "paper" not in raw:
        col.add("site.json: 'resume.paper' is required (\"Letter\" or \"A4\"); no default is guessed from a "
                "locale", "resume.paper", "missing", "\"Letter\" or \"A4\"",
                "add \"paper\": \"Letter\" or \"A4\" to resume (or, with no resume PDF, set \"pdf\": null "
                "and \"schema\": 3)")
    elif raw["paper"] not in PAPERS:
        col.add("site.json: 'resume.paper' must be \"Letter\" or \"A4\"", "resume.paper", raw["paper"],
                "\"Letter\" or \"A4\"", "set resume.paper to \"Letter\" or \"A4\"")
    else:
        paper = raw["paper"]
    ok, path = col.run(_rel_path, raw.get("path", DEFAULT_RESUME_PATH), "resume.path")
    if ok and (not path.startswith("content/") or not path.endswith(".md")):
        col.add("site.json: 'resume.path' must be a .md file under content/", "resume.path", path,
                "a .md file under content/", "point resume.path at the resume's .md file under content/")
    pdf = raw.get("pdf", DEFAULT_RESUME_PDF)
    if pdf is not None:
        ok2, pdf = col.run(_rel_path, pdf, "resume.pdf")
        if ok2 and (not pdf.startswith("content/") or not pdf.endswith(".pdf")):
            col.add("site.json: 'resume.pdf' must be a .pdf file under content/", "resume.pdf", pdf,
                    "a .pdf file under content/", "point resume.pdf at the resume's .pdf under content/")
    if len(col.problems) > n:
        return None
    out = {"path": path, "pdf": pdf, "paper": paper}
    out.update(extra)
    return out


def resume_pdf_output(resume):
    """The path the build publishes the resume PDF at, `resume/<basename of resume.pdf>`, or None when the resume
    publishes none (design A1, #888: an existing mechanism, no new key). `resume` is `cfg.resume`. The live address of a
    site adopted from another builder is whatever that builder named the file, so adopt's `resumePdfName` conversion
    renames the committed source PDF to the live basename and sets `resume.pdf`; this is the one function that says where
    the build puts it, so the conversion, the build and the address guard cannot disagree."""
    pdf = (resume or {}).get("pdf")
    return "resume/" + pdf.rsplit("/", 1)[-1] if pdf else None
