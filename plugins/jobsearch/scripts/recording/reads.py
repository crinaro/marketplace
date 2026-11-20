"""reads: the role pipeline's reads: the stored screen and its inputs, the JD-read verbs `read-jd` / `read-failed` (the
only writers of `jd_read` besides the batch reads), their pay, setting and place parsing, the rule that a page
outcome names a page, and the stage line a read prints.

Capability module of record.py (an entry point over `recording/`)."""

import json
import re
from recording import profile_paths as _paths
from recording.common import _Refused, _Usage, _engine_version, _now, _profile_mod, _words
from recording.evidence_keys import PROBE_RETIRED, new_evidence
from recording.store_files import _load_or_empty, load


JD_READ_OPS = ("read-jd", "read-failed")
BATCH_OPS = ("capture-batch", "read-batch", "not-attempted")
CAPTURE_DEADLINE_S_DEFAULT = 120
FETCH_DEADLINE_S_DEFAULT = 240
EXIT_ITEM_REFUSED = 4                  # capture-batch: at least one item was refused (the others still landed)


def _has_read(row):
    """True when `row` has a `read` attempt. A `jd_read` the parser refuses is not a read."""
    try:
        import jd_read as _jd
        return _jd.is_read(row)
    except ValueError:
        return False


def screen_inputs(row):
    """`card` | `jd` | `candidate`, or None -- which inputs a screen of `row` is computed from (design section 3.2).
    COMPUTED from the row, never passed: `card` when the location or the listed pay carries `provenance: card`;
    else `candidate` when either carries `candidate`; else `jd`, but only when the role really has a `read` attempt
    (provenance `jd` with no read cannot happen through a verb, and is not trusted as a JD-input screen if a
    hand-edit makes it). None -- the screen stores no `inputs` -- when neither carries a provenance: a legacy row,
    which `lifecycle` trusts only beside a `via: legacy` read."""
    provs = []
    for key in ("location", "listed_pay"):
        blob = row.get(key) if isinstance(row, dict) else None
        p = blob.get("provenance") if isinstance(blob, dict) else None
        if p:
            provs.append(p)
    if not provs:
        return None
    if "card" in provs:
        return "card"
    if "candidate" in provs:
        return "candidate"
    return "jd" if _has_read(row) else "card"


def _store_screen(r, on, engine, profile=None, all_opps=None, applications=None, channels=None):
    """Compute and store `r["screen"]` (and keep the lean's title-floor hit honest). The one body of `record.py
    screened`, `read-jd`, `read-batch` and `capture-batch`. `on` is a date, `engine` the plugin version. The lists
    are loaded here only when the caller passed none -- a caller that screens many roles passes them, so each
    store is read once per call. Returns the stored screen."""
    import profile as _pf
    profile = _pf.load() if profile is None else profile
    all_opps = load("opportunities") if all_opps is None else all_opps
    applications = _load_or_empty("applications") if applications is None else applications
    channels = _load_or_empty("channels") if channels is None else channels
    result = _pf.screen_rules(r, profile, all_opps, applications=applications, channels=channels, today=on)
    r["screen"] = {"on": on.isoformat(), "verdict": result["verdict"],
                   "rules": dict(result["rules"]), "engine": engine,
                   "title_keys": _pf.title_keys(profile),
                   # dev #739 / #740 (0.73.0, R2): the sibling hash of the comp inputs, so a later decision or
                   # engagement edit makes this screen stale.
                   "comp_keys": _pf.comp_keys(r, profile)}
    inputs = screen_inputs(r)
    if inputs:
        r["screen"]["inputs"] = inputs                    # dev #820: which inputs this verdict stands on
    if result.get("engagement_source"):
        # dev #740 / public #160: the pay was routed on an engagement INFERRED from the title; the stored
        # result says so, as it does for an inferred setting.
        r["screen"]["engagement_source"] = result["engagement_source"]
    if result.get("setting_source"):
        # dev #727 / public #159: the role was screened as onsite on an INFERENCE; the stored result says so, so a
        # later reader never mistakes it for a stated setting.
        r["screen"]["setting_source"] = result["setting_source"]
    # dev #722 / public #156 (R1, R2): a re-screen that finds the title BELOW the floor attaches the computed lean
    # hit to a lean the run already recorded -- the hit only, never the choice (an explicit lean wins) -- and drops
    # a title-floor hit the screen no longer supports. A role with no lean yet gets it from `lean`.
    ln = r.get("lean")
    if isinstance(ln, dict):
        kept = [h for h in (ln.get("signals") or [])
                if not (isinstance(h, dict) and h.get("id") == _pf.TITLE_FLOOR_LEAN_ID)]
        tf = _pf.title_floor_lean(r["screen"], profile)
        if tf:
            kept.append(tf[2])
        if kept != (ln.get("signals") or []):
            ln["signals"] = kept
    return r["screen"]


def _default_lean(r, on_iso, profile=None, company=None):
    """The lean `read-jd` stores when the role has none (design section 4.2, "writes the default lean when none is
    stored"): the SAME defaults `record.py lean` falls back to when `--lean` is omitted -- an age-flagged recruiter
    role asks (with the age line's first move), a title below the floor leans by pay -- computed from the stored
    screen. None when neither applies: there is no JD text on the command line to match signals against, so no
    lean is invented. An unreadable signal list stores NO lean (a lean stored with `signals: []` because the list
    could not be read would claim nothing matched)."""
    import profile as _pf
    screen = r.get("screen")
    profile = _pf.load() if profile is None else profile
    first_move = _pf.age_flag_first_move(screen)
    title_lean = _pf.title_floor_lean(screen, profile)
    if first_move:
        choice, line = "ask", "FIRST MOVE: %s" % first_move
    elif title_lean:
        choice, line = title_lean[0], title_lean[1]
    else:
        return None
    try:
        signals = (_pf.config().get("screen") or {}).get("likely_pass_signals")
        hits = _pf.match_signals(r, company, "", signals or [])
    except (OSError, ValueError):
        return None
    if title_lean:
        hits = hits + [title_lean[2]]
    return {"lean": choice, "line": line.strip(), "on": on_iso, "signals": hits}


_SET_REMOTE = ("remote", "telecommut", "work from home", "work-from-home", "wfh", "work from anywhere")
_SET_HYBRID = ("hybrid",)
_SET_ONSITE = ("on-site", "onsite", "on site", "in-office", "in office", "in-person", "in person")


def type_from_setting(declared, primary):
    """`(location.type | None, inferred)` for a work-setting text read off a JD (OURS; the validator requires a
    `location.type` beside any declared setting except `none stated`).

      `none stated` at a concrete place (`places.parse_place` reads it) -> `("onsite", True)`: the 0.70.0 inference,
        kept for a JD read -- the posting itself has been read, so the flag `setting_source: inferred` is honest.
        With no readable place -> `(None, False)`; the screen asks.
      a verbatim setting -> `remote`, `hybrid` or `onsite` by its words; `hybrid` with `remote` beside it, `remote`
        with `onsite`, or no recognised word at all -> `unresolved` (the posting's wording is contested or unreadable;
        `declared` keeps it verbatim, which is what the question to the employer is asked from). Never a guess."""
    import places as _places
    text = str(declared or "").casefold()
    if text.strip() == "none stated":
        return ("onsite", True) if _places.parse_place(primary) else (None, False)
    remote = any(w in text for w in _SET_REMOTE)
    hybrid = any(w in text for w in _SET_HYBRID)
    onsite = any(w in text for w in _SET_ONSITE)
    if hybrid:
        return ("unresolved" if remote else "hybrid"), False
    if remote and onsite:
        return "unresolved", False
    if remote:
        return "remote", False
    if onsite:
        return "onsite", False
    return "unresolved", False


def _evidence_names_role(quote, row, company):
    """N16 (design section 17): a render read must quote its OWN role. True when the normalised quote shares at least
    one word with the opportunity's title or its company's name. A page of another role (a wrong tab) shares none."""
    names = _words(row.get("title")) | _words((company or {}).get("name")) | _words(row.get("company_id"))
    return bool(_words(quote) & names)


def _closed_status_hit(text):
    """True when `text` carries the closed-status marker (`posting_fetch.CLOSED_MARKER`), whitespace collapsed and case
    folded: the one constant, so the script and the fetch path cannot disagree about what a closed posting says
    (dev #871). English only (the marker is); a localised page is the reader's judgement."""
    import posting_fetch as _pfe
    return _norm_text(_pfe.CLOSED_MARKER) in _norm_text(text)


def _closed_read_refusal(rec, run, url, status_text, evidence):
    """The `_Usage` text of a `read-jd --via render` whose quoted evidence or `--status-text` carries the closed
    marker: nothing is written, and the exact `read-failed ... --outcome closed` line to run instead is printed. The
    evidence it prints names the role (the title) and quotes the status words, which `read-failed` requires."""
    said = next((t for t in (status_text, evidence) if t and _closed_status_hit(t)), evidence)
    quote = ("%s - %s" % (rec.get("title") or rec.get("id"), " ".join(said.split())))[:200]
    return ("this page says the posting is closed (%r): a closed posting is not a read, so nothing was written. "
            "Record it instead:\n  record.py read-failed %s --run %s --url %s --via render --outcome closed "
            "--page-result chars=<N> --evidence %s\n(<N> is the length of this page's get_page_text result)"
            % (" ".join(said.split())[:80], rec.get("id"), run, url or "-", json.dumps(quote)))


_VIA_PAY_SOURCE = {"fetch": "json-ld", "feed": "json-ld", "ats-api": "ats-api", "render": "listing-text",
                   "candidate": "candidate"}


def supersede_listed_pay(row, on_iso, by):
    """dev #846 (0.88.0, design 4.2): move a row's `listed_pay` to the END of its append-only `listed_pay_prior` list, stamped
    `superseded_on` / `superseded_by`, and delete `listed_pay`, so the field is ABSENT (NOT captured: the screen asks for a
    re-read before the role is surfaced). Touches nothing else. The old value is never lost (the expand step of an
    expand-and-contract change: the contract step is not in this release). Returns True when a `listed_pay` was moved, False when
    the row had none. The ONE transform: its callers are the migration (`by="m_0_88_0_pay_evidence"`) and `read-jd --pay ?`
    (`by="read-jd:<run id>"`), so the two can never disagree about what a supersede keeps."""
    old = row.get("listed_pay")
    if not isinstance(old, dict):
        return False
    prior = row.get("listed_pay_prior")
    prior = list(prior) if isinstance(prior, list) else []
    prior.append(dict(old, superseded_on=on_iso, superseded_by=by))
    row["listed_pay_prior"] = prior
    del row["listed_pay"]
    return True


def jd_pay(slot, via, on_iso, provenance):
    """The `listed_pay` object a JD read stores, from the ROLE line's own pay grammar (`none` |
    `stated:<range>[;<range>]` | `estimate:<range>[;<range>]`, parsed by `deferred.parse_pay_slot`, the one parser), or
    `None` for `?` (dev #846, 0.88.0: "I read it and did not find or parse pay" -- the field is NOT captured, never a
    `none`). The `source` is the form the figure took, by how it was read; `provenance` says WHERE (`jd`, or `candidate`).
    A `none` read by a script-checkable or rendered route carries `none_basis: <via>` so a later reader can tell a none-shown
    this engine earned from a legacy one (the 0.88.0 migration selects the legacy ones, which have none)."""
    import deferred as _deferred
    slot = str(slot or "").strip()
    if not slot:
        raise _Usage("--pay is required: none | ? | stated:<min>-<max>/<yr|mo|day|hr>/<CUR> | estimate:<range>")
    if slot == "?":
        if via == "candidate":
            raise _Refused("--pay ? is the reader's word for \"I did not find or parse the pay\". The candidate's own read states "
                           "the pay or states there is none: --pay none | stated:<range>")
        return None
    lp, why = _deferred.parse_pay_slot(slot)
    if why:
        raise _Refused(why)
    if lp["state"] == "board-estimate":
        source = "board-widget"
    elif lp["state"] == "none-shown":
        source = "candidate" if via == "candidate" else "listing-text"
    else:
        source = _VIA_PAY_SOURCE[via]
    out = dict(lp, source=source, captured_on=on_iso, provenance=provenance)
    if lp["state"] == "none-shown" and source == "listing-text":
        out["none_basis"] = via
    return out


def jd_location(old, setting, place, provenance):
    """The `location` object a JD read stores. The JD wins over whatever was there (a card's place may be the
    search's own echo), so the facts the card or the JD states -- `declared`, `primary`, `type`, `remote`, the
    inference flags, `anchor_echo` -- are replaced; what a person added (a `note`, a `commute_minutes` for the SAME
    place) is kept."""
    old = old if isinstance(old, dict) else {}
    replaced = ("primary", "declared", "type", "remote", "setting_source", "inference_overturned", "anchor_echo",
                "provenance")
    new = {k: v for k, v in old.items() if k not in replaced}
    if "commute_minutes" in new and (old.get("primary") or None) != (place or None):
        del new["commute_minutes"]                  # an estimate for a place this read no longer states
    new["declared"] = setting
    if place:
        new["primary"] = place
    typ, inferred = type_from_setting(setting, place)
    if typ:
        new["type"] = typ
        new["remote"] = typ == "remote"
    if inferred:
        new["setting_source"] = "inferred"
    new["provenance"] = provenance
    return new


JD_READ_USAGE = ("read-jd <opp> --run <id> --url <u|-> --via fetch|render|feed|ats-api|candidate "
                 "--pay none|?|stated:<range>|estimate:<range> --setting \"<verbatim|none stated>\" "
                 "--location \"<text|?>\" --evidence \"<1-200 characters>\" [--status-text \"<the page's status line, or "
                 "none shown>\": --via render only] [--body-sha1 <sha1>: required with --via "
                 "fetch] [--browser pane|extension: --via render only] [--dry-run] [--already-locked]\n"
                 "       read-failed <opp> --run <id> --url <u|-> --via fetch|render|feed|ats-api --outcome "
                 "closed|dead-link|manual-board|no-url|login-wall|challenge|render-failed|surface-cannot-read|"
                 "site-not-allowed --evidence \"<1-200 characters>\" [--page-result chars=<N>|error=<text>: required "
                 "with --via render, except for no-url, manual-board and site-not-allowed] [--pane \"<the tabs_context "
                 "line>\": required for render-failed unless --browser extension] [--gate paints|not-painting|probe-error: "
                 "required for render-failed] [--browser pane|extension] [--ready READY|NOT-READY|READY-ERROR] "
                 "[--fallback-extension <code>] [--dry-run] [--already-locked]")


def _jd_read_common(args, rec):
    """`(run, url, evidence, via)` after the checks `read-jd` and `read-failed` share. Raises `_Usage` / `_Refused`
    before anything is written."""
    import jd_read as _jd
    import board_hosts as _bh
    if args.rest:
        raise _Usage("usage: " + JD_READ_USAGE)
    if args.jd_file:
        raise _Usage("%s takes no JD file (--jd-file): a page's text never crosses the command line, and a hash of a "
                     "file proves only that a file existed. Record what the posting states in --pay, --setting, "
                     "--location and a short --evidence quote\nusage: %s" % (args.op, JD_READ_USAGE))
    run = (args.run_id_arg or "").strip()
    if not run or re.search(r"\s", run):
        raise _Usage("--run <run id> is required (the run that made this read; no whitespace)\nusage: " + JD_READ_USAGE)
    via = args.via_medium
    legal = _jd.VIAS if args.op == "read-jd" else tuple(v for v in _jd.VIAS if v != "candidate")
    if via not in legal:
        raise _Usage("--via must be one of %s for %s (got %r)\nusage: %s"
                     % (", ".join(legal), args.op, via, JD_READ_USAGE))
    raw_url = (args.listing_url or "").strip()
    if not raw_url:
        raise _Usage("--url <the address read, or -> is required\nusage: " + JD_READ_USAGE)
    url = None if raw_url == "-" else raw_url
    if url is not None and _bh.host_of(url) is None:
        raise _Refused("--url must be an http(s) address with a host, or - (got %r)" % raw_url)
    body_read = args.op == "read-jd" and via == "fetch"      # `--url -` here is checked by `_jd_read_mutation` (needs --body-sha1)
    if url is None and via != "candidate" and args.op == "read-jd" and not body_read:
        raise _Refused("--url - is only for a candidate read (or a `--via fetch --body-sha1` read of a saved body, whose "
                       "address is the one its index entry names): a read of a posting names the address it read")
    evidence = (args.evidence_text or "").strip()
    if not evidence:
        raise _Usage("--evidence is required: 1-200 characters\nusage: " + JD_READ_USAGE)
    if len(evidence) > _jd.EVIDENCE_CAP:
        raise _Refused("--evidence is %d characters; the cap is %d (shorten it -- it is never truncated for you)"
                       % (len(evidence), _jd.EVIDENCE_CAP))
    if url is not None and via != "candidate" and args.op == "read-jd":
        blocked = _bh.blocked_channel(url, _load_or_empty("channels"))
        if blocked is not None:
            raise _Refused("--url %r is on the manual-candidate board %s (host %s), which the engine never opens "
                           "(ADR-037): record `read-failed --outcome manual-board` instead, or `read-jd --via "
                           "candidate` with what the candidate read" % (url, blocked.get("id"), _bh.host_of(url)))
    return run, url, evidence, via


RENDER_EXEMPT_OUTCOMES = ("no-url", "manual-board", "site-not-allowed")
_PAGE_RESULT_RE = re.compile(r"^(?:chars=\d+|error=[^\r\n]{1,120})$")


def _failed_page_evidence(args, via, outcome):
    """The extra evidence keys (`page`, `pane`, and from 0.90.0 `browser`, `ready`, `gate`, `fallback`) a `read-failed` stores,
    after the per-page requirement above. `page` is the page result as given and `pane` the PARSED state (never the raw line);
    `gate` is the word `pane_probe.py --gate` printed. Raises `_Usage` (exit 2, nothing written) when a required flag is missing
    or malformed, when `--probe` is given (retired: `gate` replaces it), or when the gate says the page never painted for a
    `render-failed` (a page that did not paint is `not-attempted --reason pane-hidden`). A hidden pane LINE alone is no longer a
    refusal (design 3.3): the pane line is recorded and the gate decides."""
    import pane_probe as _pp
    on_page = via == "render" and outcome not in RENDER_EXEMPT_OUTCOMES
    on_render_failed = via == "render" and outcome == "render-failed"
    extra = {}
    if args.probe_json is not None:
        raise _Usage(PROBE_RETIRED + "\nusage: " + JD_READ_USAGE)
    page = (args.page_result or "").strip()
    if page:
        if not _PAGE_RESULT_RE.match(page):
            raise _Usage("--page-result must be `chars=<N>` (the length of this page's get_page_text result) or `error=<the "
                         "tool's own error text, 1-120 characters, one line>` (got %r)\nusage: %s" % (page, JD_READ_USAGE))
        extra["page"] = page
    elif on_page:
        raise _Usage("read-failed --via render --outcome %s needs --page-result chars=<N>|error=<text>: no page outcome is "
                     "recorded for a page that was not opened and read, by itself, in this dispatch. A role you did not open "
                     "is reported in your hand-back (or, when the pane was hidden, recorded with `record.py not-attempted "
                     "--reason pane-hidden`), never given another role's outcome\nusage: %s" % (outcome, JD_READ_USAGE))
    new_keys = new_evidence(args, "read-failed", via, JD_READ_USAGE)
    extra.update(new_keys)
    if args.pane_line is not None and str(args.pane_line).strip():
        extra["pane"] = _pp.pane_state(args.pane_line)
    elif on_render_failed and new_keys.get("browser") != "extension":
        raise _Usage("read-failed --outcome render-failed needs --pane \"<the last line of tabs_context>\": the pane state is "
                     "parsed from the harness's own line (a read on the Chrome extension has no pane line: pass --browser "
                     "extension instead)\nusage: " + JD_READ_USAGE)
    if on_render_failed and "gate" not in new_keys:
        raise _Usage("read-failed --outcome render-failed needs --gate paints|not-painting|probe-error: the word `pane_probe.py "
                     "--gate --result '<json>'` printed for the frame probe run on this page (pane_probe.PROBE_JS, with this "
                     "tab's tabId). A failed render is a page that PAINTED and still did not read\nusage: " + JD_READ_USAGE)
    if on_render_failed and new_keys.get("gate") in ("not-painting", "probe-error"):
        raise _Usage("a page that does not paint is not a failed render: with the gate at %s the page never rendered, which is "
                     "no evidence about the role. Try the next rung (the Chrome extension, then the fetch), and when none "
                     "reads, record `record.py not-attempted <opp_id> ... --run <run id> --via render --reason pane-hidden "
                     "--pane \"<line>\" --tab-active yes|no --gate %s --evidence \"<the status line>\"`\nusage: %s"
                     % (new_keys["gate"], new_keys["gate"], NOT_ATTEMPTED_USAGE))
    return extra


def _norm_text(text):
    """Case-folded, whitespace-collapsed text: how a saved body is compared with a quote taken from it."""
    return " ".join(str(text or "").casefold().split())


_FIGURE_RE = re.compile(r"\d+(?:[.,]\d+)*[kK]?")


def _figures(text):
    """The set of numbers in `text`, each normalised (design 5.1, R2-M10): remove `,` and `.` separators and a trailing
    `k`/`K`, then strip trailing zeros, so `150000`, `150K`, `USD 150,000` and `150.0K` all read `15` and `152.5K` and `152,500`
    both read `1525`. A number that is all zeros reads `0`."""
    out = set()
    for m in _FIGURE_RE.finditer(str(text or "")):
        digits = re.sub(r"[.,]", "", m.group(0)).rstrip("kK")
        out.add(digits.rstrip("0") or "0")
    return out


def _fetch_body_read(args, rec, evidence, place):
    """`(url, extra_evidence)` for `read-jd --via fetch --body-sha1 <sha1>`: the reader's read of a body the fallback saved
    (`RESIDUE <id> (body)`), from the saved index entry and file under `posting_fetch.state_dir()`. Raises `_Usage` /
    `_Refused` (nothing written) unless ALL of these hold:

      * the sha1 given matches the index entry for this role AND the file on disk (`posting_fetch.saved_body` re-hashes it);
      * `--evidence` is a substring of the saved body, or of the title the index holds for it (the body file carries the
        description only; the title came from the same page), case-folded with whitespace collapsed;
      * `--location` is `?` (it states none), or such a substring, or equal to the index's `place`;
      * every figure in `--pay` is found in the body (a NECESSARY condition: it refuses an invented figure without guessing
        the right reading. PARTIAL: a figure found in the body may still be the wrong one).

    `--url` is `-` (the address the index entry names is used) or exactly that address. `--setting` is the posting's own
    words and is checked only against what `read-jd` already validates; the closed vocabulary the design hoped for does not
    exist (INFERRED at design time, CONFIRMED at build: `jd_location` classifies free text), so it stays the reader's word."""
    import posting_fetch as _pf
    sha1 = (args.body_sha1 or "").strip().lower()
    if not re.match(r"^[0-9a-f]{40}$", sha1):
        raise _Usage("--body-sha1 must be the 40 lowercase hex digits the `RESIDUE <id> (body)` line printed (got %r)\nusage: %s"
                     % (args.body_sha1, JD_READ_USAGE))
    sdir = _pf.state_dir()
    if sdir is None:
        raise _Refused("read-jd --via fetch reads a body the posting fallback saved, and this machine has no profile state "
                       "directory to hold one: nothing written")
    saved = _pf.saved_body(sdir, rec.get("id"))
    if saved is None:
        raise _Refused("no saved body for %s (none was fetched, it is older than 7 days, or its file no longer matches its "
                       "index entry): read-jd --via fetch reads only a body the fallback saved; nothing written" % rec.get("id"))
    path, entry = saved
    if entry.get("sha1") != sha1:
        raise _Refused("--body-sha1 %s is not the saved body's sha1: the file for %s hashes to %s. Pass the sha1 the RESIDUE "
                       "(body) line printed; nothing written" % (sha1, rec.get("id"), entry.get("sha1")))
    try:
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
    except (OSError, ValueError) as e:
        raise _Refused("the saved body cannot be read (%s); nothing written" % e)
    if _pf._sha1_text(body) != sha1:
        raise _Refused("the saved body file does not hash to %s; nothing written" % sha1)
    entry_url = entry.get("url")
    given_url = (args.listing_url or "").strip()
    if given_url not in ("", "-") and given_url != entry_url:
        raise _Refused("--url %r is not the address this body was fetched from (%r): pass --url - to use it; nothing written"
                       % (given_url, entry_url))
    hay = _norm_text(body) + " " + _norm_text(entry.get("title"))
    if _norm_text(evidence) not in hay:
        raise _Refused("--evidence is not found in the saved body (or its title): quote the posting's own words from the file "
                       "%s, never from memory; nothing written" % path)
    if place:
        if _norm_text(place) not in hay and _norm_text(place) != _norm_text(entry.get("place")):
            raise _Refused("--location %r is not found in the saved body and is not the place its index entry holds (%r); "
                           "nothing written" % (place, entry.get("place")))
    missing = sorted(_figures(args.pay_slot) - _figures(body))
    if missing:
        raise _Refused("--pay names figure(s) the saved body does not contain (normalised %s): a pay figure is quoted from the "
                       "body, never estimated or remembered. Use --pay none if the posting states none, or --pay ? if you "
                       "could not find it; nothing written" % ", ".join(missing))
    # dev #846 (0.88.0, design 3.1): `none` is a statement about the WHOLE description, so it is refused when the saved body
    # states a pay (`deferred.pay_phrase`, the one detector). This is the check the figure test above could never make: it
    # confirms the figures a reader GAVE appear in the body, and a `none` gives none. PARTIAL: a currency or language outside
    # `pay_phrase`'s lists passes, and the rule then rests on `jd-reader.md`.
    if str(args.pay_slot or "").strip() == "none":
        import deferred as _deferred
        phrase = _deferred.pay_phrase(body, _pay_marks())
        if phrase:
            raise _Refused("--pay none, but the saved body states pay: \"%s\". Record --pay stated:<range>, or --pay ? if you "
                           "cannot read it; nothing written" % phrase)
    return entry_url, {"sha1": sha1, "chars": len(body)}


def _pay_marks():
    """The profile's own currency marks for `deferred.pay_phrase`: its `compensation.currency` code and `currency_symbol`. An
    unreadable config contributes none (the closed symbol and code lists still apply), never an error: this only widens what is
    detected."""
    marks = []
    try:
        comp = _profile_mod().config().get("compensation")
    except (OSError, ValueError, KeyError, AttributeError):
        return marks
    if isinstance(comp, dict):
        for key in ("currency", "currency_symbol"):
            v = comp.get(key)
            if isinstance(v, str) and v.strip():
                marks.append(v.strip())
    return marks


def _jd_read_mutation(args, rec):
    """`(desc, apply)` for `read-jd` and `read-failed` against the opportunity `rec` (dev #820 / public #175; design
    section 4.2). `apply(row)` runs under the lock on the row as re-read there. BOTH append ONE attempt built by
    `jd_read.make_attempt` (the one constructor: an unknown outcome, empty evidence or a bad `at` is refused by the
    parser, not by this code). Raises `_Refused` / `_Usage` before anything is written.

    `read-jd` also REPLACES `location` and `listed_pay` with what the JD says (`provenance: jd`, or `candidate`
    under `--via candidate`, the replaced values kept in `evidence.replaced`), except a value the CANDIDATE wrote,
    which only the candidate replaces; it re-runs the screen (so `screen.inputs` follows the new provenance), and
    stores the default lean when the role has none. `read-failed` changes nothing but the attempt."""
    import jd_read as _jd
    run, url, evidence, via = _jd_read_common(args, rec)
    company = next((c for c in _load_or_empty("companies") if c.get("id") == rec.get("company_id")), None)
    at = _now()
    on = at.date()
    at_iso = at.isoformat()

    def append_attempt(r, attempt):
        try:
            existing = _jd.attempts(r)
        except _jd.JdReadError as e:
            raise KeyError("the stored jd_read cannot be read (%s); nothing was written" % e)
        r["jd_read"] = {"attempts": [dict(a) for a in existing] + [attempt]}

    if args.op == "read-failed":
        outcome = (args.outcome_arg or "").strip()
        failed = tuple(o for o in _jd.OUTCOMES if o != _jd.READ)
        if outcome == _jd.READ:
            raise _Refused("--outcome read is `record.py read-jd`'s: a read states pay, setting and location")
        if outcome not in failed:
            raise _Usage("--outcome must be one of %s (got %r)\nusage: %s"
                         % (", ".join(failed), outcome or None, JD_READ_USAGE))
        if args.body_sha1:
            raise _Usage("--body-sha1 belongs to `read-jd --via fetch` (a read of a saved body), not to read-failed\nusage: "
                         + JD_READ_USAGE)
        if getattr(args, "status_text", None) is not None:
            raise _Usage("--status-text belongs to `read-jd --via render` (the words where the Apply control is), not to "
                         "read-failed\nusage: " + JD_READ_USAGE)
        failed_evidence = {"text": evidence}
        failed_evidence.update(_failed_page_evidence(args, via, outcome))
        # (after the page-result requirement, which is the older, more basic refusal)
        if via == "render" and outcome == "closed" and not _evidence_names_role(evidence, rec, company):
            raise _Usage("a rendered `closed` must name this role: the evidence shares no word of three or more letters "
                         "with the title %r or the company %r, so it may be another role's page (a wrong tab). Quote this "
                         "role's title with the status words, or record `read-failed --via render --outcome render-failed "
                         "--evidence \"quote did not match the role\"`"
                         % (rec.get("title"), (company or {}).get("name") or rec.get("company_id")))
        try:
            attempt = _jd.make_attempt(at_iso, run, url, via, outcome, failed_evidence)
        except _jd.JdReadError as e:
            raise _Refused(str(e))

        def apply_failed(r):
            append_attempt(r, dict(attempt))
        return ("read-failed via %s: %s (%s)" % (via, outcome, _jd.outcome_class(outcome))), apply_failed

    # ---- read-jd ----
    if args.probe_json is not None:
        raise _Usage(PROBE_RETIRED + "\nusage: " + JD_READ_USAGE)
    for flag, val in (("--page-result", args.page_result), ("--pane", args.pane_line)):
        if val is not None:
            raise _Usage("%s belongs to `read-failed` (it describes a page that did not render as a posting), not to read-jd\n"
                         "usage: %s" % (flag, JD_READ_USAGE))
    new_read_keys = new_evidence(args, "read-jd", via, JD_READ_USAGE)   # a read records its --browser only (and needs the pin)
    if via == "fetch" and not (args.body_sha1 or "").strip():
        raise _Usage("read-jd --via fetch needs --body-sha1 <sha1>: it records the reader's read of a body the fallback saved "
                     "(`RESIDUE <id> (body)`), and is refused unless the sha1, the evidence, the location and every --pay "
                     "figure are found in that saved body\nusage: " + JD_READ_USAGE)
    if via != "fetch" and (args.body_sha1 or "").strip():
        raise _Usage("--body-sha1 is only for `read-jd --via fetch` (got --via %s)\nusage: %s" % (via, JD_READ_USAGE))
    status_text = None
    if getattr(args, "status_text", None) is not None:
        status_text = getattr(args, "status_text", None).strip()
        if via != "render":
            raise _Usage("--status-text belongs to `read-jd --via render` (the words where the Apply control is on a "
                         "rendered page), not --via %s\nusage: %s" % (via, JD_READ_USAGE))
        if not status_text or "\n" in status_text or len(status_text) > _jd.EVIDENCE_CAP:
            raise _Usage("--status-text is 1-%d characters on one line: the words where the Apply control is, verbatim, "
                         "or the literal `none shown`\nusage: %s" % (_jd.EVIDENCE_CAP, JD_READ_USAGE))
    if via == "render":
        # dev #871: a rendered page that says it is closed is `closed`, never a read. Checked on both the quoted
        # evidence and the status text, never stored; the flag is OPTIONAL here so a 0.86.0 reader prose (which never
        # passes it) still records its read (the evidence check still runs).
        if any(t and _closed_status_hit(t) for t in (status_text, evidence)):
            raise _Usage(_closed_read_refusal(rec, run, url, status_text, evidence))
        if status_text is None:
            print("status-text absent: the closed-status check ran on --evidence only")
    if via != "candidate" and not _evidence_names_role(evidence, rec, company):
        raise _Usage("evidence does not name this role: the quote shares no word of three or more letters with "
                     "the title %r or the company %r. A wrong tab is not a read -- record `read-failed --outcome "
                     "render-failed --evidence \"quote did not match the role\"`"
                     % (rec.get("title"), (company or {}).get("name") or rec.get("company_id")))
    provenance = "candidate" if via == "candidate" else "jd"
    pay = jd_pay(args.pay_slot, via, on.isoformat(), provenance)
    setting = (args.setting_text or "").strip()
    if setting == "?":
        raise _Refused("--setting ? is a card's word: a read states the setting, or `none stated`")
    if not setting or "\n" in setting:
        raise _Usage("--setting is required: the posting's own work-setting text on one line, or the literal "
                     "`none stated`\nusage: " + JD_READ_USAGE)
    if len(setting) > 200:
        raise _Refused("--setting is %d characters; the cap is 200 (never truncated for you)" % len(setting))
    place = (args.location_text or "").strip()
    if not place:
        raise _Usage("--location is required: the posting's place text, or ? when it states none\nusage: "
                     + JD_READ_USAGE)
    if place == "?":
        place = None
    elif "\n" in place or len(place) > 200:
        raise _Refused("--location is one line of at most 200 characters")
    read_evidence = {"quote": evidence}
    read_evidence.update(new_read_keys)
    body_pay_inferred = False
    if via == "fetch":
        url, body_evidence = _fetch_body_read(args, rec, evidence, place)
        read_evidence.update(body_evidence)
        if pay is not None and pay.get("state") == "employer-stated":
            # a figure the reader took out of the saved description's PROSE, not out of JSON-LD: the same shape the fallback's
            # own scripted read stores (`listing-text`, `inferred_from: description`), so the screen weighs it the same way
            pay = dict(pay, source="listing-text")
            body_pay_inferred = True
    engine = _engine_version()

    def apply_read(r):
        _apply_read(r, run=run, url=url, via=via, evidence=dict(read_evidence), pay=pay, setting=setting,
                    place=place, at_iso=at_iso, on=on, engine=engine, profile=_profile_mod().load(),
                    company=company, pay_inferred=body_pay_inferred)

    if pay is None:
        return ("read-jd via %s: location re-read from the posting (provenance %s), screen re-run; pay: NOT captured (the reader "
                "did not find or parse pay: a range already stored stays, a legacy `none shown` moves to listed_pay_prior)"
                % (via, provenance)), apply_read
    return ("read-jd via %s: location and listed_pay re-read from the posting (provenance %s), screen re-run"
            % (via, provenance)), apply_read


def _stage_line(opp_id):
    """`stage: <name>` (with the failure cause) for one stored role, from `lifecycle` -- the only function that says
    where a role is. A snapshot that cannot be read prints `NOT CHECKED`, never a guess."""
    try:
        import lifecycle as _lc
        data = _lc.load_data(_paths.ROOT)
        opp = next((o for o in data["opportunities"] if o.get("id") == opp_id), None)
        if opp is None:
            return "stage: NOT CHECKED (no such role in the snapshot)"
        st = _lc.stage(opp, _lc.context(data, _now()))
    except Exception as e:                                   # noqa: BLE001 -- an advisory line; the write landed
        return "stage: NOT CHECKED (%s)" % " ".join(str(e).split())[:200]
    text = "stage: %s" % st.name
    if st.failure:
        text += " (FAILURE %s%s)" % (st.cause, (" %s" % st.detail) if st.detail else "")
    elif st.cause:
        text += " (%s)" % st.cause
    return text


def _apply_read(r, *, run, url, via, evidence, pay, setting, place, at_iso, on, engine, profile, company,
                all_opps=None, applications=None, channels=None, pay_inferred=False):
    """Apply one READ of a JD to the fresh row `r`: replace `location` and `listed_pay` with what the JD says
    (`provenance: jd`, or `candidate`), except a value the candidate wrote; append the `read` attempt through
    `jd_read.make_attempt` (the replaced values kept in `evidence.replaced`); re-run the screen; store the default lean
    when the role has none. The one body of `read-jd` and `read-batch --fetch`. `evidence` is the attempt's evidence
    without `replaced` (`{quote}` or `{sha1, chars}`). Raises KeyError (a refusal the shared write path prints)."""
    import jd_read as _jd
    provenance = "candidate" if via == "candidate" else "jd"
    replaced = {}
    old_loc, old_pay = r.get("location"), r.get("listed_pay")
    keep_loc = isinstance(old_loc, dict) and old_loc.get("provenance") == "candidate" and via != "candidate"
    keep_pay = isinstance(old_pay, dict) and old_pay.get("provenance") == "candidate" and via != "candidate"
    if not keep_loc:
        if isinstance(old_loc, dict) and old_loc:
            replaced["location"] = old_loc
        r["location"] = jd_location(old_loc, setting, place, provenance)
    if pay is None:
        # dev #846 (0.88.0, design 3.2): `read-jd --pay ?` -- the reader read the posting and did not find or parse pay. A stored
        # RANGE stays (a read that missed a figure does not erase one); a stored `none shown` the candidate did not write is
        # superseded (moved to `listed_pay_prior`, so the field is NOT captured and the role is re-read before it is
        # surfaced); nothing stored stays nothing. The CANDIDATE's own none (`source: candidate`) is never touched here.
        if (isinstance(old_pay, dict) and old_pay.get("state") == "none-shown" and old_pay.get("source") != "candidate"
                and not keep_pay):
            supersede_listed_pay(r, on.isoformat(), "read-jd:%s" % run)
    elif not keep_pay:
        if isinstance(old_pay, dict) and old_pay:
            replaced["listed_pay"] = old_pay
        new_pay = dict(pay)
        if pay_inferred and new_pay.get("state") != "none-shown":
            new_pay["inferred_from"] = "description"
        r["listed_pay"] = new_pay
    ev = dict(evidence)
    if via == "candidate":
        ev["attestation"] = "candidate"
    if replaced:
        ev["replaced"] = json.loads(json.dumps(replaced))
    try:
        existing = _jd.attempts(r)
        attempt = _jd.make_attempt(at_iso, run, url, via, _jd.READ, ev)
    except _jd.JdReadError as e:
        raise KeyError("the read cannot be recorded (%s); nothing was written" % e)
    r["jd_read"] = {"attempts": [dict(a) for a in existing] + [attempt]}
    _store_screen(r, on, engine, profile=profile, all_opps=all_opps, applications=applications, channels=channels)
    if not isinstance(r.get("lean"), dict):
        lean = _default_lean(r, on.isoformat(), profile=profile, company=company)
        if lean:
            r["lean"] = lean


def _apply_failed(r, *, run, url, via, outcome, text, at_iso):
    """Append one failed-read attempt to the fresh row `r` (`jd_read.make_attempt`). Raises KeyError on a refusal."""
    import jd_read as _jd
    try:
        existing = _jd.attempts(r)
        attempt = _jd.make_attempt(at_iso, run, url, via, outcome, {"text": text})
    except _jd.JdReadError as e:
        raise KeyError("the failed read cannot be recorded (%s); nothing was written" % e)
    r["jd_read"] = {"attempts": [dict(a) for a in existing] + [attempt]}


NOT_ATTEMPTED_USAGE = ("not-attempted <opp id> [<opp id> ...] --run <id> --via render --reason pane-hidden "
                       "--pane \"<the tabs_context line>\" --tab-active yes|no --evidence \"<1-200 characters>\" "
                       "[--gate paints|not-painting|probe-error] [--ready READY|NOT-READY|READY-ERROR] "
                       "[--fallback-extension <code>] [--browser pane] [--dry-run] [--already-locked]")
