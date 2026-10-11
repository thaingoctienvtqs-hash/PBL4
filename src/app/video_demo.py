from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.runtime_paths import configure_runtime_paths

configure_runtime_paths(ROOT)

import cv2
from ultralytics import YOLO

from inference.camera_factory import build_camera_source
from server.contact.hand_landmarker import MediaPipeHandLandmarker
from server.contact.video import VideoContactPipeline, run_video, settings_from_config


def _load_config(path: Path) -> dict[str, Any]:
    import tomllib

    with path.open("rb") as stream:
        return tomllib.load(stream)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run server-side YOLO tracking and temporal painting-contact analysis on video or a camera source."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--input", help="Offline video file or OpenCV-compatible network stream URL.")
    source_group.add_argument("--webcam", type=int, metavar="INDEX", help="Optional laptop webcam index, usually 0.")
    source_group.add_argument("--esp32-url", help="Optional ESP32-CAM MJPEG stream URL; hardware is not required for offline work.")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/system.toml")
    parser.add_argument("--weights", type=Path, help="YOLO checkpoint. Defaults to model.weights in the TOML config.")
    parser.add_argument("--output", type=Path, help="Rendered MP4 path. Existing files are never overwritten.")
    parser.add_argument("--events", type=Path, help="JSONL event log path; records are appended.")
    parser.add_argument("--evidence-dir", type=Path, help="Directory for alert evidence frames.")
    parser.add_argument("--use-hand-landmarker", action="store_true", help="Add optional MediaPipe hand landmarks to YOLO detections.")
    args = parser.parse_args()

    config = _load_config(args.config)
    model_config = config.get("model", {})
    configured_weights = args.weights or Path(str(model_config.get("weights", "yolov8n-seg.pt")))
    weights = configured_weights if configured_weights.is_absolute() else ROOT / configured_weights
    if not weights.is_file():
        parser.error(f"YOLO checkpoint does not exist: {weights}. Supply --weights to a local checkpoint.")

    contact_settings, pipeline_config = settings_from_config(config)
    model = YOLO(str(weights))
    hand_config = config.get("hand_landmarker", {})
    hand_detector = None
    if args.use_hand_landmarker or bool(hand_config.get("enabled", False)):
        configured_task = Path(str(hand_config.get("task_model", "dataset/public/mediapipe/hand_landmarker.task")))
        task_model = configured_task if configured_task.is_absolute() else ROOT / configured_task
        hand_detector = MediaPipeHandLandmarker(
            task_model,
            contact_settings=contact_settings,
            min_detection_confidence=float(hand_config.get("min_detection_confidence", 0.5)),
            num_hands=int(hand_config.get("num_hands", 4)),
        )
    pipeline = VideoContactPipeline(model, contact_settings, pipeline_config, hand_detector=hand_detector)

    if args.input is not None:
        source: Any = args.input
        source_label = args.input
        stem = Path(args.input).stem if not args.input.startswith(("http://", "https://", "rtsp://")) else "stream"
    elif args.webcam is not None:
        camera = build_camera_source("webcam", camera_index=args.webcam)
        source = camera
        source_label = f"webcam:{args.webcam}"
        stem = f"webcam_{args.webcam}"
    else:
        camera = build_camera_source("esp32", url=args.esp32_url)
        source = camera
        source_label = f"esp32:{args.esp32_url}"
        stem = "esp32"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default_output = ROOT / "server/data/results" / f"{stem}_{timestamp}.mp4"
    output = args.output or default_output
    events = args.events or output.with_suffix(".events.jsonl")
    evidence = args.evidence_dir or output.with_suffix("").with_name(output.stem + "_evidence")

    try:
        summary = run_video(
            pipeline,
            source,
            output_path=output,
            events_path=events,
            evidence_dir=evidence,
            source_label=source_label,
        )
    finally:
        if hand_detector is not None:
            hand_detector.close()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

