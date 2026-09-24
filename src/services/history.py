import json
from pathlib import Path
from datetime import datetime

HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "history.json"


def save_alert(status, oc=None, overlap=None):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = []
    else:
        data = []

    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "oc": oc,
        "overlap": overlap,
    }

    data.append(record)

    data = data[-1000:]

    HISTORY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
