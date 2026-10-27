"""Shared diagnostics; importing this module never loads an AI model or creates files."""
import copy
import hashlib
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import realtime_worker_integrated_v3 as worker
from src.core.contact_logic import advance_track_contact, analyze_predictions
from src.core.geometry import normalized_roi_to_pixels
from src.utils import config_compat

OVERRIDES = (
    "PBL4_CONFIG", "PBL4_CAMERA_URL", "PBL4_CAPTURE_FRAME", "PBL4_LATEST_FRAME",
    "PBL4_EVENT_DB", "PBL4_STATUS_FILE", "PBL4_EVIDENCE_DIR",
    "CONTACTHANDS_MODEL_WEIGHTS", "CONTACTHANDS_SECOND_STREAM_WEIGHTS",
)

def reject_overrides(environ=None):
    environ = os.environ if environ is None else environ
    conflicts = [key for key in OVERRIDES if environ.get(key)]
    if conflicts:
        raise ValueError("Unset conflicting overrides in this test shell only: " + ", ".join(conflicts))

def load_config(path, environ=None):
    reject_overrides(environ)
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    roi = raw.get("roi", {})
    if roi.get("shape") != "rectangle" or roi.get("normalized") is not True:
        raise ValueError("Diagnostics requires shape=rectangle and normalized=true (boolean)")
    if roi.get("enabled") is not True or "coordinates" not in roi or "type" in roi:
        raise ValueError("Provide enabled=true and coordinates; legacy ROI type is rejected")
    if not isinstance(roi.get("points", []), list) or roi.get("points"):
        raise ValueError("Rectangle diagnostics must not contain polygon points")
    settings = config_compat.validate_settings(raw)
    for key in ("request_timeout_seconds", "poll_interval_seconds"):
        if not math.isfinite(settings["camera"][key]):
            raise ValueError("Camera times must be finite")
    return settings

def inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False

def create_run(kind):
    if kind not in ("logic", "inference"):
        raise ValueError("Invalid diagnostic kind")
    runs = HERE / "runs"
    if not inside(runs, HERE):
        raise ValueError("runs directory resolves outside diagnostics")
    runs.mkdir(exist_ok=True)
    name = "{}_{}_{}".format(kind, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
                            uuid.uuid4().hex[:8])
    run = runs / name
    run.mkdir(exist_ok=False)
    return run

def write_json_new(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")

def source_hashes():
    paths = ("src/realtime_worker_integrated_v3.py", "src/core/contact_logic.py",
             "src/core/geometry.py", "src/utils/config_compat.py",
             "src/services/event_store.py")
    return {p: hashlib.sha256((PROJECT_ROOT / p).read_bytes()).hexdigest() for p in paths}

def blockers(track, decision, settings):
    if decision["alert_started"]:
        return []
    if track.get("alert_active"):
        return ["alert_already_active_no_duplicate_event"]
    reasons = []
    if not settings["roi"]["enabled"]:
        reasons.append("roi_disabled")
    if not track.get("frame_observed"):
        reasons.append("hand_not_observed")
    if not track.get("currently_in_roi"):
        reasons.append("outside_roi")
    if track.get("last_object_contact_score", 0.0) < settings["thresholds"]["object_contact"]:
        reasons.append("object_contact_below_threshold")
    if not track.get("ever_entered_roi"):
        reasons.append("awaiting_roi_entry")
    if decision["positive_frames"] < settings["alert"]["minimum_contact_roi_frames"]:
        reasons.append("window_below_minimum")
    if track.get("high_contact_streak", 0) < settings["alert"]["fast_contact_consecutive_frames"]:
        reasons.append("fast_streak_below_minimum")
    if decision["state"] == "COOLDOWN":
        reasons.append("cooldown")
    return reasons

def track_row(track_id, track, decision, settings, new_ids):
    return {
        "track_id": track_id, "new_track": track_id in new_ids,
        "observed": bool(track.get("frame_observed")),
        "ever_entered_roi": bool(track.get("ever_entered_roi")),
        "entered_this_frame": bool(track.get("entered_roi")),
        "object_contact_score": track.get("last_object_contact_score"),
        "roi_overlap": track.get("roi_overlap"),
        "positive_frames": decision["positive_frames"],
        "history": list(track.get("contact_history", [])),
        "high_contact_streak": track.get("high_contact_streak", 0),
        "movement_normalized": track.get("movement_normalized", 0.0),
        "state": decision["state"], "state_reason": decision["reason"],
        "alert_started": decision["alert_started"],
        "valid_contact": decision["valid_contact"],
        "alert_blockers": blockers(track, decision, settings),
        "window_required": settings["alert"]["minimum_contact_roi_frames"],
        "window_size": settings["alert"]["history_window_frames"],
        "fast_score_required": settings["alert"]["fast_contact_score"],
        "fast_frames_required": settings["alert"]["fast_contact_consecutive_frames"],
    }

class LogicSession:
    """Controlled bounding boxes/scores only; not images, dataset or model evidence."""
    def __init__(self, settings=None):
        self.settings = copy.deepcopy(settings or config_compat.DEFAULTS)
        self.settings["roi"].update(enabled=True, shape="rectangle", normalized=True,
                                    coordinates=[0.4, 0.1, 0.8, 0.9], points=[])
        self.tracks = {}
        self.next_id = 0
        self.last_update = None
        self.rows = []

    def step(self, now, centers=(500,), score=0.6):
        settings = self.settings
        boxes = [[x - 50, 300, x + 50, 500] for x in centers]
        report = analyze_predictions(boxes, [0.99] * len(boxes),
                                     [[0.0, 0.0, 0.0, score] for _ in boxes],
                                     (400, 100, 800, 900), settings["thresholds"],
                                     settings["roi"]["minimum_bbox_overlap"])
        old_ids = set(self.tracks)
        expired = [key for key, value in self.tracks.items()
                   if now - value["last_seen"] > settings["alert"]["track_timeout_seconds"]]
        self.tracks, self.next_id, unused = worker.update_tracks(
            report["hands"], self.tracks, self.next_id, now,
            settings["alert"]["track_match_distance_normalized"],
            settings["alert"]["track_timeout_seconds"], image_width=1000, image_height=1000,
            roi=(400, 100, 800, 900),
            minimum_roi_overlap=settings["roi"]["minimum_bbox_overlap"],
            alert_settings=settings["alert"])
        new_ids = set(self.tracks) - old_ids
        hand_map = {h["index"]: h for h in report["hands"]}
        frame = {"input_kind": "controlled_logic_input_not_model_prediction",
                 "frame_index": len(self.rows), "tracking_monotonic_seconds": now,
                 "tracking_delta_seconds": None if self.last_update is None else now - self.last_update,
                 "expired_track_ids": expired, "tracks": []}
        for key, track in self.tracks.items():
            hand = hand_map.get(track["hand_index"]) if track["frame_observed"] else None
            decision = advance_track_contact(track, hand, now, settings["alert"],
                                             settings["thresholds"]["object_contact"],
                                             settings["roi"]["minimum_bbox_overlap"], True)
            frame["tracks"].append(track_row(key, track, decision, settings, new_ids))
        self.last_update = now
        self.rows.append(frame)
        return frame

def isolated_settings(settings, run):
    settings = copy.deepcopy(settings)
    run = Path(run).resolve()
    if not inside(run, HERE / "runs"):
        raise ValueError("Run output must be below diagnostic runs/")
    paths = settings["paths"]
    paths.update(event_db=str(run / "events.sqlite3"), evidence_dir=str(run / "evidence"),
                 status_file=str(run / "status.txt"), latest_frame=str(run / "frames" / "unused.jpg"))
    return settings

def isolated_resolve(settings, key):
    path = Path(settings["paths"][key]).resolve()
    if key != "capture_frame" and not inside(path, HERE / "runs"):
        raise ValueError("Attempt to write outside diagnostic runs/")
    if key == "latest_frame" and path.exists():
        raise FileExistsError("Refusing to overwrite diagnostic frame: " + str(path))
    return path
