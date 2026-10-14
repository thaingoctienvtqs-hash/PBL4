"""Select and save a normalized four-corner painting ROI.

Run with ``python -m src.calibrate_roi --image path/to/frame.jpg`` or
``--camera-url http://.../capture``. Enter confirms and saves; Escape cancels.
"""

import argparse
import math
import sys
from pathlib import Path

from src.core.geometry import validate_polygon
from src.services.camera import CaptureError, fetch_jpeg
from src.utils.config import load_settings, save_settings


def _read_source(args, settings, cv2):
    if args.image:
        image = cv2.imread(str(Path(args.image).expanduser()))
        if image is None:
            raise ValueError("sample image is missing or unreadable: {}".format(args.image))
        return image
    url = args.camera_url or settings["camera"].get("url")
    if not url:
        raise CaptureError("provide --camera-url or configure camera.url/PBL4_CAMERA_URL")
    import numpy as np
    data = fetch_jpeg(url, settings["camera"]["request_timeout_seconds"])
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("camera returned a JPEG that OpenCV could not decode")
    return image


def _clockwise_from_center(points):
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    return sorted(points, key=lambda point: math.atan2(point[1] - center_y,
                                                        point[0] - center_x))


def select_corners(cv2, image):
    """Open a preview, collect four corners, and return them in perimeter order."""
    height, width = image.shape[:2]
    if width <= 0 or height <= 0:
        raise ValueError("source image has invalid dimensions")
    scale = min(1.0, 1280.0 / width, 800.0 / height)
    display = (image if scale == 1.0 else cv2.resize(
        image, (max(1, int(round(width * scale))), max(1, int(round(height * scale))))))
    scale_x, scale_y = display.shape[1] / float(width), display.shape[0] / float(height)
    state = {"points": []}

    def on_mouse(event, x, y, flags, unused):
        if event == cv2.EVENT_LBUTTONDOWN and len(state["points"]) < 4:
            state["points"].append((x / scale_x, y / scale_y))

    window = "PBL4 ROI calibration"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window, on_mouse)
    try:
        while True:
            preview = display.copy()
            selected = state["points"]
            if selected:
                import numpy as np
                points = np.asarray([(int(round(x * scale_x)), int(round(y * scale_y)))
                                     for x, y in selected], dtype="int32")
                for index, point in enumerate(points):
                    cv2.circle(preview, tuple(point), 5, (0, 255, 255), -1)
                    cv2.putText(preview, str(index + 1), tuple(point + (7, -7)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                if len(points) >= 2:
                    if len(points) == 4:
                        ordered = _clockwise_from_center(selected)
                        points = np.asarray([(int(round(x * scale_x)), int(round(y * scale_y)))
                                             for x, y in ordered], dtype="int32")
                        cv2.polylines(preview, [points.reshape((-1, 1, 2))], True,
                                      (0, 255, 0), 2)
                    else:
                        cv2.polylines(preview, [points.reshape((-1, 1, 2))], False,
                                      (0, 255, 0), 2)
            instruction = "Click 4 painting corners | Enter save | U undo | R reset | Esc cancel"
            cv2.putText(preview, instruction, (12, 26), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imshow(window, preview)
            key = cv2.waitKey(30) & 0xFF
            if key in (13, 10):
                if len(selected) != 4:
                    print("Select exactly four corners before confirming.", file=sys.stderr)
                    continue
                ordered = _clockwise_from_center(selected)
                try:
                    return validate_polygon(ordered)
                except ValueError as error:
                    print("ROI is invalid: {}. Reset and select four perimeter corners.".format(error),
                          file=sys.stderr)
            elif key in (ord("u"), ord("U")) and selected:
                selected.pop()
            elif key in (ord("r"), ord("R")):
                selected[:] = []
            elif key in (27, ord("q"), ord("Q")):
                return None
    finally:
        cv2.destroyWindow(window)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image", help="real sample image to calibrate")
    source.add_argument("--camera-url", help="ESP32-CAM /capture URL; one JPEG request is made")
    parser.add_argument("--config", help="PBL4 JSON config to update; defaults to PBL4_CONFIG")
    parser.add_argument("--shape", choices=("polygon", "rectangle"), default="polygon",
                        help="save a perspective polygon or its axis-aligned rectangle")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    try:
        import cv2
    except ImportError as error:
        print("ROI calibration requires OpenCV in this Python environment: {}".format(error),
              file=sys.stderr)
        return 2
    try:
        image = _read_source(args, settings, cv2)
        points = select_corners(cv2, image)
        if points is None:
            print("Cancelled; ROI configuration was not changed.")
            return 1
        height, width = image.shape[:2]
        normalized = [[min(1.0, max(0.0, x / width)),
                       min(1.0, max(0.0, y / height))] for x, y in points]
        xs, ys = [point[0] for point in normalized], [point[1] for point in normalized]
        roi = settings["roi"]
        roi.update({"enabled": True, "shape": args.shape, "normalized": True,
                    "coordinates": [min(xs), min(ys), max(xs), max(ys)],
                    "points": normalized if args.shape == "polygon" else []})
        target = save_settings(settings, args.config)
        print("ROI saved to {}: shape={}, normalized points={}".format(
            target, args.shape, normalized))
        return 0
    except (CaptureError, OSError, ValueError, ImportError, cv2.error) as error:
        print("ROI calibration failed: {}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
