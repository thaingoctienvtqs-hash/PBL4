"""Explicit model smoke test (not part of the camera-free unit suite).

Run from the PBL4 root with a real image and the configured model environment:
    python tests/test_contacthands.py --image data/camera_frame.jpg
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="real input image path")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=None)
    args = parser.parse_args(argv)
    try:
        import cv2
        from src.core.contacthands import ContactHandsDetector
    except ImportError as error:
        parser.error("model smoke test needs OpenCV, PyTorch and Detectron2: {}".format(error))
    image = cv2.imread(str(Path(args.image).expanduser()))
    if image is None:
        parser.error("image is missing or unreadable: {}".format(args.image))
    detector = ContactHandsDetector(device=args.device)
    instances = detector.predict(image)
    print("Model loaded; detections in this real image: {}".format(len(instances)))
    for box, score, states in zip(instances.pred_boxes.tensor.tolist(),
                                  instances.scores.tolist(), instances.pred_cats.tolist()):
        print("box={} hand_score={:.3f} scores(No,Self,Person,Object)={}".format(
            [round(value, 1) for value in box], float(score),
            [round(float(value), 3) for value in states]))
    print("Smoke test completed; these outputs are model predictions, not accuracy metrics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
