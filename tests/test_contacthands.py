import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2

from src.core.contacthands import ContactHandsDetector
from src.utils.config import ROI, OC_THRESH, OVERLAP_THRESH

IMAGE_PATH = "/mnt/c/Users/LEGION/PaintingProtection/webcam_frame.jpg"

print("Loading model...")
detector = ContactHandsDetector()

print("Reading image...")
image = cv2.imread(IMAGE_PATH)

if image is None:
    raise RuntimeError(f"Khong doc duoc anh: {IMAGE_PATH}")

print("Running ContactHands...")
result = detector.detect(
    image,
    ROI,
    OC_THRESH,
    OVERLAP_THRESH,
)

if result:
    print(f"ALERT: CHAM TRANH - {len(result)} detection(s)")
    for box, oc, overlap in result:
        print(
            f"  OC={oc:.2f}, overlap={overlap:.2f}, "
            f"box={box}"
        )
else:
    print("OK - Khong phat hien cham tranh")
