from pathlib import Path

import pytest

from tools import train_yolo
from tools.runtime_paths import project_path

validate_dataset_yaml = train_yolo.validate_dataset_yaml


def _make_dataset(root):
    import cv2
    import numpy as np

    splits = {name: [] for name in ("train", "val", "test")}
    groups = {name: [] for name in ("train", "val", "test")}
    by_image = {}
    for index, split in enumerate(("train", "val", "test")):
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        image_dir.mkdir(parents=True)
        label_dir.mkdir(parents=True)
        image_path = image_dir / f"{split}.jpg"
        image = np.full((24, 24, 3), index * 50, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        image_path.write_bytes(encoded.tobytes())
        (label_dir / f"{split}.txt").write_text("0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n", encoding="utf-8")
        relative = image_path.relative_to(root).as_posix()
        splits[split] = (Path(f"images/{split}"),)
        groups[split] = [f"source-{split}"]
        by_image[relative] = f"source-{split}"
    data = {
        "path": str(root),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {0: "person"},
        "source_groups": {**groups, "by_image": by_image},
    }
    yaml_path = root / "dataset.yaml"
    import yaml

    yaml_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return yaml_path


def test_dataset_validation_checks_masks_splits_and_groups(tmp_path):
    report = validate_dataset_yaml(_make_dataset(tmp_path))
    assert report["valid"]
    assert report["image_counts"] == {"train": 1, "val": 1, "test": 1}
    assert report["source_group_counts"] == {"train": 1, "val": 1, "test": 1}


def test_dataset_validation_rejects_source_group_leakage(tmp_path):
    yaml_path = _make_dataset(tmp_path)
    import yaml

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["source_groups"]["val"] = ["source-train"]
    data["source_groups"]["by_image"]["images/val/val.jpg"] = "source-train"
    yaml_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Source-group leakage"):
        validate_dataset_yaml(yaml_path)


def test_dataset_validation_rejects_missing_label_file(tmp_path):
    yaml_path = _make_dataset(tmp_path)
    (tmp_path / "labels/test/test.txt").unlink()
    with pytest.raises(FileNotFoundError, match="no label file"):
        validate_dataset_yaml(yaml_path)


def test_low_memory_training_stops_before_dataset_or_model_loading(monkeypatch, tmp_path):
    monkeypatch.setattr(train_yolo, "_system_memory", lambda: {
        "total_bytes": 8_000_000_000,
        "available_bytes": 900_000_000,
    })
    monkeypatch.setattr(
        train_yolo,
        "validate_dataset_yaml",
        lambda *_args, **_kwargs: pytest.fail("dataset validation must not start under the RAM gate"),
    )

    with pytest.raises(MemoryError, match="Training was stopped before dataset/model loading"):
        train_yolo.train(
            Path("missing.yaml"),
            model_path=Path("missing.pt"),
            project=Path("experiments"),
            name="should-not-start",
        )


def test_relative_project_paths_resolve_under_repository_root(tmp_path):
    resolved = project_path(Path("dataset/prepared/segmentation.yaml"), tmp_path)
    assert resolved == (tmp_path / "dataset/prepared/segmentation.yaml").resolve()


def test_low_memory_profile_defaults_disable_caching():
    assert train_yolo.TRAINING_CONFIG["image_size"] == 320
    assert train_yolo.TRAINING_CONFIG["batch_size"] == 1
    assert train_yolo.TRAINING_CONFIG["workers"] == 0
    assert train_yolo.TRAINING_CONFIG["cache"] is False

