"""FastAPI status, configuration, frame and persisted-history endpoints."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.services.history import get_history
from src.services.status import get_status
from src.utils.config import (DEFAULT_CONFIG_PATH, load_settings, resolve_path,
                              save_settings)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALERT_DIR = resolve_path(load_settings(), "evidence_dir")
ALERT_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="PBL4 Painting Protection API", version="1.1.0")
app.mount("/alerts", StaticFiles(directory=str(ALERT_DIR)), name="alerts")


@app.get("/")
def dashboard():
    return FileResponse(str(PROJECT_ROOT / "index.html"), media_type="text/html")


@app.get("/health")
def health():
    return {"api": "available"}


@app.get("/status")
def status():
    settings = load_settings()
    current = get_status(resolve_path(settings, "status_file"))
    updated = current.get("updated_at")
    if updated is not None:
        import time
        age = max(0.0, time.time() - updated)
        current["age_seconds"] = age
        if age > settings["dashboard"]["stale_after_seconds"] and current.get("status") not in ("STOPPED", "ERROR"):
            current["previous_status"] = current["status"]
            current["status"] = "WORKER_NOT_RESPONDING"
            current["message"] = "No inference status update for {:.0f} seconds".format(age)
    return {"status": current}


@app.get("/history")
def history(limit: int = 100, event_type: str = None, status: str = None):
    return get_history(limit, event_type, status)


@app.get("/frame/latest.jpg")
def latest_frame():
    path = resolve_path(load_settings(), "latest_frame")
    if not path.is_file():
        return JSONResponse(status_code=404, content={"error": "No processed frame is available"})
    return FileResponse(str(path), media_type="image/jpeg")


@app.get("/config")
def get_config():
    config = load_settings()
    # The camera URL is deliberately not returned: it may contain a private host or credentials.
    return {"roi": config["roi"], "thresholds": config["thresholds"],
            "alert": config["alert"],
            "camera_configured": bool(config["camera"].get("url"))}


@app.post("/config")
async def update_config(request: Request):
    try:
        length = int(request.headers.get("content-length", "0"))
        if length <= 0 or length > 65536:
            raise ValueError("request body must be between 1 and 65536 bytes")
        incoming = await request.json()
        if not isinstance(incoming, dict):
            raise ValueError("configuration must be a JSON object")
        unknown = set(incoming) - {"roi", "thresholds", "alert"}
        if unknown:
            raise ValueError("unsupported configuration sections: {}".format(sorted(unknown)))
        settings = load_settings()
        for section in ("roi", "thresholds", "alert"):
            if section in incoming:
                if not isinstance(incoming[section], dict):
                    raise ValueError("{} must be an object".format(section))
                if section == "thresholds":
                    supported = {"no_contact", "self_contact", "other_person_contact", "object_contact"}
                    unsupported = set(incoming[section]) - supported
                    if unsupported:
                        raise ValueError("unsupported thresholds: {} (hand_score requires worker restart)".format(
                            sorted(unsupported)))
                settings[section].update(incoming[section])
        target = os.environ.get("PBL4_CONFIG", str(DEFAULT_CONFIG_PATH))
        saved = save_settings(settings, target)
        return {"saved": True, "path": str(saved)}
    except (ValueError, TypeError, OSError) as error:
        return JSONResponse(status_code=400, content={"saved": False, "error": str(error)})
