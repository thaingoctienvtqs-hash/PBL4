"""Separate five-vote window from time evidence and fast-path support."""
import math
from collections import deque
from ..pipeline_v4 import finite

class TemporalD:
    def __init__(self, config, thresholds):
        self.config=dict(config);self.thresholds=dict(thresholds)
        self.samples=deque(maxlen=config["window_frames"])
        self.evidence=deque()
        self.episode=0;self.emitted_episode=None;self.active=False;self.cooldown_until=0.0
        self.last_valid_at=None;self.last_observed_at=None;self.last_update=None
        self.ema_score=None;self.last_score=None

    def clear_evidence(self):
        self.samples.clear();self.evidence.clear()

    def update(self,now,detection,overlap,entry):
        now=finite(now)
        if self.last_update is not None and now<=self.last_update:
            raise ValueError("Temporal timestamps must increase")
        self.last_update=now
        c=self.config;observed=detection is not None
        raw_valid=bool(observed and overlap>=self.thresholds["minimum_overlap"] and
                       detection["object_contact_score"]>=self.thresholds["object_contact"])
        if entry["episode"]!=self.episode:
            self.episode=entry["episode"];self.clear_evidence();self.last_valid_at=None
        if self.last_observed_at is not None and now-self.last_observed_at>c["max_support_gap_seconds"]:
            self.clear_evidence()
        for queue in (self.samples,self.evidence):
            while queue and now-queue[0]["timestamp"]>c["max_evidence_age_seconds"]:
                queue.popleft()
        capacity=False
        if not observed:
            self.clear_evidence()
        else:
            score=detection["object_contact_score"]
            dt=None if self.last_observed_at is None else now-self.last_observed_at
            alpha=1.0 if dt is None else 1-math.exp(-dt/c["ema_tau_seconds"])
            self.ema_score=score if self.ema_score is None else self.ema_score+alpha*(score-self.ema_score)
            self.last_score=score;self.last_observed_at=now
            if entry["entered"]:
                if len(self.evidence)>=2048:
                    self.clear_evidence();capacity=True
                sample={"timestamp":now,"valid":raw_valid,"score":score}
                self.samples.append(sample);self.evidence.append(sample)
                if raw_valid:self.last_valid_at=now
        positive=sum(s["valid"] for s in self.samples)
        timeline=list(self.evidence)
        support=sum(min(b["timestamp"]-a["timestamp"],c["support_interval_cap_seconds"])
                    for a,b in zip(timeline,timeline[1:])
                    if a["valid"] and b["valid"] and b["timestamp"]-a["timestamp"]<=c["max_support_gap_seconds"])
        streak=[]
        for sample in reversed(timeline):
            if not sample["valid"] or sample["score"]<self.thresholds["fast_score"]:break
            streak.append(sample)
        fast_span=0.0 if len(streak)<2 else streak[0]["timestamp"]-streak[-1]["timestamp"]
        started=closed=False
        if self.active:
            grace=c["clear_after_seconds"] if observed else c["missing_grace_seconds"]
            if not entry["entered"] or self.last_valid_at is None or now-self.last_valid_at>=grace:
                self.active=False;self.cooldown_until=now+c["cooldown_seconds"]
                self.clear_evidence();positive=0;support=0.0
                state,reason,closed="COOLDOWN","contact_cleared_or_roi_exit",True
            else:
                state="ALERT";reason="contact_persists" if observed else "temporarily_unobserved_no_new_evidence"
        elif now<self.cooldown_until:
            state,reason="COOLDOWN","per_track_cooldown"
        elif not observed:
            state,reason="UNOBSERVED","missing_detection_no_evidence"
        elif overlap<self.thresholds["minimum_overlap"]:
            state,reason="OUTSIDE_ROI","outside_roi"
        elif not entry["entered"]:
            state,reason=("CANDIDATE","awaiting_roi_entry") if raw_valid else ("NO_CONTACT","object_contact_below_threshold")
        else:
            fast=raw_valid and len(streak)>=c["fast_frames"] and fast_span+1e-9>=c["fast_min_span_seconds"]
            window=raw_valid and positive>=c["minimum_frames"] and support+1e-9>=c["minimum_supported_seconds"]
            if not capacity and (fast or window):
                self.active=True;started=self.emitted_episode!=self.episode;self.emitted_episode=self.episode
                state,reason="ALERT","fast_contact_confirmed" if fast else "window_and_time_confirmed"
                if not started:reason="episode_resumed_no_duplicate_event"
            else:
                state,reason=("CANDIDATE","insufficient_temporal_support") if raw_valid else ("NO_CONTACT","current_frame_not_contact_valid")
        return {"state":state,"state_reason":reason,"event_started":started,"event_closed":closed,
                "alert_active":self.active,"raw_contact_valid":raw_valid,"positive_frames":positive,
                "support_seconds":support,"high_contact_streak":len(streak),"fast_span_seconds":fast_span,
                "ema_score_telemetry_only":self.ema_score,"history":[s["valid"] for s in self.samples],
                "time_evidence_count":len(self.evidence),"evidence_capacity_guard":capacity}
