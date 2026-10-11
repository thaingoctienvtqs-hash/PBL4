import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tools import custom_dataset as custom
from tools import dataset_acquire as acquire


def set_roots(monkeypatch, tmp_path):
    root = tmp_path / "dữ liệu PBL"
    dataset = root / "dataset"
    monkeypatch.setattr(custom, "ROOT", root)
    monkeypatch.setattr(custom, "DATASET", dataset)
    monkeypatch.setattr(acquire, "ROOT", root)
    monkeypatch.setattr(acquire, "DATASET", dataset)
    monkeypatch.setattr(acquire, "MANIFEST", dataset / "metadata/acquisition_manifest.json")
    monkeypatch.setattr(acquire, "REPORT_JSON", dataset / "reports/dataset_report.json")
    monkeypatch.setattr(acquire, "REPORT_MD", root / "docs/DATASET_REPORT.md")
    monkeypatch.setattr(custom, "RAW_VIDEOS", dataset / "custom/raw_videos")
    monkeypatch.setattr(custom, "EXTRACTED_FRAMES", dataset / "custom/extracted_frames")
    monkeypatch.setattr(custom, "ANNOTATED", dataset / "custom/annotated")
    monkeypatch.setattr(custom, "PREPARED", dataset / "custom/prepared")
    monkeypatch.setattr(custom, "CUSTOM_METADATA", dataset / "custom/metadata")
    monkeypatch.setattr(custom, "ANNOTATION_MANIFEST", dataset / "custom/metadata/annotation_manifest.json")
    monkeypatch.setattr(custom, "SPLIT_MANIFEST", dataset / "custom/splits/source_groups.json")
    monkeypatch.setattr(custom, "CUSTOM_REPORT", dataset / "custom/reports/custom_readiness.json")
    return root, dataset


def write_test_image(path: Path, width=32, height=24, color=80):
    image = np.full((height, width, 3), color, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    custom.write_image_unicode(path, image)


def test_unicode_safe_image_roundtrip_and_duplicate_protection(tmp_path):
    path = tmp_path / "nghệ thuật" / "ảnh thử.jpg"
    write_test_image(path)

    decoded = custom.read_image_unicode(path)

    assert decoded.shape == (24, 32, 3)
    with pytest.raises(FileExistsError):
        custom.write_image_unicode(path, decoded)


def test_webcam_recorder_writes_session_video_and_metadata(monkeypatch, tmp_path):
    _, dataset = set_roots(monkeypatch, tmp_path)

    class FakeSource:
        kind = "webcam"
        active_backend = "dshow"
        is_open = True

        def open(self):
            return True

        def read(self):
            return SimpleNamespace(frame=np.full((24, 32, 3), 100, dtype=np.uint8))

        def release(self):
            pass

    class FakeWriter:
        def __init__(self, path, fourcc, fps, size):
            self.path = Path(path)
            self.frames = 0

        def isOpened(self):
            return True

        def write(self, frame):
            self.frames += 1

        def release(self):
            self.path.write_bytes(b"test video bytes")

    monkeypatch.setattr(custom, "build_camera_source", lambda *args, **kwargs: FakeSource())
    monkeypatch.setattr(custom.cv2, "VideoWriter", FakeWriter)

    metadata = custom.record_webcam(0.01, 0, 32, 24, 15, "dshow", False, "test-session")

    video = dataset / "custom/raw_videos/test-session.avi"
    sidecar = json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
    assert video.is_file()
    assert metadata["frames_written"] > 0
    assert sidecar["recording_session_id"] == "test-session"
    assert sidecar["camera_backend"] == "dshow"
    assert sidecar["width"] == 32 and sidecar["height"] == 24
    assert sidecar["video_sha256"] == custom.file_sha256(video)


def test_labelme_tasks_start_pending_and_link_to_source_group(monkeypatch, tmp_path):
    root, dataset = set_roots(monkeypatch, tmp_path)
    image_path = dataset / "custom/extracted_frames/session-1/frame_000001_0002000ms.jpg"
    write_test_image(image_path)
    frames_manifest = dataset / "custom/extracted_frames/session-1/frames_manifest.json"
    acquire.write_json(frames_manifest, {
        "source_identifier": "session-1",
        "source_url": "local://webcam/session-1",
        "video_path": "dataset/custom/raw_videos/session-1.avi",
        "frames": [{"path": image_path.relative_to(root).as_posix(), "timestamp_seconds": 2.0}],
    })

    result = custom.prepare_labelme_tasks()

    assert result["created"] == 1
    task = result["tasks"][0]
    assert task["annotation_state"] == "pending"
    assert task["source_group_id"] == "session-1"
    annotation = json.loads((root / task["annotation_file"]).read_text(encoding="utf-8"))
    assert annotation["shapes"] == []
    assert (root / task["annotation_file"]).parent.joinpath(annotation["imagePath"]).resolve() == image_path.resolve()


def test_custom_frame_extraction_uses_unicode_safe_image_writer(monkeypatch, tmp_path):
    root, dataset = set_roots(monkeypatch, tmp_path)
    video = dataset / "custom/raw_videos/session-unicode.avi"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"mock video")
    acquire.write_json(video.with_suffix(".json"), {
        "source_url": "local://webcam/session-unicode",
        "license": "Custom operator recording",
        "attribution": "Operator",
        "source_identifier": "session-unicode",
        "original_filename": video.name,
        "recorded_at_utc": "2026-10-10T00:00:00+00:00",
        "permission_verified": True,
        "intended_use_permitted": True,
    })

    class FakeCapture:
        def __init__(self, _path):
            self.position = 0

        def isOpened(self):
            return True

        def get(self, prop):
            return {
                cv2.CAP_PROP_FPS: 2.0,
                cv2.CAP_PROP_FRAME_COUNT: 8,
                cv2.CAP_PROP_FRAME_WIDTH: 32,
                cv2.CAP_PROP_FRAME_HEIGHT: 24,
            }[prop]

        def set(self, _prop, value):
            self.position = int(value // 1000 * 2)
            return True

        def read(self):
            return True, np.full((24, 32, 3), min(255, 50 + self.position), dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)

    result = custom.extract_custom_frames(video, 2.0)

    assert result["frame_count"] == 2
    for frame in result["frames"]:
        frame_path = root / frame["path"]
        assert custom.read_image_unicode(frame_path).shape == (24, 32, 3)
        assert frame["source_identifier"] == "session-unicode"
    provenance = [json.loads(row) for row in (dataset / "metadata/provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(row["source_identifier"] == "session-unicode" for row in provenance)


def test_frame_extraction_records_and_skips_duplicate_samples(monkeypatch, tmp_path):
    _, dataset = set_roots(monkeypatch, tmp_path)
    video = dataset / "custom/raw_videos/repeated-frame.avi"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"mock video")
    acquire.write_json(video.with_suffix(".json"), {
        "source_url": "local://webcam/repeated-frame",
        "license": "Custom operator recording",
        "attribution": "Operator",
        "source_identifier": "repeated-session",
        "original_filename": video.name,
        "recorded_at_utc": "2026-10-10T00:00:00+00:00",
        "permission_verified": True,
        "intended_use_permitted": True,
    })

    class FakeCapture:
        def __init__(self, _path):
            pass

        def isOpened(self):
            return True

        def get(self, prop):
            return {
                cv2.CAP_PROP_FPS: 2.0,
                cv2.CAP_PROP_FRAME_COUNT: 8,
                cv2.CAP_PROP_FRAME_WIDTH: 32,
                cv2.CAP_PROP_FRAME_HEIGHT: 24,
            }[prop]

        def set(self, _prop, _value):
            return True

        def read(self):
            return True, np.full((24, 32, 3), 99, dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)

    result = custom.extract_custom_frames(video, 2.0)

    assert result["frame_count"] == 1
    assert len(result["duplicate_sample_timestamps"]) == 1
    assert result["duplicate_sample_timestamps"][0]["duplicate_of"] == result["frames"][0]["path"]


def _write_reviewed_task(root: Path, dataset: Path, image_name: str, source_group: str, image_bytes: bytes | None = None):
    image_path = dataset / "custom/extracted_frames" / source_group / image_name
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if image_bytes is None:
        image = np.full((24, 32, 3), 90, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image_bytes = encoded.tobytes()
    image_path.write_bytes(image_bytes)
    annotation_path = dataset / "custom/annotated/labelme" / source_group / f"{Path(image_name).stem}.json"
    acquire.write_json(annotation_path, {
        "version": "5.8.1", "flags": {}, "imagePath": "../../../extracted_frames/" + source_group + "/" + image_name,
        "imageData": None, "imageHeight": 24, "imageWidth": 32,
        "shapes": [{"label": "painting", "points": [[2, 2], [28, 2], [28, 20], [2, 20]], "shape_type": "polygon", "flags": {}}],
    })
    return {
        "annotation_file": annotation_path.relative_to(root).as_posix(),
        "image_path": image_path.relative_to(root).as_posix(),
        "image_sha256": custom.file_sha256(image_path),
        "image_width": 32,
        "image_height": 24,
        "source_group_id": source_group,
        "annotation_state": "reviewed",
        "reviewer": "human-reviewer",
        "reviewed_at_utc": "2026-10-10T00:00:00+00:00",
    }


def test_reviewed_polygon_conversion_requires_review_state(monkeypatch, tmp_path):
    root, dataset = set_roots(monkeypatch, tmp_path)
    task = _write_reviewed_task(root, dataset, "frame.jpg", "session-a")
    task["annotation_state"] = "proposed_unverified"
    acquire.write_json(custom.ANNOTATION_MANIFEST, {"schema_version": 1, "tasks": [task]})

    assert custom.validate_labelme_tasks()["reviewed_polygon_counts"] == {}
    assert custom.build_grouped_splits()["unique_images"] == 0


def test_source_grouped_split_keeps_duplicate_hashes_together(monkeypatch, tmp_path):
    root, dataset = set_roots(monkeypatch, tmp_path)
    shared_bytes = None
    tasks = []
    for index, session in enumerate(("s1", "s2", "s3", "s4")):
        if session == "s2":
            same_bytes = shared_bytes
        elif session in {"s3", "s4"}:
            image = np.full((24, 32, 3), 120 if session == "s3" else 150, dtype=np.uint8)
            ok, encoded = cv2.imencode(".jpg", image)
            assert ok
            same_bytes = encoded.tobytes()
        else:
            same_bytes = None
        task = _write_reviewed_task(root, dataset, f"frame-{index}.jpg", session, same_bytes)
        tasks.append(task)
        if session == "s1":
            shared_bytes = (root / task["image_path"]).read_bytes()
    acquire.write_json(custom.ANNOTATION_MANIFEST, {"schema_version": 1, "tasks": tasks})

    splits = custom.build_grouped_splits("fixed-seed")

    assert splits["source_groups"] == 3
    assert splits["duplicate_image_hash_groups"] == 1
    assert splits["duplicate_images_excluded"] == 1
    locations = {}
    for split, rows in splits["splits"].items():
        for row in rows:
            locations.setdefault(row["image_sha256"], set()).add(split)
    assert all(len(split_names) == 1 for split_names in locations.values())
    assert splits["hash_leakage"] is False


def test_human_reviewed_empty_frame_is_valid_negative(monkeypatch, tmp_path):
    root, dataset = set_roots(monkeypatch, tmp_path)
    task = _write_reviewed_task(root, dataset, "empty.jpg", "session-empty")
    annotation_path = root / task["annotation_file"]
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    annotation["shapes"] = []
    acquire.write_json(annotation_path, annotation)
    task["image_sha256"] = custom.file_sha256(root / task["image_path"])
    task["verified_empty"] = True
    acquire.write_json(custom.ANNOTATION_MANIFEST, {"schema_version": 1, "tasks": [task]})

    validation = custom.validate_labelme_tasks()
    split = custom.build_grouped_splits("verified-negative")

    assert validation["invalid_reviewed_tasks"] == []
    assert split["image_counts"] == {"train": 1, "val": 0, "test": 0}


def test_yolo_conversion_writes_only_reviewed_polygons(monkeypatch, tmp_path):
    root, dataset = set_roots(monkeypatch, tmp_path)
    task = _write_reviewed_task(root, dataset, "frame.jpg", "session-a")
    acquire.write_json(custom.ANNOTATION_MANIFEST, {"schema_version": 1, "tasks": [task]})
    custom.build_grouped_splits("one-group")

    result = custom.convert_reviewed_to_yolo()

    assert result["converted_images_by_split"] == {"train": 1}
    label = dataset / "custom/prepared/labels/train/session-a/frame.txt"
    row = label.read_text(encoding="utf-8").strip().split()
    assert row[0] == "0"
    assert len(row[1:]) == 8
    assert all(0 <= float(point) <= 1 for point in row[1:])
    provenance_path = dataset / "metadata/provenance.jsonl"
    provenance = [json.loads(line) for line in provenance_path.read_text(encoding="utf-8").splitlines()]
    assert any(item["path"] == "dataset/custom/prepared/images/train/session-a/frame.jpg" for item in provenance)


def test_contact_event_requires_human_review_evidence(tmp_path):
    event_file = tmp_path / "session.events.json"
    acquire.write_json(event_file, {
        "schema_version": 1,
        "recording_session_id": "session-1",
        "duration_seconds": 10,
        "review_state": "reviewed",
        "reviewer": "reviewer",
        "events": [{"start_seconds": 1, "end_seconds": 2, "label": "CONTACT", "evidence": "visible hand touches frame", "reviewed_by": "reviewer"}],
    })
    assert custom.validate_event_file(event_file)["labels"] == {"CONTACT": 1}
    event = json.loads(event_file.read_text(encoding="utf-8"))
    event["events"][0].pop("reviewed_by")
    acquire.write_json(event_file, event)
    with pytest.raises(ValueError, match="explicit human reviewer"):
        custom.validate_event_file(event_file)