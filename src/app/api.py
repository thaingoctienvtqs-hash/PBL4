from pathlib import Path
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.services.status import get_status


app = FastAPI(
    title="PBL4 Painting Protection API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


STATUS_PATH = "/mnt/c/Users/LEGION/PaintingProtection/webcam_status.txt"

HISTORY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "history.json"
)


@app.get("/")
def root():
    return {
        "project": "PBL4",
        "system": "Painting Protection",
        "status": "running",
    }


@app.get("/status")
def status():
    return {
        "status": get_status(STATUS_PATH)
    }


@app.get("/history")
def history():
    if not HISTORY_PATH.exists():
        return []

    try:
        return json.loads(
            HISTORY_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        return []
