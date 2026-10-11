# Laptop Webcam on Windows

This project is designed to work first with a laptop webcam during development, while preserving the later ESP32-CAM integration path.

## Default camera source

The default development source is:

- camera_source = webcam

This is configured in [inference/config.py](../inference/config.py).

## Windows webcam backend preference

On Windows, the webcam layer prefers the following backend order:

1. DirectShow (`CAP_DSHOW`)
2. MSMF (`CAP_MSMF`)
3. default OpenCV backend (`CAP_ANY`)

This is automatically selected when `camera_backend = auto` and the OS is Windows.

## Commands

### Probe available camera indexes and backends

```powershell
cd "D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4"
.\.venv-py314\Scripts\Activate.ps1
python -m inference.webcam --probe-only --probe-range 4
```

### Start webcam inference

```powershell
cd "D:\Study\Năm 3\PBL4\PBL4-PROJECT\PBL4"
.\.venv-py314\Scripts\Activate.ps1
python -m inference.webcam --camera-index 0 --width 640 --height 480 --fps 10 --backend auto
```

### Force a specific backend

```powershell
python -m inference.webcam --camera-index 0 --backend dshow
python -m inference.webcam --camera-index 0 --backend msmf
```

## Notes

- The webcam is the primary development camera source.
- ESP32-CAM remains compatible as a later network stream source.
- The AI pipeline is camera-source independent.
- Set `--probe-only` to detect which webcam indexes and backends work before running live inference.
- If the webcam is not available in the current environment, the system reports: `NOT HARDWARE-VALIDATED`.

## Troubleshooting

If Windows shows a camera backend error such as `CvCapture_MSMF::grabFrame ... can't grab frame`, the webcam layer will:

- release the failed backend
- try the next backend in the configured priority list
- print a diagnostic message explaining likely causes such as:
  - camera unavailable
  - camera occupied by another application
  - permission denied
  - invalid camera index
  - backend initialization failure

The webcam stack does not depend on the ESP32 hardware and therefore remains testable on a laptop without an external camera device.
