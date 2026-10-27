"""Offline analyzer tests. Test timestamps never represent measured AI latency."""
import copy
import io
import json
import unittest

from debug.latency_diagnostics import schema
from debug.latency_diagnostics.analyzer import analyze_records, parse_jsonl
from debug.latency_diagnostics.tests.test_schema import alert, frame, stamp, sync_map, with_camera


def timed_frame(frame_id="f1", at_ms=1000, phase="WARM"):
    value = frame(frame_id, at_ms, phase)
    for stage, delta in (
            ("t_request_start", -50), ("t_file_publish", 5),
            ("t_worker_read_start", 10), ("t_worker_read_end", 15),
            ("t_decode_start", 15), ("t_decode_end", 20),
            ("t_inference_start", 20), ("t_stream2_start", 20), ("t_stream2_end", 40),
            ("t_stream1_start", 40), ("t_stream1_end", 70),
            ("t_prediction_ready", 75), ("t_tracking_end", 80), ("t_temporal_end", 85)):
        value["timestamps"][stage] = stamp(at_ms + delta)
    value["prediction_ready_confirmed"] = True
    return value


def add_alert(value, key="event1"):
    base = value["timestamps"]["t_receive_complete"]["value_ns"] / 1000000.0
    a = alert(key, base + 90)
    a["timestamps"]["t_event_committed"] = stamp(base + 95)
    a["timestamps"]["t_evidence_ready"] = stamp(base + 100)
    value["alerts"] = [a]
    return value


def truth(label="TOUCH", episode="episode1", complete=False, matches=None):
    return {"label": label, "episode_id": episode, "episode_complete": complete,
            "matched_event_keys": [] if matches is None else matches,
            "verification": None if label == "UNKNOWN" else "SYNTHETIC_TEST"}


def group(records):
    report = analyze_records(records)
    if len(report["groups"]) != 1:
        raise AssertionError("Expected one fixture group, got " + repr(report))
    return report["groups"][0]


def sample_count(result, name, bucket="MEASURED"):
    return result["metrics"][name][bucket]["n"]


class ParseTests(unittest.TestCase):
    def test_stringio_roundtrip_and_blank_lines(self):
        rows, errors = parse_jsonl(io.StringIO("\n" + json.dumps(frame()) + "\n\n"))
        self.assertEqual(errors, [])
        self.assertEqual(rows, [frame()])

    def test_malformed_row_not_hide_later_valid_row(self):
        rows, errors = parse_jsonl(io.StringIO("{broken\n" + json.dumps(frame()) + "\n"))
        self.assertEqual(rows, [frame()])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["line"], 1)

    def test_duplicate_json_keys_rejected(self):
        payload = json.dumps(frame()).replace('"frame_id": "f1"', '"frame_id": "f1", "frame_id": "f2"')
        rows, errors = parse_jsonl(io.StringIO(payload))
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_nonfinite_json_constant_rejected(self):
        value = frame()
        value["issues"] = [float("nan")]
        rows, errors = parse_jsonl(io.StringIO(json.dumps(value)))
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_json_valid_but_schema_invalid_not_accepted(self):
        value = frame()
        del value["frame_id"]
        rows, errors = parse_jsonl(io.StringIO(json.dumps(value)))
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_invalid_utf8_bytes_rejected_without_fake_record(self):
        rows, errors = parse_jsonl([b"\xff\n"])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)


class AnalyzerTests(unittest.TestCase):
    def test_empty_input_does_not_invent_a_group_or_metrics(self):
        result = analyze_records([])
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["counts"]["input_records"], 0)

    def test_known_same_process_stage_intervals(self):
        result = group([timed_frame()])
        expected = {"request_to_receive": 50, "receive_to_decode": 20,
                    "file_publish_to_worker_read": 5, "worker_read": 5, "decode": 5,
                    "stream2_wall": 20, "stream1_wall": 30,
                    "inference_total_wall": 55, "tracking": 5, "temporal": 5,
                    "tracking_temporal": 10}
        for name, ms in expected.items():
            with self.subTest(stage=name):
                bucket = result["metrics"][name]["MEASURED"]
                self.assertEqual(bucket["n"], 1)
                self.assertEqual(bucket["p50_ms"], ms)
                self.assertEqual(bucket["p95_ms"], ms)
                self.assertEqual(bucket["p99_ms"], ms)

    def test_missing_all_stage_endpoints_is_unavailable_not_zero(self):
        result = group([frame()])
        for name in ("receive_to_decode", "stream1_wall", "stream2_wall", "inference_total_wall"):
            with self.subTest(stage=name):
                metric = result["metrics"][name]
                self.assertEqual(metric["MEASURED"]["n"], 0)
                self.assertEqual(metric["ESTIMATED"]["n"], 0)
                for quantile in ("p50_ms", "p95_ms", "p99_ms"):
                    self.assertIsNone(metric["MEASURED"][quantile])

    def test_unknown_capture_not_used_for_capture_latency_or_frame_age(self):
        result = group([add_alert(timed_frame())])
        for name in ("capture_to_receive", "frame_age_at_decision"):
            with self.subTest(stage=name):
                self.assertEqual(sample_count(result, name), 0)
                self.assertEqual(sample_count(result, name, "ESTIMATED"), 0)

    def test_unsynchronized_capture_clock_cannot_create_latency(self):
        value = with_camera(add_alert(timed_frame()))
        value["timestamps"]["t_capture"] = stamp(100, "camera")
        result = group([value])
        self.assertEqual(sample_count(result, "capture_to_receive"), 0)
        self.assertEqual(sample_count(result, "capture_to_receive", "ESTIMATED"), 0)

    def test_valid_calibration_only_populates_estimated_bucket(self):
        value = with_camera(timed_frame())
        value["timestamps"]["t_capture"] = stamp(100, "camera")
        value["clock_sync"] = [sync_map(offset_ns=800000000)]
        result = group([value])
        metric = result["metrics"]["capture_to_receive"]
        self.assertEqual(metric["MEASURED"]["n"], 0)
        self.assertEqual(metric["ESTIMATED"]["n"], 1)
        self.assertEqual(metric["ESTIMATED"]["p50_ms"], 100)

    def test_expired_calibration_not_used(self):
        value = with_camera(timed_frame())
        value["timestamps"]["t_capture"] = stamp(100, "camera")
        value["clock_sync"] = [sync_map(valid_to_ns=50000000)]
        result = group([value])
        self.assertEqual(sample_count(result, "capture_to_receive", "ESTIMATED"), 0)

    def test_ambiguous_calibrations_not_arbitrarily_selected(self):
        value = with_camera(timed_frame())
        value["timestamps"]["t_capture"] = stamp(100, "camera")
        value["clock_sync"] = [sync_map(), sync_map(sync_id="second")]
        result = group([value])
        self.assertEqual(sample_count(result, "capture_to_receive", "ESTIMATED"), 0)

    def test_estimated_same_clock_not_mixed_with_measured(self):
        value = timed_frame()
        value["timestamps"]["t_decode_end"]["status"] = "ESTIMATED"
        value["timestamps"]["t_decode_end"]["uncertainty_ns"] = 3000000
        result = group([value])
        self.assertEqual(sample_count(result, "receive_to_decode"), 0)
        self.assertEqual(sample_count(result, "receive_to_decode", "ESTIMATED"), 1)

    def test_negative_stage_duration_not_positive_or_zero(self):
        value = timed_frame()
        value["timestamps"]["t_decode_end"] = stamp(990)
        result = group([value])
        self.assertEqual(sample_count(result, "receive_to_decode"), 0)

    def test_exact_duplicate_frame_never_increases_metric_or_alert_counts(self):
        value = add_alert(timed_frame())
        report = analyze_records([value, copy.deepcopy(value)])
        result = report["groups"][0]
        self.assertEqual(report["counts"]["duplicate_records"], 1)
        self.assertEqual(sample_count(result, "stream1_wall"), 1)
        self.assertEqual(result["counts"]["alerts"], 1)

    def test_conflicting_duplicate_cannot_create_second_alert(self):
        first = timed_frame()
        second = add_alert(timed_frame())
        report = analyze_records([first, second])
        self.assertEqual(report["counts"]["conflicting_duplicates"], 2)
        self.assertEqual(report["groups"][0]["counts"]["alerts"], 0)

    def test_new_frame_with_nonincreasing_clock_is_not_used(self):
        for timestamp in (1000, 900):
            report = analyze_records([timed_frame(), timed_frame("f2", timestamp)])
            with self.subTest(timestamp=timestamp):
                self.assertEqual(report["counts"]["chronology_rejected_records"], 1)
                self.assertEqual(sample_count(report["groups"][0], "stream1_wall"), 1)

    def test_clock_identifier_epoch_reuse_is_rejected(self):
        second = timed_frame("f2", 1100)
        second["clock_domains"]["host"]["epoch_id"] = "different-process"
        report = analyze_records([timed_frame(), second])
        self.assertEqual(report["counts"]["clock_conflict_records"], 2)
        self.assertEqual(sample_count(report["groups"][0], "stream1_wall"), 0)

    def test_observed_cadence_is_not_assumed_configured_fps(self):
        result = group([timed_frame("f1", 1000), timed_frame("f2", 1100),
                        timed_frame("f3", 1400)])
        series = result["cadence"]["receive"]["series"]
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["clock_id"], "host")
        self.assertAlmostEqual(series[0]["fps"], 5.0)
        self.assertEqual(series[0]["intervals"]["MEASURED"]["n"], 2)

    def test_single_frame_does_not_have_observed_fps(self):
        result = group([timed_frame()])
        for series in result["cadence"]["receive"]["series"]:
            self.assertIsNone(series["fps"])

    def test_phases_are_not_pooled(self):
        report = analyze_records([timed_frame("f1", 1000, "COLD_START"),
                                  timed_frame("f2", 2000, "WARM")])
        self.assertEqual(len(report["groups"]), 2)
        self.assertEqual({x["phase"] for x in report["groups"]}, {"COLD_START", "WARM"})

    def test_real_and_synthetic_are_never_pooled(self):
        # This label-only copy is an adversarial partition test, not an inference result.
        # It exists only in memory and must never be exported as a benchmark artifact.
        test_only_real_label = timed_frame("partition-only", 2000)
        test_only_real_label["data_kind"] = "REAL_INFERENCE"
        report = analyze_records([timed_frame(), test_only_real_label])
        self.assertEqual(len(report["groups"]), 2)
        self.assertEqual({x["data_kind"] for x in report["groups"]}, {"SYNTHETIC_TEST", "REAL_INFERENCE"})

    def test_source_and_session_are_not_pooled(self):
        other_source, other_session = timed_frame("f2", 2000), timed_frame("f3", 3000)
        other_source["source_id"] = "another-source"
        other_session["session_id"] = "another-session"
        self.assertEqual(len(analyze_records([timed_frame(), other_source, other_session])["groups"]), 3)

    def test_cuda_enqueue_not_reported_as_execution_wall_time(self):
        value = timed_frame()
        value["execution_modes"] = {"stream1": "CUDA_ENQUEUE_ONLY", "stream2": "CUDA_ENQUEUE_ONLY",
                                    "inference": "CUDA_ENQUEUE_ONLY"}
        result = group([value])
        for name in ("stream1_wall", "stream2_wall", "inference_total_wall"):
            with self.subTest(stage=name):
                self.assertEqual(sample_count(result, name), 0)
        self.assertEqual(sample_count(result, "stream1_enqueue_wall"), 1)

    def test_unknown_execution_mode_not_assumed_cpu_or_synchronized(self):
        value = timed_frame()
        value["execution_modes"] = {}
        result = group([value])
        self.assertEqual(sample_count(result, "stream1_wall"), 0)
        self.assertEqual(sample_count(result, "stream2_wall"), 0)

    def test_alert_state_without_new_event_does_not_count_as_new_alert(self):
        value = add_alert(timed_frame())
        value["alerts"][0]["new_event"] = False
        result = group([value])
        self.assertEqual(result["counts"]["alerts"], 0)
        self.assertEqual(sample_count(result, "decision_to_commit"), 0)

    def test_same_event_key_across_frames_only_counted_once(self):
        first, second = add_alert(timed_frame()), add_alert(timed_frame("f2", 2000))
        second["alerts"] = copy.deepcopy(first["alerts"])
        second["alerts"][0]["new_event"] = False
        result = group([first, second])
        self.assertEqual(result["counts"]["alerts"], 1)
        self.assertEqual(sample_count(result, "decision_to_commit"), 1)

    def test_no_alert_does_not_invent_alert_latency(self):
        result = group([timed_frame()])
        self.assertEqual(result["counts"]["alerts"], 0)
        for name in ("decision_to_commit", "commit_to_delivered", "commit_to_visible"):
            with self.subTest(stage=name):
                self.assertEqual(sample_count(result, name), 0)

    def test_decision_and_commit_do_not_mean_displayed_or_delivered(self):
        result = group([add_alert(timed_frame())])
        self.assertEqual(sample_count(result, "decision_to_commit"), 1)
        self.assertEqual(sample_count(result, "commit_to_delivered"), 0)
        self.assertEqual(sample_count(result, "commit_to_visible"), 0)

    def test_matching_delivery_ack_measured_independently_of_decision(self):
        value = add_alert(timed_frame())
        a = value["alerts"][0]
        a["timestamps"]["t_alert_delivered"] = stamp(1200)
        a["acknowledgements"]["t_alert_delivered"] = {"kind": "DELIVERY_ACK", "signal_id": "synthetic-ack",
                                                    "observer": "synthetic-client", "event_key": "event1"}
        result = group([value])
        self.assertEqual(result["metrics"]["decision_to_commit"]["MEASURED"]["p50_ms"], 5)
        self.assertEqual(result["metrics"]["commit_to_delivered"]["MEASURED"]["p50_ms"], 105)
        self.assertEqual(sample_count(result, "commit_to_visible"), 0)

    def test_unknown_or_missing_ground_truth_never_claims_zero_missed_events(self):
        unknown = timed_frame("f2", 2000)
        unknown["ground_truth"] = truth("UNKNOWN", None)
        for value in (timed_frame(), unknown):
            result = group([value])
            with self.subTest(value=value["frame_id"]):
                self.assertIsNone(result["ground_truth"]["missed_events"])

    def test_incomplete_touch_episode_not_counted_as_definitely_missed(self):
        value = timed_frame()
        value["ground_truth"] = truth(complete=False)
        gt = group([value])["ground_truth"]
        self.assertIsNone(gt["missed_events"])
        self.assertEqual(gt["missed_complete_episodes"], 0)

    def test_complete_unmatched_touch_episode_counted_once_not_per_frame(self):
        values = [timed_frame("f1", 1000), timed_frame("f2", 2000)]
        for value in values:
            value["ground_truth"] = truth(complete=True)
        gt = group(values)["ground_truth"]
        self.assertEqual(gt["missed_events"], 1)
        self.assertEqual(gt["complete_touch_episodes"], 1)

    def test_complete_matched_touch_episode_not_missed(self):
        value = add_alert(timed_frame())
        value["ground_truth"] = truth(complete=True, matches=["event1"])
        gt = group([value])["ground_truth"]
        self.assertEqual(gt["missed_events"], 0)

    def test_partial_annotations_do_not_claim_complete_ground_truth(self):
        first, second = timed_frame(), timed_frame("f2", 2000)
        first["ground_truth"] = truth(complete=True)
        gt = group([first, second])["ground_truth"]
        self.assertNotEqual(gt["status"], "COMPLETE")
        self.assertIsNone(gt["missed_events"])


class ExtendedAnalyzerTests(unittest.TestCase):
    def test_unsynchronized_cuda_event_is_not_gpu_execution_metric(self):
        value = timed_frame()
        value["gpu_intervals"] = {"stream1": {"status": "MEASURED", "duration_ms": 1.0,
                                             "method": "CUDA_EVENT", "synchronized": False}}
        self.assertEqual(sample_count(group([value]), "stream1_gpu_execution"), 0)

    def test_synchronized_cuda_event_kept_separate_from_cpu_wall(self):
        value = timed_frame()
        value["execution_modes"]["stream1"] = "CUDA_SYNCHRONIZED_WALL"
        value["gpu_intervals"] = {"stream1": {"status": "MEASURED", "duration_ms": 17.0,
                                             "method": "CUDA_EVENT", "synchronized": True}}
        result = group([value])
        self.assertEqual(result["metrics"]["stream1_gpu_execution"]["MEASURED"]["p50_ms"], 17)
        self.assertEqual(result["metrics"]["stream1_wall"]["MEASURED"]["p50_ms"], 30)

    def test_unconfirmed_prediction_not_complete_inference_or_tracking(self):
        value = timed_frame()
        value["prediction_ready_confirmed"] = False
        result = group([value])
        self.assertEqual(sample_count(result, "inference_total_wall"), 0)
        self.assertEqual(sample_count(result, "tracking"), 0)
        self.assertEqual(result["cadence"]["prediction"]["series"], [])

    def test_non_processed_frames_have_counts_but_no_stage_evidence(self):
        values = []
        for index, status in enumerate(("DUPLICATE", "STALE", "DROPPED", "MISSING", "ERROR", "REJECTED")):
            value = timed_frame("status-" + str(index), 1000 + index * 1000)
            value["frame_status"] = status
            values.append(value)
        result = group(values)
        self.assertEqual(result["counts"]["accepted_records"], 0)
        self.assertEqual(sample_count(result, "stream1_wall"), 0)
        self.assertEqual(result["counts"]["frame_status"]["DROPPED"], 1)
        self.assertEqual(result["cadence"]["receive"]["series"], [])

    def test_two_point_quantiles_are_linear_interpolation(self):
        first, second = timed_frame("f1", 1000), timed_frame("f2", 2000)
        second["timestamps"]["t_stream1_end"] = stamp(2080)
        result = group([first, second])["metrics"]["stream1_wall"]["MEASURED"]
        self.assertEqual(result["n"], 2)
        self.assertAlmostEqual(result["p50_ms"], 35)
        self.assertAlmostEqual(result["p95_ms"], 39.5)
        self.assertAlmostEqual(result["p99_ms"], 39.9)

    def test_conflicting_repeated_event_timestamps_cannot_create_favorable_latency(self):
        first, second = add_alert(timed_frame()), add_alert(timed_frame("f2", 2000))
        result = group([first, second])
        self.assertEqual(result["counts"]["alerts"], 1)
        self.assertEqual(sample_count(result, "decision_to_commit"), 0)
        self.assertEqual(result["metrics"]["decision_to_commit"]["unavailable"].get("conflicting_event_timestamp"), 1)

    def test_later_acknowledgement_joins_original_event_without_new_alert(self):
        first, second = add_alert(timed_frame()), timed_frame("f2", 2000)
        a = {"event_key": "event1", "new_event": False,
             "timestamps": {"t_alert_delivered": stamp(2050)},
             "acknowledgements": {"t_alert_delivered": {
                 "kind": "DELIVERY_ACK", "signal_id": "synthetic-late-ack",
                 "observer": "synthetic-client", "event_key": "event1"}}}
        second["alerts"] = [a]
        result = group([first, second])
        self.assertEqual(result["counts"]["alerts"], 1)
        self.assertEqual(result["metrics"]["commit_to_delivered"]["MEASURED"]["p50_ms"], 955)

    def test_unobserved_matched_event_key_not_used_to_hide_a_miss(self):
        value = timed_frame()
        value["ground_truth"] = truth(complete=True, matches=["not-observed"])
        gt = group([value])["ground_truth"]
        self.assertEqual(gt["missed_events"], 1)
        self.assertEqual(gt["unobserved_matched_event_keys"], ["not-observed"])

    def test_direct_analysis_rejects_invalid_record_and_continues(self):
        invalid = frame("invalid", 900)
        invalid["frame_status"] = "INVENTED"
        result = analyze_records([invalid, timed_frame()])
        self.assertEqual(result["counts"]["invalid_records"], 1)
        self.assertEqual(result["counts"]["accepted_records"], 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_analysis_does_not_mutate_input_records(self):
        values = [add_alert(timed_frame())]
        original = copy.deepcopy(values)
        analyze_records(values)
        self.assertEqual(values, original)


class ExtendedParseTests(unittest.TestCase):
    def test_overlong_json_line_rejected_before_record_creation(self):
        rows, errors = parse_jsonl([" " * (1024 * 1024 + 1)])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_huge_json_integer_rejected(self):
        payload = json.dumps(frame()).replace('"schema_version": 1', '"schema_version": ' + "1" * 129)
        rows, errors = parse_jsonl([payload])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_infinity_float_overflow_rejected(self):
        payload = json.dumps(frame()).replace('"schema_version": 1', '"schema_version": 1e999')
        rows, errors = parse_jsonl([payload])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_line_numbers_preserve_blank_and_invalid_lines(self):
        rows, errors = parse_jsonl(["\n", "[]\n", json.dumps(frame()) + "\n"])
        self.assertEqual(rows, [frame()])
        self.assertEqual(errors[0]["line"], 2)


if __name__ == "__main__":
    unittest.main()
