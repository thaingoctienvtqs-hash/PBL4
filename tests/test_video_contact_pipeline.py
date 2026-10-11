import json
from types import SimpleNamespace

import cv2
import numpy as np

from server.contact import ContactSettings, ContactState
from server.contact.video import VideoContactPipeline, VideoPipelineConfig, mask_from_array, polygon_mask, run_video


class FakeBoxes:
    def __init__(self, class_name="hand", track_id=7):
        self.xyxy = np.asarray([[145, 95, 175, 125]], dtype=np.float32)
        self.cls = np.asarray([0], dtype=np.float32)
        self.conf = np.asarray([0.9], dtype=np.float32)
        self.id = None if track_id is None else np.asarray([track_id], dtype=np.float32)


class FakeModel:
    names = {0: "hand"}

    def track(self, frame, **kwargs):
        return [SimpleNamespace(boxes=FakeBoxes(), masks=None)]


def _settings():
    return ContactSettings(
        confidence_threshold=0.5,
        contact_overlap_threshold=0.2,
        near_distance_threshold=10,
        minimum_contact_duration=0.03,
        required_positive_frames=2,
        sliding_window_size=4,
        alert_cooldown=1,
    )


def test_polygon_and_instance_masks_keep_frame_dimensions():
    roi = polygon_mask(((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)), 40, 30)
    assert (roi.width, roi.height) == (40, 30)
    assert 300 <= roi.area <= 340

    source = np.zeros((10, 10), dtype=np.uint8)
    source[2:8, 2:8] = 1
    resized = mask_from_array(source, 20, 20)
    assert resized is not None
    assert resized.width == 20
    assert resized.height == 20
    assert resized.area > 0


def test_video_pipeline_uses_roi_and_requires_persistent_tracked_contact():
    pipeline = VideoContactPipeline(
        FakeModel(),
        _settings(),
        VideoPipelineConfig(
            confidence_threshold=0.5,
            roi_points=((0.3, 0.2), (0.7, 0.2), (0.7, 0.8), (0.3, 0.8)),
        ),
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    first = pipeline.process(frame, monotonic_time=0.0)
    assert first.uses_roi_fallback
    assert first.analysis.state == ContactState.CONTACT_PENDING
    assert not first.analysis.events

    second = pipeline.process(frame, monotonic_time=0.05)
    assert len(second.analysis.events) == 1
    assert second.analysis.events[0].contact_type == "hand"


def test_pipeline_assigns_short_term_ids_when_tracker_returns_none():
    class NoTrackModel:
        names = {0: "hand"}

        def track(self, frame, **kwargs):
            return [SimpleNamespace(boxes=FakeBoxes(track_id=None), masks=None)]

    pipeline = VideoContactPipeline(NoTrackModel(), _settings(), VideoPipelineConfig())
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frames = [pipeline.process(frame, monotonic_time=value) for value in (0.0, 0.05)]
    hand_ids = [next(item.track_id for item in result.detections if item.class_id == 2) for result in frames]
    assert hand_ids[0] == hand_ids[1]
    assert len(frames[-1].analysis.events) == 1


def test_roi_is_not_used_when_model_detects_painting_and_roi_disabled_works():
    model = FakeModel()
    model.names = {0: "painting"}
    model.track = lambda frame, **kwargs: [
        SimpleNamespace(
            boxes=SimpleNamespace(
                xyxy=np.asarray([[100, 50, 220, 190]], dtype=np.float32),
                cls=np.asarray([0], dtype=np.float32),
                conf=np.asarray([0.95], dtype=np.float32),
                id=np.asarray([2], dtype=np.float32),
            ),
            masks=None,
        )
    ]
    pipeline = VideoContactPipeline(model, _settings(), VideoPipelineConfig(roi_mode="when_missing"))
    result = pipeline.process(np.zeros((240, 320, 3), dtype=np.uint8))
    assert not result.uses_roi_fallback
    assert len([item for item in result.detections if item.class_id == 0]) == 1


def test_offline_video_writes_rendered_video_event_log_and_summary(tmp_path):
    input_path = tmp_path / "synthetic_input.mp4"
    writer = cv2.VideoWriter(
        str(input_path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240)
    )
    assert writer.isOpened()
    for _ in range(6):
        writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    writer.release()

    output = tmp_path / "rendered.mp4"
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence"
    summary = run_video(
        VideoContactPipeline(FakeModel(), _settings(), VideoPipelineConfig()),
        str(input_path),
        output_path=output,
        events_path=events,
        evidence_dir=evidence,
        source_label="SYNTHETIC_TEST_VIDEO",
    )

    assert summary["frames"] == 6
    assert summary["alert_count"] == 1
    assert output.is_file() and output.stat().st_size > 0
    assert summary["event_metrics"] is None
    records = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    assert records[0]["sample_type"] == "UNLABELED_VIDEO_INFERENCE"
    assert len(records) == 6
    event_records = [record for record in records if record["events"]]
    assert event_records[0]["events"][0]["event"] == "painting_contact"
    assert len(list(evidence.glob("*.jpg"))) == 1

