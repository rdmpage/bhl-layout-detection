# Label Studio import

Made by `make_labelstudio.py` from detector output in the common JSON format.

| File | |
|---|---|
| `config.xml` | Labelling interface: boxes labelled figure, caption, table, text, title, header, footer, page_number, stamp; a `caption_of` relation from a caption to its figure or table |
| `pp-doclayout_plus-l_test_tasks.json` | 324 test pages; images load from BHL's S3 bucket |
| `pp-doclayout_plus-l_test_local_tasks.json` | The same, with images served from `layout/images` |

Each task carries the PP-DocLayout boxes as pre-annotations (Label Studio "predictions"), and caption pairs as relations. Boxes the ink filter marked `empty` are left out. Task data includes `page_id`, `stratum`, `era` and `bhl_url`, so you can filter and sort by them in the data manager.

## Import

1. Create a project. Under **Settings → Labeling Interface → Code**, paste `config.xml`.
2. **Import** `pp-doclayout_plus-l_test_tasks.json`.
3. Open a task: the model's boxes appear as a prediction. Correct them and submit; the submission is the gold annotation.

For the local-image version, start Label Studio with

```sh
LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=<repo>/layout \
label-studio start
```

(with Docker, mount `<repo>/layout` into the container and use the container path), and add a **Local Files** source storage with path `<repo>/layout/images` (don't sync it; the tasks file already lists the images), then import `..._local_tasks.json`.

Box coordinates are percentages of the image, so they fit whichever copy of the image is shown, as long as it is the same scan.

## Labelling rules to settle first

- One box per plate, or one per numbered figure?
- Figure numbers and lettering inside a plate are part of the figure, not captions.
- A map is a figure; a graph is a figure; a table drawn as a grid is a table.
- Section headings are `text`.
