# Custom Annotation Guide

## Prepare webcam data

Install LabelMe in the project environment (it is optional and not part of the server runtime):

```powershell
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -m pip install -r requirements-annotation.txt
```

Record a consented webcam session. Every recording gets a unique session ID and a JSON sidecar under `dataset/custom/raw_videos/`:

```powershell
python tools/custom_dataset.py record-webcam --duration 180 --camera-index 0 --backend dshow --width 640 --height 480 --fps 10
```

Extract one frame every two seconds (set `--sample-seconds` to control spacing):

```powershell
python tools/custom_dataset.py extract-frames dataset/custom/raw_videos/<session-id>.avi --sample-seconds 2
```

The extractor records the source session/video, frame timestamp, width, height and FPS. Existing frames are decoded and skipped rather than overwritten. Raw video, frames and the publicly downloaded Open Images pilot remain in distinct `custom/` and `public/` trees.

## LabelMe polygons

Create empty annotation task JSONs for custom extracted frames:

```powershell
python tools/custom_dataset.py prepare-labelme
```

Open each task from its returned `annotation_file` path:

```powershell
python tools/custom_dataset.py open-labelme dataset/custom/annotated/labelme/<session-id>/<frame-name>.json
```

Tasks reference the extracted frame instead of copying it. LabelMe is configured with the fixed classes `painting`, `person`, `hand`, and `tool`. Draw closed polygons around visible object pixels using the polygon tool. Label each visible instance once. Keep occluded pixels unannotated; do not infer a hidden hand or painting boundary. Do not label a picture frame as a painting unless the PBL annotation policy explicitly defines a human-reviewed mapping for that specific sample.

After inspecting every target instance in the frame, mark the task reviewed. Use `--verified-empty` only when you reviewed the complete frame and no target instance is visible; use `--complete-scene-reviewed` only when every visible target instance is labeled under the project policy:

```powershell
python tools/custom_dataset.py set-annotation-state dataset/custom/annotated/labelme/<session-id>/<frame-name>.json --state reviewed --reviewer "Your Name" --notes "All visible target instances checked" --complete-scene-reviewed
```

Other states are `pending`, `proposed_unverified`, and `rejected`. Proposed labels never enter conversion. A reviewed empty frame requires both `--verified-empty` and `--complete-scene-reviewed`; it becomes an empty label file only after review, for real negative examples. Review state, reviewer identity and completeness attestation live in `dataset/custom/metadata/annotation_manifest.json`, separate from LabelMe geometry.

Check reviewed polygons before conversion:

```powershell
python tools/custom_dataset.py validate-annotations
```

The validator checks exact class names, polygon shape type, at least three unique non-collinear points, bounds, image dimensions and source-image SHA-256. Rectangles, boxes, malformed polygons and stale-image annotations are rejected for segmentation conversion.

## Event labels are separate

Create one event template per webcam recording:

```powershell
python tools/custom_dataset.py event-templates
```

Edit `dataset/custom/annotated/events/<session-id>.json` after reviewing the clip. Each event uses the recording session ID and a `[start_seconds, end_seconds)` interval, with a label of `SAFE`, `NEAR`, or `CONTACT` and written visual evidence. Define the project's NEAR distance policy before collection. `CONTACT` requires an explicit `reviewed_by` and visual evidence of physical touching; box overlap alone is never sufficient. Mark the file `review_state` as `reviewed` and set `reviewer` only after reviewing the full recording. Keep event labels separate from per-object polygons.

Example event entry:

```json
{
	"start_seconds": 18.4,
	"end_seconds": 20.1,
	"label": "CONTACT",
	"evidence": "Reviewer confirmed visible hand-to-artwork contact in the clip.",
	"reviewed_by": "Your Name",
	"correction_notes": ""
}
```

Validate event files:

```powershell
python tools/custom_dataset.py validate-events
```

## Split and convert

The source-group splitter accepts only reviewed LabelMe polygons and reviewed-empty negatives. It groups every frame from the same recording session, coalesces identical image SHA-256s, and refuses hash leakage across splits:

```powershell
python tools/custom_dataset.py split-reviewed --seed pbl4-custom-v1
python tools/custom_dataset.py convert-yolo
```

YOLO segmentation labels are emitted only from actual reviewed LabelMe polygons using `0=painting`, `1=person`, `2=hand`, `3=tool`. Public Open Images boxes and masks are never copied into these custom splits. Original LabelMe JSON and source metadata remain available for review/demo evidence. Conversion does not start training.
