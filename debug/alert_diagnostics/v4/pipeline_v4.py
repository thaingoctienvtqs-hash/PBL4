"""Pure v4 pipeline with a monotonic source-clock contract and explicit rejection."""
import copy
import json
import math
from collections import deque
from pathlib import Path
from .tracking_v4 import Tracker
from .roi_entry_v4 import ROIEntry
from .temporal_v4 import TemporalContact
from src.core.geometry import (intersection_over_box_area, intersection_over_box_area_polygon,
                               validate_polygon, point_in_polygon)

DEFAULTS = {
    "schema_version": 4,
    "thresholds": {"hand_score":0.7,"object_contact":0.15,"fast_score":0.85,"minimum_overlap":0.3},
    "roi": {"enabled":True,"shape":"rectangle","normalized":True,
            "coordinates":[0.4,0.1,0.8,0.9],"points":[]},
    "tracking": {"max_idle_seconds":2.0,"max_distance":0.25,"reacquire_distance":0.1,
                 "prediction_horizon_seconds":0.5,"max_velocity":0.5,
                 "ambiguity_margin":0.05,"max_tracks":64},
    "entry": {"outside_overlap":0.2,"inside_overlap":0.4,
              "minimum_displacement":0.015,"entry_memory_seconds":10.0,
              "exit_confirm_seconds":0.4},
    "temporal": {"window_frames":5,"minimum_frames":3,"fast_frames":2,
                 "max_evidence_age_seconds":6.0,"max_support_gap_seconds":2.0,
                 "support_interval_cap_seconds":0.5,"minimum_supported_seconds":0.4,
                 "fast_min_span_seconds":0.2,"clear_after_seconds":0.75,
                 "missing_grace_seconds":2.0,"cooldown_seconds":60.0,"ema_tau_seconds":0.5},
    "input": {"max_frame_age_seconds":3.0,"frame_id_cache_size":4096,"max_detections":32}
}

def merge_checked(base, override):
    if not isinstance(override,dict):
        raise ValueError("Config section must be an object")
    result = copy.deepcopy(base)
    for key,value in override.items():
        if key not in base:
            raise ValueError("Unknown configuration key: "+key)
        result[key] = merge_checked(base[key],value) if isinstance(base[key],dict) else copy.deepcopy(value)
    return result

def finite(value):
    if isinstance(value,bool):
        raise ValueError("Boolean is not a numeric value")
    try:
        number = float(value)
    except (TypeError,ValueError):
        raise ValueError("Expected a finite number")
    if not math.isfinite(number):
        raise ValueError("Expected a finite number")
    return number

def validate_config(value=None):
    result = merge_checked(DEFAULTS,{} if value is None else value)
    if result["schema_version"] != 4:
        raise ValueError("Wrong schema version")
    if result["thresholds"] != DEFAULTS["thresholds"]:
        raise ValueError("ContactHands thresholds are frozen in this experimental phase")
    roi = result["roi"]
    if roi["enabled"] is not True or roi["normalized"] is not True:
        raise ValueError("Explicit enabled normalized ROI required")
    if roi["shape"] == "rectangle":
        r = [finite(v) for v in roi["coordinates"]]
        if len(r)!=4 or not all(0<=v<=1 for v in r) or r[0]>=r[2] or r[1]>=r[3]:
            raise ValueError("Invalid normalized ROI")
        if roi["points"]:
            raise ValueError("Rectangle cannot have polygon points")
        roi["coordinates"] = r
    elif roi["shape"] == "polygon":
        roi["points"] = [list(p) for p in validate_polygon(roi["points"],normalized=True)]
    else:
        raise ValueError("Unknown ROI shape")
    integer_keys = {"max_tracks","window_frames","minimum_frames","fast_frames",
                    "frame_id_cache_size","max_detections"}
    for section in ("tracking","entry","temporal","input"):
        for key,value in result[section].items():
            number = finite(value)
            if number<=0:
                raise ValueError(key+" must be positive")
            if key in integer_keys:
                if not isinstance(value,int) or isinstance(value,bool):
                    raise ValueError(key+" must be an integer")
            else:
                result[section][key] = number
    e,t = result["entry"],result["temporal"]
    if not 0<e["outside_overlap"]<result["thresholds"]["minimum_overlap"]<e["inside_overlap"]<=1:
        raise ValueError("ROI hysteresis bands must surround contact overlap threshold")
    if t["minimum_frames"]>t["window_frames"] or t["fast_frames"]>t["window_frames"]:
        raise ValueError("Temporal counts exceed window")
    if t["support_interval_cap_seconds"]>t["max_support_gap_seconds"]:
        raise ValueError("Support cap exceeds gap limit")
    if result["tracking"]["reacquire_distance"]>result["tracking"]["max_distance"]:
        raise ValueError("Reacquisition gate must be conservative")
    return result

def load_config(path):
    with Path(path).open(encoding="utf-8") as handle:
        return validate_config(json.load(handle))

def normalize_detections(detections, thresholds, maximum=32):
    if not isinstance(detections,list) or len(detections)>maximum:
        raise ValueError("Invalid detection list or too many detections")
    accepted,dropped = [],[]
    for index,raw in enumerate(detections):
        if not isinstance(raw,dict) or not isinstance(raw.get("box"),(list,tuple)) or len(raw["box"])!=4:
            raise ValueError("Invalid detection box")
        box = [finite(v) for v in raw["box"]]
        score,oc = finite(raw.get("hand_score",1.0)),finite(raw["object_contact_score"])
        if not 0<=score<=1 or not 0<=oc<=1 or box[0]>=box[2] or box[1]>=box[3]:
            raise ValueError("Invalid detection scores or empty/inverted box")
        clipped = [min(1.0,max(0.0,v)) for v in box]
        if clipped[0]>=clipped[2] or clipped[1]>=clipped[3] or score<thresholds["hand_score"]:
            dropped.append(index)
            continue
        accepted.append({"box":clipped,"hand_score":score,"object_contact_score":oc,
                         "input_index":index,"label":raw.get("label")})
    return accepted,dropped

class PipelineV4:
    def __init__(self, config=None):
        self.config = validate_config(config)
        self.tracker = Tracker(self.config["tracking"])
        self.entries,self.contacts = {},{}
        self.last_timestamp = None
        self.seen_ids,self.id_order = set(),deque()

    def _gate(self, frame_id, timestamp, received_timestamp):
        now = finite(timestamp)
        if isinstance(frame_id,bool) or not isinstance(frame_id,(str,int)) or not str(frame_id):
            raise ValueError("Frame ID must be a nonempty string or integer")
        key = str(frame_id)
        received = now if received_timestamp is None else finite(received_timestamp)
        if received<now:
            raise ValueError("Source and receive timestamps must share a clock; receive cannot precede source")
        if key in self.seen_ids:
            return now,key,"duplicate_frame"
        if len(self.seen_ids)>=self.config["input"]["frame_id_cache_size"]:
            return now,key,"frame_id_capacity_exceeded"
        if self.last_timestamp is not None and now<=self.last_timestamp:
            return now,key,"non_increasing_timestamp"
        if received-now>self.config["input"]["max_frame_age_seconds"]:
            return now,key,"stale_frame"
        return now,key,None

    def _commit_frame(self, key, now):
        self.last_timestamp = now
        self.seen_ids.add(key)
        self.id_order.append(key)

    def overlap(self, box):
        roi = self.config["roi"]
        if roi["shape"]=="polygon":
            return intersection_over_box_area_polygon(box,roi["points"])
        return intersection_over_box_area(box,roi["coordinates"])

    def center_inside(self, center):
        roi = self.config["roi"]
        if roi["shape"]=="polygon":
            return point_in_polygon(center,roi["points"])
        r = roi["coordinates"]
        return r[0]<=center[0]<=r[2] and r[1]<=center[1]<=r[3]

    def disconnect(self, frame_id, timestamp):
        now,key,rejection = self._gate(frame_id,timestamp,None)
        if rejection:
            return {"accepted":False,"reason":rejection,"tracks":[],"events":[]}
        retired = self.tracker.clear()
        self.entries,self.contacts = {},{}
        self._commit_frame(key,now)
        return {"accepted":True,"state":"CAMERA_DISCONNECTED","tracks":[],"events":[],
                "retired_track_ids":retired,"timestamp":now}

    def step(self, frame_id, timestamp, detections, received_timestamp=None):
        now,key,rejection = self._gate(frame_id,timestamp,received_timestamp)
        if rejection:
            return {"accepted":False,"reason":rejection,"tracks":[],"events":[]}
        detections,dropped = normalize_detections(detections,self.config["thresholds"],
                                                 self.config["input"]["max_detections"])
        previous_timestamp = self.last_timestamp
        result = self.tracker.update(detections,now)
        for track_id in result["expired_ids"]:
            self.entries.pop(track_id,None)
            self.contacts.pop(track_id,None)
        rows,events = [],[]
        for track_id,track in sorted(result["tracks"].items()):
            if track_id not in self.entries:
                self.entries[track_id] = ROIEntry(self.config["entry"])
                self.contacts[track_id] = TemporalContact(self.config["temporal"],self.config["thresholds"])
            entry_state = self.entries[track_id]
            det = detections[track["detection_index"]] if track["observed"] else None
            overlap = self.overlap(track["box"])
            if det is not None:
                entry = entry_state.update(now,track["center"],overlap,self.center_inside(track["center"]))
            else:
                entry = {"entered":entry_state.entered,"episode":entry_state.episode,"new_entry":False,
                         "entry_at":entry_state.entry_at,"exit_confirmed":False}
            decision = self.contacts[track_id].update(now,det,overlap,entry)
            row = dict(decision,track_id=track_id,new_track=track["new_track"],
                       observed=track["observed"],reacquired=track["reacquired"],
                       ever_entered_roi=entry["entered"],entry_episode=entry["episode"],
                       new_entry=entry["new_entry"],entry_at=entry["entry_at"],
                       object_contact_score=None if det is None else det["object_contact_score"],
                       roi_overlap=overlap,box=list(track["box"]),
                       input_index=None if det is None else det["input_index"],
                       label=None if det is None else det["label"],
                       matching_cost=track["matching_cost"],last_seen_gap_seconds=track["last_seen_gap"])
            rows.append(row)
            if decision["event_started"]:
                events.append({"event_key":"track_{}_episode_{}".format(track_id,entry["episode"]),
                               "track_id":track_id,"timestamp":now,"reason":decision["state_reason"]})
        self._commit_frame(key,now)
        state = "ALERT" if any(r["alert_active"] for r in rows) else (
            "CANDIDATE" if any(r["state"]=="CANDIDATE" for r in rows) else
            "NO_HAND" if not detections else "NO_CONFIRMED_CONTACT")
        return {"accepted":True,"frame_id":key,"timestamp":now,"state":state,"tracks":rows,
                "events":events,"tracking_delta_seconds":None if previous_timestamp is None else now-previous_timestamp,
                "expired_track_ids":result["expired_ids"],"new_track_ids":result["new_ids"],
                "ambiguous_detection_indices":result["ambiguous_detection_indices"],
                "untracked_indices":result["untracked_indices"],"dropped_detection_indices":dropped}
