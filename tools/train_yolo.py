from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.runtime_paths import configure_runtime_paths, project_path

configure_runtime_paths(ROOT)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _system_config() -> dict[str, Any]:
    with (ROOT / "configs/system.toml").open("rb") as stream:
        return tomllib.load(stream)


SYSTEM_CONFIG = _system_config()
TRAINING_CONFIG = SYSTEM_CONFIG.get("training", {})
MODEL_CONFIG = SYSTEM_CONFIG.get("model", {})
MIN_TRAINING_AVAILABLE_RAM = int(TRAINING_CONFIG.get("minimum_available_ram_bytes", 3_221_225_472))


def _load_dataset_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required; install the repository server requirements first.") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Dataset YAML must contain a mapping")
    return data


def _resolve_split(base: Path, value: Any) -> list[Path]:
    if not isinstance(value, (str, list)):
        raise ValueError("Each dataset split must be a directory, image-list path, or list of image paths")
    values = [value] if isinstance(value, str) else value
    paths: list[Path] = []
    for item in values:
        candidate = Path(str(item))
        candidate = candidate if candidate.is_absolute() else base / candidate
        if candidate.is_file() and candidate.suffix.lower() == ".txt":
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    listed = Path(line)
                    paths.append(listed if listed.is_absolute() else base / listed)
        elif candidate.is_dir():
            paths.extend(path for path in candidate.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
        elif candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            paths.append(candidate)
        else:
            raise FileNotFoundError(f"Dataset split path does not exist: {candidate}")
    return sorted({path.resolve() for path in paths})


def _label_path(image: Path) -> Path:
    parts = list(image.parts)
    indices = [index for index, part in enumerate(parts) if part.lower() == "images"]
    if indices:
        parts[indices[-1]] = "labels"
        return Path(*parts).with_suffix(".txt")
    return image.with_suffix(".txt")


def _validate_polygon_labels(path: Path, class_count: int) -> Counter[int]:
    counts: Counter[int] = Counter()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            values = [float(value) for value in line.split()]
            if len(values) < 7 or (len(values) - 1) % 2:
                raise ValueError("segmentation rows need a class ID and at least three x/y pairs")
            class_id = int(values[0])
            if values[0] != class_id or class_id < 0 or class_id >= class_count:
                raise ValueError("class ID is outside the declared class map")
            points = values[1:]
            if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in points):
                raise ValueError("polygon coordinates must be finite and normalized to [0, 1]")
            if len(set(zip(points[::2], points[1::2]))) < 3:
                raise ValueError("polygon must have at least three distinct points")
            counts[class_id] += 1
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Malformed polygon label {path}:{line_number}: {exc}") from exc
    return counts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_image_unicode(path: Path) -> np.ndarray | None:
    import cv2
    import numpy as np

    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None


def _system_memory() -> dict[str, int | None]:
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"total_bytes": int(status.ullTotalPhys), "available_bytes": int(status.ullAvailPhys)}
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        available = os.sysconf("SC_AVPHYS_PAGES")
        return {"total_bytes": int(page_size * pages), "available_bytes": int(page_size * available)}
    except (AttributeError, OSError, ValueError):
        return {"total_bytes": None, "available_bytes": None}


def validate_dataset_yaml(path: Path) -> dict[str, Any]:
    path = project_path(path, ROOT)
    data = _load_dataset_yaml(path)
    base = Path(str(data.get("path", path.parent)))
    if not base.is_absolute():
        base = path.parent / base
    base = base.resolve()
    names = data.get("names")
    if isinstance(names, list):
        names = {index: name for index, name in enumerate(names)}
    if not isinstance(names, dict) or not names:
        raise ValueError("Dataset YAML must declare a non-empty names mapping/list")
    class_ids = {int(key) for key in names}
    if class_ids != set(range(len(names))):
        raise ValueError("Class IDs must be contiguous and start at zero")

    split_images: dict[str, list[Path]] = {}
    split_class_counts: dict[str, Counter[int]] = {}
    image_hashes: dict[str, set[str]] = {}
    for split in ("train", "val", "test"):
        if split not in data:
            raise ValueError(f"Dataset YAML is missing required {split!r} split")
        images = _resolve_split(base, data[split])
        if not images:
            raise ValueError(f"Dataset split {split!r} is empty")
        counts: Counter[int] = Counter()
        hashes: set[str] = set()
        for image in images:
            if not image.is_file():
                raise FileNotFoundError(f"Dataset image does not exist: {image}")
            decoded = _read_image_unicode(image)
            if decoded is None or decoded.size == 0:
                raise ValueError(f"Dataset image is broken: {image}")
            labels = _label_path(image)
            if not labels.is_file():
                raise FileNotFoundError(f"Dataset image has no label file (use an empty file for reviewed negatives): {labels}")
            counts.update(_validate_polygon_labels(labels, len(names)))
            hashes.add(_sha256(image))
        split_images[split] = images
        split_class_counts[split] = counts
        image_hashes[split] = hashes

    leaks = {
        f"{left}/{right}": sorted(image_hashes[left] & image_hashes[right])
        for left, right in (("train", "val"), ("train", "test"), ("val", "test"))
        if image_hashes[left] & image_hashes[right]
    }
    if leaks:
        raise ValueError(f"Exact-image leakage across splits: {leaks}")

    source_groups = data.get("source_groups")
    if not isinstance(source_groups, dict) or any(split not in source_groups for split in ("train", "val", "test")):
        raise ValueError("Dataset YAML must include source_groups with train/val/test IDs for group-leakage checks")
    by_image = source_groups.get("by_image")
    if not isinstance(by_image, dict):
        raise ValueError("source_groups.by_image must map every relative image path to its source/video group ID")
    normalized_groups: dict[str, set[str]] = {}
    for split in ("train", "val", "test"):
        declared = {str(item) for item in source_groups[split]}
        if not declared:
            raise ValueError(f"source_groups.{split} must contain at least one source group")
        actual: set[str] = set()
        for image in split_images[split]:
            try:
                relative = image.relative_to(base).as_posix()
            except ValueError as exc:
                raise ValueError(f"Image is outside declared dataset root {base}: {image}") from exc
            group_id = by_image.get(relative)
            if group_id is None:
                raise ValueError(f"No source/video group is recorded for image {relative}")
            actual.add(str(group_id))
        if declared != actual:
            raise ValueError(f"source_groups.{split} does not match groups assigned to its actual images")
        normalized_groups[split] = actual
    group_leaks = {
        f"{left}/{right}": sorted(normalized_groups[left] & normalized_groups[right])
        for left, right in (("train", "val"), ("train", "test"), ("val", "test"))
        if normalized_groups[left] & normalized_groups[right]
    }
    if group_leaks:
        raise ValueError(f"Source-group leakage across splits: {group_leaks}")

    train_missing = [str(names[class_id]) for class_id in range(len(names)) if split_class_counts["train"][class_id] == 0]
    if train_missing:
        raise ValueError(f"No valid segmentation polygons for classes in train split: {train_missing}")
    return {
        "dataset_yaml": str(path),
        "classes": {str(key): str(value) for key, value in names.items()},
        "image_counts": {split: len(split_images[split]) for split in ("train", "val", "test")},
        "polygon_instance_counts": {
            split: {str(class_id): count for class_id, count in sorted(split_class_counts[split].items())}
            for split in ("train", "val", "test")
        },
        "source_group_counts": {split: len(normalized_groups[split]) for split in ("train", "val", "test")},
        "image_hash_leakage": leaks,
        "source_group_leakage": group_leaks,
        "valid": True,
    }


def _extract_metrics(metrics: Any) -> dict[str, Any]:
    import numpy as np

    output: dict[str, Any] = {}
    results = getattr(metrics, "results_dict", {})
    if isinstance(results, dict):
        for key, value in results.items():
            if isinstance(value, (int, float, np.number)):
                output[str(key)] = float(value)
    speed = getattr(metrics, "speed", None)
    if isinstance(speed, dict):
        output["speed_ms_per_image"] = {str(key): float(value) for key, value in speed.items()}
    return output


def train(
    data_yaml: Path,
    *,
    model_path: Path,
    project: Path,
    name: str,
    epochs: int = int(TRAINING_CONFIG.get("epochs", 20)),
    image_size: int = int(TRAINING_CONFIG.get("image_size", 320)),
    batch: int = int(TRAINING_CONFIG.get("batch_size", 1)),
    workers: int = int(TRAINING_CONFIG.get("workers", 0)),
    device: str = str(TRAINING_CONFIG.get("device", "cpu")),
    seed: int = int(TRAINING_CONFIG.get("seed", 42)),
    learning_rate: float = float(TRAINING_CONFIG.get("learning_rate", 0.001)),
    augment: bool = True,
    fraction: float = 1.0,
) -> dict[str, Any]:
    memory = _system_memory()
    if device.lower() != "cpu":
        raise RuntimeError("The safe training path currently supports CPU only; accelerator memory has not been verified.")
    available = memory["available_bytes"]
    if available is None or available < MIN_TRAINING_AVAILABLE_RAM:
        available_text = "unknown" if available is None else f"{available:,}"
        raise MemoryError(
            f"Only {available_text} bytes of RAM are available; this low-memory CPU training profile requires "
            f"at least {MIN_TRAINING_AVAILABLE_RAM:,} bytes ({MIN_TRAINING_AVAILABLE_RAM / 1024**3:.2f} GiB). "
            "Training was stopped before dataset/model loading."
        )
    if not 0.0 < fraction <= 1.0 or not math.isfinite(fraction):
        raise ValueError("fraction must be greater than 0 and at most 1")
    if learning_rate <= 0 or not math.isfinite(learning_rate):
        raise ValueError("learning_rate must be a positive finite value")
    data_yaml = project_path(data_yaml, ROOT)
    model_path = project_path(model_path, ROOT)
    project = project_path(project, ROOT)
    validation = validate_dataset_yaml(data_yaml)
    if not model_path.is_file():
        raise FileNotFoundError(f"Pretrained checkpoint does not exist locally: {model_path}")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Ultralytics is required; install the repository server requirements first.") from exc

    output = project / name
    output.mkdir(parents=True, exist_ok=False)
    settings = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path.resolve()),
        "architecture": "YOLOv8n-seg",
        "dataset": validation,
        "epochs": epochs,
        "image_size": image_size,
        "batch": batch,
        "workers": workers,
        "device": device,
        "seed": seed,
        "learning_rate": learning_rate,
        "augment": augment,
        "fraction": fraction,
        "cache": False,
        "minimum_available_ram_bytes": MIN_TRAINING_AVAILABLE_RAM,
        "system": {"platform": platform.platform(), "cpu_count": os.cpu_count(), **memory},
    }
    (output / "experiment.json").write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    model = YOLO(str(model_path.resolve()))
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=image_size,
        batch=batch,
        workers=workers,
        device=device,
        project=str(project),
        name=name,
        exist_ok=True,
        pretrained=True,
        seed=seed,
        lr0=learning_rate,
        augment=augment,
        fraction=fraction,
        cache=False,
        deterministic=True,
        plots=True,
        save=True,
        verbose=True,
    )
    best = output / "weights/best.pt"
    if not best.is_file():
        raise RuntimeError(f"Training completed without the expected checkpoint: {best}")

    del model
    gc.collect()
    trained = YOLO(str(best))
    validation_metrics = _extract_metrics(trained.val(data=str(data_yaml), split="val", imgsz=image_size, device=device, plots=True))
    test_metrics = _extract_metrics(trained.val(data=str(data_yaml), split="test", imgsz=image_size, device=device, plots=True))
    report = {
        **settings,
        "status": "TRAINED_AND_EVALUATED",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "best_checkpoint": str(best.resolve()),
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "training_curve_csv": str((output / "results.csv").resolve()),
        "training_plots_directory": str(output.resolve()),
        "accuracy_scope": "Metrics apply only to the declared dataset and source-grouped split; they do not validate artwork-contact events.",
    }
    (output / "training_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    del trained
    gc.collect()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and reproducibly train YOLOv8n-seg on compatible polygon labels.")
    parser.add_argument("--data", type=Path, required=True, help="Dataset YAML with train/val/test and source_groups.")
    parser.add_argument("--model", type=Path, default=project_path(MODEL_CONFIG.get("weights", "yolov8n-seg.pt"), ROOT), help="Local pretrained checkpoint.")
    parser.add_argument("--project", type=Path, default=project_path(TRAINING_CONFIG.get("project", "experiments"), ROOT))
    parser.add_argument("--name", default="pbl4-seg")
    parser.add_argument("--epochs", type=int, default=int(TRAINING_CONFIG.get("epochs", 1)))
    parser.add_argument("--imgsz", type=int, default=int(TRAINING_CONFIG.get("image_size", 320)))
    parser.add_argument("--batch", type=int, default=int(TRAINING_CONFIG.get("batch_size", 1)))
    parser.add_argument("--workers", type=int, default=int(TRAINING_CONFIG.get("workers", 0)))
    parser.add_argument("--device", choices=["cpu"], default="cpu")
    parser.add_argument("--seed", type=int, default=int(TRAINING_CONFIG.get("seed", 42)))
    parser.add_argument("--learning-rate", type=float, default=float(TRAINING_CONFIG.get("learning_rate", 0.001)))
    parser.add_argument("--fraction", type=float, default=1.0, help="Fraction of the training split; use 0.1 for a smoke run.")
    parser.add_argument("--smoke-test", action="store_true", help="Use one epoch, 320px, batch 1, workers 0, and the configured small data fraction.")
    parser.add_argument("--no-augment", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="Validate labels and splits without starting training.")
    args = parser.parse_args()
    if args.smoke_test:
        args.epochs = 1
        args.imgsz = 320
        args.batch = 1
        args.workers = 0
        args.fraction = float(TRAINING_CONFIG.get("smoke_fraction", 0.1))
    if min(args.epochs, args.imgsz, args.batch) <= 0 or args.workers < 0:
        parser.error("epochs, imgsz, and batch must be positive; workers cannot be negative")
    try:
        if args.validate_only:
            print(json.dumps(validate_dataset_yaml(args.data), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(train(
                args.data,
                model_path=args.model,
                project=args.project,
                name=args.name,
                epochs=args.epochs,
                image_size=args.imgsz,
                batch=args.batch,
                workers=args.workers,
                device=args.device,
                seed=args.seed,
                learning_rate=args.learning_rate,
                augment=not args.no_augment,
                fraction=args.fraction,
            ), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Training stopped safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

