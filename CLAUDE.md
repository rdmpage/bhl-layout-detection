# Notes for Claude

Context and decisions that the code doesn't record. See `README.md` for what each file does and `bhl-layout-detection-plan.md` for the overall plan.

## Goal

Free, local detection of layout blocks on BHL page images, mainly to extract **figures with their captions**. Paid services (Datalab, Mistral OCR) are only for building test labels, never for production. OCR text is out of scope here; classes that depend on meaning (species name, key, synonymy) are a later step using OCR text inside boxes.

## Decisions so far

- **Label set**: figure, caption, table, text, title (title-page title only), header, footer, page_number, stamp, empty. Section headings (`paragraph_title`) go to `text` because they are unreliable on taxonomic text; the model's own label is kept in `source_label`.
- **Caption pairing is post-processing** (`layout_post.py`), not a model class: nearest figure or table the caption is above, below, beside or inside. Captions pair with tables too, because PP-DocLayout uses one label (`figure_title`) for figure and table titles. Plate explanations on a facing page can't be paired from one page.
- **Ink filter**: PP-DocLayout boxes blank leaves and plain cloth covers as full-page images. A figure box with <1% "ink" (pixels clearly darker than the local background) becomes `empty`. On the test split real figures were ≥2.4% ink. Still wrong: show-through pages with stamps, and marbled/leather covers, pass the filter.
- PP-DocLayout labels library stamps `seal`; mapped to `stamp`, not figure.
- PP-DocLayout_plus-L draws **one box per plate**, not per numbered figure.
- Python 3.12 venv, because paddlepaddle has no build for 3.14. CPU speed was about 1 s a page.

## About the sample (`layout/`)

Strata are BHL page types, which are noisy: use them for sampling and per-stratum reporting, not as ground truth. The mix is deliberately not BHL's natural mix (plain text is ~10%), so a random sample is needed to estimate false figures at scale. `text_figure` (figures inside text) is the most useful and hardest stratum, and is thin (32 test pages). Splits are by item, but journals cross splits (e.g. Journal of the Asiatic Society, 145 pages, mostly train). Images are 1,100–3,000 px wide despite `layout/README.md` saying ~1,000; compute scale per page from `ocr_width`.

## Status (2026-11-24)

- PP-DocLayout_plus-L run on the 324 test pages; train and validation not yet run.
- Test split imported into Label Studio (Docker, http://localhost:8080, project "BHL layout test", id 2) with the model's boxes as predictions and caption pairs as `caption_of` relations. Hand correction not started.

## Next steps

1. Settle labelling rules before correcting (see `labelstudio/README.md`), especially one box per plate vs per figure.
2. Write a converter from Label Studio's export to the common JSON format (`"method": "gold"`) and a scoring script.
3. OCR word-box baseline: mask OCR word boxes and treat large remaining inked regions as figures. Needs the IA OCR data on an external drive (not yet connected).
4. Compare other detectors (DocLayout-YOLO, Docling) in the same format; fine-tune only if pretrained models fall short.
