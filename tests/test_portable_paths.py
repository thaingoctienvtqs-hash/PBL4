from src.utils.config import PROJECT_ROOT, _configured_path
from src.services.status import get_status, save_status


def test_frame_and_status_default_under_project_data_directory(monkeypatch):
    monkeypatch.delenv("PBL4_FRAME_PATH", raising=False)
    monkeypatch.delenv("PBL4_STATUS_PATH", raising=False)

    assert _configured_path("PBL4_FRAME_PATH", "webcam_frame.jpg") == (
        PROJECT_ROOT / "server" / "data" / "webcam_frame.jpg"
    ).resolve()
    assert _configured_path("PBL4_STATUS_PATH", "webcam_status.txt") == (
        PROJECT_ROOT / "server" / "data" / "webcam_status.txt"
    ).resolve()


def test_frame_and_status_accept_absolute_or_project_relative_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("PBL4_FRAME_PATH", "captures/current.jpg")
    assert _configured_path("PBL4_FRAME_PATH", "webcam_frame.jpg") == (
        PROJECT_ROOT / "captures" / "current.jpg"
    ).resolve()

    absolute_path = tmp_path / "external" / "status.txt"
    monkeypatch.setenv("PBL4_STATUS_PATH", str(absolute_path))
    assert _configured_path("PBL4_STATUS_PATH", "webcam_status.txt") == absolute_path.resolve()


def test_status_writer_creates_parent_directory(tmp_path):
    target = tmp_path / "runtime" / "status.txt"
    save_status("OK", target)
    assert get_status(target) == "OK"
