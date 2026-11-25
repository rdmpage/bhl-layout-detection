"""Build a Hugging Face dataset from the hand-corrected layout labels.

Usage:
  .venv/bin/python export_hf.py [--out hf]

Writes, all local (nothing is uploaded):
  hf/data/pages-0000N-of-0000M.parquet   one row per page, image bytes embedded
  hf/README.md                           dataset card, with counts filled in
  hf/items.tsv                           the BHL items the pages come from, for checking rights

One row per page: the page image (BHL's JPEG), its BHL metadata, the labelled
boxes ("objects") and the caption links ("caption_pairs", indexes into
objects). Boxes are COCO-style [x, y, width, height] in pixels of the image.
All pages go in one Hugging Face split; the split used in this project is the
"suggested_split" column (splits are by item, so pages of a book stay together).
"""
import argparse
import collections
import csv
import json
from pathlib import Path

from datasets import ClassLabel, Dataset, Features, Image, List, Value

from layout_post import LABELS, LAYOUT, ROOT

CATEGORIES = [c for c in LABELS if c != "empty"]
PAGES_PER_SHARD = 400

FEATURES = Features({
    "page_id": Value("int64"),
    "image": Image(),
    "width": Value("int32"),
    "height": Value("int32"),
    "objects": List({
        "id": Value("int32"),
        "category": ClassLabel(names=CATEGORIES),
        "bbox": List(Value("float32"), length=4),
        "area": Value("float32"),
    }),
    "caption_pairs": List({"caption": Value("int32"), "object": Value("int32")}),
    "item_id": Value("int64"),
    "ia_identifier": Value("string"),
    "seq": Value("int32"),
    "page_label": Value("string"),
    "year": Value("int32"),
    "era": Value("string"),
    "stratum": Value("string"),
    "bhl_page_types": List(Value("string")),
    "suggested_split": Value("string"),
    "bhl_url": Value("string"),
    "image_url": Value("string"),
})


def load_pages():
    with open(LAYOUT / "pages.tsv", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def row(page):
    pid = int(page["page_id"])
    gold = json.loads((ROOT / "results" / "gold" / page["split"] / "json" / f"{pid}.json").read_text())
    W, H = gold["image"]["width"], gold["image"]["height"]
    image_path = LAYOUT / page["image"]
    objects = []
    for i, b in enumerate(gold["boxes"]):
        assert b["id"] == i, (pid, "box ids are not indexes")
        x0, y0, x1, y1 = b["bbox"]
        assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H, (pid, b)
        objects.append({"id": i, "category": b["label"],
                        "bbox": [x0, y0, round(x1 - x0, 1), round(y1 - y0, 1)],
                        "area": round((x1 - x0) * (y1 - y0), 1)})
    pairs = []
    for p in gold["pairs"]:
        assert objects[p["caption"]]["category"] == "caption", (pid, p)
        assert objects[p["object"]]["category"] in ("figure", "table"), (pid, p)
        pairs.append({"caption": p["caption"], "object": p["object"]})
    return {
        "page_id": pid,
        "image": {"bytes": image_path.read_bytes(), "path": f"{pid}.jpg"},
        "width": W, "height": H,
        "objects": objects,
        "caption_pairs": pairs,
        "item_id": int(page["item_id"]),
        "ia_identifier": page["barcode"],
        "seq": int(page["seq"]),
        "page_label": page["page_label"],
        "year": int(page["year"]) if page["year"] else None,
        "era": page["era"],
        "stratum": page["stratum"],
        "bhl_page_types": [t.strip() for t in page["bhl_types"].split(";") if t.strip()],
        "suggested_split": page["split"],
        "bhl_url": page["bhl_url"],
        "image_url": page["image_url"],
    }


def stats(pages):
    s = {"pages": len(pages), "items": len({p["item_id"] for p in pages}),
         "split": collections.Counter(p["split"] for p in pages),
         "stratum": collections.Counter(p["stratum"] for p in pages),
         "era": collections.Counter(p["era"] for p in pages),
         "category": collections.Counter(), "pairs": 0, "empty_pages": 0}
    for p in pages:
        g = json.loads((ROOT / "results" / "gold" / p["split"] / "json" / f"{p['page_id']}.json").read_text())
        s["category"].update(b["label"] for b in g["boxes"])
        s["pairs"] += len(g["pairs"])
        s["empty_pages"] += not g["boxes"]
    return s


def table(counter, order=None, head=("", "pages")):
    keys = order or [k for k, _ in counter.most_common()]
    return "\n".join([f"| {head[0]} | {head[1]} |", "|---|---:|"] + [f"| `{k}` | {counter[k]:,} |" for k in keys])


def write_items(pages, out):
    items = collections.defaultdict(list)
    for p in pages:
        items[int(p["item_id"])].append(p)
    with open(out / "items.tsv", "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["item_id", "ia_identifier", "year", "pages", "page_ids", "suggested_split", "bhl_url"])
        for iid, ps in sorted(items.items()):
            w.writerow([iid, ps[0]["barcode"], ps[0]["year"], len(ps), ",".join(p["page_id"] for p in ps),
                        ps[0]["split"], f"https://www.biodiversitylibrary.org/item/{iid}"])
    return len(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="hf")
    args = ap.parse_args()
    out = ROOT / args.out
    (out / "data").mkdir(parents=True, exist_ok=True)

    pages = sorted(load_pages(), key=lambda p: int(p["page_id"]))
    n_items = write_items(pages, out)
    print(f"{len(pages)} pages from {n_items} items -> {out / 'items.tsv'}")

    n_shards = -(-len(pages) // PAGES_PER_SHARD)
    for old in (out / "data").glob("*.parquet"):
        old.unlink()
    for k in range(n_shards):
        chunk = pages[k * PAGES_PER_SHARD:(k + 1) * PAGES_PER_SHARD]
        ds = Dataset.from_list([row(p) for p in chunk], features=FEATURES)
        path = out / "data" / f"pages-{k:05d}-of-{n_shards:05d}.parquet"
        ds.to_parquet(str(path))
        print(f"  {path.name}: {len(chunk)} pages, {path.stat().st_size / 1e6:.0f} MB")

    s = stats(pages)
    card = (ROOT / "hf_card_template.md").read_text()
    for k, v in {
        "PAGES": f"{s['pages']:,}", "ITEMS": f"{s['items']:,}", "PAIRS": f"{s['pairs']:,}",
        "BOXES": f"{sum(s['category'].values()):,}", "EMPTY_PAGES": str(s["empty_pages"]),
        "CATEGORY_TABLE": table(s["category"], CATEGORIES, ("category", "boxes")),
        "STRATUM_TABLE": table(s["stratum"]),
        "ERA_TABLE": table(s["era"], ["pre1850", "1850-1899", "1900-1949", "1950on"], ("era", "pages")),
        "SPLIT_TABLE": table(s["split"], ["train", "validation", "test"], ("suggested_split", "pages")),
        "CATEGORY_NAMES": ", ".join(f"`{c}`" for c in CATEGORIES),
    }.items():
        card = card.replace("{{" + k + "}}", v)
    assert "{{" not in card
    (out / "README.md").write_text(card)
    print(f"-> {out / 'README.md'}")


if __name__ == "__main__":
    main()
