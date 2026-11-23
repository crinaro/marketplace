"""keys: small value predicates and the dotted lookup the `config.json` key registry shares.

`_get_dotted(cfg, "a.b.c")` walks a loaded `config.json` dict and returns None where a step is missing or is not an object;
`_is_pos_int` and `_is_number` are the strict type tests the registry's validators use (a bool is never a number). Moved out of
`config_keys.py` unedited (jobsearch 0.91.0 B4 step A); `config_keys.py` stays the one registry and re-exports every name.
Capability module of `config_keys.py`. Python 3.9+, standard library only."""


def _is_pos_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _get_dotted(cfg, dotted):
    node = cfg or {}
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


# ── jobsearch 0.91.0 (design-build-reach.md 5.3, 5.5, 6.2, 6.5): the BUILD keys. Registered into `config_keys` (`READER_KEYS`,
# `_METADATA`) from here, so a reader resolves them through `config_keys.describe`/`resolve_int` like every other key. None is
# seeded: an absent key reads the registered default.
#
# `reach.kinds_off` -- BUILD kinds the candidate does not want ranked (names from `reach.build.ALL_KINDS`, default []);
#     `reach.build.kinds_off` is its strict parser (an unknown name is loud, never ignored).
# `access.employment_recheck_days` -- a `current` employment last stated longer ago than this is still counted and is listed once
#     to re-confirm (owner O12), 90..1095, default 365 (`reach.standing.RECHECK_DAYS`).
# `network.employment_confirms_per_run` -- at most this many people are asked about in one attended run's grouped confirm
#     question, highest company motivation first (5.5), 1..25, default 5.
# `network.event_suggestions_per_week` -- at most this many public events the strategist suggests in its weekly turn (6.5),
#     0..10, default 3; 0 turns the suggestions off.
# `network.conversations_per_week` -- the week's conversation target the weekly measures print against (8), 0..20, default 2.
REACH_KINDS_OFF = "reach.kinds_off"
NETWORK_CONVERSATIONS_PER_WEEK = "network.conversations_per_week"
ACCESS_EMPLOYMENT_RECHECK_DAYS = "access.employment_recheck_days"
NETWORK_EMPLOYMENT_CONFIRMS_PER_RUN = "network.employment_confirms_per_run"
NETWORK_EVENT_SUGGESTIONS_PER_WEEK = "network.event_suggestions_per_week"
METADATA = {
    REACH_KINDS_OFF: ([], "list", ("BUILD kind names: advice-ask, affiliation-lookup, side-door, hm-note, recruiter-direct, "
                                   "plain-lookup, event, career-services",),
                      "BUILD kinds you do not want suggested at a company with no way in (for example side-door); [] means "
                      "every kind (jobsearch 0.91.0)"),
    ACCESS_EMPLOYMENT_RECHECK_DAYS: (365, "int", (90, 1095),
                                     "days after which someone you said works at a company is listed once to re-confirm; they "
                                     "are still counted (jobsearch 0.91.0)"),
    NETWORK_EMPLOYMENT_CONFIRMS_PER_RUN: (5, "int", (1, 25),
                                          "most people one attended run asks you to confirm still work where the record says, "
                                          "highest-motivation company first (jobsearch 0.91.0)"),
    NETWORK_EVENT_SUGGESTIONS_PER_WEEK: (3, "int", (0, 10),
                                         "most public events the weekly strategy turn suggests (suggestions only; nothing is "
                                         "registered); 0 turns them off (jobsearch 0.91.0)"),
    NETWORK_CONVERSATIONS_PER_WEEK: (2, "int", (0, 20),
                                     "conversations a week you aim to hold; the weekly measures print the week's held chats "
                                     "against it (jobsearch 0.91.0)"),
}


# ── jobsearch 0.91.0 B7a (design-build-reach.md 9.2, 10.1, 10.2; owner O1, O4, O7, O9, O14 and the 2026-11-21 amendment): the
# action keys. They are registered from HERE, beside the BUILD keys, for two measured reasons: `config_keys.py` is over its module
# budget and may not grow (the segmentation ratchet), and a module that registers into it must not import it back (G6). So the
# policy tables `sending/modes.py` resolves against live here too, and `doctor.py`'s CONFIG CURRENCY reads `refusal` through
# `config_keys` (no new import there): a refused value is loud at config-check time, with its reason, on the key's own row.
#
# `actions.modes.<type>` -- "you" (default: the candidate does it) or "me" (the engine does it after the candidate approves that
#     act; never unattended). `me` is OFFERED only where `ME_REFUSED` has no entry for the type, and for email-send only while
#     `communications.mail_connector` is gmail-multi (O4).
# `actions.email.stage` -- "ask" (default: a draft is put in the mailbox on the candidate's request) or "auto" (the daily run stages
#     every ready draft in its write phase (daily-run section 7), `outbox.py stage --all-ready`; O7). gmail-multi cannot delete a draft.
ACTION_MODES = "actions.modes"
ACTION_MODE_VALUES = ("you", "me")
ACTION_MODE_DEFAULT = "you"
EMAIL_SEND = "email-send"
ACTION_TYPES = (EMAIL_SEND, "linkedin-message", "linkedin-connect", "linkedin-profile-edit", "linkedin-post", "event-rsvp",
                "site-register", "ats-submit")
MAIL_CONNECTOR_KEY = "communications.mail_connector"
GMAIL_MULTI = "gmail-multi"            # also `config_keys.MAIL_CONNECTOR_DEFAULT`; tests/reach/test_keys.py pins the two equal
ME_REFUSED = {
    "linkedin-message": "LinkedIn's User Agreement (8.2 item 13) bans software that sends messages for a member (ADR-037)",
    "linkedin-connect": "LinkedIn's User Agreement (8.2 item 13) bans software that sends invitations for a member (ADR-037)",
    "linkedin-profile-edit": "LinkedIn's User Agreement (8.2 item 13) bans software that edits a profile (ADR-037)",
    "linkedin-post": "LinkedIn's User Agreement (8.2 item 13) bans software that posts for a member (ADR-037)",
    "ats-submit": "ADR-037 bans any application submit by the engine (owner O1)",
    "event-rsvp": "no event host's terms have been ruled permissive (owner O9; the catalog's event-host entries, rule K8)",
    "site-register": ("no registration pre-fill is built in this engine (owner O14), and nothing mechanical holds a "
                      "registration form's submit: the outbound-click guard's verbs do not include register or sign up"),
}
EMAIL_STAGE = "actions.email.stage"
EMAIL_STAGE_VALUES = ("ask", "auto")
EMAIL_STAGE_DEFAULT = "ask"


def mode_key(action):
    """`actions.modes.<action>`, the registered key of one action type."""
    return "%s.%s" % (ACTION_MODES, action)


def me_refusal(cfg, action):
    """Why `me` is not offered for `action` under the loaded `config.json` dict `cfg`, or None when it is. An absent connector
    selection is gmail-multi (its registered default); any other value, a misspelling included, refuses `me` (O4)."""
    if action in ME_REFUSED:
        return ME_REFUSED[action]
    if action == EMAIL_SEND:
        connector = _get_dotted(cfg, MAIL_CONNECTOR_KEY)
        connector = GMAIL_MULTI if connector is None else connector
        if connector != GMAIL_MULTI:
            return ("the selected mail connector is %r; only gmail-multi's send tools carry the platform's every-call prompt "
                    "(owner O4)" % (connector,))
    return None


def refusal(cfg, key):
    """Why the value `cfg` holds for the registered action key `key` cannot be honoured, or None (also None for every key this
    section does not own, and for an absent value, which reads the default). What `doctor.py`'s CONFIG CURRENCY prints, FAIL, on
    the key's own row; `sending/modes.py` raises the same reasons at use."""
    if key not in ACTION_METADATA:
        return None
    value = _get_dotted(cfg, key)
    if value is None:
        return None
    legal = ACTION_METADATA[key][2]
    if value not in legal:
        return "%r is not one of %s" % (value, ", ".join(legal))
    if key.startswith(ACTION_MODES + ".") and value == "me":
        why = me_refusal(cfg, key[len(ACTION_MODES) + 1:])
        if why:
            return "me is refused: %s" % why
    return None


ACTION_METADATA = {
    **{"%s.%s" % (ACTION_MODES, a): (
        ACTION_MODE_DEFAULT, "enum", ACTION_MODE_VALUES,
        "who performs a %s: you (default), or me, the engine after your approval of that act; %s (jobsearch 0.91.0)"
        % (a, ("me is not offered: " + ME_REFUSED[a]) if a in ME_REFUSED
           else "me needs the gmail-multi connector and an attended session")) for a in ACTION_TYPES},
    EMAIL_STAGE: (EMAIL_STAGE_DEFAULT, "enum", EMAIL_STAGE_VALUES,
                  "ask (default): a draft goes into your mailbox when you ask; auto: the daily run puts every ready draft "
                  "there in its write phase (gmail-multi cannot delete a draft) (jobsearch 0.91.0)"),
}

# ── jobsearch 0.92.0 (dev #1003, design-decision-surface.md B.3; owner decision 3): a reply owed ages out. Registered here, not in
# `config_keys.py` (ratcheted). Never seeded: an absent key reads 60, the `actions/stale` `days-before-stale` default.
NETWORK_REPLY_OWED_DAYS = "network.reply_owed_days"
METADATA = {**METADATA, **ACTION_METADATA,
            NETWORK_REPLY_OWED_DAYS: (60, "int", (7, 365),
                                      "a person who wrote back longer ago than this many days, with no reply drafted, is named but "
                                      "no longer listed for a reply (jobsearch 0.92.0)")}
READER_KEYS = frozenset(METADATA)
