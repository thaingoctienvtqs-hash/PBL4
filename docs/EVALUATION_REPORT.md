# Evaluation Report

Generated: 2026-10-11

## Results

- Current Windows training-readiness checks: **6 passed**, covering the RAM preflight, project-root path resolution, low-memory defaults, and dataset validation; Python compilation also passes. The broader non-legacy suite passed 52 tests before these Windows-specific changes. A full suite still has the previously observed `tests/test_contacthands.py` collection blocker because Detectron2 is not installed. Heavy model tests were not rerun with less than 1 GiB available RAM.
- Synthetic contact-logic evaluation: 3 hand-supplied geometric scenarios (SAFE, NEAR, CONTACT), with 1 true positive, 2 true negatives, no false positives or negatives; precision, recall, and F1 are each 1.0 for these scripted cases only. False alarms per hour and real-world artwork-contact performance are unmeasured.
- Offline YOLO pipeline smoke: a generated, unlabeled 4-frame, 320×240 clip at 5 FPS completed using the local pretrained YOLOv8n-seg weights and the IoU/centroid fallback tracker. Runtime was 3.5816 seconds (1.1168 frames/second); 0 alerts were emitted. No ground-truth event labels were supplied, so these are execution and output checks, not detection metrics. The summary is `server/data/results/codex_offline_smoke_output_fallback.summary.json`.
- Optional MediaPipe adapter smoke: the task bundle loaded in the isolated `.venv-hands` environment and processed blank frames with zero hand detections. This confirms initialization and safe empty-frame handling; it does not measure hand-detection accuracy. MediaPipe is not installed in the primary `.venv-py314` environment.

## Scope and limits

No public or user-supplied video was available for labeled event evaluation. The Open Images pilot is validation-only and does not annotate paintings or hand masks. The generated art scenes and scripted geometric detections are explicitly synthetic. Consequently, real-world precision, recall, false alarms per hour, and contact-detection latency remain **not measured**. The pretrained COCO model has no Painting or Hand class; the ROI and optional fingertip-landmark adapter provide demonstrator fallbacks, not a trained detector.

The previous full test-suite blocker is isolated to the original Detectron2 ContactHands test. For this resource-focused update, the targeted tests were run directly:

```powershell
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -m pytest -q -p no:cacheprovider --basetemp=runtime/tmp/pytest-training-current tests/test_training_readiness.py
```

