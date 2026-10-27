"""Strict JSONL replay and exclusive artifact writing; never loads a camera or a model."""
import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from .offline_pipeline import OfflinePipeline

BASE=Path(__file__).resolve().parent
MAX_LINE_BYTES=256*1024

def reject_constant(value):
    raise ValueError("Non-finite JSON constant "+value)

def unique_pairs(pairs):
    obj={}
    for key,value in pairs:
        if key in obj:raise ValueError("Duplicate JSON key "+key)
        obj[key]=value
    return obj

def parse_line(line):
    return json.loads(line,parse_constant=reject_constant,object_pairs_hook=unique_pairs)

def replay_lines(lines,pipeline):
    for index,line in enumerate(lines,1):
        line_hash=hashlib.sha256(line.encode("utf-8")).hexdigest()
        try:
            if len(line.encode("utf-8"))>MAX_LINE_BYTES:raise ValueError("JSONL line exceeds size limit")
            if not line.strip():raise ValueError("Blank JSONL record")
            record=parse_line(line)
        except (ValueError,TypeError) as exc:
            result=pipeline.error("invalid_jsonl",details=str(exc),invalidate=True)
        else:
            result=pipeline.process(record)
        result["line_number"]=index
        result["input_line_sha256"]=line_hash
        yield result

def summarize(logs,expected_events=None):
    events=[e for row in logs for e in row.get("events",[])]
    reasons={}
    for row in logs:
        if not row.get("used_for_confirmation"):
            reason=row["reason"];reasons[reason]=reasons.get(reason,0)+1
    result={"records":len(logs),"accepted":sum(bool(r.get("accepted")) for r in logs),
            "rejected":sum(not r.get("accepted",False) for r in logs),
            "unavailable_records":sum(not r.get("decision_available",False) for r in logs),
            "confirmation_records":sum(bool(r.get("used_for_confirmation")) for r in logs),
            "event_count":len(events),"events":events,"non_confirmation_reasons":reasons,
            "evaluation_kind":"controlled_offline_predictions_not_AI_model_metrics"}
    if expected_events is not None:
        result["controlled_expected_events"]=expected_events
        result["controlled_event_shortfall"]=max(0,expected_events-len(events))
    return result

def write_json(path,value):
    with path.open("x",encoding="utf-8") as out:json.dump(value,out,ensure_ascii=False,indent=2,allow_nan=False)

def new_output_directory(parent=None):
    parent=(BASE/"runs" if parent is None else Path(parent)).resolve()
    base=BASE.resolve()
    if parent==base or base not in parent.parents:
        raise ValueError("Output parent must be inside phase_e, in a separate subdirectory")
    path=parent/("offline_"+datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:8])
    path.mkdir(parents=True,exist_ok=False)
    return path

def replay_file(input_path,config_path,simulate_stability=False,output_parent=None):
    config=parse_line(Path(config_path).read_text(encoding="utf-8"))
    pipeline=OfflinePipeline(config,simulate_stability=simulate_stability)
    output=new_output_directory(output_parent)
    input_path=Path(input_path)
    digest=hashlib.sha256();logs=[]
    # Read binary lines: preserve exact hash and limit each line's memory.
    with input_path.open("rb") as handle,(output/"frames.jsonl").open("x",encoding="utf-8") as log:
        index=0
        while True:
            raw=handle.readline(MAX_LINE_BYTES+1)
            if not raw:break
            index+=1;digest.update(raw)
            if len(raw)>MAX_LINE_BYTES:
                while raw and not raw.endswith(b"\n"):
                    raw=handle.readline(MAX_LINE_BYTES+1);digest.update(raw)
                result=pipeline.error("oversized_jsonl_record",invalidate=True)
                result.update(line_number=index,input_line_sha256=None)
            else:
                try:line=raw.decode("utf-8")
                except UnicodeDecodeError:
                    result=pipeline.error("invalid_utf8_jsonl",invalidate=True)
                    result.update(line_number=index,input_line_sha256=hashlib.sha256(raw).hexdigest())
                else:
                    result=next(replay_lines((line,),pipeline))
                    result["line_number"]=index
            log.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+"\n")
            logs.append(result)
    summary=summarize(logs)
    summary.update(input_sha256=digest.hexdigest(),input_path=str(input_path.resolve()),
                   config=config,simulate_stability=simulate_stability,
                   real_camera_or_gpu_run=False)
    write_json(output/"summary.json",summary)
    return output,summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True)
    parser.add_argument("--config",required=True)
    parser.add_argument("--simulate-stability",action="store_true",
                        help="Explicitly trust controlled test signals, never real camera stability")
    parser.add_argument("--output-parent",default=None)
    args=parser.parse_args()
    output,summary=replay_file(args.input,args.config,args.simulate_stability,args.output_parent)
    print(json.dumps({"output":str(output),"summary":summary},indent=2))
    # Fail loudly on corrupted/rejected records; expected adversarial fixture rejects are reported too.
    return 1 if summary["rejected"] else 0

if __name__=="__main__":sys.exit(main())
