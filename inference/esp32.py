from __future__ import annotations

import argparse

from inference.camera_factory import build_camera_source
from inference.config import DEFAULT_ESP32_URL, DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH


def main():
    parser = argparse.ArgumentParser(description="Open an ESP32-CAM stream. NOT HARDWARE-VALIDATED.")
    parser.add_argument("--url", type=str, default=DEFAULT_ESP32_URL)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    args = parser.parse_args()

    source = build_camera_source("esp32", url=args.url, width=args.width, height=args.height, fps=args.fps)
    print(f"Attempting ESP32 stream: {args.url}")
    ok = source.open()
    if not ok:
        raise RuntimeError("ESP32 camera stream could not be opened. NOT HARDWARE-VALIDATED.")
    print("ESP32 stream connected.")
    try:
        while True:
            frame_info = source.read()
            if frame_info is None:
                break
            print("Received frame", frame_info.width, frame_info.height)
            if cv2 := __import__("cv2"):
                cv2.imshow("ESP32 Stream", frame_info.frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        source.release()


if __name__ == "__main__":
    main()
