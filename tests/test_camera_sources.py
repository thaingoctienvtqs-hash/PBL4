from inference.camera_base import probe_camera_backends
from inference.camera_factory import build_camera_source
from inference.config import DEFAULT_CAMERA_BACKEND, DEFAULT_CAMERA_SOURCE, WINDOWS_WEBCAM_BACKEND_PRIORITY


def test_default_camera_source_is_webcam():
    assert DEFAULT_CAMERA_SOURCE == "webcam"


def test_default_windows_backend_prefers_dshow():
    assert DEFAULT_CAMERA_BACKEND == "auto"
    assert WINDOWS_WEBCAM_BACKEND_PRIORITY[0] == "dshow"


def test_build_camera_source_webcam():
    source = build_camera_source(
        "webcam",
        camera_index=1,
        width=1280,
        height=720,
        fps=30,
        backend="dshow",
    )
    assert source.kind == "webcam"
    assert source.camera_index == 1
    assert source.backend == "dshow"


def test_build_camera_source_esp32():
    source = build_camera_source("esp32", url="http://192.168.1.10:81/stream")
    assert source.kind == "esp32"
    assert source.stream_url == "http://192.168.1.10:81/stream"


def test_probe_camera_backends_returns_empty_when_no_camera_present():
    results = probe_camera_backends(camera_index=999, backend_priority=["dshow", "msmf", "default"])
    assert results == []
