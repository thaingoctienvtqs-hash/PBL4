"""Run a project command with D-drive caches and the selected venv."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.runtime_paths import configure_runtime_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a Python command from the PBL4 project with project-local caches and temp files."
    )
    parser.add_argument("--venv", default=".venv-py314", help="Project virtual environment directory (default: .venv-py314).")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Target Python command after --.")
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("Provide a Python command after --, for example -- tools/train_yolo.py --help")

    venv_path = Path(args.venv).expanduser()
    if not venv_path.is_absolute():
        venv_path = ROOT / venv_path
    interpreter = venv_path / "Scripts/python.exe"
    if not interpreter.is_file():
        parser.error(f"Virtual environment interpreter not found: {interpreter}")

    configure_runtime_paths(ROOT)
    result = subprocess.run([str(interpreter), *command], cwd=ROOT, env=None)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
