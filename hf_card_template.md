---
license: other
license_name: per-item
license_details: "Page images keep the rights of their BHL item (public domain or Creative Commons, mostly non-commercial); see the license column and the Rights section."
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

{{PAGES}} page images from the [Biodiversity Heritage Library](https://www.biodiversitylibrary.org) (BHL), from {{ITEMS}} items printed between the 18th and 21st centuries. Every page has hand-checked layout boxes ({{BOXES}} in all) and links from captions to the figures and tables they describe ({{PAIRS}} links).

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

{{CATEGORY_NAMES}}

{{CATEGORY_TABLE}}

{{EMPTY_PAGES}} pages have no boxes at all: blank leaves, plain cloth, leather and marbled covers.

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

{{STRATUM_TABLE}}

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

{{ERA_TABLE}}

## Splits

All pages are in one Hugging Face split (`train` is just the default name). `suggested_split` gives the split used to develop and test post-processing for PP-DocLayout:

{{SPLIT_TABLE}}

Splits are by item, so all pages of a book are on the same side. **If you make your own split, split by `item_id`, not by page.** Pages from one book share typeface, layout and scanner, so a page-level split lets a model recognise the book and inflates its scores. Items are kept together, but some journals still appear in more than one split, as different volumes.

## Rights

The page images come from BHL's open data, and their rights are BHL's, item by item. Each row says what BHL records for its item:

| Column | |
|---|---|
| `copyright_status` | `not_in_copyright`, `in_copyright` (digitised with the rights holder's permission) or `unknown` (BHL: "not provided") |
| `license` | the item's Creative Commons licence, e.g. `CC-BY-NC-SA-4.0`, or empty if none |
| `bhl_copyright_status`, `bhl_rights_statement`, `bhl_license_url` | BHL's own wording, unchanged |

{{RIGHTS_TABLE}}

{{EXCLUDED}}

Most in-copyright pages are licensed for **non-commercial use only** (CC BY-NC or BY-NC-SA). If you need images you can use commercially, keep rows whose `copyright_status` is `not_in_copyright` or whose `license` is `CC-BY-4.0`. Check BHL's [permissions page](https://www.biodiversitylibrary.org/permissions) for details.

The labels (boxes, categories and caption links) are released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/): use them for anything, no permission or credit needed. This covers the labels only; the images keep their own rights, as above.
