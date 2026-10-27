"""Adversarial schema tests. All fixtures are SYNTHETIC_TEST; no hardware."""
import copy
import unittest

from debug.latency_diagnostics import schema


def stamp(ms, clock="host", **kwargs):
    return schema.measured(int(ms * 1000000), clock, **kwargs)


def frame(frame_id="f1", at_ms=1000, phase="WARM"):
    """Prediction-free fixture: these timestamps are invented test data only."""
    return {
        "schema_version": 1, "record_type": "FRAME", "data_kind": "SYNTHETIC_TEST",
        "source_id": "synthetic-source", "session_id": "synthetic-session",
        "frame_id": frame_id, "phase": phase, "frame_status": "PROCESSED",
        "clock_domains": {"host": {"kind": "MONOTONIC", "epoch_id": "synthetic-process"}},
        "clock_sync": [], "timestamps": {"t_capture": schema.unknown("UNKNOWN", "not_provided"),
                                        "t_receive_complete": stamp(at_ms)},
        "execution_modes": {"stream1": "CPU_ONLY", "stream2": "CPU_ONLY", "inference": "CPU_ONLY"},
        "prediction_ready_confirmed": False, "alerts": [],
    }


def alert(event_key="event1", decision=1200):
    return {"event_key": event_key, "new_event": True,
            "timestamps": {"t_alert_decision": stamp(decision)},
            "acknowledgements": {}}


def sync_map(**overrides):
    value = {"sync_id": "synthetic-sync", "from_clock": "camera", "to_clock": "host",
             "offset_ns": 1000000000, "uncertainty_ns": 2000000,
             "valid_from_ns": 0, "valid_to_ns": 10000000000, "method": "SYNTHETIC_TEST"}
    value.update(overrides)
    return value


def with_camera(value=None):
    value = frame() if value is None else value
    value["clock_domains"]["camera"] = {"kind": "SOURCE_MONOTONIC", "epoch_id": "synthetic-camera"}
    return value


class SchemaTests(unittest.TestCase):
    def test_empty_scene_without_predictions_or_ground_truth_is_valid(self):
        self.assertEqual(schema.validate_record(frame())["alerts"], [])

    def test_validation_returns_deep_copy(self):
        original = frame()
        result = schema.validate_record(original)
        result["timestamps"]["t_receive_complete"]["value_ns"] = 0
        self.assertNotEqual(original, result)

    def test_all_unavailable_stages_are_valid_without_metrics(self):
        value = frame()
        value["timestamps"] = {name: schema.unknown() for name in schema.FRAME_STAGES}
        self.assertEqual(schema.validate_record(value)["timestamps"]["t_decode_end"]["status"], "NOT_AVAILABLE")

    def test_missing_and_unknown_top_level_fields_rejected(self):
        for remove, add in (("phase", None), (None, "invented")):
            value = frame()
            if remove:
                del value[remove]
            if add:
                value[add] = True
            with self.subTest(remove=remove, add=add), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_boolean_schema_version_not_integer_version(self):
        value = frame()
        value["schema_version"] = True
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_invalid_enums_rejected(self):
        for key in ("data_kind", "phase", "frame_status"):
            value = frame()
            value[key] = "INVENTED"
            with self.subTest(key=key), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_invalid_identity_rejected(self):
        for identity in ("", "line\nfeed", "x" * 257, 3):
            value = frame()
            value["frame_id"] = identity
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_capture_cannot_be_file_mtime_or_file_stat(self):
        for method in ("mtime", "FILE_STAT", "estimated_file_mtime"):
            value = frame()
            value["timestamps"]["t_capture"] = stamp(1, method=method)
            with self.subTest(method=method), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_unknown_capture_has_no_numeric_fallback(self):
        value = frame()
        value["timestamps"]["t_capture"]["value_ns"] = 123
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_unknown_stamp_requires_reason(self):
        value = schema.unknown()
        value["reason"] = None
        with self.assertRaises(ValueError):
            schema.validate_stamp(value)

    def test_invalid_stamp_integer_rejected(self):
        for number in (True, -1, 1.5, schema.MAX_NS + 1):
            with self.subTest(number=number), self.assertRaises(ValueError):
                schema.measured(number, "host")

    def test_unknown_clock_rejected(self):
        value = frame()
        value["timestamps"]["t_capture"] = stamp(1, "undeclared")
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_wallclock_domain_not_accepted_as_monotonic(self):
        value = frame()
        value["clock_domains"]["host"]["kind"] = "UTC"
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_sync_negative_offset_is_valid(self):
        value = with_camera()
        value["clock_sync"] = [sync_map(offset_ns=-100)]
        schema.validate_record(value)

    def test_sync_invalid_validity_rejected(self):
        value = with_camera()
        value["clock_sync"] = [sync_map(valid_from_ns=10, valid_to_ns=9)]
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_execution_mode_unknown_value_rejected(self):
        value = frame()
        value["execution_modes"]["stream1"] = "CUDA_PROBABLY_READY"
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_prediction_readiness_must_be_boolean(self):
        value = frame()
        value["prediction_ready_confirmed"] = 1
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_cuda_interval_unsynchronized_is_explicit_not_assumed_ready(self):
        value = frame()
        value["gpu_intervals"] = {"stream1": {"status": "MEASURED", "duration_ms": 3.0,
                                             "method": "CUDA_EVENT", "synchronized": False}}
        self.assertFalse(schema.validate_record(value)["gpu_intervals"]["stream1"]["synchronized"])

    def test_invalid_gpu_duration_rejected(self):
        for duration in (-1, True, float("nan"), float("inf")):
            value = frame()
            value["gpu_intervals"] = {"stream1": {"status": "MEASURED", "duration_ms": duration,
                                                 "method": "CUDA_EVENT", "synchronized": True}}
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_decision_does_not_require_delivery_ack(self):
        value = frame()
        value["alerts"] = [alert()]
        schema.validate_record(value)

    def test_delivery_and_visible_stages_require_matching_acknowledgement(self):
        for stage in ("t_alert_delivered", "t_alert_visible"):
            value = frame()
            value["alerts"] = [alert()]
            value["alerts"][0]["timestamps"][stage] = stamp(1300)
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_visible_ack_is_not_delivery_ack(self):
        value = frame()
        a = alert()
        a["timestamps"]["t_alert_visible"] = stamp(1300)
        a["acknowledgements"]["t_alert_visible"] = {"kind": "DELIVERY_ACK", "signal_id": "ack1",
                                                  "observer": "synthetic-client", "event_key": "event1"}
        value["alerts"] = [a]
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_ack_for_another_event_rejected(self):
        value = frame()
        a = alert()
        a["timestamps"]["t_alert_delivered"] = stamp(1300)
        a["acknowledgements"]["t_alert_delivered"] = {"kind": "DELIVERY_ACK", "signal_id": "ack1",
                                                    "observer": "synthetic-client", "event_key": "another"}
        value["alerts"] = [a]
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_matching_delivery_and_display_acknowledgements_accepted(self):
        value = frame()
        a = alert()
        for stage, kind in (("t_alert_visible", "DISPLAY_RENDER_ACK"), ("t_alert_delivered", "DELIVERY_ACK")):
            a["timestamps"][stage] = stamp(1400)
            a["acknowledgements"][stage] = {"kind": kind, "signal_id": "synthetic-" + stage,
                                           "observer": "synthetic-client", "event_key": "event1"}
        value["alerts"] = [a]
        schema.validate_record(value)

    def test_invalid_frame_status_cannot_include_alert(self):
        for status in schema.FRAME_STATUSES:
            if status == "PROCESSED":
                continue
            value = frame()
            value["frame_status"], value["alerts"] = status, [alert()]
            with self.subTest(status=status), self.assertRaises(ValueError):
                schema.validate_record(value)

    def test_duplicate_alert_keys_in_one_frame_rejected(self):
        value = frame()
        value["alerts"] = [alert(), alert()]
        with self.assertRaises(ValueError):
            schema.validate_record(value)

    def test_unknown_ground_truth_is_not_no_touch(self):
        value = frame()
        value["ground_truth"] = {"label": "UNKNOWN", "episode_id": None, "episode_complete": False,
                                 "matched_event_keys": [], "verification": None}
        self.assertEqual(schema.validate_record(value)["ground_truth"]["label"], "UNKNOWN")

    def test_complete_touch_episode_requires_id_and_verification(self):
        value = frame()
        value["ground_truth"] = {"label": "TOUCH", "episode_id": "episode1", "episode_complete": True,
                                 "matched_event_keys": [], "verification": "SYNTHETIC_TEST"}
        schema.validate_record(value)
        for field in ("episode_id", "verification"):
            invalid = copy.deepcopy(value)
            invalid["ground_truth"][field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                schema.validate_record(invalid)

    def test_non_touch_or_unknown_cannot_claim_complete_touch_episode(self):
        for label in ("NO_TOUCH", "NEAR_NO_TOUCH", "UNKNOWN"):
            value = frame()
            value["ground_truth"] = {"label": label, "episode_id": "episode1", "episode_complete": True,
                                     "matched_event_keys": [], "verification": "SYNTHETIC_TEST"}
            with self.subTest(label=label), self.assertRaises(ValueError):
                schema.validate_record(value)


class DurationTests(unittest.TestCase):
    def test_same_monotonic_clock_direct_duration(self):
        result = schema.duration(stamp(100), stamp(150), frame())
        self.assertEqual((result["status"], result["value_ms"], result["uncertainty_ms"]), ("MEASURED", 50.0, 0.0))

    def test_estimated_stamp_not_relabelled_measured(self):
        result = schema.duration(stamp(100, status="ESTIMATED", uncertainty_ns=1000000),
                                 stamp(150, uncertainty_ns=2000000), frame())
        self.assertEqual((result["status"], result["uncertainty_ms"]), ("ESTIMATED", 3.0))

    def test_missing_stage_never_becomes_zero_latency(self):
        result = schema.duration(None, stamp(150), frame())
        self.assertEqual(result["status"], "NOT_AVAILABLE")
        self.assertIsNone(result["value_ms"])

    def test_unknown_capture_never_becomes_receive_time(self):
        result = schema.duration(schema.unknown("UNKNOWN", "no_source_clock"), stamp(150), frame())
        self.assertIsNone(result["value_ms"])

    def test_negative_duration_rejected(self):
        result = schema.duration(stamp(150), stamp(100), frame())
        self.assertEqual(result["reason"], "negative_duration")
        self.assertIsNone(result["value_ms"])

    def test_different_clocks_without_sync_not_subtracted(self):
        result = schema.duration(stamp(100, "camera"), stamp(1150), with_camera())
        self.assertEqual(result["reason"], "unsynchronized_or_ambiguous_clocks")
        self.assertIsNone(result["value_ms"])

    def test_valid_clock_mapping_includes_uncertainty(self):
        value = with_camera()
        value["clock_sync"] = [sync_map()]
        result = schema.duration(stamp(100, "camera", uncertainty_ns=1000000),
                                 stamp(1150, uncertainty_ns=3000000), value)
        self.assertEqual((result["status"], result["value_ms"], result["uncertainty_ms"]), ("ESTIMATED", 50.0, 6.0))

    def test_reverse_direction_uses_same_explicit_mapping(self):
        value = with_camera()
        value["clock_sync"] = [sync_map()]
        result = schema.duration(stamp(1100), stamp(150, "camera"), value)
        self.assertEqual((result["status"], result["value_ms"]), ("ESTIMATED", 50.0))

    def test_expired_mapping_not_extrapolated(self):
        value = with_camera()
        value["clock_sync"] = [sync_map(valid_to_ns=100000000)]
        result = schema.duration(stamp(200, "camera"), stamp(1300), value)
        self.assertIsNone(result["value_ms"])

    def test_both_timestamps_must_fit_mapping_validity(self):
        value = with_camera()
        value["clock_sync"] = [sync_map(valid_to_ns=100000000)]
        result = schema.duration(stamp(50, "camera"), stamp(1200), value)
        self.assertIsNone(result["value_ms"])

    def test_overlapping_mappings_are_ambiguous_even_when_offsets_equal(self):
        value = with_camera()
        value["clock_sync"] = [sync_map(), sync_map(sync_id="second")]
        result = schema.duration(stamp(100, "camera"), stamp(1150), value)
        self.assertIsNone(result["value_ms"])


if __name__ == "__main__":
    unittest.main()
