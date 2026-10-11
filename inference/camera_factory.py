from __future__ import annotations

from inference.camera_base import ESP32CameraSource, WebcamCameraSource
from inference.config import (
    DEFAULT_CAMERA_BACKEND,
    DEFAULT_CAMERA_INDEX,
    DEFAULT_CAMERA_SOURCE,
    DEFAULT_ESP32_URL,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
)


def build_camera_source(camera_source: str = DEFAULT_CAMERA_SOURCE, **kwargs):
    source_name = (camera_source or DEFAULT_CAMERA_SOURCE).lower()

    if source_name == "webcam":
        return WebcamCameraSource(
            camera_index=kwargs.get("camera_index", DEFAULT_CAMERA_INDEX),
            width=kwargs.get("width", DEFAULT_WIDTH),
            height=kwargs.get("height", DEFAULT_HEIGHT),
            fps=kwargs.get("fps", DEFAULT_FPS),
            backend=kwargs.get("backend", DEFAULT_CAMERA_BACKEND),
            backend_priority=kwargs.get("backend_priority"),
        )

    if source_name == "esp32":
        return ESP32CameraSource(
            stream_url=kwargs.get("url", kwargs.get("stream_url", DEFAULT_ESP32_URL)),
            width=kwargs.get("width", DEFAULT_WIDTH),
            height=kwargs.get("height", DEFAULT_HEIGHT),
            fps=kwargs.get("fps", DEFAULT_FPS),
        )

    raise ValueError(f"Unsupported camera source: {camera_source}")
