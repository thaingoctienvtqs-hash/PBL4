"""Compare the unchanged v3 logic functions and v4 on the SAME controlled inputs."""
import copy
import json
import sys
import uuid
from datetime import datetime,timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from src import realtime_worker_integrated_v3 as v3
from src.core.contact_logic import analyze_predictions,advance_track_contact
from src.core.geometry import polygon_bounds
from src.utils.config_compat import DEFAULTS as V3_DEFAULTS
from .pipeline_v4 import PipelineV4,validate_config,normalize_detections
from .scenarios import scenarios

class BaselineV3:
    def __init__(self, config):
        self.config = validate_config(config)
        self.settings = copy.deepcopy(V3_DEFAULTS)
        self.settings["roi"] = copy.deepcopy(self.config["roi"])
        self.settings["roi"]["minimum_bbox_overlap"] = self.config["thresholds"]["minimum_overlap"]
        self.settings["alert"]["track_timeout_seconds"] = self.config["tracking"]["max_idle_seconds"]
        self.tracks,self.next_id = {},0

    def step(self, frame_id, timestamp, detections, received_timestamp=None):
        detections,dropped = normalize_detections(detections,self.config["thresholds"])
        roi = self.settings["roi"]
        polygon = roi["points"] if roi["shape"]=="polygon" else None
        pixel_roi = polygon_bounds(polygon) if polygon else roi["coordinates"]
        report = analyze_predictions([d["box"] for d in detections],
                                     [d["hand_score"] for d in detections],
                                     [[0,0,0,d["object_contact_score"]] for d in detections],
                                     pixel_roi,self.settings["thresholds"],
                                     self.config["thresholds"]["minimum_overlap"],roi_polygon=polygon)
        self.tracks,self.next_id,observations = v3.update_tracks(
            report["hands"],self.tracks,self.next_id,timestamp,
            self.settings["alert"]["track_match_distance_normalized"],
            self.settings["alert"]["track_timeout_seconds"],image_width=1,image_height=1,
            roi=pixel_roi,minimum_roi_overlap=self.config["thresholds"]["minimum_overlap"],
            alert_settings=self.settings["alert"],roi_polygon=polygon)
        hand_map = {h["index"]:h for h in report["hands"]}
        rows,events = [],[]
        for key,track in sorted(self.tracks.items()):
            hand = hand_map.get(track["hand_index"]) if track["frame_observed"] else None
            decision = advance_track_contact(track,hand,timestamp,self.settings["alert"],
                                             self.config["thresholds"]["object_contact"],
                                             self.config["thresholds"]["minimum_overlap"],True)
            rows.append({"track_id":key,"observed":track["frame_observed"],
                         "ever_entered_roi":track["ever_entered_roi"],"positive_frames":decision["positive_frames"],
                         "state":decision["state"],"state_reason":decision["reason"],
                         "event_started":decision["alert_started"],
                         "input_index":None if hand is None else detections[hand["index"]]["input_index"]})
            if decision["alert_started"]:
                events.append({"track_id":key,"timestamp":timestamp})
        return {"accepted":True,"frame_id":frame_id,"timestamp":timestamp,"tracks":rows,"events":events}

def evaluate(frames, timeout=2.0):
    config = validate_config({"tracking":{"max_idle_seconds":timeout}})
    baseline,experimental = BaselineV3(config),PipelineV4(config)
    old,new = [],[]
    for frame in frames:
        old.append(baseline.step(**frame))
        new.append(experimental.step(**frame))
    return old,new

def event_count(rows):
    return sum(len(r["events"]) for r in rows)

def id_count(rows):
    return len({t["track_id"] for r in rows for t in r["tracks"] if t["observed"]})

def new_output_directory(kind):
    here = Path(__file__).resolve().parent
    runs = here/"runs"
    if runs.is_symlink():
        raise ValueError("Symlink output is not allowed")
    runs.mkdir(exist_ok=True)
    directory = runs/("{}_{}_{}".format(kind,datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
                                       uuid.uuid4().hex[:8]))
    directory.mkdir(exist_ok=False)
    return directory

def write_comparison(directory):
    summary = []
    with (directory/"comparison.jsonl").open("x",encoding="utf-8") as log, (directory/"controlled_inputs.jsonl").open("x",encoding="utf-8") as inputs:
        for scenario,frames in sorted(scenarios().items()):
            for frame in frames:
                inputs.write(json.dumps(dict(frame,scenario=scenario),allow_nan=False)+"\n")
            for timeout in (1.0,2.0,3.0):
                old,new = evaluate(frames,timeout)
                summary.append({"scenario":scenario,"timeout_seconds":timeout,
                                "v3_events":event_count(old),"v4_events":event_count(new),
                                "v3_observed_ids":id_count(old),"v4_observed_ids":id_count(new)})
                for frame,old_row,new_row in zip(frames,old,new):
                    log.write(json.dumps({"scenario":scenario,"timeout_seconds":timeout,
                                          "input":frame,"v3":old_row,"v4":new_row},allow_nan=False)+"\n")
    with (directory/"comparison_summary.json").open("x") as handle:
        json.dump({"input_kind":"controlled_logic_not_model_predictions",
                   "baseline":"v3 pure functions; this is not its file-watch scheduler",
                   "metrics_status":"NOT_EVALUATED_ON_LABELED_DATA","rows":summary},handle,indent=2)
    return summary
