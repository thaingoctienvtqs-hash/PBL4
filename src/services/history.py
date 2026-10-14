"""SQLite alert history with read-only compatibility for the old JSON log."""

import json
import time
from datetime import datetime
from pathlib import Path

from src.services.event_store import EventStore
from src.utils.config import load_settings, resolve_path

LEGACY_HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "history.json"


def _store():
    settings = load_settings()
    return EventStore(resolve_path(settings, "event_db")), settings


def save_alert(status, oc=None, overlap=None, image_path=None, details=None, timestamp=None):
    """Persist one event and honor the configured cooldown; never rewrites old JSON."""
    store, settings = _store()
    payload = dict(details or {})
    payload.update({"status": status, "oc": oc, "overlap": overlap})
    if timestamp is None:
        timestamp = time.time()
    return store.record_event(
        "AI_CONTACT_SUSPECTED_IN_ROI", payload, image_path,
        settings["alert"]["cooldown_seconds"], timestamp=timestamp,
    )


def _legacy_events():
    if not LEGACY_HISTORY_PATH.is_file():
        return []
    try:
        values = json.loads(LEGACY_HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return values if isinstance(values, list) else []


def get_history(limit=100, event_type=None, status=None):
    """Return recent database events plus the untouched pre-existing JSON history."""
    limit = max(1, min(int(limit), 1000))
    store, unused = _store()
    legacy = []
    for index, item in enumerate(_legacy_events()):
        value = dict(item)
        value.setdefault("event_id", "legacy-{}".format(index))
        value.setdefault("source", "legacy-json")
        value.setdefault("event_type", "legacy")
        value.setdefault("processing_status", "LEGACY")
        legacy.append(value)
    current = []
    for item in store.list_events(1000):
        details = item["details"]
        timestamp = item["timestamp"]
        try:
            shown_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            shown_time = "unknown"
        current.append({
            "event_id": item["id"], "time": shown_time,
            "event_type": item["kind"], "processing_status": item["status"],
            "timestamp": timestamp, "status": details.get(
                        "event_status", "AI contact candidate in painting ROI (unverified)"),
            "oc": (
            details.get("oc")
            if details.get("oc") is not None
            else details.get("object_contact_score")
        ),
        "overlap": (
            details.get("overlap")
            if details.get("overlap") is not None
            else details.get("roi_overlap")
        ),
            "image": Path(item["evidence_path"]).name if item["evidence_path"] else None,
            "evidence_path": item["evidence_path"], "source": "sqlite",
        })
    merged = legacy + current
    def sort_key(item):
        if isinstance(item.get("timestamp"), (int, float)):
            return float(item["timestamp"])
        try:
            return datetime.strptime(item.get("time", ""), "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, OSError, OverflowError):
            return 0.0
    merged.sort(key=sort_key, reverse=True)
    if event_type:
        merged = [item for item in merged if item.get("event_type") == event_type]
    if status:
        merged = [item for item in merged
                  if str(item.get("processing_status", "")).upper() == status.upper()]
    return merged[:limit]
