# Windows and Low-Memory Setup

Checked on 2026-10-11 (Asia/Saigon). The repository was already on D: and was not moved.

## Current machine

- Processor: Intel Core i5-10210U, 4 physical cores / 8 logical processors.
- Memory: 8,415,133,696 bytes total; 803,598,336 bytes available at the final check (0.75 GiB). The training preflight observed 473,694,208 bytes (0.44 GiB).
- Graphics: Intel UHD integrated graphics; no NVIDIA adapter or CUDA device was detected. The project's training profile is CPU-only.
- Free disk space: C: 12.04 GiB; D: 131.80 GiB; E: 76.65 GiB.

Memory and disk readings change over time. The trainer requires 3 GiB available RAM before reading a dataset or loading model weights. The final reading and preflight reading were both far below this gate. The training preflight stopped before reading the dataset or loading any model, so a training smoke run is unsafe and was not started.

## Project storage

The repository is `D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4`.

- Virtual environments are under the repository on D: `.venv-py314` (Python 3.14.7, primary), `.venv-hands` (3.14.7), `.venv` (3.14.7), and `.venv311` (3.11.9). The first three reference their base Python installation on C:, but their installed environments remain on D:.
- Dataset and acquisition reports: `D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4\dataset`.
- Existing YOLO weights: `yolov8n-seg.pt` (7,071,756 bytes) and `yolov8n.pt` (6,549,796 bytes) at the project root on D:.
- Original ContactHands checkpoint: `models\combined_data_model.pth` (818,979,315 bytes), unchanged on D:.
- Default experiment/checkpoint output: `D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4\experiments`.
- Video render, event, and evidence output: `D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4\server\data\results`.
- Project caches and temp files: `D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4\runtime\cache` and `runtime\tmp`.

The last dataset report scanned 167,388,256 bytes; the MediaPipe task model is another 7,819,105 bytes. The report does not count every temporary test artifact or venv package.

## Cache behavior

Use `tools/run_pbl4.py` for commands that may create library caches, downloads, or temporary files. It sets `TORCH_HOME`, `YOLO_CONFIG_DIR`, Hugging Face cache variables, `PIP_CACHE_DIR`, `TEMP`, and `TMP` beneath `runtime/` on D, then runs the selected project's virtual environment from the project root. New video and training entry points configure those D-drive paths before importing Ultralytics. This Python launcher works under the current PowerShell execution policy without changing it.

At the check, these user caches already existed on C: pip cache (1,133,313,284 bytes) and Ultralytics settings (516 bytes). They were inspected and left untouched; future project launches use the isolated D-drive paths. Hugging Face and PyTorch home caches were absent. No cache was moved or deleted.

Examples:

```powershell
# Inspect the runtime/cache paths selected by the project runner
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -c "import os,json; print(json.dumps({k:os.environ[k] for k in ['TORCH_HOME','YOLO_CONFIG_DIR','HF_HOME','HF_HUB_CACHE','HF_DATASETS_CACHE','PIP_CACHE_DIR','TEMP','TMP']},indent=2))"

# Run offline inference with D-drive caches and temporary files
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -m src.app.video_demo --input path/to/clip.mp4

# Use pip through the same D-drive cache configuration
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- -m pip install -r requirements-server.txt
```

## Safe training smoke profile

When available RAM reaches the 3 GiB gate and a reviewed dataset exists, the initial smoke profile uses one epoch, a 320-pixel input, batch size 1, zero workers, disabled dataset caching, and 10% of the training split:

```powershell
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- tools/train_yolo.py --data dataset/prepared/segmentation.yaml --smoke-test --name pbl4-lowmem-smoke
```

The trainer rejects non-CPU devices, has no low-memory bypass option, checks RAM before dataset/model loading, and resolves relative data, model, and output paths from the project root. After training, it releases the training model before loading the checkpoint for evaluation. A smoke checkpoint is only reported if a real `best.pt` file is created and verified.

No Windows paging-file or other system settings were changed.
