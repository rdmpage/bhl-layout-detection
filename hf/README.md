---
license: other
license_name: per-item
license_details: "Rights vary by item; see the Rights section. TO DO before publishing."
task_categories:
- object-detection
tags:
- document-layout-analysis
- biodiversity
- historical-documents
- biodiversity-heritage-library
- figures
- captions
pretty_name: BHL page layout
size_categories:
- 1K<n<10K
configs:
- config_name: default
  data_files:
  - split: train
    path: data/pages-*.parquet
---

# BHL page layout

1,507 page images from the [Biodiversity Heritage Library](https://www.biodiversitylibrary.org) (BHL), from 1,183 items printed between the 18th and 21st centuries. Every page has hand-checked layout boxes (8,878 in all) and links from captions to the figures and tables they describe (607 links).

It was made to measure how well free, local layout detectors find **figures and their captions** in the biodiversity literature: plates, foldout maps, drawings embedded in text, tables and charts, on pages that range from 18th-century letterpress to 21st-century colour journals.

## What's in a row

One row per page.

| Column | |
|---|---|
| `image` | the page image: BHL's JPEG, about half the resolution of the scan (1,100–3,000 px wide) |
| `width`, `height` | image size in pixels |
| `objects` | the labelled boxes: `id`, `category`, `bbox` as COCO-style `[x, y, width, height]` in image pixels, `area` |
| `caption_pairs` | caption links: `caption` and `object` are `id`s in `objects`; the object is a `figure` or `table`. A figure can have more than one caption box (e.g. a title and a legend) |
| `page_id`, `item_id` | BHL's PageID and ItemID |
| `ia_identifier`, `seq` | the Internet Archive identifier of the scan and the page's position in it |
| `page_label`, `year`, `era` | BHL's page label, the item's year, and the period: `pre1850`, `1850-1899`, `1900-1949`, `1950on` |
| `stratum` | the kind of page it was sampled as (see Sampling) |
| `bhl_page_types` | BHL's page types. These are often wrong and were not corrected |
| `suggested_split` | `train`, `validation` or `test`, by item (see Splits) |
| `bhl_url`, `image_url` | the page at BHL, and the source of the image |

```python
from datasets import load_dataset
ds = load_dataset("<this repo>", split="train")
page = ds[0]
names = ds.features["objects"].feature["category"].names
for o in page["objects"]:
    print(names[o["category"]], o["bbox"])
```

## Categories

`figure`, `caption`, `table`, `text`, `title`, `header`, `footer`, `page_number`, `stamp`

| category | boxes |
|---|---:|
| `figure` | 656 |
| `caption` | 609 |
| `table` | 318 |
| `text` | 4,826 |
| `title` | 275 |
| `header` | 1,097 |
| `footer` | 261 |
| `page_number` | 790 |
| `stamp` | 46 |

198 pages have no boxes at all: blank leaves, plain cloth, leather and marbled covers.

## Labelling rules

- **figure**: an illustration, photograph, map, graph or chart. One box per numbered figure (or per plate), not per panel: a figure made of several panels gets one box around all of them, including panel letters and numbers. Figure numbers and lettering inside a plate are part of the figure, not captions.
- **caption**: the text that explains a figure or table, e.g. "Fig. 3. …" or a table's title.
- **table**: a table, including tables drawn as a grid.
- **text**: body text, lists, references, footnotes, and section headings. Headings are `text` because what counts as a heading is unreliable on taxonomic text.
- **title**: the title of a work or of an article, on title pages, covers, or at the head of an article on an ordinary page. It marks where an article starts.
- **header**, **footer**, **page_number**: running heads, running feet and page numbers.
- **stamp**: library and ownership stamps only.
- **Covers** are labelled as if printed in black and white. Colour, tone and texture are background. A journal's name is `title`, other words are `text`, a real picture on a cover is `figure`.
- **Logos, crests, publisher's devices and printed seals get no box.** They are decoration, not figures.
- Barcode labels and other library stickers get no box.

## How it was made

1. **Sampling.** Pages were drawn from BHL by page type, about 150 of each kind, spread over the four periods, with no more than one page of a kind from an item.
2. **Pre-annotation.** [PP-DocLayout_plus-L](https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L) was run on every page. Its labels were mapped onto the categories above, blank and cover "figures" were filtered out, and captions were linked to figures by position.
3. **Correction.** Every page was corrected by hand in Label Studio: boxes moved, added, deleted and relabelled, and caption links fixed. One person labelled all pages.

Because labelling started from a model's boxes, the labels may lean towards that model's way of drawing boxes where more than one answer would be right. The main case is **text granularity**: whether a run of text is one box or one per paragraph. Boxes for figures, captions, tables and titles were checked carefully; text boxes are less consistent, especially on validation pages.

## Sampling

The mix of pages is deliberately not BHL's natural mix: plain text is about 10% of the sample but most of BHL. Use the `stratum` column to reweight, and don't read the overall rate of figures here as the rate in BHL.

|  | pages |
|---|---:|
| `plate` | 150 |
| `map` | 150 |
| `title` | 150 |
| `text` | 150 |
| `list` | 150 |
| `chart` | 150 |
| `blank` | 150 |
| `text_figure` | 150 |
| `foldout` | 150 |
| `two_column` | 90 |
| `rotated` | 67 |

| Stratum | What it is |
|---|---|
| `foldout` | BHL type Foldout |
| `map` | Map |
| `title` | Title Page or Cover |
| `chart` | Chart: tables and graphs |
| `list` | Index, Table of Contents, List of Illustrations |
| `plate` | Illustration without Text |
| `text_figure` | Illustration and Text: figures in text, or plates with captions |
| `rotated` | Text only, printed sideways: mostly turned tables |
| `two_column` | Text only, in columns: mostly lists, indexes, references and gazetteers |
| `text` | Text only, one column |
| `blank` | Blank, often with show-through |

Strata come from BHL's page types, which are noisy: a page sampled as `chart` may be blank, and a `text` page may have a figure. The labels, not the stratum, say what is on the page.

| era | pages |
|---|---:|
| `pre1850` | 354 |
| `1850-1899` | 364 |
| `1900-1949` | 405 |
| `1950on` | 384 |

## Splits

All pages are in one Hugging Face split (`train` is just the default name). `suggested_split` gives the split used to develop and test post-processing for PP-DocLayout:

| suggested_split | pages |
|---|---:|
| `train` | 910 |
| `validation` | 273 |
| `test` | 324 |

Splits are by item, so all pages of a book are on the same side. **If you make your own split, split by `item_id`, not by page.** Pages from one book share typeface, layout and scanner, so a page-level split lets a model recognise the book and inflates its scores. Items are kept together, but some journals still appear in more than one split, as different volumes.

## Rights

The page images come from BHL's open data. Most items are public domain, but BHL also hosts in-copyright material by permission of the rights holders, under licences that vary by item. **TO DO before publishing: check each item in `items.tsv` and record its rights here, or leave out pages whose terms don't allow redistribution.** The labels themselves can be released under an open licence (TO DO: choose one, e.g. CC0 or CC BY).

## Citation

TO DO
