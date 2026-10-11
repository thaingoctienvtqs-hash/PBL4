from pathlib import Path


def save_status(status, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(status, encoding="utf-8")


def get_status(path):
    p = Path(path)

    if not p.exists():
        return "UNKNOWN"

    return p.read_text(encoding="utf-8").strip()
