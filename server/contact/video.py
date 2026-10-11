from __future__ import annotations

import json
import importlib.util
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from .logic import BinaryMask, ContactAnalyzer, ContactSettings, Detection, FrameAnalysis


@dataclass(frozen=True)
class VideoPipelineConfig:
    confidence_threshold: float = 0.5
    image_size: int = 640
    device: str = "cpu"
    tracker: str = "bytetrack.yaml"
    roi_points: tuple[tuple[float, float], ...] = (
        (0.35, 0.18), (0.65, 0.18), (0.65, 0.78), (0.35, 0.78)
    )
    roi_mode: str = "when_missing"
    roi_enabled: bool = True
    hand_aliases: tuple[str, ...] = ("hand", "human hand", "left hand", "right hand")
    tool_aliases: tuple[str, ...] = ("tool", "pen", "scissors", "knife")

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        if self.image_size <= 0:
            raise ValueError("image_size must be positive")
        if self.roi_mode not in {"when_missing", "always", "never"}:
            raise ValueError("roi_mode must be when_missing, always, or never")
        if len(self.roi_points) < 3:
            raise ValueError("roi_points must contain at least three vertices")
        if any(
            len(point) != 2
            or not all(math.isfinite(float(value)) for value in point)
            or not all(0.0 <= float(value) <= 1.0 for value in point)
            for point in self.roi_points
        ):
            raise ValueError("roi_points must use finite normalized coordinates in [0, 1]")


@dataclass(frozen=True)
class ProcessedFrame:
    detections: tuple[Detection, ...]
    analysis: FrameAnalysis
    roi_polygon: np.ndarray
    uses_roi_fallback: bool


def _scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


def _xyxy(box: Any) -> tuple[float, float, float, float]:
    if hasattr(box, "cpu"):
        box = box.cpu()
    if hasattr(box, "tolist"):
        box = box.tolist()
    if len(box) == 1 and hasattr(box[0], "__len__"):
        box = box[0]
    values = tuple(float(value) for value in box)
    if len(values) != 4:
        raise ValueError("YOLO box must contain x1, y1, x2, y2")
    return values


def mask_from_array(mask: np.ndarray, width: int, height: int) -> BinaryMask | None:
    array = np.asarray(mask)
    if array.ndim != 2:
        raise ValueError("Instance mask must be two-dimensional")
    if array.shape != (height, width):
        array = cv2.resize(array.astype(np.float32), (width, height), interpolation=cv2.INTER_NEAREST)
    binary = array > 0.5
    if not np.any(binary):
        return None
    packed = np.packbits(binary.reshape(-1), bitorder="little").tobytes()
    return BinaryMask(width=width, height=height, packed_bits=packed)


def polygon_mask(points: Iterable[tuple[float, float]], width: int, height: int) -> BinaryMask:
    polygon = normalized_polygon(points, width, height)
    bitmap = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(bitmap, [polygon], 1)
    packed = np.packbits(bitmap.reshape(-1).astype(bool), bitorder="little").tobytes()
    return BinaryMask(width=width, height=height, packed_bits=packed)


def normalized_polygon(points: Iterable[tuple[float, float]], width: int, height: int) -> np.ndarray:
    if width <= 0 or height <= 0:
        raise ValueError("Frame dimensions must be positive")
    vertices = np.asarray(tuple(points), dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or len(vertices) < 3:
        raise ValueError("ROI polygon must have at least three x/y vertices")
    if not np.isfinite(vertices).all() or (vertices < 0).any() or (vertices > 1).any():
        raise ValueError("ROI polygon coordinates must be finite and normalized to [0, 1]")
    pixels = np.empty_like(vertices, dtype=np.int32)
    pixels[:, 0] = np.rint(vertices[:, 0] * max(width - 1, 0)).astype(np.int32)
    pixels[:, 1] = np.rint(vertices[:, 1] * max(height - 1, 0)).astype(np.int32)
    return pixels


def write_image_unicode(path: Path, image: np.ndarray, params: list[int] | None = None) -> bool:
    """OpenCV's Windows writer can reject non-ASCII paths; encode then write through pathlib."""
    encoded, buffer = cv2.imencode(path.suffix or ".jpg", image, params or [])
    if not encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.tobytes())
    return True


class VideoContactPipeline:
    """YOLO tracking, painting ROI fallback, and persistent contact event analysis."""

    def __init__(
        self,
        model: Any,
        contact_settings: ContactSettings,
        config: VideoPipelineConfig | None = None,
        hand_detector: Any | None = None,
    ) -> None:
        self.model = model
        self.contact_settings = contact_settings
        self.config = config or VideoPipelineConfig()
        self.hand_detector = hand_detector
        self.analyzer = ContactAnalyzer(contact_settings)
        names = getattr(model, "names", {})
        self.names = names if isinstance(names, dict) else dict(enumerate(names))
        self._frame_index = 0
        self._last_hand_timestamp_ms = -1
        self.tracking_backend = "uninitialized"
        self._next_fallback_track_id = 1_000_000
        self._fallback_tracks: dict[int, tuple[int, tuple[float, float, float, float], int]] = {}

    def _class_name(self, class_id: int) -> str:
        value = self.names.get(class_id, str(class_id))
        return " ".join(str(value).strip().lower().replace("_", " ").split())

    def _semantic_class(self, class_name: str) -> int | None:
        if class_name in {"painting", "artwork", "picture"}:
            return self.contact_settings.painting_class_id
        if class_name in {"person", "human"}:
            return 1
        if class_name in set(self.config.hand_aliases):
            return self.contact_settings.hand_class_id
        if class_name in set(self.config.tool_aliases):
            return self.contact_settings.tool_class_id
        return None

    @staticmethod
    def _box_iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0 else 0.0

    def _add_fallback_track_ids(self, detections: list[Detection]) -> list[Detection]:
        tracked: list[Detection] = []
        used: set[int] = set()
        max_gap = max(50.0, self.contact_settings.near_distance_threshold * 4.0)
        for detection in detections:
            if detection.track_id is not None:
                track_id = detection.track_id
            else:
                first_center = ((detection.box[0] + detection.box[2]) / 2, (detection.box[1] + detection.box[3]) / 2)
                candidates = []
                for candidate_id, (class_id, old_box, last_frame) in self._fallback_tracks.items():
                    if class_id != detection.class_id or candidate_id in used:
                        continue
                    if self._frame_index - last_frame > self.contact_settings.sliding_window_size:
                        continue
                    old_center = ((old_box[0] + old_box[2]) / 2, (old_box[1] + old_box[3]) / 2)
                    distance = math.hypot(first_center[0] - old_center[0], first_center[1] - old_center[1])
                    overlap = self._box_iou(detection.box, old_box)
                    if overlap >= 0.05 or distance <= max_gap:
                        candidates.append((overlap - distance / max_gap * 0.01, candidate_id))
                if candidates:
                    track_id = max(candidates)[1]
                else:
                    track_id = self._next_fallback_track_id
                    self._next_fallback_track_id += 1
                detection = Detection(
                    detection.class_id,
                    detection.confidence,
                    detection.box,
                    track_id,
                    detection.mask,
                    detection.contact_points,
                )
            used.add(track_id)
            self._fallback_tracks[track_id] = (detection.class_id, detection.box, self._frame_index)
            tracked.append(detection)
        for track_id, (_, _, last_frame) in list(self._fallback_tracks.items()):
            if self._frame_index - last_frame > self.contact_settings.sliding_window_size:
                del self._fallback_tracks[track_id]
        return tracked

    def process(self, frame: np.ndarray, *, monotonic_time: float | None = None) -> ProcessedFrame:
        if frame is None or frame.ndim < 2:
            raise ValueError("frame must be a decoded image")
        height, width = frame.shape[:2]
        polygon = normalized_polygon(self.config.roi_points, width, height)
        self._frame_index += 1
        if monotonic_time is None:
            monotonic_time = (self._frame_index - 1) / 30.0
        inference_options = {
            "conf": self.config.confidence_threshold,
            "imgsz": self.config.image_size,
            "device": self.config.device,
            "verbose": False,
        }
        native_track = getattr(self.model, "track", None)
        predict = getattr(self.model, "predict", None)
        lap_available = importlib.util.find_spec("lap") is not None
        if callable(native_track) and (lap_available or not callable(predict)):
            result_list = native_track(
                frame,
                persist=True,
                tracker=self.config.tracker,
                **inference_options,
            )
            self.tracking_backend = "ultralytics_tracker"
        elif callable(predict):
            result_list = predict(frame, **inference_options)
            self.tracking_backend = "iou_centroid_fallback"
        elif callable(native_track):
            result_list = native_track(frame, **inference_options)
            self.tracking_backend = "model_tracker"
        else:
            raise TypeError("YOLO model must expose predict() or track()")
        result = result_list[0] if result_list else None
        detections: list[Detection] = []
        painting_detected = False

        boxes = getattr(result, "boxes", None)
        if boxes is not None:
            xyxy = getattr(boxes, "xyxy", [])
            class_values = getattr(boxes, "cls", [])
            confidences = getattr(boxes, "conf", [])
            track_values = getattr(boxes, "id", None)
            masks = getattr(result, "masks", None)
            mask_values = getattr(masks, "data", None) if masks is not None else None
            for index, raw_box in enumerate(xyxy):
                source_class = int(_scalar(class_values[index]))
                class_name = self._class_name(source_class)
                semantic_class = self._semantic_class(class_name)
                if semantic_class is None:
                    continue
                confidence = float(_scalar(confidences[index]))
                track_id = None
                if track_values is not None:
                    track_id = int(_scalar(track_values[index]))
                mask = None
                if mask_values is not None and index < len(mask_values):
                    raw_mask = mask_values[index]
                    if hasattr(raw_mask, "cpu"):
                        raw_mask = raw_mask.cpu().numpy()
                    mask = mask_from_array(np.asarray(raw_mask), width, height)
                detection = Detection(
                    class_id=semantic_class,
                    confidence=confidence,
                    box=_xyxy(raw_box),
                    track_id=track_id,
                    mask=mask,
                )
                detections.append(detection)
                if semantic_class == self.contact_settings.painting_class_id:
                    painting_detected = True

        if self.hand_detector is not None:
            self._last_hand_timestamp_ms = max(
                int(round(monotonic_time * 1000.0)), self._last_hand_timestamp_ms + 1
            )
            detections.extend(self.hand_detector.detect(frame, self._last_hand_timestamp_ms))

        use_roi = self.config.roi_enabled and self.config.roi_mode != "never"
        if self.config.roi_mode == "when_missing" and painting_detected:
            use_roi = False
        if use_roi:
            x_values = polygon[:, 0]
            y_values = polygon[:, 1]
            roi_box = (
                float(x_values.min()), float(y_values.min()),
                float(x_values.max() + 1), float(y_values.max() + 1),
            )
            detections.append(
                Detection(
                    class_id=self.contact_settings.painting_class_id,
                    confidence=1.0,
                    box=roi_box,
                    track_id=-1,
                    mask=polygon_mask(self.config.roi_points, width, height),
                )
            )

        detections = self._add_fallback_track_ids(detections)
        analysis = self.analyzer.analyze(
            detections,
            monotonic_time=monotonic_time,
            event_time=datetime.now(timezone.utc),
        )
        return ProcessedFrame(tuple(detections), analysis, polygon, use_roi)


def render_frame(frame: np.ndarray, processed: ProcessedFrame) -> np.ndarray:
    rendered = frame.copy()
    if processed.uses_roi_fallback:
        cv2.polylines(rendered, [processed.roi_polygon], True, (0, 215, 255), 2)
        cv2.putText(
            rendered,
            "PAINTING ROI (fixed polygon)",
            (int(processed.roi_polygon[0][0]), max(20, int(processed.roi_polygon[0][1]) - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 180, 255),
            2,
            cv2.LINE_AA,
        )

    colors = {0: (0, 215, 255), 1: (220, 220, 220), 2: (255, 128, 0), 3: (0, 80, 255)}
    for detection in processed.detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.box)
        color = colors.get(detection.class_id, (255, 255, 255))
        if detection.mask is not None:
            count = detection.mask.width * detection.mask.height
            unpacked = np.unpackbits(
                np.frombuffer(detection.mask.packed_bits, dtype=np.uint8), bitorder="little"
            )[:count]
            binary = unpacked.reshape(detection.mask.height, detection.mask.width).astype(bool)
            overlay = rendered.copy()
            overlay[binary] = color
            rendered = cv2.addWeighted(overlay, 0.2, rendered, 0.8, 0)
        for point_x, point_y in detection.contact_points:
            cv2.circle(rendered, (int(round(point_x)), int(round(point_y))), 3, color, -1, cv2.LINE_AA)
        if detection.class_id != 0:
            cv2.rectangle(rendered, (x1, y1), (x2, y2), color, 2)
            label = f"class={detection.class_id} {detection.confidence:.2f}"
            if detection.track_id is not None:
                label += f" id={detection.track_id}"
            cv2.putText(rendered, label, (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    analysis = processed.analysis
    status = analysis.state.value.upper()
    color = (0, 0, 255) if analysis.events else (0, 200, 0)
    cv2.putText(rendered, status, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)
    for event in analysis.events:
        cv2.putText(
            rendered,
            f"ALERT: {event.event} via {event.contact_type}",
            (12, 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    return rendered


def run_video(
    pipeline: VideoContactPipeline,
    source: Any,
    *,
    output_path: Path,
    events_path: Path,
    evidence_dir: Path,
    source_label: str,
) -> dict[str, Any]:
    camera_source = not isinstance(source, (str, int, np.integer))
    if camera_source:
        capture = source
        if not capture.open():
            capture.release()
            raise RuntimeError(f"Could not open camera source: {getattr(source, 'last_error', source)}")
        fps = float(getattr(capture, "fps", 30.0))
        frame_width = int(getattr(capture, "width", 640))
        frame_height = int(getattr(capture, "height", 480))
    else:
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"Could not open video source: {source}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    if frame_width <= 0 or frame_height <= 0:
        capture.release()
        raise RuntimeError("Video source did not report valid frame dimensions")

    output_path = output_path.resolve()
    events_path = events_path.resolve()
    evidence_dir = evidence_dir.resolve()
    if output_path.exists():
        capture.release()
        raise FileExistsError(f"Refusing to overwrite existing result video: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frame_width, frame_height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open output video writer: {output_path}")

    frame_count = 0
    event_count = 0
    started = time.perf_counter()
    try:
        with events_path.open("a", encoding="utf-8") as event_log:
            while True:
                read_result = capture.read()
                if camera_source:
                    frame_info = read_result
                    if frame_info is None:
                        break
                    frame = frame_info.frame
                else:
                    ok, frame = read_result
                    if not ok:
                        break
                if frame is None:
                    break
                processed = pipeline.process(frame, monotonic_time=frame_count / fps)
                rendered = render_frame(frame, processed)
                writer.write(rendered)
                frame_count += 1
                serialized_events = [event.__dict__ for event in processed.analysis.events]
                event_log.write(json.dumps({
                    "sample_type": "UNLABELED_VIDEO_INFERENCE",
                    "record_type": "frame_analysis",
                    "source": source_label,
                    "frame_index": frame_count - 1,
                    "timestamp_seconds": round((frame_count - 1) / fps, 6),
                    "state": processed.analysis.state.value,
                    "nearest_distance_pixels": processed.analysis.nearest_distance,
                    "maximum_overlap": processed.analysis.maximum_overlap,
                    "events": serialized_events,
                }, ensure_ascii=False) + "\n")
                for event in processed.analysis.events:
                    event_count += 1
                    evidence_path = evidence_dir / f"event_{frame_count - 1:08d}.jpg"
                    if not write_image_unicode(evidence_path, rendered):
                        raise RuntimeError(f"Could not write alert evidence: {evidence_path}")
    finally:
        capture.release()
        writer.release()

    elapsed = time.perf_counter() - started
    summary = {
        "source": source_label,
        "frames": frame_count,
        "source_fps": fps,
        "elapsed_seconds": round(elapsed, 4),
        "inference_fps": round(frame_count / elapsed, 4) if elapsed else None,
        "tracking_backend": pipeline.tracking_backend,
        "alert_count": event_count,
        "event_metrics": None,
        "event_metrics_note": "No ground-truth event annotations were supplied for this video.",
        "output_video": str(output_path),
        "events_jsonl": str(events_path),
        "evidence_directory": str(evidence_dir),
    }
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def settings_from_config(config: dict[str, Any]) -> tuple[ContactSettings, VideoPipelineConfig]:
    model = config.get("model", {})
    classes = config.get("classes", {})
    contact = config.get("contact", {})
    roi = config.get("painting_roi", {})
    contact_settings = ContactSettings(
        confidence_threshold=float(model.get("confidence_threshold", 0.5)),
        contact_overlap_threshold=float(contact.get("contact_overlap_threshold", 0.2)),
        near_distance_threshold=float(contact.get("near_distance_threshold", 20.0)),
        minimum_contact_duration=float(contact.get("minimum_contact_duration", 0.75)),
        required_positive_frames=int(contact.get("required_positive_frames", 4)),
        sliding_window_size=int(contact.get("sliding_window_size", 6)),
        alert_cooldown=float(contact.get("alert_cooldown", 5.0)),
        painting_class_id=int(classes.get("painting", 0)),
        hand_class_id=int(classes.get("hand", 2)),
        tool_class_id=int(classes.get("tool", 3)),
    )
    pipeline_config = VideoPipelineConfig(
        confidence_threshold=float(model.get("confidence_threshold", 0.5)),
        image_size=int(model.get("image_size", 640)),
        device=str(model.get("device", "cpu")),
        tracker=str(model.get("tracker", "bytetrack.yaml")),
        roi_points=tuple(tuple(float(value) for value in point) for point in roi.get("points", VideoPipelineConfig().roi_points)),
        roi_mode=str(roi.get("mode", "when_missing")),
        roi_enabled=bool(roi.get("enabled", True)),
        hand_aliases=tuple(str(item).lower() for item in classes.get("hand_aliases", VideoPipelineConfig().hand_aliases)),
        tool_aliases=tuple(str(item).lower() for item in classes.get("tool_aliases", VideoPipelineConfig().tool_aliases)),
    )
    return contact_settings, pipeline_config

