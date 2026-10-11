import numpy as np

from src.yolo_pipeline import box_overlap_ratio, detect_contact


def test_box_overlap_ratio_outside_roi_is_zero():
    box = np.array([100, 100, 200, 200], dtype=np.float32)
    roi = np.array([0, 0, 50, 50], dtype=np.float32)

    assert box_overlap_ratio(box, roi) == 0.0


def test_detect_contact_flags_overlapping_high_confidence_box():
    boxes = [
        np.array([10, 10, 90, 90], dtype=np.float32),
        np.array([300, 300, 350, 350], dtype=np.float32),
    ]
    scores = [0.92, 0.7]
    roi = np.array([0, 0, 100, 100], dtype=np.float32)

    alerts = detect_contact(boxes, scores, roi, score_thresh=0.8, overlap_thresh=0.3)

    assert len(alerts) == 1
    assert alerts[0]["box"][0] == 10
    assert alerts[0]["overlap_ratio"] >= 0.3
