"""Score layout output against gold labels (both in the common JSON format).

Usage:
  .venv/bin/python score.py results/pp-doclayout_plus-l/test [--gold results/gold/test] [--iou 0.5]

Prints the tables and writes <result_dir>/scores.json (numbers plus the page
ids behind each error, for looking at).

Metrics (see bhl-layout-detection-plan.md):
- page level: does the page have a figure (table)? precision / recall over pages
- box level, per class: predicted and gold boxes of the same label matched
  one-to-one, greedily by IoU, at IoU >= --iou
- merges: a predicted box that covers two or more gold boxes (any label),
  e.g. one box over a plate and its caption
- splits: a gold box with two or more predicted boxes of the same label inside it,
  e.g. a plate drawn as several figures
- caption pairs: a predicted pair is right if its caption and its object match
  gold boxes that gold pairs together
Everything is also broken down by stratum. Predicted "empty" boxes (the ink
filter's rejected figures) count as no box.
"""
import argparse
import collections
import json
from pathlib import Path

from layout_post import LABELS

COVER = 0.8    # a gold box is "covered" by a predicted box if this much of it is inside
INSIDE = 0.5   # a predicted box is a fragment of a gold box if this much of it is inside
CLASSES = [c for c in LABELS if c != "empty"]
PAGE_CLASSES = ["figure", "table"]


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def iou(a, b):
    i = inter(a, b)
    return i / (area(a) + area(b) - i) if i else 0.0


def match(gold, pred, thr):
    """One-to-one matching of same-label boxes, best IoU first. Returns {pred id: gold id}."""
    cands = sorted(
        ((iou(g["bbox"], p["bbox"]), p["id"], g["id"])
         for g in gold for p in pred if g["label"] == p["label"]),
        reverse=True)
    m, used = {}, set()
    for v, pid, gid in cands:
        if v < thr:
            break
        if pid not in m and gid not in used:
            m[pid] = gid
            used.add(gid)
    return m


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f}


def score_page(gold, pred, thr):
    gb = gold["boxes"]
    pb = [b for b in pred["boxes"] if b["label"] != "empty"]
    m = match(gb, pb, thr)
    out = {"boxes": {}, "page": {}, "merges": [], "splits": []}

    for c in CLASSES:
        g = [b for b in gb if b["label"] == c]
        p = [b for b in pb if b["label"] == c]
        tp = sum(1 for b in p if b["id"] in m)
        out["boxes"][c] = (tp, len(p) - tp, len(g) - tp)
    for c in PAGE_CLASSES:
        out["page"][c] = (any(b["label"] == c for b in gb), any(b["label"] == c for b in pb))

    for p in pb:
        covered = [g for g in gb if area(g["bbox"]) and inter(p["bbox"], g["bbox"]) / area(g["bbox"]) >= COVER]
        if len(covered) >= 2:
            out["merges"].append((p["label"], tuple(sorted(g["label"] for g in covered))))
    for g in gb:
        frags = [p for p in pb if p["label"] == g["label"] and area(p["bbox"])
                 and inter(p["bbox"], g["bbox"]) / area(p["bbox"]) >= INSIDE]
        if len(frags) >= 2:
            out["splits"].append((g["label"], len(frags)))

    gold_pairs = {(p["caption"], p["object"]) for p in gold.get("pairs", [])}
    pred_pairs = [(p["caption"], p["object"]) for p in pred.get("pairs", [])
                  if p["caption"] in {b["id"] for b in pb} and p["object"] in {b["id"] for b in pb}]
    right = sum(1 for c, o in pred_pairs if (m.get(c), m.get(o)) in gold_pairs)
    out["pairs"] = (right, len(pred_pairs) - right, len(gold_pairs) - right)
    return out


def fmt(x):
    return "   -" if x is None else f"{x:.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir")
    ap.add_argument("--gold", help="gold dir (default results/gold/<split>)")
    ap.add_argument("--iou", type=float, default=0.5)
    args = ap.parse_args()

    rdir = Path(args.result_dir)
    gdir = Path(args.gold) if args.gold else rdir.parent.parent / "gold" / rdir.name
    gold = {int(f.stem): json.loads(f.read_text()) for f in (gdir / "json").glob("*.json")}
    pred = {int(f.stem): json.loads(f.read_text()) for f in (rdir / "json").glob("*.json")}
    pages = sorted(gold.keys() & pred.keys())
    missing = sorted(gold.keys() - pred.keys())

    boxes = collections.defaultdict(lambda: [0, 0, 0])            # class -> tp fp fn
    boxes_s = collections.defaultdict(lambda: [0, 0, 0])          # (stratum, class)
    page = collections.defaultdict(lambda: [0, 0, 0])             # class
    page_s = collections.defaultdict(lambda: [0, 0, 0])           # (stratum, class)
    pairs, pairs_s = [0, 0, 0], collections.defaultdict(lambda: [0, 0, 0])
    merges, splits = collections.Counter(), collections.Counter()
    n_s = collections.Counter()
    errors = collections.defaultdict(list)

    for pid in pages:
        s = gold[pid]["stratum"]
        n_s[s] += 1
        r = score_page(gold[pid], pred[pid], args.iou)
        for c, v in r["boxes"].items():
            for i in range(3):
                boxes[c][i] += v[i]
                boxes_s[s, c][i] += v[i]
        for i in range(3):
            pairs[i] += r["pairs"][i]
            pairs_s[s][i] += r["pairs"][i]
        for c, (g, p) in r["page"].items():
            k = 0 if g and p else 1 if p else 2 if g else None
            if k is not None:
                page[c][k] += 1
                page_s[s, c][k] += 1
            if p and not g:
                errors[f"page_{c}_false"].append(pid)
            if g and not p:
                errors[f"page_{c}_missed"].append(pid)
        fig = r["boxes"]["figure"]
        if fig[1] or fig[2]:
            errors["figure_box_errors"].append(pid)
        for lab, combo in r["merges"]:
            merges[lab, combo] += 1
            if lab in ("figure", "table", "caption"):
                errors["merges_figure_table_caption"].append(pid)
        for lab, n in r["splits"]:
            splits[lab] += 1
            if lab in ("figure", "table"):
                errors["splits_figure_table"].append(pid)
        if r["pairs"][1] or r["pairs"][2]:
            errors["pair_errors"].append(pid)

    method = pred[pages[0]]["method"] if pages else rdir.parent.name
    print(f"{method} vs gold, {rdir.name} split: {len(pages)} pages, IoU >= {args.iou}")
    if missing:
        print(f"  {len(missing)} gold pages have no output: {missing[:10]}{' ...' if len(missing) > 10 else ''}")

    print("\nPage level (does the page have one?)")
    print("  class      pages  prec   rec    f1")
    for c in PAGE_CLASSES:
        v = prf(*page[c])
        print(f"  {c:<9} {sum(page[c]):>5}  {fmt(v['precision'])}  {fmt(v['recall'])}  {fmt(v['f1'])}"
              f"   ({v['fp']} false, {v['fn']} missed)")

    print("\nBoxes, per class")
    print("  class         gold  pred  prec   rec    f1")
    for c in CLASSES:
        tp, fp, fn = boxes[c]
        v = prf(tp, fp, fn)
        print(f"  {c:<12} {tp + fn:>5} {tp + fp:>5}  {fmt(v['precision'])}  {fmt(v['recall'])}  {fmt(v['f1'])}")
    v = prf(*pairs)
    print(f"  {'caption pair':<12} {pairs[0] + pairs[2]:>5} {pairs[0] + pairs[1]:>5}  "
          f"{fmt(v['precision'])}  {fmt(v['recall'])}  {fmt(v['f1'])}")

    print("\nMerges (predicted box covering 2+ gold boxes), top 10")
    for (lab, combo), n in merges.most_common(10):
        print(f"  {n:>4}  {lab} over {' + '.join(f'{k} x{v}' if v > 1 else k for k, v in collections.Counter(combo).items())}")
    print("Splits (gold box with 2+ same-label predicted boxes inside)")
    print("  " + (", ".join(f"{lab} {n}" for lab, n in splits.most_common()) or "none"))

    print("\nBy stratum: figure pages, figure boxes, caption boxes, caption pairs (prec / rec)")
    print("  stratum      pages | fig pages     | fig boxes     | captions      | pairs")
    for s in sorted(n_s):
        cells = []
        for v in (prf(*page_s[s, "figure"]), prf(*boxes_s[s, "figure"]),
                  prf(*boxes_s[s, "caption"]), prf(*pairs_s[s])):
            cells.append(f"{fmt(v['precision'])} / {fmt(v['recall'])}")
        print(f"  {s:<12} {n_s[s]:>5} | " + " | ".join(cells))

    out = {
        "method": method, "split": rdir.name, "gold": str(gdir), "iou": args.iou,
        "pages": len(pages), "missing": missing,
        "page_level": {c: prf(*page[c]) for c in PAGE_CLASSES},
        "boxes": {c: prf(*boxes[c]) for c in CLASSES},
        "caption_pairs": prf(*pairs),
        "merges": [{"pred": lab, "gold": list(combo), "n": n} for (lab, combo), n in merges.most_common()],
        "splits": dict(splits),
        "by_stratum": {
            s: {"pages": n_s[s],
                "page_level": {c: prf(*page_s[s, c]) for c in PAGE_CLASSES},
                "boxes": {c: prf(*boxes_s[s, c]) for c in CLASSES},
                "caption_pairs": prf(*pairs_s[s])}
            for s in sorted(n_s)},
        "error_pages": {k: sorted(set(v)) for k, v in errors.items()},
    }
    (rdir / "scores.json").write_text(json.dumps(out, indent=1))
    print(f"\n-> {rdir / 'scores.json'}")


if __name__ == "__main__":
    main()
