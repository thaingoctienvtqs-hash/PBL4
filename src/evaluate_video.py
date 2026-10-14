"""Replay a real video through the existing temporal worker and save evidence.

This produces annotated video and per-frame predictions, not accuracy metrics.
Ground-truth labels must be collected separately before precision/recall can be
calculated.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.realtime_worker import _analyze_frame, _load_detector
from src.services.event_store import EventStore
from src.utils.config import load_settings


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="recorded MP4/MOV video")
    parser.add_argument("--output-video", required=True, help="annotated MP4 destination")
    parser.add_argument("--report-jsonl", required=True, help="per-frame prediction report")
    parser.add_argument("--config-json", help="PBL4 JSON settings")
    parser.add_argument("--config", help="ContactHands model YAML")
    parser.add_argument("--weights", help="ContactHands checkpoint")
    parser.add_argument("--second-stream-config", help="second stream YAML")
    parser.add_argument("--second-stream-weights", help="optional second stream checkpoint")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"))
    return parser


def run(args):
    source = Path(args.video).expanduser().resolve()
    output = Path(args.output_video).expanduser().resolve()
    report_path = Path(args.report_jsonl).expanduser().resolve()
    if not source.is_file():
        print("Video does not exist: {}".format(source), file=sys.stderr)
        return 2
    if source in (output, report_path) or output == report_path:
        print("Input, annotated video, and JSONL report must use different paths.",
              file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    settings = load_settings(args.config_json)
    try:
        import cv2
    except ImportError as error:
        print("Video evaluation requires OpenCV: {}".format(error), file=sys.stderr)
        return 2
    try:
        detector = _load_detector(settings, SimpleNamespace(
            config=args.config, weights=args.weights,
            second_stream_config=args.second_stream_config,
            second_stream_weights=args.second_stream_weights, device=args.device))
    except Exception as error:
        print("ContactHands initialization failed: {}".format(error), file=sys.stderr)
        return 2

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        print("Could not open input video: {}".format(source), file=sys.stderr)
        return 2
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not fps or fps <= 0:
        fps = 25.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        capture.release()
        print("Input video has invalid frame dimensions.", file=sys.stderr)
        return 2
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (width, height))
    if not writer.isOpened():
        capture.release()
        writer.release()
        print("OpenCV could not create the output MP4: {}".format(output), file=sys.stderr)
        return 2

    frame_index, previous_time = 0, -1.0
    tracks, next_track_id = {}, 0
    try:
        with tempfile.TemporaryDirectory(prefix="pbl4-video-eval-") as temporary:
            temporary = Path(temporary)
            settings["paths"]["latest_frame"] = str(temporary / "latest.jpg")
            settings["paths"]["event_db"] = str(temporary / "events.sqlite3")
            settings["paths"]["evidence_dir"] = str(temporary / "evidence")
            store = EventStore(temporary / "events.sqlite3")
            with report_path.open("w", encoding="utf-8", newline="\n") as report_file:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    if frame.shape[1] != width or frame.shape[0] != height:
                        print("Video frame dimensions changed at frame {}.".format(frame_index),
                              file=sys.stderr)
                        return 1
                    position = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
                    if frame_index and position <= previous_time:
                        position = frame_index / fps
                    previous_time = position
                    unused_code, state, tracks, next_track_id = _analyze_frame(
                        cv2, store, detector, frame, settings, "video-evaluation", {},
                        tracks, next_track_id, frame_time=position)
                    annotated = cv2.imread(str(temporary / "latest.jpg"))
                    if annotated is None:
                        raise RuntimeError("worker did not produce an annotated frame")
                    writer.write(annotated)
                    status = store.get_status()
                    report = status.get("report", {})
                    record = {
                        "frame_index": frame_index,
                        "video_seconds": position,
                        "status": state,
                        "condition": report.get("condition"),
                        "hands": report.get("hands", []),
                        "track_observations": report.get("track_observations", []),
                        "event_ids": report.get("event_ids", []),
                    }
                    report_file.write(json.dumps(record, ensure_ascii=False,
                                                 allow_nan=False) + "\n")
                    frame_index += 1
                    if frame_index % 100 == 0:
                        print("Processed {} frames ({:.1f}s)".format(frame_index, position),
                              flush=True)
    except Exception as error:
        print("Video evaluation failed: {}".format(error), file=sys.stderr)
        return 1
    finally:
        capture.release()
        writer.release()

    if frame_index == 0:
        print("Input video contains no readable frames.", file=sys.stderr)
        return 1
    print("Processed {} frames; annotated video: {}; frame report: {}".format(
        frame_index, output, report_path))
    print("No precision/recall or physical-contact metrics were calculated.")
    return 0


def main(argv=None):
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
