"""adoption.referencepropose -- the reference layout adopt SUGGESTS (site-studio 0.9.0, dev 1061; design-reference-layout section 1.6, the
owner's answer O-2, 2026-11-25). Part of the `adoption` package behind the entry point `adopt.py`.

THE LINE THIS HOLDS (O-2). Wherever data comes in, the plugin suggests the whole layout by itself, so the facts sit in their own keys before
the site's look changes. In adopt that is a measured SETTING, `referenceLayout` (`settings.SETTING_ORDER`), whose value is the list of
keys written: `["project", "type", "channel"]`, a part of it, `[]` (the person said `none`), or absent. `apply` writes the SURE rows of
those keys unless the person said no (`adopt.py setting referenceLayout none`, or a part), only where no page gets worse (`for_parity`),
only while site-studio is the publisher (`taken`), and only after every word was printed (`lines`, in `check`, `inventory`, `parity` and
`apply --dry-run`). The closing `site.json` `references` text is printed to copy and is NEVER written by adopt: a closed list refuses the
next new word.

ROWS. `propose` is pure over a tree (`paths`, `read`) as the conversion leaves it, after `references`, `pieces`, `pageFiles` and the file
accounting (`convert.converted_site_files` calls `run` last, so a reference or a piece the accounting archives is not in the tree it reads).
Per reference and per key, one `Row`: the value, the evidence, and SURE or `you decide` (§1.6's table). Only sure rows are written.

  project   sure: exactly one piece (a draft is no evidence: it has no page) names it on a `ref:` line, and no video row of another piece
            holds its address; or no piece names it and exactly one holds its address on a video row, a gallery video or a bare video line.
  channel   sure: the address is a platform's (`capturing.platforms`, the same host rule capture uses) and neither `site` nor the part of
            `kind` before its last `-` names another platform (letters and digits, case folded). A file host is never a channel.
  type      sure: `kind` is `<platform>-<form>` with the address's own platform and `<form>` is post, video, reel or article. A bare
            `article` or `video` says little (capture writes them from `og:type`): `you decide`.

A key the reference already holds, a blank one included, is never proposed and never overwritten (so a person keeps one reference out by
writing `"channel": ""`). With a site list in `site.json` (`references.types` / `channels`) a value outside it is `you decide`. Writing
inserts the members textually after `title` and keeps every other byte; a text it cannot place keeps the file as it was.
"""

import collections
import json
import re

from capturing import platforms
from configschema.configkeys import V9_REFERENCE_KEYS
from contentmodel import referencelayout
from contentmodel.errors import ContentError
from contentmodel.frontmatter import decode_text, parse_front_matter
from contentmodel.grammar import _GALLERY_ROW_TRAIL, _OPEN, _REFLINE, body_start_line
from contentmodel.links import video_embed

from adoption import lookperson
from adoption.scoring import refusals

NAME = "referenceLayout"
KEYS = V9_REFERENCE_KEYS
TAKEN = ("EQUAL", "MARKUP-ONLY", "ACCEPTED")        # parity verdicts under which site-studio is the publisher
FORMS = {"post": "Post", "video": "Video", "reel": "Video", "article": "Article"}      # the `<form>` of a kind, and the word it gives
REFERENCE_RE = re.compile(r"^content/references/([^/]+)/reference\.json$")
_CLOSE = re.compile(r"^:::[ \t]*$")
_LANG = re.compile(r"<html\b[^>]*\blang\s*=\s*[\"']?([A-Za-z-]+)", re.I)
LANG_FILES = ("site/templates/layout.html", "site/src/index.html")     # where a site's own `<html lang>` is written
_LIST_OF = {"type": "types", "channel": "channels"}
Row = collections.namedtuple("Row", "name key value sure why")        # value None: nothing to write; why: the evidence or the doubt
Measured = collections.namedtuple("Measured", "value how reason lines")


def _alias(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def aliases():
    """{channel: the letters-and-digits names that name it}: its own word and each host's first label (`twitter`, `youtu`)."""
    return dict((channel, set([_alias(channel)] + [_alias(h.rsplit(".", 1)[0]) for h in hosts])) for channel, hosts in platforms.PLATFORMS)


def mentions(text):
    """The channels `text` names: the whole of it, one dot-separated part of it (`www.instagram.com`), or one of its words (`Posted on
    Instagram`, `instagram_post`, `X (formerly Twitter)`), as letters and digits. A word that names a platform is a doubt, never a match."""
    if not isinstance(text, str) or not text.strip():
        return set()
    tokens = set([_alias(text)] + [_alias(p) for p in text.lower().split(".") if p] + [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w])
    return set(c for c, names in aliases().items() if names & tokens)


class Proposal(object):
    """What `propose` found: `rows`, `held` ([(reference, key)] the file already holds), `refs` ({name: path}), the site's own lists and the
    words the files already hold (`in_use`)."""

    def __init__(self, rows, held, refs, lists, in_use=None, unread=()):
        self.rows, self.held, self.refs, self.lists = rows, held, refs, lists
        self.in_use = in_use or {}                 # {"type": {word}, "channel": {word}}: the words the files already hold
        self.unread = list(unread)                 # [(name, why)]: references adopt could not read, named (never skipped unsaid)

    def sure(self, keys=KEYS):
        return [r for r in self.rows if r.sure and r.key in keys]

    def keys(self):
        """The keys with at least one sure row, in the layout's order."""
        have = set(r.key for r in self.rows if r.sure)
        return [k for k in KEYS if k in have]

    def words(self):
        """{"type": {word: count}, "channel": {word: count}} of the sure rows."""
        out = dict((k, collections.Counter()) for k in _LIST_OF)
        for r in self.sure():
            if r.key in out:
                out[r.key][r.value] += 1
        return out


# ------------------------------------------------------------------------------------------------------------------ reading the tree
def _lists(read, paths):
    """The site's `references` object (`types`, `channels`), or {} (read from the converted `site/site.json`)."""
    if "site/site.json" not in paths:
        return {}
    try:
        got = json.loads(read("site/site.json").decode("utf-8")).get("references")
    except (ValueError, UnicodeDecodeError, AttributeError):
        return {}
    return got if isinstance(got, dict) else {}


def _references(paths, read, unread):
    """[(name, path, text, data)] of every reference whose file is JSON text holding an object, in name order; each one that is not
    (a byte order mark, text that is not JSON, a member named twice) goes into `unread` as (name, why): adopt suggests nothing for it."""
    out = []
    for path in sorted(paths):
        m = REFERENCE_RE.match(path)
        if not m:
            continue
        try:
            text = read(path).decode("utf-8")
            data = json.loads(text)
        except (ValueError, UnicodeDecodeError, KeyError):
            unread.append((m.group(1), "it begins with a byte order mark" if read(path).startswith(b"\xef\xbb\xbf")
                           else "it is not JSON text adopt can read"))
            continue
        if not isinstance(data, dict):
            unread.append((m.group(1), "it is not a JSON object"))
            continue
        pairs = json.loads(text, object_pairs_hook=lambda p: p)
        if len(set(k for k, _v in pairs)) != len(pairs):
            unread.append((m.group(1), "a member is named twice"))
            continue
        if insert_members(text, [("\u0000", 0)]) is None:
            unread.append((m.group(1), "adopt cannot place a key after its title (no plain \"title\" member)"))
            continue
        out.append((m.group(1), path, text, data))
    return out


def video_id(url):
    """The address a video plays from (`links.video_embed`), so `youtu.be/<id>` and `youtube.com/watch?v=<id>` are one video; else the
    address as written."""
    return video_embed(url.strip()) or url.strip()


def site_lang(paths, read):
    """The language the site says it is in, lower case, or None: a `lang` in `site/site.json` (the build has no such key, so this reads only
    a file another tool wrote), else the `<html lang>` of its layout template or its home page."""
    if "site/site.json" in paths:
        try:
            got = json.loads(read("site/site.json").decode("utf-8")).get("lang")
        except (ValueError, UnicodeDecodeError, AttributeError, KeyError):
            got = None
        if isinstance(got, str) and got.strip():
            return got.strip().lower()
    for path in LANG_FILES:
        if path in paths:
            try:
                m = _LANG.search(read(path).decode("utf-8", "replace"))
            except KeyError:
                continue
            if m:
                return m.group(1).lower()
    return None


def _video_urls(lines):
    """The addresses a body writes as a video: a `:::videos` row's, a gallery video row's, a line that holds only the link."""
    stack, urls = [], []
    for line in lines:
        s = line.rstrip()
        m = _OPEN.match(s)
        if m:
            stack.append(m.group(1))
        elif _CLOSE.match(s):
            if stack:
                stack.pop()
        elif stack and stack[-1] == "videos":
            cols = [c.strip() for c in s.split("|")]
            if len(cols) in (2, 3) and cols[1]:
                urls.append(cols[1])
        elif stack and stack[-1] == "gallery":
            v = _GALLERY_ROW_TRAIL.match(s.strip())
            if v:
                urls.append(v.group(4).strip())
        elif not stack or stack[-1] == "part":
            if s.strip() and video_embed(s.strip()) is not None:
                urls.append(s.strip())
    return urls


def _pieces(paths, read):
    """{piece key: (names on its `ref:` lines, video ids)} of every piece with a page, read as the build reads it (`decode_text`: a byte
    order mark and CR LF; `parse_front_matter`: `draft: true`). A draft is a piece but no evidence. A piece the build cannot read is
    `None`: whatever it names is a doubt."""
    out = {}
    for key in referencelayout.piece_keys(paths):
        try:
            text = decode_text(read("content/%s/index.md" % key), key)
            meta = parse_front_matter(text, key)[0]
        except KeyError:
            continue
        except ContentError:
            out[key] = None
            continue
        if meta.get("draft") is True:
            continue
        body = text.split("\n")[max(body_start_line(text) - 1, 0):]
        out[key] = (set(m.group(1) for m in (_REFLINE.match(l) for l in body) if m), set(video_id(u) for u in _video_urls(body)))
    return out


# ----------------------------------------------------------------------------------------------------------------------- the rows
def _inside(value, lists, key):
    """True when the site's own list for `key` holds `value`, or sets none."""
    words = lists.get(_LIST_OF[key]) if key in _LIST_OF else None
    return not (isinstance(words, list) and words) or value in words


def _slug_for(key, keys):
    """The value written for the piece `key` (`work/harbor-lights`): its bare slug when one portfolio holds it, else `<portfolio>/<slug>`."""
    slug = key.partition("/")[2]
    return slug if referencelayout.resolve(slug, keys)[0] == key else key


def _project(name, url, pieces, keys):
    broken = sorted(k for k, v in pieces.items() if v is None)
    if broken:
        return Row(name, "project", None, False, "the build cannot read %s, so which piece names it is not known" % ", ".join(broken))
    named = sorted(k for k, (refs, _v) in pieces.items() if name in refs)
    shown = sorted(k for k, (_r, vids) in pieces.items() if url and video_id(url) in vids)
    if len(named) > 1:
        return Row(name, "project", _slug_for(named[0], keys), False,
                   "%d pieces name it on a ref: line (%s); the build shows the first, %s" % (len(named), ", ".join(named), named[0]))
    if named and set(shown) - set(named):
        return Row(name, "project", None, False, "a ref: line of %s and a video row of %s name different pieces" % (named[0], ", ".join(shown)))
    if named:
        return Row(name, "project", _slug_for(named[0], keys), True, "the one piece that names it on a ref: line is %s" % named[0])
    if len(shown) == 1:
        return Row(name, "project", _slug_for(shown[0], keys), True, "no ref: line names it; the one piece with its address on a video is %s" % shown[0])
    if shown:
        return Row(name, "project", None, False, "%d pieces hold its address on a video (%s)" % (len(shown), ", ".join(shown)))
    return Row(name, "project", None, False, "no piece names it")


def _channel(name, data, guess):
    if guess.host_kind == "file":
        return Row(name, "channel", None, False, "its address is a file host, which cannot say where it was seen")
    if guess.channel is None:
        return Row(name, "channel", None, False, "its address is not a known platform's")
    kind = data.get("kind") if isinstance(data.get("kind"), str) else ""
    other = (mentions(data.get("site")) | mentions(kind)) - set([guess.channel])
    if other:
        return Row(name, "channel", guess.channel, False, "the address says %s, and site or kind names %s" % (guess.channel, " and ".join(sorted(other))))
    return Row(name, "channel", guess.channel, True, "the address is %s's" % guess.channel)


def _type(name, data, guess, lang=None):
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        return None
    head, _dash, form = kind.strip().rpartition("-")
    word = FORMS.get(form.lower())
    if word is None:
        return None
    if guess.channel is not None and head and _alias(head) in aliases()[guess.channel]:
        if guess.type is not None and guess.type != word:
            return Row(name, "type", word, False, "its kind %s says %s, and its address says %s" % (kind.strip(), word, guess.type))
        if lang and not lang.startswith("en"):
            return Row(name, "type", word, False, "the word is English and the site's pages say lang=\"%s\": say it in the site's own words"
                       % lang)
        return Row(name, "type", word, True, "its kind %s is %s's %s" % (kind.strip(), guess.channel, form.lower()))
    return Row(name, "type", word, False, "its kind %s says little (capture writes a bare article or video from og:type)" % kind.strip()
               if not head else "its kind %s names a platform the address is not" % kind.strip())


def propose(paths, read, lists=None):
    """The `Proposal` for the tree whose paths are `paths` and whose bytes `read(path)` gives (a conversion's overlay, or a snapshot dict's
    `__getitem__`); `lists` is the site's `references` object, read from `site/site.json` when it is None. Pure."""
    paths = list(paths)
    lists = _lists(read, set(paths)) if lists is None else lists
    pieces, keys, lang = _pieces(paths, read), referencelayout.piece_keys(paths), site_lang(set(paths), read)
    rows, held, refs, in_use, unread = [], [], {}, dict((k, set()) for k in _LIST_OF), []
    for name, path, _text, data in _references(paths, read, unread):
        refs[name] = path
        url = data.get("url") if isinstance(data.get("url"), str) else ""
        guess = platforms.guess(url)
        made = {"project": lambda: _project(name, url, pieces, keys), "type": lambda: _type(name, data, guess, lang),
                "channel": lambda: _channel(name, data, guess)}
        for key in KEYS:
            if key in data:                       # the file already holds it (blank included): never proposed, never changed
                held.append((name, key))
                if key in in_use and isinstance(data[key], str) and data[key].strip():
                    in_use[key].add(data[key].strip())
                continue
            row = made[key]()
            if row is None:
                continue
            if row.sure and not _inside(row.value, lists, row.key):
                row = row._replace(sure=False, why="%s is not one of the site's references.%s" % (row.value, _LIST_OF[row.key]))
            rows.append(row)
    return Proposal(rows, sorted(set(held)), refs, lists, in_use, unread)


def propose_files(files):
    """`propose` over a snapshot ({path: bytes})."""
    return propose(files, files.__getitem__)


# ----------------------------------------------------------------------------------------------------------------------- writing
def _members(pairs, nl, indent):
    """The text `,<nl><indent>"key": value` of each pair, or `, "key": value` when the file is one line."""
    sep = (nl + indent) if indent is not None else " "
    return "".join(",%s%s: %s" % (sep, json.dumps(k), json.dumps(v, ensure_ascii=False)) for k, v in pairs)


def insert_members(text, pairs):
    """`text` (a JSON object) with `pairs` written as members right after `title`, every other byte kept; None when the result would not
    parse as the same object plus those members, in that order (then nothing is written)."""
    try:
        old = json.loads(text, object_pairs_hook=lambda p: p)
    except ValueError:
        return None
    want = list(old)
    at = [i for i, (k, _v) in enumerate(old) if k == "title"]
    if not at or any(k in dict(old) for k, _v in pairs):
        return None
    want[at[0] + 1:at[0] + 1] = list(pairs)
    nl = "\r\n" if "\r\n" in text else "\n"
    for m in re.finditer(r'"title"\s*:\s*', text):
        try:
            _val, end = json.JSONDecoder().raw_decode(text, m.end())
        except ValueError:
            continue
        line = text.rfind("\n", 0, m.start()) + 1
        lead = text[line:m.start()]
        indent = lead if lead.strip() == "" and "\n" in text[:m.start()] else None
        new = text[:end] + _members(pairs, nl, indent) + text[end:]
        try:
            got = json.loads(new, object_pairs_hook=lambda p: p)
        except ValueError:
            continue
        if got == want:
            return new
    return None


def write(read, files, proposal, keys, notes):
    """Write the sure rows of `keys` into the references (`read(path)` their text now) and `files`: one members insert per
    reference. `notes["settings"]` gets the line `apply` repeats (the words it wrote, and any reference whose file could not take the
    insert). Returns the number of references written."""
    by_path = {}
    for r in proposal.sure([k for k in KEYS if k in (keys or ())]):
        by_path.setdefault(proposal.refs[r.name], []).append(r)
    done, left, wrote = 0, [], []
    for path in sorted(by_path):
        rows = sorted(by_path[path], key=lambda r: KEYS.index(r.key))
        new = insert_members(read(path).decode("utf-8"), [(r.key, r.value) for r in rows])
        if new is None:
            left.append(path)
            continue
        files[path] = new.encode("utf-8")
        wrote.extend(rows)
        done += 1
    if left:                                  # `_references` leaves such a file out, so this is a guard: said, never silent
        notes["settings"].append("%s: left as written, adopt could not place the keys in %s" % (NAME, ", ".join(left)))
    if wrote:
        count = collections.Counter(r.key for r in wrote)
        words = ["%s %s" % (k, ", ".join("%s (%d)" % (w, n) for w, n in sorted(c.items())))
                 for k in _LIST_OF for c in [collections.Counter(r.value for r in wrote if r.key == k)] if c]
        notes["settings"].append("%s: wrote %s into %d reference(s)%s (your own words are kept; the lists in site.json are not written)"
                                 % (NAME, ", ".join("%s (%d)" % (k, count[k]) for k in KEYS if count[k]), done,
                                    ("; words: " + "; ".join(words)) if words else ""))
    return done


def run(seen, files, d, settings, notes):
    """The conversion's last step (`convert.converted_site_files`, over `seen`, the tree after the dispositions, the layout moves and the
    token rewrites, so an archived or moved piece is not one): the proposal into `notes["referenceLayout"]` for the reports, and the sure
    rows of the setting's keys written into `files`. `d` is the converted site.json's dict. A hub or custom site has no references (the build
    loads none there), so it has nothing to suggest and the keys would only raise its schema."""
    lists = d.get("references") if isinstance(d, dict) and isinstance(d.get("references"), dict) else None
    kind = notes.get("kind") or (d.get("siteKind") if isinstance(d, dict) else None)
    proposal = Proposal([], [], {}, {}) if kind in ("hub", "custom") else propose(seen, seen.__getitem__, lists)
    notes["referenceLayout"] = proposal
    keys = settings.get(NAME)
    if isinstance(keys, (list, tuple)) and keys:
        write(seen.__getitem__, files, proposal, keys, notes)


# --------------------------------------------------------------------------------------------------------- the setting, its verdict
def taken(rows, parity):
    """{name: value} of the plan's settings `apply` writes and `check` judges by (`rows`: the plan's `settings`): the measured and the chosen,
    less a `referenceLayout` that `waits`."""
    return dict((k, v["value"]) for k, v in (rows or {}).items() if v["how"] in ("measured", "chosen")
                and not (k == NAME and waits(v, parity)))


def waits(row, parity):
    """True when the layout waits for the takeover: the person's own builder stays their publisher and may refuse a key it does not know.
    A MEASURED layout waits unless the verdict is one of `TAKEN`; one the person CHOSE waits only where parity measured DIFFERENT (with
    nothing measured, their word is the only word there is)."""
    verdict = (parity or {}).get("verdict")
    return verdict == "DIFFERENT" or (row["how"] == "measured" and verdict not in TAKEN)


def _pages(base, out):
    return sorted(set(p for p in list(base) + list(out) if p.lower().endswith((".html", ".htm")) and base.get(p) != out.get(p)))


def _verdict(local, base, out):
    """(the pages `out` changes against `base`, the first page it makes worse or the build's refusal as text, None when none): worse is
    more visible differences from the old page, counted page by page, never in total."""
    refused = refusals(out, base)
    if refused:
        return [], "the plugin's build refuses it (%s)" % str(getattr(refused[0], "message", refused[0]))[:120]
    pages = _pages(base, out)
    for page in pages:
        if lookperson.visible(local, out, [page])[0] > lookperson.visible(local, base, [page])[0]:
            return pages, page
    return pages, None


def for_parity(final, local, snapshot, evaluate, previous):
    """The `referenceLayout` row `parity` adds after the settings pass (`measure._choose_settings`, before `lookperson.for_parity`, so what
    follows measures over it): `Measured(value, how, reason, lines)` or None. The person's word (`previous`, how `chosen`) is kept and never
    measured away. Otherwise the sure keys are built (one build, with the settings `final`) against the build without them, and kept only
    where no page has more visible differences from the old page; when one has, once more with the sure `project` rows left out (the
    second and last build). Neither: absent, `you decide`, naming the page. Usually the first build equals the one without: said."""
    mine = (previous or {}).get(NAME)
    if mine and mine.get("how") == "chosen":
        return Measured(mine["value"], "chosen", mine["reason"], [])
    if local is None:
        return None
    keys = propose_files(snapshot(final)).keys()
    if not keys:
        return None
    base = evaluate(final)
    tries = [keys] + ([[k for k in keys if k != "project"]] if "project" in keys and len(keys) > 1 else [])
    worse = early = None
    for i, mine_keys in enumerate(tries):
        pages, worse = _verdict(local, base, evaluate(dict(final, **{NAME: list(mine_keys)})))
        if worse is None:
            what = "changes no page" if not pages else "changes %d page(s), none for the worse" % len(pages)
            left = "" if early is None else "; the project rows are left out, because %s has more differences from your old page with them" % early
            return Measured(list(mine_keys), "measured", "%s %s%s" % (", ".join(mine_keys), what, left), [])
        early = early or worse
    return Measured(None, "not measured", "%s gets worse with the suggested layout (%s); `adopt.py setting %s <keys>` writes some "
                    "of it anyway" % (worse, ", ".join(keys), NAME), [])


# ------------------------------------------------------------------------------------------------------------------------ printing
def _all(names):
    """Every name, in order: the block hides none (owner ruling, nothing hidden)."""
    return ", ".join(names)


def closing_text(proposal):
    """The `references` member of `site/site.json` that would close the lists to the words in use (the sure words, and those the files
    already hold), to copy; "" when no word is in use. Adopt never writes it."""
    words = proposal.words()
    lists = dict((_LIST_OF[k], sorted(set(words[k]) | set(proposal.in_use.get(k, ())))) for k in _LIST_OF if words[k] or proposal.in_use.get(k))
    return ('"references": %s' % json.dumps(lists, ensure_ascii=False)) if lists else ""


def lines(proposal, rows=None, parity=None):
    """The block `check`, `inventory`, `parity` and `apply --dry-run` print: the suggestion, EVERY sure row (reference, key and word) with
    whether it is written, every distinct `type` and `channel` word with its count, each `you decide` row with the members to add as
    text, each reference adopt could not read, the closing text, and what the setting says now (`rows` the plan's settings, `parity` its
    record). Nothing is cut short. [] when no reference is in the tree."""
    if proposal is None or not (proposal.refs or proposal.unread):
        return []
    mine = (rows or {}).get(NAME)
    chosen_none = bool(mine) and mine["how"] == "chosen" and not mine["value"]
    newer = bool(mine) and isinstance((parity or {}).get("answers"), dict) and (parity["answers"].get("setting " + NAME)
                                                                                 != (json.dumps(mine["value"], sort_keys=True) if mine["value"] else None))
    keys = list(mine["value"] or []) if mine and mine["how"] in ("measured", "chosen") and not newer and not waits(mine, parity) else []
    head = ("suggested reference layout (you said none, so the references stay as they are; `adopt.py setting %s all` writes the sure rows)" % NAME
            if chosen_none else
            "suggested reference layout (apply writes the rows marked `written`; `adopt.py setting %s none` leaves the references as they are)" % NAME)
    out = [head]
    words = proposal.words()
    for key in KEYS:
        sure = [r for r in proposal.rows if r.key == key and r.sure]
        if not sure:
            continue
        said = "; ".join("%s (%d)" % (w, n) for w, n in sorted(words[key].items())) if key in words else ""
        state = ("written" if key in keys else "not written (you left %s out)" % key if mine and mine["how"] == "chosen" and not newer
                 and mine["value"] else "not written")
        out.append("  %s: %d sure, %s: %s%s" % (key, len(sure), state, _all(["%s -> %s" % (r.name, r.value) for r in sure]),
                                                ("; every word: " + said) if said else ""))
    unsure = [r for r in proposal.rows if not r.sure]
    for r in [r for r in unsure if r.value is not None]:
        out.append("  you decide: content/references/%s/reference.json: add \"%s\": %s -- %s"
                   % (r.name, r.key, json.dumps(r.value, ensure_ascii=False), r.why))
    for key in KEYS:
        none = [r for r in unsure if r.key == key and r.value is None]
        for why in sorted(set(r.why for r in none)):
            names = [r.name for r in none if r.why == why]
            out.append("  you decide: %s for %d reference(s), nothing to suggest (%s): %s" % (key, len(names), why, _all(names)))
    for name, why in proposal.unread:
        out.append("  not read, nothing suggested or written: content/references/%s/reference.json (%s)" % (name, why))
    if proposal.held:
        out.append("  already in your files, never changed: %s" % _all(["%s of %s" % (k, n) for n, k in proposal.held]))
    close = closing_text(proposal)
    if close:
        out.append("  to close the site's lists to these words, copy into site/site.json (adopt never writes it): %s" % close)
    if not proposal.keys():
        return out
    if chosen_none:
        pass
    elif mine is None:
        out.append("  not measured yet: `adopt.py parity` builds it against your old pages, and `apply` writes only what no page is worse for")
    elif newer:
        out.append("  not written yet: your choice is newer than the last `adopt.py parity`, which has not measured it; run it again")
    elif mine["how"] == "not measured":
        out.append("  not written: %s" % mine["reason"])
    elif mine["value"] and waits(mine, parity):
        out.append("  written when site-studio takes over: your own builder is still the publisher, and it may refuse a key it does not know")
    elif mine["value"]:
        out.append("  written: %s (%s)" % (", ".join(mine["value"]), mine["reason"]))
    return out
