import cv2

from src.services.alert import trigger_alert
from src.services.camera import Camera
from src.services.status import save_status
from src.utils.config import OC_THRESH, OVERLAP_THRESH, ROI
from src.yolo_pipeline import YOLOContactDetector


def main():
    print("Loading YOLO ContactHands...")
    detector = YOLOContactDetector(model_path="yolov8n.pt", score_thresh=OC_THRESH, overlap_thresh=OVERLAP_THRESH)
    print("YOLO model loaded.")
    print("Starting camera...")

    camera = Camera(0)

    try:
        while True:
            frame = camera.read()

            if frame is None:
                print("Khong doc duoc frame")
                break

            touches = detector.detect(frame, ROI)

            if touches:
                status = "ALERT: CHAM TRANH"
                trigger_alert(status)
            else:
                status = "OK"
                print(status, flush=True)

            save_status(status, "webcam_status.txt")
            cv2.imshow("PBL4 - YOLO Contact Detection", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()


if __name__ == "__main__":
    main()
