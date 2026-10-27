"""Counterexamples built from controlled predictions, never physical ground truth."""
import copy
from ..scenarios import single,detection,frame,scenarios
from ..compare_v3_v4 import evaluate,event_count,id_count

def cases():
    result = copy.deepcopy(scenarios())
    result["high_fps_30_moderate"] = single([(0,.25,.6)]+[((i+1)/30.0,.45,.6) for i in range(60)])
    result["high_fps_20_moderate"] = single([(0,.25,.6)]+[((i+1)/20.0,.45,.6) for i in range(60)])
    xs = [.5-i*.01 for i in range(21)]+[.3+i*.01 for i in range(1,26)]
    result["camera_slow_pan_printed_hand"] = single([(i*.2,x,.99) for i,x in enumerate(xs)])
    result["camera_fast_jolt_printed_hand"] = single([(0,.5,.99),(.2,.3,.99),(.4,.5,.99),(.6,.5,.99)])
    result["thin_border_overlap_035"] = single([(0,.25,.6),(.2,.3,.6)]+[(.4+i*.2,.385,.6) for i in range(8)])
    result["repeated_detection_missing"] = single([(0,.25,.6),(.2,.3,.6)]+
                                                  [(.4+i*.2,.45 if i%2==0 else None,.6) for i in range(20)])
    result["three_five_strong_oscillation"] = single([(0,.25,.6),(.2,.3,.6)]+
                                                    [((i+2)*.2,.45,s) for i,s in enumerate([.6,.1]*5)])
    result["two_contact_bouts_same_roi"] = single([(0,.25,.6),(.2,.3,.6),(.4,.45,.6),(.6,.45,.6),(.8,.45,.6)]+
                                                  [(.8+i*.5,.45,.1) for i in range(1,125)]+
                                                  [(63+i*.2,.45,.6) for i in range(1,5)])
    for offset in (0.0,.01,.03):
        rows = []
        for i in range(17):
            a,b = detection(.2+i*.035,.6,"A"),detection(.8-i*.035,.6,"B")
            b["box"][1]+=offset;b["box"][3]+=offset
            rows.append(frame(i,i*.2,[a,b] if i%2==0 else [b,a]))
        result["hands_cross_offset_"+str(offset)] = rows
    result["high_fps_30_fast"] = single([(0,.25,.99)]+[((i+1)/30.0,.45,.99) for i in range(60)])
    return result

def identity_report(inputs, outputs):
    actors,owners = {},{}
    actor_id_changes = []
    track_owner_transfers = []
    for frame,output in zip(inputs,outputs):
        for track in output["tracks"]:
            index = track.get("input_index")
            if not track["observed"] or index is None:
                continue
            label = frame["detections"][index].get("label")
            if label is None:
                continue
            key = track["track_id"]
            if label in actors and actors[label]!=key:
                actor_id_changes.append({"timestamp":frame["timestamp"],"actor":label,
                                         "old_id":actors[label],"new_id":key})
            if key in owners and owners[key]!=label:
                track_owner_transfers.append({"timestamp":frame["timestamp"],"track_id":key,
                                              "from":owners[key],"to":label})
            actors[label],owners[key] = key,label
    return {"actor_id_changes":actor_id_changes,"track_owner_transfers":track_owner_transfers}

def summarize(name,inputs,timeout):
    old,new = evaluate(inputs,timeout)
    return {"scenario":name,"timeout_seconds":timeout,"v3_events":event_count(old),
            "v4_events":event_count(new),"v3_observed_ids":id_count(old),"v4_observed_ids":id_count(new),
            "v3_identity":identity_report(inputs,old),"v4_identity":identity_report(inputs,new)},old,new
