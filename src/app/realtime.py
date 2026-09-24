import cv2
import os
import time
from pathlib import Path
from datetime import datetime

from src.core.contacthands import ContactHandsDetector
from src.services.alert import trigger_alert
from src.services.history import save_alert
from src.services.status import save_status
from src.utils.config import ROI, OC_THRESH, OVERLAP_THRESH


FRAME_PATH = "/mnt/c/Users/LEGION/PaintingProtection/webcam_frame.jpg"
STATUS_PATH = "/mnt/c/Users/LEGION/PaintingProtection/webcam_status.txt"

ALERT_DIR = Path(__file__).resolve().parents[1] / "data" / "alerts"
ALERT_DIR.mkdir(parents=True, exist_ok=True)


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
                OVERLAP_THRESH
            )

            if touches:
                status = "ALERT: CHAM TRANH"

                if trigger_alert(status):
                    _, oc, overlap = touches[0]

                    timestamp = datetime.now().strftime(
                        "%Y%m%d_%H%M%S_%f"
                    )

                    image_path = (
                        ALERT_DIR / f"alert_{timestamp}.jpg"
                    )

                    saved = cv2.imwrite(
                        str(image_path),
                        image
                    )

                    print(
                        f"Evidence: {image_path}",
                        flush=True
                    )

                    print(
                        f"Evidence saved: {saved}",
                        flush=True
                    )

                    save_alert(
                        status,
                        oc=oc,
                        overlap=overlap,
                        image_path=str(image_path)
                    )

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
