"""Same serialized exports, equal timeouts; actor/event truth stays outside the matcher."""
import copy
from ..phase_e.offline_pipeline import OfflinePipeline
from ..phase_e.replay import replay_lines
from ..phase_e.compare_phase_d import compare_case
from ..phase_e.controlled_cases import controlled_cases
from ..phase_c.audit_scenarios import identity_report
from ..phase_e.prediction_adapter import convert_prediction
from .pipeline_f import OfflineF
import json

def replay(case,geometry=True,timeout=2):
    config=copy.deepcopy(case["settings"])
    for source in config["sources"].values():
        source["pipeline_config"].setdefault("tracking",{})["max_idle_seconds"]=timeout
    model=OfflineF(config,simulate_stability=True,geometry_recovery=geometry)
    logs=list(replay_lines([json.dumps(r,sort_keys=True,allow_nan=False)+"\n" for r in case["records"]],model))
    return logs,model,config

def evaluate_truth(case,logs):
    frames=[];events=[]
    for record,output in zip(case["records"],logs):
        try:ds=convert_prediction(record)[0]
        except ValueError:ds=[]
        actors=record.get("oracle",{}).get("actors",[])
        for index,det in enumerate(ds):det["label"]=actors[index] if index<len(actors) else None
        frames.append({"timestamp":record.get("timestamp"),"detections":ds})
        for event in output["events"]:
            track=next((t for t in output["tracks"] if t["track_id"]==event["track_id"]),None)
            index=None if track is None else track.get("input_index")
            actor=actors[index] if index is not None and index<len(actors) else None
            events.append({"actor":actor,"timestamp":record["timestamp"],"track_id":event["track_id"]})
    identity=identity_report(frames,logs)
    owner_ids={}
    for frame,output in zip(frames,logs):
        for t in output["tracks"]:
            if t["observed"] and t.get("input_index") is not None:
                actor=frame["detections"][t["input_index"]].get("label")
                if actor is not None:owner_ids.setdefault(str(t["track_id"]),set()).add(actor)
    confirmed=[]
    first_owners={};commits={"correct":0,"wrong":0,"unlabelled":0}
    for frame,output in zip(frames,logs):
        filtered=dict(output,tracks=[t for t in output["tracks"] if not t.get("track_id_is_tentative")])
        confirmed.append(filtered)
        for track in output["tracks"]:
            if not track["observed"] or track.get("input_index") is None:continue
            actor=frame["detections"][track["input_index"]].get("label")
            previous=first_owners.get(track["track_id"])
            if track.get("recovery_state")=="RECOVERED_GEOMETRY":
                key="unlabelled" if actor is None or previous is None else "correct" if actor==previous else "wrong"
                commits[key]+=1
            if actor is not None:first_owners.setdefault(track["track_id"],actor)
    result={"events":events,"identity":identity,"confirmed_identity":identity_report(frames,confirmed),
            "recovery_commit_owners":commits,
            "single_owner_ids":sum(len(v)==1 for v in owner_ids.values()),
            "wrongly_shared_ids":sum(len(v)>1 for v in owner_ids.values())}
    if "truth_events" in case:
        unmatched=list(case["truth_events"]);matched=[];false=[]
        for event in events:
            choices=[(i,t) for i,t in enumerate(unmatched) if t["actor"]==event["actor"] and t["start"]<=event["timestamp"]<=t["end"]]
            if choices:
                i,truth=choices[0];unmatched.pop(i);matched.append({"event":event,"truth":truth})
            else:false.append(event)
        result.update(controlled_TP=len(matched),controlled_FP=len(false),controlled_FN=len(unmatched),
                      false_events=false,missed_truth_events=unmatched)
    return result

def compare(case,timeout=2):
    f,unused,config=replay(case,True,timeout)
    strict,unused,unused_config=replay(case,False,timeout)
    e=OfflinePipeline(config,simulate_stability=True)
    elog=list(replay_lines([json.dumps(r,sort_keys=True)+"\n" for r in case["records"]],e))
    direct_case=copy.deepcopy(case);direct_case["settings"]=config
    d_check,d_outer=compare_case(direct_case)
    dlog=[]
    for row in d_outer:
        core=copy.deepcopy(row.get("pipeline_result",row))
        core.setdefault("tracks",[]);core.setdefault("events",[]);dlog.append(core)
    result={"scenario":case["name"],"timeout_seconds":timeout,"D_E_core_mismatches":d_check["mismatch_count"]}
    for name,logs in (("D",dlog),("E",elog),("F_geometry",f),("F_strict",strict)):
        result[name]=evaluate_truth(case,logs)
    return result,{"input":case["records"],"D":dlog,"E":elog,"F_geometry":f,"F_strict":strict}
