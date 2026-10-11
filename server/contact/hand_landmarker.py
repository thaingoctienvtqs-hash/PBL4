from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import cv2
import numpy as np

from server.contact.logic import ContactSettings, Detection


class MediaPipeHandLandmarker:
    """Optional MediaPipe VIDEO-mode adapter; landmarks are points, never pixel masks."""

    TIP_INDICES = (4, 8, 12, 16, 20)

    def __init__(
        self,
        model_path: Path,
        *,
        contact_settings: ContactSettings,
        min_detection_confidence: float = 0.5,
        num_hands: int = 4,
    ) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"MediaPipe task model does not exist: {model_path}")
        if not 0.0 <= min_detection_confidence <= 1.0:
            raise ValueError("min_detection_confidence must be in [0, 1]")
        if num_hands < 1:
            raise ValueError("num_hands must be positive")
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError(
                "The optional hand landmark component needs MediaPipe. "
                "Install requirements-hands.txt before enabling it."
            ) from exc

        runtime_model_path = model_path.resolve()
        self._temporary_model_path: Path | None = None
        if os.name == "nt" and not str(runtime_model_path).isascii():
            model_digest = hashlib.sha256(runtime_model_path.read_bytes()).hexdigest()
            self._temporary_model_path = Path(tempfile.gettempdir()) / f"pbl4_hand_{os.getpid()}_{model_digest[:12]}.task"
            if not self._temporary_model_path.is_file() or hashlib.sha256(self._temporary_model_path.read_bytes()).hexdigest() != model_digest:
                shutil.copyfile(runtime_model_path, self._temporary_model_path)
            runtime_model_path = self._temporary_model_path

        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(runtime_model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence,
        )
        self._mp = mp
        original_cwd = Path.cwd()
        change_working_directory = os.name == "nt" and not str(original_cwd).isascii()
        try:
            if change_working_directory:
                os.chdir(tempfile.gettempdir())
            self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        except Exception:
            if self._temporary_model_path is not None:
                self._temporary_model_path.unlink(missing_ok=True)
            raise
        finally:
            if change_working_directory:
                os.chdir(original_cwd)
        self._settings = contact_settings
        self._confidence_gate = min_detection_confidence
        self._last_timestamp_ms = -1

    def detect(self, frame: np.ndarray, timestamp_ms: int) -> list[Detection]:
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("MediaPipe hand input must be a decoded BGR color frame")
        height, width = frame.shape[:2]
        self._last_timestamp_ms = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, self._last_timestamp_ms)

        detections = []
        for landmarks in result.hand_landmarks or []:
            points = tuple(
                (
                    float(np.clip(point.x * width, 0, width - 1)),
                    float(np.clip(point.y * height, 0, height - 1)),
                )
                for point in landmarks
            )
            if len(points) < max(self.TIP_INDICES) + 1:
                continue
            xs, ys = zip(*points)
            hand_width = max(2.0, max(xs) - min(xs))
            hand_height = max(2.0, max(ys) - min(ys))
            pad_x, pad_y = hand_width * 0.04, hand_height * 0.04
            box = (
                max(0.0, min(xs) - pad_x),
                max(0.0, min(ys) - pad_y),
                min(float(width), max(xs) + pad_x),
                min(float(height), max(ys) + pad_y),
            )
            fingertips = tuple(points[index] for index in self.TIP_INDICES)
            detections.append(
                Detection(
                    class_id=self._settings.hand_class_id,
                    # The Task result does not expose a hand-presence probability;
                    # use its configured acceptance threshold as an explicit gate.
                    confidence=self._confidence_gate,
                    box=box,
                    track_id=None,
                    contact_points=fingertips,
                )
            )
        return detections

    def close(self) -> None:
        self._landmarker.close()
        if self._temporary_model_path is not None:
            self._temporary_model_path.unlink(missing_ok=True)
