"""Run all suites, retain genuine quality FAILs and write new phase-C artifacts."""
import copy
import hashlib
import io
import json
import sys
import unittest
import uuid
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
from .. import test_comparison
from . import test_adversarial,test_metrics,test_evaluator,test_quality_gates
from .audit_scenarios import cases,summarize

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]

def main():
    runs=HERE/"runs"
    if runs.is_symlink():raise ValueError("Unsafe output path")
    runs.mkdir(exist_ok=True)
    directory=runs/("audit_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:8])
    directory.mkdir(exist_ok=False)
    groups={}
    for name,module in (("baseline_40",test_comparison),("adversarial_characterization",test_adversarial),
                        ("metrics_arithmetic",test_metrics),("evaluator_contract",test_evaluator),
                        ("desired_quality_gates",test_quality_gates)):
        stream=io.StringIO()
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        groups[name]={"tests":result.testsRun,"pass":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
                      "fail":len(result.failures),"error":len(result.errors),
                      "failures":[{"test":str(t),"traceback":text} for t,text in result.failures+result.errors]}
        with (directory/(name+".txt")).open("x") as handle:handle.write(stream.getvalue())
        print(name,json.dumps({k:groups[name][k] for k in ("tests","pass","fail","error")}))
    comparison=[]
    with (directory/"comparisons.jsonl").open("x") as log,(directory/"controlled_inputs.jsonl").open("x") as inputs:
        for name,frames in sorted(cases().items()):
            for frame in frames:inputs.write(json.dumps(dict(frame,scenario=name),allow_nan=False)+"\n")
            for timeout in (1,2,3):
                summary,old,new=summarize(name,frames,timeout);comparison.append(summary)
                for frame,a,b in zip(frames,old,new):
                    canonical=json.dumps(frame,sort_keys=True,separators=(",",":")).encode()
                    log.write(json.dumps({"scenario":name,"timeout_seconds":timeout,"input":frame,
                                          "shared_input_sha256":hashlib.sha256(canonical).hexdigest(),
                                          "v3":a,"v4":b},allow_nan=False)+"\n")
    protected=json.loads((HERE/"protected_before.json").read_text())
    after={}
    for name in protected:
        h=hashlib.sha256()
        with (ROOT/name).open("rb") as handle:
            for block in iter(lambda:handle.read(1048576),b""):h.update(block)
        after[name]=h.hexdigest()
    summary={"python":sys.version,"groups":groups,"total_tests":sum(g["tests"] for g in groups.values()),
             "total_pass":sum(g["pass"] for g in groups.values()),"total_fail":sum(g["fail"] for g in groups.values()),
             "total_error":sum(g["error"] for g in groups.values()),"comparison":comparison,
             "protected_unchanged":{name:protected[name]==after[name] for name in protected},
             "heavy_modules_loaded":[m for m in ("torch","cv2","detectron2") if m in sys.modules],
             "gpu_inference_run":False,"camera_opened":False,"database_opened":False,
             "real_accuracy_precision_recall_f1":"NOT_EVALUATED",
             "unit_PASS_is_not_model_quality_PASS":True}
    with (directory/"audit_summary.json").open("x") as handle:json.dump(summary,handle,indent=2)
    print("ARTIFACTS="+str(directory))
    print("PROTECTED_UNCHANGED",all(summary["protected_unchanged"].values()),len(protected))
    # Nonzero exit is intentional when quality requirements remain unmet.
    return 1 if summary["total_fail"] or summary["total_error"] or not all(summary["protected_unchanged"].values()) else 0

if __name__=="__main__":
    sys.exit(main())
