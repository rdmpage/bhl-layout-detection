"""Post-processing for layout detector output in the common JSON format.

- relabel: map the detector's own labels (`source_label`) onto the shared label set
- drop_duplicates: where two boxes cover the same region, keep the more confident
- pair_captions: link each caption box to the figure or table it describes
- draw_overlay / write_index: images and a review page

Run on existing output (no model needed):
  .venv/bin/python layout_post.py results/pp-doclayout_plus-l/test
"""
import collections
import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None  # some foldout scans are >90 Mpx

ROOT = Path(__file__).resolve().parent
LAYOUT = ROOT / "layout"

# A figure box with less than this % of "ink" (pixels clearly darker than the
# local background) is relabelled "empty": blank leaves and plain cloth covers.
MIN_INK_PCT = 1.0

# PP-DocLayout labels -> shared label set. Anything not listed is "text"
# (paragraph_title, reference, footnote, aside_text, formula, ...).
LABEL_MAP = {
    "image": "figure",
    "chart": "figure",
    "seal": "stamp",             # mostly library stamps on BHL pages
    "figure_title": "caption",   # PP-DocLayout uses this for figure and table titles
    "chart_title": "caption",
    "table_title": "caption",
    "table": "table",
    "doc_title": "title",
    "header": "header",
    "header_image": "header",
    "footer": "footer",
    "footer_image": "footer",
    "number": "page_number",
}
LABELS = ["figure", "caption", "table", "text", "title", "header", "footer",
          "page_number", "stamp", "empty"]
COLOURS = {
    "figure": (220, 30, 30),
    "caption": (240, 140, 0),
    "table": (30, 150, 30),
    "text": (30, 90, 220),
    "title": (0, 160, 170),
    "header": (120, 120, 120),
    "footer": (120, 120, 120),
    "page_number": (90, 90, 90),
    "stamp": (200, 0, 200),
    "empty": (0, 0, 0),
}

# Caption pairing limits, as fractions of the page size
MAX_VGAP = 0.08    # caption above/below its object
MAX_HGAP = 0.05    # caption beside its object
MIN_OVERLAP = 0.3  # shared extent, as a fraction of the narrower box

# Two boxes with at least this IoU are one region labelled twice (e.g. a heading
# as both doc_title and paragraph_title); the less confident one is dropped.
DUP_IOU = 0.8


def relabel(doc):
    # boxes dropped as duplicates on an earlier run are put back and judged again
    doc["boxes"] = sorted(doc["boxes"] + doc.pop("duplicates", []), key=lambda b: -b["confidence"])
    for i, b in enumerate(doc["boxes"]):
        b["id"] = i
        b["label"] = LABEL_MAP.get(b["source_label"], "text")
        if b["label"] == "figure" and b.get("ink_pct", 100) < MIN_INK_PCT:
            b["label"] = "empty"
    return doc


def _iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def drop_duplicates(doc):
    """Move the less confident of any two boxes with IoU >= DUP_IOU to
    doc["duplicates"] (kept, so relabel can restore them), and renumber.
    "empty" boxes are left alone."""
    keep, dups = [], []
    for b in sorted(doc["boxes"], key=lambda b: -b["confidence"]):
        if b["label"] != "empty" and any(
                k["label"] != "empty" and _iou(b["bbox"], k["bbox"]) >= DUP_IOU for k in keep):
            dups.append(b)
        else:
            keep.append(b)
    for i, b in enumerate(keep):
        b["id"] = i
    for b in dups:
        b.pop("id", None)
    doc["boxes"] = keep
    if dups:
        doc["duplicates"] = dups
    return doc


def _overlap(a0, a1, b0, b1):
    """Shared extent of two intervals, as a fraction of the shorter one."""
    shared = min(a1, b1) - max(a0, b0)
    return shared / max(1.0, min(a1 - a0, b1 - b0))


def _relation(c, o, W, H):
    """Where caption box c sits relative to object box o: (position, gap) or None."""
    cx0, cy0, cx1, cy1 = c
    ox0, oy0, ox1, oy1 = o
    tol = 0.01 * H
    if _overlap(cx0, cx1, ox0, ox1) >= MIN_OVERLAP:
        if cx0 >= ox0 - tol and cx1 <= ox1 + tol and cy0 >= oy0 - tol and cy1 <= oy1 + tol:
            return "inside", 0.0
        if cy0 >= oy1 - tol and cy0 - oy1 <= MAX_VGAP * H:
            return "below", max(0.0, cy0 - oy1)
        if cy1 <= oy0 + tol and oy0 - cy1 <= MAX_VGAP * H:
            return "above", max(0.0, oy0 - cy1)
    if _overlap(cy0, cy1, oy0, oy1) >= 0.5:
        if cx0 >= ox1 - tol and cx0 - ox1 <= MAX_HGAP * W:
            return "right", max(0.0, cx0 - ox1)
        if cx1 <= ox0 + tol and ox0 - cx1 <= MAX_HGAP * W:
            return "left", max(0.0, ox0 - cx1)
    return None


def pair_captions(doc):
    """Link each caption to the nearest figure or table it sits above, below,
    beside or inside. A figure can get several caption boxes (e.g. title plus
    legend); a caption goes to one object only. Captions with no object nearby
    stay unpaired, e.g. plate explanations printed on another page."""
    W, H = doc["image"]["width"], doc["image"]["height"]
    objects = [b for b in doc["boxes"] if b["label"] in ("figure", "table")]
    pairs = []
    for c in (b for b in doc["boxes"] if b["label"] == "caption"):
        best = None
        for o in objects:
            rel = _relation(c["bbox"], o["bbox"], W, H)
            if rel and (best is None or rel[1] < best[1]):
                best = (o, rel[1], rel[0])
        if best:
            o, gap, pos = best
            pairs.append({"object": o["id"], "object_label": o["label"],
                          "caption": c["id"], "position": pos, "gap": round(gap, 1)})
    doc["pairs"] = pairs
    return doc


def draw_overlay(doc, image_path, out_path, width=900):
    im = Image.open(image_path).convert("RGB")
    scale = width / im.width
    small = im.resize((width, round(im.height * scale)))
    d = ImageDraw.Draw(small)
    boxes = {b["id"]: b for b in doc["boxes"]}
    for b in doc["boxes"]:
        x0, y0, x1, y1 = [c * scale for c in b["bbox"]]
        col = COLOURS[b["label"]]
        d.rectangle([x0, y0, x1, y1], outline=col, width=3 if b["label"] == "figure" else 2)
        tag = b["label"] if b["label"] == b["source_label"] else f"{b['label']} ({b['source_label']})"
        d.text((x0 + 3, y0 + 2), f"{tag} {b['confidence']:.2f}", fill=col)
    for p in doc.get("pairs", []):
        o, c = boxes[p["object"]]["bbox"], boxes[p["caption"]]["bbox"]
        oc = ((o[0] + o[2]) / 2 * scale, (o[1] + o[3]) / 2 * scale)
        cc = ((c[0] + c[2]) / 2 * scale, (c[1] + c[3]) / 2 * scale)
        d.line([oc, cc], fill=COLOURS["caption"], width=3)
        d.ellipse([cc[0] - 5, cc[1] - 5, cc[0] + 5, cc[1] + 5], fill=COLOURS["caption"])
    small.save(out_path, quality=80)


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


def summarise(docs):
    """Per-stratum count of pages with each label, plus pairing counts."""
    rows = collections.OrderedDict()
    for d in sorted(docs, key=lambda d: d["stratum"]):
        r = rows.setdefault(d["stratum"], collections.Counter())
        r["pages"] += 1
        for lab in {b["label"] for b in d["boxes"]}:
            r[lab] += 1
        paired = {p["object"] for p in d.get("pairs", []) if p["object_label"] == "figure"}
        figs = [b for b in d["boxes"] if b["label"] == "figure"]
        caps = [b for b in d["boxes"] if b["label"] == "caption"]
        r["figures"] += len(figs)
        r["figures_captioned"] += len(paired)
        r["captions"] += len(caps)
        r["captions_unpaired"] += len(caps) - len(d.get("pairs", []))
    return rows


def write_index(result_dir, docs):
    rows = summarise(docs)
    cols = ["figure", "caption", "table", "title", "header", "footer", "page_number", "stamp", "empty"]
    legend = "".join(f'<span style="background:{_hex(COLOURS[k])}">{k}</span>' for k in LABELS)
    out = [
        "<!doctype html><meta charset=utf-8><title>Layout overlays</title>",
        "<style>body{font:14px system-ui;margin:16px;background:#fafafa;color:#222}"
        "figure{display:inline-block;margin:4px;vertical-align:top;width:220px}"
        "img{width:220px;border:1px solid #ccc}figcaption{font-size:11px}h2{margin-top:2em}"
        ".k span{padding:1px 6px;margin-right:4px;color:#fff;font-size:12px}"
        "table{border-collapse:collapse;font-size:12px}td,th{padding:2px 8px;text-align:right;border-bottom:1px solid #ddd}"
        "td:first-child,th:first-child{text-align:left}</style>",
        f"<h1>{html.escape(docs[0]['method'])}, {html.escape(result_dir.name)} split</h1>",
        f'<p class=k>{legend}</p><p>Orange lines join a caption to its figure or table.</p>',
        "<h2>Pages with each label</h2><table><tr><th>stratum</th><th>pages</th>"
        + "".join(f"<th>{c}</th>" for c in cols)
        + "<th>figures</th><th>with caption</th><th>unpaired captions</th></tr>",
    ]
    for s, r in rows.items():
        out.append(f'<tr><td><a href="#{s}">{s}</a></td><td>{r["pages"]}</td>'
                   + "".join(f"<td>{r[c]}</td>" for c in cols)
                   + f'<td>{r["figures"]}</td><td>{r["figures_captioned"]}</td><td>{r["captions_unpaired"]}</td></tr>')
    out.append("</table>")
    by = collections.defaultdict(list)
    for d in docs:
        by[d["stratum"]].append(d)
    for s in rows:
        out.append(f"<h2 id={s}>{s} ({len(by[s])})</h2>")
        for d in sorted(by[s], key=lambda d: d["page_id"]):
            n = collections.Counter(b["label"] for b in d["boxes"])
            cap = ", ".join(f"{k} {n[k]}" for k in ("figure", "caption", "table", "title", "stamp", "empty") if n[k])
            if d.get("pairs"):
                cap += f", pairs {len(d['pairs'])}"
            pid = d["page_id"]
            out.append(f'<figure><a href="overlays/{pid}.jpg"><img loading=lazy src="overlays/{pid}.jpg"></a>'
                       f'<figcaption><a href="https://www.biodiversitylibrary.org/page/{pid}">{pid}</a> '
                       f"{html.escape(cap)}</figcaption></figure>")
    (result_dir / "index.html").write_text("\n".join(out))


def page_images():
    import csv
    with open(LAYOUT / "pages.tsv", newline="") as f:
        return {int(r["page_id"]): LAYOUT / r["image"] for r in csv.DictReader(f, delimiter="\t")}


def process_dir(result_dir):
    result_dir = Path(result_dir)
    images = page_images()
    (result_dir / "overlays").mkdir(exist_ok=True)
    docs = []
    for f in sorted((result_dir / "json").glob("*.json")):
        doc = pair_captions(drop_duplicates(relabel(json.loads(f.read_text()))))
        f.write_text(json.dumps(doc, indent=1))
        draw_overlay(doc, images[doc["page_id"]], result_dir / "overlays" / f"{doc['page_id']}.jpg")
        docs.append(doc)
    write_index(result_dir, docs)
    return docs


if __name__ == "__main__":
    for d in sys.argv[1:]:
        docs = process_dir(d)
        rows = summarise(docs)
        cols = ["pages", "figure", "caption", "table", "title", "header", "footer", "page_number",
                "stamp", "empty", "figures", "figures_captioned", "captions", "captions_unpaired"]
        print("stratum".ljust(12) + "".join(c[:10].rjust(11) for c in cols))
        for s, r in rows.items():
            print(s.ljust(12) + "".join(str(r[c]).rjust(11) for c in cols))
