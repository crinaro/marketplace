#!/usr/bin/env python3
"""capture.py -- capture the pages the person lists as references: one URL in, one reference folder
out (dev #835; design 5.1 and 5.3; named change M8). Python 3.9, standard library only; Chrome via
browser.py. It NEVER crawls: it loads exactly the URLs it is given and nothing they link to.

    python3 capture.py [--repo R | --out DIR] [--name NAME] [--role TEXT] [--force] URL [URL ...]

PER URL it writes, into <out>/<name>/ (default <repo>/content/references/<name>/):
    reference.json   {url, title, description, site, published, kind, captured}: the keys content.py
                     accepts, no others (the build refuses an unknown key); with --role, also
                     `role`, what the person did on that page (template-fidelity R1, dev 897)
    text.md          the page's visible text, raw material for the person's write-up; never published
    card.jpg         the first screen (1200 x 630) through images.import_media, so it is stripped of
                     metadata and gets size copies like any photo
and prints one line per URL plus a JSON packet recording the Chrome version, the platform and the
capture date (named change M8, so a later Chrome change shows).

RULES (design 5.3, 5.1)
  * --ROLE TEXT stores the person's answer to "what did you do on this?" as `role`, which a reference
    card shows as its role line. It is a schema 4 key (siteconfig.V4_REFERENCE_KEYS), so it is REFUSED
    BEFORE ANY BROWSER STARTS, writing nothing, when the site's own site.json says a lower schema (the
    build would refuse the folder as an unknown key). Where no site.json can be read (--out beside no
    site) it is stored and the run prints that the schema was NOT CHECKED. One URL only (the answer is
    about one page), one line of text, never empty: the loader refuses anything else, so capture does
    too. With no --role the reference carries no role and nothing is assumed.
  * LOGGED OUT, always. Every run launches a fresh temporary profile (browser.py): no cookies, no
    storage, never the person's browser and never the desktop app's pane. Two captures in a row
    share nothing.
  * Two platforms are captured from their OFFICIAL EMBED VIEWS, as the examples do: a YouTube URL
    from https://www.youtube-nocookie.com/embed/<id> and a Vimeo URL from
    https://player.vimeo.com/video/<id>. Everything else is captured from the page itself.
    reference.json keeps the URL the person gave.
  * 45 seconds per page (browser.LOAD_TIMEOUT); a page that does not load is reported.
  * "NOT PUBLICLY VIEWABLE" IS REPORTED, NEVER WORKED AROUND: an HTTP 401, 403, 404, 410 or 451, or a
    redirect to a sign-in page, writes NOTHING for that URL and prints why. There is no login flow,
    no cookie import, no alternate fetch.
  * An existing reference folder is not overwritten without --force. --force replaces the page's text, the card
    and the keys above and KEEPS the person's other keys (author, image, role, ...) when the url is the same, naming
    what it kept; a different url carries nothing and names each key not carried (0.8.0, dev #1037; capturing/carry.py).
  * SANDBOX. A capture of an arbitrary URL with Chrome's sandbox off happens ONLY in the disposable
    cloud case (CLAUDE_CODE_REMOTE=true as root), and this script prints that it did. In the CI case
    (GITHUB_ACTIONS=true, where only the local fixture is loaded) any URL that is not on 127.0.0.1
    is REFUSED before Chrome loads it. On a person's own machine --no-sandbox is never added
    (browser.py), so neither case arises.
  * Needs Chrome on every surface; with none the run refuses naming the install step (browser.py),
    and nothing is written.

Exit: 0 when every URL was captured; 1 when any was not (each reason is printed); 2 usage.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser  # noqa: E402
from contentmodel import links  # noqa: E402
from imaging import errors, importer   # noqa: E402
import resize   # noqa: E402
from configschema import diagnostics, model  # noqa: E402
from capturing import carry  # noqa: E402

NOT_PUBLIC = (401, 403, 404, 410, 451)
SIGN_IN = re.compile(r"/(log-?in|sign-?in|signin|sign_in|accounts?/login|sso|auth(enticate)?)(/|$|\?)", re.I)
TEXT_LIMIT = 200000
ROLE_SCHEMA = 4      # the schema that first accepts a reference's `role` (siteconfig.V4_REFERENCE_KEYS)

META_JS = """(function(){
  function meta(n){var e=document.querySelector('meta[property="'+n+'"],meta[name="'+n+'"]');
    return e ? (e.getAttribute('content')||'').trim() : '';}
  var published = meta('article:published_time') || meta('og:article:published_time') || meta('date') ||
    meta('datePublished') || meta('pubdate');
  if (!published) { var t = document.querySelector('time[datetime]'); if (t) published = t.getAttribute('datetime') || ''; }
  if (!published) {
    var ld = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < ld.length && !published; i++) {
      var m = /"datePublished"\\s*:\\s*"([^"]+)"/.exec(ld[i].textContent || ''); if (m) published = m[1];
    }
  }
  return {title: meta('og:title') || document.title || '', description: meta('og:description') || meta('description'),
          site: meta('og:site_name'), published: published, ogtype: meta('og:type'),
          finalUrl: location.href, text: (document.body ? document.body.innerText : '')};
})()"""


class CaptureError(ValueError):
    pass


def embed_url(url):
    """The official embed view for a YouTube or Vimeo URL, else None (Drive is not a platform here)."""
    e = links.video_embed(url)
    if e and (e.startswith("https://www.youtube-nocookie.com/") or e.startswith("https://player.vimeo.com/")):
        return e
    return None


def slugify(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].strip("-") or "reference"


def iso_date(s):
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})", s or "")
    return m.group(1) if m else ""


def kind_of(embed, ogtype):
    if embed or (ogtype or "").startswith("video"):
        return "video"
    return "article" if (ogtype or "") == "article" else "page"


def clean_role(text):
    """The role the person gave, as the loader will read it: text, one line, not empty."""
    if not isinstance(text, str) or not text.strip():
        raise CaptureError("--role is empty: say what you did on the page in a few words, or leave --role off")
    if "\n" in text.strip() or "\r" in text:
        raise CaptureError("--role must be one line of text: put what you did on the page on one line")
    return text.strip()


def role_schema_problem(out_root):
    """(refusal, note) for storing a role in `out_root`. `out_root` is <repo>/content/references, so the
    site's own site.json is two levels up. A site below ROLE_SCHEMA is a refusal, not a note: the build refuses
    a reference holding `role` there. A site.json that is missing or cannot be read is NOT CHECKED: the note
    says so and the role is stored."""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(out_root))), "site", "site.json")
    if not os.path.isfile(cfg_path):
        return None, ("NOT CHECKED: no site/site.json beside %s, so the site's schema is unknown; the role is "
                      "stored, and the build refuses it unless the site is at schema %d" % (out_root, ROLE_SCHEMA))
    try:
        cfg = model.load(cfg_path)
    except diagnostics.SiteConfigError as e:
        return None, ("NOT CHECKED: %s could not be read (%s), so the site's schema is unknown; the role is stored"
                      % (cfg_path, e))
    if cfg.schema < ROLE_SCHEMA:
        return ("--role is a schema %d key and this site is at schema %d: the build would refuse the reference "
                "as an unknown key. Nothing was captured. Raise the site to schema %d first "
                "(build.py raise-schema --to %d shows what would change), then capture again"
                % (ROLE_SCHEMA, cfg.schema, ROLE_SCHEMA, ROLE_SCHEMA)), None
    return None, None


def capture_one(b, resizer, url, out_root, name=None, captured=None, force=False, log=print, role=None):
    """Capture one URL. Returns {"url", "status": "captured" | "not_public" | "error", ...}. `role` is
    already clean (`clean_role`) and already checked against the site's schema (`capture_urls`)."""
    res = {"url": url}
    if not re.match(r"^https?://", url):
        res.update(status="error", reason="not an http(s) URL")
        return res
    embed = embed_url(url)
    target = embed or url
    # The CI rule is about what Chrome LOADS with its sandbox off, so it tests `target` (the embed
    # view when there is one), not the URL the person gave (CI run 43477736354).
    if b.no_sandbox == "ci" and not browser.is_local_url(target):
        res.update(status="error", reason="refused: this run has Chrome's sandbox off (the CI case, where only "
                   "the local fixture may be loaded), so it will not load %s" % target)
        return res
    try:
        page = b.new_page(width=1200, height=630, scale=1)
        page.goto(target)
    except browser.BrowserError as e:
        res.update(status="error", reason=str(e))
        return res
    if page.status in NOT_PUBLIC:
        res.update(status="not_public", reason="not publicly viewable: %s answered HTTP %d (logged out); "
                   "nothing was captured, and no workaround is attempted" % (target, page.status))
        return res
    try:
        meta = page.evaluate(META_JS)
    except browser.BrowserError as e:
        res.update(status="error", reason=str(e))
        return res
    final = urllib.parse.urlsplit(meta.get("finalUrl") or target)
    if SIGN_IN.search(final.path or "") and not SIGN_IN.search(urllib.parse.urlsplit(target).path or ""):
        res.update(status="not_public", reason="not publicly viewable: %s redirected to a sign-in page (%s); "
                   "nothing was captured, and no workaround is attempted" % (target, final.path))
        return res
    title = (meta.get("title") or "").strip() or urllib.parse.urlsplit(url).hostname or url
    host = urllib.parse.urlsplit(url).hostname or ""
    name = name or slugify("%s-%s" % (re.sub(r"^www\.", "", host), title))
    folder = os.path.join(out_root, name)
    if os.path.exists(os.path.join(folder, "reference.json")) and not force:
        res.update(status="error", reason="%s already exists; not overwritten (use --force)" % folder)
        return res
    jpeg = page.screenshot(full=False, fmt="jpeg", quality=85)
    old, unread = carry.read_replaced(folder) if force else (None, None)
    os.makedirs(folder, exist_ok=True)
    card = None
    if not carry.keeps_image(old, url):      # a kept `image` names the card: a card.jpg beside it is a second one
        tmp = tempfile.mkdtemp(prefix="site-studio-card-")
        try:
            src = os.path.join(tmp, "card.jpg")
            with open(src, "wb") as fh:
                fh.write(jpeg)
            card = importer.import_media(src, os.path.join(folder, "card.jpg"), resizer, overwrite=force)
        except errors.ImageError as e:
            res.update(status="error", reason="the card image could not be imported: %s" % e)
            return res
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    ref = {"url": url, "title": title, "description": (meta.get("description") or "").strip(),
           "site": (meta.get("site") or "").strip() or re.sub(r"^www\.", "", host),
           "published": iso_date(meta.get("published")), "kind": kind_of(embed, meta.get("ogtype")),
           "captured": captured or datetime.datetime.utcnow().strftime("%Y-%m-%d")}
    if role is not None:
        ref["role"] = role
    ref = {k: v for k, v in ref.items() if v != "" or k in ("url", "title")}
    notes = carry.merge(old, unread, ref, url, name)
    for n in notes:
        log(n)
    with open(os.path.join(folder, "reference.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ref, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    text = (meta.get("text") or "")[:TEXT_LIMIT]
    with open(os.path.join(folder, "text.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# %s\n\nSource: %s\nCaptured: %s\n\n%s\n" % (title, url, ref["captured"], text.strip()))
    res.update(status="captured", name=name, dir=folder, title=title, card=os.path.basename(card.path) if card else None,
               kind=ref["kind"], role=ref.get("role"), notes=notes)
    return res


def capture_urls(urls, out_root, name=None, captured=None, force=False, env=None, euid=None, log=print,
                 role=None):
    """Capture each URL in a fresh Chrome profile. Returns {"results": [...], "packet": {...}}. Every refusal
    that needs no page (`--name` or `--role` with more than one URL, a role that is not one line, a site below
    schema 4) raises CaptureError before Chrome starts, and nothing is written."""
    if name and len(urls) != 1:
        raise CaptureError("--name needs exactly one URL")
    if role is not None:
        if len(urls) != 1:
            raise CaptureError("--role needs exactly one URL: the role is what you did on that page")
        role = clean_role(role)
        problem, note = role_schema_problem(out_root)
        if problem:
            raise CaptureError(problem)
        if note:
            log(note)
    with browser.Browser(env=env, euid=euid) as b:
        packet = dict(b.packet())
        packet["captured"] = captured or datetime.datetime.utcnow().strftime("%Y-%m-%d")
        if b.no_sandbox == "cloud":
            log("note: Chrome ran WITHOUT its sandbox for this capture (a disposable cloud session, "
                "CLAUDE_CODE_REMOTE=true as root); it is never done on your own machine")
        packet["sandbox"] = "off-" + b.no_sandbox if b.no_sandbox else "on"
        results = []
        with resize.Resizer(b) as rz:
            for url in urls:
                r = capture_one(b, rz, url, out_root, name, captured, force, log, role)
                results.append(r)
                if r["status"] == "captured":
                    log("captured %s -> %s (%s; card %s%s)" % (url, r["dir"], r["kind"], r["card"] or "kept (image)",
                                                              "; role: %s" % r["role"] if r.get("role") else ""))
                else:
                    log("NOT CAPTURED %s: %s" % (url, r["reason"]))
    packet["urls"] = [r["url"] for r in results]
    return {"results": results, "packet": packet}


def build_parser():
    ap = argparse.ArgumentParser(prog="capture.py", allow_abbrev=False,
                                 description="Capture listed pages as references. Never crawls.")
    ap.add_argument("urls", nargs="+", metavar="URL")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--repo", help="the dev repo; writes into <repo>/content/references/ (default: the current directory)")
    g.add_argument("--out", help="the references folder to write into")
    ap.add_argument("--name", help="the reference folder name (one URL only; default: derived from the page)")
    ap.add_argument("--role", help="what you did on this page, one line (one URL only; stored as the "
                                   "reference's `role`, which needs a site at schema 4)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing reference folder, keeping the person's keys (author, image, role, ...) when the url is the same")
    ap.add_argument("--captured", help="the capture date, YYYY-MM-DD (default: today, UTC)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = args.out or os.path.join(os.path.abspath(args.repo or "."), "content", "references")
    try:
        done = capture_urls(args.urls, out, args.name, args.captured, args.force, role=args.role)
    except (browser.BrowserError, CaptureError, OSError) as e:
        print("capture refused: %s" % e)
        return 1
    print("packet: %s" % json.dumps(done["packet"], sort_keys=True))
    return 0 if all(r["status"] == "captured" for r in done["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())
