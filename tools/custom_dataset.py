from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from inference.camera_factory import build_camera_source
from inference.config import (
    DEFAULT_CAMERA_BACKEND,
    DEFAULT_CAMERA_INDEX,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    WINDOWS_WEBCAM_BACKEND_PRIORITY,
)
from tools import dataset_acquire as acquire

ROOT = acquire.ROOT
DATASET = acquire.DATASET
CUSTOM = DATASET / "custom"
RAW_VIDEOS = CUSTOM / "raw_videos"
EXTRACTED_FRAMES = CUSTOM / "extracted_frames"
ANNOTATED = CUSTOM / "annotated"
PREPARED = CUSTOM / "prepared"
CUSTOM_METADATA = CUSTOM / "metadata"
ANNOTATION_MANIFEST = CUSTOM_METADATA / "annotation_manifest.json"
SPLIT_MANIFEST = CUSTOM / "splits/source_groups.json"
CUSTOM_REPORT = CUSTOM / "reports/custom_readiness.json"
TARGET_CLASS_IDS = {"painting": 0, "person": 1, "hand": 2, "tool": 3}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EVENT_LABELS = {"SAFE", "NEAR", "CONTACT"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_custom_layout() -> None:
    for path in (
        RAW_VIDEOS,
        EXTRACTED_FRAMES,
        ANNOTATED / "labelme",
        ANNOTATED / "events",
        CUSTOM_METADATA,
        CUSTOM / "splits",
        CUSTOM / "reports",
        *(PREPARED / "images" / split for split in ("train", "val", "test")),
        *(PREPARED / "labels" / split for split in ("train", "val", "test")),
    ):
        path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_image_unicode(path: Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None or image.size == 0:
        raise ValueError(f"Cannot decode image bytes: {path}")
    return image


def write_image_unicode(path: Path, image: np.ndarray) -> None:
    suffix = path.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError(f"Unsupported image extension: {suffix}")
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise IOError(f"Could not encode image for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing image: {path}")
    with path.open("xb") as output:
        output.write(encoded.tobytes())


def file_sha256(path: Path) -> str:
    return acquire.sha256_file(path)


def _new_session_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"webcam-{timestamp}-{uuid.uuid4().hex[:8]}"


def record_webcam(
    duration_seconds: float,
    camera_index: int = DEFAULT_CAMERA_INDEX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    backend: str = DEFAULT_CAMERA_BACKEND,
    preview: bool = True,
    session_id: str | None = None,
) -> dict:
    if duration_seconds <= 0:
        raise ValueError("Recording duration must be positive.")
    ensure_custom_layout()
    session_id = session_id or _new_session_id()
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in session_id):
        raise ValueError("Session ID may contain only letters, digits, hyphen, and underscore.")
    source = build_camera_source(
        "webcam", camera_index=camera_index, width=width, height=height, fps=fps,
        backend=backend, backend_priority=list(WINDOWS_WEBCAM_BACKEND_PRIORITY),
    )
    if not source.open():
        raise RuntimeError(f"Webcam open failed: index={camera_index} backend={backend}: {source.last_error}")

    final_path = RAW_VIDEOS / f"{session_id}.avi"
    sidecar_path = final_path.with_suffix(".json")
    if final_path.exists() or sidecar_path.exists():
        source.release()
        raise FileExistsError(f"Recording session already exists: {session_id}")

    temporary_handle = tempfile.NamedTemporaryFile(prefix="pbl4-camera-", suffix=".avi", delete=False)
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()
    temporary_path.unlink(missing_ok=True)
    writer = cv2.VideoWriter(
        str(temporary_path), cv2.VideoWriter_fourcc(*"MJPG"), float(fps), (width, height)
    )
    if not writer.isOpened():
        source.release()
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("OpenCV could not initialize the MJPG AVI writer in the system temporary directory.")

    started_local = datetime.now().astimezone().isoformat(timespec="seconds")
    started_utc = utc_now()
    started_tick = time.perf_counter()
    frame_count = 0
    actual_width, actual_height = width, height
    active_backend = source.active_backend or backend
    window_name = f"PBL4 custom recording: {session_id}"
    try:
        while time.perf_counter() - started_tick < duration_seconds:
            frame_info = source.read()
            if frame_info is None:
                raise RuntimeError(f"Webcam frame read failed: {source.last_error}")
            frame = frame_info.frame
            actual_height, actual_width = frame.shape[:2]
            if (actual_width, actual_height) != (width, height):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
            frame_count += 1
            if preview:
                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                try:
                    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except cv2.error:
                    break
    finally:
        writer.release()
        source.release()
        if preview:
            cv2.destroyAllWindows()

    ended_utc = utc_now()
    elapsed = max(time.perf_counter() - started_tick, 1e-6)
    if frame_count == 0 or not temporary_path.is_file() or temporary_path.stat().st_size == 0:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("Webcam recording produced no valid video frames.")
    shutil.copyfile(temporary_path, final_path)
    temporary_path.unlink(missing_ok=True)
    actual_fps = frame_count / elapsed
    metadata = {
        "schema_version": 1,
        "recording_session_id": session_id,
        "source_identifier": session_id,
        "source_type": "webcam",
        "camera_source": "laptop webcam",
        "camera_index": camera_index,
        "camera_backend": active_backend,
        "source_url": f"local://webcam/{session_id}",
        "license": "Custom recording made by the operator; confirm consent and institutional recording rules before use.",
        "attribution": "Recorded locally by the operator.",
        "original_filename": final_path.name,
        "recorded_at_local": started_local,
        "recorded_at_utc": started_utc,
        "ended_at_utc": ended_utc,
        "downloaded_at_utc": started_utc,
        "duration_seconds": round(elapsed, 3),
        "width": width,
        "height": height,
        "camera_reported_width": actual_width,
        "camera_reported_height": actual_height,
        "requested_fps": fps,
        "measured_recording_fps": round(actual_fps, 3),
        "frames_written": frame_count,
        "permission_verified": True,
        "intended_use_permitted": True,
        "operator_note": "Set permission flags only for the operator's own recording and after any participant consent requirements are satisfied.",
        "video_sha256": file_sha256(final_path),
        "video_bytes": final_path.stat().st_size,
    }
    write_json(sidecar_path, metadata)
    acquire.record_provenance([{
        "path": final_path.relative_to(ROOT).as_posix(),
        "source_url": metadata["source_url"],
        "source_identifier": session_id,
        "license": metadata["license"],
        "recorded_at_utc": started_utc,
        "sha256": metadata["video_sha256"],
        "bytes": metadata["video_bytes"],
    }])
    return metadata


def extract_custom_frames(video_path: Path, sample_seconds: float) -> dict:
    video_path = video_path.resolve()
    if not video_path.is_relative_to(RAW_VIDEOS.resolve()):
        raise ValueError(f"Custom video must be under {RAW_VIDEOS}.")
    return acquire.extract_video_frames(video_path, sample_seconds)


def _annotation_manifest() -> dict:
    return read_json(ANNOTATION_MANIFEST, {"schema_version": 1, "tasks": []})


def _write_annotation_manifest(manifest: dict) -> None:
    manifest["updated_at_utc"] = utc_now()
    write_json(ANNOTATION_MANIFEST, manifest)


def _frame_source_index() -> dict[str, dict]:
    index = {}
    for manifest_path in EXTRACTED_FRAMES.rglob("frames_manifest.json") if EXTRACTED_FRAMES.exists() else []:
        data = read_json(manifest_path)
        for frame in data.get("frames", []):
            relative = str(frame.get("path", "")).replace("\\", "/")
            index[relative] = {
                "source_group_id": data.get("source_identifier", manifest_path.parent.name),
                "source_video": data.get("video_path"),
                "source_url": data.get("source_url"),
                "license": data.get("license"),
                "attribution": data.get("attribution"),
                "timestamp_seconds": frame.get("timestamp_seconds"),
            }
    return index


def prepare_labelme_tasks() -> dict:
    ensure_custom_layout()
    labels_path = CUSTOM_METADATA / "labelme_labels.txt"
    labels_text = "\n".join(TARGET_CLASS_IDS) + "\n"
    if labels_path.exists() and labels_path.read_text(encoding="utf-8") != labels_text:
        raise FileExistsError(f"Refusing to overwrite a changed LabelMe class list: {labels_path}")
    if not labels_path.exists():
        labels_path.write_text(labels_text, encoding="utf-8")
    manifest = _annotation_manifest()
    known = {task["image_path"] for task in manifest["tasks"]}
    source_index = _frame_source_index()
    created = []
    skipped_existing = []
    for image_path in sorted(EXTRACTED_FRAMES.rglob("*")):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        image_relative = image_path.relative_to(ROOT).as_posix()
        if image_relative in known:
            skipped_existing.append(image_relative)
            continue
        image = read_image_unicode(image_path)
        source = source_index.get(image_relative, {})
        source_group = str(source.get("source_group_id") or image_path.parent.name)
        annotation_path = ANNOTATED / "labelme" / source_group / f"{image_path.stem}.json"
        if annotation_path.exists():
            raise FileExistsError(f"Refusing to overwrite existing annotation: {annotation_path}")
        labelme_document = {
            "version": "5.8.1",
            "flags": {},
            "shapes": [],
            "imagePath": Path(os.path.relpath(image_path, annotation_path.parent)).as_posix(),
            "imageData": None,
            "imageHeight": int(image.shape[0]),
            "imageWidth": int(image.shape[1]),
        }
        write_json(annotation_path, labelme_document)
        task = {
            "annotation_file": annotation_path.relative_to(ROOT).as_posix(),
            "image_path": image_relative,
            "image_sha256": file_sha256(image_path),
            "image_width": int(image.shape[1]),
            "image_height": int(image.shape[0]),
            "source_group_id": source_group,
            "source_video": source.get("source_video"),
            "source_url": source.get("source_url", f"local://custom/{source_group}"),
            "license": source.get("license", "Custom operator recording; confirm consent and local policy."),
            "attribution": source.get("attribution", "Recorded locally by the operator."),
            "timestamp_seconds": source.get("timestamp_seconds"),
            "annotation_state": "pending",
            "verified_empty": False,
            "reviewer": None,
            "reviewed_at_utc": None,
            "notes": "",
            "classes": list(TARGET_CLASS_IDS),
        }
        manifest["tasks"].append(task)
        known.add(image_relative)
        created.append(task)
    _write_annotation_manifest(manifest)
    return {
        "created": len(created),
        "skipped_existing": len(skipped_existing),
        "labels_file": labels_path.relative_to(ROOT).as_posix(),
        "tasks": created,
    }


def launch_labelme(annotation_file: str) -> None:
    manifest = _annotation_manifest()
    target_path = Path(annotation_file).as_posix()
    task = next((row for row in manifest["tasks"] if row["annotation_file"] == target_path), None)
    if task is None:
        raise KeyError(f"Annotation task not found: {target_path}; run prepare-labelme first.")
    image_path = ROOT / task["image_path"]
    annotation_path = ROOT / task["annotation_file"]
    labels_path = CUSTOM_METADATA / "labelme_labels.txt"
    if not image_path.is_file() or not annotation_path.is_file() or not labels_path.is_file():
        raise FileNotFoundError("Image, LabelMe task JSON, or class list is missing; run prepare-labelme first.")
    executable = shutil.which("labelme")
    if executable is None:
        raise RuntimeError("LabelMe is not installed in this environment. Install it with: python -m pip install -r requirements-annotation.txt")
    subprocess.run(
        [executable, str(image_path), "--output", str(annotation_path), "--labels", str(labels_path)],
        check=True,
    )


def update_annotation_state(
    annotation_file: str,
    state: str,
    reviewer: str | None,
    notes: str,
    verified_empty: bool = False,
    completeness_verified: bool = False,
) -> dict:
    if state not in {"pending", "proposed_unverified", "reviewed", "rejected"}:
        raise ValueError("Annotation state must be pending, proposed_unverified, reviewed, or rejected.")
    if state == "reviewed" and not reviewer:
        raise ValueError("A reviewer name is required before marking labels reviewed.")
    if verified_empty and state != "reviewed":
        raise ValueError("verified_empty is valid only for a human-reviewed task.")
    if completeness_verified and state != "reviewed":
        raise ValueError("Scene completeness can be confirmed only for a human-reviewed task.")
    manifest = _annotation_manifest()
    target_path = Path(annotation_file).as_posix()
    task = next((row for row in manifest["tasks"] if row["annotation_file"] == target_path), None)
    if task is None:
        raise KeyError(f"Annotation task not found in manifest: {target_path}")
    task["annotation_state"] = state
    task["verified_empty"] = verified_empty
    task["annotation_completeness_verified"] = completeness_verified if state == "reviewed" else False
    task["reviewer"] = reviewer
    task["reviewed_at_utc"] = utc_now() if state == "reviewed" else None
    task["notes"] = notes
    _write_annotation_manifest(manifest)
    return task


def _validate_labelme_polygons(task: dict) -> tuple[dict, list[tuple[int, list[tuple[float, float]]]]]:
    annotation_path = ROOT / task["annotation_file"]
    image_path = ROOT / task["image_path"]
    if not annotation_path.resolve().is_relative_to((ANNOTATED / "labelme").resolve()):
        raise ValueError(f"Annotation path escapes the LabelMe task folder: {annotation_path}")
    if not image_path.resolve().is_relative_to(EXTRACTED_FRAMES.resolve()):
        raise ValueError(f"Custom training image is outside extracted custom frames: {image_path}")
    if not annotation_path.is_file() or not image_path.is_file():
        raise FileNotFoundError(f"Missing image or annotation: {annotation_path} / {image_path}")
    if file_sha256(image_path) != task["image_sha256"]:
        raise ValueError(f"Source image changed since annotation task generation: {image_path}")
    data = json.loads(annotation_path.read_text(encoding="utf-8"))
    image = read_image_unicode(image_path)
    height, width = image.shape[:2]
    if data.get("imageWidth") != width or data.get("imageHeight") != height:
        raise ValueError(f"LabelMe image dimensions disagree with actual image: {annotation_path}")
    polygons = []
    class_names = set()
    for index, shape in enumerate(data.get("shapes", [])):
        label = shape.get("label")
        if label not in TARGET_CLASS_IDS:
            raise ValueError(f"Unknown target class {label!r} in {annotation_path}, shape {index}.")
        if shape.get("shape_type") != "polygon":
            raise ValueError(f"Shape {index} must be a polygon for segmentation conversion.")
        points = [(float(point[0]), float(point[1])) for point in shape.get("points", [])]
        if len(set(points)) < 3 or any(not (0 <= x <= width and 0 <= y <= height) for x, y in points):
            raise ValueError(f"Polygon {index} has fewer than 3 unique points or points outside the image.")
        area = abs(sum(
            points[i][0] * points[(i + 1) % len(points)][1]
            - points[(i + 1) % len(points)][0] * points[i][1]
            for i in range(len(points))
        )) / 2
        if area <= 0:
            raise ValueError(f"Polygon {index} has zero area.")
        class_names.add(label)
        polygons.append((TARGET_CLASS_IDS[label], points))
    return data, polygons


def validate_labelme_tasks() -> dict:
    manifest = _annotation_manifest()
    counts = Counter(task.get("annotation_state", "pending") for task in manifest["tasks"])
    invalid = []
    reviewed_shapes = Counter()
    for task in manifest["tasks"]:
        if task.get("annotation_state") != "reviewed":
            continue
        try:
            if not task.get("reviewer"):
                raise ValueError("Reviewed task is missing reviewer identity.")
            _, polygons = _validate_labelme_polygons(task)
            reviewed_shapes.update(TARGET_CLASS_IDS_INV[class_id] for class_id, _ in polygons)
            if not polygons and not task.get("verified_empty"):
                raise ValueError("Reviewed segmentation task has no reviewed polygon shapes.")
        except Exception as exc:
            invalid.append({"annotation_file": task["annotation_file"], "error": str(exc)})
    return {
        "tasks": len(manifest["tasks"]),
        "states": dict(counts),
        "reviewed_polygon_counts": dict(reviewed_shapes),
        "invalid_reviewed_tasks": invalid,
    }


TARGET_CLASS_IDS_INV = {value: key for key, value in TARGET_CLASS_IDS.items()}


def _reviewed_task_records() -> list[tuple[dict, list[tuple[int, list[tuple[float, float]]]]]]:
    manifest = _annotation_manifest()
    records = []
    for task in manifest["tasks"]:
        if task.get("annotation_state") != "reviewed":
            continue
        if not task.get("reviewer"):
            raise ValueError(f"Reviewed annotation lacks reviewer: {task['annotation_file']}")
        _, polygons = _validate_labelme_polygons(task)
        if not polygons and not task.get("verified_empty"):
            raise ValueError(f"Reviewed annotation has no polygons: {task['annotation_file']}")
        records.append((task, polygons))
    return records


def _safe_group_folder(value: str) -> str:
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in value):
        raise ValueError(f"Unsafe source-group identifier for prepared output: {value!r}")
    return value


def build_grouped_splits(seed: str = "pbl4-custom-v1") -> dict:
    records = _reviewed_task_records()
    if not records:
        split_data = {
            "schema_version": 1,
            "seed": seed,
            "ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
            "splits": {"train": [], "val": [], "test": []},
            "source_groups": 0,
            "unique_images": 0,
            "image_counts": {"train": 0, "val": 0, "test": 0},
            "source_group_counts_by_split": {"train": 0, "val": 0, "test": 0},
            "duplicate_image_hash_groups": 0,
            "duplicate_images_excluded": 0,
            "duplicate_image_paths_excluded": [],
            "meaningful_evaluation": False,
            "readiness": "No reviewed custom polygons exist; nothing is eligible for YOLO segmentation splits.",
        }
        write_json(SPLIT_MANIFEST, split_data)
        return split_data

    parents: dict[str, str] = {}

    def find(item: str) -> str:
        parents.setdefault(item, item)
        if parents[item] != item:
            parents[item] = find(parents[item])
        return parents[item]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    hash_to_item: dict[str, str] = {}
    item_keys = []
    kept_hashes = set()
    duplicate_images_excluded = 0
    duplicate_image_paths_excluded = []
    for task, _ in records:
        if task["image_sha256"] in kept_hashes:
            duplicate_images_excluded += 1
            duplicate_image_paths_excluded.append(task["image_path"])
            continue
        kept_hashes.add(task["image_sha256"])
        source_group = task.get("source_group_id") or task["image_path"]
        item = f"source:{source_group}"
        find(item)
        image_hash = task["image_sha256"]
        if image_hash in hash_to_item:
            union(item, hash_to_item[image_hash])
        else:
            hash_to_item[image_hash] = item
        item_keys.append((task, item))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for task, item in item_keys:
        grouped[find(item)].append(task)

    ordered_groups = sorted(
        grouped.items(),
        key=lambda pair: hashlib.sha256(f"{seed}:{pair[0]}".encode()).hexdigest(),
    )
    ratios = {"train": 0.70, "val": 0.15, "test": 0.15}
    counts = Counter()
    split_rows = {name: [] for name in ratios}
    forced_order = ("train", "val", "test")
    for index, (group_id, tasks) in enumerate(ordered_groups):
        if index < min(3, len(ordered_groups)):
            split = forced_order[index]
        else:
            split = min(ratios, key=lambda name: counts[name] / ratios[name])
        for task in tasks:
            split_rows[split].append({
                "image_path": task["image_path"],
                "image_sha256": task["image_sha256"],
                "annotation_file": task["annotation_file"],
                "source_group_id": task.get("source_group_id") or task["image_path"],
            })
            counts[split] += 1
    hashes_by_split = {name: {row["image_sha256"] for row in rows} for name, rows in split_rows.items()}
    leakage = any(
        hashes_by_split[left] & hashes_by_split[right]
        for left, right in (("train", "val"), ("train", "test"), ("val", "test"))
    )
    group_counts = {
        split: len({find(f"source:{row.get('source_group_id') or row['image_path']}") for row in rows})
        for split, rows in split_rows.items()
    }
    meaningful = (
        len(ordered_groups) >= 10
        and counts["train"] >= 20
        and counts["val"] >= 5
        and counts["test"] >= 5
        and group_counts["train"] >= 5
        and group_counts["val"] >= 2
        and group_counts["test"] >= 2
        and not leakage
    )
    split_data = {
        "schema_version": 1,
        "seed": seed,
        "ratios": ratios,
        "splits": split_rows,
        "source_groups": len(ordered_groups),
        "unique_images": sum(counts.values()),
        "image_counts": {name: counts[name] for name in ratios},
        "source_group_counts_by_split": group_counts,
        "duplicate_image_hash_groups": duplicate_images_excluded,
        "duplicate_images_excluded": duplicate_images_excluded,
        "duplicate_image_paths_excluded": duplicate_image_paths_excluded,
        "hash_leakage": leakage,
        "meaningful_evaluation": meaningful and not leakage,
        "readiness": "Independent source groups meet the minimum split-count checks; image and class coverage still require review." if meaningful else "Too few independent source groups/images for meaningful train/val/test evaluation.",
    }
    if leakage:
        raise AssertionError("Grouped split assigned duplicate image hashes across splits.")
    write_json(SPLIT_MANIFEST, split_data)
    return split_data


def convert_reviewed_to_yolo() -> dict:
    split_data = read_json(SPLIT_MANIFEST)
    if not split_data or not split_data.get("splits"):
        raise RuntimeError("Run split-reviewed first; refusing to create an ungrouped YOLO dataset.")
    split_by_image = {
        row["image_path"]: split
        for split, rows in split_data["splits"].items()
        for row in rows
    }
    excluded_duplicate_paths = set(split_data.get("duplicate_image_paths_excluded", []))
    records = _reviewed_task_records()
    converted = Counter()
    prepared_provenance = []
    for task, polygons in records:
        if task["image_path"] in excluded_duplicate_paths:
            continue
        split = split_by_image.get(task["image_path"])
        if split is None:
            raise ValueError(f"Reviewed task absent from source-group split manifest: {task['image_path']}")
        source_image = ROOT / task["image_path"]
        group_folder = _safe_group_folder(str(task.get("source_group_id") or source_image.parent.name))
        image_relative = Path(group_folder) / source_image.name
        image_destination = PREPARED / "images" / split / image_relative
        label_destination = PREPARED / "labels" / split / image_relative.with_suffix(".txt")
        if image_destination.exists():
            if file_sha256(image_destination) != task["image_sha256"]:
                raise FileExistsError(f"Refusing to overwrite differing prepared image: {image_destination}")
        else:
            image_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_image, image_destination)
        prepared_provenance.append({
            "path": image_destination.relative_to(ROOT).as_posix(),
            "source_url": task.get("source_url", f"local://custom/{task.get('source_group_id', 'unknown')}"),
            "source_group_id": task.get("source_group_id"),
            "source_frame_path": task["image_path"],
            "license": task.get("license", "Custom operator recording; confirm consent and local policy."),
            "attribution": task.get("attribution", "Recorded locally by the operator."),
            "image_sha256": task["image_sha256"],
            "annotation_file": task["annotation_file"],
            "annotation_state": task["annotation_state"],
            "reviewer": task.get("reviewer"),
            "annotation_completeness_verified": task.get("annotation_completeness_verified", False),
        })
        image = read_image_unicode(source_image)
        height, width = image.shape[:2]
        rows = []
        for class_id, points in polygons:
            normalized = []
            for x, y in points:
                normalized.extend((f"{x / width:.8f}", f"{y / height:.8f}"))
            rows.append(f"{class_id} " + " ".join(normalized))
        payload = "\n".join(rows) + ("\n" if rows else "")
        if label_destination.exists():
            if label_destination.read_text(encoding="utf-8") != payload:
                raise FileExistsError(f"Refusing to overwrite differing prepared label: {label_destination}")
        else:
            label_destination.parent.mkdir(parents=True, exist_ok=True)
            label_destination.write_text(payload, encoding="utf-8")
        converted[split] += 1
    if prepared_provenance:
        acquire.record_provenance(prepared_provenance)
    acquire.run_validation()
    return {"converted_images_by_split": dict(converted), "split_manifest": split_data, "training_started": False}


def create_event_templates() -> dict:
    ensure_custom_layout()
    templates = []
    for sidecar_path in sorted(RAW_VIDEOS.glob("*.json")):
        metadata = read_json(sidecar_path)
        session_id = metadata.get("recording_session_id") or metadata.get("source_identifier")
        if not session_id:
            continue
        path = ANNOTATED / "events" / f"{session_id}.json"
        if path.exists():
            continue
        template = {
            "schema_version": 1,
            "recording_session_id": session_id,
            "source_video": (RAW_VIDEOS / metadata["original_filename"]).relative_to(ROOT).as_posix(),
            "duration_seconds": metadata.get("duration_seconds"),
            "source_url": metadata.get("source_url"),
            "license": metadata.get("license"),
            "review_state": "pending",
            "reviewer": None,
            "events": [],
            "allowed_labels": sorted(EVENT_LABELS),
            "event_schema": {
                "start_seconds": "inclusive event start",
                "end_seconds": "exclusive event end",
                "label": "SAFE, NEAR, or CONTACT",
                "evidence": "Human-observed visual evidence and correction notes; bounding-box overlap alone is not evidence of CONTACT.",
            },
        }
        write_json(path, template)
        templates.append(path.relative_to(ROOT).as_posix())
    return {"created": len(templates), "files": templates}


def validate_event_file(path: Path) -> dict:
    data = read_json(path)
    if data.get("schema_version") != 1 or not data.get("recording_session_id"):
        raise ValueError("Event annotation needs schema_version=1 and recording_session_id.")
    duration = float(data.get("duration_seconds") or 0)
    seen = []
    for index, event in enumerate(data.get("events", [])):
        label = event.get("label")
        start = float(event.get("start_seconds", -1))
        end = float(event.get("end_seconds", -1))
        if label not in EVENT_LABELS:
            raise ValueError(f"Event {index} has invalid label {label!r}.")
        if start < 0 or end <= start or (duration > 0 and end > duration):
            raise ValueError(f"Event {index} has invalid interval [{start}, {end}].")
        if not event.get("evidence"):
            raise ValueError(f"Event {index} must have human visual evidence/correction notes.")
        if label == "CONTACT" and not event.get("reviewed_by"):
            raise ValueError(f"CONTACT event {index} requires an explicit human reviewer.")
        seen.append(event)
    if data.get("review_state") == "reviewed" and not data.get("reviewer"):
        raise ValueError("Reviewed event file is missing reviewer identity.")
    return {
        "valid": True,
        "session_id": data["recording_session_id"],
        "review_state": data.get("review_state", "pending"),
        "reviewer": data.get("reviewer"),
        "events": len(seen),
        "labels": dict(Counter(event["label"] for event in seen)),
    }


def custom_readiness_report() -> dict:
    annotation = _annotation_manifest()
    validation = validate_labelme_tasks()
    split_data = read_json(SPLIT_MANIFEST, {"splits": {"train": [], "val": [], "test": []}, "meaningful_evaluation": False})
    event_files = sorted((ANNOTATED / "events").glob("*.json")) if (ANNOTATED / "events").exists() else []
    events = []
    invalid_events = []
    for path in event_files:
        try:
            events.append(validate_event_file(path))
        except Exception as exc:
            invalid_events.append({"path": path.relative_to(ROOT).as_posix(), "error": str(exc)})
    pilot_path = DATASET / "public/open_images/reports/open_images_pilot_report.json"
    pilot = read_json(pilot_path) if pilot_path.exists() else {}
    reviewed_class_counts = validation["reviewed_polygon_counts"]
    minimum_target_counts = {name: reviewed_class_counts.get(name, 0) for name in TARGET_CLASS_IDS}
    reviewed_event_files = [row for row in events if row["review_state"] == "reviewed"]
    event_counts = Counter(
        label
        for event_file in reviewed_event_files
        for label, count in event_file["labels"].items()
        for _ in range(count)
    )
    event_coverage = {label: event_counts.get(label, 0) for label in sorted(EVENT_LABELS)}
    reviewed_tasks = [task for task in annotation["tasks"] if task.get("annotation_state") == "reviewed"]
    completeness_confirmed = bool(reviewed_tasks) and all(
        task.get("annotation_completeness_verified") is True for task in reviewed_tasks
    )
    provenance = acquire.provenance_check()
    training_ready = (
        all(count >= 10 for count in minimum_target_counts.values())
        and completeness_confirmed
        and all(event_coverage.values())
        and split_data.get("meaningful_evaluation", False)
        and not split_data.get("hash_leakage", False)
        and not validation["invalid_reviewed_tasks"]
        and not invalid_events
        and not provenance["custom_without_provenance"]
    )
    training_readiness_reason = (
        "Reviewed polygon classes, completeness attestations, event labels, source-group splits, and provenance meet the workflow minimums."
        if training_ready
        else "Not ready: need at least 10 reviewed polygons per target class, scene-completeness attestations, reviewed SAFE/NEAR/CONTACT labels, independent source-group splits with minimum counts, no hash leakage, valid provenance and no malformed reviewed annotations. Open Images has no painting/hand masks or artwork-contact labels."
    )
    report = {
        "generated_at_utc": utc_now(),
        "custom_recording_sessions": len(list(RAW_VIDEOS.glob("*.avi"))) + len(list(RAW_VIDEOS.glob("*.mp4"))),
        "custom_extracted_frames": sum(1 for path in EXTRACTED_FRAMES.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        "annotation_tasks": validation,
        "minimum_target_polygon_counts": minimum_target_counts,
        "all_reviewed_scenes_completeness_confirmed": completeness_confirmed,
        "event_files": len(event_files),
        "valid_event_files": events,
        "invalid_event_files": invalid_events,
        "reviewed_event_label_counts": event_coverage,
        "custom_split_counts": split_data.get("image_counts", {name: len(rows) for name, rows in split_data.get("splits", {}).items()}),
        "source_groups": split_data.get("source_groups", 0),
        "duplicate_hash_groups": split_data.get("duplicate_image_hash_groups", 0),
        "split_hash_leakage": split_data.get("hash_leakage", False),
        "meaningful_evaluation_split": split_data.get("meaningful_evaluation", False),
        "custom_provenance": {
            "custom_images": provenance["custom_images"],
            "custom_masks": provenance["custom_masks"],
            "files_without_provenance": len(provenance["custom_without_provenance"]),
        },
        "open_images_pilot": {
            "images": pilot.get("actual_images_downloaded", 0),
            "valid_masks_by_class": pilot.get("valid_segmentation_masks_by_source_class", {}),
            "bbox_only_instances": pilot.get("bounding_box_only_instances_by_source_class", {}),
            "training_ready": pilot.get("training_ready", False),
        },
        "missing_work": [
            "Record consented, representative museum/gallery webcam sessions, including SAFE and NEAR cases.",
            "Human-review LabelMe polygons for painting, person, hand, and tool; Open Images does not supply painting or hand masks.",
            "Manually review SAFE/NEAR/CONTACT intervals; do not infer contact from box overlap.",
            "Collect independent recording sessions for train, validation, and test; one session must never cross splits.",
            "Resolve tool taxonomy, annotation completeness policy, and class balance from real recordings.",
        ],
        "training_ready": training_ready,
        "training_readiness_reason": training_readiness_reason,
    }
    write_json(CUSTOM_REPORT, report)
    training_lines = [
        "# Training Readiness", "", f"Generated (UTC): {report['generated_at_utc']}", "",
        f"Ready for custom YOLO segmentation training: **{str(report['training_ready']).lower()}**.",
        report["training_readiness_reason"], "",
        "## Public Open Images Pilot", "",
        f"Actual validation JPEGs: {report['open_images_pilot']['images']}; source mask instances: `{json.dumps(report['open_images_pilot']['valid_masks_by_class'], ensure_ascii=False)}`.",
        f"Target bbox-only instances: `{json.dumps(report['open_images_pilot']['bbox_only_instances'], ensure_ascii=False)}`.",
        "Painting mask: missing. Human hand mask: missing; boxes only. Person and generic tool masks do not provide artwork-contact event labels.",
        "The public pilot stays in `dataset/public/open_images/`; it is not mixed into custom training splits.", "",
        "## Custom Annotation Status", "",
        f"Recording sessions: {report['custom_recording_sessions']}; extracted frames: {report['custom_extracted_frames']}; LabelMe tasks: {report['annotation_tasks']['tasks']}; annotation states: `{json.dumps(report['annotation_tasks']['states'])}`.",
        f"Reviewed polygons by class: `{json.dumps(report['annotation_tasks']['reviewed_polygon_counts'])}`; minimum target counts: `{json.dumps(report['minimum_target_polygon_counts'])}`.",
        f"Scene-completeness confirmed: {report['all_reviewed_scenes_completeness_confirmed']}; reviewed event label counts: `{json.dumps(report['reviewed_event_label_counts'])}`; invalid event files: {len(report['invalid_event_files'])}.",
        f"Custom split counts: `{json.dumps(report['custom_split_counts'])}`; source groups: {report['source_groups']}; duplicate hash groups: {report['duplicate_hash_groups']}; split hash leakage: {report['split_hash_leakage']}.",
        f"Meaningful evaluation split: {report['meaningful_evaluation_split']}; custom files without provenance: {report['custom_provenance']['files_without_provenance']}.",
        f"Training ready: **{str(report['training_ready']).lower()}**. {report['training_readiness_reason']}", "",
        "## Remaining Work", "",
        *[f"- {item}" for item in report["missing_work"]],
    ]
    (ROOT / "docs/TRAINING_READINESS.md").write_text("\n".join(training_lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Webcam-first custom recording and reviewed annotation workflow.")
    commands = parser.add_subparsers(dest="command", required=True)
    record_parser = commands.add_parser("record-webcam", help="Record a real webcam session to custom/raw_videos.")
    record_parser.add_argument("--duration", type=float, required=True)
    record_parser.add_argument("--camera-index", type=int, default=DEFAULT_CAMERA_INDEX)
    record_parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    record_parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    record_parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    record_parser.add_argument("--backend", choices=["auto", "dshow", "msmf", "default"], default=DEFAULT_CAMERA_BACKEND)
    record_parser.add_argument("--session-id")
    record_parser.add_argument("--no-preview", action="store_true")
    extract_parser = commands.add_parser("extract-frames", help="Extract timestamped frames from a custom recorded video.")
    extract_parser.add_argument("video", type=Path)
    extract_parser.add_argument("--sample-seconds", type=float, default=2.0)
    commands.add_parser("prepare-labelme", help="Create empty, pending LabelMe polygon tasks for extracted custom frames.")
    review_parser = commands.add_parser("set-annotation-state", help="Set pending/proposed/reviewed/rejected state for one LabelMe task.")
    review_parser.add_argument("annotation_file")
    review_parser.add_argument("--state", choices=["pending", "proposed_unverified", "reviewed", "rejected"], required=True)
    review_parser.add_argument("--reviewer")
    review_parser.add_argument("--notes", default="")
    review_parser.add_argument("--verified-empty", action="store_true", help="Mark as a human-reviewed negative image with no target instances visible.")
    review_parser.add_argument("--complete-scene-reviewed", action="store_true", help="Attest that all visible target instances were labeled under the annotation policy.")
    open_parser = commands.add_parser("open-labelme", help="Open one prepared image in LabelMe with its task JSON and fixed target class list.")
    open_parser.add_argument("annotation_file")
    commands.add_parser("validate-annotations", help="Validate reviewed polygons and report review states.")
    split_parser = commands.add_parser("split-reviewed", help="Build source-session-grouped train/val/test splits from reviewed polygons only.")
    split_parser.add_argument("--seed", default="pbl4-custom-v1")
    commands.add_parser("convert-yolo", help="Convert only reviewed LabelMe polygon tasks using the grouped split manifest.")
    commands.add_parser("event-templates", help="Create separate SAFE/NEAR/CONTACT review templates for recorded sessions.")
    event_parser = commands.add_parser("validate-events", help="Validate event intervals and human review evidence.")
    event_parser.add_argument("files", nargs="*", type=Path)
    commands.add_parser("report", help="Generate custom annotation and training-readiness reports.")
    args = parser.parse_args()

    try:
        if args.command == "record-webcam":
            result = record_webcam(
                args.duration, args.camera_index, args.width, args.height, args.fps,
                args.backend, not args.no_preview, args.session_id,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.command == "extract-frames":
            print(json.dumps(extract_custom_frames(args.video, args.sample_seconds), indent=2, ensure_ascii=False))
        elif args.command == "prepare-labelme":
            print(json.dumps(prepare_labelme_tasks(), indent=2, ensure_ascii=False))
        elif args.command == "open-labelme":
            launch_labelme(args.annotation_file)
        elif args.command == "set-annotation-state":
            task = update_annotation_state(
                args.annotation_file, args.state, args.reviewer, args.notes,
                args.verified_empty, args.complete_scene_reviewed,
            )
            print(json.dumps(task, indent=2, ensure_ascii=False))
        elif args.command == "validate-annotations":
            print(json.dumps(validate_labelme_tasks(), indent=2, ensure_ascii=False))
        elif args.command == "split-reviewed":
            print(json.dumps(build_grouped_splits(args.seed), indent=2, ensure_ascii=False))
        elif args.command == "convert-yolo":
            print(json.dumps(convert_reviewed_to_yolo(), indent=2, ensure_ascii=False))
        elif args.command == "event-templates":
            print(json.dumps(create_event_templates(), indent=2, ensure_ascii=False))
        elif args.command == "validate-events":
            paths = args.files or sorted((ANNOTATED / "events").glob("*.json"))
            results = [validate_event_file(path) for path in paths]
            print(json.dumps({"valid": len(results), "files": results}, indent=2, ensure_ascii=False))
        elif args.command == "report":
            report = custom_readiness_report()
            acquire.run_validation()
            print(json.dumps(report, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Custom dataset workflow error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())