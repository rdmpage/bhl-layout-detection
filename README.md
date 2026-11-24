# BHL layout detection

Finding figures, captions and other layout blocks on [Biodiversity Heritage Library](https://www.biodiversitylibrary.org) page images, using free models that run on a local machine. OCR is out of scope: the aim is boxes and a label for each box, plus which caption belongs to which figure.

See [`bhl-layout-detection-plan.md`](bhl-layout-detection-plan.md) for the plan, methods to compare, label set and output format.

## Contents

| Path | |
|---|---|
| `layout/` | A stratified sample of 1,507 BHL pages split into train, validation and test (`pages.tsv`; see [`layout/README.md`](layout/README.md)). The images are not in git. |
| `run_ppdoclayout.py` | Runs [PP-DocLayout](https://github.com/PaddlePaddle/PaddleOCR) on a split and writes one JSON file per page |
| `layout_post.py` | Maps detector labels to the shared label set, flags empty "figures" (blank leaves, plain covers), pairs captions with figures and tables, draws overlays and a review page. Re-runs on saved output without the model. |
| `make_labelstudio.py` | Turns output into a [Label Studio](https://labelstud.io) import, with the detector's boxes as pre-annotations to correct (see [`labelstudio/README.md`](labelstudio/README.md)) |
| `results/<method>/<split>/json/` | Detector output, one JSON per page |
| `labelstudio/` | Labelling config and import files for the test split |

## Labels

figure, caption, table, text, title, header, footer, page_number, stamp, empty. Each page's JSON also has a `pairs` list linking caption boxes to the figure or table they describe.

## Setup

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

The page images are BHL's JPEGs from its open data; each page's `image_url` in `layout/pages.tsv` gives the source, and `image` the local path (`layout/images/<split>/<page_id>.jpg`). The sample and images were made by `layout-sample.php`, which lives with the BHL Elasticsearch prototype, not in this repo.

## Running

```sh
.venv/bin/python run_ppdoclayout.py --split test          # ~1 s a page on CPU
.venv/bin/python layout_post.py results/pp-doclayout_plus-l/test
.venv/bin/python make_labelstudio.py results/pp-doclayout_plus-l/test
```

Open `results/pp-doclayout_plus-l/test/index.html` to review the overlays.
