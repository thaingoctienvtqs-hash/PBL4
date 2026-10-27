"""Bounded, multi-hypothesis recovery with probation. Geometry is not identity proof."""
import copy
from ..phase_d.tracking_d import TrackerD
from ..tracking_v4 import center,distance,iou

class RecoveryTracker(TrackerD):
    def __init__(self,config,geometry_recovery=False,on_update=None):
        super().__init__(config)
        self.geometry_recovery=geometry_recovery
        self.on_update=on_update
        self.pending={}
        self.last_audit=[]
        self.required_observations=3
        self.recovery_window=min(1.5,self.config["max_idle_seconds"])

    def clear(self):
        self.pending={}
        self.last_audit=[]
        return super().clear()

    def candidate(self,anchor,current,det,now):
        gap=now-anchor["last_seen"]
        if gap>self.recovery_window or gap>self.config["max_idle_seconds"]:return None
        a=anchor["box"];b=det["box"]
        aw,ah=a[2]-a[0],a[3]-a[1];bw,bh=b[2]-b[0],b[3]-b[1]
        if not (.85<=bw/aw<=1.15 and .85<=bh/ah<=1.15):return None
        old_iou=iou(a,b)
        last_distance=distance(center(a),center(b))
        horizon=min(gap,self.config["prediction_horizon_seconds"])
        shift=tuple(anchor["velocity"][k]*horizon for k in (0,1))
        predicted=[a[0]+shift[0],a[1]+shift[1],a[2]+shift[0],a[3]+shift[1]]
        predicted_distance=distance(center(predicted),center(b))
        uncertainty=min(self.config["reacquire_distance"],.02+.08*gap)
        static=old_iou>=.75 and last_distance<=.025
        motion=old_iou>=.4 and iou(predicted,b)>=.6 and predicted_distance<=uncertainty
        if not static and not motion:return None
        if current["last_seen"]>anchor["last_seen"]:
            dt=now-current["last_seen"]
            if dt<=0 or distance(current["center"],center(b))>min(.05,self.config["max_velocity"]*dt+.01):return None
            if iou(current["box"],b)<.6:return None
        return {"model":"stationary" if static else "constant_velocity",
                "anchor_iou":old_iou,"predicted_distance":predicted_distance,
                "last_position_distance":last_distance,"uncertainty_radius":uncertainty,
                "gap_since_confirmed":gap}

    def update(self,detections,now):
        self.last_audit=[];retired=[];recovery_details={};old_pending=set(self.pending)
        # Pending observations do not extend the lifetime of the last confirmed identity.
        for key,pending in list(self.pending.items()):
            if now-pending["anchor"]["last_seen"]>self.recovery_window:
                if key in self.tracks:del self.tracks[key]
                del self.pending[key];retired.append(key)
                self.last_audit.append({"track_id":key,"reason":"recovery_timeout"})
        lost=[k for k,t in self.tracks.items() if not t["observed"] or k in self.pending]
        if not detections:
            for key in old_pending:
                if key in self.pending and key in self.tracks:
                    self.tracks[key]=copy.deepcopy(self.pending[key]["anchor"])
                    self.pending.pop(key,None)
            result=super().update(detections,now)
        else:
            choices={}
            for key in lost:
                track=self.tracks[key]
                anchor=self.pending[key]["anchor"] if key in self.pending else copy.deepcopy(track)
                eligible=[]
                if self.geometry_recovery:
                    for j,det in enumerate(detections):
                        detail=self.candidate(anchor,track,det,now)
                        if detail is not None:eligible.append((j,detail))
                choices[key]=(anchor,eligible)
            for key,(anchor,eligible) in choices.items():
                reason="strict_identity_no_external_identity_evidence" if not self.geometry_recovery else "no_supported_recovery"
                unique=len(eligible)==1
                if unique:
                    j,detail=eligible[0]
                    # Mutual exclusivity, including visible tracks competing for the candidate.
                    contenders=[other for other,(unused,options) in choices.items() if other!=key and any(k==j for k,v in options)]
                    competitors=[other for other,t in self.tracks.items() if other!=key and
                                 (distance(t["center"],center(detections[j]["box"]))<self.proximity or
                                  iou(t["box"],detections[j]["box"])>.1)]
                    nearby_detections=[other for other,det in enumerate(detections) if other!=j and
                                       (distance(center(det["box"]),center(detections[j]["box"]))<self.proximity or
                                        iou(det["box"],detections[j]["box"])>.1)]
                    unique=not contenders and not competitors and not nearby_detections
                    if nearby_detections:reason="multiple_recovery_candidates"
                    elif not unique:reason="ambiguous_recovery_component"
                elif len(eligible)>1:reason="multiple_recovery_candidates"
                if not unique:
                    self.tracks.pop(key,None);self.pending.pop(key,None);retired.append(key)
                    self.last_audit.append({"track_id":key,"reason":reason})
                    continue
                if key not in self.pending:
                    self.pending[key]={"anchor":anchor,"count":0,"first_at":now}
                # Select a supported motion hypothesis, without widening D's distance gate.
                if detail["model"]=="stationary":self.tracks[key]["velocity"]=(0.0,0.0)
                recovery_details[key]=(j,detail)
            result=super().update(detections,now)
        for key,track in result["tracks"].items():
            track["recovery_state"]="NORMAL"
            if key in recovery_details:
                expected_index,detail=recovery_details[key]
                pending=self.pending.get(key)
                if track["observed"] and track["detection_index"]==expected_index and pending is not None:
                    pending["count"]+=1
                    track["recovery_state"]="RECOVERED_GEOMETRY" if pending["count"]>=self.required_observations else "PROBATION"
                    track["recovery_observations"]=pending["count"]
                    track["recovery_detail"]=detail
                    track["reacquired"]=True
                    self.last_audit.append(dict(detail,track_id=key,reason=track["recovery_state"],
                                                observations=pending["count"],physical_identity_proven=False))
                    if track["recovery_state"]=="RECOVERED_GEOMETRY":self.pending.pop(key,None)
                else:
                    track["recovery_state"]="MISSING"
            elif not track["observed"]:track["recovery_state"]="MISSING"
        for key in list(self.pending):
            if key not in result["tracks"]:self.pending.pop(key,None)
        result["uncertain_track_ids"]=sorted(set(result["uncertain_track_ids"]+retired))
        result["recovery_audit"]=copy.deepcopy(self.last_audit)
        if self.on_update:self.on_update(result)
        return result
