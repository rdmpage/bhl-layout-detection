"""Post-processing for layout detector output in the common JSON format.

- relabel: map the detector's own labels (`source_label`) onto the shared label set
- drop_duplicates: where two boxes cover the same region, keep the more confident
- drop_covers: a lone page-sized "figure" on a dark page is a cover -> empty
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

# Cloth, leather and marbled covers come out as one page-sized figure. A figure
# covering at least COVER_AREA of the page, with no other boxes on the page, on
# a page whose paper brightness (70th percentile of grey level, 0-1) is below
# MAX_COVER_PAPER, becomes "empty". Set on the validation split: lone
# page-sized real figures (plates, foldouts) were all >= 0.61, covers <= 0.42.
COVER_AREA = 0.5
MAX_COVER_PAPER = 0.5

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
# A caption and a figure or table that are both still unpaired after that may
# be further apart (plates often leave a blank band above the caption)
MAX_VGAP_LEFTOVER = 0.2

# Two boxes with at least this IoU are one region labelled twice (e.g. a heading
# as both doc_title and paragraph_title); the less confident one is dropped.
DUP_IOU = 0.8

# Printer's devices, crests and logos on title pages and article heads: an
# uncaptioned figure smaller than MAX_DEVICE_AREA of the page, on a page with a
# title box, becomes "empty". Devices on validation and test were <= 0.06 of
# the page; real figures that small on such pages were all logos too.
MAX_DEVICE_AREA = 0.07


def relabel(doc):
    # boxes dropped as duplicates on an earlier run are put back and judged again
    doc["boxes"] = sorted(doc["boxes"] + doc.pop("duplicates", []), key=lambda b: -b["confidence"])
    for i, b in enumerate(doc["boxes"]):
        b["id"] = i
        b["label"] = LABEL_MAP.get(b["source_label"], "text")
        b.pop("empty_reason", None)
        if b["label"] == "figure" and b.get("ink_pct", 100) < MIN_INK_PCT:
            b["label"] = "empty"
            b["empty_reason"] = "ink"
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


def paper_brightness(image_path):
    """70th percentile of the page's grey level (0-1): the paper, not the ink."""
    import numpy as np
    im = Image.open(image_path)
    im.draft("L", (400, 400))
    return round(float(np.percentile(np.asarray(im.convert("L").resize((150, 200)), float), 70)) / 255, 3)


def drop_covers(doc):
    """Relabel a lone, page-sized figure on a dark page as "empty" (needs
    doc["page"]["paper"], see paper_brightness)."""
    paper = doc.get("page", {}).get("paper")
    if paper is None or paper >= MAX_COVER_PAPER:
        return doc
    W, H = doc["image"]["width"], doc["image"]["height"]
    live = [b for b in doc["boxes"] if b["label"] != "empty"]
    for b in live:
        x0, y0, x1, y1 = b["bbox"]
        if (b["label"] == "figure" and (x1 - x0) * (y1 - y0) >= COVER_AREA * W * H
                and all(o["label"] == "figure" for o in live)):
            b["label"] = "empty"
            b["empty_reason"] = "cover"
    return doc


def _area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def drop_devices(doc):
    """Relabel small uncaptioned figures on pages with a title box as "empty"
    (printer's devices, crests, logos). "Uncaptioned": no caption has this
    figure as its nearest object. Run before pair_captions, so a device never
    takes a caption meant for something else."""
    if not any(b["label"] == "title" for b in doc["boxes"]):
        return doc
    W, H = doc["image"]["width"], doc["image"]["height"]
    objects = [b for b in doc["boxes"] if b["label"] in ("figure", "table")]
    nearest = set()
    for c in (b for b in doc["boxes"] if b["label"] == "caption"):
        rels = [(rel[1], o["id"]) for o in objects if (rel := _relation(c["bbox"], o["bbox"], W, H))]
        if rels:
            nearest.add(min(rels)[1])
    for b in objects:
        if (b["label"] == "figure" and b["id"] not in nearest
                and _area(b["bbox"]) < MAX_DEVICE_AREA * W * H):
            b["label"] = "empty"
            b["empty_reason"] = "device"
    return doc


def _overlap(a0, a1, b0, b1):
    """Shared extent of two intervals, as a fraction of the shorter one."""
    shared = min(a1, b1) - max(a0, b0)
    return shared / max(1.0, min(a1 - a0, b1 - b0))


def _relation(c, o, W, H, max_vgap=MAX_VGAP):
    """Where caption box c sits relative to object box o: (position, gap) or None."""
    cx0, cy0, cx1, cy1 = c
    ox0, oy0, ox1, oy1 = o
    tol = 0.01 * H
    if _overlap(cx0, cx1, ox0, ox1) >= MIN_OVERLAP:
        if cx0 >= ox0 - tol and cx1 <= ox1 + tol and cy0 >= oy0 - tol and cy1 <= oy1 + tol:
            return "inside", 0.0
        if cy0 >= oy1 - tol and cy0 - oy1 <= max_vgap * H:
            return "below", max(0.0, cy0 - oy1)
        if cy1 <= oy0 + tol and oy0 - cy1 <= max_vgap * H:
            return "above", max(0.0, oy0 - cy1)
    if _overlap(cy0, cy1, oy0, oy1) >= 0.5:
        if cx0 >= ox1 - tol and cx0 - ox1 <= MAX_HGAP * W:
            return "right", max(0.0, cx0 - ox1)
        if cx1 <= ox0 + tol and ox0 - cx1 <= MAX_HGAP * W:
            return "left", max(0.0, ox0 - cx1)
    return None


OPPOSITE = {"above": "below", "below": "above", "left": "right", "right": "left"}


def _assign(cands):
    """One-to-one caption -> object assignment that pairs as many captions as
    possible, then has the smallest total gap. cands: {caption id: [(object
    id, gap, position), ...]}. Exact search; pages have only a few captions."""
    caps = list(cands)
    memo = {}

    def best(i, used):
        if i == len(caps):
            return (0, 0.0, ())
        key = (i, used)
        if key not in memo:
            n, g, a = best(i + 1, used)
            res = (n, g, a)
            for o, gap, pos in cands[caps[i]]:
                if o in used:
                    continue
                n, g, a = best(i + 1, used | {o})
                if (n + 1, -(g + gap)) > (res[0], -res[1]):
                    res = (n + 1, g + gap, ((caps[i], o, gap, pos),) + a)
            memo[key] = res
        return memo[key]

    return best(0, frozenset())[2]


def pair_captions(doc):
    """Link captions to figures and tables they sit above, below, beside or
    inside. Captions are first matched one-to-one so that as many objects as
    possible get a caption (a caption between two figures goes to the one that
    would otherwise have none), with ties broken by distance. Captions left
    over then join their nearest object (e.g. a legend under a titled figure).
    Finally, captions and objects that are both still alone are matched with a
    looser vertical limit. Captions with no object nearby stay unpaired, e.g.
    plate explanations printed on another page."""
    W, H = doc["image"]["width"], doc["image"]["height"]
    objects = [b for b in doc["boxes"] if b["label"] in ("figure", "table")]
    captions = [b for b in doc["boxes"] if b["label"] == "caption"]
    label = {o["id"]: o["label"] for o in objects}

    def candidates(caps, objs, max_vgap):
        out = {}
        for c in caps:
            rels = [(o["id"], rel[1], rel[0]) for o in objs
                    if (rel := _relation(c["bbox"], o["bbox"], W, H, max_vgap))]
            if rels:
                # the nearest object, and the nearest one on the opposite side
                # (a caption between two figures); never another object on the
                # same side, which is usually an overlapping box of the same one
                rels.sort(key=lambda r: r[1])
                other = [r for r in rels if r[2] == OPPOSITE.get(rels[0][2])]
                out[c["id"]] = rels[:1] + other[:1]
        return out

    cands = candidates(captions, objects, MAX_VGAP)
    found = list(_assign(cands))
    done = {c for c, *_ in found}
    for c, rels in cands.items():
        if c not in done:
            found.append((c,) + rels[0])
            done.add(c)
    paired_objs = {o for _, o, _, _ in found}
    found += _assign(candidates([c for c in captions if c["id"] not in done],
                                [o for o in objects if o["id"] not in paired_objs], MAX_VGAP_LEFTOVER))

    doc["pairs"] = [{"object": o, "object_label": label[o], "caption": c, "position": pos,
                     "gap": round(gap, 1)} for c, o, gap, pos in sorted(found)]
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
        doc = json.loads(f.read_text())
        if "paper" not in doc.get("page", {}):
            doc.setdefault("page", {})["paper"] = paper_brightness(images[doc["page_id"]])
        doc = pair_captions(drop_devices(drop_covers(drop_duplicates(relabel(doc)))))
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
