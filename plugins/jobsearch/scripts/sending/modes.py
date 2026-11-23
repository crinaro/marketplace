"""modes: the per-action "you do it / I do it after your approval" switch, `config.json` `actions.modes` (jobsearch 0.91.0,
design-build-reach.md 10.1, 10.2, owner O1, O4, O9, O14; for email, the 2026-11-23 ruling of ADR-043: `me` drafts), and the
O7 staging switch `actions.email.stage`.

    actions.modes = {"email-send": "me"}       an object keyed by action type, each value "you" or "me"; absent is "you"
    actions.email.stage = "auto"               "ask" (default: stage on the candidate's request) or "auto"

THE RESOLVER IS STRICT. `resolve(cfg, action)` returns "you" or "me" and raises `ModeError`, naming the reason, for an unknown
action type (in the object or asked for), an unknown value, a non-object `actions` or `actions.modes`, and `me` on a type that
does not offer it:

| type                                                   | `me`                                                           |
|--------------------------------------------------------|----------------------------------------------------------------|
| email-send                                             | accepted while the selected `communications.mail_connector` has a draft tool (gmail-multi, claude.ai Gmail, Fastmail, Superhuman; refused for Microsoft 365, which publishes none): `me` puts each approved message in the drafts and the candidate presses Send (0.93.0, ADR-043) |
| linkedin-message, -connect, -profile-edit, -post       | refused: LinkedIn User Agreement 8.2 item 13 (ADR-037)         |
| ats-submit                                             | refused: ADR-037 bans any application submit (O1)              |
| event-rsvp                                             | refused: no event host's terms have been ruled permissive (O9); `check_channel_catalog.py` K8 refuses a permissive event-host entry while no RSVP is built |
| site-register                                          | refused (B7a decision): no pre-fill is built, and the outbound-click guard does not hold a registration form's submit (its verbs are send/connect/invite/apply/share/post/inmail) |

`me` NEVER MEANS UNATTENDED APPROVAL (owner ruling). It means the engine performs the act after the candidate approves that act.
For email the act is a draft, never a send (owner ruling 2026-11-23, ADR-043): the candidate approves in an attended run (the
explicit `--attended` form, `posture.py`), the message goes into their drafts, and they press Send. A scheduled run only drafts
what was already approved: `sending/approval.py`.

THE KEYS ARE REGISTERED (B7a). One enum key per action type, `actions.modes.<type>`, and `actions.email.stage`, are defined in
`reach/keys.py` (the registry's extension point: `config_keys.py` may not grow) and merged into `config_keys`' registry; this module
reads each value through `config_keys.describe`, and the refusal reasons are `reach/keys.py`'s, the same text `doctor.py`'s CONFIG
CURRENCY prints on the key's own row. The object checks (a non-object, an unknown type name) stay here: they are about the object,
not one key.

An edit of a resume variant file is not an action type (owner ruling 2026-11-23): the file is the candidate's own, so
`recording/presence_verbs.py` writes it with no mode. A LinkedIn target there is asked about as `linkedin-profile-edit`, so its
refusal is this table's. An `actions.modes` key naming no type above (the 0.93.0 branch's removed `variant-edit` included) is
refused by `raw_modes`, loudly, never ignored.

Capability module of `outbox.py` and `sending/approval.py`. Python 3.9+, standard library only."""

import config_keys
from reach import keys as _rk

KEY = _rk.ACTION_MODES
DEFAULT = _rk.ACTION_MODE_DEFAULT
VALUES = _rk.ACTION_MODE_VALUES
EMAIL_SEND = _rk.EMAIL_SEND
TYPES = _rk.ACTION_TYPES
GMAIL_MULTI = _rk.GMAIL_MULTI
ME_REFUSED = _rk.ME_REFUSED
STAGE_KEY = _rk.EMAIL_STAGE
STAGE_VALUES = _rk.EMAIL_STAGE_VALUES


class ModeError(ValueError):
    """`actions.modes` cannot be read, or asks for a mode its type does not offer. Loud: never coerced to `you` silently."""


def raw_modes(cfg):
    """The `actions.modes` object as written, `{}` when absent. Raises `ModeError` for a non-object or an unknown type key."""
    if not isinstance(cfg, dict):
        raise ModeError("config.json is not an object, so %s cannot be read" % KEY)
    actions = cfg.get("actions")
    if actions is None:
        return {}
    if not isinstance(actions, dict):
        raise ModeError("config.json `actions` is %r, not an object" % (actions,))
    modes = actions.get("modes")
    if modes is None:
        return {}
    if not isinstance(modes, dict):
        raise ModeError("%s is %r, not an object keyed by action type" % (KEY, modes))
    unknown = sorted(k for k in modes if k not in TYPES)
    if unknown:
        raise ModeError("%s names unknown action type(s) %s (known: %s)" % (KEY, ", ".join(unknown), ", ".join(TYPES)))
    return modes


def me_refusal(cfg, action):
    """Why `me` is not offered for `action` under `cfg`, or None when it is (`reach/keys.me_refusal`)."""
    return _rk.me_refusal(cfg, action)


def resolve(cfg, action):
    """"you" or "me" for `action`. Raises `ModeError` naming why for anything it cannot honour."""
    if action not in TYPES:
        raise ModeError("%r is not an action type (known: %s)" % (action, ", ".join(TYPES)))
    key = _rk.mode_key(action)
    if action in raw_modes(cfg) and raw_modes(cfg)[action] not in VALUES:   # an explicit null too: never read as the default
        raise ModeError("%s is %r; it must be one of %s" % (key, raw_modes(cfg)[action], ", ".join(VALUES)))
    value, _provenance = config_keys.describe(cfg, key)
    why = _rk.refusal(cfg, key)
    if why:
        raise ModeError("%s is %r, which is refused: %s" % (key, value, why))
    return value


def stage_policy(cfg):
    """"ask" or "auto": when the daily run puts ready drafts in the mailbox (O7). Raises `ModeError` for any other value: an
    unreadable switch is never read as either."""
    if not isinstance(cfg, dict):
        raise ModeError("config.json is not an object, so %s cannot be read" % STAGE_KEY)
    value, _provenance = config_keys.describe(cfg, STAGE_KEY)
    why = _rk.refusal(cfg, STAGE_KEY)
    if why:
        raise ModeError("%s is %r, which is refused: %s" % (STAGE_KEY, value, why))
    return value
