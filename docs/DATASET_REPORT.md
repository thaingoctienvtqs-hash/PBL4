# Dataset Acquisition Report

Generated (UTC): 2026-10-11T05:54:26+00:00

## Actual acquisition state

Validated downloaded assets: 135
Missing manifest files: 0
Dataset bytes scanned: 167388256
Duplicate file groups: 0

Manifest history: 2 duplicate successes superseded; 26 failed attempts have matching validated assets.

## Verified source inventory

Open Images boxable vocabulary: 601 CSV rows and 601 unique names from `dataset/public/open_images/metadata/oidv7-class-descriptions-boxable.csv`; official facts page headline says 600 classes (discrepancy flagged, not normalized).
Candidate names (vocabulary matches only, not sample counts or segmentation proof):
- painting: no exact candidate names in this boxable vocabulary
- person: boy, girl, man, person, woman
- hand: human hand
- tool: mobile phone, pen, scissors, tool

## Human-object action inventory

V-COCO annotations: 26 actions over 2533 unique referenced COCO image IDs; no instance masks or painting/harmful-contact labels.
Action names: hold, stand, sit, ride, walk, look, hit, eat, jump, lay, talk_on_phone, carry, throw, catch, cut, run, work_on_computer, ski, surf, skateboard, smile, drink, kick, point, read, snowboard.

## Metropolitan Museum Open Access

Verified public-domain painting images: 10; bytes: 33575954.
Only API records marked `isPublicDomain=true` are included. Artwork images are not gallery scenes or framed-painting labels.

## Public videos

Downloaded public video files: 0; valid/openable: 0; bytes: 0.

## Synthetic scenes

Synthetic images: 60; masks: 120; split counts: `{"train": 48, "val": 6, "test": 6}`.
Synthetic event labels: `{"SAFE": 20, "NEAR": 20, "CONTACT": 20}`; source-group leakage: `[]`.
Synthetic geometry and art-image crops are not real gallery scenes, real hand cutouts, or real-world ground truth.

## Optional hand-localization model

MediaPipe task model status: INSTALLED_IN_ISOLATED_ENVIRONMENT; package installed: True; verified model bytes: 7819105.
The adapter uses five fingertip landmarks as contact points. They are not pixel masks; the Task API does not expose a calibrated hand-presence probability, so event confidence uses its configured acceptance threshold.

## Open Images Image Pilot

Actual Open Images images: 100 downloaded and 100 valid; valid source masks: 158; bbox-only target instances: 273.
Official split counts: `{"train": 0, "validation": 100, "test": 0}`.
Masks by source class: `{"Person": 54, "Suit": 3, "Ipod": 7, "Mobile phone": 35, "Girl": 1, "Beer": 1, "Horse": 4, "Dress": 3, "Pen": 22, "Coffee cup": 1, "Human body": 1, "Man": 3, "Bicycle wheel": 3, "Jeans": 2, "Belt": 1, "Camera": 1, "Trousers": 2, "Shorts": 2, "Piano": 2, "Human ear": 1, "Remote control": 1, "Broccoli": 1, "Calculator": 1, "Harpsichord": 2, "Human mouth": 1, "Dog": 1, "Wine": 1, "Dumbbell": 1}`.
Images with any instance mask: 95; images with boxes but no instance mask: 5; images with at least one target bbox-only instance: 66.
Target class availability: `{"painting": {"source_aliases_checked": ["Painting"], "box_classes_available": [], "mask_classes_available": [], "box_annotation_available": false, "instance_mask_annotation_available": false, "annotation_status": "no exact usable source class"}, "person": {"source_aliases_checked": ["Person"], "box_classes_available": ["Person"], "mask_classes_available": ["Person"], "box_annotation_available": true, "instance_mask_annotation_available": true, "annotation_status": "instance masks and boxes"}, "hand": {"source_aliases_checked": ["Human hand", "Hand"], "box_classes_available": ["Human hand"], "mask_classes_available": [], "box_annotation_available": true, "instance_mask_annotation_available": false, "annotation_status": "boxes only"}, "tool": {"source_aliases_checked": ["Tool", "Mobile phone", "Pen", "Pencil"], "box_classes_available": ["Mobile phone", "Pen", "Tool"], "mask_classes_available": ["Mobile phone", "Pen"], "box_annotation_available": true, "instance_mask_annotation_available": true, "annotation_status": "instance masks and boxes"}, "picture_frame_not_painting": {"box_available": true, "mask_available": true, "mapped_to_painting": false}}`.
Pilot download bytes including extracted masks: 127615997.
Pilot training-ready: **false**. Not ready: validation-only subset; no painting or hand instance masks; source annotations are not exhaustively complete for every instance; no independent train/test sample; no artwork harmful-contact labels. Tool masks are limited to source classes Pen and Mobile phone under the documented target mapping.

## Custom Webcam and Annotation Workflow

Custom webcam sessions: 0; extracted frames: 0; LabelMe tasks: 0; review states: `{}`.
Custom source-group split counts: `{"train": 0, "val": 0, "test": 0}`; independent groups: 0; meaningful evaluation split: False; reviewed events: 0.

## Prepared labels

Prepared images: 0 (invalid: 0); valid segmentation rows: 0; box-only rows: 0; malformed rows: 0; images missing labels: 0; orphan labels: 0.
Class counts: `{}`.
A box-only row is not counted as a segmentation mask. Automatically proposed annotations must remain marked unverified until human review.

## Provenance and leakage

Public JPEG/web images: 110; public mask PNGs: 316; public files without provenance: 0. Custom JPEG/web images: 0; custom mask PNGs: 0; custom files without provenance: 0.
Source-level split check: {"checked": false, "leaks": [], "reason": "No source-level split assignments recorded."}.

## Training readiness

Ready for YOLO segmentation fine-tuning: **false**.
Not ready for the full painting/person/hand/tool task: no compatible, complete, independently split masks cover painting and hand. Person and Pen masks exist only in a small validation-only pilot with incomplete annotation coverage. No custom or contact-labeled videos are available.
- **object_segmentation: NOT_TRAINED** — The existing 100-image Open Images subset comes only from its official validation split and has incomplete target-instance annotation. It has no painting masks; Human hand is box-only. A source-grouped, complete training set for the desired task is not ready.
- **hand_localization: PRETRAINED_LANDMARK_ADAPTER_READY** — MediaPipe supplies 21 hand landmarks and the integrated adapter tests fingertip points against the configured painting mask; it does not supply hand segmentation masks or calibrated contact labels. The package and Apache 2.0 task model are validated in an isolated environment; install requirements-hands.txt in the selected server environment before enabling it. Open Images Human hand labels are boxes only, and ContactHands hosted-image terms remain unstated.
- **painting_detection: ROI_FALLBACK_CONFIGURED** — The fixed-camera polygon ROI is configurable. Met artwork images do not teach framed-painting scene detection.
- **artwork_contact_event: NOT_TRAINED** — No genuine painting-contact video labels are available. Synthetic logic scenarios are not real-world model training data.
