"""Ground-truth regression tests; entirely SYNTHETIC_TEST and in memory."""
import copy
import unittest

from debug.latency_diagnostics.analyzer import analyze_records
from debug.latency_diagnostics.tests.test_analyzer import (
    add_alert, group, sample_count, timed_frame, truth)


class GroundTruthTests(unittest.TestCase):
    def test_dropped_or_missing_complete_touch_episode_is_not_hidden(self):
        for status in ("DROPPED", "MISSING"):
            value = timed_frame()
            value["frame_status"] = status
            value["ground_truth"] = truth(complete=True)
            result = group([value])
            with self.subTest(status=status):
                self.assertEqual(result["ground_truth"]["annotated_frames"], 1)
                self.assertEqual(result["ground_truth"]["status"], "COMPLETE")
                self.assertEqual(result["ground_truth"]["missed_events"], 1)
                self.assertEqual(result["counts"]["alerts"], 0)
                self.assertEqual(result["counts"]["accepted_records"], 0)
                self.assertEqual(sample_count(result, "stream1_wall"), 0)

    def test_consecutive_missing_frames_do_not_count_episode_multiple_times(self):
        values = [timed_frame("f" + str(i), 1000 + 100 * i) for i in range(4)]
        for value in values:
            value["frame_status"] = "MISSING"
            value["ground_truth"] = truth(complete=True)
        result = group(values)
        self.assertEqual(result["ground_truth"]["annotated_frames"], 4)
        self.assertEqual(result["ground_truth"]["complete_touch_episodes"], 1)
        self.assertEqual(result["ground_truth"]["missed_events"], 1)
        self.assertEqual(sample_count(result, "stream1_wall"), 0)

    def test_unknown_on_skipped_frame_is_retained(self):
        for status in ("DROPPED", "MISSING", "ERROR", "STALE"):
            value = timed_frame()
            value["frame_status"] = status
            value["ground_truth"] = truth("UNKNOWN", None)
            gt = group([value])["ground_truth"]
            with self.subTest(status=status):
                self.assertEqual(gt["annotated_frames"], 1)
                self.assertEqual(gt["unknown_frames"], 1)
                self.assertEqual(gt["status"], "PARTIAL")
                self.assertIsNone(gt["missed_events"])

    def test_missing_labels_on_skipped_frames_do_not_become_no_touch(self):
        value = timed_frame()
        value["frame_status"] = "MISSING"
        gt = group([value])["ground_truth"]
        self.assertEqual(gt["status"], "NOT_AVAILABLE")
        self.assertIsNone(gt["missed_events"])
        self.assertIsNone(gt["unknown_frames"])
        self.assertIsNone(gt["missed_complete_episodes"])

    def test_chronology_rejected_touch_label_retained_but_completeness_conservative(self):
        first, second = timed_frame("f1", 1000), timed_frame("f2", 900)
        first["ground_truth"] = truth("NO_TOUCH", None)
        second["ground_truth"] = truth(complete=True)
        result = group([first, second])
        gt = result["ground_truth"]
        self.assertEqual(result["counts"]["chronology_rejected_records"], 1)
        self.assertEqual(sample_count(result, "stream1_wall"), 1)
        self.assertEqual(gt["annotated_frames"], 2)
        self.assertEqual(gt["complete_touch_episodes"], 1)
        self.assertEqual(gt["status"], "PARTIAL")
        self.assertIsNone(gt["missed_events"])

    def test_chronology_rejected_unknown_label_not_removed(self):
        first, second = timed_frame("f1", 1000), timed_frame("f2", 900)
        first["ground_truth"] = truth("NO_TOUCH", None)
        second["ground_truth"] = truth("UNKNOWN", None)
        result = group([first, second])
        self.assertEqual(result["ground_truth"]["annotated_frames"], 2)
        self.assertEqual(result["ground_truth"]["unknown_frames"], 1)
        self.assertIsNone(result["ground_truth"]["missed_events"])

    def test_conflicting_frame_rows_prevent_complete_ground_truth_claim(self):
        good, first = timed_frame("good", 500), timed_frame("conflict", 1000)
        good["ground_truth"] = truth("NO_TOUCH", None)
        first["ground_truth"] = truth(complete=True)
        second = copy.deepcopy(first)
        second["ground_truth"]["label"] = "NO_TOUCH"
        second["ground_truth"]["episode_complete"] = False
        result = group([good, first, second])
        self.assertEqual(result["counts"]["conflicting_duplicates"], 2)
        self.assertEqual(result["ground_truth"]["annotated_frames"], 1)
        self.assertEqual(result["ground_truth"]["status"], "PARTIAL")
        self.assertEqual(result["ground_truth"]["excluded_observation_records"], 2)
        self.assertIsNone(result["ground_truth"]["missed_events"])

    def test_clock_conflicts_preserve_explicit_uncertainty_in_gt_completeness(self):
        good = timed_frame("good", 500)
        good["clock_domains"] = {"trusted": good["clock_domains"]["host"]}
        for stamp in good["timestamps"].values():
            if stamp["clock_id"] == "host":
                stamp["clock_id"] = "trusted"
        good["ground_truth"] = truth("NO_TOUCH", None)
        first, second = timed_frame("f1", 1000), timed_frame("f2", 2000)
        for value in (first, second):
            value["ground_truth"] = truth(complete=True)
        second["clock_domains"]["host"]["epoch_id"] = "conflicting-process"
        result = group([good, first, second])
        self.assertEqual(result["counts"]["clock_conflict_records"], 2)
        self.assertEqual(result["ground_truth"]["status"], "PARTIAL")
        self.assertEqual(result["ground_truth"]["excluded_observation_records"], 2)
        self.assertIsNone(result["ground_truth"]["missed_events"])

    def test_episode_split_across_cold_and_warm_is_not_complete_in_either_slice(self):
        first = timed_frame("f1", 1000, "COLD_START")
        second = timed_frame("f2", 2000, "WARM")
        first["ground_truth"] = truth(complete=False)
        second["ground_truth"] = truth(complete=True)
        result = analyze_records([first, second])
        self.assertEqual(len(result["groups"]), 2)
        for item in result["groups"]:
            with self.subTest(phase=item["phase"]):
                self.assertEqual(item["ground_truth"]["status"], "PARTIAL")
                self.assertEqual(item["ground_truth"]["cross_phase_episodes"], ["episode1"])
                self.assertEqual(item["ground_truth"]["complete_touch_episodes"], 0)
                self.assertIsNone(item["ground_truth"]["missed_events"])

    def test_no_ground_truth_never_reports_zero_misses(self):
        result = group([timed_frame(), timed_frame("f2", 2000)])
        self.assertEqual(result["ground_truth"]["status"], "NOT_AVAILABLE")
        self.assertIsNone(result["ground_truth"]["missed_events"])
        self.assertIsNone(result["ground_truth"]["unknown_frames"])

    def test_event_associated_across_frames_is_found_once(self):
        first = add_alert(timed_frame("f1", 1000))
        second = timed_frame("f2", 2000)
        second["alerts"] = copy.deepcopy(first["alerts"])
        second["alerts"][0]["new_event"] = False
        first["ground_truth"] = truth(complete=False, matches=["event1"])
        second["ground_truth"] = truth(complete=True, matches=["event1"])
        result = group([first, second])
        self.assertEqual(result["counts"]["alerts"], 1)
        self.assertEqual(result["ground_truth"]["complete_touch_episodes"], 1)
        self.assertEqual(result["ground_truth"]["observed_matched_events"], 1)
        self.assertEqual(result["ground_truth"]["missed_events"], 0)

    def test_unobserved_external_match_key_is_not_a_found_alert(self):
        value = timed_frame()
        value["ground_truth"] = truth(complete=True, matches=["external-not-observed"])
        gt = group([value])["ground_truth"]
        self.assertEqual(gt["observed_matched_events"], 0)
        self.assertEqual(gt["unobserved_matched_event_keys"], ["external-not-observed"])
        self.assertEqual(gt["missed_events"], 1)

    def test_event_from_other_session_cannot_satisfy_this_episode(self):
        touch = timed_frame()
        touch["ground_truth"] = truth(complete=True, matches=["event1"])
        another_session = add_alert(timed_frame("another", 2000))
        another_session["session_id"] = "different-session"
        result = analyze_records([touch, another_session])
        own = next(x for x in result["groups"] if x["session_id"] == "synthetic-session")
        self.assertEqual(own["ground_truth"]["missed_events"], 1)
        self.assertEqual(own["ground_truth"]["observed_matched_events"], 0)

    def test_unknown_frame_remains_in_denominator_alongside_complete_touch(self):
        touch, unknown = timed_frame("f1", 1000), timed_frame("f2", 2000)
        touch["ground_truth"] = truth(complete=True)
        unknown["ground_truth"] = truth("UNKNOWN", None)
        gt = group([touch, unknown])["ground_truth"]
        self.assertEqual(gt["annotated_frames"], 2)
        self.assertEqual(gt["unknown_frames"], 1)
        self.assertEqual(gt["missed_complete_episodes"], 1)
        self.assertEqual(gt["status"], "PARTIAL")
        self.assertIsNone(gt["missed_events"])

    def test_all_unknown_or_missing_labels_do_not_claim_touch_recall(self):
        unknown = timed_frame("f1", 1000)
        unknown["ground_truth"] = truth("UNKNOWN", None)
        unlabeled = timed_frame("f2", 2000)
        gt = group([unknown, unlabeled])["ground_truth"]
        self.assertEqual(gt["annotated_frames"], 1)
        self.assertEqual(gt["unknown_frames"], 1)
        self.assertEqual(gt["status"], "PARTIAL")
        self.assertIsNone(gt["missed_events"])

    def test_exact_duplicate_ground_truth_frame_counted_once(self):
        value = timed_frame()
        value["ground_truth"] = truth(complete=True)
        result = group([value, copy.deepcopy(value)])
        self.assertEqual(result["counts"]["duplicate_records"], 1)
        self.assertEqual(result["ground_truth"]["annotated_frames"], 1)
        self.assertEqual(result["ground_truth"]["complete_touch_episodes"], 1)
        self.assertEqual(result["ground_truth"]["missed_events"], 1)


if __name__ == "__main__":
    unittest.main()
