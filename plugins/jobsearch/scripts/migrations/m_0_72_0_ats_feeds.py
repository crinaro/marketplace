"""Migration 0.72.0: `m_0_72_0_ats_feeds()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil
from migrations.support_ats_feeds import ATS_FEEDS_PRE_COPY, _ats_feeds_settings_step
from migrations.support_uid import _uid_text_read

VERSION = "0.72.0"


def m_0_72_0_ats_feeds(profile, apply_it):
    """0.72.0 -- company feeds: discover each tracked company's job-board slug from its own URLs and
    allow the four feed hosts for the sandbox (see the block above). Returns (done, message)."""
    import datetime
    import _atomic
    import ats_slug
    import validate_data as _vd
    lines, done = [], True

    companies, c_raws, err = _uid_text_read(profile, "companies")
    channels, ch_raws, err2 = _uid_text_read(profile, "channels")
    opps, _o_raws, err3 = _uid_text_read(profile, "opportunities")
    err = err or err2 or err3
    if err:
        lines.append("  ⏳ 0.72.0 PENDING -- %s. Nothing was written to the stores: rewriting a store "
                     "this could not fully read would drop that line. Fix it and this runs again next "
                     "session." % err)
        done = False
    else:
        todo, ambiguous = [], []
        for co in companies:
            if "ats" in co or co.get("status") == "passed":
                continue
            d = ats_slug.discover(co, opps)
            if d.ambiguous:
                ambiguous.append((co.get("id"), d.ambiguous))
            elif d.found is not None:
                todo.append((co, d))
        for cid, triples in ambiguous:
            lines.append("  ATS AMBIGUOUS %s: %s -- written nowhere; settle it with `record.py ats %s "
                         "--url <the right board>`" % (cid, " | ".join("%s:%s" % (t[0], t[1])
                                                                       for t in triples), cid))
        if todo and not apply_it:
            lines.append("  would write `ats` on %d compan%s and link or create their career-page "
                         "channel: %s" % (len(todo), "y" if len(todo) == 1 else "ies", ", ".join(
                             "%s (%s:%s)" % (c["id"], d.found[0], d.found[1]) for c, d in todo)))
        elif todo:
            data_dir = os.path.join(profile, "data")
            copies = []
            for name in ("companies", "channels"):
                src = os.path.join(data_dir, "%s.jsonl" % name)
                dst = src + "." + ATS_FEEDS_PRE_COPY
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                    except (OSError, shutil.Error) as exc:
                        lines.append("  ⚠️ %s.jsonl could not be preserved to %s (%s), so NOTHING was "
                                     "changed." % (name, os.path.basename(dst), exc))
                        done = False
                        todo = []
                        break
                if os.path.exists(dst):
                    copies.append((name, src, dst))
            today = datetime.date.today().isoformat()
            if todo:
                new_channels = [dict(r) for r in channels]
                written = []
                for co, d in todo:
                    ch_id, how = ats_slug.apply_discovery(co, new_channels, d.found, d.source, today)
                    written.append((co["id"], d.found, d.source, ch_id, how))
                _atomic.write_jsonl(os.path.join(data_dir, "companies.jsonl"), companies)
                _atomic.write_jsonl(os.path.join(data_dir, "channels.jsonl"), new_channels)
                after_c, _r, e1 = _uid_text_read(profile, "companies")
                after_ch, _r2, e2 = _uid_text_read(profile, "channels")
                bad = []
                if e1 or e2:
                    bad.append(e1 or e2)
                else:
                    by_id = {c.get("id"): c for c in after_c}
                    for cid, *_rest in written:
                        bad += ats_slug.check_ats(by_id.get(cid, {}).get("ats"), "companies[%s].ats" % cid)
                    bad += _vd.check_feed_links(after_c, after_ch)
                if bad:
                    for _n, src, dst in copies:
                        try:
                            shutil.copy2(dst, src)
                        except (OSError, shutil.Error):
                            pass
                    lines.append("  ⏳ 0.72.0 PENDING -- the success condition did not hold after the "
                                 "write (%s); the originals are restored from *.%s. Offered again next "
                                 "session." % ("; ".join(bad[:3]), ATS_FEEDS_PRE_COPY))
                    done = False
                else:
                    for cid, found, source, ch_id, how in written:
                        lines.append("  ATS %s %s:%s (%s) -> channel %s [%s]"
                                     % (cid, found[0], found[1], source, ch_id, how))
                    lines.append("  ✅ companies (0.72.0) -- wrote a company-feed slug on %d compan%s "
                                 "(the originals are kept at data/companies.jsonl.%s and "
                                 "data/channels.jsonl.%s)" % (len(written),
                                 "y" if len(written) == 1 else "ies", ATS_FEEDS_PRE_COPY,
                                 ATS_FEEDS_PRE_COPY))

    ok, line = _ats_feeds_settings_step(profile, apply_it)
    if line:
        lines.append(line)
    return (done and ok), "\n".join(lines)
