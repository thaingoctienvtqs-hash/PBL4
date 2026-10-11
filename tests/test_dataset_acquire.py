import hashlib
import io
import json
from pathlib import Path

import pytest

from tools import dataset_acquire as acquire


def set_dataset_roots(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    dataset = root / "dataset"
    monkeypatch.setattr(acquire, "ROOT", root)
    monkeypatch.setattr(acquire, "DATASET", dataset)
    monkeypatch.setattr(acquire, "MANIFEST", dataset / "metadata/acquisition_manifest.json")
    monkeypatch.setattr(acquire, "REPORT_JSON", dataset / "reports/dataset_report.json")
    monkeypatch.setattr(acquire, "REPORT_MD", root / "docs/DATASET_REPORT.md")


def test_contacthands_download_is_disabled_until_rights_are_verified():
    assert acquire.SOURCES["contacthands"]["assets"] == {}


def test_manifest_reconciliation_marks_duplicate_successes_and_verified_failures(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    relative_path = "dataset/public/metmuseum/images/438467.jpg"
    path = acquire.ROOT / relative_path
    path.parent.mkdir(parents=True)
    content = b"validated image bytes"
    path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    manifest = {"downloads": [
        {"path": relative_path, "status": "validated", "sha256": checksum, "downloaded_at_utc": "first"},
        {"path": relative_path, "status": "failed", "asset_id": "artwork_438467"},
        {"path": relative_path, "status": "validated", "sha256": checksum, "downloaded_at_utc": "latest"},
    ]}

    counts = acquire.reconcile_download_history(manifest)

    assert counts == {
        "superseded_duplicate_successes": 1,
        "recovered_failures": 1,
        "updated_rows_this_run": 2,
    }
    assert [row["status"] for row in manifest["downloads"]] == [
        "superseded_duplicate", "recovered", "validated",
    ]
    assert manifest["downloads"][1]["recovered_by_sha256"] == checksum


def test_only_catalogued_https_downloads_are_accepted():
    with pytest.raises(ValueError, match="Unknown source asset"):
        acquire.download_asset("open_images", "arbitrary_url")
    with pytest.raises(ValueError, match="Only HTTPS"):
        acquire.request("http://example.org/data")


def test_vcoco_json_validator_reports_action_classes(tmp_path):
    path = tmp_path / "vcoco.json"
    path.write_text(
        json.dumps([{
            "image_id": [1], "ann_id": [2], "role_object_id": [[3, 4]],
            "label": [1], "action_name": "hold", "role_name": ["obj"], "include": [1],
        }]),
        encoding="utf-8",
    )

    result = acquire.validate_json(path, "vcoco-json")

    assert result["actions"] == 1
    assert result["action_names"] == ["hold"]


def test_open_images_source_class_capabilities_separate_masks_from_boxes():
    capabilities = acquire.open_images_class_capabilities(
        {"person", "human hand", "tool", "mobile phone", "pen", "picture frame"},
        {"person", "mobile phone", "pen", "picture frame"},
    )

    assert capabilities["person"]["instance_mask_annotation_available"] is True
    assert capabilities["hand"]["box_annotation_available"] is True
    assert capabilities["hand"]["instance_mask_annotation_available"] is False
    assert capabilities["painting"]["box_annotation_available"] is False
    assert capabilities["painting"]["instance_mask_annotation_available"] is False
    assert capabilities["tool"]["mask_classes_available"] == ["Mobile phone", "Pen"]
    assert capabilities["picture_frame_not_painting"]["mapped_to_painting"] is False


def test_open_images_pilot_selection_uses_masks_and_box_only_hand_rows():
    names = {"person": "Person", "phone": "Mobile phone", "pen": "Pen", "hand": "Human hand"}
    mask_rows = []
    image_id = 1
    for class_id in ("person", "phone", "pen"):
        for _ in range(80):
            mask_rows.append({"ImageID": f"{image_id:016x}", "LabelName": class_id})
            image_id += 1
    box_rows = []
    for _ in range(30):
        box_rows.append({"ImageID": f"{image_id:016x}", "LabelName": "hand"})
        image_id += 1
    eligible = {row["ImageID"] for row in mask_rows + box_rows}

    selected, reasons = acquire._select_open_images_ids(mask_rows, box_rows, names, eligible, 100)
    second_selection, _ = acquire._select_open_images_ids(mask_rows, box_rows, names, eligible, 100)

    assert len(selected) == 100
    assert selected == second_selection
    assert sum(reason == "box-only:Human hand" for reason in reasons.values()) == 10
    assert any(reason == "mask:Mobile phone" for reason in reasons.values())
    assert any(reason == "mask:Pen" for reason in reasons.values())


def test_open_images_license_filter_requires_per_image_cc_by_metadata():
    image_info = {
        "Subset": "validation",
        "License": "https://creativecommons.org/licenses/by/2.0/",
        "OriginalLandingURL": "https://www.flickr.com/photos/author/1",
        "OriginalURL": "https://farm.example/image.jpg",
    }
    assert acquire._is_valid_open_images_license(image_info)
    assert not acquire._is_valid_open_images_license({**image_info, "License": "unknown"})
    assert not acquire._is_valid_open_images_license({**image_info, "OriginalLandingURL": ""})


def test_open_images_image_and_mask_validation_support_unicode_paths(tmp_path):
    import cv2
    import numpy as np

    image_dir = tmp_path / "năm 3" / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "image.jpg.part"
    ok, image_bytes = cv2.imencode(".jpg", np.full((12, 16, 3), 127, dtype=np.uint8))
    assert ok
    image_path.write_bytes(image_bytes.tobytes())

    mask_path = image_dir / "mask.png"
    mask = np.zeros((12, 16), dtype=np.uint8)
    mask[2:10, 3:13] = 255
    ok, mask_bytes = cv2.imencode(".png", mask)
    assert ok
    mask_path.write_bytes(mask_bytes.tobytes())

    assert acquire._validate_downloaded_image(image_path)["valid"]
    assert acquire._validate_binary_mask(mask_path)["valid"]


def test_mask_alignment_preserves_source_and_uses_nearest_neighbor(tmp_path):
    import cv2
    import numpy as np

    source_path = tmp_path / "năm 3" / "source.png"
    image_path = tmp_path / "năm 3" / "image.jpg"
    aligned_path = tmp_path / "năm 3" / "aligned.png"
    source_path.parent.mkdir(parents=True)
    mask = np.zeros((8, 12), dtype=np.uint8)
    mask[2:6, 3:9] = 255
    ok, encoded_mask = cv2.imencode(".png", mask)
    assert ok
    source_bytes = encoded_mask.tobytes()
    source_path.write_bytes(source_bytes)
    ok, encoded_image = cv2.imencode(".jpg", np.full((16, 24, 3), 127, dtype=np.uint8))
    assert ok
    image_path.write_bytes(encoded_image.tobytes())

    result = acquire._align_binary_mask_to_image(source_path, image_path, aligned_path, "0.0")

    assert result["resized_nearest_neighbor"] is True
    assert (result["height"], result["width"]) == (16, 24)
    assert source_path.read_bytes() == source_bytes
    assert acquire._validate_binary_mask(aligned_path)["valid"]
    with pytest.raises(ValueError, match="Non-zero source image rotation"):
        acquire._align_binary_mask_to_image(source_path, image_path, tmp_path / "rotated.png", "90")


def test_download_validates_csv_and_records_checksum(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    content = b"LabelName,DisplayName\n/m/1,person\n"
    monkeypatch.setattr(acquire, "remote_size", lambda url: len(content))

    class Response(io.BytesIO):
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(acquire, "request", lambda *args, **kwargs: Response(content))
    source = acquire.SOURCES["open_images"]
    original = source["assets"]["boxable_classes"]
    source["assets"]["boxable_classes"] = {
        **original,
        "filename": "pilot.csv",
        "destination": "public/open_images/metadata",
        "expected_size_bytes": len(content),
    }
    try:
        result = acquire.download_asset("open_images", "boxable_classes")
    finally:
        source["assets"]["boxable_classes"] = original

    expected_hash = hashlib.sha256(content).hexdigest()
    assert result["status"] == "validated"
    assert result["sha256"] == expected_hash
    assert result["validation"]["rows"] == 1
    manifest = json.loads(acquire.MANIFEST.read_text(encoding="utf-8"))
    assert manifest["downloads"][0]["sha256"] == expected_hash


def test_complete_partial_is_validated_and_promoted_without_redownload(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    content = b"LabelName,DisplayName\n/m/1,person\n"
    monkeypatch.setattr(acquire, "remote_size", lambda url: len(content))
    monkeypatch.setattr(acquire, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected network request")))
    source = acquire.SOURCES["open_images"]
    original = source["assets"]["boxable_classes"]
    source["assets"]["boxable_classes"] = {
        **original,
        "filename": "resumed.csv",
        "destination": "public/open_images/metadata",
        "expected_size_bytes": len(content),
    }
    partial = acquire.DATASET / "public/open_images/metadata/resumed.csv.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(content)
    try:
        result = acquire.download_asset("open_images", "boxable_classes")
    finally:
        source["assets"]["boxable_classes"] = original

    destination = acquire.DATASET / "public/open_images/metadata/resumed.csv"
    assert result["status"] == "validated"
    assert result["validation"]["rows"] == 1
    assert destination.read_bytes() == content
    assert not partial.exists()


def test_existing_untracked_file_is_never_overwritten(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    acquire.ensure_layout()
    path = acquire.DATASET / "public/open_images/metadata/oidv7-class-descriptions-boxable.csv"
    path.write_text("user data", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        acquire.download_asset("open_images", "boxable_classes")
    assert path.read_text(encoding="utf-8") == "user data"


def test_yolo_validator_distinguishes_boxes_from_polygons(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    images = acquire.DATASET / "custom/prepared/images/train"
    labels = acquire.DATASET / "custom/prepared/labels/train"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    (images / "person.jpg").write_bytes(b"not decoded by label validator")
    (labels / "person.txt").write_text(
        "1 0.5 0.5 0.2 0.2\n0 0.1 0.1 0.9 0.1 0.8 0.9\n3 2 0 0 1 1 0\n"
        "2 0.1 0.1 0.5 0.5 0.9 0.9\n1 0.9 0.5 0.4 0.4\n",
        encoding="utf-8",
    )

    result = acquire.validate_yolo_labels()

    assert result["box_only_rows"] == 1
    assert result["valid_segmentation_rows"] == 1
    assert result["malformed_rows"] == 3
    assert result["invalid_images"] == 1
    assert result["orphan_labels"] == 0
    assert result["class_counts"] == {"painting": 1, "person": 1}


def test_source_cannot_be_assigned_to_multiple_splits(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    acquire.assign_source_split("gallery-session-1", "train")
    with pytest.raises(ValueError, match="already assigned"):
        acquire.assign_source_split("gallery-session-1", "test")


def test_video_frame_extraction_requires_explicit_permission(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    video = acquire.DATASET / "custom/raw_videos/gallery.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"")
    video.with_suffix(".json").write_text(
        json.dumps({
            "source_url": "https://example.org/video",
            "license": "Example license",
            "attribution": "Example author",
            "source_identifier": "gallery-session",
            "original_filename": "gallery.mp4",
            "downloaded_at_utc": "2026-10-10T12:00:00+00:00",
            "permission_verified": False,
            "intended_use_permitted": True,
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="permission_verified=true"):
        acquire.extract_video_frames(video, 2.0)


def test_video_sidecar_requires_original_name_and_acquisition_date(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    video = acquire.DATASET / "custom/raw_videos/gallery.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"")
    video.with_suffix(".json").write_text(
        json.dumps({
            "source_url": "https://example.org/video",
            "license": "Example license",
            "attribution": "Example author",
            "source_identifier": "gallery-session",
            "permission_verified": True,
            "intended_use_permitted": True,
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="original_filename and downloaded_at_utc"):
        acquire.extract_video_frames(video, 2.0)


def test_open_images_inventory_matches_vocabulary_not_mask_availability(monkeypatch, tmp_path):
    set_dataset_roots(monkeypatch, tmp_path)
    metadata = acquire.DATASET / "public/open_images/metadata/oidv7-class-descriptions-boxable.csv"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        "LabelName,DisplayName\n/a,Person\n/b,Human hand\n/c,Painting\n/d,Picture frame\n",
        encoding="utf-8",
    )

    inventory = acquire.image_class_inventory()

    assert inventory["row_count"] == 4
    assert inventory["unique_class_names"] == 4
    assert inventory["target_name_matches"]["painting"] == ["painting"]
    assert inventory["target_name_matches"]["hand"] == ["human hand"]
    assert inventory["related_artwork_names_not_painting_labels"] == ["picture frame"]
    assert "not proof" in inventory["scope"]
