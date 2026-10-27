"""Phase E runner: preserve known failures, keep all artifacts exclusively under E."""
import ast
import hashlib
import json
import sys
from pathlib import Path
from ..phase_d.run_tests import run_suite,FROZEN_MODULES,KNOWN_FAILURES
from .controlled_cases import controlled_cases
from .compare_phase_d import compare_case
from .replay import new_output_directory,write_json,replay_file

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
RECOVERY_FAILURES={
    "debug.alert_diagnostics.v4.phase_e.test_adapter.OfflineCases.test_case_explicit_missing_frame",
    "debug.alert_diagnostics.v4.phase_e.test_adapter.OfflineCases.test_case_explicit_frame_error",
}

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
    return h.hexdigest()

def verify():
    expected=json.loads((BASE/"protected_before.json").read_text(encoding="utf-8"))
    return [{"path":path,"before":value,"after":digest(ROOT/path) if (ROOT/path).is_file() else None}
            for path,value in expected.items()]

def all_unchanged(rows):return all(r["before"]==r["after"] for r in rows)

def counts(suite):return {k:suite[k] for k in ("tests","pass","fail","error","skip")}

def main():
    before=verify()
    if not all_unchanged(before):raise RuntimeError("Protected snapshot mismatch before tests")
    directory=new_output_directory(BASE/"runs")
    frozen=run_suite(FROZEN_MODULES)
    phase_d=run_suite(("debug.alert_diagnostics.v4.phase_d.test_phase_d",))
    phase_e=run_suite(("debug.alert_diagnostics.v4.phase_e.test_adapter",
                       "debug.alert_diagnostics.v4.phase_e.test_replay_io"))
    for name,data in (("frozen_B_C.json",frozen),("phase_d_tests.json",phase_d),("phase_e_tests.json",phase_e)):
        write_json(directory/name,data)
    inputs=directory/"inputs";inputs.mkdir(exist_ok=False)
    reports=[]
    for case in controlled_cases():
        config_path=inputs/(case["name"]+".settings.json")
        input_path=inputs/(case["name"]+".jsonl")
        write_json(config_path,case["settings"])
        with input_path.open("x",encoding="utf-8") as stream:
            for record in case["records"]:stream.write(json.dumps(record,allow_nan=False,sort_keys=True)+"\n")
        replay_dir,summary=replay_file(input_path,config_path,True,directory/"replays"/case["name"])
        comparison,unused_logs=compare_case(case)
        actual_logs=[json.loads(line) for line in (replay_dir/"frames.jsonl").read_text().splitlines()]
        same=all({k:v for k,v in a.items() if k not in ("line_number","input_line_sha256")}==b
                 for a,b in zip(actual_logs,unused_logs)) and len(actual_logs)==len(unused_logs)
        record=dict(summary,scenario=case["name"],desired_logic_events=case["expected_logic_events"],
                    desired_logic_gate_pass=summary["event_count"]==case["expected_logic_events"],
                    controlled_expected_contact_events=case["controlled_expected_contact_events"],
                    controlled_event_shortfall=max(0,case["controlled_expected_contact_events"]-summary["event_count"]),
                    label_kind=case["label_kind"],direct_phase_d=comparison,
                    serialized_replay_matches_in_memory=same,replay_directory=str(replay_dir.relative_to(BASE)))
        record["safety_observations"]={
            "uncertain_frames":sum(bool(r.get("ambiguous_detection_indices")) for r in actual_logs),
            "unknown_stability_frames":sum(r["state"]=="CAMERA_UNVERIFIED" for r in actual_logs),
            "moving_frames":sum(r["state"]=="CAMERA_MOVING" for r in actual_logs),
            "offline_frames":sum(r["state"]=="CAMERA_OFFLINE" for r in actual_logs),
            "awaiting_entry_frames":sum(any(t.get("state_reason")=="awaiting_roi_entry" for t in r["tracks"]) for r in actual_logs),
            "input_error_frames":sum(r["state"]=="INPUT_ERROR" for r in actual_logs)}
        reports.append(record)
    write_json(directory/"offline_comparison.json",reports)
    static=[]
    for path in sorted(BASE.rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"),filename=str(path));static.append(str(path.relative_to(BASE)))
    for path in BASE.rglob("*.json"):json.loads(path.read_text(encoding="utf-8"))
    after=verify();write_json(directory/"protected_after.json",after)
    old_ok={r["test"] for r in frozen["failures"]}==KNOWN_FAILURES and frozen["error"]==0 and frozen["pass"]==98
    recovery_expected={r["test"] for r in phase_e["failures"]}==RECOVERY_FAILURES and phase_e["error"]==0
    equivalence=all(r["direct_phase_d"]["mismatch_count"]==0 and r["serialized_replay_matches_in_memory"] for r in reports)
    forbidden=[name for name in ("torch","detectron2","cv2","fastapi","pyodbc","sqlite3") if name in sys.modules]
    summary={"python":sys.version,"frozen_B_C":counts(frozen),"phase_d":counts(phase_d),"phase_e":counts(phase_e),
             "known_B_C_failures_retained":old_ok,"known_D_recovery_limits_retained_as_FAIL":recovery_expected,
             "offline_scenarios":len(reports),"jsonl_records":sum(r["records"] for r in reports),
             "direct_phase_d_records_compared":sum(r["direct_phase_d"]["compared_records"] for r in reports),
             "phase_d_equivalence_pass":equivalence,"protected_files":len(after),"protected_unchanged":all_unchanged(after),
             "python_files_parsed":static,"forbidden_runtime_modules_loaded":forbidden,
             "camera_or_gpu_run":False,"real_AI_metrics":"NOT_EVALUATED",
             "all_phase_e_tests_pass":phase_e["fail"]==0 and phase_e["error"]==0}
    write_json(directory/"summary.json",summary)
    print(json.dumps(summary,indent=2));print("Artifacts:",directory)
    # Do not mask desired recovery failures even though integration equivalence succeeds.
    return 0 if old_ok and phase_d["fail"]==0 and phase_d["error"]==0 and equivalence and all_unchanged(after) and not forbidden and summary["all_phase_e_tests_pass"] else 1

if __name__=="__main__":sys.exit(main())
