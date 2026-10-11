from __future__ import annotations

import argparse
import sys
import time

import cv2
from ultralytics import YOLO

from inference.camera_base import probe_camera_backends
from inference.camera_factory import build_camera_source
from inference.config import (
    DEFAULT_CAMERA_BACKEND,
    DEFAULT_CAMERA_INDEX,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_WIDTH,
    DEFAULT_YOLO_MODEL,
    WINDOWS_WEBCAM_BACKEND_PRIORITY,
)


def _probe_indexes(camera_index_start: int = 0, camera_index_end: int = 4):
    results = []
    for idx in range(camera_index_start, camera_index_end + 1):
        working = probe_camera_backends(camera_index=idx, backend_priority=list(WINDOWS_WEBCAM_BACKEND_PRIORITY))
        for item in working:
            results.append({"camera_index": idx, **item})
    return results


def _draw_detections(frame, results, fps: float):
    display = frame.copy()
    if results:
        display = results[0].plot()
    cv2.putText(display, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return display


def run_webcam_inference(
    camera_index: int = DEFAULT_CAMERA_INDEX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    backend: str = DEFAULT_CAMERA_BACKEND,
    model_path: str = DEFAULT_YOLO_MODEL,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    image_size: int = DEFAULT_IMAGE_SIZE,
    display: bool = True,
    max_frames: int | None = None,
):
    source = build_camera_source(
        "webcam",
        camera_index=camera_index,
        width=width,
        height=height,
        fps=fps,
        backend=backend,
        backend_priority=list(WINDOWS_WEBCAM_BACKEND_PRIORITY),
    )

    if not source.open():
        message = f"Camera unavailable: index={camera_index}, backend={backend}. {source.last_error}"
        raise RuntimeError(message)

    active_backend = source.active_backend or backend
    print(f"Model weight: {model_path}", flush=True)
    print(f"Camera index: {camera_index}", flush=True)
    print(f"Capture backend: {active_backend}", flush=True)
    print(f"Resolution: {width}x{height} FPS target: {fps}", flush=True)

    try:
        try:
            model = YOLO(model_path)
        except Exception as exc:
            print(
                f"[ERROR] model load failed: model={model_path} camera={camera_index} "
                f"backend={active_backend}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            raise

        frame_count = 0
        detection_count = 0
        detected_classes = set()
        run_started = time.perf_counter()
        fps_window_started = run_started
        fps_window_frames = 0
        fps_value = 0.0

        while True:
            frame_info = source.read()
            if frame_info is None:
                print(
                    f"[ERROR] frame read failed: camera={camera_index} backend={source.active_backend or backend}: "
                    f"{source.last_error or 'no frame returned'}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(0.2)
                continue

            frame = frame_info.frame
            try:
                results = model(frame, conf=confidence_threshold, imgsz=image_size, verbose=False)
            except Exception as exc:
                print(
                    f"[ERROR] inference failed: model={model_path} camera={camera_index} "
                    f"backend={source.active_backend or backend} frame={frame_count + 1}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            for result in results:
                if result.boxes is not None:
                    for class_id in result.boxes.cls.cpu().numpy().astype(int):
                        detected_classes.add(result.names.get(int(class_id), str(int(class_id))))
                    detection_count += len(result.boxes)

            annotated_frame = _draw_detections(frame, results, fps_value)
            frame_count += 1
            fps_window_frames += 1

            if display:
                cv2.imshow("PBL4 - YOLO Webcam Inference", annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                try:
                    if cv2.getWindowProperty("PBL4 - YOLO Webcam Inference", cv2.WND_PROP_VISIBLE) < 1:
                        break
                except cv2.error:
                    break

            if max_frames is not None and frame_count >= max_frames:
                break

            now = time.perf_counter()
            if now - fps_window_started >= 1.0:
                fps_value = fps_window_frames / (now - fps_window_started)
                fps_window_started = now
                fps_window_frames = 0

        total_elapsed = time.perf_counter() - run_started
        return {
            "frames_processed": frame_count,
            "model_weight": model_path,
            "camera_index": camera_index,
            "backend": source.active_backend or backend,
            "detected_classes": sorted(detected_classes),
            "detection_count": detection_count,
            "fps": frame_count / total_elapsed if total_elapsed else 0.0,
        }
    finally:
        source.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="Run real YOLO inference on the laptop webcam.")
    parser.add_argument("--camera-index", type=int, default=DEFAULT_CAMERA_INDEX)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--backend", choices=["auto", "dshow", "msmf", "default"], default=DEFAULT_CAMERA_BACKEND)
    parser.add_argument("--model", type=str, default=DEFAULT_YOLO_MODEL, help="Pretrained YOLO model path or weight name, e.g. yolov8n-seg.pt")
    parser.add_argument("--conf", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMAGE_SIZE)
    parser.add_argument("--max-frames", type=int, default=None, help="Optional frame limit for smoke tests; omit to run until q is pressed.")
    parser.add_argument("--probe-only", action="store_true", help="List working camera indexes and backends without entering inference.")
    parser.add_argument("--probe-range", type=int, nargs="?", default=4, help="Maximum camera index to probe when --probe-only is used.")
    parser.add_argument("--no-display", action="store_true", help="Run live inference without opening a window. Useful for smoke tests.")
    args = parser.parse_args()

    if not 0.0 <= args.conf <= 1.0:
        parser.error("--conf must be between 0.0 and 1.0")

    if args.probe_only:
        results = _probe_indexes(0, args.probe_range)
        if not results:
            print("NOT HARDWARE-VALIDATED: no working webcam index/backend detected on this machine.")
            raise SystemExit(1)
        for item in results:
            print(f"Detected camera index={item['camera_index']} backend={item['backend']} (backend_id={item['backend_id']})")
        raise SystemExit(0)

    try:
        summary = run_webcam_inference(
            camera_index=args.camera_index,
            width=args.width,
            height=args.height,
            fps=args.fps,
            backend=args.backend,
            model_path=args.model,
            confidence_threshold=args.conf,
            image_size=args.imgsz,
            display=not args.no_display,
            max_frames=args.max_frames,
        )
        print(f"Inference summary: {summary}")
    except Exception as exc:
        print(f"YOLO webcam inference failed: {exc}")
        raise


if __name__ == "__main__":
    main()
