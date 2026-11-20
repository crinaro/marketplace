"""evidence_keys: the browser-fallback evidence keys of a `jd_read` attempt (`browser`, `ready`, `gate`, `fallback`), their
vocabulary checks, and the profile-pin guard that refuses them below the pin (dev 858; design-browser-fallback.md 8.1, 8.2).

Capability module of record.py (an entry point over `recording/`).

  --browser pane|extension      which browser made the attempt           (read-jd, read-failed, not-attempted; via render)
  --ready READY|NOT-READY|READY-ERROR   `page_ready.py --verdict`'s word    (read-failed, not-attempted)
  --gate paints|not-painting|probe-error  `pane_probe.py --gate`'s word    (read-failed, not-attempted)
  --fallback-extension <code>   why the extension rung did not read        (read-failed, not-attempted)

THE WRITER REFUSES THEM WITHOUT THE PIN. A profile carries `jd_read` shapes the installed 0.86.0-0.89.x reader refuses, so a new
key is written only once `m_0_90_0_browser_fallback` has pinned the profile at 0.90.0 (`pin_scan`, the same tolerant read
`_network_gate` uses). Each value is checked against the vocabulary `jd_read` owns, and `jd_read.make_attempt` stays the
authority. `gate` REPLACES `probe` for new writes: `--probe` is refused and says what to run instead."""

import jd_read as _jd
from journaling.journal_file import pin_scan
from recording import profile_paths as _paths
from recording.common import _Refused, _Usage

PROBE_RETIRED = ("--probe is retired (jobsearch 0.90.0, dev 858): `gate` replaces `probe` for new writes. Run "
                 "`~/.claude/jobsearch/run pane_probe.py --gate --result '<the probe json>'` and pass the word it prints "
                 "as --gate paints|not-painting|probe-error")
_FLAG_OF = {"browser": "--browser", "ready": "--ready", "gate": "--gate", "fallback": "--fallback-extension"}


def new_keys_pin_refusal(keys):
    """`None` when none of `keys` is a new evidence key or the profile is pinned at `jd_read.NEW_KEYS_PIN` or later, else the
    refusal line (nothing written). A profile with no pin at all is below it: an unmigrated profile must not be given a key an
    older engine cannot read."""
    used = sorted(set(keys) & set(_jd.NEW_EVIDENCE_KEYS))
    if not used:
        return None
    need = tuple(int(x) for x in _jd.NEW_KEYS_PIN.split("."))
    pin = pin_scan(_paths.ROOT)
    have = tuple(int(x) for x in pin.split(".")) if pin else None
    if have is None or have < need:
        return ("this profile is not pinned to jobsearch %s (its pin is %s), so the evidence key(s) %s are refused: an older "
                "engine sharing the profile cannot read them. The pending migration is m_0_90_0_browser_fallback: run "
                "`~/.claude/jobsearch/run migrate.py`, read what it says, and re-issue this call. Nothing was written."
                % (_jd.NEW_KEYS_PIN, pin or "absent", ", ".join(used)))
    return None


def _given(args):
    """The keys the call gave, as a dict (empty when it gave none)."""
    given = {}
    for key, attr in (("browser", "browser_arg"), ("ready", "ready_arg"), ("gate", "gate_arg")):
        if getattr(args, attr) is not None:
            given[key] = getattr(args, attr)
    if args.fallback_ext_arg is not None:
        given["fallback"] = {"extension": args.fallback_ext_arg}
    return given


def new_evidence(args, op, via, usage):
    """The evidence keys the call gave, as the dict to merge into the attempt's evidence (empty when it gave none).
    Raises `_Usage` (exit 2, nothing written) for an unknown value, for a key on an attempt it does not belong to, or for a
    flag that belongs to another verb, and `_Refused` when the profile is below the pin. `usage` is the verb's usage text."""
    given = _given(args)
    if not given:
        return {}
    if via != "render":
        raise _Usage("%s describe a browser read, so they belong to --via render (got --via %s)\nusage: %s"
                     % (", ".join(_FLAG_OF[k] for k in given), via, usage))
    if op == "read-jd" and set(given) - {"browser"}:
        raise _Usage("%s belong to `read-failed` and `not-attempted` (they describe a page that was not read), not to read-jd: "
                     "a read records its --browser only\nusage: %s"
                     % (", ".join(_FLAG_OF[k] for k in sorted(set(given) - {"browser"})), usage))
    for key, vocab in (("browser", _jd.BROWSERS), ("ready", _jd.READY_WORDS), ("gate", _jd.GATE_WORDS)):
        if key in given and given[key] not in vocab:
            raise _Usage("%s must be one of %s (got %r)\nusage: %s" % (_FLAG_OF[key], ", ".join(vocab), given[key], usage))
    if "fallback" in given and given["fallback"]["extension"] not in _jd.EXTENSION_CODES:
        raise _Usage("--fallback-extension must be one of %s (got %r)\nusage: %s"
                     % (", ".join(_jd.EXTENSION_CODES), given["fallback"]["extension"], usage))
    refusal = new_keys_pin_refusal(given)
    if refusal:
        raise _Refused(refusal)
    return given
