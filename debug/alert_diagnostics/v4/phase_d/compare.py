"""Replay identical normalized predictions; camera evidence is a separate explicit input."""
import copy
import hashlib
import json
from ..compare_v3_v4 import evaluate,event_count,id_count
from ..phase_c.audit_scenarios import cases,identity_report
from .fixtures import pipeline,feed,evaluate_d,background

def camera_signal(name,frame):
    # Independent synthetic scene motion for camera counterexamples, not inferred as STABLE.
    if name=="camera_slow_pan_printed_hand":
        displacement=frame["detections"][0]["box"][0]-.45
        return displacement,0.0,"controlled_background_pan_from_reference"
    if name=="camera_fast_jolt_printed_hand":
        displacement=frame["detections"][0]["box"][0]-.45
        return displacement,0.0,"controlled_background_jolt_from_reference"
    return 0.0,0.0,"controlled_background_assumed_stable_not_image_verified"

def comparison():
    summaries=[];replays=[]
    for name,inputs in sorted(cases().items()):
        digest=hashlib.sha256(json.dumps(inputs,sort_keys=True,allow_nan=False).encode("utf-8")).hexdigest()
        for timeout in (1,2,3):
            v3,v4=evaluate(copy.deepcopy(inputs),timeout)
            unknown=evaluate_d(copy.deepcopy(inputs),timeout,"unknown")
            p=pipeline({"tracking":{"max_idle_seconds":timeout}})
            fixed=[];contexts=[];signal=None
            for row in inputs:
                dx,dy,signal=camera_signal(name,row)
                context=background(row["frame_id"],row["timestamp"],p.source_session,dx,dy)
                contexts.append(context)
                fixed.append(p.step(**copy.deepcopy(row),camera_context=context))
            summary={"scenario":name,"timeout_seconds":timeout,"predictions_sha256":digest,
                     "camera_evidence":signal,"real_images_evaluated":False}
            for tag,rows in (("v3",v3),("v4",v4),("phase_d_controlled",fixed),("phase_d_unknown",unknown)):
                summary[tag]={"events":event_count(rows),"observed_ids":id_count(rows),
                              "identity":identity_report(inputs,rows),
                              "unavailable_frames":sum(r.get("decision_available") is False for r in rows)}
            summaries.append(summary)
            replays.append({"summary":summary,"inputs":inputs,"camera_contexts":contexts,
                            "v3":v3,"v4":v4,"phase_d_controlled":fixed,"phase_d_unknown":unknown})
    return summaries,replays
