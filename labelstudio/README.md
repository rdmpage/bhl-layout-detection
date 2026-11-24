# Label Studio import

Made by `make_labelstudio.py` from detector output in the common JSON format.

| File | |
|---|---|
| `config.xml` | Labelling interface: boxes labelled figure, caption, table, text, title, header, footer, page_number, stamp; a `caption_of` relation from a caption to its figure or table |
| `pp-doclayout_plus-l_test_tasks.json` | 324 test pages; images load from BHL's S3 bucket |
| `pp-doclayout_plus-l_test_local_tasks.json` | The same, with images served from `layout/images` |
| `pp-doclayout_plus-l_validation_tasks.json`, `..._local_tasks.json` | The 273 validation pages, the same way (separate project, "BHL layout validation") |

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

## Export

Only **submitted** annotations are exported; drafts (Label Studio's autosave of a page you have opened but not submitted) are not. Check the Data Manager shows every task as completed before exporting. To export from the Docker container (its data dir is mounted at `/label-studio/data`):

```sh
docker exec <container> label-studio export 2 JSON --export-path /label-studio/data/export.json
```

then copy it to `export/` (replace `completed_by` with the user id, so no email address goes into git) and run `labelstudio_to_gold.py`. If a page was submitted twice, the converter uses the newer annotation.

## Validation: partial correction

Validation is for tuning post-processing (cover/logo filter, merging figure panels, ink threshold, caption pairing), which only depends on figures and captions. So on validation pages correct only `figure`, `caption`, `table`, `title` and `stamp` boxes and the `caption_of` relations, and leave `text`, `header`, `footer` and `page_number` as the model drew them unless badly wrong. Validation scores for those classes are not meaningful.

## Labelling rules

- One box per numbered figure (or per plate), not per panel. A figure made of several panels or charts (e.g. "adults" and "juveniles" bar charts under one Figure 2) gets one box around all of them, including panel labels.
- Figure numbers and lettering inside a plate are part of the figure, not captions.
- A map is a figure; a graph is a figure; a table drawn as a grid is a table.
- Section headings are `text`. Titles of works and articles are `title`, wherever they appear: title pages, covers, and the head of an article on an ordinary page.
- Covers: label as if printed in black and white. Colour, tone or texture is background, not a figure. Journal name → `title`, other words → `text`; a real picture on the cover (photo, drawing) → `figure`. Plain cloth, marbled and leather covers get no boxes.
- Logos, crests, publisher's devices and printed seals get no box: they are decoration, not figures we want to extract.
- `stamp` is for library and ownership stamps only.
