"""Input-quality regressions; synthetic records and in-memory I/O only."""
import contextlib
import copy
import io
import json
import unittest
from unittest import mock

from debug.latency_diagnostics import cli, schema
from debug.latency_diagnostics.analyzer import analyze_records
from debug.latency_diagnostics.tests.test_analyzer import timed_frame, truth
from debug.latency_diagnostics.tests.test_schema import stamp


def capture_records():
    first, second = timed_frame("f1", 1000), timed_frame("f2", 2000)
    first["timestamps"]["t_capture"] = stamp(900, method="SYNTHETIC_TEST_source_capture")
    second["timestamps"]["t_capture"] = stamp(1900, method="SYNTHETIC_TEST_source_capture")
    for value in (first, second):
        value["ground_truth"] = truth(complete=True)
    return first, second


def complete_record(frame_id="f1", at_ms=1000, phase="WARM"):
    value = timed_frame(frame_id, at_ms, phase)
    value["ground_truth"] = truth(complete=True, episode="episode-" + frame_id)
    return value


class CaptureChronologyTests(unittest.TestCase):
    def test_repeated_capture_new_frame_id_does_not_add_evidence(self):
        first, second = capture_records()
        second["timestamps"]["t_capture"] = copy.deepcopy(first["timestamps"]["t_capture"])
        report = analyze_records([first, second])
        self.assertEqual(report["counts"]["chronology_rejected_records"], 1)
        self.assertEqual(report["counts"]["accepted_records"], 1)
        self.assertEqual(report["groups"][0]["ground_truth"]["annotated_frames"], 2)
        self.assertIsNone(report["groups"][0]["ground_truth"]["missed_events"])

    def test_decreasing_capture_new_frame_id_does_not_add_evidence(self):
        first, second = capture_records()
        second["timestamps"]["t_capture"] = stamp(800, method="SYNTHETIC_TEST_source_capture")
        report = analyze_records([first, second])
        self.assertEqual(report["counts"]["chronology_rejected_records"], 1)
        self.assertEqual(report["counts"]["accepted_records"], 1)
        self.assertEqual(report["groups"][0]["metrics"]["stream1_wall"]["MEASURED"]["n"], 1)

    def test_unknown_capture_does_not_fabricate_or_reject_local_cadence(self):
        first, second = capture_records()
        second["timestamps"]["t_capture"] = schema.unknown("UNKNOWN", "source_not_provided")
        report = analyze_records([first, second])
        self.assertEqual(report["counts"]["chronology_rejected_records"], 0)
        self.assertEqual(report["counts"]["accepted_records"], 2)
        result = report["groups"][0]
        self.assertEqual(result["metrics"]["capture_to_receive"]["MEASURED"]["n"], 1)
        self.assertEqual(result["cadence"]["receive"]["series"][0]["n"], 2)

    def test_increasing_capture_and_receive_are_accepted(self):
        report = analyze_records(capture_records())
        self.assertEqual(report["counts"]["chronology_rejected_records"], 0)
        self.assertEqual(report["counts"]["accepted_records"], 2)
        self.assertEqual(report["groups"][0]["metrics"]["capture_to_receive"]["MEASURED"]["n"], 2)

    def test_capture_absent_first_frame_still_allows_next_known_capture(self):
        first, second = capture_records()
        del first["timestamps"]["t_capture"]
        report = analyze_records([first, second])
        self.assertEqual(report["counts"]["chronology_rejected_records"], 0)
        self.assertEqual(report["counts"]["accepted_records"], 2)


class UnknownScopeInputErrorTests(unittest.TestCase):
    def test_schema_error_prevents_full_ground_truth_claim_in_surviving_group(self):
        valid = complete_record()
        invalid = complete_record("invalid", 2000)
        del invalid["frame_id"]
        report = analyze_records([valid, invalid])
        gt = report["groups"][0]["ground_truth"]
        self.assertEqual(report["counts"]["invalid_records"], 1)
        self.assertEqual(gt["status"], "PARTIAL")
        self.assertIsNone(gt["missed_events"])
        self.assertEqual(gt["missed_complete_episodes"], 1)
        self.assertEqual(report["groups"][0]["metrics"]["stream1_wall"]["MEASURED"]["n"], 1)

    def test_error_with_unattributable_input_prevents_full_evaluation_claim(self):
        report = analyze_records([complete_record(), None])
        self.assertEqual(report["counts"]["invalid_records"], 1)
        self.assertEqual(report["groups"][0]["ground_truth"]["status"], "PARTIAL")
        self.assertIsNone(report["groups"][0]["ground_truth"]["missed_events"])

    def test_no_input_error_preserves_explicit_complete_ground_truth(self):
        report = analyze_records([complete_record()])
        gt = report["groups"][0]["ground_truth"]
        self.assertEqual(gt["status"], "COMPLETE")
        self.assertEqual(gt["missed_events"], 1)
        self.assertEqual(report["counts"]["invalid_records"], 0)

    def test_cli_parse_error_does_not_hide_unknown_session_observations(self):
        payload = json.dumps(complete_record()).encode("utf-8") + b"\n{broken\n"
        output = io.StringIO()
        with mock.patch.object(cli.Path, "is_file", return_value=True), \
                mock.patch.object(cli.Path, "open", return_value=io.BytesIO(payload)), \
                mock.patch.object(cli, "_write_summary", side_effect=AssertionError("no output artifact")), \
                contextlib.redirect_stdout(output):
            code = cli.main(["analyze", "--input", "SYNTHETIC_TEST.jsonl", "--stdout"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report["counts"]["invalid_jsonl_lines"], 1)
        self.assertEqual(report["groups"][0]["ground_truth"]["status"], "PARTIAL")
        self.assertIsNone(report["groups"][0]["ground_truth"]["missed_events"])
        self.assertEqual(report["groups"][0]["ground_truth"]["missed_complete_episodes"], 1)
        self.assertEqual(report["groups"][0]["metrics"]["stream1_wall"]["MEASURED"]["n"], 1)

    def test_unknown_scope_error_never_merges_phase_or_data_kind_timing_buckets(self):
        first = complete_record("synthetic-warm", 1000)
        cold = complete_record("synthetic-cold", 2000, "COLD_START")
        # Label-only copy for partition testing. Never export as inference data.
        real_label_only = complete_record("partition-only", 3000)
        real_label_only["data_kind"] = "REAL_INFERENCE"
        report = analyze_records([first, cold, real_label_only, {}])
        self.assertEqual(len(report["groups"]), 3)
        self.assertEqual({(x["data_kind"], x["phase"]) for x in report["groups"]},
                         {("SYNTHETIC_TEST", "WARM"), ("SYNTHETIC_TEST", "COLD_START"),
                          ("REAL_INFERENCE", "WARM")})
        for result in report["groups"]:
            with self.subTest(group=(result["data_kind"], result["phase"])):
                self.assertEqual(result["ground_truth"]["status"], "PARTIAL")
                self.assertIsNone(result["ground_truth"]["missed_events"])
                self.assertEqual(result["metrics"]["stream1_wall"]["MEASURED"]["n"], 1)
                self.assertEqual(result["metrics"]["stream1_wall"]["MEASURED"]["p50_ms"], 30)
                self.assertEqual(result["metrics"]["stream1_wall"]["ESTIMATED"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
