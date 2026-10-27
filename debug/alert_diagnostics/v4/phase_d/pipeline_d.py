"""Isolated fixes, explicit camera stability and reconnect session boundaries."""
import copy
import json
from collections import deque
from ..pipeline_v4 import PipelineV4,finite,normalize_detections,DEFAULTS
from ..roi_entry_v4 import ROIEntry
from .tracking_d import TrackerD
from .temporal_d import TemporalD
from .camera_stability import BackgroundStability

class PipelineD(PipelineV4):
    def __init__(self,config=None,calibration_id=None,source_session="session0",test_mode=False,
                 allow_external_background=False):
        super().__init__(config)
        if not isinstance(source_session,str) or not source_session:raise ValueError("Source session required")
        self.tracker=TrackerD(self.config["tracking"])
        self.test_mode=test_mode;self.source_session=source_session
        self.session_history={source_session};self.online=True
        self.calibration_id=calibration_id
        self.stability=BackgroundStability(calibration_id,test_mode,allow_external_background)
        self.roi_signature=json.dumps(self.config["roi"],sort_keys=True,allow_nan=False)

    def _clear_state(self):
        ids=self.tracker.clear();self.entries={};self.contacts={}
        return ids

    def disconnect(self,frame_id=None,timestamp=None,source_session=None):
        # Control path precedes frame cache, dedup, age and source timestamp filters.
        if source_session is not None and source_session!=self.source_session:
            return {"accepted":False,"reason":"wrong_control_session","tracks":[],"events":[]}
        retired=self._clear_state();self.online=False
        try:
            ts=finite(timestamp);valid=True
        except (ValueError,TypeError):
            ts=None;valid=False
        return {"accepted":True,"state":"CAMERA_OFFLINE","tracks":[],"events":[],
                "retired_track_ids":retired,"timestamp":ts,"control_timestamp_valid":valid,
                "decision_available":False,"source_session":self.source_session}

    def reconnect(self,new_session,calibration_id):
        if not isinstance(new_session,str) or not new_session or new_session in self.session_history:
            raise ValueError("Reconnect must use a new source session")
        if not isinstance(calibration_id,str) or not calibration_id:
            raise ValueError("Fresh calibration reference identifier required")
        retired=self._clear_state()
        self.source_session=new_session;self.session_history.add(new_session);self.calibration_id=calibration_id
        self.stability.reference_id=calibration_id
        self.seen_ids=set();self.id_order=deque();self.last_timestamp=None;self.online=True
        self.roi_signature=json.dumps(self.config["roi"],sort_keys=True,allow_nan=False)
        return {"state":"CAMERA_UNVERIFIED","decision_available":False,"tracks":[],"events":[],
                "retired_track_ids":retired,"source_session":new_session}

    def step(self,frame_id,timestamp,detections,received_timestamp=None,camera_context=None,source_session=None):
        if not self.online:
            return {"accepted":False,"reason":"camera_offline_requires_reconnect","state":"CAMERA_OFFLINE",
                    "tracks":[],"events":[],"decision_available":False}
        if source_session is None and not self.test_mode:
            return {"accepted":False,"reason":"missing_source_session","tracks":[],"events":[],"decision_available":False}
        session=self.source_session if source_session is None else source_session
        if session!=self.source_session:
            return {"accepted":False,"reason":"wrong_source_session","tracks":[],"events":[],"decision_available":False}
        now,key,rejection=self._gate(frame_id,timestamp,received_timestamp)
        if rejection:return {"accepted":False,"reason":rejection,"tracks":[],"events":[],"decision_available":False}
        detections,dropped=normalize_detections(detections,self.config["thresholds"],self.config["input"]["max_detections"])
        if self.config["thresholds"]!=DEFAULTS["thresholds"]:
            self._clear_state()
            raise ValueError("ContactHands thresholds must remain frozen")
        if json.dumps(self.config["roi"],sort_keys=True,allow_nan=False)!=self.roi_signature:
            retired=self._clear_state()
            return {"accepted":False,"state":"NEEDS_RECALIBRATION","reason":"roi_changed_requires_new_pipeline",
                    "retired_track_ids":retired,"tracks":[],"events":[],"decision_available":False}
        camera=self.stability.assess(key,now,session,camera_context)
        previous=self.last_timestamp
        if not camera["stable"]:
            retired=self._clear_state();self._commit_frame(key,now)
            return {"accepted":True,"frame_id":key,"timestamp":now,"tracks":[],"events":[],
                    "state":"CAMERA_MOVING" if camera["status"]=="MOVING" else "CAMERA_UNVERIFIED",
                    "decision_available":False,"camera_stability":camera,"retired_track_ids":retired}
        result=self.tracker.update(detections,now)
        for track_id in set(result["expired_ids"]+result["uncertain_track_ids"]):
            self.entries.pop(track_id,None);self.contacts.pop(track_id,None)
        rows,events=[],[]
        for track_id,track in sorted(result["tracks"].items()):
            if track_id not in self.entries:
                self.entries[track_id]=ROIEntry(self.config["entry"])
                self.contacts[track_id]=TemporalD(self.config["temporal"],self.config["thresholds"])
            entry_state=self.entries[track_id]
            det=detections[track["detection_index"]] if track["observed"] else None
            overlap=self.overlap(track["box"])
            if det is not None:
                entry=entry_state.update(now,track["center"],overlap,self.center_inside(track["center"]))
            else:
                entry={"entered":entry_state.entered,"episode":entry_state.episode,"new_entry":False,
                       "entry_at":entry_state.entry_at,"exit_confirmed":False}
            decision=self.contacts[track_id].update(now,det,overlap,entry)
            row=dict(decision,track_id=track_id,new_track=track["new_track"],observed=track["observed"],
                     reacquired=track["reacquired"],ever_entered_roi=entry["entered"],entry_episode=entry["episode"],
                     entry_at=entry["entry_at"],new_entry=entry["new_entry"],roi_overlap=overlap,
                     object_contact_score=None if det is None else det["object_contact_score"],
                     input_index=None if det is None else det["input_index"],label=None if det is None else det["label"],
                     box=list(track["box"]),matching_cost=track["matching_cost"],last_seen_gap_seconds=track["last_seen_gap"])
            rows.append(row)
            if decision["event_started"]:
                events.append({"event_key":"{}_track_{}_episode_{}".format(session,track_id,entry["episode"]),
                               "track_id":track_id,"timestamp":now,"reason":decision["state_reason"]})
        self._commit_frame(key,now)
        state="ALERT" if any(r["alert_active"] for r in rows) else (
            "TRACK_UNCERTAIN" if result["ambiguous_detection_indices"] else
            "CANDIDATE" if any(r["state"]=="CANDIDATE" for r in rows) else
            "NO_HAND" if not detections else "NO_CONFIRMED_CONTACT")
        return {"accepted":True,"frame_id":key,"timestamp":now,"state":state,"decision_available":True,
                "camera_stability":camera,"tracks":rows,"events":events,"source_session":session,
                "tracking_delta_seconds":None if previous is None else now-previous,
                "expired_track_ids":result["expired_ids"],"new_track_ids":result["new_ids"],
                "uncertain_track_ids":result["uncertain_track_ids"],
                "ambiguous_detection_indices":result["ambiguous_detection_indices"],
                "untracked_indices":result["untracked_indices"],"dropped_detection_indices":dropped}
