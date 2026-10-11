import unittest
from datetime import datetime, timezone

import numpy as np

from server.contact import BinaryMask, ContactAnalyzer, ContactSettings, ContactState, Detection


class ContactLogicTests(unittest.TestCase):
    def setUp(self):
        self.settings = ContactSettings(
            confidence_threshold=0.5,
            contact_overlap_threshold=0.2,
            near_distance_threshold=20.0,
            minimum_contact_duration=0.5,
            required_positive_frames=3,
            sliding_window_size=5,
            alert_cooldown=1.0,
        )
        self.analyzer = ContactAnalyzer(self.settings)
        self.painting = Detection(0, 0.95, (100, 100, 300, 300), 1)

    def hand(self, box=(150, 150, 170, 170), track_id=7, confidence=0.9):
        return Detection(2, confidence, box, track_id)

    def analyze(self, detections, now):
        return self.analyzer.analyze(
            detections,
            monotonic_time=now,
            event_time=datetime.fromtimestamp(now, tz=timezone.utc),
        )

    def test_person_or_non_contact_does_not_raise_contact(self):
        person = Detection(1, 0.99, (20, 20, 90, 300), 4)
        result = self.analyze([self.painting, person], 0.0)
        self.assertEqual(result.state, ContactState.SAFE)
        self.assertEqual(result.events, ())

    def test_near_hand_is_near_but_not_an_alert(self):
        result = self.analyze([self.painting, self.hand((80, 150, 95, 165))], 0.0)
        self.assertEqual(result.state, ContactState.NEAR)
        self.assertEqual(result.events, ())

    def test_single_frame_overlap_is_pending_without_event(self):
        result = self.analyze([self.painting, self.hand()], 0.0)
        self.assertEqual(result.state, ContactState.CONTACT_PENDING)
        self.assertEqual(result.events, ())

    def test_persistent_contact_emits_one_event(self):
        results = [
            self.analyze([self.painting, self.hand()], now)
            for now in (0.0, 0.25, 0.5, 0.75)
        ]
        self.assertEqual(len(results[0].events), 0)
        self.assertEqual(len(results[1].events), 0)
        self.assertEqual(len(results[2].events), 1)
        self.assertEqual(len(results[3].events), 0)
        self.assertEqual(results[2].events[0].contact_type, "hand")
        self.assertEqual(results[2].events[0].event, "painting_contact")

    def test_tool_contact_uses_same_temporal_confirmation(self):
        tool = Detection(3, 0.9, (150, 150, 170, 170), 12)
        results = [
            self.analyze([self.painting, tool], now)
            for now in (0.0, 0.25, 0.5)
        ]
        self.assertEqual(len(results[-1].events), 1)
        self.assertEqual(results[-1].events[0].contact_type, "tool")

    def test_hand_landmark_fingertips_use_artwork_mask_without_claiming_hand_mask(self):
        artwork = np.zeros((100, 100), dtype=np.uint8)
        artwork[40:60, 40:60] = 1
        mask = BinaryMask(100, 100, np.packbits(artwork.reshape(-1), bitorder="little").tobytes())
        painting = Detection(0, 0.95, (40, 40, 60, 60), 1, mask)
        tips = ((50.0, 50.0), (10.0, 10.0), (20.0, 10.0), (30.0, 10.0), (10.0, 20.0))
        hand = Detection(2, 0.5, (20, 20, 80, 80), 7, contact_points=tips)
        results = [self.analyze([painting, hand], now) for now in (0.0, 0.25, 0.5)]
        self.assertEqual(results[0].maximum_overlap, 0.2)
        self.assertEqual(results[-1].state, ContactState.CONTACT_EVENT)
        self.assertEqual(len(results[-1].events), 1)

    def test_invalid_time_and_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze([self.painting], monotonic_time=float("nan"))
        with self.assertRaises(ValueError):
            ContactSettings(0.5, 0.0, 20, 0.5, 3, 5, 1.0)


if __name__ == "__main__":
    unittest.main()
