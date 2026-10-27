"""Run frozen B/C and isolated D logic. Writes only a fresh phase_d/runs subdirectory."""
import ast
import hashlib
import importlib
import io
import json
import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from .compare import comparison

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
FROZEN_MODULES=(
    "debug.alert_diagnostics.v4.test_comparison",
    "debug.alert_diagnostics.v4.phase_c.test_adversarial",
    "debug.alert_diagnostics.v4.phase_c.test_metrics",
    "debug.alert_diagnostics.v4.phase_c.test_evaluator",
    "debug.alert_diagnostics.v4.phase_c.test_quality_gates",
)
KNOWN_FAILURES={
    "debug.alert_diagnostics.v4.phase_c.test_quality_gates.QualityGates.test_sustained_valid_contact_should_confirm_at_30fps",
    "debug.alert_diagnostics.v4.phase_c.test_quality_gates.QualityGates.test_camera_pan_should_not_alert_on_stationary_print",
    "debug.alert_diagnostics.v4.phase_c.test_quality_gates.QualityGates.test_crossing_should_not_transfer_id_between_actors",
    "debug.alert_diagnostics.v4.phase_c.test_quality_gates.QualityGates.test_disconnect_should_clear_active_state_even_when_cache_full",
    "debug.alert_diagnostics.v4.phase_c.test_quality_gates.FastPathQualityGate.test_fast_valid_contact_should_confirm_at_30fps",
}

def dump(path,data):
    with path.open("x",encoding="utf-8") as out:json.dump(data,out,indent=2,ensure_ascii=False,allow_nan=False)

def verify():
    snapshots={}
    for filename in ("protected_before.json","protected_extended_before.json"):
        path=BASE/filename
        if not path.exists():
            if filename=="protected_before.json":raise RuntimeError("Protected baseline missing")
            continue
        hashes=json.loads(path.read_text(encoding="utf-8"));rows=[]
        for relative,expected in hashes.items():
            p=ROOT/relative
            actual=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            rows.append({"path":relative,"before":expected,"after":actual,"unchanged":actual==expected})
        snapshots[filename]=rows
    return snapshots

def run_suite(modules):
    suite=unittest.TestSuite()
    for name in modules:suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    return {"tests":result.testsRun,"pass":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            "fail":len(result.failures),"error":len(result.errors),"skip":len(result.skipped),
            "failures":[{"test":t.id(),"traceback":tb} for t,tb in result.failures],
            "errors":[{"test":t.id(),"traceback":tb} for t,tb in result.errors],
            "output":stream.getvalue()}

def main():
    before=verify()
    if not all(r["unchanged"] for rows in before.values() for r in rows):
        raise RuntimeError("Protected files changed before tests; stopping")
    directory=BASE/"runs"/("logic_"+datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True,exist_ok=False)
    frozen=run_suite(FROZEN_MODULES)
    fixed=run_suite(("debug.alert_diagnostics.v4.phase_d.test_phase_d",))
    summaries,replays=comparison()
    for name,data in (("frozen_tests.json",frozen),("phase_d_tests.json",fixed),
                      ("comparison.json",summaries),("replays.json",replays)):
        dump(directory/name,data)
    checked=[]
    for p in sorted(BASE.rglob("*")):
        if p.is_file() and p.suffix==".py":
            ast.parse(p.read_text(encoding="utf-8"),filename=str(p));checked.append(str(p.relative_to(BASE)))
        elif p.is_file() and p.suffix==".json":
            json.loads(p.read_text(encoding="utf-8"))
    after=verify();dump(directory/"protected_after.json",after)
    unchanged=all(r["unchanged"] for rows in after.values() for r in rows)
    retained={r["test"] for r in frozen["failures"]}==KNOWN_FAILURES and frozen["error"]==0 and frozen["pass"]==98
    passed=unchanged and retained and fixed["fail"]==0 and fixed["error"]==0 and fixed["skip"]==0
    summary={"python":sys.version,"frozen_B_C":{k:frozen[k] for k in ("tests","pass","fail","error","skip")},
             "phase_d":{k:fixed[k] for k in ("tests","pass","fail","error","skip")},
             "old_five_failures_retained_without_test_edits":retained,"protected_files_unchanged":unchanged,
             "phase_d_python_files_parsed":checked,"comparison_rows":len(summaries),
             "real_camera_or_gpu_run":False,"logic_regression_check_pass":passed}
    dump(directory/"summary.json",summary)
    print(json.dumps(summary,indent=2));print("Artifacts:",directory)
    return 0 if passed else 1

if __name__=="__main__":sys.exit(main())
