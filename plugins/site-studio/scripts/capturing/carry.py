"""capturing/carry.py -- what a forced recapture keeps of the reference.json it replaces (site-studio 0.8.0, G3, dev #1037;
design-adopt-local-reach section 1.3). Python 3.9, standard library only.

`capture.py --force` replaces the page's text and the card picture and rewrites the keys capture writes (`CAPTURE_KEYS`); every
other key of the old file is the person's (`author`, `image`, `fetched`, `imageAlt`, `imagePosition`, and `role` unless --role gave
one). With the SAME url they are carried into the new file and one line names them; with a different url the page is a different
page, nothing is carried, and one line names each key not carried with its value. A file that cannot be read carries nothing and
says so (a missing thing is never an empty thing). A kept `image` names the card, so no `card.jpg` is written beside it (the loader
refuses a reference with both); with no `image`, a kept `imageAlt` or `imagePosition` describes the `card.jpg` this run replaced,
and the line says so.

    read_replaced(folder)                  (the old reference.json as a dict, None) | (None, None) none there | (None, problem)
    keeps_image(old, url)                  True when the old file names a card by `image` and the url is the same
    merge(old, unread, ref, url, name)     adds the carried keys to `ref`; returns the lines to print, each led by `name`
    carry_over(old, ref, url)              ({key: value} to carry, [line]): the rule `merge` applies
"""
import json
import os

# The keys capture itself writes into reference.json: this run's on a recapture, never carried from the old file (a `description`
# the page no longer has is dropped). `role` is the person's unless --role gives one. Pinned equal to the loader's base table by
# test_capture.py.
CAPTURE_KEYS = ("url", "title", "description", "site", "published", "kind", "captured")


def read_replaced(folder):
    """(the reference.json being replaced as a dict, problem). (None, None) when the folder has none; (None, text) when it
    cannot be read, which the caller names rather than treating as empty."""
    path = os.path.join(folder, "reference.json")
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError) as e:
        return None, "%s could not be read (%s)" % (path, e)
    if not isinstance(old, dict):
        return None, "%s is not a JSON object" % path
    return old, None


def keeps_image(old, url):
    return old is not None and old.get("url") == url and "image" in old


def carry_over(old, ref, url):
    """({key: value} to add to the new reference, [line to print]) for a forced recapture of `url` over the reference `old`.
    The keys of `old` this run does not write (`ref` holds the ones it does, `role` among them under --role) are the person's:
    carried when `old` is the same url, else carried never, and named with their values."""
    person = dict((k, v) for k, v in old.items() if k not in CAPTURE_KEYS and k not in ref)
    if not person:
        return {}, []
    if old.get("url") != url:
        listed = "; ".join("%s = %s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in sorted(person.items()))
        return {}, ["the previous reference.json was captured from %s, not %s, so nothing was carried over; not carried: %s"
                    % (old.get("url"), url, listed)]
    notes = ["kept from the previous reference.json: %s" % ", ".join(sorted(person))]
    companions = [k for k in ("imageAlt", "imagePosition") if k in person]
    if companions and "image" not in person:
        notes.append("kept %s, which described the card.jpg this capture has replaced: check the new picture still fits"
                     % " and ".join(companions))
    if "image" in person:
        notes.append("image %s names the card, so no card.jpg was written beside it; the picture is the one you named"
                     % json.dumps(person["image"], ensure_ascii=False))
    return person, notes


def merge(old, unread, ref, url, name):
    """Carry what `carry_over` says into `ref` (in place); the lines to print, each led by the reference's `name`."""
    notes = ["%s; nothing was carried over" % unread] if unread else []
    if old is not None:
        kept, more = carry_over(old, ref, url)
        ref.update(kept)
        notes += more
    return ["%s: %s" % (name, n) for n in notes]
