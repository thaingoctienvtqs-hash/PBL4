from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from detect import (
    prepare_first_stream,
    prepare_second_stream,
    find_painting_touches,
)


class ContactHandsDetector:
    def __init__(
        self,
        config="./src/configs/ContactHands.yaml",
        weights="./models/combined_data_model.pth",
        score_thresh=0.7,
    ):
        self.model1 = prepare_first_stream(
            config,
            weights,
            score_thresh,
        )
        self.model2 = prepare_second_stream()

    def detect(self, image, roi, oc_thresh=0.6, overlap_thresh=0.3):
        outputs = self.model1(image, self.model2)
        instances = outputs["instances"].to("cpu")

        return find_painting_touches(
            instances,
            roi,
            oc_thresh,
            overlap_thresh,
        )
