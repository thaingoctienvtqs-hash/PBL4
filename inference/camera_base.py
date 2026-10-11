from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from inference.config import SUPPORTED_CAMERA_BACKENDS, get_default_backend_priority


class CameraInitError(RuntimeError):
    pass


class InvalidCameraIndexError(CameraInitError):
    pass


class CameraUnavailableError(CameraInitError):
    pass


class CameraPermissionError(CameraInitError):
    pass


class CameraBackendError(CameraInitError):
    pass


@dataclass
class CameraFrame:
    frame: np.ndarray
    source: str
    width: int
    height: int
    fps: int
    metadata: dict[str, Any] | None = None


def _get_backend_id(backend_name: str):
    if backend_name is None:
        return cv2.CAP_ANY
    backend_name = str(backend_name).lower().strip()
    if backend_name == "auto":
        return cv2.CAP_ANY
    return SUPPORTED_CAMERA_BACKENDS.get(backend_name, cv2.CAP_ANY)


def get_backend_names_for_windows():
    return list(get_default_backend_priority())


def probe_camera_backends(camera_index: int = 0, backend_priority: list[str] | None = None):
    priorities = list(backend_priority or get_default_backend_priority())
    working = []

    for backend_name in priorities:
        backend_id = _get_backend_id(backend_name)
        cap = cv2.VideoCapture(camera_index, backend_id)
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        if ok and frame is not None:
            working.append({"camera_index": camera_index, "backend": backend_name, "backend_id": backend_id})
        cap.release()

    return working


class BaseCameraSource(ABC):
    kind: str = "base"

    @abstractmethod
    def open(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read(self) -> CameraFrame | None:
        raise NotImplementedError

    @abstractmethod
    def release(self) -> None:
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        return False


class WebcamCameraSource(BaseCameraSource):
    kind = "webcam"

    def __init__(
        self,
        camera_index: int = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        backend: str = "auto",
        backend_priority: list[str] | None = None,
    ):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.backend = backend.lower() if backend else "auto"
        self.backend_priority = list(backend_priority or get_default_backend_priority())
        self.cap = None
        self.last_error = None
        self.active_backend = None

    def _candidate_backends(self):
        if self.backend and self.backend != "auto":
            return [self.backend]
        return self.backend_priority

    def _open_with_backend(self, backend_name: str):
        backend_id = _get_backend_id(backend_name)
        cap = cv2.VideoCapture(self.camera_index, backend_id)
        if not cap.isOpened():
            msg = (
                f"Backend '{backend_name}' could not open camera index {self.camera_index}. "
                "The camera may be unavailable, occupied, or permission may be denied."
            )
            cap.release()
            return None, msg

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)

        ok, frame = cap.read()
        if not ok or frame is None:
            msg = (
                f"Backend '{backend_name}' opened camera index {self.camera_index} but did not return a valid frame. "
                "This often means the device is busy or the backend is incompatible with the current Windows camera stack."
            )
            cap.release()
            return None, msg

        self.cap = cap
        self.active_backend = backend_name
        self.last_error = None
        return cap, None

    def open(self) -> bool:
        self.release()
        last_error = None

        for backend_name in self._candidate_backends():
            cap, err = self._open_with_backend(backend_name)
            if cap is not None:
                return True
            last_error = err
            self.release()

        self.last_error = last_error or (
            f"Unable to open camera index {self.camera_index} with any supported backend. "
            "Check Windows camera access, device availability, or camera permissions."
        )
        return False

    def read(self) -> CameraFrame | None:
        if self.cap is None or not self.cap.isOpened():
            self.last_error = (
                f"Camera index {self.camera_index} is not open. "
                "The selected backend may have failed during initialization."
            )
            return None

        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.last_error = (
                f"The active webcam backend '{self.active_backend}' could not read a frame from camera index {self.camera_index}. "
                "Falling back to another supported backend if available."
            )
            self.release()
            return self._retry_next_backend()

        return CameraFrame(
            frame=frame,
            source="webcam",
            width=int(frame.shape[1]),
            height=int(frame.shape[0]),
            fps=self.fps,
            metadata={"camera_index": self.camera_index, "backend": self.active_backend},
        )

    def _retry_next_backend(self):
        tried = {self.active_backend} if self.active_backend else set()
        for backend_name in self._candidate_backends():
            if backend_name in tried:
                continue
            tried.add(backend_name)
            cap, err = self._open_with_backend(backend_name)
            if cap is not None:
                return self.read()
            self.last_error = err
        self.last_error = (
            f"Camera index {self.camera_index} failed on every supported backend. "
            "Check that the webcam is available, not in use by another app, and not blocked by Windows camera permissions."
        )
        return None

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.active_backend = None

    @property
    def is_open(self) -> bool:
        return self.cap is not None and self.cap.isOpened()


class ESP32CameraSource(BaseCameraSource):
    kind = "esp32"

    def __init__(self, stream_url: str, width: int = 640, height: int = 480, fps: int = 15):
        self.stream_url = stream_url
        self.width = width
        self.height = height
        self.fps = fps
        self.cap = None

    def open(self) -> bool:
        self.release()
        self.cap = cv2.VideoCapture(self.stream_url)
        if not self.cap.isOpened():
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        return True

    def read(self) -> CameraFrame | None:
        if self.cap is None or not self.cap.isOpened():
            return None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        return CameraFrame(
            frame=frame,
            source="esp32",
            width=int(frame.shape[1]),
            height=int(frame.shape[0]),
            fps=self.fps,
            metadata={"stream_url": self.stream_url},
        )

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    @property
    def is_open(self) -> bool:
        return self.cap is not None and self.cap.isOpened()
