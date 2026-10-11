# Windows Transfer and Setup

This guide is for a fresh Windows checkout. The current repository already lives on D:, but the commands work from any project root. Do not copy a `.venv*` directory from another computer; virtual environments contain machine-specific interpreter paths.

## Create the environment

Use 64-bit Python 3.11 (the repository's `.python-version` is `3.11.9`) and Git. Clone the repository onto a drive with room for packages, datasets, caches, and training outputs; D: is preferred when available.

```powershell
git clone https://github.com/thaingoctienvtqs-hash/PBL4.git D:/Study/PBL4
Set-Location D:/Study/PBL4
py -3.11 -m venv .venv
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- -m pip install --upgrade pip
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes the pinned server/runtime requirements and pytest. Install optional hand landmarks only if needed:

```powershell
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- -m pip install -r requirements-hands.txt
```

The optional LabelMe annotation UI is separate and declares Python 3.12 or newer in `requirements-annotation.txt`; it is not needed for inference or tests. Use a separate `.venv-annotation` if installing it alongside the Python 3.11 runtime.

## Keep generated files on the project drive

Run Python commands that may download weights, use library caches, or create temporary files through `tools/run_pbl4.py`. It routes PyTorch, Ultralytics, Hugging Face, pip, and temporary paths under the ignored `runtime/` directory in the project. The venv, `dataset/`, `experiments/`, server outputs, and caches then stay on the drive holding the checkout. Use `--venv .venv` for the freshly created environment.

```powershell
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- -m pytest -q tests/test_contact_logic.py tests/test_camera_sources.py tests/test_portable_paths.py
```

To use an external camera process that writes frame/status files elsewhere, set `PBL4_FRAME_PATH` and `PBL4_STATUS_PATH` to matching paths before launching both producer and consumer. The legacy `start_pbl4.bat` is tied to a prior WSL, Conda, CUDA, and `C:/Users/LEGION` setup; it is not the portable launcher for this Windows setup.

## Reacquire public assets and check missing data

Manifests, checksums, provenance, licenses, acquisition code, and setup notes are source-controlled candidates. Downloaded image/mask/model payloads are ignored and should be reacquired on the new machine. From the repository root:

```powershell
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/dataset_acquire.py sources
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/dataset_acquire.py open-images-pilot --limit 100 --max-bytes 1000000000 --preflight-only
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/dataset_acquire.py open-images-pilot --limit 100 --max-bytes 1000000000
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/dataset_acquire.py metmuseum-artworks --limit 10 --max-bytes 200000000
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/dataset_acquire.py download mediapipe_hand_landmarker full_task_model
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/dataset_acquire.py validate
```

Validation output reports missing/invalid manifest assets; `report` regenerates the human-readable readiness report. The Open Images pilot is bounded by 100 images and a 1 GB preflight cap. The Met subset is capped at 200 MB, and the optional MediaPipe task is capped at 50 MB. ContactHands image acquisition remains disabled pending clear image reuse terms; ContactPose and HOI4D remain catalog-only because the bounded public files could not be safely verified. See [DATASET_ACQUISITION.md](DATASET_ACQUISITION.md), [PUBLIC_DATA_SOURCES.md](PUBLIC_DATA_SOURCES.md), and [DATASET_LICENSES.md](DATASET_LICENSES.md) for source details.

The generated synthetic images and masks are reproducible from `tools/synthetic_scenes.py`; tests create small fixtures in temporary directories. Keep generated bulk synthetic samples out of ordinary commits. Commit the generator, tests, split/provenance manifests, and reports instead.

## Training safety

Sixteen GB installed RAM does not guarantee sufficient free memory. Check available RAM immediately before training. The current trainer refuses to load the dataset or model below its configured 3 GiB available-memory threshold and uses batch size 1, 320-pixel inputs, zero workers, and no RAM dataset cache for the smoke profile. On a 16 GB machine, proceed only when the preflight passes and the reviewed `dataset/prepared/segmentation.yaml` exists:

```powershell
./.venv/Scripts/python.exe ./tools/run_pbl4.py --venv .venv -- tools/train_yolo.py --data dataset/prepared/segmentation.yaml --smoke-test --name pbl4-lowmem-smoke
```

The script reports a missing dataset YAML instead of starting with absent data. A successful run is only confirmed when its checkpoint exists and validates. No paging-file change is required or made by this project.

## Git transfer contents

Commit project source and tests (`src/`, `server/contact/`, `inference/`, `tools/`, `tests/`), configuration (`configs/`, `.python-version`, requirements), and the dataset manifests, reports, license notes, and documentation. Do not commit venvs, cache/temp folders, raw video, downloaded `dataset/public/` payloads, prepared/custom dataset image-label payloads, runtime outputs, or newly downloaded/trained checkpoint files. This repository already tracks `models/combined_data_model.pth` as the original ContactHands baseline checkpoint (about 819 MB); it remains unchanged and is included by Git when cloning. Avoid copying it a second time. Removing that historical Git blob would require a separately reviewed history change and is outside this transfer preparation.

Before transfer, inspect `git status --short`, `git diff --cached --name-status`, and `git check-ignore -v <path>`. Do not stage or commit as part of setup.
