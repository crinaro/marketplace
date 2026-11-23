"""docx_state: the state of one variant's Word file (jobsearch 0.93.0, design-resume-docx.md §3.2, §3.3, §R2 S2-2 and
S2-8, §R3 R3-1 and R3-4; B12).

`derive` reads only what it is handed: the variant's `presence_changes` rows (already loaded and checked), the Word
file's bytes or None when there is no file, the md's bytes, this machine's id, whether the profile has a git remote,
and the identity the header zone is found by. It writes nothing and runs nothing. `has_remote` is the one reader of
the profile's git state the verb calls (R3-4: read at each run, never stored as a setting).

**Newest** is `changes.newest_document`: the greatest `written_at`, a tie going to the greater `machine` with null
lowest; never the line's position (S2-8).

**The states** (§3.2 as amended by §R3), decided in this order:

| state | when | `action` |
|---|---|---|
| `elsewhere` | NO remote, the newest row's `machine` is set and is not this machine (whatever is on disk) | `hold` |
| `none` | no file, no row | `render` |
| `missing` | a row, no file (never read as `none`; with a remote, whichever machine wrote the row) | `refuse` |
| `unrecorded` | a file, no row | texts agree: `adopt`; differ: `ask` |
| `in-sync` | bytes same, md same | `nothing` |
| `md-ahead` | bytes same, md changed | `update` |
| `layout-edited` | bytes changed, Word text same | `adopt` (md same) or `update` (md changed); never asked (R3-2) |
| `words-edited` | bytes changed, Word text changed, md same | `ask` (R3-1: never taken back by itself) |
| `both-edited` | bytes changed, Word text changed, md changed | texts agree: `adopt`; differ: `ask` |
| `stale-save` | `words-edited` or `both-edited` with differing texts, and the stale-save test matches | `ask`, with the stale line |

**R3-4.** With a remote the Word file travels with the profile: `elsewhere` is never derived and a file present here
is compared with the newest row whichever machine wrote it. With no remote (or no repository) the file is
machine-local and another machine's newest row is `elsewhere`. `here=True` (`--here --attended`) skips `elsewhere`
and checks the file present as `unrecorded` is.

**The stale-save test** (§3.2): over `changes.updates_since_adopt`, it matches when a Word paragraph that is not an md
block's text hashes into a row's `removed`, or an md block not in the Word file hashes into its `added`. A paragraph's
hash is `text_hash` of its comparison text (§4.2), the same text the alignment compares: the writer of `update` rows
records `removed` and `added` with `text_hash`, and `doc_text_sha256` with `body_sha256` over `body_texts`.

**"Texts agree"** is the alignment of the Word body (below the header zone, contact-only paragraphs left out) with the
md blocks being all `equal` (§4.3).

Capability module. Python 3.9+, standard library only."""

import hashlib
import subprocess

from presence.changes import newest_document, updates_since_adopt, word_edited_ask_id
from presence.docx_match import align, word_text
from presence.docx_package import read_part, sha256_bytes
from presence.docx_scan import scan
from presence.variant_blocks import parse_variant_blocks
from presence.variant_compose import DEFAULT_RENDER

STATES = ("none", "unrecorded", "elsewhere", "missing", "in-sync", "md-ahead", "layout-edited", "words-edited",
          "both-edited", "stale-save")
ACTIONS = ("render", "nothing", "update", "adopt", "ask", "hold", "refuse")
# §3.3: presence-apply and presence-import refuse while the variant is in one of these (not on `unrecorded`, §R1 M-1)
BLOCKS_MD_WRITES = ("words-edited", "both-edited", "stale-save")

QUESTION = ("You changed the Word file for {variant}. Update the resume we keep on file from it? "
            "If not, your change will be overwritten at the next update.")
STALE_LINE = " The file holds words from before the team's update of {date}, so it may be an older copy."
GIT_TIMEOUT = 10


class RemoteUnknown(Exception):
    """git could not say whether the profile has a remote (no git, a timeout, an unexpected failure). Never read as
    "no remote": that would make another machine's file `elsewhere`, or this machine's travel, by accident."""


class DocState:
    """What `derive` found. `state` and `action` (one of STATES, ACTIONS); `why`, one plain line; `newest`, the
    newest `document` row or None; `home`, that row's `machine`; `since`, its `written_at` date; the current
    fingerprints `doc_sha256`, `doc_text_sha256`, `source_sha256` (None where there is no file); `md_changed` and
    `bytes_changed` against the newest row; `texts_agree` (None with no file); `stale_matches`, the `update` rows the
    stale-save test matched; `scan`, `alignment` and `blocks` for the verb's edit; `header`, the header lines to print;
    and, when `action` is `ask`, `ask_id` and `question` (R3-1)."""

    __slots__ = ("variant_id", "state", "action", "why", "newest", "home", "since", "doc_sha256", "doc_text_sha256",
                 "source_sha256", "md_changed", "bytes_changed", "texts_agree", "stale_matches", "scan", "alignment",
                 "blocks", "header", "ask_id", "question", "remote")

    def __init__(self, variant_id, **kw):
        for name in self.__slots__:
            setattr(self, name, None)
        self.variant_id = variant_id
        self.stale_matches = []
        self.header = []
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def held(self):
        """True when nothing may be written to either file this run (`ask` and `hold`)."""
        return self.action in ("ask", "hold")

    def __repr__(self):
        return "<DocState %s %s: %s>" % (self.variant_id, self.state, self.action)


def text_hash(text):
    """The 64-hex hash of one paragraph's comparison text: what `removed` and `added` hold (§6.1)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def body_texts(paragraphs, alignment):
    """The comparison texts of the Word paragraphs the alignment reads as body (below the zone, not contact-only, not
    empty), in file order: what `doc_text_sha256` fingerprints."""
    idx = sorted(i for s in alignment.spans for i in s.word)
    return [word_text(paragraphs[i]) for i in idx]


def body_sha256(texts):
    """`doc_text_sha256` (§6.1): the body texts joined by newline, hashed."""
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


def _date(stamp):
    return (stamp or "")[:10] or None


def stale_save_matches(rows, variant_id, word_texts, md_texts):
    """The `update` rows newer than the newest `adopt` whose `removed` holds a Word text that is not an md text, or
    whose `added` holds an md text that is not in the Word file (§3.2), oldest first."""
    md_set, word_set = set(md_texts), set(word_texts)
    stray = {text_hash(t) for t in word_texts if t not in md_set}
    lost = {text_hash(t) for t in md_texts if t not in word_set}
    return [r for r in updates_since_adopt(rows, variant_id)
            if stray & set(r.get("removed") or ()) or lost & set(r.get("added") or ())]


def question(variant_id, stale_date=None):
    """R3-1's question for a variant whose Word file's words changed; with `stale_date`, the stale-save line too."""
    q = QUESTION.format(variant=variant_id)
    return q + STALE_LINE.format(date=stale_date) if stale_date else q


def _ask(st, why, stale_date=None):
    st.action = "ask"
    st.why = why
    st.ask_id = word_edited_ask_id(st.variant_id)
    st.question = question(st.variant_id, stale_date)
    return st


def _read_word(st, docx, md_text, ident, cfg, heading_styles):
    """Scan the file and align it with the md; fills the fingerprints. Raises the scan's or package's refusal."""
    blocks = parse_variant_blocks(md_text, cfg.get("page_break_marker"), cfg.get("preamble_marker"))
    sc = scan(read_part(docx))
    al = align(sc.paragraphs, blocks, ident, heading_styles)
    st.scan, st.alignment, st.blocks = sc, al, blocks
    st.header = [sc.paragraphs[i].text for i in al.header]
    st.doc_sha256 = sha256_bytes(docx)
    texts = body_texts(sc.paragraphs, al)
    st.doc_text_sha256 = body_sha256(texts)
    st.texts_agree = al.all_equal
    md_texts = [blocks[j]["text"] for j in range(len(blocks)) if j not in al.md_contact]
    return texts, md_texts


def _edited(st, rows, word_texts, md_texts):
    """Bytes changed and the Word text changed: `words-edited`, `both-edited` or `stale-save`."""
    st.state = "both-edited" if st.md_changed else "words-edited"
    if st.md_changed and st.texts_agree:
        st.action = "adopt"
        st.why = "the Word file and the md were both changed and now agree"
        return st
    st.stale_matches = stale_save_matches(rows, st.variant_id, word_texts, md_texts)
    if st.stale_matches:
        st.state = "stale-save"
        date = _date(st.stale_matches[-1].get("written_at"))
        return _ask(st, "the Word file holds words from before the team's update of %s" % date, date)
    if st.state == "words-edited":
        return _ask(st, "the Word file's words changed and the md did not")
    return _ask(st, "the Word file's words and the md both changed, and they differ")


def derive(rows, variant_id, docx, md, machine, has_remote, ident, cfg=None, heading_styles=None, here=False):
    """The state of `variant_id`'s Word file. `rows` are the checked `presence_changes` rows; `docx` the file's bytes,
    or None when no file is at the path; `md` the variant md's bytes; `machine` this machine's id (None in a profile
    with no git common dir); `has_remote` `has_remote(root)`'s answer; `ident` `docx_match.identity(user)`; `cfg` the
    render settings holding `page_break_marker` and `preamble_marker` (default `DEFAULT_RENDER`); `here` True under
    `--here --attended`. Returns a `DocState`; raises `docx_scan.ScanRefusal` or `docx_package.PackageRefusal` on a
    file it cannot read."""
    if not isinstance(has_remote, bool):
        raise TypeError("has_remote must be True or False (got %r): an unknown remote is never read as none"
                        % (has_remote,))
    cfg = cfg or DEFAULT_RENDER
    newest = newest_document(rows, variant_id)
    st = DocState(variant_id, newest=newest, remote=has_remote, source_sha256=sha256_bytes(md))
    if newest is not None:
        st.home = newest.get("machine")
        st.since = _date(newest.get("written_at"))
    if (newest is not None and not has_remote and not here and st.home is not None and st.home != machine):
        st.state, st.action = "elsewhere", "hold"
        st.why = "its Word file is kept on another machine (last written %s)" % st.since
        return st
    if docx is None:
        if newest is None:
            st.state, st.action, st.why = "none", "render", "no Word file and no record of one"
        else:
            st.state, st.action = "missing", "refuse"
            st.why = "the record says a Word file was written (%s) and none is at the path" % st.since
        return st
    word_texts, md_texts = _read_word(st, docx, md.decode("utf-8"), ident, cfg, heading_styles)
    if newest is None or here:
        st.state = "unrecorded"
        if st.texts_agree:
            st.action, st.why = "adopt", "a Word file with no record, whose words agree with the md"
            return st
        return _ask(st, "a Word file with no record, whose words differ from the md: neither side is known newer")
    st.md_changed = st.source_sha256 != newest.get("source_sha256")
    st.bytes_changed = st.doc_sha256 != newest.get("doc_sha256")
    if not st.bytes_changed:
        st.state = "md-ahead" if st.md_changed else "in-sync"
        st.action = "update" if st.md_changed else "nothing"
        st.why = "the md changed since the team's last write" if st.md_changed else "nothing changed"
        return st
    if st.doc_text_sha256 == newest.get("doc_text_sha256"):
        st.state = "layout-edited"
        st.action = "update" if st.md_changed else "adopt"
        st.why = "the Word file's layout changed and its words did not"
        return st
    return _edited(st, rows, word_texts, md_texts)


def blocks_md_write(state):
    """§3.3: True when `presence-apply` and `presence-import` must refuse for a variant in `state`."""
    return state in BLOCKS_MD_WRITES


def has_remote(root):
    """R3-4: True when the profile at `root` names at least one git remote, False when it names none or is not a git
    repository. Raises `RemoteUnknown` when git cannot answer (not on PATH, a timeout, another failure)."""
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--git-dir"], capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise RemoteUnknown("git could not be run (%s)" % type(e).__name__)
    if r.returncode != 0:
        if "not a git repository" in (r.stderr or ""):
            return False
        raise RemoteUnknown("git rev-parse failed: %s" % (r.stderr or "").strip()[:200])
    try:
        r = subprocess.run(["git", "-C", root, "remote"], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise RemoteUnknown("git could not be run (%s)" % type(e).__name__)
    if r.returncode != 0:
        raise RemoteUnknown("git remote failed: %s" % (r.stderr or "").strip()[:200])
    return bool((r.stdout or "").strip())
