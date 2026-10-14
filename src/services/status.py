"""Persist structured runtime status while keeping the legacy status-text file."""

import os
import tempfile
from pathlib import Path

from src.services.event_store import EventStore
from src.utils.config import load_settings, resolve_path


def save_status(status, path=None, **details):
    settings = load_settings()
    payload = EventStore(resolve_path(settings, "event_db")).set_status(status, **details)
    if path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp",
                                         dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(str(status) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, str(target))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return payload


def get_status(path=None):
    settings = load_settings()
    status = EventStore(resolve_path(settings, "event_db")).get_status()
    if status is not None:
        return status
    if path:
        target = Path(path).expanduser()
        if target.is_file():
            return {"status": target.read_text(encoding="utf-8").strip(), "legacy": True}
    return {"status": "NOT_STARTED", "message": "The inference worker has not started"}
