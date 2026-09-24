import cv2

from src.core.contacthands import ContactHandsDetector
from src.services.camera import Camera
from src.services.alert import trigger_alert
from src.services.status import save_status
from src.utils.config import ROI, OC_THRESH, OVERLAP_THRESH


def main():
    print("Loading ContactHands...")

    detector = ContactHandsDetector()

    print("ContactHands loaded.")
    print("Starting camera...")

    camera = Camera(0)

    try:
        while True:
            frame = camera.read()

            if frame is None:
                print("Khong doc duoc frame")
                break

            touches = detector.detect(
                frame,
                ROI,
                OC_THRESH,
                OVERLAP_THRESH,
            )

            if touches:
                status = "ALERT: CHAM TRANH"
                trigger_alert(status)
            else:
                status = "OK"
                print(status, flush=True)

            save_status(
                status,
                "webcam_status.txt",
            )

            cv2.imshow("PBL4 - Painting Protection", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()


if __name__ == "__main__":
    main()
