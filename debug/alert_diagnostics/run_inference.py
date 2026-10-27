"""Opt-in, bounded file-watch instrumentation of unchanged worker v3. Never opens a camera."""
import argparse
import copy
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from common import (HERE, PROJECT_ROOT, worker, load_config, create_run, source_hashes,
                    write_json_new, isolated_settings, isolated_resolve, track_row)

def utc_now():
    return datetime.now(timezone.utc).isoformat()

class TimedDetector:
    def __init__(self, detector, synchronize=lambda: None):
        self.detector = detector
        self.synchronize = synchronize
        self.inference_seconds = None

    def predict(self, frame):
        self.synchronize()
        started = time.monotonic()
        try:
            return self.detector.predict(frame)
        finally:
            self.synchronize()
            self.inference_seconds = time.monotonic() - started

class FrameProbe:
    def __init__(self):
        self.original = worker.update_tracks
        self.last_update = None
        self.now = None
        self.delta = None
        self.new_ids = set()
        self.expired_ids = []
        self.last_seen_gaps = {}

    def __call__(self, hands, previous, next_id, now, move_threshold, timeout, **kwargs):
        self.now = now
        self.delta = None if self.last_update is None else now - self.last_update
        old_ids = set(previous)
        self.last_seen_gaps = {key: now - value["last_seen"] for key, value in previous.items()}
        self.expired_ids = [key for key, gap in self.last_seen_gaps.items() if gap > timeout]
        result = self.original(hands, previous, next_id, now, move_threshold, timeout, **kwargs)
        self.new_ids = set(result[0]) - old_ids
        self.last_update = now
        return result

def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-inference", action="store_true",
                        help="Explicit opt-in; run only after approval for real inference")
    parser.add_argument("--config-json", default=str(HERE / "config.baseline.json"))
    parser.add_argument("--frame-file", default=str(PROJECT_ROOT / "data/camera_frame.jpg"))
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--poll-interval", type=float, default=.5)
    parser.add_argument("--track-timeout", type=float,
                        help="Diagnostic override only; baseline is unchanged at 1 second")
    parser.add_argument("--max-frames", type=int, default=30)
    parser.add_argument("--max-seconds", type=float, default=120)
    return parser

def check_args(args):
    if not args.allow_inference:
        raise ValueError("Inference is disabled: explicit --allow-inference is required")
    for name in ("poll_interval", "max_seconds"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            raise ValueError(name + " must be finite and positive")
    if args.track_timeout is not None and (
            not math.isfinite(args.track_timeout) or args.track_timeout <= 0):
        raise ValueError("track_timeout must be finite and positive")
    if args.max_frames < 1:
        raise ValueError("max_frames must be positive")

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        check_args(args)
        settings = load_config(args.config_json)
        if args.track_timeout is not None:
            settings["alert"]["track_timeout_seconds"] = args.track_timeout
        frame_file = Path(args.frame_file).expanduser().resolve()
        if not frame_file.is_file():
            raise ValueError("Existing JPEG required: " + str(frame_file))
        # Prevent automatic download: second stream must already be local.
        second = settings["model"].get("second_stream_weights")
        second = (Path(second).expanduser() if second else
                  Path.home() / ".torch/iopath_cache/detectron2/COCO-InstanceSegmentation/"
                  "mask_rcnn_R_101_FPN_3x/138205316/model_final_a3ec72.pkl")
        if not second.is_absolute():
            second = PROJECT_ROOT / second
        if not second.is_file():
            raise ValueError("Existing local second-stream checkpoint required; downloads are disabled: " + str(second))
        settings["model"]["second_stream_weights"] = str(second.resolve())
        for key in ("contacthands_weights", "contacthands_config", "second_stream_config"):
            if not (PROJECT_ROOT / settings["model"][key]).is_file():
                raise ValueError("Missing local model file: " + settings["model"][key])
    except (ValueError, OSError) as error:
        parser.error(str(error))
    run = create_run("inference")
    settings = isolated_settings(settings, run)
    settings["paths"]["capture_frame"] = str(frame_file)
    settings["camera"]["poll_interval_seconds"] = args.poll_interval
    before = source_hashes()
    write_json_new(run / "effective_config.json", settings)
    write_json_new(run / "run_metadata.json", {
        "started_utc": utc_now(), "argv": vars(args), "source_hashes": before,
        "input_kind": "real_file_watch", "camera_requests": 0,
        "roi_is_test_region_not_calibrated": True,
        "checkpoint_writes": False, "limits_checked_between_calls": True})
    frame_log = (run / "frames.jsonl").open("x", encoding="utf-8")
    runtime_log = (run / "runtime.jsonl").open("x", encoding="utf-8")
    def record_runtime(kind, **details):
        runtime_log.write(json.dumps(dict(details, kind=kind, timestamp_utc=utc_now()),
                                     allow_nan=False) + "\n")
        runtime_log.flush()
    processed = 0
    failure = None
    store = None
    old_update = worker.update_tracks
    old_resolve = worker.resolve_path
    deadline = time.monotonic() + args.max_seconds
    tracks, next_id, last_signature, last_success = {}, 0, None, None
    probe = FrameProbe()
    try:
        # All heavy imports occur after explicit opt-in; never during logic tests/help.
        import cv2
        import numpy as np
        import torch
        import detectron2
        import detectron2._C
        record_runtime("environment", python=sys.version, torch=torch.__version__,
                       detectron2=getattr(detectron2, "__version__", "unknown"),
                       cuda_available=torch.cuda.is_available())
        if args.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable in this interpreter")
        synchronize = torch.cuda.synchronize if args.device == "cuda" else (lambda: None)
        from src.services.event_store import EventStore
        store = EventStore(run / "events.sqlite3")
        detector_args = argparse.Namespace(config=None, weights=None, second_stream_config=None,
                                           second_stream_weights=str(second), device=args.device)
        init_start = time.monotonic()
        detector = TimedDetector(worker._load_detector(settings, detector_args), synchronize)
        record_runtime("model_initialized", seconds=time.monotonic() - init_start)
        worker.update_tracks = probe
        worker.resolve_path = isolated_resolve
        while processed < args.max_frames and time.monotonic() < deadline:
            try:
                stat = frame_file.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if signature == last_signature:
                    if last_success is not None and time.monotonic() - last_success > settings["dashboard"]["stale_after_seconds"]:
                        record_runtime("camera_disconnected_stale_file", cleared_track_ids=list(tracks))
                        tracks = {}
                        last_success = None
                    time.sleep(min(args.poll_interval, max(0, deadline-time.monotonic())))
                    continue
                data = frame_file.read_bytes()
                after = frame_file.stat()
                if signature != (after.st_mtime_ns, after.st_size):
                    record_runtime("frame_changed_while_reading")
                    time.sleep(args.poll_interval)
                    continue
                frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    record_runtime("unreadable_frame")
                    time.sleep(args.poll_interval)
                    continue
            except OSError as error:
                record_runtime("camera_source_missing", message=str(error), cleared_track_ids=list(tracks))
                tracks = {}
                time.sleep(args.poll_interval)
                continue
            started = time.monotonic()
            started_utc = utc_now()
            processed += 1
            # Unique output filename per frame: never replace an existing preview.
            settings["paths"]["latest_frame"] = str(run / "frames" / ("frame_%06d.jpg" % processed))
            unused, state, tracks, next_id = worker._analyze_frame(
                cv2, store, detector, frame, settings, "file-watch",
                0, tracks, next_id)
            process_seconds = time.monotonic() - started
            payload = store.get_status()
            report = payload["report"]
            observations = {item["track_id"]: item for item in report["track_observations"]}
            rows = []
            for key, track in tracks.items():
                observation = observations.get(key, {})
                # Snapshot decisions already made by production; never advance twice.
                decision = {
                    "state": track["state"], "reason": track.get("state_reason", ""),
                    "positive_frames": observation.get("contact_window_positive_frames",
                                                      sum(track.get("contact_history", []))),
                    "alert_started": any(item["track_id"] == key for item in report["trigger_reasons"]),
                    "valid_contact": bool(track["contact_history"][-1]) if track["contact_history"] else False,
                }
                row = track_row(key, track, decision, settings, probe.new_ids)
                row["last_seen_gap_seconds"] = probe.last_seen_gaps.get(key)
                rows.append(row)
            frame_log.write(json.dumps({
                "input_kind": "real_file_watch", "frame_index": processed,
                "timestamp_utc": started_utc, "finished_utc": utc_now(),
                "source_mtime_ns": stat.st_mtime_ns, "source_bytes": len(data),
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "inference_seconds": detector.inference_seconds,
                "frame_processing_seconds": process_seconds,
                "tracking_monotonic_seconds": probe.now,
                "tracking_delta_seconds": probe.delta,
                "track_timeout_seconds": settings["alert"]["track_timeout_seconds"],
                "expired_track_ids": probe.expired_ids,
                "tracks": rows, "state": state, "event_ids": report["event_ids"],
                "annotated_frame": settings["paths"]["latest_frame"],
            }, allow_nan=False) + "\n")
            frame_log.flush()
            last_signature = signature
            last_success = time.monotonic()
            print("frame={} state={} inference={:.3f}s tracking_delta={}".format(
                processed, state, detector.inference_seconds, probe.delta), flush=True)
            time.sleep(min(args.poll_interval, max(0, deadline-time.monotonic())))
    except KeyboardInterrupt:
        failure = "interrupted"
        record_runtime("interrupted")
    except Exception as error:
        failure = "{}: {}".format(type(error).__name__, error)
        record_runtime("error", message=failure)
    finally:
        worker.update_tracks = old_update
        worker.resolve_path = old_resolve
        if store is not None:
            store.set_status("DIAGNOSTIC_STOPPED", processed_frames=processed, error=failure)
        frame_log.close()
        runtime_log.close()
        write_json_new(run / "summary.json", {
            "processed_frames": processed, "error": failure, "finished_utc": utc_now(),
            "sources_unchanged": before == source_hashes(), "camera_requests": 0,
            "no_accuracy_metrics_computed": True})
        print("ARTIFACTS=" + str(run))
    return 1 if failure else 0

if __name__ == "__main__":
    sys.exit(main())
