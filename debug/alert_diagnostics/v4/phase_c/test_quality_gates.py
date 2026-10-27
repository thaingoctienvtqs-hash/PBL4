"""Desired quality gates. Real FAILs are retained; never marked expectedFailure."""
import unittest
from ..pipeline_v4 import PipelineV4
from ..scenarios import scenarios
from ..compare_v3_v4 import evaluate,event_count
from .audit_scenarios import cases,identity_report

class QualityGates(unittest.TestCase):
    def test_sustained_valid_contact_should_confirm_at_30fps(self):
        unused,rows=evaluate(cases()["high_fps_30_moderate"],2)
        self.assertGreaterEqual(event_count(rows),1,"Window size limits support below 0.4s at high FPS")

    def test_camera_pan_should_not_alert_on_stationary_print(self):
        unused,rows=evaluate(cases()["camera_slow_pan_printed_hand"],2)
        self.assertEqual(event_count(rows),0,"Camera-relative motion is mistaken for hand approach")

    def test_crossing_should_not_transfer_id_between_actors(self):
        inputs=cases()["hands_cross_offset_0.0"]
        unused,rows=evaluate(inputs,2)
        self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[],
                         "Existing IDs transfer between two constant-velocity actors")

    def test_disconnect_should_clear_active_state_even_when_cache_full(self):
        p=PipelineV4({"input":{"frame_id_cache_size":5}})
        for row in scenarios()["normal_entry_hold"][:5]:p.step(**row)
        p.disconnect("off",1)
        self.assertEqual(p.tracker.tracks,{},"Safety control path is blocked by frame-capacity gate")

class FastPathQualityGate(unittest.TestCase):
    def test_fast_valid_contact_should_confirm_at_30fps(self):
        unused,rows=evaluate(cases()["high_fps_30_fast"],2)
        self.assertGreaterEqual(event_count(rows),1,"Five-sample deque also caps fast-path time span")
