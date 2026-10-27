"""Injectable stability interface. Simulation and image evidence remain distinct."""
from ..phase_d.camera_stability import BackgroundStability
from .prediction_adapter import number

class StabilityProvider:
    def __init__(self,source_id,reference_id):
        self.source_id=source_id
        self.reference_id=reference_id

    def assess(self,frame_id,timestamp,session,context):
        return {"status":"UNKNOWN","stable":False,"reason":"no_verified_image_stability"}

class SimulatedStability(StabilityProvider):
    """Offline-only signals; no claim of extracting background motion from images."""
    def assess(self,frame_id,timestamp,session,context):
        result={"status":"UNKNOWN","stable":False,"reason":"missing_simulated_signal",
                "evidence_kind":"controlled_offline_signal","image_extraction_validated":False}
        if not isinstance(context,dict):return result
        expected={"frame_id":str(frame_id),"source_id":self.source_id,
                  "session_id":session,"reference_id":self.reference_id}
        if any(context.get(k)!=v for k,v in expected.items()):
            result["reason"]="stability_binding_mismatch";return result
        try:
            if abs(number(context.get("timestamp"),"stability timestamp")-timestamp)>1e-8:
                result["reason"]="stale_stability_signal";return result
        except ValueError:
            result["reason"]="invalid_stability_timestamp";return result
        status=context.get("status")
        if status not in ("STABLE","MOVING","UNKNOWN"):
            result["reason"]="invalid_stability_status";return result
        result.update(status=status,stable=status=="STABLE",reason="explicit_offline_"+status.lower())
        return result

class CorrespondenceStability(StabilityProvider):
    """Future explicit opt-in, still uses D validation; no extractor implemented."""
    def assess(self,frame_id,timestamp,session,context):
        if not isinstance(context,dict) or context.get("source_id")!=self.source_id:
            return {"status":"UNKNOWN","stable":False,"reason":"background_source_mismatch"}
        validator=BackgroundStability(self.reference_id,test_mode=False,allow_external=True)
        return validator.assess(frame_id,timestamp,session,context)
