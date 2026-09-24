import cv2
import os
import time

from src.core.contacthands import ContactHandsDetector
from src.services.alert import trigger_alert
from src.services.status import save_status
from src.utils.config import (
    ROI,
    OC_THRESH,
    OVERLAP_THRESH,
)

FRAME_PATH = "/mnt/c/Users/LEGION/PaintingProtection/webcam_frame.jpg"
STATUS_PATH = "/mnt/c/Users/LEGION/PaintingProtection/webcam_status.txt"


def main():
    print("Loading ContactHands...", flush=True)

    detector = ContactHandsDetector()

    print("ContactHands loaded.", flush=True)
    print("Waiting for webcam frames...", flush=True)

    last_mtime = 0

    while True:
        try:
            if not os.path.exists(FRAME_PATH):
                time.sleep(0.05)
                continue

            mtime = os.path.getmtime(FRAME_PATH)

            if mtime == last_mtime:
                time.sleep(0.03)
                continue

            last_mtime = mtime

            image = cv2.imread(FRAME_PATH)

            if image is None:
                continue

            touches = detector.detect(
                image,
                ROI,
                OC_THRESH,
                OVERLAP_THRESH,
            )

            if touches:
                status = "ALERT: CHAM TRANH"
                trigger_alert(status)
            else:
                status = "OK"

            save_status(status, STATUS_PATH)

            print(status, flush=True)

        except KeyboardInterrupt:
            print("\nDa dung PBL4 realtime.")
            break

        except Exception as e:
            print("ERROR:", repr(e), flush=True)
            time.sleep(0.2)


if __name__ == "__main__":
    main()
