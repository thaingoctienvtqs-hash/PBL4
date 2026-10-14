"""Fetch ESP32-CAM /capture snapshots on Windows using only the standard library."""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.camera import CaptureError, capture_to_file
from src.utils.config import load_settings, resolve_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-url", help="ESP32-CAM /capture URL (or PBL4_CAMERA_URL)")
    parser.add_argument("--output", help="snapshot destination (default: data/camera_frame.jpg)")
    parser.add_argument("--config", help="PBL4 JSON config path")
    parser.add_argument("--interval", type=float, help="seconds between snapshots")
    parser.add_argument("--timeout", type=float, help="HTTP timeout in seconds")
    parser.add_argument("--once", action="store_true", help="capture one image")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
    except Exception as error:
        print("ERROR: invalid PBL4 config: {}".format(error), file=sys.stderr)
        return 2
    url = args.camera_url or settings["camera"]["url"]
    if not url:
        parser.error("set PBL4_CAMERA_URL or configure camera.url in configs/pbl4.json")
    destination = Path(args.output).expanduser() if args.output else resolve_path(settings, "capture_frame")
    interval = args.interval or settings["camera"]["poll_interval_seconds"]
    timeout = args.timeout or settings["camera"]["request_timeout_seconds"]
    if interval <= 0 or timeout <= 0:
        parser.error("--interval and --timeout must be positive")
    print("ESP32-CAM snapshots -> {}".format(destination))
    previous_state = None
    while True:
        try:
            path = capture_to_file(url, destination, timeout)
            if previous_state != "connected":
                print("{} CAMERA_CONNECTED; snapshots -> {}".format(
                    datetime.now().isoformat(timespec="seconds"), path), flush=True)
            previous_state = "connected"
        except CaptureError as error:
            state = "disconnected:" + str(error)
            if state != previous_state:
                print("{} CAMERA_DISCONNECTED: {}".format(
                    datetime.now().isoformat(timespec="seconds"), error), file=sys.stderr, flush=True)
            previous_state = state
            if args.once:
                return 1
        except OSError as error:
            state = "write-error:" + str(error)
            if state != previous_state:
                print("{} ERROR writing snapshot: {}".format(
                    datetime.now().isoformat(timespec="seconds"), error), file=sys.stderr, flush=True)
            previous_state = state
            if args.once:
                return 1
        if args.once:
            return 0
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

