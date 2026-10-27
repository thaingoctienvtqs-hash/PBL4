"""Compare the adapter's delegated core with direct immutable D on identical exports."""
import copy
from ..phase_d.pipeline_d import PipelineD
from ..phase_d.fixtures import background
from ..phase_c.audit_scenarios import identity_report
from .offline_pipeline import OfflinePipeline
from .prediction_adapter import convert_prediction

def compare_case(case):
    source=next(iter(case["settings"]["sources"]))
    source_config=case["settings"]["sources"][source]
    direct=PipelineD(source_config["pipeline_config"],calibration_id=source_config["calibration_id"],
                     source_session=source_config["session_id"],test_mode=True)
    adapter=OfflinePipeline(case["settings"],simulate_stability=True)
    mismatches=[];compared=0;adapter_only=[];logs=[];oracle_frames=[]
    for index,record in enumerate(case["records"]):
        output=adapter.process(copy.deepcopy(record));logs.append(output)
        try:detections,unused=convert_prediction(record)
        except ValueError:detections=[]
        actors=record.get("oracle",{}).get("actors",[])
        for i,det in enumerate(detections):det["label"]=actors[i] if i<len(actors) else None
        oracle_frames.append({"timestamp":record.get("timestamp"),"detections":detections})
        if "pipeline_result" not in output:
            adapter_only.append(index)
            if output.get("invalidated_track_ids"):direct._clear_state()
            continue
        kind=record["kind"]
        if kind=="disconnect":
            result=direct.disconnect(record.get("frame_id"),record.get("timestamp"),source_session=record["session_id"])
        elif kind=="reconnect":
            result=direct.reconnect(record["session_id"],record["calibration_id"]);result["accepted"]=True
        else:
            raw_detections=convert_prediction(record)[0] if kind=="prediction" else []
            signal=record.get("stability",{}).get("status","UNKNOWN")
            context=None
            if signal in ("STABLE","MOVING"):
                context=background(record["frame_id"],record["timestamp"],record["session_id"],dx=.01 if signal=="MOVING" else 0)
                context["reference_id"]=direct.calibration_id
            result=direct.step(record["frame_id"],record["timestamp"],raw_detections,
                               received_timestamp=record["received_timestamp"],source_session=record["session_id"],
                               camera_context=context)
        core=output["pipeline_result"]
        fields=("accepted","state","tracks","events")
        # D does not give accepted=True on reconnect; both calls normalize that above.
        actual={k:core.get(k) for k in fields}
        expected={k:result.get(k) for k in fields}
        compared+=1
        if actual!=expected:mismatches.append({"index":index,"adapter":actual,"direct_phase_d":expected})
    identity=identity_report(oracle_frames,logs)
    return {"scenario":case["name"],"compared_records":compared,"adapter_only_rejection_indices":adapter_only,
            "mismatch_count":len(mismatches),"mismatches":mismatches,"identity":identity},logs
