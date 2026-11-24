"""Make a Label Studio import from layout output in the common JSON format.

Each page becomes a task; the detector's boxes become pre-annotations
("predictions") to correct, and caption pairs become relations.

Usage:
  .venv/bin/python make_labelstudio.py results/pp-doclayout_plus-l/test [--local]

Writes labelstudio/<method>_<split>_tasks.json and labelstudio/config.xml.

Images: by default tasks point at BHL's JPEGs on S3 (the same files as the
local copies), so nothing needs serving. With --local they point at the local
copies instead; start Label Studio with
  LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true
  LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=<this repo>/layout
and add a Local Files storage for <this repo>/layout/images.
"""
import argparse
import csv
import json
from pathlib import Path

from layout_post import COLOURS, LABELS, LAYOUT, ROOT

# "empty" boxes are known false positives, so they are not pre-annotated
EXCLUDE = {"empty"}
RELATION = "caption_of"


def config_xml():
    labels = "\n".join(
        f'    <Label value="{k}" background="#%02x%02x%02x"/>' % COLOURS[k]
        for k in LABELS if k not in EXCLUDE
    )
    return f"""<View>
  <Header value="$page_id ($stratum)"/>
  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="false"/>
  <RectangleLabels name="label" toName="image" strokeWidth="2">
{labels}
  </RectangleLabels>
  <Relations>
    <Relation value="{RELATION}"/>
  </Relations>
  <HyperText name="bhl" value="$bhl_link" inline="true"/>
</View>
"""


def to_task(doc, page, local):
    W, H = doc["image"]["width"], doc["image"]["height"]
    image = (f"/data/local-files/?d={page['image']}" if local else page["image_url"])
    results, region_ids = [], {}
    for b in doc["boxes"]:
        if b["label"] in EXCLUDE:
            continue
        x0, y0, x1, y1 = b["bbox"]
        x0, y0 = max(0.0, x0), max(0.0, y0)
        x1, y1 = min(float(W), x1), min(float(H), y1)
        rid = f"b{b['id']}"
        region_ids[b["id"]] = rid
        results.append({
            "id": rid,
            "type": "rectanglelabels",
            "from_name": "label",
            "to_name": "image",
            "original_width": W,
            "original_height": H,
            "image_rotation": 0,
            "score": b["confidence"],
            "value": {
                "x": 100 * x0 / W,
                "y": 100 * y0 / H,
                "width": 100 * (x1 - x0) / W,
                "height": 100 * (y1 - y0) / H,
                "rotation": 0,
                "rectanglelabels": [b["label"]],
            },
        })
    for p in doc.get("pairs", []):
        if p["caption"] in region_ids and p["object"] in region_ids:
            results.append({
                "type": "relation",
                "from_id": region_ids[p["caption"]],
                "to_id": region_ids[p["object"]],
                "direction": "right",
                "labels": [RELATION],
            })
    scores = [b["confidence"] for b in doc["boxes"] if b["label"] not in EXCLUDE]
    return {
        "data": {
            "image": image,
            "page_id": doc["page_id"],
            "stratum": doc["stratum"],
            "era": page["era"],
            "split": page["split"],
            "bhl_url": page["bhl_url"],
            "bhl_link": f'<a href="{page["bhl_url"]}" target="_blank">{page["bhl_url"]}</a>',
        },
        "predictions": [{
            "model_version": doc["method"],
            "score": round(sum(scores) / len(scores), 4) if scores else 0,
            "result": results,
        }],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir")
    ap.add_argument("--local", action="store_true", help="point tasks at local image copies")
    args = ap.parse_args()

    result_dir = Path(args.result_dir)
    with open(LAYOUT / "pages.tsv", newline="") as f:
        pages = {int(r["page_id"]): r for r in csv.DictReader(f, delimiter="\t")}

    tasks = []
    for f in sorted((result_dir / "json").glob("*.json")):
        doc = json.loads(f.read_text())
        tasks.append(to_task(doc, pages[doc["page_id"]], args.local))
    tasks.sort(key=lambda t: (t["data"]["stratum"], t["data"]["page_id"]))

    out = ROOT / "labelstudio"
    out.mkdir(exist_ok=True)
    name = f"{result_dir.parent.name}_{result_dir.name}{'_local' if args.local else ''}_tasks.json"
    (out / name).write_text(json.dumps(tasks, indent=1))
    (out / "config.xml").write_text(config_xml())
    n_boxes = sum(sum(r["type"] == "rectanglelabels" for r in t["predictions"][0]["result"]) for t in tasks)
    n_rel = sum(sum(r["type"] == "relation" for r in t["predictions"][0]["result"]) for t in tasks)
    print(f"{len(tasks)} tasks, {n_boxes} boxes, {n_rel} relations -> {out / name}")


if __name__ == "__main__":
    main()
