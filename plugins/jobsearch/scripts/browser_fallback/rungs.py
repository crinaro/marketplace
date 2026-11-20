"""rungs: the browser fallback chain of one step, as pure functions (dev 858; docs/design-browser-fallback.md section 4).

Capability module of `route.py`, which declares the flags, re-exports these names and runs `--next` and `--pick-browser` through `run_cli`.

When the in-app pane cannot paint, one step does not stop: it moves down a chain of RUNGS. `fallback_chain(step, cfg)` is the
ordered list, `next_rung(step, cfg, outcomes, latch)` is the pure function an agent calls (as `route.py --next`) at each rung
change, and `pick_browser(browsers)` says which connected Chrome to drive (`--pick-browser`).

    rungs       browser (the in-app pane), chrome (the extension), fetch (`posting_fetch`, a LinkedIn posting read only),
                not-checked (terminal, loud)
    order       `browser` and `chrome` in the order `config.sourcing.route_preference` gives them; `plugin` is dropped for these
                step kinds; a mechanism the user removed is not a rung (the extension's record then says `not-preferred`)
    attended    a BRIEF FIELD, never inferred. Only the exact string `yes` is attended; absent, empty, `YES`, `true`, anything
                else reads as `no`. An unattended step never enters the extension rung while EXTENSION_UNATTENDED_PROBED is
                False (`unattended-unprobed`), because a site prompt or a CAPTCHA blocks the tool call and nothing records it.
    latch       `browser` once the pane has answered `not-painting`: later steps of the pass skip the pane rung. Cleared only
                by a `paints` outcome that carries `pane: displayed`.

`--next` prints one line: `NEXT <rung> LATCH <browser|none>`, then ` NOTE waiting-on-person` when the rung is `chrome` for an
attended step, then ` CODE <code>` when the rung is `fetch` or `not-checked` and the extension was passed over without being tried
(`unattended-unprobed` or `not-preferred`: the `fallback.extension` code the agent must record). `NEXT done` means a rung worked."""

import json
import os

MECHANISMS = ("plugin", "browser", "chrome")

# The default order, used when the profile does not state one. In-app pane first because it is
# in-process and needs no second application running; Chrome last because it depends on a real
# browser being awake and signed in, which is the most fragile of the three.
DEFAULT_PREFERENCE = ("plugin", "browser", "chrome")

# False until P-C2 (design section 11) shows a BOUNDED result on every credential type an unattended
# extension rung would run under. Flipping it is a release, with that output recorded. It is a module
# constant and never read from config, so no profile can turn the rung on by itself.
EXTENSION_UNATTENDED_PROBED = False

# step kind -> does it have a rung 3 (the scripted fetch)? Only a LinkedIn posting read: every other
# host already ran `read-batch --fetch`, and every LinkedIn surface is signed in (design 4.1 table).
STEP_KINDS = {
    "posting-read-linkedin": True,
    "posting-read": False,
    "linkedin-surface": False,
    "board-sweep": False,
    "research-render": False,
    "profile-read": False,
}
RUNG_BROWSER, RUNG_CHROME, RUNG_FETCH, RUNG_NOT_CHECKED = "browser", "chrome", "fetch", "not-checked"
RUNG_DONE = "done"
OUTCOME_OK = "ok"          # an outcome word meaning the rung worked
PAINTS_WORD = "paints"     # a fresh gate result on a displayed pane: the only thing that clears the latch
NOT_PAINTING_WORD = "not-painting"
# Words meaning the BROWSER failed, so the next rung is tried (design 4.2's `fallback.extension`
# vocabulary that admits the fetch, plus the pane's own gate words).
MOVE_ON_WORDS = ("not-painting", "probe-error", "navigate-timeout", "tools-absent", "not-connected",
                 "not-this-computer", "browser-ambiguous", "unattended-unprobed", "not-preferred",
                 "lock-held")
# Words meaning the PAGE failed, not the browser: no other rung is tried and the fetch is barred
# (a logged-out fetch must not get round a wall, a person's "no", or a page that painted and failed).
PAGE_FAILED_WORDS = ("not-ready", "challenge", "permission-denied", "not-signed-in")
LATCH_VALUES = ("browser", "none")


class RouteError(ValueError):
    """An access value nobody can read. ⚠️ MUST BE LOUD: a channel whose route cannot be
    resolved is a channel that will be skipped, and a silent skip is indistinguishable from a
    channel that was searched and found nothing."""


def preference(cfg):
    """The candidate's ordered mechanisms, validated. An unknown mechanism is refused rather
    than skipped: a preference list with a typo would silently fall through to the default and
    look like it was honoured."""
    raw = ((cfg.get("sourcing") or {}).get("route_preference")) or list(DEFAULT_PREFERENCE)
    if not isinstance(raw, list) or not raw:
        raise RouteError("config.sourcing.route_preference must be a non-empty list")
    bad = [m for m in raw if m not in MECHANISMS]
    if bad:
        raise RouteError("unknown mechanism(s) %s in config.sourcing.route_preference; "
                         "valid: %s" % (bad, ", ".join(MECHANISMS)))
    return list(raw)


def fallback_chain(step, cfg):
    """The ordered rungs of one step's fallback chain (design section 4.1), terminal rung included.

    `browser` and `chrome` come in the order `config.sourcing.route_preference` gives them (a user who
    put `chrome` first gets the extension as rung 1); `plugin` is dropped, because a site plugin is not
    a way to read a rendered page; a mechanism the user removed is not a rung. Then `fetch` for a
    LinkedIn posting read only, then `not-checked`. An unknown step kind or preference is refused, not
    guessed."""
    if step not in STEP_KINDS:
        raise RouteError("unknown step kind %r; valid: %s" % (step, ", ".join(sorted(STEP_KINDS))))
    chain = []
    for mech in preference(cfg):
        if mech in (RUNG_BROWSER, RUNG_CHROME) and mech not in chain:
            chain.append(mech)
    if STEP_KINDS[step]:
        chain.append(RUNG_FETCH)
    chain.append(RUNG_NOT_CHECKED)
    return chain


def is_attended(value):
    """`attended` is a brief field, never inferred: ONLY the exact string `yes` is attended. Absent,
    empty, `YES`, `true`, `1` and every other value read as no (design 4.1). An unattended step that
    wrongly reads as attended would enter a rung that can block forever on a prompt nobody sees."""
    return isinstance(value, str) and value == "yes"


def _latch_in(latch):
    if latch is None or latch == "":
        return "none"
    if latch not in LATCH_VALUES:
        raise RouteError("unknown latch %r; valid: %s" % (latch, ", ".join(LATCH_VALUES)))
    return latch


def _outcomes_seen(outcomes, latch_out):
    """`(tried, page_failed, worked, latch)` read from the outcomes so far. An outcome word that is not in the vocabulary is
    refused: an unreadable word must be loud."""
    tried, page_failed, worked = set(), False, False
    for o in (outcomes or []):
        rung, word = o.get("rung"), o.get("word")
        if rung not in (RUNG_BROWSER, RUNG_CHROME, RUNG_FETCH):
            raise RouteError("unknown rung %r in outcomes; valid: browser, chrome, fetch" % (rung,))
        if rung != RUNG_FETCH and word not in (
                (OUTCOME_OK, PAINTS_WORD) + MOVE_ON_WORDS + PAGE_FAILED_WORDS):
            raise RouteError("unknown outcome word %r for rung %s" % (word, rung))
        if rung == RUNG_BROWSER and word == NOT_PAINTING_WORD:
            latch_out = "browser"
        elif rung == RUNG_BROWSER and word == PAINTS_WORD and o.get("pane") == "displayed":
            latch_out = "none"
        if word == PAINTS_WORD:
            continue                  # a gate result, not the end of a rung
        tried.add(rung)
        worked = worked or word == OUTCOME_OK
        page_failed = page_failed or (rung != RUNG_FETCH and word in PAGE_FAILED_WORDS)
    return tried, page_failed, worked, latch_out


def next_rung(step, cfg, outcomes, latch):
    """The next rung to try for one step. PURE: it reads nothing but its arguments.

    `cfg` is the profile config (`sourcing.route_preference`) plus an optional top-level `attended`;
    `outcomes` is the list of `{rung, word}` so far (a `paints` outcome on `browser` may carry `pane`);
    `latch` is `browser` or `none`. Returns `{rung, latch, note, code}`:

      rung   one of the chain's rungs, or `done` when a rung already worked
      latch  `browser` once the pane answered `not-painting` (later steps skip it); cleared only by a
             `paints` outcome with `pane: displayed`
      note   `waiting-on-person` when `rung` is `chrome` for an attended step, else None
      code   the `fallback.extension` code when the extension was passed over without being tried
             (`unattended-unprobed`, `not-preferred`) and the rung returned is `fetch` or
             `not-checked`; else None"""
    chain = fallback_chain(step, cfg)
    tried, page_failed, worked, latch_out = _outcomes_seen(outcomes, _latch_in(latch))

    def result(rung, note=None, code=None):
        return {"rung": rung, "latch": latch_out, "note": note, "code": code}

    if worked:
        return result(RUNG_DONE)
    if page_failed:
        return result(RUNG_NOT_CHECKED)
    attended = is_attended(cfg.get("attended"))
    ext_code = None if RUNG_CHROME in chain else "not-preferred"
    for rung in chain:
        if rung in tried:
            continue
        if rung == RUNG_NOT_CHECKED:
            return result(rung, code=ext_code)
        if rung == RUNG_BROWSER and latch_out == "browser":
            continue                  # the pane already said it does not paint
        if rung == RUNG_CHROME and not attended and not EXTENSION_UNATTENDED_PROBED:
            ext_code = "unattended-unprobed"
            continue
        if rung == RUNG_FETCH:
            return result(rung, code=ext_code)
        return result(rung, note="waiting-on-person" if (rung == RUNG_CHROME and attended) else None)
    return result(RUNG_NOT_CHECKED, code=ext_code)       # unreachable: the chain ends in not-checked


def _flag(value):
    """True only for the JSON boolean true: `"true"`, 1 and a missing key are NOT this computer."""
    return value is True


def pick_browser(browsers):
    """Which connected Chrome to drive (design 4.2), from `list_connected_browsers`' result, as
    `(word, deviceId)`. `word` is `USE` or `SELECT` (with the device id) or a code (id None):

      USE <id>        the `inUse` browser, and it is on this computer
      SELECT <id>     none is in use and exactly one is on this computer: select_browser that one
      not-connected   none listed
      not-this-computer   some are listed, none is on this computer
      browser-ambiguous   two or more on this computer and none in use, or `onThisComputer` is absent

    ONLY `onThisComputer` is read: `isLocal`, `local` or a missing field is never taken for it
    (design round C may add one). The caller never calls `switch_browser`, and never `select_browser`
    on a browser off this computer. A shape nobody can read is refused, never guessed."""
    if isinstance(browsers, dict) and isinstance(browsers.get("browsers"), list):
        browsers = browsers["browsers"]
    if not isinstance(browsers, list) or not all(isinstance(b, dict) for b in browsers):
        raise RouteError("list_connected_browsers result is not a list of browsers")
    if not browsers:
        return "not-connected", None
    unknown = [b for b in browsers if not isinstance(b.get("onThisComputer"), bool)]
    local = [b for b in browsers if _flag(b.get("onThisComputer"))]
    in_use = [b for b in local if _flag(b.get("inUse"))]
    if len(in_use) == 1:
        chosen = in_use[0]
        word = "USE"
    elif len(in_use) > 1:
        return "browser-ambiguous", None
    elif not local:
        return ("browser-ambiguous", None) if unknown else ("not-this-computer", None)
    elif len(local) == 1 and not unknown:
        chosen = local[0]
        word = "SELECT"
    else:
        return "browser-ambiguous", None
    device = chosen.get("deviceId")
    if not isinstance(device, str) or not device.strip():
        return "browser-ambiguous", None                 # cannot name it, so cannot select it
    return word, device


def load_config(root):
    """`<root>/config.json` as a dict; a missing file is a `RouteError`, never an empty config."""
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise RouteError("no config.json at %s — cannot resolve any route" % root)


def run_cli(args, root_fn):
    """`route.py --pick-browser` / `--next`: print the one answer line and return the exit code. `root_fn` gives the profile root
    (only `--next` reads it)."""
    if args.pick_browser is not None:
        try:
            word, device = pick_browser(json.loads(args.pick_browser))
        except (RouteError, ValueError) as e:
            print("!! NOT PICKED: %s" % e)
            return 1
        print("%s %s" % (word, device) if device else word)
        return 0
    try:
        if not args.step:
            raise RouteError("--next needs --step <%s>" % "|".join(sorted(STEP_KINDS)))
        outcomes = json.loads(args.outcomes)
        if not isinstance(outcomes, list) or not all(isinstance(o, dict) for o in outcomes):
            raise RouteError("--outcomes must be a JSON list of objects")
        out = next_rung(args.step, dict(load_config(root_fn()), attended=args.attended), outcomes, args.latch)
    except (RouteError, ValueError) as e:
        print("!! NO NEXT RUNG: %s" % e)
        print("   Do NOT guess a rung; report the step as NOT CHECKED.")
        return 1
    line = "NEXT %s LATCH %s" % (out["rung"], out["latch"])
    if out["note"]:
        line += " NOTE %s" % out["note"]
    if out["code"]:
        line += " CODE %s" % out["code"]
    print(line)
    return 0
