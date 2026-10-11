# Final Implementation Report

Date: 2026-10-11

## Delivered

- Added a rights-aware acquisition catalog and downloader with HTTPS and size preflight, bounded downloads, checksums, provenance, safe resume behavior, source/license reporting, and validation. The current audit verifies 135 manifest assets with no missing files and no duplicate payload groups. It keeps acquisition history, annotates two superseded duplicate success records, and records all failed attempts as recovered when the surviving file matches a validated checksum.
- Acquired an Open Images V7 validation-only pilot (100 valid JPEGs, 158 original instance masks, and 158 aligned raster copies), 10 Met Museum CC0 public-domain painting images (33,575,954 bytes), V-COCO action annotations, and the Apache 2.0 MediaPipe hand-landmarker task bundle (7,819,105 bytes). Public/custom/synthetic assets and provenance are kept separate.
- Generated 60 labeled, stylized synthetic scenes and 120 exact binary masks, balanced across SAFE, NEAR, and CONTACT. They use ten Met artwork source groups and a 48/6/6 train/validation/test image split with no group leakage, malformed samples, or orphan masks.
- Added configurable YOLOv8n-seg video inference, polygon ROI fallback, optional MediaPipe fingertip landmarks, temporal contact logic, local tracker fallback, JSONL event logs, evidence images, rendered video, summary metrics, and offline/webcam/ESP32-CAM input paths.
- Added dataset preparation checks, source-group split validation, a D-drive runtime cache/temp launcher, root-relative model/data/output paths, and a safe training profile with 320-pixel images, batch 1, zero workers, disabled dataset caching, and a one-epoch/10% smoke option. Added synthetic contact-logic evaluation and current setup, annotation, dataset, training, and evaluation reports.

## Verification and actual-data limits

- Current Windows training-readiness checks: **6 passed**, covering the RAM preflight, project-root path resolution, low-memory defaults, and dataset validation; Python compilation also passes. The broader 52-test non-legacy run was completed before these Windows-specific changes. A full suite still has the previously observed missing-Detectron2 blocker; heavy model tests were not rerun with less than 1 GiB available RAM.
- A four-frame generated clip completed through actual YOLO inference at 1.1168 FPS with no alerts; it had no event labels and is only a pipeline smoke test.
- Three scripted geometry cases pass synthetic logic evaluation (1 TP, 2 TN). This does not establish model or real-scene accuracy.
- No public video or custom gallery video was acquired. ContactPose did not expose an anonymous bounded download, and the HOI4D links did not provide a bounded sequence download without access barriers.
- **No custom model was trained.** The available public annotations do not provide complete independent target-class masks or contact-event labels. The live training preflight found 473,694,208 bytes available (0.44 GiB); the latest reading was 803,598,336 bytes (0.75 GiB), both below the trainer's 3 GiB CPU safety gate.

The original ContactHands/Detectron2 code and `models/combined_data_model.pth` were preserved. See [DATASET_ACQUISITION.md](DATASET_ACQUISITION.md) for exact run commands, [DATASET_REPORT.md](DATASET_REPORT.md) for the generated inventory, [TRAINING_REPORT.md](TRAINING_REPORT.md) for the training decision, and [EVALUATION_REPORT.md](EVALUATION_REPORT.md) for test scope and performance limits.
