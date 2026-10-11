"""Project-local cache and temporary paths for Windows runs."""

from __future__ import annotations

import os
import json
from pathlib import Path
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(value: str | Path, project_root: Path = PROJECT_ROOT) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else project_root / path).resolve()


def configure_runtime_paths(project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Route model, library, package, and temporary caches to project storage."""
    project_root = project_root.resolve()
    runtime_root = project_path(os.environ.get("PBL4_RUNTIME_ROOT", "runtime"), project_root)
    cache_root = runtime_root / "cache"
    hf_root = cache_root / "huggingface"
    temp_root = runtime_root / "tmp"
    paths = {
        "PBL4_RUNTIME_ROOT": runtime_root,
        "PBL4_MODEL_CACHE_DIR": cache_root / "models",
        "TORCH_HOME": cache_root / "torch",
        "YOLO_CONFIG_DIR": cache_root / "ultralytics",
        "HF_HOME": hf_root,
        "HF_HUB_CACHE": hf_root / "hub",
        "HF_DATASETS_CACHE": hf_root / "datasets",
        "HF_XET_CACHE": hf_root / "xet",
        "HF_ASSETS_CACHE": hf_root / "assets",
        "PIP_CACHE_DIR": cache_root / "pip",
        "XDG_CACHE_HOME": cache_root / "xdg",
        "TORCHINDUCTOR_CACHE_DIR": cache_root / "torchinductor",
        "TRITON_CACHE_DIR": cache_root / "triton",
        "TEMP": temp_root,
        "TMP": temp_root,
    }
    for name, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    tempfile.tempdir = None

    # Seed only project-local path settings. Ultralytics adds its normal defaults
    # when it loads this file; an existing D-drive settings file is left intact.
    settings_file = paths["YOLO_CONFIG_DIR"] / "settings.json"
    if not settings_file.exists():
        settings = {
            "datasets_dir": str(project_root / "dataset"),
            "weights_dir": str(cache_root / "models"),
            "runs_dir": str(project_root / "experiments"),
        }
        settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    cpu_threads = str(max(1, (os.cpu_count() or 2) // 2))
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = cpu_threads
    return {name: str(path) for name, path in paths.items()}
