"""JSONL replay using immutable E parsing and F-specific exclusive output paths."""
import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from ..phase_e.replay import replay_lines,summarize,parse_line,write_json,MAX_LINE_BYTES
from .pipeline_f import OfflineF
BASE=Path(__file__).resolve().parent

def output_directory(parent=None):
    root=BASE.resolve();parent=(root/"runs" if parent is None else Path(parent)).resolve()
    if root not in parent.parents:raise ValueError("Output must be in a subdirectory of phase_f")
    path=parent/("offline_"+datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:8])
    path.mkdir(parents=True,exist_ok=False)
    return path

def replay_file(input_path,settings_path,geometry_recovery=False,simulate_stability=False,output_parent=None):
    config=parse_line(Path(settings_path).read_text(encoding="utf-8"))
    model=OfflineF(config,simulate_stability,geometry_recovery)
    output=output_directory(output_parent);logs=[]
    import hashlib
    digest=hashlib.sha256()
    with Path(input_path).open("rb") as stream,(output/"frames.jsonl").open("x",encoding="utf-8") as out:
        index=0
        while True:
            raw=stream.readline(MAX_LINE_BYTES+1)
            if not raw:break
            index+=1;digest.update(raw)
            if len(raw)>MAX_LINE_BYTES:
                while raw and not raw.endswith(b"\n"):
                    raw=stream.readline(MAX_LINE_BYTES+1);digest.update(raw)
                result=model.error("oversized_jsonl_record",invalidate=True)
            else:
                try:text=raw.decode("utf-8")
                except UnicodeDecodeError:result=model.error("invalid_utf8_jsonl",invalidate=True)
                else:result=next(replay_lines([text],model))
            result["line_number"]=index
            out.write(json.dumps(result,allow_nan=False)+"\n");logs.append(result)
    summary=summarize(logs)
    summary.update(input_sha256=digest.hexdigest(),geometry_recovery=geometry_recovery,
                   simulate_stability=simulate_stability,real_camera_or_gpu_run=False)
    write_json(output/"summary.json",summary)
    return output,summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True);parser.add_argument("--config",required=True)
    parser.add_argument("--geometry-recovery",action="store_true",help="Experimental, residual identity FP documented")
    parser.add_argument("--simulate-stability",action="store_true")
    args=parser.parse_args()
    path,summary=replay_file(args.input,args.config,args.geometry_recovery,args.simulate_stability)
    print(json.dumps({"output":str(path),"summary":summary},indent=2))
    return 1 if summary["rejected"] else 0

if __name__=="__main__":sys.exit(main())
