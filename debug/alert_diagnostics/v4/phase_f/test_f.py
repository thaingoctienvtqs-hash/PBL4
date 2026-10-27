"""Positive recovery, negative association and an explicit unresolved identity quality gate."""
import copy
import json
import types
import unittest
from .pipeline_f import OfflineF
from .compare_f import replay,evaluate_truth,compare
from .cases_f import cases_f
from ..phase_e.controlled_cases import controlled_cases,exported,control,stability,settings,SOURCE
from ..phase_e.replay import replay_lines
from ..scenarios import scenarios,frame,detection

def get(name):return copy.deepcopy(next(c for c in cases_f() if c["name"]==name))
def event_count(logs):return sum(len(r["events"]) for r in logs)

class RecoveryGates(unittest.TestCase):
    def test_original_missing_frame_gate(self):
        logs,p,unused=replay(get("explicit_missing_frame"))
        self.assertEqual(event_count(logs),1)
        self.assertEqual([t["track_id"] for t in logs[-1]["tracks"] if t["observed"]],[0])
        self.assertEqual(logs[-1]["tracks"][0]["entry_episode"],1)
    def test_original_frame_error_gate(self):
        logs,p,unused=replay(get("explicit_frame_error"))
        self.assertEqual(event_count(logs),1)
        self.assertEqual(logs[-1]["tracks"][0]["track_id"],0)
    def test_no_alert_until_three_fresh_recovery_observations(self):
        logs,p,unused=replay(get("explicit_missing_frame"))
        for row in logs[3:6]:
            self.assertEqual(row["events"],[])
            self.assertFalse(row["used_for_confirmation"])
            for t in row["tracks"]:self.assertEqual(t["positive_frames"],0)
        track=logs[-1]["tracks"][0]
        self.assertEqual(track["positive_frames"],3)
        self.assertGreaterEqual(track["support_seconds"]+1e-9,.4)
        self.assertEqual(len(set(track["recovery_evidence_frame_ids"])),3)
        self.assertEqual(track["recovery_evidence_frame_ids"],["after0","after1","after2"])
    def test_roi_entry_is_quarantined_not_committed_during_probation(self):
        logs,p,unused=replay(get("explicit_missing_frame"))
        for r in logs[4:6]:
            self.assertFalse(r["tracks"][0]["ever_entered_roi"])
            self.assertTrue(r["tracks"][0]["track_id_is_tentative"])
        self.assertTrue(logs[-1]["tracks"][0]["ever_entered_roi"])
    def test_multiple_missing_frames_can_recover(self):
        logs,p,unused=replay(get("multiple_missing"))
        self.assertEqual(event_count(logs),1)
        self.assertEqual(logs[-1]["tracks"][0]["track_id"],0)
        self.assertEqual(logs[-1]["tracks"][0]["positive_frames"],3)
    def test_small_speed_direction_change(self):
        logs,p,unused=replay(get("speed_direction_change"))
        self.assertEqual(event_count(logs),1)
        self.assertEqual(evaluate_truth(get("speed_direction_change"),logs)["wrongly_shared_ids"],0)
    def test_excessive_motion_abstains_not_distance_gate_inflation(self):
        logs,p,unused=replay(get("unsupported_large_motion"))
        self.assertEqual(event_count(logs),0)
        self.assertEqual(p.pipelines[SOURCE].config["tracking"]["reacquire_distance"],.1)
        self.assertEqual(p.pipelines[SOURCE].tracker.config["reacquire_distance"],.1)
    def test_default_strict_mode_does_not_claim_bbox_identity(self):
        logs,p,unused=replay(get("explicit_missing_frame"),geometry=False)
        self.assertEqual(event_count(logs),0)
    def test_geometry_mode_keeps_thresholds_frozen(self):
        logs,p,unused=replay(get("explicit_missing_frame"))
        self.assertEqual(p.pipelines[SOURCE].config["thresholds"],
                         {"hand_score":.7,"object_contact":.15,"fast_score":.85,"minimum_overlap":.3})

class NegativeAssociationTests(unittest.TestCase):
    def test_other_hand_near_velocity_prediction_does_not_inherit_entry(self):
        c=get("replacement_near_prediction");logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),0)
        self.assertEqual(evaluate_truth(c,logs)["wrongly_shared_ids"],0)
    def test_bbox_scale_change_does_not_inherit_entry(self):
        c=get("replacement_scale_change");logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),0)
        self.assertEqual(evaluate_truth(c,logs)["wrongly_shared_ids"],0)
    def test_multiple_recovery_candidates_rejected(self):
        c=get("two_candidates_after_gap");logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),0)
        self.assertTrue(any("multiple_recovery_candidates" in str(r.get("recovery_audit")) for r in logs))
    def test_crossing_after_missing_no_owner_transfer(self):
        c=get("crossing_after_missing");logs,p,unused=replay(c)
        self.assertEqual(evaluate_truth(c,logs)["identity"]["track_owner_transfers"],[])
    def test_permissive_recovery_fails_negative_control(self):
        c=get("replacement_near_prediction")
        model=OfflineF(c["settings"],True,True)
        tracker=model.pipelines[SOURCE].tracker
        tracker.config["reacquire_distance"]=.3
        def loose(self,anchor,current,det,now):
            return {"model":"stationary","anchor_iou":0,"uncertainty_radius":.3,
                    "gap_since_confirmed":now-anchor["last_seen"]}
        tracker.candidate=types.MethodType(loose,tracker)
        logs=[model.process(r) for r in c["records"]]
        self.assertGreater(evaluate_truth(c,logs)["controlled_FP"],0)
        good,unused,unused_config=replay(c)
        self.assertEqual(evaluate_truth(c,good)["controlled_FP"],0)
    def test_strict_mode_blocks_indistinguishable_replacement(self):
        c=get("replacement_indistinguishable");logs,p,unused=replay(c,False)
        self.assertEqual(evaluate_truth(c,logs)["controlled_FP"],0)
        self.assertEqual(evaluate_truth(c,logs)["wrongly_shared_ids"],0)
    def test_labels_are_oracle_only_never_matching_inputs(self):
        c=get("explicit_missing_frame");a,p,unused=replay(c)
        for r in c["records"]:r["oracle"]={"actors":["arbitrary"]}
        b,p,unused=replay(c)
        self.assertNotEqual(a[0]["input_line_sha256"],b[0]["input_line_sha256"])
        for row in a+b:row.pop("input_line_sha256")
        self.assertEqual(a,b)

class EvidenceSafetyTests(unittest.TestCase):
    def test_recovery_low_object_contact_no_alert(self):
        c=get("recovered_low_contact_score");logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),0)
        self.assertEqual(logs[-1]["tracks"][0]["track_id"],0)
        self.assertEqual(logs[-1]["tracks"][0]["positive_frames"],0)
    def test_current_invalid_score_no_retrospective_alert(self):
        logs,p,unused=replay(get("recover_current_score_invalid"))
        self.assertEqual(event_count(logs),0)
        self.assertFalse(logs[-1]["tracks"][0]["alert_active"])
    def test_timeout_never_extended_by_probation(self):
        c=get("multiple_missing")
        logs,p,unused=replay(c,True,timeout=1)
        self.assertEqual(event_count(logs),0)
        self.assertNotEqual(logs[-1]["tracks"][0]["track_id"],0)
    def test_after_timeout_inside_hand_needs_entry(self):
        logs,p,unused=replay(get("timeout_expired"))
        self.assertEqual(event_count(logs),0)
        self.assertTrue(all(not t["ever_entered_roi"] for t in logs[-1]["tracks"]))
    def test_compare_timeouts_one_two_three(self):
        values=[]
        for timeout in (1,2,3):
            logs,p,unused=replay(get("multiple_missing"),True,timeout)
            values.append(event_count(logs))
        self.assertEqual(values,[0,1,1])
    def test_camera_shake_clears_recovery(self):
        logs,p,unused=replay(get("camera_shake"))
        self.assertEqual(event_count(logs),0)
        self.assertTrue(any(r["state"]=="CAMERA_MOVING" for r in logs))
    def test_camera_unknown_clears_recovery(self):
        logs,p,unused=replay(get("camera_unknown"))
        self.assertEqual(event_count(logs),0)
        self.assertTrue(any(r["state"]=="CAMERA_UNVERIFIED" for r in logs))
    def test_printed_static_never_arms_entry(self):
        logs,p,unused=replay(get("printed_static"))
        self.assertEqual(event_count(logs),0)
    def test_duplicate_and_old_timestamp_never_count(self):
        logs,p,unused=replay(get("duplicate_and_bad_timestamp"))
        self.assertEqual(event_count(logs),1)
        rejected=[r for r in logs if not r["accepted"]]
        self.assertEqual(len(rejected),2)
        self.assertTrue(all(not r["used_for_confirmation"] for r in rejected))
        self.assertEqual(logs[-1]["tracks"][0]["positive_frames"],3)
    def test_invalid_nan_timestamp_clears_buffer(self):
        c=get("explicit_missing_frame");model=OfflineF(c["settings"],True,True)
        for r in c["records"][:5]:model.process(r)
        r=copy.deepcopy(c["records"][5]);r["timestamp"]=float("nan")
        self.assertFalse(model.process(r)["accepted"])
        self.assertEqual(model.pipelines[SOURCE].tracker.pending,{})
        self.assertEqual(model.pipelines[SOURCE].contacts,{})
    def test_disconnect_before_dedup_clears_probation(self):
        c=get("explicit_missing_frame");model=OfflineF(c["settings"],True,True)
        for r in c["records"][:5]:model.process(r)
        result=model.process(control("disconnect",.8,frame_id=c["records"][4]["frame_id"]))
        self.assertEqual(result["state"],"CAMERA_OFFLINE")
        self.assertEqual(model.pipelines[SOURCE].tracker.pending,{})
        self.assertEqual(model.pipelines[SOURCE].contacts,{})
    def test_missing_during_probation_discards_unconfirmed_samples(self):
        c=get("explicit_missing_frame")
        r=control("missing",.9,frame_id="second_miss",received_timestamp=.9);r["stability"]=stability(r)
        c["records"].insert(5,r)
        logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),0)
        self.assertEqual(logs[-1]["tracks"][0]["state"],"RECOVERY_PENDING")
    def test_no_duplicate_event_after_recovering_already_alerted_track(self):
        c=get("explicit_missing_frame")
        c["records"]=[exported(r) for r in scenarios()["normal_entry_hold"][:5]]
        miss=control("missing",1,frame_id="missing",received_timestamp=1);miss["stability"]=stability(miss)
        c["records"].append(miss)
        c["records"].extend(exported(frame("back"+str(i),1.2+i*.2,[detection(.45)])) for i in range(5))
        logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),1)
        self.assertTrue(logs[-1]["tracks"][0]["alert_active"])

class ContinuousRegressionTests(unittest.TestCase):
    pass

def case_test(c):
    def test(self):
        logs,p,unused=replay(c)
        self.assertEqual(event_count(logs),c["expected_logic_events"])
    return test

# Frozen E desired recovery cases are separately required above; no assertion is weakened.
for c in controlled_cases():
    if c["name"] not in ("explicit_missing_frame","explicit_frame_error"):
        setattr(ContinuousRegressionTests,"test_"+c["name"].replace(".","_"),case_test(c))

class InformationLimitGate(unittest.TestCase):
    def test_geometry_must_not_alert_for_indistinguishable_new_hand(self):
        c=get("replacement_indistinguishable");logs,p,unused=replay(c,True)
        self.assertEqual(evaluate_truth(c,logs)["controlled_FP"],0,
                         "BBox/score-only recovery cannot distinguish this replacement; keep FAIL visible")

if __name__=="__main__":unittest.main()
