"""budgets.py -- the `performance` and `size` families of the site gate (design 4.3). A mixin of
`checker.Checker`.

  performance  the budgets of site.json (siteconfig.BUDGET_DEFAULTS): an image over sizeCopyOverKB
               that images.plan_copies says needs size copies but has none; per page, the images
               it loads against firstViewMaxMB (non-lazy images and the first image) and
               pageImagesMaxMB (all). An image costs its largest candidate up to 1440 px wide
               (what a 2x screen would fetch from the srcset). OURS: an approximation, stated.
  size         the published tree against treeMaxMB, and any single file near GitHub's limit.

  Dated note, 2026-11-20 (design-adopt-parity-2 section 4.7.2, owner decision 2 (i)): a CARRIED page (`site.json`
  `carried`, schema 6; `sitechecks/carriedpages.py`) is the person's page as their old site served it. `size` HOLDS it
  like any file (it is about the files, not their form), as does `performance`'s per-file rule (an image over the size
  budget with no size copies). `performance`'s per-page image weights are NOT applied to it: the page loads what the
  old site's page loaded, and refusing it now would change nothing for a visitor and block the person. `checker.run`
  prints the `carried:` note, so the skip is never a quiet pass. A tree without the key is judged as before.
"""

from imaging import plan, sniff
import os
import re
from sitechecks.kinds import IMAGE_EXTS
from sitechecks.page import parse_srcset
from sitechecks.tree import _size_copy_of, classify


class BudgetChecks(object):
    """The `performance` and `size` families (a mixin of `Checker`)."""

    # -- performance and size ----------------------------------------------------------------
    def _img_cost(self, rel, im):
        """Bytes this <img> would cost on a 2x screen: its largest candidate up to 1440 wide."""
        cands = []
        for u, d in parse_srcset(im["srcset"]):
            m = re.match(r"^(\d+)w$", d)
            k, rest = classify(u, self.base)
            if k not in ("rel", "internal"):
                continue
            tgt, _f, pr = self.resolve(rel, rest if k == "internal" else u)
            if tgt and not pr and tgt in self.t.files:
                cands.append((int(m.group(1)) if m else 0, tgt))
        src = im["src"]
        if src:
            k, rest = classify(src, self.base)
            if k in ("rel", "internal"):
                tgt, _f, pr = self.resolve(rel, rest if k == "internal" else src)
                if tgt and not pr and tgt in self.t.files:
                    d = sniff.read_dimensions(self.t.read(tgt))
                    cands.append((d[0] if d else 0, tgt))
        if not cands:
            return None, 0
        under = [c for c in cands if c[0] <= 1440] or [min(cands)]
        w, tgt = max(under)
        return tgt, self.t.files[tgt]

    def performance(self):
        fam = "performance"
        b = self.cfg.effective_budgets()
        n = 0
        over_kb = b["sizeCopyOverKB"]
        schema3 = getattr(self.cfg, "schema", 1) >= 3
        for rel in sorted(self.t.files):
            if not rel.lower().endswith(IMAGE_EXTS) or re.search(r"-\d+w\.\w+$", rel):
                continue
            if schema3 and _size_copy_of(rel, self.t.files):
                continue            # a `.wNNN` size copy (schema 3, F4) is a copy of its original, not an original
            n += 1
            d = sniff.read_dimensions(self.t.read(rel))
            if not d:
                continue
            stem, ext = os.path.splitext(rel)
            has_copy = any(f.startswith(stem + "-") and re.match(r"-\d+w" + re.escape(ext) + "$", f[len(stem):])
                           for f in self.t.files)
            if schema3 and not has_copy:
                has_copy = any(f.startswith(stem + ".w") and re.match(r"\.w\d+" + re.escape(ext) + "$", f[len(stem):])
                               for f in self.t.files)
            if plan.plan_copies(d[0], self.t.files[rel], over_kb) and not has_copy:
                self.r.add(fam, rel, "%d KB is over the %s KB budget and the image has no size copies "
                                     "(<stem>-<width>w.<ext>); import it again" % (self.t.files[rel] // 1024, over_kb))
        first_cap = b["firstViewMaxMB"] * 1024 * 1024
        page_cap = b["pageImagesMaxMB"] * 1024 * 1024
        for rel, p in sorted(self.pages.items()):
            if rel in self.carried:             # the page as the person wrote it (the dated note)
                continue
            n += 1
            seen, total, first, first_seen = set(), 0, 0, set()
            for i, im in enumerate(p.imgs):
                tgt, cost = self._img_cost(rel, im)
                if tgt is None:
                    continue
                if tgt not in seen:
                    seen.add(tgt)
                    total += cost
                if (i == 0 or (im["loading"] or "").lower() != "lazy") and tgt not in first_seen:
                    first_seen.add(tgt)
                    first += cost
            if first > first_cap:
                self.r.add(fam, rel, "first-view images weigh %.2f MB at 2x, over the %s MB budget"
                           % (first / 1048576.0, b["firstViewMaxMB"]))
            if total > page_cap:
                self.r.add(fam, rel, "images on the page weigh %.2f MB at 2x, over the %s MB budget"
                           % (total / 1048576.0, b["pageImagesMaxMB"]))
        self.r.count(fam, n)

    def size(self):
        fam = "size"
        total = sum(self.t.files.values())
        cap = self.cfg.effective_budgets()["treeMaxMB"] * 1024 * 1024
        self.r.count(fam, len(self.t.files))
        if total > cap:
            self.r.add(fam, ".", "the published tree is %.1f MB, over the %s MB budget (Pages allows 1 GB)"
                       % (total / 1048576.0, self.cfg.effective_budgets()["treeMaxMB"]))
        for rel, sz in sorted(self.t.files.items()):
            if sz >= 50 * 1024 * 1024:
                self.r.add(fam, rel, "file is %.0f MB; GitHub warns at 50 MB and refuses 100 MB" % (sz / 1048576.0))
