"""Validated PBL4 settings with relative paths and environment overrides."""

import copy
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "pbl4.json"
DEFAULTS = {
    "schema_version": 1,
    "camera": {"url": "", "request_timeout_seconds": 5.0, "poll_interval_seconds": 0.5},
    "roi": {"enabled": False, "shape": "rectangle",
            "coordinates": [0.2, 0.1, 0.8, 0.9], "points": [],
            "normalized": True, "minimum_bbox_overlap": 0.3},
    "thresholds": {"hand_score": 0.7, "no_contact": 0.5,
                   "self_contact": 0.5, "other_person_contact": 0.4,
                   "object_contact": 0.15},
    "alert": {"confirm_frames": 2, "cooldown_seconds": 60,
              "stationary_seconds": 2.0, "move_threshold_pixels": 20.0,
              "track_timeout_seconds": 1.0,
              "track_match_distance_normalized": 0.25,
              "track_iou_threshold": 0.1, "movement_threshold_normalized": 0.015,
              "history_window_frames": 5, "minimum_contact_roi_frames": 3,
              "fast_contact_score": 0.85, "fast_contact_consecutive_frames": 2,
              "clear_after_seconds": 0.75},
    "model": {"device": "auto", "contacthands_config": "src/configs/ContactHands.yaml",
              "contacthands_weights": "models/combined_data_model.pth",
              "second_stream_config": "src/configs/second_stream.yaml",
              "second_stream_weights": ""},
    "paths": {"capture_frame": "data/camera_frame.jpg",
              "latest_frame": "src/data/latest.jpg",
              "event_db": "src/data/events.sqlite3",
              "status_file": "src/data/status.txt",
              "evidence_dir": "src/data/alerts"},
    "dashboard": {"host": "127.0.0.1", "port": 8000, "stale_after_seconds": 15},
}
CONTACT_THRESHOLDS = ("no_contact", "self_contact", "other_person_contact", "object_contact")
PATH_KEYS = ("capture_frame", "latest_frame", "event_db", "status_file", "evidence_dir")


def _merge(base, overrides):
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError("PBL4 config must be a JSON object")
    config = _merge(DEFAULTS, value)
    roi = config["roi"]
    if not isinstance(roi.get("enabled"), bool):
        raise ValueError("roi.enabled must be true or false")
    shape = roi.get("shape", "rectangle")
    if shape not in ("rectangle", "polygon"):
        raise ValueError("roi.shape must be rectangle or polygon")
    roi["shape"] = shape
    if shape == "polygon":
        from src.core.geometry import polygon_bounds, validate_polygon
        if roi.get("normalized", True) is not True:
            raise ValueError("polygon ROI coordinates must be normalized")
        points = validate_polygon(roi.get("points"), normalized=True)
        roi["points"] = [list(point) for point in points]
        roi["coordinates"] = list(polygon_bounds(points))
    elif not isinstance(roi.get("points", []), list):
        raise ValueError("roi.points must be a list")
    coordinates = roi.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 4:
        raise ValueError("roi.coordinates must be [x1, y1, x2, y2]")
    try:
        coordinates = [float(item) for item in coordinates]
    except (TypeError, ValueError):
        raise ValueError("roi.coordinates must be numbers")
    if any(not _finite(item) for item in coordinates):
        raise ValueError("roi.coordinates must be finite")
    if roi.get("normalized", True) and any(item < 0 or item > 1 for item in coordinates):
        raise ValueError("normalized ROI coordinates must be between 0 and 1")
    if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ValueError("ROI top-left must be before bottom-right")
    roi["coordinates"] = coordinates
    overlap = float(roi.get("minimum_bbox_overlap", -1))
    if not 0 <= overlap <= 1:
        raise ValueError("roi.minimum_bbox_overlap must be between 0 and 1")
    roi["minimum_bbox_overlap"] = overlap
    for key in CONTACT_THRESHOLDS:
        threshold = float(config["thresholds"].get(key, -1))
        if not 0 <= threshold <= 1:
            raise ValueError("thresholds.{} must be between 0 and 1".format(key))
        config["thresholds"][key] = threshold
    hand_score = float(config["thresholds"].get("hand_score", -1))
    if not 0 <= hand_score <= 1:
        raise ValueError("thresholds.hand_score must be between 0 and 1")
    config["thresholds"]["hand_score"] = hand_score
    for key in ("request_timeout_seconds", "poll_interval_seconds"):
        number = float(config["camera"].get(key, 0))
        if not _finite(number) or number <= 0:
            raise ValueError("camera.{} must be positive".format(key))
        config["camera"][key] = number
    frames = config["alert"].get("confirm_frames")
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise ValueError("alert.confirm_frames must be a positive integer")
    cooldown = float(config["alert"].get("cooldown_seconds", -1))
    if not _finite(cooldown) or cooldown < 0:
        raise ValueError("alert.cooldown_seconds cannot be negative or non-finite")
    config["alert"]["cooldown_seconds"] = cooldown
    for key in ("stationary_seconds", "move_threshold_pixels", "track_timeout_seconds",
                "track_match_distance_normalized"):
        number = float(config["alert"].get(key, 0))
        if not _finite(number) or number <= 0:
            raise ValueError("alert.{} must be finite and positive".format(key))
        config["alert"][key] = number
    for key in ("movement_threshold_normalized", "clear_after_seconds"):
        number = float(config["alert"].get(key, -1))
        if not _finite(number) or number < 0:
            raise ValueError("alert.{} cannot be negative or non-finite".format(key))
        config["alert"][key] = number
    iou = float(config["alert"].get("track_iou_threshold", -1))
    fast_score = float(config["alert"].get("fast_contact_score", -1))
    if not 0 <= iou <= 1 or not 0 <= fast_score <= 1:
        raise ValueError("track IoU and fast contact score must be between 0 and 1")
    config["alert"]["track_iou_threshold"] = iou
    config["alert"]["fast_contact_score"] = fast_score
    for key in ("history_window_frames", "minimum_contact_roi_frames",
                "fast_contact_consecutive_frames"):
        value = config["alert"].get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("alert.{} must be a positive integer".format(key))
    if config["alert"]["minimum_contact_roi_frames"] > config["alert"]["history_window_frames"]:
        raise ValueError("minimum_contact_roi_frames cannot exceed history_window_frames")
    if config["model"].get("device") not in ("auto", "cpu", "cuda"):
        raise ValueError("model.device must be auto, cpu, or cuda")
    if not 1 <= int(config["dashboard"].get("port", 0)) <= 65535:
        raise ValueError("dashboard.port must be between 1 and 65535")
    for key in PATH_KEYS:
        if not isinstance(config["paths"].get(key), str):
            raise ValueError("paths.{} must be a path string".format(key))
    if os.environ.get("PBL4_CAMERA_URL"):
        config["camera"]["url"] = os.environ["PBL4_CAMERA_URL"]
    if os.environ.get("CONTACTHANDS_SECOND_STREAM_WEIGHTS"):
        config["model"]["second_stream_weights"] = os.environ["CONTACTHANDS_SECOND_STREAM_WEIGHTS"]
    if os.environ.get("CONTACTHANDS_MODEL_WEIGHTS"):
        config["model"]["contacthands_weights"] = os.environ["CONTACTHANDS_MODEL_WEIGHTS"]
    return config


def _finite(value):
    return value == value and value not in (float("inf"), float("-inf"))


def load_settings(path=None):
    path = Path(path or os.environ.get("PBL4_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    else:
        raw = DEFAULTS
    return validate_settings(raw)


def save_settings(config, path=None):
    """Atomically persist validated settings and keep the prior file on failure."""
    import tempfile
    config = validate_settings(config)
    # A runtime override must not be copied back into a tracked config file.
    if os.environ.get("PBL4_CAMERA_URL"):
        config["camera"]["url"] = ""
    if os.environ.get("CONTACTHANDS_SECOND_STREAM_WEIGHTS"):
        config["model"]["second_stream_weights"] = ""
    if os.environ.get("CONTACTHANDS_MODEL_WEIGHTS"):
        config["model"]["contacthands_weights"] = DEFAULTS["model"]["contacthands_weights"]
    target = Path(path or os.environ.get("PBL4_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(config, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(target))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def resolve_path(config, key):
    env_name = "PBL4_" + key.upper()
    value = os.environ.get(env_name) or config["paths"][key]
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


# Compatibility constants for earlier PBL4 scripts. New code uses load_settings().
ROI = tuple(DEFAULTS["roi"]["coordinates"])
ROI_ENABLED = DEFAULTS["roi"]["enabled"]
OC_THRESH = DEFAULTS["thresholds"]["object_contact"]
OVERLAP_THRESH = DEFAULTS["roi"]["minimum_bbox_overlap"]
FRAME_PATH = str((PROJECT_ROOT / DEFAULTS["paths"]["capture_frame"]).resolve())
STATUS_PATH = str((PROJECT_ROOT / DEFAULTS["paths"]["status_file"]).resolve())
