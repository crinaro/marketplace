"""card_evidence: when a degraded query holds a shown role, and when its own card answers for it (jobsearch 0.94.0, dev 1055; docs/design-role-first.md 5.1, 3.5 part C).

Until 0.94.0 a role was held aside ("quarantined") whenever EVERY query that showed it was degraded, whatever the degradation. A search that
dropped the work-type filter held every role it showed, even one whose card said "Remote" in so many words (public 156's flood, and its
reverse). From 0.94.0 a role is held only when a degradation can have made the card WRONG and the card does not say otherwise:

  code                       what it damages                              holds a shown role unless its card states
  filter-dropped worktype    the work setting may be wrong                its setting (a setting word in `setting=`, or "(Remote)" and
                                                                          the like in the place)
  filter-dropped location    the place may be elsewhere                   a place that is not an echo of the owner's own commute anchor
  filter-dropped date,       the posting may be old                       `posted=`
  window-unapplied
  query-unparsed             nothing is known of the query                (nothing: it always holds)
  filter-dropped pay / seniority / jobtype / other, truncated, param-added
                             coverage, or what the first look and the JD read test anyway
                                                                          NEVER holds: a gap and a count (`query_gaps.file_query_gaps`)

A query VOUCHES for a role when none of its holding codes is left unanswered by the card; the role is held only when NO query that showed
it vouches. The item then carries only the unanswered codes, sorted. `?` and `none stated` are never a stated setting, and a setting the
classifier cannot resolve (`unresolved`: contested wording or no setting word) does not answer either. A card answers per ROLE line: the same
card answers for every query that showed the role. Nothing here reads a file: `Evidence.from_config(cfg)` is built by the entry point from the
profile's `config.json` (a package imports no entry point, G5).

TWO LEAF COPIES, STATED (OURS; measured 2026-11-25 with `scripts/check_segmentation.py`): the setting words are
`recording.reads.type_from_setting`'s and the echo test is `profile.anchor_echo`'s, copied here because `deferred.py` may not import either.
Importing `recording.reads` grows the plugin's largest import cycle from 39 to 41 (G6), and a second `import profile` makes the 20th
entry-point import of `deferred.py` (G5.L2, 19 at the merge-base). `tests/searching/test_card_evidence.py::TestParityWithTheShippedClassifier`
and `tests/test_card_evidence_roles.py::TestEchoParity` run both copies against the originals over a battery, so a change to an original that
is not made here goes red.

Pure. Python 3.9+, standard library only."""

import re

SETTING_WORDS = ("remote", "hybrid", "onsite")          # what `type_from_setting` returns for a stated setting
NOT_STATED = ("", "?", "none stated")

_SET_REMOTE = ("remote", "telecommut", "work from home", "work-from-home", "wfh", "work from anywhere")
_SET_HYBRID = ("hybrid",)
_SET_ONSITE = ("on-site", "onsite", "on site", "in-office", "in office", "in-person", "in person")
_PLACE_PAREN = re.compile(r"\([^)]*\)")

# which fact of the card answers a dropped filter; a filter not named here never holds a role (a gap and a count only)
FILTER_NEEDS = {"worktype": "setting", "location": "place", "date": "posted"}


def setting_type(text):
    """`remote`, `hybrid`, `onsite` or `unresolved` for a work-setting text: `recording.reads.type_from_setting(text, None)[0]` for any text
    that is not `none stated`, which this module never asks about. `hybrid` with `remote` beside it, `remote` with `onsite`, and no
    setting word at all are `unresolved`: contested or unreadable wording states no setting."""
    t = str(text or "").casefold()
    remote = any(w in t for w in _SET_REMOTE)
    hybrid = any(w in t for w in _SET_HYBRID)
    onsite = any(w in t for w in _SET_ONSITE)
    if hybrid:
        return "unresolved" if remote else "hybrid"
    if remote and onsite:
        return "unresolved"
    if remote:
        return "remote"
    return "onsite" if onsite else "unresolved"


def place_core(text):
    """`profile._place_core`: the city part of a place text, case-folded, a parenthetical and everything after the first comma dropped,
    punctuation removed; None when nothing is left."""
    if not isinstance(text, str):
        return None
    t = _PLACE_PAREN.sub(" ", text).split(",")[0]
    return " ".join(re.sub(r"[^\w]+", " ", t.casefold()).split()) or None


def anchor_cores(cfg):
    """The set of `place_core`s of `cfg["geography"]["commute_anchors"]` (an entry that is not an object is skipped, as `profile` does), or None
    when `cfg` is not a readable config: then no place answers, because an echo proves nothing and an unreadable config cannot say."""
    if not isinstance(cfg, dict):
        return None
    geo = cfg.get("geography")
    anchors = geo.get("commute_anchors") if isinstance(geo, dict) else None
    anchors = [a for a in anchors if isinstance(a, dict)] if isinstance(anchors, list) else []
    return frozenset(c for c in (place_core(a.get("place")) for a in anchors) if c)


def holding_needs(q):
    """`{code: {need, ...}}` for a REACHED query: the holding codes it carries, each with the card facts (`setting`, `place`, `posted`) that
    answer it. A code absent here never holds a role. `q` is a parsed QUERY dict of `deferred.parse_roles`."""
    out = {}
    if q.get("window_gap"):
        out["window-unapplied"] = {"posted"}
    needs = {FILTER_NEEDS[f] for f in (q.get("dropped") or ()) if f in FILTER_NEEDS}
    if needs:
        out["filter-dropped"] = needs
    return out


class Evidence:
    """What a card can state, read off a parsed ROLE entry. `anchors` is `anchor_cores(config)`: the owner's own commute places, or None."""

    def __init__(self, anchors):
        self.anchors = anchors

    @classmethod
    def from_config(cls, cfg):
        return cls(anchor_cores(cfg))

    def echo(self, place):
        """True when a card's place is one of the owner's own anchors (a board searched at home prints it on every card), or cannot be told."""
        if self.anchors is None:
            return True
        return any(place_core(part) in self.anchors for part in re.split(r"[;|]", place))

    def states_setting(self, role):
        for text in (role.get("setting"), role.get("location")):
            text = str(text or "").strip()
            if text.casefold() not in NOT_STATED and setting_type(text) in SETTING_WORDS:
                return True
        return False

    def states_place(self, role):
        place = str(role.get("location") or "").strip()
        return place.casefold() not in NOT_STATED and not self.echo(place)

    @staticmethod
    def states_posted(role):
        return (role.get("posted_parsed") or ("unknown", None))[0] != "unknown"

    def answers(self, role, needs):
        """True when the card states EVERY fact in `needs`."""
        have = {"setting": self.states_setting, "place": self.states_place, "posted": self.states_posted}
        return all(have[n](role) for n in needs)

    def unanswered(self, role, q):
        """The sorted holding codes of query `q` (None: a QUERY line that did not parse) that the card of `role` leaves unanswered."""
        if q is None:
            return ["query-unparsed"]
        return sorted(code for code, needs in holding_needs(q).items() if not self.answers(role, needs))

    def verdict(self, role, ordinals):
        """`quarantine_codes` of `role`: the sorted union of the unanswered holding codes of its queries when NO query vouches (each has some),
        else None. `ordinals` is `{ordinal: parsed query}`; `role["q"]` its ordinals, every one in range and reached (the parser checks)."""
        per_query = [self.unanswered(role, ordinals.get(k)) for k in role["q"]]
        if not per_query or any(not codes for codes in per_query):
            return None
        return sorted({c for codes in per_query for c in codes})
