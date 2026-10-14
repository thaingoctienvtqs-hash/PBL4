"""Capture laptop webcam frames to a JPEG for PBL4 file-watch mode (Windows)."""
import argparse
import os
import sys
import time
from pathlib import Path

import cv2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--output", default="data/webcam_frame.jpg")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(args.index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(args.index)
    if not cap.isOpened():
        print("ERROR: cannot open webcam index {}".format(args.index), file=sys.stderr)
        return 2
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    try:
        for _ in range(5):  # let exposure settle
            cap.read()
        while True:
            saved = False
            got, frame = cap.read()
            if not got or frame is None:
                print("WARN: frame read failed", file=sys.stderr)
            else:
                encoded, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if encoded:
                    tmp = out.with_name(out.name + ".tmp")
                    tmp.write_bytes(buf.tobytes())
                    os.replace(str(tmp), str(out))
                    saved = True
                    print("saved {} {}x{}".format(out, frame.shape[1], frame.shape[0]))
            if args.once:
                return 0 if saved else 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped")
        return 0
    finally:
        cap.release()


if __name__ == "__main__":
    sys.exit(main())