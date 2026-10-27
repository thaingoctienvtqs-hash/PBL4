"""Logic characterization and safety tests. No camera, GPU, images, DB or environment writes."""
import copy
import math
import unittest
from .pipeline_v4 import PipelineV4,validate_config
from .tracking_v4 import minimum_assignment
from .scenarios import scenarios,detection,frame
from .compare_v3_v4 import evaluate,event_count,id_count

class ComparisonTests(unittest.TestCase):
    def compare(self,name,timeout=2):
        return evaluate(scenarios()[name],timeout)

    def test_initial_inside_neither_alerts(self):
        old,new = self.compare("initial_inside")
        self.assertEqual((event_count(old),event_count(new)),(0,0))
        self.assertEqual(old[-1]["tracks"][0]["positive_frames"],5)
        self.assertEqual(new[-1]["tracks"][0]["positive_frames"],0)
        self.assertEqual(new[-1]["tracks"][0]["state_reason"],"awaiting_roi_entry")

    def test_normal_entry_stationary_hold_one_event_both(self):
        old,new = self.compare("normal_entry_hold")
        self.assertEqual((event_count(old),event_count(new)),(1,1))
        self.assertTrue(new[-1]["tracks"][0]["alert_active"])

    def test_slow_entry_improves_over_v3(self):
        old,new = self.compare("slow_entry")
        self.assertEqual(event_count(old),0)
        self.assertEqual(event_count(new),1)
        self.assertEqual(id_count(new),1)

    def test_timeout_comparison_1_2_3(self):
        results = []
        for timeout in (1,2,3):
            old,new = self.compare("gap_1_01",timeout)
            results.append((timeout,id_count(old),id_count(new),event_count(new)))
        self.assertEqual(results,[(1,6,6,0),(2,1,1,1),(3,1,1,1)])

    def test_v4_candidate_timeout_not_v3_default(self):
        frames = scenarios()["gap_1_01"]
        old_at_one,unused = evaluate(frames,1)
        unused,new_at_two = evaluate(frames,2)
        self.assertEqual(id_count(old_at_one),6)
        self.assertEqual(id_count(new_at_two),1)
        self.assertEqual(event_count(new_at_two),1)

    def test_uneven_intervals_keep_id_at_two(self):
        old,new = self.compare("uneven_frames",2)
        self.assertEqual(id_count(new),1)
        self.assertEqual(event_count(new),1)

    def test_short_miss_retains_id_but_resets_evidence(self):
        old,new = self.compare("short_detection_loss")
        lost = new[4]["tracks"][0]
        self.assertFalse(lost["observed"])
        self.assertEqual(lost["positive_frames"],0)
        self.assertEqual(lost["support_seconds"],0)
        self.assertEqual(new[5]["tracks"][0]["positive_frames"],1)
        self.assertTrue(new[5]["tracks"][0]["reacquired"])
        self.assertEqual(id_count(new),1)
        self.assertEqual(event_count(new),1)

    def test_long_miss_reappearing_inside_needs_new_entry(self):
        old,new = self.compare("long_detection_loss")
        self.assertEqual(id_count(new),2)
        self.assertFalse(new[-1]["tracks"][0]["ever_entered_roi"])
        self.assertEqual(event_count(new),0)

    def test_depicted_static_high_score_never_alerts(self):
        old,new = self.compare("depicted_static")
        self.assertEqual((event_count(old),event_count(new)),(0,0))

    def test_pass_by_low_score_never_alerts(self):
        old,new = self.compare("pass_by_low_score")
        self.assertEqual((event_count(old),event_count(new)),(0,0))

    def test_one_contact_spike_never_alerts(self):
        old,new = self.compare("pass_by_one_spike")
        self.assertEqual((event_count(old),event_count(new)),(0,0))

    def test_oscillation_is_conservative_not_a_claim_of_physical_truth(self):
        old,new = self.compare("score_oscillation")
        self.assertEqual(event_count(old),1)
        self.assertEqual(event_count(new),0)
        self.assertEqual(max(t["support_seconds"] for row in new for t in row["tracks"]),0)

    def test_fast_path_at_exact_score_threshold(self):
        old,new = self.compare("fast_path")
        self.assertEqual((event_count(old),event_count(new)),(1,1))
        self.assertEqual(new[-1]["tracks"][0]["state_reason"],"fast_contact_confirmed")

    def test_multiple_hands_order_invariant_and_no_entry_transfer(self):
        old,new = self.compare("multiple_hands")
        left,right = set(),set()
        for row in new:
            for track in row["tracks"]:
                if track["observed"]:
                    (left if track["label"]=="left" else right).add(track["track_id"])
                    if track["label"]=="right":
                        self.assertFalse(track["ever_entered_roi"])
        self.assertEqual((len(left),len(right)),(1,1))
        self.assertTrue(left.isdisjoint(right))
        self.assertEqual(event_count(new),1)

    def test_global_assignment_not_greedy(self):
        self.assertEqual(minimum_assignment([[1,2,50],[1.1,9,50]]),[1,0])

class InputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = PipelineV4()
        self.pipeline.step("first",0,[detection(.25)])

    def test_duplicate_frame_does_not_advance_state(self):
        before = copy.deepcopy(self.pipeline.tracker.tracks)
        result = self.pipeline.step("first",1,[detection(.45)])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"],"duplicate_frame")
        self.assertEqual(self.pipeline.tracker.tracks,before)
        self.assertEqual(self.pipeline.last_timestamp,0)

    def test_equal_timestamp_rejected(self):
        self.assertEqual(self.pipeline.step("second",0,[detection(.45)])["reason"],"non_increasing_timestamp")

    def test_decreasing_timestamp_rejected(self):
        self.assertEqual(self.pipeline.step("second",-1,[detection(.45)])["reason"],"non_increasing_timestamp")

    def test_stale_frame_does_not_accumulate(self):
        result = self.pipeline.step("second",1,[detection(.45)],received_timestamp=5)
        self.assertEqual(result["reason"],"stale_frame")
        self.assertEqual(self.pipeline.last_timestamp,0)

    def test_timestamp_nan_and_infinity_rejected(self):
        for value in (float("nan"),float("inf"),True):
            with self.assertRaises(ValueError):
                self.pipeline.step("second",value,[])

    def test_mixed_clock_rejected(self):
        with self.assertRaises(ValueError):
            self.pipeline.step("second",1,[],received_timestamp=.5)

    def test_invalid_detection_rejected_atomically(self):
        with self.assertRaises(ValueError):
            self.pipeline.step("second",.2,[{"box":[.5,.3,.4,.5],"object_contact_score":.6}])
        self.assertEqual(self.pipeline.last_timestamp,0)

    def test_low_hand_confidence_is_not_contact_evidence(self):
        det = detection(.45,.99)
        det["hand_score"] = .69
        result = self.pipeline.step("second",.2,[det])
        self.assertEqual(result["dropped_detection_indices"],[0])
        self.assertFalse(any(t["raw_contact_valid"] for t in result["tracks"]))

    def test_frame_cache_capacity_stops_instead_of_forgetting_duplicates(self):
        p = PipelineV4({"input":{"frame_id_cache_size":2}})
        p.step("a",0,[])
        p.step("b",.1,[])
        self.assertEqual(p.step("c",.2,[])["reason"],"frame_id_capacity_exceeded")
        self.assertEqual(p.step("a",.3,[])["reason"],"duplicate_frame")

    def test_frozen_thresholds_reject_lowering(self):
        with self.assertRaises(ValueError):
            validate_config({"thresholds":{"object_contact":.1}})

    def test_config_rejects_legacy_roi_and_nonfinite(self):
        for config in ({"roi":{"type":"rectangle"}},{"tracking":{"max_idle_seconds":float("nan")}},
                       {"roi":{"normalized":[.1,.1,.9,.9]}},[],{"temporal":{"minimum_frames":6}}):
            with self.assertRaises(ValueError):
                validate_config(config)

class EventAndEntryTests(unittest.TestCase):
    def test_border_jitter_does_not_arm_entry(self):
        p = PipelineV4()
        rows = [p.step(str(i),i*.2,[detection(x,.99)])
                for i,x in enumerate([.39,.41]*10)]
        self.assertEqual(event_count(rows),0)
        self.assertFalse(any(t["ever_entered_roi"] for r in rows for t in r["tracks"]))

    def test_predicted_motion_without_observation_never_creates_entry(self):
        p = PipelineV4()
        p.step("a",0,[detection(.25)])
        p.step("b",.2,[detection(.3)])
        row = p.step("missing",.4,[])
        self.assertEqual(row["events"],[])
        self.assertFalse(row["tracks"][0]["ever_entered_roi"])
        self.assertEqual(row["tracks"][0]["positive_frames"],0)

    def test_ambiguous_crossing_cannot_inherit_entry(self):
        p = PipelineV4()
        p.step("a",0,[detection(.15),detection(.9)])
        p.step("b",.2,[detection(.3),detection(.85)])
        p.step("c",.4,[detection(.45),detection(.7)])
        row = p.step("d",.6,[detection(.57,.99),detection(.57,.99)])
        self.assertEqual(row["events"],[])
        self.assertEqual(row["ambiguous_detection_indices"],[0,1])
        for track in row["tracks"]:
            if track["observed"]:
                self.assertTrue(track["new_track"])
                self.assertFalse(track["ever_entered_roi"])

    def test_camera_disconnect_clears_all_evidence_and_entry(self):
        p = PipelineV4()
        for row in scenarios()["normal_entry_hold"][:5]:
            p.step(**row)
        disconnected = p.disconnect("disconnect",1.0)
        self.assertEqual(disconnected["events"],[])
        self.assertEqual(p.tracker.tracks,{})
        resumed = p.step("resumed",1.2,[detection(.45,.99)])
        self.assertFalse(resumed["tracks"][0]["ever_entered_roi"])
        self.assertEqual(resumed["events"],[])

    def test_missing_after_alert_keeps_episode_without_new_evidence(self):
        p = PipelineV4()
        for frame in scenarios()["normal_entry_hold"][:5]:
            result = p.step(**frame)
        self.assertTrue(result["tracks"][0]["alert_active"])
        result = p.step("miss",1,[])
        self.assertTrue(result["tracks"][0]["alert_active"])
        self.assertEqual(result["tracks"][0]["positive_frames"],0)
        self.assertEqual(result["events"],[])

    def test_current_low_score_never_starts_alert_from_old_history(self):
        p = PipelineV4()
        for row in scenarios()["normal_entry_hold"][:4]:
            p.step(**row)
        result = p.step("low",.8,[detection(.45,.1)])
        self.assertFalse(result["tracks"][0]["raw_contact_valid"])
        self.assertEqual(result["events"],[])

    def test_long_gap_breaks_confirmation_even_if_id_survives(self):
        p = PipelineV4({"tracking":{"max_idle_seconds":3}})
        rows = [p.step(str(i),i*2.5,[detection(.25 if i==0 else .45)]) for i in range(4)]
        self.assertEqual(id_count(rows),1)
        self.assertEqual(event_count(rows),0)
        self.assertEqual(rows[-1]["tracks"][0]["positive_frames"],1)

    def test_fast_pair_too_close_in_time_cannot_force_alert(self):
        p = PipelineV4()
        p.step("a",0,[detection(.25,.99)])
        p.step("b",.1,[detection(.45,.99)])
        row = p.step("c",.11,[detection(.45,.99)])
        self.assertEqual(row["events"],[])

    def test_ema_telemetry_does_not_turn_low_score_into_positive(self):
        p = PipelineV4()
        p.step("a",0,[detection(.25,.99)])
        p.step("b",.2,[detection(.45,.99)])
        row = p.step("c",.4,[detection(.45,.149)])
        self.assertGreater(row["tracks"][0]["ema_score_telemetry_only"],.15)
        self.assertFalse(row["tracks"][0]["raw_contact_valid"])
        self.assertEqual(row["tracks"][0]["history"],[True,False])

    def test_same_episode_resume_never_emits_duplicate_event(self):
        p = PipelineV4()
        rows = [p.step(**r) for r in scenarios()["normal_entry_hold"][:5]]
        # Keep the same visible track alive through cooldown, without exiting ROI.
        for i in range(1,125):
            rows.append(p.step("low"+str(i),.8+i*.5,[detection(.45,.1)]))
        for i in range(1,4):
            rows.append(p.step("again"+str(i),63+i*.2,[detection(.45,.6)]))
        self.assertEqual(event_count(rows),1)
        self.assertTrue(rows[-1]["tracks"][0]["alert_active"])

    def test_confirmed_exit_then_reentry_creates_distinct_episode(self):
        p = PipelineV4({"temporal":{"cooldown_seconds":.1}})
        rows = [p.step(**r) for r in scenarios()["normal_entry_hold"][:5]]
        for i,(time,x) in enumerate([(1,.3),(1.2,.25),(1.6,.25),(1.8,.4),
                                      (2,.45),(2.2,.45),(2.4,.45)]):
            rows.append(p.step("return"+str(i),time,[detection(x)]))
        self.assertEqual(event_count(rows),2)

    def test_polygon_hysteresis_and_entry(self):
        config = {"roi":{"shape":"polygon","points":[[.4,.1],[.8,.1],[.8,.9],[.4,.9]]}}
        p = PipelineV4(config)
        rows = [p.step(**r) for r in scenarios()["normal_entry_hold"][:6]]
        self.assertEqual(event_count(rows),1)

    def test_track_ids_are_not_reused_after_disconnect(self):
        p = PipelineV4()
        a = p.step("a",0,[detection(.25)])["tracks"][0]["track_id"]
        p.disconnect("d",.2)
        b = p.step("b",.4,[detection(.25)])["tracks"][0]["track_id"]
        self.assertGreater(b,a)

    def test_new_session_for_changed_roi_does_not_inherit_evidence(self):
        p = PipelineV4()
        for r in scenarios()["normal_entry_hold"][:5]:
            p.step(**r)
        changed = PipelineV4({"roi":{"coordinates":[.3,.1,.9,.9]}})
        row = changed.step("new",1,[detection(.45,.99)])
        self.assertEqual(row["events"],[])
        self.assertFalse(row["tracks"][0]["ever_entered_roi"])

if __name__=="__main__":
    unittest.main()
