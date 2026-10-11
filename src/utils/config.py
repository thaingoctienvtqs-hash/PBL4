import os
from pathlib import Path


ROI = (0, 0, 640, 480)

OC_THRESH = 0.6
OVERLAP_THRESH = 0.3

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _configured_path(environment_variable, default_name):
    value = os.environ.get(environment_variable)
    path = Path(value).expanduser() if value else Path("server") / "data" / default_name
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


FRAME_PATH = str(_configured_path("PBL4_FRAME_PATH", "webcam_frame.jpg"))
STATUS_PATH = str(_configured_path("PBL4_STATUS_PATH", "webcam_status.txt"))
