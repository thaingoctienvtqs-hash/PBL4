import platform

import cv2

DEFAULT_CAMERA_SOURCE = "webcam"
DEFAULT_CAMERA_INDEX = 0
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 30
DEFAULT_CAMERA_BACKEND = "auto"
DEFAULT_ESP32_URL = "http://192.168.1.10:81/stream"
DEFAULT_YOLO_MODEL = "yolov8n-seg.pt"
DEFAULT_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_IMAGE_SIZE = 640

WINDOWS_WEBCAM_BACKEND_PRIORITY = ["dshow", "msmf", "default"]
SUPPORTED_CAMERA_BACKENDS = {
    "default": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
}

CAMERA_SOURCE_CHOICES = {
    "webcam": "Laptop webcam development path",
    "esp32": "ESP32-CAM network stream path (NOT HARDWARE-VALIDATED)",
}


def get_default_backend_priority():
    if platform.system().lower() == "windows":
        return list(WINDOWS_WEBCAM_BACKEND_PRIORITY)
    return ["default"]
