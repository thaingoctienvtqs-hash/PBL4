"""Unit and end-to-end JSONL safety tests; controlled expectations are not AI metrics."""
import copy
import io
import json
import unittest
from .controlled_cases import settings,exported,stability,control,controlled_cases,SOURCE,SESSION,REFERENCE
from ..scenarios import frame,detection,scenarios
from .prediction_adapter import convert_prediction,serialize_instances
from .offline_pipeline import OfflinePipeline
from .replay import replay_lines,summarize,new_output_directory
from .compare_phase_d import compare_case

def process_records(records,config=None,simulate=True):
    p=OfflinePipeline(config or settings(),simulate_stability=simulate)
    lines=[json.dumps(r,allow_nan=False)+"\n" for r in records]
    return list(replay_lines(lines,p)),p

class PredictionUnitTests(unittest.TestCase):
    def record(self):return exported(frame("a",0,[detection(.45,.8)]))
    def test_pixels_to_normalized_xyxy(self):
        d,log=convert_prediction(self.record())
        self.assertEqual(d[0]["box"],[.4,.3,.5,.5])
        self.assertEqual(d[0]["object_contact_score"],.8)
        self.assertEqual(d[0]["hand_score"],.99)
    def test_non_square_image_uses_correct_axes(self):
        r=self.record();r["image_size"]=[200,400]
        r["prediction"]["pred_boxes"]=[[0,0,400,200]]
        self.assertEqual(convert_prediction(r)[0][0]["box"],[0,0,1,1])
    def test_normalized_input_not_scaled_twice(self):
        r=exported(frame("a",0,[detection(.45)]),space="normalized_xyxy")
        self.assertEqual(convert_prediction(r)[0][0]["box"],r["prediction"]["pred_boxes"][0])
    def test_no_voc_minus_one_shift(self):
        r=self.record();r["prediction"]["pred_boxes"]=[[0,0,1000,1000]]
        self.assertEqual(convert_prediction(r)[0][0]["box"],[0,0,1,1])
    def test_sigmoid_scores_not_softmax_or_argmax(self):
        r=self.record();r["prediction"]["pred_cats"]=[[.99,.99,.99,.16]]
        self.assertEqual(convert_prediction(r)[0][0]["object_contact_score"],.16)
    def test_empty_predictions_are_valid_no_hand(self):
        r=exported(frame("a",0,[]))
        self.assertEqual(convert_prediction(r)[0],[])
        logs,unused=process_records([r])
        self.assertEqual(logs[0]["state"],"NO_HAND")
        self.assertTrue(logs[0]["decision_available"])
    def test_array_length_mismatch_rejected(self):
        r=self.record();r["prediction"]["scores"]=[]
        with self.assertRaises(ValueError):convert_prediction(r)
    def test_contact_vector_shape_rejected(self):
        r=self.record();r["prediction"]["pred_cats"]=[[.9,.8,.7]]
        with self.assertRaises(ValueError):convert_prediction(r)
    def test_inverted_and_empty_boxes_rejected(self):
        for box in ([10,10,0,20],[0,0,0,10]):
            r=self.record();r["prediction"]["pred_boxes"]=[box]
            with self.assertRaises(ValueError):convert_prediction(r)
    def test_non_finite_boolean_and_string_numbers_rejected(self):
        for value in (float("nan"),float("inf"),True,"0.8"):
            r=self.record();r["prediction"]["scores"]=[value]
            with self.assertRaises(ValueError):convert_prediction(r)
    def test_score_outside_range_rejected(self):
        r=self.record();r["prediction"]["pred_cats"][0][3]=1.1
        with self.assertRaises(ValueError):convert_prediction(r)
    def test_missing_coordinate_space_or_size_rejected(self):
        for field in ("coordinate_space","image_size"):
            r=self.record();r.pop(field)
            with self.assertRaises(ValueError):convert_prediction(r)
    def test_invalid_image_size_rejected(self):
        for value in ([0,100],[-1,100],[True,100],[1.5,100]):
            r=self.record();r["image_size"]=value
            with self.assertRaises(ValueError):convert_prediction(r)
    def test_clipping_delegates_to_phase_d(self):
        r=self.record();r["prediction"]["pred_boxes"]=[[-1,0,1001,1000]]
        logs,p=process_records([r])
        self.assertEqual(logs[0]["tracks"][0]["box"],[0,0,1,1])
        self.assertTrue(logs[0]["conversion"][0]["will_clip_in_phase_d"])
    def test_low_hand_score_not_contact_evidence(self):
        r=self.record();r["prediction"]["scores"]=[.69]
        logs,p=process_records([r])
        self.assertEqual(logs[0]["pipeline_result"]["dropped_detection_indices"],[0])
        self.assertFalse(logs[0]["used_for_confirmation"])
    def test_detection_limit_is_not_silently_truncated(self):
        r=self.record()
        r["prediction"]={"pred_boxes":[[0,0,1,1]]*33,"scores":[.99]*33,"pred_cats":[[.1,.2,.3,.8]]*33}
        with self.assertRaises(ValueError):convert_prediction(r)
    def test_cpu_instances_serializer_without_torch(self):
        class Tensor:
            device="cpu"
            def __init__(self,values):self.values=values
            def tolist(self):return self.values
        class Boxes:
            tensor=Tensor([[0,0,100,100]])
        class Instances:
            pred_boxes=Boxes();scores=Tensor([.99]);pred_cats=Tensor([[.1,.2,.3,.8]])
            def has(self,name):return hasattr(self,name)
        self.assertEqual(serialize_instances(Instances())["pred_cats"][0][3],.8)
        Instances.scores.device="cuda"
        with self.assertRaises(ValueError):serialize_instances(Instances())

class BoundarySafetyTests(unittest.TestCase):
    def test_explicit_roi_required(self):
        c=settings();c["sources"][SOURCE]["pipeline_config"]={}
        with self.assertRaises(ValueError):OfflinePipeline(c)
    def test_contact_threshold_lowering_rejected(self):
        c=settings();c["sources"][SOURCE]["pipeline_config"]["thresholds"]={"object_contact":.1}
        with self.assertRaises(ValueError):OfflinePipeline(c)
    def test_schema_boolean_rejected(self):
        c=settings();c["schema_version"]=True
        with self.assertRaises(ValueError):OfflinePipeline(c)
        r=exported(frame("a",0,[]));r["schema_version"]=True
        self.assertFalse(OfflinePipeline(settings()).process(r)["accepted"])
    def test_default_unknown_never_promoted_to_stable(self):
        records=[exported(r) for r in scenarios()["normal_entry_hold"]]
        logs,p=process_records(records,simulate=False)
        self.assertEqual(summarize(logs)["event_count"],0)
        self.assertTrue(all(not r["decision_available"] for r in logs))
    def test_missing_stability_does_not_use_cached_stable(self):
        records=[exported(r) for r in scenarios()["normal_entry_hold"][:3]]
        r=exported(frame("nostability",.6,[detection(.45)]));r.pop("stability")
        records.append(r)
        logs,p=process_records(records)
        self.assertEqual(logs[-1]["state"],"CAMERA_UNVERIFIED")
        self.assertEqual(p.pipelines[SOURCE].contacts,{})
    def test_stability_bound_to_frame_source_session_reference_time(self):
        for field,value in (("frame_id","old"),("source_id","other"),("session_id","old"),
                            ("reference_id","wrong"),("timestamp",10)):
            r=exported(frame("a",0,[detection(.25)]));r["stability"][field]=value
            logs,p=process_records([r])
            self.assertFalse(logs[0]["decision_available"])
    def test_unknown_and_invalid_stability_are_not_stable(self):
        for status in ("UNKNOWN","stable",True,None):
            r=exported(frame("a",0,[detection(.25)]));r["stability"]["status"]=status
            logs,p=process_records([r])
            self.assertFalse(logs[0]["decision_available"])
    def test_duplicate_does_not_increment_or_clear_contact_history(self):
        records=[exported(r) for r in scenarios()["normal_entry_hold"][:3]]
        logs,p=process_records(records)
        contact=next(iter(p.pipelines[SOURCE].contacts.values()))
        before=copy.deepcopy(contact.__dict__)
        r=copy.deepcopy(records[-1]);r["timestamp"]=.5;r["received_timestamp"]=.5;r["stability"]=stability(r)
        result=p.process(r)
        self.assertFalse(result["accepted"])
        self.assertEqual(contact.__dict__,before)
    def test_bad_timestamp_invalidates_without_synthetic_observation(self):
        records=[exported(r) for r in scenarios()["normal_entry_hold"][:3]]
        logs,p=process_records(records)
        r=exported(frame("bad",.6,[detection(.45)]));r["timestamp"]=float("nan")
        result=p.process(r)
        self.assertFalse(result["accepted"]);self.assertEqual(p.pipelines[SOURCE].contacts,{})
        self.assertEqual(p.pipelines[SOURCE].last_timestamp,.4)
    def test_missing_receive_timestamp_is_not_assumed_fresh(self):
        r=exported(frame("a",0,[detection(.25)]));r.pop("received_timestamp")
        self.assertEqual(OfflinePipeline(settings(),True).process(r)["reason"],"invalid_frame_payload")
    def test_disconnect_bypasses_full_cache_and_bad_control_timestamp(self):
        c=settings();c["sources"][SOURCE]["pipeline_config"]["input"]={"frame_id_cache_size":5}
        records=[exported(r) for r in scenarios()["normal_entry_hold"][:5]]
        logs,p=process_records(records,c)
        r=p.process(control("disconnect",float("nan"),frame_id="4"))
        self.assertEqual(r["state"],"CAMERA_OFFLINE")
        self.assertIsNone(r["timestamp"])
        self.assertEqual(p.pipelines[SOURCE].contacts,{})
        self.assertEqual(p.process(records[-1])["state"],"CAMERA_OFFLINE")
    def test_missing_frame_not_no_hand(self):
        r=control("missing",0,frame_id="miss",received_timestamp=0);r["stability"]=stability(r)
        logs,p=process_records([r])
        self.assertEqual(logs[0]["state"],"FRAME_MISSING")
        self.assertFalse(logs[0]["decision_available"])
    def test_invalid_payload_cannot_bridge_contact(self):
        case=next(c for c in controlled_cases() if c["name"]=="malformed_payload_barrier")
        logs,p=process_records(case["records"])
        self.assertEqual(summarize(logs)["event_count"],0)
        self.assertFalse(logs[-1]["tracks"][0]["ever_entered_roi"])
    def test_resolution_change_requires_reconnect(self):
        records=[exported(r) for r in scenarios()["normal_entry_hold"][:3]]
        logs,p=process_records(records)
        r=exported(frame("resized",.6,[detection(.45)]));r["image_size"]=[500,1000]
        self.assertEqual(p.process(r)["reason"],"image_size_changed_requires_reconnect")
        self.assertEqual(p.pipelines[SOURCE].contacts,{})
    def test_source_and_session_isolation(self):
        c=settings();c["sources"]["painting1"]=copy.deepcopy(c["sources"][SOURCE])
        p=OfflinePipeline(c,simulate_stability=True)
        logs=[]
        for row in scenarios()["normal_entry_hold"][:5]:
            logs.extend(p.process(exported(row,source=s)) for s in (SOURCE,"painting1"))
        events=[e for r in logs for e in r["events"]]
        self.assertEqual(len(events),2)
        self.assertEqual(len(set(e["source_event_key"] for e in events)),2)
        p.process(control("disconnect",1))
        self.assertFalse(p.pipelines[SOURCE].online)
        self.assertTrue(p.pipelines["painting1"].contacts)
    def test_wrong_session_does_not_clear_live_source(self):
        p=OfflinePipeline(settings(),True)
        p.process(exported(frame("a",0,[detection(.25)])))
        r=control("disconnect",1,session="old")
        self.assertEqual(p.process(r)["reason"],"wrong_source_session")
        self.assertTrue(p.pipelines[SOURCE].tracker.tracks)
    def test_roi_override_record_rejected_not_ignored(self):
        r=exported(frame("a",0,[]));r["roi"]={"coordinates":[0,0,1,1]}
        self.assertEqual(OfflinePipeline(settings(),True).process(r)["reason"],"unknown_record_fields")
    def test_input_config_mutation_does_not_change_active_roi(self):
        c=settings();p=OfflinePipeline(c,True);c["sources"][SOURCE]["pipeline_config"]["roi"]["coordinates"]=[0,0,1,1]
        self.assertEqual(p.pipelines[SOURCE].config["roi"]["coordinates"],[.4,.1,.8,.9])
    def test_bad_reconnect_previous_session_rejected(self):
        p=OfflinePipeline(settings(),True)
        r=control("reconnect",session="new",previous_session_id="wrong",calibration_id=REFERENCE)
        self.assertFalse(p.process(r)["accepted"])
    def test_cache_rejection_is_not_no_hand(self):
        c=settings();c["sources"][SOURCE]["pipeline_config"]["input"]={"frame_id_cache_size":1}
        logs,p=process_records([exported(frame("a",0,[])),exported(frame("b",1,[]))],c)
        self.assertEqual(logs[-1]["state"],"FRAME_REJECTED")
        self.assertFalse(logs[-1]["decision_available"])

class JsonlIntegrationSafetyTests(unittest.TestCase):
    def test_corrupt_line_invalidates_history_before_continuing(self):
        records=[exported(r) for r in scenarios()["normal_entry_hold"][:3]]
        lines=[json.dumps(r)+"\n" for r in records]+["{invalid\n"]
        lines += [json.dumps(exported(frame("inside"+str(i),.6+i*.2,[detection(.45)])))+"\n" for i in range(5)]
        logs=list(replay_lines(lines,OfflinePipeline(settings(),True)))
        self.assertEqual(summarize(logs)["event_count"],0)
        self.assertEqual(logs[3]["reason"],"invalid_jsonl")
    def test_nan_and_duplicate_json_keys_rejected(self):
        for line in ('{"source_id":"painting0","timestamp":NaN}','{"source_id":"a","source_id":"b"}'):
            logs=list(replay_lines([line],OfflinePipeline(settings(),True)))
            self.assertEqual(logs[0]["reason"],"invalid_jsonl")
    def test_empty_line_is_visible_rejection(self):
        logs=list(replay_lines(["\n"],OfflinePipeline(settings(),True)))
        self.assertEqual(logs[0]["line_number"],1)
        self.assertFalse(logs[0]["used_for_confirmation"])
    def test_replay_is_deterministic(self):
        records=next(c for c in controlled_cases() if c["name"]=="slow_entry")["records"]
        a,unused=process_records(records);b,unused=process_records(records)
        self.assertEqual(a,b)
    def test_output_path_outside_phase_e_rejected_before_writing(self):
        with self.assertRaises(ValueError):new_output_directory("/mnt/c/Users/LEGION/Pbl4/data")
    def test_missing_detection_does_not_add_votes(self):
        records=next(c for c in controlled_cases() if c["name"]=="explicit_missing_frame")["records"]
        logs,p=process_records(records)
        r=next(r for r in logs if r["kind"]=="missing")
        self.assertEqual(r["pipeline_result"]["tracks"][0]["positive_frames"],0)
        self.assertEqual(r["pipeline_result"]["tracks"][0]["support_seconds"],0)
    def test_uncertainty_misses_are_counted_not_claimed_as_precision(self):
        case=next(c for c in controlled_cases() if c["name"]=="crossing_0.0")
        logs,p=process_records(case["records"])
        report=summarize(logs,case["controlled_expected_contact_events"])
        self.assertEqual(report["controlled_event_shortfall"],1)
        self.assertTrue(any(r.get("ambiguous_detection_indices") for r in logs))
    def test_default_unknown_shortfall_is_unavailable_not_true_negative(self):
        case=next(c for c in controlled_cases() if c["name"]=="unknown_stability_real_contact")
        logs,p=process_records(case["records"])
        report=summarize(logs,case["controlled_expected_contact_events"])
        self.assertEqual(report["controlled_event_shortfall"],1)
        self.assertEqual(report["unavailable_records"],report["records"])
    def test_early_missing_reacquisition_limit_is_proven_not_adapter_error(self):
        case=next(c for c in controlled_cases() if c["name"]=="explicit_missing_frame")
        comparison,logs=compare_case(case)
        self.assertEqual(comparison["mismatch_count"],0)
        self.assertEqual(summarize(logs)["event_count"],0)
        at_reappear=logs[4]["tracks"]
        self.assertEqual([t["track_id"] for t in at_reappear if t["observed"]],[1])
        self.assertFalse(next(t for t in at_reappear if t["observed"])["ever_entered_roi"])
        self.assertEqual(logs[5]["state"],"TRACK_UNCERTAIN")
    def test_crossing_oracle_ownership_not_transferred(self):
        case=next(c for c in controlled_cases() if c["name"]=="crossing_0.0")
        comparison,logs=compare_case(case)
        self.assertEqual(comparison["identity"]["track_owner_transfers"],[])
        self.assertEqual(comparison["mismatch_count"],0)

class OfflineCases(unittest.TestCase):
    pass

def make_case_test(case):
    def test(self):
        logs,p=process_records(case["records"],case["settings"])
        self.assertEqual(summarize(logs)["event_count"],case["expected_logic_events"],case["name"])
        comparison,unused=compare_case(case)
        self.assertEqual(comparison["mismatch_count"],0,comparison["mismatches"])
    return test

for _case in controlled_cases():
    setattr(OfflineCases,"test_case_"+_case["name"].replace(".","_"),make_case_test(_case))

if __name__=="__main__":unittest.main()
