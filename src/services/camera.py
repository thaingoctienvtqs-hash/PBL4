"""USB camera and ESP32-CAM adapters plus crash-safe snapshot storage."""

import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class CaptureError(RuntimeError):
    pass


def atomic_write_bytes(destination, data):
    """Write beside the target, flush, then atomically replace it."""
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp",
                                     dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(destination))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def fetch_jpeg(url, timeout_seconds=5.0, max_bytes=20 * 1024 * 1024):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise CaptureError("camera URL must be an http(s) /capture URL")
    request = Request(url, headers={"Accept": "image/jpeg", "User-Agent": "PBL4-camera/1.0"})
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            if response.status < 200 or response.status >= 300:
                raise CaptureError("camera returned HTTP {}".format(response.status))
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not ("image/" in content_type or "octet-stream" in content_type):
                raise CaptureError("camera returned unexpected content type {}".format(content_type))
            data = response.read(max_bytes + 1)
    except HTTPError as error:
        raise CaptureError("camera returned HTTP {}".format(error.code))
    except (URLError, TimeoutError, OSError) as error:
        raise CaptureError("camera connection failed: {}".format(error))
    if not data:
        raise CaptureError("camera returned an empty response")
    if len(data) > max_bytes:
        raise CaptureError("camera image exceeds {} byte limit".format(max_bytes))
    if not data.startswith(b"\xff\xd8\xff"):
        raise CaptureError("camera response is not a JPEG image")
    if not data.rstrip().endswith(b"\xff\xd9"):
        raise CaptureError("camera response is a truncated JPEG image")
    return data


def capture_to_file(url, destination, timeout_seconds=5.0):
    return atomic_write_bytes(destination, fetch_jpeg(url, timeout_seconds))


class Camera:
    """Backward-compatible USB camera reader; OpenCV is imported only when opened."""
    def __init__(self, camera_id=0):
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("USB camera mode requires OpenCV: {}".format(error))
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(camera_id)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError("Could not open USB camera {}".format(camera_id))

    def read(self):
        ret, frame = self.cap.read()
        return frame if ret else None

    def release(self):
        self.cap.release()
