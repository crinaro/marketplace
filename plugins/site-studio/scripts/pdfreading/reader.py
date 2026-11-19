"""reader.py -- read_pdf: decide by outcome whether a PDF was READ, never raising on a hostile or damaged file.

Moved out of pdftext.py unchanged (S1b, dev 939); the interface and the design notes are in pdftext.py."""

import re
from pdfreading.document import Document
from pdfreading.result import PdfReadResult, _INFO_KEYS, _XMP_FIELDS, _pdf_text_string
from pdfreading.streamrun import _Acc, _run_content
from pdfreading.values import PdfUnsupported, Ref


def _walk_pages(doc, root):
    pages = []
    seen = set()

    def walk(node, inherited, depth):
        n = doc.res(node)
        if not isinstance(n, dict) or depth > 40:
            return
        key = node.num if isinstance(node, Ref) else id(n)
        if key in seen:
            return
        seen.add(key)
        inh = dict(inherited)
        if "Resources" in n:
            inh["Resources"] = n["Resources"]
        kids = doc.res(n.get("Kids"))
        if isinstance(kids, list) and n.get("Type") != "Page":
            for k in kids:
                walk(k, inh, depth + 1)
        else:
            pages.append((n, inh))
    walk(root.get("Pages"), {}, 0)
    return pages


def read_pdf(data):
    """Decide whether the PDF in `data` (bytes) was READ, and return its text and metadata."""
    r = PdfReadResult()
    try:
        _read(data, r)
    except Exception as e:  # a hostile file must come back NOT READ, never crash the gate
        r.status = "not_read"
        r.reasons.append("parse failure: %s" % e.__class__.__name__)
    return r


def _read(data, r):
    if b"%PDF-" not in data[:1024]:
        r.reasons.append("not a PDF (no %PDF- header)")
        return
    doc = Document(data)
    for p in doc.problems:
        r.reasons.append(p)
    if not doc.objs:
        r.reasons.append("no PDF objects found")
        return
    enc = any(("Encrypt" in t) for t in doc.trailers)
    if enc:
        r.reasons.append("encrypted")
    # metadata first: it is judged even when the text is not read
    info = None
    for t in reversed(doc.trailers):
        if "Info" in t:
            info = doc.res(t["Info"])
            break
    if isinstance(info, dict):
        for k in _INFO_KEYS:
            v = doc.res(info.get(k))
            if isinstance(v, bytes):
                s = _pdf_text_string(v).strip()
                if s:
                    r.info[k] = s
    root = None
    for t in reversed(doc.trailers):
        if "Root" in t:
            root = doc.res(t["Root"])
            break
    if not isinstance(root, dict):
        for num in sorted(doc.objs):
            v = doc.objs[num][0]
            if isinstance(v, dict) and v.get("Type") == "Catalog":
                root = v
    if isinstance(root, dict) and "Metadata" in root:
        sdic, raw = doc.stream_of(root["Metadata"])
        if sdic is not None:
            try:
                x = doc.decode_stream(sdic, raw).decode("utf-8", "replace")
                for tag, key in _XMP_FIELDS:
                    vals = []
                    for m in re.finditer(r"<%s\b[^>]*>(.*?)</%s>" % (re.escape(tag), re.escape(tag)),
                                         x, re.S):
                        vals.extend(re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", m.group(1), re.S)
                                    or [m.group(1)])
                    vals = [re.sub(r"<[^>]+>", "", v).strip() for v in vals]
                    vals = [v for v in vals if v]
                    if vals:
                        r.xmp[key] = "; ".join(vals)
            except PdfUnsupported:
                r.reasons.append("XMP metadata stream not decoded")
    if enc:
        return
    if not isinstance(root, dict):
        r.reasons.append("no document catalog")
        return
    pages = _walk_pages(doc, root)
    if not pages:
        pages = [(v, {}) for _n, (v, _raw) in sorted(doc.objs.items())
                 if isinstance(v, dict) and v.get("Type") == "Page"]
    if not pages:
        r.reasons.append("no pages")
        return
    r.pages = len(pages)
    font_cache = {}
    all_text = []
    empty_pages = []
    for idx, (pg, inh) in enumerate(pages, 1):
        acc = _Acc()
        contents = doc.res(pg.get("Contents"))
        refs = pg.get("Contents")
        items = [x for x in contents] if isinstance(contents, list) else [refs]
        chunks = []
        for it in items:
            sdic, raw = doc.stream_of(it)
            if sdic is None:
                continue
            try:
                chunks.append(doc.decode_stream(sdic, raw))
            except PdfUnsupported as e:
                acc.note("page %d content: %s" % (idx, e))
        _run_content(doc, b"\n".join(chunks), pg.get("Resources", inh.get("Resources")), acc, 0,
                     font_cache)
        extra = []
        annots = doc.res(pg.get("Annots"))
        for a in (annots if isinstance(annots, list) else []):
            ad = doc.res(a)
            if isinstance(ad, dict):
                for k in ("Contents", "V", "T", "TU", "Subj"):
                    v = doc.res(ad.get(k))
                    if isinstance(v, bytes) and v.strip():
                        extra.append(_pdf_text_string(v))
        text = "".join(acc.text)
        if acc.text_ops and not text.replace("\ufffd", "").strip():
            empty_pages.append(idx)
        r.text_ops += acc.text_ops
        for why in acc.reasons:
            r.reasons.append("page %d: %s" % (idx, why))
        all_text.append(text + (" " + " ".join(extra) if extra else ""))
    r.text = "\n".join(all_text)
    if empty_pages:
        r.reasons.append("decoded text is empty on page(s) %s" % ", ".join(map(str, empty_pages)))
    if r.text_ops == 0:
        r.reasons.append("no text operators: image-only or empty")
    if not r.reasons:
        r.status = "read"
