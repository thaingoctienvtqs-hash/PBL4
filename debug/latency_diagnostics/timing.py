"""Dependency-injected call timing; never imports Torch or opens hardware."""
from .schema import ALERT_STAGES, FRAME_STAGES, unknown

def _issue(trace, message):
    try:
        trace.record["issues"].append("instrumentation: " + message)
    except Exception:
        pass

def _probe(trace, operation):
    try:
        operation()
        return True
    except Exception as exc:
        _issue(trace, "probe_failed: " + type(exc).__name__)
        return False

def _unavailable(trace, stage, event_key=None):
    # A failed probe must not leave an old timestamp looking newly measured.
    try:
        if stage in FRAME_STAGES:
            trace.record["timestamps"][stage] = unknown(reason="instrumentation_probe_failed")
            if stage == "t_prediction_ready":
                trace.record["prediction_ready_confirmed"] = False
        elif stage in ALERT_STAGES:
            trace._alert(event_key)["timestamps"][stage] = unknown(reason="instrumentation_probe_failed")
    except Exception:
        pass

def observe_call(fn, trace, start_stage, end_stage, args=(), kwargs=None,
                 execution_stage=None, execution_mode="UNKNOWN", synchronize=None,
                 prediction_ready_confirmed=False, event_key=None, end_predicate=None):
    """Forward identical arguments/result/exception. Measurements are best effort.

    CUDA_SYNCHRONIZED_WALL includes CPU and final GPU wait, not pure kernel time.
    Supply sync callbacks only in a separately approved run. Event lifecycle end
    milestones require an explicit success predicate; a normal return alone is
    not proof that an event was committed. Delivery/visibility still require ACK.
    """
    sync_ok = True
    if execution_stage is not None:
        valid_mode = _probe(trace, lambda: trace.set_execution_mode(execution_stage, execution_mode))
        if not valid_mode:
            _probe(trace, lambda: trace.set_execution_mode(execution_stage, "UNKNOWN"))
    if execution_mode == "CUDA_SYNCHRONIZED_WALL":
        if not callable(synchronize):
            sync_ok = False
            _issue(trace, "CUDA synchronization callback missing")
        else:
            sync_ok = _probe(trace, synchronize)
    if not sync_ok and execution_stage is not None:
        _probe(trace, lambda: trace.set_execution_mode(execution_stage, "UNKNOWN"))

    def stamp(stage):
        if stage is None:
            return
        if stage == "t_prediction_ready":
            trace.prediction_ready(confirmed=prediction_ready_confirmed)
        elif stage in ALERT_STAGES:
            trace.mark_alert(event_key, stage)
        else:
            trace.mark(stage)

    def safe_stamp(stage):
        if not _probe(trace, lambda: stamp(stage)):
            _unavailable(trace, stage, event_key)

    safe_stamp(start_stage)
    try:
        result = fn(*args, **({} if kwargs is None else kwargs))
    except BaseException:
        _issue(trace, "observed_callable_failed; end milestone unavailable")
        _unavailable(trace, end_stage, event_key)
        raise
    if execution_mode == "CUDA_SYNCHRONIZED_WALL" and sync_ok:
        sync_ok = _probe(trace, synchronize)
        if not sync_ok and execution_stage is not None:
            _probe(trace, lambda: trace.set_execution_mode(execution_stage, "UNKNOWN"))
    accepted = True
    if end_stage in ALERT_STAGES and not callable(end_predicate):
        accepted = False
        _issue(trace, "event milestone requires explicit success predicate")
    elif end_predicate is not None:
        checked = []
        def check():
            checked.append(bool(end_predicate(result)))
        if not _probe(trace, check):
            accepted = False
        else:
            accepted = checked[0]
    if not accepted:
        _unavailable(trace, end_stage, event_key)
    elif end_stage == "t_prediction_ready" and execution_mode == "CUDA_SYNCHRONIZED_WALL" and not sync_ok:
        _probe(trace, lambda: trace.prediction_ready(confirmed=False))
    else:
        safe_stamp(end_stage)
    return result
