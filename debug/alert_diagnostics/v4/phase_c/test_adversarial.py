"""Characterization PASS documents observations; it does NOT declare camera quality PASS."""
import copy
import itertools
import random
import unittest
from ..pipeline_v4 import PipelineV4,validate_config
from ..tracking_v4 import minimum_assignment
from ..scenarios import detection,scenarios,frame
from ..compare_v3_v4 import evaluate,event_count,id_count
from .audit_scenarios import cases,identity_report

def snapshot(p):
    return copy.deepcopy({"tracker":vars(p.tracker),"entries":{k:vars(v) for k,v in p.entries.items()},
                          "contacts":{k:vars(v) for k,v in p.contacts.items()},
                          "timestamp":p.last_timestamp,"seen":p.seen_ids,"order":list(p.id_order)})

class AdversarialCharacterization(unittest.TestCase):
    def test_30fps_moderate_score_v4_never_confirms(self):
        old,new = evaluate(cases()["high_fps_30_moderate"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,0))
        self.assertLess(max(t["support_seconds"] for r in new for t in r["tracks"]),.4)

    def test_20fps_moderate_score_same_recall_risk(self):
        old,new = evaluate(cases()["high_fps_20_moderate"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,0))

    def test_slow_camera_motion_creates_entry_and_v4_event(self):
        old,new = evaluate(cases()["camera_slow_pan_printed_hand"],2)
        self.assertEqual((event_count(old),event_count(new)),(0,1))

    def test_fast_camera_jolt_is_shared_false_positive_risk(self):
        old,new = evaluate(cases()["camera_fast_jolt_printed_hand"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,1))

    def test_overlap_035_passes_contact_gate_but_cannot_enter_v4(self):
        old,new = evaluate(cases()["thin_border_overlap_035"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,0))
        self.assertGreater(new[-1]["tracks"][0]["roi_overlap"],.3)
        self.assertFalse(new[-1]["tracks"][0]["ever_entered_roi"])

    def test_continuous_missing_resets_support_and_cannot_alert(self):
        old,new = evaluate(cases()["repeated_detection_missing"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,0))
        for row in new:
            for track in row["tracks"]:
                if not track["observed"]:
                    self.assertEqual(track["positive_frames"],0)
                    self.assertEqual(track["support_seconds"],0)

    def test_strong_score_oscillation_could_also_be_true_contact(self):
        old,new = evaluate(cases()["three_five_strong_oscillation"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,0))

    def test_two_bouts_same_roi_are_suppressed_by_episode_deduplication(self):
        old,new = evaluate(cases()["two_contact_bouts_same_roi"],2)
        self.assertEqual((event_count(old),event_count(new)),(2,1))

    def test_crossing_can_transfer_existing_id_to_other_actor(self):
        inputs = cases()["hands_cross_offset_0.0"]
        old,new = evaluate(inputs,2)
        self.assertEqual(len(identity_report(inputs,new)["track_owner_transfers"]),2)
        self.assertEqual(id_count(new),2)  # Counting IDs alone hides the swaps.

    def test_near_crossing_causes_fragmentation_instead_of_transfer(self):
        inputs = cases()["hands_cross_offset_0.01"]
        old,new = evaluate(inputs,2)
        self.assertGreater(len(identity_report(inputs,new)["actor_id_changes"]),0)
        self.assertGreater(id_count(new),2)

    def test_separated_crossing_keeps_identity(self):
        inputs = cases()["hands_cross_offset_0.03"]
        old,new = evaluate(inputs,2)
        self.assertEqual(identity_report(inputs,new)["actor_id_changes"],[])

    def test_detection_permutation_preserves_event_and_identity_counts(self):
        inputs = cases()["hands_cross_offset_0.03"]
        reversed_inputs = copy.deepcopy(inputs)
        for row in reversed_inputs:
            row["detections"].reverse()
        unused,first = evaluate(inputs,2)
        unused,second = evaluate(reversed_inputs,2)
        self.assertEqual(event_count(first),event_count(second))
        self.assertEqual(identity_report(inputs,first)["actor_id_changes"],
                         identity_report(reversed_inputs,second)["actor_id_changes"])

    def test_assignment_against_brute_force_seeded_matrices(self):
        rng = random.Random(20261017)
        for n in range(1,5):
            for trial in range(15):
                matrix = [[rng.randrange(0,31)/10.0 for _ in range(n+1)] for _ in range(n)]
                chosen = minimum_assignment(matrix)
                optimum = min(sum(matrix[i][j] for i,j in enumerate(columns))
                              for columns in itertools.permutations(range(n+1),n))
                self.assertEqual(len(set(chosen)),n)
                self.assertAlmostEqual(sum(matrix[i][j] for i,j in enumerate(chosen)),optimum)

    def test_rejected_frames_preserve_entire_state_after_alert(self):
        for kind in ("duplicate","equal","old","stale"):
            p = PipelineV4()
            for row in scenarios()["normal_entry_hold"][:5]:
                p.step(**row)
            before = snapshot(p)
            if kind=="duplicate":result=p.step("4",1,[])
            elif kind=="equal":result=p.step("next",.8,[])
            elif kind=="old":result=p.step("next",.7,[])
            else:result=p.step("next",1,[],received_timestamp=4.001)
            self.assertFalse(result["accepted"])
            self.assertEqual(snapshot(p),before)

    def test_invalid_timestamps_preserve_entire_state(self):
        for value in (None,True,"nan","inf",-float("inf")):
            p = PipelineV4();p.step("a",0,[detection(.25)])
            before = snapshot(p)
            with self.assertRaises(ValueError):p.step("b",value,[detection(.45)])
            self.assertEqual(snapshot(p),before)

    def test_max_age_exact_boundary_and_just_over(self):
        p = PipelineV4()
        self.assertTrue(p.step("a",1,[],received_timestamp=4)["accepted"])
        before = snapshot(p)
        self.assertEqual(p.step("b",2,[],received_timestamp=5.00001)["reason"],"stale_frame")
        self.assertEqual(snapshot(p),before)

    def test_without_receive_time_age_cannot_be_known(self):
        p = PipelineV4()
        self.assertTrue(p.step("old_file",0,[detection(.5)])["accepted"])

    def test_timeout_boundary_not_equal_to_temporal_support(self):
        p = PipelineV4({"tracking":{"max_idle_seconds":2}})
        first = p.step("a",0,[detection(.25)])
        exact = p.step("b",2,[detection(.45)])
        self.assertEqual(first["tracks"][0]["track_id"],exact["tracks"][0]["track_id"])
        later = p.step("c",4.00001,[detection(.45)])
        self.assertTrue(later["tracks"][0]["new_track"])
        self.assertFalse(later["tracks"][0]["ever_entered_roi"])

    def test_long_no_hand_sequence_never_generates_evidence(self):
        p=PipelineV4()
        for i in range(100):
            result=p.step(str(i),i*.2,[])
            self.assertEqual(result["events"],[])
            self.assertEqual(result["tracks"],[])

    def test_new_roi_session_does_not_reuse_entry_for_expanded_roi(self):
        for coordinates in ([.1,.1,.9,.9],[.45,.2,.7,.8]):
            p=PipelineV4({"roi":{"coordinates":coordinates}})
            rows=[p.step(str(i),i*.2,[detection(.55,.99)]) for i in range(10)]
            self.assertEqual(event_count(rows),0)

    def test_in_place_roi_mutation_is_not_detected(self):
        p=PipelineV4()
        for row in scenarios()["normal_entry_hold"][:5]:p.step(**row)
        p.config["roi"]["coordinates"]=[.3,.1,.9,.9]
        result=p.step("changed",1,[detection(.45,.99)])
        self.assertTrue(result["tracks"][0]["ever_entered_roi"])
        self.assertTrue(result["tracks"][0]["alert_active"])
        # Unsupported use per README; records lack of a defensive API guard.

    def test_cache_full_blocks_disconnect_current_behavior(self):
        p=PipelineV4({"input":{"frame_id_cache_size":5}})
        for row in scenarios()["normal_entry_hold"][:5]:p.step(**row)
        result=p.disconnect("offline",1)
        self.assertFalse(result["accepted"])
        self.assertTrue(p.tracker.tracks)
        self.assertTrue(any(t.active for t in p.contacts.values()))

    def test_duplicate_disconnect_after_real_disconnect_adds_no_evidence(self):
        p=PipelineV4();p.step("a",0,[detection(.25)])
        self.assertTrue(p.disconnect("off",.2)["accepted"])
        before=snapshot(p)
        self.assertFalse(p.disconnect("off",.4)["accepted"])
        self.assertEqual(snapshot(p),before)

    def test_already_inside_real_and_depicted_inputs_are_indistinguishable(self):
        inputs=cases()["depicted_static"]
        unused,real_hypothesis=evaluate(inputs,2)
        unused,printed_hypothesis=evaluate(copy.deepcopy(inputs),2)
        self.assertEqual(real_hypothesis,printed_hypothesis)
        self.assertEqual(event_count(real_hypothesis),0)

class HighFpsCharacterization(unittest.TestCase):
    def test_30fps_fast_scores_also_cannot_confirm(self):
        old,new=evaluate(cases()["high_fps_30_fast"],2)
        self.assertEqual((event_count(old),event_count(new)),(1,0))

    def test_sensitivity_changes_when_only_frame_rate_changes(self):
        from ..scenarios import single
        observed=[]
        for fps,score in ((10,.6),(20,.6),(20,.99),(30,.99)):
            frames=single([(0,.25,score)]+[((i+1)/float(fps),.45,score) for i in range(fps*2)])
            old,new=evaluate(frames,2)
            observed.append((event_count(old),event_count(new)))
        self.assertEqual(observed,[(1,1),(1,0),(1,1),(1,0)])
