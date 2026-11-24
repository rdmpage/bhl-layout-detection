"""Convert a Label Studio JSON export into gold labels in the common JSON format.

Usage:
  .venv/bin/python labelstudio_to_gold.py labelstudio/export/test_annotations.json

Writes results/gold/<split>/json/<page_id>.json, one per task, with
"method": "gold". If a task has more than one annotation (e.g. a page
submitted twice), the most recently updated one is used. Pages with no
annotation are skipped and reported. A page whose annotation has no boxes is
written with an empty box list: that is a real label (blank leaf, plain cover).

Relations become caption pairs. The caption end is found from the box labels,
so the direction a relation was drawn in does not matter.

Pages with two boxes in (almost) the same place are listed at the end: in
Label Studio the top box hides the other, so a duplicate from the model is
easy to miss. Delete one of each stack and export again.
"""
import argparse
import collections
import json
from pathlib import Path

from PIL import Image

from layout_post import LABELS, LAYOUT, ROOT
from score import iou

Image.MAX_IMAGE_PIXELS = None
STACKED_IOU = 0.9


def image_size(page_id, split):
    # only reads the header
    with Image.open(LAYOUT / "images" / split / f"{page_id}.jpg") as im:
        return im.size


def convert(task):
    data = task["data"]
    ann = max(task["annotations"], key=lambda a: a["updated_at"])
    rects = [r for r in ann["result"] if r["type"] == "rectanglelabels"]
    if rects:
        W, H = rects[0]["original_width"], rects[0]["original_height"]
    else:
        W, H = image_size(data["page_id"], data["split"])

    boxes, index = [], {}
    for r in rects:
        v = r["value"]
        if v.get("rotation"):
            raise ValueError(f"page {data['page_id']}: rotated box {r['id']}")
        (label,) = v["rectanglelabels"]
        if label not in LABELS:
            raise ValueError(f"page {data['page_id']}: unknown label {label}")
        x0, y0 = v["x"] * W / 100, v["y"] * H / 100
        x1, y1 = x0 + v["width"] * W / 100, y0 + v["height"] * H / 100
        index[r["id"]] = len(boxes)
        boxes.append({
            "label": label,
            "bbox": [round(max(0.0, x0), 1), round(max(0.0, y0), 1),
                     round(min(float(W), x1), 1), round(min(float(H), y1), 1)],
            "id": len(boxes),
        })

    stacked = [(a["label"], b["label"]) for i, a in enumerate(boxes) for b in boxes[i + 1:]
               if iou(a["bbox"], b["bbox"]) >= STACKED_IOU]

    pairs, skipped = [], 0
    for r in ann["result"]:
        if r["type"] != "relation":
            continue
        a, b = index.get(r["from_id"]), index.get(r["to_id"])
        if a is None or b is None:
            skipped += 1
            continue
        if boxes[a]["label"] != "caption":
            a, b = b, a
        if boxes[a]["label"] == "caption" and boxes[b]["label"] in ("figure", "table"):
            pairs.append({"caption": a, "object": b})
        else:
            skipped += 1

    doc = {
        "page_id": data["page_id"],
        "method": "gold",
        "image": {"width": W, "height": H},
        "stratum": data["stratum"],
        "boxes": boxes,
        "pairs": pairs,
        "source": {"label_studio_task": task["id"], "annotation": ann["id"],
                   "updated_at": ann["updated_at"]},
    }
    return doc, skipped, stacked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    args = ap.parse_args()

    tasks = json.loads(Path(args.export).read_text())
    counts, n_pairs, n_skipped, no_ann, splits = collections.Counter(), 0, 0, [], set()
    stacks = []
    for t in tasks:
        if not t.get("annotations"):
            no_ann.append(t["data"]["page_id"])
            continue
        doc, skipped, stacked = convert(t)
        if stacked:
            stacks.append((t["id"], doc["page_id"], stacked))
        split = t["data"]["split"]
        splits.add(split)
        out = ROOT / "results" / "gold" / split / "json"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{doc['page_id']}.json").write_text(json.dumps(doc, indent=1))
        counts.update(b["label"] for b in doc["boxes"])
        n_pairs += len(doc["pairs"])
        n_skipped += skipped

    print(f"{len(tasks) - len(no_ann)} pages -> results/gold/{'+'.join(sorted(splits))}/json")
    print("boxes:", dict(counts.most_common()))
    print(f"caption pairs: {n_pairs}" + (f" ({n_skipped} relations skipped)" if n_skipped else ""))
    if no_ann:
        print(f"no annotation, skipped: {no_ann}")
    if stacks:
        print(f"\n{sum(len(s) for _, _, s in stacks)} stacked boxes (IoU >= {STACKED_IOU}) on {len(stacks)} pages; "
              "delete one of each in Label Studio:")
        print("  task  page_id   labels")
        for tid, pid, st in sorted(stacks):
            print(f"  {tid:>4}  {pid:<9} " + ", ".join(f"{a}+{b}" for a, b in st))


if __name__ == "__main__":
    main()
