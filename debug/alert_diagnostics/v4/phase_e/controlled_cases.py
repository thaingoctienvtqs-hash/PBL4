"""Controlled prediction fixtures and synthetic labels, never a ContactHands dataset."""
import copy
from ..scenarios import scenarios,single,detection,frame
from ..phase_c.audit_scenarios import cases as old_cases

REFERENCE="offline_controlled_reference"
SOURCE="painting0"
SESSION="boot0"

def settings(polygon=False,sources=None):
    roi={"enabled":True,"normalized":True,"shape":"rectangle","coordinates":[.4,.1,.8,.9]}
    if polygon:
        roi={"enabled":True,"normalized":True,"shape":"polygon",
             "points":[[.4,.1],[.75,.15],[.85,.85],[.4,.9]]}
    entry={"session_id":SESSION,"calibration_id":REFERENCE,"pipeline_config":{"roi":roi}}
    return {"schema_version":1,"sources":sources or {SOURCE:entry}}

def stability(record,status="STABLE",reference=REFERENCE):
    return {"status":status,"frame_id":str(record["frame_id"]),"timestamp":record["timestamp"],
            "source_id":record["source_id"],"session_id":record["session_id"],"reference_id":reference}

def exported(row,source=SOURCE,session=SESSION,status="STABLE",space="pixels_xyxy"):
    boxes=[d["box"] if space=="normalized_xyxy" else [v*1000 for v in d["box"]] for d in row["detections"]]
    record={"schema_version":1,"kind":"prediction","source_id":source,"session_id":session,
            "frame_id":row["frame_id"],"timestamp":row["timestamp"],"received_timestamp":row["timestamp"],
            "image_size":[1000,1000],"coordinate_space":space,
            "prediction":{"pred_boxes":boxes,"scores":[d["hand_score"] for d in row["detections"]],
                          "pred_cats":[[.3,.4,.2,d["object_contact_score"]] for d in row["detections"]]},
            "oracle":{"actors":[d.get("label") for d in row["detections"]]}}
    record["stability"]=stability(record,status)
    return record

def sequence(rows):return [exported(r) for r in rows]

def control(kind,timestamp=None,session=SESSION,**values):
    record={"schema_version":1,"kind":kind,"source_id":SOURCE,"session_id":session,"timestamp":timestamp}
    record.update(values)
    return record

def case(name,records,expected,config=None,physical_expected=None):
    return {"name":name,"settings":config or settings(),"records":records,
            "expected_logic_events":expected,
            "controlled_expected_contact_events":expected if physical_expected is None else physical_expected,
            "label_kind":"controlled_scenario_expectation_not_real_video_ground_truth"}

def controlled_cases():
    old=scenarios()
    result=[case("slow_entry",sequence(old["slow_entry"]),1),
            case("initial_inside",sequence(old["initial_inside"]),0,physical_expected=1),
            case("printed_static",sequence(old["depicted_static"]),0),
            case("polygon_slow_entry",sequence(old["slow_entry"]),1,settings(polygon=True)),
            case("multiple_separate_hands",sequence(old["multiple_hands"]),1),
            case("score_oscillation",sequence(old["score_oscillation"]),0,physical_expected=1),
            case("missing_detection",sequence(old["short_detection_loss"]),1),
            case("two_bouts_same_entry",sequence(old_cases()["two_contact_bouts_same_roi"]),1,physical_expected=2)]
    for fps in (1,5,10,15,30):
        for score,tag in ((.6,"moderate"),(.85,"fast")):
            rows=single([(0,.25,score)]+[(i/float(fps),.45,score) for i in range(1,fps*3+1)])
            result.append(case("contact_{}_{}fps".format(tag,fps),sequence(rows),1))
    for offset in (0.0,.01,.03):
        result.append(case("crossing_"+str(offset),sequence(old_cases()["hands_cross_offset_"+str(offset)]),0,physical_expected=1))
    # Disconnect is independent from data timestamp/frame cache. Reconnect inside does not inherit entry.
    records=sequence(old["normal_entry_hold"][:5])
    records.append(control("disconnect",.8,frame_id="4"))
    records.append(exported(frame("offline",1,[detection(.45,.99)])))
    records.append(control("reconnect",session="boot1",previous_session_id=SESSION,calibration_id=REFERENCE))
    records.extend(exported(frame("inside"+str(i),i*.2,[detection(.45,.99)]),session="boot1") for i in range(6))
    result.append(case("disconnect_alert_reconnect_inside",records,1,physical_expected=2))
    records=sequence(old["normal_entry_hold"][:5])
    records.append(exported(frame("shake",1,[detection(.45,.99)]),status="MOVING"))
    records.extend(exported(frame("restore"+str(i),1.2+i*.2,[detection(.45,.99)])) for i in range(4))
    records.extend(exported(frame("return"+str(i),t,[detection(x)])) for i,(t,x) in enumerate(
        [(2.2,.3),(2.4,.25),(2.8,.25),(3,.4),(3.2,.45),(3.4,.45),(3.6,.45)]))
    result.append(case("shake_recovery_requires_entry",records,2))
    # Distinct physical ROI entry episodes; keep source alive while default 60-second cooldown expires.
    rows=old["normal_entry_hold"][:5]+[frame("exit"+str(i),1+i,[detection(.25,.1)]) for i in range(63)]
    rows += [frame("again"+str(i),64+i*.2,[detection(.45)]) for i in range(4)]
    result.append(case("separate_episodes_default_cooldown",sequence(rows),2))
    records=sequence(old["normal_entry_hold"][:3])
    missing=control("missing",.6,frame_id="miss",received_timestamp=.6)
    missing["stability"]=stability(missing)
    records.append(missing)
    records.extend(exported(frame("after"+str(i),.8+i*.2,[detection(.45)])) for i in range(3))
    result.append(case("explicit_missing_frame",records,1))
    records=sequence(old["normal_entry_hold"][:3])
    broken=control("frame_error",.6,frame_id="bad",received_timestamp=.6,error="unreadable image")
    broken["stability"]=stability(broken);records.append(broken)
    records.extend(exported(frame("after"+str(i),.8+i*.2,[detection(.45)])) for i in range(3))
    result.append(case("explicit_frame_error",records,1))
    records=sequence(old["normal_entry_hold"][:3])
    repeated=copy.deepcopy(records[-1]);repeated["timestamp"]=.5;repeated["received_timestamp"]=.5
    repeated["stability"]=stability(repeated);records.append(repeated)
    stale=exported(frame("stale",.5,[detection(.45)]));stale["received_timestamp"]=4;records.append(stale)
    backwards=exported(frame("backwards",.3,[detection(.45)]));records.append(backwards)
    records.extend(exported(frame("fresh"+str(i),.6+i*.2,[detection(.45)])) for i in range(2))
    result.append(case("duplicate_stale_nonmonotonic",records,1))
    records=sequence(old["normal_entry_hold"][:3])
    bad=exported(frame("bad_payload",.6,[detection(.45)]));bad["prediction"]["pred_cats"]=[[.5]]
    records.append(bad)
    records.extend(exported(frame("inside"+str(i),.8+i*.2,[detection(.45)])) for i in range(6))
    result.append(case("malformed_payload_barrier",records,0,physical_expected=1))
    records=sequence(old["normal_entry_hold"])
    for r in records:r["stability"]["status"]="UNKNOWN"
    result.append(case("unknown_stability_real_contact",records,0,physical_expected=1))
    for kind in ("missing","frame_error"):
        records=sequence(old["normal_entry_hold"][:4])
        absent=control(kind,.8,frame_id="stable_miss",received_timestamp=.8)
        absent["stability"]=stability(absent);records.append(absent)
        records.extend(exported(frame("recover"+str(i),1+i*.2,[detection(.45)])) for i in range(3))
        result.append(case("stable_hold_"+kind+"_recovery",records,1))
    return result
