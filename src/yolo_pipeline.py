from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from tools.runtime_paths import configure_runtime_paths

configure_runtime_paths(PROJECT_ROOT)

import cv2
import numpy as np
from ultralytics import YOLO

DEFAULT_YOLO_MODEL = "yolov8n-seg.pt"


def box_overlap_ratio(box: Iterable[float], roi: Iterable[float]) -> float:
    box_array = np.asarray(box, dtype=np.float32)
    roi_array = np.asarray(roi, dtype=np.float32)

    if box_array.shape != (4,) or roi_array.shape != (4,):
        raise ValueError("box and roi must each have exactly 4 values: x1, y1, x2, y2")

    x1 = max(float(box_array[0]), float(roi_array[0]))
    y1 = max(float(box_array[1]), float(roi_array[1]))
    x2 = min(float(box_array[2]), float(roi_array[2]))
    y2 = min(float(box_array[3]), float(roi_array[3]))

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    box_area = max(1.0, (float(box_array[2]) - float(box_array[0])) * (float(box_array[3]) - float(box_array[1])))
    return float(intersection / box_area)


def detect_contact(
    boxes: Iterable[Iterable[float]],
    scores: Iterable[float],
    roi: Iterable[float],
    score_thresh: float = 0.5,
    overlap_thresh: float = 0.3,
):
    alerts: List[dict] = []

    for box, score in zip(boxes, scores):
        s = float(score)
        if s < score_thresh:
            continue

        ratio = box_overlap_ratio(box, roi)
        if ratio < overlap_thresh:
            continue

        alerts.append(
            {
                "box": [float(v) for v in box],
                "score": s,
                "overlap_ratio": float(ratio),
            }
        )

    return alerts


class YOLOContactDetector:
    def __init__(
        self,
        model_path: str = DEFAULT_YOLO_MODEL,
        score_thresh: float = 0.5,
        overlap_thresh: float = 0.3,
        imgsz: int = 320,
    ):
        checkpoint = Path(model_path).expanduser()
        if not checkpoint.is_absolute():
            checkpoint = PROJECT_ROOT / checkpoint
        self.model_path = str(checkpoint.resolve())
        self.model = YOLO(self.model_path)
        self.score_thresh = score_thresh
        self.overlap_thresh = overlap_thresh
        self.imgsz = imgsz

    def predict(self, image, conf: float | None = None, imgsz: int | None = None):
        used_conf = self.score_thresh if conf is None else conf
        used_imgsz = self.imgsz if imgsz is None else imgsz
        return self.model(image, conf=used_conf, imgsz=used_imgsz, verbose=False)

    def detect(self, image, roi, score_thresh: float | None = None, overlap_thresh: float | None = None):
        used_score_thresh = self.score_thresh if score_thresh is None else score_thresh
        used_overlap_thresh = self.overlap_thresh if overlap_thresh is None else overlap_thresh

        boxes: List[np.ndarray] = []
        scores: List[float] = []

        results = self.predict(image, conf=used_score_thresh, imgsz=self.imgsz)
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                confidence = float(box.conf[0])
                boxes.append(xyxy)
                scores.append(confidence)

        return detect_contact(
            boxes,
            scores,
            roi,
            score_thresh=used_score_thresh,
            overlap_thresh=used_overlap_thresh,
        )


def main():
    print("YOLO contact detector ready")


if __name__ == "__main__":
    main()
