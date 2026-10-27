from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import cv2

from inference.camera_factory import build_camera_source
from inference.config import DEFAULT_CAMERA_INDEX, DEFAULT_HEIGHT, DEFAULT_WIDTH


def collect_webcam_dataset(
    output_dir: str,
    seconds: float = 10.0,
    fps: int = 10,
    camera_index: int = DEFAULT_CAMERA_INDEX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_dir = output_path / "raw_videos" / timestamp
    video_dir.mkdir(parents=True, exist_ok=True)

    source = build_camera_source("webcam", camera_index=camera_index, width=width, height=height, fps=fps)
    if not source.open():
        raise RuntimeError(f"Unable to open webcam index {camera_index}")

    frame_count = 0
    sample_count = int(seconds * fps)
    metadata = {
        "source": "webcam",
        "date": datetime.now().isoformat(),
        "resolution": {"width": width, "height": height},
        "fps": fps,
        "camera_index": camera_index,
        "record_duration_seconds": seconds,
    }

    metadata_path = video_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    try:
        while frame_count < sample_count:
            frame_info = source.read()
            if frame_info is None:
                continue
            file_name = video_dir / f"frame_{frame_count:05d}.jpg"
            cv2.imwrite(str(file_name), frame_info.frame)
            frame_count += 1
    finally:
        source.release()

    return video_dir


def main():
    parser = argparse.ArgumentParser(description="Collect webcam footage for development and training datasets.")
    parser.add_argument("--output-dir", type=str, default="dataset/raw_videos")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--camera-index", type=int, default=DEFAULT_CAMERA_INDEX)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    args = parser.parse_args()

    path = collect_webcam_dataset(
        output_dir=args.output_dir,
        seconds=args.seconds,
        fps=args.fps,
        camera_index=args.camera_index,
        width=args.width,
        height=args.height,
    )
    print(f"Dataset captured to: {path}")


if __name__ == "__main__":
    main()
