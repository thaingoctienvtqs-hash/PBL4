"""Run ORIGINAL v3, file-watch only, with bounded lifetime and TEST-only output.
No process/model/GPU/database work on import. Requires separate hardware approval.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from .event_sender import REPO, SafetyError, inside, controlled_path, canonical


def validate_settings(test_root, config_path):
    root = Path(test_root).expanduser().resolve()
    if not root.is_dir() or inside(root, REPO) or inside(REPO, root):
        raise SafetyError("external_test_root_required")
    config = controlled_path(config_path, root, True)
    settings = json.loads(config.read_text(encoding="utf8"))
    required = ("capture_frame", "latest_frame", "event_db", "evidence_dir", "status_file")
    for key in required:
        value = Path(settings.get("paths", {}).get(key, ""))
        if not value.is_absolute():
            raise SafetyError("absolute_test_paths_required")
        controlled_path(value, root)
    roi = settings.get("roi", {})
    if roi.get("enabled") is not True or roi.get("shape") != "polygon" or roi.get("normalized") is not True:
        raise SafetyError("confirmed_normalized_polygon_required")
    if not settings.get("hardware_session", {}).get("roi_user_confirmed"):
        raise SafetyError("roi_user_confirmation_required")
    if len(roi.get("points", [])) < 3:
        raise SafetyError("roi_points_missing")
    model = settings.get("model", {})
    for key in ("contacthands_config", "contacthands_weights", "second_stream_config", "second_stream_weights"):
        path = Path(model.get(key, "")).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise SafetyError("explicit_existing_local_model_paths_required")
    return root, config, settings


def build_command(test_root, config_path, interpreter=None):
    root, config, settings = validate_settings(test_root, config_path)
    model, paths = settings["model"], settings["paths"]
    command = [
        str(interpreter or sys.executable), "-B", "-m", "src.realtime_worker_integrated_v3",
        "--mode", "file-watch", "--config-json", str(config),
        "--frame-file", paths["capture_frame"], "--database", paths["event_db"],
        "--config", model["contacthands_config"], "--weights", model["contacthands_weights"],
        "--second-stream-config", model["second_stream_config"],
        "--second-stream-weights", model["second_stream_weights"], "--device", "cuda",
    ]
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONPATH=str(REPO),
               PBL4_CONFIG=str(config), CONTACTHANDS_MODEL_WEIGHTS=model["contacthands_weights"],
               CONTACTHANDS_SECOND_STREAM_WEIGHTS=model["second_stream_weights"])
    env.pop("PBL4_CAMERA_URL", None)
    for key, value in paths.items():
        if key in ("capture_frame", "latest_frame", "event_db", "evidence_dir", "status_file"):
            env["PBL4_" + key.upper()] = str(Path(value).resolve())
    for key in ("CUDA_CACHE_PATH", "TORCH_HOME", "XDG_CACHE_HOME", "TORCH_EXTENSIONS_DIR", "MPLCONFIGDIR"):
        env[key] = str(root / "cache")
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = str(root / "tmp")
    env["MPLBACKEND"] = "Agg"
    return root, command, env


def stop_owned_process(process):
    if process.poll() is not None:
        return "already_exited"
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
        return "sigint"
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
            return "terminated"
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return "killed_owned_process"


def run_worker(test_root, config_path, duration=60, hardware_approved=False,
               interpreter=None, popen=subprocess.Popen, clock=time.monotonic, sleep=time.sleep):
    if hardware_approved is not True:
        raise SafetyError("separate_hardware_approval_required")
    if os.name != "posix":
        raise SafetyError("run_inside_verified_WSL_environment")
    if not 1 <= float(duration) <= 300:
        raise SafetyError("bounded_worker_duration_required")
    root, command, env = build_command(test_root, config_path, interpreter)
    stdout, stderr = root / "worker_stdout.log", root / "worker_stderr.log"
    manifest, final = root / "worker_process.json", root / "worker_result.json"
    if any(p.exists() for p in (stdout, stderr, manifest, final)):
        raise SafetyError("preexisting_worker_outputs_refused")
    (root / "tmp").mkdir(exist_ok=True)
    (root / "cache").mkdir(exist_ok=True)
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = popen(command, cwd=str(root), env=env, stdout=out, stderr=err, start_new_session=True)
        with manifest.open("x", encoding="utf8") as handle:
            json.dump({"pid": process.pid, "command": command, "cwd": str(root),
                       "duration_limit_seconds": duration, "worker_source_unchanged": True}, handle, indent=2)
        started = clock()
        stopped = None
        try:
            while process.poll() is None and clock() - started < duration:
                sleep(.2)
        finally:
            stopped = stop_owned_process(process)
        result = {"pid": process.pid, "returncode": process.returncode,
                  "elapsed_seconds": clock() - started, "termination": stopped,
                  "stdout": str(stdout), "stderr": str(stderr)}
        with final.open("x", encoding="utf8") as handle:
            json.dump(result, handle, indent=2)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--duration-seconds", type=float, default=60)
    parser.add_argument("--hardware-approved", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if args.preflight_only:
        root, command, env = build_command(args.test_root, args.config)
        print(canonical({"command": command, "cwd": str(root), "gpu_started": False}))
        return 0
    print(canonical(run_worker(args.test_root, args.config, args.duration_seconds, args.hardware_approved)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
