"""Behavior characterization of unchanged production functions; no camera or GPU."""
import copy
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import (HERE, LogicSession, config_compat, load_config, reject_overrides,
                    write_json_new, isolated_resolve)
from run_inference import FrameProbe, TimedDetector, build_parser, check_args

TRACES = {}

class LogicTests(unittest.TestCase):
    def record(self, name, inputs, settings=None):
        session = LogicSession(settings)
        for now, center, score in inputs:
            session.step(now, (center,), score)
        TRACES[name] = session.rows
        return [frame["tracks"][0] for frame in session.rows]

    def test_A_first_detection_inside(self):
        rows = self.record("A_initial_inside", [(i*.2, 500, .6) for i in range(6)])
        self.assertEqual(rows[-1]["positive_frames"], 5)
        self.assertEqual({r["track_id"] for r in rows}, {0})
        self.assertTrue(all(r["state_reason"] == "awaiting ROI entry" for r in rows))
        self.assertFalse(any(r["alert_started"] for r in rows))

    def test_B_entry_then_stationary_hold_one_event(self):
        rows = self.record("B_entry_hold", [(0, 250, .6)] +
                           [(i*.2, 400, .6) for i in range(1, 16)])
        self.assertTrue(rows[1]["ever_entered_roi"])
        self.assertEqual(rows[3]["state"], "ALERT")
        self.assertEqual(sum(r["alert_started"] for r in rows), 1)
        self.assertTrue(all(r["state"] == "ALERT" for r in rows[3:]))

    def test_C_slow_crossing_is_not_recorded(self):
        rows = self.record("C_slow_crossing", [(i*.2, x, .6)
                           for i, x in enumerate(range(350, 471, 10))])
        self.assertGreaterEqual(rows[-1]["roi_overlap"], .3)
        self.assertEqual(rows[-1]["positive_frames"], 5)
        self.assertEqual({r["track_id"] for r in rows}, {0})
        self.assertFalse(any(r["ever_entered_roi"] for r in rows))
        self.assertEqual(rows[-1]["state_reason"], "awaiting ROI entry")

    def test_D_timeout_recreates_ids(self):
        rows = self.record("D_timeout", [(0, 250, .6)] +
                           [(i*1.01, 400, .6) for i in range(1, 6)])
        self.assertEqual([r["track_id"] for r in rows], list(range(6)))
        self.assertTrue(all(r["positive_frames"] == 1 for r in rows[1:]))
        self.assertFalse(any(r["alert_started"] for r in rows))

    def test_E_three_of_five_with_intermittent_low_scores(self):
        rows = self.record("E_three_of_five", [(0, 250, .6)] +
                           [((i+1)*.2, 400, score)
                            for i, score in enumerate([.6, .1, .6, .1, .6])])
        self.assertFalse(any(r["alert_started"] for r in rows[:-1]))
        self.assertEqual(rows[-1]["history"], [True, False, True, False, True])
        self.assertTrue(rows[-1]["alert_started"])

    def test_F_two_high_frames_after_entry(self):
        rows = self.record("F_fast_path", [(0, 250, .85), (.2, 400, .85), (.4, 400, .85)])
        self.assertFalse(rows[1]["alert_started"])
        self.assertTrue(rows[2]["alert_started"])
        self.assertEqual(rows[2]["positive_frames"], 2)
        self.assertIn("high_object_contact", rows[2]["state_reason"])

    def test_G_static_depicted_hand_stays_candidate(self):
        rows = self.record("G_static_depicted_hand", [(i*.2, 500, .99) for i in range(20)])
        self.assertEqual({r["track_id"] for r in rows}, {0})
        self.assertFalse(any(r["ever_entered_roi"] or r["alert_started"] for r in rows))
        self.assertEqual(rows[-1]["state"], "CANDIDATE")

    def test_low_object_contact_after_entry(self):
        rows = self.record("low_object_contact", [(0, 250, .1)] +
                           [(i*.2, 400, .149) for i in range(1, 8)])
        self.assertTrue(rows[-1]["ever_entered_roi"])
        self.assertEqual(rows[-1]["positive_frames"], 0)
        self.assertIn("object_contact_below_threshold", rows[-1]["alert_blockers"])
        self.assertFalse(any(r["alert_started"] for r in rows))

    def test_fast_scores_still_require_entry(self):
        rows = self.record("fast_without_entry", [(i*.2, 500, .99) for i in range(5)])
        self.assertGreaterEqual(rows[-1]["high_contact_streak"], 2)
        self.assertFalse(rows[-1]["alert_started"])

    def test_detection_miss_is_invalid_frame(self):
        session = LogicSession()
        session.step(0, (250,))
        session.step(.2, (400,))
        missing = session.step(.4, ())
        self.assertFalse(missing["tracks"][0]["observed"])
        self.assertFalse(missing["tracks"][0]["valid_contact"])
        self.assertEqual(missing["tracks"][0]["history"], [False, True, False])

class SafetyTests(unittest.TestCase):
    def test_template_matches_contacthands_defaults(self):
        settings = load_config(HERE / "config.baseline.json", environ={})
        self.assertEqual(settings["thresholds"], config_compat.DEFAULTS["thresholds"])
        self.assertEqual(settings["alert"], config_compat.DEFAULTS["alert"])
        self.assertIs(settings["roi"]["normalized"], True)

    def test_environment_override_is_rejected(self):
        for key in ("PBL4_EVENT_DB", "PBL4_LATEST_FRAME", "CONTACTHANDS_MODEL_WEIGHTS"):
            with self.assertRaises(ValueError):
                reject_overrides({key: "protected"})

    def test_existing_file_is_never_overwritten(self):
        # TemporaryDirectory is contained inside diagnostics, never live data.
        with tempfile.TemporaryDirectory(dir=str(HERE)) as folder:
            path = Path(folder) / "new.json"
            write_json_new(path, {"original": True})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_json_new(path, {"original": False})
            self.assertEqual(path.read_bytes(), before)

    def test_runtime_output_outside_diagnostics_is_rejected(self):
        with self.assertRaises(ValueError):
            isolated_resolve({"paths": {"latest_frame": "src/data/latest.jpg"}}, "latest_frame")

    def test_explicit_inference_gate_and_positive_limits(self):
        parser = build_parser()
        with self.assertRaises(ValueError):
            check_args(parser.parse_args([]))
        for option, value in (("--poll-interval", "nan"), ("--max-seconds", "inf"),
                              ("--track-timeout", "0"), ("--max-frames", "0")):
            with self.assertRaises(ValueError):
                check_args(parser.parse_args(["--allow-inference", option, value]))

    def test_probe_uses_actual_tracking_timestamp_and_new_id(self):
        session = LogicSession()
        probe = FrameProbe()
        from common import worker
        original = worker.update_tracks
        with patch.object(worker, "update_tracks", probe):
            session.step(0, (250,))
            self.assertEqual(probe.new_ids, {0})
            session.step(.2, (400,))
            self.assertEqual(probe.new_ids, set())
            self.assertAlmostEqual(probe.delta, .2)
            session.step(1.3, (400,))
            self.assertEqual(probe.new_ids, {1})
            self.assertEqual(probe.expired_ids, [0])
        self.assertIs(worker.update_tracks, original)

    def test_timed_detector_measures_and_synchronizes_without_gpu(self):
        calls = []
        class Detector:
            def predict(self, frame):
                calls.append("predict")
                return frame
        measured = TimedDetector(Detector(), lambda: calls.append("sync"))
        frame = object()
        self.assertIs(measured.predict(frame), frame)
        self.assertEqual(calls, ["sync", "predict", "sync"])
        self.assertGreaterEqual(measured.inference_seconds, 0)

if __name__ == "__main__":
    unittest.main()
