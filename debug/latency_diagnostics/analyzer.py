"""Clock-safe offline analysis. No product, camera, CUDA or database imports."""
import json
import math
from collections import Counter, defaultdict

try:
    from . import schema
except ImportError:
    import schema

MAX_LINE_BYTES = 1024 * 1024

def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result

def _constant(value):
    raise ValueError("nonfinite JSON number")

def _integer(value):
    if len(value) > 128:
        raise ValueError("JSON integer too long")
    return int(value)

def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result

def parse_jsonl(lines):
    """Return schema-valid records and per-line errors; never access payload paths."""
    records, errors = [], []
    for number, raw in enumerate(lines, 1):
        try:
            if not isinstance(raw, (str, bytes)):
                raise ValueError("JSONL line must be text or bytes")
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError("line exceeds 1 MiB limit")
            line = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ValueError("line exceeds 1 MiB limit")
            if not line.strip():
                continue
            value = json.loads(line, object_pairs_hook=_object,
                               parse_constant=_constant, parse_int=_integer,
                               parse_float=_float)
            records.append(schema.validate_record(value))
        except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError) as exc:
            errors.append(dict(line=number, error=str(exc)[:512]))
    return records, errors

def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)

def _group_key(record):
    return tuple(record[k] for k in ("data_kind", "phase", "source_id", "session_id"))

def _scope(record):
    return tuple(record[k] for k in ("data_kind", "source_id", "session_id"))

def _known(stamp):
    return stamp is not None and stamp["status"] in ("MEASURED", "ESTIMATED")

def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered)-1) * percentile
    low, high = int(math.floor(index)), int(math.ceil(index))
    return ordered[low] + (ordered[high]-ordered[low]) * (index-low)

def _summary(samples):
    values = [v for v, _ in samples]
    uncertainties = [u for _, u in samples if u is not None]
    return dict(n=len(values), p50_ms=_percentile(values, 0.5),
                p95_ms=_percentile(values, 0.95), p99_ms=_percentile(values, 0.99),
                min_ms=min(values) if values else None,
                max_ms=max(values) if values else None,
                uncertainty_ms_max=max(uncertainties) if uncertainties else None)

class _Metric:
    def __init__(self):
        self.samples = dict(MEASURED=[], ESTIMATED=[])
        self.unavailable = Counter()

    def add(self, value):
        status = value["status"]
        if status in self.samples:
            self.samples[status].append((value["value_ms"], value["uncertainty_ms"]))
        else:
            self.unavailable[value["reason"]] += 1

    def reject(self, reason):
        self.unavailable[reason] += 1

    def output(self):
        result = {kind: _summary(samples) for kind, samples in self.samples.items()}
        result["unavailable"] = dict(sorted(self.unavailable.items()))
        return result

PAIRS = {
    "request_to_receive": ("t_request_start", "t_receive_complete"),
    "capture_to_receive": ("t_capture", "t_receive_complete"),
    "receive_to_decode": ("t_receive_complete", "t_decode_end"),
    "file_publish_to_worker_read": ("t_file_publish", "t_worker_read_start"),
    "worker_read": ("t_worker_read_start", "t_worker_read_end"),
    "decode": ("t_decode_start", "t_decode_end"),
    "tracking": ("t_prediction_ready", "t_tracking_end"),
    "temporal": ("t_tracking_end", "t_temporal_end"),
    "tracking_temporal": ("t_prediction_ready", "t_temporal_end"),
    "frame_age_at_decision_all_frames": ("t_capture", "t_decision_end"),
}
STREAM_PAIRS = {
    "stream2": ("t_stream2_start", "t_stream2_end"),
    "stream1": ("t_stream1_start", "t_stream1_end"),
    "inference": ("t_inference_start", "t_prediction_ready"),
}
ALERT_PAIRS = {
    "decision_to_commit": ("t_alert_decision", "t_event_committed"),
    "commit_to_delivered": ("t_event_committed", "t_alert_delivered"),
    "commit_to_visible": ("t_event_committed", "t_alert_visible"),
    "decision_to_evidence": ("t_alert_decision", "t_evidence_ready"),
}
METRIC_NAMES = (list(PAIRS) + ["stream2_wall", "stream1_wall", "inference_total_wall",
    "stream2_enqueue_wall", "stream1_enqueue_wall", "inference_enqueue_wall",
    "stream2_gpu_execution", "stream1_gpu_execution", "inference_gpu_execution"] +
    list(ALERT_PAIRS) + ["frame_age_at_decision"])

class _Group:
    def __init__(self, key):
        self.key = key
        self.counts = Counter(input_records=0, accepted_records=0, alerts=0,
                              duplicate_records=0, conflicting_duplicates=0,
                              clock_conflict_records=0, chronology_rejected_records=0)
        self.statuses = Counter()
        self.metrics = {name: _Metric() for name in METRIC_NAMES}
        self.cadence = {"receive": defaultdict(list), "prediction": defaultdict(list)}
        self.records = []
        self.gt_records = []
        self.cross_phase_episodes = set()
        self.event_keys = set()

    def output(self):
        result = dict(zip(("data_kind", "phase", "source_id", "session_id"), self.key))
        result["counts"] = dict(self.counts)
        result["counts"]["frame_status"] = dict(sorted(self.statuses.items()))
        result["metrics"] = {name: value.output() for name, value in sorted(self.metrics.items())}
        result["cadence"] = {}
        for name, clocks in self.cadence.items():
            series = []
            for clock_id, observations in sorted(clocks.items()):
                metric = _Metric()
                for previous, current, record in zip(observations, observations[1:],
                                                      [x[1] for x in observations[1:]]):
                    metric.add(schema.duration(previous[0], current[0], record))
                stamps = [item[0] for item in observations]
                span = schema.duration(stamps[0], stamps[-1], observations[-1][1]) if len(stamps) > 1 else None
                fps = ((len(stamps)-1)*1000.0/span["value_ms"]
                       if span and span["status"] in ("MEASURED", "ESTIMATED") and span["value_ms"] > 0 else None)
                series.append(dict(clock_id=clock_id, n=len(stamps), fps=fps,
                                   fps_status=span["status"] if fps is not None else "NOT_AVAILABLE",
                                   span_ms=span["value_ms"] if fps is not None else None,
                                   span_uncertainty_ms=span["uncertainty_ms"] if fps is not None else None,
                                   intervals=metric.output()))
            result["cadence"][name] = dict(series=series)
        result["ground_truth"] = _ground_truth(
            self.gt_records, self.event_keys, self.cross_phase_episodes,
            self.counts["conflicting_duplicates"] + self.counts["clock_conflict_records"]
            + self.counts["chronology_rejected_records"])
        return result

def _ground_truth(records, observed_events, cross_phase_episodes=(), excluded_records=0):
    annotated = [r["ground_truth"] for r in records if "ground_truth" in r]
    if not annotated:
        return dict(status="NOT_AVAILABLE", annotated_frames=0, unknown_frames=None,
                    missed_events=None, missed_complete_episodes=None,
                    complete_touch_episodes=0, incomplete_touch_episodes=0,
                    unobserved_matched_event_keys=[], cross_phase_episodes=[],
                    excluded_observation_records=excluded_records, verification="NO_GROUND_TRUTH")
    unknown = sum(gt["label"] == "UNKNOWN" for gt in annotated)
    episodes = {}
    unidentified = 0
    all_reviewed_matches = set()
    for gt in annotated:
        all_reviewed_matches.update(gt["matched_event_keys"])
        if gt["label"] != "TOUCH":
            continue
        if gt["episode_id"] is None:
            unidentified += 1
            continue
        episode = episodes.setdefault(gt["episode_id"], dict(complete=False, matches=set()))
        episode["complete"] = episode["complete"] or (
            gt["episode_complete"] and gt["episode_id"] not in cross_phase_episodes)
        episode["matches"].update(gt["matched_event_keys"])
    complete = [e for e in episodes.values() if e["complete"]]
    incomplete = sum(not e["complete"] for e in episodes.values()) + unidentified
    missed = sum(not (e["matches"] & observed_events) for e in complete)
    full = (len(annotated) == len(records) and unknown == 0 and incomplete == 0
            and excluded_records == 0)
    return dict(status="COMPLETE" if full else "PARTIAL",
                annotated_frames=len(annotated), unknown_frames=unknown,
                complete_touch_episodes=len(complete), incomplete_touch_episodes=incomplete,
                missed_complete_episodes=missed,
                missed_events=missed if full else None,
                observed_matched_events=len(all_reviewed_matches & observed_events),
                unobserved_matched_event_keys=sorted(all_reviewed_matches-observed_events),
                cross_phase_episodes=sorted(cross_phase_episodes),
                excluded_observation_records=excluded_records,
                verification="EXPLICIT_REVIEWER_MATCHES_NOT_MODEL_GROUND_TRUTH")

def _add_frame_metrics(group, record):
    stamps = record["timestamps"]
    for name, (left, right) in PAIRS.items():
        if name in ("tracking", "tracking_temporal") and not record["prediction_ready_confirmed"]:
            group.metrics[name].reject("prediction_not_confirmed_ready")
        else:
            group.metrics[name].add(schema.duration(stamps.get(left), stamps.get(right), record))
    for stream, (left, right) in STREAM_PAIRS.items():
        wall = "inference_total_wall" if stream == "inference" else stream + "_wall"
        mode = record["execution_modes"].get(stream, "UNKNOWN")
        ready = stream != "inference" or record["prediction_ready_confirmed"]
        if not ready:
            group.metrics[wall].reject("prediction_not_confirmed_ready")
        elif mode in ("CPU_ONLY", "CUDA_SYNCHRONIZED_WALL"):
            group.metrics[wall].add(schema.duration(stamps.get(left), stamps.get(right), record))
        else:
            group.metrics[wall].reject("cuda_enqueue_only" if mode == "CUDA_ENQUEUE_ONLY" else "execution_mode_unknown")
        enqueue = group.metrics[stream + "_enqueue_wall"]
        if mode == "CUDA_ENQUEUE_ONLY":
            enqueue.add(schema.duration(stamps.get(left), stamps.get(right), record))
        else:
            enqueue.reject("not_enqueue_only")
        gpu = group.metrics[stream + "_gpu_execution"]
        interval = record.get("gpu_intervals", {}).get(stream)
        if interval and interval["status"] == "MEASURED" and interval["synchronized"] and interval["method"] == "CUDA_EVENT":
            gpu.add(dict(status="MEASURED", value_ms=interval["duration_ms"], uncertainty_ms=0, reason=None))
        else:
            gpu.reject("synchronized_cuda_event_not_available")
    for name, stage in (("receive", "t_receive_complete"), ("prediction", "t_prediction_ready")):
        stamp = stamps.get(stage)
        if _known(stamp) and (name != "prediction" or record["prediction_ready_confirmed"]):
            group.cadence[name][stamp["clock_id"]].append((stamp, record))

def _merge_event(observations):
    """Keep only nonconflicting timestamps; preserve source clock declarations."""
    timestamps = {}
    conflicts = set()
    for alert, _ in observations:
        for stage, stamp in alert["timestamps"].items():
            if not _known(stamp):
                continue
            if stage in timestamps and timestamps[stage] != stamp:
                conflicts.add(stage)
            else:
                timestamps[stage] = stamp
    for stage in conflicts:
        timestamps.pop(stage, None)
    owner = next(((alert, record) for alert, record in observations if alert["new_event"]), None)
    return owner, timestamps, conflicts

def mark_incomplete_input(report, reason):
    """Retain valid timing samples, but never claim complete GT after lost rows.

    Invalid rows may lack source/session identity, so attribution to one group
    would be speculation. No synthetic UNKNOWN annotation is added.
    """
    reasons = report.setdefault("incomplete_input_reasons", [])
    if reason not in reasons:
        reasons.append(reason)
    for group in report["groups"]:
        gt = group["ground_truth"]
        gt_reasons = gt.setdefault("incomplete_input_reasons", [])
        if reason not in gt_reasons:
            gt_reasons.append(reason)
        if gt["status"] != "NOT_AVAILABLE":
            gt["status"] = "PARTIAL"
            gt["missed_events"] = None
    return report

def analyze_records(records):
    """Analyze validated copies. Invalid, conflicting and out-of-order data add no evidence."""
    valid, errors = [], []
    counts = Counter(input_records=0, valid_records=0, invalid_records=0,
                     duplicate_records=0, conflicting_duplicates=0,
                     clock_conflict_records=0, chronology_rejected_records=0)
    groups = {}
    for index, record in enumerate(records, 1):
        counts["input_records"] += 1
        try:
            value = schema.validate_record(record)
            _canonical(value)
            valid.append(value)
            counts["valid_records"] += 1
            key = _group_key(value)
            group = groups.setdefault(key, _Group(key))
            group.counts["input_records"] += 1
            group.statuses[value["frame_status"]] += 1
        except (ValueError, TypeError, RecursionError, OverflowError) as exc:
            counts["invalid_records"] += 1
            errors.append(dict(record=index, error=str(exc)[:512]))
    # The same source frame cannot contribute twice, even under a different phase.
    frame_buckets = defaultdict(list)
    descriptors, sync_descriptors = defaultdict(set), defaultdict(set)
    for record in valid:
        scope = _scope(record)
        frame_buckets[scope + (record["frame_id"],)].append(record)
        for clock, descriptor in record["clock_domains"].items():
            descriptors[scope + (clock,)].add(_canonical(descriptor))
        for sync in record["clock_sync"]:
            sync_descriptors[scope + (sync["sync_id"],)].add(_canonical(sync))
    conflicts = {key for key, values in descriptors.items() if len(values) > 1}
    sync_conflicts = {key for key, values in sync_descriptors.items() if len(values) > 1}
    excluded = set()
    for bucket in frame_buckets.values():
        variants = {_canonical(record) for record in bucket}
        if len(variants) > 1:
            for record in bucket:
                excluded.add(id(record))
                counts["conflicting_duplicates"] += 1
                groups[_group_key(record)].counts["conflicting_duplicates"] += 1
        else:
            for record in bucket[1:]:
                excluded.add(id(record))
                counts["duplicate_records"] += 1
                groups[_group_key(record)].counts["duplicate_records"] += 1
    accepted = []
    last = {}
    for record in valid:
        if id(record) in excluded:
            continue
        group = groups[_group_key(record)]
        scope = _scope(record)
        if any(scope + (clock,) in conflicts for clock in record["clock_domains"]) or any(
                scope + (sync["sync_id"],) in sync_conflicts for sync in record["clock_sync"]):
            counts["clock_conflict_records"] += 1
            group.counts["clock_conflict_records"] += 1
            continue
        # Ground truth describes what happened even when the pipeline rejected
        # a frame; it must never become positive prediction evidence.
        group.gt_records.append(record)
        if record["frame_status"] != "PROCESSED":
            continue
        pending = {}
        bad = False
        for name in ("t_capture", "t_receive_complete", "t_prediction_ready"):
            if name == "t_prediction_ready" and not record["prediction_ready_confirmed"]:
                continue
            stamp = record["timestamps"].get(name)
            if _known(stamp):
                key = scope + (name, stamp["clock_id"])
                if key in last and stamp["value_ns"] <= last[key]:
                    bad = True
                pending[key] = stamp["value_ns"]
        if bad:
            counts["chronology_rejected_records"] += 1
            group.counts["chronology_rejected_records"] += 1
            continue
        last.update(pending)
        accepted.append(record)
        group.counts["accepted_records"] += 1
        group.records.append(record)
        _add_frame_metrics(group, record)
    # Merge event lifecycle observations without treating repeated active state as a new alert.
    # A complete session episode split across cold/warm groups is not a complete
    # episode inside either timing group. Keep those evaluation slices partial.
    episode_groups = defaultdict(set)
    for group in groups.values():
        for record in group.gt_records:
            gt = record.get("ground_truth")
            if gt and gt["label"] == "TOUCH" and gt["episode_id"] is not None:
                episode_groups[_scope(record) + (gt["episode_id"],)].add(group.key)
    for group in groups.values():
        for record in group.gt_records:
            gt = record.get("ground_truth")
            if gt and gt["label"] == "TOUCH" and gt["episode_id"] is not None:
                if len(episode_groups[_scope(record) + (gt["episode_id"],)]) > 1:
                    group.cross_phase_episodes.add(gt["episode_id"])
    events = defaultdict(list)
    contexts = {}
    for record in accepted:
        scope = _scope(record)
        context = contexts.setdefault(scope, dict(clock_domains={}, clock_sync=[]))
        context["clock_domains"].update(record["clock_domains"])
        seen_sync = {_canonical(sync) for sync in context["clock_sync"]}
        for sync in record["clock_sync"]:
            if _canonical(sync) not in seen_sync:
                context["clock_sync"].append(sync)
                seen_sync.add(_canonical(sync))
        for alert in record["alerts"]:
            events[scope + (alert["event_key"],)].append((alert, record))
    for event_key, observations in events.items():
        owner, stamps, bad_stages = _merge_event(observations)
        if owner is None:
            continue
        alert, record = owner
        group = groups[_group_key(record)]
        group.counts["alerts"] += 1
        group.event_keys.add(alert["event_key"])
        context = contexts[_scope(record)]
        for name, (left, right) in ALERT_PAIRS.items():
            if left in bad_stages or right in bad_stages:
                group.metrics[name].reject("conflicting_event_timestamp")
            else:
                group.metrics[name].add(schema.duration(stamps.get(left), stamps.get(right), context))
        age = group.metrics["frame_age_at_decision"]
        if "t_alert_decision" in bad_stages:
            age.reject("conflicting_event_timestamp")
        else:
            age.add(schema.duration(record["timestamps"].get("t_capture"), stamps.get("t_alert_decision"), context))
    counts["accepted_records"] = len(accepted)
    counts["alerts"] = sum(group.counts["alerts"] for group in groups.values())
    report = dict(schema_version=1, counts=dict(counts),
                groups=[groups[key].output() for key in sorted(groups)],
                errors=errors,
                interpretation="OFFLINE_TIMING_ONLY_NOT_AI_ACCURACY; measured/estimated and synthetic/real remain separate",
                calibration_caveat="clock_sync is trusted external calibration evidence; this analyzer cannot verify calibration accuracy",
                percentile_caveat="Tail percentiles require representative independent samples; small unit-test counts do not establish p95/p99 performance",
                counts_scope="INPUT_INVENTORY_ONLY; sums may include synthetic/real and cold/warm; use separate groups, never treat these totals as AI accuracy")
    if counts["invalid_records"]:
        mark_incomplete_input(report, "invalid_input_records")
    return report
