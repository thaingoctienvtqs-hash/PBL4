"""Explicit, opt-in trace construction. No device, DB, network or file writes on import."""
import copy
import json
import os
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .schema import (FRAME_STAGES, ALERT_STAGES, DATA_KINDS, EXECUTION_MODES,
                     measured, unknown, validate_record, validate_stamp, text)

BASE = Path(__file__).resolve().parent

class ProcessClock:
    def __init__(self, clock_id=None, epoch_id=None, read_ns=None):
        self.epoch_id = uuid.uuid4().hex if epoch_id is None else epoch_id
        self.clock_id = "process:" + self.epoch_id if clock_id is None else clock_id
        self.read_ns = read_ns or time.monotonic_ns
        text(self.clock_id, "clock_id")
        text(self.epoch_id, "epoch_id")

    def stamp(self):
        return measured(self.read_ns(), self.clock_id)

class FrameTrace:
    def __init__(self, source_id, session_id, frame_id, data_kind, phase, clock=None):
        self.clock = clock or ProcessClock()
        self.record = dict(
            schema_version=1, record_type="FRAME", data_kind=data_kind,
            source_id=source_id, session_id=session_id, frame_id=frame_id,
            phase=phase, frame_status="PROCESSED",
            clock_domains={self.clock.clock_id: dict(kind="MONOTONIC", epoch_id=self.clock.epoch_id)},
            clock_sync=[], timestamps={name: unknown() for name in FRAME_STAGES},
            execution_modes={name: "UNKNOWN" for name in ("stream1", "stream2", "inference")},
            prediction_ready_confirmed=False, alerts=[], gpu_intervals={}, issues=[])
        self.record["timestamps"]["t_capture"] = unknown("UNKNOWN", "source_capture_timestamp_not_provided")
        validate_record(self.record)

    def add_clock(self, clock_id, kind, epoch_id):
        proposed = copy.deepcopy(self.record)
        domain = dict(kind=kind, epoch_id=epoch_id)
        if clock_id in proposed["clock_domains"] and proposed["clock_domains"][clock_id] != domain:
            raise ValueError("Do not reuse a clock ID across epochs")
        proposed["clock_domains"][clock_id] = domain
        validate_record(proposed)
        self.record = proposed

    def add_sync(self, mapping):
        proposed = copy.deepcopy(self.record)
        proposed["clock_sync"].append(copy.deepcopy(mapping))
        validate_record(proposed)
        self.record = proposed

    def _set(self, stamps, stage, stamp, replace=False):
        validate_stamp(stamp, self.record["clock_domains"], capture=stage == "t_capture")
        if stamps.get(stage, unknown())["status"] in ("MEASURED", "ESTIMATED") and not replace:
            raise ValueError("Timestamp already measured; replacement must be explicit")
        stamps[stage] = copy.deepcopy(stamp)

    def mark(self, stage, replace=False):
        if stage not in FRAME_STAGES or stage in ("t_capture", "t_prediction_ready"):
            raise ValueError("Capture/readiness require their explicit API")
        self._set(self.record["timestamps"], stage, self.clock.stamp(), replace)

    def set_capture(self, stamp):
        # Caller supplies an actual source timestamp and declares its domain.
        # Neither file mtime nor the act of reading a JPEG is a capture event.
        if stamp["status"] in ("MEASURED", "ESTIMATED") and stamp["method"] == "monotonic_ns":
            raise ValueError("Capture requires source provenance, not a local clock-now placeholder")
        self._set(self.record["timestamps"], "t_capture", stamp)

    def set_timestamp(self, stage, stamp, replace=False):
        if stage not in FRAME_STAGES or stage in ("t_capture", "t_prediction_ready"):
            raise ValueError("Use explicit capture/readiness API")
        self._set(self.record["timestamps"], stage, stamp, replace)

    def prediction_ready(self, confirmed=False):
        if type(confirmed) is not bool:
            raise ValueError("Readiness must be a boolean")
        self.record["prediction_ready_confirmed"] = confirmed
        stamp = self.clock.stamp() if confirmed else unknown("UNKNOWN", "prediction_readiness_unconfirmed")
        self._set(self.record["timestamps"], "t_prediction_ready", stamp)

    def set_execution_mode(self, stage, mode):
        if stage not in ("stream1", "stream2", "inference") or mode not in EXECUTION_MODES:
            raise ValueError("Invalid execution mode")
        self.record["execution_modes"][stage] = mode

    def add_alert(self, event_key, new_event=True):
        text(event_key, "event_key")
        if type(new_event) is not bool or any(a["event_key"] == event_key for a in self.record["alerts"]):
            raise ValueError("Invalid/duplicate alert")
        self.record["alerts"].append(dict(
            event_key=event_key, new_event=new_event,
            timestamps={name: unknown() for name in ALERT_STAGES}, acknowledgements={}))

    def _alert(self, event_key):
        for alert in self.record["alerts"]:
            if alert["event_key"] == event_key:
                return alert
        raise ValueError("Unknown alert event")

    def mark_alert(self, event_key, stage, stamp=None):
        if stage not in ALERT_STAGES or stage in ("t_alert_delivered", "t_alert_visible"):
            raise ValueError("Delivery/visibility require explicit acknowledgement")
        self._set(self._alert(event_key)["timestamps"], stage, stamp or self.clock.stamp())

    def acknowledge(self, event_key, stage, stamp, signal_id, observer):
        if stage not in ("t_alert_delivered", "t_alert_visible"):
            raise ValueError("Invalid acknowledgement stage")
        validate_stamp(stamp, self.record["clock_domains"])
        if stamp["status"] not in ("MEASURED", "ESTIMATED"):
            raise ValueError("An acknowledgement needs its observer timestamp")
        alert = self._alert(event_key)
        if stage in alert["acknowledgements"]:
            raise ValueError("Acknowledgement already recorded")
        acknowledgement = dict(kind="DELIVERY_ACK" if stage == "t_alert_delivered" else "DISPLAY_RENDER_ACK",
                               signal_id=text(signal_id), observer=text(observer), event_key=event_key)
        self._set(alert["timestamps"], stage, stamp)
        alert["acknowledgements"][stage] = acknowledgement

    def record_gpu_interval(self, stage, duration_ms, synchronized):
        if stage not in ("stream1", "stream2", "inference"):
            raise ValueError("Invalid GPU stage")
        interval = dict(status="MEASURED", duration_ms=duration_ms,
                        method="CUDA_EVENT", synchronized=synchronized)
        proposed = copy.deepcopy(self.record)
        proposed["gpu_intervals"][stage] = interval
        validate_record(proposed)
        self.record = proposed

    def snapshot(self):
        return validate_record(self.record)

def _safe_parent(parent):
    allowed = BASE / "runs"
    candidate = Path(parent) if parent is not None else allowed
    resolved = candidate.resolve()
    if resolved != allowed.resolve() and allowed.resolve() not in resolved.parents:
        raise ValueError("Artifacts must stay under latency_diagnostics/runs")
    # Refuse symlink/junction ancestors, including existing output parents.
    for node in [candidate] + list(candidate.parents):
        if node.exists():
            flags = getattr(node.lstat(), "st_file_attributes", 0)
            if node.is_symlink() or flags & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise ValueError("Reparse/symlink output paths are forbidden")
        if node == BASE:
            break
    return resolved

def create_run_directory(parent=None, label="offline"):
    if label not in ("offline", "synthetic", "real", "tests", "analysis"):
        raise ValueError("Invalid run label")
    parent = _safe_parent(parent)
    path = parent / (label + "_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path

class JsonlWriter:
    """A newly created, append-only owned file; never reopens an existing artifact."""
    def __init__(self, path, data_kind):
        if data_kind not in DATA_KINDS:
            raise ValueError("Explicit data kind required")
        path = Path(path)
        _safe_parent(path.parent)
        self.data_kind = data_kind
        self.path = path
        self.handle = path.open("x", encoding="utf-8", newline="\n")

    def write(self, record):
        value = validate_record(record)
        if value["data_kind"] != self.data_kind:
            raise ValueError("Never mix real and synthetic records in one writer")
        line = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        self.handle.write(line)
        self.handle.flush()

    def close(self):
        self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
