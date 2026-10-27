"""Replay saved normalized detections only. No camera, model, torch, or database."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from .pipeline_v4 import PipelineV4,load_config
from .compare_v3_v4 import new_output_directory

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True,help="Existing prediction JSONL; not images")
    parser.add_argument("--scenario",help="Required to select one scenario from comparison inputs")
    parser.add_argument("--config",default=str(Path(__file__).with_name("config.v4.json")))
    parser.add_argument("--track-timeout",type=float,choices=(1.0,2.0,3.0),
                        help="Explicit comparison candidate, not a learned optimum")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.track_timeout is not None:
        config["tracking"]["max_idle_seconds"] = args.track_timeout
    source = Path(args.input).expanduser().resolve()
    raw = source.read_bytes()
    if len(raw)>10000000:
        parser.error("Replay input exceeds 10 MB experimental limit")
    frames = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    available = {r.get("scenario") for r in frames}
    if len(available)>1 and args.scenario is None:
        parser.error("Select one --scenario; do not concatenate independent source clocks")
    if args.scenario is not None:
        frames = [r for r in frames if r.get("scenario")==args.scenario]
    if not frames or len(frames)>4096:
        parser.error("Expected 1..4096 frames for this bounded replay")
    pipeline = PipelineV4(config)
    # Validate/compute before creating outputs; no writes if a malformed input raises.
    outputs = []
    for row in frames:
        if row.get("camera_disconnected") is True:
            outputs.append(pipeline.disconnect(row["frame_id"],row["timestamp"]))
        else:
            values = {key:row[key] for key in ("frame_id","timestamp","detections","received_timestamp") if key in row}
            outputs.append(pipeline.step(**values))
    directory = new_output_directory("replay_v4")
    with (directory/"effective_config.json").open("x") as handle:
        json.dump(pipeline.config,handle,indent=2)
    with (directory/"frames.jsonl").open("x",encoding="utf-8") as handle:
        for row in outputs:
            handle.write(json.dumps(row,allow_nan=False)+"\n")
    with (directory/"summary.json").open("x") as handle:
        json.dump({"input_file":str(source),"input_sha256":hashlib.sha256(raw).hexdigest(),
                   "input_origin":"external_predictions_unverified_not_inferred_here",
                   "accepted_frames":sum(r["accepted"] for r in outputs),
                   "rejected_frames":sum(not r["accepted"] for r in outputs),
                   "event_count":sum(len(r["events"]) for r in outputs),
                   "gpu_inference_run":False,"camera_opened":False,"accuracy":"NOT_EVALUATED",
                   "precision":"NOT_EVALUATED","recall":"NOT_EVALUATED","f1":"NOT_EVALUATED"},
                  handle,indent=2)
    print("ARTIFACTS="+str(directory))
    return 0

if __name__=="__main__":
    sys.exit(main())
