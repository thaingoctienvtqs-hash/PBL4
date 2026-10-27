"""PBL4 worker for ESP32-CAM, offline images, and atomically refreshed JPEG files."""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.core.contact_logic import advance_track_contact, analyze_predictions
from src.core.geometry import (normalized_polygon_to_pixels, normalized_roi_to_pixels,
                               point_in_polygon, polygon_bounds)
from src.services.camera_compat import CaptureError, atomic_write_bytes, capture_to_file
from src.services.event_store import EventStore
from src.services.sensors import UnconfiguredSensor
from src.utils.config_compat import PROJECT_ROOT, load_settings, resolve_path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def _read_frame(cv2, path):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError("image is missing, incomplete, or unreadable: {}".format(path))
    return image


def _get_predictions(detector, frame):
    instances = detector.predict(frame)
    fields = ("pred_boxes", "scores", "pred_cats")
    missing = [field for field in fields if not instances.has(field)]
    if missing:
        raise RuntimeError("model output is missing {}".format(", ".join(missing)))
    return (instances.pred_boxes.tensor.tolist(), instances.scores.tolist(),
            instances.pred_cats.tolist())


def _write_jpeg(cv2, path, image):
    ok, data = cv2.imencode(".jpg", image)
    if not ok:
        raise OSError("OpenCV could not encode a JPEG frame")
    return atomic_write_bytes(path, data.tobytes())


def _normalized_box(box, width, height):
    x1, y1, x2, y2 = [float(value) for value in box]
    return [x1 / width, y1 / height, x2 / width, y2 / height]


def _box_iou(first, second):
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area2 = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area1 + area2 - intersection
    return intersection / union if union > 0.0 else 0.0


def _point_in_roi(point, roi, roi_polygon=None):
    if roi_polygon is not None:
        return point_in_polygon(point, roi_polygon)
    return roi[0] <= point[0] <= roi[2] and roi[1] <= point[1] <= roi[3]


def update_tracks(hands, previous_tracks, next_track_id, now, move_threshold,
                  track_timeout, image_width=1, image_height=1, roi=(0, 0, 0, 0),
                  minimum_roi_overlap=0.3, alert_settings=None, roi_polygon=None):
    """Track all detections with IoU and resolution-normalized center distance."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")
    if alert_settings is None:
        alert_settings = {}
    max_distance = float(alert_settings.get("track_match_distance_normalized", move_threshold))
    movement_threshold = float(alert_settings.get("movement_threshold_normalized", 0.015))
    iou_threshold = float(alert_settings.get("track_iou_threshold", 0.1))

    tracks = {}
    for track_id, old in previous_tracks.items():
        if now - old["last_seen"] <= track_timeout:
            old["frame_observed"] = False
            old["hand_index"] = None
            old["entered_roi"] = False
            old["movement_normalized"] = 0.0
            tracks[track_id] = old

    edges = []
    for index, hand in enumerate(hands):
        box = [float(value) for value in hand["box"]]
        norm_box = _normalized_box(box, image_width, image_height)
        center = ((box[0] + box[2]) / (2.0 * image_width),
                  (box[1] + box[3]) / (2.0 * image_height))
        for track_id, old in tracks.items():
            old_center, old_box = old.get("center_normalized"), old.get("box_normalized")
            if old_center is None or old_box is None:
                continue
            distance = ((center[0] - old_center[0]) ** 2
                        + (center[1] - old_center[1]) ** 2) ** 0.5
            iou = _box_iou(norm_box, old_box)
            if distance <= max_distance or iou >= iou_threshold:
                edges.append((distance / max_distance + (1.0 - iou) * 0.5,
                              track_id, index, distance))
    assignments, used_tracks, used_hands = {}, set(), set()
    for unused_cost, track_id, index, distance in sorted(edges):
        if track_id not in used_tracks and index not in used_hands:
            assignments[index] = (track_id, distance)
            used_tracks.add(track_id)
            used_hands.add(index)

    observations = []
    for index, hand in enumerate(hands):
        box = [float(value) for value in hand["box"]]
        norm_box = _normalized_box(box, image_width, image_height)
        center = ((box[0] + box[2]) / (2.0 * image_width),
                  (box[1] + box[3]) / (2.0 * image_height))
        overlap = float(hand["roi_overlap"])
        center_px = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        center_inside = _point_in_roi(center_px, roi, roi_polygon)
        inside = overlap >= minimum_roi_overlap
        if index in assignments:
            track_id, movement = assignments[index]
            track = tracks[track_id]
            crossed_center = not track.get("center_in_roi", False) and center_inside
            crossed_overlap = (track.get("roi_overlap", 0.0) < minimum_roi_overlap
                               and inside and movement >= movement_threshold)
            entered = movement >= movement_threshold and (crossed_center or crossed_overlap)
            stationary_since = track.get("stationary_since", now)
            if movement >= movement_threshold:
                stationary_since = now
            track["stationary_since"] = stationary_since
            track["movement_normalized"] = movement
        else:
            track_id = next_track_id
            next_track_id += 1
            track = {
                "first_seen": now, "stationary_since": now,
                "contact_history": [], "high_contact_streak": 0,
                "alert_active": False, "cooldown_until": 0.0,
                "last_contact_at": None, "contact_started_at": None,
                "ever_entered_roi": False, "state": "OUTSIDE_ROI",
            }
            entered, movement = False, 0.0
        if entered:
            track["ever_entered_roi"] = True
            track["entry_at"] = now
        track.update({
            "center_normalized": center, "box_normalized": norm_box,
            "box": box, "last_seen": now, "roi_overlap": overlap,
            "currently_in_roi": inside, "center_in_roi": center_inside,
            "entered_roi": entered, "frame_observed": True, "hand_index": hand["index"],
        })
        observation = {
            "hand_index": hand["index"], "track_id": track_id, "box": box,
            "movement_normalized": movement,
            "stationary_seconds": max(0.0, now - track["stationary_since"]),
            "age_seconds": max(0.0, now - track["first_seen"]),
            "roi_overlap": overlap, "entered_roi": entered,
        }
        observations.append(observation)
        tracks[track_id] = track
    return tracks, next_track_id, observations


def _analyze_frame(cv2, store, detector, frame, settings, mode, streak,
                   previous_tracks, next_track_id, frame_time=None):
    height, width = frame.shape[:2]
    roi_shape = settings["roi"].get("shape", "rectangle")
    pixel_roi_polygon = None
    if roi_shape == "polygon":
        pixel_roi_polygon = normalized_polygon_to_pixels(
            settings["roi"]["points"], width, height)
        pixel_roi = polygon_bounds(pixel_roi_polygon)
    else:
        pixel_roi = normalized_roi_to_pixels(
            settings["roi"]["coordinates"], width, height,
            normalized=settings["roi"].get("normalized", True),
        )
    pixel_roi = tuple(int(round(value)) for value in pixel_roi)
    boxes, detection_scores, contact_scores = _get_predictions(detector, frame)
    report = analyze_predictions(
        boxes, detection_scores, contact_scores, pixel_roi,
        settings["thresholds"], settings["roi"]["minimum_bbox_overlap"],
        roi_polygon=pixel_roi_polygon,
    )
    roi_enabled = settings["roi"]["enabled"]
    report["roi"] = list(pixel_roi)
    report["roi_shape"] = roi_shape
    if pixel_roi_polygon is not None:
        report["roi_polygon"] = [[float(x), float(y)] for x, y in pixel_roi_polygon]
    report["image_size"] = {"width": width, "height": height}
    report["model"] = "ContactHands"
    report["interpretation"] = "AI suspicion; not verified physical contact"
    now = time.monotonic() if frame_time is None else float(frame_time)
    tracks, next_track_id, observations = update_tracks(
        report["hands"], previous_tracks, next_track_id, now,
        settings["alert"]["track_match_distance_normalized"],
        settings["alert"]["track_timeout_seconds"],
        image_width=width, image_height=height, roi=pixel_roi,
        minimum_roi_overlap=settings["roi"]["minimum_bbox_overlap"],
        alert_settings=settings["alert"], roi_polygon=pixel_roi_polygon,
    )
    hand_map = {hand["index"]: hand for hand in report["hands"]}
    observation_map = {item["track_id"]: item for item in observations}
    new_alerts = []
    for track_id, track in tracks.items():
        hand = hand_map.get(track.get("hand_index")) if track.get("frame_observed") else None
        decision = advance_track_contact(
            track, hand, now, settings["alert"],
            settings["thresholds"]["object_contact"],
            settings["roi"]["minimum_bbox_overlap"], roi_enabled,
        )
        item = observation_map.get(track_id)
        if item is not None:
            item.update({"state": decision["state"],
                         "object_contact_score": decision["object_contact_score"],
                         "contact_window_positive_frames": decision["positive_frames"],
                         "state_reason": decision["reason"],
                         "stationary": item["stationary_seconds"] >= settings["alert"]["stationary_seconds"]})
            hand["track_id"] = track_id
            hand["track_state"] = decision["state"]
        if decision["alert_started"]:
            new_alerts.append((track_id, track, decision))

    active = [track for track in tracks.values()
              if track.get("state") == "ALERT" and track.get("alert_active")]
    candidates = [track for track in tracks.values()
                  if track.get("state") == "CANDIDATE" and track.get("frame_observed")]
    cooling = [track for track in tracks.values()
               if track.get("state") == "COOLDOWN" and track.get("frame_observed")]
    in_roi = [track for track in tracks.values()
              if track.get("frame_observed") and track.get("currently_in_roi")]
    if not roi_enabled:
        state, condition, message = (
            "NEEDS_CONFIGURATION", "ROI_NOT_CONFIGURED",
            "Set and enable the painting ROI before generating contact alerts")
    elif active:
        state, condition, message = (
            "ALERT", "CONTACT_CONFIRMED_TEMPORALLY",
            "Persistent Object-Contact candidate after ROI entry; verify the evidence image")
    elif not observations:
        state, condition, message = "NO_HAND", "NO_HANDS", "No hand detections in this frame"
    elif candidates:
        state, condition, message = (
            "CANDIDATE", "CONTACT_CANDIDATE_IN_ROI",
            "Contact candidate is being checked across recent frames")
    elif cooling:
        state, condition, message = "COOLDOWN", "TRACK_COOLDOWN", "Per-track cooldown is active"
    elif in_roi:
        state, condition, message = (
            "NO_CONTACT", "HANDS_IN_ROI_NO_OBJECT_CONTACT",
            "Hands overlap the painting ROI without Object-Contact evidence")
    else:
        state, condition, message = "OUTSIDE_ROI", "HANDS_OUTSIDE_ROI", "Hands are outside the painting ROI"

    report.update({
        "status": state, "condition": condition, "message": message,
        "event_kind": "AI_CONTACT_SUSPECTED_IN_ROI" if active else None,
        "track_observations": observations,
        "track_states": {str(key): value.get("state") for key, value in tracks.items()},
        "candidate_hand_indices": [
            hand["index"] for hand in report["hands"]
            if hand.get("track_state") in ("CANDIDATE", "ALERT")],
        "trigger_reasons": [{"track_id": key, "reason": result["reason"]}
                            for key, unused, result in new_alerts],
    })
    if active:
        report["event_status"] = "AI suspicion; pending human verification"
    annotated = frame.copy()
    if roi_enabled:
        if pixel_roi_polygon is None:
            cv2.rectangle(annotated, (pixel_roi[0], pixel_roi[1]),
                          (pixel_roi[2], pixel_roi[3]), (255, 200, 0), 2)
        else:
            import numpy as np
            points = np.asarray(pixel_roi_polygon, dtype="int32").reshape((-1, 1, 2))
            cv2.polylines(annotated, [points], True, (255, 200, 0), 2)
    for hand in report["hands"]:
        x1, y1, x2, y2 = [int(round(value)) for value in hand["box"]]
        hand_state = hand.get("track_state", "OUTSIDE_ROI")
        color = (0, 0, 255) if hand_state == "ALERT" else (
            (0, 165, 255) if hand_state == "CANDIDATE" else (0, 220, 0))
        label = "T{} {} OC:{:.2f} ROI:{:.2f}".format(
            hand.get("track_id", "?"), hand_state,
            hand["contact_scores"]["Object-Contact"], hand["roi_overlap"])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, label, (max(0, x1), max(16, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
    cv2.putText(annotated, state, (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 0, 255) if state == "ALERT" else (255, 200, 0), 2)
    latest_frame = resolve_path(settings, "latest_frame")
    latest_frame.parent.mkdir(parents=True, exist_ok=True)
    _write_jpeg(cv2, latest_frame, annotated)

    event_ids = []
    wall_now = datetime.now().astimezone()
    for track_id, track, decision in new_alerts:
        elapsed = max(0.0, now - track["contact_started_at"])
        event_details = dict(report)
        event_details.update({
            "track_id": track_id,
            "contact_started_at": (wall_now - timedelta(seconds=elapsed)).isoformat(),
            "alert_at": wall_now.isoformat(),
            "object_contact_score": track.get("last_object_contact_score", 0.0),
            "roi_overlap": track.get("last_contact_overlap", 0.0),
            "trigger_reason": decision["reason"],
            "stationary_seconds": max(0.0, now - track["stationary_since"]),
        })
        event_id = store.record_event(
            report["event_kind"], event_details,
            cooldown_seconds=0,
        )
        event_ids.append(event_id)
        evidence_dir = resolve_path(settings, "evidence_dir")
        evidence_path = evidence_dir / "suspected_contact_track_{}_{}.jpg".format(
            track_id, wall_now.strftime("%Y%m%d_%H%M%S_%f"))
        try:
            atomic_write_bytes(evidence_path, latest_frame.read_bytes())
            store.set_event_evidence(event_id, str(evidence_path))
        except OSError as error:
            report.setdefault("evidence_errors", []).append(str(error))
    report["event_ids"] = event_ids
    if event_ids:
        report["event_id"] = event_ids[0]
    store.set_status(
        state, mode=mode, condition=condition, message=message,
        report=report, frame_path=str(latest_frame), model="ContactHands",
        updated_local=datetime.now().astimezone().isoformat(timespec="seconds"),
        sensor=UnconfiguredSensor().read(),
    )
    return 0, state, tracks, next_track_id


def _load_detector(settings, args):
    from src.core.contacthands import ContactHandsDetector
    model = settings["model"]
    return ContactHandsDetector(
        config=args.config or PROJECT_ROOT / model["contacthands_config"],
        weights=args.weights or PROJECT_ROOT / model["contacthands_weights"],
        score_thresh=settings["thresholds"]["hand_score"],
        second_stream_config=args.second_stream_config or PROJECT_ROOT / model["second_stream_config"],
        second_stream_weights=args.second_stream_weights or model["second_stream_weights"] or None,
        device=args.device or model["device"],
    )


def _batch(args, settings, store, detector, cv2):
    if args.mode == "image":
        if not args.image:
            raise ValueError("--image is required in image mode")
        paths = [Path(args.image).expanduser()]
    else:
        folder = Path(args.image_dir).expanduser()
        if not folder.is_dir():
            raise ValueError("image directory does not exist: {}".format(folder))
        paths = sorted(path for path in folder.iterdir()
                       if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
        if not paths:
            raise ValueError("no supported images found in {}".format(folder))
    streak = 0
    errors = 0
    for index, path in enumerate(paths, 1):
        try:
            frame = _read_frame(cv2, path)
            streak, state, unused_tracks, unused_next_id = _analyze_frame(
                cv2, store, detector, frame, load_settings(args.config_json), args.mode,
                streak, {}, 0)
            print("{}/{} {} {}".format(index, len(paths), state, path), flush=True)
        except Exception as error:
            errors += 1
            store.set_status("ERROR", mode=args.mode,
                             message="Frame {} failed: {}".format(path, error))
            print("ERROR: {}: {}".format(path, error), file=sys.stderr, flush=True)
            if args.mode == "image":
                break
    store.set_status("STOPPED", mode=args.mode, message="Offline inference completed",
                     error_count=errors, processed_count=len(paths) - errors)
    return 1 if errors else 0


def run(args):
    settings = load_settings(args.config_json)
    store = EventStore(args.database or resolve_path(settings, "event_db"))
    store.set_status("STARTING", mode=args.mode, message="Initializing PBL4 inference worker")
    try:
        import cv2
    except ImportError as error:
        store.set_status("ERROR", mode=args.mode, message="OpenCV unavailable: {}".format(error))
        print("ERROR: OpenCV unavailable in this Python environment: {}".format(error), file=sys.stderr)
        return 2
    try:
        detector = _load_detector(settings, args)
    except Exception as error:
        store.set_status("ERROR", mode=args.mode, message="ContactHands initialization failed: {}".format(error))
        print("ERROR: ContactHands initialization failed: {}".format(error), file=sys.stderr)
        return 2

    if args.mode in ("image", "image-dir"):
        return _batch(args, settings, store, detector, cv2)

    capture_path = Path(args.frame_file or resolve_path(settings, "capture_frame")).expanduser()
    latest_signature = None
    last_frame_at = None
    streak = 0
    tracks = {}
    next_track_id = 0
    interval = args.poll_interval or settings["camera"]["poll_interval_seconds"]
    last_log_signature = None
    last_log_at = 0.0
    try:
        while True:
            settings = load_settings(args.config_json)
            try:
                if args.mode == "camera":
                    camera_url = args.camera_url or settings["camera"]["url"]
                    if not camera_url:
                        raise CaptureError("ESP32-CAM URL is not configured")
                    capture_to_file(camera_url, capture_path,
                                    settings["camera"]["request_timeout_seconds"])
                if not capture_path.is_file():
                    state = "WAITING_FOR_FRAME"
                    if last_frame_at and time.time() - last_frame_at > settings["dashboard"]["stale_after_seconds"]:
                        state = "CAMERA_DISCONNECTED"
                    store.set_status(state, mode=args.mode,
                                     message="Waiting for ESP32-CAM snapshot at {}".format(capture_path))
                    if state == "CAMERA_DISCONNECTED":
                        tracks = {}
                    if args.once:
                        return 1
                    time.sleep(interval)
                    continue
                stat = capture_path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if args.mode == "file-watch" and signature == latest_signature:
                    if last_frame_at and time.time() - last_frame_at > settings["dashboard"]["stale_after_seconds"]:
                        tracks = {}
                        store.set_status("CAMERA_DISCONNECTED", mode=args.mode,
                                         message="Capture file has not been refreshed")
                    else:
                        store.set_status("MONITORING", mode=args.mode,
                                         message="Waiting for the next atomically written frame")
                    if args.once:
                        return 0
                    time.sleep(interval)
                    continue
                frame = _read_frame(cv2, capture_path)
                latest_signature = signature
                last_frame_at = time.time()
                streak, state, tracks, next_track_id = _analyze_frame(
                    cv2, store, detector, frame, settings, args.mode,
                    streak, tracks, next_track_id)
                signature = (state, store.get_status().get("condition"))
                now = time.monotonic()
                if signature != last_log_signature or now - last_log_at >= 10.0:
                    print("{} {} {}".format(datetime.now().isoformat(timespec="seconds"),
                                             state, capture_path), flush=True)
                    last_log_signature, last_log_at = signature, now
                if args.once:
                    store.set_status("STOPPED", mode=args.mode, message="One frame processed")
                    return 0
            except CaptureError as error:
                tracks = {}
                store.set_status("CAMERA_DISCONNECTED", mode=args.mode, message=str(error))
                signature = ("CAMERA_DISCONNECTED", str(error))
                now = time.monotonic()
                if signature != last_log_signature or now - last_log_at >= 10.0:
                    print("CAMERA_DISCONNECTED: {}".format(error), file=sys.stderr, flush=True)
                    last_log_signature, last_log_at = signature, now
                if args.once:
                    return 1
            except Exception as error:
                tracks = {}
                store.set_status("ERROR", mode=args.mode,
                                 message="Frame processing failed: {}".format(error))
                signature = ("ERROR", str(error))
                now = time.monotonic()
                if signature != last_log_signature or now - last_log_at >= 10.0:
                    print("ERROR: frame processing failed: {}".format(error), file=sys.stderr, flush=True)
                    last_log_signature, last_log_at = signature, now
                if args.once:
                    return 1
            time.sleep(interval)
    except KeyboardInterrupt:
        store.set_status("STOPPED", mode=args.mode, message="Worker stopped by keyboard interrupt")
        return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("camera", "file-watch", "image", "image-dir"),
                        default="camera")
    parser.add_argument("--config-json", help="PBL4 JSON config path")
    parser.add_argument("--config", help="ContactHands model config YAML")
    parser.add_argument("--second-stream-config", help="Detectron2 object model YAML")
    parser.add_argument("--weights", help="ContactHands checkpoint")
    parser.add_argument("--second-stream-weights", help="optional second-stream checkpoint")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--camera-url", help="ESP32-CAM /capture URL")
    parser.add_argument("--frame-file", help="Windows snapshot path for file-watch mode")
    parser.add_argument("--image", help="one offline image")
    parser.add_argument("--image-dir", help="offline image directory")
    parser.add_argument("--database", help="override SQLite history database")
    parser.add_argument("--poll-interval", type=float, help="camera/file poll interval seconds")
    parser.add_argument("--once", action="store_true", help="process one frame if available")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.poll_interval is not None and args.poll_interval <= 0:
        parser.error("--poll-interval must be positive")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
