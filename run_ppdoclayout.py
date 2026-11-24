"""Run PP-DocLayout on the BHL layout sample and write one JSON per page in the
common format from bhl-layout-detection-plan.md, plus overlays and a review page.

Labels, caption pairing and overlays come from layout_post.py, which can be
re-run on saved output without the model.

Usage:
  .venv/bin/python run_ppdoclayout.py [--split test] [--model PP-DocLayout_plus-L] [--limit N]
"""
import argparse
import csv
import json
import os
import time

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

from layout_post import LABEL_MAP, LAYOUT, ROOT, process_dir  # noqa: E402

Image.MAX_IMAGE_PIXELS = None  # some foldout scans are >90 Mpx


def ink_map(im, width=800):
    """Boolean map of pixels clearly darker than their local background."""
    s = width / im.width
    g = im.convert("L").resize((width, round(im.height * s)))
    a = np.asarray(g, float)
    bg = np.asarray(g.filter(ImageFilter.GaussianBlur(25)), float)
    return (bg - a) > 25, s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--model", default="PP-DocLayout_plus-L")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from paddleocr import LayoutDetection

    method = args.model.lower()
    result_dir = ROOT / "results" / method / args.split
    out_json = result_dir / "json"
    out_json.mkdir(parents=True, exist_ok=True)

    with open(LAYOUT / "pages.tsv", newline="") as f:
        pages = [r for r in csv.DictReader(f, delimiter="\t") if r["split"] == args.split]
    if args.limit:
        pages = pages[: args.limit]

    model = LayoutDetection(model_name=args.model)
    t0 = time.time()
    done = 0
    for i, p in enumerate(pages, 1):
        dest = out_json / f"{p['page_id']}.json"
        if dest.exists():
            continue
        img_path = LAYOUT / p["image"]
        im = Image.open(img_path).convert("RGB")
        res = list(model.predict(str(img_path), batch_size=1))[0]
        dark, s = ink_map(im)
        boxes = []
        for b in res["boxes"]:
            box = {
                "source_label": b["label"],
                "bbox": [round(float(c), 1) for c in b["coordinate"]],
                "confidence": round(float(b["score"]), 4),
            }
            if LABEL_MAP.get(b["label"]) == "figure":
                x0, y0, x1, y1 = [int(c * s) for c in box["bbox"]]
                region = dark[y0:y1, x0:x1]
                box["ink_pct"] = round(100 * float(region.mean()), 2) if region.size else 0.0
            boxes.append(box)
        doc = {
            "page_id": int(p["page_id"]),
            "method": method,
            "image": {"width": im.width, "height": im.height},
            "stratum": p["stratum"],
            "boxes": boxes,
        }
        dest.write_text(json.dumps(doc, indent=1))
        done += 1
        if done % 25 == 0:
            print(f"{i}/{len(pages)}  {(time.time() - t0) / done:.2f}s/page", flush=True)
    print(f"detected {done} new pages in {time.time() - t0:.0f}s; post-processing")
    process_dir(result_dir)


if __name__ == "__main__":
    main()
