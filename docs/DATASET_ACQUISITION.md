# Dataset Acquisition, Conversion, and Runbook

The tools keep public raw data, original annotations, aligned masks, synthetic data, custom annotations, and training-ready data separate. No webcam, phone, or ESP32 recording is required for acquisition, tests, or the offline demo.

## Current local data

- Open Images V7: 100 valid validation images, 158 original instance-mask PNGs, and 158 nearest-neighbor image-aligned masks. The pilot has no Painting or hand masks and is not a training set.
- The Met: 10 valid CC0 public-domain Painting images (33,575,954 bytes) plus their API object metadata and provenance.
- V-COCO: one MIT-licensed action/role JSON (3,135,892 bytes); no image pixels.
- MediaPipe: one Apache 2.0 hand-landmarker task bundle (7,819,105 bytes); it is an inference model, not a labeled dataset.
- Synthetic: 60 images, 120 binary masks, 20 each of SAFE / NEAR / CONTACT; 48/6/6 train/val/test images split by Met object ID.
- Public videos: zero. The ContactPose sample Drive link showed a sign-in prompt and no anonymous size preflight was available; HOI4D did not expose a bounded per-sequence size. No video was downloaded.
- Custom webcam sessions: zero. No user footage was supplied or required.

See [DATASET_REPORT.md](DATASET_REPORT.md) for current checksums, exact file inventory, source-group leakage, and readiness.

## Layout

```text
dataset/
  public/
    open_images/
      images/                         # 100 downloaded validation JPEGs
      original_annotations/           # official CSVs and source mask PNGs
      converted_annotations/masks/    # image-aligned raster copies only
      reports/
    metmuseum/
      images/                         # 10 CC0 artwork JPEGs
      metadata/                       # source API records and Met manifest
    mediapipe/hand_landmarker.task     # optional Apache 2.0 inference model
    other_sources/vcoco/annotations/  # V-COCO JSON and MIT notice
  synthetic/art_contact/
    images/                            # stylized synthetic scenes
    masks/                             # exact binary painting/interaction masks
    metadata/                          # per-sample provenance and group splits
  custom/
    raw_videos/
    extracted_frames/
    annotated/
    prepared/{images,labels}/{train,val,test}/
    metadata/
  metadata/
    acquisition_manifest.json
    provenance.jsonl
  reports/
    dataset_report.json
```

The original ContactHands/Detectron2 code and checkpoint remain intact. No rewrite or destructive conversion was applied to that baseline.

## Acquire and validate

Run commands from the repository root in PowerShell with the project Python. For model, package, and temporary caches on D, run Python commands through `tools/run_pbl4.py` as shown in [WINDOWS_LOW_MEMORY.md](WINDOWS_LOW_MEMORY.md). Dataset acquisition itself writes under the repository's D-drive `dataset/` directory.

```powershell
python tools/dataset_acquire.py sources
python tools/dataset_acquire.py inspect contacthands
python tools/dataset_acquire.py inspect contactpose
python tools/dataset_acquire.py inspect hoi4d
python tools/dataset_acquire.py open-images-pilot --limit 100 --max-bytes 1000000000 --preflight-only
python tools/dataset_acquire.py open-images-pilot --limit 100 --max-bytes 1000000000
python tools/dataset_acquire.py metmuseum-artworks --limit 10 --max-bytes 200000000
python tools/dataset_acquire.py download mediapipe_hand_landmarker full_task_model
python tools/dataset_acquire.py validate
python tools/dataset_acquire.py report
```

The Open Images pilot and Met download are already present in this workspace; rerun those commands only in a fresh checkout or with a higher limit. Downloads use HTTPS, preflight remote sizes, check disk reserve, record SHA-256 and provenance, retain partial files for resume, and refuse to overwrite changed or untracked destinations. The Met flow filters API records to `isPublicDomain=true` and `classification=Paintings`. The MediaPipe task bundle has a 50 MB hard cap and format/header check.

ContactHands image download remains disabled because the hosted image terms are unstated. ContactPose and HOI4D stay catalog-only until a bounded, permitted item can be downloaded without credentials or access-control workarounds.

## Annotation conversion and validation

The Open Images pilot retains source mask PNGs. It creates separate raster-aligned copies using nearest-neighbor interpolation only when the source and image aspect ratios match within 1% and no nonzero rotation is reported. It does not convert boxes to masks, map picture frames to paintings, or polygonize raster masks. This avoids pretending that box labels or a contour approximation are original instance ground truth.

The synthetic generator writes exact binary masks and checks the expected mask overlap/gap for every scene. Its shapes are vector drawings, not real cutouts or photo backgrounds, so these outputs are for geometry and logic checks only.

Dataset validation checks manifest hashes and formats, decodable images, annotation syntax, provenance, duplicate hashes, source-group splits, and the synthetic image/mask hashes, dimensions, and binary values. No video is counted unless a real video file opens and yields valid metadata and a frame.

## Generate and evaluate synthetic logic data

```powershell
python tools/synthetic_scenes.py --per-scenario 2 --seed 42
python tools/evaluate_contact_logic.py
python tools/dataset_acquire.py report
```

The checked-in run contains 60 `SYNTHETIC` images and 120 masks. Eight artwork source groups are train, one is validation, and one is test; no Met source group crosses splits. The labels are not real-world ground truth. A failed early generation attempt is preserved outside the active dataset under `_codex_partial_synthetic_20261011/`; it is excluded from the synthetic manifest and training inventory.

## Optional MediaPipe hand localization

The adapter uses the official MediaPipe Hand Landmarker VIDEO API. It converts the five fingertips into point contacts against the painting mask; it does not emit hand pixel masks or a calibrated hand-presence probability.

Install the optional package in the Python environment that will run the demo, then use the already acquired task model:

```powershell
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -m pip install -r requirements-hands.txt
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -m src.app.video_demo --input path\to\clip.mp4 --use-hand-landmarker
```

The MediaPipe package and adapter were smoke-tested in the isolated `.venv-hands`; the primary `.venv-py314` remains separate. On Windows the adapter makes a temporary ASCII-path copy of the task model during initialization, then removes it when closed, because the native runtime cannot load the task from this workspace’s non-ASCII path.

## Offline video, webcam, and ESP32-CAM

```powershell
# Offline file or network stream
python -m src.app.video_demo --input path\to\clip.mp4

# Optional webcam
python -m src.app.video_demo --webcam 0

# Optional ESP32-CAM-compatible MJPEG source
python -m src.app.video_demo --esp32-url http://192.168.4.1/stream
```

The server-side pipeline loads local `yolov8n-seg.pt`, predicts detections, uses Ultralytics’ configured tracker when `lap` is installed, otherwise uses local IoU/centroid IDs, applies a configurable painting ROI if no painting class is detected, evaluates spatial/temporal contact, writes per-frame JSONL and summary JSON, and saves event evidence and a rendered MP4 under `server/data/results/` by default. Webcam and ESP32 inputs are optional. The default pretrained COCO model has no Painting or Hand class; use the ROI and optional MediaPipe hand landmark path until valid task-specific training labels exist.

## Custom annotation and training

Use [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md) for reviewed custom labels and event intervals. Keep source video/session IDs intact and assign an entire source to one split:

```powershell
python tools/dataset_acquire.py assign-source-split gallery-session-001 train
python tools/dataset_acquire.py assign-source-split gallery-session-002 val
python tools/dataset_acquire.py assign-source-split gallery-session-003 test
```

The training YAML must declare nonempty `train`, `val`, and `test` image sets, class names, and `source_groups` with exact per-image group IDs. The validator rejects corrupt images, malformed normalized segmentation polygons, exact image hash leakage, and source-group leakage. It also requires every declared class to occur in train. A label file for a reviewed negative may be empty; missing labels are rejected.

```powershell
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- tools/train_yolo.py --data dataset/prepared/segmentation.yaml --smoke-test --name pbl4-lowmem-smoke
```

The CPU training gate requires at least 3 GiB of available RAM and has no bypass. It checks memory before opening the dataset or loading a model, uses `cache=False`, and stops safely on the current 0.44 GiB available state. A complete reviewed dataset is also required. Synthetic scenes are not used to claim real-world accuracy. Current CPU/RAM state is recorded in [TRAINING_REPORT.md](TRAINING_REPORT.md).

## Preservation and license records

Successful downloads are recorded in `dataset/metadata/acquisition_manifest.json` with source, terms, bytes, checksum, validation, and status. `dataset/metadata/provenance.jsonl` records per-image sources. The Open Images original CSVs and mask PNGs remain separate from aligned outputs. No public video, COCO image archive, ContactHands images, or ContactPose/HOI4D archive is represented as locally acquired.

