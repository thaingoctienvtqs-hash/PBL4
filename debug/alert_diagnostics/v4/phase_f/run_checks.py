"""Frozen regression + F replay; all writes constrained to F, DB/network calls denied."""
import ast
import builtins
import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock
from .replay_f import BASE,output_directory
from ..phase_e.replay import write_json
from ..phase_d.run_tests import run_suite,FROZEN_MODULES,KNOWN_FAILURES
from ..phase_e.run_tests import RECOVERY_FAILURES
from .compare_f import compare
from .cases_f import cases_f
from ..phase_e.controlled_cases import controlled_cases

ROOT=BASE.parents[3]
INFORMATION_LIMIT="debug.alert_diagnostics.v4.phase_f.test_f.InformationLimitGate.test_geometry_must_not_alert_for_indistinguishable_new_hand"

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def verify():
    old=json.loads((BASE/"protected_before.json").read_text())
    return [{"path":p,"before":h,"after":digest(ROOT/p) if (ROOT/p).is_file() else None} for p,h in old.items()]

def counts(test):return {k:test[k] for k in ("tests","pass","fail","error","skip")}

@contextlib.contextmanager
def runtime_guard():
    root=BASE.resolve();attempts=[];writes=[]
    native_open=builtins.open;native_io=io.open;native_mkdir=os.mkdir
    def check(path,mode):
        if isinstance(path,int):return
        target=Path(path).resolve()
        if root not in target.parents and target!=root:
            attempts.append("write_outside_F");raise PermissionError("Only F writes allowed")
        if target.exists() and any(c in mode for c in "wa+"):
            attempts.append("overwrite_existing_file");raise FileExistsError(str(target))
        writes.append({"path":str(target.relative_to(root)),"mode":mode})
    def fopen(original):
        def wrapped(file,mode="r",*args,**kwargs):
            if any(c in mode for c in "wax+"):check(file,mode)
            return original(file,mode,*args,**kwargs)
        return wrapped
    def mkdir(path,*args,**kwargs):
        check(path,"mkdir");return native_mkdir(path,*args,**kwargs)
    def block(name):
        def call(*args,**kwargs):
            attempts.append(name);raise RuntimeError("Forbidden offline operation: "+name)
        return call
    with contextlib.ExitStack() as stack:
        for name in ("sqlite3.connect","sqlite3.dbapi2.connect","socket.create_connection","socket.socket.connect",
                     "os.remove","os.unlink","os.rename","os.replace"):
            stack.enter_context(mock.patch(name,side_effect=block(name)))
        stack.enter_context(mock.patch("builtins.open",side_effect=fopen(native_open)))
        stack.enter_context(mock.patch("io.open",side_effect=fopen(native_io)))
        stack.enter_context(mock.patch("os.mkdir",side_effect=mkdir))
        yield {"blocked_attempts":attempts,"writes":writes}

def execute(directory):
    before=verify()
    if any(r["before"]!=r["after"] for r in before):raise RuntimeError("Protected files differ before tests")
    frozen=run_suite(FROZEN_MODULES)
    d=run_suite(("debug.alert_diagnostics.v4.phase_d.test_phase_d",))
    e=run_suite(("debug.alert_diagnostics.v4.phase_e.test_adapter",))
    f=run_suite(("debug.alert_diagnostics.v4.phase_f.test_f","debug.alert_diagnostics.v4.phase_f.test_io_f"))
    for name,data in (("B_C.json",frozen),("D.json",d),("E_in_memory.json",e),("F.json",f)):
        write_json(directory/name,data)
    inputs=directory/"inputs";inputs.mkdir(exist_ok=False)
    rows=[];selected=controlled_cases()+cases_f()
    for index,case in enumerate(selected):
        prefix="{:02d}_{}".format(index,case["name"])
        input_path=inputs/(prefix+".jsonl")
        with input_path.open("x",encoding="utf-8") as out:
            for record in case["records"]:out.write(json.dumps(record,sort_keys=True,allow_nan=False)+"\n")
        write_json(inputs/(prefix+".settings.json"),case["settings"])
        for timeout in (1,2,3):
            comparison,replays=compare(case,timeout)
            comparison["input_sha256"]=digest(input_path)
            comparison["scenario_group"]="E_existing" if index<len(controlled_cases()) else "F_new_controlled"
            rows.append(comparison)
            with (directory/(prefix+"_timeout"+str(timeout)+".jsonl")).open("x",encoding="utf-8") as out:
                for i,record in enumerate(case["records"]):
                    out.write(json.dumps({"input":record,**{k:replays[k][i] for k in ("D","E","F_geometry","F_strict")}},
                                         allow_nan=False)+"\n")
    write_json(directory/"comparison.json",rows)
    after=verify();write_json(directory/"protected_after.json",after)
    parsed=[]
    for path in sorted(BASE.rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"),filename=str(path));parsed.append(path.name)
    for path in BASE.rglob("*.json"):json.loads(path.read_text(encoding="utf-8"))
    two=[]
    for name in ("explicit_missing_frame","explicit_frame_error"):
        row=next(r for r in rows if r["scenario_group"]=="F_new_controlled" and r["scenario"]==name and r["timeout_seconds"]==2)
        two.append({"scenario":name,"D_events":len(row["D"]["events"]),"E_events":len(row["E"]["events"]),
                    "F_geometry_events":len(row["F_geometry"]["events"]),"F_strict_events":len(row["F_strict"]["events"]),
                    "experiment_gate_pass":len(row["F_geometry"]["events"])==1 and row["F_geometry"]["wrongly_shared_ids"]==0})
    old_ok={v["test"] for v in frozen["failures"]}==KNOWN_FAILURES and frozen["error"]==0
    e_ok={v["test"] for v in e["failures"]}==RECOVERY_FAILURES and e["error"]==0
    summary={"python":sys.version,"B_C":counts(frozen),"D":counts(d),"E_in_memory":counts(e),"F":counts(f),
             "frozen_regression_behaviour_unchanged":old_ok and e_ok and d["fail"]==0 and d["error"]==0,
             "E_IO_tests_not_rerun":4,"E_IO_reason":"Would write frozen E; six equivalent F file tests run instead",
             "two_old_recovery_gates":two,"comparison_scenarios":len(selected),"comparison_rows":len(rows),
             "D_E_core_mismatches":sum(r["D_E_core_mismatches"] for r in rows),
             "protected_files":len(after),"protected_unchanged":all(r["before"]==r["after"] for r in after),
             "known_information_limit_failure_visible":{r["test"] for r in f["failures"]}=={INFORMATION_LIMIT},
             "camera_GPU_used":False,"model_metrics":"NOT_EVALUATED","python_parsed":parsed}
    write_json(directory/"summary.json",summary)
    return summary

def main():
    directory=output_directory(BASE/"runs")
    with runtime_guard() as guard:summary=execute(directory)
    guard["AI_modules_loaded"]=[name for name in ("torch","detectron2","cv2","fastapi","pyodbc") if name in sys.modules]
    write_json(directory/"runtime_guard.json",guard)
    print(json.dumps(summary,indent=2));print("Runtime blocked attempts:",len(guard["blocked_attempts"]))
    print("Artifacts:",directory)
    # Do not mask the unresolved geometry identity false-positive gate.
    return 1 if summary["F"]["fail"] or summary["F"]["error"] or guard["blocked_attempts"] or not summary["protected_unchanged"] or not summary["frozen_regression_behaviour_unchanged"] else 0

if __name__=="__main__":sys.exit(main())
