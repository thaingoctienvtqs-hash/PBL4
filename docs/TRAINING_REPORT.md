# Training Report

Generated: 2026-10-11 (Asia/Saigon)

## Result

**Training status: NOT RUN.** No custom checkpoint, best weights, loss curves, validation metrics, or test metrics were produced. The local `yolov8n-seg.pt` is a pretrained initialization checkpoint, not a PBL4-trained model. The legacy `models/combined_data_model.pth` remains the original ContactHands baseline and was not modified.

Training was stopped before launch because the live preflight found 473,694,208 bytes (0.44 GiB) available out of 8,415,133,696 bytes total. The latest check found 803,598,336 bytes (0.75 GiB). Both are below the 3 GiB CPU gate, which has no override flag. The dataset is also not ready: Open Images is validation-only with incomplete instance coverage, no painting masks, and hand boxes only. Stylized synthetic scenes are for geometry and code-path checks, not real-world accuracy.

## Prepared training configuration

The defaults in `configs/system.toml` and `tools/train_yolo.py` keep the YOLOv8n-seg architecture, use 320-pixel images, batch size 1, CPU, zero workers, disabled image caching, seed 42, learning rate 0.001, deterministic mode, and augmentation enabled. A `--smoke-test` profile uses one epoch and 10% of the training split. The trainer checks memory before reading the dataset or loading the model, then validates nonempty train/validation/test splits, normalized polygon labels, exact-image hashes, source-group assignments, and class presence. No prepared `dataset/prepared/segmentation.yaml` is present.

To train after collecting and reviewing a suitable dataset:

```powershell
.\.venv-py314\Scripts\python.exe .\tools\run_pbl4.py -- tools/train_yolo.py --data dataset/prepared/segmentation.yaml --smoke-test --name pbl4-lowmem-smoke
```

The current machine fails the 3 GiB RAM preflight before dataset or checkpoint loading; a valid reviewed dataset is also still required. Do not treat the command as a current training result.

## Checkpoint inventory

- `yolov8n-seg.pt`: 7,071,756 bytes, pretrained starting weights.
- `models/combined_data_model.pth`: 818,979,315 bytes, existing ContactHands/Detectron2 baseline, unchanged.
- No custom training output or best checkpoint exists.

Default checkpoints and outputs are on D: `yolov8n-seg.pt`, `runtime/cache/models/`, and `experiments/`. The Python runner routes PyTorch, Ultralytics, Hugging Face, pip, and process temp paths to `runtime/cache/` and `runtime/tmp/` under the project root.

See [TRAINING_READINESS.md](TRAINING_READINESS.md) for the annotation and source-split gaps, and [DATASET_REPORT.md](DATASET_REPORT.md) for the current inventory.
