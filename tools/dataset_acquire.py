from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
MANIFEST = DATASET / "metadata" / "acquisition_manifest.json"
REPORT_JSON = DATASET / "reports" / "dataset_report.json"
REPORT_MD = ROOT / "docs" / "DATASET_REPORT.md"
USER_AGENT = "PBL4-dataset-acquisition/1.0 (documented public dataset retrieval)"
TARGET_CLASSES = {"0": "painting", "1": "person", "2": "hand", "3": "tool"}

SOURCES = {
    "contacthands": {
        "name": "ContactHands",
        "official_source_url": "https://vision.cs.stonybrook.edu/~supreeth/ContactHands_data_website/",
        "terms_url": "https://vision.cs.stonybrook.edu/~supreeth/ContactHands_data_website/",
        "license": "The official dataset page does not state image-level reuse terms. The companion code repository is MIT, but that does not by itself establish rights for the separately hosted images.",
        "attribution": "Cite Narasimhaswamy et al., Detecting Hands and Recognizing Physical Contact in the Wild (NeurIPS 2020); per-image attribution terms are not stated on the dataset page.",
        "classes": "Hands with four non-exclusive contact states: No-Contact, Self-Contact, Other-Person-Contact, Object-Contact.",
        "annotations": "Quadrilateral hand bounding boxes and Yes/No/Unsure labels for each contact state; no pixel masks and no painting-contact class.",
        "format": "In-the-wild images and hand/contact annotations; the official page states a 4.5 GB release.",
        "estimated_size": "4.5 GB per the official project page.",
        "limitations": "Dataset facts are verified from the official project page, but image reuse terms remain unclear. No download until rights for the hosted images are established.",
        "relevance": "Potentially relevant to hand-object contact research and legacy baseline comparison, but does not establish painting masks or harmful artwork contact.",
        "assets": {},
    },
    "contactpose": {
        "name": "ContactPose",
        "official_source_url": "https://github.com/facebookresearch/ContactPose",
        "terms_url": "https://github.com/facebookresearch/ContactPose#licensing",
        "license": "The repository states all data other than 3D models are MIT licensed; each 3D model has a separate license in the download metadata.",
        "attribution": "Cite Brahmbhatt et al., ContactPose (ECCV 2020), retain MIT notices, and follow each included 3D model's own license.",
        "classes": "Hand-object grasps, hand and object pose, object identity, and functional use/handoff intent.",
        "annotations": "3D hand joints/MANO fits, camera calibration, hand-object contact maps, and RGB-D grasp sequences. Documentation describes hand/object depth maps and masks; contact is generic object contact, not artwork contact.",
        "format": "Per-sequence compressed RGB video or RGB-D frames, contact-map/pose annotations, and model assets with separate licenses.",
        "estimated_size": "The official documentation reports about 2.08 GB for one participant/object/intent RGB-D subset and about 2.5 TB for the full RGB-D collection. The current public sample ZIP size is not verified.",
        "limitations": "Not gallery behavior or painting-contact supervision. Sample archives may contain 3D models with separate terms. No dataset files downloaded in this acquisition stage.",
        "relevance": "Potential auxiliary hand/object contact baseline while preserving original contact semantics.",
        "assets": {},
    },
    "hoi4d": {
        "name": "HOI4D",
        "official_source_url": "https://hoi4d.github.io/",
        "terms_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "license": "CC BY-NC 4.0; attribution and noncommercial use are required.",
        "attribution": "Cite Liu et al., HOI4D (CVPR 2022), attribute the authors/source, and link the CC BY-NC 4.0 license.",
        "classes": "16 household object categories, egocentric hand interactions, object pose, and action segments.",
        "annotations": "RGB/depth videos; frame-wise action, 2D motion segmentation, 3D static and 4D dynamic panoptic labels, 3D hand pose, and object pose. No painting/artwork class or harmful artwork-contact labels.",
        "format": "OneDrive/Baidu-hosted video archives with annotation, pose, and segmentation assets.",
        "estimated_size": "2.4 million RGB-D frames over about 4,000 sequences. The official materials inspected do not list a bounded per-sequence archive size.",
        "limitations": "Full release is large; a small, size-checked official clip could not be identified in the current catalog. No download until a bounded item is identified. Generic HOI labels are not artwork-contact labels.",
        "relevance": "Potential source for interaction video if a permitted, bounded archive can be selected; CC BY-NC use must remain noncommercial.",
        "assets": {},
    },
    "metmuseum": {
        "name": "The Metropolitan Museum of Art Open Access API",
        "official_source_url": "https://metmuseum.github.io/",
        "terms_url": "https://www.metmuseum.org/policies/terms-and-conditions",
        "license": "Only API records with isPublicDomain=true and their corresponding Open Access image are downloaded. Those records/images are identified as CC0; other records are excluded.",
        "attribution": "CC0 requires no attribution. Preserve artist, title, object URL, credit line, source API record, and license metadata as good practice.",
        "classes": "Artwork images, including paintings where the API record identifies classification=Paintings.",
        "annotations": "Artwork catalog metadata and the image itself; no gallery-scene, frame, person, hand, or contact labels.",
        "format": "JSON API records and JPEG images.",
        "estimated_size": "Per-run image budget defaults to 200 MB; actual total is recorded after acquisition.",
        "limitations": "An artwork photograph is not a gallery scene. The artwork image boundary is used only for the explicitly synthetic artwork-image boundary task and does not train framed-painting detection.",
        "relevance": "CC0 art assets for synthetic composites and visual demos, not scene-detection supervision.",
        "assets": {},
    },
    "mediapipe_hand_landmarker": {
        "name": "MediaPipe Hand Landmarker Full model asset",
        "official_source_url": "https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker",
        "terms_url": "https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Hand%20Tracking%20%28Lite_Full%29%20with%20Fairness%20Oct%202021.pdf",
        "license": "Apache License 2.0, as stated by the official model card.",
        "attribution": "MediaPipe Hand Landmarker model; retain the Apache 2.0 notice when redistributing the model asset.",
        "classes": "Hand landmarks (21 points) and handedness; this is a pretrained inference model, not a labeled training dataset.",
        "annotations": "Inference output only: 21 image/world landmarks and handedness. It does not produce pixel masks or contact labels.",
        "format": "Official MediaPipe .task model bundle.",
        "estimated_size": "Unknown until HTTPS HEAD preflight; the downloader refuses files larger than 50 MB.",
        "limitations": "Landmarks support hand localization but are not pixel segmentation. The model card flags gloves and occlusions as out of scope.",
        "relevance": "Optional hand-localization component because the COCO YOLO checkpoint has no hand class and available Open Images hand labels are boxes only.",
        "assets": {
            "full_task_model": {
                "url": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
                "filename": "hand_landmarker.task",
                "destination": "public/mediapipe",
                "kind": "model-task",
                "required_columns": [],
                "download_allowed": True,
                "max_size_bytes": 50_000_000,
                "purpose": "Apache 2.0 MediaPipe hand landmark inference bundle; not used as segmentation ground truth.",
            },
        },
    },
    "open_images": {
        "name": "Open Images V7",
        "official_source_url": "https://storage.googleapis.com/openimages/web/index.html",
        "terms_url": "https://storage.googleapis.com/openimages/web/factsfigures_v7.html#licenses",
        "license": "Annotations: CC BY 4.0. Images are listed as CC BY 2.0, but the official page disclaims warranties and requires users to verify each image license themselves.",
        "attribution": "Credit Google LLC for annotations and preserve per-image author/license/landing URL attribution; cite the Open Images and relevant annotation papers.",
        "classes": "Official overview: 600 box classes, 350 segmentation classes, 5,827 point-label classes. Exact boxable inventory is downloaded as the pilot. Segmentation inventory is not inferred from box labels.",
        "annotations": "Boxes, instance masks, visual relationships, image labels, localized narratives, points; availability varies by image/split/class.",
        "format": "CSV annotations and metadata; binary PNG instance masks; images.",
        "estimated_size": "Full dense subset is multi-gigabyte. The bounded 100-image validation pilot preflight estimated about 128 MB including metadata, required mask shards, JPEGs, and extracted masks; the full dataset was not downloaded.",
        "limitations": "No artwork-contact supervision. Boxes are not masks. Per-image license must be checked. Body-part boxes are limited to stated splits/subsets; point labels are not instance masks.",
        "relevance": "Actual validation pilot confirms Person, Mobile phone, and Pen masks; Human hand has boxes only and Painting has no exact box/mask class. Not museum behavior or harmful-contact ground truth.",
        "assets": {
            "boxable_classes": {
                "url": "https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv",
                "filename": "oidv7-class-descriptions-boxable.csv",
                "destination": "public/open_images/metadata",
                "expected_size_bytes": 12064,
                "kind": "csv",
                "required_columns": ["LabelName", "DisplayName"],
                "download_allowed": True,
                "purpose": "Small official class-inventory metadata pilot only; this is not an image or annotation download.",
            },
            "segmentation_classes": {
                "url": "https://storage.googleapis.com/openimages/v7/oidv7-classes-segmentation.txt",
                "filename": "oidv7-classes-segmentation.txt",
                "destination": "public/open_images/metadata",
                "expected_size_bytes": 3351,
                "kind": "text",
                "required_columns": [],
                "download_allowed": True,
                "purpose": "Official V7 list of classes with segmentation annotations; distinct from the box class inventory.",
            },
            "class_descriptions": {
                "url": "https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions.csv",
                "filename": "oidv7-class-descriptions.csv",
                "destination": "public/open_images/metadata",
                "expected_size_bytes": 501178,
                "kind": "csv",
                "required_columns": ["LabelName", "DisplayName"],
                "download_allowed": True,
                "purpose": "Official V7 MID-to-display-name mapping for preserving source class identities.",
            },
            "validation_segmentation_annotations": {
                "url": "https://storage.googleapis.com/openimages/v5/validation-annotations-object-segmentation.csv",
                "filename": "validation-annotations-object-segmentation.csv",
                "destination": "public/open_images/original_annotations",
                "expected_size_bytes": 2920821,
                "kind": "csv",
                "required_columns": ["MaskPath", "ImageID", "LabelName", "BoxID", "BoxXMin", "BoxXMax", "BoxYMin", "BoxYMax"],
                "download_allowed": True,
                "purpose": "Official Open Images validation instance-mask annotations; source masks remain binary PNGs.",
            },
            "validation_bbox_annotations": {
                "url": "https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv",
                "filename": "validation-annotations-bbox.csv",
                "destination": "public/open_images/original_annotations",
                "expected_size_bytes": 25105048,
                "kind": "csv",
                "required_columns": ["ImageID", "LabelName", "XMin", "XMax", "YMin", "YMax"],
                "download_allowed": True,
                "purpose": "Official validation bounding boxes kept distinct from instance masks.",
            },
            "validation_image_info": {
                "url": "https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv",
                "filename": "validation-images-with-rotation.csv",
                "destination": "public/open_images/metadata",
                "expected_size_bytes": 15245485,
                "kind": "csv",
                "required_columns": ["ImageID", "Subset", "OriginalURL", "OriginalLandingURL", "License", "Author", "OriginalSize", "OriginalMD5", "Thumbnail300KURL"],
                "download_allowed": True,
                "purpose": "Official per-image source URL, landing page, license, author, size, and source checksum metadata for validation images.",
            },
        },
    },
    "coco": {
        "name": "COCO 2017",
        "official_source_url": "https://cocodataset.org/",
        "terms_url": "https://cocodataset.org/#termsofuse",
        "license": "Annotations and website: CC BY 4.0. Images are third-party Flickr works; use is subject to each image's source terms and user responsibility.",
        "attribution": "Attribution is required for annotations; preserve COCO and image-specific attribution/license metadata.",
        "classes": "80 object categories; official overview reports 250,000 people with keypoints. Exact category inventory is in the downloaded COCO instance annotation JSON, not class names guessed here.",
        "annotations": "Instance segmentation polygons/RLE and bounding boxes in COCO JSON; also keypoints and captions in separate annotations.",
        "format": "JSON annotations and JPEG images.",
        "estimated_size": "The official page does not state archive sizes. The annotations archive is often published as a few hundred MB; acquisition requires a live Content-Length preflight before download.",
        "limitations": "No painting or hand instance classes in the standard 80 categories; person and some generic objects are useful. Presence near an object is not contact/harmful-contact ground truth. Image rights remain separate from annotation rights.",
        "relevance": "Useful instance-segmentation pretraining for person and supported objects, not paintings, hands, gallery behavior, or artwork contact.",
        "assets": {
            "annotations_trainval2017": {
                "url": "https://images.cocodataset.org/annotations/annotations_trainval2017.zip",
                "filename": "annotations_trainval2017.zip",
                "destination": "public/coco/annotations",
                "expected_size_bytes": None,
                "kind": "zip",
                "required_columns": [],
                "download_allowed": True,
                "purpose": "Official annotation archive only; does not download images.",
            },
        },
    },
    "vcoco": {
        "name": "V-COCO",
        "official_source_url": "https://github.com/s-gupta/v-coco",
        "terms_url": "https://github.com/s-gupta/v-coco/blob/master/LICENSE",
        "license": "The official repository LICENSE is MIT and includes its copyright/license notice. COCO images referenced by the annotations are separate third-party assets under COCO/Flickr terms and are not included in this download.",
        "attribution": "Retain the Regents of the University of California copyright/license notice and cite Visual Semantic Role Labeling and COCO. Preserve the official image-ID split references.",
        "classes": "The downloaded official training JSON contains 26 action names: hold, stand, sit, ride, walk, look, hit, eat, jump, lay, talk_on_phone, carry, throw, catch, cut, run, work_on_computer, ski, surf, skateboard, smile, drink, kick, point, read, snowboard.",
        "annotations": "Per-action image IDs, person annotation IDs, action labels, role names, include flags, and role object IDs. This represents human-object action/role supervision, not artwork-contact labels or image masks.",
        "format": "JSON annotation arrays linked to COCO image IDs.",
        "estimated_size": "Official vcoco_train.json is 3,135,892 bytes; official repository tree lists this size.",
        "limitations": "No painting class, no segmentation masks in this JSON, and actions are not harmful-contact labels. The official README documents missing role annotations for six categories. Images are not included and retain their own rights.",
        "relevance": "Useful for general person-action and human-object interaction research; not a substitute for hand localization, painting masks, museum negatives, or dangerous artwork-contact labels.",
        "assets": {
            "train_annotations": {
                "url": "https://raw.githubusercontent.com/s-gupta/v-coco/master/data/vcoco/vcoco_train.json",
                "filename": "vcoco_train.json",
                "destination": "public/other_sources/vcoco/annotations",
                "expected_size_bytes": 3135892,
                "kind": "vcoco-json",
                "required_columns": [],
                "download_allowed": True,
                "purpose": "Official MIT-repository human-object action annotations only; no COCO image files are downloaded.",
            },
            "license_text": {
                "url": "https://raw.githubusercontent.com/s-gupta/v-coco/master/LICENSE",
                "filename": "LICENSE",
                "destination": "public/other_sources/vcoco/metadata",
                "expected_size_bytes": 1133,
                "kind": "text",
                "required_columns": [],
                "download_allowed": True,
                "purpose": "Upstream copyright and MIT license notice for the repository release.",
            },
        },
    },
    "other_sources": {
        "name": "Other public sources",
        "official_source_url": "",
        "terms_url": "",
        "license": "Not assessed; no downloads enabled.",
        "attribution": "Must be assessed per source before enabling.",
        "classes": "None assessed.",
        "annotations": "None assessed.",
        "format": "Varies.",
        "estimated_size": "Unknown.",
        "limitations": "Additional sources remain disabled until official licensing, annotation definitions, and documented download procedures are verified.",
        "relevance": "Candidate bucket only; not evidence of an approved dataset.",
        "assets": {},
    },
}

_VALIDATION_MASK_SHARD_BYTES = {
    "0": 3746207, "1": 3671742, "2": 3507780, "3": 4122191,
    "4": 3459177, "5": 3549308, "6": 3503979, "7": 3473248,
    "8": 3853829, "9": 3849739, "a": 3360016, "b": 3530025,
    "c": 3619116, "d": 3402178, "e": 3721143, "f": 3193857,
}
for _shard_id, _shard_size in _VALIDATION_MASK_SHARD_BYTES.items():
    SOURCES["open_images"]["assets"][f"validation_mask_shard_{_shard_id}"] = {
        "url": f"https://storage.googleapis.com/openimages/v5/validation-masks/validation-masks-{_shard_id}.zip",
        "filename": f"validation-masks-{_shard_id}.zip",
        "destination": "public/open_images/original_annotations/mask_shards",
        "expected_size_bytes": _shard_size,
        "kind": "zip",
        "required_columns": [],
        "download_allowed": True,
        "purpose": f"Official Open Images validation binary instance masks, shard { _shard_id }.",
    }


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_layout() -> None:
    paths = [
        "public/contacthands", "public/open_images/metadata", "public/open_images/images",
        "public/open_images/annotations", "public/coco/annotations", "public/coco/images",
        "public/open_images/original_annotations", "public/open_images/converted_annotations",
        "public/open_images/masks/validation", "public/open_images/images/validation",
        "public/metmuseum/images", "public/metmuseum/metadata/objects",
        "public/other_sources", "synthetic/art_contact/images", "synthetic/art_contact/masks",
        "synthetic/art_contact/metadata", "custom/raw_videos", "custom/extracted_frames",
        "custom/annotated", "custom/prepared/images/train", "custom/prepared/images/val",
        "custom/prepared/images/test", "custom/prepared/labels/train",
        "custom/prepared/labels/val", "custom/prepared/labels/test", "custom/metadata",
        "custom/splits", "metadata", "splits", "reports",
    ]
    for relative in paths:
        (DATASET / relative).mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        write_json(MANIFEST, {"schema_version": 1, "downloads": []})


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_manifest() -> dict:
    if not MANIFEST.exists():
        return {"schema_version": 1, "downloads": []}
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read acquisition manifest {MANIFEST}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("downloads"), list):
        raise RuntimeError("Acquisition manifest has an invalid schema.")
    return data


def reconcile_download_history(manifest: dict) -> dict:
    """Mark repeated success rows and recovered failures without dropping audit history."""
    latest_validated = {}
    for index, record in enumerate(manifest["downloads"]):
        if record.get("status") == "validated" and record.get("path"):
            latest_validated[record["path"]] = (index, record)

    updated_rows = 0
    for relative_path, (latest_index, latest_record) in latest_validated.items():
        target = ROOT / relative_path
        try:
            if not target.resolve().is_relative_to(ROOT.resolve()) or not target.is_file():
                continue
            current_hash = sha256_file(target)
        except (OSError, ValueError):
            continue
        if current_hash != latest_record.get("sha256"):
            continue

        for index, record in enumerate(manifest["downloads"]):
            if record.get("path") != relative_path:
                continue
            if record.get("status") == "failed":
                record["status"] = "recovered"
                record["recovered_at_utc"] = now_utc()
                record["recovered_by_sha256"] = current_hash
                updated_rows += 1
            elif (
                record.get("status") == "validated"
                and index < latest_index
                and record.get("sha256") == current_hash
            ):
                record["status"] = "superseded_duplicate"
                record["superseded_at_utc"] = now_utc()
                record["superseded_by_downloaded_at_utc"] = latest_record.get("downloaded_at_utc")
                record["superseded_by_sha256"] = current_hash
                updated_rows += 1
    return {
        "superseded_duplicate_successes": sum(
            record.get("status") == "superseded_duplicate" for record in manifest["downloads"]
        ),
        "recovered_failures": sum(record.get("status") == "recovered" for record in manifest["downloads"]),
        "updated_rows_this_run": updated_rows,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def available_space_for(path: Path) -> int:
    directory = path
    while not directory.exists():
        directory = directory.parent
    return shutil.disk_usage(directory).free


def request(url: str, method: str = "GET", headers: dict[str, str] | None = None):
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS source URLs are accepted.")
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, method=method, headers=request_headers), timeout=45)


def remote_size(url: str) -> int | None:
    try:
        with request(url, method="HEAD") as response:
            if response.status != 200:
                raise RuntimeError(f"HEAD returned HTTP {response.status}")
            length = response.headers.get("Content-Length")
            return int(length) if length else None
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError):
        return None


def validate_csv(path: Path, required_columns: list[str]) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
        missing = sorted(set(required_columns) - set(headers))
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")
        count = sum(1 for row in reader if any(value for value in row.values()))
    return {"format_valid": True, "rows": count, "columns": headers}


def validate_archive(path: Path, kind: str) -> dict:
    if kind == "zip":
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"Corrupt ZIP member: {bad_member}")
            return {"format_valid": True, "members": len(archive.infolist())}
    if kind == "tar":
        with tarfile.open(path, "r:*") as archive:
            return {"format_valid": True, "members": len(archive.getmembers())}
    return {"format_valid": True}


def validate_json(path: Path, kind: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if kind != "vcoco-json":
        return {"format_valid": True, "root_type": type(data).__name__}
    if not isinstance(data, list) or not data:
        raise ValueError("V-COCO annotation root must be a non-empty list.")
    action_names = []
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("action_name"), str):
            raise ValueError("V-COCO entries must be objects with action_name.")
        action_names.append(entry["action_name"])
        for key in ("image_id", "ann_id", "role_object_id", "label", "role_name", "include"):
            if key not in entry:
                raise ValueError(f"V-COCO action {entry['action_name']!r} lacks {key}.")
        if not isinstance(entry["image_id"], list) or not isinstance(entry["label"], list) or len(entry["image_id"]) != len(entry["label"]):
            raise ValueError(f"V-COCO action {entry['action_name']!r} has inconsistent image_id/label arrays.")
    if len(set(action_names)) != len(action_names):
        raise ValueError("V-COCO action names must be unique.")
    return {"format_valid": True, "actions": len(action_names), "action_names": action_names}


def validate_asset(path: Path, asset: dict) -> dict:
    if asset["kind"] == "csv":
        return validate_csv(path, asset.get("required_columns", []))
    if asset["kind"] in {"zip", "tar"}:
        return validate_archive(path, asset["kind"])
    if asset["kind"] == "image":
        return _validate_downloaded_image(path)
    if asset["kind"] == "model-task":
        if path.stat().st_size < 1_000_000:
            raise ValueError("MediaPipe .task bundle is unexpectedly small.")
        with path.open("rb") as stream:
            header = stream.read(32).lstrip().lower()
        if header.startswith((b"<!doctype html", b"<html", b"{\"error\"")):
            raise ValueError("MediaPipe model URL returned text instead of a binary task bundle.")
        return {"format_valid": True, "bytes": path.stat().st_size, "runtime_validation": "MediaPipe task loader not invoked by acquisition validator"}
    if asset["kind"].endswith("json"):
        return validate_json(path, asset["kind"])
    return {"format_valid": True}


def download_asset(source_id: str, asset_id: str, retries: int = 3) -> dict:
    source = SOURCES.get(source_id)
    if not source or asset_id not in source["assets"]:
        raise ValueError(f"Unknown source asset: {source_id}/{asset_id}")
    asset = source["assets"][asset_id]
    if not asset["download_allowed"]:
        raise PermissionError(f"Downloads are disabled for {source_id}/{asset_id} pending source verification.")
    destination = DATASET / asset["destination"] / asset["filename"]
    return _download_registered_file(source_id, asset_id, asset, destination, retries=retries)


def _met_api_json(url: str) -> dict:
    if not url.startswith("https://collectionapi.metmuseum.org/public/collection/"):
        raise ValueError("Met API request must use the official HTTPS Collection API.")
    with request(url, headers={"Accept": "application/json"}) as response:
        if response.status != 200:
            raise RuntimeError(f"Met API returned HTTP {response.status} for {url}")
        payload = response.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("Met API response exceeded the 8 MiB response limit.")
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Met API returned a non-object JSON response.")
    return data


def download_met_artworks(limit: int = 10, max_bytes: int = 200_000_000) -> dict:
    """Acquire a bounded set of CC0 public-domain painting images from The Met API."""
    if not 1 <= limit <= 50:
        raise ValueError("Met artwork limit must be between 1 and 50.")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive.")
    ensure_layout()
    root = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
    query = urllib.parse.urlencode({
        "departmentId": 11,
        "hasImages": "true",
        "medium": "Paintings",
        "offset": 0,
        "limit": 100,
        "q": "painting",
    })
    search_url = f"{root}?{query}"
    search = _met_api_json(search_url)
    object_ids = search.get("objectIDs")
    if not isinstance(object_ids, list):
        raise ValueError("Met search response has no objectIDs list.")

    base_dir = DATASET / "public/metmuseum"
    manifest_path = base_dir / "metadata/met_artworks_manifest.json"
    current = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "dataset": "The Metropolitan Museum of Art Open Access API",
        "official_source_url": SOURCES["metmuseum"]["official_source_url"],
        "terms_url": SOURCES["metmuseum"]["terms_url"],
        "license": "CC0 1.0; only API records with isPublicDomain=true",
        "query_url": search_url,
        "objects": [],
    }
    known_ids = {int(item["object_id"]) for item in current["objects"]}
    total_bytes = sum(int(item.get("bytes", 0)) for item in current["objects"])
    candidates_checked = 0
    skipped = []

    for object_id in object_ids:
        if len(current["objects"]) >= limit:
            break
        object_id = int(object_id)
        if object_id in known_ids:
            continue
        candidates_checked += 1
        record_url = f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"
        record = _met_api_json(record_url)
        if record.get("isPublicDomain") is not True:
            skipped.append({"object_id": object_id, "reason": "not public domain"})
            continue
        if str(record.get("classification", "")).casefold() != "paintings":
            skipped.append({"object_id": object_id, "reason": "classification is not Paintings"})
            continue
        image_url = str(record.get("primaryImage") or "")
        if not image_url.startswith("https://images.metmuseum.org/"):
            skipped.append({"object_id": object_id, "reason": "no official HTTPS primary image"})
            continue
        image_size = remote_size(image_url)
        if image_size is None:
            skipped.append({"object_id": object_id, "reason": "image size could not be preflighted"})
            continue
        if total_bytes + image_size > max_bytes:
            skipped.append({"object_id": object_id, "reason": "configured total-byte budget reached", "bytes": image_size})
            break

        asset_id = f"artwork_{object_id}"
        asset = {
            "url": image_url,
            "filename": f"{object_id}.jpg",
            "destination": "public/metmuseum/images",
            "expected_size_bytes": image_size,
            "kind": "image",
            "required_columns": [],
            "download_allowed": True,
            "purpose": "CC0 public-domain artwork image for synthetic composition; not gallery-scene training data.",
        }
        SOURCES["metmuseum"]["assets"][asset_id] = asset
        file_record = _download_registered_file(
            "metmuseum",
            asset_id,
            asset,
            base_dir / "images" / asset["filename"],
            record_metadata={
                "image_id": object_id,
                "title": record.get("title", ""),
                "artist": record.get("artistDisplayName", ""),
                "object_url": record.get("objectURL", ""),
                "license": "CC0 1.0 (Open Access public-domain record)",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        object_metadata_path = base_dir / "metadata/objects" / f"{object_id}.json"
        if object_metadata_path.exists():
            saved_record = json.loads(object_metadata_path.read_text(encoding="utf-8"))
            if int(saved_record.get("objectID", -1)) != object_id:
                raise ValueError(f"Existing Met metadata does not match object ID {object_id}.")
        else:
            write_json(object_metadata_path, record)
        source_record = {
            "object_id": object_id,
            "title": record.get("title", ""),
            "artist": record.get("artistDisplayName", ""),
            "classification": record.get("classification", ""),
            "object_url": record.get("objectURL", ""),
            "api_record_url": record_url,
            "image_url": image_url,
            "metadata_path": object_metadata_path.relative_to(ROOT).as_posix(),
            "path": file_record["path"],
            "bytes": file_record["bytes"],
            "sha256": file_record["sha256"],
            "license": "CC0 1.0 (Open Access public-domain record)",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "credit_line": record.get("creditLine", ""),
        }
        current["objects"].append(source_record)
        known_ids.add(object_id)
        total_bytes += int(file_record["bytes"])
        record_provenance([{
            "path": file_record["path"],
            "source_url": image_url,
            "source_landing_url": record.get("objectURL", ""),
            "source_identifier": f"met-object-{object_id}",
            "license": "CC0 1.0 (Open Access public-domain record)",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "attribution": f"{record.get('artistDisplayName', '')} — {record.get('title', '')}; The Metropolitan Museum of Art, object {object_id}.",
            "sha256": file_record["sha256"],
            "bytes": file_record["bytes"],
        }])
        current.update({"generated_at_utc": now_utc(), "total_image_bytes": total_bytes})
        write_json(manifest_path, current)
        time.sleep(0.05)

    current.update({
        "generated_at_utc": now_utc(),
        "search_candidates": len(object_ids),
        "candidates_checked_this_run": candidates_checked,
        "total_image_bytes": total_bytes,
        "configured_limit": limit,
        "configured_max_bytes": max_bytes,
        "skipped_candidates_this_run": skipped,
    })
    write_json(manifest_path, current)
    return current


def _download_registered_file(
    source_id: str,
    asset_id: str,
    asset: dict,
    destination: Path,
    retries: int = 3,
    record_metadata: dict | None = None,
) -> dict:
    source = SOURCES[source_id]
    ensure_layout()
    if not destination.resolve().is_relative_to(DATASET.resolve()):
        raise ValueError("Catalog destination escapes dataset root.")
    manifest = read_manifest()
    previous = next((row for row in manifest["downloads"] if row.get("path") == destination.relative_to(ROOT).as_posix() and row.get("status") == "validated"), None)
    if destination.exists():
        existing_hash = sha256_file(destination)
        if previous and previous.get("sha256") == existing_hash:
            print(f"Already downloaded and validated; skipping: {destination.relative_to(ROOT).as_posix()}")
            return previous
        raise FileExistsError(f"Refusing to overwrite an existing untracked or changed file: {destination}")

    expected_size = asset.get("expected_size_bytes")
    observed_size = remote_size(asset["url"])
    if expected_size is not None and observed_size is not None and observed_size != expected_size:
        raise ValueError(f"Remote size changed: expected {expected_size} bytes, observed {observed_size} bytes.")
    planned_size = observed_size or expected_size
    free_space = available_space_for(destination.parent)
    if planned_size is None:
        raise RuntimeError("Cannot verify remote size before download; refusing unknown-size download.")
    max_size = asset.get("max_size_bytes")
    if max_size is not None and planned_size > int(max_size):
        raise ValueError(f"Remote file exceeds the configured {int(max_size)} byte maximum: {planned_size} bytes.")
    if planned_size + max(16 * 1024 * 1024, planned_size // 10) > free_space:
        raise OSError(f"Insufficient free space: need at least {planned_size} bytes plus safety margin; available {free_space} bytes.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    started = time.perf_counter()
    error_text = None

    def record_validated_download(actual_size: int, checksum: str, validation: dict, http_status: int) -> dict:
        for previous_record in manifest["downloads"]:
            if previous_record.get("path") == destination.relative_to(ROOT).as_posix() and previous_record.get("status") == "failed":
                previous_record["status"] = "recovered"
                previous_record["recovered_at_utc"] = now_utc()
        record = {
            "source_id": source_id,
            "dataset_name": source["name"],
            "asset_id": asset_id,
            "source_url": asset["url"],
            "official_source_url": source["official_source_url"],
            "license": source["license"],
            "attribution": source["attribution"],
            "downloaded_at_utc": now_utc(),
            "path": destination.relative_to(ROOT).as_posix(),
            "bytes": actual_size,
            "sha256": checksum,
            "http_status": http_status,
            "status": "validated",
            "validation": validation,
            "purpose": asset["purpose"],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        if record_metadata:
            record.update(record_metadata)
        manifest["downloads"].append(record)
        write_json(MANIFEST, manifest)
        relative_path = destination.relative_to(ROOT).as_posix()
        print(f"Downloaded and validated {relative_path} ({actual_size:,} bytes; sha256={checksum})")
        return record

    try:
        if partial.exists() and partial.stat().st_size == planned_size:
            try:
                validation = validate_asset(partial, asset)
                checksum = sha256_file(partial)
                partial.replace(destination)
                return record_validated_download(planned_size, checksum, validation, 206)
            except Exception:
                if destination.exists():
                    raise

        for attempt in range(1, retries + 1):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset >= planned_size:
                offset = 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            try:
                with request(asset["url"], headers=headers) as response:
                    if response.status not in (200, 206):
                        raise RuntimeError(f"Unexpected HTTP status {response.status}")
                    append = offset > 0 and response.status == 206
                    if offset > 0 and response.status == 200:
                        offset = 0
                    mode = "ab" if append else "wb"
                    with partial.open(mode) as output:
                        shutil.copyfileobj(response, output, length=1024 * 1024)
                actual_size = partial.stat().st_size
                if actual_size != planned_size:
                    raise IOError(f"Incomplete download: expected {planned_size} bytes, received {actual_size} bytes.")
                validation = validate_asset(partial, asset)
                checksum = sha256_file(partial)
                partial.replace(destination)
                return record_validated_download(actual_size, checksum, validation, response.status)
            except Exception as exc:
                error_text = f"attempt {attempt}/{retries}: {type(exc).__name__}: {exc}"
                if attempt == retries:
                    break
                time.sleep(min(attempt, 3))
        failure = {
            "source_id": source_id,
            "dataset_name": source["name"],
            "asset_id": asset_id,
            "source_url": asset["url"],
            "downloaded_at_utc": now_utc(),
            "path": destination.relative_to(ROOT).as_posix(),
            "status": "failed",
            "error": error_text,
            "partial_bytes": partial.stat().st_size if partial.exists() else 0,
        }
        manifest["downloads"].append(failure)
        write_json(MANIFEST, manifest)
        raise RuntimeError(f"Download failed safely; partial retained for resume. {error_text}")
    except Exception:
        raise


def normalized_name(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def image_class_inventory() -> dict | None:
    catalog_csv = DATASET / "public/open_images/metadata/oidv7-class-descriptions-boxable.csv"
    if not catalog_csv.exists():
        return None
    with catalog_csv.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    names = {normalized_name(row["DisplayName"]) for row in rows if row.get("DisplayName")}
    unique_class_names = len(names)
    candidates = {
        "painting": {"painting", "artwork", "painted artwork"},
        "person": {"person", "man", "woman", "boy", "girl"},
        "hand": {"hand", "human hand"},
        "tool": {"tool", "pen", "pencil", "paintbrush", "brush", "marker", "scissors", "cell phone", "mobile phone"},
    }
    return {
        "inventory_file": catalog_csv.relative_to(ROOT).as_posix(),
        "row_count": len(rows),
        "unique_class_names": unique_class_names,
        "official_facts_page_box_class_count": 600,
        "count_discrepancy": unique_class_names != 600,
        "target_name_matches": {key: sorted(names & values) for key, values in candidates.items()},
        "related_artwork_names_not_painting_labels": sorted(names & {"picture frame"}),
        "segmentation_class_inventory_verified": False,
        "scope": "Boxable class vocabulary only; not proof of samples or segmentation-mask availability. A picture-frame label is not a painting label. Raw CSV count differs from the official facts-page headline and has not been normalized.",
    }


def vcoco_action_inventory() -> dict | None:
    annotation_path = DATASET / "public/other_sources/vcoco/annotations/vcoco_train.json"
    if not annotation_path.is_file():
        return None
    entries = json.loads(annotation_path.read_text(encoding="utf-8"))
    validation = validate_json(annotation_path, "vcoco-json")
    image_ids = {image_id for entry in entries for image_id in entry["image_id"]}
    return {
        "annotation_file": annotation_path.relative_to(ROOT).as_posix(),
        "action_count": validation["actions"],
        "action_names": validation["action_names"],
        "unique_coco_image_ids": len(image_ids),
        "has_instance_masks": False,
        "painting_or_harmful_contact_labels": False,
    }


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames or [], list(reader)


def open_images_class_capabilities(box_names: set[str], mask_names: set[str]) -> dict:
    capabilities = {}
    source_aliases = {
        "painting": ["Painting"],
        "person": ["Person"],
        "hand": ["Human hand", "Hand"],
        "tool": ["Tool", "Mobile phone", "Pen", "Pencil"],
    }
    for target, aliases in source_aliases.items():
        box = sorted(name for name in aliases if name.casefold() in box_names)
        masks = sorted(name for name in aliases if name.casefold() in mask_names)
        capabilities[target] = {
            "source_aliases_checked": aliases,
            "box_classes_available": box,
            "mask_classes_available": masks,
            "box_annotation_available": bool(box),
            "instance_mask_annotation_available": bool(masks),
            "annotation_status": "instance masks and boxes" if masks and box else "boxes only" if box else "no exact usable source class",
        }
    capabilities["picture_frame_not_painting"] = {
        "box_available": "picture frame" in box_names,
        "mask_available": "picture frame" in mask_names,
        "mapped_to_painting": False,
    }
    return capabilities


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _pilot_image_order(class_name: str, image_ids: set[str]) -> list[str]:
    return sorted(image_ids, key=lambda image_id: hashlib.sha256(f"pbl4-oi-v7-{class_name}-{image_id}".encode()).hexdigest())


def _select_open_images_ids(
    mask_rows: list[dict[str, str]],
    box_rows: list[dict[str, str]],
    names_by_mid: dict[str, str],
    eligible_image_ids: set[str],
    limit: int,
) -> tuple[list[str], dict[str, str]]:
    mask_images_by_class: dict[str, set[str]] = defaultdict(set)
    for row in mask_rows:
        class_name = names_by_mid.get(row["LabelName"], "")
        if class_name in {"Person", "Mobile phone", "Pen"} and row["ImageID"] in eligible_image_ids:
            mask_images_by_class[class_name].add(row["ImageID"])

    quotas = {"Person": int(limit * 0.50), "Mobile phone": int(limit * 0.25), "Pen": int(limit * 0.15)}
    selected: dict[str, str] = {}
    for class_name, quota in quotas.items():
        already_covered = sum(
            1 for image_id in selected if image_id in mask_images_by_class[class_name]
        )
        for image_id in _pilot_image_order(class_name, mask_images_by_class[class_name]):
            if already_covered >= quota or len(selected) >= limit:
                break
            if image_id not in selected:
                selected[image_id] = f"mask:{class_name}"
                already_covered += 1

    hand_mid = next((mid for mid, name in names_by_mid.items() if name.casefold() == "human hand"), None)
    hand_box_images = {
        row["ImageID"] for row in box_rows
        if hand_mid and row["LabelName"] == hand_mid and row["ImageID"] in eligible_image_ids
    }
    hand_quota = min(limit - len(selected), max(1, limit // 10))
    added_hand = 0
    for image_id in _pilot_image_order("Human hand boxes only", hand_box_images):
        if len(selected) >= limit or added_hand >= hand_quota:
            break
        if image_id not in selected:
            selected[image_id] = "box-only:Human hand"
            added_hand += 1

    all_target_mask_images = set().union(*mask_images_by_class.values()) if mask_images_by_class else set()
    for image_id in _pilot_image_order("target mask fill", all_target_mask_images & eligible_image_ids):
        if len(selected) >= limit:
            break
        selected.setdefault(image_id, "mask:target-class-fill")

    if len(selected) < limit:
        raise RuntimeError(
            f"Only {len(selected)} eligible unique validation images were annotated for Person/Mobile phone/Pen "
            f"and available Human hand boxes; requested {limit}. No unrelated classes will be substituted."
        )
    return list(selected), selected


def _is_valid_open_images_license(row: dict[str, str]) -> bool:
    return (
        row.get("Subset", "").casefold() == "validation"
        and row.get("License") == "https://creativecommons.org/licenses/by/2.0/"
        and row.get("OriginalLandingURL", "").startswith("https://")
        and row.get("OriginalURL", "").startswith("https://")
    )


def _validate_downloaded_image(path: Path) -> dict:
    import cv2
    import numpy as np

    image_bytes = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"Downloaded image is not a decodable image: {path}")
    return {"valid": True, "width": int(image.shape[1]), "height": int(image.shape[0]), "channels": int(image.shape[2])}


def _validate_binary_mask(path: Path) -> dict:
    import cv2
    import numpy as np

    mask_bytes = np.fromfile(path, dtype=np.uint8)
    mask = cv2.imdecode(mask_bytes, cv2.IMREAD_UNCHANGED)
    if mask is None or mask.size == 0 or mask.ndim != 2:
        raise ValueError(f"Source instance mask is not a valid single-channel PNG: {path}")
    values = np.unique(mask)
    if len(values) < 2 or not np.any(mask != 0):
        raise ValueError(f"Source instance mask is empty or malformed: {path}")
    return {"valid": True, "width": int(mask.shape[1]), "height": int(mask.shape[0]), "pixel_values": values.tolist()}


def _align_binary_mask_to_image(
    source_mask_path: Path,
    image_path: Path,
    destination: Path,
    rotation: str,
) -> dict:
    import cv2
    import numpy as np

    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    mask = cv2.imdecode(np.fromfile(source_mask_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or mask is None or mask.ndim != 2:
        raise ValueError("Cannot decode source image or single-channel source mask.")
    if rotation.strip() not in {"", "0", "0.0", "0.00"}:
        raise ValueError(f"Non-zero source image rotation is not supported for mask alignment: {rotation}")
    image_height, image_width = image.shape[:2]
    mask_height, mask_width = mask.shape[:2]
    aspect_delta = abs((image_width / image_height) - (mask_width / mask_height))
    if aspect_delta > 0.01:
        raise ValueError(f"Source mask/image aspect ratio differs by {aspect_delta:.5f}; refusing spatial alignment.")
    if mask.shape != (image_height, image_width):
        mask = cv2.resize(mask, (image_width, image_height), interpolation=cv2.INTER_NEAREST)
    if not np.any(mask != 0):
        raise ValueError("Aligned source mask is empty.")
    success, encoded = cv2.imencode(".png", mask)
    if not success:
        raise IOError("Could not encode aligned PNG mask.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        current = cv2.imdecode(np.fromfile(destination, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if current is None or not np.array_equal(current, mask):
            raise FileExistsError(f"Refusing to overwrite a different aligned mask: {destination}")
    else:
        with destination.open("xb") as file:
            file.write(encoded.tobytes())
    return {
        "valid": True,
        "width": image_width,
        "height": image_height,
        "source_width": mask_width,
        "source_height": mask_height,
        "resized_nearest_neighbor": (mask_width, mask_height) != (image_width, image_height),
        "max_aspect_ratio_delta": aspect_delta,
        "rotation": rotation,
    }


def _box_geometry_key(row: dict[str, str], prefix: str = "") -> tuple[float, float, float, float]:
    fields = (f"{prefix}XMin", f"{prefix}XMax", f"{prefix}YMin", f"{prefix}YMax")
    return tuple(round(float(row[field]), 6) for field in fields)


def run_open_images_pilot(
    limit: int = 100,
    max_bytes: int = 1_000_000_000,
    preflight_only: bool = False,
) -> dict:
    if not 100 <= limit <= 300:
        raise ValueError("The Open Images pilot limit must be between 100 and 300 images.")
    if max_bytes <= 0 or max_bytes > 1_000_000_000:
        raise ValueError("--max-bytes must be positive and no greater than 1,000,000,000 bytes.")

    ensure_layout()
    source_id = "open_images"
    metadata_assets = (
        "segmentation_classes", "class_descriptions", "validation_segmentation_annotations",
        "validation_bbox_annotations", "validation_image_info",
    )
    for asset_id in metadata_assets:
        download_asset(source_id, asset_id)

    open_images_root = DATASET / "public/open_images"
    segmentation_classes_path = open_images_root / "metadata/oidv7-classes-segmentation.txt"
    descriptions_path = open_images_root / "metadata/oidv7-class-descriptions.csv"
    mask_annotations_path = open_images_root / "original_annotations/validation-annotations-object-segmentation.csv"
    bbox_annotations_path = open_images_root / "original_annotations/validation-annotations-bbox.csv"
    image_info_path = open_images_root / "metadata/validation-images-with-rotation.csv"
    segmentation_mids = set(segmentation_classes_path.read_text(encoding="utf-8").split())
    _, description_rows = _csv_rows(descriptions_path)
    names_by_mid = {row["LabelName"]: row["DisplayName"] for row in description_rows}
    boxable_path = open_images_root / "metadata/oidv7-class-descriptions-boxable.csv"
    _, boxable_rows = _csv_rows(boxable_path)
    box_class_names = {normalized_name(row["DisplayName"]) for row in boxable_rows}
    mask_class_names = {normalized_name(names_by_mid[mid]) for mid in segmentation_mids if mid in names_by_mid}
    capabilities = open_images_class_capabilities(box_class_names, mask_class_names)

    mask_fieldnames, mask_rows = _csv_rows(mask_annotations_path)
    bbox_fieldnames, bbox_rows = _csv_rows(bbox_annotations_path)
    _, image_info_rows = _csv_rows(image_info_path)
    image_info_by_id = {row["ImageID"]: row for row in image_info_rows}
    all_candidate_ids = {
        row["ImageID"] for row in mask_rows
        if names_by_mid.get(row["LabelName"]) in {"Person", "Mobile phone", "Pen"}
    }
    hand_mid = next((mid for mid, name in names_by_mid.items() if name.casefold() == "human hand"), None)
    hand_box_ids = {row["ImageID"] for row in bbox_rows if hand_mid and row["LabelName"] == hand_mid}
    considered_ids = all_candidate_ids | hand_box_ids
    license_skips = {
        image_id: "missing or non-CC-BY-2.0 image license/HTTPS source metadata"
        for image_id in considered_ids
        if image_id not in image_info_by_id or not _is_valid_open_images_license(image_info_by_id[image_id])
    }
    eligible_ids = considered_ids - set(license_skips)
    selected_ids, selection_reasons = _select_open_images_ids(
        mask_rows, bbox_rows, names_by_mid, eligible_ids, limit
    )
    selected_set = set(selected_ids)
    selected_info = [image_info_by_id[image_id] for image_id in selected_ids]
    selected_masks = [row for row in mask_rows if row["ImageID"] in selected_set]
    selected_boxes = [row for row in bbox_rows if row["ImageID"] in selected_set]

    needed_shards = sorted({row["ImageID"][0].lower() for row in selected_masks})
    image_sizes = {}
    preflight_failures = []
    image_urls = {}
    for info in selected_info:
        image_id = info["ImageID"]
        url = f"https://open-images-dataset.s3.amazonaws.com/validation/{image_id}.jpg"
        size = remote_size(url)
        if size is None:
            preflight_failures.append(image_id)
        else:
            image_urls[image_id] = url
            image_sizes[image_id] = size
    if preflight_failures:
        raise RuntimeError(f"Official image URL preflight failed for {len(preflight_failures)} selected IDs; no pilot images downloaded.")

    mask_shard_sizes = {}
    for shard_id in needed_shards:
        asset = SOURCES[source_id]["assets"][f"validation_mask_shard_{shard_id}"]
        observed = remote_size(asset["url"])
        if observed is None or observed != asset["expected_size_bytes"]:
            raise RuntimeError(f"Mask shard {shard_id} did not pass the expected-size HTTPS preflight.")
        mask_shard_sizes[shard_id] = observed

    planned_metadata_bytes = sum(SOURCES[source_id]["assets"][asset_id]["expected_size_bytes"] for asset_id in metadata_assets)
    planned_mask_bytes = sum(mask_shard_sizes.values())
    planned_compressed_bytes = planned_metadata_bytes + planned_mask_bytes + sum(image_sizes.values())
    free_bytes = available_space_for(DATASET)
    if planned_compressed_bytes >= max_bytes:
        raise OSError(f"Planned Open Images pilot is {planned_compressed_bytes:,} bytes and must be below --max-bytes={max_bytes:,}.")
    if planned_compressed_bytes + max(16 * 1024 * 1024, planned_compressed_bytes // 10) > free_bytes:
        raise OSError(f"Insufficient disk space for pilot: need at least {planned_compressed_bytes:,} bytes plus safety margin; available {free_bytes:,} bytes.")

    image_list_path = open_images_root / "metadata/validation-image-list.txt"
    image_list_text = "".join(f"validation/{image_id}\n" for image_id in selected_ids)
    if image_list_path.exists() and image_list_path.read_text(encoding="utf-8") != image_list_text:
        raise FileExistsError(f"Refusing to overwrite a different official image list: {image_list_path}")
    if not image_list_path.exists():
        image_list_path.write_text(image_list_text, encoding="utf-8")

    if preflight_only:
        return {
            "preflight_only": True,
            "requested_images": limit,
            "selected_image_ids": selected_ids,
            "selected_mask_class_images": {name: len(ids & selected_set) for name, ids in {
                class_name: {row["ImageID"] for row in mask_rows if names_by_mid.get(row["LabelName"]) == class_name}
                for class_name in ("Person", "Mobile phone", "Pen")
            }.items()},
            "mask_shards": needed_shards,
            "planned_compressed_bytes_including_metadata_masks_and_images": planned_compressed_bytes,
            "max_bytes": max_bytes,
            "available_disk_bytes": free_bytes,
            "license_eligible_images": len(eligible_ids),
            "skipped_unverified_or_ineligible_license_candidates": len(license_skips),
        }

    shard_records = {}
    for shard_id in needed_shards:
        shard_records[shard_id] = download_asset(source_id, f"validation_mask_shard_{shard_id}")

    expanded_mask_bytes = 0
    for shard_id in needed_shards:
        archive_path = ROOT / shard_records[shard_id]["path"]
        wanted = {row["MaskPath"] for row in selected_masks if row["ImageID"].startswith(shard_id)}
        with zipfile.ZipFile(archive_path) as archive:
            infos = {info.filename: info for info in archive.infolist()}
            missing = sorted(wanted - set(infos))
            if missing:
                raise ValueError(f"Official mask shard {shard_id} lacks {len(missing)} selected mask entries.")
            expanded_mask_bytes += sum(infos[mask_path].file_size for mask_path in wanted)
    planned_bytes = planned_compressed_bytes + expanded_mask_bytes
    free_bytes = available_space_for(DATASET)
    if planned_bytes >= max_bytes:
        raise OSError(f"Pilot plus extracted source masks would use {planned_bytes:,} bytes and must be below --max-bytes={max_bytes:,}.")
    if planned_bytes + max(16 * 1024 * 1024, planned_bytes // 10) > free_bytes:
        raise OSError(f"Insufficient disk space for pilot and extracted masks: need {planned_bytes:,} bytes plus safety margin; available {free_bytes:,} bytes.")

    downloaded_images = []
    invalid_images = []
    failed_images = []
    image_paths = {}
    image_shapes = {}
    for info in selected_info:
        image_id = info["ImageID"]
        relative_path = f"dataset/public/open_images/images/validation/{image_id}.jpg"
        destination = ROOT / relative_path
        asset = {
            "url": image_urls[image_id], "filename": f"{image_id}.jpg",
            "destination": "public/open_images/images/validation",
            "expected_size_bytes": image_sizes[image_id], "kind": "image", "required_columns": [],
            "download_allowed": True, "purpose": "Official Open Images CVDF/S3 validation image selected via its source segmentation/bbox annotations.",
        }
        try:
            record = _download_registered_file(
                source_id,
                f"image_validation_{image_id}",
                asset,
                destination,
                record_metadata={
                    "image_id": image_id,
                    "source_split": "validation",
                    "original_url": info["OriginalURL"],
                    "source_landing_url": info["OriginalLandingURL"],
                    "image_license_url": info["License"],
                    "image_license": "CC BY 2.0",
                    "author": info.get("Author", ""),
                    "author_profile_url": info.get("AuthorProfileURL", ""),
                    "title": info.get("Title", ""),
                    "flickr_original_size_bytes": info.get("OriginalSize", ""),
                    "flickr_original_md5_base64": info.get("OriginalMD5", ""),
                    "selection_reason": selection_reasons[image_id],
                },
            )
            validation = _validate_downloaded_image(destination)
            record["validation"].update(validation)
            manifest = read_manifest()
            for entry in reversed(manifest["downloads"]):
                if entry.get("path") == relative_path and entry.get("status") == "validated":
                    entry["validation"].update(validation)
                    break
            write_json(MANIFEST, manifest)
            image_paths[image_id] = destination
            image_shapes[image_id] = (validation["height"], validation["width"])
            downloaded_images.append(image_id)
        except Exception as exc:
            failed_images.append({"image_id": image_id, "error": f"{type(exc).__name__}: {exc}"})
            if destination.is_file():
                invalid_images.append({"image_id": image_id, "path": relative_path, "reason": str(exc)})
                manifest = read_manifest()
                for entry in reversed(manifest["downloads"]):
                    if entry.get("path") == relative_path:
                        entry["status"] = "invalid"
                        entry["validation_error"] = str(exc)
                        break
                write_json(MANIFEST, manifest)

    valid_id_set = set(image_paths)
    usable_mask_rows = [row for row in selected_masks if row["ImageID"] in valid_id_set]
    required_mask_paths = {row["MaskPath"] for row in usable_mask_rows}
    extracted_masks = []
    failed_masks = []
    for shard_id in needed_shards:
        shard_record = shard_records[shard_id]
        archive_path = ROOT / shard_record["path"]
        wanted = {
            row["MaskPath"] for row in usable_mask_rows
            if row["ImageID"].startswith(shard_id)
        }
        if not wanted:
            continue
        with zipfile.ZipFile(archive_path) as archive:
            members = set(archive.namelist())
            for mask_name in sorted(wanted):
                if mask_name not in members:
                    failed_masks.append({"mask_path": mask_name, "reason": "not present in official shard"})
                    continue
                destination = open_images_root / "masks/validation" / Path(mask_name).name
                if destination.exists():
                    if _validate_binary_mask(destination)["valid"]:
                        extracted_masks.append(destination)
                        continue
                    failed_masks.append({"mask_path": mask_name, "reason": "existing mask is invalid; refusing overwrite"})
                    continue
                with archive.open(mask_name) as source_file, destination.open("xb") as output:
                    shutil.copyfileobj(source_file, output)
                try:
                    _validate_binary_mask(destination)
                    extracted_masks.append(destination)
                except Exception as exc:
                    failed_masks.append({"mask_path": mask_name, "reason": str(exc)})

    pilot_annotations_dir = open_images_root / "original_annotations"
    _write_csv(pilot_annotations_dir / "pilot-validation-segmentation-selected.csv", mask_fieldnames, [row for row in selected_masks if row["ImageID"] in valid_id_set])
    _write_csv(pilot_annotations_dir / "pilot-validation-bbox-selected.csv", bbox_fieldnames, [row for row in selected_boxes if row["ImageID"] in valid_id_set])

    mask_rows_by_image_class = {
        (row["ImageID"], names_by_mid.get(row["LabelName"], ""), _box_geometry_key(row, "Box"))
        for row in usable_mask_rows
    }
    target_box_names = {"Person", "Human hand", "Tool", "Mobile phone", "Pen", "Pencil"}
    target_box_mids = {mid for mid, name in names_by_mid.items() if name in target_box_names}
    target_bbox_rows = [row for row in selected_boxes if row["LabelName"] in target_box_mids and row["ImageID"] in valid_id_set]
    bbox_only_instances: Counter[str] = Counter()
    bbox_only_image_classes: set[tuple[str, str]] = set()
    for row in target_bbox_rows:
        source_class = names_by_mid.get(row["LabelName"], "")
        key = (row["ImageID"], source_class, _box_geometry_key(row))
        if key not in mask_rows_by_image_class:
            bbox_only_instances[source_class] += 1
            bbox_only_image_classes.add((row["ImageID"], source_class))

    valid_mask_paths = {path.name for path in extracted_masks}
    source_valid_masks = [row for row in usable_mask_rows if row["MaskPath"] in valid_mask_paths]
    info_by_image_id = {row["ImageID"]: row for row in selected_info}
    aligned_masks = []
    mask_alignment_failures = []
    aligned_mask_provenance = []
    for row in source_valid_masks:
        image_id = row["ImageID"]
        source_mask_path = open_images_root / "masks/validation" / Path(row["MaskPath"]).name
        aligned_path = open_images_root / "converted_annotations/masks/validation" / Path(row["MaskPath"]).name
        image_path = image_paths[image_id]
        image_info = info_by_image_id[image_id]
        try:
            alignment = _align_binary_mask_to_image(source_mask_path, image_path, aligned_path, image_info.get("Rotation", ""))
            if (alignment["height"], alignment["width"]) != image_shapes[image_id]:
                raise ValueError("Aligned mask dimensions do not match the downloaded image.")
            aligned_masks.append({"row": row, "path": aligned_path, "alignment": alignment})
            aligned_mask_provenance.append({
                "path": aligned_path.relative_to(ROOT).as_posix(),
                "source_url": f"https://storage.googleapis.com/openimages/v5/validation-masks/validation-masks-{image_id[0].lower()}.zip",
                "source_image_id": image_id,
                "source_mask_path": row["MaskPath"],
                "source_annotation_csv": "validation-annotations-object-segmentation.csv",
                "source_class_mid": row["LabelName"],
                "source_class_name": names_by_mid.get(row["LabelName"], ""),
                "source_mask_license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_mask_license": "CC BY 4.0 (Open Images annotations); nearest-neighbor raster aligned, not polygonized",
                "underlying_image_license_url": image_info["License"],
                "underlying_image_landing_url": image_info["OriginalLandingURL"],
                "author": image_info.get("Author", ""),
                "derived_from": source_mask_path.relative_to(ROOT).as_posix(),
                "resizing": alignment,
                "sha256": sha256_file(aligned_path),
                "bytes": aligned_path.stat().st_size,
            })
        except Exception as exc:
            mask_alignment_failures.append({"mask_path": row["MaskPath"], "reason": str(exc)})
    valid_pilot_masks = [entry["row"] for entry in aligned_masks]
    mask_instances_by_class = Counter(names_by_mid.get(row["LabelName"], row["LabelName"]) for row in valid_pilot_masks)
    mask_images_by_class: dict[str, set[str]] = defaultdict(set)
    for row in valid_pilot_masks:
        mask_images_by_class[names_by_mid.get(row["LabelName"], row["LabelName"])].add(row["ImageID"])
    images_with_any_mask = {row["ImageID"] for row in valid_pilot_masks}
    images_with_any_box = {row["ImageID"] for row in selected_boxes if row["ImageID"] in valid_id_set}

    provenance_rows = []
    per_image_manifest = []
    for info in selected_info:
        image_id = info["ImageID"]
        image_path = image_paths.get(image_id)
        if not image_path:
            continue
        image_masks = [row for row in valid_pilot_masks if row["ImageID"] == image_id]
        provenance = {
            "path": image_path.relative_to(ROOT).as_posix(),
            "source_url": image_urls[image_id],
            "source_image_id": image_id,
            "source_split": "validation",
            "original_url": info["OriginalURL"],
            "source_landing_url": info["OriginalLandingURL"],
            "license_url": info["License"],
            "license": "CC BY 2.0",
            "author": info.get("Author", ""),
            "author_profile_url": info.get("AuthorProfileURL", ""),
            "attribution": f"{info.get('Author') or 'Author not listed'} / Open Images V7 image {image_id}; CC BY 2.0",
            "sha256": sha256_file(image_path),
            "bytes": image_path.stat().st_size,
            "source_annotation_csv": "validation-annotations-object-segmentation.csv",
            "mask_paths": [row["MaskPath"] for row in image_masks],
        }
        provenance_rows.append(provenance)
        per_image_manifest.append(provenance)
    mask_provenance_rows = []
    for mask_row in valid_pilot_masks:
        mask_path = open_images_root / "masks/validation" / Path(mask_row["MaskPath"]).name
        image_info = info_by_image_id[mask_row["ImageID"]]
        mask_provenance_rows.append({
            "path": mask_path.relative_to(ROOT).as_posix(),
            "source_url": f"https://storage.googleapis.com/openimages/v5/validation-masks/validation-masks-{mask_row['ImageID'][0].lower()}.zip",
            "source_image_id": mask_row["ImageID"],
            "source_mask_path": mask_row["MaskPath"],
            "source_annotation_csv": "validation-annotations-object-segmentation.csv",
            "source_class_mid": mask_row["LabelName"],
            "source_class_name": names_by_mid.get(mask_row["LabelName"], ""),
            "source_box_id": mask_row["BoxID"],
            "source_mask_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_mask_license": "CC BY 4.0 (Open Images annotations)",
            "underlying_image_license_url": image_info["License"],
            "underlying_image_landing_url": image_info["OriginalLandingURL"],
            "author": image_info.get("Author", ""),
            "attribution": f"Google LLC / Open Images annotations for image {mask_row['ImageID']}; CC BY 4.0",
            "sha256": sha256_file(mask_path),
            "bytes": mask_path.stat().st_size,
        })
    record_provenance(provenance_rows + mask_provenance_rows + aligned_mask_provenance)
    write_json(open_images_root / "metadata/open_images_pilot_manifest.json", {"images": per_image_manifest})

    image_list_by_split = Counter("validation" for _ in downloaded_images)
    image_disk_bytes = sum(path.stat().st_size for path in image_paths.values())
    public_sample_inventory = []
    sample_type_counts: Counter[str] = Counter()
    for image_id in downloaded_images:
        image_mask_rows = [row for row in valid_pilot_masks if row["ImageID"] == image_id]
        image_box_rows = [row for row in selected_boxes if row["ImageID"] == image_id]
        mask_keys = {
            (row["LabelName"], _box_geometry_key(row, "Box"))
            for row in image_mask_rows
        }
        bbox_only_classes = sorted({
            names_by_mid.get(row["LabelName"], row["LabelName"])
            for row in image_box_rows
            if (row["LabelName"], _box_geometry_key(row)) not in mask_keys
        })
        annotation_types = []
        if image_mask_rows:
            annotation_types.append("instance_segmentation_available")
        if image_box_rows:
            annotation_types.append("bounding_boxes_available")
        if not image_mask_rows and image_box_rows:
            classification = "bbox_only"
        elif image_mask_rows:
            classification = "segmentation_available"
        else:
            classification = "unsuitable_no_location_annotations"
        sample_type_counts[classification] += 1
        public_sample_inventory.append({
            "image_id": image_id,
            "source_split": "validation",
            "annotation_types": annotation_types,
            "classification": classification,
            "instance_mask_classes": sorted({names_by_mid.get(row["LabelName"], row["LabelName"]) for row in image_mask_rows}),
            "bbox_only_classes": bbox_only_classes,
            "image_level_labels": "not_downloaded",
            "suitable_for_full_artwork_protection_task": False,
            "unsuitable_reason": "No Painting/hand mask or verified SAFE/NEAR/CONTACT artwork-event labels; picture_frame remains its own source class.",
        })
    pilot_report = {
        "generated_at_utc": now_utc(),
        "official_dataset_split": "validation",
        "image_list_file": image_list_path.relative_to(ROOT).as_posix(),
        "requested_images": limit,
        "actual_images_downloaded": len(downloaded_images),
        "valid_images": len(downloaded_images),
        "invalid_images": invalid_images,
        "failed_image_downloads": failed_images,
        "license_skips_considered_candidates": len(license_skips),
        "preflight_failed_image_ids": preflight_failures,
        "valid_segmentation_masks_by_source_class": dict(mask_instances_by_class),
        "images_with_masks_by_source_class": {name: len(ids) for name, ids in sorted(mask_images_by_class.items())},
        "bounding_box_only_instances_by_source_class": dict(bbox_only_instances),
        "images_with_bbox_only_target_class_annotations": len({image_id for image_id, _ in bbox_only_image_classes}),
        "images_with_any_instance_mask": len(images_with_any_mask),
        "images_without_any_instance_mask": len(valid_id_set - images_with_any_mask),
        "images_with_boxes_but_no_instance_mask": len((images_with_any_box & valid_id_set) - images_with_any_mask),
        "source_target_capabilities": capabilities,
        "target_mapping": {"person": ["Person"], "tool": ["Pen", "Mobile phone"], "hand": ["Human hand"], "painting": ["Painting"]},
        "picture_frame_mapped_to_painting": False,
        "masks_failed_or_invalid": failed_masks,
        "mask_alignment_failures": mask_alignment_failures,
        "downloaded_source_mask_files": len(extracted_masks),
        "valid_image_aligned_mask_files": len(aligned_masks),
        "downloaded_mask_files": len(aligned_masks),
        "resampled_mask_count": sum(entry["alignment"]["resized_nearest_neighbor"] for entry in aligned_masks),
        "mask_shards_downloaded": needed_shards,
        "source_split_image_counts": {"train": 0, "validation": len(downloaded_images), "test": 0},
        "source_image_ids": downloaded_images,
        "public_sample_annotation_type_counts": dict(sample_type_counts),
        "public_sample_annotation_types": public_sample_inventory,
        "annotation_files": [
            "dataset/public/open_images/original_annotations/validation-annotations-object-segmentation.csv",
            "dataset/public/open_images/original_annotations/validation-annotations-bbox.csv",
            "dataset/public/open_images/original_annotations/pilot-validation-segmentation-selected.csv",
            "dataset/public/open_images/original_annotations/pilot-validation-bbox-selected.csv",
        ],
        "image_disk_bytes": image_disk_bytes,
        "pilot_bytes_including_metadata_and_mask_shards": planned_bytes,
        "selected_uncompressed_mask_bytes": expanded_mask_bytes,
        "disk_bytes_after_pilot": sum(path.stat().st_size for path in DATASET.rglob("*") if path.is_file()),
        "license": "Selected image metadata must explicitly list CC BY 2.0. Preserve original URL, landing URL, author when available, and license URL for each downloaded image. Open Images disclaims warranties; users remain responsible for source-image rights.",
        "conversion": {"yolo_polygons_created": 0, "image_aligned_masks": "Nearest-neighbor raster resize only, only for same-aspect ratio pairs with zero/unspecified rotation; source PNGs remain unchanged.", "reason": "No contour approximation or bounding-box-to-polygon conversion was made."},
        "training_ready": False,
        "training_readiness_reason": "Not ready: validation-only subset; no painting or hand instance masks; source annotations are not exhaustively complete for every instance; no independent train/test sample; no artwork harmful-contact labels. Tool masks are limited to source classes Pen and Mobile phone under the documented target mapping.",
    }
    pilot_report_path = open_images_root / "reports/open_images_pilot_report.json"
    write_json(pilot_report_path, pilot_report)
    return pilot_report


def validate_yolo_labels() -> dict:
    result = {"images": 0, "valid_segmentation_rows": 0, "box_only_rows": 0, "malformed_rows": 0, "class_counts": {}, "missing_labels": 0}
    result["invalid_images"] = 0
    result["orphan_labels"] = 0
    class_counts: Counter[int] = Counter()
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for split in ("train", "val", "test"):
        image_dir = DATASET / f"custom/prepared/images/{split}"
        label_dir = DATASET / f"custom/prepared/labels/{split}"
        for image_path in image_dir.rglob("*") if image_dir.exists() else []:
            if not image_path.is_file() or image_path.suffix.lower() not in image_extensions:
                continue
            result["images"] += 1
            try:
                _validate_downloaded_image(image_path)
            except (OSError, ValueError):
                result["invalid_images"] += 1
            label_path = label_dir / image_path.relative_to(image_dir).with_suffix(".txt")
            if not label_path.exists():
                result["missing_labels"] += 1
        for label_path in label_dir.rglob("*.txt") if label_dir.exists() else []:
            expected_image = image_dir / label_path.relative_to(label_dir)
            if not any(expected_image.with_suffix(extension).is_file() for extension in image_extensions):
                result["orphan_labels"] += 1
            for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
                parts = line.split()
                try:
                    class_id = int(parts[0])
                    coords = [float(value) for value in parts[1:]]
                    if class_id not in range(4) or not coords or any(not 0 <= value <= 1 for value in coords):
                        raise ValueError("class/coordinate outside supported range")
                    if (
                        len(coords) == 4
                        and coords[2] > 0
                        and coords[3] > 0
                        and coords[0] - coords[2] / 2 >= 0
                        and coords[0] + coords[2] / 2 <= 1
                        and coords[1] - coords[3] / 2 >= 0
                        and coords[1] + coords[3] / 2 <= 1
                    ):
                        result["box_only_rows"] += 1
                    elif len(coords) >= 6 and len(coords) % 2 == 0:
                        points = list(zip(coords[::2], coords[1::2]))
                        area = abs(sum(
                            points[index][0] * points[(index + 1) % len(points)][1]
                            - points[(index + 1) % len(points)][0] * points[index][1]
                            for index in range(len(points))
                        )) / 2
                        if len(set(points)) < 3 or area <= 0:
                            raise ValueError("polygon must have at least three unique, non-collinear points")
                        result["valid_segmentation_rows"] += 1
                    else:
                        raise ValueError("not a YOLO box or polygon row")
                    class_counts[class_id] += 1
                except (ValueError, IndexError):
                    result["malformed_rows"] += 1
                    print(f"Malformed label row: {label_path.relative_to(ROOT)}:{line_number}", file=sys.stderr)
    result["class_counts"] = {TARGET_CLASSES[str(class_id)]: count for class_id, count in sorted(class_counts.items())}
    return result


def check_split_leakage() -> dict:
    split_file = DATASET / "splits/sources.json"
    if not split_file.exists():
        return {"checked": False, "leaks": [], "reason": "No source-level split assignments recorded."}
    assignments = json.loads(split_file.read_text(encoding="utf-8"))
    locations: dict[str, set[str]] = defaultdict(set)
    for split, source_ids in assignments.items():
        for source_id in source_ids:
            locations[str(source_id)].add(split)
    leaks = sorted(source_id for source_id, splits in locations.items() if len(splits) > 1)
    return {"checked": True, "leaks": leaks, "sources": len(locations)}


def provenance_check() -> dict:
    path = DATASET / "metadata/provenance.jsonl"
    records: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("path") and row.get("source_url"):
                    records.add(str(row["path"]).replace("\\", "/"))
    image_extensions = {".jpg", ".jpeg", ".webp"}
    mask_extensions = {".png"}
    public_files = [p for p in (DATASET / "public").rglob("*") if p.is_file() and p.suffix.lower() in image_extensions | mask_extensions]
    custom_files = [p for p in (DATASET / "custom").rglob("*") if p.is_file() and p.suffix.lower() in image_extensions | mask_extensions]
    public_images = [p for p in public_files if p.suffix.lower() in image_extensions]
    public_masks = [p for p in public_files if p.suffix.lower() in mask_extensions]
    custom_images = [p for p in custom_files if p.suffix.lower() in image_extensions]
    custom_masks = [p for p in custom_files if p.suffix.lower() in mask_extensions]
    untracked_public = [p.relative_to(ROOT).as_posix() for p in public_files if p.relative_to(ROOT).as_posix() not in records]
    untracked_custom = [p.relative_to(ROOT).as_posix() for p in custom_files if p.relative_to(ROOT).as_posix() not in records]
    return {
        "public_images": len(public_images),
        "public_masks": len(public_masks),
        "public_without_provenance": untracked_public,
        "custom_images": len(custom_images),
        "custom_masks": len(custom_masks),
        "custom_without_provenance": untracked_custom,
    }


def met_artwork_inventory() -> dict:
    path = DATASET / "public/metmuseum/metadata/met_artworks_manifest.json"
    if not path.is_file():
        return {"objects": 0, "valid_images": 0, "bytes": 0, "missing_or_invalid": [], "source": "The Met Open Access API"}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    valid = []
    missing = []
    total_bytes = 0
    for item in manifest.get("objects", []):
        image = ROOT / item.get("path", "")
        if not image.is_file():
            missing.append(item.get("path", ""))
            continue
        try:
            digest = sha256_file(image)
            validation = _validate_downloaded_image(image)
            if digest != item.get("sha256"):
                raise ValueError("SHA-256 does not match Met artwork manifest")
            valid.append({"object_id": item.get("object_id"), "path": item["path"], "bytes": image.stat().st_size, "sha256": digest, "valid_image": validation["valid"]})
            total_bytes += image.stat().st_size
        except Exception as exc:
            missing.append({"path": item.get("path", ""), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "objects": len(manifest.get("objects", [])),
        "valid_images": len(valid),
        "bytes": total_bytes,
        "files": valid,
        "missing_or_invalid": missing,
        "license": "CC0 1.0 only; source metadata must confirm isPublicDomain=true",
        "gallery_scene_images": 0,
    }


def synthetic_scene_inventory() -> dict:
    import cv2
    import numpy as np

    manifest_path = DATASET / "synthetic/art_contact/metadata/synthetic_manifest.jsonl"
    if not manifest_path.is_file():
        return {"sample_type": "SYNTHETIC", "images": 0, "masks": 0, "split_counts": {"train": 0, "val": 0, "test": 0}, "validation_errors": []}
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    validation_errors = []
    splits = Counter()
    event_counts = Counter()
    mask_count = 0
    for row in rows:
        if row.get("sample_type") != "SYNTHETIC" or row.get("event_label_source") != "SYNTHETIC geometry label; not real-world ground truth":
            validation_errors.append({"sample_id": row.get("sample_id"), "error": "synthetic source marker is missing or invalid"})
        splits[row.get("split", "unknown")] += 1
        event_counts[row.get("event_label", "unknown")] += 1
        image_path = row.get("image_path")
        image = None
        if not image_path or not (ROOT / image_path).is_file():
            validation_errors.append({"sample_id": row.get("sample_id"), "path": image_path, "error": "image file is missing"})
        else:
            image_file = ROOT / image_path
            if sha256_file(image_file) != row.get("image_sha256"):
                validation_errors.append({"sample_id": row.get("sample_id"), "path": image_path, "error": "image SHA-256 mismatch"})
            image = cv2.imdecode(np.fromfile(image_file, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                validation_errors.append({"sample_id": row.get("sample_id"), "path": image_path, "error": "image cannot be decoded"})
        image_shape = image.shape[:2] if image is not None else None
        for class_name, mask_row in row.get("masks", {}).items():
            relative = mask_row.get("path")
            if not relative or not (ROOT / relative).is_file():
                validation_errors.append({"sample_id": row.get("sample_id"), "path": relative, "error": "mask file is missing"})
                continue
            mask_file = ROOT / relative
            if sha256_file(mask_file) != mask_row.get("sha256"):
                validation_errors.append({"sample_id": row.get("sample_id"), "path": relative, "error": "mask SHA-256 mismatch"})
            mask = cv2.imdecode(np.fromfile(mask_file, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.size == 0:
                validation_errors.append({"sample_id": row.get("sample_id"), "path": relative, "error": "mask cannot be decoded"})
            elif image_shape is not None and mask.shape != image_shape:
                validation_errors.append({"sample_id": row.get("sample_id"), "path": relative, "error": "mask and image dimensions differ"})
            elif not set(np.unique(mask)).issubset({0, 255}):
                validation_errors.append({"sample_id": row.get("sample_id"), "path": relative, "error": "mask is not binary"})
        mask_count += len(row.get("masks", {}))
    group_splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group_splits[str(row.get("source_group_id"))].add(str(row.get("split")))
    leaks = sorted(group for group, assigned in group_splits.items() if len(assigned) > 1)
    listed_images = {str(row.get("image_path")) for row in rows}
    listed_masks = {str(mask.get("path")) for row in rows for mask in row.get("masks", {}).values()}
    orphan_files = []
    for directory, listed in ((manifest_path.parents[1] / "images", listed_images), (manifest_path.parents[1] / "masks", listed_masks)):
        for path in directory.glob("*"):
            if path.is_file() and path.relative_to(ROOT).as_posix() not in listed:
                orphan_files.append(path.relative_to(ROOT).as_posix())
    return {
        "sample_type": "SYNTHETIC",
        "images": len(rows),
        "masks": mask_count,
        "split_counts": {split: int(splits.get(split, 0)) for split in ("train", "val", "test")},
        "event_counts": dict(event_counts),
        "source_groups": len(group_splits),
        "source_group_leaks": leaks,
        "validation_errors": validation_errors,
        "orphan_files": sorted(orphan_files),
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
    }


def mediapipe_model_inventory() -> dict:
    model_path = DATASET / "public/mediapipe/hand_landmarker.task"
    manifest = read_manifest()
    relative_path = model_path.relative_to(ROOT).as_posix()
    record = next(
        (row for row in reversed(manifest["downloads"]) if row.get("path") == relative_path and row.get("status") == "validated"),
        None,
    )
    active_installed = importlib.util.find_spec("mediapipe") is not None
    isolated_installed = (ROOT / ".venv-hands/Lib/site-packages/mediapipe/__init__.py").is_file()
    model_valid = bool(model_path.is_file() and record and sha256_file(model_path) == record.get("sha256"))
    status = "READY_IN_ACTIVE_ENVIRONMENT" if active_installed and model_valid else (
        "INSTALLED_IN_ISOLATED_ENVIRONMENT" if isolated_installed and model_valid else "NOT_READY"
    )
    return {
        "package_installed": active_installed or isolated_installed,
        "package_installed_in_active_environment": active_installed,
        "package_installed_in_isolated_environment": isolated_installed,
        "model_path": relative_path,
        "model_present_and_hash_verified": model_valid,
        "bytes": model_path.stat().st_size if model_valid else 0,
        "status": status,
        "output_type": "21 landmarks and handedness; no pixel mask or contact ground truth",
    }


def video_inventory() -> dict:
    extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".mpeg", ".mpg"}
    videos = [path for path in (DATASET / "public").rglob("*") if path.is_file() and path.suffix.lower() in extensions]
    valid = []
    invalid = []
    try:
        import cv2
    except ImportError:
        return {"count": len(videos), "valid": 0, "invalid": [], "validation_blocked": "OpenCV is not installed"}
    for path in videos:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            invalid.append(path.relative_to(ROOT).as_posix())
            continue
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, sample = capture.read()
        capture.release()
        if not ok or sample is None or frames <= 0 or width <= 0 or height <= 0:
            invalid.append(path.relative_to(ROOT).as_posix())
        else:
            valid.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "frames": frames, "fps": fps, "width": width, "height": height})
    return {"count": len(videos), "valid": len(valid), "total_bytes": sum(item["bytes"] for item in valid), "files": valid, "invalid": invalid}


def record_provenance(records: list[dict]) -> None:
    path = DATASET / "metadata/provenance.jsonl"
    existing = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                existing[record["path"]] = record
    for record in records:
        existing[record["path"]] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in existing.values()), encoding="utf-8")
    temporary.replace(path)


def run_validation() -> dict:
    ensure_layout()
    manifest = read_manifest()
    manifest_history_reconciliation = reconcile_download_history(manifest)
    if manifest_history_reconciliation["updated_rows_this_run"]:
        write_json(MANIFEST, manifest)
    verified_assets = []
    missing_assets = []
    latest_validated = {}
    for record in manifest["downloads"]:
        if record.get("status") == "validated":
            latest_validated[record.get("path")] = record
    for record in latest_validated.values():
        path = ROOT / record["path"]
        if not path.is_file():
            missing_assets.append(record["path"])
            continue
        try:
            digest = sha256_file(path)
            asset = SOURCES[record["source_id"]]["assets"].get(record["asset_id"])
            if asset is None and record.get("image_id"):
                asset = {"kind": "image", "required_columns": []}
            if asset is None:
                raise KeyError(f"No source catalog entry for manifest asset {record['asset_id']!r}.")
            format_validation = validate_asset(path, asset)
            verified_assets.append({
                "path": record["path"],
                "hash_matches": digest == record["sha256"],
                "bytes": path.stat().st_size,
                "format_validation": format_validation,
            })
        except Exception as exc:
            verified_assets.append({"path": record["path"], "hash_matches": False, "validation_error": f"{type(exc).__name__}: {exc}"})
    duplicates: dict[str, list[str]] = defaultdict(list)
    scanned_bytes = 0
    for path in DATASET.rglob("*"):
        if path.is_file() and not path.name.endswith(".part") and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".csv", ".json", ".zip", ".tar", ".gz"}:
            scanned_bytes += path.stat().st_size
            duplicates[sha256_file(path)].append(path.relative_to(ROOT).as_posix())
    duplicate_groups = [paths for paths in duplicates.values() if len(paths) > 1]
    label_report = validate_yolo_labels()
    open_images_pilot_path = DATASET / "public/open_images/reports/open_images_pilot_report.json"
    open_images_pilot = json.loads(open_images_pilot_path.read_text(encoding="utf-8")) if open_images_pilot_path.exists() else None
    custom_readiness_path = DATASET / "custom/reports/custom_readiness.json"
    custom_readiness = json.loads(custom_readiness_path.read_text(encoding="utf-8")) if custom_readiness_path.exists() else None
    met_inventory = met_artwork_inventory()
    synthetic_inventory = synthetic_scene_inventory()
    hand_model_inventory = mediapipe_model_inventory()
    public_videos = video_inventory()
    pilot_masks = (open_images_pilot or {}).get("valid_segmentation_masks_by_source_class", {})
    training_components = {
        "object_segmentation": {
            "status": "NOT_TRAINED",
            "available_mask_instances": {"Person": int(pilot_masks.get("Person", 0)), "Pen": int(pilot_masks.get("Pen", 0))},
            "reason": "The existing 100-image Open Images subset comes only from its official validation split and has incomplete target-instance annotation. It has no painting masks; Human hand is box-only. A source-grouped, complete training set for the desired task is not ready.",
        },
        "hand_localization": {
            "status": "PRETRAINED_LANDMARK_ADAPTER_READY" if hand_model_inventory["status"] in {"READY_IN_ACTIVE_ENVIRONMENT", "INSTALLED_IN_ISOLATED_ENVIRONMENT"} else "OPTIONAL_LANDMARK_ADAPTER_NOT_READY",
            "reason": "MediaPipe supplies 21 hand landmarks and the integrated adapter tests fingertip points against the configured painting mask; it does not supply hand segmentation masks or calibrated contact labels. The package and Apache 2.0 task model are validated in an isolated environment; install requirements-hands.txt in the selected server environment before enabling it. Open Images Human hand labels are boxes only, and ContactHands hosted-image terms remain unstated.",
        },
        "painting_detection": {
            "status": "ROI_FALLBACK_CONFIGURED",
            "reason": "The fixed-camera polygon ROI is configurable. Met artwork images do not teach framed-painting scene detection.",
        },
        "artwork_contact_event": {
            "status": "NOT_TRAINED",
            "reason": "No genuine painting-contact video labels are available. Synthetic logic scenarios are not real-world model training data.",
        },
    }
    report = {
        "generated_at_utc": now_utc(),
        "verified_downloads": verified_assets,
        "missing_downloads": missing_assets,
        "manifest_history_reconciliation": manifest_history_reconciliation,
        "open_images_boxable_inventory": image_class_inventory(),
        "open_images_pilot": open_images_pilot,
        "custom_readiness": custom_readiness,
        "vcoco_action_inventory": vcoco_action_inventory(),
        "met_artwork_inventory": met_inventory,
        "mediapipe_hand_landmarker": hand_model_inventory,
        "synthetic_scene_inventory": synthetic_inventory,
        "public_video_inventory": public_videos,
        "training_components": training_components,
        "yolo_segmentation_validation": label_report,
        "duplicate_groups": duplicate_groups,
        "provenance": provenance_check(),
        "source_split_leakage": check_split_leakage(),
        "dataset_bytes_scanned": scanned_bytes,
        "training_ready": False,
        "training_readiness_reason": "Not ready for the full painting/person/hand/tool task: no compatible, complete, independently split masks cover painting and hand. Person and Pen masks exist only in a small validation-only pilot with incomplete annotation coverage. No custom or contact-labeled videos are available.",
    }
    write_json(REPORT_JSON, report)
    write_report(report)
    return report


def write_report(report: dict | None = None) -> None:
    if report is None and REPORT_JSON.exists():
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    if report is None:
        report = {
            "generated_at_utc": now_utc(), "verified_downloads": [], "missing_downloads": [],
            "open_images_boxable_inventory": image_class_inventory(), "yolo_segmentation_validation": validate_yolo_labels(),
            "duplicate_groups": [], "provenance": provenance_check(), "source_split_leakage": check_split_leakage(),
            "dataset_bytes_scanned": 0, "training_ready": False,
            "training_readiness_reason": "Not ready: no verified prepared target-class segmentation dataset.",
        }
    lines = [
        "# Dataset Acquisition Report", "", f"Generated (UTC): {report['generated_at_utc']}", "",
        "## Actual acquisition state", "",
        f"Validated downloaded assets: {len(report['verified_downloads'])}",
        f"Missing manifest files: {len(report['missing_downloads'])}",
        f"Dataset bytes scanned: {report['dataset_bytes_scanned']}",
        f"Duplicate file groups: {len(report['duplicate_groups'])}", "",
        f"Manifest history: {report.get('manifest_history_reconciliation', {}).get('superseded_duplicate_successes', 0)} duplicate successes superseded; {report.get('manifest_history_reconciliation', {}).get('recovered_failures', 0)} failed attempts have matching validated assets.", "",
        "## Verified source inventory", "",
    ]
    inventory = report.get("open_images_boxable_inventory")
    if inventory:
        lines.extend([
            f"Open Images boxable vocabulary: {inventory['row_count']} CSV rows and {inventory['unique_class_names']} unique names from `{inventory['inventory_file']}`; official facts page headline says 600 classes (discrepancy flagged, not normalized).",
            "Candidate names (vocabulary matches only, not sample counts or segmentation proof):",
        ])
        for target, names in inventory["target_name_matches"].items():
            lines.append(f"- {target}: {', '.join(names) if names else 'no exact candidate names in this boxable vocabulary'}")
    else:
        lines.append("Open Images class inventory file has not been downloaded.")
    vcoco = report.get("vcoco_action_inventory")
    lines.extend(["", "## Human-object action inventory", ""])
    if vcoco:
        lines.append(f"V-COCO annotations: {vcoco['action_count']} actions over {vcoco['unique_coco_image_ids']} unique referenced COCO image IDs; no instance masks or painting/harmful-contact labels.")
        lines.append(f"Action names: {', '.join(vcoco['action_names'])}.")
    else:
        lines.append("V-COCO train annotations have not been downloaded.")
    met = report.get("met_artwork_inventory", {})
    lines.extend(["", "## Metropolitan Museum Open Access", ""])
    lines.append(f"Verified public-domain painting images: {met.get('valid_images', 0)}; bytes: {met.get('bytes', 0)}.")
    lines.append("Only API records marked `isPublicDomain=true` are included. Artwork images are not gallery scenes or framed-painting labels.")
    videos = report.get("public_video_inventory", {})
    lines.extend(["", "## Public videos", ""])
    lines.append(f"Downloaded public video files: {videos.get('count', 0)}; valid/openable: {videos.get('valid', 0)}; bytes: {videos.get('total_bytes', 0)}.")
    synthetic = report.get("synthetic_scene_inventory", {})
    lines.extend(["", "## Synthetic scenes", ""])
    lines.append(f"Synthetic images: {synthetic.get('images', 0)}; masks: {synthetic.get('masks', 0)}; split counts: `{json.dumps(synthetic.get('split_counts', {}), ensure_ascii=False)}`.")
    lines.append(f"Synthetic event labels: `{json.dumps(synthetic.get('event_counts', {}), ensure_ascii=False)}`; source-group leakage: `{json.dumps(synthetic.get('source_group_leaks', []), ensure_ascii=False)}`.")
    lines.append("Synthetic geometry and art-image crops are not real gallery scenes, real hand cutouts, or real-world ground truth.")
    hand_model = report.get("mediapipe_hand_landmarker", {})
    lines.extend(["", "## Optional hand-localization model", ""])
    lines.append(f"MediaPipe task model status: {hand_model.get('status', 'NOT_READY')}; package installed: {hand_model.get('package_installed', False)}; verified model bytes: {hand_model.get('bytes', 0)}.")
    lines.append("The adapter uses five fingertip landmarks as contact points. They are not pixel masks; the Task API does not expose a calibrated hand-presence probability, so event confidence uses its configured acceptance threshold.")
    open_images_pilot = report.get("open_images_pilot")
    lines.extend(["", "## Open Images Image Pilot", ""])
    if open_images_pilot:
        lines.append(
            f"Actual Open Images images: {open_images_pilot['actual_images_downloaded']} downloaded and "
            f"{open_images_pilot['valid_images']} valid; valid source masks: "
            f"{sum(open_images_pilot['valid_segmentation_masks_by_source_class'].values())}; "
            f"bbox-only target instances: {sum(open_images_pilot['bounding_box_only_instances_by_source_class'].values())}."
        )
        lines.append(f"Official split counts: `{json.dumps(open_images_pilot['source_split_image_counts'])}`.")
        lines.append(f"Masks by source class: `{json.dumps(open_images_pilot['valid_segmentation_masks_by_source_class'], ensure_ascii=False)}`.")
        lines.append(
            f"Images with any instance mask: {open_images_pilot.get('images_with_any_instance_mask', 'not recorded')}; "
            f"images with boxes but no instance mask: {open_images_pilot.get('images_with_boxes_but_no_instance_mask', 'not recorded')}; "
            f"images with at least one target bbox-only instance: {open_images_pilot['images_with_bbox_only_target_class_annotations']}."
        )
        lines.append(f"Target class availability: `{json.dumps(open_images_pilot['source_target_capabilities'], ensure_ascii=False)}`.")
        lines.append(f"Pilot download bytes including extracted masks: {open_images_pilot['pilot_bytes_including_metadata_and_mask_shards']}.")
        lines.append(f"Pilot training-ready: **{str(open_images_pilot['training_ready']).lower()}**. {open_images_pilot['training_readiness_reason']}")
    else:
        lines.append("No Open Images pixel-data pilot has been run.")
    custom_readiness = report.get("custom_readiness")
    lines.extend(["", "## Custom Webcam and Annotation Workflow", ""])
    if custom_readiness:
        lines.append(
            f"Custom webcam sessions: {custom_readiness['custom_recording_sessions']}; extracted frames: "
            f"{custom_readiness['custom_extracted_frames']}; LabelMe tasks: {custom_readiness['annotation_tasks']['tasks']}; "
            f"review states: `{json.dumps(custom_readiness['annotation_tasks']['states'])}`."
        )
        lines.append(
            f"Custom source-group split counts: `{json.dumps(custom_readiness['custom_split_counts'])}`; "
            f"independent groups: {custom_readiness['source_groups']}; meaningful evaluation split: "
            f"{custom_readiness['meaningful_evaluation_split']}; reviewed events: {sum(sum(event['labels'].values()) for event in custom_readiness['valid_event_files'])}."
        )
    else:
        lines.append("No custom webcam sessions or reviewed annotation tasks have been recorded yet.")
    yolo = report["yolo_segmentation_validation"]
    lines.extend([
        "", "## Prepared labels", "",
        f"Prepared images: {yolo['images']} (invalid: {yolo['invalid_images']}); valid segmentation rows: {yolo['valid_segmentation_rows']}; box-only rows: {yolo['box_only_rows']}; malformed rows: {yolo['malformed_rows']}; images missing labels: {yolo['missing_labels']}; orphan labels: {yolo['orphan_labels']}.",
        f"Class counts: `{json.dumps(yolo['class_counts'], ensure_ascii=False)}`.",
        "A box-only row is not counted as a segmentation mask. Automatically proposed annotations must remain marked unverified until human review.",
        "", "## Provenance and leakage", "",
        f"Public JPEG/web images: {report['provenance']['public_images']}; public mask PNGs: {report['provenance']['public_masks']}; public files without provenance: {len(report['provenance']['public_without_provenance'])}. Custom JPEG/web images: {report['provenance']['custom_images']}; custom mask PNGs: {report['provenance']['custom_masks']}; custom files without provenance: {len(report['provenance']['custom_without_provenance'])}.",
        f"Source-level split check: {json.dumps(report['source_split_leakage'], ensure_ascii=False)}.",
        "", "## Training readiness", "", f"Ready for YOLO segmentation fine-tuning: **{str(report['training_ready']).lower()}**.",
        report["training_readiness_reason"],
    ])
    for component, details in report.get("training_components", {}).items():
        lines.append(f"- **{component}: {details['status']}** — {details['reason']}")
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_archive(source_id: str, asset_id: str) -> Path:
    source = SOURCES[source_id]
    asset = source["assets"][asset_id]
    if not asset["download_allowed"]:
        raise PermissionError("Source asset is not approved for extraction.")
    archive_path = DATASET / asset["destination"] / asset["filename"]
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    extraction = archive_path.parent / archive_path.stem
    extraction.mkdir(parents=True, exist_ok=True)
    if asset["kind"] != "zip":
        raise ValueError("Only ZIP extraction is currently supported.")
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe archive path: {member.filename}")
            target = (extraction / Path(*member_path.parts)).resolve()
            if not target.is_relative_to(extraction.resolve()):
                raise ValueError(f"Archive member escapes extraction root: {member.filename}")
        archive.extractall(extraction)
    return extraction


def extract_video_frames(video_path: Path, sample_seconds: float) -> dict:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for video frame extraction.") from exc
    video_path = video_path.resolve()
    raw_roots = [(DATASET / "custom/raw_videos").resolve(), (DATASET / "public/other_sources").resolve()]
    if not any(video_path.is_relative_to(root) for root in raw_roots):
        raise ValueError("Video must be stored under dataset/custom/raw_videos or dataset/public/other_sources.")
    metadata_path = video_path.with_suffix(".json")
    if not metadata_path.is_file():
        raise ValueError("A same-basename JSON sidecar with documented source, license, and explicit permission is required.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    required = ("source_url", "license", "attribution", "source_identifier")
    if any(not metadata.get(key) for key in required) or metadata.get("permission_verified") is not True or metadata.get("intended_use_permitted") is not True:
        raise ValueError("Video sidecar must document source URL, license, attribution, source ID, permission_verified=true, and intended_use_permitted=true.")
    if not metadata.get("original_filename") or not (metadata.get("downloaded_at_utc") or metadata.get("recorded_at_utc")):
        raise ValueError("Video sidecar must include original_filename and downloaded_at_utc or recorded_at_utc.")
    if sample_seconds <= 0:
        raise ValueError("--sample-seconds must be positive.")
    source_id = str(metadata["source_identifier"])
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in source_id):
        raise ValueError("source_identifier may contain only letters, digits, hyphen, and underscore.")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open permitted video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Video metadata is invalid; duration, resolution, and FPS cannot be recorded reliably.")
    duration = frame_count / fps
    output_root = DATASET / ("public/other_sources/extracted_frames" if video_path.is_relative_to((DATASET / "public").resolve()) else "custom/extracted_frames") / source_id
    output_root.mkdir(parents=True, exist_ok=True)
    frames = []
    duplicate_frames = []
    frame_provenance = []
    frame_hash_to_path = {}
    timestamp = 0.0
    try:
        while timestamp < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            encoded_ok, encoded_frame = cv2.imencode(".jpg", frame)
            if not encoded_ok:
                raise IOError(f"Could not encode sampled frame at {timestamp:.3f}s")
            frame_digest = hashlib.sha256(encoded_frame.tobytes()).hexdigest()
            if frame_digest in frame_hash_to_path:
                duplicate_frames.append({
                    "timestamp_seconds": round(timestamp, 3),
                    "duplicate_of": frame_hash_to_path[frame_digest],
                    "sha256": frame_digest,
                    "source_identifier": source_id,
                })
                timestamp += sample_seconds
                continue
            output = output_root / f"frame_{len(frames):06d}_{int(timestamp * 1000):010d}ms.jpg"
            if output.exists():
                try:
                    _validate_downloaded_image(output)
                except (OSError, ValueError) as exc:
                    raise ValueError(f"Existing extracted frame is invalid; refusing to overwrite: {output}")
                frame_digest = sha256_file(output)
                frames.append({"path": output.relative_to(ROOT).as_posix(), "timestamp_seconds": round(timestamp, 3), "source_identifier": source_id})
                frame_hash_to_path[frame_digest] = output.relative_to(ROOT).as_posix()
                frame_provenance.append({
                    "path": output.relative_to(ROOT).as_posix(), "source_url": metadata["source_url"],
                    "license": metadata["license"], "attribution": metadata["attribution"],
                    "source_identifier": source_id, "video_path": video_path.relative_to(ROOT).as_posix(),
                    "timestamp_seconds": round(timestamp, 3), "permission_verified_by_operator": True,
                })
                timestamp += sample_seconds
                continue
            with output.open("xb") as frame_file:
                frame_file.write(encoded_frame.tobytes())
            frames.append({"path": output.relative_to(ROOT).as_posix(), "timestamp_seconds": round(timestamp, 3), "source_identifier": source_id})
            frame_hash_to_path[frame_digest] = output.relative_to(ROOT).as_posix()
            frame_provenance.append({
                "path": output.relative_to(ROOT).as_posix(), "source_url": metadata["source_url"],
                "license": metadata["license"], "attribution": metadata["attribution"],
                "source_identifier": source_id, "video_path": video_path.relative_to(ROOT).as_posix(),
                "timestamp_seconds": round(timestamp, 3), "permission_verified_by_operator": True,
            })
            timestamp += sample_seconds
    finally:
        capture.release()
    result = {
        "source_url": metadata["source_url"], "license": metadata["license"], "attribution": metadata["attribution"],
        "source_identifier": source_id, "original_filename": metadata.get("original_filename", video_path.name),
        "downloaded_at_utc": metadata.get("downloaded_at_utc"), "recorded_at_utc": metadata.get("recorded_at_utc"),
        "video_path": video_path.relative_to(ROOT).as_posix(),
        "duration_seconds": duration, "width": width, "height": height, "fps": fps,
        "sample_interval_seconds": sample_seconds, "frame_count": len(frames), "frames": frames,
        "duplicate_sample_timestamps": duplicate_frames,
    }
    write_json(output_root / "frames_manifest.json", result)
    record_provenance(frame_provenance)
    return result


def assign_source_split(source_id: str, split: str) -> None:
    if split not in {"train", "val", "test"}:
        raise ValueError("Split must be train, val, or test.")
    path = DATASET / "splits/sources.json"
    assignments = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"train": [], "val": [], "test": []}
    existing = [key for key, values in assignments.items() if source_id in values]
    if existing and existing != [split]:
        raise ValueError(f"Source {source_id!r} already assigned to {existing}; refusing cross-split reuse.")
    for values in assignments.values():
        if source_id in values:
            values.remove(source_id)
    assignments.setdefault(split, []).append(source_id)
    write_json(path, assignments)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rights-aware public dataset acquisition and validation for PBL4.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create separated public/custom dataset layout and manifest.")
    commands.add_parser("sources", help="List dataset sources and approval state.")
    inspect_parser = commands.add_parser("inspect", help="Print source metadata.")
    inspect_parser.add_argument("source", choices=sorted(SOURCES))
    download_parser = commands.add_parser("download", help="Download a catalog-approved, documented dataset asset.")
    download_parser.add_argument("source", choices=sorted(SOURCES))
    download_parser.add_argument("asset")
    download_parser.add_argument("--retries", type=int, default=3)
    commands.add_parser("validate", help="Validate downloaded files, images, labels, duplicates, provenance, and split leakage.")
    pilot_parser = commands.add_parser("open-images-pilot", help="Acquire an annotation-selected, CC BY 2.0 Open Images validation image/mask subset.")
    pilot_parser.add_argument("--limit", type=int, default=100, help="Number of images to select (100-300).")
    pilot_parser.add_argument("--max-bytes", type=int, default=1_000_000_000, help="Maximum planned download plus selected extracted masks; actual pilot must remain below 1 GB.")
    pilot_parser.add_argument("--preflight-only", action="store_true", help="Download only the small annotation/license metadata needed to select images; do not download images or mask shards.")
    met_parser = commands.add_parser("metmuseum-artworks", help="Download a small set of CC0 public-domain Met painting images through its official API.")
    met_parser.add_argument("--limit", type=int, default=10, help="Maximum number of paintings to retrieve (1-50).")
    met_parser.add_argument("--max-bytes", type=int, default=200_000_000, help="Maximum total image bytes to download after size preflight.")
    commands.add_parser("report", help="Regenerate the dataset readiness report from actual local data.")
    extract_parser = commands.add_parser("extract", help="Safely extract a validated catalog ZIP while retaining the archive.")
    extract_parser.add_argument("source", choices=sorted(SOURCES))
    extract_parser.add_argument("asset")
    frames_parser = commands.add_parser("extract-frames", help="Sample frames from a video with explicit reuse permission metadata.")
    frames_parser.add_argument("video", type=Path)
    frames_parser.add_argument("--sample-seconds", type=float, default=2.0)
    split_parser = commands.add_parser("assign-source-split", help="Assign a whole video/source to one split.")
    split_parser.add_argument("source_id")
    split_parser.add_argument("split", choices=["train", "val", "test"])
    args = parser.parse_args()

    try:
        if args.command == "init":
            ensure_layout()
            print(f"Initialized separated dataset layout under {DATASET}")
        elif args.command == "sources":
            for key, source in SOURCES.items():
                enabled = [asset_id for asset_id, asset in source["assets"].items() if asset["download_allowed"]]
                print(f"{key}: {source['name']} | downloadable assets: {', '.join(enabled) or 'none'}")
        elif args.command == "inspect":
            print(json.dumps(SOURCES[args.source], indent=2, ensure_ascii=False))
        elif args.command == "download":
            download_asset(args.source, args.asset, max(1, args.retries))
        elif args.command == "open-images-pilot":
            pilot = run_open_images_pilot(args.limit, args.max_bytes, args.preflight_only)
            if args.preflight_only:
                print(json.dumps(pilot, indent=2, ensure_ascii=False))
            else:
                report = run_validation()
                print(json.dumps({"pilot": pilot, "report": report}, indent=2, ensure_ascii=False))
        elif args.command == "metmuseum-artworks":
            result = download_met_artworks(args.limit, args.max_bytes)
            print(json.dumps({"objects": len(result["objects"]), "total_image_bytes": result["total_image_bytes"], "manifest": str(DATASET / "public/metmuseum/metadata/met_artworks_manifest.json")}, indent=2))
        elif args.command == "validate":
            report = run_validation()
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.command == "report":
            report = run_validation()
            print(f"Updated dataset report files; training_ready={report['training_ready']}")
        elif args.command == "extract":
            print(f"Extracted to {extract_archive(args.source, args.asset)}")
        elif args.command == "extract-frames":
            print(json.dumps(extract_video_frames(args.video, args.sample_seconds), indent=2, ensure_ascii=False))
        elif args.command == "assign-source-split":
            ensure_layout()
            assign_source_split(args.source_id, args.split)
            print(f"Assigned source {args.source_id} to {args.split}")
    except Exception as exc:
        print(f"Acquisition error: {type(exc).__name__}: {exc!a}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
