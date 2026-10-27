"""Per-source offline integration that delegates all alert logic to immutable Phase D."""
import copy
import re
from ..phase_d.pipeline_d import PipelineD
from ..pipeline_v4 import validate_config
from .prediction_adapter import convert_prediction,number
from .stability import StabilityProvider,SimulatedStability,CorrespondenceStability

def identifier(value):
    return isinstance(value,str) and re.match(r"\A[A-Za-z0-9_.-]{1,64}\Z",value) is not None

class OfflinePipeline:
    def __init__(self,settings,simulate_stability=False,allow_correspondences=False):
        if simulate_stability and allow_correspondences:raise ValueError("Choose one stability mode")
        if not isinstance(settings,dict) or set(settings)!={"schema_version","sources"} or type(settings["schema_version"]) is not int or settings["schema_version"]!=1:
            raise ValueError("Invalid offline configuration schema")
        sources=settings["sources"]
        if not isinstance(sources,dict) or not 1<=len(sources)<=16:raise ValueError("Configure 1..16 explicit sources")
        self.pipelines={};self.configs={};self.last_size={}
        self.simulate_stability=simulate_stability
        for source,config in sources.items():
            if not identifier(source) or not isinstance(config,dict) or set(config)!={"session_id","calibration_id","pipeline_config"}:
                raise ValueError("Invalid source configuration")
            if not identifier(config["session_id"]) or not isinstance(config["calibration_id"],str) or not config["calibration_id"]:
                raise ValueError("Explicit session and calibration identifiers required")
            pipeline_config=config["pipeline_config"]
            if not isinstance(pipeline_config,dict) or "roi" not in pipeline_config:
                raise ValueError("Explicit ROI is required; no automatic default painting area")
            roi=pipeline_config["roi"]
            if not isinstance(roi,dict) or not {"enabled","normalized","shape"}.issubset(roi):
                raise ValueError("Explicit ROI schema required")
            if roi.get("shape")=="rectangle" and "coordinates" not in roi:
                raise ValueError("Explicit rectangle coordinates required")
            if roi.get("shape")=="polygon" and "points" not in roi:
                raise ValueError("Explicit polygon points required")
            normalized=validate_config(pipeline_config)
            p=PipelineD(normalized,calibration_id=config["calibration_id"],source_session=config["session_id"])
            provider=SimulatedStability if simulate_stability else CorrespondenceStability if allow_correspondences else StabilityProvider
            p.stability=provider(source,config["calibration_id"])
            self.pipelines[source]=p;self.configs[source]=copy.deepcopy(normalized)

    def invalidate(self,source=None):
        """Reuse D's state barrier without fabricating an observation/timestamp."""
        targets=self.pipelines if source is None else {source:self.pipelines[source]}
        return {key:p._clear_state() for key,p in targets.items()}

    def error(self,reason,source=None,frame_id=None,details=None,invalidate=False):
        retired=self.invalidate(source) if invalidate else {}
        return {"accepted":False,"state":"INPUT_ERROR","decision_available":False,
                "source_id":source,"frame_id":frame_id,"reason":reason,"details":details,
                "used_for_confirmation":False,"tracks":[],"events":[],"invalidated_track_ids":retired}

    def process(self,record):
        if not isinstance(record,dict):
            return self.error("record_not_object",invalidate=True)
        source=record.get("source_id")
        if not identifier(source) or source not in self.pipelines:
            return self.error("unknown_or_missing_source")
        p=self.pipelines[source];kind=record.get("kind");session=record.get("session_id")
        frame_id=record.get("frame_id")
        if type(record.get("schema_version")) is not int or record.get("schema_version")!=1:
            return self.error("unsupported_record_schema",source,frame_id,invalidate=True)
        allowed={"schema_version","kind","source_id","session_id","frame_id","timestamp","received_timestamp",
                 "stability","oracle","image_size","coordinate_space","prediction","error",
                 "previous_session_id","calibration_id"}
        if set(record)-allowed:
            return self.error("unknown_record_fields",source,frame_id,invalidate=True)
        if kind=="reconnect":
            if not identifier(session):return self.error("invalid_reconnect_session",source,frame_id)
            if record.get("previous_session_id")!=p.source_session:
                return self.error("wrong_previous_session",source,frame_id)
            try:
                # A reconnect is a deliberate control event, never inferred from a data frame.
                result=p.reconnect(session,record.get("calibration_id"))
            except (ValueError,TypeError) as exc:
                return self.error("invalid_reconnect",source,frame_id,str(exc))
            self.last_size.pop(source,None)
            result["accepted"]=True
            return self._log(record,result,"reconnected_requires_new_entry",False)
        if session!=p.source_session:
            return self.error("wrong_source_session",source,frame_id)
        if kind=="disconnect":
            result=p.disconnect(frame_id,record.get("timestamp"),source_session=session)
            return self._log(record,result,"camera_disconnected",False)
        if kind not in ("prediction","missing","frame_error"):
            return self.error("unknown_record_kind",source,frame_id,invalidate=True)
        if not p.online:
            return self._log(record,{"accepted":False,"state":"CAMERA_OFFLINE","tracks":[],"events":[],
                                    "decision_available":False},"camera_offline_requires_reconnect",False)
        try:
            now=number(record.get("timestamp"),"timestamp")
            received=number(record.get("received_timestamp"),"received_timestamp")
            # Check the identical D gate before decoding prediction or clearing state.
            unused_now,unused_key,rejection=p._gate(frame_id,now,received)
            if rejection:
                return self._log(record,{"accepted":False,"reason":rejection,"tracks":[],"events":[],
                                        "decision_available":False},"frame_rejected_"+rejection,False)
            if kind=="prediction":
                detections,conversion=convert_prediction(record)
                previous_size=self.last_size.get(source)
                if previous_size is not None and previous_size!=record["image_size"]:
                    return self.error("image_size_changed_requires_reconnect",source,frame_id,invalidate=True)
            else:
                if "prediction" in record:raise ValueError("Missing/error record must not include predictions")
                detections,conversion=[],[]
            result=p.step(frame_id,now,detections,received_timestamp=received,
                          camera_context=record.get("stability"),source_session=session)
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            return self.error("invalid_frame_payload",source,frame_id,str(exc),invalidate=True)
        if result.get("accepted") and kind=="prediction":
            self.last_size[source]=list(record["image_size"])
        used=bool(kind=="prediction" and result.get("accepted") and result.get("decision_available") and
                  any(t["observed"] and t["ever_entered_roi"] and t["raw_contact_valid"] for t in result["tracks"]))
        if kind in ("missing","frame_error"):
            reason="frame_missing_no_new_evidence" if kind=="missing" else "frame_error_no_new_evidence"
        elif result.get("ambiguous_detection_indices"):
            reason="ambiguous_tracking_no_evidence_for_uncertain_hands"
        elif not result.get("decision_available"):
            reason=result.get("camera_stability",{}).get("reason",result.get("reason","decision_unavailable"))
        elif used:
            reason="observed_contact_added_to_phase_d"
        elif not detections:
            reason="valid_frame_without_hand"
        else:
            reason="no_confirmable_contact_see_track_reasons"
        output=self._log(record,result,reason,used)
        output["conversion"]=conversion
        if kind in ("missing","frame_error") and result.get("accepted"):
            output["state"]="FRAME_MISSING" if kind=="missing" else "FRAME_ERROR"
            output["decision_available"]=False
            output["current_image_available"]=False
        else:
            output["current_image_available"]=bool(kind=="prediction" and result.get("accepted"))
        return output

    def _log(self,record,result,reason,used):
        output=copy.deepcopy(result)
        output["pipeline_result"]=copy.deepcopy(result)
        output.update(source_id=record["source_id"],session_id=record.get("session_id"),
                      frame_id=record.get("frame_id"),kind=record.get("kind"),
                      timestamp=result.get("timestamp") if record.get("kind")=="disconnect" else record.get("timestamp"),
                      received_timestamp=None if record.get("kind") in ("disconnect","reconnect") else record.get("received_timestamp"),
                      reason=reason,used_for_confirmation=used,
                      decision_available=bool(result.get("decision_available",False)))
        output.setdefault("state","FRAME_REJECTED")
        output.setdefault("tracks",[]);output.setdefault("events",[])
        for event in output["events"]:
            event["source_id"]=record["source_id"]
            event["source_event_key"]=record["source_id"]+"::"+event["event_key"]
        output["interpretation"]="AI contact suspicion from 2D predictions; not proof of physical touch"
        return output
