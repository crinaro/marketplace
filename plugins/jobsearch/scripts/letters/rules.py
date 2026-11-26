"""The writing values a letter is held to, from config and user dicts, and the `profile.py --writing` block (jobsearch 0.95.0; dev 1072, 1071; design § 6).

Pure functions over the `config` and `user` dicts the entry points pass in (`prof.config()`, `prof.user()`); nothing is read
here and `profile.py` is never imported, so a test holds `render_template` equal to `profile._render` on the fixture.

* `render_template(lines, user)`  each template line formatted with the identity fields `profile._render` uses: `full_name`,
  `phone`, `city`, `primary_email`, `linkedin`, and `linkedin_display` (`linkedin` without `https://` and a trailing `/`).
  A missing identity key raises `KeyError`, as `profile._render` does; `writing_rules` catches it.
* `writing_rules(config, user)` returns a dict:
    `header`, `signature`      rendered lists of lines (None when unreadable, with the reason in `problems`)
    `target_words`, `max_pages`  integers or None
    `banned`                   the banned characters (non-empty strings)
    `banned_note`              `writing._banned_note` verbatim, or None
    `us_english`               {"on", "builtin", "terms", "pairs_profile", "variants_usable", "variants_total", "watch"}
    `problems`                 reasons the `writing` block cannot be read (no `writing` object, a template that is not a
                               list of text, a placeholder the identity lacks, and any value that is there but cannot be
                               read: a `banned_characters` that is not a list of non-empty strings, a target or page count
                               that is not a whole number, a `_banned_note` that is not text, a `us_english` of an unknown
                               shape, or one of its `prefer`, `avoid_variants`, `watch_words` or `prefer_ize_not_ise` of the
                               wrong type): `profile.py --writing` exits 1 on any.
    `unreadable`               the part of `problems` about a value that is PRESENT and wrong in shape (dev 1072, review item 5;
                               a template whose placeholder the identity lacks is not one: that is missing data). The
                               letter check fails on these (`letters.check.Report`), and the dashboard says "Letters not
                               checked". An absent block, template or key is in `problems` only: an unset rule is not a wrong
                               one, and a profile that never set `us_english` is checked without it. A half-readable value still
                               gives what is readable (`["—", 5]` bans `—`) beside its problem.
* `us_terms(rules)` is the list of `(word, replacement_or_None)` the US-English check flags, in force order.
* `render_block(rules, verdict)` is § 6.1's block as a list of lines; `verdict` is a `letters.guide.Verdict` (anything with a
  `.text`).

**US English, every shape (§ 6.2).** `writing.us_english` absent, null, `false` or an empty object: off. `true`: the built-in
pairs (`BUILTIN_PAIRS`, 25 common British to American spellings, matched whole word and case-insensitive, with their plural, -ed, -ing and -ation forms: `letters.check`). An object: its
`prefer` map is flagged, and the built-in pairs apply when `prefer` is a non-empty map or `prefer_ize_not_ise` is true. Each
`avoid_variants` item that is a single alphabetic word is flagged (no replacement is known); any other item (a phrase, a
placeholder such as `FIXTURE-...`) is counted as not usable, never flagged. `watch_words` are counted and printed for the
writer, never flagged. A spelling hit is a note, never a failure (the check decides that).

Standard library only; imports nothing of the plugin. Python 3.9+.
"""

LABEL_WIDTH = 19
OVER_FACTOR = 1.25

BUILTIN_PAIRS = (
    ("organise", "organize"), ("organised", "organized"), ("organising", "organizing"),
    ("organisation", "organization"), ("realise", "realize"), ("realised", "realized"),
    ("recognise", "recognize"), ("recognised", "recognized"), ("prioritise", "prioritize"),
    ("prioritised", "prioritized"), ("optimise", "optimize"), ("optimised", "optimized"),
    ("analyse", "analyze"), ("analysed", "analyzed"), ("utilise", "utilize"),
    ("utilised", "utilized"), ("summarise", "summarize"), ("standardise", "standardize"),
    ("colour", "color"), ("behaviour", "behavior"), ("favour", "favor"),
    ("centre", "center"), ("programme", "program"), ("defence", "defense"),
    ("judgement", "judgment"),
)


def render_template(lines, user):
    """Format each template line against `user["identity"]`, as `profile._render` does."""
    u = user["identity"]
    fields = {
        "full_name": u["full_name"],
        "phone": u["phone"],
        "city": u["city"],
        "primary_email": u["primary_email"],
        "linkedin": u["linkedin"],
        "linkedin_display": u["linkedin"].replace("https://", "").rstrip("/"),
    }
    return [line.format(**fields) for line in lines]


def _template(writing, key, user, problems, unreadable):
    lines = writing.get(key)
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        problems.append("writing.%s is not a list of lines" % key)
        if lines is not None:
            unreadable.append(problems[-1])
        return None
    try:
        return render_template(lines, user)
    except (KeyError, IndexError, AttributeError, ValueError, TypeError) as exc:
        problems.append("writing.%s cannot be rendered (%s: %s)" % (key, type(exc).__name__, exc))
        return None                     # not `unreadable`: the identity lacks a field, which is not a wrong rule


def _us_english(raw, bad=None):
    """The US-English settings in force for the `writing.us_english` value `raw`; `bad(text)` is told each unreadable part."""
    bad = bad or (lambda _text: None)
    out = {"on": False, "builtin": False, "terms": [], "pairs_profile": 0,
           "variants_usable": 0, "variants_total": 0, "watch": []}
    if raw is True:
        out["on"] = out["builtin"] = True
    elif isinstance(raw, dict) and raw:
        out["on"] = True
        prefer = raw.get("prefer")
        if prefer is not None and not isinstance(prefer, dict):
            bad("writing.us_english.prefer is not a map of spellings")
        prefer = prefer if isinstance(prefer, dict) else {}
        for word, good in prefer.items():
            if isinstance(word, str) and word.strip() and isinstance(good, str):
                out["terms"].append((word.strip(), good))
            else:
                bad("writing.us_english.prefer has an entry that is not text to text")
        out["pairs_profile"] = len(out["terms"])
        out["builtin"] = bool(prefer) or raw.get("prefer_ize_not_ise") is True
        if raw.get("prefer_ize_not_ise") not in (None, True, False):
            bad("writing.us_english.prefer_ize_not_ise is not true or false")
        variants = raw.get("avoid_variants")
        if variants is not None and not isinstance(variants, list):
            bad("writing.us_english.avoid_variants is not a list")
        variants = variants if isinstance(variants, list) else []
        out["variants_total"] = len(variants)
        for item in variants:
            if isinstance(item, str) and item.isalpha():
                out["variants_usable"] += 1
                out["terms"].append((item, None))
        watch = raw.get("watch_words")
        if watch is not None and not isinstance(watch, list):
            bad("writing.us_english.watch_words is not a list")
        out["watch"] = [w for w in watch if isinstance(w, str)] if isinstance(watch, list) else []
    elif not (raw is None or raw is False or raw == {}):
        bad("writing.us_english is not true, false or an object (got %s)" % type(raw).__name__)
    if out["builtin"]:
        out["terms"].extend(BUILTIN_PAIRS)
    seen, unique = set(), []
    for word, good in out["terms"]:
        if word.lower() not in seen:
            seen.add(word.lower())
            unique.append((word, good))
    out["terms"] = unique
    return out


def _whole_number(value, key, bad):
    """`value` as an int, or None when unset (absent or null); a present value that is not a whole number is `bad`."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    bad("writing.%s is not a whole number" % key)
    return None


def writing_rules(config, user):
    """The writing values in force; see the module docstring. Never raises on a malformed block: it fills `problems`."""
    problems, unreadable = [], []

    def bad(text):
        problems.append(text)
        unreadable.append(text)
    writing = config.get("writing") if isinstance(config, dict) else None
    if not isinstance(writing, dict):
        return {"header": None, "signature": None, "target_words": None, "max_pages": None, "banned": [],
                "banned_note": None, "us_english": _us_english(None), "problems": ["config.json has no writing block"],
                "unreadable": []}
    target = _whole_number(writing.get("cover_letter_target_body_words"), "cover_letter_target_body_words", bad)
    pages = _whole_number(writing.get("cover_letter_max_pages"), "cover_letter_max_pages", bad)
    banned = writing.get("banned_characters")
    if banned is not None and not (isinstance(banned, list) and all(isinstance(c, str) and c for c in banned)):
        bad("writing.banned_characters is not a list of non-empty text")
    note = writing.get("_banned_note")
    if note is not None and not isinstance(note, str):
        bad("writing._banned_note is not text")
    rules = {
        "header": _template(writing, "cover_letter_header_template", user, problems, unreadable),
        "signature": _template(writing, "email_signature_template", user, problems, unreadable),
        "target_words": target,
        "max_pages": pages,
        "banned": [c for c in banned if isinstance(c, str) and c] if isinstance(banned, list) else [],
        "banned_note": note if isinstance(note, str) and note.strip() else None,
        "us_english": _us_english(writing.get("us_english"), bad),
        "problems": problems,
        "unreadable": unreadable,
    }
    return rules


def us_terms(rules):
    """[(word, replacement_or_None)] the US-English check flags; empty when the check is off."""
    return list(rules["us_english"]["terms"])


def over_limit(rules):
    """The body word count above which a letter is noted (1.25 x the target), or None when no target is set."""
    t = rules["target_words"]
    return None if t is None else t * OVER_FACTOR


def _banned_text(chars):
    return ", ".join('"%s" (%s)' % (c, " ".join("U+%04X" % ord(x) for x in c)) for c in chars) or "none"


def _us_text(us):
    if not us["on"]:
        return "off"
    parts = ["%d built-in pairs" % (len(BUILTIN_PAIRS) if us["builtin"] else 0)]
    if us["pairs_profile"]:
        parts.append("profile pairs: %d" % us["pairs_profile"])
    parts.append("profile variants: %d of %d usable" % (us["variants_usable"], us["variants_total"]))
    parts.append("watch words: %d" % len(us["watch"]))
    return "on: " + "; ".join(parts)


def _row(label, value_lines):
    pad = " " * (2 + LABEL_WIDTH)
    first, rest = (value_lines[0], value_lines[1:]) if value_lines else ("none", [])
    return ["  %s%s" % (label.ljust(LABEL_WIDTH), first)] + [pad + x for x in rest]


def render_block(rules, verdict):
    """§ 6.1's block as lines (no trailing newline). `rules` is `writing_rules(...)`; `verdict` a guide verdict."""
    target = rules["target_words"]
    words = "not set" if target is None else "%d target (a body over %g is a note)" % (target, target * OVER_FACTOR)
    lines = ["WRITING RULES (config.json `writing` x user.json; read these, never retype them)"]
    for label, key in (("letter header", "header"), ("email signature", "signature")):
        lines += _row(label, ["unreadable (see below)"] if rules[key] is None else rules[key])
    lines += _row("letter body words", [words])
    lines += _row("letter pages", ["not set" if rules["max_pages"] is None else str(rules["max_pages"])])
    lines += _row("banned characters", [_banned_text(rules["banned"])])
    lines += _row("banned phrasing", [rules["banned_note"] or "none"])
    lines += _row("US English", [_us_text(rules["us_english"])])
    lines += _row("letter guide", [verdict.text])
    for p in rules["problems"]:
        lines.append("  UNREADABLE  %s" % p)
    return lines
