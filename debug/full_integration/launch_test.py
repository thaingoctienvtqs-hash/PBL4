"""Start/stop only owned ArtGuard integration TEST services; no camera/model."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "web" / "backend"
NODE = Path(r"C:\Program Files\nodejs\node.exe")
PROFILE = "ARTGUARD_INTEGRATION_TEST"

def load(run):
    run = Path(run).resolve()
    if not run.is_dir() or run == ROOT or ROOT in run.parents:
        raise RuntimeError("External TEST run required")
    config = run / "integration_config.json"
    data = json.loads(config.read_text(encoding="utf8"))
    if data.get("profile") != PROFILE or data["database"]["name"] != "ArtGuard_Integration_TEST":
        raise RuntimeError("Approved TEST profile required")
    return run, config

def identity(pid):
    command = ("$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(int(pid)) +
               "'; if($p){$p | Select-Object ProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress}")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None

def check_port(port):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))

def http_ok(url, timeout=2):
    from urllib.request import build_opener, ProxyHandler
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False

def start(run, which):
    run, config = load(run)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", ARTGUARD_INTEGRATION_CONFIG=str(config),
               TEMP=str(run/"tmp"), TMP=str(run/"tmp"))
    if which == "backend":
        reports = [json.loads(p.read_text(encoding="utf8")) for p in (run/"logs").glob("sql_admin_bootstrap_*.json")]
        if not any(r.get("status")=="TEST_SCHEMA_AND_SEED_READY" and r.get("database")=="ArtGuard_Integration_TEST" for r in reports):
            raise RuntimeError("Verified successful TEST schema/seed bootstrap report is required")
        port, url = 8101, "http://127.0.0.1:8101/health"
        command = [str(BACKEND/".venv/Scripts/python.exe"), "-B", "-m", "uvicorn",
                   "app.integration_app:create_app", "--factory", "--host", "127.0.0.1",
                   "--port", str(port), "--no-access-log"]
        cwd = BACKEND
    else:
        port, url = 5175, "http://127.0.0.1:5175/"
        env.update(ARTGUARD_INTEGRATION_TEST="1", ARTGUARD_BACKEND_ORIGIN="http://127.0.0.1:8101",
                   ARTGUARD_FRONTEND_PORT=str(port), ARTGUARD_FRONTEND_CACHE_DIR=str(run/"frontend_cache"))
        command = [str(NODE), str(ROOT/"web/frontend/node_modules/vite/bin/vite.js"),
                   str(ROOT/"web/frontend"), "--config", str(ROOT/"web/frontend/vite.config.ts"),
                   "--configLoader", "runner", "--host", "127.0.0.1", "--port", str(port), "--strictPort"]
        cwd = run
    check_port(port)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log = run/"logs"/(which+"_"+stamp+".log")
    with log.open("xb") as output:
        process = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    record = {"service": which, "pid": process.pid, "identity": identity(process.pid),
              "url": url, "log": str(log), "started_at": stamp}
    with (run/"process_registry.jsonl").open("a", encoding="utf8") as handle:
        handle.write(json.dumps(record)+"\n")
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(which+" exited; inspect "+str(log))
        if http_ok(url):
            print(json.dumps({"service":which,"pid":process.pid,"url":url,"ready":True,"log":str(log)}))
            return
        time.sleep(.5)
    raise RuntimeError("Readiness timeout; registered process retained for explicit stop")

def stop(run, which=None):
    run, _ = load(run)
    path = run/"process_registry.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    result = []
    for row in reversed(records):
        if which is not None and row["service"] != which:
            continue
        current = identity(row["pid"])
        if current is None:
            result.append({"pid":row["pid"],"status":"already_exited"})
            continue
        if current != row["identity"] or not current.get("CommandLine"):
            result.append({"pid":row["pid"],"status":"identity_mismatch_REFUSED"})
            continue
        subprocess.run(["powershell.exe","-NoProfile","-Command",
                        "Stop-Process -Id "+str(int(row["pid"]))+" -ErrorAction Stop"], check=True)
        result.append({"pid":row["pid"],"status":"stopped_owned_service"})
    print(json.dumps(result))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root",required=True)
    parser.add_argument("action",choices=["start-backend","start-frontend","stop-test","stop-backend","stop-frontend","status"])
    args=parser.parse_args()
    if args.action.startswith("start-"):
        start(args.run_root,args.action[6:])
    elif args.action.startswith("stop-"):
        stop(args.run_root, None if args.action=="stop-test" else args.action[5:])
    else:
        run,_=load(args.run_root)
        print(json.dumps({"backend":http_ok("http://127.0.0.1:8101/health"),
                          "frontend":http_ok("http://127.0.0.1:5175/"),"run":str(run)}))

if __name__=="__main__":
    main()
