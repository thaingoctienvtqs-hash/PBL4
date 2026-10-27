"""Compose F association/probation with original D ROI and temporal implementations."""
import copy
from ..phase_d.pipeline_d import PipelineD
from ..phase_d.temporal_d import TemporalD
from ..roi_entry_v4 import ROIEntry
from ..phase_e.offline_pipeline import OfflinePipeline
from .recovery_tracker import RecoveryTracker

class DeferredEntry:
    def __init__(self,config,track):
        self.inner=ROIEntry(config);self.track=track
        self.buffer=[];self.timeline=[]

    @property
    def entered(self):
        return False if self.track.get("recovery_state")=="PROBATION" else self.inner.entered
    @property
    def episode(self):return self.inner.episode
    @property
    def entry_at(self):return self.inner.entry_at

    def update(self,now,center,overlap,inside):
        status=self.track.get("recovery_state")
        self.timeline=[]
        if status=="PROBATION":
            self.buffer.append((now,center,overlap,inside))
            return {"entered":False,"episode":self.inner.episode,"entry_at":None,
                    "new_entry":False,"exit_confirmed":False}
        if status=="RECOVERED_GEOMETRY":
            for t,c,o,i in self.buffer+[(now,center,overlap,inside)]:
                self.timeline.append((t,self.inner.update(t,c,o,i)))
            self.buffer=[]
            return self.timeline[-1][1]
        self.buffer=[]
        return self.inner.update(now,center,overlap,inside)

class DeferredTemporal:
    def __init__(self,config,thresholds,entry,track,current_frame):
        self.config=config;self.thresholds=thresholds;self.entry=entry;self.track=track
        self.inner=TemporalD(config,thresholds);self.buffer=[];self.current_frame=current_frame

    def update(self,now,detection,overlap,entry):
        status=self.track.get("recovery_state")
        if status=="PROBATION" and detection is not None:
            self.buffer.append((now,copy.deepcopy(detection),overlap,self.current_frame()))
            return {"state":"RECOVERY_PENDING","state_reason":"identity_probation_no_contact_confirmation",
                    "event_started":False,"event_closed":False,"alert_active":False,"raw_contact_valid":False,
                    "positive_frames":0,"support_seconds":0.0,"high_contact_streak":0,"fast_span_seconds":0.0,
                    "ema_score_telemetry_only":None,"history":[],"time_evidence_count":0,
                    "evidence_capacity_guard":False,"quarantined_observations":len(self.buffer)}
        if status=="RECOVERED_GEOMETRY" and detection is not None:
            evidence=self.buffer+[(now,copy.deepcopy(detection),overlap,self.current_frame())]
            entries=dict(self.entry.timeline)
            old_emitted=self.inner.emitted_episode
            fresh=TemporalD(self.config,self.thresholds)
            fresh.emitted_episode=old_emitted
            fresh.cooldown_until=self.inner.cooldown_until
            started=False;confirmed_at=None
            for timestamp,det,roi,frame_id in evidence:
                decision=fresh.update(timestamp,det,roi,entries[timestamp])
                if decision["event_started"]:started=True;confirmed_at=timestamp
            # Do not publish a retrospective start from a now-invalid observation.
            publish=started and decision["alert_active"] and decision["raw_contact_valid"]
            if started and not publish:
                fresh.active=False;fresh.emitted_episode=old_emitted;fresh.clear_evidence()
                decision.update(state="NO_CONTACT",state_reason="recovery_current_score_not_valid",
                                alert_active=False,positive_frames=0,support_seconds=0,time_evidence_count=0,history=[])
            decision["event_started"]=publish
            decision["recovery_evidence_frame_ids"]=[sample[3] for sample in evidence]
            decision["recovery_first_confirmation_timestamp"]=confirmed_at
            decision["physical_identity_proven"]=False
            self.inner=fresh;self.buffer=[]
            return decision
        self.buffer=[]
        if detection is None:self.entry.buffer=[]
        return self.inner.update(now,detection,overlap,entry)

class PipelineF(PipelineD):
    def __init__(self,config=None,geometry_recovery=False,**kwargs):
        super().__init__(config,**kwargs)
        self.current_frame=None
        self.tracker=RecoveryTracker(self.config["tracking"],geometry_recovery,self.prepare_tracks)

    def prepare_tracks(self,result):
        for key,track in result["tracks"].items():
            if key not in self.entries:
                entry=DeferredEntry(self.config["entry"],track)
                self.entries[key]=entry
                self.contacts[key]=DeferredTemporal(self.config["temporal"],self.config["thresholds"],
                                                   entry,track,lambda:self.current_frame)
            else:
                self.entries[key].track=track;self.contacts[key].track=track

    def step(self,frame_id,timestamp,detections,**kwargs):
        self.current_frame=str(frame_id)
        result=super().step(frame_id,timestamp,detections,**kwargs)
        if result.get("accepted"):
            pending=False
            for row in result["tracks"]:
                track=self.tracker.tracks[row["track_id"]]
                row["recovery_state"]=track.get("recovery_state")
                row["identity_basis"]="geometry_only_not_physical_identity_proof"
                row["track_id_is_tentative"]=row["recovery_state"]=="PROBATION"
                pending=pending or row["recovery_state"]=="PROBATION"
            result["recovery_audit"]=copy.deepcopy(self.tracker.last_audit)
            if pending and result.get("state")!="ALERT":
                result["state"]="RECOVERY_PENDING";result["decision_available"]=False
        return result

class OfflineF(OfflinePipeline):
    def __init__(self,settings,simulate_stability=False,geometry_recovery=False):
        super().__init__(settings,simulate_stability)
        for source,old in list(self.pipelines.items()):
            pipeline=PipelineF(old.config,geometry_recovery,calibration_id=old.calibration_id,
                               source_session=old.source_session)
            pipeline.stability=old.stability
            self.pipelines[source]=pipeline
