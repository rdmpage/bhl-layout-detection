# Notes for Claude

Context and decisions that the code doesn't record. See `README.md` for what each file does and `bhl-layout-detection-plan.md` for the overall plan.

## Goal

Free, local detection of layout blocks on BHL page images, mainly to extract **figures with their captions**. Paid services (Datalab, Mistral OCR) are only for building test labels, never for production. OCR text is out of scope here; classes that depend on meaning (species name, key, synonymy) are a later step using OCR text inside boxes.

## Decisions so far

- **Label set**: figure, caption, table, text, title (the title of a work or an article: on title pages and covers, and at the head of an article on an ordinary page; it marks where an article starts), header, footer, page_number, stamp, empty. Section headings (`paragraph_title`) go to `text` because they are unreliable on taxonomic text; the model's own label is kept in `source_label`. PP-DocLayout sometimes calls a section heading `doc_title` (e.g. "Family: RHIPICERIDAE"); a title-pages-only rule can't fix that because article titles on ordinary pages are real titles.
- **Duplicate boxes**: PP-DocLayout sometimes labels one region twice (e.g. `doc_title` + `paragraph_title`, `footer` + `footnote`). `layout_post.py` keeps the more confident of any two boxes with IoU ≥ 0.8 and keeps the other under `duplicates` in the JSON. In Label Studio a stacked box hides the one below it, so `labelstudio_to_gold.py` lists any stacks left in gold.
- **Caption pairing is post-processing** (`layout_post.py`), not a model class: nearest figure or table the caption is above, below, beside or inside. Captions pair with tables too, because PP-DocLayout uses one label (`figure_title`) for figure and table titles. Plate explanations on a facing page can't be paired from one page.
- **Ink filter**: PP-DocLayout boxes blank leaves and plain cloth covers as full-page images. A figure box with <1% "ink" (pixels clearly darker than the local background) becomes `empty`. On the test split real figures were ≥2.4% ink (one real faint foldout in validation is 1.25%, so don't raise it).
- **Cover filter** (`drop_covers` in `layout_post.py`): a figure covering ≥50% of the page, with no other boxes on the page, on a page whose paper brightness (70th percentile grey level) is <0.5, becomes `empty` (`empty_reason: cover`). Set on validation: lone page-sized real figures were all ≥0.61, cloth/leather/marbled covers ≤0.42. BHL's "Cover" page type would also work but our strata were drawn from page types, so it can't be tested here. Paper brightness is computed once from the image and stored in each page's JSON (`page.paper`).
- PP-DocLayout labels library stamps `seal`; mapped to `stamp`, not figure.
- PP-DocLayout_plus-L draws **one box per plate**, not per numbered figure.
- Python 3.12 venv, because paddlepaddle has no build for 3.14. CPU speed was about 1 s a page.

## About the sample (`layout/`)

Strata are BHL page types, which are noisy: use them for sampling and per-stratum reporting, not as ground truth. The mix is deliberately not BHL's natural mix (plain text is ~10%), so a random sample is needed to estimate false figures at scale. `text_figure` (figures inside text) is the most useful and hardest stratum, and is thin (32 test pages). Splits are by item, but journals cross splits (e.g. Journal of the Asiatic Society, 145 pages, mostly train). Images are 1,100–3,000 px wide despite `layout/README.md` saying ~1,000; compute scale per page from `ocr_width`.

## Status (2026-11-24)

- PP-DocLayout_plus-L run on test (324 pages) and validation (273); train not run.
- Test split fully hand-corrected (Label Studio project "BHL layout test", id 2, Docker at http://localhost:8080) → `labelstudio/export/test_annotations.json` → `results/gold/test/` (1,770 boxes, 128 caption pairs). Page 8283512 is labelled one text box per column.
- Validation split partly corrected (project "BHL layout validation", id 3): only figure, caption, table, title, stamp boxes and caption links were checked; text/header/footer/page_number are the model's, so ignore validation scores for those. → `results/gold/validation/` (103 caption pairs). Use validation for tuning post-processing, test only to check.
- With ink, duplicate and cover filters: figure pages F1 0.96 on test (4 false, 6 missed) and 0.94 on validation (6 false, 7 missed); figure boxes 0.92 / 0.90; caption pairs 0.85 / 0.79.
- Remaining false figures: blank leaves with show-through or stamps (pale, so the cover filter misses them) and small printer's devices/crests on title pages. Missed figures are mostly foldouts with no box, or figures called tables. Caption recall is weakest on plates and foldouts (~0.6).
- Test `text` precision is low (0.58) because of box granularity (paragraph vs block), not real errors.

## Next steps

1. Small-device filter for title pages (printer's devices, crests), tuned on validation.
2. Caption recall on plates and foldouts; merge figure panels that share one caption.
3. OCR word-box baseline: mask OCR word boxes and treat large remaining inked regions as figures. Needs the IA OCR data on an external drive (not yet connected).
4. Compare other detectors (DocLayout-YOLO, Docling) in the same format; fine-tune only if pretrained models fall short.
