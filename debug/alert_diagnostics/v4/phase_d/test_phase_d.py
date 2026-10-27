"""Controlled logic contracts, not AI accuracy or real image motion validation."""
import copy
import unittest
from ..scenarios import scenarios,single,detection,frame
from ..compare_v3_v4 import evaluate,event_count,id_count
from ..phase_c.audit_scenarios import cases,identity_report
from ..pipeline_v4 import DEFAULTS
from .fixtures import pipeline,feed,background,REFERENCE,evaluate_d
from .pipeline_d import PipelineD
from .camera_stability import BackgroundStability
from .temporal_d import TemporalD

def fps_frames(fps,score=.6,duration=3):
    return single([(0,.25,score)]+[(i/float(fps),.45,score) for i in range(1,int(fps*duration)+1)])

class FiveQualityGatesD(unittest.TestCase):
    def test_moderate_contact_30fps(self):
        rows=evaluate_d(cases()["high_fps_30_moderate"],background_mode="controlled_stable")
        self.assertEqual(event_count(rows),1)
        self.assertGreater(rows[-1]["tracks"][0]["time_evidence_count"],5)
    def test_fast_contact_30fps(self):
        rows=evaluate_d(cases()["high_fps_30_fast"],background_mode="controlled_stable")
        self.assertEqual(event_count(rows),1)
        first=next(r for r in rows if r["events"])
        self.assertEqual(first["events"][0]["reason"],"fast_contact_confirmed")
        self.assertGreaterEqual(first["tracks"][0]["fast_span_seconds"]+1e-9,.2)
    def test_camera_pan_unknown_abstains(self):
        rows=evaluate_d(cases()["camera_slow_pan_printed_hand"])
        self.assertEqual(event_count(rows),0)
        self.assertTrue(all(not r["decision_available"] for r in rows))
    def test_crossing_does_not_transfer_identity(self):
        inputs=cases()["hands_cross_offset_0.0"]
        rows=evaluate_d(inputs,background_mode="controlled_stable")
        self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[])
        self.assertTrue(any(r["uncertain_track_ids"] for r in rows))
        self.assertGreaterEqual(id_count(rows),2)
    def test_disconnect_full_cache_clears_active(self):
        p=pipeline({"input":{"frame_id_cache_size":5}})
        for r in scenarios()["normal_entry_hold"][:5]:result=feed(p,r)
        self.assertEqual(result["state"],"ALERT")
        off=p.disconnect("off",1)
        self.assertEqual(off["state"],"CAMERA_OFFLINE")
        self.assertEqual(p.tracker.tracks,{})
        self.assertEqual(p.contacts,{})

class TimeEvidenceTests(unittest.TestCase):
    def test_moderate_all_fps(self):
        for fps in (1,5,10,15,30):
            with self.subTest(fps=fps):
                rows=evaluate_d(fps_frames(fps),background_mode="controlled_stable")
                self.assertEqual(event_count(rows),1)
                self.assertTrue(rows[-1]["tracks"][0]["alert_active"])
                first=next(r for r in rows if r["events"])
                self.assertGreaterEqual(first["tracks"][0]["positive_frames"],3)
                self.assertGreaterEqual(first["tracks"][0]["support_seconds"]+1e-9,.4)
    def test_two_seconds_at_one_fps_cannot_override_three_votes(self):
        rows=evaluate_d(fps_frames(1,.6,2),background_mode="controlled_stable")
        self.assertEqual(event_count(rows),0)
        self.assertEqual(rows[-1]["tracks"][0]["positive_frames"],2)
    def test_fast_all_fps(self):
        for fps in (1,5,10,15,30):
            with self.subTest(fps=fps):
                rows=evaluate_d(fps_frames(fps,.85),background_mode="controlled_stable")
                self.assertEqual(event_count(rows),1)
    def test_short_contact_less_than_fast_span_no_alert(self):
        for fps in (1,5,10,15,30):
            frames=single([(0,.25,.99)]+[(1+i/float(fps),.45,.99) for i in range(int(.15*fps)+1)])
            rows=evaluate_d(frames,background_mode="controlled_stable")
            self.assertEqual(event_count(rows),0)
    def test_short_moderate_contact_does_not_meet_duration(self):
        rows=evaluate_d(fps_frames(30,.6,.3),background_mode="controlled_stable")
        self.assertEqual(event_count(rows),0)
    def test_fast_short_but_sufficient_contact_confirms(self):
        rows=evaluate_d(fps_frames(30,.85,.3),background_mode="controlled_stable")
        self.assertEqual(event_count(rows),1)
    def test_fast_pair_too_close_does_not_confirm(self):
        rows=evaluate_d(single([(0,.25,.99),(.1,.45,.99),(.11,.45,.99)]),background_mode="controlled_stable")
        self.assertEqual(event_count(rows),0)
    def test_deque_and_clock_independent_at_high_fps(self):
        rows=evaluate_d(fps_frames(30),background_mode="controlled_stable")
        t=next(r for r in rows if r["events"])["tracks"][0]
        self.assertEqual(len(t["history"]),5)
        self.assertGreater(t["time_evidence_count"],5)
    def test_duplicates_and_invalid_timestamps_do_not_add_evidence(self):
        p=pipeline()
        for r in single([(0,.25,.6),(.1,.45,.6)]):feed(p,r)
        before=copy.deepcopy(p.contacts[next(iter(p.contacts))].__dict__)
        for r in (frame(1,.2,[detection(.45)]),frame(2,.1,[detection(.45)]),frame(3,.05,[detection(.45)])):
            self.assertFalse(feed(p,r)["accepted"])
        for bad in (float("nan"),float("inf"),True):
            with self.assertRaises(ValueError):feed(p,frame("bad",bad,[]))
        self.assertEqual(p.contacts[next(iter(p.contacts))].__dict__,before)
    def test_stale_frame_never_increments(self):
        p=pipeline();feed(p,frame("a",0,[detection(.25)]))
        r=frame("b",1,[detection(.45)]);r["received_timestamp"]=5
        self.assertEqual(feed(p,r)["reason"],"stale_frame")
        self.assertEqual(p.last_timestamp,0)
    def test_missing_resets_support_and_votes(self):
        p=pipeline()
        for r in single([(0,.25,.6),(.1,.45,.6),(.2,.45,.6)]):feed(p,r)
        missing=feed(p,frame("miss",.3,[]))["tracks"][0]
        self.assertEqual((missing["positive_frames"],missing["support_seconds"]),(0,0))
        back=feed(p,frame("back",.4,[detection(.45)]))["tracks"][0]
        self.assertEqual((back["positive_frames"],back["support_seconds"]),(1,0))
    def test_long_gap_retains_id_but_not_support(self):
        p=pipeline({"tracking":{"max_idle_seconds":3}})
        rows=[feed(p,r) for r in single([(0,.25,.6),(.1,.45,.6),(.2,.45,.6),(2.7,.45,.6)])]
        self.assertEqual(id_count(rows),1)
        self.assertEqual(event_count(rows),0)
        self.assertEqual(rows[-1]["tracks"][0]["positive_frames"],1)
    def test_expired_evidence_is_not_used(self):
        c=dict(DEFAULTS["temporal"],max_evidence_age_seconds=.25)
        t=TemporalD(c,DEFAULTS["thresholds"]);entry={"entered":True,"episode":1}
        for now in (0,.1,.2):
            t.update(now,detection(.45),1,entry)
        result=t.update(.6,detection(.45),1,entry)
        self.assertEqual((result["positive_frames"],result["support_seconds"]),(1,0))
        self.assertFalse(result["event_started"])
    def test_time_evidence_resource_guard_is_conservative(self):
        t=TemporalD(DEFAULTS["temporal"],DEFAULTS["thresholds"])
        for i in range(2050):r=t.update(i*.00001,detection(.45),1,{"entered":True,"episode":1})
        self.assertFalse(r["event_started"]);self.assertLessEqual(len(t.evidence),2048)
    def test_direct_temporal_non_increasing_rejected(self):
        t=TemporalD(DEFAULTS["temporal"],DEFAULTS["thresholds"])
        t.update(1,detection(.45),1,{"entered":True,"episode":1})
        with self.assertRaises(ValueError):t.update(1,detection(.45),1,{"entered":True,"episode":1})
        self.assertEqual(len(t.samples),1)
    def test_missing_after_alert_no_new_event_or_support(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:5]:feed(p,r)
        r=feed(p,frame("missing",1,[]))["tracks"][0]
        self.assertEqual((r["positive_frames"],r["support_seconds"]),(0,0))
        self.assertTrue(r["alert_active"])
    def test_score_thresholds_unchanged(self):
        self.assertEqual(pipeline().config["thresholds"],DEFAULTS["thresholds"])
        with self.assertRaises(ValueError):pipeline({"thresholds":{"object_contact":.1}})
    def test_old_support_cannot_confirm_current_low_score(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:4]:feed(p,r)
        r=feed(p,frame("low",.8,[detection(.45,.149)]))
        self.assertEqual(r["events"],[])
        self.assertFalse(r["tracks"][0]["raw_contact_valid"])

class CameraControlTests(unittest.TestCase):
    def test_disconnect_empty_cache(self):
        p=pipeline();r=p.disconnect("off",0)
        self.assertEqual(r["state"],"CAMERA_OFFLINE");self.assertFalse(r["decision_available"])
    def test_disconnect_after_alert(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:5]:feed(p,r)
        self.assertTrue(p.contacts[next(iter(p.contacts))].active)
        p.disconnect("off",1)
        self.assertEqual((p.entries,p.contacts,p.tracker.tracks),({},{},{}))
    def test_disconnect_duplicate_timestamp_bad_timestamp_never_blocked(self):
        for timestamp in (0,-1,float("nan"),None):
            p=pipeline();feed(p,frame("a",0,[detection(.25)]))
            r=p.disconnect("a",timestamp)
            self.assertTrue(r["accepted"]);self.assertEqual(p.tracker.tracks,{})
            self.assertFalse(p.online)
    def test_offline_data_requires_explicit_reconnect(self):
        p=pipeline();p.disconnect("d",0)
        self.assertEqual(feed(p,frame("a",1,[detection(.45)]))["state"],"CAMERA_OFFLINE")
    def test_reconnect_new_session_needs_new_entry(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:5]:feed(p,r)
        old_id=next(iter(p.tracker.tracks))
        p.disconnect("off",1);p.reconnect("session1",REFERENCE)
        rows=[feed(p,frame(i,i*.2,[detection(.45,.99)])) for i in range(10)]
        self.assertEqual(event_count(rows),0);self.assertFalse(rows[-1]["tracks"][0]["ever_entered_roi"])
        self.assertGreater(rows[-1]["tracks"][0]["track_id"],old_id)
    def test_reconnect_new_valid_episode_can_alert(self):
        p=pipeline();p.disconnect();p.reconnect("session1",REFERENCE)
        rows=[feed(p,r) for r in scenarios()["normal_entry_hold"]]
        self.assertEqual(event_count(rows),1)
        self.assertTrue(rows[-1]["events"]==[])
        self.assertTrue(next(r for r in rows if r["events"])["events"][0]["event_key"].startswith("session1_"))
    def test_old_session_rejected_after_reconnect(self):
        p=pipeline();p.disconnect();p.reconnect("session1",REFERENCE)
        r=p.step("old",0,[],source_session="session0")
        self.assertEqual(r["reason"],"wrong_source_session")
    def test_wrong_control_session_does_not_clear_live_session(self):
        p=pipeline();feed(p,frame(0,0,[detection(.25)]))
        self.assertFalse(p.disconnect("old",1,source_session="old")["accepted"])
        self.assertTrue(p.tracker.tracks)
    def test_session_cannot_be_reused(self):
        p=pipeline()
        with self.assertRaises(ValueError):p.reconnect("session0",REFERENCE)
    def test_reconnect_resets_full_cache_but_not_track_counter(self):
        p=pipeline({"input":{"frame_id_cache_size":1}})
        a=feed(p,frame("a",0,[detection(.25)]))["tracks"][0]["track_id"]
        p.disconnect("a",0);p.reconnect("new",REFERENCE)
        b=feed(p,frame("a",0,[detection(.25)]))["tracks"][0]["track_id"]
        self.assertGreater(b,a)
    def test_unknown_background_clears_active_alert(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:5]:feed(p,r)
        r=p.step("unknown",1,[detection(.45,.99)])
        self.assertEqual(r["state"],"CAMERA_UNVERIFIED")
        self.assertEqual((p.contacts,p.tracker.tracks),({},{}))
    def test_camera_move_clears_and_requires_fresh_entry(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:5]:feed(p,r)
        r=feed(p,frame("pan",1,[detection(.45,.99)]),dx=.01)
        self.assertEqual(r["state"],"CAMERA_MOVING")
        r=feed(p,frame("back",1.2,[detection(.45,.99)]))
        self.assertFalse(r["tracks"][0]["ever_entered_roi"])

class StabilityContractTests(unittest.TestCase):
    def setUp(self):
        self.provider=BackgroundStability(REFERENCE,test_mode=True)
        self.context=background("a",0)
    def assess(self,context):
        return self.provider.assess("a",0,"session0",context)
    def test_spatial_background_reference_is_stable(self):
        self.assertTrue(self.assess(self.context)["stable"])
    def test_no_image_evidence_defaults_to_unknown(self):
        p=PipelineD(calibration_id=REFERENCE)
        r=p.step("a",0,[detection(.25)],source_session="session0")
        self.assertEqual(r["state"],"CAMERA_UNVERIFIED")
        self.assertFalse(r["decision_available"])
    def test_synthetic_provider_rejected_outside_test_mode(self):
        p=PipelineD(calibration_id=REFERENCE)
        r=p.step("a",0,[],camera_context=self.context,source_session="session0")
        self.assertEqual(r["camera_stability"]["reason"],"synthetic_evidence_not_allowed")
    def test_real_provider_requires_explicit_enable(self):
        self.context["provider"]="background_correspondences"
        self.assertEqual(self.assess(self.context)["status"],"UNKNOWN")
    def test_stale_or_wrong_context_is_unknown(self):
        for key,value in (("timestamp",1),("frame_id","b"),("source_session","bad"),("reference_id","old")):
            c=copy.deepcopy(self.context);c[key]=value
            self.assertEqual(self.assess(c)["status"],"UNKNOWN")
    def test_bad_match_and_poor_coverage_unknown(self):
        for matches in ([],[[.1,.1,.1,.1,0]]*19,[[.5,.5,.5,.5,0]]*30,[[0,1]]*30):
            c=dict(self.context,matches=matches)
            self.assertEqual(self.assess(c)["status"],"UNKNOWN")
    def test_reference_drift_is_moving(self):
        self.assertEqual(self.assess(background("a",0,dx=.01))["status"],"MOVING")
    def test_cumulative_pan_not_reset_by_per_frame_small_shift(self):
        values=[self.assess(background("a",0,dx=i*.001)) for i in range(10)]
        self.assertEqual(values[-1]["status"],"MOVING")
    def test_jitter_without_trusted_background_never_arms_entry(self):
        rows=evaluate_d(cases()["camera_fast_jolt_printed_hand"])
        self.assertEqual(event_count(rows),0)
        self.assertTrue(all(r["state"]=="CAMERA_UNVERIFIED" for r in rows))
    def test_inconsistent_geometry_is_not_stable(self):
        c=copy.deepcopy(self.context)
        for i,m in enumerate(c["matches"]):m[2]+=.01 if i%2 else -.01
        self.assertEqual(self.assess(c)["status"],"MOVING")
    def test_false_stability_signal_cannot_be_treated_as_image_proof(self):
        # Exposes the boundary: a fabricated static background bypasses any geometry-only guard.
        rows=evaluate_d(cases()["camera_slow_pan_printed_hand"],background_mode="controlled_stable")
        self.assertEqual(event_count(rows),1)
        self.assertTrue(all(r["camera_stability"]["image_extraction_validated"] is False for r in rows))
    def test_production_source_session_required(self):
        self.assertEqual(PipelineD().step("a",0,[])["reason"],"missing_source_session")

class IdentityAndRegressionTests(unittest.TestCase):
    def test_crossings_all_offsets_no_owner_transfer(self):
        for offset in (0.0,.01,.03):
            inputs=cases()["hands_cross_offset_"+str(offset)]
            rows=evaluate_d(inputs,background_mode="controlled_stable")
            self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[])
    def test_permuting_detections_preserves_actor_ownership(self):
        inputs=cases()["hands_cross_offset_0.0"]
        for reverse in (False,True):
            frames=copy.deepcopy(inputs)
            if reverse:
                for r in frames:r["detections"].reverse()
            rows=evaluate_d(frames,background_mode="controlled_stable")
            self.assertEqual(identity_report(frames,rows)["track_owner_transfers"],[])
    def test_retired_ids_have_no_entry_or_history(self):
        p=pipeline();retired=set()
        for row in cases()["hands_cross_offset_0.0"]:
            result=feed(p,row);retired.update(result["uncertain_track_ids"])
            self.assertTrue(retired.isdisjoint(p.entries))
            self.assertTrue(retired.isdisjoint(p.contacts))
            for t in result["tracks"]:
                if t["new_track"]:self.assertFalse(t["ever_entered_roi"])
        self.assertTrue(retired)
    def test_two_hands_reverse_before_crossing(self):
        xs=[.2,.25,.3,.35,.4,.43,.4,.35,.3,.25]
        inputs=[frame(i,i*.2,[detection(x,.6,"A"),detection(1-x,.6,"B")]) for i,x in enumerate(xs)]
        rows=evaluate_d(inputs,background_mode="controlled_stable")
        self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[])
    def test_occlusion_does_not_transfer_retired_entry(self):
        inputs=cases()["hands_cross_offset_0.0"]
        for i in (8,9,10):inputs[i]["detections"]=[]
        rows=evaluate_d(inputs,background_mode="controlled_stable")
        self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[])
    def test_grid_of_crossing_speeds_and_offsets(self):
        for speed in (.015,.025,.035,.05):
            for offset in (0,.02,.05):
                for missing in (False,True):
                    inputs=[]
                    count=int(.6/speed)+1
                    for i in range(count):
                        a=detection(.2+i*speed,.6,"A")
                        b=detection(.8-i*speed,.6,"B")
                        b["box"][1]+=offset;b["box"][3]+=offset
                        ds=[a,b] if i%2 else [b,a]
                        if missing and abs(.6-2*i*speed)<.06:ds=[]
                        inputs.append(frame(i,i*.2,ds))
                    rows=evaluate_d(inputs,background_mode="controlled_stable")
                    with self.subTest(speed=speed,offset=offset,missing=missing):
                        self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[])
    def test_same_entry_episode_two_bouts_retains_known_recall_limit(self):
        rows=evaluate_d(cases()["two_contact_bouts_same_roi"],background_mode="controlled_stable")
        self.assertEqual(event_count(rows),1)
    def test_confirmed_exit_and_reentry_separate_episodes(self):
        p=pipeline({"temporal":{"cooldown_seconds":.1}})
        rows=[feed(p,r) for r in scenarios()["normal_entry_hold"][:5]]
        for i,(t,x) in enumerate([(1,.3),(1.2,.25),(1.6,.25),(1.8,.4),(2,.45),(2.2,.45),(2.4,.45)]):
            rows.append(feed(p,frame("return"+str(i),t,[detection(x)])))
        self.assertEqual(event_count(rows),2)
    def test_identity_oracle_is_not_used_by_matching(self):
        inputs=cases()["hands_cross_offset_0.0"]
        swapped=copy.deepcopy(inputs)
        for r in swapped:
            for d in r["detections"]:d["label"]="anything"
        a=evaluate_d(inputs,background_mode="controlled_stable")
        b=evaluate_d(swapped,background_mode="controlled_stable")
        for x,y in zip(a,b):
            self.assertEqual([t["track_id"] for t in x["tracks"]],[t["track_id"] for t in y["tracks"]])
    def test_inside_and_printed_hand_do_not_alert(self):
        for name in ("initial_inside","depicted_static"):
            self.assertEqual(event_count(evaluate_d(scenarios()[name],background_mode="controlled_stable")),0)
    def test_slow_entry_improvement_over_v3(self):
        frames=scenarios()["slow_entry"];old,base=evaluate(frames,2)
        rows=evaluate_d(frames,background_mode="controlled_stable")
        self.assertEqual((event_count(old),event_count(base),event_count(rows)),(0,1,1))
    def test_stationary_after_entry_single_event(self):
        rows=evaluate_d(scenarios()["normal_entry_hold"],background_mode="controlled_stable")
        self.assertEqual(event_count(rows),1)
        self.assertTrue(rows[-1]["tracks"][0]["alert_active"])
    def test_pass_by_and_score_oscillation_no_new_false_alert(self):
        for name in ("pass_by_low_score","pass_by_one_spike","score_oscillation"):
            rows=evaluate_d(scenarios()[name],background_mode="controlled_stable")
            self.assertEqual(event_count(rows),0)
    def test_multiple_hands_evidence_not_shared(self):
        inputs=scenarios()["multiple_hands"];rows=evaluate_d(inputs,background_mode="controlled_stable")
        self.assertEqual(identity_report(inputs,rows)["track_owner_transfers"],[])
        self.assertEqual(event_count(rows),1)
        for r in rows:
            for t in r["tracks"]:
                if t["label"]=="right":self.assertFalse(t["ever_entered_roi"])
    def test_timeout_1_2_3_not_declared_optimal(self):
        inputs=scenarios()["gap_1_01"]
        self.assertEqual([(timeout,id_count(evaluate_d(inputs,timeout,"controlled_stable")),
                          event_count(evaluate_d(inputs,timeout,"controlled_stable"))) for timeout in (1,2,3)],
                         [(1,6,0),(2,1,1),(3,1,1)])
    def test_roi_change_clears_state_and_requires_recalibration(self):
        p=pipeline()
        for r in scenarios()["normal_entry_hold"][:5]:feed(p,r)
        p.config["roi"]["coordinates"]=[.3,.1,.9,.9]
        r=feed(p,frame("changed",1,[detection(.45,.99)]))
        self.assertEqual(r["state"],"NEEDS_RECALIBRATION")
        self.assertEqual((p.contacts,p.entries),({},{}))
    def test_low_hand_confidence_never_contact_evidence(self):
        p=pipeline();feed(p,frame(0,0,[detection(.25)]))
        d=detection(.45,.99);d["hand_score"]=.69
        r=feed(p,frame(1,.2,[d]))
        self.assertEqual(r["dropped_detection_indices"],[0])
        self.assertTrue(all(not t["raw_contact_valid"] for t in r["tracks"]))

if __name__=="__main__":unittest.main()
