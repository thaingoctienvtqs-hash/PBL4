"""Bounded selected regressions, never whole-repository pytest or inference."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root",required=True)
    p.add_argument("--with-sql",action="store_true")
    a=p.parse_args()
    run=Path(a.run_root).resolve()
    if not run.is_dir() or run==ROOT or ROOT in run.parents:
        p.error("Existing external TEST artifacts directory required")
    output=run/("checks_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir()
    env=os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1",TEMP=str(run/"tmp"),TMP=str(run/"tmp"),
               ARTGUARD_TEST_ARTIFACTS=str(run/"tmp"))
    python=str(ROOT/"web/backend/.venv/Scripts/python.exe")
    prefix=[python,"-B","-X","utf8"]
    suites=[
        ("stepA_core",prefix+["debug/minimal_demo/test_evidence_api.py"]),
        ("stepA_http",prefix+["debug/minimal_demo/test_evidence_http.py"]),
        ("ingest_core",prefix+["debug/minimal_demo/test_ai_event_ingest.py"]),
        ("ingest_http",prefix+["debug/minimal_demo/test_ai_event_ingest_http.py"]),
        ("sender_camera_worker_probe_logic",prefix+["-m","unittest",
            "debug.full_integration.test_event_sender",
            "debug.full_integration.test_camera_receiver",
            "debug.full_integration.test_worker_test_runner",
            "debug.full_integration.test_inference_probe"]),
        ("launcher_e2e_logic",prefix+["-m","unittest",
            "debug.full_integration.test_launch_test","debug.full_integration.test_software_e2e"]),
        ("frontend_helpers",[r"C:\Program Files\nodejs\node.exe",
            str(ROOT/"debug/full_integration/test_frontend_helpers.mjs"),"--artifacts",str(run/"tmp")]),
        ("diff_check",["git","diff","--check"]),
    ]
    if a.with_sql:
        env["ARTGUARD_INTEGRATION_CONFIG"]=str(run/"integration_config.json")
        suites.append(("sql_TEST",prefix+["debug/full_integration/test_sql_integration.py"]))
    report={"run":str(run),"suites":[],"camera":False,"inference":False,
            "sql_TEST_optin":a.with_sql,"whole_repo_pytest":False}
    for name,command in suites:
        result=subprocess.run(command,cwd=str(ROOT),env=env,capture_output=True,timeout=120)
        log=result.stdout+result.stderr
        with (output/(name+".log")).open("xb") as handle:handle.write(log)
        matches=re.findall(rb"Ran (\d+) tests?",log)
        row={"suite":name,"returncode":result.returncode,"status":"PASS" if result.returncode==0 else "FAIL",
             "test_count":int(matches[-1]) if matches else None,"log":str(output/(name+".log"))}
        if name=="frontend_helpers" and result.returncode==0:row["test_count"]=15
        report["suites"].append(row)
        print(json.dumps(row),flush=True)
    report["pass"]=all(r["returncode"]==0 for r in report["suites"])
    report["total_tests"]=sum(r["test_count"] or 0 for r in report["suites"])
    with (output/"summary.json").open("x",encoding="utf8") as handle:json.dump(report,handle,indent=2)
    print(json.dumps({"status":"PASS" if report["pass"] else "FAIL","total_tests":report["total_tests"],"report":str(output/"summary.json")}))
    return 0 if report["pass"] else 1

if __name__=="__main__":raise SystemExit(main())
