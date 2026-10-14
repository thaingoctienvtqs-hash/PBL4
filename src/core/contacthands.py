"""Adapter from the two-stream ContactHands model to the monitor worker."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = str(PROJECT_ROOT / "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from detect import prepare_first_stream, prepare_second_stream


class ContactHandsDetector:
    def __init__(self, config=None, weights=None, score_thresh=0.7,
                 second_stream_config=None, second_stream_weights=None,
                 device="auto"):
        config = config or PROJECT_ROOT / "src" / "configs" / "ContactHands.yaml"
        weights = weights or PROJECT_ROOT / "models" / "combined_data_model.pth"
        self.model2 = prepare_second_stream(
            weights=second_stream_weights,
            config_file=second_stream_config,
            device=device,
        )
        self.model1 = prepare_first_stream(
            config,
            weights,
            score_thresh,
            device=device,
        )

    def predict(self, image):
        outputs = self.model1(image, self.model2)
        if "instances" not in outputs:
            raise RuntimeError("ContactHands model output has no instances")
        return outputs["instances"]
