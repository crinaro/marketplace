#!/usr/bin/env python3
"""capture.py -- capture the pages the person lists as references: one URL in, one reference folder
out (dev #835; design 5.1 and 5.3; named change M8). Python 3.9, standard library only; Chrome via
browser.py. It NEVER crawls: it loads exactly the URLs it is given and nothing they link to.

    python3 capture.py [--repo R | --out DIR] [--name NAME] [--force] URL [URL ...]

PER URL it writes, into <out>/<name>/ (default <repo>/content/references/<name>/):
    reference.json   {url, title, description, site, published, kind, captured}: the keys content.py
                     accepts, no others (the build refuses an unknown key)
    text.md          the page's visible text, raw material for the person's write-up; never published
    card.jpg         the first screen (1200 x 630) through images.import_media, so it is stripped of
                     metadata and gets size copies like any photo
and prints one line per URL plus a JSON packet recording the Chrome version, the platform and the
capture date (named change M8, so a later Chrome change shows).

RULES (design 5.3, 5.1)
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
  * An existing reference folder is not overwritten without --force.
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
import content  # noqa: E402
import images   # noqa: E402
import resize   # noqa: E402

NOT_PUBLIC = (401, 403, 404, 410, 451)
SIGN_IN = re.compile(r"/(log-?in|sign-?in|signin|sign_in|accounts?/login|sso|auth(enticate)?)(/|$|\?)", re.I)
TEXT_LIMIT = 200000

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
    e = content.video_embed(url)
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


def capture_one(b, resizer, url, out_root, name=None, captured=None, force=False, log=print):
    """Capture one URL. Returns {"url", "status": "captured" | "not_public" | "error", ...}."""
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
    os.makedirs(folder, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="site-studio-card-")
    try:
        src = os.path.join(tmp, "card.jpg")
        with open(src, "wb") as fh:
            fh.write(jpeg)
        card = images.import_media(src, os.path.join(folder, "card.jpg"), resizer, overwrite=force)
    except images.ImageError as e:
        res.update(status="error", reason="the card image could not be imported: %s" % e)
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ref = {"url": url, "title": title, "description": (meta.get("description") or "").strip(),
           "site": (meta.get("site") or "").strip() or re.sub(r"^www\.", "", host),
           "published": iso_date(meta.get("published")), "kind": kind_of(embed, meta.get("ogtype")),
           "captured": captured or datetime.datetime.utcnow().strftime("%Y-%m-%d")}
    ref = {k: v for k, v in ref.items() if v != "" or k in ("url", "title")}
    with open(os.path.join(folder, "reference.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ref, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    text = (meta.get("text") or "")[:TEXT_LIMIT]
    with open(os.path.join(folder, "text.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# %s\n\nSource: %s\nCaptured: %s\n\n%s\n" % (title, url, ref["captured"], text.strip()))
    res.update(status="captured", name=name, dir=folder, title=title, card=os.path.basename(card.path),
               kind=ref["kind"])
    return res


def capture_urls(urls, out_root, name=None, captured=None, force=False, env=None, euid=None, log=print):
    """Capture each URL in a fresh Chrome profile. Returns {"results": [...], "packet": {...}}."""
    if name and len(urls) != 1:
        raise CaptureError("--name needs exactly one URL")
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
                r = capture_one(b, rz, url, out_root, name, captured, force, log)
                results.append(r)
                if r["status"] == "captured":
                    log("captured %s -> %s (%s; card %s)" % (url, r["dir"], r["kind"], r["card"]))
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
    ap.add_argument("--force", action="store_true", help="overwrite an existing reference folder")
    ap.add_argument("--captured", help="the capture date, YYYY-MM-DD (default: today, UTC)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = args.out or os.path.join(os.path.abspath(args.repo or "."), "content", "references")
    try:
        done = capture_urls(args.urls, out, args.name, args.captured, args.force)
    except (browser.BrowserError, CaptureError, OSError) as e:
        print("capture refused: %s" % e)
        return 1
    print("packet: %s" % json.dumps(done["packet"], sort_keys=True))
    return 0 if all(r["status"] == "captured" for r in done["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())
