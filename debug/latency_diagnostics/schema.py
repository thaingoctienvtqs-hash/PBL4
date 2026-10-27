"""Versioned, passive latency records. Python 3.7; standard library only."""
import copy
import math

SCHEMA_VERSION = 1
DATA_KINDS = ("SYNTHETIC_TEST", "REAL_INFERENCE")
PHASES = ("COLD_START", "WARM", "NOT_APPLICABLE", "UNKNOWN")
STATUSES = ("MEASURED", "ESTIMATED", "UNKNOWN", "NOT_AVAILABLE")
FRAME_STATUSES = ("PROCESSED", "DUPLICATE", "STALE", "DROPPED", "MISSING", "ERROR", "REJECTED")
EXECUTION_MODES = ("CPU_ONLY", "CUDA_SYNCHRONIZED_WALL", "CUDA_ENQUEUE_ONLY", "UNKNOWN")
FRAME_STAGES = (
    "t_capture", "t_request_start", "t_receive_complete", "t_file_publish",
    "t_worker_read_start", "t_worker_read_end", "t_decode_start", "t_decode_end",
    "t_inference_start", "t_stream2_start", "t_stream2_end", "t_stream1_start",
    "t_stream1_end", "t_prediction_ready", "t_tracking_end", "t_temporal_end", "t_decision_end")
ALERT_STAGES = ("t_alert_decision", "t_event_committed", "t_evidence_ready",
                "t_alert_visible", "t_alert_delivered")
MAX_NS = 2 ** 63 - 1

def text(value, label="identifier"):
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid " + label)
    return value

def integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= MAX_NS:
        raise ValueError("Invalid integer " + label)
    return value

def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required).issubset(value) or set(value) - set(required) - set(optional):
        raise ValueError("Missing/unknown fields: " + ",".join(required))
    return value

def unknown(status="NOT_AVAILABLE", reason="not_instrumented"):
    if status not in ("UNKNOWN", "NOT_AVAILABLE"):
        raise ValueError("Unknown stamp requires UNKNOWN or NOT_AVAILABLE")
    return dict(status=status, value_ns=None, clock_id=None, method=None,
                uncertainty_ns=None, reason=text(reason, "reason"))

def measured(value_ns, clock_id, method="monotonic_ns", status="MEASURED", uncertainty_ns=0):
    result = dict(status=status, value_ns=value_ns, clock_id=clock_id, method=method,
                  uncertainty_ns=uncertainty_ns, reason=None)
    validate_stamp(result)
    return result

def validate_stamp(stamp, domains=None, capture=False):
    fields(stamp, ("status", "value_ns", "clock_id", "method", "uncertainty_ns", "reason"))
    if stamp["status"] not in STATUSES:
        raise ValueError("Invalid timestamp status")
    if stamp["status"] in ("UNKNOWN", "NOT_AVAILABLE"):
        if any(stamp[k] is not None for k in ("value_ns", "clock_id", "method", "uncertainty_ns")):
            raise ValueError("Unavailable timestamp must not contain a numeric value")
        text(stamp["reason"], "reason")
    else:
        integer(stamp["value_ns"], "value_ns")
        integer(stamp["uncertainty_ns"], "uncertainty_ns")
        text(stamp["clock_id"], "clock_id")
        text(stamp["method"], "measurement method")
        if stamp["reason"] is not None:
            raise ValueError("Known timestamp reason must be null")
        if domains is not None and stamp["clock_id"] not in domains:
            raise ValueError("Undeclared clock domain")
        if capture and ("mtime" in stamp["method"].lower() or "file_stat" in stamp["method"].lower()):
            raise ValueError("File metadata is not a capture timestamp")
    return stamp

def validate_record(value):
    required = ("schema_version", "record_type", "data_kind", "source_id", "session_id",
                "frame_id", "phase", "frame_status", "clock_domains", "clock_sync",
                "timestamps", "execution_modes", "prediction_ready_confirmed", "alerts")
    fields(value, required, ("gpu_intervals", "ground_truth", "issues", "worker_state"))
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION or value["record_type"] != "FRAME":
        raise ValueError("Unsupported record schema")
    if value["data_kind"] not in DATA_KINDS or value["phase"] not in PHASES or value["frame_status"] not in FRAME_STATUSES:
        raise ValueError("Invalid kind/phase/frame status")
    for key in ("source_id", "session_id", "frame_id"):
        text(value[key], key)
    domains = value["clock_domains"]
    if not isinstance(domains, dict) or not domains:
        raise ValueError("Declare clock domains")
    for key, domain in domains.items():
        text(key, "clock_id")
        fields(domain, ("kind", "epoch_id"))
        if domain["kind"] not in ("MONOTONIC", "SOURCE_MONOTONIC"):
            raise ValueError("Durations require monotonic domains")
        text(domain["epoch_id"], "epoch_id")
    if not isinstance(value["clock_sync"], list):
        raise ValueError("clock_sync must be a list")
    for sync in value["clock_sync"]:
        fields(sync, ("sync_id", "from_clock", "to_clock", "offset_ns", "uncertainty_ns",
                      "valid_from_ns", "valid_to_ns", "method"))
        for key in ("sync_id", "method"):
            text(sync[key], key)
        if sync["from_clock"] not in domains or sync["to_clock"] not in domains or sync["from_clock"] == sync["to_clock"]:
            raise ValueError("Invalid clock mapping")
        integer(sync["offset_ns"], "offset_ns", -MAX_NS)
        integer(sync["uncertainty_ns"], "sync uncertainty")
        integer(sync["valid_from_ns"], "valid_from_ns")
        integer(sync["valid_to_ns"], "valid_to_ns")
        if sync["valid_to_ns"] < sync["valid_from_ns"]:
            raise ValueError("Invalid calibration validity interval")
    stamps = value["timestamps"]
    if not isinstance(stamps, dict) or set(stamps) - set(FRAME_STAGES):
        raise ValueError("Invalid frame timestamp stage")
    for key, stamp in stamps.items():
        validate_stamp(stamp, domains, capture=key == "t_capture")
    modes = value["execution_modes"]
    if not isinstance(modes, dict) or set(modes) - {"stream1", "stream2", "inference"} or any(m not in EXECUTION_MODES for m in modes.values()):
        raise ValueError("Invalid execution mode")
    if type(value["prediction_ready_confirmed"]) is not bool:
        raise ValueError("Readiness must be explicit")
    gpu = value.get("gpu_intervals", {})
    if not isinstance(gpu, dict) or set(gpu) - {"stream1", "stream2", "inference"}:
        raise ValueError("Invalid GPU interval")
    for interval in gpu.values():
        fields(interval, ("status", "duration_ms", "method", "synchronized"))
        if type(interval["synchronized"]) is not bool or interval["status"] not in ("MEASURED", "NOT_AVAILABLE"):
            raise ValueError("Invalid GPU measurement")
        if interval["status"] == "MEASURED":
            n = interval["duration_ms"]
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0 or interval["method"] != "CUDA_EVENT":
                raise ValueError("Invalid CUDA event duration")
        elif interval["duration_ms"] is not None or interval["method"] is not None or interval["synchronized"]:
            raise ValueError("Unavailable GPU timing must have null duration/method and synchronized=false")
    if not isinstance(value["alerts"], list):
        raise ValueError("alerts must be a list")
    keys = set()
    for alert in value["alerts"]:
        fields(alert, ("event_key", "new_event", "timestamps", "acknowledgements"))
        text(alert["event_key"], "event_key")
        if alert["event_key"] in keys or type(alert["new_event"]) is not bool:
            raise ValueError("Duplicate event or invalid new_event")
        keys.add(alert["event_key"])
        if value["frame_status"] != "PROCESSED":
            raise ValueError("Invalid input frame cannot create alert evidence")
        if not isinstance(alert["timestamps"], dict) or set(alert["timestamps"]) - set(ALERT_STAGES):
            raise ValueError("Invalid alert timestamp")
        for stamp in alert["timestamps"].values():
            validate_stamp(stamp, domains)
        acks = alert["acknowledgements"]
        if not isinstance(acks, dict) or set(acks) - {"t_alert_delivered", "t_alert_visible"}:
            raise ValueError("Invalid acknowledgement")
        for name, kind in (("t_alert_delivered", "DELIVERY_ACK"), ("t_alert_visible", "DISPLAY_RENDER_ACK")):
            stamp = alert["timestamps"].get(name, unknown())
            if stamp["status"] in ("MEASURED", "ESTIMATED"):
                ack = acks.get(name)
                fields(ack, ("kind", "signal_id", "observer", "event_key"))
                if ack["kind"] != kind or ack["event_key"] != alert["event_key"]:
                    raise ValueError("Acknowledgement does not bind to this event")
                text(ack["signal_id"], "signal_id")
                text(ack["observer"], "observer")
    if "ground_truth" in value:
        gt = value["ground_truth"]
        fields(gt, ("label", "episode_id", "episode_complete", "matched_event_keys", "verification"))
        if gt["label"] not in ("TOUCH", "NEAR_NO_TOUCH", "NO_TOUCH", "UNKNOWN") or type(gt["episode_complete"]) is not bool:
            raise ValueError("Invalid ground truth label")
        if gt["episode_id"] is not None:
            text(gt["episode_id"], "ground truth episode")
        if gt["verification"] is not None:
            text(gt["verification"], "ground truth verification")
        if gt["label"] != "UNKNOWN" and gt["verification"] is None:
            raise ValueError("Known ground truth requires verification")
        if gt["episode_complete"] and (gt["label"] != "TOUCH" or gt["episode_id"] is None):
            raise ValueError("Only identified TOUCH episodes may be marked complete")
        if not isinstance(gt["matched_event_keys"], list):
            raise ValueError("Invalid ground truth matches")
        for key in gt["matched_event_keys"]:
            text(key, "matched event key")
    if "issues" in value and (not isinstance(value["issues"], list) or any(not isinstance(x, str) for x in value["issues"])):
        raise ValueError("Invalid issues")
    if "worker_state" in value and not isinstance(value["worker_state"], str):
        raise ValueError("Invalid worker_state")
    return copy.deepcopy(value)

def duration(start, end, record):
    """Only same-domain subtraction or a single explicit, in-range offset map."""
    unavailable = lambda reason: dict(status="NOT_AVAILABLE", value_ms=None, uncertainty_ms=None, reason=reason)
    if start is None or end is None:
        return unavailable("missing_stage")
    if start["status"] not in ("MEASURED", "ESTIMATED") or end["status"] not in ("MEASURED", "ESTIMATED"):
        return unavailable("timestamp_unknown_or_not_available")
    left, right = start["value_ns"], end["value_ns"]
    uncertainty = start["uncertainty_ns"] + end["uncertainty_ns"]
    estimated = start["status"] == "ESTIMATED" or end["status"] == "ESTIMATED"
    if start["clock_id"] != end["clock_id"]:
        candidates = []
        for sync in record["clock_sync"]:
            if sync["from_clock"] == start["clock_id"] and sync["to_clock"] == end["clock_id"]:
                translated_end = right - sync["offset_ns"]
                if sync["valid_from_ns"] <= left <= sync["valid_to_ns"] and sync["valid_from_ns"] <= translated_end <= sync["valid_to_ns"]:
                    candidates.append((left + sync["offset_ns"], right, sync["uncertainty_ns"]))
            elif sync["from_clock"] == end["clock_id"] and sync["to_clock"] == start["clock_id"]:
                translated_start = left - sync["offset_ns"]
                if sync["valid_from_ns"] <= right <= sync["valid_to_ns"] and sync["valid_from_ns"] <= translated_start <= sync["valid_to_ns"]:
                    candidates.append((left, right + sync["offset_ns"], sync["uncertainty_ns"]))
        if len(candidates) != 1:
            return unavailable("unsynchronized_or_ambiguous_clocks")
        left, right, extra = candidates[0]
        uncertainty += extra
        estimated = True
    if right < left:
        return unavailable("negative_duration")
    return dict(status="ESTIMATED" if estimated else "MEASURED", value_ms=(right-left)/1000000.0,
                uncertainty_ms=uncertainty/1000000.0, reason=None)
